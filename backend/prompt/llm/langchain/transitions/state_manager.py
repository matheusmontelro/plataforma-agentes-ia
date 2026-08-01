"""
State manager with Redis persistence and LangChain Memory compatibility.
Provides thread-safe state management for appointment conversations.
"""

import redis
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from .models import AppointmentState

logger = logging.getLogger(__name__)


class LangChainStateManager:
    """
    State manager compatible with LangChain Memory interface.
    Uses Redis for persistence with automatic TTL.
    """

    # We don't inherit from BaseMemory to avoid Pydantic conflicts
    # Instead, we implement the required interface methods

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        redis_url: str = "redis://localhost:6379",
        ttl: int = 86400,  # 24 hours default
        key_prefix: str = "langchain_state"
    ):
        """
        Initialize state manager.

        Args:
            redis_client: Existing Redis client (optional)
            redis_url: Redis connection URL
            ttl: Time to live for states in seconds
            key_prefix: Prefix for Redis keys
        """
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = redis.from_url(redis_url)

        self.ttl = ttl
        self.key_prefix = key_prefix
        self.memory_key = "appointment_state"

    def _get_key(self, phone: str, company_id: int) -> str:
        """Generate Redis key for state"""
        return f"{self.key_prefix}:company_{company_id}:phone_{phone}"

    def _ensure_redis(self) -> redis.Redis:
        """Ensure Redis client is available"""
        if not hasattr(self, 'redis') or not self.redis:
            raise ValueError("Redis client not initialized")
        return self.redis

    def get_state(self, phone: str, company_id: int) -> AppointmentState:
        """
        Retrieve current state from Redis.
        Creates new state if not exists.

        Args:
            phone: Customer phone number
            company_id: Company identifier

        Returns:
            AppointmentState object
        """
        try:
            key = self._get_key(phone, company_id)
            redis_client = self._ensure_redis()
            data = redis_client.get(key)

            if data:
                logger.info(f"[StateManager] Retrieved state for {phone} in company {company_id}")
                state_dict = json.loads(data)
                # Convert datetime strings back to datetime objects
                if 'created_at' in state_dict:
                    state_dict['created_at'] = datetime.fromisoformat(state_dict['created_at'])
                if 'updated_at' in state_dict:
                    state_dict['updated_at'] = datetime.fromisoformat(state_dict['updated_at'])
                return AppointmentState(**state_dict)
            else:
                logger.info(f"[StateManager] Creating new state for {phone} in company {company_id}")
                return AppointmentState(phone=phone, company_id=company_id)

        except Exception as e:
            logger.error(f"[StateManager] Error retrieving state: {e}")
            return AppointmentState(phone=phone, company_id=company_id)

    def save_state(self, state: AppointmentState) -> bool:
        """
        Save state to Redis with TTL.

        Args:
            state: AppointmentState to save

        Returns:
            Success status
        """
        try:
            key = self._get_key(state.phone, state.company_id)
            state.updated_at = datetime.now()

            # Convert to dict and handle datetime serialization
            state_dict = state.model_dump()
            state_dict['created_at'] = state_dict['created_at'].isoformat()
            state_dict['updated_at'] = state_dict['updated_at'].isoformat()

            # Save with TTL
            redis_client = self._ensure_redis()
            redis_client.setex(
                key,
                self.ttl,
                json.dumps(state_dict, ensure_ascii=False)
            )

            logger.info(f"[StateManager] Saved state for {state.phone} in company {state.company_id}")
            return True

        except Exception as e:
            logger.error(f"[StateManager] Error saving state: {e}")
            return False

    def delete_state(self, phone: str, company_id: int) -> bool:
        """
        Delete state from Redis.

        Args:
            phone: Customer phone number
            company_id: Company identifier

        Returns:
            Success status
        """
        try:
            key = self._get_key(phone, company_id)
            redis_client = self._ensure_redis()
            result = redis_client.delete(key)
            logger.info(f"[StateManager] Deleted state for {phone} in company {company_id}")
            return bool(result)
        except Exception as e:
            logger.error(f"[StateManager] Error deleting state: {e}")
            return False

    def update_fields(self, phone: str, company_id: int, **fields) -> bool:
        """
        Update specific fields in the state.

        Args:
            phone: Customer phone number
            company_id: Company identifier
            **fields: Fields to update

        Returns:
            Success status
        """
        try:
            state = self.get_state(phone, company_id)

            for field, value in fields.items():
                if hasattr(state, field):
                    setattr(state, field, value)
                else:
                    # Store in context if not a direct field
                    state.context[field] = value

            return self.save_state(state)

        except Exception as e:
            logger.error(f"[StateManager] Error updating fields: {e}")
            return False

    # LangChain Memory interface implementation
    @property
    def memory_variables(self) -> List[str]:
        """Return memory variables for LangChain"""
        return [self.memory_key]

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Load state for LangChain context.

        Args:
            inputs: Must contain 'phone' and 'company_id'

        Returns:
            Dictionary with state
        """
        phone = inputs.get("phone")
        company_id = inputs.get("company_id")

        if phone and company_id:
            state = self.get_state(phone, company_id)
            return {self.memory_key: state}

        return {self.memory_key: None}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """
        Save context after LangChain execution.

        Args:
            inputs: Input context
            outputs: Output context
        """
        # Extract state from inputs if available
        if self.memory_key in inputs:
            state = inputs[self.memory_key]
            if isinstance(state, AppointmentState):
                self.save_state(state)

    def clear(self) -> None:
        """Clear all states (use with caution)"""
        pattern = f"{self.key_prefix}:*"
        redis_client = self._ensure_redis()
        for key in redis_client.scan_iter(match=pattern):
            redis_client.delete(key)
        logger.warning("[StateManager] Cleared all states")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored states"""
        pattern = f"{self.key_prefix}:*"
        redis_client = self._ensure_redis()
        keys = list(redis_client.scan_iter(match=pattern))

        return {
            "total_states": len(keys),
            "key_prefix": self.key_prefix,
            "ttl_seconds": self.ttl,
            "redis_info": redis_client.info()
        }