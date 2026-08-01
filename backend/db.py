import os
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker, declarative_base
from sqlalchemy.pool import Pool
from typing import Generator

# URL de conexão (obrigatório usar variável de ambiente)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required!")

# Parâmetros de pool — todos lidos do ambiente, com defaults
POOL_SIZE        = int(os.getenv("DB_POOL_SIZE", "50"))
MAX_OVERFLOW     = int(os.getenv("DB_MAX_OVERFLOW", "50"))
POOL_TIMEOUT     = int(os.getenv("DB_POOL_TIMEOUT", "30"))   # segundos
POOL_RECYCLE     = int(os.getenv("DB_POOL_RECYCLE", "1800")) # segundos
WEB_TRANSACTION_LOCK_TIMEOUT_MS = max(
    50,
    min(5000, int(os.getenv("DB_WEB_LOCK_TIMEOUT_MS", "1000"))),
)
WEB_REQUEST_SESSION_INFO_KEY = "agentive_web_request"
TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY = "agentive_transaction_lock_timeout_ms"
TRANSACTION_LOCK_TIMEOUT_MIN_MS = 50
TRANSACTION_LOCK_TIMEOUT_MAX_MS = 60_000

# Configuração condicional de connect_args
connect_args = {}
if "postgresql" in DATABASE_URL:
    connect_args = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
elif "sqlite" in DATABASE_URL:
    connect_args = {
        "check_same_thread": False
    }

engine = create_engine(
    DATABASE_URL,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,      # ping antes de usar
    connect_args=connect_args
)

logger = logging.getLogger(__name__)

# Event listeners para monitorar conexões
@event.listens_for(Pool, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Evento disparado quando uma nova conexão é criada"""
    logger.debug(f"Nova conexão criada. Pool size: {engine.pool.size()}, checked out: {engine.pool.checkedout()}")

@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    """Evento disparado quando uma conexão é retirada do pool"""
    checked_out = engine.pool.checkedout()
    pool_size = engine.pool.size()
    logger.debug(f"Conexão retirada do pool. Pool: {pool_size}, checked out: {checked_out}")

    # Alerta se estivermos próximo do limite
    total_capacity = POOL_SIZE + MAX_OVERFLOW
    if checked_out > total_capacity * 0.8:  # 80% do pool total
        logger.warning(f"Pool de conexões sob pressão! {checked_out}/{total_capacity} conexões em uso")

@event.listens_for(Pool, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    """Evento disparado quando uma conexão é devolvida ao pool"""
    logger.debug(f"Conexão devolvida ao pool. Pool size: {engine.pool.size()}, checked out: {engine.pool.checkedout()}")

def get_connection_stats():
    """Retorna estatísticas do pool de conexões"""
    return {
        "pool_size": engine.pool.size(),
        "checked_out": engine.pool.checkedout(),
        "overflow": engine.pool.overflow(),
        "checked_in": engine.pool.checkedin(),
        "max_overflow": MAX_OVERFLOW,
        "total_capacity": POOL_SIZE + MAX_OVERFLOW
    }


def check_database_connection() -> None:
    """Executa uma consulta real para validar que o banco responde."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)
Base = declarative_base()


def mark_session_as_web_request(db: Session) -> Session:
    """Mark a request-owned session so every PostgreSQL transaction is fused."""
    db.info[WEB_REQUEST_SESSION_INFO_KEY] = True
    return db


def mark_session_with_transaction_lock_timeout(
    db: Session,
    timeout_ms: int,
) -> Session:
    """Apply a bounded lock fuse to every transaction opened by ``db``."""
    db.info[TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY] = max(
        TRANSACTION_LOCK_TIMEOUT_MIN_MS,
        min(int(timeout_ms), TRANSACTION_LOCK_TIMEOUT_MAX_MS),
    )
    return db


def _session_transaction_lock_timeout_ms(session: Session) -> int | None:
    configured = session.info.get(TRANSACTION_LOCK_TIMEOUT_MS_INFO_KEY)
    if configured is not None:
        try:
            return max(
                TRANSACTION_LOCK_TIMEOUT_MIN_MS,
                min(int(configured), TRANSACTION_LOCK_TIMEOUT_MAX_MS),
            )
        except (TypeError, ValueError):
            return None
    if session.info.get(WEB_REQUEST_SESSION_INFO_KEY):
        return WEB_TRANSACTION_LOCK_TIMEOUT_MS
    return None


@event.listens_for(Session, "after_begin")
def apply_web_transaction_lock_timeout(
    session: Session,
    transaction,
    connection,
) -> None:
    """Bound explicit and trigger-owned lock waits for HTTP request sessions.

    ``SET LOCAL`` is transaction-scoped, so pooled connections are never
    contaminated and a request that commits then starts another transaction
    receives the fuse again.
    """
    del transaction
    if connection.dialect.name != "postgresql":
        return
    timeout_ms = _session_transaction_lock_timeout_ms(session)
    if timeout_ms is None:
        return
    connection.exec_driver_sql(
        "SET LOCAL lock_timeout = "
        f"'{timeout_ms}ms'"
    )

def get_db() -> Generator:
    """Dependency do FastAPI para obter sessão e fechar ao final."""
    db = mark_session_as_web_request(SessionLocal())
    try:
        yield db
    finally:
        db.close()
