# Customer Tools for Agents SDK
import logging
from agents import function_tool, RunContextWrapper
from ..config import CompanyContext
from ..services import AppointmentService
from ..utils.terminal_response import TerminalResponseHandler
from typing import Optional
import re

logger = logging.getLogger(__name__)

@function_tool
async def obter_informacoes_cliente(wrapper: RunContextWrapper[CompanyContext]) -> str:
    """
    Obtém informações relevantes do cliente do contexto.
    Útil para personalizar a conversa.
    """
    context = wrapper.context

    if not context.customer_context:
        return "Cliente novo, sem histórico anterior."

    info = []

    # Verifica se é cliente novo
    if context.customer_context.get("is_new_customer"):
        info.append("• Cliente novo (primeira vez na empresa)")
    else:
        info.append("• Cliente com histórico na empresa")

    # Agendamentos
    total_appointments = context.customer_context.get("total_appointments", 0)
    if total_appointments > 0:
        info.append(f"• Total de agendamentos anteriores: {total_appointments}")

    # Comparecimentos
    total_attendance = context.customer_context.get("total_attendance", 0)
    if total_attendance > 0:
        info.append(f"• Total de comparecimentos: {total_attendance}")

    return "\n".join(info) if info else "Sem informações específicas do cliente."


@function_tool
async def agendar_consulta(
    wrapper: RunContextWrapper[CompanyContext],
    data_hora: str,
    nome_completo: str
) -> str:
    """
    Agenda uma consulta para o cliente usando o sistema integrado.

    Args:
        data_hora: Data e hora no formato DD/MM/YYYY HH:MM
        nome_completo: Nome completo do cliente

    Returns:
        str: Mensagem de confirmação oficial com protocolo, endereço, dentista e formatação padrão.

    NOTA: Esta é uma TERMINAL TOOL - após executar com sucesso, encerra a conversa com a mensagem retornada.
    """
    context = wrapper.context

    # 🚨 VALIDAÇÃO CRÍTICA: Verifica se nome é válido
    if not nome_completo or len(nome_completo.strip()) < 2:
        return "❌ Nome completo é obrigatório para agendar a consulta."

    # 🚨 VALIDAÇÃO CRÍTICA: Verifica se nome não é um horário
    if re.match(r'^\d{2}:\d{2}$', nome_completo.strip()):
        return "❌ Erro: foi fornecido um horário onde deveria ser o nome. Por favor, informe seu nome completo."

    # Extrai data e hora separadamente
    match = re.match(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', data_hora)
    if not match:
        return "❌ Formato de data/hora inválido. Use DD/MM/YYYY HH:MM"

    data, horario = match.groups()

    # Verifica se o horário está disponível nos slots
    if context.available_slots:
        # Extrai strings dos slots (suporte para dict ou string)
        available_slot_strings = []
        for slot in context.available_slots:
            if isinstance(slot, dict):
                available_slot_strings.append(slot["slot"])
            else:
                available_slot_strings.append(slot)

        if data_hora not in available_slot_strings:
            return "❌ Este horário não está mais disponível. Por favor, escolha outro horário da lista."

    # Usa o serviço de agendamento
    appointment_service = AppointmentService(
        db=context.db,
        company_id=context.company_id
    )

    # Obtém api_key do contexto se disponível
    api_key = getattr(context, 'api_key', None)

    logger.info(f"[customer_tools] Criando agendamento via AppointmentService")

    try:
        result = await appointment_service.create_appointment(
            phone=context.contact_phone,
            nome=nome_completo,
            data=data,
            horario=horario,
            api_key=api_key
        )

        if result["success"]:
            # 🎯 IMPORTANTE: A mensagem já vem formatada com protocolo, endereço, dentista, etc
            # do _generate_confirmation_message() em agendamento_logic.py
            logger.info(f"[customer_tools] Retornando mensagem padrão como TERMINAL RESPONSE: {result['message'][:100]}...")

            # Atualiza estado para pós-agendamento
            try:
                state_manager = await context.get_state_manager()
                await state_manager.set_state_data("agendamento_confirmado", True)
                await state_manager.transition_to_step(7)  # Step de pós-agendamento
                logger.info(f"[customer_tools] Estado atualizado para step 7 (pós-agendamento)")
            except Exception as e:
                logger.error(f"[customer_tools] Erro ao atualizar estado: {e}")

            # Retorna como resposta terminal para evitar que o LLM processe/reformate
            return TerminalResponseHandler.create_terminal_response(result["message"])
        else:
            # Trata erros específicos
            error_type = result.get("error_type", "unknown")

            if error_type == "slot_unavailable":
                return "❌ Este horário não está mais disponível. Por favor, escolha outro horário."
            elif error_type == "validation_error":
                return f"❌ Dados inválidos: {result.get('error_details', 'Verifique as informações')}"
            else:
                return f"❌ {result.get('message', 'Erro ao processar agendamento')}"

    except Exception as e:
        logger.error(f"[customer_tools] Erro ao agendar consulta: {e}")
        return "❌ Ocorreu um erro ao processar seu agendamento. Por favor, tente novamente."


@function_tool
async def cancelar_agendamento(
    wrapper: RunContextWrapper[CompanyContext]
) -> str:
    """
    Cancela um agendamento existente do cliente.
    """
    context = wrapper.context

    # Usa o serviço de agendamento
    appointment_service = AppointmentService(
        db=context.db,
        company_id=context.company_id
    )

    # Obtém api_key do contexto se disponível
    api_key = getattr(context, 'api_key', None)

    logger.info(f"[customer_tools] Cancelando agendamento via AppointmentService")

    try:
        result = await appointment_service.cancel_appointment(
            phone=context.contact_phone,
            api_key=api_key
        )

        if result["success"]:
            # Após cancelamento bem-sucedido, volta para step 4 para oferecer novo agendamento
            try:
                state_manager = await context.get_state_manager()
                await state_manager.transition_to_step(4)  # Volta para step de agendamento
                logger.info(f"[customer_tools] Estado atualizado para step 4 após cancelamento")
            except Exception as e:
                logger.error(f"[customer_tools] Erro ao atualizar estado após cancelamento: {e}")

            return result["message"]
        else:
            return f"❌ {result.get('message', 'Não foi possível cancelar o agendamento')}"

    except Exception as e:
        logger.error(f"[customer_tools] Erro ao cancelar agendamento: {e}")
        return "❌ Ocorreu um erro ao cancelar seu agendamento. Por favor, tente novamente."


@function_tool
async def reagendar_consulta(
    wrapper: RunContextWrapper[CompanyContext],
    nova_data_hora: str,
    nome_completo: str
) -> str:
    """
    Reagenda uma consulta existente para nova data/hora.

    Args:
        nova_data_hora: Nova data e hora no formato DD/MM/YYYY HH:MM
        nome_completo: Nome completo do cliente
    """
    context = wrapper.context

    # Extrai data e hora separadamente
    match = re.match(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', nova_data_hora)
    if not match:
        return "❌ Formato de data/hora inválido. Use DD/MM/YYYY HH:MM"

    nova_data, novo_horario = match.groups()

    # Verifica disponibilidade
    if context.available_slots:
        # Extrai strings dos slots (suporte para dict ou string)
        available_slot_strings = []
        for slot in context.available_slots:
            if isinstance(slot, dict):
                available_slot_strings.append(slot["slot"])
            else:
                available_slot_strings.append(slot)

        if nova_data_hora not in available_slot_strings:
            return "❌ Este horário não está mais disponível. Por favor, escolha outro horário."

    # Usa o serviço de agendamento
    appointment_service = AppointmentService(
        db=context.db,
        company_id=context.company_id
    )

    api_key = getattr(context, 'api_key', None)

    logger.info(f"[customer_tools] Reagendando consulta via AppointmentService")

    try:
        result = await appointment_service.reschedule_appointment(
            phone=context.contact_phone,
            nova_data=nova_data,
            novo_horario=novo_horario,
            nome=nome_completo,
            api_key=api_key
        )

        if result["success"]:
            # Após reagendamento bem-sucedido, vai para step 7 (pós-agendamento)
            try:
                state_manager = await context.get_state_manager()
                await state_manager.transition_to_step(7)  # Step de pós-agendamento
                logger.info(f"[customer_tools] Estado atualizado para step 7 após reagendamento")
            except Exception as e:
                logger.error(f"[customer_tools] Erro ao atualizar estado após reagendamento: {e}")

            return result["message"]
        else:
            return f"❌ {result.get('message', 'Não foi possível reagendar')}"

    except Exception as e:
        logger.error(f"[customer_tools] Erro ao reagendar consulta: {e}")
        return "❌ Ocorreu um erro ao reagendar sua consulta."