import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, validator
from datetime import datetime
from backend.routes.agendamento_routes import remove_conversation_state_if_no_appointments

from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import (
    Client,
    Contact,
    Customer,
    CustomerManagedCompany,
    Lead,
    LeadCustomField,
    LeadCustomValue,
    Message,
)
from backend.services.company_access_control import (
    CompanyOperationallyBlockedError,
    ensure_company_operational,
    lock_entities_for_mutation,
)
from backend.services.leads_with_custom_fields_service import (
    LeadsWithCustomFieldsService,
    LeadCreateWithCustom,
    LeadUpdateWithCustom,
    LeadWithCustomFieldsResponse
)

logger = logging.getLogger("saas_business.leads")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/leads",
    tags=["Leads"]
)


def _trigger_flow_lead_created(db: Session, lead_id: int, source: str) -> None:
    try:
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            logger.warning("[FlowBuilder] Lead criado nao encontrado para disparo lead_created id=%s", lead_id)
            return

        from backend.services.flow_event_service import trigger_crm_lead_created

        started_flows = trigger_crm_lead_created(db, lead=lead, created_at=lead.created_at)
        if started_flows:
            logger.info(
                "[FlowBuilder] %s fluxo(s) lead_created iniciados para lead_id=%s source=%s",
                started_flows,
                lead.id,
                source,
            )
    except Exception as flow_event_err:
        logger.error(
            "[FlowBuilder] Erro ao iniciar fluxos lead_created para lead_id=%s source=%s: %s",
            lead_id,
            source,
            flow_event_err,
        )


# -- Função para verificar API Key --
async def verify_api_key(
    api_key: str = Header(..., alias="X-API-Key"),
    client_id: int = None,
    db: Session = Depends(get_db)
):
    """
    Verifica se a API key é válida para o client_id fornecido
    """
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

# =========================
# Schemas Pydantic
# =========================

class LeadCreate(BaseModel):
    client_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[str] = None
    data_entrada: Optional[str] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None

    @validator("data_entrada")
    def parse_data_entrada(cls, value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError(
                "A data/hora deve estar no formato YYYY-MM-DD HH:MM:SS"
            )

class LeadUpdate(BaseModel):
    client_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[str] = None
    data_entrada: Optional[datetime] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None

class LeadResponse(BaseModel):
    id: int
    client_id: Optional[int] = None
    company_id: Optional[int] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = None
    data_entrada: Optional[datetime] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None
    current_stage_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    pipeline_entered_at: Optional[datetime] = None
    last_stage_move_at: Optional[datetime] = None
    deal_value: Optional[float] = None

    class Config:
        orm_mode = True

# =========================
# Schemas para Campos Customizados
# =========================

class LeadCustomFieldCreate(BaseModel):
    field_name: str
    field_key: str
    field_type: Literal['text', 'number', 'email', 'date', 'select', 'textarea']
    is_required: bool = False
    default_value: Optional[Any] = None
    validation_rules: Optional[Dict[str, Any]] = None
    display_order: int = 0
    is_active: bool = True

    @validator('field_name')
    def field_name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('field_name não pode estar vazio')
        return v.strip()

    @validator('field_key')
    def field_key_format(cls, v):
        if not v or not v.strip():
            raise ValueError('field_key não pode estar vazio')
        v = v.strip()
        if not v[0].isalpha():
            raise ValueError('field_key deve começar com uma letra')
        if not all(c.isalnum() or c == '_' for c in v):
            raise ValueError('field_key deve conter apenas letras, números e underscores')
        return v

    @validator('display_order')
    def display_order_positive(cls, v):
        if v < 0:
            raise ValueError('display_order deve ser um número positivo')
        return v

class LeadCustomFieldUpdate(BaseModel):
    field_name: Optional[str] = None
    field_type: Optional[Literal['text', 'number', 'email', 'date', 'select', 'textarea']] = None
    is_required: Optional[bool] = None
    default_value: Optional[Any] = None
    validation_rules: Optional[Dict[str, Any]] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None

class LeadCustomFieldResponse(BaseModel):
    id: int
    company_id: int
    field_name: str
    field_key: str
    field_type: str
    is_required: bool
    default_value: Optional[Any] = None
    validation_rules: Optional[Dict[str, Any]] = None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class LeadCustomValueCreate(BaseModel):
    custom_field_id: int
    value: Any

class LeadCustomValueUpdate(BaseModel):
    value: Any

class LeadCustomValueResponse(BaseModel):
    id: int
    custom_field_id: int
    value: Any
    field_name: str
    field_key: str
    field_type: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

class FieldOrderRequest(BaseModel):
    field_id: int
    display_order: int

# Schemas atualizados para incluir campos customizados
class LeadCreateWithCustom(BaseModel):
    client_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[str] = None
    data_entrada: Optional[str] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None
    custom_values: Optional[List[LeadCustomValueCreate]] = []

    @validator("data_entrada")
    def parse_data_entrada(cls, value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError(
                "A data/hora deve estar no formato YYYY-MM-DD HH:MM:SS"
            )

class LeadUpdateWithCustom(BaseModel):
    client_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[str] = None
    data_entrada: Optional[datetime] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None
    custom_values: Optional[List[LeadCustomValueCreate]] = []

class LeadWithCustomFieldsResponse(BaseModel):
    id: int
    client_id: Optional[int] = None
    company_id: Optional[int] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = None
    data_entrada: Optional[datetime] = None
    source_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sender_lid: Optional[str] = None
    follow_up_sequence_id: Optional[int] = None
    current_stage_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    pipeline_entered_at: Optional[datetime] = None
    last_stage_move_at: Optional[datetime] = None
    custom_values: List[LeadCustomValueResponse] = []

    class Config:
        orm_mode = True

class LeadCustomFieldsValidationRequest(BaseModel):
    values: Dict[str, Any]  # field_key -> value

# =========================
# Rotas CRUD de Leads
# =========================

# =========================
# Schemas para Histórico
# =========================

class LeadPipelineHistoryResponse(BaseModel):
    id: int
    lead_id: int
    company_id: int
    from_stage_id: Optional[int] = None
    to_stage_id: int
    moved_by_user_id: Optional[int] = None
    moved_at: datetime
    notes: Optional[str] = None
    time_in_previous_stage: Optional[int] = None

    class Config:
        orm_mode = True

@router.get("/history", response_model=List[LeadPipelineHistoryResponse])
async def obter_historico_leads(
    client_id: int,
    company_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Retorna o histórico de movimentação de leads entre estágios.
    Útil para métricas de funil baseadas em quando o lead entrou no estágio.
    """
    logger.info(f"[obter_historico_leads] client_id={client_id}, company_id={company_id}, start={start_date}, end={end_date}")
    try:
        from backend.models import LeadPipelineHistory

        query = db.query(LeadPipelineHistory).filter(
            LeadPipelineHistory.company_id == company_id
        )

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                query = query.filter(LeadPipelineHistory.moved_at >= start_dt)
            except ValueError:
                pass # Ignorar se formato inválido

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                # Ajustar para final do dia
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(LeadPipelineHistory.moved_at <= end_dt)
            except ValueError:
                pass

        history = query.all()
        logger.info(f"[obter_historico_leads] Retornando {len(history)} registros.")
        return history
    except Exception as e:
        logger.exception("[obter_historico_leads] Erro ao buscar histórico")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.get("/", response_model=List[LeadWithCustomFieldsResponse])
async def listar_leads(
    client_id: int,
    company_id: int,
    pipeline_id: Optional[int] = None,
    stage_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Lista todos os leads de um client_id e company_id específicos.
    Suporta filtros por pipeline_id e stage_id para integração com Kanban CRM.
    Retorna também os campos customizados (UTMs, etc) de cada lead.
    """
    logger.info(f"[listar_leads] client_id={client_id}, company_id={company_id}, pipeline_id={pipeline_id}, stage_id={stage_id}")
    try:
        leads_with_custom = LeadsWithCustomFieldsService.list_leads_with_custom_fields(
            client_id, company_id, db, pipeline_id, stage_id
        )
        logger.info(f"[listar_leads] Retornando {len(leads_with_custom)} registros com campos customizados.")
        return leads_with_custom
    except Exception as e:
        logger.exception("[listar_leads] Erro ao listar leads")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.get("/{lead_id}", response_model=LeadWithCustomFieldsResponse)
async def obter_lead(
    client_id: int,
    company_id: int,
    lead_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Obtém um lead específico pelo ID, associado a client_id e company_id.
    """
    logger.info(f"[obter_lead] client_id={client_id}, company_id={company_id}, lead_id={lead_id}")
    try:
        lead_with_custom = LeadsWithCustomFieldsService.get_lead_with_custom_fields(
            lead_id, company_id, db
        )

        if not lead_with_custom:
            logger.warning("[obter_lead] Lead não encontrado.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead não encontrado para este cliente/empresa."
            )

        return lead_with_custom
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[obter_lead] Erro ao obter lead")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def criar_lead(
    client_id: int,
    company_id: int,
    payload: LeadCreateWithCustom,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Cria um novo lead e, caso necessário, insere/atualiza também na tabela contacts.
    Verifica se já existe lead para evitar duplicação.
    """
    logger.info(f"[criar_lead] client_id={client_id}, company_id={company_id}, payload={payload.dict()}")

    # 1. Primeiro verificar se já existe contato
    contato_existente = db.query(Contact).filter(
        Contact.client_id == client_id,
        Contact.company_id == company_id,
        Contact.phone == payload.phone
    ).first()

    # 2. Se contato existe, verificar se já tem lead
    if contato_existente:
        lead_existente = db.query(Lead).filter(
            Lead.phone == payload.phone,
            Lead.company_id == company_id
        ).first()

        if lead_existente:
            logger.warning(f"[criar_lead] Lead já existe para telefone {payload.phone} na empresa {company_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Já existe um lead para o telefone {payload.phone} nesta empresa. Nome: {lead_existente.name}"
            )

    # 3. Cria o lead (e campos customizados) usando o service
    try:
        novo_lead = LeadsWithCustomFieldsService.create_lead_with_custom_fields(
            payload, client_id, company_id, db
        )
        logger.info(f"[criar_lead] Novo lead criado com campos customizados. id={novo_lead.id}")

        # 4. Criar/atualizar contato (usar a variável já definida acima)
        try:
            if contato_existente:
                # Contato existe, apenas atualizar nome se necessário
                if novo_lead.name and contato_existente.name != novo_lead.name:
                    contato_existente.name = novo_lead.name
                    db.commit()
                    logger.info(f"[criar_lead] Contato existente atualizado. id={contato_existente.id}")
            else:
                # Contato não existe, criar novo
                contato_novo = Contact(
                    client_id=client_id,
                    company_id=company_id,
                    phone=novo_lead.phone,
                    name=novo_lead.name
                )
                db.add(contato_novo)
                db.commit()
                logger.info(f"[criar_lead] Contato criado para lead.id={novo_lead.id}, phone={novo_lead.phone}")

        except Exception as e:
            db.rollback()
            logger.exception("[criar_lead] Erro ao sincronizar contato")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro ao sincronizar contato: {str(e)}"
            )

        _trigger_flow_lead_created(db, int(novo_lead.id), "crm_manual")
        return novo_lead

    except Exception as e:
        logger.exception("[criar_lead] Erro ao criar lead")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar lead: {str(e)}"
        )



@router.put("/{lead_id}", response_model=LeadResponse)
async def atualizar_lead(
    client_id: int,
    company_id: int,
    lead_id: int,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Atualiza os campos de um lead e reflete as mudanças também na tabela contacts.
    """
    logger.info(f"[atualizar_lead] client_id={client_id}, company_id={company_id}, lead_id={lead_id}")
    lead = db.query(Lead).filter(
        Lead.id == lead_id,
        Lead.company_id == company_id,
        Lead.client_id == str(client_id)
    ).first()

    if not lead:
        logger.warning("[atualizar_lead] Lead não encontrado.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado para este cliente/empresa."
        )

    campos_para_atualizar = payload.dict(exclude_unset=True)
    for campo, valor in campos_para_atualizar.items():
        setattr(lead, campo, valor)

    # Aqui precisamos verificar se o telefone foi alterado ou não
    telefone_antigo = lead.phone

    try:
        db.commit()
        db.refresh(lead)
        logger.info(f"[atualizar_lead] Lead atualizado. id={lead.id}")
    except Exception as e:
        db.rollback()
        logger.exception("[atualizar_lead] Erro ao atualizar lead")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao atualizar lead: {str(e)}"
        )

    # Ajuste de contato após atualização do Lead
    try:
        # Se o phone não foi passado na atualização, significa que permanece igual
        # ou então está em campos_para_atualizar, mas é o mesmo valor.
        # De qualquer forma, consultamos o phone atual que está no lead.
        telefone_novo = lead.phone

        if telefone_novo:
            # Verifica se já existe um contato para (client_id, company_id, telefone_novo)
            contato_existente = db.query(Contact).filter(
                Contact.client_id == client_id,
                Contact.company_id == company_id,
                Contact.phone == telefone_novo
            ).first()

            if not contato_existente:
                # Se não existe, pode ser que o telefone mudou; então removemos o contato antigo (se existir)
                # e criamos um novo. Ou simplesmente criamos se não existia nenhum.
                # Verificar se existia contato com o telefone antigo:
                if telefone_antigo and telefone_antigo != telefone_novo:
                    contato_antigo = db.query(Contact).filter(
                        Contact.client_id == client_id,
                        Contact.company_id == company_id,
                        Contact.phone == telefone_antigo
                    ).first()
                    if contato_antigo:
                        db.delete(contato_antigo)
                        db.commit()
                        logger.info(f"[atualizar_lead] Contato antigo removido. phone={telefone_antigo}")

                # Criar contato novo com o telefone atualizado
                contato_novo = Contact(
                    client_id=client_id,
                    company_id=company_id,
                    phone=telefone_novo,
                    name=lead.name
                )
                db.add(contato_novo)
                db.commit()
                logger.info(f"[atualizar_lead] Contato novo criado p/ phone={telefone_novo}")

            else:
                # Se já existe contato com telefone_novo, apenas atualizamos o nome (se necessário)
                if lead.name and contato_existente.name != lead.name:
                    contato_existente.name = lead.name
                    db.commit()
                    logger.info(f"[atualizar_lead] Contato existente atualizado. id={contato_existente.id}")
    except Exception as e:
        db.rollback()
        logger.exception("[atualizar_lead] Erro ao sincronizar contato (atualização)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao sincronizar contato: {str(e)}"
        )

    return lead

@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_lead(
    client_id: int,
    company_id: int,
    lead_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Deleta um lead e, caso seja a regra de negócio, pode remover também
    o contato e as mensagens associadas a esse phone, desde que não haja
    mais nenhum lead que utilize esse número de telefone.

    Agora, após a remoção, chamamos remove_conversation_state_if_no_appointments
    para apagar o conversation_state e o arquivo .txt, caso não haja
    mais agendamentos para o (company_id, phone).
    """
    logger.info(f"[deletar_lead] client_id={client_id}, company_id={company_id}, lead_id={lead_id}")

    lock_entities_for_mutation(
        db,
        company_ids=[company_id],
        client_ids=[client_id],
    )
    actor = (
        db.query(Client)
        .filter(Client.id == client_id)
        .with_for_update()
        .first()
    )
    if not actor or not actor.is_active:
        raise HTTPException(status_code=423, detail="Acesso suspenso")
    try:
        ensure_company_operational(db, company_id)
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(status_code=423, detail="Acesso suspenso") from exc

    # 1. Buscar o lead
    lead = (
        db.query(Lead)
        .filter(
            Lead.id == lead_id,
            Lead.company_id == company_id,
            Lead.client_id == str(client_id),
        )
        .with_for_update()
        .first()
    )

    if not lead:
        logger.warning("[deletar_lead] Lead não encontrado.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado para este cliente/empresa."
        )

    telefone = lead.phone

    # 2. Excluir dados do funil relacionados ao lead (mantendo contato e mensagens)
    try:
        from sqlalchemy import text

        linked_workspace = (
            db.query(CustomerManagedCompany.id)
            .join(Customer, Customer.id == CustomerManagedCompany.customer_id)
            .filter(
                CustomerManagedCompany.owner_company_id == company_id,
                Customer.convertido_de_lead_id == lead_id,
            )
            .with_for_update()
            .first()
        )
        if linked_workspace:
            raise HTTPException(
                status_code=409,
                detail="Lead convertido em cliente com workspace vinculado não pode ser excluído",
            )

        # 2.1. Excluir vendas dos comparecimentos dos agendamentos do lead
        vendas_result = db.execute(text("""
            DELETE FROM vendas v
            USING comparecimentos comp, agendamentos a
            WHERE v.comparecimento_id = comp.id
              AND comp.agendamento_id = a.id
              AND a.lead_id = :lead_id
        """), {"lead_id": lead_id})
        vendas_deleted = vendas_result.rowcount

        # 2.2. Excluir comparecimentos dos agendamentos do lead
        comparecimentos_result = db.execute(text("""
            DELETE FROM comparecimentos comp
            USING agendamentos a
            WHERE comp.agendamento_id = a.id
              AND a.lead_id = :lead_id
        """), {"lead_id": lead_id})
        comparecimentos_deleted = comparecimentos_result.rowcount

        # 2.3. Excluir no-shows dos agendamentos do lead
        noshows_result = db.execute(text("""
            DELETE FROM noshow_events ns
            USING agendamentos a
            WHERE ns.agendamento_id = a.id
              AND a.lead_id = :lead_id
        """), {"lead_id": lead_id})
        noshows_deleted = noshows_result.rowcount

        # 2.4. Excluir agendamentos do lead
        agendamentos_result = db.execute(text("""
            DELETE FROM agendamentos
            WHERE lead_id = :lead_id
        """), {"lead_id": lead_id})
        agendamentos_deleted = agendamentos_result.rowcount

        # 2.5. Excluir APENAS clientes convertidos deste lead específico
        # NÃO excluir clientes que existiam antes ou foram criados por outros meios
        clientes_result = db.execute(text("""
            DELETE FROM customers
            WHERE convertido_de_lead_id = :lead_id
        """), {"lead_id": lead_id})
        clientes_deleted = clientes_result.rowcount

        # 2.6. Excluir manualmente o histórico do pipeline (workaround CASCADE issue)
        # Este workaround é necessário pois o CASCADE DELETE do SQLAlchemy não está funcionando
        # como esperado em alguns cenários, mesmo com a configuração correta no banco
        history_result = db.execute(text("""
            DELETE FROM lead_pipeline_history
            WHERE lead_id = :lead_id
        """), {"lead_id": lead_id})
        history_deleted = history_result.rowcount

        # 2.7. Finalmente, excluir o lead
        db.delete(lead)

        db.commit()
        logger.info(f"[deletar_lead] ✅ Exclusão do funil completa para lead {lead_id}:")
        logger.info(f"  - Lead deletado: 1")
        logger.info(f"  - Histórico pipeline deletado: {history_deleted}")
        logger.info(f"  - Agendamentos deletados: {agendamentos_deleted}")
        logger.info(f"  - Comparecimentos deletados: {comparecimentos_deleted}")
        logger.info(f"  - Vendas deletadas: {vendas_deleted}")
        logger.info(f"  - No-shows deletados: {noshows_deleted}")
        logger.info(f"  - Clientes deletados: {clientes_deleted}")
        logger.info(f"  📱 PRESERVADO: Contato, mensagens e conversation state")

        return None

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("[deletar_lead] Erro ao deletar lead e dados do funil")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao deletar lead: {str(e)}"
        )


# =========================
# Novos endpoints com campos customizados
# =========================

@router.post("/", response_model=LeadWithCustomFieldsResponse, status_code=status.HTTP_201_CREATED)
async def criar_lead_com_custom_fields(
    client_id: int,
    company_id: int,
    lead_data: LeadCreateWithCustom,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Cria um novo lead com campos customizados.

    Este endpoint deve ser usado em vez do POST / quando precisar trabalhar com campos customizados.
    """
    logger.info(f"[criar_lead_com_custom_fields] client_id={client_id}, company_id={company_id}, lead_name={lead_data.name}")

    try:
        lead = LeadsWithCustomFieldsService.create_lead_with_custom_fields(
            lead_data, client_id, company_id, db
        )

        logger.info(f"[criar_lead_com_custom_fields] Lead criado com sucesso: id={lead.id}")
        _trigger_flow_lead_created(db, int(lead.id), "crm_custom_fields")
        return lead

    except ValueError as e:
        logger.warning(f"[criar_lead_com_custom_fields] Erro de validação: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.exception("[criar_lead_com_custom_fields] Erro ao criar lead com campos customizados")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.put("/{lead_id}", response_model=LeadWithCustomFieldsResponse)
async def atualizar_lead_com_custom_fields(
    client_id: int,
    company_id: int,
    lead_id: int,
    lead_data: LeadUpdateWithCustom,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Atualiza um lead existente com campos customizados.

    Este endpoint deve ser usado em vez do PUT /{lead_id} quando precisar trabalhar com campos customizados.
    """
    logger.info(f"[atualizar_lead_com_custom_fields] client_id={client_id}, company_id={company_id}, lead_id={lead_id}")

    try:
        lead = LeadsWithCustomFieldsService.update_lead_with_custom_fields(
            lead_id, lead_data, company_id, db
        )

        logger.info(f"[atualizar_lead_com_custom_fields] Lead atualizado com sucesso: id={lead.id}")
        return lead

    except ValueError as e:
        logger.warning(f"[atualizar_lead_com_custom_fields] Erro de validação: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.exception("[atualizar_lead_com_custom_fields] Erro ao atualizar lead com campos customizados")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


@router.post("/validate-custom-fields", status_code=status.HTTP_200_OK)
async def validate_lead_custom_fields(
    client_id: int,
    company_id: int,
    validation_request: LeadCustomFieldsValidationRequest,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Valida valores de campos customizados sem criar o lead.

    Útil para validação em tempo real em formulários frontend.
    """
    logger.info(f"[validate_lead_custom_fields] client_id={client_id}, company_id={company_id}")

    try:
        result = LeadsWithCustomFieldsService.validate_lead_custom_fields(
            company_id, validation_request.values, db
        )

        logger.info(f"[validate_lead_custom_fields] Validação concluída: is_valid={result['is_valid']}")
        return result

    except Exception as e:
        logger.exception("[validate_lead_custom_fields] Erro na validação de campos customizados")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )


# =========================
# Deal Value Endpoint (para Meta CAPI)
# =========================

class DealValueUpdate(BaseModel):
    deal_value: float

@router.patch("/{lead_id}/deal-value", response_model=LeadResponse)
async def update_lead_deal_value(
    client_id: int,
    company_id: int,
    lead_id: int,
    deal_value_update: DealValueUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Atualiza o valor do negócio (deal_value) de um lead.
    Usado quando lead é movido para 'Ganhou' no CRM.
    Esse valor é enviado para a Meta Conversions API.
    """
    logger.info(f"[update_deal_value] lead_id={lead_id}, deal_value={deal_value_update.deal_value}")

    try:
        lead = db.query(Lead).filter(
            Lead.id == lead_id,
            Lead.company_id == company_id
        ).first()

        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead não encontrado"
            )

        lead.deal_value = deal_value_update.deal_value
        db.commit()
        db.refresh(lead)

        logger.info(f"[update_deal_value] ✅ deal_value atualizado para lead {lead_id}: {deal_value_update.deal_value}")
        return lead

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[update_deal_value] Erro ao atualizar deal_value")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )
