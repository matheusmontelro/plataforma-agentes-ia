import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.prompt.db_integration.agendamento_logic import confirm_appointment
from backend.prompt.llm.states.state_machine import ConversationStateMachine

logger = logging.getLogger(__name__)

class ReagendamentoFlow:
    """
    Gerencia o fluxo de reagendamento de consultas.
    Mantém dados do cliente e permite novo agendamento.
    """

    def __init__(self, state_machine: ConversationStateMachine):
        self.state_machine = state_machine
        self.db = state_machine.db_session
        self.company_id = state_machine.company_id
        self.phone = state_machine.phone

    def prepare_for_reschedule(self) -> Dict[str, Any]:
        """
        Prepara o state machine para reagendamento.
        Mantém dados do cliente, limpa dados de agendamento.
        """
        try:
            logger.info(
                f"[ReagendamentoFlow] Iniciando preparação para reagendamento: "
                f"company_id={self.company_id}, phone={self.phone}"
            )

            # Mantém dados básicos do cliente
            nome = self.state_machine.get_state_data("nome")
            tratamento = self.state_machine.get_state_data("tratamento")
            cliente = self.state_machine.get_state_data("cliente")

            if not all([nome, tratamento, cliente]):
                logger.warning("[ReagendamentoFlow] Dados básicos do cliente incompletos")
                return {
                    "success": False,
                    "message": "Dados do cliente insuficientes para reagendamento",
                    "data": {
                        "company_id": self.company_id,
                        "phone": self.phone
                    }
                }

            # Prepara state machine para reagendamento
            self.state_machine.prepare_for_reschedule()

            return {
                "success": True,
                "message": "State preparado para reagendamento",
                "data": {
                    "company_id": self.company_id,
                    "phone": self.phone,
                    "nome": nome,
                    "tratamento": tratamento,
                    "cliente": cliente
                }
            }

        except Exception as e:
            logger.error(f"[ReagendamentoFlow] Erro ao preparar reagendamento: {e}")
            return {
                "success": False,
                "message": "Erro interno ao preparar reagendamento",
                "error": str(e),
                "data": {
                    "company_id": self.company_id,
                    "phone": self.phone
                }
            }

    def process_reschedule(self, data: str, horario: str) -> Dict[str, Any]:
        """
        Processa o reagendamento com nova data e horário.
        """
        try:
            logger.info(
                f"[ReagendamentoFlow] Processando reagendamento: "
                f"company_id={self.company_id}, phone={self.phone}, "
                f"data={data}, horario={horario}"
            )

            # Atualiza data e horário no state
            self.state_machine.set_state_data("data", data)
            self.state_machine.set_state_data("horario", horario)
            self.state_machine.set_state_data("agendamento_confirmado", True)

            # Confirma novo agendamento
            confirmation_msg = confirm_appointment(self.state_machine)

            if not confirmation_msg:
                logger.error("[ReagendamentoFlow] Falha ao confirmar reagendamento")
                return {
                    "success": False,
                    "message": "Erro ao confirmar reagendamento",
                    "data": {
                        "company_id": self.company_id,
                        "phone": self.phone,
                        "data": data,
                        "horario": horario
                    }
                }

            return {
                "success": True,
                "message": confirmation_msg,
                "data": {
                    "company_id": self.company_id,
                    "phone": self.phone,
                    "data": data,
                    "horario": horario,
                    "nome": self.state_machine.get_state_data("nome"),
                    "tratamento": self.state_machine.get_state_data("tratamento"),
                    "cliente": self.state_machine.get_state_data("cliente")
                }
            }

        except Exception as e:
            logger.error(f"[ReagendamentoFlow] Erro ao processar reagendamento: {e}")
            return {
                "success": False,
                "message": "Erro interno ao processar reagendamento",
                "error": str(e),
                "data": {
                    "company_id": self.company_id,
                    "phone": self.phone,
                    "data": data,
                    "horario": horario
                }
            }

def handle_reschedule_request(
    state_machine: ConversationStateMachine,
    data: Optional[str] = None,
    horario: Optional[str] = None
) -> Dict[str, Any]:
    """
    Função auxiliar para processar reagendamentos.
    Se data/horario fornecidos, processa reagendamento.
    Caso contrário, apenas prepara o state.
    """
    flow = ReagendamentoFlow(state_machine=state_machine)

    if data and horario:
        return flow.process_reschedule(data=data, horario=horario)
    else:
        return flow.prepare_for_reschedule()
