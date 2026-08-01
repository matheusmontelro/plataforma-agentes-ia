"""
Parser semântico de restrições temporais usando LLM.
Extrai constraints de horário de texto em português de forma robusta.
"""

from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TimeConstraints(BaseModel):
    """Modelo para restrições de horário extraídas"""
    earliest_time: Optional[str] = Field(None, description="Horário mais cedo no formato HH:MM")
    latest_time: Optional[str] = Field(None, description="Horário mais tarde no formato HH:MM")
    reasoning: str = Field("", description="Explicação da extração")


def extract_time_constraints_semantic(text: str) -> TimeConstraints:
    """
    Extrai restrições de horário usando LLM semântico.

    Args:
        text: Texto do usuário para analisar

    Returns:
        TimeConstraints: Objeto com as restrições extraídas
    """
    try:
        llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0.1)
        parser = PydanticOutputParser(pydantic_object=TimeConstraints)

        prompt = ChatPromptTemplate.from_template("""
Você é especialista em extrair restrições de horário de texto em português.

Analise o texto e extraia APENAS restrições de horário específicas:

EXEMPLOS:
- "depois das 15h" → earliest_time: "15:00", reasoning: "Usuário quer horário após 15:00"
- "antes das 18" → latest_time: "18:00", reasoning: "Usuário quer horário antes de 18:00"
- "só posso após as 16h30" → earliest_time: "16:30", reasoning: "Disponível somente após 16:30"
- "entre 14 e 17 horas" → earliest_time: "14:00", latest_time: "17:00", reasoning: "Janela específica entre 14:00 e 17:00"
- "manhã" → earliest_time: null, latest_time: null, reasoning: "Período genérico, não específico"
- "tarde" → earliest_time: null, latest_time: null, reasoning: "Período genérico, não específico"
- "não posso antes das 15h" → earliest_time: "15:00", reasoning: "Não disponível antes de 15:00"
- "até 16 horas no máximo" → latest_time: "16:00", reasoning: "Limite máximo às 16:00"

IMPORTANTE:
- Só extraia horários ESPECÍFICOS (com números)
- Use formato 24h: HH:MM
- Se não houver restrição específica com números, deixe null
- Considere variações como "15h", "15:00", "3 da tarde" (→ 15:00)
- Para "não posso antes", converta para earliest_time
- Para "não posso depois", converta para latest_time

Texto: "{text}"

{format_instructions}
""")

        result = llm.invoke(prompt.format(
            text=text,
            format_instructions=parser.get_format_instructions()
        ))

        constraints = parser.parse(result.content)
        logger.info(f"[TimeSemanticParser] Extracted constraints: {constraints.dict()}")
        return constraints

    except Exception as e:
        logger.error(f"[TimeSemanticParser] Error extracting time constraints: {e}")
        # Return empty constraints on error
        return TimeConstraints(
            earliest_time=None,
            latest_time=None,
            reasoning=f"Erro na extração: {str(e)}"
        )


def has_time_constraints(text: str) -> bool:
    """
    Verifica rapidamente se o texto contém restrições de horário.

    Args:
        text: Texto para verificar

    Returns:
        bool: True se contém indicadores de restrições temporais
    """
    time_indicators = [
        "depois das", "após", "antes das", "entre", "até", "h", "horas",
        "horário", "horarios", "não posso antes", "não posso depois",
        "só posso", "somente", "apenas", "no máximo", "no mínimo"
    ]

    text_lower = text.lower()
    return any(indicator in text_lower for indicator in time_indicators)


def detect_cancellation_intent_semantic(text: str) -> bool:
    """
    Detecta intenção de cancelamento sem confundir com restrições de horário.

    Args:
        text: Texto do usuário

    Returns:
        bool: True se é cancelamento, False se é restrição de horário
    """
    # Se contém restrições de horário, NÃO é cancelamento
    if has_time_constraints(text):
        logger.info(f"[CancellationDetector] Time constraints detected, not cancellation: {text}")
        return False

    # Agora sim, verifica cancelamento
    cancel_phrases = ["cancelar", "desmarcar", "não quero mais", "desistir", "deixa pra lá"]
    text_lower = text.lower()
    is_cancellation = any(phrase in text_lower for phrase in cancel_phrases)

    if is_cancellation:
        logger.info(f"[CancellationDetector] Cancellation intent detected: {text}")

    return is_cancellation