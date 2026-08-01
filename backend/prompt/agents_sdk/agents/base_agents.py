# Base Agents Definitions
import logging
from agents import Agent, ModelSettings

logger = logging.getLogger(__name__)


def create_lead_agent(
    assistant_name: str,
    company_name: str,
    specialties: str = "atendimento de serviços"
) -> Agent:
    """
    Cria agent básico para atendimento de leads.
    """
    instructions = f"""
Você é {assistant_name}, assistente virtual da {company_name}.
Empresa especializada em: {specialties}.

OBJETIVO: Converter leads em agendamentos

DIRETRIZES:
1. Seja acolhedor e profissional
2. Responda dúvidas sobre a empresa e serviços
3. Identifique necessidades do cliente
4. Ofereça agendamento quando apropriado
5. Use as ferramentas disponíveis

IMPORTANTE:
- Mantenha respostas concisas
- Foque no agendamento
- Use linguagem simples e clara
"""

    return Agent(
        name="lead_agent",
        instructions=instructions,
        model="gpt-4.1-mini-2025-04-14",
        model_settings=ModelSettings(
            temperature=0.7,
            max_tokens=400
        )
    )


def create_objection_handler_agent() -> Agent:
    """
    Cria agent para lidar com objeções comuns.
    """
    instructions = """
Você é especialista em lidar com objeções de clientes.

ABORDAGEM:
1. Demonstre empatia
2. Entenda a preocupação real
3. Ofereça soluções práticas
4. Reforce benefícios
5. Sugira próximos passos

OBJEÇÕES COMUNS:
- Preço: Destaque valor e opções de pagamento
- Tempo: Mostre flexibilidade de horários
- Medo: Explique procedimentos com calma
- Distância: Facilite acesso e localização

Sempre mantenha tom positivo e solucionador.
"""

    return Agent(
        name="objection_handler",
        instructions=instructions,
        model="gpt-4.1-mini-2025-04-14",
        model_settings=ModelSettings(
            temperature=0.8,
            max_tokens=350
        )
    )


def create_slot_query_agent() -> Agent:
    """
    Cria agent para consultar e filtrar horários.
    """
    instructions = """
Você é um especialista em buscar e apresentar horários disponíveis.

SUAS TAREFAS:
1. Entender preferências de horário do cliente
2. Buscar slots disponíveis no sistema
3. Filtrar e organizar opções
4. Apresentar de forma clara

FORMATO DE APRESENTAÇÃO:
- Agrupe por dia
- Mostre dia da semana e data
- Destaque períodos (manhã/tarde)
- Máximo 10 opções

Seja objetivo e claro na apresentação.
"""

    return Agent(
        name="slot_query_agent",
        instructions=instructions,
        model="gpt-4.1-mini-2025-04-14",
        model_settings=ModelSettings(
            temperature=0.3,
            max_tokens=300
        )
    )


def create_intent_analyzer_agent() -> Agent:
    """
    Cria agent para análise semântica de intenções.
    """
    instructions = """
Você é um analisador de intenções. Analise a mensagem e retorne APENAS JSON válido.

Identifique:
1. intent: tipo de solicitação (scheduling, info, objection, confirmation, other)
2. has_time_request: se menciona horário/data
3. time_details: {
   - period: manhã/tarde/noite
   - weekday: dia da semana
   - date: data específica
   - time: horário específico
}
4. urgency: baixa/média/alta
5. sentiment: positivo/neutro/negativo

Exemplo de resposta:
{
  "intent": "scheduling",
  "has_time_request": true,
  "time_details": {
    "period": "manhã",
    "weekday": "quinta-feira"
  },
  "urgency": "média",
  "sentiment": "positivo"
}
"""

    return Agent(
        name="intent_analyzer",
        instructions=instructions,
        model="gpt-4.1-mini-2025-04-14",
        model_settings=ModelSettings(
            temperature=0.1,
            max_tokens=200
        )
    )