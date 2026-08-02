from backend.integrations.whatsapp_provider import WhatsAppConfig
from backend.services import company_access_control
from backend.worker import agent_workforce_debounce, debounce_tasks
from backend.worker.agent_workforce_debounce import _image_payloads_from_entries


def test_image_payloads_from_entries_preserves_debounced_whatsapp_images():
    entries = [
        {
            "message_text": "oi",
            "message_data": {
                "type": "text",
                "body": "oi",
            },
        },
        {
            "message_text": "[Imagem recebida via WhatsApp]",
            "message_data": {
                "type": "image",
                "mediaUrl": "/api/waha/media/company_7/foto.png",
                "caption": "comprovante",
                "mimetype": "image/png",
            },
        },
    ]

    assert _image_payloads_from_entries(entries) == [
        {
            "imageUrl": "/api/waha/media/company_7/foto.png",
            "caption": "comprovante",
            "mimetype": "image/png",
        }
    ]


def test_image_payloads_from_entries_deduplicates_sources():
    entries = [
        {
            "message_text": "[Imagem recebida via WhatsApp]",
            "message_data": {
                "type": "image",
                "image": {
                    "imageUrl": "/api/waha/media/company_7/foto.png",
                    "caption": "a",
                    "mimetype": "image/png",
                },
            },
        },
        {
            "message_text": "[Imagem recebida via WhatsApp]",
            "message_data": {
                "type": "image",
                "mediaUrl": "/api/waha/media/company_7/foto.png",
                "caption": "b",
                "mimetype": "image/png",
            },
        },
    ]

    assert len(_image_payloads_from_entries(entries)) == 1


def test_stale_operational_epoch_drops_debounce_before_flow_execution(monkeypatch):
    events = []

    class _DB:
        def close(self):
            events.append("db-close")

    class _Redis:
        def delete(self, *keys):
            events.append(("delete", keys))

    monkeypatch.setattr("backend.db.SessionLocal", lambda: _DB())
    monkeypatch.setattr(
        company_access_control,
        "validate_company_job_epoch",
        lambda _db, company_id, epoch: (
            events.append(("validate", company_id, epoch)) or False
        ),
    )
    monkeypatch.setattr(agent_workforce_debounce, "redis_client", _Redis())
    monkeypatch.setattr(
        agent_workforce_debounce,
        "_stop_typing_indicator",
        lambda **kwargs: events.append(("stop", kwargs)),
    )

    agent_workforce_debounce.process_debounced_whatsapp_flow.run(
        7,
        "5500000000007",
        11,
        13,
        "nonce",
        0,
    )

    assert events[0] == ("validate", 7, 0)
    assert events[1] == "db-close"
    assert events[2][0] == "delete"
    assert all(":0:" in key for key in events[2][1])
    assert events[3] == (
        "stop",
        {"company_id": 7, "phone": "5500000000007"},
    )


def test_legacy_debounce_drops_stale_epoch_before_reading_buffer(monkeypatch):
    events = []

    class _DB:
        def close(self):
            events.append("db-close")

    class _Redis:
        def delete(self, *keys):
            events.append(("delete", keys))

        def lrange(self, *_args):
            raise AssertionError("buffer obsoleto não deve ser lido")

    monkeypatch.setattr("backend.db.SessionLocal", lambda: _DB())
    monkeypatch.setattr(
        company_access_control,
        "validate_company_job_epoch",
        lambda _db, company_id, epoch: (
            events.append(("validate", company_id, epoch)) or False
        ),
    )
    monkeypatch.setattr(debounce_tasks, "redis_client", _Redis())

    debounce_tasks.process_debounced_messages.run(
        "5500000000007",
        {"company_id": 7, "_operational_epoch": 0},
    )

    assert events == [
        ("validate", 7, 0),
        "db-close",
        (
            "delete",
            (
                "debounce_buffer:7:0:5500000000007",
                "debounce_task:7:0:5500000000007",
            ),
        ),
    ]


def test_typing_indicator_rechecks_company_under_access_lock(monkeypatch):
    events = []

    class _DB:
        locked = False

        def close(self):
            events.append("close")

    db = _DB()

    def lock(current_db, *, company_ids=(), **_kwargs):
        assert current_db is db
        assert list(company_ids) == [7]
        current_db.locked = True
        events.append("lock")

    def ensure(current_db, company_id):
        assert current_db.locked
        assert company_id == 7
        events.append("recheck")

    class _WAHA:
        def start_typing(self, *, session, phone):
            assert db.locked
            assert session == "company_7"
            assert phone == "5500000000007"
            events.append("remote")

    monkeypatch.setattr("backend.db.SessionLocal", lambda: db)
    monkeypatch.setattr(
        company_access_control,
        "lock_entities_for_mutation",
        lock,
    )
    monkeypatch.setattr(company_access_control, "ensure_company_operational", ensure)
    monkeypatch.setattr(
        WhatsAppConfig,
        "from_company",
        classmethod(
            lambda cls, company_id, db=None: WhatsAppConfig(
                "waha",
                session_name="company_7",
                base_url="http://waha.local",
                api_key="test-key",
            )
        ),
    )
    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: _WAHA(),
    )

    agent_workforce_debounce._set_typing_indicator(
        company_id=7,
        phone="5500000000007",
        active=True,
    )

    assert events == ["lock", "recheck", "remote", "close"]


def test_typing_indicator_has_no_remote_side_effect_when_company_is_blocked(
    monkeypatch,
):
    events = []

    class _DB:
        def close(self):
            events.append("close")

    db = _DB()

    monkeypatch.setattr("backend.db.SessionLocal", lambda: db)
    monkeypatch.setattr(
        company_access_control,
        "lock_entities_for_mutation",
        lambda *_args, **_kwargs: events.append("lock"),
    )

    def blocked(_db, company_id):
        events.append("recheck-blocked")
        raise company_access_control.CompanyOperationallyBlockedError(
            company_id,
            "inactive",
        )

    monkeypatch.setattr(company_access_control, "ensure_company_operational", blocked)
    monkeypatch.setattr(
        "backend.integrations.waha_sdk.get_client",
        lambda **_kwargs: events.append("unexpected-remote"),
    )

    agent_workforce_debounce._set_typing_indicator(
        company_id=7,
        phone="5500000000007",
        active=False,
    )

    assert events == ["lock", "recheck-blocked", "close"]
