"""
Voice Module - Audio generation for business company agents
Modular implementation following agents_sdk architecture patterns
"""

from .models import AudioResponse, VoiceConfig, AudioRequest
from .audio_service import AudioService
from .triggers import AudioTriggers
from .tools import trigger_audio_response
from .config import get_voice_config

__all__ = [
    "AudioResponse",
    "VoiceConfig",
    "AudioRequest",
    "AudioService",
    "AudioTriggers",
    "trigger_audio_response",
    "get_voice_config"
]