from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from typing import List, Union
from pydantic import BaseModel, EmailStr, validator
from backend.db import get_db
from backend.models import User, Client, Company, ClientCompany, Team
from backend.auth import get_current_user, hash_password
from backend.services.company_access_control import (
    AccountEmailCollisionError,
    CompanyOperationalLockBusyError,
    IdentityOperationBusyError,
    IdentityOperationReservation,
    account_identity_operation_lock,
    account_identity_operation_reservation,
    lock_and_validate_account_email_available,
    lock_entities_for_mutation,
    normalize_account_email,
)
from contextlib import ExitStack, contextmanager
from datetime import datetime
import logging
from typing import Iterator

logger = logging.getLogger(__name__)
router = APIRouter()

# Schemas (Pydantic models)
class UserBase(BaseModel):
    email: EmailStr
    name: str
    role: str
    company_id: int
    team_id: int | None = None

    @validator('role')
    def validate_role(cls, v):
        valid_roles = ['admin', 'manager', 'staff']
        if v not in valid_roles:
            raise ValueError(f'Role deve ser um dos valores: {", ".join(valid_roles)}')
        return v

class UserCreate(UserBase):
    password: str
    confirm_password: str

    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Senhas não conferem')
        return v

class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    role: str | None = None
    team_id: int | None = None
    is_active: bool | None = None

    @validator('role')
    def validate_role(cls, v):
        if v is None:
            return v
        valid_roles = ['admin', 'manager', 'staff']
        if v not in valid_roles:
            raise ValueError(f'Role deve ser um dos valores: {", ".join(valid_roles)}')
        return v

class TeamInfo(BaseModel):
    id: int
    name: str
    code: str

    class Config:
        from_attribute = True

class UserResponse(UserBase):
    id: int
    client_id: int
    is_active: bool
    created_at: datetime
    team: TeamInfo | None = None

    class Config:
        from_attribute = True

async def validate_master_access(current_user: Union[Client, User]) -> Client:
    """Valida se o usuário atual é um master e retorna o Client"""
    if not isinstance(current_user, Client):
        logger.warning(f"Tentativa de acesso não autorizado por usuário não-master: {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso permitido apenas para usuários master"
        )
    return current_user

async def validate_company_access(db: Session, master_id: int, company_id: int):
    """Valida se o master tem acesso à empresa especificada"""
    company_access = db.query(Company).join(
        ClientCompany, ClientCompany.company_id == Company.id
    ).filter(
        Company.id == company_id,
        ClientCompany.client_id == master_id
    ).first()

    if not company_access:
        logger.warning(f"Tentativa de acesso à empresa {company_id} por master {master_id} sem permissão")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sem permissão para esta empresa"
        )
    return company_access

async def validate_team_access(db: Session, company_id: int, team_id: int | None):
    """Valida se a equipe pertence à empresa informada."""
    if team_id is None:
        return None

    team = db.query(Team).filter(
        Team.id == team_id,
        Team.company_id == company_id
    ).first()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Equipe inválida para esta empresa"
        )
    return team

async def validate_email_available(
    db: Session,
    email: str,
    ignore_user_id: int | None = None,
) -> str:
    """Evita colisão entre usuários internos e contas master no login."""
    try:
        return lock_and_validate_account_email_available(
            db,
            email,
            ignore_user_id=ignore_user_id,
        )
    except AccountEmailCollisionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email já está em uso",
        ) from exc


def _identity_operation_busy_http(
    exc: IdentityOperationBusyError,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Operação temporariamente indisponível. Tente novamente.",
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def _rollback_if_available(db: Session) -> None:
    rollback = getattr(db, "rollback", None)
    if callable(rollback):
        rollback()


@contextmanager
def _account_identity_locks(
    db: Session,
    emails: List[str],
    *,
    reservation: IdentityOperationReservation,
) -> Iterator[None]:
    """Hold every account identity involved in an internal-user mutation."""
    normalized_emails = sorted(
        {
            normalized
            for email in emails
            if (normalized := normalize_account_email(email))
        }
    )
    with ExitStack() as stack:
        for email in normalized_emails:
            stack.enter_context(
                account_identity_operation_lock(
                    db,
                    email,
                    reservation=reservation,
                )
            )
        yield


def _revalidate_internal_user_mutation(
    db: Session,
    *,
    master_id: int,
    user_id: int,
    company_id: int,
    user_email: str,
) -> tuple[Client, User, Company] | None:
    lock_entities_for_mutation(
        db,
        company_ids=[int(company_id)],
        client_ids=[int(master_id)],
        user_ids=[int(user_id)],
    )
    expire_all = getattr(db, "expire_all", None)
    if callable(expire_all):
        expire_all()

    master = (
        db.query(Client)
        .filter(Client.id == int(master_id))
        .with_for_update()
        .first()
    )
    user = (
        db.query(User)
        .filter(
            User.id == int(user_id),
            User.client_id == int(master_id),
            User.company_id == int(company_id),
            User.email == normalize_account_email(user_email),
        )
        .with_for_update()
        .first()
    )
    company = (
        db.query(Company)
        .filter(Company.id == int(company_id))
        .with_for_update()
        .first()
    )
    if (
        not master
        or not bool(master.is_active)
        or not user
        or not bool(user.is_active)
        or not company
        or company.operational_status != "active"
    ):
        return None

    return master, user, company


@router.get("/users/", response_model=List[UserResponse], tags=["users"])
async def list_users(
    company_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Lista todos os usuários vinculados ao client atual - sem soft delete."""
    master = await validate_master_access(current_user)

    # Base query
    query = db.query(User).filter(User.client_id == master.id)

    # Se company_id for especificado, filtrar por empresa
    if company_id is not None:
        # Valida acesso à empresa
        await validate_company_access(db, master.id, company_id)
        query = query.filter(User.company_id == company_id)

    users = query.all()

    logger.info(f"Master {master.email} listou usuários" + (f" da empresa {company_id}" if company_id else ""))
    return users

@router.post("/users/", response_model=UserResponse, tags=["users"])
async def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    reservation_key = f"create-internal-user:{normalize_account_email(user_data.email)}"
    try:
        with account_identity_operation_reservation(
            db,
            reservation_key,
        ):
            return await _create_user_with_identity_reservation(
                user_data=user_data,
                db=db,
                current_user=current_user,
            )
    except IdentityOperationBusyError as exc:
        _rollback_if_available(db)
        raise _identity_operation_busy_http(exc) from exc


async def _create_user_with_identity_reservation(
    *,
    user_data: UserCreate,
    db: Session,
    current_user: Union[Client, User],
):
    """Cria um novo usuário vinculado ao client atual"""
    master = await validate_master_access(current_user)

    # Serializa a criação e mantém a ordem global company -> client.
    normalized_email = await validate_email_available(db, str(user_data.email))
    lock_entities_for_mutation(db, company_ids=[user_data.company_id])
    lock_entities_for_mutation(db, client_ids=[master.id])

    locked_master = (
        db.query(Client)
        .filter(Client.id == master.id)
        .with_for_update()
        .first()
    )
    company = (
        db.query(Company)
        .filter(Company.id == user_data.company_id)
        .with_for_update()
        .first()
    )
    if (
        not locked_master
        or not bool(locked_master.is_active)
        or not company
        or company.operational_status != "active"
    ):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Acesso suspenso para esta empresa",
        )

    # Valida acesso à empresa novamente depois dos locks e do recheck.
    company = await validate_company_access(db, locked_master.id, user_data.company_id)
    await validate_team_access(db, user_data.company_id, user_data.team_id)

    # Cria o usuário
    hashed_password = hash_password(user_data.password)
    new_user = User(
        email=normalized_email,
        password=hashed_password,
        name=user_data.name,
        role=user_data.role,
        client_id=locked_master.id,
        company_id=user_data.company_id,
        team_id=user_data.team_id,
        is_active=True
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        new_user_id = int(new_user.id)
        master_id = int(locked_master.id)
        logger.info(
            "Usuário master ID=%s criou novo usuário ID=%s para empresa ID=%s",
            master_id,
            new_user_id,
            user_data.company_id,
        )
        return new_user
    except Exception as e:
        logger.error(f"Erro ao criar usuário: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar usuário"
        )

@router.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
async def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Obtém detalhes de um usuário específico"""
    master = await validate_master_access(current_user)

    user = db.query(User).filter(
        User.id == user_id,
        User.client_id == master.id,
        #User.deleted_at.is_(None)
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )

    logger.info(f"Master {master.email} consultou usuário {user.email}")
    return user

@router.patch("/users/{user_id}", response_model=UserResponse, tags=["users"])
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """Atualiza dados de um usuário"""
    master = await validate_master_access(current_user)

    user = db.query(User).filter(
        User.id == user_id,
        User.client_id == master.id,
        #User.deleted_at.is_(None)
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )

    try:
        # Atualiza os campos
        update_data = user_data.dict(exclude_unset=True)

        if "email" in update_data:
            update_data["email"] = await validate_email_available(
                db,
                update_data["email"],
                ignore_user_id=user.id,
            )

        if "team_id" in update_data:
            await validate_team_access(db, user.company_id, update_data["team_id"])

        for field, value in update_data.items():
            setattr(user, field, value)

        db.commit()
        db.refresh(user)

        logger.info(f"Master {master.email} atualizou usuário {user.email}")
        return user
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"Erro ao atualizar usuário: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao atualizar usuário"
        )

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["users"])
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Deleta definitivamente um usuário do banco (sem soft delete).
    """
    master = await validate_master_access(current_user)

    user = db.query(User).filter(
        User.id == user_id,
        User.client_id == master.id
        # User.deleted_at.is_(None)  <-- Remover isso
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )

    try:
        # Delete real: remove o objeto do banco
        db.delete(user)
        db.commit()

        logger.info(f"Master {master.email} deletou usuário {user.email}")
        return None
    except Exception as e:
        logger.error(f"Erro ao deletar usuário: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao deletar usuário"
        )

@router.post("/users/{user_id}/change-password", response_model=UserResponse, tags=["users"])
async def change_user_password(
    user_id: int,
    password_data: dict,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    try:
        with account_identity_operation_reservation(
            db,
            f"change-internal-user-password:{int(user_id)}",
        ) as reservation:
            return await _change_user_password_with_identity_reservation(
                user_id=user_id,
                password_data=password_data,
                db=db,
                current_user=current_user,
                reservation=reservation,
            )
    except IdentityOperationBusyError as exc:
        _rollback_if_available(db)
        raise _identity_operation_busy_http(exc) from exc


async def _change_user_password_with_identity_reservation(
    *,
    user_id: int,
    password_data: dict,
    db: Session,
    current_user: Union[Client, User],
    reservation: IdentityOperationReservation,
):
    """Altera a senha de um usuário"""
    master = await validate_master_access(current_user)

    if "new_password" not in password_data or "confirm_password" not in password_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nova senha e confirmação são obrigatórias"
        )

    if password_data["new_password"] != password_data["confirm_password"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senhas não conferem"
        )

    user = db.query(User).filter(
        User.id == user_id,
        User.client_id == master.id,
        #User.deleted_at.is_(None)
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )

    master_id = int(master.id)
    master_email = str(master.email)
    user_email = normalize_account_email(user.email)
    company_id = int(user.company_id)
    _rollback_if_available(db)

    try:
        with _account_identity_locks(
            db,
            [master_email, user_email],
            reservation=reservation,
        ):
            state = _revalidate_internal_user_mutation(
                db,
                master_id=master_id,
                user_id=int(user_id),
                company_id=company_id,
                user_email=user_email,
            )
            if state is None:
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Acesso suspenso para esta empresa",
                )

            _current_master, current_user, _current_company = state
            current_user.password = hash_password(password_data["new_password"])
            db.commit()
            db.refresh(current_user)
            logger.info(
                "Master ID=%s alterou senha do usuário ID=%s",
                master_id,
                user_id,
            )

            return current_user
    except HTTPException:
        _rollback_if_available(db)
        raise
    except IdentityOperationBusyError as exc:
        _rollback_if_available(db)
        raise _identity_operation_busy_http(exc) from exc
    except (CompanyOperationalLockBusyError, OperationalError):
        _rollback_if_available(db)
        raise
    except Exception as exc:
        logger.error(
            "Erro ao alterar senha do usuário ID=%s erro=%s",
            user_id,
            exc.__class__.__name__,
        )
        _rollback_if_available(db)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao alterar senha"
        ) from exc
