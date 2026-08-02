import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("WAHA_API_KEY", "test-waha-key")
os.environ.setdefault("WAHA_BASE_URL", "http://waha.local")

from backend.integrations.whatsapp_provider import WhatsAppConfig
from backend.prompt.memory import memory_manager
from backend.worker import process_message_waha as waha_worker
from backend.worker.process_message_waha import (
    _build_internal_waha_file_url,
    _extract_waha_file_path,
    _message_tracker_content_for_check,
    _materialize_audio_content,
    _waha_conversation_kind,
    _waha_payload_summary,
    _waha_proxy_media_url,
    normalize_waha_payload,
)
from backend.webhook_audit import save_webhook_audit
from backend.services.message_metadata import (
    _waha_stanza_id,
    extract_waha_reply_to,
    map_waha_ack_to_delivery_status,
    normalize_reply_request,
    update_message_delivery_status,
)


class _FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeDB:
    def __init__(self, row):
        self.row = row
        self.queries = []

    def execute(self, query, params):
        self.queries.append(str(query))
        return _FakeResult(self.row)


class _AckFallbackDB:
    def __init__(self, candidates):
        self.candidates = candidates
        self.executions = []
        self.commits = 0
        self.exact_updates = 0
        self.fallback_updates = 0
        self.fallback_pattern = None

    def execute(self, query, params):
        sql = " ".join(str(query).split())
        self.executions.append((sql, params))

        if "UPDATE messages" in sql and "zapi_message_id = :provider_message_id" in sql:
            self.exact_updates += 1
            return _FakeResult()

        if "SELECT id, zapi_message_id" in sql and "LIKE :stanza_pattern" in sql:
            self.fallback_pattern = params["stanza_pattern"]
            return _FakeResult(rows=self.candidates)

        if "UPDATE messages" in sql and "WHERE id = :message_db_id" in sql:
            self.fallback_updates += 1
            local_message = self.candidates[0]
            return _FakeResult(SimpleNamespace(
                id=local_message.id,
                contact_phone="5500000000004",
                zapi_message_id=local_message.zapi_message_id,
                delivery_status=params["status"],
                delivery_ack=params["ack"],
            ))

        raise AssertionError(f"Query inesperada: {sql}")

    def commit(self):
        self.commits += 1


def test_whatsapp_config_ignores_legacy_zapi_credentials():
    db = _FakeDB(
        SimpleNamespace(
            waha_enabled=False,
            waha_session_name=None,
            operational_status="active",
            zapi_instance_id="legacy-instance",
            zapi_token="legacy-token",
        )
    )

    assert WhatsAppConfig.from_company(7, db) is None
    assert "zapi_instance_id" not in " ".join(db.queries)
    assert "zapi_token" not in " ".join(db.queries)


def test_whatsapp_config_returns_only_waha():
    db = _FakeDB(
        SimpleNamespace(
            waha_enabled=True,
            waha_session_name="sessao-teste",
            operational_status="active",
        )
    )

    config = WhatsAppConfig.from_company(7, db)

    assert config is not None
    assert config.provider == "waha"
    assert config.config["session_name"] == "sessao-teste"


@pytest.mark.parametrize(
    ("payload", "expected_kind"),
    [
        (
            {
                "id": "false_000000000000000001@g.us_MESSAGE",
                "from": "5500000000007@c.us",
                "type": "chat",
            },
            "group",
        ),
        (
            {
                "id": "true_120363000000000000@newsletter_MESSAGE",
                "from": "5500000000007@c.us",
                "to": "120363000000000000@newsletter",
                "fromMe": True,
                "type": "chat",
            },
            "newsletter",
        ),
        (
            {
                "id": "status-message",
                "from": "5500000000007@c.us",
                "type": "chat",
                "_data": {"Info": {"Chat": "status@broadcast"}},
            },
            "status",
        ),
        (
            {
                "id": "false_5500900000003@c.us_MESSAGE",
                "from": "5500000000007@c.us",
                "type": "chat",
            },
            None,
        ),
    ],
)
def test_normalize_waha_payload_classifies_non_direct_conversations(
    payload,
    expected_kind,
):
    assert _waha_conversation_kind(payload) == expected_kind

    normalized = normalize_waha_payload(
        {"event": "message.any", "session": "sessao-teste", "payload": payload}
    )

    assert normalized["isGroup"] is (expected_kind == "group")
    assert normalized["isNewsletter"] is (expected_kind == "newsletter")
    assert normalized["broadcast"] is (expected_kind == "status")


def test_save_webhook_audit_persists_resolved_company_and_waha_message_id():
    class _AuditDB:
        def __init__(self):
            self.executions = []
            self.commits = 0

        def execute(self, query, params):
            self.executions.append((" ".join(str(query).split()), params))
            return _FakeResult((91,))

        def commit(self):
            self.commits += 1

        def rollback(self):
            raise AssertionError("rollback não esperado")

    db = _AuditDB()

    audit_id = save_webhook_audit(
        db,
        "company_7_waha",
        {
            "id": "raw-waha-id",
            "from": "5500000000007@c.us",
            "type": "image",
        },
        company_id=7,
        message_id="normalized-waha-id",
        event_type="message.any",
    )

    sql, params = db.executions[0]
    assert audit_id == 91
    assert "instance_id, company_id, message_id" in sql
    assert params["company_id"] == 7
    assert params["message_id"] == "normalized-waha-id"
    assert params["phone"] == "5500000000007@c.us"
    assert params["message_type"] == "waha:message.any"
    assert json.loads(params["message_data"]) == {
        "id": "raw-waha-id",
        "from": "5500000000007@c.us",
        "type": "image",
    }
    assert db.commits == 1


def test_whatsapp_config_blocks_inactive_company():
    db = _FakeDB(
        SimpleNamespace(
            waha_enabled=True,
            waha_session_name="sessao-teste",
            operational_status="inactive",
        )
    )

    assert WhatsAppConfig.from_company(7, db) is None


def test_memory_manager_creates_configured_chatmemory_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_manager, "BASE_PATH", tmp_path / "chatmemory")

    memory_manager.append_message_to_chat_file(
        company_id=7,
        contact_phone="5500000000004",
        from_me=False,
        content="Ola",
    )

    history_file = tmp_path / "chatmemory" / "chatmemory_7_5500000000004.txt"
    assert history_file.exists()
    assert "HUMAN:" in history_file.read_text(encoding="utf-8")


def test_waha_payload_summary_does_not_include_sensitive_payload_values():
    payload = {
        "event": "message",
        "session": "sessao-teste",
        "payload": {
            "body": "texto sigiloso do cliente",
            "media": {
                "url": "http://localhost:3000/api/files/private/audio.ogg",
                "mimetype": "audio/ogg",
                "filename": "audio.ogg",
            },
            "_data": {
                "Message": {
                    "audioMessage": {
                        "base64": "BASE64_SUPER_SECRETO",
                        "mimetype": "audio/ogg",
                    },
                    "messageSecret": "MESSAGE_SECRET_VALUE",
                }
            },
        },
    }

    summary = _waha_payload_summary(payload)
    serialized = repr(summary)

    assert "texto sigiloso" not in serialized
    assert "http://localhost:3000/api/files/private/audio.ogg" not in serialized
    assert "BASE64_SUPER_SECRETO" not in serialized
    assert "MESSAGE_SECRET_VALUE" not in serialized
    assert summary["media"]["has_url"] is True
    assert summary["body_len"] == len("texto sigiloso do cliente")


def test_normalize_waha_from_me_app_message_keeps_external_origin():
    normalized = normalize_waha_payload({
        "event": "message.any",
        "session": "sessao-teste",
        "payload": {
            "id": "true_5500900000005@c.us_APP",
            "timestamp": 1710000000,
            "from": "me@c.us",
            "to": "5500000000004@c.us",
            "fromMe": True,
            "source": "app",
            "type": "chat",
            "body": "Mensagem enviada pelo celular",
            "_data": {"Info": {"PushName": "Cliente"}},
        },
    })

    assert normalized["phone"] == "5500000000004"
    assert normalized["fromMe"] is True
    assert normalized["fromApi"] is False
    assert normalized["source"] == "app"
    assert normalized["text"]["message"] == "Mensagem enviada pelo celular"


def test_normalize_waha_text_uses_conversation_fallback_when_body_is_empty():
    normalized = normalize_waha_payload({
        "event": "message.any",
        "session": "sessao-teste",
        "payload": {
            "id": "true_5500900000005@c.us_API",
            "timestamp": 1710000000,
            "from": "me@c.us",
            "to": "5500000000004@c.us",
            "fromMe": True,
            "source": "api",
            "type": "chat",
            "body": "",
            "_data": {
                "Info": {"PushName": "Cliente"},
                "Message": {"conversation": "Texto veio do campo interno"},
            },
        },
    })

    assert normalized["fromApi"] is True
    assert normalized["text"]["message"] == "Texto veio do campo interno"


def test_message_tracker_content_uses_normalized_media_keys():
    assert _message_tracker_content_for_check(
        "image",
        {"image": {"imageUrl": "/api/waha/media/foto.jpg"}},
        "",
    ) == "/api/waha/media/foto.jpg"
    assert _message_tracker_content_for_check(
        "text",
        {"text": {"message": "Ola"}},
        "",
    ) == "Ola"


def test_waha_media_url_helpers_use_configured_internal_base(monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "WAHA_BASE_URL", "http://waha.local")
    media_url = "http://localhost:3000/api/files/sessao-exemplo/video.mp4?download=1"

    assert _extract_waha_file_path(media_url) == "sessao-exemplo/video.mp4"
    assert _build_internal_waha_file_url("sessao-exemplo/video.mp4") == "http://waha.local/api/files/sessao-exemplo/video.mp4"
    assert _waha_proxy_media_url(media_url) == "/api/waha/media/sessao-exemplo/video.mp4"


def test_waha_media_url_helpers_ignore_non_waha_files_urls():
    media_url = "https://example.com/video.mp4"

    assert _extract_waha_file_path(media_url) == ""
    assert _waha_proxy_media_url(media_url) == media_url


def test_materialize_audio_content_preserves_local_waha_proxy(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("requests.get nao deveria ser chamado para proxy local")

    monkeypatch.setattr(waha_worker.requests, "get", fail_get)

    audio_url = "/api/waha/media/company_3/audio.oga"

    assert _materialize_audio_content(audio_url, "audio/ogg; codecs=opus") == audio_url


def test_waha_ack_status_mapping_prefers_ack_name():
    assert map_waha_ack_to_delivery_status(3, "READ") == "read"
    assert map_waha_ack_to_delivery_status(4, "PLAYED") == "played"
    assert map_waha_ack_to_delivery_status(-1, "FAILED") == "failed"
    assert map_waha_ack_to_delivery_status(2, None) == "delivered"


def test_waha_stanza_id_extracts_only_direct_message_suffix():
    assert _waha_stanza_id("true_000000000000002@lid_3EB0000000000000000001") == "3EB0000000000000000001"
    assert _waha_stanza_id("true_5500900000005@c.us_3EB0000000000000000001") == "3EB0000000000000000001"
    assert _waha_stanza_id("false_000000000000009001@g.us_3EB0000000000000002329_000000000000003@lid") == ""


def test_update_message_delivery_status_matches_waha_lid_ack_by_stanza_id():
    db = _AckFallbackDB([
        SimpleNamespace(
            id=4260,
            zapi_message_id="true_5500900000005@c.us_3EB0000000000000000001",
        )
    ])

    payload = update_message_delivery_status(
        db=db,
        company_id=3,
        provider_message_id="true_000000000000002@lid_3EB0000000000000000001",
        status="delivered",
        ack=2,
        ack_name="DEVICE",
        publish=False,
    )

    assert payload["messageId"] == "true_5500900000005@c.us_3EB0000000000000000001"
    assert payload["status"] == "delivered"
    assert payload["ack"] == 2
    assert db.exact_updates == 1
    assert db.fallback_updates == 1
    assert db.fallback_pattern == "%!_3EB0000000000000000001"
    assert db.commits == 1


def test_update_message_delivery_status_does_not_update_ambiguous_stanza_id():
    db = _AckFallbackDB([
        SimpleNamespace(id=1, zapi_message_id="true_1111111111111@c.us_3EB0000000000000000001"),
        SimpleNamespace(id=2, zapi_message_id="true_2222222222222@c.us_3EB0000000000000000001"),
    ])

    payload = update_message_delivery_status(
        db=db,
        company_id=3,
        provider_message_id="true_000000000000002@lid_3EB0000000000000000001",
        status="delivered",
        ack=2,
        ack_name="DEVICE",
        publish=False,
    )

    assert payload is None
    assert db.exact_updates == 1
    assert db.fallback_updates == 0
    assert db.commits == 1


def test_update_waha_ack_delivery_status_retries_when_ack_races_insert(monkeypatch):
    calls = []
    sleeps = []

    def fake_update_message_delivery_status(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return None
        return {"status": kwargs["status"], "messageId": kwargs["provider_message_id"]}

    monkeypatch.setattr(waha_worker, "update_message_delivery_status", fake_update_message_delivery_status)
    monkeypatch.setattr(waha_worker.time, "sleep", lambda seconds: sleeps.append(seconds))

    payload = waha_worker._update_waha_ack_delivery_status(
        db=object(),
        company_id=3,
        message_id="true_000000000000002@lid_3EB0000000000000000001",
        delivery_status="delivered",
        ack_status=2,
        ack_name="DEVICE",
        retry_attempts=2,
        retry_delay_seconds=0.01,
    )

    assert payload["status"] == "delivered"
    assert len(calls) == 2
    assert sleeps == [0.01]


def test_extract_waha_reply_to_uses_safe_preview():
    payload = {
        "replyTo": {
            "id": "false_5500900000003@c.us_ABC",
            "participant": "5500000000007@c.us",
            "body": "Mensagem original muito grande " * 20,
            "hasMedia": True,
            "media": {
                "url": "http://localhost:3000/api/files/example.jpg",
                "mimetype": "image/jpeg",
                "filename": None,
            },
        }
    }

    reply = extract_waha_reply_to(payload)

    assert reply["id"] == "false_5500900000003@c.us_ABC"
    assert reply["hasMedia"] is True
    assert reply["media"]["mimetype"] == "image/jpeg"
    assert len(reply["body"]) <= 160


def test_normalize_reply_request_accepts_frontend_preview():
    reply = normalize_reply_request({
        "id": "42",
        "providerMessageId": "false_5500900000003@c.us_ABC",
        "content": "Ola",
        "senderName": "Cliente",
        "type": "text",
    })

    assert reply["id"] == "42"
    assert reply["providerMessageId"] == "false_5500900000003@c.us_ABC"
    assert reply["body"] == "Ola"
    assert reply["senderName"] == "Cliente"


def test_download_waha_media_uses_internal_base_and_returns_proxy(monkeypatch, tmp_path):
    from backend import config

    class _FakeResponse:
        status_code = 200
        text = ""

        def iter_content(self, chunk_size):
            yield b"media-bytes"

    requested = {}

    def fake_get(url, timeout, stream, headers):
        requested["url"] = url
        requested["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr(waha_worker, "MEDIA_ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(waha_worker, "WAHA_MEDIA_DIR", str(tmp_path / "waha"))
    monkeypatch.setattr(config, "WAHA_BASE_URL", "http://waha.local")
    monkeypatch.setattr(config, "WAHA_API_KEY", "test-waha-key")
    monkeypatch.setattr(waha_worker.requests, "get", fake_get)

    proxy_url = waha_worker.download_waha_media(
        "http://localhost:3000/api/files/sessao-exemplo/foto.jpeg",
        company_id=3,
        message_id="false_123@lid_ABC",
    )

    assert requested["url"] == "http://waha.local/api/files/sessao-exemplo/foto.jpeg"
    assert requested["headers"] == {"X-Api-Key": "test-waha-key"}
    assert proxy_url == "/api/waha/media/company_3/false_123@lid_ABC_foto.jpeg"
    assert (tmp_path / "waha/company_3/false_123@lid_ABC_foto.jpeg").read_bytes() == b"media-bytes"
