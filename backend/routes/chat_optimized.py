
import logging
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from backend.db import get_db
from backend.auth import get_current_user
from backend.models import Message, Client, User, Contact
from datetime import datetime
import math
from backend.ws_manager import manager
from backend.auth import (
    WebSocketAuthError,
    authenticate_websocket_access_off_loop,
    revalidate_websocket_access_off_loop,
    verify_company_access,
)
from backend.services.message_metadata import message_metadata_for_response

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

optimized_router = APIRouter()

@optimized_router.get("/messages/paged")
async def get_paged_messages(
    contact_phone: str,
    limit: int = Query(30, ge=1, le=100),
    before_id: Optional[str] = None,
    before_timestamp: Optional[int] = None,
    company_id: Optional[int] = Query(None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna mensagens paginadas para um contato específico.

    - contact_phone: número de telefone do contato
    - limit: quantidade máxima de mensagens a retornar (1-100)
    - before_id: ID da mensagem mais antiga já carregada (para paginação)
    - before_timestamp: timestamp em milissegundos (alternativa ao before_id)
    - company_id: ID da empresa (opcional, defaults to user.company_id)
    """

    # Determinar qual company_id usar
    target_company_id = user.company_id

    # Se company_id foi fornecido, verificar permissão
    if company_id:
        logger.info(f"[DEBUG] company_id fornecido: {company_id}")
        # Verifica se o usuário tem acesso a esta empresa
        has_access = await verify_company_access(str(user.id), company_id, db)
        if has_access:
            target_company_id = company_id
            logger.info(f"[DEBUG] Acesso permitido à empresa {company_id}")
        else:
            logger.warning(f"[DEBUG] Acesso negado: User {user.id} tentou acessar mensagens da empresa {company_id}")
            return {"error": "Acesso negado à empresa solicitada", "messages": []}
    else:
        logger.info(f"[DEBUG] Nenhum company_id fornecido, usando padrão: {target_company_id}")

    logger.info(f"[DEBUG] Obtendo mensagens paginadas para {user.email} - phone={contact_phone}, limit={limit}, company_id={target_company_id}")

    if not target_company_id:
        logger.error("[DEBUG] Erro: Usuário sem empresa associada")
        return {"error": "Usuário sem empresa associada", "messages": []}

    # Se for usuário não-master, pegar o client_id do master
    if hasattr(user, 'client_id'):  # Se for um User (não-master)
        client_id = user.client_id  # Usa o client_id do master
    else:  # Se for um Client (master)
        client_id = user.id

    logger.info(f"[DEBUG] Buscando mensagens: client_id={client_id}, company_id={target_company_id}, phone={contact_phone}")

    # Base query
    query = db.query(Message).filter(
        Message.client_id == client_id,
        Message.company_id == target_company_id,
        Message.contact_phone == contact_phone
    )

    # Aplicar filtro para paginação
    if before_id:
        logger.info(f"[DEBUG] Paginando com before_id={before_id}")
        # Se tiver before_id, usamos ele primeiro (mais preciso)
        before_message = db.query(Message).filter(Message.id == before_id).first()
        if before_message:
            query = query.filter(Message.id < before_id)
        else:
            logger.warning(f"[DEBUG] Mensagem com ID {before_id} não encontrada para paginação")

    elif before_timestamp:
        logger.info(f"[DEBUG] Paginando com before_timestamp={before_timestamp}")
        # Alternativa: usar timestamp
        try:
            before_date = datetime.fromtimestamp(before_timestamp / 1000.0)  # converter de ms para s
            query = query.filter(Message.timestamp < before_date)
        except Exception as e:
            logger.error(f"[DEBUG] Erro ao converter timestamp {before_timestamp}: {e}")

    # Ordenar e limitar
    total_count = query.count()
    logger.info(f"[DEBUG] Total de mensagens encontradas na query (antes do limit): {total_count}")

    messages = query.order_by(Message.timestamp.desc()).limit(limit).all()
    logger.info(f"[DEBUG] Mensagens retornadas após limit({limit}): {len(messages)}")

    # Invertemos para ordem cronológica
    messages.reverse()

    # Calcular metadados para paginação
    has_more = total_count > limit
    next_id = messages[-1].id if messages and has_more else None
    next_timestamp = int(messages[-1].timestamp.timestamp() * 1000) if messages and has_more else None

    # Log das mensagens retornadas
    if messages:
        logger.info(f"[DEBUG] Primeira mensagem (cronológica): ID={messages[0].id}, Time={messages[0].timestamp}")
        logger.info(f"[DEBUG] Última mensagem (cronológica): ID={messages[-1].id}, Time={messages[-1].timestamp}")
    else:
        logger.info("[DEBUG] Nenhuma mensagem encontrada para retornar.")

    contact_photo_row = db.query(Contact.photo).filter(
        Contact.client_id == client_id,
        Contact.company_id == target_company_id,
        Contact.phone == contact_phone
    ).first()
    contact_photo = contact_photo_row[0] if contact_photo_row and contact_photo_row[0] else ""

    result = []
    for m in messages:
        result.append({
            "id": m.id,
            "type": m.message_type,
            "content": m.content,
            "sender": {
                "phone": m.sender_phone,
                "name": m.sender_name if m.sender_name else "Unknown",
                "photo": m.photo if m.photo else (contact_photo if not m.from_me else "")
            },
            "timestamp": m.timestamp.isoformat(),
            "timestampNumber": int(m.timestamp.timestamp() * 1000),  # milissegundos
            "fromMe": m.from_me,
            "sequenceNumber": getattr(m, 'sequence_number', None),  # Caso exista esse campo
            **message_metadata_for_response(m)
        })

    return {
        "messages": result,
        "pagination": {
            "totalCount": total_count,
            "hasMore": has_more,
            "nextId": next_id,
            "nextTimestamp": next_timestamp
        }
    }

@optimized_router.websocket("/ws/unified")
async def unified_websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    company_id: int = Query(...),
    topics: str = Query("__global__")  # Tópicos separados por vírgula, padrão é global
):
    """
    Endpoint WebSocket unificado que suporta múltiplos tópicos de interesse.

    - token: token de autenticação
    - company_id: ID da empresa
    - topics: lista de tópicos separados por vírgula (phones ou "__global__")
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

        # 3) Parsear lista de tópicos
        topic_list = [t.strip() for t in topics.split(",") if t.strip()]
        if not topic_list:
            topic_list = ["__global__"]  # Fallback para global se não especificado

        logger.info(f"[WebSocket] Conectando para tópicos: {topic_list}")

        # 4) Aceitar a conexão WebSocket
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

        # 5) Registrar antes de revalidar para que todo resultado da corrida
        # seja coberto: rejeição pós-registro ou broadcast de revogação.
        connected = await manager.connect_with_access_barrier(
            websocket,
            client_id,
            company_id,
            topic_list,
            access_barrier,
            user_id=str(user_id),
            user_type=principal.user_type,
            auth_token_version=principal.auth_token_version,
        )
        if not connected:
            return

        # 6) Enviar confirmação de conexão (verificar se WebSocket ainda está aberto)
        try:
            if websocket.client_state.name == "CONNECTED":
                await websocket.send_json({
                    "type": "connection_established",
                    "company_id": company_id,
                    "client_id": client_id,
                    "topics": topic_list,
                    "timestamp": datetime.now().isoformat()
                })
        except RuntimeError:
            # WebSocket já foi fechado, ignorar silenciosamente
            pass

        try:
            # 7) Loop para receber comandos do cliente
            while True:
                # Verificar se WebSocket ainda está conectado antes de tentar receber
                if websocket.client_state.name != "CONNECTED":
                    break

                try:
                    data = await websocket.receive_json()
                    logger.info(f"[WS-Unified] Mensagem recebida: {data}")
                except RuntimeError as e:
                    if "not connected" in str(e).lower():
                        # WebSocket foi desconectado, sair do loop silenciosamente
                        break
                    else:
                        # Outro erro RuntimeError, re-lançar
                        raise

                # Processar comandos do cliente
                message_type = data.get("type")

                if message_type == "ping":
                    await websocket.send_json({"type": "pong"})

                elif message_type == "subscribe":
                    # Usuário quer se inscrever em mais tópicos
                    new_topics = [
                        str(new_topic)
                        for new_topic in data.get("topics", [])
                        if str(new_topic) not in topic_list
                    ]
                    if new_topics:
                        subscribed = await manager.connect_with_access_barrier(
                            websocket,
                            client_id,
                            company_id,
                            new_topics,
                            access_barrier,
                            user_id=str(user_id),
                            user_type=principal.user_type,
                            auth_token_version=principal.auth_token_version,
                        )
                        if not subscribed:
                            return
                        topic_list.extend(new_topics)

                    try:
                        if websocket.client_state.name == "CONNECTED":
                            await websocket.send_json({
                                "type": "subscribe_ack",
                                "topics": topic_list,
                                "timestamp": datetime.now().isoformat()
                            })
                    except RuntimeError:
                        pass

                elif message_type == "unsubscribe":
                    # Usuário quer cancelar inscrição em tópicos
                    topics_to_remove = data.get("topics", [])
                    for topic in topics_to_remove:
                        if topic in topic_list:
                            topic_list.remove(topic)
                            await manager.disconnect(websocket, client_id, company_id, topic)

                    try:
                        if websocket.client_state.name == "CONNECTED":
                            await websocket.send_json({
                                "type": "unsubscribe_ack",
                                "topics": topic_list,
                                "timestamp": datetime.now().isoformat()
                            })
                    except RuntimeError:
                        pass

                # Outros comandos podem ser implementados aqui

        except Exception as exc:
            logger.error(
                "[WebSocket-Unified] Erro durante processamento: error_type=%s",
                exc.__class__.__name__,
            )
        finally:
            # Ao cair do while, removemos do manager para todos os tópicos
            for topic in topic_list:
                await manager.disconnect(websocket, client_id, company_id, topic)

    except Exception as exc:
        logger.error(
            "[WebSocket-Unified] Erro geral: error_type=%s",
            exc.__class__.__name__,
        )
        try:
            await websocket.close(code=4000)
        except Exception:
            pass
