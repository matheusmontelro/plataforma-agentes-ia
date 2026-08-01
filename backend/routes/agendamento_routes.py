# backend/routes/agendamento_routes.py
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, validator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json

import os
from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import Agendamento, Agenda, Client, NoShowEvent, Lead, CalendarIntegration
from backend.worker.tasks_confirmation import enviar_passo_confirmacao
from backend.worker.tasks_noshow import enviar_passo_noshow
from backend.worker.tasks_noshow import clear_noshow_steps
from backend.worker.tasks_confirmation import clear_confirmation_steps
from backend.services.company_access_control import (
    CompanyOperationallyBlockedError,
    capture_company_job_epoch,
)
from backend.runtime_settings import CHAT_MEMORY_DIR

# --- ADICIONAR ESTES IMPORTS ---
from backend.routes.integrations.clinicorp_flow_service import (
    reschedule_clinicorp_appointment, # A NOVA função para reagendamento
    cancel_clinicorp_appointment_flow,
    sync_appointment_to_clinicorp,  # Função de cancelamento que já usamos no service
    ClinicorpSyncError               # Exceção customizada
)

from backend.routes.integrations.google_calendar_flow_service import (
    sync_appointment_to_google_calendar,
    cancel_google_calendar_appointment_flow
)

logger = logging.getLogger("saas_business.agendamentos")

CHATMEMORY_PATH = str(CHAT_MEMORY_DIR)
DEFAULT_AGENDA_TIMEZONE = "America/Sao_Paulo"

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/agendamentos",
    tags=["Agendamentos"]
)

class NoShowCreate(BaseModel):
    """
    Schema para receber os dados de no-show que vão popular a tabela noshow_events.
    Recomendado não incluir: client_id, company_id, lead_id, agendamento_id,
    pois esses dados já temos dos parâmetros e do próprio agendamento.
    """
    observacao: Optional[str] = None
    # Exemplo: se quiser mais campos dentro de no-show, adicione aqui
    # data_avisada: Optional[str] = None
    # outro_campo: Optional[str] = None

# -----------------------------------------------------------------------------
# Função para verificar API Key
# -----------------------------------------------------------------------------
async def verify_api_key(
    api_key: str = Header(..., alias="X-API-Key"),
    client_id: int = None,
    db: Session = Depends(get_db)
):
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key não fornecida"
        )

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.api_key == api_key
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida"
        )

    return client

# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class AgendamentoCreate(BaseModel):
    lead_id: int
    nome: Optional[str] = None
    phone: Optional[str] = None
    consulta_data: Optional[str] = None
    midia: Optional[str] = None
    interesse: Optional[str] = None
    endereco: Optional[str] = None
    local_link: Optional[str] = None
    customer_id: Optional[str] = None
    id_agendamento: Optional[str] = None
    event_id: Optional[str] = None
    agenda_id: Optional[int] = None

    @validator("consulta_data")
    def parse_datetime(cls, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.strptime(value, "%d/%m/%Y %H:%M")
        except ValueError:
            raise ValueError(
                "A data/hora deve estar no formato DD/MM/YYYY HH:mm. "
                "Exemplo: 25/01/2025 10:00"
            )

class AgendamentoUpdate(BaseModel):
    lead_id: Optional[int] = None
    nome: Optional[str] = None
    phone: Optional[str] = None
    consulta_data: Optional[datetime] = None
    midia: Optional[str] = None
    interesse: Optional[str] = None
    endereco: Optional[str] = None
    local_link: Optional[str] = None
    customer_id: Optional[str] = None
    id_agendamento: Optional[str] = None
    event_id: Optional[str] = None
    agenda_id: Optional[int] = None

class AgendamentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    company_id: Optional[int]
    lead_id: int
    agendamento_realizado_em: datetime
    nome: Optional[str]
    phone: Optional[str]
    consulta_data: Optional[datetime]
    midia: Optional[str]
    interesse: Optional[str]
    endereco: Optional[str]
    local_link: Optional[str]
    customer_id: Optional[str]
    id_agendamento: Optional[str]
    event_id: Optional[str]
    google_calendar_id: Optional[str]
    status: Optional[str]
    clinicorp_sync_status: Optional[str]
    google_sync_status: Optional[str]
    agenda_id: Optional[int]
    consulta_timezone: Optional[str] = None
    consulta_data_local: Optional[str] = None
    consulta_data_display: Optional[str] = None

def _safe_zoneinfo(timezone_name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or DEFAULT_AGENDA_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_AGENDA_TIMEZONE)


def _agenda_timezone(
    db: Session,
    company_id: int,
    agenda_id: Optional[int],
) -> str:
    if not agenda_id:
        return DEFAULT_AGENDA_TIMEZONE

    agenda = (
        db.query(Agenda.timezone)
        .filter(Agenda.id == agenda_id, Agenda.company_id == company_id)
        .first()
    )
    return agenda.timezone if agenda and agenda.timezone else DEFAULT_AGENDA_TIMEZONE


def _normalize_consulta_data_for_storage(
    value: Optional[datetime],
    *,
    db: Session,
    company_id: int,
    agenda_id: Optional[int],
) -> Optional[datetime]:
    if value is None:
        return None

    timezone_name = _agenda_timezone(db, company_id, agenda_id)
    if value.tzinfo is None:
        return value.replace(tzinfo=_safe_zoneinfo(timezone_name))

    return value.astimezone(_safe_zoneinfo(timezone_name))


def _consulta_data_in_timezone(
    value: Optional[datetime],
    timezone_name: Optional[str],
) -> Optional[datetime]:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))

    return value.astimezone(_safe_zoneinfo(timezone_name))

# -----------------------------------------------------------------------------
# Rotas
# -----------------------------------------------------------------------------

@router.get("", response_model=List[AgendamentoResponse])
async def listar_agendamentos(
    client_id: int,
    company_id: int,
    agenda_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    logger.info(f"[listar_agendamentos] client_id={client_id}, company_id={company_id}, agenda_id={agenda_id}, range={start_date}-{end_date}")
    try:
        query = db.query(Agendamento).options(joinedload(Agendamento.agenda)).filter(
            Agendamento.client_id == client_id,
            Agendamento.company_id == company_id
        )

        if agenda_id:
            query = query.filter(Agendamento.agenda_id == agenda_id)

        if start_date:
            query = query.filter(Agendamento.consulta_data >= start_date)

        if end_date:
            query = query.filter(Agendamento.consulta_data <= end_date)

        agendamentos = query.all()
        logger.info(f"[listar_agendamentos] Retornando {len(agendamentos)} registros.")
        return agendamentos
    except Exception as e:
        logger.exception("[listar_agendamentos] Erro ao listar agendamentos")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.get("/{agendamento_id}", response_model=AgendamentoResponse)
async def obter_agendamento(
    client_id: int,
    company_id: int,
    agendamento_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    logger.info(f"[obter_agendamento] client_id={client_id}, company_id={company_id}, agendamento_id={agendamento_id}")
    try:
        agendamento = db.query(Agendamento).options(joinedload(Agendamento.agenda)).filter(
            Agendamento.id == agendamento_id,
            Agendamento.client_id == client_id,
            Agendamento.company_id == company_id
        ).first()
        if not agendamento:
            logger.warning("[obter_agendamento] Agendamento não encontrado.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agendamento não encontrado para este cliente/empresa."
            )
        return agendamento
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[obter_agendamento] Erro ao obter agendamento")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

# --- ROTA POST / (Criar Agendamento) - AJUSTADA ---
@router.post("", response_model=AgendamentoResponse, status_code=status.HTTP_201_CREATED)
async def criar_agendamento(
    client_id: int,
    company_id: int,
    payload: AgendamentoCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key) # Renomeado para _
):
    """
    Cria um novo agendamento localmente. Tenta sincronizar com a integração
    ativa (Clinicorp ou Google Calendar, se houver) APÓS a criação local
    bem-sucedida. A função sync_appointment_to_clinicorp (se usada)
    deleta o registro local anterior e cria um novo.
    """
    logger.info(f"[Criar Agendamento Rota] company_id={company_id}, payload={payload.dict(exclude_unset=True)}")

    # --- Validação do Lead (como no original) ---
    lead = db.query(Lead).filter(Lead.id == payload.lead_id, Lead.company_id == company_id).first()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead com id {payload.lead_id} não encontrado para a empresa {company_id}."
        )
    phone_to_use = payload.phone or lead.phone
    name_to_use = payload.nome or lead.name
    if not phone_to_use:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Telefone não fornecido no payload nem encontrado no Lead.")
    if not payload.consulta_data:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Data e hora da consulta (consulta_data) são obrigatórios.")
    consulta_data = _normalize_consulta_data_for_storage(
        payload.consulta_data,
        db=db,
        company_id=company_id,
        agenda_id=payload.agenda_id,
    )
    # --- Fim Validação ---

    # Cria o agendamento local inicial (pode ser deletado/substituído pelo sync do Clinicorp)
    novo_agendamento_inicial = Agendamento(
        client_id=client_id, company_id=company_id, lead_id=payload.lead_id,
        nome=name_to_use, phone=phone_to_use, consulta_data=consulta_data,
        midia=payload.midia, interesse=payload.interesse,
        endereco=payload.endereco, local_link=payload.local_link,
        status='SCHEDULED',
        agenda_id=payload.agenda_id # Adicionado agenda_id
    )
    db.add(novo_agendamento_inicial)
    try:
        db.commit()
        db.refresh(novo_agendamento_inicial)
        local_agn_id_inicial = novo_agendamento_inicial.id
        logger.info(f"[Criar Agendamento Rota] Agendamento local inicial criado. ID Local={local_agn_id_inicial} para company_id={company_id}")

        # Variável para retornar o objeto final (pode ser atualizada pelo sync)
        agendamento_final = novo_agendamento_inicial
        id_final_para_task = local_agn_id_inicial

        # --- SINCRONIZAÇÃO CONDICIONAL BASEADA NA INTEGRAÇÃO (AGORA PARA QUALQUER company_id) ---
        # A resolução de integração é igual para todas as empresas.

        # Determina o tipo de integração ativa para o company_id da rota
        integration_type = _get_active_integration_type(db, company_id)
        logger.info(f"[Criar Agendamento] Tipo de integração detectada para company_id={company_id}: {integration_type}")

        # Continua apenas se consulta_data estiver presente (já validado acima, mas verificamos de novo)
        if novo_agendamento_inicial.consulta_data:
            local_consulta_data = _consulta_data_in_timezone(
                novo_agendamento_inicial.consulta_data,
                _agenda_timezone(db, company_id, novo_agendamento_inicial.agenda_id),
            )
            data_str = local_consulta_data.strftime("%d/%m/%Y")
            time_str = local_consulta_data.strftime("%H:%M")

            # Executa a lógica de acordo com a integração encontrada
            if integration_type == 'clinicorp':
                logger.info(f"[Criar Agendamento Rota] Usando integração Clinicorp para company_id={company_id}")
                try:
                    # Executar a integração com Clinicorp
                    sync_local_id, clinicorp_id = sync_appointment_to_clinicorp(
                        db=db, company_id=company_id, phone=phone_to_use, name=name_to_use,
                        date_str=data_str, time_str=time_str
                        # Passar outros parâmetros se a função exigir
                    )

                    # Atualiza as variáveis se o sync do Clinicorp criou um novo registro local
                    logger.info(f"[Criar Agendamento Rota] Sincronização com Clinicorp BEM-SUCEDIDA para company_id={company_id}. Novo ID Local={sync_local_id}, Clinicorp ID={clinicorp_id}")
                    novo_agendamento_sync = db.query(Agendamento).filter(Agendamento.id == sync_local_id).first()
                    if novo_agendamento_sync:
                        novo_agendamento_sync.endereco = payload.endereco
                        novo_agendamento_sync.local_link = payload.local_link
                        db.commit()
                        db.refresh(novo_agendamento_sync)
                        agendamento_final = novo_agendamento_sync
                        id_final_para_task = sync_local_id
                    else:
                        # Isso não deveria acontecer se sync_appointment_to_clinicorp funcionou
                        logger.error(f"[Criar Agendamento Rota] Não foi possível encontrar o novo agendamento local (ID={sync_local_id}) após sync com Clinicorp para company_id={company_id}!")
                        # Mantém o agendamento inicial como fallback? Ou levanta erro?
                        # Por segurança, mantemos o inicial, mas logamos o erro grave.

                except ClinicorpSyncError as e_sync:
                    logger.warning(f"[Criar Agendamento Rota] Falha controlada ao sincronizar com Clinicorp para company_id={company_id}: {e_sync}.")
                    # Neste caso, o agendamento_final continua sendo o novo_agendamento_inicial
                except Exception as e_sync_inesperado:
                    logger.exception(f"[Criar Agendamento Rota] Erro inesperado ao sincronizar com Clinicorp para company_id={company_id}: {e_sync_inesperado}")
                    # Neste caso, o agendamento_final continua sendo o novo_agendamento_inicial

            elif integration_type == 'google':
                logger.info(f"[Criar Agendamento Rota] Usando integração Google Calendar para company_id={company_id}")
                try:
                    # Chamar a função de sincronização com Google Calendar
                    sync_success = sync_appointment_to_google_calendar(
                        db=db,
                        local_appointment_id=local_agn_id_inicial, # Usa o ID do agendamento local já criado
                        date_str=data_str,
                        time_str=time_str
                        # Passar outros parâmetros se a função exigir
                    )

                    if sync_success:
                        logger.info(f"[Criar Agendamento Rota] Sincronização com Google Calendar BEM-SUCEDIDA para company_id={company_id}.")
                        # Recarregar o objeto local para obter eventuais mudanças do sync (ex: event_id)
                        db.refresh(novo_agendamento_inicial)
                        agendamento_final = novo_agendamento_inicial # O registro local é o mesmo
                        id_final_para_task = local_agn_id_inicial
                    else:
                        logger.warning(f"[Criar Agendamento Rota] Falha na sincronização com Google Calendar para company_id={company_id}.")
                        # agendamento_final continua sendo novo_agendamento_inicial
                except Exception as e_google:
                    logger.exception(f"[Criar Agendamento Rota] Erro ao sincronizar com Google Calendar para company_id={company_id}: {e_google}")
                    # agendamento_final continua sendo novo_agendamento_inicial

            else: # Caso integration_type seja None
                logger.info(f"[Criar Agendamento Rota] Nenhuma integração ativa detectada para company_id={company_id}. Mantendo apenas registro local.")
                # Nenhuma ação de sincronização é necessária

        else:
             # Caso raro, pois validamos payload.consulta_data antes, mas por segurança
             logger.warning(f"[Criar Agendamento Rota] Agendamento ID={local_agn_id_inicial} não possui data/hora (consulta_data), sincronização externa pulada para company_id={company_id}.")
        # --- FIM SINCRONIZAÇÃO CONDICIONAL ---

        # --- Ações Pós-Criação (usando o agendamento_final e id_final_para_task corretos) ---
        logger.debug(f"ID do agendamento para ações pós-criação: {id_final_para_task} (company_id={company_id})")
        try:
            # Atualizar Estado Conversa (usando dados do objeto final)
            #update_conversation_state_after_agendamento(
                #db=db, company_id=company_id, phone=agendamento_final.phone,
                #agendamento_nome=agendamento_final.nome, consulta_data=agendamento_final.consulta_data,
                #agendamento_tratamento=agendamento_final.interesse
            #)
            row_cred = db.execute(
                text("SELECT waha_session_name, waha_enabled FROM companies WHERE id = :cid LIMIT 1"),
                {"cid": company_id}
            ).fetchone()
            if row_cred and row_cred.waha_enabled and row_cred.waha_session_name:
                if agendamento_final.phone: # Verifica se há telefone para enviar
                    # <<< ADICIONAR LOG AQUI >>>
                    logger.info(f"Disparando task enviar_passo_confirmacao (step 1) para agendamento ID={id_final_para_task}, company_id={company_id}, phone={agendamento_final.phone}")
                    # --- FIM DO LOG ADICIONADO ---
                    operational_epoch = capture_company_job_epoch(db, company_id)
                    db.commit()
                    enviar_passo_confirmacao.delay(
                        agendamento_id=id_final_para_task, # Usa id_final_para_task
                        step_number=1,
                        instance_id="",
                        instance_token="",
                        phone=agendamento_final.phone,
                        operational_epoch=operational_epoch,
                    )
                    logger.info(f"Task de confirmação (passo 1) disparada para agendamento ID={id_final_para_task}, phone={agendamento_final.phone}")
                else:
                    logger.warning(f"Não foi possível disparar task de confirmação para agendamento ID={id_final_para_task} pois não há telefone associado.")
            else:
                 logger.warning(f"Sessão WAHA ativa não encontrada para company_id={company_id}. Task de confirmação não disparada.")
        except Exception as post_create_err:
             logger.error(f"[Criar Agendamento Rota] Erro em ações pós-criação para agendamento ID {id_final_para_task} (company_id={company_id}): {post_create_err}")

        try:
            from backend.services.flow_event_service import trigger_appointment_event
            started_flows = trigger_appointment_event(db, agendamento_final, "appointment_created")
            logger.info(
                "[FlowBuilder] %s fluxo(s) de agendamento iniciados para appointment_id=%s",
                started_flows,
                id_final_para_task,
            )
        except Exception as flow_event_err:
            logger.error(
                "[FlowBuilder] Erro ao iniciar fluxos de agendamento appointment_id=%s: %s",
                id_final_para_task,
                flow_event_err,
            )

        # Retorna o objeto Agendamento (o original se sync falhou/não ocorreu, ou o novo criado pelo sync do Clinicorp)
        return agendamento_final

    except HTTPException as http_exc:
        # Se o erro foi uma HTTPException já lançada (ex: validação), propaga
        db.rollback() # Garante rollback em caso de erro antes do commit ou validação Pydantic
        raise http_exc
    except Exception as e: # Captura outros erros (ex: commit inicial, erro de banco)
        db.rollback()
        logger.exception(f"[Criar Agendamento Rota] Erro geral ao criar agendamento para company_id={company_id}")
        detail = f"Erro interno ao criar agendamento: {str(e)}"
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR # Default para erros inesperados

        # (Lógica original para tratar erros de constraint unique/FK)
        error_str = str(e).lower()
        if "violates unique constraint" in error_str or "duplicate key value violates unique constraint" in error_str :
            # Tenta identificar qual constraint foi violada se possível, senão usa mensagem genérica
            detail = "Já existe um agendamento neste horário para este cliente ou telefone, ou conflito de ID externo."
            status_code = status.HTTP_409_CONFLICT
        elif "violates foreign key constraint" in error_str:
            # Tenta identificar qual FK foi violada se possível
            detail = "Lead ID ou Company ID inválido."
            status_code = status.HTTP_400_BAD_REQUEST # Ou 404 dependendo do contexto da FK

        raise HTTPException(status_code=status_code, detail=detail)

@router.put("/{agendamento_id}", response_model=AgendamentoResponse)
async def atualizar_agendamento(
    client_id: int,
    company_id: int,
    agendamento_id: int,
    payload: AgendamentoUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Atualiza um agendamento local.
    Detecta o tipo de integração ativa (Clinicorp ou Google Calendar) para
    a empresa atual e, caso a data/hora tenha mudado (reagendamento), tenta:
    1. Cancelar o agendamento anterior na integração externa.
    2. Criar o novo agendamento na integração externa.

    As atualizações locais são feitas PRIMEIRO. Falhas na sincronização
    são logadas como aviso, mas não impedem o sucesso da requisição PUT.
    """
    logger.info(f"[Atualizar Agendamento Rota] ID={agendamento_id} para company_id={company_id}")

    # --- AJUSTE AQUI ---
    # Determina o tipo de integração ativa para QUALQUER company_id
    integration_type = _get_active_integration_type(db, company_id) # Chamada incondicional
    if integration_type:
        logger.info(f"[Atualizar Agendamento] Tipo de integração detectada para company_id={company_id}: {integration_type}")
    else:
        logger.info(f"[Atualizar Agendamento] Nenhuma integração ativa detectada para company_id={company_id}.")
    # --- FIM DO AJUSTE ---

    # Buscar agendamento com lock otimista
    agendamento = db.query(Agendamento).filter(
        Agendamento.id == agendamento_id,
        Agendamento.company_id == company_id # Mantém a segurança de atualizar apenas da empresa correta
        # Adicionar client_id ao filtro se a segurança exigir também a nível de cliente
        # Agendamento.client_id == client_id
    ).with_for_update().first()

    if not agendamento:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agendamento não encontrado.")

    # Guarda valores originais para detectar mudanças
    data_original = agendamento.consulta_data
    agenda_original = agendamento.agenda_id
    status_original = agendamento.status

    # Atualiza o objeto Agendamento com os dados do payload
    update_data = payload.dict(exclude_unset=True)
    if "consulta_data" in update_data:
        update_data["consulta_data"] = _normalize_consulta_data_for_storage(
            update_data["consulta_data"],
            db=db,
            company_id=company_id,
            agenda_id=update_data.get("agenda_id", agendamento.agenda_id),
        )
    logger.debug(f"Dados para atualizar para agendamento ID={agendamento_id}: {update_data}")
    for campo, valor in update_data.items():
        setattr(agendamento, campo, valor)

    try:
        # Salva as alterações locais PRIMEIRO
        db.commit()
        db.refresh(agendamento)
        logger.info(f"Agendamento local ID={agendamento.id} atualizado no DB.")

        data_nova = agendamento.consulta_data # Pega a data potencialmente atualizada

        # --- Lógica de Reagendamento (se data/hora mudou) ---
        # Verifica se ambos data_nova e data_original existem e são diferentes
        is_reschedule = bool(
            data_nova
            and data_original
            and (data_nova != data_original or agendamento.agenda_id != agenda_original)
        )

        if is_reschedule:
            logger.info(f"Reagendamento detectado para agendamento ID={agendamento.id} na company_id={company_id}.")

            # --- PROCESSAMENTO DE INTEGRAÇÃO (SE EXISTIR PARA ESTA EMPRESA) ---
            # --- AJUSTE AQUI ---
            # Usa a integração configurada para a empresa atual.
            if integration_type: # Verifica apenas se uma integração foi encontrada para esta company_id
            # --- FIM DO AJUSTE ---
                local_data_nova = _consulta_data_in_timezone(
                    data_nova,
                    _agenda_timezone(db, company_id, agendamento.agenda_id),
                )
                new_date_str = local_data_nova.strftime("%d/%m/%Y")
                new_time_str = local_data_nova.strftime("%H:%M")

                if integration_type == 'clinicorp':
                    # --- FLUXO CLINICORP ---
                    logger.info(f"Executando reagendamento Clinicorp para agendamento ID={agendamento.id} (company_id={company_id})")
                    try:
                        # Assume que reschedule_clinicorp_appointment usa local_appointment_id
                        success_reschedule = reschedule_clinicorp_appointment(
                            db=db,
                            local_appointment_id=agendamento.id,
                            new_name=agendamento.nome, # Passa o nome atualizado
                            new_date_str=new_date_str,
                            new_time_str=new_time_str
                            # Adicionar outros campos se necessário para a função
                        )

                        if success_reschedule:
                            logger.info(f"Reagendamento no Clinicorp BEM-SUCEDIDO para agendamento ID={agendamento.id}")
                            db.refresh(agendamento) # Recarrega para pegar possíveis updates da função de sync
                        else:
                            # A função deveria retornar True/False ou levantar exceção em caso de falha
                            logger.warning(f"Fluxo de reagendamento no Clinicorp FALHOU (retornou False) para ID={agendamento.id}.")
                    except ClinicorpSyncError as e_sync:
                        logger.warning(f"Falha controlada no reagendamento Clinicorp para ID={agendamento.id}: {e_sync}")
                    except Exception as e:
                        logger.exception(f"Erro inesperado no reagendamento Clinicorp ID={agendamento.id}: {e}")

                elif integration_type == 'google':
                    # --- FLUXO GOOGLE CALENDAR ---
                    logger.info(f"Executando reagendamento Google Calendar para agendamento ID={agendamento.id} (company_id={company_id})")
                    try:
                        # 1. Primeiro tenta cancelar o agendamento atual no Google Calendar
                        #    Assume que a função usa o ID local para encontrar o event_id correto
                        cancel_success = cancel_google_calendar_appointment_flow(db, agendamento.id, delete_local=False)
                        if not cancel_success:
                            # Loga aviso, mas prossegue para tentar criar o novo evento mesmo assim
                            logger.warning(f"Falha ao cancelar agendamento anterior no Google Calendar durante reagendamento (ID={agendamento.id}). Tentando criar o novo mesmo assim.")

                        # 2. Depois tenta criar um novo com a nova data/hora
                        sync_success = sync_appointment_to_google_calendar(
                            db=db,
                            local_appointment_id=agendamento.id, # ID do agendamento local atualizado
                            date_str=new_date_str,
                            time_str=new_time_str,
                            is_rescheduling=True # Sinaliza que é um reagendamento
                        )

                        if sync_success:
                            logger.info(f"Criação de novo evento no Google Calendar (reagendamento) BEM-SUCEDIDA para ID={agendamento.id}")
                            db.refresh(agendamento) # Recarrega para pegar o novo event_id se foi atualizado
                        else:
                            logger.warning(f"Falha ao criar novo agendamento no Google Calendar durante reagendamento para ID={agendamento.id}")
                    except Exception as e:
                        logger.exception(f"Erro inesperado no reagendamento Google Calendar ID={agendamento.id}: {e}")
            # --- FIM PROCESSAMENTO DE INTEGRAÇÃO ---
            # Se integration_type for None, nada acontece aqui (nenhuma integração externa é chamada)

            # --- Limpeza de Fluxos Locais (Executa SEMPRE se data mudou, independentemente da integração) ---
            logger.info(f"Limpando fluxos locais de confirmação/no-show para reagendamento ID={agendamento.id}")
            try:
                # Ajustar status local para SCHEDULED se não foi feito pela integração (ou se não houve integração)
                # Importante para garantir que o fluxo de confirmação reinicie corretamente
                if agendamento.status != "SCHEDULED":
                    agendamento.status = "SCHEDULED"
                    logger.info(f"Ajustando status local para SCHEDULED para reagendamento ID={agendamento.id}")
                    # Precisa commitar essa mudança de status? Sim.
                    # db.commit() # O commit principal está no final do try/except geral

                # Limpeza das tabelas de execução
                db.execute(text("DELETE FROM confirmation_executions WHERE agendamento_id = :ag_id"),{"ag_id": agendamento_id})
                db.execute(text("DELETE FROM noshow_events WHERE agendamento_id = :ag_id"), {"ag_id": agendamento_id})
                # A limpeza de noshow_follow_up_executions usa lead_id, que não muda no PUT
                if agendamento.lead_id:
                    db.execute(text("DELETE FROM noshow_follow_up_executions WHERE lead_id = :lead_id"), {"lead_id": agendamento.lead_id})
                else:
                    logger.warning(f"Lead ID não encontrado no agendamento ID={agendamento.id} durante limpeza de reagendamento.")

                db.commit() # Commit das deleções e da mudança de status se houve

                # Limpeza do Redis (Celery tasks)
                clear_confirmation_steps(agendamento_id)
                if agendamento.lead_id:
                    clear_noshow_steps(company_id, agendamento.lead_id)
                logger.info(f"Fluxos locais (DB e Redis) limpos para reagendamento ID={agendamento.id}")

                # Reiniciar fluxo de confirmação (passo 1) com a nova data/hora
                row_cred = db.execute(text("SELECT waha_session_name, waha_enabled FROM companies WHERE id = :cid LIMIT 1"), {"cid": company_id}).fetchone()
                if row_cred and row_cred.waha_enabled and row_cred.waha_session_name:
                    if agendamento.phone:
                        # <<< ADICIONAR LOG AQUI >>>
                        logger.info(f"Reiniciando fluxo de confirmação: Disparando task enviar_passo_confirmacao (step 1) para agendamento ID={agendamento.id}, company_id={company_id}, phone={agendamento.phone}")
                        # --- FIM DO LOG ADICIONADO ---
                        operational_epoch = capture_company_job_epoch(db, company_id)
                        db.commit()
                        enviar_passo_confirmacao.delay(
                            agendamento_id=agendamento.id, step_number=1,
                            instance_id="", instance_token="",
                            phone=agendamento.phone,
                            operational_epoch=operational_epoch,
                        )
                        logger.info(f"Reiniciado fluxo de confirmação (passo 1) para reagendamento ID={agendamento.id}.")
                    else:
                        logger.warning(f"Não foi possível reiniciar confirmação para reagendamento ID={agendamento.id}: telefone ausente.")
                else:
                    logger.warning(f"Sessão WAHA ativa não encontrada para company_id={company_id}. Fluxo de confirmação não reiniciado.")

            except Exception as e_cleanup:
                logger.error(f"Erro ao limpar/reiniciar fluxos locais durante reagendamento ID={agendamento.id}: {e_cleanup}")
                # Continua mesmo assim, pois a atualização principal já foi feita.

        # --- Lógica para tratar saída de NO_SHOW (se não foi um reagendamento) ---
        elif status_original == "NO_SHOW" and agendamento.status != "NO_SHOW":
            logger.info(f"Status mudou de NO_SHOW para {agendamento.status} para agendamento ID={agendamento.id} -> limpando dados de no-show.")
            try:
                # Limpa apenas os dados relacionados ao no-show
                db.execute(text("DELETE FROM noshow_events WHERE agendamento_id = :ag_id"),{"ag_id": agendamento_id})
                if agendamento.lead_id:
                     db.execute(text("DELETE FROM noshow_follow_up_executions WHERE lead_id = :lead_id"), {"lead_id": agendamento.lead_id})
                db.commit()
                if agendamento.lead_id:
                    clear_noshow_steps(company_id, agendamento.lead_id) # Limpa Redis também
                logger.info(f"Dados de no-show (DB e Redis) limpos para ID={agendamento.id}")
            except Exception as e_noshow_cleanup:
                logger.error(f"Erro ao limpar dados de no-show para ID={agendamento.id}: {e_noshow_cleanup}")

        # Garante que estamos retornando o estado mais atualizado do agendamento
        # após todas as operações (refresh já feito após commit inicial e nos syncs)
        # db.refresh(agendamento) # Pode ser redundante, mas garante
        try:
            from backend.services.flow_event_service import trigger_appointment_event
            flow_event_name = None
            if is_reschedule:
                flow_event_name = "appointment_rescheduled"
            elif status_original != agendamento.status:
                current_status = str(agendamento.status or "").upper()
                flow_event_name = "appointment_cancelled" if current_status in {"CANCELLED", "CANCELED", "CANCELADO"} else "appointment_status_changed"

            if flow_event_name:
                started_flows = trigger_appointment_event(db, agendamento, flow_event_name)
                logger.info(
                    "[FlowBuilder] %s fluxo(s) processados para appointment_id=%s evento=%s",
                    started_flows,
                    agendamento.id,
                    flow_event_name,
                )
        except Exception as flow_event_err:
            logger.error(
                "[FlowBuilder] Erro ao processar evento de agendamento appointment_id=%s: %s",
                agendamento.id,
                flow_event_err,
            )

        return agendamento

    except HTTPException as he:
        db.rollback() # Garante rollback em caso de erro HTTP conhecido
        raise he
    except Exception as e:
        db.rollback() # Garante rollback em caso de erro inesperado
        logger.exception(f"[atualizar_agendamento] Erro inesperado ao atualizar ID={agendamento_id} para company_id={company_id}")
        # Retorna um erro genérico para não expor detalhes internos
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Erro interno ao atualizar agendamento.")

@router.delete("/{agendamento_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_agendamento(
    client_id: int, # Mantido para validação de API Key e filtro (se necessário)
    company_id: int,
    agendamento_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key) # Valida o acesso do cliente
):
    """
    Deleta um agendamento localmente e limpa fluxos relacionados.
    Detecta a integração ativa (Clinicorp ou Google Calendar) para a empresa
    e tenta cancelar na plataforma externa ANTES da deleção local.
    Falha no cancelamento externo é logada como aviso, mas não impede a deleção local.
    """
    logger.info(f"[Deletar Agendamento Rota] Iniciando para company_id={company_id}, agendamento_id={agendamento_id}")

    # --- AJUSTE AQUI ---
    # Determina o tipo de integração ativa para QUALQUER company_id
    integration_type = _get_active_integration_type(db, company_id) # Chamada incondicional
    if integration_type:
        logger.info(f"[Deletar Agendamento] Tipo de integração detectada para company_id={company_id}: {integration_type}")
    else:
        logger.info(f"[Deletar Agendamento] Nenhuma integração ativa detectada para company_id={company_id}. Cancelamento externo será pulado.")
    # --- FIM DO AJUSTE ---

    # 1) Busca o agendamento local
    #    Garante que o agendamento pertence à empresa correta
    agendamento = db.query(Agendamento).filter(
        Agendamento.id == agendamento_id,
        Agendamento.company_id == company_id
        # Considerar adicionar Agendamento.client_id == client_id se a regra de negócio exigir
    ).with_for_update().first() # Lock otimista

    if not agendamento:
        # Log já informa company_id e agendamento_id
        logger.warning(f"[Deletar Agendamento Rota] Agendamento local não encontrado.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado para esta empresa."
        )

    try:
        # Guarda informações necessárias ANTES de deletar o objeto 'agendamento'
        lead_id = agendamento.lead_id
        phone = agendamento.phone
        # IDs externos (podem ser None, a lógica de cancelamento deve tratar isso)
        id_clinicorp_a_cancelar = agendamento.id_agendamento
        id_google_a_cancelar = agendamento.event_id

        # --- PASSO ADICIONAL: CANCELAMENTO CONDICIONAL EXTERNO (SE EXISTIR INTEGRAÇÃO) ---
        # --- AJUSTE AQUI ---
        # Usa a integração configurada para a empresa atual.
        if integration_type: # Verifica apenas se uma integração foi encontrada para esta company_id
        # --- FIM DO AJUSTE ---
            logger.info(f"[Deletar Agendamento] Integração ativa '{integration_type}' para company_id={company_id}. Tentando cancelar externamente...")

            if integration_type == 'clinicorp':
                if id_clinicorp_a_cancelar:
                    logger.info(f"Tentando cancelar no Clinicorp (Agendamento Local ID={agendamento_id}, Clinicorp ID={id_clinicorp_a_cancelar})")
                    try:
                        # Chama a função de fluxo de cancelamento Clinicorp
                        # Assume que a função usa o ID local para buscar credenciais e ID externo
                        cancel_ok = cancel_clinicorp_appointment_flow(db, agendamento_id)
                        if cancel_ok:
                            logger.info(f"Cancelamento no Clinicorp (ID={id_clinicorp_a_cancelar}) BEM-SUCEDIDO.")
                        else:
                            logger.warning(f"Cancelamento no Clinicorp (ID={id_clinicorp_a_cancelar}) FALHOU ou não confirmado (retornou False). Procedendo com deleção local.")
                    except Exception as e_cancel_clin:
                        # Captura qualquer erro inesperado durante o cancelamento externo
                        logger.exception(f"Erro inesperado ao tentar cancelar no Clinicorp (ID={id_clinicorp_a_cancelar}): {e_cancel_clin}. Procedendo com deleção local.")
                else:
                    # Log informativo se a integração está ativa mas o agendamento não tem ID externo
                    logger.info(f"Integração Clinicorp ativa para company_id={company_id}, mas agendamento local ID={agendamento_id} não possui ID Clinicorp associado. Pulando cancelamento externo.")

            elif integration_type == 'google':
                if id_google_a_cancelar:
                    logger.info(f"Tentando cancelar no Google Calendar (Agendamento Local ID={agendamento_id}, Event ID={id_google_a_cancelar})")
                    try:
                         # Chama a função de fluxo de cancelamento Google Calendar
                         # Assume que a função usa o ID local para buscar credenciais e event_id
                        cancel_ok = cancel_google_calendar_appointment_flow(db, agendamento_id)
                        if cancel_ok:
                            logger.info(f"Cancelamento no Google Calendar (Event ID={id_google_a_cancelar}) BEM-SUCEDIDO.")
                        else:
                            logger.warning(f"Cancelamento no Google Calendar (Event ID={id_google_a_cancelar}) FALHOU ou não confirmado (retornou False). Procedendo com deleção local.")
                    except Exception as e_cancel_goog:
                        logger.exception(f"Erro inesperado ao tentar cancelar no Google Calendar (Event ID={id_google_a_cancelar}): {e_cancel_goog}. Procedendo com deleção local.")
                else:
                    logger.info(f"Integração Google ativa para company_id={company_id}, mas agendamento local ID={agendamento_id} não possui Event ID associado. Pulando cancelamento externo.")

            # Removido bloco 'else:' desnecessário aqui, pois só tratamos 'clinicorp' e 'google'
            # O log inicial já cobre o caso sem integração.

        # --- FIM CANCELAMENTO CONDICIONAL EXTERNO ---
        # A execução continua aqui independentemente do sucesso/falha do cancelamento externo

        # --- Limpeza de Fluxos Relacionados (Lógica Original Mantida) ---
        # Executa para TODAS as empresas, limpando dados locais associados
        logger.info(f"Limpando fluxos locais relacionados para agendamento ID={agendamento_id} (company_id={company_id})")
        try:
            # Deleta execuções de confirmação
            deleted_confirmations = db.execute(text("DELETE FROM confirmation_executions WHERE agendamento_id = :ag_id RETURNING id"),{"ag_id": agendamento_id}).rowcount
            logger.debug(f"{deleted_confirmations} registro(s) deletado(s) de confirmation_executions.")

            # Deleta eventos de no-show
            deleted_noshow_events = db.execute(text("DELETE FROM noshow_events WHERE agendamento_id = :ag_id RETURNING id"), {"ag_id": agendamento_id}).rowcount
            logger.debug(f"{deleted_noshow_events} registro(s) deletado(s) de noshow_events.")

            # Deleta execuções de follow-up de no-show (usando lead_id)
            if lead_id: # Só executa se o lead_id foi recuperado
                deleted_noshow_followups = db.execute(text("DELETE FROM noshow_follow_up_executions WHERE lead_id = :lead_id RETURNING id"), {"lead_id": lead_id}).rowcount
                logger.debug(f"{deleted_noshow_followups} registro(s) deletado(s) de noshow_follow_up_executions para lead_id={lead_id}.")
            else:
                logger.warning(f"Lead ID não encontrado no agendamento ID={agendamento_id} durante limpeza de deleção.")

            # Limpar Redis (Celery tasks pendentes)
            clear_confirmation_steps(agendamento_id) # Limpa baseado no ID do agendamento
            if lead_id: # Só executa se o lead_id foi recuperado
                clear_noshow_steps(company_id, lead_id) # Limpa baseado na empresa e lead

            # O commit das deleções acima será feito junto com a deleção do agendamento principal
            logger.info(f"Limpeza de fluxos locais (DB pendente de commit, Redis OK) concluída para agendamento ID={agendamento_id}.")

        except Exception as e_cleanup:
             logger.error(f"Erro durante limpeza de fluxos locais para agendamento ID={agendamento_id}: {e_cleanup}")
             # Decide-se continuar com a deleção principal mesmo se a limpeza falhar,
             # pois o objetivo primário é remover o agendamento. O erro fica logado.

        # --- Deletar o Agendamento Local ---
        try:
            from backend.services.flow_event_service import trigger_appointment_event
            trigger_appointment_event(db, agendamento, "appointment_deleted")
        except Exception as flow_event_err:
            logger.error(
                "[FlowBuilder] Erro ao cancelar fluxos do agendamento deletado appointment_id=%s: %s",
                agendamento_id,
                flow_event_err,
            )

        logger.info(f"Deletando registro local do agendamento ID={agendamento.id} (company_id={company_id})")
        db.delete(agendamento)
        db.commit() # Comita a deleção do agendamento E as deleções da limpeza de fluxos
        logger.info(f"[Deletar Agendamento Rota] Agendamento local ID={agendamento_id} deletado com sucesso.")

        # --- Limpeza Final de Estado/Arquivo (Lógica Original Mantida) ---
        # Tenta limpar o estado da conversa e arquivo de chat SE não houver mais agendamentos para este telefone/empresa
        if phone:
            # Esta função interna verifica a contagem de agendamentos antes de remover
            remove_conversation_state_if_no_appointments(db, company_id, phone)
            logger.debug(f"Verificação de limpeza de estado/arquivo para phone={phone}, company_id={company_id} concluída.")
        else:
            logger.warning(f"Não foi possível verificar/limpar estado/arquivo para agendamento ID={agendamento_id} pois o telefone não foi encontrado no registro deletado.")

        # Se chegou aqui, a deleção (pelo menos local) foi bem-sucedida
        return None # Retorno HTTP 204 (No Content) é implícito para DELETE bem-sucedido

    except Exception as e:
        db.rollback() # Reverte qualquer mudança no banco se algo der errado no bloco try
        logger.exception(f"[Deletar Agendamento Rota] Erro inesperado ao deletar agendamento ID={agendamento_id} para company_id={company_id}")
        # Evitar expor detalhes internos no erro final para o cliente da API
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar a exclusão do agendamento."
        )

@router.get("/by-phone/{phone}", response_model=AgendamentoResponse)
async def obter_agendamento_por_telefone(
    client_id: int,
    company_id: int,
    phone: str,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Obtém um agendamento específico pelo número de telefone,
    vinculado ao client_id e company_id.
    """
    logger.info(f"[obter_agendamento_por_telefone] client_id={client_id}, company_id={company_id}, phone={phone}")
    try:
        agendamento = db.query(Agendamento).filter(
            Agendamento.phone == phone,
            Agendamento.client_id == client_id,
            Agendamento.company_id == company_id
        ).order_by(Agendamento.agendamento_realizado_em.desc()).first()

        if not agendamento:
            logger.warning("[obter_agendamento_por_telefone] Agendamento não encontrado.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agendamento não encontrado para este telefone."
            )

        logger.info(f"[obter_agendamento_por_telefone] Retornando agendamento id={agendamento.id}.")
        return agendamento
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[obter_agendamento_por_telefone] Erro ao obter agendamento")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.put("/{agendamento_id}/noshow")
def marcar_no_show(
    client_id: int,
    company_id: int,
    agendamento_id: int,
    payload: NoShowCreate,
    db: Session = Depends(get_db)
):
    """
    Atualiza o status do agendamento para "NO_SHOW",
    cria registro na tabela noshow_events, copiando dados do Agendamento
    (nome, phone, data_agendada), e salva a observação vinda do payload.
    Dispara eventuais tarefas Celery (caso necessário).
    """
    try:
        # 1) Verifica se o agendamento existe
        ag = db.query(Agendamento).filter_by(
            id=agendamento_id,
            client_id=client_id,
            company_id=company_id
        ).first()

        if not ag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agendamento não encontrado."
            )

        operational_epoch = capture_company_job_epoch(db, company_id)

        # 2) Verifica se já existe NoShow para este agendamento
        existing_noshow = db.query(NoShowEvent).filter_by(
            agendamento_id=agendamento_id
        ).first()
        if existing_noshow:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este agendamento já foi marcado como no-show."
            )

        # 3) Marca o agendamento como NO_SHOW
        ag.status = "NO_SHOW"

        # 4) Cria registro na tabela noshow_events, copiando dados
        novo_noshow = NoShowEvent(
            client_id=client_id,
            company_id=company_id,
            lead_id=ag.lead_id,
            agendamento_id=ag.id,
            # Copiamos o "snapshot" de nome, phone e consulta_data
            nome=ag.nome,
            phone=ag.phone,
            data_agendada=ag.consulta_data,
            # Recebendo observacao via payload
            observacao=payload.observacao
        )
        db.add(novo_noshow)

        db.commit()
        db.refresh(ag)
        db.refresh(novo_noshow)

        try:
            from backend.services.flow_event_service import trigger_appointment_event
            trigger_appointment_event(db, ag, "appointment_status_changed")
        except Exception as flow_event_err:
            logger.error(
                "[FlowBuilder] Erro ao processar no-show no FlowBuilder appointment_id=%s: %s",
                agendamento_id,
                flow_event_err,
            )

        # 5) Dispara a task Celery (opcional)
        try:
            task = enviar_passo_noshow.apply_async(
                args=[
                    ag.lead_id,
                    1,
                    company_id,
                    ag.phone,
                    operational_epoch,
                ],
                retry=True,
                retry_policy={
                    'max_retries': 3,
                    'interval_start': 0,
                    'interval_step': 0.2,
                    'interval_max': 0.5,
                }
            )
            return {
                "message": "Agendamento marcado como no-show e fluxo disparado.",
                "task_id": task.id,
                "noshow_id": novo_noshow.id
            }
        except Exception as e:
            logger.error(f"Erro ao disparar task de no-show: {str(e)}")
            return {
                "message": "Agendamento marcado como no-show, mas houve erro ao disparar notificações.",
                "error": str(e)
            }

    except CompanyOperationallyBlockedError as exc:
        db.rollback()
        raise HTTPException(
            status_code=423,
            detail=f"Acesso operacional bloqueado: {exc.status}",
        ) from exc

    except HTTPException as he:
        raise he

    except Exception as e:
        logger.error(f"Erro em marcar_no_show: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao processar no-show: {str(e)}"
        )

def update_conversation_state_after_agendamento(
    db: Session,
    company_id: int,
    phone: str,
    agendamento_nome: Optional[str],
    consulta_data: Optional[datetime],
    agendamento_tratamento: Optional[str] = None,
):
    """
    Atualiza (ou cria, se não existir) o registro em conversation_state
    para refletir que já existe um agendamento confirmado para este phone.
    :param agendamento_tratamento: Se quiser pegar do campo "interesse" do agendamento, passe como string.
    """
    if not phone:
        return  # Se phone estiver vazio/nulo, não faz sentido atualizar conversation_state

    result = db.execute(
        text("""
            SELECT current_step, state_data
            FROM conversation_state
            WHERE phone = :phone AND company_id = :company_id
            LIMIT 1
        """),
        {"phone": phone, "company_id": company_id}
    ).fetchone()

    if result:
        # 1) Já existe; mesclar dados
        current_step = result[0] or 0
        state_data = result[1] or {}

        # Garantir step >= 7 (pós-agendamento)
        if current_step < 7:
            current_step = 7

        # Ajustar campos:
        if agendamento_nome:
            state_data["nome"] = agendamento_nome
        if agendamento_tratamento:
            state_data["tratamento"] = agendamento_tratamento
        # Se não existir 'cliente', define como "novo"
        if "cliente" not in state_data:
            state_data["cliente"] = "novo"

        if consulta_data:
            data_str = consulta_data.strftime("%d/%m/%Y")
            hora_str = consulta_data.strftime("%H:%M")
            state_data["data"] = data_str
            state_data["horario"] = hora_str

        state_data["agendamento_confirmado"] = True

        db.execute(
            text("""
                UPDATE conversation_state
                SET current_step = :step,
                    state_data = CAST(:data as JSONB),
                    updated_at = CURRENT_TIMESTAMP
                WHERE phone = :phone
                  AND company_id = :company_id
            """),
            {
                "step": current_step,
                "data": json.dumps(state_data),
                "phone": phone,
                "company_id": company_id
            }
        )
        db.commit()

    else:
        # 2) Não existe; cria registro
        initial_data = {}

        if agendamento_nome:
            initial_data["nome"] = agendamento_nome
        if agendamento_tratamento:
            initial_data["tratamento"] = agendamento_tratamento
        # Define cliente como "novo"
        initial_data["cliente"] = "novo"

        if consulta_data:
            initial_data["data"] = consulta_data.strftime("%d/%m/%Y")
            initial_data["horario"] = consulta_data.strftime("%H:%M")

        initial_data["agendamento_confirmado"] = True

        db.execute(
            text("""
                INSERT INTO conversation_state (phone, company_id, current_step, state_data, created_at, updated_at)
                VALUES (:phone, :company_id, :step, CAST(:data as JSONB), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {
                "phone": phone,
                "company_id": company_id,
                "step": 7,  # Step pós-agendamento
                "data": json.dumps(initial_data)
            }
        )
        db.commit()

def remove_conversation_state_if_no_appointments(
    db: Session,
    company_id: int,
    phone: str
):
    """
    Verifica se ainda existem agendamentos ativos para (company_id, phone).
    Se não existir mais nenhum, remove o registro correspondente em conversation_state
    E também apaga o arquivo de chat memory .txt correspondente.
    """
    if not phone:
        return

    qtd = db.execute(
        text("""
            SELECT COUNT(*)
            FROM agendamentos
            WHERE company_id = :company_id
              AND phone = :phone
        """),
        {"company_id": company_id, "phone": phone}
    ).scalar()

    # Se não há mais agendamentos
    if qtd == 0:
        # 1) Remove conversation_state
        db.execute(
            text("""
                DELETE FROM conversation_state
                WHERE phone = :phone
                  AND company_id = :company_id
            """),
            {"phone": phone, "company_id": company_id}
        )
        db.commit()

        # 2) Exclui também o arquivo de chat memory,
        #    caso exista algo como chatmemory_{company_id}_{phone}.txt
        #    Ajuste o nome do arquivo de acordo com seu padrão real.
        chatmemory_filename = f"chatmemory_{company_id}_{phone}.txt"
        filepath = os.path.join(CHATMEMORY_PATH, chatmemory_filename)

        try:
            os.remove(filepath)
            logger.info(f"[remove_conversation_state] Arquivo de chat removido: {filepath}")
        except FileNotFoundError:
            logger.warning(f"[remove_conversation_state] Arquivo de chat não encontrado: {filepath}")
        except Exception as e:
            logger.error(f"[remove_conversation_state] Erro ao remover arquivo de chat: {e}")

def _get_active_integration_type(db: Session, company_id: int) -> Optional[str]:
    """
    Verifica a tabela calendar_integrations e retorna o tipo de integração
    ativa ('google' ou 'clinicorp') para a company_id especificada.

    Args:
        db: A sessão do banco de dados SQLAlchemy.
        company_id: O ID da empresa para verificar a integração.

    Returns:
        O nome do provedor ('google' ou 'clinicorp') se uma integração
        válida e ativa for encontrada, caso contrário None.
    """
    # A configuração é resolvida para qualquer empresa autorizada.

    logger.debug(f"Verificando tipo de integração ativa para company_id={company_id}")

    # Busca a configuração de integração para a empresa especificada
    integration = db.query(CalendarIntegration).filter(
        CalendarIntegration.company_id == company_id
    ).first()

    # Se não houver nenhuma configuração para esta empresa no banco
    if not integration:
        logger.debug(f"Nenhuma entrada encontrada em calendar_integrations para company_id={company_id}.")
        return None

    provider = integration.provider
    is_valid = False # Flag para indicar se a configuração encontrada é válida/utilizável

    # Validação específica para cada provedor conhecido
    if provider == 'google':
        has_linked_agenda = db.query(Agenda.id).filter(
            Agenda.company_id == company_id,
            Agenda.google_calendar_id.isnot(None),
        ).first()
        # Para Google, precisamos do OAuth e de pelo menos uma agenda Google vinculada.
        if getattr(integration, "google_oauth_token", None) and (integration.google_calendar_id or has_linked_agenda):
            is_valid = True
        else:
            # Loga um aviso se a integração existe mas falta informação essencial
            logger.warning(f"Integração Google encontrada para company_id={company_id}, mas não há agenda Google vinculada ou token OAuth.")

    elif provider == 'clinicorp':
        # Para Clinicorp, verificamos os campos mínimos de credenciais
        if (integration.clinicorp_username and
            integration.clinicorp_password and
            integration.clinicorp_subscriber_id):
            is_valid = True
        else:
            # Loga um aviso se a integração existe mas falta informação essencial
            logger.warning(f"Integração Clinicorp encontrada para company_id={company_id}, mas configuração está incompleta (faltam credenciais).")

    else:
        # Loga um aviso se o provedor na tabela não é reconhecido
        logger.warning(f"Provider '{provider}' desconhecido encontrado para company_id={company_id} na tabela calendar_integrations.")

    # Retorna o nome do provedor APENAS se a configuração foi considerada válida
    if is_valid:
        logger.info(f"Integração ativa e válida encontrada para company_id={company_id}: {provider}")
        return provider
    else:
        # Loga que uma configuração foi encontrada, mas não passou na validação
        logger.debug(f"Configuração de integração encontrada para company_id={company_id} (provedor: {provider}) mas é considerada inválida/incompleta.")
        return None
