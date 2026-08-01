"""
Parser Temporal Inteligente usando LangChain
============================================

Extrai referências temporais complexas de forma inteligente.
"""

from typing import Optional, Tuple, Dict, Any
from datetime import datetime, date, timedelta
from pydantic import BaseModel, Field
import logging

from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser

logger = logging.getLogger(__name__)


class TemporalReference(BaseModel):
    """Resultado da análise temporal"""
    has_temporal_reference: bool = Field(
        description="Se há alguma referência temporal na mensagem"
    )

    # Intervalo de datas
    start_date: Optional[date] = Field(
        None,
        description="Data inicial do intervalo solicitado"
    )
    end_date: Optional[date] = Field(
        None,
        description="Data final do intervalo solicitado"
    )

    # Detalhes
    reference_type: Optional[str] = Field(
        None,
        description="Tipo de referência: specific_date, date_range, relative, recurring"
    )

    # Períodos do dia
    time_preferences: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Preferências de horário (manhã, tarde, após 18h, etc)"
    )

    # Interpretação
    interpretation: str = Field(
        default="",
        description="Explicação de como interpretou a referência temporal"
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confiança na interpretação"
    )


class TemporalParser:
    """
    Parser inteligente para referências temporais usando LLM.

    Capaz de entender:
    - "semana que vem"
    - "daqui 15 dias"
    - "entre segunda e quarta"
    - "qualquer dia exceto sexta"
    - "mês que vem, de preferência no início"
    - "depois do dia 20"
    - "antes do feriado"
    - E qualquer outra variação natural
    """

    def __init__(self, llm: Optional[ChatOpenAI] = None):
        self.llm = llm or ChatOpenAI(
            model="gpt-4.1-mini-2025-04-14",
            temperature=0.1
        )

    def parse(self, text: str, context_date: Optional[datetime] = None) -> TemporalReference:
        """
        Analisa texto e extrai referências temporais.

        Args:
            text: Texto para analisar
            context_date: Data de contexto (default: agora)

        Returns:
            TemporalReference com intervalo de datas
        """
        if not context_date:
            context_date = datetime.now()

        # Parser estruturado
        parser = PydanticOutputParser(pydantic_object=TemporalReference)

        # Prompt inteligente
        prompt = ChatPromptTemplate.from_template("""
Você é um especialista em interpretar referências temporais em português brasileiro.
Analise o texto e extraia QUANDO o usuário quer agendar.

Data/hora atual: {current_datetime}
Dia da semana: {weekday_name} ({weekday_num})
Dia do mês: {day_of_month}
Mês: {month_name} ({month_num})
Ano: {year}

EXEMPLOS DE INTERPRETAÇÃO:
- "semana que vem" → próxima segunda a domingo
- "próximos 15 dias" → hoje até hoje+15
- "final do mês" → últimos 5 dias do mês atual
- "depois do dia 20" → dia 21 até final do mês
- "qualquer terça ou quinta" → todas as terças e quintas dos próximos 30 dias
- "mês que vem" → dia 1 ao último dia do próximo mês
- "daqui 2 semanas" → 14 dias a partir de hoje
- "entre 10 e 15 de julho" → intervalo específico
- "exceto fim de semana" → apenas dias úteis
- "manhãs da próxima semana" → seg-sex 6h-12h da próxima semana

IMPORTANTE:
1. Sempre retorne um intervalo (start_date e end_date)
2. Se for data única, start_date = end_date
3. Se não houver referência temporal clara, has_temporal_reference = false
4. Interprete de forma natural e flexível
5. Considere contexto brasileiro (semana começa na segunda)

Texto para analisar: "{text}"

{format_instructions}
""")

        # Prepara contexto
        weekday_names = [
            "Segunda-feira", "Terça-feira", "Quarta-feira",
            "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"
        ]

        month_names = [
            "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
        ]

        # Invoca LLM
        try:
            result = self.llm.invoke(
                prompt.format(
                    current_datetime=context_date.strftime("%d/%m/%Y %H:%M"),
                    weekday_name=weekday_names[context_date.weekday()],
                    weekday_num=context_date.weekday(),
                    day_of_month=context_date.day,
                    month_name=month_names[context_date.month - 1],
                    month_num=context_date.month,
                    year=context_date.year,
                    text=text,
                    format_instructions=parser.get_format_instructions()
                )
            )

            # Parse do resultado
            return parser.parse(result.content)

        except Exception as e:
            logger.error(f"Erro no parser temporal: {e}")
            return TemporalReference(has_temporal_reference=False)

    def get_date_range(self, text: str) -> Tuple[Optional[date], Optional[date]]:
        """
        Método simplificado que retorna apenas o intervalo de datas.

        Returns:
            (start_date, end_date) ou (None, None)
        """
        result = self.parse(text)

        if result.has_temporal_reference:
            return result.start_date, result.end_date

        return None, None


# Função utilitária para uso direto
def extract_date_range(text: str, llm: Optional[ChatOpenAI] = None) -> Tuple[Optional[date], Optional[date]]:
    """
    Extrai intervalo de datas de um texto.

    Examples:
        >>> extract_date_range("quero marcar semana que vem")
        (date(2024, 6, 24), date(2024, 6, 30))

        >>> extract_date_range("qualquer dia depois do dia 15")
        (date(2024, 6, 16), date(2024, 6, 30))
    """
    parser = TemporalParser(llm)
    return parser.get_date_range(text)