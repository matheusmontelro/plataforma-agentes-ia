import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import text

from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import Comparecimento, Client
# Ajuste o import do verify_api_key se estiver separado ou replique aqui
# Exemplo: from .auth_utils import verify_api_key

logger = logging.getLogger("saas_business.comparecimentos")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/comparecimentos",
    tags=["Comparecimentos"]
)

# --------------------
# Função para verificar API Key
# --------------------
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

# --------------------
# Schemas Pydantic
# --------------------
class ComparecimentoCreate(BaseModel):
    """
    Schema para criação de um novo Comparecimento.
    Inclui todos os campos, menos o ID, pois normalmente
    ele é autoincremental no banco.
    """
    client_id: Optional[int] = None  # Caso queira sobrescrever (se não, pode remover)
    company_id: Optional[int] = None  # Caso queira sobrescrever (se não, pode remover)
    lead_id: int
    agendamento_id: int
    nome: Optional[str] = None
    phone: Optional[str] = None
    midia: Optional[str] = None
    interesse: Optional[str] = None
    tratamento_orcado: Optional[str] = None
    valor_orcamento: Optional[float] = None
    compareceu_em: Optional[datetime] = None  # Se quiser permitir sobrescrever data/hora

class ComparecimentoUpdate(BaseModel):
    """
    Schema para edição de um Comparecimento.
    Todos os campos são opcionais, pois podemos editar
    apenas parte deles.
    """
    client_id: Optional[int] = None
    company_id: Optional[int] = None
    lead_id: Optional[int] = None
    agendamento_id: Optional[int] = None
    nome: Optional[str] = None
    phone: Optional[str] = None
    midia: Optional[str] = None
    interesse: Optional[str] = None
    tratamento_orcado: Optional[str] = None
    valor_orcamento: Optional[float] = None
    compareceu_em: Optional[datetime] = None

class ComparecimentoResponse(BaseModel):
    """
    Schema de resposta (leitura) para um Comparecimento,
    incluindo todos os campos da tabela.
    """
    id: int
    client_id: int
    company_id: Optional[int]
    lead_id: int
    agendamento_id: int
    compareceu_em: datetime
    nome: Optional[str]
    phone: Optional[str]
    midia: Optional[str]
    interesse: Optional[str]
    tratamento_orcado: Optional[str]
    valor_orcamento: Optional[float]

    class Config:
        orm_mode = True

# --------------------
# ROTAS CRUD
# --------------------
@router.get("/", response_model=List[ComparecimentoResponse])
async def listar_comparecimentos(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Lista todos os comparecimentos de um client/company
    """
    logger.info(f"[listar_comparecimentos] client_id={client_id}, company_id={company_id}")
    try:
        comps = db.query(Comparecimento).filter(
            Comparecimento.client_id == client_id,
            Comparecimento.company_id == company_id
        ).all()
        logger.info(f"[listar_comparecimentos] Retornando {len(comps)} registros.")
        return comps
    except Exception as e:
        logger.exception("[listar_comparecimentos] Erro ao listar comparecimentos")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.get("/{comparecimento_id}", response_model=ComparecimentoResponse)
async def obter_comparecimento(
    client_id: int,
    company_id: int,
    comparecimento_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Obtém um comparecimento específico pelo ID.
    """
    logger.info(f"[obter_comparecimento] client_id={client_id}, company_id={company_id}, comparecimento_id={comparecimento_id}")
    try:
        comp = db.query(Comparecimento).filter(
            Comparecimento.id == comparecimento_id,
            Comparecimento.client_id == client_id,
            Comparecimento.company_id == company_id
        ).first()
        if not comp:
            logger.warning("[obter_comparecimento] Comparecimento não encontrado.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comparecimento não encontrado para este cliente/empresa."
            )
        return comp
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[obter_comparecimento] Erro ao obter comparecimento")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no servidor: {str(e)}"
        )

@router.post("/", response_model=ComparecimentoResponse, status_code=status.HTTP_201_CREATED)
async def criar_comparecimento(
    client_id: int,
    company_id: int,
    payload: ComparecimentoCreate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Cria um novo comparecimento.
    """
    logger.info(f"[criar_comparecimento] client_id={client_id}, company_id={company_id}, payload={payload.dict()}")

    # 1) Criar o registro Comparecimento
    novo_comp = Comparecimento(
        client_id=client_id,
        company_id=company_id,
        lead_id=payload.lead_id,
        agendamento_id=payload.agendamento_id,
        nome=payload.nome,
        phone=payload.phone,
        midia=payload.midia,
        interesse=payload.interesse,
        tratamento_orcado=payload.tratamento_orcado,
        valor_orcamento=payload.valor_orcamento,
        compareceu_em=payload.compareceu_em
    )
    db.add(novo_comp)

    try:
        db.commit()
        db.refresh(novo_comp)
        logger.info(f"[criar_comparecimento] Novo comparecimento criado. id={novo_comp.id}")

        # ------------------------------------------------------
        # 2) Remover registros de NoShow (se houver)
        #    - "noshow_events"
        #    - "noshow_follow_up_executions"
        # ------------------------------------------------------
        logger.info(f"[criar_comparecimento] Removendo no-show para agendamento_id={payload.agendamento_id}")
        db.execute(
            text("""
                DELETE FROM noshow_events
                WHERE agendamento_id = :ag_id
            """),
            {"ag_id": payload.agendamento_id}
        )
        db.execute(
            text("""
                DELETE FROM noshow_follow_up_executions
                WHERE lead_id = :lead_id
            """),
            {"lead_id": payload.lead_id}
        )
        db.commit()

        # ------------------------------------------------------
        # 3) (Opcional) Atualizar o status do agendamento para
        #    "COMPARECEU" ou algo similar
        # ------------------------------------------------------
        agendamento = db.execute(
            text("""
                SELECT id, status
                FROM agendamentos
                WHERE id = :ag_id
                LIMIT 1
            """),
            {"ag_id": payload.agendamento_id}
        ).fetchone()

        if agendamento:
            db.execute(
                text("""
                    UPDATE agendamentos
                    SET status = 'ATTENDED'  -- ou 'COMPARECEU'
                    WHERE id = :ag_id
                """),
                {"ag_id": agendamento.id}
            )
            db.commit()
            logger.info(f"[criar_comparecimento] Agendamento {agendamento.id} status -> 'ATTENDED'.")

        # ------------------------------------------------------
        # 4) Iniciar follow-up pós-consulta se configurado
        # ------------------------------------------------------
        try:
            # LIMPAR qualquer execução anterior para este comparecimento
            # (caso comparecimento tenha sido excluído e recriado)
            from backend.worker.tasks_pos_consulta import clear_pos_consulta_steps, cancel_pending_pos_consulta_executions

            # Limpar Redis
            clear_pos_consulta_steps(company_id, novo_comp.id)

            # Cancelar execuções pendentes no banco (se existirem)
            cancel_pending_pos_consulta_executions(db, novo_comp.id, "Comparecimento recriado")

            # Verificar se existe sequência pós-consulta ativa e buscar primeiro step
            first_step = db.execute(
                text("""
                    SELECT
                        seq.id as sequence_id,
                        step.id as step_id,
                        step.send_after,
                        step.send_after_unit
                    FROM pos_consulta_sequences seq
                    INNER JOIN pos_consulta_steps step ON step.pos_consulta_sequence_id = seq.id
                    WHERE seq.company_id = :company_id
                      AND seq.active = true
                      AND step.step_number = 1
                    LIMIT 1
                """),
                {"company_id": company_id}
            ).fetchone()

            if first_step:
                from backend.worker.tasks_pos_consulta import enviar_passo_pos_consulta
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

                # Registrar agendamento
                db.execute(
                    text("""
                        INSERT INTO pos_consulta_executions (
                            comparecimento_id, lead_id, company_id,
                            pos_consulta_sequence_id, pos_consulta_step_id, step_number,
                            status, scheduled_for
                        ) VALUES (
                            :comp_id, :lead_id, :company_id,
                            :seq_id, :step_id, 1, 'SCHEDULED', :eta
                        )
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "comp_id": novo_comp.id,
                        "lead_id": payload.lead_id,
                        "company_id": company_id,
                        "seq_id": first_step.sequence_id,
                        "step_id": first_step.step_id,
                        "eta": eta
                    }
                )
                db.commit()

                # Disparar task
                enviar_passo_pos_consulta.apply_async(
                    args=[novo_comp.id, 1, company_id, payload.lead_id, payload.phone],
                    eta=eta
                )
                logger.info(f"[criar_comparecimento] Follow-up pós-consulta agendado para {eta} (após {first_step.send_after} {first_step.send_after_unit})")
        except Exception as e:
            logger.warning(f"[criar_comparecimento] Erro ao agendar follow-up pós-consulta: {str(e)}")

        return novo_comp

    except Exception as e:
        db.rollback()
        logger.exception("[criar_comparecimento] Erro ao criar comparecimento")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao criar comparecimento: {str(e)}"
        )

@router.put("/{comparecimento_id}", response_model=ComparecimentoResponse)
async def atualizar_comparecimento(
    client_id: int,
    company_id: int,
    comparecimento_id: int,
    payload: ComparecimentoUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Atualiza um comparecimento específico.
    """
    logger.info(f"[atualizar_comparecimento] client_id={client_id}, company_id={company_id}, comparecimento_id={comparecimento_id}")
    comp = db.query(Comparecimento).filter(
        Comparecimento.id == comparecimento_id,
        Comparecimento.client_id == client_id,
        Comparecimento.company_id == company_id
    ).first()

    if not comp:
        logger.warning("[atualizar_comparecimento] Comparecimento não encontrado.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comparecimento não encontrado para este cliente/empresa."
        )

    campos_para_atualizar = payload.dict(exclude_unset=True)
    for campo, valor in campos_para_atualizar.items():
        setattr(comp, campo, valor)

    try:
        db.commit()
        db.refresh(comp)
        logger.info(f"[atualizar_comparecimento] Comparecimento atualizado. id={comp.id}")
        return comp
    except Exception as e:
        db.rollback()
        logger.exception("[atualizar_comparecimento] Erro ao atualizar comparecimento")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao atualizar comparecimento: {str(e)}"
        )

@router.delete("/{comparecimento_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_comparecimento(
    client_id: int,
    company_id: int,
    comparecimento_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Deleta um comparecimento específico.
    """
    logger.info(f"[deletar_comparecimento] client_id={client_id}, company_id={company_id}, comparecimento_id={comparecimento_id}")
    comp = db.query(Comparecimento).filter(
        Comparecimento.id == comparecimento_id,
        Comparecimento.client_id == client_id,
        Comparecimento.company_id == company_id
    ).first()

    if not comp:
        logger.warning("[deletar_comparecimento] Comparecimento não encontrado.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comparecimento não encontrado para este cliente/empresa."
        )

    try:
        db.delete(comp)
        db.commit()
        logger.info(f"[deletar_comparecimento] Comparecimento deletado. id={comp.id}")
        return None
    except Exception as e:
        db.rollback()
        logger.exception("[deletar_comparecimento] Erro ao deletar comparecimento")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao deletar comparecimento: {str(e)}"
        )
