# backend/routes/prompt_config.py
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from backend.db import get_db
from backend.models import AgentConfiguration, Client, User
from backend.auth import ensure_user_can_access_company, get_current_user
from backend.services.ai_provider_service import (
    AIProviderCredentialError,
    get_company_openai_api_key,
)
from pydantic import BaseModel
from typing import Dict, Any, List, Optional, Union
import logging

# Configuração do logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Criar um handler para console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Definir o formato do log
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# Adicionar o handler ao logger
logger.addHandler(console_handler)

from backend.agents_sdk.prompts.generators.criar_generator import generate_criar_prompt
from backend.agents_sdk.prompts.generators.ai_generator import generate_with_ai

router = APIRouter()


AuthenticatedUser = Union[Client, User]


def _active_company_id(current_user: AuthenticatedUser) -> int:
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(
            status_code=400,
            detail="Empresa ativa não selecionada",
        )
    return int(company_id)


def _authorize_company(
    current_user: AuthenticatedUser,
    company_id: int,
    db: Session,
) -> int:
    """Bind request-selected company IDs to an authenticated tenant."""

    ensure_user_can_access_company(current_user, company_id, db)
    return int(company_id)


class AgentConfigPayload(BaseModel):
    id: Optional[int] = None
    assistant_identity: Dict[str, Any]
    assistant_tone_and_voice: Optional[Dict[str, Any]] = None # Deprecated/Unused in new UI but kept for compat
    company_info: Dict[str, Any]
    team_and_specialties: Dict[str, Any]
    scheduling_config: Dict[str, Any]
    financial_config: Dict[str, Any]
    conversation_flow: Dict[str, Any]
    company_id: Optional[int] = None

@router.post("/agent-config/preview-prompt")
def preview_agent_prompt(
    data: AgentConfigPayload,
    use_ai: bool = False,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Gera um preview do prompt baseado no payload atual, sem salvar no banco.
    """
    # Converter o payload Pydantic para ditado compatível com o gerador
    # O gerador espera a estrutura consolidada. Precisamos montar algo similar ao que o 'manager' faria.

    # Mapeando input do front para o formato esperado pelo gerador
    # O front manda 'conversation_flow.criar_data' com a estrutura C.R.I.A.R.
    # O gerador espera { context, role, instruction, action, restriction } na raiz ou passados explicitamente.

    # Vamos extrair do conversation_flow se existir
    criar_data = data.conversation_flow.get('criar_data', {})

    # Se não tiver criar_data (ex: legado), tenta montar com os campos legacy (falback)
    config_dict = {
        'context': criar_data.get('context', {
            'name': data.company_info.get('company_name'),
            # outros campos legacy...
        }),
        'role': criar_data.get('role', {
            'name': data.assistant_identity.get('assistant_name'),
            'role': data.assistant_identity.get('assistant_role'),
            'tone': data.assistant_identity.get('assistant_tone'),
        }),
        'instruction': criar_data.get('instruction', {}),
        'action': criar_data.get('action', {}),
        'restriction': criar_data.get('restriction', {})
    }

    if use_ai:
        company_id = _active_company_id(current_user)
        try:
            api_key = get_company_openai_api_key(db, company_id)
        except AIProviderCredentialError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        generated_prompt = generate_with_ai(config_dict, api_key=api_key)
    else:
        generated_prompt = generate_criar_prompt(config_dict)

    return {"status": "success", "prompt": generated_prompt}


class AgentConfigPayload(BaseModel):
    id: Optional[int] = None
    assistant_identity: Dict[str, Any]
    company_info: Dict[str, Any]
    team_and_specialties: Dict[str, Any]
    scheduling_config: Dict[str, Any]
    financial_config: Dict[str, Any]
    conversation_flow: Dict[str, Any]
    generated_prompt: Optional[str] = None  # AI-generated or manually edited prompt
    company_id: int

class AgentSummary(BaseModel):
    id: int
    name: str
    role: str
    updated_at: str

# --- LIST ROUTES ---

@router.get("/agent-configs/list/{company_id}")
def list_agent_configs(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Lists all agent configurations for a company."""
    company_id = _authorize_company(current_user, company_id, db)
    configs = db.query(AgentConfiguration).filter_by(company_id=company_id).all()

    summary_list = []
    for c in configs:
        identity = c.assistant_identity or {}
        summary_list.append({
            "id": c.id,
            "name": identity.get("assistant_name", "Agente sem nome"),
            "role": identity.get("assistant_role", "Assistente"),
            "updated_at": str(c.updated_at)
        })
    return summary_list

# --- DETAIL/CRUD ROUTES ---

@router.get("/agent-config/detail/{config_id}")
def get_agent_config_detail(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Gets a specific agent configuration by ID."""
    company_id = _active_company_id(current_user)
    config = (
        db.query(AgentConfiguration)
        .filter_by(id=config_id, company_id=company_id)
        .first()
    )
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    response_data = {
        "id": config.id,
        "company_id": config.company_id,
        "assistant_identity": config.assistant_identity,
        "assistant_tone_and_voice": config.assistant_tone_and_voice,
        "company_info": config.company_info,
        "team_and_specialties": config.team_and_specialties,
        "scheduling_config": config.scheduling_config,
        "financial_config": config.financial_config,
        "conversation_flow": config.conversation_flow,
        "generated_prompt": config.generated_prompt
    }
    return response_data

@router.post("/agent-config")
def upsert_agent_config(
    data: AgentConfigPayload,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Creates a new agent or updates if ID provided."""
    company_id = _authorize_company(current_user, data.company_id, db)

    if data.id:
        # UPDATE
        config = (
            db.query(AgentConfiguration)
            .filter_by(id=data.id, company_id=company_id)
            .first()
        )
        if not config:
             raise HTTPException(status_code=404, detail="Config ID not found for update")
    else:
        # CREATE
        config = AgentConfiguration(company_id=company_id)
        db.add(config)

    # Update fields
    config.assistant_identity = data.assistant_identity
    config.company_info = data.company_info
    config.team_and_specialties = data.team_and_specialties
    config.scheduling_config = data.scheduling_config
    config.financial_config = data.financial_config
    config.conversation_flow = data.conversation_flow
    config.generated_prompt = data.generated_prompt

    db.commit()
    db.refresh(config)
    return {"status": "success", "config_id": config.id, "message": "Configuração salva com sucesso"}


@router.delete("/agent-config/detail/{config_id}")
def delete_agent_config_by_id(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Deletes a specific agent configuration."""
    company_id = _active_company_id(current_user)
    config = (
        db.query(AgentConfiguration)
        .filter_by(id=config_id, company_id=company_id)
        .first()
    )
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    db.delete(config)
    db.commit()
    return {"status": "success", "message": "Configuração descarta com sucesso"}

# --- LEGACY ROUTES (BACKWARD COMPATIBILITY) ---

@router.get("/agent-config/{company_id}")
def get_agent_config_legacy(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Legacy: Returns the first/default config for the company."""
    company_id = _authorize_company(current_user, company_id, db)
    logger.info(f"Legacy fetch for company_id: {company_id}")
    config = db.query(AgentConfiguration).filter_by(company_id=company_id).first()

    if not config:
        # Return empty structure instead of 404 to allow creating
        return {}

    return {
        "id": config.id,
        "company_id": config.company_id,
        "assistant_identity": config.assistant_identity,
        "assistant_tone_and_voice": config.assistant_tone_and_voice,
        "company_info": config.company_info,
        "team_and_specialties": config.team_and_specialties,
        "scheduling_config": config.scheduling_config,
        "financial_config": config.financial_config,
        "conversation_flow": config.conversation_flow
    }

@router.put("/agent-config/{company_id}")
def update_agent_config_legacy(
    company_id: int,
    data: AgentConfigPayload,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Legacy: Updates the default config."""
    company_id = _authorize_company(current_user, company_id, db)
    if data.company_id != company_id:
        raise HTTPException(status_code=403, detail="Company ID mismatch")
    config = db.query(AgentConfiguration).filter_by(company_id=company_id).first()
    # Redirect to upsert logic
    data.id = config.id if config else None
    return upsert_agent_config(data, db, current_user)
