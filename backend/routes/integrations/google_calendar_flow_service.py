
import logging
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any
import pytz # Necessário para conversão de timezone

# Models do nosso DB
from backend.models import Agenda, Agendamento, CalendarIntegration, AgentConfiguration
from backend.runtime_settings import APP_NAME

# Funções do serviço de API Google Calendar
from backend.routes.integrations.google_calendar_service import ( # Corrigido caminho do import
    build_google_oauth_service,
    create_google_event,
    update_google_event,
    delete_google_event,
    get_google_calendar_timezone,
    extract_google_meeting_link,
)

logger = logging.getLogger(__name__)

# --- Constantes ---
DEFAULT_APPOINTMENT_DURATION_MINUTES = 60
DEFAULT_TIMEZONE = "America/Sao_Paulo" # Timezone padrão Brasil

# --- Constantes de Status de Sincronização ---
SYNC_STATUS_SYNCED = "SYNCED"
SYNC_STATUS_FAILED = "FAILED"
# SYNC_STATUS_PENDING = "PENDING" # Pode ser útil, mas não implementado agora
SYNC_STATUS_CANCELLED = "CANCELLED"
SYNC_STATUS_CANCEL_FAILED = "CANCEL_FAILED"
SYNC_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
# ---------------------------------------------


def _resolve_agenda_google_calendar(
    db: Session,
    agn: Agendamento,
    integration: CalendarIntegration,
) -> tuple[Optional[str], Optional[Agenda]]:
    if agn.google_calendar_id:
        linked_agenda = None
        if agn.agenda_id:
            linked_agenda = db.query(Agenda).filter(
                Agenda.id == agn.agenda_id,
                Agenda.company_id == agn.company_id,
            ).first()
        return agn.google_calendar_id, linked_agenda

    linked_agenda = None
    if agn.agenda_id:
        linked_agenda = db.query(Agenda).filter(
            Agenda.id == agn.agenda_id,
            Agenda.company_id == agn.company_id,
        ).first()
        if linked_agenda and linked_agenda.google_calendar_id:
            return linked_agenda.google_calendar_id, linked_agenda

    return integration.google_calendar_id, linked_agenda


def _build_google_event_summary(agn: Agendamento) -> str:
    customer_name = str(agn.nome or "").strip() or "Cliente"
    return f"Reunião | {customer_name}"


# --- Função de Sincronização - ATUALIZADA com Status ---
def sync_appointment_to_google_calendar(
    db: Session,
    local_appointment_id: int,
    date_str: str, # Recebe "DD/MM/YYYY"
    time_str: str,  # Recebe "HH:MM"
    is_rescheduling: bool = False,
    create_google_meet: bool = False,
    ) -> bool:
    """
    Sincroniza (cria/atualiza) agendamento local com Google Calendar.
    Usa data/hora NAIVE (sem fuso) + ID do Timezone obtido da API Google.
    Atualiza google_sync_status localmente ('SYNCED' ou 'FAILED').

    Retorna True se a chamada à API Google foi bem-sucedida, False caso contrário.
    """
    log_prefix = f"[GCAL Sync][Local ID: {local_appointment_id}]"
    logger.info(f"{log_prefix} Iniciando sync (naive) com Google Calendar para {date_str} {time_str}.")
    api_success = False
    final_sync_status = SYNC_STATUS_FAILED
    agn: Optional[Agendamento] = None # Define agn aqui

    try:
        # 1. Buscar Agendamento Local e verificar pré-condições
        agn = db.query(Agendamento).filter(Agendamento.id == local_appointment_id).with_for_update().first()
        if not agn: logger.error(f"{log_prefix} Agendamento local não encontrado."); return False
        if agn.status and 'CANCELLED' in agn.status.upper() and not is_rescheduling:
            logger.info(f"{log_prefix} Cancelado localmente.");
            return True
        # Não precisamos mais validar consulta_data aqui, pois recebemos date_str/time_str

        company_id = agn.company_id
        google_event_id = agn.event_id

        # 2. Buscar Configuração Google e resolver calendário da agenda local
        integration = db.query(CalendarIntegration).filter(
             CalendarIntegration.company_id == company_id, CalendarIntegration.provider == 'google'
        ).first()
        if not integration or not integration.google_oauth_token:
            logger.debug(f"{log_prefix} Integração Google não ativa.")
            if agn.google_sync_status != SYNC_STATUS_NOT_APPLICABLE: agn.google_sync_status = SYNC_STATUS_NOT_APPLICABLE; db.commit()
            return True
        target_calendar_id, linked_agenda = _resolve_agenda_google_calendar(db, agn, integration)
        if not target_calendar_id:
            logger.debug(f"{log_prefix} Agendamento sem agenda Google vinculada.")
            if agn.google_sync_status != SYNC_STATUS_NOT_APPLICABLE: agn.google_sync_status = SYNC_STATUS_NOT_APPLICABLE; db.commit()
            return True
        google_service = build_google_oauth_service(integration, db)
        if not google_service:
            logger.error(f"{log_prefix} Token OAuth Google indisponível ou inválido.")
            agn.google_sync_status = SYNC_STATUS_FAILED; db.commit(); return False

        # 3. Buscar Timezone DA API GOOGLE (ainda necessário para o campo 'timeZone')
        timezone_str = get_google_calendar_timezone(target_calendar_id, service=google_service) or DEFAULT_TIMEZONE
        logger.info(f"{log_prefix} Usando Timezone da API/Default: {timezone_str}")

        # 4. Buscar Duração (config local)
        duration_minutes = DEFAULT_APPOINTMENT_DURATION_MINUTES
        if linked_agenda and linked_agenda.slot_duration:
            duration_minutes = int(linked_agenda.slot_duration)
        else:
            agent_config = db.query(AgentConfiguration).filter(AgentConfiguration.company_id == company_id).first()
            if agent_config and agent_config.scheduling_config and isinstance(agent_config.scheduling_config, dict):
                 extracted_duration = agent_config.scheduling_config.get("consultation_duration")
                 if isinstance(extracted_duration, (int, float)) and extracted_duration > 0: duration_minutes = int(extracted_duration)
        logger.debug(f"{log_prefix} Usando Duração: {duration_minutes} min.")

        # 5. Preparar Dados do Evento (Datas Naive Formatadas)
        try:
            # Cria datetime NAIVE a partir das strings recebidas
            start_dt_naive = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
            end_dt_naive = start_dt_naive + timedelta(minutes=duration_minutes)
            # Formata para ISO SEM timezone/offset: YYYY-MM-DDTHH:MM:SS
            start_naive_iso = start_dt_naive.strftime("%Y-%m-%dT%H:%M:%S")
            end_naive_iso = end_dt_naive.strftime("%Y-%m-%dT%H:%M:%S")
            logger.debug(f"{log_prefix} Datetimes Naive Formatados: Start={start_naive_iso}, End={end_naive_iso}")
        except (ValueError, TypeError) as e:
            logger.error(f"{log_prefix} Erro ao formatar/calcular data/hora naive: {e}")
            agn.google_sync_status = SYNC_STATUS_FAILED; db.commit(); return False

        # Montar Título e Descrição
        summary = _build_google_event_summary(agn)
        description = f"Agendamento {APP_NAME}\nCliente: {agn.nome or 'N/A'}\nTelefone: {agn.phone or 'N/A'}\nInteresse: {agn.interesse or 'Avaliação'}\nID Local: {agn.id}"

        # 6. Chamar API Google: Criar ou Atualizar (passando strings naive + timezone)
        new_or_updated_event_id = None
        new_or_updated_event = None
        # --- ASSUME que create/update_google_event foram AJUSTADOS para receber strings naive ---
        if google_event_id: # Atualizar
            logger.info(f"{log_prefix} Tentando atualizar evento Google ID: {google_event_id}")
            new_or_updated_event = update_google_event(
                calendar_id=target_calendar_id, event_id=google_event_id, summary=summary,
                description=description, start_naive_iso=start_naive_iso, # <-- Passa string naive
                end_naive_iso=end_naive_iso, timezone=timezone_str,       # <-- Passa ID do Timezone
                service=google_service, create_conference=create_google_meet, return_event=True
            )
            if new_or_updated_event and new_or_updated_event.get("id"):
                api_success = True
                new_or_updated_event_id = new_or_updated_event.get("id") or google_event_id
            else: api_success = False; logger.error(f"{log_prefix} Falha API ao ATUALIZAR evento ID={google_event_id}.")
        else: # Criar
             logger.info(f"{log_prefix} Tentando criar novo evento Google.")
             new_or_updated_event = create_google_event(
                 calendar_id=target_calendar_id, summary=summary, description=description,
                 start_naive_iso=start_naive_iso, # <-- Passa string naive
                 end_naive_iso=end_naive_iso,     # <-- Passa string naive
                 timezone=timezone_str,           # <-- Passa ID do Timezone
                 service=google_service, create_conference=create_google_meet, return_event=True
             )
             if new_or_updated_event and new_or_updated_event.get("id"):
                 api_success = True
                 new_or_updated_event_id = new_or_updated_event.get("id")
             else: api_success = False; logger.error(f"{log_prefix} Falha API ao CRIAR evento Google.")

        # 7. Definir Status e Salvar ID localmente
        final_sync_status = SYNC_STATUS_SYNCED if api_success else SYNC_STATUS_FAILED
        if api_success:
            agn.event_id = new_or_updated_event_id
            agn.google_calendar_id = target_calendar_id
            meeting_link = extract_google_meeting_link(new_or_updated_event) if create_google_meet else None
            if meeting_link:
                agn.local_link = meeting_link
        elif google_event_id: # Limpa ID se update falhou
             agn.event_id = None
             agn.google_calendar_id = None
        agn.google_sync_status = final_sync_status
        logger.info(f"{log_prefix} Definindo google_sync_status: {final_sync_status}")

        # Commit final
        db.commit()
        logger.info(f"{log_prefix} Sincronização concluída. Sucesso API Google: {api_success}")
        return api_success

    except Exception as e:
        logger.exception(f"{log_prefix} Erro inesperado: {e}")
        if db.is_active:
            try: # Tenta salvar status de falha
                if agn: agn.google_sync_status = SYNC_STATUS_FAILED; db.commit()
            except: db.rollback()
        return False

# --- Função de Cancelamento - ATUALIZADA com Status ---
def cancel_google_calendar_appointment_flow(db: Session, local_appointment_id: int, delete_local: bool = True) -> bool:
    """
    Busca agendamento local, deleta evento no Google Calendar (se event_id existir)
    e atualiza status local e google_sync_status.

    Retorna True se a operação na API Google foi bem-sucedida OU não necessária.
    Retorna False se ocorreu erro na API Google ou erro crítico no processo.
    """
    log_prefix = f"[GCAL Cancel][Local ID: {local_appointment_id}]"
    logger.info(f"{log_prefix} Iniciando fluxo de cancelamento Google Calendar.")
    api_success = True # Assume sucesso se não precisar chamar API
    final_sync_status = SYNC_STATUS_CANCELLED # Status padrão para sucesso

    # Variável para referenciar o objeto Agendamento na sessão
    agn: Optional[Agendamento] = None

    try:
        # 1. Buscar agendamento local
        agn = db.query(Agendamento).filter(Agendamento.id == local_appointment_id).with_for_update().first()
        if not agn: logger.error(f"{log_prefix} Agendamento local não encontrado."); return False

        company_id = agn.company_id
        google_event_id = agn.event_id

        # 2. Verificar se há evento Google para cancelar
        if not google_event_id:
            logger.info(f"{log_prefix} Sem Google Event ID. Apenas atualizando status local.")
            final_sync_status = SYNC_STATUS_NOT_APPLICABLE
            # api_success continua True
        else:
            # 3. Buscar ID do Calendário Google
            integration = db.query(CalendarIntegration).filter(
                CalendarIntegration.company_id == company_id,
                CalendarIntegration.provider == 'google'
            ).first()
            if not integration or not integration.google_oauth_token:
                logger.warning(f"{log_prefix} Integração Google não ativa para cancelar evento {google_event_id}.")
                final_sync_status = SYNC_STATUS_CANCEL_FAILED
                api_success = False
                agn.event_id = None # Limpa ID antigo pois não conseguimos cancelar
            else:
                target_calendar_id, _ = _resolve_agenda_google_calendar(db, agn, integration)
                if not target_calendar_id:
                    logger.warning(f"{log_prefix} Agendamento com evento Google, mas sem calendário Google resolvido.")
                    agn.event_id = None
                    agn.google_calendar_id = None
                    agn.google_sync_status = SYNC_STATUS_CANCEL_FAILED
                    db.commit()
                    return False
                google_service = build_google_oauth_service(integration, db)
                if not google_service:
                    logger.error(f"{log_prefix} Token OAuth Google indisponível ou inválido para cancelar evento.")
                    agn.event_id = None
                    agn.google_sync_status = SYNC_STATUS_CANCEL_FAILED
                    db.commit()
                    return False
                # 4. Chamar API para Deletar Evento Google
                logger.info(f"{log_prefix} Tentando deletar evento Google ID: {google_event_id}")
                delete_api_result = delete_google_event(target_calendar_id, google_event_id, service=google_service) # Retorna True/False

                if delete_api_result:
                    logger.info(f"{log_prefix} Evento Google deletado com sucesso pela API.")
                    agn.event_id = None # Limpa ID local
                    agn.google_calendar_id = None
                    final_sync_status = SYNC_STATUS_CANCELLED
                    api_success = True
                else:
                    logger.error(f"{log_prefix} Falha ao deletar evento Google ID={google_event_id} via API.")
                    agn.event_id = None # Limpa ID local mesmo em falha
                    agn.google_calendar_id = None
                    final_sync_status = SYNC_STATUS_CANCEL_FAILED
                    api_success = False

        # 5. Excluir ou manter registro local conforme o fluxo chamador.
        if delete_local:
            logger.info(f"{log_prefix} Executando HARD DELETE do registro local.")
            db.delete(agn)
        else:
            agn.google_sync_status = final_sync_status
            db.add(agn)
        db.commit()
        if delete_local:
            logger.info(f"{log_prefix} Registro local EXCLUÍDO fisicamente do banco.")
        return api_success # Retorna o sucesso da operação na API Google (ou True se não precisou)

    except Exception as e:
        logger.exception(f"{log_prefix} Erro inesperado: {e}")
        if db.is_active:
             # Tenta salvar status de falha se possível
            try:
                 if agn: agn.google_sync_status = SYNC_STATUS_FAILED; db.commit()
            except: db.rollback()
        return False

# --- (Não incluir outras funções como _get_clinicorp_credentials aqui) ---
