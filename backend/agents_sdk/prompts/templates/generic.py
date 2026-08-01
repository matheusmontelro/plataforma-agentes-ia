"""
Generic Organization Prompt Template
"""
from typing import Dict, Any
from agents import RunContextWrapper
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)

def get_generic_instructions(
    run_context: RunContextWrapper,
    agent
) -> str:
    """
    Generic instructions generation for any organization type.
    Uses 'organization_info' and 'team_and_resources' from AgentConfiguration.
    """
    context = run_context.context

    organization_data = (
        getattr(context, "organization_data", None)
        or getattr(context, "company_data", None)
        or {}
    )
    channel = (
        getattr(getattr(context, "channel", None), "value", None)
        or getattr(context, "channel", "whatsapp")
    )
    lifecycle = (
        getattr(getattr(context, "lifecycle", None), "value", None)
        or getattr(context, "lifecycle", "unknown")
    )

    # Helper to safe access
    def get_config(key, default=None):
        return organization_data.get(key, default or {})

    organization_info = get_config("organization_info") or get_config("company_info")
    agent_identity = get_config("assistant_identity")

    # Build Variables
    variables = {
        'assistant_name': agent_identity.get('assistant_name', 'Assistente Virtual'),
        'organization_name': organization_info.get('name', 'Nossa Empresa'),
        'current_time': datetime.now(ZoneInfo('America/Sao_Paulo')).strftime("%d/%m/%Y %H:%M"),
        'channel': channel,
        'lifecycle': lifecycle,
    }

    return f"""
Você é {variables['assistant_name']}, assistente virtual da {variables['organization_name']}.
Data e Hora atual: {variables['current_time']}
Canal: {variables['channel']}
Estagio do contato: {variables['lifecycle']}

SEU OBJETIVO:
Atender leads, clientes e contatos com cordialidade e eficiencia, seguindo as diretrizes da empresa.

DIRETRIZES:
1. Seja educado e profissional.
2. Entenda se o contato e lead, cliente ativo ou outra relacao comercial.
3. Responda duvidas sobre a empresa quando houver dados confiaveis.
4. Use ferramentas disponiveis antes de prometer acoes como agendar, cancelar, comprar ou alterar dados.
5. Se nao souber a resposta ou faltar permissao, direcione para atendimento humano.
"""
