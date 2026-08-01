"""
Audio Service - Core audio generation service using OpenAI TTS
Following agents_sdk service patterns for business logic encapsulation
"""

import os
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from .models import AudioRequest, AudioResponse, VoiceConfig, TTSVoice, TTSProvider
from .config import get_voice_config
from .triggers import AudioTriggers
from .gender_detection import get_assistant_voice_from_db
from backend.services.ai_provider_service import (
    AIProviderCredentialError,
    get_company_openai_api_key,
)
from backend.services.ai_credit_guard import get_ai_credit_balance

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratedAudio:
    audio_data: bytes
    metadata: Dict[str, Any] = field(default_factory=dict)


def _parse_int_header(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _audio_response_usage_fields(generated_audio: GeneratedAudio) -> Dict[str, Any]:
    metadata = generated_audio.metadata or {}
    return {
        "characters_used": metadata.get("characters_used"),
        "provider_usage_units": metadata.get("provider_usage_units"),
        "provider_request_id": metadata.get("provider_request_id"),
        "provider_metadata": metadata.get("provider_metadata"),
    }


class AudioService:
    """
    Service for generating audio responses using OpenAI TTS
    Follows agents_sdk patterns for service implementation
    """

    def __init__(
        self,
        db: Session,
        company_id: int,
        voice_config_override: Optional[Dict[str, Any]] = None
    ):
        self.db = db
        self.company_id = company_id
        self.voice_config = get_voice_config(db, company_id, voice_config_override)
        self.triggers = AudioTriggers()

    async def process_audio_request(self, request: AudioRequest, agent_result=None, force_audio: bool = False) -> AudioResponse:
        """
        Main method to process audio request following service pattern

        Args:
            request: AudioRequest with text and context
            agent_result: Agent execution result (for tool detection)
            force_audio: Force audio generation (for long responses >300 tokens)

        Returns:
            AudioResponse with audio data if generated
        """
        start_time = time.time()

        try:
            # Voice is a legacy opt-in during the BYOK migration. Enforce the
            # flag before every trigger, including the long-response shortcut,
            # so force_audio can never bypass the two preserved workspaces.
            if not self.voice_config.voice_enabled:
                logger.info("Voice disabled for company %s", self.company_id)
                return AudioResponse(
                    should_send_audio=False,
                    text_processed=request.text,
                    trigger_detected=request.trigger_type,
                    generation_time_ms=int((time.time() - start_time) * 1000),
                )

            # Step 1: Check if audio should be generated
            # Priority 1: Force audio (long responses)
            if force_audio:
                logger.info(f"Audio forced for long response (>300 tokens) - company {self.company_id}")
                # Skip to generation
                generated_audio = await self._generate_audio(request, "long_response")
                if generated_audio:
                    return AudioResponse(
                        audio_data=generated_audio.audio_data,
                        should_send_audio=True,
                        trigger_detected="long_response",
                        voice_used=self._voice_used_for_response(request),
                        provider_used=self._provider_for_request(request),
                        model_used=self._model_used_for_response(request),
                        speed_used=request.speed_override or self.voice_config.speed,
                        text_processed=request.text[:self.voice_config.max_text_length],
                        generation_time_ms=int((time.time() - start_time) * 1000),
                        **_audio_response_usage_fields(generated_audio),
                    )
                else:
                    logger.error(f"Failed to generate audio for long response - company {self.company_id}")
                    # Continue with normal flow if audio generation failed

            # Priority 2: Check for tool calls (agent explicitly requested audio)
            tool_triggered = False
            if agent_result and hasattr(agent_result, 'tool_calls'):
                audio_tools = ['trigger_audio_response']  # Only explicit audio requests
                for tool_call in agent_result.tool_calls:
                    if hasattr(tool_call, 'name') and tool_call.name in audio_tools:
                        tool_triggered = True
                        request.trigger_type = "audio_requested"
                        break

            # Then check text-based triggers
            trigger_result = self.triggers.detect_trigger(
                request.user_message,
                request.trigger_type
            )

            # Override if tool was called
            if tool_triggered:
                trigger_result.should_send_audio = True
                trigger_result.trigger_name = "beneficios_preparacao"

            if not trigger_result.should_send_audio:
                return AudioResponse(
                    should_send_audio=False,
                    text_processed=request.text,
                    generation_time_ms=int((time.time() - start_time) * 1000)
                )

            # Step 2: Generate audio
            generated_audio = await self._generate_audio(request, trigger_result.trigger_name)

            if generated_audio is None:
                return AudioResponse(
                    should_send_audio=False,
                    text_processed=request.text,
                    trigger_detected=trigger_result.trigger_name,
                    error="Audio generation failed",
                    generation_time_ms=int((time.time() - start_time) * 1000)
                )

            # Step 3: Success response
            generation_time = int((time.time() - start_time) * 1000)

            return AudioResponse(
                audio_data=generated_audio.audio_data,
                should_send_audio=True,
                trigger_detected=trigger_result.trigger_name,
                voice_used=self._voice_used_for_response(request),
                provider_used=self._provider_for_request(request),
                model_used=self._model_used_for_response(request),
                speed_used=request.speed_override or self.voice_config.speed,
                text_processed=request.text[:self.voice_config.max_text_length],
                generation_time_ms=generation_time,
                **_audio_response_usage_fields(generated_audio),
            )

        except Exception as e:
            logger.error(
                "Audio service error for company %s: %s",
                self.company_id,
                type(e).__name__,
            )
            return AudioResponse(
                should_send_audio=False,
                text_processed=request.text,
                error="Não foi possível gerar o áudio",
                generation_time_ms=int((time.time() - start_time) * 1000)
            )

    async def _generate_audio(self, request: AudioRequest, trigger_name: str) -> Optional[GeneratedAudio]:
        """Generate audio using the configured TTS provider."""
        provider = self._provider_for_request(request)

        if provider == "elevenlabs":
            if get_ai_credit_balance(self.db, self.company_id) <= 0:
                logger.warning(
                    "Legacy ElevenLabs allowance exhausted for company %s",
                    self.company_id,
                )
                return None
            return await self._generate_audio_elevenlabs(request, trigger_name)

        return await self._generate_audio_openai(request, trigger_name)

    async def _generate_audio_openai(self, request: AudioRequest, trigger_name: str) -> Optional[GeneratedAudio]:
        """Generate audio using OpenAI TTS."""

        try:
            api_key = get_company_openai_api_key(self.db, self.company_id)
        except AIProviderCredentialError:
            logger.warning(
                "OpenAI API key not configured for company %s",
                self.company_id,
            )
            return None

        try:
            # Dynamic import for OpenAI
            import openai

            client = openai.AsyncOpenAI(api_key=api_key)

            # Prepare text for TTS (just the content, no instructions)
            audio_text = request.text[:self.voice_config.max_text_length]

            # Voice selection priority: request override > gender-based > config > default
            if request.voice_override:
                voice = request.voice_override
            else:
                # Use LLM to detect gender and select appropriate voice
                voice = await get_assistant_voice_from_db(
                    self.db,
                    self.company_id,
                    self.voice_config.default_voice
                )

            # Speed selection
            speed = (
                request.speed_override or
                self.voice_config.speed
            )

            # Generate audio with PT-BR instructions
            logger.info(f"Generating OpenAI audio for company {self.company_id} - trigger: {trigger_name}, voice: {voice}")

            response = await client.audio.speech.create(
                model=self.voice_config.model,
                voice=voice,
                input=audio_text,
                response_format="mp3",
                speed=speed,
                extra_body={
                    "instructions": "Fale em português brasileiro claro e natural, com sotaque brasileiro."
                }
            )

            audio_bytes = response.content
            logger.info(f"OpenAI audio generated successfully - {len(audio_bytes)} bytes")

            return GeneratedAudio(
                audio_data=audio_bytes,
                metadata={
                    "characters_used": len(audio_text),
                    "provider_metadata": {
                        "provider": "openai",
                        "voice": voice,
                    },
                },
            )

        except Exception as e:
            logger.error(
                "OpenAI TTS generation failed: %s",
                type(e).__name__,
            )
            return None

    async def _generate_audio_elevenlabs(self, request: AudioRequest, trigger_name: str) -> Optional[GeneratedAudio]:
        """Generate audio using ElevenLabs TTS."""
        elevenlabs_token = os.getenv("ELEVENLABS_API_KEY")
        if not elevenlabs_token:
            logger.warning("ElevenLabs API key not found")
            return None

        voice_id = request.voice_override or self.voice_config.elevenlabs_voice_id
        if not voice_id:
            logger.warning("ElevenLabs voice_id not configured for company %s", self.company_id)
            return None

        try:
            import httpx

            audio_text = request.text[:self.voice_config.max_text_length]
            model_id = request.model_override or self.voice_config.elevenlabs_model_id
            output_format = request.output_format_override or self.voice_config.output_format

            voice_settings = self._elevenlabs_voice_settings()
            payload: Dict[str, Any] = {
                "text": audio_text,
                "model_id": model_id,
                "language_code": "pt"
            }
            if voice_settings:
                payload["voice_settings"] = voice_settings

            logger.info(
                "Generating ElevenLabs audio for company %s - trigger: %s, voice_label: %s",
                self.company_id,
                trigger_name,
                self.voice_config.elevenlabs_voice_label or "configured_voice",
            )

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    params={"output_format": output_format},
                    headers={
                        "xi-api-key": elevenlabs_token,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    json=payload,
                )
                response.raise_for_status()

            audio_bytes = response.content
            character_count = _parse_int_header(response.headers.get("x-character-count"))
            request_id = (
                response.headers.get("request-id")
                or response.headers.get("x-request-id")
                or response.headers.get("xi-request-id")
            )
            logger.info("ElevenLabs audio generated successfully - %s bytes", len(audio_bytes))
            return GeneratedAudio(
                audio_data=audio_bytes,
                metadata={
                    "characters_used": character_count or len(audio_text),
                    "provider_usage_units": character_count,
                    "provider_request_id": request_id,
                    "provider_metadata": {
                        "provider": "elevenlabs",
                        "voice_id": voice_id,
                        "model_id": model_id,
                        "output_format": output_format,
                    },
                },
            )

        except Exception as e:
            logger.error(
                "ElevenLabs TTS generation failed: %s",
                type(e).__name__,
            )
            return None

    def _provider_for_request(self, request: AudioRequest) -> TTSProvider:
        provider = request.provider_override or self.voice_config.provider
        return provider if provider in {"openai", "elevenlabs"} else "openai"

    def _voice_used_for_response(self, request: AudioRequest) -> str:
        if self._provider_for_request(request) == "elevenlabs":
            return request.voice_override or self.voice_config.elevenlabs_voice_id or ""
        return request.voice_override or self.voice_config.default_voice

    def _model_used_for_response(self, request: AudioRequest) -> str:
        if self._provider_for_request(request) == "elevenlabs":
            return request.model_override or self.voice_config.elevenlabs_model_id
        return request.model_override or self.voice_config.model

    def _elevenlabs_voice_settings(self) -> Dict[str, Any]:
        settings: Dict[str, Any] = {}
        if self.voice_config.stability is not None:
            settings["stability"] = self.voice_config.stability
        if self.voice_config.similarity_boost is not None:
            settings["similarity_boost"] = self.voice_config.similarity_boost
        if self.voice_config.style is not None:
            settings["style"] = self.voice_config.style
        if self.voice_config.use_speaker_boost is not None:
            settings["use_speaker_boost"] = self.voice_config.use_speaker_boost
        return settings

    def get_voice_config(self) -> VoiceConfig:
        """Get current voice configuration"""
        return self.voice_config

    async def test_voice_generation(self, test_text: str = "Teste de áudio") -> AudioResponse:
        """Test voice generation for debugging"""
        request = AudioRequest(
            text=test_text,
            user_message="teste de áudio",
            company_id=self.company_id,
            trigger_type="audio_requested"
        )

        return await self.process_audio_request(request)
