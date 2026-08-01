"""
Professional validation strategies using LangChain's advanced features.
Implements multiple approaches for robust, context-aware validation.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple, Protocol
from abc import ABC, abstractmethod
from functools import lru_cache
import json

try:
    from langchain_core.runnables import RunnablePassthrough, RunnableLambda
    from langchain_core.output_parsers import JsonOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
    from langchain.cache import InMemoryCache
    from langchain.globals import set_llm_cache
except ImportError:
    from langchain.schema.runnable import RunnablePassthrough, RunnableLambda
    from langchain.output_parsers import JsonOutputParser
    from langchain.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# Enable caching for better performance
set_llm_cache(InMemoryCache())


class ValidationStrategy(Protocol):
    """Protocol for validation strategies"""

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate input data and return results"""
        ...


class BaseValidationStrategy(ABC):
    """Base class for all validation strategies"""

    def __init__(self, llm: Optional[ChatOpenAI] = None):
        self.llm = llm or ChatOpenAI(
            model="gpt-4.1-mini-2025-04-14",
            temperature=0
        )
        self._setup()

    @abstractmethod
    def _setup(self):
        """Setup strategy-specific components"""
        pass

    @abstractmethod
    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate input data"""
        pass


class FunctionCallingValidator(BaseValidationStrategy):
    """
    Uses OpenAI function calling for structured validation.
    Most efficient for well-defined validation rules.
    """

    def _setup(self):
        """Setup function definitions"""
        self.functions = [
            {
                "name": "validate_appointment_data",
                "description": "Validate appointment scheduling data",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "is_valid": {"type": "boolean"},
                        "validated_fields": {
                            "type": "object",
                            "properties": {
                                "treatment": {"type": "string"},
                                "date": {"type": "string"},
                                "time": {"type": "string"},
                                "customer_name": {"type": "string"},
                                "customer_type": {"type": "string", "enum": ["novo", "existente"]},
                                "confirmation_detected": {"type": "boolean"}
                            }
                        },
                        "errors": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "warnings": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "normalized_values": {
                            "type": "object"
                        }
                    },
                    "required": ["is_valid", "validated_fields"]
                }
            }
        ]

        self.llm = self.llm.bind(functions=self.functions)

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate using function calling"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um validador de agendamentos de serviços.
Analise os dados fornecidos e valide cada campo.

Regras de validação:
1. Datas: formato DD/MM/YYYY, não no passado, máximo 90 dias futuro
2. Horários: formato HH:MM, horário comercial (8h-18h)
3. Nomes: nome e sobrenome, capitalização correta
4. Tratamentos: validar contra lista conhecida
5. Confirmações: detectar intenção clara

Normalize valores quando possível. Retorne o resultado em formato JSON."""),
            ("human", "Valide estes dados: {input}")
        ])

        chain = prompt | self.llm

        try:
            response = chain.invoke({"input": json.dumps(input_data, ensure_ascii=False)})

            # Extract function call result
            if hasattr(response, 'additional_kwargs') and 'function_call' in response.additional_kwargs:
                result = json.loads(response.additional_kwargs['function_call']['arguments'])
                return result
            else:
                return {"is_valid": False, "errors": ["Invalid response format"]}

        except Exception as e:
            logger.error(f"Function calling validation error: {e}")
            return {"is_valid": False, "errors": [str(e)]}


class RunnableValidator(BaseValidationStrategy):
    """
    Uses LangChain Runnables for composable validation pipelines.
    Excellent for complex, multi-stage validation.
    """

    def _setup(self):
        """Setup runnable pipeline"""
        self.parser = JsonOutputParser()

        # Create validation stages
        self.extract_stage = self._create_extraction_runnable()
        self.validate_stage = self._create_validation_runnable()
        self.normalize_stage = self._create_normalization_runnable()

        # Compose pipeline
        self.pipeline = (
            self.extract_stage
            | self.validate_stage
            | self.normalize_stage
        )

    def _create_extraction_runnable(self):
        """Extract relevant fields from input"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Extraia campos relevantes para agendamento.
Retorne JSON com campos encontrados."""),
            ("human", "{input}")
        ])

        return {
            "raw_input": RunnablePassthrough(),
            "extracted": prompt | self.llm | self.parser
        }

    def _create_validation_runnable(self):
        """Validate extracted fields"""
        def validate_fields(data):
            extracted = data.get("extracted", {})
            errors = []
            warnings = []

            # Custom validation logic
            if "date" in extracted:
                # Validate date logic
                pass

            return {
                **data,
                "validation": {
                    "errors": errors,
                    "warnings": warnings,
                    "is_valid": len(errors) == 0
                }
            }

        return RunnableLambda(validate_fields)

    def _create_normalization_runnable(self):
        """Normalize validated fields"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Normalize os campos validados para formato padrão.
Datas: DD/MM/YYYY
Horários: HH:MM
Nomes: Capitalização correta
Retorne JSON."""),
            ("human", "{validation}")
        ])

        def normalize(data):
            if not data["validation"]["is_valid"]:
                return data

            chain = prompt | self.llm | self.parser
            normalized = chain.invoke({"validation": data})

            return {
                **data,
                "normalized": normalized
            }

        return RunnableLambda(normalize)

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run validation pipeline"""
        try:
            result = self.pipeline.invoke({"input": input_data})
            return {
                "is_valid": result["validation"]["is_valid"],
                "errors": result["validation"]["errors"],
                "warnings": result["validation"]["warnings"],
                "normalized_values": result.get("normalized", {}),
                "extracted_fields": result.get("extracted", {})
            }
        except Exception as e:
            logger.error(f"Runnable validation error: {e}")
            return {"is_valid": False, "errors": [str(e)]}


class StructuredOutputValidator(BaseValidationStrategy):
    """
    Uses structured output parsing for type-safe validation.
    Best for when you need guaranteed output structure.
    """

    def _setup(self):
        """Setup structured output schema"""
        from pydantic import BaseModel, Field

        class ValidationOutput(BaseModel):
            is_valid: bool = Field(description="Overall validation status")
            confidence: float = Field(description="Confidence score 0-1")

            class ValidatedFields(BaseModel):
                treatment: Optional[str] = None
                date: Optional[str] = None
                time: Optional[str] = None
                customer_name: Optional[str] = None
                customer_type: Optional[str] = None
                has_confirmation: bool = False

            fields: ValidatedFields = Field(description="Validated field values")
            errors: List[str] = Field(default_factory=list)
            warnings: List[str] = Field(default_factory=list)
            suggestions: List[str] = Field(default_factory=list)

            class NormalizedValues(BaseModel):
                treatment_category: Optional[str] = None
                appointment_datetime: Optional[str] = None
                formatted_name: Optional[str] = None

            normalized: NormalizedValues = Field(description="Normalized values")

        self.output_class = ValidationOutput
        self.parser = JsonOutputParser(pydantic_object=ValidationOutput)

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate with structured output"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Valide dados de agendamento de serviços.

Aplique estas validações:
1. Tratamento: deve ser válido e reconhecido
2. Data/hora: formato correto, futuro, horário comercial
3. Nome: completo com sobrenome
4. Tipo cliente: novo ou existente
5. Confirmação: detectar intenção clara

Retorne o resultado em formato JSON.
{format_instructions}"""),
            ("human", "Dados para validar: {input}")
        ])

        chain = prompt | self.llm | self.parser

        try:
            result = chain.invoke({
                "input": json.dumps(input_data, ensure_ascii=False),
                "format_instructions": self.parser.get_format_instructions()
            })

            return result.model_dump() if hasattr(result, 'model_dump') else result

        except Exception as e:
            logger.error(f"Structured output validation error: {e}")
            return {"is_valid": False, "errors": [str(e)]}


class CachedSemanticValidator(BaseValidationStrategy):
    """
    Semantic validator with intelligent caching.
    Reduces API calls for similar validations.
    """

    def _setup(self):
        """Setup caching mechanism"""
        self.cache_size = 1000
        self._validation_cache = {}

    @lru_cache(maxsize=128)
    def _get_semantic_key(self, text: str) -> str:
        """Generate semantic key for caching"""
        # Use a simpler model for key generation
        prompt = "Gere uma chave semântica curta (max 50 chars) para: {text}"

        try:
            response = self.llm.invoke(prompt.format(text=text[:200]))
            return response.content.strip()[:50]
        except:
            # Fallback to hash
            return str(hash(text))[:50]

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate with semantic caching"""
        # Generate cache key
        cache_key = self._get_semantic_key(str(input_data))

        # Check cache
        if cache_key in self._validation_cache:
            logger.info(f"Cache hit for validation: {cache_key}")
            return self._validation_cache[cache_key]

        # Perform validation
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Realize validação semântica inteligente.
Considere contexto, sinônimos e variações linguísticas.
Retorne JSON com resultado detalhado."""),
            ("human", "{input}")
        ])

        chain = prompt | self.llm | JsonOutputParser()

        try:
            result = chain.invoke({"input": input_data})

            # Cache result
            if len(self._validation_cache) < self.cache_size:
                self._validation_cache[cache_key] = result

            return result

        except Exception as e:
            logger.error(f"Cached semantic validation error: {e}")
            return {"is_valid": False, "errors": [str(e)]}


class EnsembleValidator(BaseValidationStrategy):
    """
    Combines multiple validation strategies for robust results.
    Uses voting or weighted consensus.
    """

    def _setup(self):
        """Setup ensemble validators"""
        self.validators = {
            "function": FunctionCallingValidator(self.llm),
            "structured": StructuredOutputValidator(self.llm),
            "semantic": CachedSemanticValidator(self.llm)
        }

        self.weights = {
            "function": 0.4,
            "structured": 0.4,
            "semantic": 0.2
        }

        # Import StateValidator for basic validation methods
        from .validators import StateValidator
        self.state_validator = StateValidator

    def validate(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate using ensemble approach"""
        results = {}

        # Run all validators
        for name, validator in self.validators.items():
            try:
                results[name] = validator.validate(input_data)
            except Exception as e:
                logger.error(f"Ensemble validator {name} failed: {e}")
                results[name] = {"is_valid": False, "errors": [str(e)]}

        # Aggregate results
        return self._aggregate_results(results)

    def _aggregate_results(self, results: Dict[str, Dict]) -> Dict[str, Any]:
        """Aggregate results from multiple validators"""
        # Weighted voting for is_valid
        total_weight = sum(self.weights.values())
        valid_score = sum(
            self.weights.get(name, 0) * (1 if result.get("is_valid", False) else 0)
            for name, result in results.items()
        ) / total_weight

        # Collect all errors and warnings
        all_errors = []
        all_warnings = []

        for result in results.values():
            all_errors.extend(result.get("errors", []))
            all_warnings.extend(result.get("warnings", []))

        # Merge normalized values (prefer function calling results)
        normalized = {}
        for name in ["function", "structured", "semantic"]:
            if name in results and "normalized_values" in results[name]:
                normalized.update(results[name]["normalized_values"])

        return {
            "is_valid": valid_score >= 0.5,
            "confidence": valid_score,
            "errors": list(set(all_errors)),  # Deduplicate
            "warnings": list(set(all_warnings)),
            "normalized_values": normalized,
            "validator_results": results
        }

    def is_confirmation(self, text: str, context: Optional[str] = None) -> bool:
        """Check if text contains confirmation intent using basic validator"""
        return self.state_validator.is_confirmation(text)

    def is_cancellation(self, text: str, context: Optional[str] = None) -> bool:
        """Check if text contains cancellation intent using basic validator"""
        return self.state_validator.is_cancellation(text)

    def validate_date(self, date_str: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Validate date using semantic understanding"""
        result = self.validate({"date": date_str, "validation_type": "date"})

        if result.get("is_valid"):
            normalized = result.get("normalized_values", {}).get("date", date_str)
            return True, None, normalized
        else:
            errors = result.get("errors", ["Invalid date"])
            return False, errors[0] if errors else "Invalid date", None

    def validate_time(self, time_str: str, context: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """Validate time using semantic understanding"""
        result = self.validate({"time": time_str, "context": context, "validation_type": "time"})

        if result.get("is_valid"):
            normalized = result.get("normalized_values", {}).get("time", time_str)
            return True, None, normalized
        else:
            errors = result.get("errors", ["Invalid time"])
            return False, errors[0] if errors else "Invalid time", None

    def validate_treatment(self, treatment_str: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Validate treatment using ensemble approach"""
        result = self.validate({"treatment": treatment_str, "validation_type": "treatment"})

        if result.get("is_valid"):
            normalized = result.get("normalized_values", {}).get("treatment", treatment_str)
            return True, None, normalized
        else:
            errors = result.get("errors", ["Invalid treatment"])
            return False, errors[0] if errors else "Invalid treatment", None

    def validate_customer_name(self, name_str: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Validate customer name using ensemble approach"""
        result = self.validate({"customer_name": name_str, "validation_type": "name"})

        if result.get("is_valid"):
            normalized = result.get("normalized_values", {}).get("customer_name", name_str)
            return True, None, normalized
        else:
            errors = result.get("errors", ["Invalid name"])
            return False, errors[0] if errors else "Invalid name", None


# Factory with strategy pattern
class ValidatorFactory:
    """Factory for creating validators with different strategies"""

    _strategies = {
        "function_calling": FunctionCallingValidator,
        "runnable": RunnableValidator,
        "structured": StructuredOutputValidator,
        "cached_semantic": CachedSemanticValidator,
        "ensemble": EnsembleValidator
    }

    @classmethod
    def create(
        cls,
        strategy: str = "ensemble",
        llm: Optional[ChatOpenAI] = None
    ) -> ValidationStrategy:
        """
        Create validator with specified strategy.

        Args:
            strategy: Validation strategy name
            llm: Optional LLM instance

        Returns:
            Validator instance
        """
        if strategy not in cls._strategies:
            raise ValueError(f"Unknown strategy: {strategy}. Available: {list(cls._strategies.keys())}")

        validator_class = cls._strategies[strategy]
        return validator_class(llm)

    @classmethod
    def register_strategy(cls, name: str, validator_class: type):
        """Register custom validation strategy"""
        cls._strategies[name] = validator_class