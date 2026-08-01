"""
Generic lead scheduling tools for frontend-created agents.

These tools intentionally use product-neutral language: lead, agenda, workspace.
They are registered by backend ID and attached only to agents that selected the
Scheduling capability in the agent builder.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents import RunContextWrapper, function_tool
from pydantic import Field
from sqlalchemy import and_, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/Sao_Paulo"
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y")
DATETIME_FORMATS = ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M")
PERIOD_LIMITS = {
    "manha": (0, 12 * 60),
    "manhã": (0, 12 * 60),
    "tarde": (12 * 60, 18 * 60),
    "noite": (18 * 60, 24 * 60),
}
CALENDAR_SCHEDULING_ACTIONS = {
    "find_slots",
    "create_appointment",
    "reschedule_appointment",
    "cancel_appointment",
}


def create_calendar_scheduling_tools(
    *,
    company_id: int,
    configured_agenda_id: Optional[int] = None,
    require_confirmation: bool = True,
    allowed_actions: Optional[List[str]] = None,
    max_suggestions: int = 3,
    create_google_meet: bool = False,
) -> List[Any]:
    """Create OpenAI Agents SDK tools scoped to a workspace."""

    suggestion_limit = _bounded_int(max_suggestions, default=3, minimum=1, maximum=6)
    action_set = {
        str(action).strip()
        for action in (allowed_actions or ["find_slots", "create_appointment"])
        if str(action).strip() in CALENDAR_SCHEDULING_ACTIONS
    }
    if not action_set:
        action_set = {"find_slots"}

    @function_tool
    async def find_available_lead_slots(
        context: RunContextWrapper,
        agenda_id: Annotated[Optional[int], Field(description="ID da agenda da plataforma a consultar. Opcional quando houver apenas uma agenda ativa.")] = None,
        agenda_name: Annotated[str, Field(description="Nome aproximado da agenda, quando o agente conhece o nome mas não o ID.")] = "",
        date_from: Annotated[str, Field(description="Data inicial em YYYY-MM-DD ou DD/MM/YYYY. Vazio usa hoje.")] = "",
        date_to: Annotated[str, Field(description="Data final em YYYY-MM-DD ou DD/MM/YYYY. Vazio usa 14 dias após a data inicial.")] = "",
        preferred_period: Annotated[str, Field(description="Período opcional: manha, tarde ou noite.")] = "",
        limit: Annotated[int, Field(description="Quantidade máxima de horários para retornar.", ge=1, le=30)] = 12,
    ) -> Dict[str, Any]:
        """
        Consulta horários disponíveis para agendar um lead.

        Use quando o lead pedir disponibilidade, perguntar "qual tem?",
        sugerir data/horário ou antes de criar um agendamento. A resposta
        retorna horários reais da agenda, respeitando janelas de atendimento,
        margem de segurança e conflitos. Nunca diga que não há horários sem
        consultar esta ferramenta.
        """

        _ = context
        from backend.db import get_db

        db = next(get_db())
        try:
            agenda_result = _resolve_agenda(
                db=db,
                company_id=company_id,
                agenda_id=agenda_id or configured_agenda_id,
                agenda_name=agenda_name,
            )
            if not agenda_result["success"]:
                return agenda_result

            agenda: Agenda = agenda_result["agenda"]
            tz = _safe_timezone(agenda.timezone)
            start_date = _parse_date(date_from, datetime.now(tz).date())
            end_date = _parse_date(date_to, start_date + timedelta(days=14))
            if end_date < start_date:
                return {
                    "success": False,
                    "error": "date_range_invalid",
                    "message_for_agent": "A data final precisa ser igual ou posterior à data inicial.",
                }

            end_date = min(end_date, start_date + timedelta(days=31))
            slots = _build_available_slots(
                db=db,
                agenda=agenda,
                start_date=start_date,
                end_date=end_date,
                preferred_period=preferred_period,
                limit=limit,
            )
            next_available_slots = []
            if not slots:
                next_available_slots = _build_available_slots(
                    db=db,
                    agenda=agenda,
                    start_date=end_date + timedelta(days=1),
                    end_date=end_date + timedelta(days=21),
                    preferred_period=preferred_period,
                    limit=min(limit, suggestion_limit),
                )
            now = datetime.now(tz)
            earliest_bookable = now + timedelta(minutes=agenda.safety_margin_minutes or 0)

            return {
                "success": True,
                "agenda": _agenda_payload(agenda),
                "date_from": start_date.isoformat(),
                "date_to": end_date.isoformat(),
                "timezone": agenda.timezone or DEFAULT_TIMEZONE,
                "current_datetime": now.isoformat(),
                "current_date": now.date().isoformat(),
                "current_time": now.strftime("%H:%M"),
                "current_weekday": now.strftime("%A"),
                "earliest_bookable_time": earliest_bookable.isoformat(),
                "max_suggestions": suggestion_limit,
                "requested_range_has_slots": bool(slots),
                "slots": slots,
                "next_available_slots": next_available_slots,
                "message_for_agent": (
                    f"Apresente no máximo {suggestion_limit} opções por vez e peça o lead para escolher uma."
                    if slots
                    else (
                        f"Não há horários no período pedido. Ofereça até {suggestion_limit} opções de next_available_slots e explique que são as próximas opções disponíveis."
                        if next_available_slots
                        else "Não há horários disponíveis nesse período; ofereça consultar outro período."
                    )
                ),
            }
        except Exception as exc:
            logger.exception("[CalendarSchedulingTool] find_available_lead_slots failed")
            return {
                "success": False,
                "error": "internal_error",
                "message_for_agent": "Não foi possível consultar a agenda agora.",
                "details": str(exc),
            }
        finally:
            db.close()

    @function_tool
    async def create_lead_appointment(
        context: RunContextWrapper,
        selected_start_time: Annotated[str, Field(description="Horário escolhido em ISO, YYYY-MM-DD HH:MM ou DD/MM/YYYY HH:MM.")],
        lead_name: Annotated[str, Field(description="Nome do lead confirmado na conversa.")],
        lead_phone: Annotated[str, Field(description="Telefone do lead. Vazio usa o telefone do contexto da conversa.")] = "",
        agenda_id: Annotated[Optional[int], Field(description="ID da agenda da plataforma. Opcional quando houver agenda configurada ou apenas uma agenda ativa.")] = None,
        agenda_name: Annotated[str, Field(description="Nome aproximado da agenda, se não houver ID.")] = "",
        lead_id: Annotated[Optional[int], Field(description="ID do lead existente, se já conhecido.")] = None,
        interest: Annotated[str, Field(description="Interesse, serviço ou motivo do agendamento.")] = "",
        notes: Annotated[str, Field(description="Observações relevantes para a equipe.")] = "",
        confirmed_by_lead: Annotated[bool, Field(description="True somente quando o lead confirmou explicitamente o horário.")] = False,
    ) -> Dict[str, Any]:
        """
        Cria agendamento para um lead em uma agenda da plataforma.

        Só use depois que o lead escolher um horário específico. Se a ferramenta
        exigir confirmação, chame com confirmed_by_lead=true apenas após o lead
        confirmar claramente que deseja aquele horário.
        """

        from backend.db import get_db

        db = next(get_db())
        try:
            if require_confirmation and not confirmed_by_lead:
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "message_for_agent": "Confirme explicitamente o dia e horário com o lead antes de criar o agendamento.",
                }

            agenda_result = _resolve_agenda(
                db=db,
                company_id=company_id,
                agenda_id=agenda_id or configured_agenda_id,
                agenda_name=agenda_name,
            )
            if not agenda_result["success"]:
                return agenda_result

            agenda: Agenda = agenda_result["agenda"]
            starts_at = _parse_datetime(selected_start_time, agenda.timezone)
            ends_at = starts_at + timedelta(minutes=agenda.slot_duration or 30)
            availability = _validate_slot_availability(
                db=db,
                agenda=agenda,
                starts_at=starts_at,
                ends_at=ends_at,
            )
            if not availability["success"]:
                return availability

            runtime_context = getattr(context, "context", None)
            context_phone = getattr(runtime_context, "contact_phone", None)
            context_name = getattr(runtime_context, "contact_name", None)
            lead = _get_or_create_lead(
                db=db,
                company_id=company_id,
                lead_id=lead_id,
                lead_name=lead_name or context_name or "Lead",
                lead_phone=lead_phone or context_phone or "",
            )
            if not lead["success"]:
                return lead

            db_lead: Lead = lead["lead"]
            from backend.models import Agendamento

            appointment = Agendamento(
                client_id=db_lead.client_id,
                company_id=company_id,
                lead_id=db_lead.id,
                nome=lead_name or db_lead.name,
                phone=_normalize_phone(lead_phone or db_lead.phone or context_phone or ""),
                consulta_data=starts_at,
                midia="Agente IA",
                interesse=interest or notes or "Agendamento via agente",
                status="SCHEDULED",
                agenda_id=agenda.id,
            )
            db.add(appointment)
            db.commit()
            db.refresh(appointment)

            google_sync_status = _sync_google_calendar_if_available(
                db,
                appointment,
                starts_at,
                create_google_meet=create_google_meet,
            )
            db.refresh(appointment)
            confirmation_status = _dispatch_confirmation_task_if_configured(
                db=db,
                company_id=company_id,
                appointment=appointment,
            )
            dynamic_followup_status = _cancel_dynamic_followup_for_appointment_if_present(
                db=db,
                appointment=appointment,
                event_name="appointment_created",
            )
            appointment_display = _format_datetime_for_lead(starts_at, agenda.timezone)
            relative_day = _relative_day_label(starts_at, agenda.timezone)
            meeting_link = (
                appointment.local_link
                if create_google_meet and appointment.local_link and appointment.event_id
                else None
            )

            return {
                "success": True,
                "status": "scheduled",
                "appointment_id": appointment.id,
                "appointment": _appointment_payload(appointment, agenda.timezone),
                "agenda": _agenda_payload(agenda),
                "lead": {
                    "id": db_lead.id,
                    "name": db_lead.name,
                    "phone": db_lead.phone,
                },
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "timezone": agenda.timezone or DEFAULT_TIMEZONE,
                "appointment_display": appointment_display,
                "relative_day": relative_day,
                "meeting_link": meeting_link,
                "local_link": appointment.local_link,
                "google_sync_status": google_sync_status,
                "confirmation_status": confirmation_status,
                "dynamic_followup_status": dynamic_followup_status,
                "message_for_agent": (
                    f"Confirme usando a data/hora exata `{appointment_display}`. "
                    "Não troque por 'hoje', 'amanhã' ou outro termo relativo se ele não combinar com `relative_day` e com a data local atual da agenda."
                    + (
                        f" Envie também este link de reunião ao lead: {meeting_link}."
                        if meeting_link
                        else " Não prometa link de reunião se `meeting_link` vier vazio."
                    )
                ),
                "message_for_lead": (
                    f"Perfeito, ficou agendado para {appointment_display}. Link da reunião: {meeting_link}"
                    if meeting_link
                    else f"Perfeito, ficou agendado para {appointment_display}."
                ),
            }
        except Exception as exc:
            db.rollback()
            logger.exception("[CalendarSchedulingTool] create_lead_appointment failed")
            return {
                "success": False,
                "error": "internal_error",
                "message_for_agent": "Não foi possível criar o agendamento agora.",
                "details": str(exc),
            }
        finally:
            db.close()

    @function_tool
    async def reschedule_lead_appointment(
        context: RunContextWrapper,
        new_start_time: Annotated[str, Field(description="Novo horário escolhido em ISO, YYYY-MM-DD HH:MM ou DD/MM/YYYY HH:MM.")],
        appointment_id: Annotated[Optional[int], Field(description="ID do agendamento existente, quando conhecido.")] = None,
        lead_phone: Annotated[str, Field(description="Telefone do lead. Vazio usa o telefone do contexto da conversa.")] = "",
        lead_id: Annotated[Optional[int], Field(description="ID do lead existente, se já conhecido.")] = None,
        current_start_time: Annotated[str, Field(description="Horário atual do agendamento, se o ID não for conhecido.")] = "",
        agenda_id: Annotated[Optional[int], Field(description="ID da agenda da plataforma para o novo horário. Opcional quando a tool já tiver agenda fixa.")] = None,
        agenda_name: Annotated[str, Field(description="Nome aproximado da agenda para o novo horário.")] = "",
        reason: Annotated[str, Field(description="Motivo informado pelo lead para o reagendamento.")] = "",
        confirmed_by_lead: Annotated[bool, Field(description="True somente quando o lead confirmou explicitamente o novo horário.")] = False,
    ) -> Dict[str, Any]:
        """
        Reagenda um agendamento futuro de lead.

        Use quando o lead pedir para trocar dia ou horário. Consulte horários
        disponíveis antes e confirme o novo horário antes de alterar.
        """

        from backend.db import get_db

        db = next(get_db())
        try:
            if require_confirmation and not confirmed_by_lead:
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "message_for_agent": "Confirme explicitamente o novo dia e horário com o lead antes de reagendar.",
                }

            runtime_context = getattr(context, "context", None)
            context_phone = getattr(runtime_context, "contact_phone", None)
            appointment_result = _resolve_appointment(
                db=db,
                company_id=company_id,
                appointment_id=appointment_id,
                lead_id=lead_id,
                lead_phone=lead_phone or context_phone or "",
                current_start_time=current_start_time,
                agenda_id=agenda_id or configured_agenda_id,
            )
            if not appointment_result["success"]:
                return appointment_result

            appointment: Agendamento = appointment_result["appointment"]
            if (
                configured_agenda_id
                and appointment.agenda_id
                and int(appointment.agenda_id) != int(configured_agenda_id)
            ):
                return {
                    "success": False,
                    "error": "agenda_mismatch",
                    "message_for_agent": "Esse agendamento pertence a outra agenda. Use a agenda correta antes de reagendar.",
                }

            agenda_result = _resolve_agenda(
                db=db,
                company_id=company_id,
                agenda_id=agenda_id or configured_agenda_id or appointment.agenda_id,
                agenda_name=agenda_name,
            )
            if not agenda_result["success"]:
                return agenda_result

            agenda: Agenda = agenda_result["agenda"]
            starts_at = _parse_datetime(new_start_time, agenda.timezone)
            ends_at = starts_at + timedelta(minutes=agenda.slot_duration or 30)
            availability = _validate_slot_availability(
                db=db,
                agenda=agenda,
                starts_at=starts_at,
                ends_at=ends_at,
                exclude_appointment_id=appointment.id,
            )
            if not availability["success"]:
                return availability

            previous_start = appointment.consulta_data
            appointment.consulta_data = starts_at
            appointment.agenda_id = agenda.id
            appointment.status = "SCHEDULED"
            if reason:
                appointment.interesse = _append_appointment_note(
                    appointment.interesse,
                    f"Reagendamento via agente: {reason}",
                )
            db.commit()
            db.refresh(appointment)

            google_sync_status = _sync_google_calendar_if_available(
                db,
                appointment,
                starts_at,
                is_rescheduling=True,
                create_google_meet=create_google_meet,
            )
            db.refresh(appointment)
            confirmation_status = _dispatch_confirmation_task_if_configured(
                db=db,
                company_id=company_id,
                appointment=appointment,
            )
            dynamic_followup_status = _cancel_dynamic_followup_for_appointment_if_present(
                db=db,
                appointment=appointment,
                event_name="appointment_rescheduled",
            )
            appointment_display = _format_datetime_for_lead(starts_at, agenda.timezone)
            relative_day = _relative_day_label(starts_at, agenda.timezone)
            meeting_link = (
                appointment.local_link
                if create_google_meet and appointment.local_link and appointment.event_id
                else None
            )

            return {
                "success": True,
                "status": "rescheduled",
                "appointment_id": appointment.id,
                "agenda": _agenda_payload(agenda),
                "previous_start_time": previous_start.isoformat()
                if previous_start
                else None,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "timezone": agenda.timezone or DEFAULT_TIMEZONE,
                "appointment_display": appointment_display,
                "relative_day": relative_day,
                "meeting_link": meeting_link,
                "local_link": appointment.local_link,
                "google_sync_status": google_sync_status,
                "confirmation_status": confirmation_status,
                "dynamic_followup_status": dynamic_followup_status,
                "message_for_agent": (
                    f"Confirme o reagendamento usando a data/hora exata `{appointment_display}`. "
                    "Não troque por 'hoje', 'amanhã' ou outro termo relativo se ele não combinar com `relative_day` e com a data local atual da agenda."
                    + (
                        f" Envie também este link de reunião ao lead: {meeting_link}."
                        if meeting_link
                        else " Não prometa link de reunião se `meeting_link` vier vazio."
                    )
                ),
                "message_for_lead": (
                    f"Perfeito, reagendei para {appointment_display}. Link da reunião: {meeting_link}"
                    if meeting_link
                    else f"Perfeito, reagendei para {appointment_display}."
                ),
            }
        except Exception as exc:
            db.rollback()
            logger.exception("[CalendarSchedulingTool] reschedule_lead_appointment failed")
            return {
                "success": False,
                "error": "internal_error",
                "message_for_agent": "Não foi possível reagendar agora.",
                "details": str(exc),
            }
        finally:
            db.close()

    @function_tool
    async def cancel_lead_appointment(
        context: RunContextWrapper,
        appointment_id: Annotated[Optional[int], Field(description="ID do agendamento existente, quando conhecido.")] = None,
        lead_phone: Annotated[str, Field(description="Telefone do lead. Vazio usa o telefone do contexto da conversa.")] = "",
        lead_id: Annotated[Optional[int], Field(description="ID do lead existente, se já conhecido.")] = None,
        current_start_time: Annotated[str, Field(description="Horário atual do agendamento, se o ID não for conhecido.")] = "",
        agenda_id: Annotated[Optional[int], Field(description="ID da agenda da plataforma. Opcional quando a tool já tiver agenda fixa.")] = None,
        reason: Annotated[str, Field(description="Motivo informado pelo lead para o cancelamento.")] = "",
        confirmed_by_lead: Annotated[bool, Field(description="True somente quando o lead confirmou explicitamente o cancelamento.")] = False,
    ) -> Dict[str, Any]:
        """
        Cancela um agendamento futuro de lead.

        Use quando o lead confirmar que deseja cancelar ou excluir o horário.
        Quando a tool exigir confirmação, não cancele sem confirmação explícita.
        """

        from backend.db import get_db

        db = next(get_db())
        try:
            if require_confirmation and not confirmed_by_lead:
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "message_for_agent": "Confirme explicitamente com o lead antes de cancelar o agendamento.",
                }

            runtime_context = getattr(context, "context", None)
            context_phone = getattr(runtime_context, "contact_phone", None)
            appointment_result = _resolve_appointment(
                db=db,
                company_id=company_id,
                appointment_id=appointment_id,
                lead_id=lead_id,
                lead_phone=lead_phone or context_phone or "",
                current_start_time=current_start_time,
                agenda_id=agenda_id or configured_agenda_id,
            )
            if not appointment_result["success"]:
                return appointment_result

            appointment: Agendamento = appointment_result["appointment"]
            if (
                configured_agenda_id
                and appointment.agenda_id
                and int(appointment.agenda_id) != int(configured_agenda_id)
            ):
                return {
                    "success": False,
                    "error": "agenda_mismatch",
                    "message_for_agent": "Esse agendamento pertence a outra agenda. Use a agenda correta antes de cancelar.",
                }

            starts_at = appointment.consulta_data
            confirmation_status = _cancel_confirmation_tasks_if_present(db, appointment.id)
            google_sync_status = _cancel_google_calendar_event_if_available(db, appointment)
            appointment.status = "CANCELLED"
            if reason:
                appointment.interesse = _append_appointment_note(
                    appointment.interesse,
                    f"Cancelamento via agente: {reason}",
                )
            db.commit()
            db.refresh(appointment)

            return {
                "success": True,
                "status": "cancelled",
                "appointment": _appointment_payload(appointment),
                "starts_at": starts_at.isoformat() if starts_at else None,
                "google_sync_status": google_sync_status,
                "confirmation_status": confirmation_status,
                "message_for_lead": "Tudo certo, o agendamento foi cancelado.",
            }
        except Exception as exc:
            db.rollback()
            logger.exception("[CalendarSchedulingTool] cancel_lead_appointment failed")
            return {
                "success": False,
                "error": "internal_error",
                "message_for_agent": "Não foi possível cancelar o agendamento agora.",
                "details": str(exc),
            }
        finally:
            db.close()

    tools: List[Any] = []
    if "find_slots" in action_set:
        tools.append(find_available_lead_slots)
    if "create_appointment" in action_set:
        tools.append(create_lead_appointment)
    if "reschedule_appointment" in action_set:
        tools.append(reschedule_lead_appointment)
    if "cancel_appointment" in action_set:
        tools.append(cancel_lead_appointment)
    return tools


def _safe_timezone(timezone_name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def _agenda_payload(agenda: Agenda) -> Dict[str, Any]:
    return {
        "id": agenda.id,
        "name": agenda.name,
        "slot_duration": agenda.slot_duration,
        "timezone": agenda.timezone,
    }


def _appointment_payload(
    appointment: Agendamento,
    timezone_name: Optional[str] = None,
) -> Dict[str, Any]:
    starts_at = appointment.consulta_data
    return {
        "id": appointment.id,
        "lead_id": appointment.lead_id,
        "agenda_id": appointment.agenda_id,
        "name": appointment.nome,
        "phone": appointment.phone,
        "status": appointment.status,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "local_link": appointment.local_link,
        "meeting_link": appointment.local_link,
        "display": _format_datetime_for_lead(starts_at, timezone_name)
        if starts_at
        else None,
    }


def _relative_day_label(value: datetime, timezone_name: Optional[str]) -> Optional[str]:
    tz = _safe_timezone(timezone_name)
    local_value = value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
    local_date = local_value.date()
    today = datetime.now(tz).date()
    delta_days = (local_date - today).days

    if delta_days == 0:
        return "hoje"
    if delta_days == 1:
        return "amanhã"
    if delta_days == 2:
        return "depois de amanhã"
    return None


def _resolve_agenda(
    *,
    db: Session,
    company_id: int,
    agenda_id: Optional[int],
    agenda_name: str = "",
) -> Dict[str, Any]:
    from backend.models import Agenda

    query = db.query(Agenda).filter(Agenda.company_id == company_id, Agenda.active.is_(True))
    agendas = query.order_by(Agenda.name.asc()).all()

    if not agendas:
        return {
            "success": False,
            "error": "no_active_agendas",
            "message_for_agent": "Não há agenda ativa configurada para este workspace.",
        }

    if agenda_id:
        agenda = next((item for item in agendas if int(item.id) == int(agenda_id)), None)
        if agenda:
            return {"success": True, "agenda": agenda}
        return {
            "success": False,
            "error": "agenda_not_found",
            "message_for_agent": "A agenda informada não existe ou não está ativa neste workspace.",
            "available_agendas": [_agenda_payload(item) for item in agendas],
        }

    normalized_name = agenda_name.strip().lower()
    if normalized_name:
        matches = [item for item in agendas if normalized_name in item.name.lower()]
        if len(matches) == 1:
            return {"success": True, "agenda": matches[0]}
        if len(matches) > 1:
            return {
                "success": False,
                "error": "agenda_name_ambiguous",
                "message_for_agent": "Mais de uma agenda combina com esse nome. Peça o lead ou o usuário para escolher a agenda correta.",
                "available_agendas": [_agenda_payload(item) for item in matches],
            }

    if len(agendas) == 1:
        return {"success": True, "agenda": agendas[0]}

    return {
        "success": False,
        "error": "agenda_required",
        "message_for_agent": "Escolha qual agenda usar antes de consultar ou criar agendamentos.",
        "available_agendas": [_agenda_payload(item) for item in agendas],
    }


def _resolve_appointment(
    *,
    db: Session,
    company_id: int,
    appointment_id: Optional[int],
    lead_id: Optional[int],
    lead_phone: str,
    current_start_time: str,
    agenda_id: Optional[int],
) -> Dict[str, Any]:
    from backend.models import Agendamento

    if not any([appointment_id, lead_id, lead_phone, current_start_time]):
        return {
            "success": False,
            "error": "appointment_identifier_required",
            "message_for_agent": "Informe o ID do agendamento, telefone do lead ou horário atual para localizar o agendamento.",
        }

    query = db.query(Agendamento).filter(
        Agendamento.company_id == company_id,
        Agendamento.consulta_data.isnot(None),
        ~Agendamento.status.ilike("CANCELLED%"),
        ~Agendamento.status.ilike("CANCELED%"),
        Agendamento.consulta_data >= datetime.now(_safe_timezone(DEFAULT_TIMEZONE)),
    )

    if appointment_id:
        query = query.filter(Agendamento.id == appointment_id)
    if lead_id:
        query = query.filter(Agendamento.lead_id == lead_id)

    normalized_phone = _normalize_phone(lead_phone)
    if normalized_phone:
        query = query.filter(Agendamento.phone == normalized_phone)

    if agenda_id:
        query = query.filter(Agendamento.agenda_id == agenda_id)

    if current_start_time:
        parsed_start = _parse_datetime(current_start_time, DEFAULT_TIMEZONE)
        query = query.filter(
            Agendamento.consulta_data >= parsed_start - timedelta(minutes=1),
            Agendamento.consulta_data <= parsed_start + timedelta(minutes=1),
        )

    appointments = query.order_by(Agendamento.consulta_data.asc()).limit(5).all()
    if not appointments:
        return {
            "success": False,
            "error": "appointment_not_found",
            "message_for_agent": "Não encontrei um agendamento futuro correspondente para esse lead.",
        }

    has_precise_identifier = bool(appointment_id or current_start_time)
    if len(appointments) > 1 and not has_precise_identifier:
        return {
            "success": False,
            "error": "appointment_ambiguous",
            "message_for_agent": "Há mais de um agendamento futuro para esse lead. Confirme qual horário deve ser alterado.",
            "appointments": [_appointment_payload(item) for item in appointments],
        }

    return {"success": True, "appointment": appointments[0]}


def _parse_date(raw_value: str, fallback: date) -> date:
    value = (raw_value or "").strip()
    if not value:
        return fallback
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return fallback


def _parse_datetime(raw_value: str, timezone_name: Optional[str]) -> datetime:
    value = (raw_value or "").strip()
    tz = _safe_timezone(timezone_name)
    if not value:
        raise ValueError("selected_start_time is required")

    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=tz)
        except ValueError:
            continue

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _time_to_minutes(value: Any) -> Optional[int]:
    if value is None:
        return None
    return int(value.hour) * 60 + int(value.minute)


def _minutes_to_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _schedule_windows(schedule: Optional[AgendaSchedule]) -> List[tuple[int, int]]:
    if not schedule:
        return []

    windows = []
    for start_value, end_value in (
        (schedule.morning_start, schedule.morning_end),
        (schedule.afternoon_start, schedule.afternoon_end),
        (schedule.night_start, schedule.night_end),
    ):
        start = _time_to_minutes(start_value)
        end = _time_to_minutes(end_value)
        if start is not None and end is not None and end > start:
            windows.append((start, end))
    return windows


def _period_filter(preferred_period: str) -> Optional[tuple[int, int]]:
    value = (preferred_period or "").strip().lower()
    return PERIOD_LIMITS.get(value)


def _slot_inside_windows(
    *,
    start_minutes: int,
    duration: int,
    windows: List[tuple[int, int]],
    preferred_period: str = "",
) -> bool:
    end_minutes = start_minutes + duration
    period = _period_filter(preferred_period)
    if period and not (start_minutes >= period[0] and end_minutes <= period[1]):
        return False
    return any(start_minutes >= start and end_minutes <= end for start, end in windows)


def _has_conflict(
    *,
    db: Session,
    agenda: Agenda,
    starts_at: datetime,
    ends_at: datetime,
    exclude_appointment_id: Optional[int] = None,
) -> bool:
    from backend.models import Agendamento

    query = (
        db.query(Agendamento.id)
        .filter(
            Agendamento.company_id == agenda.company_id,
            Agendamento.agenda_id == agenda.id,
            Agendamento.consulta_data >= starts_at,
            Agendamento.consulta_data < ends_at,
            ~Agendamento.status.ilike("CANCELLED%"),
            ~Agendamento.status.ilike("CANCELED%"),
        )
    )
    if exclude_appointment_id:
        query = query.filter(Agendamento.id != exclude_appointment_id)
    return query.first() is not None


def _validate_slot_availability(
    *,
    db: Session,
    agenda: Agenda,
    starts_at: datetime,
    ends_at: datetime,
    exclude_appointment_id: Optional[int] = None,
) -> Dict[str, Any]:
    if not agenda.active:
        return {
            "success": False,
            "error": "agenda_inactive",
            "message_for_agent": "Essa agenda está inativa.",
        }

    tz = _safe_timezone(agenda.timezone)
    local_start = starts_at.astimezone(tz)
    local_end = ends_at.astimezone(tz)
    earliest = datetime.now(tz) + timedelta(minutes=agenda.safety_margin_minutes or 0)

    if local_start < earliest:
        return {
            "success": False,
            "error": "slot_too_soon_or_past",
            "message_for_agent": "Esse horário já passou ou não respeita a margem de segurança da agenda.",
        }

    schedule = next(
        (item for item in agenda.schedules if item.day_of_week == local_start.weekday()),
        None,
    )
    start_minutes = local_start.hour * 60 + local_start.minute
    duration = int((local_end - local_start).total_seconds() // 60)
    if not _slot_inside_windows(
        start_minutes=start_minutes,
        duration=duration,
        windows=_schedule_windows(schedule),
    ):
        return {
            "success": False,
            "error": "outside_business_hours",
            "message_for_agent": "Esse horário está fora da janela de atendimento configurada para a agenda.",
        }

    if _has_conflict(
        db=db,
        agenda=agenda,
        starts_at=starts_at,
        ends_at=ends_at,
        exclude_appointment_id=exclude_appointment_id,
    ):
        return {
            "success": False,
            "error": "slot_unavailable",
            "message_for_agent": "Esse horário acabou de ficar indisponível. Consulte novos horários antes de responder.",
        }

    return {"success": True}


def _build_available_slots(
    *,
    db: Session,
    agenda: Agenda,
    start_date: date,
    end_date: date,
    preferred_period: str,
    limit: int,
) -> List[Dict[str, Any]]:
    tz = _safe_timezone(agenda.timezone)
    earliest = datetime.now(tz) + timedelta(minutes=agenda.safety_margin_minutes or 0)
    schedules = {schedule.day_of_week: schedule for schedule in agenda.schedules}
    slots: List[Dict[str, Any]] = []
    duration = agenda.slot_duration or 30

    current_day = start_date
    while current_day <= end_date and len(slots) < limit:
        schedule = schedules.get(current_day.weekday())
        windows = _schedule_windows(schedule)
        for start_window, end_window in windows:
            slot_start_minutes = start_window
            while slot_start_minutes + duration <= end_window and len(slots) < limit:
                if _slot_inside_windows(
                    start_minutes=slot_start_minutes,
                    duration=duration,
                    windows=windows,
                    preferred_period=preferred_period,
                ):
                    slot_start = datetime.combine(
                        current_day,
                        datetime.strptime(_minutes_to_time(slot_start_minutes), "%H:%M").time(),
                    ).replace(tzinfo=tz)
                    slot_end = slot_start + timedelta(minutes=duration)
                    if slot_start >= earliest and not _has_conflict(
                        db=db,
                        agenda=agenda,
                        starts_at=slot_start,
                        ends_at=slot_end,
                    ):
                        slots.append(
                            {
                                "start_time": slot_start.isoformat(),
                                "end_time": slot_end.isoformat(),
                                "display": _format_datetime_for_lead(slot_start, agenda.timezone),
                                "local_date": slot_start.date().isoformat(),
                                "local_time": slot_start.strftime("%H:%M"),
                                "relative_day": _relative_day_label(slot_start, agenda.timezone),
                            }
                        )
                slot_start_minutes += duration
        current_day += timedelta(days=1)

    return slots


def _get_client_id_for_lead(db: Session, company_id: int, phone: str) -> Optional[int]:
    from backend.models import ClientCompany, Contact

    contact = None
    if phone:
        contact = (
            db.query(Contact)
            .filter(Contact.company_id == company_id, Contact.phone == phone)
            .first()
        )
    if contact:
        return int(contact.client_id)

    association = db.query(ClientCompany).filter(ClientCompany.company_id == company_id).first()
    return int(association.client_id) if association else None


def _get_or_create_lead(
    *,
    db: Session,
    company_id: int,
    lead_id: Optional[int],
    lead_name: str,
    lead_phone: str,
) -> Dict[str, Any]:
    from backend.models import Contact, Lead

    phone = _normalize_phone(lead_phone)

    if lead_id:
        lead = db.query(Lead).filter(Lead.id == lead_id, Lead.company_id == company_id).first()
        if lead:
            return {"success": True, "lead": lead}
        return {
            "success": False,
            "error": "lead_not_found",
            "message_for_agent": "O lead informado não foi encontrado neste workspace.",
        }

    if not phone:
        return {
            "success": False,
            "error": "lead_phone_required",
            "message_for_agent": "Peça o telefone do lead antes de criar o agendamento.",
        }

    lead = (
        db.query(Lead)
        .filter(and_(Lead.company_id == company_id, Lead.phone == phone))
        .first()
    )
    if lead:
        if lead_name and not lead.name:
            lead.name = lead_name
            db.commit()
            db.refresh(lead)
        return {"success": True, "lead": lead}

    client_id = _get_client_id_for_lead(db, company_id, phone)
    if not client_id:
        return {
            "success": False,
            "error": "workspace_owner_not_found",
            "message_for_agent": "Não foi possível identificar o proprietário do workspace para criar o lead.",
        }

    contact = (
        db.query(Contact)
        .filter(Contact.client_id == client_id, Contact.phone == phone)
        .first()
    )
    if not contact:
        db.add(
            Contact(
                client_id=client_id,
                company_id=company_id,
                phone=phone,
                name=lead_name or "Lead",
            )
        )
        db.flush()

    lead = Lead(
        client_id=client_id,
        company_id=company_id,
        name=lead_name or "Lead",
        phone=phone,
        source_id="Agente IA",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return {"success": True, "lead": lead}


def _sync_google_calendar_if_available(
    db: Session,
    appointment: Agendamento,
    starts_at: datetime,
    is_rescheduling: bool = False,
    create_google_meet: bool = False,
) -> str:
    try:
        from backend.routes.integrations.google_calendar_flow_service import (
            sync_appointment_to_google_calendar,
        )

        synced = sync_appointment_to_google_calendar(
            db=db,
            local_appointment_id=appointment.id,
            date_str=starts_at.strftime("%d/%m/%Y"),
            time_str=starts_at.strftime("%H:%M"),
            is_rescheduling=is_rescheduling,
            create_google_meet=create_google_meet,
        )
        return "synced_or_not_applicable" if synced else "failed"
    except Exception as exc:
        logger.warning(
            "[CalendarSchedulingTool] Google Calendar sync skipped for appointment=%s: %s",
            appointment.id,
            exc,
        )
        return "skipped"


def _cancel_google_calendar_event_if_available(
    db: Session,
    appointment: Agendamento,
) -> str:
    if not appointment.event_id:
        appointment.google_sync_status = "NOT_APPLICABLE"
        return "skipped_no_event"

    try:
        from backend.models import Agenda, CalendarIntegration
        from backend.routes.integrations.google_calendar_service import (
            build_google_oauth_service,
            delete_google_event,
        )

        integration = (
            db.query(CalendarIntegration)
            .filter(
                CalendarIntegration.company_id == appointment.company_id,
                CalendarIntegration.provider == "google",
            )
            .first()
        )
        target_calendar_id = appointment.google_calendar_id
        if not target_calendar_id and appointment.agenda_id:
            linked_agenda = (
                db.query(Agenda)
                .filter(
                    Agenda.id == appointment.agenda_id,
                    Agenda.company_id == appointment.company_id,
                )
                .first()
            )
            target_calendar_id = linked_agenda.google_calendar_id if linked_agenda else None
        if not target_calendar_id and integration:
            target_calendar_id = integration.google_calendar_id

        if not integration or not target_calendar_id or not integration.google_oauth_token:
            appointment.google_sync_status = "CANCEL_FAILED"
            return "failed_not_configured"

        google_service = build_google_oauth_service(integration, db)
        if not google_service:
            appointment.google_sync_status = "CANCEL_FAILED"
            return "failed_invalid_oauth"

        deleted = delete_google_event(
            target_calendar_id,
            appointment.event_id,
            service=google_service,
        )
        if deleted:
            appointment.event_id = None
            appointment.google_calendar_id = None
            appointment.google_sync_status = "CANCELLED"
            return "cancelled"

        appointment.google_sync_status = "CANCEL_FAILED"
        return "failed"
    except Exception as exc:
        appointment.google_sync_status = "CANCEL_FAILED"
        logger.warning(
            "[CalendarSchedulingTool] Google Calendar cancel skipped for appointment=%s: %s",
            appointment.id,
            exc,
        )
        return "failed"


def _cancel_confirmation_tasks_if_present(db: Session, appointment_id: int) -> str:
    try:
        result = db.execute(
            text(
                """
                UPDATE confirmation_executions
                   SET status = 'CANCELED'
                 WHERE agendamento_id = :appointment_id
                   AND status NOT IN ('SUCCESS', 'FAILED', 'CANCELED')
                """
            ),
            {"appointment_id": appointment_id},
        )
        return f"cancelled_{result.rowcount or 0}"
    except Exception as exc:
        db.rollback()
        logger.warning(
            "[CalendarSchedulingTool] confirmation cancellation skipped for appointment=%s: %s",
            appointment_id,
            exc,
        )
        return "skipped"


def _append_appointment_note(current_value: Optional[str], note: str) -> str:
    current = (current_value or "").strip()
    clean_note = note.strip()
    if not current:
        return clean_note
    if clean_note in current:
        return current
    return f"{current}\n{clean_note}"


def _dispatch_confirmation_task_if_configured(
    *,
    db: Session,
    company_id: int,
    appointment: Agendamento,
) -> str:
    if not appointment.phone:
        return "skipped_no_phone"

    row = db.execute(
        text("SELECT zapi_instance_id, zapi_token FROM companies WHERE id = :cid LIMIT 1"),
        {"cid": company_id},
    ).fetchone()
    if not row or not row.zapi_instance_id or not row.zapi_token:
        return "skipped_not_configured"

    try:
        from backend.services.company_access_control import capture_company_job_epoch
        from backend.worker.tasks_confirmation import enviar_passo_confirmacao

        operational_epoch = capture_company_job_epoch(db, company_id)
        db.commit()
        enviar_passo_confirmacao.delay(
            agendamento_id=appointment.id,
            step_number=1,
            instance_id=row.zapi_instance_id,
            instance_token=row.zapi_token,
            phone=appointment.phone,
            operational_epoch=operational_epoch,
        )
        return "queued"
    except Exception as exc:
        logger.warning(
            "[CalendarSchedulingTool] confirmation task skipped for appointment=%s: %s",
            appointment.id,
            exc,
        )
        return "failed"


def _cancel_dynamic_followup_for_appointment_if_present(
    *,
    db: Session,
    appointment: Agendamento,
    event_name: str,
) -> str:
    try:
        from backend.services.agent_dynamic_followup_service import (
            cancel_dynamic_followups_for_appointment,
        )

        cancelled = cancel_dynamic_followups_for_appointment(
            db,
            appointment=appointment,
            reason=f"{event_name}:appointment_active",
        )
        return f"cancelled_{cancelled}" if cancelled else "not_applicable"
    except Exception as exc:
        logger.warning(
            "[CalendarSchedulingTool] dynamic follow-up cancellation skipped for appointment=%s: %s",
            getattr(appointment, "id", None),
            exc,
        )
        db.rollback()
        return "skipped"


def _format_datetime_for_lead(value: datetime, timezone_name: Optional[str]) -> str:
    tz = _safe_timezone(timezone_name)
    local_value = value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
    return local_value.strftime("%d/%m/%Y às %H:%M")
