"""
Audio Triggers - Logic to detect when to send audio responses
Following agents_sdk patterns for business logic separation
"""

import logging
import unicodedata
from typing import List, Optional, Dict
from dataclasses import dataclass

from .models import AudioTrigger

logger = logging.getLogger(__name__)

@dataclass
class TriggerResult:
    """Result of trigger detection"""
    should_send_audio: bool
    trigger_name: Optional[str] = None
    confidence: float = 0.0

class AudioTriggers:
    """
    Audio trigger detection system
    Determines when agent should send audio responses
    """

    def __init__(self):
        self.triggers = self._load_default_triggers()

    def _load_default_triggers(self) -> List[AudioTrigger]:
        """Load default audio triggers"""
        return [
            # Automatic long responses (>300 tokens) - HIGHEST PRIORITY
            AudioTrigger(
                trigger_name="long_response",
                keywords=["long_response"],  # Internal trigger, not text-based
                priority=1  # Highest priority (minimum allowed by Pydantic)
            ),

            # Channel configuration explicitly allows audio for this response.
            AudioTrigger(
                trigger_name="channel_audio_enabled",
                keywords=["channel_audio_enabled"],
                priority=1
            ),

            # User explicitly requests audio
            AudioTrigger(
                trigger_name="audio_requested",
                # Semantic user intent is handled by the agent tool
                # `request_whatsapp_audio_response`. This legacy trigger is kept
                # only so explicit runtime trigger_type="audio_requested" remains
                # accepted by AudioService.
                keywords=[],
                priority=2  # Second priority
            ),

            # Appointment confirmation
            AudioTrigger(
                trigger_name="confirmation_sent",
                keywords=["confirmado", "agendado", "marcado", "sua consulta"],
                priority=3
            )
        ]

    def detect_trigger(self, user_message: str, explicit_trigger: Optional[str] = None) -> TriggerResult:
        """
        Detect if audio should be sent based on user message or explicit trigger

        Args:
            user_message: User's message to analyze
            explicit_trigger: Explicitly set trigger type

        Returns:
            TriggerResult with detection info
        """

        # Handle explicit trigger (from tools or other systems)
        if explicit_trigger:
            trigger = self._get_trigger_by_name(explicit_trigger)
            if trigger:
                return TriggerResult(
                    should_send_audio=True,
                    trigger_name=explicit_trigger,
                    confidence=1.0
                )

        # Detect from user message
        user_lower = self._normalize_text(user_message)

        # Check each trigger
        for trigger in sorted(self.triggers, key=lambda x: x.priority):
            matches = sum(
                1
                for keyword in trigger.keywords
                if self._normalize_text(keyword) in user_lower
            )

            if matches > 0:
                confidence = matches / len(trigger.keywords)

                # Ativar triggers específicos
                if trigger.trigger_name in ["audio_requested", "confirmation_sent"]:
                    logger.info(f"Audio trigger detected: {trigger.trigger_name} (confidence: {confidence:.2f})")
                    return TriggerResult(
                        should_send_audio=True,
                        trigger_name=trigger.trigger_name,
                        confidence=confidence
                    )

        return TriggerResult(should_send_audio=False)

    def _get_trigger_by_name(self, trigger_name: str) -> Optional[AudioTrigger]:
        """Get trigger by name"""
        return next((t for t in self.triggers if t.trigger_name == trigger_name), None)

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Normalize text for accent-insensitive keyword matching."""
        normalized = unicodedata.normalize("NFKD", str(value or "").lower().strip())
        return normalized.encode("ascii", "ignore").decode("ascii")

    def add_custom_trigger(self, trigger: AudioTrigger) -> None:
        """Add custom trigger (future feature for per-company customization)"""
        self.triggers.append(trigger)
        self.triggers.sort(key=lambda x: x.priority)

    def get_active_triggers(self) -> List[str]:
        """Get list of active trigger names"""
        return [t.trigger_name for t in self.triggers]

    def should_send_audio_simple(self, user_message: str) -> bool:
        """Simple boolean check for MVP compatibility"""
        result = self.detect_trigger(user_message)
        return result.should_send_audio
