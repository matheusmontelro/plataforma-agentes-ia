"""
Voice Models - Pydantic models for audio system validation
Following agents_sdk patterns for type safety and validation
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field, validator
from datetime import datetime

# OpenAI TTS voice options. ElevenLabs voices use account-specific IDs, so the
# runtime voice type must remain a plain string.
OpenAITTSVoice = Literal["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]
TTSProvider = Literal["openai", "elevenlabs"]
TTSVoice = str

class VoiceConfig(BaseModel):
    """Configuration for voice generation per company"""

    voice_enabled: bool = True
    provider: TTSProvider = "openai"
    default_voice: TTSVoice = "nova"
    elevenlabs_voice_id: Optional[str] = None
    elevenlabs_voice_label: Optional[str] = None
    elevenlabs_model_id: str = "eleven_flash_v2_5"
    output_format: str = "mp3_44100_128"
    speed: float = Field(default=0.9, ge=0.25, le=4.0)
    model: str = "gpt-4o-mini-tts"
    max_text_length: int = Field(default=500, le=4096)
    triggers: List[str] = Field(default_factory=lambda: ["audio_requested"])
    stability: Optional[float] = Field(default=None, ge=0, le=1)
    similarity_boost: Optional[float] = Field(default=None, ge=0, le=1)
    style: Optional[float] = Field(default=None, ge=0, le=1)
    use_speaker_boost: Optional[bool] = None

    @validator('speed')
    def validate_speed(cls, v):
        if not 0.25 <= v <= 4.0:
            raise ValueError('Speed must be between 0.25 and 4.0')
        return v

class AudioRequest(BaseModel):
    """Request to generate audio"""

    text: str = Field(..., min_length=1, max_length=4096)
    user_message: str = Field(..., description="Original user message for trigger detection")
    company_id: int = Field(..., gt=0)
    voice_override: Optional[TTSVoice] = None
    provider_override: Optional[TTSProvider] = None
    model_override: Optional[str] = None
    output_format_override: Optional[str] = None
    speed_override: Optional[float] = Field(None, ge=0.25, le=4.0)
    trigger_type: Optional[str] = None

    class Config:
        example = {
            "text": "Seu agendamento está confirmado para amanhã às 14:00",
            "user_message": "pode mandar por áudio?",
            "company_id": 42,
            "voice_override": "nova",
            "speed_override": 0.9,
            "trigger_type": "audio_requested"
        }

class AudioResponse(BaseModel):
    """Response containing generated audio data"""

    audio_data: Optional[bytes] = None
    should_send_audio: bool = False
    trigger_detected: Optional[str] = None
    voice_used: Optional[TTSVoice] = None
    provider_used: Optional[TTSProvider] = None
    model_used: Optional[str] = None
    speed_used: Optional[float] = None
    text_processed: str = ""
    generation_time_ms: Optional[int] = None
    characters_used: Optional[int] = None
    provider_usage_units: Optional[float] = None
    provider_request_id: Optional[str] = None
    provider_metadata: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        # Don't include audio_data in JSON serialization by default
        fields = {
            'audio_data': {'exclude': True}
        }

class AudioTrigger(BaseModel):
    """Audio trigger configuration"""

    trigger_name: str
    keywords: List[str]
    priority: int = Field(default=1, ge=1, le=10)
    voice_settings: Optional[dict] = None

    class Config:
        example = {
            "trigger_name": "audio_requested",
            "keywords": ["áudio", "audio", "voz", "falando"],
            "priority": 1,
            "voice_settings": {"voice": "nova", "speed": 0.9}
        }

class VoiceStats(BaseModel):
    """Statistics for voice usage tracking"""

    company_id: int
    total_generations: int = 0
    total_bytes: int = 0
    avg_generation_time_ms: float = 0
    most_used_voice: Optional[TTSVoice] = None
    most_common_trigger: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.now)
