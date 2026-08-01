import copy
from datetime import datetime
import io
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from openai import NotFoundError, OpenAI
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.auth import get_current_user
from backend.agents_sdk.agent_builder import AgentCreationConfig
from backend.db import get_db
from backend.models import AgentWorkforce, User
from backend.runtime_settings import app_user_agent
from backend.services import (
    ai_provider_knowledge_migration,
    ai_provider_service,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class AgentWorkforceBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "draft"
    channel: str = "whatsapp"
    root_agent_key: Optional[str] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    viewport: Dict[str, Any] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})
    agent_configs: Dict[str, Any] = Field(default_factory=dict)
    settings: Dict[str, Any] = Field(default_factory=dict)


class AgentWorkforceCreate(AgentWorkforceBase):
    pass


class AgentWorkforceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    channel: Optional[str] = None
    root_agent_key: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    viewport: Optional[Dict[str, Any]] = None
    agent_configs: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None


class AgentWorkforceResponse(AgentWorkforceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    version: int
    created_at: datetime
    updated_at: datetime


class KnowledgeLinkRequest(BaseModel):
    url: str = Field(..., min_length=8)
    title: Optional[str] = None


ALLOWED_WORKFORCE_STATUSES = {"draft", "active", "paused"}
SERVER_MANAGED_KNOWLEDGE_FIELDS = {
    "vector_store_id",
    "files",
    "links",
    "provider_scope",
    "api_key_fingerprint",
}


def _company_id_or_400(user: User) -> int:
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    return int(user.company_id)


def _node_agent_key(node: Dict[str, Any]) -> Optional[str]:
    data = node.get("data") if isinstance(node, dict) else None
    if not isinstance(data, dict) or data.get("kind") == "human":
        return None
    key = data.get("key")
    return str(key).strip() if key else None


def _validate_workforce_contract(data: Dict[str, Any]) -> None:
    status_value = str(data.get("status") or "draft")
    if status_value not in ALLOWED_WORKFORCE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid workforce status",
        )

    raw_nodes = data.get("nodes")
    raw_agent_configs = data.get("agent_configs")
    nodes = raw_nodes if raw_nodes is not None else []
    agent_configs = raw_agent_configs if raw_agent_configs is not None else {}
    root_agent_key = data.get("root_agent_key")

    if not isinstance(nodes, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="nodes must be a list",
        )
    if not isinstance(agent_configs, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="agent_configs must be an object",
        )

    agent_keys = [_node_agent_key(node) for node in nodes]
    agent_keys = [key for key in agent_keys if key]
    if not agent_keys:
        if status_value == "draft" and not root_agent_key and not agent_configs:
            return
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Agent workforce must include at least one AI agent",
        )

    if len(agent_keys) != len(set(agent_keys)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Agent keys must be unique",
        )

    if not root_agent_key or root_agent_key not in agent_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Agent workforce must define a valid root_agent_key",
        )

    missing_configs = [key for key in agent_keys if key not in agent_configs]
    if missing_configs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing agent_configs for: {', '.join(missing_configs)}",
        )

    for key in agent_keys:
        try:
            AgentCreationConfig.model_validate(agent_configs[key])
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid agent config for {key}: {exc}",
            ) from exc


def _file_search_from_settings(
    settings: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(settings, dict):
        return None
    agent_context = settings.get("agent_context")
    if not isinstance(agent_context, dict):
        return None
    knowledge = agent_context.get("knowledge")
    if not isinstance(knowledge, dict):
        return None
    file_search = knowledge.get("file_search")
    return file_search if isinstance(file_search, dict) else None


def _protect_server_managed_knowledge_settings(
    next_settings: Dict[str, Any],
    *,
    previous_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Prevent generic workforce writes from forging remote knowledge IDs."""

    protected = copy.deepcopy(next_settings or {})
    previous_file_search = _file_search_from_settings(previous_settings)
    next_file_search = _file_search_from_settings(protected)
    if next_file_search is None:
        if previous_file_search is None or not any(
            field in previous_file_search
            for field in SERVER_MANAGED_KNOWLEDGE_FIELDS
        ):
            return protected
        agent_context = protected.get("agent_context")
        agent_context = (
            copy.deepcopy(agent_context)
            if isinstance(agent_context, dict)
            else {}
        )
        knowledge = agent_context.get("knowledge")
        knowledge = (
            copy.deepcopy(knowledge)
            if isinstance(knowledge, dict)
            else {}
        )
        next_file_search = {}
        knowledge["file_search"] = next_file_search
        agent_context["knowledge"] = knowledge
        protected["agent_context"] = agent_context

    for field in SERVER_MANAGED_KNOWLEDGE_FIELDS:
        if previous_file_search is not None and field in previous_file_search:
            next_file_search[field] = copy.deepcopy(previous_file_search[field])
        else:
            next_file_search.pop(field, None)
    return protected


def _agent_models(data: Dict[str, Any]) -> Dict[str, str]:
    agent_configs = data.get("agent_configs")
    if not isinstance(agent_configs, dict):
        return {}

    models: Dict[str, str] = {}
    for agent_key, raw_config in agent_configs.items():
        if not isinstance(raw_config, dict):
            continue
        model_config = raw_config.get("model")
        if not isinstance(model_config, dict):
            continue
        model_id = str(model_config.get("model") or "").strip()
        if model_id:
            models[str(agent_key)] = model_id
    return models


def _audio_enabled_agent_keys(data: Dict[str, Any]) -> set[str]:
    agent_configs = data.get("agent_configs")
    if not isinstance(agent_configs, dict):
        return set()

    enabled: set[str] = set()
    for agent_key, raw_config in agent_configs.items():
        if not isinstance(raw_config, dict):
            continue
        channel = raw_config.get("channel")
        if isinstance(channel, dict) and channel.get("allow_audio") is True:
            enabled.add(str(agent_key))
    return enabled


def _elevenlabs_audio_enabled_agent_keys(data: Dict[str, Any]) -> set[str]:
    agent_configs = data.get("agent_configs")
    if not isinstance(agent_configs, dict):
        return set()

    enabled: set[str] = set()
    for agent_key, raw_config in agent_configs.items():
        if not isinstance(raw_config, dict):
            continue
        channel = raw_config.get("channel")
        if not isinstance(channel, dict) or channel.get("allow_audio") is not True:
            continue
        voice = channel.get("voice")
        provider = (
            str(voice.get("provider") or "").strip().lower()
            if isinstance(voice, dict)
            else ""
        )
        if provider == "elevenlabs":
            enabled.add(str(agent_key))
    return enabled


def _validate_company_models(
    db: Session,
    company_id: int,
    data: Dict[str, Any],
) -> None:
    configured_models = _agent_models(data)
    if not configured_models:
        return

    credential = ai_provider_service.get_company_ai_provider_credential(
        db,
        company_id,
    )
    if credential is None or credential.status != "valid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configure e valide a chave OpenAI da empresa antes de salvar agentes",
        )

    available_models = {
        str(model_id).strip()
        for model_id in (credential.available_models or [])
        if str(model_id).strip()
    }
    unavailable = [
        f"{agent_key}: {model_id}"
        for agent_key, model_id in configured_models.items()
        if model_id not in available_models
    ]
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Modelo indisponível para a chave OpenAI da empresa: "
                + ", ".join(unavailable)
            ),
        )


def _reject_new_audio_activations(
    next_state: Dict[str, Any],
    *,
    previous_state: Optional[Dict[str, Any]] = None,
) -> None:
    previous_elevenlabs = (
        _elevenlabs_audio_enabled_agent_keys(previous_state)
        if (
            previous_state is not None
            and str(previous_state.get("status") or "").strip().lower()
            == "active"
        )
        else set()
    )
    next_enabled = (
        _audio_enabled_agent_keys(next_state)
        if str(next_state.get("status") or "").strip().lower() == "active"
        else set()
    )
    next_elevenlabs = _elevenlabs_audio_enabled_agent_keys(next_state)
    newly_enabled = next_enabled - previous_elevenlabs
    unsupported_provider = next_enabled - next_elevenlabs
    if newly_enabled or unsupported_provider:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Novas ativações de voz estão indisponíveis. "
                "Somente agentes que já estavam ativos com ElevenLabs podem permanecer assim."
            ),
        )


def _workforce_state(workforce: AgentWorkforce) -> Dict[str, Any]:
    return {
        "name": workforce.name,
        "description": workforce.description,
        "status": workforce.status,
        "channel": workforce.channel,
        "root_agent_key": workforce.root_agent_key,
        "nodes": workforce.nodes,
        "edges": workforce.edges,
        "viewport": workforce.viewport,
        "agent_configs": workforce.agent_configs,
        "settings": workforce.settings,
    }


def _get_workforce_or_404(
    db: Session,
    company_id: int,
    workforce_id: int,
) -> AgentWorkforce:
    workforce = (
        db.query(AgentWorkforce)
        .filter(
            AgentWorkforce.id == workforce_id,
            AgentWorkforce.company_id == company_id,
        )
        .first()
    )
    if not workforce:
        raise HTTPException(status_code=404, detail="Agent workforce not found")
    return workforce


def _ensure_openai_client(db: Session, company_id: int) -> OpenAI:
    try:
        api_key = ai_provider_service.get_company_openai_api_key(
            db,
            company_id,
        )
    except ai_provider_service.AIProviderCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return OpenAI(api_key=api_key)


def _mark_company_knowledge_scope(
    db: Session,
    company_id: int,
    file_search: Dict[str, Any],
) -> None:
    api_key = ai_provider_service.get_company_openai_api_key(
        db,
        company_id,
    )
    file_search["provider_scope"] = (
        ai_provider_knowledge_migration.COMPANY_BYOK_SCOPE
    )
    file_search["api_key_fingerprint"] = (
        ai_provider_knowledge_migration.api_key_fingerprint(api_key)
    )


def _ensure_file_search_settings(workforce: AgentWorkforce) -> tuple[Dict[str, Any], Dict[str, Any]]:
    settings = dict(workforce.settings or {})
    agent_context = dict(settings.get("agent_context") or {})
    knowledge = dict(agent_context.get("knowledge") or {})
    file_search = dict(knowledge.get("file_search") or {})
    file_search.setdefault("enabled", True)
    file_search.setdefault("max_num_results", 4)
    file_search.setdefault("files", [])
    file_search.setdefault("links", [])
    knowledge["file_search"] = file_search
    agent_context["knowledge"] = knowledge
    settings["agent_context"] = agent_context
    return settings, file_search


def _ensure_vector_store(
    client: OpenAI,
    workforce: AgentWorkforce,
    file_search: Dict[str, Any],
) -> str:
    vector_store_id = str(file_search.get("vector_store_id") or "").strip()
    if vector_store_id:
        return vector_store_id

    vector_store = client.vector_stores.create(
        name=f"agentive-workforce-{workforce.company_id}-{workforce.id}-{workforce.name[:60]}",
        metadata={
            "company_id": str(workforce.company_id),
            "workforce_id": str(workforce.id),
        },
    )
    file_search["vector_store_id"] = vector_store.id
    return vector_store.id


def _require_completed_vector_file(vector_file: Any) -> str:
    vector_file_status = str(
        getattr(vector_file, "status", None) or ""
    ).strip().lower()
    if vector_file_status != "completed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="A OpenAI não concluiu a indexação da base de conhecimento",
        )
    return vector_file_status


def _cleanup_failed_knowledge_write(
    client: OpenAI,
    *,
    file_id: Optional[str],
    created_vector_store_id: Optional[str],
    vector_store_id: Optional[str] = None,
    vector_store_file_id: Optional[str] = None,
) -> None:
    if created_vector_store_id:
        try:
            client.vector_stores.delete(created_vector_store_id)
        except Exception:
            logger.warning(
                "Could not remove orphan vector store after knowledge failure"
            )
    elif vector_store_id and vector_store_file_id:
        try:
            client.vector_stores.files.delete(
                vector_store_file_id,
                vector_store_id=vector_store_id,
            )
        except Exception:
            logger.warning(
                "Could not detach orphan vector store file after knowledge failure"
            )
    if file_id:
        try:
            client.files.delete(file_id)
        except Exception:
            logger.warning(
                "Could not remove orphan OpenAI file after knowledge failure"
            )


def _delete_workforce_remote_knowledge(
    client: OpenAI,
    *,
    workforce: AgentWorkforce,
) -> None:
    file_search = _file_search_from_settings(workforce.settings or {})
    if not file_search:
        return

    vector_store_id = str(
        file_search.get("vector_store_id") or ""
    ).strip()
    items = [
        item
        for item in [
            *(file_search.get("files") or []),
            *(file_search.get("links") or []),
        ]
        if isinstance(item, dict)
    ]
    if not vector_store_id and not items:
        return
    if not vector_store_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A base de conhecimento precisa ser revisada antes de excluir a equipe",
        )

    try:
        vector_store = client.vector_stores.retrieve(vector_store_id)
    except NotFoundError:
        vector_store = None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível validar a base de conhecimento na OpenAI",
        ) from None

    if vector_store is not None:
        metadata = getattr(vector_store, "metadata", None)
        metadata = metadata if isinstance(metadata, dict) else {}
        if (
            str(metadata.get("company_id") or "")
            != str(workforce.company_id)
            or str(metadata.get("workforce_id") or "")
            != str(workforce.id)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A base de conhecimento não pertence à equipe ativa",
            )

    seen_file_ids: set[str] = set()
    for item in items:
        openai_file_id = str(item.get("file_id") or "").strip()
        vector_file_id = str(
            item.get("vector_store_file_id") or openai_file_id
        ).strip()
        if vector_store is not None and vector_file_id:
            try:
                client.vector_stores.files.delete(
                    vector_file_id,
                    vector_store_id=vector_store_id,
                )
            except NotFoundError:
                pass
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Não foi possível remover um arquivo da base na OpenAI",
                ) from None
        if openai_file_id and openai_file_id not in seen_file_ids:
            try:
                client.files.delete(openai_file_id)
            except NotFoundError:
                pass
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Não foi possível remover um arquivo da OpenAI",
                ) from None
            seen_file_ids.add(openai_file_id)

    if vector_store is not None:
        try:
            client.vector_stores.delete(vector_store_id)
        except NotFoundError:
            pass
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Não foi possível remover a base de conhecimento na OpenAI",
            ) from None


def _append_unique_item(items: List[Dict[str, Any]], item: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    item_value = item.get(key)
    filtered = [
        existing
        for existing in items
        if not isinstance(existing, dict) or existing.get(key) != item_value
    ]
    return [item, *filtered][:50]


def _persist_workforce_settings(
    db: Session,
    workforce: AgentWorkforce,
    settings: Dict[str, Any],
) -> AgentWorkforce:
    workforce.settings = settings
    flag_modified(workforce, "settings")
    workforce.version = (workforce.version or 1) + 1
    db.commit()
    try:
        db.refresh(workforce)
    except Exception:
        logger.warning(
            "Workforce settings were committed but could not be refreshed"
        )
    return workforce


def _refresh_file_search_statuses(client: OpenAI, file_search: Dict[str, Any]) -> bool:
    vector_store_id = str(file_search.get("vector_store_id") or "").strip()
    if not vector_store_id:
        return False

    changed = False
    for collection_key in ("files", "links"):
        items = file_search.get(collection_key)
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            file_id = str(item.get("file_id") or item.get("vector_store_file_id") or "").strip()
            if not file_id:
                continue

            try:
                vector_file = client.vector_stores.files.retrieve(
                    file_id,
                    vector_store_id=vector_store_id,
                )
                next_status = getattr(vector_file, "status", None)
                usage_bytes = getattr(vector_file, "usage_bytes", None)
                last_error = getattr(vector_file, "last_error", None)
            except NotFoundError:
                next_status = "missing"
                usage_bytes = None
                last_error = None
            except Exception as exc:
                logger.warning(
                    "Failed to refresh vector store file status for workforce knowledge file %s: %s",
                    file_id,
                    exc,
                )
                continue

            if next_status and item.get("status") != next_status:
                item["status"] = next_status
                changed = True
            if usage_bytes is not None and item.get("usage_bytes") != usage_bytes:
                item["usage_bytes"] = usage_bytes
                changed = True
            if last_error is not None:
                error_value = str(last_error)
                if item.get("last_error") != error_value:
                    item["last_error"] = error_value
                    changed = True
            elif item.get("last_error"):
                item.pop("last_error", None)
                changed = True

    return changed


def _refresh_workforce_knowledge_statuses(
    db: Session,
    workforce: AgentWorkforce,
    client: Optional[OpenAI] = None,
) -> AgentWorkforce:
    settings, file_search = _ensure_file_search_settings(workforce)
    has_items = bool(file_search.get("files") or file_search.get("links"))
    if not has_items or not file_search.get("vector_store_id"):
        return workforce

    openai_client = client or _ensure_openai_client(
        db,
        int(workforce.company_id),
    )
    if _refresh_file_search_statuses(openai_client, file_search):
        workforce.settings = settings
        flag_modified(workforce, "settings")
        db.commit()
        db.refresh(workforce)
    return workforce


def _remove_knowledge_item(
    items: Any,
    file_id: str,
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not isinstance(items, list):
        return [], None

    kept: List[Dict[str, Any]] = []
    removed: Optional[Dict[str, Any]] = None
    for item in items:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        item_file_id = str(item.get("file_id") or "").strip()
        item_vector_file_id = str(item.get("vector_store_file_id") or "").strip()
        if item_file_id == file_id or item_vector_file_id == file_id:
            removed = item
            continue
        kept.append(item)
    return kept, removed


def _safe_link_filename(url: str) -> str:
    parsed = urlparse(url)
    raw = parsed.netloc + parsed.path
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw).strip("_") or "link"
    return f"{slug[:90]}.txt"


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="URL must be http or https")
    host = parsed.hostname or ""
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    if host.lower() in blocked_hosts or host.lower().endswith(".local"):
        raise HTTPException(status_code=422, detail="URL host is not allowed")
    return parsed.geturl()


def _html_to_text(content: str) -> str:
    content = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", content)
    content = re.sub(r"(?s)<[^>]+>", " ", content)
    content = re.sub(r"\s+", " ", content)
    return content.strip()


@router.get("/agent-workforces", response_model=List[AgentWorkforceResponse])
def list_agent_workforces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    return (
        db.query(AgentWorkforce)
        .filter(AgentWorkforce.company_id == company_id)
        .order_by(AgentWorkforce.updated_at.desc())
        .all()
    )


@router.post(
    "/agent-workforces",
    response_model=AgentWorkforceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_workforce(
    payload: AgentWorkforceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    next_state = payload.model_dump()
    next_state["settings"] = _protect_server_managed_knowledge_settings(
        next_state.get("settings") or {},
    )
    _validate_workforce_contract(next_state)
    _validate_company_models(db, company_id, next_state)
    _reject_new_audio_activations(next_state)

    workforce = AgentWorkforce(
        company_id=company_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        channel=payload.channel,
        root_agent_key=payload.root_agent_key,
        nodes=payload.nodes,
        edges=payload.edges,
        viewport=payload.viewport,
        agent_configs=payload.agent_configs,
        settings=next_state["settings"],
    )
    db.add(workforce)
    db.commit()
    db.refresh(workforce)
    return workforce


@router.get("/agent-workforces/{workforce_id}", response_model=AgentWorkforceResponse)
def get_agent_workforce(
    workforce_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    workforce = (
        db.query(AgentWorkforce)
        .filter(
            AgentWorkforce.id == workforce_id,
            AgentWorkforce.company_id == company_id,
        )
        .first()
    )
    if not workforce:
        raise HTTPException(status_code=404, detail="Agent workforce not found")
    return workforce


@router.put("/agent-workforces/{workforce_id}", response_model=AgentWorkforceResponse)
def update_agent_workforce(
    workforce_id: int,
    payload: AgentWorkforceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    workforce = (
        db.query(AgentWorkforce)
        .filter(
            AgentWorkforce.id == workforce_id,
            AgentWorkforce.company_id == company_id,
        )
        .first()
    )
    if not workforce:
        raise HTTPException(status_code=404, detail="Agent workforce not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "settings" in update_data:
        update_data["settings"] = (
            _protect_server_managed_knowledge_settings(
                update_data.get("settings") or {},
                previous_settings=workforce.settings or {},
            )
        )
    previous_state = _workforce_state(workforce)
    next_state = {**previous_state, **update_data}
    _validate_workforce_contract(next_state)
    _validate_company_models(db, company_id, next_state)
    _reject_new_audio_activations(
        next_state,
        previous_state=previous_state,
    )
    for key, value in update_data.items():
        setattr(workforce, key, value)
    workforce.version = (workforce.version or 1) + 1

    db.commit()
    db.refresh(workforce)
    return workforce


@router.post(
    "/agent-workforces/{workforce_id}/knowledge/files",
    response_model=AgentWorkforceResponse,
)
async def upload_workforce_knowledge_file(
    workforce_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    workforce = _get_workforce_or_404(db, company_id, workforce_id)
    client = _ensure_openai_client(db, company_id)
    settings, file_search = _ensure_file_search_settings(workforce)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    previous_vector_store_id = str(
        file_search.get("vector_store_id") or ""
    ).strip()
    uploaded_file_id: Optional[str] = None
    created_vector_store_id: Optional[str] = None
    vector_store_id: Optional[str] = None
    vector_store_file_id: Optional[str] = None
    try:
        _mark_company_knowledge_scope(db, company_id, file_search)
        vector_store_id = _ensure_vector_store(
            client,
            workforce,
            file_search,
        )
        if not previous_vector_store_id:
            created_vector_store_id = vector_store_id

        uploaded_file = client.files.create(
            file=(
                file.filename or "knowledge.txt",
                content,
                file.content_type or "application/octet-stream",
            ),
            purpose="assistants",
        )
        uploaded_file_id = str(uploaded_file.id)
        vector_file = client.vector_stores.files.create_and_poll(
            vector_store_id=vector_store_id,
            file_id=uploaded_file_id,
            attributes={
                "company_id": str(company_id),
                "workforce_id": str(workforce.id),
                "source": "agentive_upload",
                "filename": file.filename or "knowledge.txt",
            },
            poll_interval_ms=1000,
        )
        vector_store_file_id = str(vector_file.id)
        vector_file_status = _require_completed_vector_file(vector_file)

        files = (
            file_search.get("files")
            if isinstance(file_search.get("files"), list)
            else []
        )
        file_search["files"] = _append_unique_item(
            files,
            {
                "file_id": uploaded_file_id,
                "vector_store_file_id": vector_store_file_id,
                "filename": file.filename or "knowledge.txt",
                "content_type": file.content_type,
                "status": vector_file_status,
                "created_at": datetime.utcnow().isoformat(),
            },
            "file_id",
        )
        file_search["enabled"] = True
        file_search["vector_store_id"] = vector_store_id
        return _persist_workforce_settings(db, workforce, settings)
    except Exception:
        db.rollback()
        _cleanup_failed_knowledge_write(
            client,
            file_id=uploaded_file_id,
            created_vector_store_id=created_vector_store_id,
            vector_store_id=vector_store_id,
            vector_store_file_id=vector_store_file_id,
        )
        raise


@router.post(
    "/agent-workforces/{workforce_id}/knowledge/refresh",
    response_model=AgentWorkforceResponse,
)
def refresh_workforce_knowledge(
    workforce_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    workforce = _get_workforce_or_404(db, company_id, workforce_id)
    return _refresh_workforce_knowledge_statuses(db, workforce)


@router.delete(
    "/agent-workforces/{workforce_id}/knowledge/files/{file_id}",
    response_model=AgentWorkforceResponse,
)
def delete_workforce_knowledge_file(
    workforce_id: int,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    workforce = _get_workforce_or_404(db, company_id, workforce_id)
    client = _ensure_openai_client(db, company_id)
    settings, file_search = _ensure_file_search_settings(workforce)

    next_files, removed_file = _remove_knowledge_item(file_search.get("files"), file_id)
    next_links, removed_link = _remove_knowledge_item(file_search.get("links"), file_id)
    removed = removed_file or removed_link
    if not removed:
        raise HTTPException(status_code=404, detail="Knowledge file not found")

    vector_store_id = str(file_search.get("vector_store_id") or "").strip()
    openai_file_id = str(removed.get("file_id") or "").strip()
    vector_file_id = str(removed.get("vector_store_file_id") or openai_file_id).strip()

    if vector_store_id and vector_file_id:
        try:
            client.vector_stores.files.delete(
                vector_file_id,
                vector_store_id=vector_store_id,
            )
        except NotFoundError:
            logger.info("Vector store file already missing during delete: %s", vector_file_id)

    if openai_file_id:
        try:
            client.files.delete(openai_file_id)
        except NotFoundError:
            logger.info("OpenAI file already missing during delete: %s", openai_file_id)

    file_search["files"] = next_files
    file_search["links"] = next_links
    if not next_files and not next_links:
        file_search["enabled"] = False
        if vector_store_id:
            try:
                client.vector_stores.delete(vector_store_id)
            except NotFoundError:
                pass
            file_search.pop("vector_store_id", None)
            file_search.pop("provider_scope", None)
            file_search.pop("api_key_fingerprint", None)

    return _persist_workforce_settings(db, workforce, settings)


@router.post(
    "/agent-workforces/{workforce_id}/knowledge/links",
    response_model=AgentWorkforceResponse,
)
def ingest_workforce_knowledge_link(
    workforce_id: int,
    payload: KnowledgeLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    workforce = _get_workforce_or_404(db, company_id, workforce_id)
    client = _ensure_openai_client(db, company_id)
    settings, file_search = _ensure_file_search_settings(workforce)
    url = _validate_public_url(payload.url)

    try:
        response = requests.get(
            url,
            headers={"User-Agent": app_user_agent("knowledge-ingest")},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=422, detail=f"Could not fetch URL: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    raw_text = response.text
    text = _html_to_text(raw_text) if "html" in content_type.lower() else raw_text.strip()
    text = text[:300_000]
    if len(text) < 40:
        raise HTTPException(status_code=422, detail="URL did not return enough text content")

    title = (payload.title or "").strip() or url
    document_text = f"Title: {title}\nURL: {url}\n\n{text}"
    buffer = io.BytesIO(document_text.encode("utf-8"))
    filename = _safe_link_filename(url)
    previous_vector_store_id = str(
        file_search.get("vector_store_id") or ""
    ).strip()
    uploaded_file_id: Optional[str] = None
    created_vector_store_id: Optional[str] = None
    vector_store_id: Optional[str] = None
    vector_store_file_id: Optional[str] = None
    try:
        _mark_company_knowledge_scope(db, company_id, file_search)
        vector_store_id = _ensure_vector_store(
            client,
            workforce,
            file_search,
        )
        if not previous_vector_store_id:
            created_vector_store_id = vector_store_id

        uploaded_file = client.files.create(
            file=(filename, buffer, "text/plain"),
            purpose="assistants",
        )
        uploaded_file_id = str(uploaded_file.id)
        vector_file = client.vector_stores.files.create_and_poll(
            vector_store_id=vector_store_id,
            file_id=uploaded_file_id,
            attributes={
                "company_id": str(company_id),
                "workforce_id": str(workforce.id),
                "source": "agentive_link",
                "url": url,
                "title": title,
            },
            poll_interval_ms=1000,
        )
        vector_store_file_id = str(vector_file.id)
        vector_file_status = _require_completed_vector_file(vector_file)

        links = (
            file_search.get("links")
            if isinstance(file_search.get("links"), list)
            else []
        )
        file_search["links"] = _append_unique_item(
            links,
            {
                "url": url,
                "title": title,
                "file_id": uploaded_file_id,
                "vector_store_file_id": vector_store_file_id,
                "status": vector_file_status,
                "created_at": datetime.utcnow().isoformat(),
            },
            "url",
        )
        file_search["enabled"] = True
        file_search["vector_store_id"] = vector_store_id
        return _persist_workforce_settings(db, workforce, settings)
    except Exception:
        db.rollback()
        _cleanup_failed_knowledge_write(
            client,
            file_id=uploaded_file_id,
            created_vector_store_id=created_vector_store_id,
            vector_store_id=vector_store_id,
            vector_store_file_id=vector_store_file_id,
        )
        raise


@router.delete("/agent-workforces/{workforce_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_workforce(
    workforce_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company_id = _company_id_or_400(current_user)
    workforce = (
        db.query(AgentWorkforce)
        .filter(
            AgentWorkforce.id == workforce_id,
            AgentWorkforce.company_id == company_id,
        )
        .first()
    )
    if not workforce:
        raise HTTPException(status_code=404, detail="Agent workforce not found")

    file_search = _file_search_from_settings(workforce.settings or {})
    if file_search and (
        file_search.get("vector_store_id")
        or file_search.get("files")
        or file_search.get("links")
    ):
        client = _ensure_openai_client(db, company_id)
        _delete_workforce_remote_knowledge(
            client,
            workforce=workforce,
        )

    db.delete(workforce)
    db.commit()
    return None
