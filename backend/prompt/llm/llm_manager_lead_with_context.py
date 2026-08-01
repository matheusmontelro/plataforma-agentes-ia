# Implementação no llm_manager_lead.py com sistema de contexto universal

"""
OPÇÃO 1: MODIFICAÇÃO MÍNIMA (Adicionar no início de handle_user_input)
Adicione estas linhas logo após o logger.info inicial (linha ~743)
"""

def handle_user_input_modificado(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = ""
) -> str:
    """
    Versão modificada com detecção de contexto universal.
    """
    logger.info(f"[handle_user_input] Processando entrada: '{user_input}'")

    # ============ INÍCIO DA MODIFICAÇÃO ============
    # Detecção de Contexto Universal
    try:
        from .universal_context_learner import AdaptiveContextLearner

        # Carrega learner (com cache para performance)
        if not hasattr(handle_user_input_modificado, '_learner_cache'):
            handle_user_input_modificado._learner_cache = {}

        if company_id not in handle_user_input_modificado._learner_cache:
            handle_user_input_modificado._learner_cache[company_id] = AdaptiveContextLearner(company_id)

        learner = handle_user_input_modificado._learner_cache[company_id]

        # Carrega histórico atual
        from ..memory.memory_manager import get_chat_history
        current_messages = get_chat_history(company_id=company_id, contact_phone=contact_phone)

        # Obtém recomendações de contexto
        context_recommendations = learner.get_context_recommendations(current_messages, user_input)

        # Se detectou mudanças importantes de contexto
        if context_recommendations["detected_shifts"]:
            shift = context_recommendations["detected_shifts"][0]
            logger.info(f"[CONTEXTO] Detectada mudança: {shift['type']} (confiança: {shift['confidence']})")

            # Ajusta comportamento baseado no tipo de mudança
            if shift["type"] == "intervention" and context_recommendations["suggested_approach"] == "acknowledge_and_adapt":
                # Força etapa 7 se for confirmação
                state_machine = ConversationStateMachine(db_session=db, phone=contact_phone, company_id=company_id)
                if "confirmad" in user_input.lower() or "agendad" in user_input.lower():
                    state_machine.set_current_step(7)
                    logger.info("[CONTEXTO] Confirmação detectada, movendo para etapa 7")

            elif shift["type"] == "correction":
                # Marca que precisa corrigir informação
                state_machine = ConversationStateMachine(db_session=db, phone=contact_phone, company_id=company_id)
                state_machine.set_state_data("needs_correction", True)
                state_machine.set_state_data("correction_context", user_input)
                logger.info("[CONTEXTO] Correção detectada, marcando para ajuste")

            elif shift["type"] == "new_info":
                # Marca que há nova informação para processar
                logger.info("[CONTEXTO] Nova informação detectada, garantindo processamento")
                # O prompt será ajustado abaixo

            # Armazena recomendações para uso posterior
            _context_recommendations = context_recommendations
        else:
            _context_recommendations = None

    except Exception as e:
        logger.debug(f"Sistema de contexto não disponível: {e}")
        _context_recommendations = None

    # ============ FIM DA MODIFICAÇÃO INICIAL ============

    # ... continua com o código original ...

    # 1) Carrega (ou cria) ConversationState
    state_machine = ConversationStateMachine(db_session=db, phone=contact_phone, company_id=company_id)
    current_step = state_machine.get_current_step()
    logger.info(f"[handle_user_input] Step inicial: {current_step}")

    # ... resto do código original até criar o chain ...

    # ============ MODIFICAÇÃO NO PROMPT ============
    # Quando for invocar o chain (por volta da linha 936)

    # Adiciona contexto detectado ao input se necessário
    enhanced_input = user_input
    if _context_recommendations and _context_recommendations["detected_shifts"]:
        shift_info = _context_recommendations["detected_shifts"][0]
        approach = _context_recommendations["suggested_approach"]

        # Injeta instruções baseadas no contexto detectado
        context_instructions = f"\n\n[CONTEXTO DETECTADO: {shift_info['type']}]"

        if approach == "acknowledge_and_adapt":
            context_instructions += "\nReconheça a informação fornecida e adapte sua resposta."
        elif approach == "apologize_and_correct":
            context_instructions += "\nReconheça o erro e corrija a informação gentilmente."
        elif approach == "process_and_confirm":
            context_instructions += "\nProcesse a nova informação e confirme o entendimento."
        elif approach == "confirm_and_move_forward":
            context_instructions += "\nConfirme o que foi dito e prossiga sem repetir perguntas."

        # Adiciona exemplos bem-sucedidos se houver
        if _context_recommendations["similar_successful_patterns"]:
            context_instructions += "\n\n[Padrões de sucesso similares detectados - responda de forma similar]"

        # Adiciona o que evitar
        if _context_recommendations["avoid_responses"]:
            avoid_list = ", ".join(_context_recommendations["avoid_responses"])
            context_instructions += f"\n[EVITE: {avoid_list}]"

        enhanced_input = user_input + context_instructions

    # Invoca com input melhorado
    response = chain.invoke({
        "input": enhanced_input,
        "chat_history": memory.chat_memory.messages
    })
    chain_output = response.content

    # ============ PÓS-PROCESSAMENTO ============
    # Após obter a resposta (por volta da linha 941)

    # Valida se a resposta está adequada ao contexto
    if _context_recommendations and _context_recommendations["avoid_responses"]:
        response_lower = chain_output.lower()

        # Verifica se caiu em algum padrão a evitar
        needs_correction = False
        if "asking_again" in _context_recommendations["avoid_responses"]:
            if any(phrase in response_lower for phrase in ["qual seu nome", "como posso ajudar", "gostaria de agendar"]):
                needs_correction = True

        if needs_correction:
            # Gera resposta alternativa mais apropriada
            logger.warning("[CONTEXTO] Resposta inadequada detectada, ajustando...")

            # Resposta genérica segura baseada no tipo de contexto
            shift_type = _context_recommendations["detected_shifts"][0]["type"]
            safe_responses = {
                "intervention": "Perfeito! Entendi a informação. Há algo mais que precisa?",
                "confirmation": "Ótimo! Está tudo confirmado. Posso ajudar com mais alguma coisa?",
                "correction": "Ah sim, entendi! Desculpe pelo equívoco. Vou corrigir isso.",
                "new_info": "Entendi! Obrigado pela informação. Vou considerar isso."
            }
            chain_output = safe_responses.get(shift_type, chain_output)

    # ============ APRENDIZADO ============
    # No final da função, antes do return (por volta da linha 1046)

    # Sistema aprende com a interação
    if 'learner' in locals():
        try:
            # Prepara mensagens atualizadas
            updated_messages = current_messages + [
                HumanMessage(content=user_input),
                AIMessage(content=chain_output)
            ]

            # Aprende com a conversa
            learner.learn_from_any_conversation(updated_messages)

        except Exception as e:
            logger.debug(f"Erro no aprendizado: {e}")

    # ... resto do código original ...

    logger.info(f"[handle_user_input] Retornando resposta do LLM (step={current_step})")
    return chain_output


"""
OPÇÃO 2: IMPLEMENTAÇÃO COMO DECORATOR (Menos invasiva)
"""

from functools import wraps
from .universal_context_learner import AdaptiveContextLearner

def with_context_awareness(original_function):
    """
    Decorator que adiciona consciência de contexto a qualquer função de chat.
    """
    @wraps(original_function)
    def wrapper(db, company_id, contact_phone, user_input, **kwargs):
        # Análise de contexto PRÉ-processamento
        try:
            learner = AdaptiveContextLearner(company_id)
            from ..memory.memory_manager import get_chat_history

            messages = get_chat_history(company_id=company_id, contact_phone=contact_phone)
            recommendations = learner.get_context_recommendations(messages, user_input)

            # Adiciona recomendações aos kwargs
            kwargs['_context_recommendations'] = recommendations

            # Se detectou mudança crítica, adiciona flag
            if recommendations["detected_shifts"]:
                kwargs['_context_shift_detected'] = True
                logger.info(f"[DECORATOR] Contexto detectado: {recommendations['detected_shifts'][0]['type']}")

        except Exception as e:
            logger.debug(f"Análise de contexto falhou: {e}")

        # Chama função original
        response = original_function(db, company_id, contact_phone, user_input, **kwargs)

        # Aprendizado PÓS-processamento
        try:
            if 'learner' in locals():
                messages.extend([
                    HumanMessage(content=user_input),
                    AIMessage(content=response)
                ])
                learner.learn_from_any_conversation(messages)
        except:
            pass

        return response

    return wrapper


# USO DO DECORATOR:
# No arquivo que importa handle_user_input:
#
# from backend.prompt.llm.llm_manager_lead import handle_user_input
# from backend.prompt.llm.llm_manager_lead_with_context import with_context_awareness
#
# handle_user_input = with_context_awareness(handle_user_input)


"""
OPÇÃO 3: IMPLEMENTAÇÃO COMO MIDDLEWARE (Para toda a aplicação)
"""

class ContextAwarenessMiddleware:
    """
    Middleware que adiciona contexto a todas as interações de chat.
    """
    def __init__(self):
        self.learners = {}  # Cache por empresa

    def get_learner(self, company_id: int) -> AdaptiveContextLearner:
        if company_id not in self.learners:
            self.learners[company_id] = AdaptiveContextLearner(company_id)
        return self.learners[company_id]

    def pre_process(self, company_id: int, contact_phone: str, user_input: str) -> dict:
        """Analisa contexto antes do processamento."""
        try:
            learner = self.get_learner(company_id)
            from ..memory.memory_manager import get_chat_history

            messages = get_chat_history(company_id=company_id, contact_phone=contact_phone)
            recommendations = learner.get_context_recommendations(messages, user_input)

            return {
                "success": True,
                "recommendations": recommendations,
                "messages": messages
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def post_process(self, company_id: int, messages: list, user_input: str, ai_response: str):
        """Aprende após o processamento."""
        try:
            learner = self.get_learner(company_id)
            updated_messages = messages + [
                HumanMessage(content=user_input),
                AIMessage(content=ai_response)
            ]
            learner.learn_from_any_conversation(updated_messages)
        except:
            pass


# Instância global do middleware
context_middleware = ContextAwarenessMiddleware()


# EXEMPLO DE USO DO MIDDLEWARE:
# No ponto de entrada da API
#
# # Antes de processar
# context_data = context_middleware.pre_process(company_id, phone, user_input)
# if context_data["success"]:
#     # Usa recomendações no processamento
#     response = handle_user_input(db, company_id, phone, user_input,
#                                  _context_data=context_data)
# else:
#     response = handle_user_input(db, company_id, phone, user_input)
#
# # Depois de processar
# if context_data["success"]:
#     context_middleware.post_process(company_id, context_data["messages"],
#                                     user_input, response)