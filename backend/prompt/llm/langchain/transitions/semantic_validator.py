"""
Advanced semantic validator using LangChain for intelligent validation.
Replaces regex/list-based validation with LLM-powered understanding.
"""

import logging
from typing import Tuple, Optional, Dict, Any, List
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

try:
    from langchain_core.tools import BaseTool
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import PydanticOutputParser
    from langchain_openai import ChatOpenAI
except ImportError:
    from langchain.tools import BaseTool
    from langchain.prompts import ChatPromptTemplate
    from langchain.output_parsers import PydanticOutputParser
    from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# Timezone configuration
try:
    from zoneinfo import ZoneInfo
    SP_TZ = ZoneInfo("America/Sao_Paulo")
except ImportError:
    import pytz
    SP_TZ = pytz.timezone("America/Sao_Paulo")


class ValidationResult(BaseModel):
    """Result of semantic validation"""
    is_valid: bool = Field(description="Whether the input is valid")
    confidence: float = Field(description="Confidence score 0-1")
    reason: Optional[str] = Field(description="Explanation of validation result")
    normalized_value: Optional[str] = Field(description="Normalized/cleaned value")
    intent: Optional[str] = Field(description="Detected user intent")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Extracted entities")


class SemanticDateValidator(BaseTool):
    """LangChain tool for intelligent date validation and normalization"""

    name: str = "semantic_date_validator"
    description: str = "Validates and normalizes date expressions in Portuguese"

    def _run(self, date_input: str) -> ValidationResult:
        """Validate date with semantic understanding"""
        llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)
        parser = PydanticOutputParser(pydantic_object=ValidationResult)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um validador de datas em português brasileiro.
Analise a entrada e determine se é uma data válida.

Regras:
1. Aceite formatos diversos: "amanhã", "próxima terça", "dia 15", "15/03", etc.
2. Normalize sempre para DD/MM/YYYY
3. Use a data de hoje como referência: {today}
4. Máximo 90 dias no futuro
5. Não aceite datas passadas

{format_instructions}"""),
            ("human", "Valide esta data: '{date_input}'")
        ])

        chain = prompt | llm | parser

        try:
            result = chain.invoke({
                "date_input": date_input,
                "today": datetime.now(SP_TZ).strftime("%d/%m/%Y"),
                "format_instructions": parser.get_format_instructions()
            })
            return result
        except Exception as e:
            logger.error(f"Date validation error: {e}")
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                reason=str(e)
            )


class SemanticConfirmationValidator(BaseTool):
    """LangChain tool for intelligent confirmation detection"""

    name: str = "semantic_confirmation_validator"
    description: str = "Detects confirmation intent with context awareness"

    def _run(self, user_input: str, context: Optional[str] = None) -> ValidationResult:
        """Detect confirmation with semantic understanding"""
        llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)
        parser = PydanticOutputParser(pydantic_object=ValidationResult)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um detector de intenção de confirmação.
Analise se o usuário está confirmando algo considerando o contexto.

Tipos de confirmação:
- Explícita: "sim", "confirmo", "pode ser"
- Implícita: "beleza", "tá bom", "perfeito"
- Contextual: repetir horário, "esse mesmo"
- Emoji: "👍", "✅", "🆗"

Tipos de negação/cancelamento:
- Explícita: "não", "cancela", "desisto"
- Implícita: "deixa pra lá", "outro dia"
- Mudança: "na verdade prefiro..."

Contexto da conversa: {context}

{format_instructions}"""),
            ("human", "O usuário disse: '{user_input}'")
        ])

        chain = prompt | llm | parser

        try:
            result = chain.invoke({
                "user_input": user_input,
                "context": context or "Agendamento de consulta",
                "format_instructions": parser.get_format_instructions()
            })
            return result
        except Exception as e:
            logger.error(f"Confirmation validation error: {e}")
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                reason=str(e)
            )


class TreatmentValidator(BaseTool):
    """Validates and categorizes business treatments"""

    name: str = "treatment_validator"
    description: str = "Validates and categorizes business treatments with semantic understanding"

    def _run(self, treatment_input: str, available_treatments: List[str]) -> ValidationResult:
        """Validate treatment with fuzzy matching and categorization"""
        llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)
        parser = PydanticOutputParser(pydantic_object=ValidationResult)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um especialista em tratamentos de serviços.
Valide e categorize o tratamento mencionado.

Tratamentos disponíveis: {treatments}

Considere:
1. Sinônimos e variações (ex: "branqueamento" = "clareamento")
2. Abreviações (ex: "impl" = "implante")
3. Descrições (ex: "dor de dente" → "urgência")
4. Múltiplos tratamentos (ex: "limpeza e clareamento")

Se não corresponder a nenhum tratamento conhecido, sugira o mais próximo.

{format_instructions}"""),
            ("human", "Tratamento solicitado: '{treatment}'")
        ])

        chain = prompt | llm | parser

        try:
            result = chain.invoke({
                "treatment": treatment_input,
                "treatments": ", ".join(available_treatments),
                "format_instructions": parser.get_format_instructions()
            })
            return result
        except Exception as e:
            logger.error(f"Treatment validation error: {e}")
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                reason=str(e)
            )


class NameValidator(BaseTool):
    """Validates and formats customer names"""

    name: str = "name_validator"
    description: str = "Validates and properly formats Brazilian names"

    def _run(self, name_input: str) -> ValidationResult:
        """Validate name with cultural awareness"""
        llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)
        parser = PydanticOutputParser(pydantic_object=ValidationResult)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um validador de nomes brasileiros.
Valide e formate nomes próprios corretamente.

Regras:
1. Deve ter nome e sobrenome
2. Capitalize corretamente (João da Silva, não JOÃO DA SILVA)
3. Preserve partículas (de, da, do, dos, das)
4. Aceite nomes compostos (Maria José, João Paulo)
5. Remova títulos (Dr., Sr., Sra.)
6. Mínimo 2 palavras

{format_instructions}"""),
            ("human", "Nome fornecido: '{name}'")
        ])

        chain = prompt | llm | parser

        try:
            result = chain.invoke({
                "name": name_input,
                "format_instructions": parser.get_format_instructions()
            })
            return result
        except Exception as e:
            logger.error(f"Name validation error: {e}")
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                reason=str(e)
            )


class SmartValidator:
    """
    Main validator class that orchestrates all semantic validations.
    Replaces the old StateValidator with LangChain-powered intelligence.
    """

    def __init__(self, llm: Optional[ChatOpenAI] = None):
        """Initialize with optional custom LLM"""
        self.llm = llm or ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)

        # Initialize tools
        self.date_validator = SemanticDateValidator()
        self.confirmation_validator = SemanticConfirmationValidator()
        self.treatment_validator = TreatmentValidator()
        self.name_validator = NameValidator()

        # Cache for performance
        self._validation_cache: Dict[str, ValidationResult] = {}

    def validate_date(self, date_str: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate date with semantic understanding.

        Returns:
            (is_valid, error_message, normalized_date)
        """
        cache_key = f"date:{date_str}"
        if cache_key in self._validation_cache:
            result = self._validation_cache[cache_key]
        else:
            result = self.date_validator._run(date_str)
            self._validation_cache[cache_key] = result

        if result.is_valid:
            return True, None, result.normalized_value
        else:
            return False, result.reason, None

    def validate_time(self, time_str: str, context: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate time with semantic understanding.

        Returns:
            (is_valid, error_message, normalized_time)
        """
        llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """Normalize horários para formato HH:MM.
Aceite: "2 da tarde" → "14:00", "meio dia" → "12:00", "3:30 PM" → "15:30"
Contexto: {context}"""),
            ("human", "{time_input}")
        ])

        try:
            chain = prompt | llm
            normalized = chain.invoke({
                "time_input": time_str,
                "context": context or "Horário comercial 8h-18h"
            }).content.strip()

            # Basic validation of result
            if ":" in normalized and len(normalized) <= 5:
                return True, None, normalized
            else:
                return False, "Horário inválido", None

        except Exception as e:
            return False, str(e), None

    def is_confirmation(self, text: str, context: Optional[str] = None) -> bool:
        """Check if text contains confirmation intent"""
        result = self.confirmation_validator._run(text, context)
        return result.is_valid and result.intent == "confirmation"

    def is_cancellation(self, text: str, context: Optional[str] = None) -> bool:
        """Check if text contains cancellation intent"""
        result = self.confirmation_validator._run(text, context)
        return result.is_valid and result.intent == "cancellation"

    def validate_treatment(
        self,
        treatment: str,
        available_treatments: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate treatment with fuzzy matching.

        Returns:
            (is_valid, error_message, normalized_treatment)
        """
        if not available_treatments:
            available_treatments = [
                "limpeza", "clareamento", "implante", "canal",
                "extração", "aparelho", "restauração", "prótese",
                "urgência", "avaliação", "manutenção"
            ]

        result = self.treatment_validator._run(treatment, available_treatments)

        if result.is_valid:
            return True, None, result.normalized_value
        else:
            return False, result.reason, None

    def validate_customer_name(self, name: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate and format customer name.

        Returns:
            (is_valid, error_message, formatted_name)
        """
        result = self.name_validator._run(name)

        if result.is_valid:
            return True, None, result.normalized_value
        else:
            return False, result.reason, None

    def validate_slot_with_context(
        self,
        user_input: str,
        available_slots: List[str],
        last_offered_slots: List[str]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate slot selection with context awareness.
        Handles cases like "o primeiro", "o de 14h", "aquele das 3"
        """
        llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """Identifique qual horário o usuário escolheu.
Horários oferecidos: {offered_slots}
Horários disponíveis: {available_slots}

O usuário pode referenciar por:
- Posição: "o primeiro", "o último", "o segundo"
- Horário: "o de 14h", "às 3 da tarde"
- Dia: "na terça", "amanhã"
- Referência: "esse mesmo", "aquele que você falou"

Retorne o horário completo no formato DD/MM/YYYY HH:MM"""),
            ("human", "{user_input}")
        ])

        try:
            chain = prompt | llm
            result = chain.invoke({
                "user_input": user_input,
                "offered_slots": ", ".join(last_offered_slots[-5:]),  # Last 5 offered
                "available_slots": ", ".join(available_slots[:10])   # First 10 available
            }).content.strip()

            # Verify if result is in available slots
            if result in available_slots:
                return True, None, result
            else:
                return False, "Horário não disponível", None

        except Exception as e:
            return False, str(e), None

    def extract_all_entities(self, text: str) -> Dict[str, Any]:
        """
        Extract all relevant entities from user input in one pass.
        More efficient than multiple validations.
        """
        llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)

        class ExtractedEntities(BaseModel):
            treatment: Optional[str] = Field(None, description="Tipo de tratamento")
            date: Optional[str] = Field(None, description="Data no formato DD/MM/YYYY")
            time: Optional[str] = Field(None, description="Horário no formato HH:MM")
            customer_name: Optional[str] = Field(None, description="Nome completo")
            customer_type: Optional[str] = Field(None, description="novo ou existente")
            confirmation: bool = Field(False, description="Se há confirmação")
            cancellation: bool = Field(False, description="Se há cancelamento")

        parser = PydanticOutputParser(pydantic_object=ExtractedEntities)

        prompt = ChatPromptTemplate.from_messages([
            ("system", """Extraia todas as informações relevantes do texto.
{format_instructions}"""),
            ("human", "{text}")
        ])

        try:
            chain = prompt | llm | parser
            entities = chain.invoke({
                "text": text,
                "format_instructions": parser.get_format_instructions()
            })
            return entities.model_dump(exclude_none=True)
        except Exception as e:
            logger.error(f"Entity extraction error: {e}")
            return {}