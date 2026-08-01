from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.services import agent_dynamic_followup_service as service
from backend.services.agent_dynamic_followup_service import (
    ENROLLMENT_ACTIVE,
    ENROLLMENT_COMPLETED,
    EXECUTION_CANCELED,
    _as_aware_utc,
    _lead_reached_target_stage,
    _normalize_dynamic_followup_settings,
    _scheduled_for_step,
    cancel_dynamic_followups_for_lead_appointment,
)


def test_normalize_dynamic_followup_settings_accepts_camel_and_snake_case():
    settings = _normalize_dynamic_followup_settings(
        {
            "pipelineId": "8",
            "targetStageIds": ["30", 31, None, "0"],
            "deliveryWindow": {
                "enabled": True,
                "timezone": "America/Sao_Paulo",
                "allowedWeekdays": [0, "4", 9],
                "startTime": "09:00",
                "endTime": "18:00",
            },
            "steps": [
                {
                    "stepNumber": 3,
                    "sendAfter": "2",
                    "sendAfterUnit": "days",
                    "objective": "Retomar conversa",
                    "miniPrompt": "Gere uma mensagem natural.",
                },
                {
                    "step_number": 1,
                    "send_after": 0,
                    "send_after_unit": "minutes",
                    "objective": "Responder no pico",
                    "mini_prompt": "Cumprimente e reconheca o cadastro.",
                },
                {
                    "step_number": 2,
                    "mini_prompt": "",
                },
            ],
        }
    )

    assert settings["pipeline_id"] == 8
    assert settings["target_stage_ids"] == [30, 31]
    assert settings["stop_on_appointment_created"] is True
    assert settings["delivery_window"] == {
        "enabled": True,
        "timezone": "America/Sao_Paulo",
        "allowed_weekdays": [0, 4],
        "start_time": "09:00",
        "end_time": "18:00",
    }
    assert [step["step_number"] for step in settings["steps"]] == [1, 2]
    assert settings["steps"][0]["send_after"] == 0
    assert settings["steps"][0]["send_after_unit"] == "minutes"
    assert settings["steps"][1]["send_after"] == 2
    assert settings["steps"][1]["send_after_unit"] == "days"


def test_normalize_dynamic_followup_settings_accepts_stop_on_appointment_toggle():
    settings = _normalize_dynamic_followup_settings(
        {
            "stopOnAppointmentCreated": False,
            "steps": [{"miniPrompt": "Mensagem"}],
        }
    )

    assert settings["stop_on_appointment_created"] is False


def test_scheduled_for_step_uses_anchor_for_future_first_step():
    anchor = datetime.now(timezone.utc) + timedelta(days=2)
    scheduled_for = _scheduled_for_step(
        anchor,
        {
            "send_after": 3,
            "send_after_unit": "hours",
        },
    )

    assert scheduled_for >= anchor + timedelta(hours=3) - timedelta(seconds=1)


def test_scheduled_for_step_moves_to_delivery_window_start():
    scheduled_for = _scheduled_for_step(
        datetime(2030, 1, 7, 6, 0, tzinfo=timezone.utc),
        {
            "send_after": 0,
            "send_after_unit": "minutes",
        },
        {
            "delivery_window": {
                "enabled": True,
                "timezone": "America/Sao_Paulo",
                "allowed_weekdays": [0, 1, 2, 3, 4],
                "start_time": "09:00",
                "end_time": "18:00",
            }
        },
    )

    assert scheduled_for == datetime(2030, 1, 7, 12, 0, tzinfo=timezone.utc)


def test_scheduled_for_step_moves_after_weekend_when_outside_window():
    scheduled_for = _scheduled_for_step(
        datetime(2030, 1, 11, 22, 0, tzinfo=timezone.utc),
        {
            "send_after": 0,
            "send_after_unit": "minutes",
        },
        {
            "delivery_window": {
                "enabled": True,
                "timezone": "America/Sao_Paulo",
                "allowed_weekdays": [0, 1, 2, 3, 4],
                "start_time": "09:00",
                "end_time": "18:00",
            }
        },
    )

    assert scheduled_for == datetime(2030, 1, 14, 12, 0, tzinfo=timezone.utc)


def test_as_aware_utc_accepts_sql_datetime_strings():
    naive_value = _as_aware_utc("2026-06-07 02:30:15")
    aware_value = _as_aware_utc("2026-06-07 02:30:15.732757+00")
    zulu_value = _as_aware_utc("2026-06-07T02:30:15Z")

    assert naive_value.tzinfo is not None
    assert aware_value.tzinfo is not None
    assert zulu_value.tzinfo is not None
    assert naive_value.hour == 2
    assert aware_value.minute == 30
    assert zulu_value.year == 2026


def test_lead_reached_target_stage_matches_current_stage():
    lead = SimpleNamespace(current_stage_id=44)

    assert _lead_reached_target_stage(lead, [12, 44]) is True
    assert _lead_reached_target_stage(lead, [12, 45]) is False


def test_cancel_dynamic_followups_for_lead_appointment_completes_active_enrollment():
    lead = SimpleNamespace(id=10, company_id=3)
    enrollment = SimpleNamespace(
        id=99,
        company_id=3,
        lead_id=10,
        status=ENROLLMENT_ACTIVE,
        config_snapshot={
            "tool_settings": {
                "stop_on_appointment_created": True,
            }
        },
    )
    enrollment_query = MagicMock()
    enrollment_query.filter.return_value = enrollment_query
    enrollment_query.all.return_value = [enrollment]
    execution_query = MagicMock()
    execution_query.filter.return_value = execution_query
    db = MagicMock()
    db.query.side_effect = [enrollment_query, execution_query]

    cancelled = cancel_dynamic_followups_for_lead_appointment(
        db,
        lead=lead,
        reason="appointment_created:appointment_active",
    )

    assert cancelled == 1
    assert enrollment.status == ENROLLMENT_COMPLETED
    assert enrollment.cancel_reason == "appointment_created:appointment_active"
    execution_query.update.assert_called_once()
    update_values = execution_query.update.call_args.args[0]
    assert EXECUTION_CANCELED in update_values.values()
    db.commit.assert_called_once()


def test_cancel_dynamic_followups_for_lead_appointment_respects_disabled_setting():
    lead = SimpleNamespace(id=10, company_id=3)
    enrollment = SimpleNamespace(
        id=99,
        company_id=3,
        lead_id=10,
        status=ENROLLMENT_ACTIVE,
        config_snapshot={
            "tool_settings": {
                "stop_on_appointment_created": False,
            }
        },
    )
    enrollment_query = MagicMock()
    enrollment_query.filter.return_value = enrollment_query
    enrollment_query.all.return_value = [enrollment]
    db = MagicMock()
    db.query.return_value = enrollment_query

    cancelled = cancel_dynamic_followups_for_lead_appointment(
        db,
        lead=lead,
        reason="appointment_created:appointment_active",
    )

    assert cancelled == 0
    assert enrollment.status == ENROLLMENT_ACTIVE
    db.commit.assert_not_called()


def test_dynamic_followup_uses_company_scoped_run_config(monkeypatch):
    db = MagicMock()
    enrollment = SimpleNamespace(
        id=81,
        company_id=22,
        workforce_id=13,
        agent_key="consultor",
        lead_id=44,
        config_snapshot={
            "agent": {
                "name": "Consultor",
                "role": "Vendas",
                "model": "gpt-5.4-mini",
            }
        },
    )
    execution = SimpleNamespace(
        id=91,
        agent_key="consultor",
        step_number=2,
    )
    lead = SimpleNamespace(phone="5500000000007")
    company_run_config = object()
    captured = {}

    monkeypatch.setattr(
        service,
        "_build_generation_payload",
        lambda *_args, **_kwargs: {"lead": {"phone": lead.phone}},
    )
    monkeypatch.setattr(
        service,
        "build_company_openai_run_config",
        lambda fake_db, company_id, tracing_disabled, model_override: (
            company_run_config
            if (
                fake_db is db
                and company_id == 22
                and tracing_disabled is True
                and model_override is None
            )
            else None
        ),
    )

    async def fake_run_generation_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            final_output="Podemos retomar por aqui?",
            context_wrapper=SimpleNamespace(usage=None),
        )

    monkeypatch.setattr(
        service,
        "_run_generation_agent",
        fake_run_generation_agent,
    )

    message, payload, usage, model = service._generate_dynamic_followup_message(
        db,
        enrollment=enrollment,
        execution=execution,
        lead=lead,
    )

    assert message == "Podemos retomar por aqui?"
    assert payload == {"lead": {"phone": lead.phone}}
    assert usage is None
    assert model == "gpt-5.4-mini"
    assert captured["run_config"] is company_run_config
