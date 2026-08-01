"""
Runtime audio delivery tools for frontend-created WhatsApp agents.

The tool does not generate audio itself. It records the agent's semantic
decision in the run context so the FlowBuilder runtime can render the final
answer as TTS through the existing audio pipeline.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List

from agents import RunContextWrapper, function_tool
from pydantic import Field


AUDIO_REQUEST_TRIGGER = "audio_requested"
AUDIO_REQUEST_DELIVERY_MODE = "llm_requested_full"


def record_audio_delivery_request(
    runtime_context: Any,
    *,
    spoken_text: str = "",
    reason: str = "",
) -> Dict[str, Any]:
    """Mark the current agent run so the final answer is rendered as audio."""

    request = {
        "trigger_type": AUDIO_REQUEST_TRIGGER,
        "delivery_mode": AUDIO_REQUEST_DELIVERY_MODE,
        "spoken_text": str(spoken_text or "").strip(),
        "reason": str(reason or "").strip(),
        "source": "agent_tool",
    }

    if runtime_context is not None:
        setattr(runtime_context, "audio_delivery_request", request)
        calls = getattr(runtime_context, "audio_delivery_tool_calls", None)
        if not isinstance(calls, list):
            calls = []
            setattr(runtime_context, "audio_delivery_tool_calls", calls)
        calls.append(request)

    return request


def create_audio_delivery_tools() -> List[Any]:
    """Create audio delivery tools attached only to audio-capable agents."""

    @function_tool
    async def request_whatsapp_audio_response(
        context: RunContextWrapper,
        spoken_text: Annotated[
            str,
            Field(
                description=(
                    "Texto exato que deve ser falado no audio. Pode ficar vazio "
                    "quando a resposta final do agente ja sera o conteudo falado."
                )
            ),
        ] = "",
        reason: Annotated[
            str,
            Field(
                description=(
                    "Motivo curto para enviar audio, por exemplo pedido direto "
                    "do usuario ou aceite de uma oferta anterior."
                )
            ),
        ] = "",
    ) -> Dict[str, Any]:
        """
        Solicita que a runtime envie a resposta atual como audio no WhatsApp.

        Use quando o usuario pedir para ouvir, pedir audio, aceitar receber audio
        ou preferir resposta falada. Depois de chamar, escreva a resposta final
        com o conteudo natural que deve ser falado.
        """

        runtime_context = getattr(context, "context", None)
        request = record_audio_delivery_request(
            runtime_context,
            spoken_text=spoken_text,
            reason=reason,
        )
        return {
            "success": True,
            "trigger_type": request["trigger_type"],
            "delivery_mode": request["delivery_mode"],
            "message_for_agent": (
                "A proxima resposta final sera renderizada como audio. "
                "Escreva somente o conteudo natural que deve ser falado; "
                "nao use placeholders e nao diga que nao consegue enviar audio."
            ),
        }

    return [request_whatsapp_audio_response]
