"""
LangChain-based transition chain for appointment state management.
Uses LLM to make intelligent decisions about conversation flow.
"""

import logging
from typing import Dict, Any, Optional, List
try:
    # LangChain 0.3.x
    from langchain.chains import LLMChain
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import PydanticOutputParser
    from langchain_openai import ChatOpenAI
except ImportError:
    # LangChain 0.2.x and older
    from langchain.chains import LLMChain
    from langchain.prompts import ChatPromptTemplate
    from langchain.output_parsers import PydanticOutputParser
    from langchain_openai import ChatOpenAI

from .models import TransitionDecision, AppointmentState, TransitionContext

# Importar validadores avançados
try:
    from .semantic_validator import SmartValidator
    SMART_VALIDATOR_AVAILABLE = True
except ImportError:
    from .validators import StateValidator
    SMART_VALIDATOR_AVAILABLE = False

logger = logging.getLogger(__name__)


class TransitionChain:
    """
    Custom chain for state transition decisions.
    Uses LLMChain internally with validation and business logic.
    """

    def __init__(self, llm: ChatOpenAI, verbose: bool = False, use_smart_validator: bool = True):
        """Initialize transition chain with LLM and parser"""
        self.parser = PydanticOutputParser(pydantic_object=TransitionDecision)

        # Usar SmartValidator se disponível e habilitado
        if SMART_VALIDATOR_AVAILABLE and use_smart_validator:
            self.validator = SmartValidator(llm)
            self.use_smart_validator = True
            logger.info("[TransitionChain] Usando SmartValidator para validações semânticas")
        else:
            self.validator = StateValidator()
            self.use_smart_validator = False
            logger.info("[TransitionChain] Usando StateValidator básico")

        self.verbose = verbose

        # Create prompt and chain
        self.prompt = self._create_prompt()
        self.chain = LLMChain(llm=llm, prompt=self.prompt, verbose=verbose)
        self.output_key = self.chain.output_key

    def _create_prompt(self) -> ChatPromptTemplate:
        """Create the prompt template for transition decisions"""
        format_instructions = self.parser.get_format_instructions()
        return ChatPromptTemplate.from_messages([
            ("system", """Você é um especialista em fluxo de agendamento de serviços.
Analise o estado atual da conversa e decida se deve avançar para a próxima etapa.

REGRAS DE TRANSIÇÃO POR ETAPA:

Step 0 → 1: Início da conversa
- Avança quando: Qualquer interação do usuário
- Valida: Nada específico

Step 1 → 2: Identificação do tratamento
- Avança quando: Tratamento foi identificado
- Valida: Campo 'treatment' preenchido
- Exemplo: "implante", "clareamento", "limpeza"

Step 2 → 3: Tipo de cliente
- Avança quando: Tipo de cliente identificado (novo/existente)
- Valida: Campo 'customer_type' preenchido

Step 3 → 4: Conscientização e oferta de horários
- Avança quando: Usuário demonstra interesse em agendar
- Valida: Intenção de agendamento

Step 4 → 5: Seleção e confirmação de horário
- Avança quando: Data E horário foram escolhidos E confirmados EXPLICITAMENTE
- Valida: Campos 'appointment_date' e 'appointment_time' preenchidos
- IMPORTANTE: NÃO avance apenas por ter data/hora. Usuário DEVE confirmar!
- Verificar: slot_verified = true, user_confirmed_slot = true

Step 5 → 6: Coleta do nome completo
- Avança quando: Nome completo fornecido
- Valida: Campo 'customer_name' preenchido

Step 6 → 7: Finalização
- Avança quando: Todos os dados necessários foram coletados
- Valida: Todos os campos obrigatórios preenchidos

IMPORTANTE:
1. No step 4, aguarde CONFIRMAÇÃO EXPLÍCITA do usuário antes de avançar
2. Palavras de confirmação: "sim", "confirmo", "pode ser", "ok", "perfeito", etc.
3. Se o usuário apenas escolheu horário mas não confirmou, NÃO avance
4. MUDANÇA CRÍTICA: Se o assistente já mencionou o preço em qualquer momento da conversa, considere price_shown = true
5. NÃO bloqueie o avanço por "preço não mostrado" se já foi mencionado anteriormente

{format_instructions}"""),

            ("human", """Estado atual:
Step atual: {current_step}
Dados salvos:
- Tratamento: {treatment}
- Tipo cliente: {customer_type}
- Nome: {customer_name}
- Data: {appointment_date}
- Horário: {appointment_time}
- Confirmado: {confirmed}
- Preço mostrado: {price_shown}
- Slot verificado: {slot_verified}
- Usuário confirmou slot: {user_confirmed_slot}

Entrada do usuário: "{user_input}"

Dados extraídos da entrada: {extracted_data}

Slots disponíveis: {available_slots_count} horários

Última resposta do assistente: {llm_response}

Analise e decida se deve avançar para o próximo step.""")
        ])

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the chain with validation.

        Args:
            inputs: Context for decision

        Returns:
            Decision with validation results
        """
        try:
            # Add format instructions
            inputs["format_instructions"] = self.parser.get_format_instructions()

            # Call LLM chain
            response = self.chain.invoke(inputs)

            # Parse response
            decision = self.parser.parse(response[self.output_key])

            # Add validation based on current step
            self._add_validations(decision, inputs)

            return {self.output_key: decision}

        except Exception as e:
            logger.error(f"[TransitionChain] Error in chain execution: {e}", exc_info=True)
            # Return safe default decision
            return {
                self.output_key: TransitionDecision(
                    should_advance=False,
                    reason=f"Erro ao processar: {str(e)}",
                    validation_errors=[str(e)]
                )
            }

    def _add_validations(self, decision: TransitionDecision, inputs: Dict[str, Any]) -> None:
        """Add business logic validations to the decision"""
        current_step = inputs.get("current_step", 0)
        user_input = inputs.get("user_input", "")

        # Se usando SmartValidator, fazer validações semânticas adicionais
        if self.use_smart_validator and hasattr(self.validator, 'is_confirmation'):
            # Contexto para validação semântica
            context = f"Step {current_step} - Aguardando confirmação de horário"

            # Validar confirmação semântica no step 4
            if current_step == 4 and decision.should_advance:
                if not inputs.get("user_confirmed_slot"):
                    # Verificar confirmação semântica
                    if self.validator.is_confirmation(user_input, context):
                        logger.info("[TransitionChain] Confirmação semântica detectada")
                        # Atualizar decisão para indicar confirmação
                        decision.update_fields["user_confirmed_slot"] = True
                    else:
                        decision.validation_errors.append(
                            "Aguardando confirmação explícita do horário escolhido"
                        )
                        decision.should_advance = False
                        decision.reason = "Usuário precisa confirmar o horário"

        # Validações padrão
        if current_step == 4:
            # Special validation for step 4 - needs explicit confirmation
            if decision.should_advance:
                if not inputs.get("user_confirmed_slot") and "user_confirmed_slot" not in decision.update_fields:
                    decision.validation_errors.append(
                        "Usuário ainda não confirmou explicitamente o horário"
                    )
                    decision.should_advance = False
                    decision.reason = "Aguardando confirmação explícita do usuário"

                if not inputs.get("slot_verified"):
                    decision.validation_errors.append(
                        "Disponibilidade do horário não foi verificada"
                    )
                    decision.should_advance = False

        # Check if price was shown before final confirmation
        if current_step >= 4 and decision.should_advance:
            if not inputs.get("price_shown"):
                decision.validation_errors.append(
                    "Preço deve ser informado antes da confirmação"
                )
                decision.needs_confirmation = True


def create_transition_chain(
    llm: Optional[ChatOpenAI] = None,
    model: str = "gpt-4.1-mini-2025-04-14",
    temperature: float = 0.1,
    verbose: bool = False
) -> TransitionChain:
    """
    Factory function to create a transition chain.

    Args:
        llm: Existing LLM instance (optional)
        model: Model name if creating new LLM
        temperature: Temperature for LLM
        verbose: Enable verbose logging

    Returns:
        Configured TransitionChain
    """
    if not llm:
        llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=500
        )

    return TransitionChain(llm=llm, verbose=verbose)


def prepare_transition_context(
    state: AppointmentState,
    context: TransitionContext
) -> Dict[str, Any]:
    """
    Prepare input context for the transition chain.

    Args:
        state: Current appointment state
        context: Transition context with user input

    Returns:
        Dictionary ready for chain input
    """
    return {
        # State fields
        "current_step": state.current_step,
        "treatment": state.treatment or "não informado",
        "customer_type": state.customer_type or "não informado",
        "customer_name": state.customer_name or "não informado",
        "appointment_date": state.appointment_date or "não selecionada",
        "appointment_time": state.appointment_time or "não selecionado",
        "confirmed": state.confirmed,
        "price_shown": state.price_shown,
        "slot_verified": state.slot_verified,
        "user_confirmed_slot": state.user_confirmed_slot,

        # Context fields
        "user_input": context.user_input,
        "extracted_data": str(context.extracted_data),
        "available_slots_count": len(context.available_slots),
        "llm_response": (context.llm_response or "")[:500]  # Limit size
    }