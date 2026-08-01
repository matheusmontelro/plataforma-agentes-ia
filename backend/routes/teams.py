import logging
import re
from datetime import datetime
from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import and_
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Client, Pipeline, PipelineStage, Team, TeamPermission, User

logger = logging.getLogger(__name__)
router = APIRouter()

SIDEBAR_PERMISSION_KEYS = [
    "dashboard",
    "crm",
    "chat",
    "whatsapp",
    "follow-up",
    "prompt",
    "company",
]
SIDEBAR_PERMISSION_SET = set(SIDEBAR_PERMISSION_KEYS)

DEFAULT_CONTACT_PERMISSIONS = {
    "include_outside_crm": False,
    "pipeline_stage_ids": [],
}


class ContactPermissionConfig(BaseModel):
    include_outside_crm: bool = False
    pipeline_stage_ids: List[int] = Field(default_factory=list)


class TeamBase(BaseModel):
    name: str
    description: str | None = None
    sidebar_permissions: List[str] = Field(default_factory=list)
    contact_permissions: ContactPermissionConfig = Field(default_factory=ContactPermissionConfig)

    @validator("name")
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Nome da equipe deve ter pelo menos 2 caracteres")
        if len(value) > 100:
            raise ValueError("Nome da equipe deve ter no máximo 100 caracteres")
        return value


class TeamCreate(TeamBase):
    pass


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sidebar_permissions: List[str] | None = None
    contact_permissions: ContactPermissionConfig | None = None

    @validator("name")
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Nome da equipe deve ter pelo menos 2 caracteres")
        if len(value) > 100:
            raise ValueError("Nome da equipe deve ter no máximo 100 caracteres")
        return value


class TeamResponse(BaseModel):
    id: int
    company_id: int
    name: str
    code: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime
    user_count: int = 0
    sidebar_permissions: List[str] = Field(default_factory=list)
    contact_permissions: ContactPermissionConfig = Field(default_factory=ContactPermissionConfig)


class AssignUserRequest(BaseModel):
    user_id: int


async def validate_master_or_admin_access(current_user: Union[Client, User]) -> Union[Client, User]:
    """Valida se o usuário atual pode administrar equipes."""
    if isinstance(current_user, Client):
        return current_user

    if isinstance(current_user, User) and current_user.role in ["admin", "manager"]:
        return current_user

    logger.warning("Tentativa de acesso não autorizado às equipes por: %s", current_user.email)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acesso permitido apenas para administradores",
    )


def _current_company_id(current_user: Union[Client, User]) -> int:
    return int(current_user.company_id)


def _normalize_sidebar_permissions(values: List[str]) -> List[str]:
    normalized: List[str] = []
    invalid: List[str] = []

    for raw_value in values:
        value = str(raw_value).strip()
        if value == "clinic":
            value = "company"
        if not value:
            continue
        if value not in SIDEBAR_PERMISSION_SET:
            invalid.append(value)
            continue
        if value not in normalized:
            normalized.append(value)

    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Permissões de menu inválidas: {', '.join(invalid)}",
        )

    return normalized


def _normalize_stage_ids(values: List[int]) -> List[int]:
    normalized: List[int] = []
    for value in values:
        try:
            stage_id = int(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="IDs de etapa devem ser numéricos",
            )
        if stage_id > 0 and stage_id not in normalized:
            normalized.append(stage_id)
    return normalized


def _validate_stage_ids_belong_to_company(db: Session, company_id: int, stage_ids: List[int]) -> None:
    if not stage_ids:
        return

    rows = (
        db.query(PipelineStage.id)
        .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
        .filter(Pipeline.company_id == company_id, PipelineStage.id.in_(stage_ids))
        .all()
    )
    valid_ids = {row[0] for row in rows}
    invalid_ids = [stage_id for stage_id in stage_ids if stage_id not in valid_ids]

    if invalid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Etapas do CRM inválidas para esta empresa: {', '.join(map(str, invalid_ids))}",
        )


def _generate_team_code(db: Session, company_id: int, name: str, exclude_team_id: int | None = None) -> str:
    base = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "EQUIPE"
    base = base[:16]
    suffix = 1

    while True:
        candidate = base if suffix == 1 else f"{base[:16 - len(str(suffix)) - 1]}_{suffix}"
        query = db.query(Team).filter(Team.company_id == company_id, Team.code == candidate)
        if exclude_team_id is not None:
            query = query.filter(Team.id != exclude_team_id)
        if not query.first():
            return candidate
        suffix += 1


def _validate_team_name_available(
    db: Session,
    company_id: int,
    name: str,
    exclude_team_id: int | None = None,
) -> None:
    query = db.query(Team).filter(Team.company_id == company_id, Team.name == name)
    if exclude_team_id is not None:
        query = query.filter(Team.id != exclude_team_id)

    if query.first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe uma equipe com este nome",
        )


def _extract_team_permissions(team: Team | None) -> dict:
    if not team:
        return {
            "sidebar_permissions": [],
            "contact_permissions": DEFAULT_CONTACT_PERMISSIONS.copy(),
        }

    sidebar_permissions: List[str] = []
    contact_permissions = DEFAULT_CONTACT_PERMISSIONS.copy()

    for permission in team.permissions or []:
        criteria = permission.filter_criteria or {}

        if permission.resource == "sidebar" and permission.permission == "view":
            sidebar_permissions = _normalize_sidebar_permissions(criteria.get("items", []))

        if permission.resource == "contacts" and permission.permission == "view":
            contact_permissions = {
                "include_outside_crm": bool(criteria.get("include_outside_crm", False)),
                "pipeline_stage_ids": _normalize_stage_ids(criteria.get("pipeline_stage_ids", [])),
            }

    return {
        "sidebar_permissions": sidebar_permissions,
        "contact_permissions": contact_permissions,
    }


def build_user_permissions_payload(db: Session, current_user: Union[Client, User]) -> dict:
    """Retorna permissões serializáveis para login/frontend."""
    if isinstance(current_user, Client):
        return {
            "sidebar_permissions": SIDEBAR_PERMISSION_KEYS,
            "contact_permissions": {
                "include_outside_crm": True,
                "pipeline_stage_ids": [],
            },
            "team": None,
        }

    team = None
    if current_user.team_id:
        team = (
            db.query(Team)
            .filter(Team.id == current_user.team_id, Team.company_id == current_user.company_id)
            .first()
        )

    payload = _extract_team_permissions(team)
    payload["team"] = (
        {"id": team.id, "name": team.name, "code": team.code}
        if team
        else None
    )
    return payload


def _apply_team_permissions(
    db: Session,
    team: Team,
    sidebar_permissions: List[str],
    contact_permissions: ContactPermissionConfig,
) -> None:
    sidebar_permissions = _normalize_sidebar_permissions(sidebar_permissions)
    stage_ids = _normalize_stage_ids(contact_permissions.pipeline_stage_ids)
    _validate_stage_ids_belong_to_company(db, int(team.company_id), stage_ids)

    db.query(TeamPermission).filter(TeamPermission.team_id == team.id).delete(synchronize_session=False)
    db.add(
        TeamPermission(
            team_id=team.id,
            resource="sidebar",
            permission="view",
            filter_criteria={"items": sidebar_permissions},
        )
    )
    db.add(
        TeamPermission(
            team_id=team.id,
            resource="contacts",
            permission="view",
            filter_criteria={
                "include_outside_crm": bool(contact_permissions.include_outside_crm),
                "pipeline_stage_ids": stage_ids,
            },
        )
    )


def _team_to_response(db: Session, team: Team) -> TeamResponse:
    permission_payload = _extract_team_permissions(team)
    user_count = db.query(User).filter(User.team_id == team.id).count()
    return TeamResponse(
        id=team.id,
        company_id=int(team.company_id),
        name=team.name,
        code=team.code,
        description=team.description,
        created_at=team.created_at,
        updated_at=team.updated_at,
        user_count=user_count,
        sidebar_permissions=permission_payload["sidebar_permissions"],
        contact_permissions=permission_payload["contact_permissions"],
    )


def _get_team_or_404(db: Session, company_id: int, team_id: int) -> Team:
    team = db.query(Team).filter(and_(Team.id == team_id, Team.company_id == company_id)).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipe não encontrada")
    return team


@router.get("/teams/", response_model=List[TeamResponse], tags=["teams"])
async def list_teams(
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    await validate_master_or_admin_access(current_user)
    company_id = _current_company_id(current_user)

    teams = db.query(Team).filter(Team.company_id == company_id).order_by(Team.name.asc()).all()
    return [_team_to_response(db, team) for team in teams]


@router.post("/teams/", response_model=TeamResponse, status_code=status.HTTP_201_CREATED, tags=["teams"])
async def create_team(
    team_data: TeamCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    await validate_master_or_admin_access(current_user)
    company_id = _current_company_id(current_user)
    _validate_team_name_available(db, company_id, team_data.name)

    team = Team(
        company_id=company_id,
        name=team_data.name,
        code=_generate_team_code(db, company_id, team_data.name),
        description=team_data.description,
    )

    try:
        db.add(team)
        db.flush()
        _apply_team_permissions(
            db,
            team,
            team_data.sidebar_permissions,
            team_data.contact_permissions,
        )
        db.commit()
        db.refresh(team)
        logger.info("Equipe %s criada para empresa %s por %s", team.name, company_id, current_user.email)
        return _team_to_response(db, team)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Erro ao criar equipe: %s", exc)
        raise HTTPException(status_code=500, detail="Erro ao criar equipe")


@router.get("/teams/current/permissions", tags=["teams"])
async def get_current_permissions(
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    return build_user_permissions_payload(db, current_user)


@router.get("/teams/{team_id}", response_model=TeamResponse, tags=["teams"])
async def get_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    await validate_master_or_admin_access(current_user)
    team = _get_team_or_404(db, _current_company_id(current_user), team_id)
    return _team_to_response(db, team)


@router.put("/teams/{team_id}", response_model=TeamResponse, tags=["teams"])
async def update_team(
    team_id: int,
    team_data: TeamUpdate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    await validate_master_or_admin_access(current_user)
    company_id = _current_company_id(current_user)
    team = _get_team_or_404(db, company_id, team_id)

    update_data = team_data.dict(exclude_unset=True)
    existing_permissions = _extract_team_permissions(team)

    if "name" in update_data and update_data["name"]:
        _validate_team_name_available(db, company_id, update_data["name"], exclude_team_id=team.id)
        team.name = update_data["name"]
        team.code = _generate_team_code(db, company_id, team.name, exclude_team_id=team.id)
    if "description" in update_data:
        team.description = update_data["description"]

    sidebar_permissions = update_data.get("sidebar_permissions", existing_permissions["sidebar_permissions"])
    contact_permissions = update_data.get(
        "contact_permissions",
        ContactPermissionConfig(**existing_permissions["contact_permissions"]),
    )
    if isinstance(contact_permissions, dict):
        contact_permissions = ContactPermissionConfig(**contact_permissions)

    try:
        _apply_team_permissions(db, team, sidebar_permissions, contact_permissions)
        db.commit()
        db.refresh(team)
        logger.info("Equipe %s atualizada por %s", team.name, current_user.email)
        return _team_to_response(db, team)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Erro ao atualizar equipe: %s", exc)
        raise HTTPException(status_code=500, detail="Erro ao atualizar equipe")


@router.patch("/teams/{team_id}", response_model=TeamResponse, tags=["teams"])
async def patch_team(
    team_id: int,
    team_data: TeamUpdate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    return await update_team(team_id, team_data, db, current_user)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["teams"])
async def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    await validate_master_or_admin_access(current_user)
    team = _get_team_or_404(db, _current_company_id(current_user), team_id)

    try:
        db.query(User).filter(User.team_id == team.id).update({"team_id": None}, synchronize_session=False)
        db.delete(team)
        db.commit()
        logger.info("Equipe %s excluída por %s", team.name, current_user.email)
        return None
    except Exception as exc:
        db.rollback()
        logger.error("Erro ao excluir equipe: %s", exc)
        raise HTTPException(status_code=500, detail="Erro ao excluir equipe")


@router.get("/teams/{team_id}/users", response_model=List[dict], tags=["teams"])
async def list_team_users(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    await validate_master_or_admin_access(current_user)
    company_id = _current_company_id(current_user)
    _get_team_or_404(db, company_id, team_id)

    users = db.query(User).filter(User.team_id == team_id, User.company_id == company_id).order_by(User.name.asc()).all()
    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "team_id": user.team_id,
            "is_active": user.is_active,
        }
        for user in users
    ]


@router.post("/teams/{team_id}/users", tags=["teams"])
async def assign_user_to_team(
    team_id: int,
    request: AssignUserRequest,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    await validate_master_or_admin_access(current_user)
    company_id = _current_company_id(current_user)
    team = _get_team_or_404(db, company_id, team_id)

    user = db.query(User).filter(User.id == request.user_id, User.company_id == company_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado")

    try:
        user.team_id = team.id
        db.commit()
        logger.info("Usuário %s atribuído à equipe %s por %s", user.email, team.name, current_user.email)
        return {"message": f"Usuário {user.name} atribuído à equipe {team.name} com sucesso"}
    except Exception as exc:
        db.rollback()
        logger.error("Erro ao atribuir usuário à equipe: %s", exc)
        raise HTTPException(status_code=500, detail="Erro ao atribuir usuário à equipe")


@router.delete("/teams/{team_id}/users/{user_id}", tags=["teams"])
async def remove_user_from_team(
    team_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    await validate_master_or_admin_access(current_user)
    company_id = _current_company_id(current_user)
    _get_team_or_404(db, company_id, team_id)

    user = db.query(User).filter(User.id == user_id, User.team_id == team_id, User.company_id == company_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado nesta equipe")

    try:
        user.team_id = None
        db.commit()
        logger.info("Usuário %s removido da equipe por %s", user.email, current_user.email)
        return {"message": f"Usuário {user.name} removido da equipe com sucesso"}
    except Exception as exc:
        db.rollback()
        logger.error("Erro ao remover usuário da equipe: %s", exc)
        raise HTTPException(status_code=500, detail="Erro ao remover usuário da equipe")
