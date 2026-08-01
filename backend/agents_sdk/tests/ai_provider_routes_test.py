import os
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-with-at-least-32-characters",
)

from backend.models import AIProviderCredential, Client, User
from backend.routes import ai_provider_routes as routes
from backend.services import (
    ai_provider_knowledge_migration,
    ai_provider_service,
)


class _FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []
        self.deleted = []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, value):
        self.refreshed.append(value)

    def delete(self, value):
        self.deleted.append(value)


def _client(company_id=7):
    return Client(
        id=1,
        email="owner@example.com",
        company_id=company_id,
        ownership_company_id=company_id,
    )


def _user(role, company_id=7):
    return User(
        id=2,
        client_id=1,
        email=f"{role}@example.com",
        password="hash",
        name=role,
        role=role,
        company_id=company_id,
    )


def _credential(company_id=7):
    return AIProviderCredential(
        id=3,
        company_id=company_id,
        provider="openai",
        api_key_encrypted="encrypted-secret-never-return",
        status="valid",
        available_models=["gpt-5.6-sol", "gpt-4o-mini"],
        last_validated_at=datetime.now(timezone.utc),
    )


def test_management_permission_allows_owner_admin_and_manager():
    assert routes.require_ai_provider_management_access(_client()).company_id == 7
    assert routes.require_ai_provider_management_access(_user("admin")).role == "admin"
    assert routes.require_ai_provider_management_access(_user("manager")).role == "manager"


def test_management_permission_rejects_staff():
    with pytest.raises(HTTPException) as exc_info:
        routes.require_ai_provider_management_access(_user("staff"))

    assert exc_info.value.status_code == 403


def test_get_response_never_contains_encrypted_or_plaintext_secret(monkeypatch):
    credential = _credential(company_id=44)
    monkeypatch.setattr(
        ai_provider_service,
        "get_company_ai_provider_credential",
        lambda db, company_id: credential
        if db == "db" and company_id == 44
        else None,
    )

    response = routes.get_ai_provider(db="db", current_user=_client(44))
    payload = response.model_dump()

    assert payload == {
        "configured": True,
        "status": "valid",
        "last_validated_at": credential.last_validated_at,
        "last_error": None,
        "models": ["gpt-5.6-sol", "gpt-4o-mini"],
    }
    assert "api_key" not in payload
    assert "encrypted-secret-never-return" not in str(payload)


def test_get_catalog_is_read_only_for_staff_with_company(monkeypatch):
    credential = _credential(company_id=44)
    monkeypatch.setattr(
        ai_provider_service,
        "get_company_ai_provider_credential",
        lambda _db, company_id: credential if company_id == 44 else None,
    )

    response = routes.get_ai_provider(
        db="db",
        current_user=_user("staff", company_id=44),
    )

    assert response.configured is True
    assert response.models == ["gpt-5.6-sol", "gpt-4o-mini"]


def test_put_uses_active_user_company_and_secret_value(monkeypatch):
    db = _FakeDB()
    captured = {}
    credential = _credential(company_id=31)

    def fake_configure(fake_db, company_id, api_key):
        captured.update(
            db=fake_db,
            company_id=company_id,
            api_key=api_key,
        )
        return credential

    monkeypatch.setattr(
        ai_provider_service,
        "configure_company_openai_api_key",
        fake_configure,
    )
    monkeypatch.setattr(
        ai_provider_service,
        "get_company_ai_provider_credential",
        lambda _db, _company_id: None,
    )
    monkeypatch.setattr(
        ai_provider_knowledge_migration,
        "migrate_company_workforce_knowledge",
        lambda fake_db, company_id, **kwargs: captured.update(
            migration_db=fake_db,
            migration_company_id=company_id,
            migration_key=kwargs["new_api_key"],
        ),
    )
    monkeypatch.setattr(
        ai_provider_service,
        "ensure_company_workforce_models_are_supported",
        lambda fake_db, company_id, models: captured.update(
            compatibility_db=fake_db,
            compatibility_company_id=company_id,
            compatibility_models=list(models),
        ),
    )

    response = routes.put_ai_provider(
        routes.AIProviderUpsertRequest(api_key="provider-key-company-31-marker"),
        db=db,
        current_user=_client(31),
    )

    assert captured == {
        "db": db,
        "company_id": 31,
        "api_key": "provider-key-company-31-marker",
        "migration_db": db,
        "migration_company_id": 31,
        "migration_key": "provider-key-company-31-marker",
        "compatibility_db": db,
        "compatibility_company_id": 31,
        "compatibility_models": ["gpt-5.6-sol", "gpt-4o-mini"],
    }
    assert db.commits == 1
    assert response.configured is True
    assert "secret" not in str(response.model_dump())


def test_put_cleans_remote_migration_when_database_commit_fails(monkeypatch):
    class _CommitFailDB(_FakeDB):
        def commit(self):
            self.commits += 1
            raise RuntimeError("database commit failed")

    db = _CommitFailDB()
    credential = _credential(company_id=31)
    migration_result = (
        ai_provider_knowledge_migration.KnowledgeMigrationResult(
            migrated_count=1,
            created_vector_store_ids=("vs-staged",),
            created_file_ids=("file-staged",),
        )
    )
    cleanup_calls = []

    monkeypatch.setattr(
        ai_provider_service,
        "get_company_ai_provider_credential",
        lambda _db, _company_id: None,
    )
    monkeypatch.setattr(
        ai_provider_service,
        "configure_company_openai_api_key",
        lambda _db, _company_id, _api_key: credential,
    )
    monkeypatch.setattr(
        ai_provider_service,
        "ensure_company_workforce_models_are_supported",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        ai_provider_knowledge_migration,
        "migrate_company_workforce_knowledge",
        lambda *_args, **_kwargs: migration_result,
    )
    monkeypatch.setattr(
        ai_provider_knowledge_migration,
        "cleanup_company_workforce_knowledge_migration",
        lambda api_key, result: cleanup_calls.append((api_key, result)),
    )

    with pytest.raises(RuntimeError, match="database commit failed"):
        routes.put_ai_provider(
            routes.AIProviderUpsertRequest(
                api_key="provider-key-company-31-marker"
            ),
            db=db,
            current_user=_client(31),
        )

    assert db.rollbacks == 1
    assert cleanup_calls == [
        ("provider-key-company-31-marker", migration_result)
    ]


def test_saved_validation_persists_safe_invalid_status(monkeypatch):
    db = _FakeDB()
    credential = _credential()
    error = ai_provider_service.AIProviderValidationError(
        "Chave OpenAI inválida ou sem autorização",
        credential_status="invalid",
        http_status_code=400,
    )
    monkeypatch.setattr(
        ai_provider_service,
        "get_company_ai_provider_credential",
        lambda _db, _company_id: credential,
    )

    def fail_validation(_db, _company_id):
        raise error

    monkeypatch.setattr(
        ai_provider_service,
        "validate_saved_company_openai_api_key",
        fail_validation,
    )

    response = routes.validate_ai_provider(
        db=db,
        current_user=_user("admin"),
    )

    assert response.status == "invalid"
    assert response.models == []
    assert response.last_error == "Chave OpenAI inválida ou sem autorização"
    assert "encrypted-secret" not in str(response.model_dump())
    assert db.commits == 1


def test_delete_is_scoped_to_active_company(monkeypatch):
    db = _FakeDB()
    credential = _credential(company_id=88)
    requested_company_ids = []

    def fake_get(_db, company_id):
        requested_company_ids.append(company_id)
        return credential

    monkeypatch.setattr(
        ai_provider_service,
        "get_company_ai_provider_credential",
        fake_get,
    )
    monkeypatch.setattr(
        ai_provider_knowledge_migration,
        "company_has_workforce_knowledge",
        lambda _db, _company_id: False,
    )

    response = routes.delete_ai_provider(
        db=db,
        current_user=_user("manager", company_id=88),
    )

    assert requested_company_ids == [88]
    assert db.deleted == [credential]
    assert db.commits == 1
    assert response.model_dump() == {
        "configured": False,
        "status": "not_configured",
        "last_validated_at": None,
        "last_error": None,
        "models": [],
    }


def test_delete_rejects_stranding_company_knowledge(monkeypatch):
    db = _FakeDB()
    credential = _credential(company_id=88)
    monkeypatch.setattr(
        ai_provider_service,
        "get_company_ai_provider_credential",
        lambda _db, _company_id: credential,
    )
    monkeypatch.setattr(
        ai_provider_knowledge_migration,
        "company_has_workforce_knowledge",
        lambda _db, company_id: company_id == 88,
    )

    with pytest.raises(HTTPException) as exc_info:
        routes.delete_ai_provider(
            db=db,
            current_user=_user("manager", company_id=88),
        )

    assert exc_info.value.status_code == 409
    assert "Substitua a chave" in exc_info.value.detail
    assert db.deleted == []
    assert db.commits == 0


def test_put_length_validation_never_echoes_raw_secret():
    db = _FakeDB()
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.dependency_overrides[routes.get_db] = lambda: db
    app.dependency_overrides[
        routes.require_ai_provider_management_access
    ] = lambda: _client(7)
    secret = "provider-sensitive-marker-" + ("x" * 520)

    with TestClient(app) as test_client:
        response = test_client.put(
            "/api/ai-provider",
            json={"api_key": secret},
        )

    assert response.status_code == 422
    assert secret not in response.text
    assert response.json() == {
        "detail": "A chave OpenAI deve ter entre 10 e 512 caracteres"
    }
