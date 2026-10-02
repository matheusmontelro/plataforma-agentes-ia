import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/agentive-create-lead-phone-test.db")

from backend.services.flow_node_handlers import CreateLeadHandler  # noqa: E402


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Database:
    def __init__(self, waha_enabled=True):
        self.row = SimpleNamespace(
            waha_enabled=waha_enabled,
            waha_session_name="test-session" if waha_enabled else None,
        )

    def execute(self, *_args, **_kwargs):
        return _Result(self.row)


def _mock_waha(monkeypatch, chat_id):
    import backend.config as config
    import backend.integrations.waha_sdk as waha_sdk

    class _Client:
        def check_number_status(self, **_kwargs):
            return {"chatId": chat_id}

    monkeypatch.setattr(config, "WAHA_API_KEY", "test-key")
    monkeypatch.setattr(waha_sdk, "get_client", lambda **_kwargs: _Client())


def test_waha_canonical_phone_accepts_valid_brazilian_chat_id(monkeypatch):
    _mock_waha(monkeypatch, "5511999999999@c.us")

    result = CreateLeadHandler()._canonicalize_phone_for_waha(
        _Database(), 1, "5511888888888"
    )

    assert result == "5511999999999"


def test_waha_canonical_phone_rejects_technical_chat_id(monkeypatch):
    _mock_waha(monkeypatch, "220005673242624@lid")

    result = CreateLeadHandler()._canonicalize_phone_for_waha(
        _Database(), 1, "5511888888888"
    )

    assert result == "5511888888888"


def test_waha_canonical_phone_keeps_original_when_chat_id_is_missing(monkeypatch):
    _mock_waha(monkeypatch, "")

    result = CreateLeadHandler()._canonicalize_phone_for_waha(
        _Database(), 1, "5511888888888"
    )

    assert result == "5511888888888"
