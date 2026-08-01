# Validation Guards and Safety Rails for State Management
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import pytz
from agents import RunContextWrapper
from ..config.company_context import CompanyContext

logger = logging.getLogger(__name__)


class StateValidationGuards:
    """
    Implementa validações e guard rails para o sistema de estado.
    Baseado na lógica robusta do state_machine.py original.
    """

    @staticmethod
    async def validate_state_transition(
        wrapper: RunContextWrapper[CompanyContext],
        target_step: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Valida se uma transição de estado é permitida.

        Args:
            wrapper: Context wrapper
            target_step: Step de destino

        Returns:
            Tuple[bool, Optional[str]]: (pode_transicionar, erro_se_houver)
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()
        current_step = state_manager.state.current_step

        # Se já está no target step, permite
        if current_step == target_step:
            return True, None

        # Validações específicas por step
        if target_step == 0:
            # Sempre pode voltar ao início
            return True, None

        elif target_step == 1:
            # Pode ir para step 1 se tiver dados básicos ou for início
            return True, None

        elif target_step == 2:
            # Precisa ter tratamento identificado
            if not state_manager.is_field_filled("tratamento"):
                return False, "Tratamento não foi identificado ainda"
            return True, None

        elif target_step == 3:
            # Precisa ter tratamento e tipo de cliente
            missing = []
            if not state_manager.is_field_filled("tratamento"):
                missing.append("tratamento")
            if not state_manager.is_field_filled("cliente"):
                missing.append("tipo de cliente")

            if missing:
                return False, f"Dados faltando: {', '.join(missing)}"
            return True, None

        elif target_step == 4:
            # Pode ofertar agendamento após exploração
            if current_step < 3:
                return False, "Precisa completar exploração antes de agendar"
            return True, None

        elif target_step == 5:
            # Precisa ter horário escolhido
            missing = []
            if not state_manager.is_field_filled("data"):
                missing.append("data")
            if not state_manager.is_field_filled("horario"):
                missing.append("horário")

            if missing:
                return False, f"Dados de agendamento faltando: {', '.join(missing)}"
            return True, None

        elif target_step == 6:
            # Precisa ter todos os dados obrigatórios
            missing = state_manager._get_missing_required_fields()
            if missing:
                return False, f"Campos obrigatórios faltando: {', '.join(missing)}"

            # Verifica cooldown de confirmação
            if await state_manager._has_recent_confirmation():
                remaining = state_manager.get_confirmation_cooldown_remaining()
                return False, f"Período de cooldown ativo. Aguarde {remaining} segundos"

            return True, None

        elif target_step == 7:
            # Step pós-agendamento - precisa ter confirmado
            if not state_manager.get_state_data("agendamento_confirmado"):
                return False, "Agendamento não foi confirmado ainda"
            return True, None

        elif target_step == 8:
            # Cancelamento - sempre permitido
            return True, None

        else:
            return False, f"Step inválido: {target_step}"

    @staticmethod
    async def validate_scheduling_data(
        wrapper: RunContextWrapper[CompanyContext]
    ) -> Tuple[bool, List[str]]:
        """
        Valida dados de agendamento antes de confirmar.

        Returns:
            Tuple[bool, List[str]]: (dados_válidos, lista_de_erros)
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()
        errors = []

        # Verifica campos obrigatórios
        nome = state_manager.get_state_data("nome")
        data = state_manager.get_state_data("data")
        horario = state_manager.get_state_data("horario")

        if not nome or len(nome.strip()) < 2:
            errors.append("Nome completo é obrigatório")

        if not data:
            errors.append("Data é obrigatória")
        elif not StateValidationGuards._validate_date_format(data):
            errors.append("Formato de data inválido (use DD/MM/YYYY)")

        if not horario:
            errors.append("Horário é obrigatório")
        elif not StateValidationGuards._validate_time_format(horario):
            errors.append("Formato de horário inválido (use HH:MM)")

        # Valida se o slot ainda está disponível
        if data and horario:
            data_hora = f"{data} {horario}"
            if context.available_slots and data_hora not in context.available_slots:
                errors.append("Horário não está mais disponível")

        # Valida se a data não é no passado
        if data and StateValidationGuards._validate_date_format(data):
            if StateValidationGuards._is_date_in_past(data):
                errors.append("Não é possível agendar para datas no passado")

        return len(errors) == 0, errors

    @staticmethod
    def _validate_date_format(date_str: str) -> bool:
        """Valida formato DD/MM/YYYY."""
        import re
        if not re.match(r'^\d{2}/\d{2}/\d{4}$', date_str):
            return False

        try:
            datetime.strptime(date_str, "%d/%m/%Y")
            return True
        except ValueError:
            return False

    @staticmethod
    def _validate_time_format(time_str: str) -> bool:
        """Valida formato HH:MM."""
        import re
        if not re.match(r'^\d{2}:\d{2}$', time_str):
            return False

        try:
            datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_date_in_past(date_str: str) -> bool:
        """Verifica se a data está no passado."""
        try:
            date_obj = datetime.strptime(date_str, "%d/%m/%Y").date()
            today = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
            return date_obj < today
        except ValueError:
            return True  # Se não conseguir parsear, considera inválido

    @staticmethod
    async def check_rate_limiting(
        wrapper: RunContextWrapper[CompanyContext]
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifica rate limiting para evitar spam de agendamentos.

        Returns:
            Tuple[bool, Optional[str]]: (pode_prosseguir, mensagem_erro)
        """
        context = wrapper.context
        state_manager = await context.get_state_manager()

        # Verifica cooldown de confirmação
        if await state_manager._has_recent_confirmation():
            remaining = state_manager.get_confirmation_cooldown_remaining()
            return False, f"Aguarde {remaining} segundos antes de fazer um novo agendamento"

        return True, None

    @staticmethod
    async def sanitize_input_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitiza dados de entrada para prevenir problemas.

        Args:
            data: Dados para sanitizar

        Returns:
            Dict[str, Any]: Dados sanitizados
        """
        sanitized = {}

        for key, value in data.items():
            if value is None:
                continue

            if isinstance(value, str):
                # Remove caracteres especiais e limita tamanho
                clean_value = value.strip()

                if key == "nome":
                    # Para nomes, mantém apenas letras, espaços e acentos
                    import re
                    clean_value = re.sub(r'[^a-zA-ZÀ-ÿ\s]', '', clean_value)
                    clean_value = ' '.join(clean_value.split())  # Remove espaços duplos
                    clean_value = clean_value[:100]  # Limita tamanho

                elif key in ["data", "horario"]:
                    # Para data/horário, mantém apenas números, : e /
                    import re
                    clean_value = re.sub(r'[^\d:/]', '', clean_value)

                elif key == "tratamento":
                    # Para tratamento, limita opções válidas
                    valid_treatments = [
                        "dor", "limpeza", "clareamento", "ortodontia",
                        "implante", "restauração", "avaliação", "consulta"
                    ]
                    clean_value = clean_value.lower()
                    if clean_value not in valid_treatments:
                        clean_value = "avaliação"  # Default

                elif key == "cliente":
                    # Para tipo de cliente, limita opções
                    clean_value = clean_value.lower()
                    if clean_value not in ["novo", "retorno"]:
                        clean_value = "novo"  # Default

                sanitized[key] = clean_value
            else:
                sanitized[key] = value

        return sanitized


class SecurityGuards:
    """
    Guard rails de segurança para o sistema.
    """

    @staticmethod
    async def validate_company_access(
        wrapper: RunContextWrapper[CompanyContext],
        requested_action: str
    ) -> bool:
        """
        Valida se a ação pode ser executada para esta empresa.

        Args:
            wrapper: Context wrapper
            requested_action: Ação solicitada

        Returns:
            bool: True se a ação é permitida
        """
        context = wrapper.context

        # Verifica se a empresa está ativa
        # Isso poderia ser expandido para verificar no banco
        if context.company_id <= 0:
            logger.warning(f"[SecurityGuards] Company ID inválido: {context.company_id}")
            return False

        # Verifica ações sensíveis
        sensitive_actions = ["agendar_consulta", "cancelar_agendamento"]
        if requested_action in sensitive_actions:
            # Adiciona validações extras para ações sensíveis
            if not context.contact_phone or len(context.contact_phone) < 10:
                logger.warning(f"[SecurityGuards] Telefone inválido para {requested_action}")
                return False

        return True

    @staticmethod
    def log_security_event(
        company_id: int,
        contact_phone: str,
        event_type: str,
        details: str
    ) -> None:
        """
        Log de eventos de segurança.

        Args:
            company_id: ID da empresa
            contact_phone: Telefone do contato
            event_type: Tipo do evento
            details: Detalhes do evento
        """
        logger.warning(
            f"[SECURITY] {event_type} - Company: {company_id}, "
            f"Phone: {contact_phone[-4:] if contact_phone else 'N/A'}, "
            f"Details: {details}"
        )


class PerformanceGuards:
    """
    Guard rails de performance para otimização.
    """

    @staticmethod
    def check_context_size(context: CompanyContext) -> bool:
        """
        Verifica se o contexto não está muito grande.

        Returns:
            bool: True se o tamanho está ok
        """
        # Verifica tamanho do histórico
        if context.chat_history and len(context.chat_history) > 50:
            logger.info("[PerformanceGuards] Histórico longo detectado")
            return False

        # Verifica número de slots
        if context.available_slots and len(context.available_slots) > 20:
            logger.info("[PerformanceGuards] Muitos slots disponíveis")
            # Não é erro, mas pode ser otimizado

        return True

    @staticmethod
    def optimize_context(context: CompanyContext) -> CompanyContext:
        """
        Otimiza o contexto para reduzir uso de tokens.

        Returns:
            CompanyContext: Contexto otimizado
        """
        # Limita histórico de chat
        if context.chat_history and len(context.chat_history) > 30:
            context.chat_history = context.chat_history[-30:]
            logger.info("[PerformanceGuards] Histórico truncado")

        # Limita slots disponíveis
        if context.available_slots and len(context.available_slots) > 15:
            context.available_slots = context.available_slots[:15]
            logger.info("[PerformanceGuards] Slots limitados")

        return context