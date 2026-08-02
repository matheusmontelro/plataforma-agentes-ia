import os
import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from functools import partial
from typing import Optional, Dict, Any, Callable, TypeVar, Union

from dotenv import load_dotenv
from jose import JWTError, jwt
from fastapi import Cookie, Header, HTTPException, Depends, WebSocket
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from backend.models import Client, Company, CustomerManagedCompany, User, UserSession
from backend.db import SessionLocal, get_db, mark_session_as_web_request
from backend.services.company_access_control import (
    CompanyOperationalLockBusyError,
    CompanyOperationallyBlockedError,
    IdentityOperationBusyError,
    account_identity_operation_lock,
    account_identity_operation_reservation,
    ensure_company_operational,
    normalize_account_email,
    try_lock_entities_for_access,
)
from backend.runtime_settings import APP_NAME
import logging

logger = logging.getLogger(__name__)
load_dotenv(Path(__file__).parent / os.getenv("ENV_FILE", ".env"))

MANAGED_WORKSPACE_TRIAL_EXPIRED_MESSAGE = (
    "Seu período de teste acabou. Fale com o responsável pelo seu acesso para ativar o workspace."
)
MANAGED_WORKSPACE_ARCHIVED_MESSAGE = "Este workspace foi arquivado e não pode ser acessado."
OPERATIONAL_ACCESS_BLOCKED_MESSAGE = (
    f"Seu acesso à {APP_NAME} está temporariamente indisponível. "
    "Entre em contato com o administrador da instalação."
)

# =============================================================================
# CONFIGURAÇÕES DE TOKEN
# =============================================================================
ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    if ENVIRONMENT == "production":
        raise RuntimeError("JWT_SECRET_KEY environment variable is required in production")
    SECRET_KEY = "secretkeylocaldev"
elif ENVIRONMENT == "production" and len(SECRET_KEY) < 32:
    raise RuntimeError("JWT_SECRET_KEY must be at least 32 characters in production")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def _websocket_auth_executor_worker_count() -> int:
    try:
        configured = int(os.getenv("WEBSOCKET_AUTH_EXECUTOR_WORKERS", "4").strip())
    except ValueError:
        configured = 4
    return max(1, min(configured, 8))


WEBSOCKET_AUTH_EXECUTOR_WORKERS = _websocket_auth_executor_worker_count()
_WEBSOCKET_AUTH_EXECUTOR = ThreadPoolExecutor(
    max_workers=WEBSOCKET_AUTH_EXECUTOR_WORKERS,
    thread_name_prefix="ws-auth-db",
)
_WEBSOCKET_AUTH_ADMISSION = threading.BoundedSemaphore(
    WEBSOCKET_AUTH_EXECUTOR_WORKERS
)
_WebSocketExecutorResult = TypeVar("_WebSocketExecutorResult")


def _http_auth_executor_worker_count() -> int:
    try:
        configured = int(os.getenv("HTTP_AUTH_EXECUTOR_WORKERS", "4").strip())
    except ValueError:
        configured = 4
    return max(1, min(configured, 8))


HTTP_AUTH_EXECUTOR_WORKERS = _http_auth_executor_worker_count()
_HTTP_AUTH_EXECUTOR = ThreadPoolExecutor(
    max_workers=HTTP_AUTH_EXECUTOR_WORKERS,
    thread_name_prefix="http-auth-db",
)
_HTTP_AUTH_ADMISSION = threading.BoundedSemaphore(HTTP_AUTH_EXECUTOR_WORKERS)
_AUTH_EXECUTORS_STOPPING = False

# Rota usada pelo OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# =============================================================================
# CONTEXTO DE HASH E MODELOS
# =============================================================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class TokenData(BaseModel):
    email: Optional[str] = None
    user_id: Optional[str] = None
    user_type: Optional[str] = None  # 'master' ou 'user'
    client_id: Optional[str] = None  # usado quando user_type = 'user'


@dataclass(frozen=True)
class LoginAuthenticationResult:
    account_id: int
    client_id: int
    company_id: int
    user_type: str
    team_id: Optional[int]
    tokens: Dict[str, str]


@dataclass(frozen=True)
class WebSocketAccessSnapshot:
    """Detached principal data safe to move from a DB worker to the event loop."""

    user_id: str
    client_id: str
    company_id: str
    user_type: str
    auth_token_version: int
    operational_epoch: Optional[int] = None


class AuthenticationInfrastructureError(RuntimeError):
    """Sanitized transient failure while issuing authentication credentials."""

    retry_after_seconds = 2

    def __init__(self):
        super().__init__("authentication_infrastructure_unavailable")


class WebSocketAuthError(Exception):
    def __init__(self, message: str, code: int = 4001):
        self.message = message
        self.code = code

# =============================================================================
# FUNÇÕES DE HASH/VERIFICAÇÃO
# =============================================================================
def _normalize_password(password: str) -> str:
    """
    Normaliza a senha usando SHA-256 antes do bcrypt.

    Isso resolve a limitação do bcrypt de 72 bytes e permite senhas de qualquer tamanho.
    O SHA-256 sempre retorna 64 caracteres hexadecimais (32 bytes), bem abaixo do limite.

    Referência: https://security.stackexchange.com/q/39849
    """
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def hash_password(password: str) -> str:
    """Hash de senha usando SHA-256 + bcrypt para suportar senhas longas"""
    normalized = _normalize_password(password)
    return pwd_context.hash(normalized)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica senha usando SHA-256 + bcrypt"""
    normalized = _normalize_password(plain_password)
    return pwd_context.verify(normalized, hashed_password)

# =============================================================================
# CRIAÇÃO DE TOKENS
# =============================================================================
def create_access_token(data: Dict[str, Any], expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({
        "type": "access",
        "exp": expire
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: Dict[str, Any], expires_days: int = REFRESH_TOKEN_EXPIRE_DAYS) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=expires_days)
    to_encode.update({
        "type": "refresh",
        "exp": expire
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_tokens_for_user(user: Union[Client, User]) -> Dict[str, str]:
    """Cria tokens diferenciados para client (master) ou user"""
    if isinstance(user, Client):
        token_data = {
            "sub": user.email,
            "user_id": str(user.id),
            "user_type": "master",
            "client_id": str(user.id),  # para master, client_id é o próprio id
            "company_id": str(user.company_id),
            "clinic_id": str(user.company_id),
            "tv": int(user.auth_token_version or 0),
        }
    else:
        token_data = {
            "sub": user.email,
            "user_id": str(user.id),
            "user_type": "user",
            "client_id": str(user.client_id),  # id do master
            "company_id": str(user.company_id),
            "clinic_id": str(user.company_id),
            "tv": int(user.auth_token_version or 0),
        }

    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer"
    }


def _operational_company_ids_for_account(
    account: Union[Client, User],
    master: Optional[Client] = None,
) -> list[int]:
    values = {
        int(value)
        for value in (
            getattr(account, "company_id", None),
            getattr(account, "ownership_company_id", None),
            getattr(master, "company_id", None),
            getattr(master, "ownership_company_id", None),
        )
        if value is not None
    }
    return sorted(values)


def lock_and_revalidate_account_for_token_issue(
    db: Session,
    account: Union[Client, User],
) -> Union[Client, User]:
    """Revalidate account and company state under shared admission locks."""
    if isinstance(account, Client):
        try_lock_entities_for_access(
            db,
            company_ids=_operational_company_ids_for_account(account),
            client_ids=[int(account.id)],
        )
        db.expire_all()
        current = (
            db.query(Client)
            .filter_by(
                id=int(account.id),
                email=normalize_account_email(account.email),
            )
            .first()
        )
        if not current or not current.is_active:
            raise HTTPException(status_code=401, detail="Usuário inativo")
        for company_id in _operational_company_ids_for_account(current):
            ensure_company_operational(db, company_id)
        ensure_managed_workspace_access(db, int(current.company_id))
        return current

    master = db.query(Client).filter_by(id=int(account.client_id)).first()
    if not master:
        raise HTTPException(
            status_code=401,
            detail="Cliente master não encontrado",
        )
    try_lock_entities_for_access(
        db,
        company_ids=_operational_company_ids_for_account(account, master),
        client_ids=[int(master.id)],
        user_ids=[int(account.id)],
    )
    db.expire_all()
    current = (
        db.query(User)
        .filter_by(
            id=int(account.id),
            email=normalize_account_email(account.email),
            client_id=int(account.client_id),
        )
        .first()
    )
    master = db.query(Client).filter_by(id=int(account.client_id)).first()
    if not current or not current.is_active:
        raise HTTPException(status_code=401, detail="Usuário inativo")
    if not master or not master.is_active:
        raise HTTPException(
            status_code=401,
            detail="Cliente master não encontrado",
        )
    for company_id in _operational_company_ids_for_account(current, master):
        ensure_company_operational(db, company_id)
    ensure_managed_workspace_access(db, int(current.company_id))
    return current


def authenticate_login_and_issue_tokens(
    db: Session,
    *,
    email: str,
    password: str,
    finalize_transaction: bool = True,
) -> LoginAuthenticationResult:
    """Authenticate and issue credentials inside identity/entity locks.

    ``finalize_transaction=False`` lets the HTTP login worker materialize the
    complete response before committing a staff session. Direct callers keep
    the historical commit/rollback behavior by default.
    """
    normalized_email = normalize_account_email(email)
    try:
        with account_identity_operation_reservation(
            db,
            f"auth-login:{normalized_email}",
        ) as reservation:
            with account_identity_operation_lock(
                db,
                normalized_email,
                reservation=reservation,
            ):
                account: Optional[Union[Client, User]] = (
                    db.query(Client)
                    .filter(Client.email == normalized_email)
                    .first()
                )
                if account is None:
                    account = (
                        db.query(User)
                        .filter(User.email == normalized_email)
                        .first()
                    )
                if account is None:
                    raise HTTPException(
                        status_code=400,
                        detail="Email não encontrado",
                    )
                if not verify_password(password, account.password):
                    raise HTTPException(
                        status_code=401,
                        detail="Credenciais inválidas",
                    )
                if not account.is_active:
                    raise HTTPException(
                        status_code=401,
                        detail="Usuário inativo",
                    )

                account = lock_and_revalidate_account_for_token_issue(db, account)
                tokens = create_tokens_for_user(account)
                if isinstance(account, Client):
                    result = LoginAuthenticationResult(
                        account_id=int(account.id),
                        client_id=int(account.id),
                        company_id=int(account.company_id),
                        user_type="master",
                        team_id=None,
                        tokens=tokens,
                    )
                    if finalize_transaction:
                        # Release transaction-scoped entity fences before returning.
                        db.rollback()
                    return result

                db.add(
                    UserSession(
                        user_id=int(account.id),
                        client_id=int(account.client_id),
                        token=hashlib.sha256(
                            tokens["access_token"].encode("utf-8")
                        ).hexdigest(),
                        expires_at=datetime.utcnow()
                        + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
                    )
                )
                result = LoginAuthenticationResult(
                    account_id=int(account.id),
                    client_id=int(account.client_id),
                    company_id=int(account.company_id),
                    user_type="user",
                    team_id=(
                        int(account.team_id)
                        if account.team_id is not None
                        else None
                    ),
                    tokens=tokens,
                )
                if finalize_transaction:
                    db.commit()
                return result
    except (
        CompanyOperationalLockBusyError,
        IdentityOperationBusyError,
    ):
        if finalize_transaction:
            db.rollback()
        raise
    except CompanyOperationallyBlockedError:
        if finalize_transaction:
            db.rollback()
        raise HTTPException(
            status_code=423,
            detail=OPERATIONAL_ACCESS_BLOCKED_MESSAGE,
        ) from None
    except HTTPException:
        if finalize_transaction:
            db.rollback()
        raise
    except Exception as exc:
        if finalize_transaction:
            db.rollback()
        logger.error(
            "Falha de infraestrutura durante autenticação: %s",
            exc.__class__.__name__,
        )
        raise AuthenticationInfrastructureError() from None

# =============================================================================
# DECODIFICAR TOKENS
# =============================================================================
def decode_token(token: str, verify_access: bool = True) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # Verifica se é o tipo correto de token
        if verify_access and payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Token não é de acesso.")
        elif not verify_access and payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token não é de refresh.")

        return payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token inválido ou expirado: {str(e)}")

# =============================================================================
# FUNÇÕES DE AUTENTICAÇÃO
# =============================================================================
def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    cookie_token: Optional[str] = Cookie(None, alias="access_token"),
    db: Session = Depends(get_db)
) -> Union[Client, User]:
    try:
        token = token or cookie_token
        if not token:
            raise HTTPException(status_code=401, detail="Token não fornecido")

        payload = decode_token(token)
        email = payload.get("sub")
        user_type = payload.get("user_type", "master")
        user_id = payload.get("user_id")
        client_id = payload.get("client_id")

        if not email or not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")

        if user_type == "master":
            user = db.query(Client).filter_by(email=email, id=user_id).first()
        else:
            user = db.query(User).filter_by(
                email=email,
                id=user_id,
                client_id=client_id
            ).first()

        if not user:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")

        if user_type == "master" and not user.is_active:
            raise HTTPException(status_code=401, detail="Usuário inativo")
        if int(payload.get("tv") or 0) != int(user.auth_token_version or 0):
            raise HTTPException(status_code=401, detail="Token revogado")

        # Verificações adicionais para usuário não-master
        if user_type == "user":
            if not user.is_active:
                raise HTTPException(status_code=401, detail="Usuário inativo")

            # Verifica se o client (master) ainda existe e está ativo
            master = db.query(Client).filter_by(id=user.client_id).first()
            if not master or not master.is_active:
                raise HTTPException(status_code=401, detail="Cliente master não encontrado")
            ensure_company_operational(db, int(user.company_id))
        else:
            ensure_company_operational(db, int(user.company_id))

        return user
    except CompanyOperationallyBlockedError:
        raise HTTPException(status_code=401, detail="Acesso suspenso")
    except HTTPException:
        raise
    except (
        CompanyOperationalLockBusyError,
        OperationalError,
        IdentityOperationBusyError,
    ):
        raise
    except Exception as exc:
        logger.error(
            "Falha de infraestrutura ao autenticar requisição: error_type=%s",
            exc.__class__.__name__,
        )
        raise AuthenticationInfrastructureError() from None


def _as_aware_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_managed_workspace_trial_state(
    link: CustomerManagedCompany,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Calculate trial/access status for a managed customer workspace."""

    current_time = _as_aware_datetime(now) or datetime.now(timezone.utc)
    started_at = _as_aware_datetime(link.trial_started_at)
    ends_at = _as_aware_datetime(link.trial_ends_at)
    trial_days = int(link.trial_days or 0)
    has_trial = trial_days > 0 and ends_at is not None
    expired_by_date = bool(has_trial and ends_at <= current_time)
    lifecycle_status = link.lifecycle_status or ("trialing" if has_trial else "active")
    if expired_by_date:
        lifecycle_status = "expired"

    days_remaining: Optional[int] = None
    progress_percent: Optional[float] = None
    if has_trial:
        remaining_seconds = max(0.0, (ends_at - current_time).total_seconds())
        days_remaining = int(ceil(remaining_seconds / 86400)) if remaining_seconds else 0

        if started_at and ends_at > started_at:
            total_seconds = max(1.0, (ends_at - started_at).total_seconds())
            elapsed_seconds = min(max(0.0, (current_time - started_at).total_seconds()), total_seconds)
            progress_percent = round((elapsed_seconds / total_seconds) * 100, 2)
        else:
            progress_percent = 100.0 if expired_by_date else 0.0

        if expired_by_date:
            progress_percent = 100.0

    return {
        "lifecycle_status": lifecycle_status,
        "trial_days_remaining": days_remaining,
        "trial_progress_percent": progress_percent,
        "is_trial_expired": expired_by_date or lifecycle_status == "expired",
    }


def refresh_managed_workspace_lifecycle(
    db: Session,
    link: CustomerManagedCompany,
    now: Optional[datetime] = None,
) -> bool:
    state = get_managed_workspace_trial_state(link, now=now)
    if state["is_trial_expired"] and link.lifecycle_status == "trialing":
        link.lifecycle_status = "expired"
        db.flush()
        return True
    return False


def get_managed_workspace_link(db: Session, company_id: int) -> Optional[CustomerManagedCompany]:
    return (
        db.query(CustomerManagedCompany)
        .filter(CustomerManagedCompany.managed_company_id == company_id)
        .first()
    )


def ensure_managed_workspace_access(db: Session, company_id: int) -> None:
    try:
        ensure_company_operational(db, company_id)
    except CompanyOperationallyBlockedError as exc:
        raise HTTPException(status_code=403, detail="Acesso suspenso") from exc

    link = get_managed_workspace_link(db, company_id)
    if not link:
        return

    if link.lifecycle_status == "archived":
        raise HTTPException(status_code=403, detail=MANAGED_WORKSPACE_ARCHIVED_MESSAGE)

    state = get_managed_workspace_trial_state(link)
    if state["is_trial_expired"]:
        raise HTTPException(status_code=403, detail=MANAGED_WORKSPACE_TRIAL_EXPIRED_MESSAGE)


def ensure_user_can_access_company(user: Union[Client, User], company_id: int, db: Session) -> None:
    """Raise 403 when the authenticated user is not allowed to access a company."""
    if isinstance(user, User):
        if not user.is_active or int(user.company_id) != int(company_id):
            raise HTTPException(status_code=403, detail="Acesso negado para esta empresa")
        ensure_managed_workspace_access(db, company_id)
        return

    result = db.execute(
        text("""
            SELECT 1
            FROM client_companies
            WHERE client_id = :client_id
              AND company_id = :company_id
            LIMIT 1
        """),
        {"client_id": user.id, "company_id": company_id}
    ).fetchone()

    if not result:
        raise HTTPException(status_code=403, detail="Acesso negado para esta empresa")

    ensure_managed_workspace_access(db, company_id)


def verify_client_or_bearer_api_key(
    client_id: int,
    company_id: int,
    api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    cookie_token: Optional[str] = Cookie(None, alias="access_token"),
    db: Session = Depends(get_db)
) -> Union[Client, User]:
    """
    Compatibilidade para rotas legadas: aceita API key server-to-server ou JWT do usuário logado.

    O navegador deve usar cookie HttpOnly/Bearer. API key fica reservada para integrações externas
    e nunca precisa ser exposta ao frontend.
    """
    if api_key:
        client = db.query(Client).filter(
            Client.id == client_id,
            Client.api_key == api_key,
            Client.is_active.is_(True),
        ).first()
        if not client:
            raise HTTPException(status_code=401, detail="API Key inválida")
        ensure_user_can_access_company(client, company_id, db)
        return client

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif cookie_token:
        token = cookie_token

    if token:
        payload = decode_token(token)
        email = payload.get("sub")
        user_id = payload.get("user_id")
        user_type = payload.get("user_type", "master")
        token_client_id = payload.get("client_id")

        if not email or not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")

        if user_type == "master":
            if str(client_id) != str(user_id):
                raise HTTPException(status_code=403, detail="Acesso negado para este cliente")
            user = db.query(Client).filter_by(email=email, id=user_id).first()
        else:
            if str(client_id) != str(token_client_id):
                raise HTTPException(status_code=403, detail="Acesso negado para este cliente")
            user = db.query(User).filter_by(
                email=email,
                id=user_id,
                client_id=token_client_id
            ).first()

        if not user:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        if not user.is_active:
            raise HTTPException(status_code=401, detail="Usuário inativo")
        if int(payload.get("tv") or 0) != int(user.auth_token_version or 0):
            raise HTTPException(status_code=401, detail="Token revogado")
        if isinstance(user, User):
            master = db.query(Client).filter(Client.id == user.client_id).first()
            if not master or not master.is_active:
                raise HTTPException(status_code=401, detail="Cliente master não encontrado")

        ensure_user_can_access_company(user, company_id, db)
        return user

    raise HTTPException(status_code=401, detail="Credenciais não fornecidas")

def get_current_user_ws_sync(token: str, db: Session) -> Dict[str, Any]:
    """Obtém usuário atual via token (para WebSocket)"""
    try:
        payload = decode_token(token)
        email = payload.get("sub")
        user_type = payload.get("user_type", "master")
        user_id = payload.get("user_id")
        client_id = payload.get("client_id")
        company_id = payload.get("company_id")

        if not all((email, user_id, client_id)):
            raise WebSocketAuthError("Token inválido", 4001)

        if user_type == "master":
            if str(client_id) != str(user_id):
                raise WebSocketAuthError("Token inválido", 4001)
            user = db.query(Client).filter_by(email=email, id=user_id).first()
        else:
            if not company_id:
                raise WebSocketAuthError("Token inválido", 4001)
            user = db.query(User).filter_by(
                email=email,
                id=user_id,
                client_id=client_id,
            ).first()

        if not user:
            raise WebSocketAuthError("Usuário não encontrado", 4001)

        if user_type == "master" and not user.is_active:
            raise WebSocketAuthError("Usuário inativo", 4001)
        if int(payload.get("tv") or 0) != int(user.auth_token_version or 0):
            raise WebSocketAuthError("Token revogado", 4001)

        # Se for um usuário normal, verifica se está ativo
        if user_type == "user" and not user.is_active:
            raise WebSocketAuthError("Usuário inativo", 4001)

        if user_type == "user":
            if (
                str(user.client_id) != str(client_id)
                or str(user.company_id) != str(company_id)
            ):
                raise WebSocketAuthError("Token inválido", 4001)
            master = db.query(Client).filter_by(id=user.client_id).first()
            if not master or not master.is_active:
                raise WebSocketAuthError("Cliente master não encontrado", 4001)
            ensure_company_operational(db, int(user.company_id))
        else:
            # Compatibilidade com tokens master antigos emitidos por
            # create_tokens_for_user antes do claim company_id. Os claims de
            # identidade continuam obrigatórios e amarrados ao mesmo Client,
            # então uma conta recriada com o mesmo e-mail não herda o token.
            if not company_id:
                company_id = str(user.company_id)
            ensure_user_can_access_company(user, int(company_id), db)

        return {
            "id": str(user.id),
            "email": user.email,
            "user_type": user_type,
            "client_id": str(user.client_id if user_type == "user" else user.id),
            "company_id": str(company_id),
            "auth_token_version": int(user.auth_token_version or 0),
        }
    except WebSocketAuthError as e:
        raise e
    except CompanyOperationallyBlockedError:
        raise WebSocketAuthError("Acesso suspenso", 4003)
    except Exception as exc:
        logger.error(
            "Erro na autenticação WebSocket: error_type=%s",
            exc.__class__.__name__,
        )
        raise WebSocketAuthError("Falha ao autenticar", 4001) from None

async def get_current_user_ws(token: str, db: Session) -> Dict[str, Any]:
    """Compatibility wrapper for legacy WebSocket routes."""

    return get_current_user_ws_sync(token, db)


def verify_company_access_sync(user_id: str, company_id: int, db: Session) -> bool:
    try:
        # Primeiro tenta como user normal (mais comum)
        result = db.execute(
            text("""
                SELECT 1
                FROM users u
                JOIN clients c ON c.id = u.client_id
                JOIN companies co ON co.id = u.company_id
                WHERE u.id = :user_id
                  AND u.company_id = :company_id
                  AND u.is_active = true
                  AND c.is_active = true
                  AND co.operational_status = 'active'
                LIMIT 1
            """),
            {"user_id": user_id, "company_id": company_id}
        ).fetchone()

        if result:
            try:
                ensure_managed_workspace_access(db, company_id)
            except HTTPException:
                return False
            return True

        # Se não encontrou, tenta como client master
        result = db.execute(
            text("""
                SELECT 1
                FROM client_companies cc
                JOIN clients c ON c.id = cc.client_id
                JOIN companies co ON co.id = cc.company_id
                WHERE cc.client_id = :user_id
                  AND cc.company_id = :company_id
                  AND c.is_active = true
                  AND co.operational_status = 'active'
                LIMIT 1
            """),
            {"user_id": user_id, "company_id": company_id}
        ).fetchone()

        if not result:
            return False

        try:
            ensure_managed_workspace_access(db, company_id)
        except HTTPException:
            return False
        return True
    except Exception as exc:
        logger.error(
            "Erro ao verificar acesso à empresa: error_type=%s",
            exc.__class__.__name__,
        )
        return False


async def verify_company_access(user_id: str, company_id: int, db: Session) -> bool:
    """Compatibility wrapper for existing request handlers."""

    return verify_company_access_sync(user_id, company_id, db)


def revalidate_websocket_access_sync(
    token: str,
    company_id: int,
    db: Session,
    *,
    expected_user_id: str,
    expected_client_id: str,
) -> Optional[Dict[str, Any]]:
    """Start a fresh read and revalidate the signed identity after WS registration."""
    db.rollback()
    db.expire_all()
    user = get_current_user_ws_sync(token, db)
    if (
        str(user["id"]) != str(expected_user_id)
        or str(user["client_id"]) != str(expected_client_id)
    ):
        return None
    if not verify_company_access_sync(user["id"], company_id, db):
        return None
    operational_epoch = (
        db.query(Company.operational_epoch)
        .filter(
            Company.id == int(company_id),
            Company.operational_status == "active",
        )
        .scalar()
    )
    if operational_epoch is None:
        return None
    user["operational_epoch"] = int(operational_epoch)
    return user


async def revalidate_websocket_access(
    token: str,
    company_id: int,
    db: Session,
    *,
    expected_user_id: str,
    expected_client_id: str,
) -> Optional[Dict[str, Any]]:
    """Compatibility wrapper for legacy WebSocket routes."""

    return revalidate_websocket_access_sync(
        token,
        company_id,
        db,
        expected_user_id=expected_user_id,
        expected_client_id=expected_client_id,
    )


def release_websocket_db_transaction(db: Session) -> None:
    """Return the checked-out connection while keeping the Session reusable."""
    try:
        db.rollback()
    except Exception:
        db.close()
        raise


WebSocketResourceValidator = Callable[[Session, Dict[str, Any]], bool]


def _websocket_access_snapshot(user: Dict[str, Any]) -> WebSocketAccessSnapshot:
    operational_epoch = user.get("operational_epoch")
    return WebSocketAccessSnapshot(
        user_id=str(user["id"]),
        client_id=str(user["client_id"]),
        company_id=str(user["company_id"]),
        user_type=str(user.get("user_type") or "master"),
        auth_token_version=int(user.get("auth_token_version") or 0),
        operational_epoch=(
            int(operational_epoch)
            if operational_epoch is not None
            else None
        ),
    )


def authenticate_websocket_access_in_fresh_session(
    token: str,
    company_id: int,
    *,
    resource_validator: Optional[WebSocketResourceValidator] = None,
) -> Optional[WebSocketAccessSnapshot]:
    """Authenticate using a web-marked session owned by the current DB thread.

    Callers must execute this synchronous helper in a worker thread.  Only the
    detached snapshot escapes; the SQLAlchemy session is rolled back and closed
    before the helper returns.
    """

    db = mark_session_as_web_request(SessionLocal())
    try:
        user = get_current_user_ws_sync(token, db)
        if not verify_company_access_sync(user["id"], company_id, db):
            return None
        if resource_validator is not None and not resource_validator(db, user):
            return None
        return _websocket_access_snapshot(user)
    finally:
        try:
            db.rollback()
        finally:
            db.close()


def revalidate_websocket_access_in_fresh_session(
    token: str,
    company_id: int,
    *,
    expected_user_id: str,
    expected_client_id: str,
    resource_validator: Optional[WebSocketResourceValidator] = None,
) -> Optional[WebSocketAccessSnapshot]:
    """Revalidate in a new worker-owned session and return only detached data."""

    db = mark_session_as_web_request(SessionLocal())
    try:
        user = revalidate_websocket_access_sync(
            token,
            company_id,
            db,
            expected_user_id=expected_user_id,
            expected_client_id=expected_client_id,
        )
        if user is None:
            return None
        if resource_validator is not None and not resource_validator(db, user):
            return None
        return _websocket_access_snapshot(user)
    finally:
        try:
            db.rollback()
        finally:
            db.close()


async def _run_websocket_auth_executor(
    operation: Callable[[], _WebSocketExecutorResult],
) -> _WebSocketExecutorResult:
    if _AUTH_EXECUTORS_STOPPING:
        raise WebSocketAuthError("Serviço indisponível", 1012)
    if not _WEBSOCKET_AUTH_ADMISSION.acquire(blocking=False):
        raise WebSocketAuthError("Serviço temporariamente ocupado", 1013)
    loop = asyncio.get_running_loop()
    try:
        future = _WEBSOCKET_AUTH_EXECUTOR.submit(operation)
    except BaseException:
        _WEBSOCKET_AUTH_ADMISSION.release()
        raise
    future.add_done_callback(lambda _done: _WEBSOCKET_AUTH_ADMISSION.release())
    return await asyncio.wrap_future(future, loop=loop)


async def run_http_auth_off_loop(
    operation: Callable[..., _WebSocketExecutorResult],
    *args: Any,
    **kwargs: Any,
) -> _WebSocketExecutorResult:
    """Run login/refresh outside AnyIO with bounded, cancellation-safe capacity."""

    if _AUTH_EXECUTORS_STOPPING or not _HTTP_AUTH_ADMISSION.acquire(blocking=False):
        raise AuthenticationInfrastructureError()
    loop = asyncio.get_running_loop()
    try:
        future = _HTTP_AUTH_EXECUTOR.submit(
            partial(operation, *args, **kwargs)
        )
    except BaseException:
        _HTTP_AUTH_ADMISSION.release()
        raise
    future.add_done_callback(lambda _done: _HTTP_AUTH_ADMISSION.release())
    return await asyncio.wrap_future(future, loop=loop)


def shutdown_auth_executors() -> None:
    """Reject new auth work and cancel tasks that have not started."""

    global _AUTH_EXECUTORS_STOPPING
    _AUTH_EXECUTORS_STOPPING = True
    _HTTP_AUTH_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    _WEBSOCKET_AUTH_EXECUTOR.shutdown(wait=False, cancel_futures=True)


async def authenticate_websocket_access_off_loop(
    token: str,
    company_id: int,
    *,
    resource_validator: Optional[WebSocketResourceValidator] = None,
) -> Optional[WebSocketAccessSnapshot]:
    """Run WebSocket authentication on the dedicated bounded DB executor."""

    return await _run_websocket_auth_executor(
        partial(
            authenticate_websocket_access_in_fresh_session,
            token,
            company_id,
            resource_validator=resource_validator,
        )
    )


async def revalidate_websocket_access_off_loop(
    token: str,
    company_id: int,
    *,
    expected_user_id: str,
    expected_client_id: str,
    resource_validator: Optional[WebSocketResourceValidator] = None,
) -> Optional[WebSocketAccessSnapshot]:
    """Run post-registration revalidation on the dedicated DB executor."""

    return await _run_websocket_auth_executor(
        partial(
            revalidate_websocket_access_in_fresh_session,
            token,
            company_id,
            expected_user_id=expected_user_id,
            expected_client_id=expected_client_id,
            resource_validator=resource_validator,
        )
    )


# =============================================================================
# FUNÇÕES DE REFRESH TOKEN
# =============================================================================
def _refresh_access_token_with_db(
    refresh_token: str,
    db: Session,
) -> Dict[str, str]:
    """Validate and rotate a refresh token using the caller-owned session."""
    try:
        payload = decode_token(refresh_token, verify_access=False)
        email = normalize_account_email(payload.get("sub"))
        user_id = payload.get("user_id")
        user_type = payload.get("user_type", "master")

        if not email or not user_id:
            raise HTTPException(status_code=401, detail="Refresh token inválido")

        with account_identity_operation_reservation(
            db,
            "auth-refresh:"
            + hashlib.sha256(refresh_token.encode("utf-8")).hexdigest(),
        ) as reservation:
            with account_identity_operation_lock(
                db,
                email,
                reservation=reservation,
            ):
                if user_type == "master":
                    user = (
                        db.query(Client)
                        .filter_by(email=email, id=user_id)
                        .first()
                    )
                else:
                    user = (
                        db.query(User)
                        .filter_by(email=email, id=user_id)
                        .first()
                    )

                if not user:
                    raise HTTPException(
                        status_code=401,
                        detail="Usuário não encontrado",
                    )
                if int(payload.get("tv") or 0) != int(
                    user.auth_token_version or 0
                ):
                    raise HTTPException(
                        status_code=401,
                        detail="Token revogado",
                    )

                user = lock_and_revalidate_account_for_token_issue(db, user)
                # Recheck the version after acquiring the entity fence. A
                # A concurrent administrative state change that wins before
                # this fence invalidates the token version before rotation.
                if int(payload.get("tv") or 0) != int(
                    user.auth_token_version or 0
                ):
                    raise HTTPException(
                        status_code=401,
                        detail="Token revogado",
                    )
                tokens = create_tokens_for_user(user)
                db.rollback()
                return tokens
    except (
        CompanyOperationalLockBusyError,
        IdentityOperationBusyError,
    ):
        db.rollback()
        raise
    except CompanyOperationallyBlockedError:
        db.rollback()
        raise HTTPException(status_code=401, detail="Acesso suspenso")
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(
            "Falha de infraestrutura durante refresh: %s",
            exc.__class__.__name__,
        )
        raise AuthenticationInfrastructureError() from None


def refresh_access_token(refresh_token: str) -> Dict[str, str]:
    """Rotate credentials in a fresh session owned by the worker thread."""
    db = mark_session_as_web_request(SessionLocal())
    try:
        return _refresh_access_token_with_db(refresh_token, db)
    finally:
        db.close()
