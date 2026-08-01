import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Torna os imports independentes do diretório em que o Alembic é executado.
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Importe todos os registros de modelos antes de expor o metadata. A aplicação
# mantém modelos no Base principal e um pequeno conjunto legado do Agents SDK
# em outro Base; ambos fazem parte do schema público suportado.
from backend.config import DATABASE_URL
from backend.db import Base
import backend.models  # noqa: F401
import backend.prompt.agents_sdk.models.memory_models  # noqa: F401
from backend.agents_sdk.database.models import Base as AgentsSDKBase

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = [Base.metadata, AgentsSDKBase.metadata]

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

# Configurar URL do banco baseado no ambiente
def get_url():
    # DATABASE_URL é obrigatória fora do modo development e nunca deve conter
    # credenciais versionadas no alembic.ini.
    return DATABASE_URL or config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        # PostgreSQL's ``json`` type has no equality operator. Comparing
        # defaults such as ``'[]'::json`` makes ``alembic check`` fail before
        # it can report real schema drift, so defaults are intentionally
        # excluded while types, tables, indexes and constraints are checked.
        compare_server_default=False,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    configuration = config.get_section(config.config_ini_section)
    if configuration is None:
        raise RuntimeError("Seção [alembic] não encontrada")
    configuration['sqlalchemy.url'] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
