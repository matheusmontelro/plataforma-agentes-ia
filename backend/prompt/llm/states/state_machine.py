import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
import json
import pytz

logger = logging.getLogger(__name__)

class ConversationStateMachine:
    """
    Gerencia o estado da conversa e suas transições.
    Inclui validações rigorosas e controle de estado pós-agendamento.
    """

    REQUIRED_FIELDS = ["tratamento", "cliente", "nome", "data", "horario"]
    VALID_STEPS = range(0, 10)  # Steps válidos: 0 a 9
    CONFIRMATION_COOLDOWN = 300  # 5 minutos em segundos

    def __init__(self, db_session: Session, phone: str, company_id: int):
        self.db_session = db_session
        self.phone = phone
        self.company_id = company_id

        self.current_step: int = 0
        self.state_data: Dict[str, Any] = {}
        self.pending_updates: bool = False

        # Rastrear perguntas respondidas e apresentadas
        self.answered_questions: Dict[str, bool] = {}
        self.presented_questions: Dict[str, bool] = {}

        # Carregar estado do banco
        self._load_state_from_db()

    def _validate_step(self, step: int) -> bool:
        """
        Valida se um step é válido e apropriado para o estado atual.
        Agora considera também o contexto pós-agendamento.
        """
        if step not in self.VALID_STEPS:
            logger.warning(f"[StateMachine] Step inválido: {step}")
            return False

        # Se step > 0 mas não há dados básicos, impede avanço
        if step > 0 and not self.state_data:
            logger.warning("[StateMachine] Tentativa de avançar sem dados básicos")
            return False

        # Se for step 8 (cancelamento), pula as validações de agendamento
        if step == 8:
            # Aqui você decide se quer ignorar a verificação de cooldown também.
            # Caso queira ignorar o cooldown, retorne True diretamente:
            return True

        if step >= 5:
            # Se já houve confirmação recente, impede nova confirmação
            if self.has_recent_confirmation():
                logger.warning("[StateMachine] Tentativa de confirmação durante período de cooldown")
                return False

            missing = self.get_missing_required_fields()
            if missing:
                logger.warning(f"[StateMachine] Tentativa de ir para step {step} com campos faltando: {missing}")
                return False

        return True

    def has_recent_confirmation(self) -> bool:
        """
        Verifica se houve uma confirmação recente baseado no timestamp.
        """
        last_confirmation = self.state_data.get('last_confirmation_timestamp')
        if not last_confirmation:
            return False

        try:
            last_time = datetime.fromisoformat(last_confirmation)
            cooldown_time = datetime.now(pytz.UTC) - timedelta(seconds=self.CONFIRMATION_COOLDOWN)
            return last_time > cooldown_time
        except (ValueError, TypeError):
            return False

    def _load_state_from_db(self) -> None:
        """
        Carrega o estado do DB com validações adicionais.
        """
        try:
            result = self.db_session.execute(
                text("""
                    SELECT current_step, state_data
                    FROM conversation_state
                    WHERE phone = :phone AND company_id = :company_id
                    LIMIT 1
                """),
                {"phone": self.phone, "company_id": self.company_id}
            ).fetchone()

            if result:
                loaded_step = result[0] or 0
                if self._validate_step(loaded_step):
                    self.current_step = loaded_step
                else:
                    self.current_step = 0  # Reset para step inicial se inválido

                self.state_data = result[1] or {}

                # Validação adicional dos dados carregados
                self._validate_state_data()

                logger.info(f"[StateMachine] Estado carregado: step={self.current_step}, data={self.state_data}")
            else:
                self._create_initial_state()

        except Exception as e:
            logger.error(f"[StateMachine] Erro ao carregar estado: {e}")
            self._create_initial_state()

    def _create_initial_state(self) -> None:
        """
        Cria estado inicial com validações.
        """
        try:
            self.db_session.execute(
                text("""
                    INSERT INTO conversation_state (phone, company_id, current_step, state_data)
                    VALUES (:phone, :company_id, 0, '{}')
                    ON CONFLICT (phone, company_id) DO UPDATE
                    SET current_step = 0,
                        state_data = '{}',
                        updated_at = CURRENT_TIMESTAMP
                """),
                {"phone": self.phone, "company_id": self.company_id}
            )
            self.db_session.commit()
            logger.info("[StateMachine] Novo estado criado")
        except Exception as e:
            logger.error(f"[StateMachine] Erro ao criar estado: {e}")

    def _validate_state_data(self) -> None:
        """
        Valida os dados do estado atual e corrige inconsistências.
        """
        # Remove campos inválidos/vazios
        invalid_keys = []
        for key, value in self.state_data.items():
            if value in [None, "", "null", "undefined"]:
                invalid_keys.append(key)

        for key in invalid_keys:
            self.state_data.pop(key, None)

        # Valida tipos de dados esperados
        date_fields = ["data"]
        time_fields = ["horario"]

        for field in date_fields:
            if field in self.state_data:
                try:
                    datetime.strptime(self.state_data[field], "%d/%m/%Y")
                except ValueError:
                    logger.warning(f"[StateMachine] Data inválida removida: {field}={self.state_data[field]}")
                    self.state_data.pop(field)

        for field in time_fields:
            if field in self.state_data:
                try:
                    datetime.strptime(self.state_data[field], "%H:%M")
                except ValueError:
                    logger.warning(f"[StateMachine] Horário inválido removido: {field}={self.state_data[field]}")
                    self.state_data.pop(field)

    def save_state_to_db(self) -> None:
        """
        Salva o estado atual com validações.
        """
        if not self.pending_updates:
            return

        try:
            # Valida dados antes de salvar
            self._validate_state_data()

            self.db_session.execute(
                text("""
                    UPDATE conversation_state
                    SET current_step = :step,
                        state_data = CAST(:data as JSONB),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE phone = :phone
                      AND company_id = :company_id
                """),
                {
                    "step": self.current_step,
                    "data": json.dumps(self.state_data),
                    "phone": self.phone,
                    "company_id": self.company_id
                }
            )
            self.db_session.commit()
            self.pending_updates = False
            logger.info(f"[StateMachine] Estado salvo: step={self.current_step}, data={self.state_data}")
        except Exception as e:
            logger.error(f"[StateMachine] Erro ao salvar estado: {e}")
            raise

    def reset_post_confirmation(self) -> None:
        """
        Reseta o estado após uma confirmação de agendamento.
        """
        # Salva timestamp da confirmação
        self.state_data['last_confirmation_timestamp'] = datetime.now(pytz.UTC).isoformat()

        # Limpa dados do agendamento (mas mantém nome, cliente, tratamento)
        fields_to_clear = [
            'data',
            'horario',
            'agendamento_confirmado',
            # 'tratamento',  # Não remover
            # 'cliente',   # Não remover
            # 'nome'        # Não remover
        ]

        for field in fields_to_clear:
            self.state_data.pop(field, None)

        # Volta para step inicial (ou, se quiser, para step 7)
        self.current_step = 7  # se decidir seguir o fluxo pós-agendamento
        self.pending_updates = True
        self.save_state_to_db()

        logger.info("[StateMachine] Estado resetado após confirmação, mantendo tratamento/cliente/nome.")

    def get_current_step(self) -> int:
        """Retorna o step atual."""
        return self.current_step

    def set_current_step(self, step: int) -> None:
        """
        Define o step atual com validações.
        """
        if self._validate_step(step):
            if step != self.current_step:
                self.current_step = step
                self.pending_updates = True
                self.save_state_to_db()

    def get_state_data(self, key: str, default: Any = None) -> Any:
        """Retorna valor do state_data."""
        return self.state_data.get(key, default)

    def set_state_data(self, key: str, value: Any) -> None:
        """
        Define valor no state_data com validações.
        """
        if value is not None and value != "":
            if key not in self.state_data or self.state_data[key] != value:
                self.state_data[key] = value
                # Marcar pergunta como respondida
                self.answered_questions[key] = True
                self.pending_updates = True
                self.save_state_to_db()

                # REMOVIDO: Avanço automático para step 5
                # O avanço deve ser controlado explicitamente pelo fluxo de conversa

    def is_filled(self, key: str) -> bool:
        """Verifica se campo está preenchido."""
        return bool(self.state_data.get(key))

    def is_question_answered(self, key: str) -> bool:
        """Verifica se uma pergunta já foi respondida."""
        return self.answered_questions.get(key, False)

    def is_question_presented(self, key: str) -> bool:
        """Verifica se uma pergunta já foi apresentada ao usuário."""
        return self.presented_questions.get(key, False)

    def mark_question_presented(self, key: str) -> None:
        """Marca uma pergunta como apresentada ao usuário."""
        self.presented_questions[key] = True
        self.pending_updates = True

    def get_missing_required_fields(self) -> List[str]:
        """
        Retorna lista de campos obrigatórios faltantes.
        """
        return [field for field in self.REQUIRED_FIELDS if not self.is_filled(field)]

    def can_confirm_appointment(self) -> bool:
        """
        Verifica se pode confirmar o agendamento.
        """
        return (
            self.current_step >= 5 and
            not self.get_missing_required_fields() and
            not self.get_state_data("cancelar_agendamento", False) and
            not self.has_recent_confirmation()
        )

    def is_in_post_confirmation_state(self) -> bool:
        """
        Verifica se está em estado pós-confirmação.
        """
        return bool(self.state_data.get('last_confirmation_timestamp'))

    def get_confirmation_cooldown_remaining(self) -> int:
        """
        Retorna segundos restantes do cooldown, ou 0 se não estiver em cooldown.
        """
        last_confirmation = self.state_data.get('last_confirmation_timestamp')
        if not last_confirmation:
            return 0

        try:
            last_time = datetime.fromisoformat(last_confirmation)
            cooldown_end = last_time + timedelta(seconds=self.CONFIRMATION_COOLDOWN)
            remaining = (cooldown_end - datetime.now(pytz.UTC)).total_seconds()
            return max(0, int(remaining))
        except (ValueError, TypeError):
            return 0
