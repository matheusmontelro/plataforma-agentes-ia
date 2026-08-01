# State Management for OpenAI Agents SDK
import logging
import json
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from sqlalchemy import text
from sqlalchemy.orm import Session
import pytz

logger = logging.getLogger(__name__)

@dataclass
class ConversationState:
    """
    Representa o estado atual da conversa.
    Similar ao state_machine.py mas otimizado para Agents SDK.
    """
    current_step: int = 0
    state_data: Dict[str, Any] = field(default_factory=dict)
    answered_questions: Dict[str, bool] = field(default_factory=dict)
    presented_questions: Dict[str, bool] = field(default_factory=dict)
    pending_updates: bool = False
    offered_slots: List[str] = field(default_factory=list)  # Slots oferecidos pelo LLM

    def to_dict(self) -> Dict[str, Any]:
        """Converte o estado para um dicionário para persistência."""
        return {
            'current_step': self.current_step,
            'state_data': self.state_data,
            'answered_questions': self.answered_questions,
            'presented_questions': self.presented_questions,
            'pending_updates': self.pending_updates,
            'offered_slots': self.offered_slots
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationState':
        """Cria um ConversationState a partir de um dicionário."""
        return cls(
            current_step=data.get('current_step', 0),
            state_data=data.get('state_data', {}),
            answered_questions=data.get('answered_questions', {}),
            presented_questions=data.get('presented_questions', {}),
            pending_updates=data.get('pending_updates', False),
            offered_slots=data.get('offered_slots', [])
        )


class AgentsSDKStateManager:
    """
    Gerencia o estado da conversa para o OpenAI Agents SDK.
    Integra com o sistema existente de conversation_state.
    """

    # Constantes do sistema original
    REQUIRED_FIELDS = ["tratamento", "cliente", "nome", "data", "horario"]
    VALID_STEPS = range(0, 11)  # Estendido para incluir step 9 (reagendamento) e 10 para futuro

    def __init__(self, db: Session, company_id: int, contact_phone: str):
        self.db = db
        self.company_id = company_id
        self.contact_phone = contact_phone
        self.state = ConversationState()

    async def load_state(self) -> None:
        """Carrega o estado do banco de dados."""
        try:
            result = self.db.execute(
                text("""
                    SELECT current_step, state_data
                    FROM conversation_state
                    WHERE phone = :phone AND company_id = :company_id
                    LIMIT 1
                """),
                {"phone": self.contact_phone, "company_id": self.company_id}
            ).fetchone()

            if result:
                loaded_step = result[0] or 0
                loaded_data = result[1] or {}

                # Valida o step carregado
                if loaded_step in self.VALID_STEPS:
                    self.state.current_step = loaded_step
                else:
                    logger.warning(f"[StateManager] Step inválido {loaded_step}, resetando para 0")
                    self.state.current_step = 0

                # Carrega dados do estado
                if isinstance(loaded_data, dict):
                    self.state.state_data = loaded_data

                    # Extrai metadados se estiverem no state_data
                    if '_metadata' in loaded_data:
                        metadata = loaded_data['_metadata']
                        self.state.answered_questions = metadata.get('answered_questions', {})
                        self.state.presented_questions = metadata.get('presented_questions', {})

                logger.info(f"[StateManager] Estado carregado: step={self.state.current_step}, data keys={list(self.state.state_data.keys())}")
            else:
                await self._create_initial_state()

        except Exception as e:
            logger.error(f"[StateManager] Erro ao carregar estado: {e}")
            await self._create_initial_state()

    async def _create_initial_state(self) -> None:
        """Cria estado inicial no banco."""
        try:
            self.db.execute(
                text("""
                    INSERT INTO conversation_state (phone, company_id, current_step, state_data)
                    VALUES (:phone, :company_id, 0, '{}')
                    ON CONFLICT (phone, company_id) DO UPDATE
                    SET current_step = 0,
                        state_data = '{}',
                        updated_at = CURRENT_TIMESTAMP
                """),
                {"phone": self.contact_phone, "company_id": self.company_id}
            )
            self.db.commit()
            logger.info(f"[StateManager] Estado inicial criado para {self.contact_phone}")
        except Exception as e:
            logger.error(f"[StateManager] Erro ao criar estado inicial: {e}")

    async def save_state(self) -> None:
        """Salva o estado atual no banco."""
        if not self.state.pending_updates:
            return

        try:
            # Prepara dados para persistência
            state_data_with_metadata = self.state.state_data.copy()
            state_data_with_metadata['_metadata'] = {
                'answered_questions': self.state.answered_questions,
                'presented_questions': self.state.presented_questions
            }

            self.db.execute(
                text("""
                    UPDATE conversation_state
                    SET current_step = :step,
                        state_data = CAST(:data as JSONB),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE phone = :phone AND company_id = :company_id
                """),
                {
                    "step": self.state.current_step,
                    "data": json.dumps(state_data_with_metadata),
                    "phone": self.contact_phone,
                    "company_id": self.company_id
                }
            )
            self.db.commit()
            self.state.pending_updates = False
            logger.info(f"[StateManager] Estado salvo: step={self.state.current_step}")
        except Exception as e:
            logger.error(f"[StateManager] Erro ao salvar estado: {e}")
            raise

    async def transition_to_step(self, target_step: int) -> bool:
        """
        Transiciona para um novo step com validações.

        Args:
            target_step: Step de destino

        Returns:
            bool: True se a transição foi bem-sucedida
        """
        if target_step == self.state.current_step:
            return True

        # Valida a transição
        can_transition, error_msg = await self._validate_step_transition(target_step)

        if not can_transition:
            logger.warning(f"[StateManager] Transição negada para step {target_step}: {error_msg}")
            return False

        # Executa a transição
        old_step = self.state.current_step
        self.state.current_step = target_step
        self.state.pending_updates = True

        logger.info(f"[StateManager] Transição {old_step} → {target_step}")

        # Salva automaticamente
        await self.save_state()

        return True

    async def _validate_step_transition(self, target_step: int) -> Tuple[bool, Optional[str]]:
        """
        Valida se uma transição de step é permitida.

        Returns:
            Tuple[bool, Optional[str]]: (pode_transicionar, mensagem_erro)
        """
        # Valida se o step é válido
        if target_step not in self.VALID_STEPS:
            return False, f"Step inválido: {target_step}"

        # Se for step 8 (cancelamento), permite sem validações
        if target_step == 8:
            return True, None

        # Valida se tem dados básicos para steps > 0
        if target_step > 0 and not self.state.state_data:
            return False, "Não há dados básicos para avançar"

        # Valida campos obrigatórios para steps >= 5
        if target_step >= 5:
            # Removido cooldown - usuário deve poder cancelar/reagendar imediatamente

            # Valida campos obrigatórios
            missing_fields = self._get_missing_required_fields()
            if missing_fields:
                return False, f"Campos obrigatórios faltando: {missing_fields}"

        return True, None

    # Método removido - cooldown não é mais necessário

    def _get_missing_required_fields(self) -> List[str]:
        """Retorna lista de campos obrigatórios faltando."""
        return [field for field in self.REQUIRED_FIELDS if not self.state.state_data.get(field)]

    async def set_state_data(self, key: str, value: Any) -> None:
        """
        Define um valor no state_data com validações.

        Args:
            key: Chave do dado
            value: Valor a ser armazenado
        """
        if value is not None and value != "":
            if key not in self.state.state_data or self.state.state_data[key] != value:
                self.state.state_data[key] = value
                self.state.answered_questions[key] = True
                self.state.pending_updates = True

                logger.info(f"[StateManager] Dados atualizados: {key}={value}")

                # Salva automaticamente
                await self.save_state()

    def get_state_data(self, key: str, default: Any = None) -> Any:
        """Retorna valor do state_data."""
        return self.state.state_data.get(key, default)

    async def set_offered_slots(self, slots: List[str]) -> None:
        """
        Define quais slots foram oferecidos pelo LLM ao cliente.

        Args:
            slots: Lista de slots no formato "DD/MM/YYYY HH:MM"
        """
        if slots and len(slots) > 0:
            self.state.offered_slots = slots.copy()
            self.state.pending_updates = True

            logger.info(f"[StateManager] Slots oferecidos salvos: {len(slots)} slots")
            logger.debug(f"[StateManager] Slots: {slots}")

            # Salva automaticamente
            await self.save_state()

    def get_offered_slots(self) -> List[str]:
        """Retorna os slots que foram oferecidos pelo LLM."""
        return self.state.offered_slots.copy()

    def has_offered_slots(self) -> bool:
        """Verifica se há slots oferecidos salvos."""
        return len(self.state.offered_slots) > 0

    def clear_offered_slots(self) -> None:
        """Limpa a lista de slots oferecidos."""
        self.state.offered_slots.clear()
        self.state.pending_updates = True

    def is_field_filled(self, key: str) -> bool:
        """Verifica se um campo está preenchido."""
        return bool(self.state.state_data.get(key))

    def is_question_answered(self, key: str) -> bool:
        """Verifica se uma pergunta foi respondida."""
        return self.state.answered_questions.get(key, False)

    def is_question_presented(self, key: str) -> bool:
        """Verifica se uma pergunta foi apresentada."""
        return self.state.presented_questions.get(key, False)

    async def mark_question_presented(self, key: str) -> None:
        """Marca uma pergunta como apresentada."""
        self.state.presented_questions[key] = True
        self.state.pending_updates = True
        await self.save_state()

    async def can_confirm_appointment(self) -> bool:
        """Verifica se pode confirmar o agendamento."""
        return (
            self.state.current_step >= 5 and
            not self._get_missing_required_fields() and
            not self.state.state_data.get("cancelar_agendamento", False)
            # Removido cooldown - usuário pode remarcar quando quiser
        )

    async def reset_post_confirmation(self) -> None:
        """Reseta o estado após confirmação de agendamento."""
        # Limpa dados específicos do agendamento mas mantém dados do cliente
        fields_to_clear = ['data', 'horario', 'agendamento_confirmado']
        for field in fields_to_clear:
            self.state.state_data.pop(field, None)

        # Vai para step pós-agendamento
        self.state.current_step = 7
        self.state.pending_updates = True

        await self.save_state()

        logger.info("[StateManager] Estado resetado após confirmação")

    # Método removido - cooldown não é mais necessário

    def get_step_description(self) -> str:
        """Retorna descrição do step atual."""
        step_descriptions = {
            0: "Boas-vindas",
            1: "Identificação do tratamento",
            2: "Situação do cliente",
            3: "Exploração e benefícios",
            4: "Agendamento",
            5: "Confirmação e nome",
            6: "Encerramento",
            7: "Pós-agendamento",
            8: "Cancelamento",
            9: "Reagendamento"
        }
        return step_descriptions.get(self.state.current_step, f"Step {self.state.current_step}")

    async def should_trigger_automatic_scheduling(self) -> bool:
        """
        Verifica se deve disparar o agendamento automático.

        Returns:
            bool: True se deve agendar automaticamente
        """
        return (
            self.state.current_step == 5 and
            self.is_field_filled("nome") and
            self.is_field_filled("data") and
            self.is_field_filled("horario") and
            not self.state.state_data.get("agendamento_confirmado", False)
        )

    async def should_trigger_automatic_cancellation(self) -> bool:
        """
        Verifica se deve disparar o cancelamento automático.

        Returns:
            bool: True se deve cancelar automaticamente
        """
        return (
            self.state.current_step == 8 and
            not self.state.state_data.get("cancelamento_processado", False)
        )

    async def should_trigger_automatic_rescheduling(self) -> bool:
        """
        Verifica se deve disparar o reagendamento automático.

        Returns:
            bool: True se deve reagendar automaticamente
        """
        return (
            self.state.current_step == 9 and
            not self.state.state_data.get("reagendamento_processado", False)
        )