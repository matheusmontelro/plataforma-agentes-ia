"""
State manager for conversation flow.

This module manages the conversation state for each user,
tracking their progress through the conversation steps and
collected data.
"""

import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ConversationStateManager:
    """Manages conversation state for users across steps."""

    def __init__(self):
        """Initialize the state manager."""
        # In-memory cache for quick access
        self._state_cache = {}

    def get_state(self,
                  contact_phone: str,
                  company_id: int,
                  db_session: Optional[Session] = None) -> Dict[str, Any]:
        """
        Get current conversation state for a contact.

        Args:
            contact_phone: Contact's phone number
            company_id: Company ID
            db_session: Database session for persistence

        Returns:
            Dictionary containing current state
        """
        cache_key = f"{company_id}:{contact_phone}"

        # Try to load from database first
        if db_session:
            db_state = self._load_from_db(contact_phone, company_id, db_session)
            if db_state:
                self._state_cache[cache_key] = db_state
                return db_state

        # Check cache
        if cache_key in self._state_cache:
            return self._state_cache[cache_key]

        # Return default state
        default_state = {
            "step": 0,
            "tratamento": None,
            "cliente": None,
            "nome": None,
            "data": None,
            "horario": None,
            "last_interaction": datetime.now().isoformat(),
            "conversation_start": datetime.now().isoformat(),
            "cancelamento": False,
            "reagendamento": False
        }

        self._state_cache[cache_key] = default_state
        return default_state

    def update_state(self,
                     contact_phone: str,
                     company_id: int,
                     user_input: str,
                     assistant_response: str,
                     current_state: Dict[str, Any],
                     db_session: Optional[Session] = None) -> Dict[str, Any]:
        """
        Update conversation state based on interaction.

        Args:
            contact_phone: Contact's phone number
            company_id: Company ID
            user_input: User's message
            assistant_response: Assistant's response
            current_state: Current state dictionary
            db_session: Database session for persistence

        Returns:
            Updated state dictionary
        """
        cache_key = f"{company_id}:{contact_phone}"

        # Extract data from user input and response
        extracted_data = self._extract_data(user_input, assistant_response, current_state)

        # Update state with extracted data
        updated_state = {**current_state, **extracted_data}
        updated_state["last_interaction"] = datetime.now().isoformat()

        # Handle special cases
        if self._check_cancellation(user_input):
            updated_state["cancelamento"] = True

        if self._check_reschedule(user_input):
            updated_state["reagendamento"] = True

        # Save to cache
        self._state_cache[cache_key] = updated_state

        # Persist to database if session provided
        if db_session:
            self._save_to_db(contact_phone, company_id, updated_state, db_session)

        logger.info(f"[StateManager] Updated state for {contact_phone}: step={updated_state['step']}")

        return updated_state

    def reset_state(self, contact_phone: str, company_id: int, db_session: Optional[Session] = None):
        """Reset conversation state for a contact."""
        cache_key = f"{company_id}:{contact_phone}"

        if cache_key in self._state_cache:
            del self._state_cache[cache_key]

        if db_session:
            try:
                db_session.execute(
                    text("""
                        DELETE FROM conversation_state
                        WHERE phone = :phone AND company_id = :company_id
                    """),
                    {"phone": contact_phone, "company_id": company_id}
                )
                db_session.commit()
            except Exception as e:
                logger.error(f"[StateManager] Error resetting state in DB: {e}")

    def _extract_data(self, user_input: str, assistant_response: str, current_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract relevant data from user input and assistant response.

        This is a simplified version - in production, you might want to use
        NLP or regex patterns for better extraction.
        """
        extracted = {}
        user_lower = user_input.lower()

        # Extract treatment type (step 1)
        if current_state["step"] == 1 and not current_state.get("tratamento"):
            treatments = {
                "limpeza": ["limpeza", "profilaxia", "higienização"],
                "canal": ["canal", "endodontia", "dói muito"],
                "implante": ["implante", "perdi dente", "sem dente"],
                "aparelho": ["aparelho", "ortodontia", "dentes tortos"],
                "clareamento": ["clareamento", "branquear", "dentes amarelos"],
                "restauração": ["restauração", "obturação", "buraco no dente"],
                "extração": ["extração", "arrancar", "tirar dente"],
                "prótese": ["prótese", "dentadura", "ponte"]
            }

            for treatment, keywords in treatments.items():
                if any(keyword in user_lower for keyword in keywords):
                    extracted["tratamento"] = treatment
                    break

        # Extract customer type (step 2)
        if current_state["step"] == 2 and not current_state.get("cliente"):
            if any(word in user_lower for word in ["primeira vez", "novo", "nunca vim", "não conheço"]):
                extracted["cliente"] = "novo"
            elif any(word in user_lower for word in ["já sou", "retorno", "volta", "já fui"]):
                extracted["cliente"] = "retorno"

        # Extract chosen date/time (step 4)
        if current_state["step"] == 4:
            # Simple pattern matching for date/time
            import re

            # Pattern for date: DD/MM/YYYY
            date_pattern = r'\d{2}/\d{2}/\d{4}'
            date_match = re.search(date_pattern, user_input)
            if date_match:
                extracted["data"] = date_match.group()

            # Pattern for time: HH:MM
            time_pattern = r'\d{1,2}:\d{2}'
            time_match = re.search(time_pattern, user_input)
            if time_match:
                extracted["horario"] = time_match.group()

        # Extract name (step 5)
        if current_state["step"] == 5 and not current_state.get("nome"):
            # Simple heuristic: if message has more than one word and no question mark
            if " " in user_input.strip() and "?" not in user_input:
                # Assume it's the name (in production, use better NLP)
                extracted["nome"] = user_input.strip().title()

        return extracted

    def _check_cancellation(self, user_input: str) -> bool:
        """Check if user wants to cancel appointment."""
        cancel_keywords = ["cancelar", "desmarcar", "não vou", "desistir", "não quero mais"]
        return any(keyword in user_input.lower() for keyword in cancel_keywords)

    def _check_reschedule(self, user_input: str) -> bool:
        """Check if user wants to reschedule appointment."""
        reschedule_keywords = ["remarcar", "reagendar", "mudar horário", "outro dia", "trocar horário"]
        return any(keyword in user_input.lower() for keyword in reschedule_keywords)

    def _load_from_db(self, contact_phone: str, company_id: int, db_session: Session) -> Optional[Dict[str, Any]]:
        """Load state from database."""
        try:
            result = db_session.execute(
                text("""
                    SELECT state_data, current_step, updated_at
                    FROM conversation_state
                    WHERE phone = :phone AND company_id = :company_id
                    ORDER BY updated_at DESC
                    LIMIT 1
                """),
                {"phone": contact_phone, "company_id": company_id}
            ).fetchone()

            if result:
                # Handle case where state_data might already be a dict
                if isinstance(result.state_data, dict):
                    state = result.state_data
                elif isinstance(result.state_data, str):
                    state = json.loads(result.state_data) if result.state_data else {}
                else:
                    state = {}
                state["step"] = result.current_step
                return state

        except Exception as e:
            logger.error(f"[StateManager] Error loading from DB: {e}")

        return None

    def _save_to_db(self, contact_phone: str, company_id: int, state: Dict[str, Any], db_session: Session):
        """Save state to database."""
        try:
            # Remove step from state data before saving
            state_data = {k: v for k, v in state.items() if k != "step"}

            db_session.execute(
                text("""
                    INSERT INTO conversation_state (phone, company_id, current_step, state_data, updated_at)
                    VALUES (:phone, :company_id, :step, :state_data, NOW())
                    ON CONFLICT (phone, company_id)
                    DO UPDATE SET
                        current_step = :step,
                        state_data = :state_data,
                        updated_at = NOW()
                """),
                {
                    "phone": contact_phone,
                    "company_id": company_id,
                    "step": state.get("step", 0),
                    "state_data": json.dumps(state_data, ensure_ascii=False)
                }
            )
            db_session.commit()

        except Exception as e:
            logger.error(f"[StateManager] Error saving to DB: {e}")
            db_session.rollback()