
"""
Módulo para melhorar o fluxo de validação de slots, verificando disponibilidade
e fornecendo respostas contextualizadas em vez de mensagens de erro genéricas.
"""

import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, List
from zoneinfo import ZoneInfo
from langchain_openai import ChatOpenAI
from ..scheduling.scheduling_service import SchedulingService, SP_TZ
from .slot_verification import verify_slot_availability, suggest_alternative_slots
from backend.services.ai_provider_service import get_company_openai_api_key

logger = logging.getLogger(__name__)

def check_date_availability(db, company_id: int, date_str: str, time_str: str, conversation_context: str = "") -> Tuple[bool, List[str], str]:
    """
    Verifica disponibilidade e gera resposta natural apenas quando NÃO disponível.

    Args:
        db: Sessão do banco de dados
        company_id: ID da empresa
        date_str: String de data (ex: "13/03", "13/03/2025")
        time_str: String de horário (ex: "14:00", "14h")
        conversation_context: Últimas mensagens da conversa para contextualização

    Returns:
        Tupla (disponível, alternativas, mensagem)
    """
    # Verificar disponibilidade
    is_available, formatted_slot = verify_slot_availability(db, company_id, date_str, time_str)

    # Preparar contexto para o LLM
    date_part = formatted_slot.split()[0] if formatted_slot else date_str
    time_part = formatted_slot.split()[1] if formatted_slot else time_str

    # Verificar se é "amanhã"
    tomorrow = (datetime.now(SP_TZ) + timedelta(days=1)).date()
    try:
        slot_date = datetime.strptime(date_part, "%d/%m/%Y").date()
        is_tomorrow = slot_date == tomorrow
    except:
        is_tomorrow = False

    date_context = f"amanhã ({date_part})" if is_tomorrow else date_part

    if is_available:
        # Slot disponível - não gerar mensagem, apenas retornar status
        return True, [], ""
    else:
        # Slot indisponível - obter alternativas e gerar mensagem
        alternatives = suggest_alternative_slots(db, company_id, date_str, time_str, max_suggestions=2)

        if not alternatives:
            # Sem alternativas - obter slots genéricos
            scheduling_service = SchedulingService(db=db, company_id=company_id)
            available_slots = scheduling_service.get_next_available_slots()
            alternatives = available_slots[:2] if available_slots else []

        # Formatar alternativas para LLM
        alt_display = []
        for alt in alternatives:
            alt_date = alt.split()[0]
            alt_time = alt.split()[1]

            # Verificar se alternativa é amanhã
            try:
                alt_date_obj = datetime.strptime(alt_date, "%d/%m/%Y").date()
                if alt_date_obj == tomorrow:
                    alt_display.append(f"amanhã ({alt_date}) às {alt_time}")
                else:
                    alt_display.append(f"{alt_date} às {alt_time}")
            except:
                alt_display.append(f"{alt_date} às {alt_time}")

        suggestions = " ou ".join(alt_display)

        # Gerar resposta com LLM apenas para indisponibilidade
        prompt = f"""
        Como assistente de agendamento de uma empresa de serviços,
        crie uma resposta natural e amigável explicando que o horário solicitado
        para {date_context} às {time_part} não está disponível.

        Alternativas disponíveis: {suggestions}

        A resposta deve:
        1. Informar de forma educada que o horário solicitado não está disponível
        2. Sugerir 2 alternativas disponíveis SOMENTE, proximas do horario escolhido.
        3. Perguntar se alguma das alternativas funciona para o usuário
        4. Ser breve (máximo de 3 frases)
        5. Ser cordial e natural

        Contexto da conversa: {conversation_context}
        """

        try:
            llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0.7,
                openai_api_key=get_company_openai_api_key(db, company_id),
            )
            response = llm.invoke(prompt).content.strip()
            return False, alternatives, response
        except Exception as e:
            logger.error(f"[ImprovedFlow] Erro ao gerar resposta com LLM: {e}")
            # Fallback para resposta padrão
            return False, alternatives, f"Infelizmente não temos disponibilidade para {date_context} às {time_part}. Posso sugerir {suggestions}. Algum desses horários funciona para você?"

def handle_date_time_extraction(state_machine, extracted_date: str, extracted_time: str) -> Optional[str]:
    """
    Processa data/hora extraídos e verifica disponibilidade.
    Interrompe o fluxo apenas quando o horário NÃO está disponível.

    Args:
        state_machine: Instância de ConversationStateMachine
        extracted_date: Data extraída da conversa
        extracted_time: Horário extraído da conversa

    Returns:
        Mensagem contextualizada para o usuário se não disponível, ou None para continuar fluxo normal
    """
    # Verificar se temos data e horário extraídos
    if not extracted_date or not extracted_time:
        return None

    # Verificar disponibilidade
    is_available, alternatives, context_message = check_date_availability(
        state_machine.db_session,
        state_machine.company_id,
        extracted_date,
        extracted_time
    )

    if is_available:
        # Slot disponível - apenas marca internamente e continua o fluxo
        # Marcar que o slot foi verificado
        state_machine.set_state_data("slot_verified", True)

        # Marcar que a confirmação já foi implicitamente aceita (para evitar perguntar novamente)
        state_machine.set_state_data("confirmation_asked", True)
        state_machine.set_state_data("user_confirmed", True)

        logger.info(f"[ImprovedFlow] Slot disponível: {extracted_date} {extracted_time} - continuando fluxo normal")

        # Retornar None para não interromper o fluxo normal
        return None
    else:
        # Slot indisponível - atualizar state_machine com alternativas e interromper fluxo
        logger.warning(f"[ImprovedFlow] Slot indisponível: {extracted_date} {extracted_time}")

        if alternatives:
            # Limpar data/hora inválidos
            state_machine.set_state_data("data", None)
            state_machine.set_state_data("horario", None)

            # Armazenar alternativas para uso futuro
            state_machine.set_state_data("slot_alternatives", alternatives)

            # Voltar para o step de coleta de data/hora
            state_machine.set_current_step(4)

        # Retornar mensagem contextualizada sobre indisponibilidade
        return context_message

def process_slot_selection(state_machine, user_input: str) -> Optional[str]:
    """
    Processa a seleção de um slot alternativo pelo usuário.

    Args:
        state_machine: Instância de ConversationStateMachine
        user_input: Entrada de texto do usuário

    Returns:
        Mensagem para o usuário ou None para continuar fluxo normal
    """
    # Verificar se temos alternativas armazenadas
    alternatives = state_machine.get_state_data("slot_alternatives", [])
    if not alternatives:
        return None

    # Verificar se o usuário está selecionando uma das alternativas
    user_input_lower = user_input.lower()

    # Aceita respostas como "primeira opção", "segundo horário", "opção 1", etc.
    first_option_terms = ["primeira", "primeiro", "1", "opção 1", "opção 1", "primeira opção"]
    second_option_terms = ["segunda", "segundo", "2", "opção 2", "opção 2", "segunda opção"]

    if any(term in user_input_lower for term in first_option_terms) and len(alternatives) >= 1:
        selected_slot = alternatives[0]
        state_machine.set_state_data("slot_alternatives", [])
        process_selected_alternative(state_machine, selected_slot)
        return f"Perfeito! Você selecionou o horário {selected_slot}. Confirmado?"

    elif any(term in user_input_lower for term in second_option_terms) and len(alternatives) >= 2:
        selected_slot = alternatives[1]
        state_machine.set_state_data("slot_alternatives", [])
        process_selected_alternative(state_machine, selected_slot)
        return f"Perfeito! Você selecionou o horário {selected_slot}. Confirmado?"

    # Verificar se o usuário está mencionando uma das alternativas diretamente
    for slot in alternatives:
        slot_date = slot.split()[0]
        slot_time = slot.split()[1]

        # Verificar se a data ou horário estão na resposta
        if slot_date in user_input_lower or slot_time in user_input_lower:
            state_machine.set_state_data("slot_alternatives", [])
            process_selected_alternative(state_machine, slot)
            return f"Perfeito! Você selecionou o horário {slot}. Confirmado?"

    # Se chegou aqui, o usuário não selecionou nenhuma alternativa claramente
    return None

def process_selected_alternative(state_machine, selected_slot: str) -> None:
    """
    Processa o slot alternativo selecionado pelo usuário.

    Args:
        state_machine: Instância de ConversationStateMachine
        selected_slot: Slot selecionado no formato "DD/MM/YYYY HH:MM"
    """
    if not selected_slot or " " not in selected_slot:
        return

    # Extrair data e horário
    date_part = selected_slot.split()[0]
    time_part = selected_slot.split()[1]

    # Atualizar state machine
    state_machine.set_state_data("data", date_part)
    state_machine.set_state_data("horario", time_part)

    # Atualizar para step que coleta nome ou confirma agendamento
    if state_machine.get_state_data("nome"):
        # Se já temos o nome, podemos ir para confirmação
        state_machine.set_current_step(5)
    else:
        # Se não temos nome, precisamos coletá-lo
        state_machine.set_current_step(5)  # Step que coleta nome
