import base64
from contextlib import contextmanager

from backend.integrations import whatsapp_provider
from backend.integrations import waha_utils
from backend.integrations.whatsapp_provider import (
    WhatsAppConfig,
    _detect_audio_mime_from_header,
    send_audio,
    send_contact_card,
)
from backend.integrations.waha_sdk import WAHAClient


@contextmanager
def _passthrough_company_operation(_company_id, db):
    yield db if db is not None else object()


def test_detect_audio_mime_from_header_supports_elevenlabs_mp3_id3():
    audio = b"ID3\x04\x00\x00\x00\x00\x00\x21" + b"\x00" * 32

    assert _detect_audio_mime_from_header(audio) == "audio/mpeg"


def test_detect_audio_mime_from_header_supports_raw_mp3_frame():
    audio = b"\xff\xfb\x90\x64" + b"\x00" * 32

    assert _detect_audio_mime_from_header(audio) == "audio/mpeg"


def test_detect_audio_mime_from_header_supports_webm():
    audio = b"\x1a\x45\xdf\xa3" + b"\x00" * 32

    assert _detect_audio_mime_from_header(audio) == "audio/webm"


def test_waha_send_voice_base64_payload_uses_convert_true(monkeypatch):
    client = WAHAClient("http://waha.local", "test-key")
    requests = []

    monkeypatch.setattr(
        client,
        "resolve_chat_id",
        lambda session, phone: "5500000000001@c.us",
    )

    def fake_request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        return {"id": "voice-1"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.send_voice_base64(
        session="workspace-demo",
        phone="5500000000001",
        audio_data="SUQz",
        filename="audio.mp3",
        mimetype="audio/mpeg",
    )

    assert result == {"id": "voice-1"}
    method, endpoint, kwargs = requests[0]
    assert method == "POST"
    assert endpoint == "/api/sendVoice"
    assert kwargs["json"] == {
        "session": "workspace-demo",
        "chatId": "5500000000001@c.us",
        "file": {
            "mimetype": "audio/mpeg",
            "filename": "audio.mp3",
            "data": "SUQz",
        },
        "convert": True,
    }


def test_waha_send_contact_vcard_payload(monkeypatch):
    client = WAHAClient("http://waha.local", "test-key")
    requests = []

    monkeypatch.setattr(
        client,
        "resolve_chat_id",
        lambda session, phone: "5500000000001@c.us",
    )

    def fake_request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        return {"id": "contact-1"}

    monkeypatch.setattr(client, "_request", fake_request)

    contacts = [
        {
            "fullName": "Cliente Exemplo",
            "phoneNumber": "+55 00 00000-0000",
            "whatsappId": "5500000000001",
            "vcard": "BEGIN:VCARD\nVERSION:3.0\nFN:Cliente Exemplo\nEND:VCARD",
        }
    ]
    result = client.send_contact_vcard(
        session="workspace-demo",
        phone="5500000000001",
        contacts=contacts,
    )

    assert result == {"id": "contact-1"}
    method, endpoint, kwargs = requests[0]
    assert method == "POST"
    assert endpoint == "/api/sendContactVcard"
    assert kwargs["json"] == {
        "session": "workspace-demo",
        "chatId": "5500000000001@c.us",
        "contacts": contacts,
    }


def test_waha_send_text_payload_requests_automatic_link_preview(monkeypatch):
    client = WAHAClient("http://waha.local", "test-key")
    requests = []

    monkeypatch.setattr(
        client,
        "resolve_chat_id",
        lambda session, phone: "5500000000001@c.us",
    )

    def fake_request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        return {"id": "text-1"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.send_text(
        session="workspace-demo",
        phone="5500000000001",
        text="Veja https://example.com",
    )

    assert result == {"id": "text-1"}
    method, endpoint, kwargs = requests[0]
    assert method == "POST"
    assert endpoint == "/api/sendText"
    assert kwargs["json"] == {
        "session": "workspace-demo",
        "chatId": "5500000000001@c.us",
        "text": "Veja https://example.com",
        "linkPreview": True,
        "linkPreviewHighQuality": True,
    }


def test_waha_utils_send_text_payload_requests_automatic_link_preview(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 201
        text = '{"id":"text-2"}'

        def json(self):
            return {"id": "text-2"}

    def fake_post(url, headers, json, timeout):
        requests.append({
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        })
        return FakeResponse()

    monkeypatch.setattr(waha_utils, "WAHA_BASE_URL", "http://waha.local")
    monkeypatch.setattr(waha_utils, "WAHA_API_KEY", "test-key")
    monkeypatch.setattr(
        waha_utils,
        "_post_for_operational_company",
        lambda _company_id, url, *, headers, payload, timeout: fake_post(
            url,
            headers,
            payload,
            timeout,
        ),
    )
    monkeypatch.setattr(waha_utils.requests, "post", fake_post)

    result = waha_utils.send_text_to_waha(
        waha_session_name="workspace-demo",
        phone="5500000000001",
        message="Veja https://example.com",
        company_id=7,
    )

    assert result == {"id": "text-2"}
    request = requests[0]
    assert request["url"] == "http://waha.local/api/sendText"
    assert request["json"] == {
        "session": "workspace-demo",
        "chatId": "5500000000001@c.us",
        "text": "Veja https://example.com",
        "linkPreview": True,
        "linkPreviewHighQuality": True,
    }


def test_waha_request_code_uses_session_auth_endpoint(monkeypatch):
    client = WAHAClient("http://waha.local", "test-key")
    requests = []

    def fake_request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        return {"code": "ABCD-ABCD"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.request_code("workspace-demo", "5500000000001")

    assert result == {"code": "ABCD-ABCD"}
    assert requests == [
        (
            "POST",
            "/api/workspace-demo/auth/request-code",
            {"json": {"phoneNumber": "5500000000001"}},
        )
    ]


def test_send_audio_waha_uses_base64_payload_for_bytes(monkeypatch):
    audio = b"ID3\x04\x00\x00\x00\x00\x00\x21" + b"\x00" * 32
    sent = {}
    monkeypatch.setattr(
        whatsapp_provider,
        "_locked_company_remote_operation",
        _passthrough_company_operation,
    )

    monkeypatch.setattr(
        whatsapp_provider.WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: WhatsAppConfig(
                "waha",
                session_name="workspace-demo",
                base_url="http://waha.local",
                **{"api" + "_key": "placeholder-token"},
            )
        ),
    )

    class FakeWAHAClient:
        def send_voice_base64(self, **kwargs):
            sent.update(kwargs)
            return {"id": "voice-1"}

    monkeypatch.setattr(
        whatsapp_provider,
        "get_waha_client",
        lambda **kwargs: FakeWAHAClient(),
    )

    result = send_audio(
        company_id=7,
        phone="5500000000001",
        audio_bytes=audio,
        db=None,
    )

    assert result == {"id": "voice-1"}
    assert sent["session"] == "workspace-demo"
    assert sent["phone"] == "5500000000001"
    assert sent["audio_data"] == base64.b64encode(audio).decode("ascii")
    assert sent["filename"] == "audio.mp3"
    assert sent["mimetype"] == "audio/mpeg"


def test_send_contact_card_waha_uses_vcard_payload(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        whatsapp_provider,
        "_locked_company_remote_operation",
        _passthrough_company_operation,
    )

    monkeypatch.setattr(
        whatsapp_provider.WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: WhatsAppConfig(
                "waha",
                session_name="workspace-demo",
                base_url="http://waha.local",
                **{"api" + "_key": "placeholder-token"},
            )
        ),
    )

    class FakeWAHAClient:
        def send_contact_vcard(self, **kwargs):
            sent.update(kwargs)
            return {"id": "contact-1"}

    monkeypatch.setattr(
        whatsapp_provider,
        "get_waha_client",
        lambda **kwargs: FakeWAHAClient(),
    )

    contacts = [
        {
            "fullName": "Cliente Exemplo",
            "phoneNumber": "+55 00 00000-0000",
            "vcard": "BEGIN:VCARD\nVERSION:3.0\nFN:Cliente Exemplo\nEND:VCARD",
        }
    ]
    result = send_contact_card(
        company_id=7,
        phone="5500000000001",
        contacts=contacts,
        db=None,
    )

    assert result == {"id": "contact-1"}
    assert sent["session"] == "workspace-demo"
    assert sent["phone"] == "5500000000001"
    assert sent["contacts"] == contacts
