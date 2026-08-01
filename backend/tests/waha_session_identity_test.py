import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("WAHA_API_KEY", "test-waha-key")
os.environ.setdefault("WAHA_BASE_URL", "http://waha.local")

from backend.routes.webhook import (  # noqa: E402
    _new_waha_session_name,
    _resolve_or_generate_waha_session_name,
)
from backend.routes.waha_routes import _resolve_waha_company_id  # noqa: E402
from backend.runtime_settings import app_slug  # noqa: E402


class _Result:
    def __init__(self, *, scalar_value=None, rows=None):
        self.scalar_value = scalar_value
        self.rows = rows or []

    def scalar(self):
        return self.scalar_value

    def fetchall(self):
        return self.rows


class _SessionDB:
    def __init__(self, current_session, sessions_owned_by_others=()):
        self.current_session = current_session
        self.sessions_owned_by_others = {value.lower() for value in sessions_owned_by_others}

    def execute(self, query, params):
        sql = " ".join(str(query).split())
        if sql.startswith("SELECT waha_session_name"):
            return _Result(scalar_value=self.current_session)
        if "SELECT EXISTS" in sql:
            return _Result(
                scalar_value=params["session_name"].strip().lower() in self.sessions_owned_by_others
            )
        raise AssertionError(f"Query inesperada: {sql}")


class _WebhookDB:
    def __init__(self, company_ids):
        self.company_ids = company_ids

    def execute(self, _query, _params):
        return _Result(rows=[SimpleNamespace(id=company_id) for company_id in self.company_ids])


def test_generated_session_name_is_opaque_and_company_scoped():
    session_name = _new_waha_session_name(12)
    prefix = f"{app_slug()}-c12-"

    assert session_name.startswith(prefix)
    assert len(session_name) == len(prefix) + 12


def test_existing_exclusive_session_is_reused():
    existing = f"{app_slug()}-c12-existing"
    db = _SessionDB(existing)

    assert _resolve_or_generate_waha_session_name(db, 12) == existing


def test_shared_session_is_replaced_with_generated_identifier():
    db = _SessionDB("Agente", sessions_owned_by_others={"agente"})

    session_name = _resolve_or_generate_waha_session_name(db, 12)

    assert session_name.startswith(f"{app_slug()}-c12-")
    assert session_name.lower() != "agente"


def test_webhook_resolves_exactly_one_company():
    assert _resolve_waha_company_id(_WebhookDB([12]), f"{app_slug()}-c12-test") == 12


def test_webhook_rejects_ambiguous_session_mapping():
    with pytest.raises(HTTPException) as error:
        _resolve_waha_company_id(_WebhookDB([12, 24]), "Agente")

    assert error.value.status_code == 409


def test_webhook_rejects_unknown_session():
    with pytest.raises(HTTPException) as error:
        _resolve_waha_company_id(_WebhookDB([]), "missing")

    assert error.value.status_code == 404
