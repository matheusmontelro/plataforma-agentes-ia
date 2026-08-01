"""
Conversation Flow Chain for managing step-based conversations.

This module implements the main conversation flow using LangChain,
managing the 8 steps of the business company appointment flow.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

from ..prompts.templates import get_step_template, get_system_prompt
from ..core.state_manager import ConversationStateManager

logger = logging.getLogger(__name__)


class ConversationFlowChain:
    """Main chain for managing conversation flow through steps."""

    def __init__(self, llm: Optional[ChatOpenAI] = None, company_config: Dict[str, Any] = None):
        """
        Initialize the conversation flow chain.

        Args:
            llm: Language model instance
            company_config: Configuration dictionary from agent_config
        """
        self.llm = llm or ChatOpenAI(model_name="gpt-4o-mini", temperature=0.7)
        self.company_config = company_config or {}
        self.state_manager = ConversationStateManager()
        # Store chat history manually instead of using deprecated ConversationBufferMemory
        self.chat_history = []

    def process(self,
                user_input: str,
                contact_phone: str,
                company_id: int,
                db_session: Any = None,
                available_slots: list = None,
                **kwargs) -> Dict[str, Any]:
        """
        Process user input through the conversation flow.

        Args:
            user_input: The user's message
            contact_phone: User's phone number
            company_id: Company ID
            db_session: Database session
            available_slots: Available appointment slots
            **kwargs: Additional context variables

        Returns:
            Dict containing response and updated state
        """
        try:
            # Load current state
            current_state = self.state_manager.get_state(contact_phone, company_id, db_session)
            current_step = current_state.get("step", 0)

            logger.info(f"[ConversationFlowChain] Processing step {current_step} for {contact_phone}")

            # Prepare context variables
            context_vars = self._prepare_context_variables(
                current_state,
                user_input,
                available_slots,
                **kwargs
            )

            # Get appropriate prompt template for current step with context
            prompt_template = get_step_template(current_step, context_vars)

            # Load chat history from database if needed
            if not self.chat_history:
                self._load_chat_history(contact_phone, company_id)

            # Create modern chain using LCEL (LangChain Expression Language)
            chain = (
                {"input": RunnablePassthrough()}
                | prompt_template
                | self.llm
                | StrOutputParser()
            )

            # Generate response
            response = chain.invoke({"input": user_input})

            # Store conversation turn
            self._add_to_chat_history(user_input, response)

            # Update state based on response and user input
            new_state = self.state_manager.update_state(
                contact_phone=contact_phone,
                company_id=company_id,
                user_input=user_input,
                assistant_response=response,
                current_state=current_state,
                db_session=db_session
            )

            # Check for step transitions
            should_transition = self._check_transition(
                current_step,
                user_input,
                response,
                new_state
            )

            if should_transition:
                new_state["step"] = current_step + 1
                logger.info(f"[ConversationFlowChain] Transitioning to step {new_state['step']}")

            return {
                "response": response,
                "state": new_state,
                "current_step": new_state["step"],
                "collected_data": {
                    "tratamento": new_state.get("tratamento"),
                    "cliente": new_state.get("cliente"),
                    "nome": new_state.get("nome"),
                    "data": new_state.get("data"),
                    "horario": new_state.get("horario")
                }
            }

        except Exception as e:
            logger.error(f"[ConversationFlowChain] Error processing: {e}", exc_info=True)
            return {
                "response": "Desculpe, houve um erro ao processar sua mensagem. Por favor, tente novamente.",
                "state": current_state,
                "error": str(e)
            }

    def _prepare_context_variables(self,
                                   current_state: Dict[str, Any],
                                   user_input: str,
                                   available_slots: list = None,
                                   **kwargs) -> Dict[str, Any]:
        """Prepare all context variables for the prompt."""

        # Get company configuration sections
        assistant_identity = self.company_config.get("assistant_identity", {})
        company_info = self.company_config.get("company_info", {})
        conversation_flow = self.company_config.get("conversation_flow", {})
        scheduling_config = self.company_config.get("scheduling_config", {})

        # Format available slots if provided
        formatted_slots = self._format_available_slots(available_slots) if available_slots else "Sem horários disponíveis no momento."

        # Get current date/time info
        now = datetime.now()
        today_info = now.strftime("%A, %d/%m/%Y %H:%M")

        return {
            "input": user_input,
            "user_input": user_input,
            # Assistant identity
            "assistant_name": assistant_identity.get("assistant_name", "Assistente"),
            "assistant_role": assistant_identity.get("assistant_role", "assistente virtual"),
            # Company info
            "company_name": company_info.get("company_name", "Nossa empresa"),
            "company_address": company_info.get("company_address", ""),
            "company_phone": company_info.get("company_phone_fixed", ""),
            # Conversation flow steps
            "step0": conversation_flow.get("step0", ""),
            "step1_first": conversation_flow.get("step1First", ""),
            "step1_second": conversation_flow.get("step1Second", ""),
            "step2": conversation_flow.get("step2", ""),
            "step3": conversation_flow.get("step3", ""),
            # Scheduling
            "available_slots": formatted_slots,
            "today_info": today_info,
            # Current state data
            "current_step": current_state.get("step", 0),
            "tratamento": current_state.get("tratamento", ""),
            "cliente": current_state.get("cliente", ""),
            "nome": current_state.get("nome", ""),
            **kwargs
        }

    def _format_available_slots(self, slots: list) -> str:
        """Format available slots for display in the prompt."""
        if not slots:
            return "Sem horários disponíveis no momento."

        # Group slots by day
        from collections import defaultdict
        slots_by_day = defaultdict(list)

        for slot in slots[:10]:  # Limit to 10 slots
            try:
                # Assuming slot format: "DD/MM/YYYY HH:MM"
                date_part = slot.split(" ")[0]
                time_part = slot.split(" ")[1]
                slots_by_day[date_part].append(time_part)
            except:
                continue

        # Format output
        formatted = []
        for date, times in sorted(slots_by_day.items()):
            formatted.append(f"\n{date}:")
            for time in sorted(times):
                formatted.append(f"  - {time}")

        return "\n".join(formatted) if formatted else "Sem horários disponíveis no momento."

    def _check_transition(self,
                          current_step: int,
                          user_input: str,
                          response: str,
                          state: Dict[str, Any]) -> bool:
        """
        Check if should transition to next step based on current context.

        Returns:
            bool: True if should transition to next step
        """
        user_input_lower = user_input.lower()

        # Step-specific transition logic
        if current_step == 0:
            # Transition if user shows interest
            interest_keywords = ["sim", "quero", "gostaria", "preciso", "interesse", "agendar"]
            return any(keyword in user_input_lower for keyword in interest_keywords)

        elif current_step == 1:
            # Transition if treatment was identified
            return state.get("tratamento") is not None

        elif current_step == 2:
            # Transition if customer type was identified
            return state.get("cliente") is not None

        elif current_step == 3:
            # Transition if user agrees to schedule
            agreement_keywords = ["sim", "quero", "vamos", "pode", "agendar", "marcar"]
            return any(keyword in user_input_lower for keyword in agreement_keywords)

        elif current_step == 4:
            # Transition if user selected a time slot
            return state.get("data") is not None and state.get("horario") is not None

        elif current_step == 5:
            # Transition if name was provided
            return state.get("nome") is not None

        elif current_step == 6:
            # Stay in post-scheduling
            return False

        return False

    def reset_conversation(self, contact_phone: str, company_id: int):
        """Reset conversation state and memory for a contact."""
        self.state_manager.reset_state(contact_phone, company_id)
        self.chat_history = []

    def _load_chat_history(self, contact_phone: str, company_id: int):
        """Load chat history from memory manager."""
        try:
            from backend.prompt.memory.memory_manager import get_chat_history
            history = get_chat_history(contact_phone=contact_phone, company_id=company_id)
            if history:
                self.chat_history = [(msg.content, None) for msg in history]
        except Exception as e:
            logger.warning(f"Could not load chat history: {e}")
            self.chat_history = []

    def _add_to_chat_history(self, user_input: str, assistant_response: str):
        """Add a conversation turn to chat history."""
        self.chat_history.append((user_input, assistant_response))