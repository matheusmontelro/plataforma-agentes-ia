# Main agent handler using the modular Agents SDK structure.

import logging
from typing import Dict, Any, List, Optional
import asyncio
from datetime import datetime
import pytz
from sqlalchemy.orm import Session

# OpenAI Agents SDK
from agents import Agent, Runner, function_tool, handoff, ModelSettings, RunContextWrapper

# Import configuration
from .config import CompanyContext, configure_agents_sdk, AgentsConfig

# Import agents
from .agents import CompanyAgentSystem

# Import utilities
from .utils import (
    ConversationManager,
    analyze_slot_request_with_llm,
    filter_slots_by_request,
    diversify_slot_selection,
    get_company_timezone
)
from .utils.state_triggers import StateTriggerHandler
from .utils.terminal_response import TerminalResponseHandler
from .utils.memory_integration import AgentsSDKMemoryIntegration

# Import external dependencies
from ..db_integration.agent_config import get_agent_config_dict
from ..scheduling.scheduling_service import SchedulingService
from ..memory.memory_manager import get_chat_history
from ..llm.states.customer_context import get_customer_context
from backend.services.ai_provider_service import get_company_openai_api_key

# Timezone
SP_TZ = pytz.timezone('America/Sao_Paulo')

# Configuration
logger = logging.getLogger(__name__)

def create_scheduling_service_with_fix(db: Session, company_id: int):
    """Cria um SchedulingService e aplica a correção para filtrar slots passados."""
    scheduling = SchedulingService(db, company_id)

    try:
        from ..scheduling.scheduling_service_fix import create_fixed_get_next_available_slots
        scheduling.get_next_available_slots = create_fixed_get_next_available_slots(scheduling)
        logger.info(f"[SchedulingService] Correção aplicada para company_id={company_id}")
    except ImportError:
        logger.warning(f"[SchedulingService] Correção não disponível para company_id={company_id}")

    return scheduling


def handle_user_input(
    db,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = "",
    api_key: Optional[str] = None
) -> str:
    """
    Função principal para processar entrada do usuário usando Agents SDK.
    Versão modularizada e otimizada para redução de custos.

    Args:
        db: Database session
        company_id: ID da empresa
        contact_phone: Telefone do contato
        user_input: Mensagem do usuário
        msg_category: Categoria da mensagem
        funnel_stage: Estágio do funil
        funnel_status: Status do funil
        api_key: API key para webhooks (opcional)

    Returns:
        str: Resposta do agent
    """
    try:
        logger.info(f"[AgentsSDK] Processando entrada para company_id={company_id}")

        # 1. Resolve a credencial BYOK e cria uma configuração isolada por run.
        company_openai_api_key = get_company_openai_api_key(db, company_id)
        run_config = configure_agents_sdk(
            AgentsConfig(
                api_key=company_openai_api_key,
                enable_tracing=False,
                verbose_logging=False,
            )
        )

        # 2. Carrega configuração da empresa
        company_config = get_agent_config_dict(db, company_id)
        if not company_config:
            raise ValueError(f"Configuração não encontrada para company_id={company_id}")

        # 3. Inicializa integração de memória
        memory_integration = AgentsSDKMemoryIntegration(company_id, contact_phone)

        # 4. Carrega histórico de conversação
        chat_history = memory_integration.load_chat_history()

        # 5. Extrai preferências do cliente do histórico
        customer_preferences = memory_integration.extract_customer_preferences()
        logger.info(f"[AgentsSDK] Preferências extraídas: {customer_preferences}")

        # 6. Cria e configura serviço de agendamento
        scheduling_service = create_scheduling_service_with_fix(db, company_id)

        # 7. Carrega contexto do cliente
        customer_context = get_customer_context(db, contact_phone, company_id)

        # 8. Obtém o timezone da empresa
        company_timezone = get_company_timezone(db, company_id)

        # 9. Analisa solicitação de slots
        slot_request = analyze_slot_request_with_llm(user_input)

        # 10. Carrega e filtra slots disponíveis
        all_slots = scheduling_service.get_next_available_slots()
        if slot_request.get("has_request"):
            filtered_slots = filter_slots_by_request(all_slots, slot_request)
        else:
            filtered_slots = diversify_slot_selection(all_slots, limit=10, timezone=company_timezone)

        # 11. Cria contexto completo
        context = CompanyContext(
            db=db,
            company_id=company_id,
            contact_phone=contact_phone,
            company_config=company_config,
            scheduling_service=scheduling_service,
            customer_context=customer_context,
            available_slots=filtered_slots,
            chat_history=chat_history,
            msg_category=msg_category,
            funnel_stage=funnel_stage,
            funnel_status=funnel_status,
            api_key=api_key  # Passa api_key para o contexto
        )

        # 12. Cria sistema de agents com contexto
        agent_system = CompanyAgentSystem(context)

        # 13. Gerencia conversação usando RunResults
        # Recupera resultado anterior se houver
        previous_result = ConversationManager.get_previous_result(company_id, contact_phone)
        last_agent = ConversationManager.get_last_agent(company_id, contact_phone)

        # Se há um agent anterior e é diferente do main, pode usar ele
        if last_agent and last_agent.name != "main":
            logger.info(f"[AgentsSDK] Continuando com agent anterior: {last_agent.name}")
            current_agent = last_agent
        else:
            current_agent = agent_system.agents["main"]

        # Constrói input usando RunResult anterior ou histórico inicial
        messages = ConversationManager.build_conversation_input(
            previous_result=previous_result,
            user_input=user_input,
            max_context_length=15  # Limita contexto para economizar tokens
        )

        logger.info(f"[AgentsSDK] Executando com {len(messages)} mensagens no contexto")

        # 14. Executa com contexto e histórico
        from agents import Runner
        result = asyncio.run(
            Runner.run(
                current_agent,
                messages,
                context=context,  # Passa o contexto para o Runner
                run_config=run_config,
            )
        )

        # 14.1 Processa triggers pós-execução
        # Isso é onde a mágica acontece - triggers automáticos baseados no estado
        logger.info("[AgentsSDK] Iniciando processamento de triggers automáticos")

        try:
            # Cria wrapper mock temporariamente para evitar problemas
            class MockWrapper:
                def __init__(self, context):
                    self.context = context

            additional_output = asyncio.run(
                StateTriggerHandler.handle_post_message_processing(
                    wrapper=MockWrapper(context),
                    user_message=user_input,
                    agent_response=result.final_output if result else "",
                    openai_api_key=company_openai_api_key,
                )
            )
            logger.info(f"[AgentsSDK] Triggers processados, output adicional: {len(additional_output) if additional_output else 0} chars")
        except Exception as exc:
            logger.error(
                "[AgentsSDK] Erro nos triggers automáticos (%s)",
                type(exc).__name__,
            )
            additional_output = None

        # Se houve output adicional (ex: agendamento automático), append na resposta
        if additional_output:
            final_response = result.final_output + additional_output
            logger.info("[AgentsSDK] Triggers automáticos executados")
        else:
            final_response = result.final_output

        # 11. Processa e salva resultado
        if result:
            # Salva resultado para próxima interação
            ConversationManager.save_result(company_id, contact_phone, result)

            # Salva último agent usado
            if result.last_agent:
                ConversationManager.save_last_agent(company_id, contact_phone, result.last_agent)
                logger.info(f"[AgentsSDK] Último agent: {result.last_agent.name}")

            # 12. [REMOVIDO] Não salva mais mensagens - já é feito em outro lugar

            # Log de informações úteis
            if result.new_items:
                logger.info(f"[AgentsSDK] {len(result.new_items)} novos itens gerados")

                # Analisa tipos de itens gerados
                for item in result.new_items:
                    item_type = type(item).__name__
                    logger.info(f"[AgentsSDK] Item tipo: {item_type}")

                    # Log detalhado do item
                    if hasattr(item, 'tool_name'):
                        logger.info(f"[AgentsSDK] Tool: {getattr(item, 'tool_name', 'N/A')}")
                    if hasattr(item, 'output'):
                        logger.info(f"[AgentsSDK] Output preview: {str(item.output)[:100]}...")
                        if isinstance(item.output, str) and "__TERMINAL_RESPONSE__" in item.output:
                            logger.info(f"[AgentsSDK] MARCADOR TERMINAL ENCONTRADO NO OUTPUT")
                    if hasattr(item, 'result'):
                        logger.info(f"[AgentsSDK] Result preview: {str(item.result)[:100]}...")
                        if isinstance(item.result, str) and "__TERMINAL_RESPONSE__" in item.result:
                            logger.info(f"[AgentsSDK] MARCADOR TERMINAL ENCONTRADO NO RESULT")

                    # Se houve handoff, log especial
                    if "HandoffOutputItem" in item_type:
                        logger.info(f"[AgentsSDK] Handoff realizado")

            # Verifica se alguma tool retornou terminal response
            terminal_response_found = None
            if result.new_items:
                for item in result.new_items:
                    # Verifica se é um ToolOutputItem com resultado terminal
                    if hasattr(item, 'output') and isinstance(item.output, str):
                        if TerminalResponseHandler.is_terminal_response(item.output):
                            terminal_response_found = TerminalResponseHandler.extract_terminal_message(item.output)
                            logger.info(f"[AgentsSDK] Terminal response detectado de ferramenta (output)")
                            break
                    elif hasattr(item, 'result') and isinstance(item.result, str):
                        if TerminalResponseHandler.is_terminal_response(item.result):
                            terminal_response_found = TerminalResponseHandler.extract_terminal_message(item.result)
                            logger.info(f"[AgentsSDK] Terminal response detectado de ferramenta (result)")
                            break

            # Se encontrou terminal response, usa ele ao invés da resposta do LLM
            if terminal_response_found:
                logger.info(f"[AgentsSDK] Usando terminal response ao invés da resposta do LLM")
                final_output = terminal_response_found
            else:
                # Processa resposta terminal se existir
                processed_response = TerminalResponseHandler.process_agent_response(final_response)
                final_output = processed_response if processed_response else "Desculpe, não consegui processar sua mensagem."

            # 13. [REMOVIDO] Não salva mais resposta - já é feito em outro lugar

            # Retorna output final (incluindo triggers automáticos)
            return final_output

        # Fallback se não houver resultado
        return "Desculpe, não consegui processar sua mensagem."

    except Exception as exc:
        logger.error(
            "[AgentsSDK] Erro ao processar entrada (%s)",
            type(exc).__name__,
        )
        return "Desculpe, ocorreu um erro ao processar sua mensagem. Por favor, tente novamente."
