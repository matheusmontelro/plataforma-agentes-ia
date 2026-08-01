# Appointment Service Layer for Agents SDK
"""
Camada de serviço que abstrai a complexidade do sistema legado de agendamento
e fornece uma interface limpa e estruturada para os agents.
"""
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

# Import do sistema legado
from backend.prompt.db_integration.agendamento_logic import processar_json_do_llm

logger = logging.getLogger(__name__)


# Exceções customizadas
class AppointmentError(Exception):
    """Erro base para operações de agendamento"""
    pass


class SlotNotAvailableError(AppointmentError):
    """Erro quando o slot solicitado não está mais disponível"""
    pass


class IntegrationError(AppointmentError):
    """Erro de integração com sistemas externos (Clinicorp, Google Calendar)"""
    pass


class ValidationError(AppointmentError):
    """Erro de validação de dados"""
    pass


class AppointmentService:
    """
    Serviço de agendamento que encapsula a lógica complexa do sistema legado
    e fornece uma interface moderna e estruturada para os agents.
    """

    def __init__(self, db: Session, company_id: int):
        """
        Inicializa o serviço de agendamento.

        Args:
            db: Sessão do banco de dados SQLAlchemy
            company_id: ID da empresa
        """
        self.db = db
        self.company_id = company_id

    async def create_appointment(
        self,
        phone: str,
        nome: str,
        data: str,
        horario: str,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cria um novo agendamento usando o sistema legado.

        Args:
            phone: Telefone do cliente
            nome: Nome completo do cliente
            data: Data no formato DD/MM/YYYY
            horario: Horário no formato HH:MM
            api_key: Chave de API (opcional, usado para webhooks)

        Returns:
            Dict com resultado estruturado:
            {
                "success": bool,
                "message": str,
                "appointment_data": {...} se sucesso,
                "error_type": str se erro,
                "error_details": str se erro
            }
        """
        # Validação básica dos dados
        if not all([phone, nome, data, horario]):
            return {
                "success": False,
                "error_type": "validation_error",
                "error_details": "Dados incompletos",
                "message": "Por favor, forneça todos os dados necessários: nome, data e horário."
            }

        # Valida formato da data e horário
        try:
            datetime.strptime(f"{data} {horario}", "%d/%m/%Y %H:%M")
        except ValueError:
            return {
                "success": False,
                "error_type": "validation_error",
                "error_details": "Formato inválido de data/hora",
                "message": "Formato de data ou horário inválido. Use DD/MM/YYYY HH:MM"
            }

        # Prepara JSON no formato esperado pelo sistema legado
        llm_json = {
            "agendamento_confirmado": True,
            "data": data,
            "horario": horario,
            "nome": nome,
            "cancelar_agendamento": False
        }

        try:
            # Chama sistema legado
            logger.info(f"[AppointmentService] Criando agendamento - company_id={self.company_id}, phone={phone}, nome={nome}, data={data}, hora={horario}")

            result_msg = processar_json_do_llm(
                db=self.db,
                company_id=self.company_id,
                phone=phone,
                llm_json=llm_json,
                api_key=api_key
            )

            # Analisa resposta para determinar sucesso
            success = self._analyze_result_message(result_msg)

            logger.info(f"[AppointmentService] Mensagem retornada de processar_json_do_llm: {result_msg[:100]}...")

            if success:
                logger.info(f"[AppointmentService] Agendamento criado com sucesso")
                return {
                    "success": True,
                    "message": result_msg,
                    "appointment_data": {
                        "nome": nome,
                        "data": data,
                        "horario": horario,
                        "phone": phone,
                        "company_id": self.company_id
                    }
                }
            else:
                # Tenta identificar o tipo de erro
                error_type = self._identify_error_type(result_msg)
                logger.warning(f"[AppointmentService] Falha ao criar agendamento: {result_msg}")

                return {
                    "success": False,
                    "error_type": error_type,
                    "error_details": result_msg,
                    "message": result_msg
                }

        except Exception as e:
            logger.error(f"[AppointmentService] Erro inesperado ao criar agendamento: {e}")
            return {
                "success": False,
                "error_type": "system_error",
                "error_details": str(e),
                "message": "Ocorreu um erro ao processar seu agendamento. Por favor, tente novamente."
            }

    async def cancel_appointment(
        self,
        phone: str,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cancela um agendamento existente.

        Args:
            phone: Telefone do cliente
            api_key: Chave de API (opcional)

        Returns:
            Dict com resultado estruturado
        """
        # Prepara JSON para cancelamento
        llm_json = {
            "cancelar_agendamento": True,
            "agendamento_confirmado": False
        }

        try:
            logger.info(f"[AppointmentService] Cancelando agendamento - company_id={self.company_id}, phone={phone}")

            result_msg = processar_json_do_llm(
                db=self.db,
                company_id=self.company_id,
                phone=phone,
                llm_json=llm_json,
                api_key=api_key
            )

            # Analisa resposta
            success = "cancelado com sucesso" in result_msg.lower()

            if success:
                logger.info(f"[AppointmentService] Agendamento cancelado com sucesso")
                return {
                    "success": True,
                    "message": result_msg
                }
            else:
                logger.warning(f"[AppointmentService] Falha ao cancelar agendamento: {result_msg}")
                return {
                    "success": False,
                    "error_type": "cancellation_error",
                    "error_details": result_msg,
                    "message": result_msg
                }

        except Exception as e:
            logger.error(f"[AppointmentService] Erro ao cancelar agendamento: {e}")
            return {
                "success": False,
                "error_type": "system_error",
                "error_details": str(e),
                "message": "Ocorreu um erro ao cancelar seu agendamento."
            }

    async def reschedule_appointment(
        self,
        phone: str,
        nova_data: str,
        novo_horario: str,
        nome: str,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Reagenda um agendamento existente.
        Internamente, cancela o antigo e cria um novo.

        Args:
            phone: Telefone do cliente
            nova_data: Nova data (DD/MM/YYYY)
            novo_horario: Novo horário (HH:MM)
            nome: Nome do cliente
            api_key: Chave de API (opcional)

        Returns:
            Dict com resultado estruturado
        """
        logger.info(f"[AppointmentService] Iniciando reagendamento - phone={phone}")

        # Primeiro cancela o agendamento existente
        cancel_result = await self.cancel_appointment(phone, api_key)

        if not cancel_result.get("success"):
            # Se não tem agendamento para cancelar, tenta criar direto
            if "não encontrei" in cancel_result.get("message", "").lower():
                logger.info("[AppointmentService] Nenhum agendamento anterior, criando novo")
            else:
                return cancel_result

        # Cria novo agendamento
        create_result = await self.create_appointment(
            phone=phone,
            nome=nome,
            data=nova_data,
            horario=novo_horario,
            api_key=api_key
        )

        if create_result.get("success"):
            create_result["message"] = f"Reagendamento realizado com sucesso! {create_result['message']}"

        return create_result

    def _analyze_result_message(self, message: str) -> bool:
        """
        Analisa a mensagem de retorno para determinar se foi sucesso.

        Args:
            message: Mensagem retornada pelo sistema legado

        Returns:
            True se sucesso, False caso contrário
        """
        if not message:
            return False

        message_lower = message.lower()

        # Indicadores de sucesso
        success_indicators = [
            "agendada com sucesso",
            "confirmado com sucesso",
            "segue abaixo as informações",
            "protocolo",
            "data e horário"
        ]

        # Indicadores de erro
        error_indicators = [
            "erro",
            "falha",
            "não foi possível",
            "problema",
            "tente novamente",
            "não encontr"
        ]

        # Verifica indicadores de sucesso
        if any(indicator in message_lower for indicator in success_indicators):
            return True

        # Verifica indicadores de erro
        if any(indicator in message_lower for indicator in error_indicators):
            return False

        # Se tem informações de agendamento, provavelmente é sucesso
        if "📍" in message or "🗓" in message or "🔢" in message:
            return True

        return False

    def _identify_error_type(self, message: str) -> str:
        """
        Identifica o tipo de erro baseado na mensagem.

        Args:
            message: Mensagem de erro

        Returns:
            Tipo do erro
        """
        message_lower = message.lower()

        if "não encontr" in message_lower:
            return "not_found"
        elif "horário" in message_lower and ("indisponível" in message_lower or "não está" in message_lower):
            return "slot_unavailable"
        elif "sincroniz" in message_lower or "clinicorp" in message_lower or "google" in message_lower:
            return "integration_error"
        elif "validação" in message_lower or "formato" in message_lower:
            return "validation_error"
        else:
            return "unknown_error"