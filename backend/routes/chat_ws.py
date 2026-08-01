import logging
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional

from backend.ws_manager import manager
from backend.auth import (
    WebSocketAuthError,
    authenticate_websocket_access_off_loop,
    revalidate_websocket_access_off_loop,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

chat_router = APIRouter()

@chat_router.websocket("/ws/chat")
async def chat_websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    company_id: int = Query(...),
    phone: str = Query(...)
):
    """
    Endpoint WebSocket para chat em tempo real.
    - Se phone != 'ALL': é uma conexão normal, focada em um contato específico.
    - Se phone == 'ALL': é a conexão 'global' que recebe mensagens de todos os contatos.
    Autentica o usuário, valida se ele tem acesso à company_id,
    registra no manager e fica aguardando mensagens do front.
    """
    try:
        try:
            token = token or websocket.cookies.get("access_token")
            if not token:
                await websocket.close(code=403)
                return
            principal = await authenticate_websocket_access_off_loop(
                token,
                company_id,
            )
        except WebSocketAuthError as exc:
            logger.warning(
                "[WebSocket] Autenticação recusada: close_code=%s",
                exc.code,
            )
            await websocket.close(code=exc.code)
            return
        except Exception as exc:
            logger.error(
                "[WebSocket] Erro de autenticação: error_type=%s",
                exc.__class__.__name__,
            )
            await websocket.close(code=403)
            return

        if principal is None:
            logger.error(f"[WebSocket] Acesso negado company_id={company_id}")
            await websocket.close(code=403)
            return
        user_id = principal.user_id
        client_id = principal.client_id

        # 3) Aceitar a conexão WebSocket
        await websocket.accept()

        async def access_barrier() -> Optional[int]:
            fresh_principal = await revalidate_websocket_access_off_loop(
                token,
                company_id,
                expected_user_id=user_id,
                expected_client_id=client_id,
            )
            return (
                int(fresh_principal.operational_epoch)
                if fresh_principal is not None
                and fresh_principal.operational_epoch is not None
                else None
            )

        # Registrar antes da revalidação fecha a janela com a publicação de
        # revogação: a conexão sempre será rejeitada ou alcançada pelo broadcast.
        connected = await manager.connect_with_access_barrier(
            websocket,
            client_id,
            company_id,
            [phone],
            access_barrier,
            user_id=str(user_id),
            user_type=principal.user_type,
            auth_token_version=principal.auth_token_version,
        )
        if not connected:
            return

        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.send_json({
                    "type": "connection_established",
                    "company_id": company_id,
                    "client_id": client_id,
                    "phone": phone,
                    "timestamp": datetime.now().isoformat(),
                })
        except RuntimeError:
            pass

        try:
            # 5) Loop para receber mensagens do front (opcional)
            while True:
                data = await websocket.receive_json()
                logger.info(f"[WS] Mensagem recebida do front (phone={phone}): {data}")
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

        except WebSocketDisconnect:
            logger.info(f"[WebSocket] Desconexão (phone={phone}).")
        finally:
            # Ao cair do while, removemos do manager
            await manager.disconnect(websocket, client_id, company_id, phone)

    except Exception as exc:
        logger.error(
            "[WebSocket] Erro geral: error_type=%s",
            exc.__class__.__name__,
        )
        try:
            await websocket.close(code=4000)
        except Exception:
            pass
