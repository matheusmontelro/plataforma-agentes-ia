"""
Z-API Integration for Audio Sending
Integrates voice module with existing Z-API infrastructure
"""

import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def convert_audio_to_base64(audio_bytes: bytes) -> str:
    """
    Convert audio bytes to base64 format required by Z-API

    Args:
        audio_bytes: Raw audio bytes (MP3)

    Returns:
        Base64 encoded audio with proper data URI format
    """
    try:
        # Encode to base64
        base64_audio = base64.b64encode(audio_bytes).decode('utf-8')

        # Add proper data URI prefix for MP3
        data_uri = f"data:audio/mpeg;base64,{base64_audio}"

        logger.info(f"Audio converted to base64 - size: {len(audio_bytes)} bytes")
        return data_uri

    except Exception as e:
        logger.error(f"Error converting audio to base64: {e}")
        raise

def prepare_zapi_audio_body(phone: str, audio_bytes: bytes) -> dict:
    """
    Prepare Z-API audio body from audio bytes

    Args:
        phone: Target phone number
        audio_bytes: Audio data in bytes

    Returns:
        Dict ready for Z-API send-audio endpoint
    """

    # Convert to base64
    audio_base64 = convert_audio_to_base64(audio_bytes)

    # Prepare Z-API body
    body = {
        "phone": phone,
        "audio": audio_base64,
        "viewOnce": False,
        "delayMessage": 1000,  # 1 second delay
        "delayTyping": 2000,   # 2 second typing indicator
        "waveform": True       # Show waveform in WhatsApp
    }

    return body

async def send_audio_via_zapi(
    phone: str,
    audio_bytes: bytes,
    instance_id: str,
    instance_token: str
) -> bool:
    """
    Send audio via Z-API (wrapper for existing function)

    Args:
        phone: Target phone
        audio_bytes: Audio data
        instance_id: Z-API instance ID
        instance_token: Z-API token

    Returns:
        True if sent successfully
    """
    try:
        # Import existing Z-API function
        from backend.routes.webhook import send_audio_to_zapi, WhatsAppSendAudioBody

        # Prepare audio body
        audio_body_dict = prepare_zapi_audio_body(phone, audio_bytes)

        # Create Pydantic model
        audio_body = WhatsAppSendAudioBody(**audio_body_dict)

        # Send via existing function
        result = send_audio_to_zapi(instance_id, instance_token, audio_body)

        if result and result.status_code == 200:
            logger.info(f"Audio sent successfully to {phone}")
            return True
        else:
            logger.error(f"Failed to send audio - Z-API response: {result}")
            return False

    except Exception as e:
        logger.error(f"Error sending audio via Z-API: {e}")
        return False