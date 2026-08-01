"""
Voice Configuration - Configuration management for voice system
Following agents_sdk patterns for configuration handling
"""

import logging
import os
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from .models import VoiceConfig

logger = logging.getLogger(__name__)

def get_voice_config(
    db: Session,
    company_id: int,
    voice_override: Optional[Dict[str, Any]] = None
) -> VoiceConfig:
    """
    Get voice configuration for company - defined in code

    Args:
        db: Database session (unused, kept for compatibility)
        company_id: Company ID

    Returns:
        VoiceConfig based on company_id
    """

    active_workforce_config = _load_voice_config_from_agent_workforce(
        db,
        company_id,
    )
    base_config = active_workforce_config or (
        _load_voice_config_from_agent_configuration(db, company_id)
        or _get_company_default_voice_config(company_id)
    )
    if active_workforce_config is None:
        # Legacy prompt preferences may retain voice/provider details, but they
        # are not proof that an agent was one of the already-active exceptions.
        base_config = base_config.model_copy(update={"voice_enabled": False})
    if voice_override:
        resolved = _apply_voice_override(base_config, voice_override)
        if (
            active_workforce_config is None
            or resolved.provider != "elevenlabs"
        ):
            return resolved.model_copy(update={"voice_enabled": False})
        return resolved
    return base_config

def get_default_voice_config() -> VoiceConfig:
    """Get default voice configuration"""
    default_provider = os.getenv("AGENTS_SDK_TTS_PROVIDER")
    if not default_provider:
        default_provider = "elevenlabs" if os.getenv("ELEVENLABS_DEFAULT_VOICE_ID") else "openai"

    return VoiceConfig(
        # Voice is opt-in. Existing workforces with allow_audio=true are
        # re-enabled below; every other company remains text-only.
        voice_enabled=False,
        provider=default_provider if default_provider in {"openai", "elevenlabs"} else "openai",
        default_voice="nova",  # Friendly female voice for companies
        elevenlabs_voice_id=os.getenv("ELEVENLABS_DEFAULT_VOICE_ID"),
        elevenlabs_voice_label=os.getenv("ELEVENLABS_DEFAULT_VOICE_LABEL"),
        elevenlabs_model_id=os.getenv("ELEVENLABS_TTS_MODEL_ID", "eleven_flash_v2_5"),
        output_format=os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128"),
        speed=0.9,  # Slightly slower for clarity
        model="gpt-4o-mini-tts",  # Updated to use gpt-4o-mini-tts
        max_text_length=4096,  # Maximum allowed to prevent audio truncation
        triggers=["beneficios_preparacao"]  # Updated for Etapa 3
    )

def _get_company_default_voice_config(company_id: int) -> VoiceConfig:
    """Return provider-neutral defaults when no saved config exists."""
    return get_default_voice_config()

def _load_voice_config_from_agent_configuration(db: Session, company_id: int) -> Optional[VoiceConfig]:
    """Read optional voice preferences from the legacy agent configuration JSON."""
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
                SELECT assistant_tone_and_voice
                FROM agent_configurations
                WHERE company_id = :company_id
                LIMIT 1
            """),
            {"company_id": company_id}
        ).fetchone()
        if not result or not isinstance(result.assistant_tone_and_voice, dict):
            return None

        voice_config = result.assistant_tone_and_voice.get("audio_voice")
        if not isinstance(voice_config, dict):
            return None

        return _apply_voice_override(get_default_voice_config(), voice_config)
    except Exception as exc:
        logger.warning("Could not load voice config for company %s: %s", company_id, exc)
        return None


def _load_voice_config_from_agent_workforce(db: Session, company_id: int) -> Optional[VoiceConfig]:
    """Read voice preferences from the latest active AgentWorkforce root agent."""
    try:
        from sqlalchemy import text

        result = db.execute(
            text("""
                SELECT root_agent_key, agent_configs
                FROM agent_workforces
                WHERE company_id = :company_id
                  AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
            """),
            {"company_id": company_id}
        ).fetchone()
        if not result or not isinstance(result.agent_configs, dict):
            return None

        root_key = result.root_agent_key or next(iter(result.agent_configs.keys()), None)
        agent_config = result.agent_configs.get(root_key) if root_key else None
        if not isinstance(agent_config, dict):
            return None

        channel = agent_config.get("channel")
        if not isinstance(channel, dict) or not channel.get("allow_audio"):
            return None

        voice_config = channel.get("voice")
        if not isinstance(voice_config, dict):
            return None
        provider = str(voice_config.get("provider") or "").strip().lower()
        if provider != "elevenlabs":
            return None

        return _apply_voice_override(
            get_default_voice_config(),
            {**voice_config, "voice_enabled": True},
        )
    except Exception as exc:
        logger.warning("Could not load AgentWorkforce voice config for company %s: %s", company_id, exc)
        return None


def _apply_voice_override(base_config: VoiceConfig, voice_override: Dict[str, Any]) -> VoiceConfig:
    """Merge a frontend voice config into a VoiceConfig instance."""
    provider = str(voice_override.get("provider") or base_config.provider).strip()
    if provider not in {"openai", "elevenlabs"}:
        provider = base_config.provider

    voice_id = str(voice_override.get("voice_id") or "").strip()
    label = str(voice_override.get("label") or "").strip()
    model_id = str(voice_override.get("model_id") or "").strip()
    output_format = str(voice_override.get("output_format") or "").strip()

    return base_config.model_copy(update={
        "voice_enabled": bool(
            voice_override.get(
                "voice_enabled",
                voice_override.get("enabled", base_config.voice_enabled),
            )
        ),
        "provider": provider,
        "default_voice": voice_id if provider == "openai" and voice_id else base_config.default_voice,
        "elevenlabs_voice_id": voice_id if provider == "elevenlabs" else base_config.elevenlabs_voice_id,
        "elevenlabs_voice_label": label or base_config.elevenlabs_voice_label,
        "elevenlabs_model_id": model_id or base_config.elevenlabs_model_id,
        "output_format": output_format or base_config.output_format,
        "stability": voice_override.get("stability", base_config.stability),
        "similarity_boost": voice_override.get("similarity_boost", base_config.similarity_boost),
        "style": voice_override.get("style", base_config.style),
        "use_speaker_boost": voice_override.get("use_speaker_boost", base_config.use_speaker_boost),
    })

def get_company_voice_preferences(company_id: int) -> Dict[str, Any]:
    """
    Get voice preferences based on company type/specialty
    Future feature for automatic voice selection

    Args:
        company_id: Company ID

    Returns:
        Dict with voice preferences
    """

    # Default preferences (can be expanded based on company data)
    preferences = {
        "family_company": {
            "voice": "nova",
            "speed": 0.9,
            "instructions": "Fale de forma carinhosa e acolhedora"
        },
        "corporate_company": {
            "voice": "alloy",
            "speed": 1.0,
            "instructions": "Fale de forma profissional e objetiva"
        },
        "specialized_company": {
            "voice": "fable",
            "speed": 0.95,
            "instructions": "Fale com autoridade técnica mas acessível"
        }
    }

    # For MVP, return default
    return preferences.get("family_company", preferences["family_company"])
