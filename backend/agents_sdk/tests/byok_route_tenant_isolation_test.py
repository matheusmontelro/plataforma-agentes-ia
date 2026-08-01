import asyncio
import inspect
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/agentive_test")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-with-at-least-32-characters",
)

from backend.routes import agents_sdk_routes
from backend.routes import prompt_config


class _FakeQuery:
    def __init__(self, records, db):
        self.records = list(records)
        self.db = db
        self.filters = {}

    def filter_by(self, **filters):
        self.filters.update(filters)
        self.db.query_filters.append(dict(self.filters))
        return self

    def first(self):
        return next(
            (
                record
                for record in self.records
                if all(
                    getattr(record, key, None) == value
                    for key, value in self.filters.items()
                )
            ),
            None,
        )

    def all(self):
        return [
            record
            for record in self.records
            if all(
                getattr(record, key, None) == value
                for key, value in self.filters.items()
            )
        ]


class _FakeDB:
    def __init__(self, records=()):
        self.records = list(records)
        self.query_filters = []
        self.added = []
        self.deleted = []
        self.commits = 0
        self.refreshed = []

    def query(self, _model):
        return _FakeQuery(self.records, self)

    def add(self, value):
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        self.refreshed.append(value)


def _user(company_id=7):
    return SimpleNamespace(company_id=company_id)


def _tenant_check(user, company_id, _db):
    if int(user.company_id) != int(company_id):
        raise HTTPException(status_code=403, detail="Acesso negado para esta empresa")


def _payload(*, company_id=7, config_id=1):
    return prompt_config.AgentConfigPayload(
        id=config_id,
        company_id=company_id,
        assistant_identity={"assistant_name": "Agente"},
        company_info={},
        team_and_specialties={},
        scheduling_config={},
        financial_config={},
        conversation_flow={},
        generated_prompt="Prompt",
    )


def test_agents_sdk_chat_rejects_foreign_company_before_manager_or_byok_use(
    monkeypatch,
):
    constructed = []

    class _ForbiddenManager:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

    from backend.agents_sdk import manager as manager_module

    monkeypatch.setattr(
        agents_sdk_routes,
        "ensure_user_can_access_company",
        _tenant_check,
    )
    monkeypatch.setattr(
        manager_module,
        "BusinessCompanyManager",
        _ForbiddenManager,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            agents_sdk_routes.chat_with_agent(
                agents_sdk_routes.ChatRequest(
                    company_id=8,
                    phone="5500000000007",
                    message="Olá",
                ),
                db="db",
                current_user=_user(7),
            ),
        )

    assert exc_info.value.status_code == 403
    assert constructed == []


def test_agents_sdk_chat_preserves_authenticated_same_company_behavior(
    monkeypatch,
):
    captured = {}

    class _Manager:
        def __init__(self, *, company_id, db):
            captured.update(company_id=company_id, db=db)

        def get_conversation_history(self, *, phone, limit):
            captured.update(history_phone=phone, history_limit=limit)
            return [{"role": "user", "content": "anterior"}]

        async def process_conversation(
            self,
            *,
            phone,
            user_input,
            conversation_history,
        ):
            captured.update(
                process_phone=phone,
                user_input=user_input,
                conversation_history=conversation_history,
            )
            return {"response": "Oi!", "metadata": {"tenant": 7}}

    from backend.agents_sdk import manager as manager_module

    monkeypatch.setattr(
        agents_sdk_routes,
        "ensure_user_can_access_company",
        _tenant_check,
    )
    monkeypatch.setattr(manager_module, "BusinessCompanyManager", _Manager)

    response = asyncio.run(
        agents_sdk_routes.chat_with_agent(
            agents_sdk_routes.ChatRequest(
                company_id=7,
                phone="5500000000007",
                message="Olá",
            ),
            db="db",
            current_user=_user(7),
        ),
    )

    assert response.response == "Oi!"
    assert response.metadata == {"tenant": 7}
    assert captured["company_id"] == 7
    assert captured["db"] == "db"
    assert captured["history_limit"] == 6
    assert captured["conversation_history"] == [
        {"role": "user", "content": "anterior"}
    ]


def test_agents_sdk_company_routes_require_authenticated_principal():
    protected = (
        agents_sdk_routes.chat_with_agent,
        agents_sdk_routes.get_company_info,
        agents_sdk_routes.refresh_company_embedding,
        agents_sdk_routes.get_company_slots,
        agents_sdk_routes.create_sample_slots,
        agents_sdk_routes.test_scheduling,
        agents_sdk_routes.get_conversation_history,
        agents_sdk_routes.get_company_stats,
        agents_sdk_routes.get_company_config_status,
    )

    for endpoint in protected:
        dependency = inspect.signature(endpoint).parameters["current_user"].default
        assert dependency.dependency is agents_sdk_routes.get_current_user


def test_prompt_config_routes_require_authenticated_principal():
    protected = (
        prompt_config.preview_agent_prompt,
        prompt_config.list_agent_configs,
        prompt_config.get_agent_config_detail,
        prompt_config.upsert_agent_config,
        prompt_config.delete_agent_config_by_id,
        prompt_config.get_agent_config_legacy,
        prompt_config.update_agent_config_legacy,
    )

    for endpoint in protected:
        dependency = inspect.signature(endpoint).parameters["current_user"].default
        assert dependency.dependency is prompt_config.get_current_user


def test_prompt_detail_hides_foreign_tenant_config(monkeypatch):
    foreign = SimpleNamespace(id=42, company_id=8)
    db = _FakeDB([foreign])
    monkeypatch.setattr(
        prompt_config,
        "ensure_user_can_access_company",
        _tenant_check,
    )

    with pytest.raises(HTTPException) as exc_info:
        prompt_config.get_agent_config_detail(
            42,
            db=db,
            current_user=_user(7),
        )

    assert exc_info.value.status_code == 404
    assert db.query_filters == [{"id": 42, "company_id": 7}]


def test_prompt_upsert_rejects_request_company_before_database_mutation(
    monkeypatch,
):
    db = _FakeDB()
    monkeypatch.setattr(
        prompt_config,
        "ensure_user_can_access_company",
        _tenant_check,
    )

    with pytest.raises(HTTPException) as exc_info:
        prompt_config.upsert_agent_config(
            _payload(company_id=8),
            db=db,
            current_user=_user(7),
        )

    assert exc_info.value.status_code == 403
    assert db.query_filters == []
    assert db.added == []
    assert db.commits == 0


def test_prompt_upsert_preserves_same_tenant_update(monkeypatch):
    config = SimpleNamespace(id=12, company_id=7)
    db = _FakeDB([config])
    monkeypatch.setattr(
        prompt_config,
        "ensure_user_can_access_company",
        _tenant_check,
    )

    response = prompt_config.upsert_agent_config(
        _payload(company_id=7, config_id=12),
        db=db,
        current_user=_user(7),
    )

    assert response["config_id"] == 12
    assert db.query_filters == [{"id": 12, "company_id": 7}]
    assert db.commits == 1
    assert config.generated_prompt == "Prompt"


def test_prompt_delete_cannot_delete_foreign_tenant_config(monkeypatch):
    foreign = SimpleNamespace(id=42, company_id=8)
    db = _FakeDB([foreign])
    monkeypatch.setattr(
        prompt_config,
        "ensure_user_can_access_company",
        _tenant_check,
    )

    with pytest.raises(HTTPException) as exc_info:
        prompt_config.delete_agent_config_by_id(
            42,
            db=db,
            current_user=_user(7),
        )

    assert exc_info.value.status_code == 404
    assert db.deleted == []
    assert db.commits == 0


def test_prompt_legacy_update_rejects_path_payload_tenant_mismatch(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(
        prompt_config,
        "ensure_user_can_access_company",
        _tenant_check,
    )

    with pytest.raises(HTTPException) as exc_info:
        prompt_config.update_agent_config_legacy(
            7,
            _payload(company_id=8),
            db=db,
            current_user=_user(7),
        )

    assert exc_info.value.status_code == 403
    assert db.query_filters == []
    assert db.commits == 0
