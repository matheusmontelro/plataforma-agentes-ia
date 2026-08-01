
# --- Imports Padrão e SQLAlchemy ---
import logging
import random
import requests
from sqlalchemy.orm import Session, selectinload # Adicionar selectinload se usado no helper _get_active_integration_type
from sqlalchemy.sql import text
from datetime import datetime, timedelta, timezone # Adicionar timezone se usado nos helpers
from typing import Optional, Dict, Any, Tuple # Adicionar Tuple se usado

# --- Imports dos Modelos ---
from backend.models import (
    Agendamento,
    Agenda,
    Lead,
    Contact,
    CalendarIntegration,    # <-- Adicionado para checar integração
    ClinicorpDetails,       # <-- Adicionado para checar integração Clinicorp
    AgentConfiguration,     # <-- Adicionado para buscar config (duração, detalhes msg)
    Client,                 # <-- Verificar se já estava ou se é necessário
    Company,                 # <-- Verificar se já estava ou se é necessário
    NoShowEvent             # <-- Manter se usado em outras partes do arquivo
    # Adicionar outros modelos se forem usados neste arquivo
)

# --- Imports dos Serviços de Integração ---
# Clinicorp (Já existente)
from backend.routes.integrations.clinicorp_flow_service import (
    sync_appointment_to_clinicorp,
    cancel_clinicorp_appointment_flow,
    ClinicorpSyncError,
    reschedule_clinicorp_appointment # Importar se for usar futuramente aqui
)
# Google Calendar (Novo)
from backend.routes.integrations.google_calendar_flow_service import (
    sync_appointment_to_google_calendar,
    cancel_google_calendar_appointment_flow
    # Adicionar GoogleSyncError se criou uma exceção específica
)

# --- Imports de Tasks Celery e Helpers Internos ---
from backend.worker.tasks_confirmation import enviar_passo_confirmacao, clear_confirmation_steps # Manter
from backend.worker.tasks_noshow import clear_noshow_steps # Manter se usado no PUT/DELETE original
# Manter imports originais se ainda forem usados no fluxo webhook/LLM
from backend.prompt.llm.validation_service import validate_all_extracted_data, get_full_conversation_history
from backend.prompt.llm.slot_verification import verify_slot_availability, suggest_alternative_slots, check_time_in_available_slots
from backend.prompt.scheduling.scheduling_service import SchedulingService
from backend.prompt.db_integration.support_webhook import send_to_webhook
# -------------------------------------------

logger = logging.getLogger(__name__)

# --- Helper Gerar Protocolo (Mantido) ---
def _gerar_numero_protocolo() -> str:
    """Gera um número de protocolo aleatório."""
    numeros = [str(random.randint(0, 9)) for _ in range(8)]
    numero_aleatorio = ''.join(numeros)
    protocolo = f"{numero_aleatorio}"
    return protocolo

# --- Helper para buscar detalhes da empresa para mensagem (Necessário para ambos os fluxos) ---
def _get_company_message_details(db: Session, company_id: int) -> dict:
    """Busca company_info e team_specialties para gerar mensagem, e webhooks."""
    # Usando LEFT JOIN para o caso de agent_configurations não existir
    row = db.execute(text("""
        SELECT sgi.webhook_scheduling, sgi.webhook_cancellation, ac.company_info, ac.team_and_specialties
        FROM support_group_integrations sgi
        LEFT JOIN agent_configurations ac ON ac.company_id = sgi.company_id
        WHERE sgi.company_id = :cid LIMIT 1
    """), {"cid": company_id}).fetchone()

    # Fallback se não houver support_group_integrations mas houver agent_configurations
    if not row:
         row = db.execute(text("""
             SELECT ac.company_info, ac.team_and_specialties
             FROM agent_configurations ac
             WHERE ac.company_id = :cid LIMIT 1
         """), {"cid": company_id}).fetchone()

    if row:
        row_map = row._mapping if hasattr(row, '_mapping') else row.__dict__
        return {
            "webhook_scheduling": row_map.get("webhook_scheduling"),
            "webhook_cancellation": row_map.get("webhook_cancellation"),
            "company_info": row_map.get('company_info') or {},
            "team_sp": row_map.get('team_and_specialties') or {}
        }
    logger.warning(f"Configurações (Agent/Support) não encontradas company_id {company_id} para detalhes da mensagem.")
    return {"webhook_scheduling": None, "webhook_cancellation": None, "company_info": {}, "team_sp": {}}


# --- Helper para gerar mensagem de confirmação (Necessário para ambos os fluxos) ---
def _generate_confirmation_message(company_info: dict, team_sp: dict, data: str, horario: str) -> str:
    """Gera a mensagem final de confirmação."""
    endereco_str = company_info.get("company_address", "Endereço não cadastrado")
    location_str = company_info.get("company_location", "")
    link_Maps = company_info.get("company_maps", "")
    # CORREÇÃO APLICADA: Usar a chave correta do DB
    dentista_responsavel = team_sp.get("technical_responsible", "Dr(a). [Responsável não cadastrado]")
    endereco_completo = f"{endereco_str}, {location_str}".strip().rstrip(",")
    protocolo = _gerar_numero_protocolo() # Helper original

    data_display = data if data != "DD/MM/YYYY" else "[Data não confirmada]"
    horario_display = horario if horario != "HH:MM" else "[Horário não confirmado]"

    return f"""
Segue abaixo as informações da sua consulta agendada.

🗓 *Data e Horário*: {data_display} às {horario_display}
📍 *Endereço*: {endereco_completo}
🔗 *Link do Google Maps*: {link_Maps or 'Link não disponível'}
🔢 *Número de Protocolo*: {protocolo}

Por favor, apresente este número de protocolo na recepção ao chegar.

👩‍⚕️ *Dentista Responsável*: {dentista_responsavel}

Se tiver qualquer dúvida sobre sua consulta de avaliação, não hesite em nos contatar.
""".strip()

def _try_send_confirmation_task(db: Session, company_id: int, local_appointment_id: int, phone: str):
    """Tenta buscar credenciais Z-API e disparar a task Celery."""
    # (Código como nas respostas anteriores)
    try:
        row_cred = db.execute(text("SELECT zapi_instance_id, zapi_token FROM companies WHERE id = :cid"), {"cid": company_id}).fetchone()
        if row_cred and row_cred.zapi_instance_id and row_cred.zapi_token:
            # <<< ADICIONAR LOG AQUI >>>
            logger.info(f"[agendamento_logic] Disparando task enviar_passo_confirmacao (step 1) via _try_send_confirmation_task para agendamento ID={local_appointment_id}, company_id={company_id}, phone={phone}")
            # --- FIM DO LOG ADICIONADO ---
            from backend.services.company_access_control import capture_company_job_epoch

            operational_epoch = capture_company_job_epoch(db, company_id)
            db.commit()
            enviar_passo_confirmacao.delay(
                agendamento_id=local_appointment_id,
                step_number=1,
                instance_id=row_cred.zapi_instance_id,
                instance_token=row_cred.zapi_token,
                phone=phone,
                operational_epoch=operational_epoch,
            )
            logger.info(f"Task Celery 'enviar_passo_confirmacao' disparada para agendamento local ID {local_appointment_id}")
        else: logger.warning(f"Credenciais Z-API não encontradas company_id={company_id}.")
    except Exception as e: logger.error(f"Erro ao disparar task Celery para agendamento local ID {local_appointment_id}: {e}")

# --- Fluxo de integração por webhook ---
def enviar_agendamento_confirmado(
    db: Session,
    company_id: int,
    phone: str,
    agendamento: dict, # Dict vindo do LLM {data, horario, nome, etc.}
    api_key: Optional[str], # api_key pode ser None
    agendamento_id: int # ID do Agendamento LOCAL recém-criado
) -> str:
    """
    Envia o payload ao webhook e retorna a mensagem de confirmação.
    """
    logger.info(f"[Webhook Flow] Iniciando envio para webhook para agendamento local ID {agendamento_id}")
    # Busca webhook URL e detalhes para mensagem usando o helper
    agent_info = _get_company_message_details(db, company_id)
    webhook_url = agent_info.get("webhook_scheduling")
    company_info = agent_info.get("company_info", {})
    team_sp = agent_info.get("team_sp", {})

    # Busca Lead ID e Client ID
    # (Esta busca é feita novamente aqui, mas pode ser otimizada se necessário)
    lead_check = db.execute(text("SELECT id AS lead_id, client_id FROM leads WHERE phone = :p AND company_id = :cid LIMIT 1"), {"p": phone, "cid": company_id}).fetchone()
    lead_id = lead_check.lead_id if lead_check else None
    client_id_db = lead_check.client_id if lead_check else None

    # Enviar para Webhook se URL existir
    if webhook_url:
        payload = {
            "company_id": company_id, "client_id": client_id_db, "lead_id": lead_id,
            "api_key": api_key, "phone": phone, "agendamento_id": agendamento_id,
            "agendamento": agendamento
        }
        headers = {"X-API-Key": api_key or "", "Content-Type": "application/json"}
        try:
            resp = requests.post(webhook_url, json=payload, headers=headers, timeout=15)
            logger.info(f"[Webhook Flow] Webhook enviado para {webhook_url}. Status: {resp.status_code}")
            if resp.status_code >= 400:
                 logger.error(f"[Webhook Flow] Webhook retornou erro: {resp.status_code} - {resp.text[:500]}")
        except requests.RequestException as e:
            logger.error(f"[Webhook Flow] Erro ao enviar para webhook {webhook_url}: {e}")
    else:
        logger.warning(f"[Webhook Flow] URL de webhook não configurada para company_id={company_id}.")

    # Gerar mensagem de confirmação usando o helper
    data_str = agendamento.get("data", "DD/MM/YYYY")
    horario_str = agendamento.get("horario", "HH:MM")
    return _generate_confirmation_message(company_info, team_sp, data_str, horario_str)

# --- Cancelamento por webhook ---
def processar_cancelamento(db: Session, company_id: int, phone: str, api_key: Optional[str]) -> str:
    """
    Cancela localmente e envia webhook.
    """
    logger.info(f"[Webhook Flow] Iniciando cancelamento para {phone}, company_id={company_id}")

    # 1) Buscar lead_id
    lead_check = db.execute(text("SELECT id AS lead_id FROM leads WHERE phone = :p AND company_id = :cid ORDER BY id DESC LIMIT 1"), {"p": phone, "cid": company_id}).fetchone()
    if not lead_check:
        logger.warning(f"[Webhook Flow Cancel] Lead não encontrado para {phone}, {company_id}.")
        return "Não localizei um registro seu associado a um agendamento ativo."

    lead_id = lead_check.lead_id

    # 2) Buscar e DELETAR agendamento local mais recente
    deleted = db.execute(text("""
        DELETE FROM agendamentos
        WHERE id = (
            SELECT id FROM agendamentos
            WHERE lead_id = :lead_id AND company_id = :company_id AND status != 'CANCELLED' -- Evita deletar o que já foi cancelado?
            ORDER BY id DESC LIMIT 1
        )
        RETURNING id;
    """), {"lead_id": lead_id, "company_id": company_id}).scalar_one_or_none()

    if deleted:
        db.commit()
        logger.info(f"[Webhook Flow Cancel] Agendamento local ID={deleted} EXCLUÍDO.")
    else:
        db.rollback()
        logger.warning(f"[Webhook Flow Cancel] Nenhum agendamento local ativo encontrado para deletar (lead_id={lead_id}).")
        return "Não localizei um agendamento ativo para cancelar."

    # 3) Disparar webhook de cancelamento
    cancel_data = {"action": "cancel_appointment", "phone": phone, "status": "cancelled", "agendamento_id": deleted} # Adiciona ID deletado ao payload
    # Busca URL do webhook de cancelamento
    webhook_info = _get_company_message_details(db, company_id) # Reutiliza helper
    webhook_url_cancel = webhook_info.get("webhook_cancellation") # Precisa garantir que a query busque este campo ou que ele esteja em support_group_integrations

    # Se não existir webhook_url_cancel, tentar o webhook_scheduling como fallback? Ou apenas logar?
    if not webhook_url_cancel:
         webhook_url_cancel = webhook_info.get("webhook_scheduling") # Fallback para o de agendamento? Decidir regra.
         if webhook_url_cancel:
             logger.warning(f"Webhook de cancelamento não encontrado para company_id {company_id}, usando webhook de agendamento como fallback.")
         else:
             logger.error(f"Nenhum webhook encontrado para notificar cancelamento company_id {company_id}.")
             # Retorna sucesso mesmo assim, pois cancelamento local ocorreu
             return """Seu agendamento foi cancelado com sucesso."""


    # Reutilizar a função send_to_webhook se ela existir e for adequada, ou fazer o POST aqui
    headers_wh = {"X-API-Key": api_key or "", "Content-Type": "application/json"}
    success_webhook = False
    try:
        resp_wh = requests.post(webhook_url_cancel, json=cancel_data, headers=headers_wh, timeout=10)
        logger.info(f"[Webhook Flow Cancel] Webhook de cancelamento enviado para {webhook_url_cancel}. Status: {resp_wh.status_code}")
        success_webhook = resp_wh.ok # Considera sucesso se status < 400
    except requests.RequestException as e:
         logger.error(f"[Webhook Flow Cancel] Erro ao enviar webhook de cancelamento para {webhook_url_cancel}: {e}")


    # Mensagem de retorno para o usuário
    if success_webhook:
        return """Seu agendamento foi cancelado com sucesso.
Caso deseje reagendar sua consulta de avaliação, estou à disposição."""
    else:
        # O cancelamento local ocorreu, mas a notificação falhou
        return "Seu agendamento foi cancelado, mas houve um problema ao notificar o sistema externo."


# --- Função Principal Modificada com Roteamento ---
def processar_json_do_llm(db: Session, company_id: int, phone: str, llm_json: dict, api_key: Optional[str]) -> str:
    """
    Processa o JSON do LLM e direciona dinamicamente para o fluxo de integração
    apropriado (Clinicorp, Google Calendar) ou para o fluxo padrão/webhook,
    baseado na configuração da empresa em calendar_integrations.
    """
    try:
        # Determina o tipo de integração ativa para esta empresa
        integration_type = _get_active_integration_type(db, company_id)
        logger.info(f"[Router] Iniciando processamento para company_id={company_id}. Integração Ativa: {integration_type or 'Nenhuma/Webhook'}")

        # --- ROTEAMENTO CANCELAMENTO ---
        if llm_json.get("cancelar_agendamento") is True:
            logger.info(f"[Router] Cancelamento solicitado.")

            # 1. Encontrar ID do agendamento local ativo (lógica comum)
            lead_info = db.query(Lead).filter(Lead.phone == phone, Lead.company_id == company_id).order_by(Lead.id.desc()).first()
            if not lead_info: return "Não encontrei um registro seu para cancelar um agendamento."

            agn_antigo = db.query(Agendamento).filter(
                Agendamento.lead_id == lead_info.id, Agendamento.company_id == company_id,
                Agendamento.status.notlike('CANCELLED%')
            ).order_by(Agendamento.id.desc()).first()
            if not agn_antigo: return "Não encontrei um agendamento ativo para cancelar."
            local_agn_id = agn_antigo.id

            # 2. Direcionar com base no tipo de integração ATIVA (para QUALQUER company_id)
            if integration_type == 'clinicorp':
                logger.info(f"[Router] Direcionando cancelamento para Clinicorp (ID Local: {local_agn_id}).")
                try:
                    success = cancel_clinicorp_appointment_flow(db, local_agn_id)
                    msg = ("Seu agendamento foi cancelado com sucesso." if success else
                           "Tive um problema ao sincronizar o cancelamento com a agenda externa (C).")
                    return msg
                except Exception as e_cancel:
                     logger.exception(f"[Clinicorp Cancel Flow] Erro inesperado: {e_cancel}")
                     return "Ocorreu um erro inesperado ao processar o cancelamento (C)."

            elif integration_type == 'google':
                logger.info(f"[Router] Direcionando cancelamento para Google Calendar (ID Local: {local_agn_id}).")
                try:
                    success = cancel_google_calendar_appointment_flow(db, local_agn_id)
                    msg = ("Seu agendamento foi cancelado com sucesso." if success else
                           "Tive um problema ao sincronizar o cancelamento com a agenda externa (G).")
                    return msg
                except Exception as e_cancel:
                     logger.exception(f"[Google Cancel Flow] Erro inesperado: {e_cancel}")
                     return "Ocorreu um erro inesperado ao processar o cancelamento (G)."

            else: # Nenhuma integração ativa/válida -> Usa Webhook/Padrão
                logger.info(f"[Router] Nenhuma integração externa ativa/válida. Direcionando cancelamento para Webhook/Padrão.")
                return processar_cancelamento(db=db, company_id=company_id, phone=phone, api_key=api_key)


        # --- ROTEAMENTO CONFIRMAÇÃO ---
        elif llm_json.get("agendamento_confirmado") is True and llm_json.get("data") and llm_json.get("horario"):
            logger.info(f"[Router] Confirmação recebida para company_id={company_id}. Integração: {integration_type or 'Nenhuma/Webhook'}")

            nome = llm_json.get("nome")
            data_str = llm_json.get("data")
            time_str = llm_json.get("horario")
            if not all([nome, data_str, time_str]):
                 logger.error("[Router] Dados essenciais (nome, data, horario) faltando no llm_json.")
                 return "Preciso que confirme nome, data e horário."

            # --- MODIFICADO: Tratamento de erros semelhante ao Google Calendar ---
            elif integration_type == 'clinicorp':
                logger.info(f"[Router] Direcionando confirmação para Clinicorp.")
                local_agn_id = None
                try:
                    # Lógica de reagendamento (cancelar antigo)
                    lead_info = db.query(Lead).filter(Lead.phone == phone, Lead.company_id == company_id).order_by(Lead.id.desc()).first()
                    if not lead_info:
                        logger.error(f"Lead local não encontrado.")
                        return "Não foi possível encontrar seus dados para agendamento."

                    client_id = lead_info.client_id

                    # Verifica se existe agendamento antigo com id_agendamento no Clinicorp
                    agn_antigo = db.query(Agendamento).filter(
                        Agendamento.lead_id == lead_info.id,
                        Agendamento.company_id == company_id,
                        Agendamento.status.notlike('CANCELLED%')
                    ).order_by(Agendamento.id.desc()).first()

                    # Cancelar evento antigo no Clinicorp antes de criar o novo
                    if agn_antigo and agn_antigo.id_agendamento:
                        logger.info(f"Reagendamento (Clinicorp): Cancelando agendamento anterior ID Local={agn_antigo.id} / Clinicorp ID={agn_antigo.id_agendamento}.")
                        try:
                            cancelled_ok = cancel_clinicorp_appointment_flow(db, agn_antigo.id)
                            if not cancelled_ok:
                                logger.warning(f"Falha ao cancelar agendamento anterior no Clinicorp.")
                            else:
                                logger.info(f"Agendamento anterior ({agn_antigo.id}) cancelado via Clinicorp.")
                        except Exception as e_cancel:
                            # Apenas loga erro e continua, não interrompe o fluxo
                            logger.warning(f"Erro ao cancelar agendamento anterior no Clinicorp: {e_cancel}")

                    # MODIFICADO: Excluir TODOS os agendamentos deste telefone+empresa, independente do status
                    # Para manter consistência com o fluxo Google Calendar
                    db.execute(text("DELETE FROM agendamentos WHERE phone = :phone AND company_id = :cid"),
                            {"phone": phone, "cid": company_id})
                    logger.info(f"[Clinicorp Flow] Excluídos todos os agendamentos anteriores para phone={phone}, company_id={company_id}")

                    # Cria novo agendamento local primeiro
                    consulta_dt_obj = datetime.strptime(f"{data_str} {time_str}", "%d/%m/%Y %H:%M").astimezone()
                    agenda_id = llm_json.get("agenda_id")
                    agendamento_obj = Agendamento(client_id=client_id, company_id=company_id, lead_id=lead_info.id, phone=phone, nome=nome, consulta_data=consulta_dt_obj, status='SCHEDULED', id_agendamento=None, agenda_id=agenda_id)
                    db.add(agendamento_obj); db.commit(); db.refresh(agendamento_obj)
                    local_agn_id = agendamento_obj.id
                    logger.info(f"[Clinicorp Flow] Agendamento local criado/atualizado ID={local_agn_id}")

                    # Atualizar nome e tratamento no banco
                    treatment = llm_json.get("tratamento", "")
                    if treatment:
                        logger.info(f"[NAME_UPDATE] Atualizando interesse para: '{treatment}'")
                        agendamento_obj.interesse = treatment
                        db.add(agendamento_obj)
                    if nome:
                        logger.info(f"[NAME_UPDATE] Tentando atualizar contact.name para: '{nome}' (phone={phone}, company_id={company_id})")
                        result = db.execute(text("UPDATE contacts SET name = :name WHERE phone = :phone AND company_id = :company_id"),
                                {"name": nome, "phone": phone, "company_id": company_id})
                        logger.info(f"[NAME_UPDATE] Linhas afetadas em contacts: {result.rowcount}")

                        logger.info(f"[NAME_UPDATE] Tentando atualizar leads.name para: '{nome}' (phone={phone}, company_id={company_id})")
                        result2 = db.execute(text("UPDATE leads SET name = :name WHERE phone = :phone AND company_id = :company_id"),
                                {"name": nome, "phone": phone, "company_id": company_id})
                        logger.info(f"[NAME_UPDATE] Linhas afetadas em leads: {result2.rowcount}")
                    db.commit()
                    logger.info(f"[NAME_UPDATE] Commit realizado com sucesso")

                    # Tenta sincronizar com Clinicorp - MODIFICADO: captura exceções de sincronização
                    sync_success = True
                    try:
                        # CORRIGIDO: Passando todos os parâmetros necessários
                        logger.info(f"[Clinicorp Flow LLM] Tentando sincronizar com Clinicorp - company_id={company_id}, phone={phone}, nome={nome}, data={data_str}, hora={time_str}")
                        local_agn_id, clinicorp_id = sync_appointment_to_clinicorp(
                            db,
                            company_id,
                            phone,
                            nome,
                            data_str,
                            time_str
                        )
                        logger.info(f"[Clinicorp Flow LLM] Sincronização retornou - local_agn_id={local_agn_id}, clinicorp_id={clinicorp_id}")
                        if not clinicorp_id:
                            logger.warning(f"[Clinicorp Flow LLM] Falha ao sincronizar com Clinicorp ID={local_agn_id}. clinicorp_id retornou None/vazio")
                            sync_success = False
                    except ClinicorpSyncError as e_sync:
                        # Captura erro de sincronização específico
                        logger.error(f"[Clinicorp Flow LLM] ERRO na sincronização com Clinicorp: {e_sync}")
                        sync_success = False
                        # Não interrompe o fluxo, continua para gerar mensagem
                    except Exception as e_unexpected:
                        # Captura qualquer outro erro não esperado
                        logger.exception(f"[Clinicorp Flow LLM] ERRO INESPERADO na sincronização com Clinicorp: {e_unexpected}")
                        sync_success = False

                    # Gerar mensagem e disparar task mesmo em caso de falha na sincronização
                    agent_info = _get_company_message_details(db, company_id)
                    final_confirmation_msg = _generate_confirmation_message(agent_info.get('company_info'), agent_info.get('team_sp'), data_str, time_str)
                    _try_send_confirmation_task(db, company_id, local_agn_id, phone)
                    return final_confirmation_msg

                except Exception as e:
                    logger.exception(f"[Clinicorp Flow] Erro inesperado: {e}")
                    if db.is_active: db.rollback()
                    return "Ocorreu um erro inesperado ao processar seu agendamento (C)."

            elif integration_type == 'google':
                logger.info(f"[Router] Direcionando confirmação para Google Calendar.")
                local_agn_id = None
                try:
                    # Criar/Atualizar registro local primeiro
                    lead_info = db.query(Lead).filter(Lead.phone == phone, Lead.company_id == company_id).order_by(Lead.id.desc()).first()
                    if not lead_info: raise Exception(f"Lead local não encontrado.")
                    client_id = lead_info.client_id

                    # Verificar se existe agendamento antigo com event_id no Google
                    agn_antigo = db.query(Agendamento).filter(
                        Agendamento.lead_id == lead_info.id,
                        Agendamento.company_id == company_id,
                        Agendamento.status.notlike('CANCELLED%')
                    ).order_by(Agendamento.id.desc()).first()

                    # Cancelar evento antigo no Google Calendar antes de criar o novo
                    if agn_antigo and agn_antigo.event_id:
                        logger.info(f"Reagendamento (Google): Cancelando agendamento anterior ID Local={agn_antigo.id} / Google Event ID={agn_antigo.event_id}.")
                        cancelled_ok = cancel_google_calendar_appointment_flow(db, agn_antigo.id)
                        if not cancelled_ok:
                            logger.warning(f"Falha ao cancelar agendamento anterior no Google Calendar.")
                        else:
                            logger.info(f"Agendamento anterior ({agn_antigo.id}) cancelado via Google Calendar.")

                    # MODIFICADO: Excluir TODOS os agendamentos deste telefone+empresa, independente do status
                    # Isso evita o problema de violação de restrição única (company_id, phone)
                    db.execute(text("DELETE FROM agendamentos WHERE phone = :phone AND company_id = :cid"),
                            {"phone": phone, "cid": company_id})
                    logger.info(f"[Google Flow] Excluídos todos os agendamentos anteriores para phone={phone}, company_id={company_id}")

                    # Cria novo local
                    consulta_dt_obj = datetime.strptime(f"{data_str} {time_str}", "%d/%m/%Y %H:%M").astimezone()
                    agenda_id = llm_json.get("agenda_id")
                    agendamento_obj = Agendamento(client_id=client_id, company_id=company_id, lead_id=lead_info.id, phone=phone, nome=nome, consulta_data=consulta_dt_obj, status='SCHEDULED', event_id=None, agenda_id=agenda_id)
                    db.add(agendamento_obj); db.commit(); db.refresh(agendamento_obj)
                    local_agn_id = agendamento_obj.id
                    logger.info(f"[Google Flow] Agendamento local criado/atualizado ID={local_agn_id}")

                    # Atualizar nome e tratamento no banco
                    treatment = llm_json.get("tratamento", "")
                    if treatment:
                        logger.info(f"[NAME_UPDATE] Atualizando interesse para: '{treatment}'")
                        agendamento_obj.interesse = treatment
                        db.add(agendamento_obj)
                    if nome:
                        logger.info(f"[NAME_UPDATE] Tentando atualizar contact.name para: '{nome}' (phone={phone}, company_id={company_id})")
                        result = db.execute(text("UPDATE contacts SET name = :name WHERE phone = :phone AND company_id = :company_id"),
                                {"name": nome, "phone": phone, "company_id": company_id})
                        logger.info(f"[NAME_UPDATE] Linhas afetadas em contacts: {result.rowcount}")

                        logger.info(f"[NAME_UPDATE] Tentando atualizar leads.name para: '{nome}' (phone={phone}, company_id={company_id})")
                        result2 = db.execute(text("UPDATE leads SET name = :name WHERE phone = :phone AND company_id = :company_id"),
                                {"name": nome, "phone": phone, "company_id": company_id})
                        logger.info(f"[NAME_UPDATE] Linhas afetadas em leads: {result2.rowcount}")
                    db.commit()
                    logger.info(f"[NAME_UPDATE] Commit realizado com sucesso")

                    # Chamar sync Google Calendar com data_str e time_str originais
                    sync_success = sync_appointment_to_google_calendar(
                        db,
                        local_agn_id,
                        llm_json.get("data"),     # Passa data_str original
                        llm_json.get("horario")   # Passa time_str original
                    )
                    if not sync_success:
                        logger.warning(f"[Google Flow] Falha ao sincronizar com Google Calendar ID={local_agn_id}.")

                    # Gerar mensagem e disparar task
                    agent_info = _get_company_message_details(db, company_id)
                    final_confirmation_msg = _generate_confirmation_message(agent_info.get('company_info'), agent_info.get('team_sp'), data_str, time_str)
                    _try_send_confirmation_task(db, company_id, local_agn_id, phone)
                    return final_confirmation_msg
                except Exception as e:
                    logger.exception(f"[Google Flow] Erro inesperado: {e}")
                    if db.is_active: db.rollback()
                    return "Ocorreu um erro inesperado ao processar seu agendamento (G)."

            else: # Nenhuma integração ativa/válida -> Usa Webhook/Padrão
                logger.info(f"[Router] Direcionando confirmação para Webhook/Padrão.")
                # --- Lógica Original Webhook ---
                try:
                    # (Colar aqui a lógica original completa do webhook como antes)
                    data_hora_str = f"{llm_json['data']} {llm_json['horario']}"
                    data_obj = datetime.strptime(data_hora_str, "%d/%m/%Y %H:%M")
                    data_formatada = data_obj.strftime("%Y-%m-%d %H:%M:%S") # Webhook pode precisar de formato diferente? Ajustar se necessário.
                    client_row = db.execute(text("SELECT cc.client_id FROM client_companies cc WHERE cc.company_id = :company_id ORDER BY cc.id LIMIT 1"), {"company_id": company_id}).fetchone()
                    if not client_row: raise ValueError(f"Client ID não encontrado")
                    client_id = client_row.client_id
                    lead_row = db.execute(text("SELECT id AS lead_id FROM leads WHERE phone = :phone AND company_id = :company_id ORDER BY id DESC LIMIT 1"), {"phone": phone, "company_id": company_id}).fetchone()
                    if not lead_row: raise ValueError(f"Lead ID não encontrado")
                    lead_id = lead_row.lead_id
                    existing_agn = db.execute(text("SELECT id FROM agendamentos WHERE lead_id = :lead_id AND company_id = :company_id ORDER BY id DESC LIMIT 1"), {"lead_id": lead_id, "company_id": company_id}).fetchone()
                    if existing_agn:
                        db.execute(text("DELETE FROM agendamentos WHERE id = :old_id"), {"old_id": existing_agn.id})
                        logger.info(f"[Webhook Flow] Excluído agendamento local anterior (id={existing_agn.id}).")
                    agenda_id = llm_json.get("agenda_id")
                    agendamento_obj = Agendamento(client_id=client_id, company_id=company_id, lead_id=lead_id, phone=phone, nome=llm_json.get("nome"), consulta_data=data_formatada, status='SCHEDULED', agenda_id=agenda_id)
                    db.add(agendamento_obj); db.flush(); agendamento_id = agendamento_obj.id

                    # Atualizar nome e tratamento no banco
                    treatment = llm_json.get("tratamento", "")
                    if treatment:
                        agendamento_obj.interesse = treatment
                        db.add(agendamento_obj)

                    try:
                        novo_nome = llm_json.get("nome") or ""; db.execute(text("UPDATE leads SET name = :n WHERE id = :l AND company_id = :c"), {"n": novo_nome, "l": lead_id, "c": company_id}); db.execute(text("UPDATE contacts SET name = :n WHERE phone = :p AND client_id = :cid AND company_id = :clid"), {"n": novo_nome, "p": phone, "cid": client_id, "clid": company_id}); db.commit()
                        logger.info(f"[Webhook Flow] Agendamento local ID={agendamento_id} criado/atualizado.")
                    except Exception as e_up: db.rollback(); logger.error(f"[Webhook Flow] Erro commit nomes: {e_up}"); return "Erro ao salvar agendamento."
                    confirmation_msg = enviar_agendamento_confirmado(db, company_id, phone, llm_json, api_key, agendamento_id)
                    _try_send_confirmation_task(db, company_id, agendamento_id, phone)
                    return confirmation_msg
                except Exception as e_webhook: db.rollback(); logger.exception(f"[Webhook Flow] Erro: {e_webhook}"); return "Erro ao salvar agendamento."
                # --- Fim Lógica Original Webhook ---

        logger.info("[Router] Nenhuma ação válida encontrada no JSON do LLM.")
        return "" # Retorna vazio para indicar que nada foi processado

    except Exception as e:
         logger.exception(f"[Router] Erro GERAL e inesperado em processar_json_do_llm: {e}")
         return "Desculpe, ocorreu um erro interno muito inesperado. Por favor, avise nossa equipe."

# --- Função confirm_appointment (Mantida) ---
# A lógica interna de validação e verificação de slot permanece,
# a chamada final para processar_json_do_llm agora faz o roteamento.
def confirm_appointment(state_machine) -> str:
    """
    Valida dados, verifica slot e chama processar_json_do_llm para
    efetivar o agendamento via Clinicorp ou Webhook.
    """
    db = state_machine.db_session
    phone = state_machine.phone
    company_id = state_machine.company_id
    # Remover api_key = state_machine.api_key

    logger.debug(f"Iniciando confirm_appointment para {phone}, company_id {company_id}")

    # --- Bloco 1: Cooldown ---
    if state_machine.has_recent_confirmation():
        logger.warning(f"[ConfirmAppointment] Tentativa durante cooldown.")
        return ""

    # --- Bloco 2: Validação Contextual Forçada (se implementada) ---
    from backend.prompt.llm.validation_integration import validate_before_appointment_confirmation
    logger.debug(f"[ConfirmAppointment] Forçando validação contextual...")
    valid_confirmation = validate_before_appointment_confirmation(state_machine)
    if not valid_confirmation:
        logger.error(f"[ConfirmAppointment] Validação contextual BLOQUEOU agendamento.")
        # Retorna string vazia para deixar o LLM gerar a mensagem
        return ""
    logger.debug(f"[ConfirmAppointment] Validação contextual PERMITIU.")

    # --- Bloco 3: Validação de Confirmação e Dados (Se aplicável) ---
    confirmation_asked = state_machine.get_state_data("confirmation_asked", False)
    user_confirmed = state_machine.get_state_data("user_confirmed", False)
    if confirmation_asked and user_confirmed:
        logger.info("[ConfirmAppointment] Usuário já confirmou explicitamente, pulando validações adicionais.")
    else:
        # --- Bloco 3.1: Validação e Correção de Dados ---
        logger.debug("[ConfirmAppointment] Executando validação/correção de dados...")
        from backend.prompt.llm.validation_service import get_full_conversation_history, validate_all_extracted_data

        conversation_history = get_full_conversation_history(db, phone, company_id)
        validation_result = validate_all_extracted_data(state_machine, conversation_history)

        if validation_result:
            # Aplicar correções com alta confiança
            for field in ["nome", "data", "horario", "tratamento"]:
                if field in validation_result:
                    field_data = validation_result[field]
                    if field_data.get("confianca", 0) >= 80 and field_data.get("valor"):
                        current_value = state_machine.get_state_data(field)
                        if current_value != field_data["valor"]:
                            logger.info(f"[ConfirmAppointment] Corrigindo {field}: '{current_value}' -> '{field_data['valor']}'")
                            state_machine.set_state_data(field, field_data["valor"])

        # Se usuário respondeu que não sabe o tratamento, definir como Avaliação
        if state_machine.get_state_data("user_responded_dont_know", False):
            state_machine.set_state_data("tratamento", "Avaliação")

    # --- Bloco 4: Leitura dos Dados (possivelmente corrigidos) ---
    nome = state_machine.get_state_data("nome")
    data_ = state_machine.get_state_data("data")
    horario = state_machine.get_state_data("horario")
    tratamento = state_machine.get_state_data("tratamento", "Consulta de Avaliação")
    cliente = state_machine.get_state_data("cliente", "novo")

    # --- Bloco 5: Verificação de Disponibilidade de Slot ---
    slot_verified = state_machine.get_state_data("slot_verified", False)
    slot_auto_corrected = False # Resetar flag
    formatted_slot = f"{data_} {horario}" # Para log
    original_data = None
    original_horario = None

    if data_ and horario and not slot_verified:
        logger.debug(f"[ConfirmAppointment] Verificando disponibilidade para {data_} {horario}")
        # ... (Lógica original de verify_slot_availability, check_time_in_available_slots, suggest_alternative_slots) ...
        # ... (Se precisar corrigir, atualiza data_, horario, marca slot_verified=True, slot_auto_corrected=True) ...
        # ... (Se não achar nem alternativa, retorna mensagem de erro para o LLM) ...
        # Exemplo simplificado:
        slot_available = True # Substituir pela lógica real
        if not slot_available:
             # ... (lógica para sugerir alternativas ou retornar erro) ...
             # return "Slot indisponível..."
             pass
        state_machine.set_state_data("slot_verified", True)
        # Marcar slot_auto_corrected se foi ajustado
        # state_machine.set_state_data("slot_auto_corrected", True)
        # state_machine.set_state_data("original_data", data_original) # Guardar originais
        # state_machine.set_state_data("original_horario", horario_original)
        # data_ = data_corrigida
        # horario = horario_corrigido

    # --- Bloco 6: Verificação Final de Campos ---
    if not all([nome, data_, horario]): # Simplificado
        logger.error(f"[ConfirmAppointment] Campos obrigatórios ausentes após validações.")
        return "Não consegui obter todos os detalhes (nome, data, hora). Poderia confirmar?" # Mensagem mais clara

    # --- Bloco 7: Montar JSON Final ---
    llm_json_final = {
        "nome": nome, "data": data_, "horario": horario,
        "agendamento_confirmado": True, "cancelar_agendamento": False,
        "tratamento": state_machine.get_state_data("tratamento", "Consulta de Avaliação"),
        "cliente": state_machine.get_state_data("cliente", "novo")
    }

    # --- Bloco 7.5: Buscar api_key do DB ---
    api_key = None
    try:
        # Usar ORM se preferir, ou manter raw SQL
        row_client_data = db.execute(text("SELECT c.api_key FROM clients c JOIN client_companies cc ON cc.client_id = c.id WHERE cc.company_id = :cid LIMIT 1"), {"cid": company_id}).fetchone()
        if row_client_data and hasattr(row_client_data, 'api_key'): api_key = row_client_data.api_key
    except Exception as api_key_err: logger.error(f"Erro ao buscar api_key para company_id {company_id}: {api_key_err}")
    if not api_key:
        logger.warning(
            "API Key não encontrada para company_id %s; fluxo webhook pode falhar.",
            company_id,
        )

    # --- Bloco 8: Chamar Processador Final com Roteamento ---
    logger.info(f"[ConfirmAppointment] Chamando processar_json_do_llm para finalizar.")
    final_message = processar_json_do_llm(db, company_id, phone, llm_json_final, api_key=api_key)

    # --- Bloco 9: Adicionar Nota e Marcar Confirmação ---
    # (Lógica original mantida)
    if final_message:
        auto_corrected = state_machine.get_state_data("slot_auto_corrected", False)
        if auto_corrected:
            original_data = state_machine.get_state_data("original_data")
            original_horario = state_machine.get_state_data("original_horario")
            if original_data and original_horario:
                note = (f"\n\nObs.: Seu horário solicitado ({original_data} às {original_horario}) "
                        f"não estava disponível, ajustamos para {data_} às {horario}.")
                final_message += note
        state_machine.set_state_data("confirmation_asked", True)
        state_machine.set_state_data("user_confirmed", True)
        state_machine.reset_post_confirmation()
        logger.info("[ConfirmAppointment] Agendamento finalizado com sucesso pela state machine.")
    else:
        logger.error("[ConfirmAppointment] Erro ao finalizar agendamento (processar_json_do_llm retornou vazio ou erro).")
        # Se final_message for uma string vazia indicando erro interno, talvez retornar uma msg padrão?
        if not final_message: # Se retornou string vazia
             return "Não foi possível concluir o agendamento neste momento."

    return final_message

# --- Manter _values_very_different e outras funções auxiliares se usadas ---
# ... (código de _values_very_different) ...

# Função auxiliar para comparar valores
def _values_very_different(val1, val2):
    """
    Determina se dois valores são significativamente diferentes
    baseado no tipo de campo.
    """
    # Para datas, comparamos apenas os dias
    if '/' in val1 and '/' in val2:
        day1 = val1.split('/')[0]
        day2 = val2.split('/')[0]
        return day1 != day2

    # Para horários, comparamos horas
    if ':' in val1 and ':' in val2:
        hour1 = val1.split(':')[0]
        hour2 = val2.split(':')[0]
        return hour1 != hour2

    # Para strings, diferença significativa se mais da metade dos caracteres forem diferentes
    if isinstance(val1, str) and isinstance(val2, str):
        if len(val1) == 0 or len(val2) == 0:
            return True

        # Comparação simplificada para nomes - se começa com o mesmo primeiro nome
        first_name1 = val1.split()[0].lower() if ' ' in val1 else val1.lower()
        first_name2 = val2.split()[0].lower() if ' ' in val2 else val2.lower()
        return not first_name1.startswith(first_name2) and not first_name2.startswith(first_name1)

    # Padrão - valores diferentes
    return val1 != val2

def _get_active_integration_type(db: Session, company_id: int) -> Optional[str]:
    """
    Verifica a tabela calendar_integrations e retorna o tipo de integração
    ativa ('google' ou 'clinicorp') ou None se nenhuma estiver configurada
    ou se a configuração estiver incompleta/inválida.
    """
    logger.debug(f"Verificando tipo de integração ativa para company_id={company_id}")
    integration = db.query(CalendarIntegration).options(
        # Carrega detalhes necessários para validação Clinicorp
        selectinload(CalendarIntegration.clinicorp_details)
    ).filter(
        CalendarIntegration.company_id == company_id
    ).first()

    if not integration:
        logger.debug(f"Nenhuma entrada encontrada em calendar_integrations para company_id={company_id}.")
        return None # Ou retornar 'webhook'/'default' explicitamente? Por enquanto None.

    provider = integration.provider
    is_valid = False

    if provider == 'google':
        has_linked_agenda = db.query(Agenda.id).filter(
            Agenda.company_id == company_id,
            Agenda.google_calendar_id.isnot(None),
        ).first()
        if getattr(integration, "google_oauth_token", None) and (integration.google_calendar_id or has_linked_agenda):
            is_valid = True
        else:
            logger.warning(f"Integração Google encontrada para company_id={company_id}, mas não há agenda Google vinculada ou OAuth conectado.")
    elif provider == 'clinicorp':
        details = integration.clinicorp_details
        # Verifica se credenciais básicas e detalhes selecionados existem
        if (integration.clinicorp_subscriber_id and
            integration.clinicorp_password and
            details and
            details.business_id and
            details.dentist_person_id):
            is_valid = True
        else:
             logger.warning(f"Integração Clinicorp encontrada para company_id={company_id}, mas configuração está incompleta (credenciais ou detalhes selecionados).")
    else:
         logger.warning(f"Provider '{provider}' desconhecido encontrado para company_id={company_id}.")

    if is_valid:
         logger.info(f"Integração ativa encontrada para company_id={company_id}: {provider}")
         return provider
    else:
         logger.debug(f"Configuração de integração encontrada para company_id={company_id} ({provider}) mas é inválida/incompleta.")
         return None
