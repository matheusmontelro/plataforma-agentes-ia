"""Proteções do pool SQLAlchemy para processos Celery prefork."""

from __future__ import annotations

from typing import Any


def dispose_inherited_sqlalchemy_pool(**_kwargs: Any) -> None:
    """Substitui no filho o pool herdado sem fechar conexões do processo pai."""

    from backend.db import engine

    engine.dispose(close=False)
