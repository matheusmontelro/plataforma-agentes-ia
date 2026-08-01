"""
Base Customer Chain - Common Functionality
=========================================

Base class for all customer status-specific chains providing:
1. Common LangChain integration patterns
2. Agent config loading and prompt template creation
3. Error handling and validation
4. Memory management and conversation history
5. Response filtering and action validation
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, ClassVar
from datetime import datetime
from sqlalchemy.orm import Session

from langchain.chains.base import Chain
from pydantic import Field, ConfigDict
from langchain_openai import ChatOpenAI
from backend.services.ai_provider_service import get_company_openai_api_key
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain.memory import ConversationBufferWindowMemory

# Import existing infrastructure
from backend.prompt.db_integration.agent_config import get_agent_config_dict
from backend.prompt.memory.memory_manager import get_chat_history
from backend.prompt.scheduling.scheduling_service import SchedulingService

# Import our new models
from ..customer_routing.models import (
    CustomerStatus,
    CustomerStatusResult,
    ActionType,
    AllowedActions,
    ChainExecutionResult
)

logger = logging.getLogger(__name__)


class BaseCustomerChain(Chain, ABC):
    """
    Abstract base class for customer status-specific chains.

    Provides common functionality:
    - Agent config loading
    - Prompt template creation
    - Memory management
    - Error handling
    - Response validation
    - Action restriction enforcement
    """

    input_keys: ClassVar[List[str]] = ["user_input", "conversation_history", "customer_status", "allowed_actions"]
    output_keys: ClassVar[List[str]] = ["response", "execution_result"]

    # Declare Pydantic fields for attributes
    db: Session = Field(default=None, exclude=True)
    company_id: int = Field(default=0)
    memory_window: int = Field(default=10)
    enable_response_filtering: bool = Field(default=True)
    agent_config: Dict[str, Any] = Field(default_factory=dict, exclude=True)
    llm: Optional[ChatOpenAI] = Field(default=None, exclude=True)
    prompt_template: Optional[ChatPromptTemplate] = Field(default=None, exclude=True)
    memory: Optional[ConversationBufferWindowMemory] = Field(default=None, exclude=True)
    output_parser: Optional[StrOutputParser] = Field(default=None, exclude=True)
    scheduling_service: Optional[Any] = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        db: Session,
        company_id: int,
        llm: Optional[ChatOpenAI] = None,
        memory_window: int = 10,
        enable_response_filtering: bool = True
    ):
        """
        Initialize base chain with common components.

        Args:
            db: Database session
            company_id: Company ID for context
            llm: Optional LLM instance (will create if not provided)
            memory_window: Number of messages to keep in memory
            enable_response_filtering: Whether to filter responses for restrictions
        """
        super().__init__()

        self.db = db
        self.company_id = company_id
        self.memory_window = memory_window
        self.enable_response_filtering = enable_response_filtering

        # Load company configuration
        self.agent_config = self._load_agent_config()

        # Initialize LLM
        self.llm = llm or self._create_default_llm()

        # Create prompt template (implemented by subclasses)
        self.prompt_template = self._create_prompt_template()

        # Create memory management
        self.memory = ConversationBufferWindowMemory(
            k=memory_window,
            memory_key="conversation_history",
            input_key="user_input",
            output_key="response",
            return_messages=True
        )

        # Create output parser
        self.output_parser = StrOutputParser()

        # Initialize scheduling service (for chains that need it)
        self.scheduling_service = None
        try:
            self.scheduling_service = SchedulingService(db, company_id)
        except Exception as e:
            logger.warning(f"[BaseChain] Could not initialize scheduling service: {e}")

        logger.info(f"[{self.__class__.__name__}] Initialized for company_id={company_id}")

    def _load_agent_config(self) -> Dict[str, Any]:
        """Load agent configuration from database"""
        try:
            config = get_agent_config_dict(self.db, self.company_id)
            if not config:
                logger.warning(f"[BaseChain] No agent config found for company_id={self.company_id}")
                return self._get_default_config()
            return config
        except Exception as e:
            logger.error(f"[BaseChain] Error loading agent config: {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration when database config is unavailable"""
        return {
            "assistant_identity": {
                "name": "Assistente Virtual",
                "role": "Assistente de agendamento de serviços",
                "personality": "Profissional, empática e eficiente"
            },
            "company_info": {
                "name": "Empresa de serviços",
                "specialties": ["Serviços gerais"],
                "working_hours": "Segunda a Sexta: 8h às 18h"
            },
            "conversation_flow": {
                "greeting": "Olá! Como posso ajudar você hoje?",
                "default_response": "Entendi. Como posso ajudar?"
            }
        }

    def _create_default_llm(self) -> ChatOpenAI:
        """Create default LLM instance"""
        return ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.7,
            max_tokens=1000,
            openai_api_key=get_company_openai_api_key(
                self.db,
                self.company_id,
            ),
        )

    @abstractmethod
    def _create_prompt_template(self) -> ChatPromptTemplate:
        """
        Create prompt template specific to customer status.
        Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    def _get_allowed_actions(self) -> List[ActionType]:
        """
        Get actions allowed for this chain's customer status.
        Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    def _get_status_specific_context(self, customer_status: CustomerStatusResult) -> Dict[str, Any]:
        """
        Get context specific to this customer status.
        Must be implemented by subclasses.
        """
        pass

    def _call(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the chain with error handling and validation.

        Args:
            inputs: Chain inputs including user_input, customer_status, etc.

        Returns:
            Dict with response and execution metadata
        """
        start_time = datetime.now()

        try:
            # Extract inputs
            user_input = inputs.get("user_input", "")
            customer_status = inputs.get("customer_status")
            conversation_history = inputs.get("conversation_history", [])
            allowed_actions = inputs.get("allowed_actions")

            # Validate inputs
            if not customer_status:
                raise ValueError("customer_status is required")

            # Prepare prompt variables
            prompt_vars = self._prepare_prompt_variables(
                user_input,
                customer_status,
                conversation_history,
                allowed_actions
            )

            # Execute LLM chain
            response = self._execute_llm_chain(prompt_vars)

            # Post-process response
            final_response = self._post_process_response(response, customer_status, allowed_actions)

            # Calculate execution time
            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            # Create execution result
            execution_result = ChainExecutionResult(
                response=final_response,
                used_chain=self.__class__.__name__,
                customer_status=customer_status.status,
                execution_time_ms=execution_time,
                customer_context=customer_status.dict(),
                conversation_state={"last_interaction": datetime.now().isoformat()}
            )

            logger.info(f"[{self.__class__.__name__}] Executed successfully in {execution_time:.1f}ms")

            return {
                "response": final_response,
                "execution_result": execution_result
            }

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] Execution error: {e}", exc_info=True)

            # Return error response
            error_response = self._get_error_response(str(e))
            execution_result = ChainExecutionResult(
                response=error_response,
                used_chain=self.__class__.__name__,
                customer_status=customer_status.status if customer_status else CustomerStatus.LEAD,
                execution_time_ms=(datetime.now() - start_time).total_seconds() * 1000,
                restrictions_violated=[f"Error: {str(e)}"]
            )

            return {
                "response": error_response,
                "execution_result": execution_result
            }

    def _prepare_prompt_variables(
        self,
        user_input: str,
        customer_status: CustomerStatusResult,
        conversation_history: List[Dict[str, Any]],
        allowed_actions: AllowedActions
    ) -> Dict[str, Any]:
        """
        Prepare variables for prompt template.

        Args:
            user_input: Current user input
            customer_status: Customer status context
            conversation_history: Recent conversation messages
            allowed_actions: Actions allowed for this status

        Returns:
            Dict with template variables
        """
        # Base prompt variables
        variables = {
            "user_input": user_input,
            "customer_status_description": customer_status.get_status_description(),
            "last_appointment": customer_status.last_appointment.strftime("%d/%m/%Y às %H:%M") if customer_status.last_appointment else "N/A",
            "allowed_actions_list": "\n".join([f"✅ {action.value}" for action in allowed_actions.actions]),
            "restrictions_list": "\n".join([f"❌ {restriction}" for restriction in allowed_actions.restrictions]),
            "conversation_history": conversation_history,

            # Agent config sections
            "assistant_name": self.agent_config.get("assistant_identity", {}).get("name", "Assistente Virtual"),
            "company_name": self.agent_config.get("company_info", {}).get("name", "Empresa de serviços"),
            "company_specialties": ", ".join(self.agent_config.get("company_info", {}).get("specialties", ["Serviços gerais"])),

            # Current context
            "current_datetime": datetime.now().strftime("%d/%m/%Y às %H:%M"),
            "company_id": self.company_id,
        }

        # Add status-specific context
        status_context = self._get_status_specific_context(customer_status)
        variables.update(status_context)

        return variables

    def _execute_llm_chain(self, prompt_vars: Dict[str, Any]) -> str:
        """
        Execute LLM chain with prompt variables.

        Args:
            prompt_vars: Prepared prompt variables

        Returns:
            Raw LLM response
        """
        try:
            # Create chain
            chain = self.prompt_template | self.llm | self.output_parser

            # Execute
            response = chain.invoke(prompt_vars)

            return response.strip() if response else ""

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] LLM execution error: {e}")
            raise

    def _post_process_response(
        self,
        response: str,
        customer_status: CustomerStatusResult,
        allowed_actions: AllowedActions
    ) -> str:
        """
        Post-process LLM response for validation and filtering.

        Args:
            response: Raw LLM response
            customer_status: Customer status context
            allowed_actions: Allowed actions for validation

        Returns:
            Processed and validated response
        """
        if not self.enable_response_filtering:
            return response

        try:
            # Basic validation
            if not response or len(response.strip()) < 10:
                return self._get_fallback_response(customer_status)

            # Check for restriction violations
            filtered_response = self._filter_restricted_content(response, allowed_actions)

            # Ensure response doesn't exceed reasonable length
            if len(filtered_response) > 2000:
                filtered_response = filtered_response[:1800] + "..."
                logger.warning(f"[{self.__class__.__name__}] Response truncated due to length")

            return filtered_response

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] Post-processing error: {e}")
            return self._get_fallback_response(customer_status)

    def _filter_restricted_content(self, response: str, allowed_actions: AllowedActions) -> str:
        """
        Filter response content that violates action restrictions.

        Args:
            response: LLM response to filter
            allowed_actions: Allowed actions for validation

        Returns:
            Filtered response
        """
        # Simple keyword-based filtering (can be enhanced with more sophisticated NLP)
        restricted_phrases = []

        # Check for scheduling-related restrictions
        if ActionType.SCHEDULE_NEW not in allowed_actions.actions:
            if any(phrase in response.lower() for phrase in ["agendar consulta", "marcar horário", "disponível para"]):
                response += "\n\nPara agendamentos, entre em contato diretamente com nossa recepção."

        if ActionType.RESCHEDULE not in allowed_actions.actions:
            if any(phrase in response.lower() for phrase in ["reagendar", "mudar horário", "trocar data"]):
                response += "\n\nPara alterações de agendamento, entre em contato com nossa recepção."

        return response

    def _get_fallback_response(self, customer_status: CustomerStatusResult) -> str:
        """
        Get safe fallback response when main response fails.

        Args:
            customer_status: Customer status for context

        Returns:
            Safe fallback response
        """
        fallback_responses = {
            CustomerStatus.SCHEDULED: "Entendi sua solicitação. Para alterar ou confirmar sua consulta agendada, posso ajudar com informações ou você pode entrar em contato diretamente conosco.",
            CustomerStatus.NO_SHOW: "Vejo que você teve uma consulta conosco. Posso ajudar a reagendar ou esclarecer qualquer dúvida.",
            CustomerStatus.ATTENDED: "Obrigada por entrar em contato! Como cliente da empresa, estou aqui para esclarecer qualquer dúvida sobre seu tratamento.",
            CustomerStatus.PURCHASED: "Fico feliz em ajudar! Como nosso cliente, estou aqui para qualquer suporte ou esclarecimento que precisar.",
            CustomerStatus.LEAD: "Olá! Como posso ajudar você hoje? Estou aqui para esclarecer dúvidas e ajudar com agendamentos."
        }

        return fallback_responses.get(
            customer_status.status,
            "Obrigada pelo contato! Como posso ajudar você hoje?"
        )

    def _get_error_response(self, error_message: str) -> str:
        """
        Get user-friendly error response.

        Args:
            error_message: Technical error message

        Returns:
            User-friendly error response
        """
        return ("Peço desculpas, mas estou tendo uma dificuldade técnica no momento. "
                "Pode repetir sua solicitação ou entrar em contato diretamente conosco? "
                "Estou aqui para ajudar assim que possível!")

    def get_chain_info(self) -> Dict[str, Any]:
        """
        Get information about this chain for debugging/monitoring.

        Returns:
            Dict with chain information
        """
        return {
            "chain_name": self.__class__.__name__,
            "company_id": self.company_id,
            "memory_window": self.memory_window,
            "response_filtering_enabled": self.enable_response_filtering,
            "allowed_actions": self._get_allowed_actions(),
            "llm_model": getattr(self.llm, "model_name", "unknown"),
            "has_scheduling_service": self.scheduling_service is not None
        }
