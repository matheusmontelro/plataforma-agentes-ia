import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")

from backend.services import ai_provider_knowledge_migration as migration


class _FakeQuery:
    def __init__(self, workforces):
        self.workforces = workforces

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.workforces


class _FakeDB:
    def __init__(self, workforces):
        self.workforces = workforces

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self.workforces)


def _workforce(*, scope=None, fingerprint=None):
    file_search = {
        "enabled": True,
        "vector_store_id": "vs-source",
        "files": [
            {
                "file_id": "file-source",
                "vector_store_file_id": "file-source",
                "filename": "base.pdf",
                "content_type": "application/pdf",
                "status": "completed",
            }
        ],
        "links": [],
    }
    if scope:
        file_search["provider_scope"] = scope
    if fingerprint:
        file_search["api_key_fingerprint"] = fingerprint
    return SimpleNamespace(
        id=25,
        company_id=32,
        name="Atendimento",
        version=3,
        settings={
            "agent_context": {
                "knowledge": {
                    "file_search": file_search,
                }
            }
        },
    )


class _FakeFiles:
    def __init__(self, *, source=False):
        self.source = source
        self.created = []
        self.deleted = []

    def content(self, file_id):
        assert self.source is True
        assert file_id == "file-source"
        return SimpleNamespace(content=b"pdf-content")

    def create(self, **kwargs):
        assert self.source is False
        self.created.append(kwargs)
        return SimpleNamespace(id="file-company")

    def delete(self, file_id):
        self.deleted.append(file_id)


class _FakeVectorFiles:
    def __init__(self, *, source=False, status="completed"):
        self.source = source
        self.status = status
        self.created = []

    def retrieve(self, file_id, *, vector_store_id):
        assert self.source is True
        assert file_id == "file-source"
        assert vector_store_id == "vs-source"
        return SimpleNamespace(
            id=file_id,
            attributes={
                "company_id": "32",
                "workforce_id": "25",
            },
        )

    def create_and_poll(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="file-company", status=self.status)


class _FakeVectorStores:
    def __init__(self, *, source=False, status="completed"):
        self.source = source
        self.files = _FakeVectorFiles(source=source, status=status)
        self.created = []
        self.deleted = []

    def retrieve(self, vector_store_id):
        assert self.source is True
        assert vector_store_id == "vs-source"
        return SimpleNamespace(
            id=vector_store_id,
            metadata={
                "company_id": "32",
                "workforce_id": "25",
            },
        )

    def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="vs-company")

    def delete(self, vector_store_id):
        self.deleted.append(vector_store_id)


class _FakeOpenAI:
    def __init__(self, *, source=False, vector_status="completed"):
        self.files = _FakeFiles(source=source)
        self.vector_stores = _FakeVectorStores(
            source=source,
            status=vector_status,
        )
        self.closed = False

    def close(self):
        self.closed = True


def test_legacy_knowledge_is_copied_to_company_project(monkeypatch):
    workforce = _workforce()
    target_client = _FakeOpenAI()
    source_client = _FakeOpenAI(source=True)
    clients = {
        "company-key": target_client,
        "legacy-key": source_client,
    }
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setattr(
        migration,
        "OpenAI",
        lambda *, api_key: clients[api_key],
    )
    modified = []
    monkeypatch.setattr(
        migration,
        "flag_modified",
        lambda value, field: modified.append((value, field)),
    )

    migrated = migration.migrate_company_workforce_knowledge(
        _FakeDB([workforce]),
        32,
        new_api_key="company-key",
    )

    file_search = workforce.settings["agent_context"]["knowledge"]["file_search"]
    assert migrated.migrated_count == 1
    assert migrated.created_vector_store_ids == ("vs-company",)
    assert migrated.created_file_ids == ("file-company",)
    assert file_search["vector_store_id"] == "vs-company"
    assert file_search["provider_scope"] == migration.COMPANY_BYOK_SCOPE
    assert file_search["api_key_fingerprint"] == migration.api_key_fingerprint(
        "company-key"
    )
    assert file_search["files"][0]["file_id"] == "file-company"
    assert target_client.files.created[0]["file"][1] == b"pdf-content"
    assert workforce.version == 4
    assert modified == [(workforce, "settings")]
    assert target_client.closed is True
    assert source_client.closed is True


def test_key_rotation_reads_from_previous_company_project(monkeypatch):
    old_key = "old-company-key"
    workforce = _workforce(
        scope=migration.COMPANY_BYOK_SCOPE,
        fingerprint=migration.api_key_fingerprint(old_key),
    )
    target_client = _FakeOpenAI()
    source_client = _FakeOpenAI(source=True)
    clients = {
        "new-company-key": target_client,
        old_key: source_client,
    }
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        migration,
        "OpenAI",
        lambda *, api_key: clients[api_key],
    )
    monkeypatch.setattr(migration, "flag_modified", lambda *_args: None)

    migrated = migration.migrate_company_workforce_knowledge(
        _FakeDB([workforce]),
        32,
        new_api_key="new-company-key",
        previous_company_api_key=old_key,
    )

    assert migrated.migrated_count == 1
    assert source_client.files.source is True


def test_legacy_knowledge_without_source_key_fails_without_db_mutation(
    monkeypatch,
):
    workforce = _workforce()
    original_settings = workforce.settings
    target_client = _FakeOpenAI()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        migration,
        "OpenAI",
        lambda *, api_key: target_client,
    )
    monkeypatch.setattr(migration, "flag_modified", lambda *_args: None)

    with pytest.raises(
        migration.AIProviderKnowledgeMigrationError,
        match="não está disponível",
    ):
        migration.migrate_company_workforce_knowledge(
            _FakeDB([workforce]),
            32,
            new_api_key="company-key",
        )

    assert workforce.settings is original_settings
    assert target_client.closed is True


def test_company_has_workforce_knowledge_detects_only_vector_stores():
    with_store = _workforce()
    without_store = _workforce()
    without_store.settings["agent_context"]["knowledge"]["file_search"].pop(
        "vector_store_id"
    )

    assert migration.company_has_workforce_knowledge(
        _FakeDB([without_store, with_store]),
        32,
    )
    assert not migration.company_has_workforce_knowledge(
        _FakeDB([without_store]),
        32,
    )


def test_failed_vector_indexing_rolls_back_remote_resources_and_metadata(
    monkeypatch,
):
    workforce = _workforce()
    original_settings = workforce.settings
    target_client = _FakeOpenAI(vector_status="failed")
    source_client = _FakeOpenAI(source=True)
    clients = {
        "company-key": target_client,
        "legacy-key": source_client,
    }
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setattr(
        migration,
        "OpenAI",
        lambda *, api_key: clients[api_key],
    )
    monkeypatch.setattr(migration, "flag_modified", lambda *_args: None)

    with pytest.raises(
        migration.AIProviderKnowledgeMigrationError,
        match="não concluiu",
    ):
        migration.migrate_company_workforce_knowledge(
            _FakeDB([workforce]),
            32,
            new_api_key="company-key",
        )

    assert workforce.settings is original_settings
    assert target_client.vector_stores.deleted == ["vs-company"]
    assert target_client.files.deleted == ["file-company"]


def test_source_vector_store_must_belong_to_company_and_workforce(
    monkeypatch,
):
    workforce = _workforce()
    target_client = _FakeOpenAI()
    source_client = _FakeOpenAI(source=True)
    source_client.vector_stores.retrieve = lambda _vector_store_id: SimpleNamespace(
        metadata={"company_id": "999", "workforce_id": "25"}
    )
    clients = {
        "company-key": target_client,
        "legacy-key": source_client,
    }
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setattr(
        migration,
        "OpenAI",
        lambda *, api_key: clients[api_key],
    )

    with pytest.raises(
        migration.AIProviderKnowledgeMigrationError,
        match="não pertence",
    ):
        migration.migrate_company_workforce_knowledge(
            _FakeDB([workforce]),
            32,
            new_api_key="company-key",
        )

    assert target_client.vector_stores.created == []
    assert target_client.files.created == []


def test_downloaded_file_id_must_match_validated_vector_file_id(
    monkeypatch,
):
    workforce = _workforce()
    file_search = workforce.settings["agent_context"]["knowledge"][
        "file_search"
    ]
    file_search["files"][0]["file_id"] = "file-other-tenant"
    file_search["files"][0]["vector_store_file_id"] = "file-source"
    target_client = _FakeOpenAI()
    source_client = _FakeOpenAI(source=True)
    clients = {
        "company-key": target_client,
        "legacy-key": source_client,
    }
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setattr(
        migration,
        "OpenAI",
        lambda *, api_key: clients[api_key],
    )

    with pytest.raises(
        migration.AIProviderKnowledgeMigrationError,
        match="não pôde ser validada",
    ):
        migration.migrate_company_workforce_knowledge(
            _FakeDB([workforce]),
            32,
            new_api_key="company-key",
        )

    assert source_client.files.created == []
    assert target_client.files.created == []
    assert target_client.vector_stores.deleted == ["vs-company"]
