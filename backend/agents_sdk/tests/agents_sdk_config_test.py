from types import SimpleNamespace

from backend.agents_sdk.config import (
    is_company_enabled,
    is_customer_identification_enabled,
)


class _ConfigDb:
    def __init__(self, configured_company_ids):
        self.configured_company_ids = set(configured_company_ids)
        self.requested_company_ids = []

    def execute(self, _statement, params):
        company_id = int(params["company_id"])
        self.requested_company_ids.append(company_id)
        row = SimpleNamespace() if company_id in self.configured_company_ids else None
        return SimpleNamespace(fetchone=lambda: row)


def test_agents_sdk_accepts_any_workspace_with_persisted_configuration():
    db = _ConfigDb({9876})

    assert is_company_enabled(9876, db) is True
    assert db.requested_company_ids == [9876]


def test_agents_sdk_rejects_workspace_without_configuration():
    db = _ConfigDb(set())

    assert is_company_enabled(4321, db) is False
    assert is_customer_identification_enabled(4321, db) is False


def test_agents_sdk_fails_closed_without_database_session():
    assert is_company_enabled(9876) is False
