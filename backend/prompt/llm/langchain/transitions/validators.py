"""
Validators for appointment state fields.
Provides validation logic for each step of the conversation flow.
"""

import re
import logging
from typing import Tuple, List, Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Timezone configuration
try:
    from zoneinfo import ZoneInfo
    SP_TZ = ZoneInfo("America/Sao_Paulo")
except ImportError:
    import pytz
    SP_TZ = pytz.timezone("America/Sao_Paulo")


class StateValidator:
    """
    Validators for appointment state fields.
    Each validator returns (is_valid, error_message).
    """

    # Common patterns
    DATE_PATTERN = re.compile(r'^(\d{2})/(\d{2})/(\d{4})$')
    TIME_PATTERN = re.compile(r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$')
    PHONE_PATTERN = re.compile(r'^55\d{10,11}$')

    # Confirmation words
    CONFIRMATION_WORDS = {
        "sim", "confirmo", "confirmado", "confirmar", "pode ser", "ok",
        "tá bom", "ta bom", "tá", "ta", "claro", "com certeza",
        "exato", "exatamente", "isso", "isso mesmo", "perfeito",
        "beleza", "combinado", "fechado", "de acordo", "concordo",
        "quero", "aceito", "eu aceito", "eu quero", "tá certo",
        "ta certo", "correto", "positivo", "afirmativo", "aham",
        "uhum", "pode", "agendado", "vamos", "tá fechado", "ta fechado"
    }

    # Cancellation words (excluding standalone "não" to avoid false positives)
    CANCELLATION_WORDS = {
        "cancelar", "cancela", "desmarcar", "desmarca", "não quero",
        "desisto", "não vai dar", "deixa pra lá",
        "outro momento"
    }

    # Time constraint indicators (to avoid false cancellation detection)
    TIME_CONSTRAINT_INDICATORS = {
        "depois das", "após", "antes das", "entre", "após as", "antes das",
        "depois de", "antes de", "após os", "antes dos", "depois dos",
        "horas", "h", "horário", "horarios", "manhã", "tarde", "noite"
    }

    @classmethod
    def validate_date(cls, date_str: str) -> Tuple[bool, Optional[str]]:
        """
        Validate date format and logical constraints.

        Args:
            date_str: Date string to validate

        Returns:
            (is_valid, error_message)
        """
        if not date_str:
            return False, "Data é obrigatória"

        match = cls.DATE_PATTERN.match(date_str)
        if not match:
            return False, "Data deve estar no formato DD/MM/YYYY"

        day, month, year = map(int, match.groups())

        try:
            date_obj = datetime(year, month, day).replace(tzinfo=SP_TZ)
            today = datetime.now(SP_TZ).replace(hour=0, minute=0, second=0, microsecond=0)

            # Check if date is not in the past
            if date_obj < today:
                return False, "Data não pode ser no passado"

            # Check if date is not too far in future (e.g., 90 days)
            max_future = today + timedelta(days=90)
            if date_obj > max_future:
                return False, "Data muito distante (máximo 90 dias)"

            return True, None

        except ValueError:
            return False, "Data inválida"

    @classmethod
    def validate_time(cls, time_str: str) -> Tuple[bool, Optional[str]]:
        """
        Validate time format.

        Args:
            time_str: Time string to validate

        Returns:
            (is_valid, error_message)
        """
        if not time_str:
            return False, "Horário é obrigatório"

        if not cls.TIME_PATTERN.match(time_str):
            return False, "Horário deve estar no formato HH:MM"

        return True, None

    @classmethod
    def validate_phone(cls, phone: str) -> Tuple[bool, Optional[str]]:
        """
        Validate Brazilian phone number.

        Args:
            phone: Phone number to validate

        Returns:
            (is_valid, error_message)
        """
        if not phone:
            return False, "Telefone é obrigatório"

        if not cls.PHONE_PATTERN.match(phone):
            return False, "Telefone deve ter formato 55DDDNUMERO"

        return True, None

    @classmethod
    def validate_treatment(cls, treatment: str) -> Tuple[bool, Optional[str]]:
        """
        Validate treatment selection.

        Args:
            treatment: Treatment type

        Returns:
            (is_valid, error_message)
        """
        if not treatment:
            return False, "Tipo de tratamento é obrigatório"

        if len(treatment) < 3:
            return False, "Tratamento deve ter pelo menos 3 caracteres"

        return True, None

    @classmethod
    def validate_customer_type(cls, customer_type: str) -> Tuple[bool, Optional[str]]:
        """
        Validate customer type.

        Args:
            customer_type: Type of customer (novo/existente)

        Returns:
            (is_valid, error_message)
        """
        if not customer_type:
            return False, "Tipo de cliente é obrigatório"

        if customer_type not in ["novo", "existente"]:
            return False, "Tipo de cliente deve ser 'novo' ou 'existente'"

        return True, None

    @classmethod
    def validate_customer_name(cls, name: str) -> Tuple[bool, Optional[str]]:
        """
        Validate customer full name.

        Args:
            name: Customer name

        Returns:
            (is_valid, error_message)
        """
        if not name:
            return False, "Nome completo é obrigatório"

        # Remove extra spaces
        clean_name = ' '.join(name.split())

        if len(clean_name) < 3:
            return False, "Nome deve ter pelo menos 3 caracteres"

        # Check if has at least two parts (first and last name)
        parts = clean_name.split()
        if len(parts) < 2:
            return False, "Por favor, informe nome e sobrenome"

        # Check for invalid characters
        if not all(part.replace('-', '').isalpha() for part in parts):
            return False, "Nome deve conter apenas letras"

        return True, None

    @classmethod
    def is_confirmation(cls, text: str) -> bool:
        """
        Check if text contains confirmation words.
        Context-aware to avoid false positives with time constraints.

        Args:
            text: User input text

        Returns:
            True if confirmation detected
        """
        text_lower = text.lower().strip()

        # Direct match
        if text_lower in cls.CONFIRMATION_WORDS:
            return True

        # Check if this is a time constraint expression
        # If so, it's likely NOT a confirmation
        for indicator in cls.TIME_CONSTRAINT_INDICATORS:
            if indicator in text_lower:
                # This appears to be a time constraint, not confirmation
                return False

        # Check if any confirmation word is in the text
        for word in cls.CONFIRMATION_WORDS:
            if word in text_lower:
                # Make sure it's not negated (but be more specific about negation)
                # Look for negation patterns that are actually negative
                negation_patterns = ["não " + word, "nao " + word, "não posso", "não quero"]
                is_negated = any(pattern in text_lower for pattern in negation_patterns)
                if not is_negated:
                    return True

        return False

    @classmethod
    def is_cancellation(cls, text: str) -> bool:
        """
        Check if text contains cancellation intent.
        Context-aware to avoid false positives with time constraints.
        Uses semantic detection for better accuracy.

        Args:
            text: User input text

        Returns:
            True if cancellation detected
        """
        try:
            # Try using semantic detection first (more robust)
            from ..langchain.slots.time_semantic_parser import detect_cancellation_intent_semantic
            return detect_cancellation_intent_semantic(text)
        except ImportError:
            # Fallback to original logic if semantic parser not available
            text_lower = text.lower().strip()

            # First check if this is a time constraint expression
            # If so, it's likely NOT a cancellation
            for indicator in cls.TIME_CONSTRAINT_INDICATORS:
                if indicator in text_lower:
                    # This appears to be a time constraint, not cancellation
                    # Only consider it cancellation if there are explicit cancellation words
                    explicit_cancellation = any(
                        word in text_lower for word in
                        ["cancelar", "cancela", "desmarcar", "desmarca", "desisto", "não quero"]
                    )
                    return explicit_cancellation

            # Check cancellation words
            for word in cls.CANCELLATION_WORDS:
                if word in text_lower:
                    return True

            return False

    @classmethod
    def validate_slot_availability(
        cls,
        selected_slot: str,
        available_slots: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if selected slot is available.

        Args:
            selected_slot: Slot in "DD/MM/YYYY HH:MM" format
            available_slots: List of available slots

        Returns:
            (is_valid, error_message)
        """
        if not selected_slot:
            return False, "Nenhum horário selecionado"

        if not available_slots:
            return False, "Nenhum horário disponível"

        if selected_slot in available_slots:
            return True, None

        # Try to find similar slots (same date)
        selected_date = selected_slot.split()[0] if ' ' in selected_slot else ''
        similar_slots = [s for s in available_slots if s.startswith(selected_date)]

        if similar_slots:
            return False, f"Horário não disponível. Horários disponíveis para {selected_date}: {', '.join([s.split()[1] for s in similar_slots[:3]])}"

        return False, "Horário selecionado não está disponível"

    @classmethod
    def validate_step_requirements(
        cls,
        step: int,
        data: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """
        Validate all requirements for a specific step.

        Args:
            step: Current conversation step
            data: State data dictionary

        Returns:
            (all_valid, list_of_errors)
        """
        errors = []

        if step == 1:
            # Need treatment
            valid, error = cls.validate_treatment(data.get('treatment', ''))
            if not valid:
                errors.append(error)

        elif step == 2:
            # Need treatment and customer type
            valid, error = cls.validate_treatment(data.get('treatment', ''))
            if not valid:
                errors.append(error)

            valid, error = cls.validate_customer_type(data.get('customer_type', ''))
            if not valid:
                errors.append(error)

        elif step == 4:
            # Need date, time, and confirmation
            valid, error = cls.validate_date(data.get('appointment_date', ''))
            if not valid:
                errors.append(error)

            valid, error = cls.validate_time(data.get('appointment_time', ''))
            if not valid:
                errors.append(error)

            if not data.get('user_confirmed_slot'):
                errors.append("Confirmação do usuário é necessária")

            if not data.get('slot_verified'):
                errors.append("Verificação de disponibilidade é necessária")

        elif step == 5:
            # Need all appointment data plus name
            valid, error = cls.validate_customer_name(data.get('customer_name', ''))
            if not valid:
                errors.append(error)

        return len(errors) == 0, errors