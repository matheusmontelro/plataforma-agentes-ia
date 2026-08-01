import json
from typing import Dict, Any

def generate_criar_prompt(config: Dict[str, Any]) -> str:
    """
    Gera um prompt baseado no framework C.R.I.A.R.

    Expected config structure (merged from AgentConfiguration):
    - context: { name, business_type, products, target_audience, differentials }
    - role: { name, role, tone }
    - instruction: { objective, qualification_criteria, stop_conditions }
    - action: { flow_steps, tools, communication_style, persistence }
    - restriction: { prohibitions, escalation_triggers, sensitive_handling }
    """

    # Extract sections with defaults
    ctx = config.get('context', {})
    role = config.get('role', {})
    inst = config.get('instruction', {})
    act = config.get('action', {})
    rest = config.get('restriction', {})

    # 1. CONTEXTO
    context_section = f"""
# CONTEXTO
- Empresa: {ctx.get('name', 'Nossa Empresa')}
- Ramo: {ctx.get('business_type', 'Geral')}
- O que vende: {ctx.get('products', 'Serviços diversos')}
- Público-alvo: {ctx.get('target_audience', 'Geral')}
- Diferenciais: {ctx.get('differentials', 'Atendimento de qualidade')}
"""

    # 2. ROLE (PAPEL)
    role_section = f"""
# PAPEL (ROLE)
- Nome: {role.get('name', 'Assistente')}
- Função: {role.get('role', 'Atendente')}
- Tom de voz: {role.get('tone', 'Profissional e prestativo')}
"""

    # 3. INSTRUÇÃO
    criteria = inst.get('qualification_criteria', [])
    if isinstance(criteria, list):
        criteria_str = "\n".join([f"  - {c}" for c in criteria])
    else:
        criteria_str = str(criteria)

    instruction_section = f"""
# INSTRUÇÃO (Objetivos)
- Objetivo Principal: {inst.get('objective', 'Atender o cliente')}
- Critérios de Qualificação:
{criteria_str}
- Condições de Parada: {inst.get('stop_conditions', 'Quando o cliente agendar ou não tiver interesse')}
"""

    # 4. AÇÃO
    steps = act.get('flow_steps', [])
    if isinstance(steps, list):
        steps_str = "\n".join([f"  {i+1}. {s}" for i, s in enumerate(steps)])
    else:
        steps_str = str(steps)

    action_section = f"""
# AÇÃO (Execução)
- Fluxo de Conversa:
{steps_str}

- Ferramentas Disponíveis: {act.get('tools', 'Agendamento, Consulta de Informações')}
- Estilo de Comunicação: {act.get('communication_style', 'Uma pergunta por vez, clara e direta')}
- Nível de Persistência: {act.get('persistence', 'Média')}
"""

    # 5. RESTRIÇÕES
    prohibitions = rest.get('prohibitions', [])
    if isinstance(prohibitions, list):
        prohibitions_str = "\n".join([f"  - {p}" for p in prohibitions])
    else:
        prohibitions_str = str(prohibitions)

    escalations = rest.get('escalation_triggers', [])
    if isinstance(escalations, list):
        escalations_str = "\n".join([f"  - {e}" for e in escalations])
    else:
        escalations_str = str(escalations)

    restriction_section = f"""
# RESTRIÇÕES & SEGURANÇA
- O QUE NÃO FAZER:
{prohibitions_str}

- QUANDO ESCALAR PARA HUMANO:
{escalations_str}

- SITUAÇÕES SENSÍVEIS:
  {rest.get('sensitive_handling', 'Seja empático e acolhedor.')}
"""

    # Combine all
    full_prompt = f"""{context_section}
{role_section}
{instruction_section}
{action_section}
{restriction_section}
"""
    return full_prompt
