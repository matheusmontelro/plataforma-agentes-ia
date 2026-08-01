from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime

from backend.db import get_db
from backend.models import Flow, WebhookTrigger
from backend.auth import get_current_user

router = APIRouter()

# --- Schemas ---

class FlowBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = False
    trigger_webhook_id: Optional[int] = None
    trigger_type: str = 'webhook'  # 'webhook', 'whatsapp', 'appointment', or 'crm_stage'
    trigger_config: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    viewport: Dict[str, Any] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1})

class FlowCreate(FlowBase):
    pass

class FlowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    trigger_webhook_id: Optional[int] = None
    trigger_type: Optional[str] = None  # 'webhook', 'whatsapp', 'appointment', or 'crm_stage'
    trigger_config: Optional[Dict[str, Any]] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    viewport: Optional[Dict[str, Any]] = None

class FlowResponse(FlowBase):
    id: int
    company_id: int
    trigger_type: str = 'webhook'  # Include in response
    trigger_config: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# --- Endpoints ---

@router.post("/", response_model=FlowResponse, status_code=status.HTTP_201_CREATED)
def create_flow(
    flow: FlowCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")

    db_flow = Flow(
        company_id=current_user.company_id,
        name=flow.name,
        description=flow.description,
        is_active=flow.is_active,
        trigger_webhook_id=flow.trigger_webhook_id,
        trigger_type=flow.trigger_type,
        trigger_config=flow.trigger_config or {},
        nodes=flow.nodes,
        edges=flow.edges,
        viewport=flow.viewport
    )
    db.add(db_flow)
    db.commit()
    db.refresh(db_flow)
    return db_flow

@router.get("/", response_model=List[FlowResponse])
def list_flows(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if not current_user.company_id:
        return []

    return db.query(Flow).filter(Flow.company_id == current_user.company_id).all()

@router.get("/{flow_id}", response_model=FlowResponse)
def get_flow(
    flow_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    flow = db.query(Flow).filter(
        Flow.id == flow_id,
        Flow.company_id == current_user.company_id
    ).first()

    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    return flow

@router.put("/{flow_id}", response_model=FlowResponse)
def update_flow(
    flow_id: int,
    flow_update: FlowUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    db_flow = db.query(Flow).filter(
        Flow.id == flow_id,
        Flow.company_id == current_user.company_id
    ).first()

    if not db_flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    update_data = flow_update.dict(exclude_unset=True)

    for key, value in update_data.items():
        setattr(db_flow, key, value)

    db.commit()
    db.refresh(db_flow)
    return db_flow

@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flow(
    flow_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    db_flow = db.query(Flow).filter(
        Flow.id == flow_id,
        Flow.company_id == current_user.company_id
    ).first()

    if not db_flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    db.delete(db_flow)
    db.commit()
    return None
