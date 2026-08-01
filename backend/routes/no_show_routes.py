from fastapi import APIRouter, Depends, HTTPException, status, Path
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import NoShowEvent, Client
from backend.auth import verify_client_or_bearer_api_key

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/noshow-events",
    tags=["NoShowEvents"]
)

# ------------------------------------------------------------
# 1) Schemas (Pydantic)
# ------------------------------------------------------------

class NoShowEventBase(BaseModel):
    """Campos básicos que podem ser atualizados/armazenados."""
    observacao: Optional[str] = None

class NoShowEventUpdate(NoShowEventBase):
    """
    Se não queremos permitir editar 'nome', 'phone', 'data_agendada',
    deixamos tudo como está em NoShowEventBase.
    """
    pass

class NoShowEventResponse(BaseModel):
    """Resposta quando listamos ou obtemos um no-show."""
    id: int
    client_id: int
    company_id: int
    lead_id: int
    agendamento_id: int

    # Estes campos são mostrados, mas não podem ser editados
    nome: Optional[str]
    phone: Optional[str]
    data_agendada: Optional[datetime]

    marcado_em: datetime
    observacao: Optional[str] = None

    class Config:
        orm_mode = True

# ------------------------------------------------------------
# 2) Rotas
# ------------------------------------------------------------

@router.get("/", response_model=List[NoShowEventResponse])
def list_no_show_events(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Lista todos os no-shows para esse client_id + company_id.
    """
    noshows = db.query(NoShowEvent).filter(
        NoShowEvent.client_id == client_id,
        NoShowEvent.company_id == company_id
    ).all()
    return noshows

@router.get("/{noshow_id}", response_model=NoShowEventResponse)
def get_no_show_event(
    client_id: int,
    company_id: int,
    noshow_id: int = Path(..., description="ID do no-show event"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Obtém um no-show específico pelo ID.
    """
    noshow = db.query(NoShowEvent).filter(
        NoShowEvent.id == noshow_id,
        NoShowEvent.client_id == client_id,
        NoShowEvent.company_id == company_id
    ).first()

    if not noshow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro de no-show não encontrado"
        )

    return noshow

@router.put("/{noshow_id}", response_model=NoShowEventResponse)
def update_no_show_event(
    client_id: int,
    company_id: int,
    noshow_id: int,
    payload: NoShowEventUpdate,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Atualiza apenas campos de um no-show específico (por exemplo, 'observacao').
    'nome', 'phone', 'data_agendada' não serão editados aqui.
    """
    noshow = db.query(NoShowEvent).filter(
        NoShowEvent.id == noshow_id,
        NoShowEvent.client_id == client_id,
        NoShowEvent.company_id == company_id
    ).first()

    if not noshow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NoShowEvent não encontrado."
        )

    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(noshow, field, value)

    try:
        db.commit()
        db.refresh(noshow)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao atualizar NoShowEvent: {str(e)}"
        )

    return noshow

@router.delete("/{noshow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_no_show_event(
    client_id: int,
    company_id: int,
    noshow_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Deleta um registro de no-show.
    """
    noshow = db.query(NoShowEvent).filter(
        NoShowEvent.id == noshow_id,
        NoShowEvent.client_id == client_id,
        NoShowEvent.company_id == company_id
    ).first()

    if not noshow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NoShowEvent não encontrado."
        )

    try:
        db.delete(noshow)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao deletar NoShowEvent: {str(e)}"
        )

    return None
