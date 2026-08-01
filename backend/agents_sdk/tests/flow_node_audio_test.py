from backend.services.flow_node_handlers import SendMessageHandler


def test_send_message_handler_sends_agent_audio_for_response_template(monkeypatch):
    sent = []

    def fake_send_audio(company_id, phone, audio_bytes=None, audio_path=None, db=None):
        sent.append(("audio", company_id, phone, audio_bytes))
        return {"id": "audio-1"}

    def fake_send_text(
        company_id,
        phone,
        message,
        db=None,
        human_mode=False,
        response_delay_seconds=0,
    ):
        sent.append(("text", company_id, phone, message))
        return {"id": "text-1"}

    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_audio",
        fake_send_audio,
    )
    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_text",
        fake_send_text,
    )

    variables = {
        "phone": "00000000007",
        "agent_workforce": {
            "response": "Resposta falada",
            "audio": b"audio-bytes",
            "should_send_audio": True,
        },
    }

    result = SendMessageHandler().execute(
        db=None,
        node_data={"messages": [{"type": "text", "content": "{{agent_workforce.response}}"}]},
        variables=variables,
        company_id=7,
        flow_id=2,
    )

    assert result["success"]
    assert sent == [("audio", 7, "5500000000007", b"audio-bytes")]
    assert variables["agent_workforce"]["audio"] is None
    assert variables["agent_workforce"]["audio_consumed"] is True


def test_send_message_handler_sends_intro_text_then_agent_audio(monkeypatch):
    sent = []

    def fake_send_audio(company_id, phone, audio_bytes=None, audio_path=None, db=None):
        sent.append(("audio", company_id, phone, audio_bytes))
        return {"id": "audio-1"}

    def fake_send_text(
        company_id,
        phone,
        message,
        db=None,
        human_mode=False,
        response_delay_seconds=0,
    ):
        sent.append(("text", company_id, phone, message, response_delay_seconds))
        return {"id": f"text-{len(sent)}"}

    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_audio",
        fake_send_audio,
    )
    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_text",
        fake_send_text,
    )

    variables = {
        "phone": "00000000007",
        "agent_workforce": {
            "response": "Intro. Conteudo longo em audio.",
            "audio": b"audio-bytes",
            "should_send_audio": True,
            "audio_delivery_mode": "text_then_audio_tail",
            "audio_text_intro": "Intro.",
            "audio_text": "Conteudo longo em audio.",
            "metadata": {"response_delay_seconds": 4},
        },
    }

    result = SendMessageHandler().execute(
        db=None,
        node_data={"messages": [{"type": "text", "content": "{{agent_workforce.response}}"}]},
        variables=variables,
        company_id=7,
        flow_id=2,
    )

    assert result["success"]
    assert sent == [
        ("text", 7, "5500000000007", "Intro.", 4),
        ("audio", 7, "5500000000007", b"audio-bytes"),
    ]
    assert result["results"][0]["audio_intro"] is True
    assert result["results"][1]["audio_delivery_mode"] == "text_then_audio_tail"
    assert variables["agent_workforce"]["audio"] is None
    assert variables["agent_workforce"]["audio_consumed"] is True


def test_send_message_handler_falls_back_to_text_when_agent_audio_fails(monkeypatch):
    sent = []

    def fake_send_audio(company_id, phone, audio_bytes=None, audio_path=None, db=None):
        raise RuntimeError("waha unavailable")

    def fake_send_text(
        company_id,
        phone,
        message,
        db=None,
        human_mode=False,
        response_delay_seconds=0,
    ):
        sent.append(("text", company_id, phone, message))
        return {"id": "text-1"}

    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_audio",
        fake_send_audio,
    )
    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_text",
        fake_send_text,
    )

    variables = {
        "phone": "00000000007",
        "agent_workforce": {
            "response": "Resposta em texto",
            "audio": b"audio-bytes",
            "should_send_audio": True,
        },
    }

    result = SendMessageHandler().execute(
        db=None,
        node_data={"messages": [{"type": "text", "content": "{{agent_workforce.response}}"}]},
        variables=variables,
        company_id=7,
        flow_id=2,
    )

    assert result["success"]
    assert sent == [("text", 7, "5500000000007", "Resposta em texto")]
    assert result["results"][0]["audio_fallback_error"] == "waha unavailable"
    assert variables["agent_workforce"]["audio"] is None


def test_send_message_handler_falls_back_to_audio_tail_after_intro(monkeypatch):
    sent = []

    def fake_send_audio(company_id, phone, audio_bytes=None, audio_path=None, db=None):
        raise RuntimeError("waha unavailable")

    def fake_send_text(
        company_id,
        phone,
        message,
        db=None,
        human_mode=False,
        response_delay_seconds=0,
    ):
        sent.append(("text", company_id, phone, message, response_delay_seconds))
        return {"id": f"text-{len(sent)}"}

    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_audio",
        fake_send_audio,
    )
    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_text",
        fake_send_text,
    )

    variables = {
        "phone": "00000000007",
        "agent_workforce": {
            "response": "Intro. Conteudo longo em audio.",
            "audio": b"audio-bytes",
            "should_send_audio": True,
            "audio_delivery_mode": "text_then_audio_tail",
            "audio_text_intro": "Intro.",
            "audio_text": "Conteudo longo em audio.",
            "metadata": {"response_delay_seconds": 4},
        },
    }

    result = SendMessageHandler().execute(
        db=None,
        node_data={"messages": [{"type": "text", "content": "{{agent_workforce.response}}"}]},
        variables=variables,
        company_id=7,
        flow_id=2,
    )

    assert result["success"]
    assert sent == [
        ("text", 7, "5500000000007", "Intro.", 4),
        ("text", 7, "5500000000007", "Conteudo longo em audio.", 0),
    ]
    assert result["results"][1]["audio_fallback_error"] == "waha unavailable"
    assert variables["agent_workforce"]["audio"] is None


def test_send_message_handler_does_not_send_unresolved_agent_response(monkeypatch):
    def fake_send_text(*args, **kwargs):
        raise AssertionError("send_text should not be called")

    monkeypatch.setattr(
        "backend.integrations.whatsapp_provider.send_text",
        fake_send_text,
    )

    result = SendMessageHandler().execute(
        db=None,
        node_data={"messages": [{"type": "text", "content": "{{agent_workforce.response}}"}]},
        variables={"phone": "00000000007"},
        company_id=7,
        flow_id=2,
    )

    assert not result["success"]
    assert result["messages_sent"] == 0
    assert result["results"][0]["error"] == "Agent response variable was not resolved"
