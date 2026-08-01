import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import Venda, Client  # Ajuste se seus modelos têm outro local
# Se tiver um verify_api_key centralizado, importe aqui. Ou replique.

logger = logging.getLogger("saas_business.vendas")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/vendas",
    tags=["Vendas"]
)

# -----------------------------------------------------------------------------
# verify_api_key (caso não esteja importado de outro arquivo)
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
# Schemas (Pydantic)
# -----------------------------------------------------------------------------
class VendaCreate(BaseModel):
    """Campos usados ao criar uma nova venda."""
    lead_id: int
    comparecimento_id: int
    nome: Optional[str] = None
    phone: Optional[str] = None
    tratamento_fechado: Optional[str] = None
    valor_faturado: Optional[float] = None
    valor_pago: Optional[float] = None

    # Se você quiser permitir passar a data manualmente ao criar a venda:
    venda_data: Optional[datetime] = None


class VendaUpdate(BaseModel):
    """
    Campos editáveis em uma venda.
    Deixamos de fora lead_id, comparecimento_id e client_id/company_id
    (pois são sensíveis e não devem ser alterados depois de criado).
    """
    nome: Optional[str] = None
    phone: Optional[str] = None
    tratamento_fechado: Optional[str] = None
    valor_faturado: Optional[float] = None
    valor_pago: Optional[float] = None

    # Se quiser permitir atualizar a data da venda:
    venda_data: Optional[datetime] = None


class VendaResponse(BaseModel):
    """
    O que retornamos ao cliente após criar/obter/atualizar uma venda.
    Inclui todos os campos da tabela, inclusive IDs e data da venda.
    """
    id: int
    client_id: int
    company_id: Optional[int]
    lead_id: int
    comparecimento_id: int
    venda_data: datetime
    nome: Optional[str]
    phone: Optional[str]
    tratamento_fechado: Optional[str]
    valor_faturado: Optional[float]
    valor_pago: Optional[float]

    class Config:
        orm_mode = True

# -----------------------------------------------------------------------------
# Rotas CRUD
# -----------------------------------------------------------------------------

@router.get("/", response_model=List[VendaResponse])
async def listar_vendas(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Lista todas as vendas de um client/company
    """
    logger.info(f"[listar_vendas] client_id={client_id}, company_id={company_id}")
    try:
        vendas = db.query(Venda).filter(
            Venda.client_id == client_id,
            Venda.company_id == company_id
        ).all()
        logger.info(f"[listar_vendas] Retornando {len(vendas)} registros.")
        return vendas
    except Exception as e:
        logger.exception("[listar_vendas] Erro ao listar vendas")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.get("/{venda_id}", response_model=VendaResponse)
async def obter_venda(
    client_id: int,
    company_id: int,
    venda_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Obtém uma venda específica pelo ID.
    """
    logger.info(f"[obter_venda] client_id={client_id}, company_id={company_id}, venda_id={venda_id}")
    try:
        venda = db.query(Venda).filter(
            Venda.id == venda_id,
            Venda.client_id == client_id,
            Venda.company_id == company_id
        ).first()
        if not venda:
            logger.warning("[obter_venda] Venda não encontrada.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Venda não encontrada para este cliente/empresa."
            )
        return venda
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[obter_venda] Erro ao obter venda")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.post("/", response_model=VendaResponse, status_code=status.HTTP_201_CREATED)
async def criar_venda(
    client_id: int,
    company_id: int,
    payload: VendaCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Cria uma nova venda.
    """
    logger.info(f"[criar_venda] client_id={client_id}, company_id={company_id}, payload={payload.dict()}")
    nova_venda = Venda(
        client_id=client_id,
        company_id=company_id,
        lead_id=payload.lead_id,
        comparecimento_id=payload.comparecimento_id,
        nome=payload.nome,
        phone=payload.phone,
        tratamento_fechado=payload.tratamento_fechado,
        valor_faturado=payload.valor_faturado,
        valor_pago=payload.valor_pago,
        venda_data=payload.venda_data
    )
    db.add(nova_venda)
    try:
        db.commit()
        db.refresh(nova_venda)
        logger.info(f"[criar_venda] Nova venda criada. id={nova_venda.id}")

        # Disparar follow-up pós-venda se configurado
        try:
            from sqlalchemy import text

            # Verificar se existe sequência de pós-venda ativa
            first_step = db.execute(
                text("""
                    SELECT ps.id, ps.send_after, ps.send_after_unit
                    FROM pos_venda_steps ps
                    JOIN pos_venda_sequences pqs ON ps.pos_venda_sequence_id = pqs.id
                    WHERE pqs.company_id = :company_id
                      AND pqs.active = true
                      AND ps.step_number = 1
                    ORDER BY ps.step_number
                    LIMIT 1
                """),
                {"company_id": company_id}
            ).fetchone()

            if first_step:
                from backend.worker.tasks_pos_venda import enviar_passo_pos_venda
                from datetime import datetime, timedelta

                # Calcular ETA baseado na configuração do primeiro step
                delta = {}
                if first_step.send_after_unit == "days":
                    delta["days"] = first_step.send_after
                elif first_step.send_after_unit == "hours":
                    delta["hours"] = first_step.send_after
                elif first_step.send_after_unit == "minutes":
                    delta["minutes"] = first_step.send_after

                eta = datetime.utcnow() + timedelta(**delta)

                # Registrar execução agendada
                db.execute(
                    text("""
                        INSERT INTO pos_venda_executions
                        (venda_id, lead_id, company_id, pos_venda_sequence_id, pos_venda_step_id,
                         step_number, status, scheduled_for)
                        VALUES
                        (:venda_id, :lead_id, :company_id,
                         (SELECT id FROM pos_venda_sequences WHERE company_id = :company_id AND active = true LIMIT 1),
                         :step_id, 1, 'SCHEDULED', :eta)
                    """),
                    {
                        "venda_id": nova_venda.id,
                        "lead_id": payload.lead_id,
                        "company_id": company_id,
                        "step_id": first_step.id,
                        "eta": eta
                    }
                )
                db.commit()

                # Disparar task
                enviar_passo_pos_venda.apply_async(
                    args=[nova_venda.id, 1, company_id, payload.lead_id, payload.phone or ""],
                    eta=eta
                )
                logger.info(f"[criar_venda] Follow-up pós-venda agendado para {eta} (após {first_step.send_after} {first_step.send_after_unit})")
        except Exception as e:
            logger.error(f"[criar_venda] Erro ao agendar follow-up pós-venda: {str(e)}")
            # Não falha a criação da venda se houver erro no follow-up

        # Verificar se contato é cliente e converter automaticamente se não for
        try:
            # Buscar contato pelo telefone
            contact_result = db.execute(
                text("""
                    SELECT id FROM contacts
                    WHERE phone = :phone AND company_id = :company_id
                    LIMIT 1
                """),
                {"phone": payload.phone, "company_id": company_id}
            ).fetchone()

            if contact_result:
                contact_id = contact_result.id

                # Verificar se já é cliente
                customer_exists = db.execute(
                    text("""
                        SELECT id FROM customers
                        WHERE contact_id = :contact_id
                        LIMIT 1
                    """),
                    {"contact_id": contact_id}
                ).fetchone()

                if not customer_exists:
                    # Converter para cliente automaticamente
                    from backend.models import Customer

                    new_customer = Customer(
                        contact_id=contact_id,
                        company_id=company_id,
                        nome=payload.nome,
                        telefone=payload.phone,
                        categoria='cliente',
                        status='ativo'
                    )

                    db.add(new_customer)
                    db.commit()
                    logger.info(f"[criar_venda] ✅ Contato {payload.nome} ({payload.phone}) convertido automaticamente para cliente após venda")
                else:
                    logger.info(f"[criar_venda] Contato {payload.nome} ({payload.phone}) já é cliente")
            else:
                logger.warning(f"[criar_venda] Contato não encontrado para telefone {payload.phone}")

        except Exception as e:
            logger.error(f"[criar_venda] Erro ao verificar/criar cliente: {str(e)}")
            # Não falha a criação da venda se houver erro na conversão

        return nova_venda
    except Exception as e:
        db.rollback()
        logger.exception("[criar_venda] Erro ao criar venda")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao criar venda: {str(e)}"
        )

@router.put("/{venda_id}", response_model=VendaResponse)
async def atualizar_venda(
    client_id: int,
    company_id: int,
    venda_id: int,
    payload: VendaUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Atualiza uma venda específica.
    """
    logger.info(f"[atualizar_venda] client_id={client_id}, company_id={company_id}, venda_id={venda_id}")
    venda = db.query(Venda).filter(
        Venda.id == venda_id,
        Venda.client_id == client_id,
        Venda.company_id == company_id
    ).first()

    if not venda:
        logger.warning("[atualizar_venda] Venda não encontrada.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Venda não encontrada para este cliente/empresa."
        )

    campos_para_atualizar = payload.dict(exclude_unset=True)
    for campo, valor in campos_para_atualizar.items():
        setattr(venda, campo, valor)

    try:
        db.commit()
        db.refresh(venda)
        logger.info(f"[atualizar_venda] Venda atualizada. id={venda.id}")
        return venda
    except Exception as e:
        db.rollback()
        logger.exception("[atualizar_venda] Erro ao atualizar venda")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao atualizar venda: {str(e)}"
        )

@router.delete("/{venda_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_venda(
    client_id: int,
    company_id: int,
    venda_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Deleta uma venda específica.
    """
    logger.info(f"[deletar_venda] client_id={client_id}, company_id={company_id}, venda_id={venda_id}")
    venda = db.query(Venda).filter(
        Venda.id == venda_id,
        Venda.client_id == client_id,
        Venda.company_id == company_id
    ).first()

    if not venda:
        logger.warning("[deletar_venda] Venda não encontrada.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Venda não encontrada para este cliente/empresa."
        )

    try:
        db.delete(venda)
        db.commit()
        logger.info(f"[deletar_venda] Venda deletada. id={venda.id}")
        return None
    except Exception as e:
        db.rollback()
        logger.exception("[deletar_venda] Erro ao deletar venda")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao deletar venda: {str(e)}"
        )
