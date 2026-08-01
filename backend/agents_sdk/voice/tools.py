"""
Audio Tools - Function tools for agent audio control
Following agents_sdk patterns for tool implementation
"""

import logging
from typing import Optional
from agents import function_tool

from .models import TTSVoice

logger = logging.getLogger(__name__)

@function_tool
def trigger_audio_response(
    trigger_type: str = "beneficios_preparacao",
    voice_override: Optional[TTSVoice] = None,
    speed_override: Optional[float] = None
) -> str:
    """
    Tool for agent to trigger audio response generation

    Args:
        trigger_type: Type of audio trigger (audio_requested, confirmation_sent, etc.)
        voice_override: Override default voice (alloy, ash, coral, echo, fable, onyx, nova, sage, shimmer)
        speed_override: Override speed (0.25 to 4.0)

    Returns:
        Confirmation message for agent
    """

    try:
        # Validate speed
        if speed_override and not (0.25 <= speed_override <= 4.0):
            return "Erro: Velocidade deve estar entre 0.25 e 4.0"

        # Validate voice
        valid_voices = ["alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer"]
        if voice_override and voice_override not in valid_voices:
            return f"Erro: Voz deve ser uma das: {', '.join(valid_voices)}"

        # Log the trigger for manager to process
        logger.info(f"Agent triggered audio response: {trigger_type}")

        # Return confirmation to agent
        audio_msg = "Áudio será enviado"
        if voice_override:
            audio_msg += f" com voz {voice_override}"
        if speed_override:
            audio_msg += f" em velocidade {speed_override}"

        return audio_msg

    except Exception as e:
        logger.error(f"Audio tool error: {e}")
        return "Erro ao configurar áudio"

@function_tool
def check_audio_capability() -> str:
    """
    Tool for agent to check if audio generation is available

    Returns:
        Status of audio capability
    """

    import os

    if os.getenv("ELEVENLABS_API_KEY"):
        return "Sistema de áudio disponível - posso enviar respostas por voz quando solicitado"
    else:
        return "Sistema de áudio temporariamente indisponível"

@function_tool
def suggest_audio_response(reason: str = "informação importante") -> str:
    """
    Tool for agent to suggest sending audio for important information

    Args:
        reason: Reason why audio would be helpful

    Returns:
        Suggestion message
    """

    suggestions = {
        "informação importante": "Esta informação é importante - posso enviar por áudio se preferir?",
        "instruções médicas": "Para facilitar o entendimento, posso explicar por áudio se desejar",
        "confirmação agendamento": "Sua confirmação de agendamento pode ser enviada por áudio também",
        "detalhes complexos": "Como são vários detalhes, posso falar ao invés de escrever se preferir"
    }

    return suggestions.get(reason, "Posso enviar esta informação por áudio se preferir")

@function_tool
def send_beneficios_audio() -> str:
    """
    Tool específica para Etapa 3 - Benefícios e Preparação
    Agent deve chamar quando explicar benefícios/importância do tratamento

    Returns:
        Confirmação para o agent
    """
    logger.info("Agent ativou áudio para Etapa 3 - Benefícios e Preparação")
    return "Áudio será enviado para explicação dos benefícios do tratamento"

# List of all audio tools for easy import
AUDIO_TOOLS = [
    trigger_audio_response,
    check_audio_capability,
    suggest_audio_response,
    send_beneficios_audio  # Nova tool para Etapa 3
]
