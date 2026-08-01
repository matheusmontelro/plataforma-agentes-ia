import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from backend.prompt.db_integration.agendamento_logic import processar_cancelamento

logger = logging.getLogger(__name__)

class CancelamentoFlow:
    """
    Gerencia o fluxo de cancelamento de consultas.
    Integra com o processar_cancelamento existente e gerencia o estado.
    """

    def __init__(self, db: Session, company_id: int, phone: str, api_key: str):
        self.db = db
        self.company_id = company_id
        self.phone = phone
        self.api_key = api_key

    def process_cancellation(self, motivo: Optional[str] = None) -> Dict[str, Any]:
        """
        Processa o cancelamento da consulta.
        Retorna dicionário com resultado do processamento.
        """
        try:
            logger.info(
                f"[CancelamentoFlow] Iniciando cancelamento para "
                f"company_id={self.company_id}, phone={self.phone}"
            )

            if motivo:
                logger.info(f"[CancelamentoFlow] Motivo do cancelamento: {motivo}")

            # Chama função existente de cancelamento
            confirmation_msg = processar_cancelamento(
                db=self.db,
                company_id=self.company_id,
                phone=self.phone,
                api_key=self.api_key
            )

            success = bool(confirmation_msg)

            result = {
                "success": success,
                "message": confirmation_msg if success else "Erro ao processar cancelamento",
                "motivo": motivo,
                "data": {
                    "company_id": self.company_id,
                    "phone": self.phone,
                }
            }

            if success:
                logger.info("[CancelamentoFlow] Cancelamento processado com sucesso")
            else:
                logger.error("[CancelamentoFlow] Falha ao processar cancelamento")

            return result

        except Exception as e:
            logger.error(f"[CancelamentoFlow] Erro ao processar cancelamento: {e}")
            return {
                "success": False,
                "message": "Erro interno ao processar cancelamento",
                "error": str(e),
                "data": {
                    "company_id": self.company_id,
                    "phone": self.phone,
                }
            }

def handle_cancellation_request(
    db: Session,
    company_id: int,
    phone: str,
    api_key: str,
    motivo: Optional[str] = None
) -> Dict[str, Any]:
    """
    Função auxiliar para processar cancelamentos.
    Cria instância de CancelamentoFlow e processa o pedido.
    """
    flow = CancelamentoFlow(
        db=db,
        company_id=company_id,
        phone=phone,
        api_key=api_key
    )

    return flow.process_cancellation(motivo=motivo)
