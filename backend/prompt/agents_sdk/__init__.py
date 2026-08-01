"""Compatibilidade com a implementação legada baseada no Agents SDK.

Os imports são intencionalmente preguiçosos. Ferramentas de infraestrutura,
como Alembic, precisam importar apenas os modelos sem inicializar provedores de
IA, calendário ou dependências opcionais da aplicação.
"""

__all__ = [
    'handle_user_input',
    'AppointmentService',
    'AppointmentError',
]


def __getattr__(name: str):
    if name == "handle_user_input":
        from .agent_main import handle_user_input

        return handle_user_input
    if name in {"AppointmentService", "AppointmentError"}:
        from .services import AppointmentError, AppointmentService

        return {
            "AppointmentService": AppointmentService,
            "AppointmentError": AppointmentError,
        }[name]
    raise AttributeError(name)
