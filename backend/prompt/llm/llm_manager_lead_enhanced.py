# Versão melhorada do handle_user_input com sistema de aprendizado contextual

from .llm_manager_lead import *  # Importa tudo do original
from .context_learning_system import create_context_aware_enhancer

# Cache global para enhancers por empresa
_enhancer_cache = {}

def get_enhancer_for_company(company_id: int):
    """Obtém ou cria enhancer para a empresa."""
    if company_id not in _enhancer_cache:
        _enhancer_cache[company_id] = create_context_aware_enhancer(company_id)
    return _enhancer_cache[company_id]


def handle_user_input_enhanced(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = ""
) -> str:
    """
    Versão melhorada do handle_user_input que usa aprendizado contextual.
    """
    logger.info(f"[handle_user_input_enhanced] Processando com aprendizado contextual")

    # 1) Obtém enhancer para a empresa
    enhancer = get_enhancer_for_company(company_id)

    # 2) Carrega histórico de conversa
    from ..memory.memory_manager import get_chat_history
    chat_history = get_chat_history(contact_phone=contact_phone, company_id=company_id)

    # 3) Analisa contexto ANTES de criar o chain
    context_analysis = enhancer.learner.analyze_context_for_response(
        chat_history,
        user_input
    )

    logger.info(f"[handle_user_input_enhanced] Análise de contexto: {context_analysis['suggested_behavior']}")

    # 4) Se detectou confirmação manual, ajusta parâmetros
    if context_analysis["suggested_behavior"] == "acknowledge_confirmation":
        # Força estado para pós-agendamento
        state_machine = ConversationStateMachine(db_session=db, phone=contact_phone, company_id=company_id)
        state_machine.set_current_step(7)  # Etapa pós-agendamento
        logger.info("[handle_user_input_enhanced] Forçando etapa 7 devido a confirmação manual detectada")

    # 5) Cria chain normalmente
    chain_dict = create_llm_chain_with_memory(
        db=db,
        company_id=company_id,
        contact_phone=contact_phone,
        msg_category=msg_category,
        funnel_stage=funnel_stage,
        funnel_status=funnel_status
    )

    chain = chain_dict["chain"]
    memory = chain_dict["memory"]
    prompt_template = chain_dict["prompt_template"]

    # 6) Melhora o prompt com contexto aprendido
    original_prompt = prompt_template.format(
        input=user_input,
        chat_history=memory.chat_memory.messages
    )

    enhanced_prompt = enhancer.enhance_prompt_with_context(
        memory.chat_memory.messages,
        user_input,
        original_prompt
    )

    # 7) Invoca o LLM com prompt melhorado
    invoke_args = {
        "input": user_input,
        "chat_history": memory.chat_memory.messages
    }

    # Se temos prompt melhorado, injeta instruções adicionais
    if enhanced_prompt != original_prompt:
        # Adiciona contexto como mensagem do sistema
        invoke_args["input"] = f"{user_input}\n\n{context_analysis.get('context_instructions', '')}"

    response = chain.invoke(invoke_args)
    ai_response = response.content

    # 8) Pós-processa resposta se necessário
    ai_response = enhancer.post_process_response(ai_response, context_analysis)

    logger.info(f"[handle_user_input_enhanced] Resposta final: {ai_response[:100]}...")

    # 9) Continua com o fluxo normal do sistema original
    # (extração de JSON, state machine, etc...)
    llm_json = extract_json_from_llm_response(ai_response)

    # ... resto do código original de handle_user_input ...
    # (copiar a partir da linha 944 do original)

    # 10) No final, aprende com a conversa
    # Adicionar após o return final:
    try:
        # Atualiza histórico com nova mensagem
        updated_history = chat_history + [
            HumanMessage(content=user_input),
            AIMessage(content=ai_response)
        ]

        # Sistema aprende se a conversa foi produtiva
        enhancer.learn_from_conversation_end(updated_history, contact_phone)
    except Exception as e:
        logger.error(f"Erro ao aprender com conversa: {e}")

    return ai_response


# Função para migrar gradualmente
def should_use_enhanced_version(company_id: int) -> bool:
    """
    Determina se deve usar versão melhorada para uma empresa.
    Permite migração gradual.
    """
    # Pode começar com empresas específicas
    PILOT_COMPANIES = [2, 5, 10]  # IDs das empresas piloto
    return company_id in PILOT_COMPANIES


# Wrapper que decide qual versão usar
def handle_user_input_wrapper(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    **kwargs
) -> str:
    """
    Decide se usa versão original ou melhorada.
    """
    if should_use_enhanced_version(company_id):
        return handle_user_input_enhanced(
            db, company_id, contact_phone, user_input, **kwargs
        )
    else:
        # Usa versão original
        from .llm_manager_lead import handle_user_input
        return handle_user_input(
            db, company_id, contact_phone, user_input, **kwargs
        )