from sqlalchemy import text
from sqlalchemy.orm import Session
import logging
from typing import Optional, List
from .step_definitions import STEP_DEFINITIONS, get_step_definition
from .state_machine import ConversationStateMachine
from ...db_integration import agendamento_logic
from ..validation_integration import validate_conversation_state
from ..improved_validation_flow import handle_date_time_extraction, process_slot_selection

logger = logging.getLogger(__name__)

# Campos necessários para confirmação do agendamento
REQUIRED_FIELDS_FOR_APPOINTMENT = ["tratamento", "cliente", "nome", "data", "horario"]

def check_existing_valid_appointment(db: Session, contact_phone: str, company_id: int) -> bool:
    """
    Verifica se existe um agendamento futuro com status 'SCHEDULED' na tabela agendamentos.
    """
    try:
        query = text("""
            SELECT EXISTS (
                SELECT 1
                FROM agendamentos
                WHERE phone = :phone
                  AND company_id = :company_id
                  AND status = 'SCHEDULED'
                  AND consulta_data > CURRENT_TIMESTAMP
            )
        """)
        result = db.execute(query, {"phone": contact_phone, "company_id": company_id}).scalar_one_or_none()
        return result is True
    except Exception as e:
        logger.error(f"[check_existing_valid_appointment] Erro ao verificar agendamento: {e}")
        return False

def check_all_required_fields(state_machine: ConversationStateMachine) -> List[str]:
    """
    Verifica se todos os campos obrigatórios estão preenchidos.
    Retorna lista de campos faltantes. Se lista vazia, tudo ok.
    """
    missing = []
    for field in REQUIRED_FIELDS_FOR_APPOINTMENT:
        if not state_machine.is_filled(field):
            missing.append(field)
    return missing

# FUNÇÃO REMOVIDA: should_force_advance_step estava travando o sistema
# por verificar métodos que não existem em state_machine.py

def advance_step_if_ready(state_machine: ConversationStateMachine) -> None:
    """
    Não avança para steps de confirmação se o usuário já confirmou.
    Agora com verificação adicional para evitar avanço automático quando há apenas
    data/hora extraídos da resposta do LLM e garantia de verificação de preço antes de avançar.
    """
    current_step = state_machine.get_current_step()
    max_step = max(STEP_DEFINITIONS.keys())

    # NOVO: Se estamos no step 0 mas já temos dados essenciais, avançar para step apropriado
    if current_step == 0:
        # Se temos tratamento, avançar para step 2
        if state_machine.is_filled("tratamento"):
            state_machine.set_current_step(2)
            logger.info("[Transitions] Avançando do step 0 para 2 - tratamento preenchido")
            current_step = 2

        # Se temos cliente também, avançar para step 3
        if state_machine.is_filled("cliente"):
            state_machine.set_current_step(3)
            logger.info("[Transitions] Avançando para step 3 - cliente preenchido")
            current_step = 3

        # Se temos data/horário, avançar para step 4
        if state_machine.is_filled("data") and state_machine.is_filled("horario"):
            state_machine.set_current_step(4)
            logger.info("[Transitions] Avançando para step 4 - data/horário preenchidos")
            current_step = 4

    # Se estiver em cooldown, não permite avanços para steps de agendamento
    if state_machine.has_recent_confirmation():
        if current_step in [4, 5]:
            logger.info("[Transitions] Em cooldown, não avançando para steps de agendamento")
            return

    # Se o usuário já confirmou explicitamente após verificação de preço, pode avançar para encerramento
    if state_machine.get_state_data("user_confirmed", False) and state_machine.get_state_data("price_verified", False) and current_step in [4, 5]:
        # Avançar para o próximo step apenas se data/horário estiverem preenchidos e slot verificado
        if (state_machine.is_filled("data") and
            state_machine.is_filled("horario") and
            state_machine.get_state_data("slot_verified", False)):
            state_machine.set_current_step(6)  # Ir para encerramento
            return

    # REGRA CRÍTICA: Verificar se o preço foi divulgado antes de avançar para step 5 ou confirmar
    if ((current_step == 4 and state_machine.is_filled("data") and state_machine.is_filled("horario")) or
        (current_step == 5)):
        # Se o preço ainda não foi verificado, não permitir avanço para confirmação
        if not state_machine.get_state_data("price_verified", False):
            logger.error("[Transitions] BLOQUEIO: Preço ainda não verificado - não avançando")
            return

        # Verificar confirmações explícitas do usuário
        slot_verified = state_machine.get_state_data("slot_verified", False)
        user_confirmed = state_machine.get_state_data("user_confirmed", False)
        confirmation_asked = state_machine.get_state_data("confirmation_asked", False)

        # Se não temos todas as confirmações necessárias, não avançar
        if not (slot_verified and user_confirmed and confirmation_asked):
            logger.error("[Transitions] BLOQUEIO: Faltam confirmações explícitas do usuário - não avançando")
            return

        # Verificar disponibilidade de slot
        if not state_machine.get_state_data("slot_verified", False):
            logger.info("[Transitions] Aguardando verificação de disponibilidade antes de avançar")
            return

    # Verificação específica para step 5 (confirmação)
    if current_step == 5:
        missing = check_all_required_fields(state_machine)
        # Só avança se:
        # 1. Todos os campos estão preenchidos
        # 2. Não está em cooldown
        # 3. Preço foi verificado
        # 4. Usuário confirmou explicitamente
        if (not missing and
            not state_machine.has_recent_confirmation() and
            state_machine.get_state_data("price_verified", False) and
            state_machine.get_state_data("user_confirmed", False)):

            state_machine.set_state_data("agendamento_confirmado", True)
            if current_step < max_step:
                state_machine.set_current_step(current_step + 1)
            return

    # REMOVIDO: Verificação de avanço automático que estava travando o sistema
    # O avanço deve ser baseado nos dados coletados, não em verificações de apresentação

def handle_special_cases(state_machine: ConversationStateMachine, user_input: str) -> bool:
    """
    Trata casos especiais como cancelamento, reagendamento e confirmações.
    Agora com verificações de estado pós-confirmação e detecção de respostas positivas.
    """
    current_step = state_machine.get_current_step()
    lower_input = user_input.lower()

    # Lista ampla de palavras de confirmação
    confirmation_words = [
        "sim", "confirmo", "confirmado", "confirmar", "pode ser", "ok", "tá bom", "ta bom",
        "tá", "ta", "claro", "com certeza", "exato", "exatamente", "isso", "isso mesmo",
        "perfeito", "beleza", "combinado", "fechado", "de acordo", "concordo", "quero",
        "aceito", "eu aceito", "eu quero", "tá certo", "ta certo", "correto", "positivo",
        "afirmativo", "aham", "uhum", "hmm", "s", "y", "yes", "yeah", "yep", "👍", "tá ok",
        "ta ok", "quero sim", "pode", "agendado", "vamos", "tá fechado", "ta fechado"
    ]

    # Detectar confirmação
    confirmation_asked = state_machine.get_state_data("confirmation_asked", False)
    if confirmation_asked and any(word in lower_input for word in confirmation_words):
        logger.info("[Transitions] Usuário confirmou explicitamente")
        state_machine.set_state_data("user_confirmed", True)
        state_machine.set_state_data("agendamento_confirmado", True)
        return True

    # Se estiver em cooldown, permite apenas reagendamento
    if state_machine.has_recent_confirmation():
        if any(keyword in lower_input for keyword in ["reagendar", "remarcar", "mudar horário", "outro dia"]):
            logger.info("[Transitions] Detectada solicitação de reagendamento pós-cooldown")
            # Reset completo do estado para novo agendamento
            state_machine.reset_post_confirmation()
            state_machine.set_current_step(4)  # Volta para step de agendamento
            return True
        return False

    # Reagendamento (prioridade mais alta que cancelamento)
    if any(keyword in lower_input for keyword in ["reagendar", "remarcar", "mudar horário", "outro dia"]):
        logger.info("[Transitions] Detectada solicitação de reagendamento")

        # Limpa dados antigos de data/horário
        state_machine.state_data.pop("data", None)
        state_machine.state_data.pop("horario", None)
        state_machine.set_state_data("agendamento_confirmado", False)

        # Volta para step de agendamento (4)
        state_machine.set_current_step(4)
        return True

    # Cancelamento (não requer data ou horário, só a confirmação)
    # Context-aware cancellation detection to avoid false positives with time constraints
    time_constraint_indicators = ["depois das", "após", "antes das", "entre", "após as", "antes das",
                                 "depois de", "antes de", "horas", "h", "horário", "horarios"]

    # Check if this appears to be a time constraint expression
    has_time_constraint = any(indicator in lower_input for indicator in time_constraint_indicators)

    # Explicit cancellation words (more specific than before)
    explicit_cancellation_keywords = ["cancelar", "desmarcar", "cancelamento", "quero cancelar", "preciso cancelar"]

    # Conditional cancellation - only if no time constraints are detected
    conditional_cancellation_keywords = ["não posso mais", "não vou conseguir ir",
                                        "não posso ir", "não conseguirei ir", "não poderei comparecer"]

    # Determine if this is actually a cancellation
    is_explicit_cancellation = any(keyword in lower_input for keyword in explicit_cancellation_keywords)
    is_conditional_cancellation = (not has_time_constraint and
                                  any(keyword in lower_input for keyword in conditional_cancellation_keywords))

    if is_explicit_cancellation or is_conditional_cancellation:
        logger.info("[Transitions] Detectada solicitação de cancelamento")

        # Se o step atual for menor que 7, impedimos o cancelamento
        if current_step < 7:
            logger.info("[Transitions] Cancelamento não permitido em step < 7. Ignorando solicitação.")
            return False

        state_machine.set_state_data("cancelar_agendamento", True)

        # Se tiver motivo explícito, salvamos
        if "imprevisto" in lower_input:
            state_machine.set_state_data("motivo_cancelamento", "Surgiu um imprevisto")
        elif "doente" in lower_input:
            state_machine.set_state_data("motivo_cancelamento", "Cliente doente")

        # Avança para o step 8 diretamente, sem precisar de data/horário
        state_machine.set_current_step(8)
        return True

    # Caso o usuário responda que não sabe o tratamento
    dont_know_keywords = [
        # Variações diretas de "não sei"
        "não sei", "nao sei", "naum sei", "n sei", "não seei", "nao seei",
        "não conheço", "nao conheco", "desconheço", "desconheco",

        # Maiúsculas e minúsculas
        "Não sei", "Nao sei", "NÃO SEI", "NAO SEI", "Não Sei", "Nao Sei",
        "N SEI", "n sei", "N Sei", "N/S", "n/s", "NS", "ns",

        # Expressões informais e gírias
        "sei não", "sei naum", "seila", "sei lá", "sei la", "sla", "s/l", "s.l.a.",
        "seilá", "sei lah", "quem sabe", "difícil saber", "difícil dizer",

        # Expressões de incerteza
        "não tenho certeza", "nao tenho certeza", "incerto", "incerta",
        "não tenho ideia", "nao tenho ideia", "não faço ideia", "nao faco ideia",
        "sem ideia", "sem noção", "sem nocao", "nem imagino",

        # Respostas vagas
        "qualquer um", "qualquer coisa", "tanto faz", "pode ser qualquer um",
        "vou ver na hora", "decido depois", "vou decidir depois", "não decidi",
        "não decidi ainda", "ainda não decidi",

        # Respostas negativas
        "nenhum", "nenhuma", "não escolhi", "nao escolhi", "não escolhi ainda",
        "não pensei nisso", "nao pensei nisso", "não pensei ainda",

        # Outras expressões comuns
        "preciso ver", "tenho que ver", "vamos ver", "verei lá", "verei la",
        "depois vejo", "a definir", "indefinido", "não definido", "nao definido",
        "o que você recomenda", "o que vc recomenda", "o q vc recomenda", "oq vc recomenda",
        "me diga você", "vc q sabe", "você que sabe", "vocês que sabem",
        "quero ver as opções", "quero ver as opcoes", "ver opções primeiro",
        "quero avaliar primeiro", "ver depois"
    ]
    if not state_machine.is_filled("tratamento"):
        if any(word in lower_input.lower() for word in dont_know_keywords):
            logger.info("[Transitions] Usuário não sabe qual tratamento - definindo como 'Avaliação'")
            state_machine.set_state_data("tratamento", "Avaliação")
            state_machine.set_state_data("user_responded_dont_know", True)
            return True

    return False

def handle_agendamento_confirmado(state_machine: ConversationStateMachine) -> Optional[str]:
    """
    Processa a confirmação do agendamento quando todos os campos estiverem ok.
    Agora com verificação de cooldown, preço da avaliação e reset pós-confirmação.
    """
    # 1) Verifica se a flag "agendamento_confirmado" está setada
    if not state_machine.is_filled("agendamento_confirmado"):
        return None

    # 2) Verifica se está em período de cooldown
    if state_machine.has_recent_confirmation():
        logger.info("[Transitions] Tentativa de confirmação durante cooldown ignorada")
        return None

    agend_conf = state_machine.get_state_data("agendamento_confirmado")
    if not agend_conf:
        return None

    # 3) Verifica campos obrigatórios
    missing = check_all_required_fields(state_machine)
    if missing:
        logger.info(f"[Transitions] Faltam campos para confirmar: {missing}")
        # Reseta a flag para evitar loop
        state_machine.set_state_data("agendamento_confirmado", False)
        state_machine.set_state_data("missing_fields", missing)
        return None

    # 4) Verificar se o preço da avaliação foi divulgado (se necessário)
    if not state_machine.get_state_data("price_verified", False):
        try:
            # Importar aqui para evitar dependências cíclicas
            from ..validation_service import check_evaluation_price_disclosure, get_full_conversation_history

            # Obter histórico da conversa
            db = state_machine.db_session
            phone = state_machine.phone
            company_id = state_machine.company_id
            conversation_history = get_full_conversation_history(db, phone, company_id)

            # Verificar divulgação de preço
            price_disclosed, price_message = check_evaluation_price_disclosure(
                db, state_machine, conversation_history
            )

            # Marcar se o preço foi divulgado
            state_machine.set_state_data("price_verified", price_disclosed)

            # Se o preço não foi divulgado, interromper confirmação e enviar mensagem
            if not price_disclosed and price_message:
                logger.info(f"[Transitions] Preço não divulgado, enviando mensagem: {price_message}")
                # Não reseta a flag agendamento_confirmado para permitir nova tentativa
                return price_message

        except Exception as e:
            logger.error(f"[Transitions] Erro ao verificar divulgação de preço: {e}")
            # Em caso de erro na verificação, permitir continuação

    # 5) Tudo certo, chama a função de confirmação real
    try:
        logger.info("[Transitions] Confirmando agendamento via agendamento_logic")
        confirm_msg = agendamento_logic.confirm_appointment(state_machine)

        # Se retornou string vazia, significa que validação falhou
        if confirm_msg == "":
            logger.info("[Transitions] Validação falhou, resetando flags e deixando LLM gerar resposta")
            # Resetar flags para forçar novo ciclo
            state_machine.set_state_data("agendamento_confirmado", False)
            state_machine.set_state_data("confirmation_asked", True)
            return None  # Retorna None para deixar o LLM gerar a resposta

        # 6) Reset completo do estado após confirmação bem-sucedida
        state_machine.reset_post_confirmation()

        return confirm_msg

    except Exception as e:
        logger.error(f"[Transitions] Erro ao confirmar agendamento: {e}")
        # Se houve erro, desativa flag para evitar tentativas contínuas
        state_machine.set_state_data("agendamento_confirmado", False)
        return None

def process_step_transition(state_machine: ConversationStateMachine, user_input: str) -> Optional[str]:
    """
    Processa a lógica de transição de steps e retorna mensagem de confirmação se houver.
    Agora previne repetições de perguntas e detecta confirmações.
    IMPORTANTE: Só permite avanço se a pergunta do step atual foi apresentada.
    """
    # REMOVIDO: Verificação de pergunta apresentada estava travando o sistema
    # Os métodos is_question_presented/mark_question_presented não existem
    # e isso estava impedindo o avanço dos steps
    current_step = state_machine.get_current_step()

    # Novo: verificar confirmações para prevenir repetições
    lower_input = user_input.lower()

    # Lista ampla de palavras de confirmação
    confirmation_words = [
        "sim", "confirmo", "confirmado", "confirmar", "pode ser", "ok", "tá bom", "ta bom",
        "tá", "ta", "claro", "com certeza", "exato", "exatamente", "isso", "isso mesmo",
        "perfeito", "beleza", "combinado", "fechado", "de acordo", "concordo", "quero",
        "aceito", "eu aceito", "eu quero", "tá certo", "ta certo", "correto", "positivo",
        "afirmativo", "aham", "uhum", "hmm", "s", "y", "yes", "yeah", "yep", "👍", "tá ok",
        "ta ok", "quero sim", "pode", "agendado", "vamos", "tá fechado", "ta fechado"
    ]

    # Se já foi solicitada confirmação e o usuário confirma
    confirmation_asked = state_machine.get_state_data("confirmation_asked", False)
    if confirmation_asked and any(word in lower_input for word in confirmation_words):
        logger.info("[Transitions] Usuário confirmou após solicitação")
        state_machine.set_state_data("user_confirmed", True)

        # Se a data e horário estão preenchidos, podemos finalizar
        if state_machine.is_filled("data") and state_machine.is_filled("horario"):
            state_machine.set_state_data("agendamento_confirmado", True)

            # Processar agendamento imediatamente para evitar nova solicitação
            confirmation_msg = handle_agendamento_confirmado(state_machine)
            if confirmation_msg:
                return confirmation_msg

    # Verificar se o usuário está selecionando uma das alternativas sugeridas
    slot_selection_msg = process_slot_selection(state_machine, user_input)
    if slot_selection_msg:
        logger.info(f"[Transitions] Usuário selecionou slot alternativo: {slot_selection_msg}")
        return slot_selection_msg

    # 1. Verifica se há algum caso especial
    if handle_special_cases(state_machine, user_input):
        logger.info("[Transitions] Caso especial tratado.")
        return None

    # 2. Verifica se existem campos obrigatórios ausentes
    missing_fields = state_machine.get_state_data("missing_fields", [])
    if missing_fields:
        prompt_for_fields = (
            f"Ainda preciso das seguintes informações: {', '.join(missing_fields)}. "
            "Poderia me informar por favor?"
        )
        logger.info("[Transitions] Interrompendo fluxo para pedir campos faltantes.")
        state_machine.set_state_data("missing_fields", [])
        return prompt_for_fields

    # 3. NOVO: Verificar disponibilidade dos slots antes da validação contextual completa
    extracted_date = state_machine.get_state_data("data")
    extracted_time = state_machine.get_state_data("horario")

    # Se temos tanto data quanto horário extraídos, verificar disponibilidade
    if extracted_date and extracted_time and state_machine.get_current_step() >= 4:
        availability_message = handle_date_time_extraction(
            state_machine, extracted_date, extracted_time
        )
        if availability_message:
            logger.info(f"[Transitions] Verificação de disponibilidade: {availability_message}")
            return availability_message

    # 4. Validação contextual dos dados extraídos (mantido, mas executado após verificação de disponibilidade)
    validation_message = validate_conversation_state(state_machine)
    if validation_message:
        logger.info(f"[Transitions] Validação contextual solicitou correção: {validation_message}")
        return validation_message

    # 5. Se não estiver em período de cooldown, podemos avançar os steps
    if not state_machine.has_recent_confirmation():
        advance_step_if_ready(state_machine)

    # 6. Processa o agendamento confirmado, se os dados já estiverem completos
    confirmation_msg = handle_agendamento_confirmado(state_machine)
    if confirmation_msg:
        return confirmation_msg

    # 7. Se chegou aqui, não há confirmação nem campos ausentes
    return None