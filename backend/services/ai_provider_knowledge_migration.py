"""Move workforce knowledge stores into the active company's OpenAI project."""

from __future__ import annotations

import copy
import hashlib
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.models import AgentWorkforce
from backend.services.ai_provider_service import AIProviderCredentialError


COMPANY_BYOK_SCOPE = "company_byok"
LEGACY_OPENAI_KEY_ENV = "OPENAI_API_KEY"


class AIProviderKnowledgeMigrationError(AIProviderCredentialError):
    """Safe error raised when legacy knowledge cannot be moved atomically."""


@dataclass(frozen=True)
class KnowledgeMigrationResult:
    migrated_count: int = 0
    created_vector_store_ids: tuple[str, ...] = ()
    created_file_ids: tuple[str, ...] = ()


def api_key_fingerprint(api_key: str) -> str:
    """Return a non-reversible marker used only to detect key rotations."""

    return hashlib.sha256((api_key or "").strip().encode("utf-8")).hexdigest()[:24]


def _file_search_settings(
    settings: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    agent_context = settings.get("agent_context")
    if not isinstance(agent_context, dict):
        return None
    knowledge = agent_context.get("knowledge")
    if not isinstance(knowledge, dict):
        return None
    file_search = knowledge.get("file_search")
    return file_search if isinstance(file_search, dict) else None


def _knowledge_items(file_search: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for collection_key in ("files", "links"):
        collection = file_search.get(collection_key)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if isinstance(item, dict):
                yield item


def company_has_workforce_knowledge(
    db: Session,
    company_id: int,
) -> bool:
    """Return whether removing the key would strand an existing vector store."""

    workforces = (
        db.query(AgentWorkforce)
        .filter(AgentWorkforce.company_id == int(company_id))
        .all()
    )
    for workforce in workforces:
        file_search = _file_search_settings(workforce.settings or {})
        if file_search and str(file_search.get("vector_store_id") or "").strip():
            return True
    return False


def _download_bytes(client: OpenAI, file_id: str) -> bytes:
    response = client.files.content(file_id)
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    read = getattr(response, "read", None)
    if callable(read):
        content = read()
        if isinstance(content, bytes):
            return content
    raise AIProviderKnowledgeMigrationError(
        "Não foi possível ler um arquivo da base de conhecimento anterior"
    )


def _metadata_dict(resource: Any) -> Dict[str, Any]:
    metadata = getattr(resource, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def _validate_source_vector_store(
    client: OpenAI,
    *,
    vector_store_id: str,
    company_id: int,
    workforce_id: int,
) -> None:
    try:
        vector_store = client.vector_stores.retrieve(vector_store_id)
    except Exception:
        raise AIProviderKnowledgeMigrationError(
            "Não foi possível validar a origem da base de conhecimento"
        ) from None

    metadata = _metadata_dict(vector_store)
    if (
        str(metadata.get("company_id") or "") != str(company_id)
        or str(metadata.get("workforce_id") or "") != str(workforce_id)
    ):
        raise AIProviderKnowledgeMigrationError(
            "A base de conhecimento anterior não pertence à empresa ativa"
        )


def _validate_source_vector_file(
    client: OpenAI,
    *,
    vector_store_id: str,
    vector_store_file_id: str,
    company_id: int,
    workforce_id: int,
) -> None:
    try:
        vector_file = client.vector_stores.files.retrieve(
            vector_store_file_id,
            vector_store_id=vector_store_id,
        )
    except Exception:
        raise AIProviderKnowledgeMigrationError(
            "Não foi possível validar um arquivo da base de conhecimento"
        ) from None

    attributes = getattr(vector_file, "attributes", None)
    attributes = attributes if isinstance(attributes, dict) else {}
    if (
        str(attributes.get("company_id") or "") != str(company_id)
        or str(attributes.get("workforce_id") or "") != str(workforce_id)
    ):
        raise AIProviderKnowledgeMigrationError(
            "Um arquivo da base de conhecimento não pertence à empresa ativa"
        )


def _close_clients(clients: Iterable[OpenAI]) -> None:
    seen: set[int] = set()
    for client in clients:
        if id(client) in seen:
            continue
        seen.add(id(client))
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _cleanup_created_resources(
    client: OpenAI,
    *,
    vector_store_ids: Iterable[str],
    file_ids: Iterable[str],
) -> None:
    for vector_store_id in reversed(tuple(vector_store_ids)):
        try:
            client.vector_stores.delete(vector_store_id)
        except Exception:
            pass
    for file_id in reversed(tuple(file_ids)):
        try:
            client.files.delete(file_id)
        except Exception:
            pass


def cleanup_company_workforce_knowledge_migration(
    api_key: str,
    result: Optional[KnowledgeMigrationResult],
) -> None:
    """Remove staged remote resources when the corresponding DB commit fails."""

    if result is None or (
        not result.created_vector_store_ids and not result.created_file_ids
    ):
        return

    client = OpenAI(api_key=api_key)
    try:
        _cleanup_created_resources(
            client,
            vector_store_ids=result.created_vector_store_ids,
            file_ids=result.created_file_ids,
        )
    finally:
        _close_clients([client])


def migrate_company_workforce_knowledge(
    db: Session,
    company_id: int,
    *,
    new_api_key: str,
    previous_company_api_key: Optional[str] = None,
) -> KnowledgeMigrationResult:
    """Stage all knowledge metadata changes without committing the DB session.

    Existing stores without a scope marker belong to the historical installation
    OpenAI project. Stores already marked ``company_byok`` belong to the
    previous company key and are copied only when the key changes.
    """

    target_fingerprint = api_key_fingerprint(new_api_key)
    workforces = (
        db.query(AgentWorkforce)
        .filter(AgentWorkforce.company_id == int(company_id))
        .all()
    )
    candidates: list[tuple[AgentWorkforce, Dict[str, Any], Dict[str, Any]]] = []
    for workforce in workforces:
        settings = copy.deepcopy(workforce.settings or {})
        file_search = _file_search_settings(settings)
        if not file_search or not str(file_search.get("vector_store_id") or "").strip():
            continue
        if (
            file_search.get("provider_scope") == COMPANY_BYOK_SCOPE
            and file_search.get("api_key_fingerprint") == target_fingerprint
        ):
            continue
        candidates.append((workforce, settings, file_search))

    if not candidates:
        return KnowledgeMigrationResult()

    legacy_api_key = (os.getenv(LEGACY_OPENAI_KEY_ENV) or "").strip()
    target_client = OpenAI(api_key=new_api_key)
    source_clients: Dict[str, OpenAI] = {}
    created_vector_store_ids: list[str] = []
    created_file_ids: list[str] = []
    staged: list[tuple[AgentWorkforce, Dict[str, Any]]] = []
    migration_completed = False

    try:
        for workforce, settings, file_search in candidates:
            source_scope = str(file_search.get("provider_scope") or "").strip()
            if source_scope == COMPANY_BYOK_SCOPE:
                source_api_key = (previous_company_api_key or "").strip()
                if not source_api_key:
                    raise AIProviderKnowledgeMigrationError(
                        "Cadastre novamente a chave OpenAI anterior para migrar a base de conhecimento"
                    )
            else:
                source_api_key = legacy_api_key
                if not source_api_key:
                    raise AIProviderKnowledgeMigrationError(
                        "A base de conhecimento anterior não está disponível para migração"
                    )

            source_client = source_clients.get(source_api_key)
            if source_client is None:
                source_client = OpenAI(api_key=source_api_key)
                source_clients[source_api_key] = source_client

            source_vector_store_id = str(
                file_search.get("vector_store_id") or ""
            ).strip()
            _validate_source_vector_store(
                source_client,
                vector_store_id=source_vector_store_id,
                company_id=int(company_id),
                workforce_id=int(workforce.id),
            )

            vector_store = target_client.vector_stores.create(
                name=(
                    f"agentive-workforce-{workforce.company_id}-"
                    f"{workforce.id}-{str(workforce.name or '')[:60]}"
                ),
                metadata={
                    "company_id": str(workforce.company_id),
                    "workforce_id": str(workforce.id),
                    "credential_scope": COMPANY_BYOK_SCOPE,
                },
            )
            created_vector_store_ids.append(str(vector_store.id))

            for item in _knowledge_items(file_search):
                source_file_id = str(
                    item.get("file_id")
                    or item.get("vector_store_file_id")
                    or ""
                ).strip()
                if not source_file_id:
                    raise AIProviderKnowledgeMigrationError(
                        "Uma referência da base de conhecimento está incompleta"
                    )

                source_vector_file_id = str(
                    item.get("vector_store_file_id") or source_file_id
                ).strip()
                if source_vector_file_id != source_file_id:
                    raise AIProviderKnowledgeMigrationError(
                        "Uma referência da base de conhecimento não pôde ser validada"
                    )
                _validate_source_vector_file(
                    source_client,
                    vector_store_id=source_vector_store_id,
                    vector_store_file_id=source_file_id,
                    company_id=int(company_id),
                    workforce_id=int(workforce.id),
                )
                content = _download_bytes(source_client, source_file_id)
                filename = str(
                    item.get("filename")
                    or item.get("title")
                    or f"knowledge-{source_file_id}.txt"
                ).strip()
                uploaded_file = target_client.files.create(
                    file=(
                        filename,
                        content,
                        str(item.get("content_type") or "application/octet-stream"),
                    ),
                    purpose="assistants",
                )
                created_file_ids.append(str(uploaded_file.id))
                vector_file = target_client.vector_stores.files.create_and_poll(
                    vector_store_id=str(vector_store.id),
                    file_id=str(uploaded_file.id),
                    attributes={
                        "company_id": str(company_id),
                        "workforce_id": str(workforce.id),
                        "source": "agentive_byok_migration",
                        "filename": filename,
                    },
                    poll_interval_ms=1000,
                )
                vector_file_status = str(
                    getattr(vector_file, "status", None) or ""
                ).strip().lower()
                if vector_file_status != "completed":
                    raise AIProviderKnowledgeMigrationError(
                        "A OpenAI não concluiu a indexação da base de conhecimento"
                    )
                item["file_id"] = str(uploaded_file.id)
                item["vector_store_file_id"] = str(vector_file.id)
                item["status"] = vector_file_status

            file_search["vector_store_id"] = str(vector_store.id)
            file_search["provider_scope"] = COMPANY_BYOK_SCOPE
            file_search["api_key_fingerprint"] = target_fingerprint
            staged.append((workforce, settings))

        for workforce, settings in staged:
            workforce.settings = settings
            flag_modified(workforce, "settings")
            workforce.version = (workforce.version or 1) + 1
        result = KnowledgeMigrationResult(
            migrated_count=len(staged),
            created_vector_store_ids=tuple(created_vector_store_ids),
            created_file_ids=tuple(created_file_ids),
        )
        migration_completed = True
        return result
    except AIProviderKnowledgeMigrationError:
        raise
    except Exception as exc:
        raise AIProviderKnowledgeMigrationError(
            "Não foi possível migrar a base de conhecimento para a chave OpenAI informada"
        ) from None
    finally:
        if not migration_completed:
            _cleanup_created_resources(
                target_client,
                vector_store_ids=created_vector_store_ids,
                file_ids=created_file_ids,
            )
        _close_clients([target_client, *source_clients.values()])
