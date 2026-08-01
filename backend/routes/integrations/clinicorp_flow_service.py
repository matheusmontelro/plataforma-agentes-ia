
import logging
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import text
from datetime import datetime, timedelta # Adicionado timedelta
from typing import Optional, Tuple, Dict, Any

# Importar modelos do nosso banco de dados
from backend.models import CalendarIntegration, ClinicorpDetails, Lead, Contact, Agendamento, AgentConfiguration
# Importar funções do serviço de API Clinicorp
from backend.routes.integrations.clinicorp_service import (
    get_clinicorp_customer,
    create_clinicorp_customer,
    create_clinicorp_appointment,
    cancel_clinicorp_appointment_api
)
# Opcional: Importar task Celery se ainda for usada no final do fluxo
# from backend.worker.tasks_confirmation import enviar_passo_confirmacao

logger = logging.getLogger(__name__)

# --- Constantes de Status de Sincronização ---
CLINICORP_SYNC_STATUS_SYNCED = "SYNCED"
CLINICORP_SYNC_STATUS_FAILED = "FAILED"
CLINICORP_SYNC_STATUS_CANCELLED = "CANCELLED"
CLINICORP_SYNC_STATUS_CANCEL_FAILED = "CANCEL_FAILED"
CLINICORP_SYNC_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

# --- Exceção Customizada ---
class ClinicorpSyncError(Exception):
    """Exceção para erros específicos durante a sincronização com Clinicorp."""
    pass

# --- Funções Auxiliares (Helpers) ---

def _get_clinicorp_credentials(db: Session, company_id: int) -> Tuple[str, str, int, int, int]:
    """
    Busca credenciais (subscriber_id, token), IDs (business_id, dentist_id)
    E a duração da consulta (consultation_duration) da integração Clinicorp.
    Retorna: subscriber_id, api_token, business_id, dentist_id, duration_minutes
    """
    # ... (código para buscar integration e details como antes) ...
    integration = db.query(CalendarIntegration).options(selectinload(CalendarIntegration.clinicorp_details)).filter(CalendarIntegration.company_id == company_id, CalendarIntegration.provider == 'clinicorp').first()
    if not integration: raise ClinicorpSyncError(f"Integração Clinicorp não configurada para company_id={company_id}.")
    subscriber_id = integration.clinicorp_subscriber_id
    api_token = integration.clinicorp_password
    details = integration.clinicorp_details
    if not subscriber_id or not api_token: raise ClinicorpSyncError(f"Credenciais Clinicorp ausentes para company_id={company_id}.")
    if not details or not details.business_id or not details.dentist_person_id: raise ClinicorpSyncError(f"IDs selecionados (Business/Dentist) não encontrados para company_id={company_id}.")

    # Buscar Configuração de Agendamento (AgentConfiguration)
    duration_minutes = 60 # Default caso não encontre
    agent_config = db.query(AgentConfiguration).filter(AgentConfiguration.company_id == company_id).first()

    if agent_config and agent_config.scheduling_config and isinstance(agent_config.scheduling_config, dict):
        # --- CORREÇÃO AQUI: Usar a chave correta 'consultation_duration' ---
        extracted_duration = agent_config.scheduling_config.get("consultation_duration")
        # ---------------------------------------------------------------
        if isinstance(extracted_duration, (int, float)) and extracted_duration > 0:
            duration_minutes = int(extracted_duration)
            logger.debug(f"Duração da consulta encontrada ('consultation_duration'): {duration_minutes} minutos.")
        else:
            # Log se a chave existe mas tem valor inválido (ex: 0, string, null)
            if "consultation_duration" in agent_config.scheduling_config:
                 logger.warning(f"Valor inválido ('{extracted_duration}') para 'consultation_duration' no scheduling_config company_id={company_id}. Usando default: {duration_minutes} min.")
            else: # Log se a chave não existe
                 logger.warning(f"Chave 'consultation_duration' não encontrada no scheduling_config para company_id={company_id}. Usando default: {duration_minutes} min.")
    else:
        logger.warning(f"AgentConfiguration ou scheduling_config não encontrado/válido para company_id={company_id}. Usando default: {duration_minutes} min.")

    logger.debug(f"Credenciais/IDs/Duração encontrados para company_id={company_id}")
    return subscriber_id, api_token, details.business_id, details.dentist_person_id, duration_minutes

def _format_phone_for_clinicorp_appointment(phone: Optional[str]) -> Optional[str]:
    """
    Formata o número de telefone para ser enviado na criação/reagendamento
    de agendamentos no Clinicorp, removendo o prefixo '55' se existir.

    Args:
        phone: O número de telefone original (string).

    Returns:
        O número de telefone formatado (string) ou o original se não
        começar com '55' ou for None/vazio.
    """
    if phone and phone.startswith('55'):
        formatted_phone = phone[2:]
        logger.info(f"FORMATANDO TELEFONE APP: Removendo prefixo '55' do telefone para payload de agendamento Clinicorp. Original: {phone}, Formatado: {formatted_phone}")
        return formatted_phone
    # Retorna o telefone original se for None, vazio ou não começar com '55'
    return phone

def _get_lead_info(db: Session, phone: str, company_id: int) -> Tuple[int, int, str, Optional[str], Optional[int]]:
    """
    Busca informações do lead no nosso banco (tabela leads).
    Retorna: lead_id, client_id, name, email, clinicorp_customer_id (se já existir)
    Lança ClinicorpSyncError se lead não existe.
    """
    logger.debug(f"Buscando lead local: phone={phone}, company_id={company_id}")
    # Adicionar busca do clinicorp_customer_id se você salvar ele na tabela leads
    lead_record = db.query(Lead).filter(
        Lead.phone == phone, Lead.company_id == company_id
    ).order_by(Lead.id.desc()).first()

    if not lead_record:
        # O que fazer se o lead não existe localmente? Criar? Falhar?
        # Por ora, vamos falhar, pois o agendamento depende de um lead existente.
        raise ClinicorpSyncError(f"Lead não encontrado em nosso sistema para phone={phone}, company_id={company_id}.")

    nome_lead = lead_record.name if lead_record.name else "Nome não informado"
    email_lead = getattr(lead_record, 'email', None) # Exemplo seguro de pegar email se existir
    # Assumindo que você adicionará uma coluna 'clinicorp_customer_id' à tabela Lead
    clinicorp_customer_id = getattr(lead_record, 'clinicorp_customer_id', None)

    logger.debug(f"Lead local encontrado: ID={lead_record.id}, ClientID={lead_record.client_id}, ClinicorpCustomerID={clinicorp_customer_id}")
    return lead_record.id, lead_record.client_id, nome_lead, email_lead, clinicorp_customer_id

def _format_datetime_for_clinicorp(date_str: str, time_str: str, duration_minutes: int = 60) -> Tuple[str, str, str]:
    """
    Formata data/hora DD/MM/YYYY HH:MM para ISO com offset local e HH:MM (From/To).
    Usa duration_minutes para calcular o toTime.
    """
    logger.debug(f"Formatando data/hora: {date_str} {time_str} com duração: {duration_minutes} min")
    try:
        dt_obj_naive = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
        # Torna aware usando timezone local do servidor
        # ATENÇÃO: Se o servidor e a empresa estiverem em fusos diferentes,
        # idealmente buscaríamos o timezone da empresa e usaríamos pytz ou zoneinfo aqui.
        dt_obj_aware = dt_obj_naive.astimezone()
        # Formato ISO 8601 com offset (ex: -03:00). Clinicorp parece preferir isso a 'Z'
        iso_date_str = dt_obj_aware.isoformat(timespec='milliseconds')

        from_time = dt_obj_aware.strftime("%H:%M")
        # Calcula to_time usando a duração fornecida
        to_time_obj = dt_obj_aware + timedelta(minutes=duration_minutes)
        to_time = to_time_obj.strftime("%H:%M")

        logger.debug(f"Data/Hora formatada: ISO={iso_date_str}, From={from_time}, To={to_time}")
        return iso_date_str, from_time, to_time
    except (ValueError, TypeError) as e:
        logger.error(f"Erro ao formatar data/hora '{date_str} {time_str}' com duração {duration_minutes}: {e}")
        raise ClinicorpSyncError(f"Formato de data ou hora inválido: {date_str} {time_str}")

def _update_local_db_after_sync(
    db: Session,
    lead_id: int,
    client_id: int,
    company_id: int,
    phone: str,
    name: str,
    consulta_dt_obj: datetime,
    clinicorp_appointment_id: int,
    clinicorp_customer_id: Optional[int],
    clinicorp_sync_status: str = CLINICORP_SYNC_STATUS_SYNCED  # Novo parâmetro com valor padrão
    ) -> int:
    """Deleta agendamentos locais antigos, insere o novo com IDs Clinicorp, atualiza nomes."""
    logger.debug(f"Atualizando DB local para lead_id={lead_id}, company_id={company_id}")
    try:
        # 1. Excluir agendamentos locais anteriores (lógica mantida)
        deleted = db.query(Agendamento).filter(
            Agendamento.lead_id == lead_id,
            Agendamento.company_id == company_id
        ).delete(synchronize_session=False)
        if deleted > 0:
             logger.info(f"Excluídos {deleted} agendamentos locais antigos para lead_id={lead_id}, company_id={company_id}")

        # 2. Criar novo registro de agendamento local
        novo_agendamento = Agendamento(
            client_id=client_id,
            company_id=company_id,
            lead_id=lead_id,
            phone=phone,
            nome=name,
            consulta_data=consulta_dt_obj,
            status='SCHEDULED',
            id_agendamento=str(clinicorp_appointment_id),
            customer_id=str(clinicorp_customer_id) if clinicorp_customer_id else None,
            clinicorp_sync_status=clinicorp_sync_status  # Define o status de sincronização
        )
        db.add(novo_agendamento)
        db.flush()
        local_agn_id = novo_agendamento.id
        logger.info(f"Criado novo agendamento local ID={local_agn_id} com ID Clinicorp Agend={clinicorp_appointment_id}, Cliente={clinicorp_customer_id}, Sync Status={clinicorp_sync_status}")

        # Resto do código permanece igual...
        # 3. Atualizar nomes
        db.query(Lead).filter(Lead.id == lead_id).update({"name": name}, synchronize_session=False)
        db.query(Contact).filter(
            Contact.phone == phone, Contact.company_id == company_id
        ).update({"name": name}, synchronize_session=False)

        db.commit()
        logger.info(f"Banco de dados local atualizado para agendamento {local_agn_id}.")
        return local_agn_id

    except Exception as e:
        db.rollback()
        logger.exception(f"Erro ao atualizar banco de dados local após sync Clinicorp: {e}")
        raise ClinicorpSyncError(f"Falha ao atualizar o banco de dados interno: {e}")

# --- Função Principal de Sincronização de Agendamento ---
def sync_appointment_to_clinicorp(
    db: Session,
    company_id: int,
    phone: str,
    name: str,
    date_str: str,
    time_str: str
) -> Tuple[int, int]:
    """
    Orquestra a criação/atualização de cliente e agendamento no Clinicorp
    e atualiza o banco de dados local (salvando IDs em agendamentos).
    """
    logger.info(f"Iniciando sync com Clinicorp para {phone} em {date_str} {time_str}")
    try:
        # 1. Obter Credenciais, IDs e Duração
        subscriber_id, api_token, business_id, dentist_id, duration_minutes = _get_clinicorp_credentials(db, company_id)

        # 2. Obter informações do Lead local
        lead_id, client_id, lead_name, lead_email, _ = _get_lead_info(db, phone, company_id)
        customer_name_to_use = name if name else lead_name

        # 3. Verificar/Criar Cliente no Clinicorp
        clinicorp_customer_id = None # Reinicia aqui
        try:
             # Tenta buscar pelo telefone
             customer_info = get_clinicorp_customer(subscriber_id, api_token, identifier_field="Phone", identifier_value=phone)
             if customer_info and customer_info.get("CustomerId"):
                  clinicorp_customer_id = customer_info["CustomerId"]
                  logger.info(f"Cliente encontrado no Clinicorp pelo telefone: ID={clinicorp_customer_id}")
             else:
                  logger.info(f"Cliente não encontrado no Clinicorp ({phone}). Criando novo...")
                  phone_for_customer_payload = _format_phone_for_clinicorp_appointment(phone)
                  logger.info(f"Telefone formatado para CRIAÇÃO do cliente: {phone_for_customer_payload}")
                  create_payload = { "Name": customer_name_to_use, "MobilePhone": phone_for_customer_payload, "Email": lead_email or "" }
                  created_customer = create_clinicorp_customer(subscriber_id, api_token, create_payload)
                  clinicorp_customer_id = created_customer.get("CustomerId")
                  if not clinicorp_customer_id: raise ClinicorpSyncError("Falha ao obter CustomerId após criação.")
                  logger.info(f"Cliente criado no Clinicorp com ID: {clinicorp_customer_id}")

        except Exception as e:
             detail = getattr(e, 'detail', str(e))
             raise ClinicorpSyncError(f"Falha ao verificar/criar cliente no Clinicorp: {detail}")

        if not clinicorp_customer_id: raise ClinicorpSyncError("ID Cliente Clinicorp não obtido.")

        # 4. Criar Agendamento no Clinicorp
        try:
            iso_date, from_time, to_time = _format_datetime_for_clinicorp(date_str, time_str, duration_minutes)
            phone_for_appointment_payload = _format_phone_for_clinicorp_appointment(phone)
            appointment_payload = {
                "Company_BusinessId": business_id, "Dentist_PersonId": dentist_id,
                "Customer_PersonId": clinicorp_customer_id, "date": iso_date,
                "fromTime": from_time, "toTime": to_time,
                "CustomerName": customer_name_to_use, "MobilePhone": phone_for_appointment_payload, "Email": lead_email or ""
            }
            created_appointment = create_clinicorp_appointment(subscriber_id, api_token, appointment_payload)
            clinicorp_appointment_id = created_appointment.get("id")
            if not clinicorp_appointment_id: raise ClinicorpSyncError("Falha ao obter ID agendamento Clinicorp.")
            logger.info(f"Agendamento criado no Clinicorp com ID: {clinicorp_appointment_id}")
        except Exception as e:
             detail = getattr(e, 'detail', str(e))
             raise ClinicorpSyncError(f"Falha ao criar agendamento no Clinicorp: {detail}")

        # Após criar com sucesso no Clinicorp, define status como SYNCED
        sync_status = CLINICORP_SYNC_STATUS_SYNCED
        logger.info(f"Definindo clinicorp_sync_status: {sync_status}")

        # 5. Atualizar Banco de Dados Local com status de sincronização
        try:
             consulta_dt_obj = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M").astimezone()
             local_appointment_id = _update_local_db_after_sync(
                 db=db, lead_id=lead_id, client_id=client_id, company_id=company_id, phone=phone,
                 name=customer_name_to_use, consulta_dt_obj=consulta_dt_obj,
                 clinicorp_appointment_id=clinicorp_appointment_id,
                 clinicorp_customer_id=clinicorp_customer_id,
                 clinicorp_sync_status=sync_status
             )
        except Exception as e:
             raise ClinicorpSyncError(f"Falha ao atualizar o banco de dados local: {e}")

        logger.info(f"Sincronização com Clinicorp concluída para agendamento local {local_appointment_id}. Sucesso API Clinicorp: True")
        return local_appointment_id, clinicorp_appointment_id

    except ClinicorpSyncError as sync_error:
        logger.error(f"[ERRO SYNC CLINICORP] company_id={company_id}, phone={phone}: {sync_error}")
        raise # Re-lança para a camada superior (API route ou quem chamou) tratar
    except Exception as e:
         logger.exception(f"[ERRO INESPERADO SYNC CLINICORP] company_id={company_id}, phone={phone}: {e}")
         # Encapsula erro inesperado
         raise ClinicorpSyncError(f"Erro inesperado durante sincronização: {e}")

# --- Função Principal de Cancelamento ---
def cancel_clinicorp_appointment_flow(db: Session, local_appointment_id: int) -> bool:
    """
    Busca um agendamento local pelo seu ID, cancela no Clinicorp (se tiver ID associado)
    e atualiza o status local.

    Retorna True se o cancelamento foi bem-sucedido (ou se não precisou cancelar no Clinicorp),
    False se houve falha na API Clinicorp ou erro no processo.
    """
    logger.info(f"Iniciando fluxo de cancelamento Clinicorp para agendamento local ID: {local_appointment_id}")
    try:
         # 1. Buscar agendamento local e ID Clinicorp
         agn = db.query(Agendamento).filter(Agendamento.id == local_appointment_id).first()
         if not agn:
              logger.error(f"Cancelamento: Agendamento local ID={local_appointment_id} não encontrado.")
              return False

         company_id = agn.company_id
         clinicorp_appointment_id_str = agn.id_agendamento

         # 2. Se não há ID Clinicorp, HARD DELETE local apenas
         if not clinicorp_appointment_id_str:
             logger.warning(f"Agendamento local ID={local_appointment_id} não possui ID Clinicorp. Executando HARD DELETE apenas local.")
             db.delete(agn)
             db.commit()
             logger.info(f"Agendamento local ID={local_appointment_id} EXCLUÍDO fisicamente (sem integração Clinicorp).")
             return True

         try:
             clinicorp_appointment_id = int(clinicorp_appointment_id_str)
         except (ValueError, TypeError):
             logger.error(f"ID Clinicorp salvo ({clinicorp_appointment_id_str}) para agendamento local {local_appointment_id} é inválido.")
             agn.status = 'CANCELLED_INVALID_EXT_ID'
             agn.clinicorp_sync_status = CLINICORP_SYNC_STATUS_FAILED  # Define status de sync como falha
             db.commit()
             return False

         # 3. Obter Credenciais Clinicorp
         try:
              subscriber_id, api_token, _, _, _ = _get_clinicorp_credentials(db, company_id)
         except ClinicorpSyncError as cred_error:
              logger.error(f"Erro ao obter credenciais para cancelar agendamento Clinicorp ID={clinicorp_appointment_id}: {cred_error}")
              agn.status = 'CANCELLED_NO_CREDS'
              agn.clinicorp_sync_status = CLINICORP_SYNC_STATUS_FAILED  # Define status de sync como falha
              db.commit()
              return False

         # 4. Chamar API de Cancelamento Clinicorp
         logger.info(f"Tentando cancelar agendamento Clinicorp ID={clinicorp_appointment_id}")
         success_api = cancel_clinicorp_appointment_api(subscriber_id, api_token, clinicorp_appointment_id)

         # 5. HARD DELETE - Excluir fisicamente do banco após cancelamento
         if success_api:
             logger.info(f"Executando HARD DELETE do agendamento local ID={local_appointment_id} após sucesso na API Clinicorp.")
             db.delete(agn)
             db.commit()
             logger.info(f"Agendamento local ID={local_appointment_id} EXCLUÍDO fisicamente do banco.")
         else:
             agn.status = 'CANCELLED_API_FAILED'
             agn.clinicorp_sync_status = CLINICORP_SYNC_STATUS_CANCEL_FAILED
             db.commit()
             logger.warning(f"Falha na API ao cancelar Clinicorp ID={clinicorp_appointment_id}. Mantendo registro com status de falha.")

         return success_api

    except ClinicorpSyncError as sync_error:
         logger.error(f"[ERRO CANCEL SYNC CLINICORP] {sync_error}")
         db.rollback()
         return False
    except Exception as e:
         logger.exception(f"Erro inesperado no fluxo de cancelamento Clinicorp para agendamento local ID {local_appointment_id}: {e}")
         db.rollback()
         return False

# --- NOVA FUNÇÃO PARA REAGENDAMENTO VIA PUT - CORRIGIDA ---
def reschedule_clinicorp_appointment(
    db: Session,
    local_appointment_id: int, # ID do agendamento NO NOSSO BANCO
    new_name: str,             # Novo nome (pode ser o mesmo)
    new_date_str: str,         # Nova data "DD/MM/YYYY"
    new_time_str: str          # Nova hora "HH:MM"
) -> bool:
    """
    Orquestra um reagendamento no Clinicorp para um agendamento local existente.
    1. Cancela o agendamento antigo no Clinicorp (se existir vínculo).
    2. Busca/Cria o cliente correspondente no Clinicorp.
    3. Cria o novo agendamento no Clinicorp.
    4. ATUALIZA o registro local existente com os novos dados e IDs Clinicorp.

    Retorna True em sucesso completo, False em caso de falha em qualquer etapa crítica.
    Lança ClinicorpSyncError internamente em caso de falhas, que são convertidas para False no retorno final (ou tratadas pelo chamador).
    """
    log_prefix = f"[Reschedule Flow][Local ID: {local_appointment_id}]"
    logger.info(f"{log_prefix} Iniciando reagendamento para {new_date_str} {new_time_str}")

    # Buscar agendamento local que será atualizado
    agn_local = db.query(Agendamento).filter(Agendamento.id == local_appointment_id).first()
    if not agn_local:
        logger.error(f"{log_prefix} Agendamento local não encontrado.")
        # Retornar False ou lançar erro? Lançar erro é mais explícito.
        raise ClinicorpSyncError("Agendamento local não encontrado para reagendamento.")

    company_id = agn_local.company_id
    phone = agn_local.phone
    old_clinicorp_appointment_id_str = agn_local.id_agendamento # ID Clinicorp antigo (pode ser None)

    try:
        # 1. Obter Credenciais, IDs Selecionados e Duração
        subscriber_id, api_token, business_id, dentist_id, duration_minutes = _get_clinicorp_credentials(db, company_id)

        # 2. Cancelar Agendamento Antigo no Clinicorp (SE existir ID salvo)
        if old_clinicorp_appointment_id_str:
            logger.info(f"{log_prefix} Tentando cancelar agendamento Clinicorp anterior ID: {old_clinicorp_appointment_id_str}")
            try:
                old_clinicorp_appointment_id = int(old_clinicorp_appointment_id_str)
                cancel_success = cancel_clinicorp_appointment_api(subscriber_id, api_token, old_clinicorp_appointment_id)
                if not cancel_success:
                    # Se falhar, logamos mas podemos decidir continuar ou não.
                    # Para reagendamento, o ideal é abortar se o cancelamento falha.
                    logger.error(f"{log_prefix} Falha ao cancelar agendamento anterior {old_clinicorp_appointment_id} no Clinicorp.")
                    raise ClinicorpSyncError("Falha ao cancelar o agendamento anterior na agenda externa.")
                logger.info(f"{log_prefix} Agendamento Clinicorp anterior {old_clinicorp_appointment_id} cancelado com sucesso.")
            except (ValueError, TypeError):
                 logger.error(f"{log_prefix} ID Clinicorp anterior ('{old_clinicorp_appointment_id_str}') inválido. Não é possível cancelar.")
                 raise ClinicorpSyncError("ID do agendamento externo anterior é inválido.")
        else:
            logger.info(f"{log_prefix} Agendamento local não possuía ID Clinicorp. Pulando cancelamento externo.")

        # 3. Buscar/Criar Cliente no Clinicorp
        # Busca info do lead local (precisa existir)
        lead_id, client_id, lead_name, lead_email, _ = _get_lead_info(db, phone, company_id)
        customer_name_to_use = new_name if new_name else lead_name # Usa o nome passado (novo) se existir

        # Tenta pegar o ID do cliente do próprio agendamento local (pode ter sido salvo antes)
        clinicorp_customer_id = None
        if agn_local.customer_id:
             try:
                 clinicorp_customer_id = int(agn_local.customer_id)
                 logger.info(f"{log_prefix} Usando ID Cliente Clinicorp do agendamento local: {clinicorp_customer_id}")
             except (ValueError, TypeError):
                 logger.warning(f"{log_prefix} customer_id salvo localmente ('{agn_local.customer_id}') é inválido. Buscando na API.")
                 clinicorp_customer_id = None # Força a busca na API

        if not clinicorp_customer_id: # Se não tinha no agendamento local ou era inválido
            customer_info = get_clinicorp_customer(subscriber_id, api_token, "Phone", phone)
            if customer_info and customer_info.get("CustomerId"):
                clinicorp_customer_id = customer_info["CustomerId"]
                logger.info(f"{log_prefix} Cliente encontrado no Clinicorp: ID={clinicorp_customer_id}")
            else:
                logger.info(f"{log_prefix} Cliente não encontrado no Clinicorp. Criando...")
                phone_for_customer_payload = _format_phone_for_clinicorp_appointment(phone)
                logger.info(f"Telefone formatado para CRIAÇÃO do cliente: {phone_for_customer_payload}")
                create_payload = {"Name": customer_name_to_use, "MobilePhone": phone_for_customer_payload, "Email": lead_email or ""}
                # TODO: Adicionar outros campos se disponíveis e necessários para criação
                created_customer = create_clinicorp_customer(subscriber_id, api_token, create_payload)
                clinicorp_customer_id = created_customer.get("CustomerId") # create_clinicorp_customer já verifica e garante CustomerId
                if not clinicorp_customer_id: raise ClinicorpSyncError("Falha ao obter CustomerId após criação no Clinicorp.")
                logger.info(f"{log_prefix} Cliente criado Clinicorp ID={clinicorp_customer_id}")

        if not clinicorp_customer_id: raise ClinicorpSyncError("ID do Cliente Clinicorp não obtido.")

        # 4. Formatar Nova Data/Hora
        new_iso_date, new_from_time, new_to_time = _format_datetime_for_clinicorp(new_date_str, new_time_str, duration_minutes)
        phone_for_appointment_payload = _format_phone_for_clinicorp_appointment(phone) # 'phone' foi pego do agn_local

        # 5. Criar Novo Agendamento no Clinicorp
        new_appointment_payload = {
            "Company_BusinessId": business_id, "Dentist_PersonId": dentist_id,
            "Customer_PersonId": clinicorp_customer_id, "date": new_iso_date,
            "fromTime": new_from_time, "toTime": new_to_time,
            "CustomerName": customer_name_to_use, "MobilePhone": phone_for_appointment_payload, "Email": lead_email or ""
        }
        created_appointment = create_clinicorp_appointment(subscriber_id, api_token, new_appointment_payload)
        new_clinicorp_appointment_id = created_appointment.get("id") # create_clinicorp_appointment já verifica e garante 'id'
        if not new_clinicorp_appointment_id: raise ClinicorpSyncError("Falha ao criar novo agendamento no Clinicorp.")
        logger.info(f"{log_prefix} Novo agendamento criado Clinicorp ID={new_clinicorp_appointment_id}")

        # 6. ATUALIZAR o Registro Local Existente
        try:
            # Converte string DD/MM/YYYY HH:MM para datetime object com timezone
            consulta_dt_obj_nova = datetime.strptime(f"{new_date_str} {new_time_str}", "%d/%m/%Y %H:%M").astimezone()

            # Busca novamente para garantir que está na sessão atual antes do update
            agn_to_update = db.query(Agendamento).filter(Agendamento.id == local_appointment_id).with_for_update().first()
            if not agn_to_update: raise ClinicorpSyncError("Agendamento local não encontrado para atualização final.")

            # Atualiza os campos relevantes do registro local existente
            agn_to_update.nome = customer_name_to_use
            agn_to_update.consulta_data = consulta_dt_obj_nova
            agn_to_update.status = 'SCHEDULED' # Garante status correto após reagendamento
            agn_to_update.id_agendamento = str(new_clinicorp_appointment_id) # NOVO ID Clinicorp
            agn_to_update.customer_id = str(clinicorp_customer_id) # ID do Cliente Clinicorp

            # Atualizar nomes em Lead/Contact (opcional, mas mantém consistência)
            db.query(Lead).filter(Lead.id == lead_id).update({"name": customer_name_to_use}, synchronize_session=False)
            db.query(Contact).filter(Contact.phone == phone, Contact.company_id == company_id).update({"name": customer_name_to_use}, synchronize_session=False)

            db.commit() # Comita a ATUALIZAÇÃO do agendamento local e dos nomes
            logger.info(f"{log_prefix} Registro local ID={local_appointment_id} ATUALIZADO com sucesso.")
            return True # Indica sucesso geral do fluxo

        except Exception as db_err:
            db.rollback()
            logger.exception(f"{log_prefix} Erro ao ATUALIZAR registro local ID={local_appointment_id}: {db_err}")
            # O agendamento antigo foi cancelado e o novo criado no Clinicorp,
            # mas o DB local falhou ao refletir. Estado inconsistente.
            raise ClinicorpSyncError(f"Falha ao atualizar DB local após reagendamento Clinicorp: {db_err}")

    except ClinicorpSyncError as sync_error:
        logger.error(f"{log_prefix} Erro durante reagendamento: {sync_error}")
        # Rollback pode ser perigoso se o cancelamento já foi comitado pela API externa
        # Idealmente, teríamos Sagas ou compensações, mas por ora retornamos False.
        # db.rollback() # Evitar rollback aqui pode ser mais seguro
        return False # Indica falha no fluxo
    except Exception as e:
        logger.exception(f"{log_prefix} Erro inesperado no fluxo: {e}")
        db.rollback() # Rollback em erro inesperado geral
        return False
