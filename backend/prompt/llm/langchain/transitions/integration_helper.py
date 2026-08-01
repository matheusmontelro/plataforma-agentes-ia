"""
Helpers for integrating the transition system with the generic legacy LLM.
Provides a compatibility layer during migration.
"""

import logging
import redis
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session

from .models import AppointmentState, TransitionContext, TransitionDecision
from .state_manager import LangChainStateManager
from .transition_chain import create_transition_chain, prepare_transition_context

# Importar validadores avançados
try:
    from .validation_strategies import ValidatorFactory
    from .semantic_validator import SmartValidator
    ADVANCED_VALIDATORS_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("[Integration] Validadores avançados disponíveis")
except ImportError:
    from .validators import StateValidator
    ADVANCED_VALIDATORS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("[Integration] Usando validador básico (avançados não disponíveis)")


def get_redis_client() -> redis.Redis:
    """Get Redis client instance"""
    # Try to get from environment or use default
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url)


def process_transition_with_langchain(
    db: Session,
    phone: str,
    company_id: int,
    user_input: str,
    extracted_data: Dict[str, Any],
    available_slots: list,
    llm_response: Optional[str] = None,
    validation_strategy: str = "ensemble"
) -> Tuple[Optional[str], AppointmentState, TransitionDecision]:
    """
    Process state transition using the new LangChain system.

    Args:
        db: Database session
        phone: Customer phone
        company_id: Company ID
        user_input: User input text
        extracted_data: Data extracted from user input
        available_slots: Available appointment slots
        llm_response: Last LLM response (optional)

    Returns:
        Tuple of (confirmation_message, updated_state, decision)
    """
    try:
        # Initialize state manager
        state_manager = LangChainStateManager(redis_client=get_redis_client())

        # Get current state
        current_state = state_manager.get_state(phone, company_id)
        logger.info(f"[Integration] Current state - Step: {current_state.current_step}")

        # Update state with extracted data
        if extracted_data:
            # Map old field names to new ones
            field_mapping = {
                'tratamento': 'treatment',
                'cliente': 'customer_type',
                'nome': 'customer_name',
                'data': 'appointment_date',
                'horario': 'appointment_time',
                'price_verified': 'price_shown'  # Map price verification status
            }

            for old_field, new_field in field_mapping.items():
                if old_field in extracted_data and extracted_data[old_field]:
                    setattr(current_state, new_field, extracted_data[old_field])

            # Check for confirmation flags
            if extracted_data.get('agendamento_confirmado'):
                current_state.confirmed = True
                current_state.user_confirmed_slot = True

        # Usar validador avançado se disponível
        if ADVANCED_VALIDATORS_AVAILABLE:
            # Criar validador com estratégia configurada
            validator = ValidatorFactory.create(validation_strategy)
            logger.info(f"[Integration] Usando validador avançado: {validation_strategy}")

            # Validar confirmação com contexto semântico
            context_str = f"Agendamento de {current_state.treatment or 'consulta'} para {current_state.appointment_date} às {current_state.appointment_time}"

            if validator.is_confirmation(user_input, context_str):
                # If we're in step 4 and have date/time, mark as confirmed
                if current_state.current_step == 4 and current_state.appointment_date and current_state.appointment_time:
                    current_state.user_confirmed_slot = True
                    logger.info("[Integration] Confirmação semântica detectada para slot")

            # Validar cancelamento com contexto
            if validator.is_cancellation(user_input, context_str):
                logger.info("[Integration] Intenção de cancelamento detectada semanticamente")
                # Reset appointment data
                current_state.reset_slot_selection()
                return "Entendi que você deseja cancelar. Posso ajudar com algo mais?", current_state, TransitionDecision(
                    should_advance=False,
                    reason="Usuário solicitou cancelamento"
                )

            # Validar e normalizar data se presente
            if extracted_data.get('data'):
                is_valid, error, normalized_date = validator.validate_date(extracted_data['data'])
                if is_valid and normalized_date:
                    extracted_data['data'] = normalized_date
                    current_state.appointment_date = normalized_date
                    logger.info(f"[Integration] Data normalizada: {normalized_date}")
                elif error:
                    logger.warning(f"[Integration] Erro na validação de data: {error}")

            # Validar e normalizar horário se presente
            if extracted_data.get('horario'):
                is_valid, error, normalized_time = validator.validate_time(
                    extracted_data['horario'],
                    context="Horário comercial da empresa: 8h às 18h"
                )
                if is_valid and normalized_time:
                    extracted_data['horario'] = normalized_time
                    current_state.appointment_time = normalized_time
                    logger.info(f"[Integration] Horário normalizado: {normalized_time}")
                elif error:
                    logger.warning(f"[Integration] Erro na validação de horário: {error}")

            # Validar tratamento se presente
            if extracted_data.get('tratamento'):
                is_valid, error, normalized_treatment = validator.validate_treatment(extracted_data['tratamento'])
                if is_valid and normalized_treatment:
                    extracted_data['tratamento'] = normalized_treatment
                    current_state.treatment = normalized_treatment
                    logger.info(f"[Integration] Tratamento normalizado: {normalized_treatment}")

            # Validar nome se presente
            if extracted_data.get('nome'):
                is_valid, error, formatted_name = validator.validate_customer_name(extracted_data['nome'])
                if is_valid and formatted_name:
                    extracted_data['nome'] = formatted_name
                    current_state.customer_name = formatted_name
                    logger.info(f"[Integration] Nome formatado: {formatted_name}")

        else:
            # Fallback para validador básico
            logger.info("[Integration] Usando validador básico")

            # Check for user confirmation in input
            if StateValidator.is_confirmation(user_input):
                # If we're in step 4 and have date/time, mark as confirmed
                if current_state.current_step == 4 and current_state.appointment_date and current_state.appointment_time:
                    current_state.user_confirmed_slot = True
                    logger.info("[Integration] User confirmation detected for slot")

            # Check for cancellation
            if StateValidator.is_cancellation(user_input):
                logger.info("[Integration] Cancellation intent detected")
                # Reset appointment data
                current_state.reset_slot_selection()
                return "Entendi que você deseja cancelar. Posso ajudar com algo mais?", current_state, TransitionDecision(
                    should_advance=False,
                    reason="Usuário solicitou cancelamento"
                )

        # Create transition context
        context = TransitionContext(
            current_state=current_state,
            user_input=user_input,
            extracted_data=extracted_data,
            available_slots=available_slots,
            llm_response=llm_response
        )

        # Create and run transition chain
        chain = create_transition_chain()
        chain_input = prepare_transition_context(current_state, context)

        result = chain.invoke(chain_input)
        decision = result["text"] if isinstance(result["text"], TransitionDecision) else result

        logger.info(f"[Integration] Transition decision - Advance: {decision.should_advance}, Reason: {decision.reason}")

        # Process decision
        confirmation_msg = None

        if decision.should_advance and decision.next_step is not None:
            current_state.current_step = decision.next_step
            logger.info(f"[Integration] Advanced to step {decision.next_step}")

            # Check if we need to process appointment confirmation
            if decision.next_step == 6 and current_state.is_ready_for_confirmation():
                confirmation_msg = _process_appointment_confirmation(
                    db, current_state, phone, company_id
                )

        # Update fields from decision
        if decision.update_fields:
            for field, value in decision.update_fields.items():
                if hasattr(current_state, field):
                    setattr(current_state, field, value)

        # Save updated state
        state_manager.save_state(current_state)

        # IMPORTANTE: Não retornar mensagens genéricas de confirmação
        # Deixar o LLM conduzir a conversa naturalmente
        # Só retornar confirmation_msg em casos específicos (ex: agendamento confirmado)
        if decision.confirmation_message and current_state.current_step >= 6:
            # Só usa confirmation_message em steps finais
            confirmation_msg = decision.confirmation_message

        return confirmation_msg, current_state, decision

    except Exception as e:
        logger.error(f"[Integration] Error in transition processing: {e}")
        # Return safe defaults
        return None, current_state if 'current_state' in locals() else AppointmentState(phone=phone, company_id=company_id), TransitionDecision(
            should_advance=False,
            reason=f"Erro: {str(e)}",
            validation_errors=[str(e)]
        )


def _process_appointment_confirmation(
    db: Session,
    state: AppointmentState,
    phone: str,
    company_id: int
) -> Optional[str]:
    """
    Process appointment confirmation when all data is ready.
    Calls agendamento_logic to create the actual appointment.

    Args:
        db: Database session
        state: Current appointment state
        phone: Customer phone
        company_id: Company ID

    Returns:
        Confirmation message or None
    """
    try:
        # Import the appointment processing function
        from ....db_integration.agendamento_logic import processar_json_do_llm
        from sqlalchemy import text

        logger.info(f"[Integration] Processing appointment confirmation:")
        logger.info(f"  - Treatment: {state.treatment}")
        logger.info(f"  - Customer: {state.customer_name} ({state.customer_type})")
        logger.info(f"  - Date/Time: {state.appointment_date} {state.appointment_time}")

        # Get client API key
        row_client_data = db.execute(text("""
            SELECT c.api_key
            FROM clients c
            JOIN client_companies cc ON cc.client_id = c.id
            WHERE cc.company_id = :company_id
            LIMIT 1
        """), {"company_id": company_id}).fetchone()

        api_key = row_client_data.api_key if row_client_data else None

        # Prepare the appointment data in the expected format
        llm_json = {
            "tratamento": state.treatment,
            "cliente": state.customer_type,
            "nome": state.customer_name,
            "data": state.appointment_date,
            "horario": state.appointment_time,
            "agendamento_confirmado": True,
            "cancelar_agendamento": False
        }

        logger.info(f"[Integration] Calling processar_json_do_llm with data: {llm_json}")

        # Call the actual appointment creation logic
        result = processar_json_do_llm(
            db=db,
            company_id=company_id,
            phone=phone,
            llm_json=llm_json,
            api_key=api_key
        )

        logger.info(f"[Integration] Appointment processing result: {result[:100]}...")

        # Return the result message from the appointment system
        return result

    except Exception as e:
        logger.error(f"[Integration] Error confirming appointment: {e}")
        import traceback
        logger.error(f"[Integration] Traceback: {traceback.format_exc()}")
        return "Desculpe, houve um erro ao confirmar seu agendamento. Por favor, tente novamente ou entre em contato conosco."


def migrate_old_state_data(old_state_data: Dict[str, Any]) -> AppointmentState:
    """
    Migrate data from old state system to new AppointmentState.

    Args:
        old_state_data: Dictionary from old state system

    Returns:
        New AppointmentState object
    """
    # Map old fields to new
    field_mapping = {
        'tratamento': 'treatment',
        'cliente': 'customer_type',
        'nome': 'customer_name',
        'data': 'appointment_date',
        'horario': 'appointment_time',
        'agendamento_confirmado': 'confirmed',
        'price_verified': 'price_shown',  # Map price verification status
        'missing_fields': 'context'  # Store in context
    }

    new_state = AppointmentState(
        phone=old_state_data.get('phone', ''),
        company_id=old_state_data.get('company_id', 0)
    )

    for old_field, new_field in field_mapping.items():
        if old_field in old_state_data:
            value = old_state_data[old_field]
            if new_field == 'context':
                new_state.context['missing_fields'] = value
            else:
                setattr(new_state, new_field, value)

    # Migrate step number
    if 'step' in old_state_data:
        new_state.current_step = old_state_data['step']

    return new_state
