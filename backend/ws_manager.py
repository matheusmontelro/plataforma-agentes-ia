import json
import asyncio
import inspect
import os
import threading
import time
import redis.asyncio as aioredis
from collections import deque
from concurrent.futures import Future as ConcurrentFuture, ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Deque, Dict, FrozenSet, List, Optional, Tuple
from fastapi import WebSocket
from asyncio import Lock
import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.events.websocket_channels import (
    strip_websocket_channel_namespace,
    websocket_channel,
    websocket_channel_namespace,
    websocket_redis_url,
)
from backend.services.company_access_control import (
    CompanyOperationalLockBusyError,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _bounded_int_env(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        configured = int(os.getenv(name, str(default)).strip())
    except ValueError:
        configured = default
    return max(minimum, min(configured, maximum))

FLOW_BUILDER_WHATSAPP_TOPIC = "__flow_builder_whatsapp__"
WEBSOCKET_SEND_TIMEOUT_SECONDS = 5.0
WEBSOCKET_CLOSE_TIMEOUT_SECONDS = 2.0
REDIS_REVOCATION_PUBLISH_TIMEOUT_SECONDS = 1.0
REDIS_PUBLISH_TIMEOUT_SECONDS = 1.0
REDIS_START_TIMEOUT_SECONDS = 1.0
COMPANY_BROADCAST_WAIT_TIMEOUT_SECONDS = 6.0
ACCESS_FENCE_RETRY_ATTEMPTS = 4
ACCESS_FENCE_RETRY_DELAY_SECONDS = 0.05
EVENT_DEDUPE_TTL_SECONDS = 120.0
EVENT_DEDUPE_MAX_ENTRIES = 4096
REDIS_COMPANY_QUEUE_MAXSIZE = _bounded_int_env(
    "WEBSOCKET_REDIS_QUEUE_MAXSIZE",
    256,
    minimum=1,
    maximum=4096,
)
REDIS_DISPATCH_MAX_CONCURRENCY = 8
REDIS_BUSY_REQUEUE_LOG_INTERVAL = 3
REDIS_BUSY_REQUEUE_DELAY_SECONDS = 0.1
REDIS_BUSY_REQUEUE_MAX_DELAY_SECONDS = 2.0
REDIS_COMPANY_OVERFLOW_WARN_SIZE = 1024
REDIS_COMPANY_OVERFLOW_MAXSIZE = _bounded_int_env(
    "WEBSOCKET_REDIS_OVERFLOW_MAXSIZE",
    1024,
    minimum=0,
    maximum=16384,
)
REDIS_GLOBAL_QUEUE_MAXSIZE = _bounded_int_env(
    "WEBSOCKET_REDIS_GLOBAL_QUEUE_MAXSIZE",
    8192,
    minimum=1,
    maximum=65536,
)
REDIS_ACTIVE_COMPANY_MAXSIZE = _bounded_int_env(
    "WEBSOCKET_REDIS_ACTIVE_COMPANY_MAXSIZE",
    512,
    minimum=1,
    maximum=4096,
)
WEBSOCKET_AUTH_EXECUTOR_WORKERS = _bounded_int_env(
    "WEBSOCKET_AUTH_EXECUTOR_WORKERS",
    4,
    minimum=1,
    maximum=8,
)
WEBSOCKET_STOP_TIMEOUT_SECONDS = 5.0

# A holder worker opens, validates, keeps and closes each SQLAlchemy Session on
# the same thread. It is isolated from AnyIO worker threads and waits only on a
# threading.Event while the event loop performs the bounded socket send.
_FENCE_PREPARE_EXECUTOR = ThreadPoolExecutor(
    max_workers=WEBSOCKET_AUTH_EXECUTOR_WORKERS,
    thread_name_prefix="ws-auth-fence",
)

BROADCAST_DELIVERED = "delivered"
BROADCAST_NO_LOCAL_SOCKET = "no_local_socket"
BROADCAST_DEDUPLICATED = "deduplicated"
BROADCAST_BUSY = "busy"
BROADCAST_FAILED = "failed"

@dataclass
class WSConnection:
    websocket: WebSocket
    client_id: str
    company_id: int
    phone: str
    connected_at: datetime
    user_id: Optional[str] = None
    user_type: Optional[str] = None
    auth_token_version: Optional[int] = None
    access_epoch: Optional[int] = None


@dataclass
class _RedisDispatchItem:
    company_id: int
    channel: str
    steps: List[Tuple[str, Dict[str, Any]]]
    step_index: int = 0
    busy_requeues: int = 0


@dataclass(frozen=True)
class _PreparedCompanyAccessFence:
    current_epoch: int
    active_connection_ids: FrozenSet[int]


@dataclass(eq=False)
class _CompanyAccessFenceHandle:
    prepared: ConcurrentFuture = field(default_factory=ConcurrentFuture)
    release_event: threading.Event = field(default_factory=threading.Event)
    completion: Optional[asyncio.Future] = None

class ConnectionManager:
    def __init__(self):
        """
        Estrutura de dados para armazenar conexões no formato:
        self.connections[company_id][client_id][topic] = [lista de WSConnection]
        onde topic pode ser phone ou "__global__"
        """
        self.connections: Dict[int, Dict[str, Dict[str, List[WSConnection]]]] = {}
        self.lock = Lock()
        self.redis: Optional[aioredis.Redis] = None
        self.task: Optional[asyncio.Task] = None
        self.reconciliation_task: Optional[asyncio.Task] = None
        self._pubsub = None
        self._stop_task: Optional[asyncio.Task] = None
        self._stopped = False
        self._stopping = False
        self.websocket_send_timeout_seconds = WEBSOCKET_SEND_TIMEOUT_SECONDS
        self.websocket_close_timeout_seconds = WEBSOCKET_CLOSE_TIMEOUT_SECONDS
        self.redis_publish_timeout_seconds = REDIS_PUBLISH_TIMEOUT_SECONDS
        self.company_broadcast_wait_timeout_seconds = (
            COMPANY_BROADCAST_WAIT_TIMEOUT_SECONDS
        )
        self.access_fence_retry_attempts = ACCESS_FENCE_RETRY_ATTEMPTS
        self.access_fence_retry_delay_seconds = ACCESS_FENCE_RETRY_DELAY_SECONDS
        self._company_operation_locks: Dict[int, Lock] = {}
        self._recent_event_ids: Dict[str, float] = {}
        self.websocket_channel_namespace = websocket_channel_namespace()
        self.redis_company_queue_maxsize = REDIS_COMPANY_QUEUE_MAXSIZE
        self.redis_company_overflow_maxsize = REDIS_COMPANY_OVERFLOW_MAXSIZE
        self.redis_global_queue_maxsize = REDIS_GLOBAL_QUEUE_MAXSIZE
        self.redis_active_company_maxsize = REDIS_ACTIVE_COMPANY_MAXSIZE
        self.redis_busy_requeue_log_interval = REDIS_BUSY_REQUEUE_LOG_INTERVAL
        self.redis_busy_requeue_delay_seconds = (
            REDIS_BUSY_REQUEUE_DELAY_SECONDS
        )
        self.redis_busy_requeue_max_delay_seconds = (
            REDIS_BUSY_REQUEUE_MAX_DELAY_SECONDS
        )
        self._redis_dispatch_semaphore = asyncio.Semaphore(
            REDIS_DISPATCH_MAX_CONCURRENCY
        )
        self._redis_company_queues: Dict[int, asyncio.Queue] = {}
        self._redis_company_overflows: Dict[
            int,
            Deque[_RedisDispatchItem],
        ] = {}
        self._redis_company_tasks: Dict[int, asyncio.Task] = {}
        self._redis_company_inflight: Dict[int, _RedisDispatchItem] = {}
        self._redis_pending_items = 0
        self._redis_revocation_tasks: set[asyncio.Task] = set()
        self._redis_overload_tasks: Dict[int, asyncio.Task] = {}
        self._redis_overloaded_companies: set[int] = set()
        self._active_fence_handles: set[_CompanyAccessFenceHandle] = set()

    def _websocket_channel(self, logical_channel: str) -> str:
        return websocket_channel(
            logical_channel,
            namespace=self.websocket_channel_namespace,
        )

    def _company_operation_lock(self, company_id: int) -> Lock:
        """Return the process-local serializer for one company."""
        normalized_company_id = int(company_id)
        lock = self._company_operation_locks.get(normalized_company_id)
        if lock is None:
            lock = Lock()
            self._company_operation_locks[normalized_company_id] = lock
        return lock

    def claim_event_for_local_delivery(
        self,
        channel: str,
        data: Dict[str, Any],
    ) -> bool:
        """Claim one event for Redis or ambiguous-publish local fallback.

        The public claim lets a local fallback share the exact same dedupe key
        as the Redis listener.  If ``PUBLISH`` was accepted but its response
        timed out, whichever path claims first delivers and the other becomes
        a no-op.
        """
        event_id = data.get("event_id")
        if event_id is None or str(event_id).strip() == "":
            return True

        loop_time = time.monotonic()
        cache_key = f"{channel}:{event_id}"
        expires_at = self._recent_event_ids.get(cache_key)
        if expires_at is not None and expires_at > loop_time:
            return False

        if len(self._recent_event_ids) >= EVENT_DEDUPE_MAX_ENTRIES:
            self._recent_event_ids = {
                key: expiration
                for key, expiration in self._recent_event_ids.items()
                if expiration > loop_time
            }
            if len(self._recent_event_ids) >= EVENT_DEDUPE_MAX_ENTRIES:
                oldest_key = min(
                    self._recent_event_ids,
                    key=self._recent_event_ids.__getitem__,
                )
                self._recent_event_ids.pop(oldest_key, None)

        self._recent_event_ids[cache_key] = loop_time + EVENT_DEDUPE_TTL_SECONDS
        return True

    def _claim_event_id(self, channel: str, data: Dict[str, Any]) -> bool:
        """Compatibility alias for callers/tests predating the public claim."""
        return self.claim_event_for_local_delivery(channel, data)

    def release_event_delivery_claim(
        self,
        channel: str,
        data: Dict[str, Any],
    ) -> None:
        """Undo a synchronous reservation when no delivery path retained it."""
        event_id = data.get("event_id")
        if event_id is None or str(event_id).strip() == "":
            return
        self._recent_event_ids.pop(f"{channel}:{event_id}", None)

    async def _publish_redis(self, channel: str, payload: str) -> None:
        """Publish without allowing a slow Redis connection to stall a request."""
        if self.redis is None:
            raise RuntimeError("redis_not_connected")
        await asyncio.wait_for(
            self.redis.publish(channel, payload),
            timeout=self.redis_publish_timeout_seconds,
        )

    def _mask_phone(self, phone: str) -> str:
        digits = ''.join(ch for ch in str(phone) if ch.isdigit())
        if not digits:
            return "n/a"
        if len(digits) <= 4:
            return "***"
        return f"{digits[:2]}***{digits[-2:]}"

    def _build_whatsapp_trigger_payload(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        phone = str(data.get('phone') or '').strip()
        if not phone:
            return None

        text_payload = data.get('text')
        if isinstance(text_payload, dict):
            body = str(text_payload.get('message') or data.get('content') or '')
        elif isinstance(text_payload, str):
            body = text_payload
        else:
            body = str(data.get('content') or '')

        message_type = str(data.get('type') or 'text')
        media_url = ''

        if isinstance(data.get('image'), dict):
            media_url = str(data['image'].get('imageUrl') or '')
        elif isinstance(data.get('video'), dict):
            media_url = str(data['video'].get('videoUrl') or '')
        elif isinstance(data.get('audio'), dict):
            media_url = str(data['audio'].get('audioUrl') or '')

        trigger_timestamp = data.get('momment') or data.get('timestamp')
        if not trigger_timestamp:
            tz_sp = ZoneInfo("America/Sao_Paulo")
            trigger_timestamp = datetime.now(tz_sp).isoformat(timespec='seconds')

        return {
            "phone": phone,
            "name": str(data.get('senderName') or data.get('chatName') or ''),
            "body": body,
            "type": message_type,
            "mediaUrl": media_url,
            "timestamp": trigger_timestamp,
            "provider": str(data.get('provider') or 'unknown'),
            "raw": data
        }

    async def start(self):
        """Inicia a conexão com Redis e o listener de mensagens."""
        if self._stopping or self._stopped:
            return
        self._stopping = False
        self._stopped = False
        if self._stop_task is not None and self._stop_task.done():
            self._stop_task = None
        if self.reconciliation_task is None or self.reconciliation_task.done():
            self.reconciliation_task = asyncio.create_task(
                self._reconcile_access_loop()
            )
        redis_client = None
        listener_ready = None
        try:
            logger.info("[WebSocket] Iniciando conexão com Redis...")
            redis_client = aioredis.from_url(websocket_redis_url())
            self.redis = redis_client
            await asyncio.wait_for(
                redis_client.ping(),
                timeout=REDIS_START_TIMEOUT_SECONDS,
            )
            if self._stopping or self._stopped:
                await self._close_redis_resource(redis_client)
                if self.redis is redis_client:
                    self.redis = None
                return
            logger.info("[WebSocket] Conexão com Redis estabelecida.")

            # Criar task para escutar mensagens do Redis
            listener_ready = asyncio.get_running_loop().create_future()
            self.task = asyncio.create_task(
                self._listen_to_redis(startup_ready=listener_ready)
            )
            await asyncio.wait_for(
                asyncio.shield(listener_ready),
                timeout=REDIS_START_TIMEOUT_SECONDS,
            )
            if self._stopping or self._stopped:
                await self._cleanup_failed_start(redis_client)
                return
            logger.info("[WebSocket] Listener do Redis iniciado.")
        except BaseException as exc:
            if listener_ready is not None and not listener_ready.done():
                listener_ready.cancel()
            await self._cleanup_failed_start(redis_client)
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.error(
                "[WebSocket] Falha ao iniciar manager error_type=%s",
                exc.__class__.__name__,
            )
            raise

    async def _cleanup_failed_start(self, redis_client: Any) -> None:
        """Undo a partial startup so FastAPI never becomes falsely ready."""
        tasks = [
            task
            for task in (self.task, self.reconciliation_task)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.task = None
        self.reconciliation_task = None
        await self._close_redis_resource(self._pubsub)
        self._pubsub = None
        await self._close_redis_resource(redis_client)
        if self.redis is redis_client:
            self.redis = None

    async def stop(self) -> None:
        """Idempotently release DB holders and stop every manager background task."""
        if self._stopped:
            return
        existing = self._stop_task
        if existing is None:
            existing = asyncio.create_task(self._stop_impl())
            self._stop_task = existing
        try:
            await asyncio.shield(existing)
        except asyncio.CancelledError:
            await asyncio.shield(existing)
            raise

    async def _stop_impl(self) -> None:
        self._stopping = True
        for handle in list(self._active_fence_handles):
            handle.release_event.set()

        tasks = {
            task
            for task in (
                self.task,
                self.reconciliation_task,
                *self._redis_company_tasks.values(),
                *self._redis_revocation_tasks,
                *self._redis_overload_tasks.values(),
            )
            if task is not None and not task.done()
        }
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=WEBSOCKET_STOP_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[WebSocket] Timeout ao encerrar tasks de background count=%s",
                    len(tasks),
                )

        # Cancellations can race with fence submission. Signal the fresh
        # snapshot too, then wait boundedly for same-thread Session cleanup.
        handles = list(self._active_fence_handles)
        for handle in handles:
            handle.release_event.set()
        completions = [
            handle.completion
            for handle in handles
            if handle.completion is not None and not handle.completion.done()
        ]
        if completions:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(asyncio.shield(completion) for completion in completions),
                        return_exceptions=True,
                    ),
                    timeout=WEBSOCKET_STOP_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[WebSocket] Timeout ao liberar holders de autenticação count=%s",
                    len(completions),
                )

        local_connections: List[WSConnection] = []
        async with self.lock:
            for clients in self.connections.values():
                for phones in clients.values():
                    for connections in phones.values():
                        local_connections.extend(connections)
            self.connections.clear()
        await self._close_connections_bounded(
            local_connections,
            code=1012,
            reason="service_restart",
        )

        await self._close_redis_resource(self._pubsub)
        self._pubsub = None
        await self._close_redis_resource(self.redis)
        self.redis = None
        self.task = None
        self.reconciliation_task = None
        self._redis_company_tasks.clear()
        self._redis_company_inflight.clear()
        self._redis_revocation_tasks.clear()
        self._redis_overload_tasks.clear()
        self._redis_overloaded_companies.clear()
        self._redis_company_queues.clear()
        self._redis_company_overflows.clear()
        self._redis_pending_items = 0
        self._recent_event_ids.clear()
        self._stopped = True
        self._stopping = False

    async def _close_redis_resource(self, resource: Any) -> None:
        if resource is None:
            return
        close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
        if not callable(close):
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=1.0)
        except Exception as exc:
            logger.warning(
                "[WebSocket] Falha ao fechar recurso Redis error_type=%s",
                exc.__class__.__name__,
            )

    async def _listen_to_redis(
        self,
        startup_ready: Optional[asyncio.Future] = None,
    ):
        """
        Escuta mensagens publicadas no Redis no canal chat_messages:<company_id>,
        e agenda broadcasts ordenados por empresa sem bloquear o consumidor.
        """
        while True:
            if self._stopping:
                return
            pubsub = None
            try:
                if self.redis is None:
                    raise RuntimeError("redis_not_connected")
                pubsub = self.redis.pubsub()
                self._pubsub = pubsub
                await pubsub.psubscribe(
                    self._websocket_channel('chat_messages:*')
                )
                await pubsub.psubscribe(
                    self._websocket_channel('company_global:*')
                )
                await pubsub.psubscribe(
                    self._websocket_channel('task_notifications:*')
                )
                await pubsub.psubscribe(
                    self._websocket_channel('task_reminder_*')
                )
                await pubsub.psubscribe(
                    self._websocket_channel('access_revocations')
                )
                if startup_ready is not None and not startup_ready.done():
                    startup_ready.set_result(True)
                logger.info(
                    "[WebSocket] Inscrito nos canais de mensagens e revogação de acesso"
                )

                async for message in pubsub.listen():
                    if message['type'] != 'pmessage':
                        continue
                    try:
                        published_channel = message['channel'].decode('utf-8')
                        channel = strip_websocket_channel_namespace(
                            published_channel,
                            namespace=self.websocket_channel_namespace,
                        )
                        if channel is None:
                            logger.debug(
                                "[WebSocket] Canal Redis de outro namespace ignorado: %s",
                                published_channel,
                            )
                            continue
                        data = json.loads(message['data'])

                        if channel == 'access_revocations':
                            if not self._claim_event_id(published_channel, data):
                                continue
                            retained = False
                            try:
                                self._schedule_access_revocation(data)
                                retained = True
                            finally:
                                if not retained:
                                    self.release_event_delivery_claim(
                                        published_channel,
                                        data,
                                    )
                            continue

                        item = self._build_redis_dispatch_item(channel, data)
                        if item is None:
                            continue
                        item.channel = published_channel
                        if not self._claim_and_enqueue_redis_item(
                            published_channel,
                            data,
                            item,
                        ):
                            logger.debug(
                                "[WebSocket] Evento Redis duplicado ignorado "
                                "channel=%s event_id=%s",
                                channel,
                                data.get("event_id"),
                            )
                            continue

                    except Exception as exc:
                        logger.error(
                            "Erro ao processar msg do Redis error_type=%s",
                            exc.__class__.__name__,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if startup_ready is not None and not startup_ready.done():
                    startup_ready.set_exception(exc)
                    return
                if self._stopping:
                    return
                logger.error(
                    "Erro no listener do Redis error_type=%s",
                    exc.__class__.__name__,
                )
                await asyncio.sleep(5)
            finally:
                await self._close_redis_resource(pubsub)
                if self._pubsub is pubsub:
                    self._pubsub = None

    def _schedule_access_revocation(self, data: Dict[str, Any]) -> None:
        """Dispatch revocation immediately, ahead of ordinary company queues."""
        company_ids = [
            int(value) for value in (data.get("company_ids") or [])
        ]
        client_ids = [
            int(value) for value in (data.get("client_ids") or [])
        ]
        user_ids = [
            int(value) for value in (data.get("user_ids") or [])
        ]
        task = asyncio.create_task(
            self.close_access_connections(
                company_ids=company_ids,
                client_ids=client_ids,
                user_ids=user_ids,
            )
        )
        self._redis_revocation_tasks.add(task)

        def completed(done: asyncio.Task) -> None:
            self._redis_revocation_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception(
                    "[WebSocket] Falha ao aplicar revogação prioritária"
                )

        task.add_done_callback(completed)

    def _build_redis_dispatch_item(
        self,
        channel: str,
        data: Dict[str, Any],
    ) -> Optional[_RedisDispatchItem]:
        """Translate one Pub/Sub event into ordered per-company socket steps."""
        steps: List[Tuple[str, Dict[str, Any]]] = []
        company_id: Optional[int] = None

        if channel.startswith('company_global:'):
            company_id = int(channel.split(':', 1)[1])
            steps.append(("__global__", data))
        elif channel.startswith('chat_messages:'):
            company_id = int(channel.split(':', 1)[1])
            phone = str(data.get('phone') or '').strip()
            if not phone:
                logger.warning(
                    "[WebSocket] Mensagem Redis sem phone channel=%s",
                    channel,
                )
                return None
            if 'momment' not in data:
                tz_sp = ZoneInfo("America/Sao_Paulo")
                data['momment'] = datetime.now(tz_sp).isoformat(
                    timespec='seconds'
                )
            steps.append((phone, data))
            if data.get('fromMe') is False:
                trigger_payload = self._build_whatsapp_trigger_payload(data)
                if trigger_payload:
                    tz_sp = ZoneInfo("America/Sao_Paulo")
                    steps.append(
                        (
                            FLOW_BUILDER_WHATSAPP_TOPIC,
                            {
                                "type": "whatsapp_trigger_event",
                                "payload": trigger_payload,
                                "timestamp": datetime.now(tz_sp).isoformat(
                                    timespec='seconds'
                                ),
                            },
                        )
                    )
        elif (
            channel.startswith('task_notifications:')
            or channel.startswith('task_reminder_')
        ):
            if data.get('company_id') is None:
                logger.warning(
                    "[WebSocket] Notificação sem company_id channel=%s",
                    channel,
                )
                return None
            company_id = int(data['company_id'])
            steps.append(("__global__", data))

        if company_id is None or not steps:
            return None
        return _RedisDispatchItem(
            company_id=company_id,
            channel=channel,
            steps=steps,
        )

    def _enqueue_redis_dispatch_item(
        self,
        item: _RedisDispatchItem,
    ) -> bool:
        """Queue without blocking Pub/Sub or allowing unbounded memory growth."""
        company_id = int(item.company_id)
        if company_id in self._redis_overloaded_companies:
            return False

        if self._redis_pending_items >= self.redis_global_queue_maxsize:
            logger.error(
                "[WebSocket] Cap global de eventos em dispatch atingido "
                "company_id=%s pending=%s cap=%s",
                company_id,
                self._redis_pending_items,
                self.redis_global_queue_maxsize,
            )
            self._schedule_company_overload_reconnect(company_id)
            return False

        queue = self._redis_company_queues.get(company_id)
        if queue is None:
            if len(self._redis_company_queues) >= self.redis_active_company_maxsize:
                logger.error(
                    "[WebSocket] Cap global de empresas em dispatch atingido "
                    "company_id=%s active=%s cap=%s",
                    company_id,
                    len(self._redis_company_queues),
                    self.redis_active_company_maxsize,
                )
                self._schedule_company_overload_reconnect(company_id)
                return False
            queue = asyncio.Queue(maxsize=self.redis_company_queue_maxsize)
            self._redis_company_queues[company_id] = queue

        overflow = self._redis_company_overflows.get(company_id)
        if overflow or queue.full():
            overflow_size = len(overflow) if overflow is not None else 0
            if overflow_size >= self.redis_company_overflow_maxsize:
                # Redis Pub/Sub has no acknowledgement/redelivery contract. At
                # capacity we fail explicitly, release the event claim in the
                # caller and force local clients to reconnect/resync durable
                # state. This bounds memory without blocking the event loop.
                logger.error(
                    "[WebSocket] Cap de dispatch Redis atingido; reconexão "
                    "necessária company_id=%s queue=%s overflow=%s cap=%s "
                    "channel=%s event_id=%s",
                    company_id,
                    queue.qsize(),
                    overflow_size,
                    self.redis_company_overflow_maxsize,
                    item.channel,
                    self._dispatch_item_event_id(item),
                )
                self._schedule_company_overload_reconnect(company_id)
                return False
            if overflow is None:
                overflow = deque()
                self._redis_company_overflows[company_id] = overflow
            overflow.append(item)
            overflow_size = len(overflow)
            if (
                overflow_size == 1
                or overflow_size % REDIS_COMPANY_OVERFLOW_WARN_SIZE == 0
            ):
                logger.warning(
                    "[WebSocket] Pressão na fila Redis; usando overflow local "
                    "company_id=%s pending=%s",
                    company_id,
                    overflow_size,
                )
        else:
            queue.put_nowait(item)
        self._redis_pending_items += 1

        task = self._redis_company_tasks.get(company_id)
        if task is None or task.done():
            self._redis_company_tasks[company_id] = asyncio.create_task(
                self._drain_redis_company_queue(company_id, queue)
            )
        return True

    @staticmethod
    def _dispatch_item_event_id(item: _RedisDispatchItem) -> Optional[str]:
        for _phone, payload in item.steps:
            event_id = payload.get("event_id")
            if event_id is not None:
                return str(event_id)
        return None

    def _release_dispatch_item_claim(self, item: Any) -> None:
        if not isinstance(item, _RedisDispatchItem):
            return
        for _phone, payload in item.steps:
            if payload.get("event_id") is not None:
                self.release_event_delivery_claim(item.channel, payload)
                return

    def _schedule_company_overload_reconnect(self, company_id: int) -> None:
        """Close local sockets once with 1013 so clients reload durable state."""
        normalized_company_id = int(company_id)
        existing = self._redis_overload_tasks.get(normalized_company_id)
        if existing is not None and not existing.done():
            return
        if len(self._redis_overload_tasks) >= self.redis_active_company_maxsize:
            logger.error(
                "[WebSocket] Cap de tarefas de ressincronização atingido "
                "company_id=%s active=%s cap=%s",
                normalized_company_id,
                len(self._redis_overload_tasks),
                self.redis_active_company_maxsize,
            )
            return

        self._redis_overloaded_companies.add(normalized_company_id)
        task = asyncio.create_task(
            self._close_company_for_redis_overload(normalized_company_id)
        )
        self._redis_overload_tasks[normalized_company_id] = task

        def completed(done: asyncio.Task) -> None:
            if self._redis_overload_tasks.get(normalized_company_id) is done:
                self._redis_overload_tasks.pop(normalized_company_id, None)
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception(
                    "[WebSocket] Falha ao fechar sockets após saturação "
                    "company_id=%s",
                    normalized_company_id,
                )

        task.add_done_callback(completed)

    async def _close_company_for_redis_overload(self, company_id: int) -> int:
        normalized_company_id = int(company_id)
        queue = self._redis_company_queues.get(normalized_company_id)
        overflow = self._redis_company_overflows.get(normalized_company_id)
        inflight = self._redis_company_inflight.get(normalized_company_id)
        dispatch_task = self._redis_company_tasks.get(normalized_company_id)
        dropped_items: List[Any] = []
        try:
            if (
                dispatch_task is not None
                and dispatch_task is not asyncio.current_task()
                and not dispatch_task.done()
            ):
                dispatch_task.cancel()
                await asyncio.gather(dispatch_task, return_exceptions=True)

            if queue is not None:
                while True:
                    try:
                        dropped_items.append(queue.get_nowait())
                        queue.task_done()
                    except asyncio.QueueEmpty:
                        break
            if overflow is not None:
                while overflow:
                    dropped_items.append(overflow.popleft())

            self._redis_company_queues.pop(normalized_company_id, None)
            self._redis_company_overflows.pop(normalized_company_id, None)
            if self._redis_company_tasks.get(normalized_company_id) is dispatch_task:
                self._redis_company_tasks.pop(normalized_company_id, None)
            self._redis_company_inflight.pop(normalized_company_id, None)
            self._redis_pending_items = max(
                0,
                self._redis_pending_items - len(dropped_items),
            )

            # Keep the in-flight claim until its normal TTL expires: a socket
            # send can be accepted before cancellation becomes observable, so
            # releasing that ambiguous claim could duplicate delivery.
            for dropped_item in dropped_items:
                self._release_dispatch_item_claim(dropped_item)

            targets: List[WSConnection] = []
            async with self.lock:
                for phones in self.connections.get(normalized_company_id, {}).values():
                    for connections in phones.values():
                        targets.extend(connections)
                self._discard_connections_locked(normalized_company_id, targets)

            closed = await self._close_connections_bounded(
                targets,
                code=1013,
                reason="redis_backpressure",
            )
            logger.warning(
                "[WebSocket] Backlog descartado e sockets fechados após saturação "
                "company_id=%s dropped=%s closed=%s",
                normalized_company_id,
                len(dropped_items) + int(inflight is not None),
                closed,
            )
            return closed
        finally:
            self._redis_overloaded_companies.discard(normalized_company_id)

    def _claim_and_enqueue_redis_item(
        self,
        channel: str,
        data: Dict[str, Any],
        item: _RedisDispatchItem,
    ) -> bool:
        """Atomically retain a dedupe claim only when a queue owns the event."""
        if not self._claim_event_id(channel, data):
            return False
        retained = False
        try:
            retained = self._enqueue_redis_dispatch_item(item)
            return retained
        finally:
            if not retained:
                self.release_event_delivery_claim(channel, data)

    async def _drain_redis_company_queue(
        self,
        company_id: int,
        queue: asyncio.Queue,
    ) -> None:
        """Preserve arrival order inside one company, bounded across companies."""
        try:
            while True:
                from_primary_queue = False
                try:
                    item = queue.get_nowait()
                    from_primary_queue = True
                except asyncio.QueueEmpty:
                    overflow = self._redis_company_overflows.get(company_id)
                    if not overflow:
                        return
                    item = overflow.popleft()
                self._redis_pending_items = max(0, self._redis_pending_items - 1)
                self._redis_company_inflight[company_id] = item
                try:
                    await self._dispatch_redis_item(item)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "[WebSocket] Falha isolada no dispatch Redis "
                        "company_id=%s channel=%s",
                        company_id,
                        item.channel,
                    )
                finally:
                    if self._redis_company_inflight.get(company_id) is item:
                        self._redis_company_inflight.pop(company_id, None)
                    if from_primary_queue:
                        queue.task_done()
        finally:
            if self._redis_company_queues.get(company_id) is queue:
                self._redis_company_queues.pop(company_id, None)
            current = asyncio.current_task()
            if self._redis_company_tasks.get(company_id) is current:
                self._redis_company_tasks.pop(company_id, None)
            overflow = self._redis_company_overflows.get(company_id)
            if not overflow:
                self._redis_company_overflows.pop(company_id, None)

    async def _dispatch_redis_item(self, item: _RedisDispatchItem) -> None:
        """Deliver every step, retrying transient access-fence contention."""
        while item.step_index < len(item.steps):
            phone, payload = item.steps[item.step_index]
            async with self._redis_dispatch_semaphore:
                result = await self.broadcast_to_phone(
                    item.company_id,
                    phone,
                    payload,
                    _event_claimed=True,
                    _requeue_on_busy=False,
                )
            if result == BROADCAST_BUSY:
                item.busy_requeues += 1
                if (
                    item.busy_requeues == 1
                    or item.busy_requeues
                    % max(1, self.redis_busy_requeue_log_interval) == 0
                ):
                    logger.warning(
                        "[WebSocket] Fence ocupado; evento permanece na cabeça "
                        "company_id=%s channel=%s event_id=%s",
                        item.company_id,
                        item.channel,
                        payload.get("event_id"),
                    )
                await asyncio.sleep(
                    min(
                        self.redis_busy_requeue_max_delay_seconds,
                        self.redis_busy_requeue_delay_seconds
                        * item.busy_requeues,
                    )
                )
                continue

            item.step_index += 1
            item.busy_requeues = 0
            if phone == FLOW_BUILDER_WHATSAPP_TOPIC:
                trigger_payload = payload.get("payload") or {}
                logger.info(
                    "[FlowBuilderTrigger] whatsapp_trigger_event sent "
                    "(company_id=%s, phone=%s)",
                    item.company_id,
                    self._mask_phone(trigger_payload.get("phone", "")),
                )

    async def _reconcile_access_loop(self) -> None:
        """Durably close stale sockets even when Redis Pub/Sub loses an event."""
        while True:
            try:
                async with self.lock:
                    company_ids = list(self.connections)
                for company_id in company_ids:
                    await self.reconcile_company_access(company_id)
            except Exception:
                logger.exception("[WebSocket] Falha na reconciliação durável de acesso")
            await asyncio.sleep(10)

    async def connect(
        self,
        websocket: WebSocket,
        client_id: str,
        company_id: int,
        phone: str,
        *,
        send_confirmation: bool = True,
        access_epoch: Optional[int] = None,
        user_id: Optional[str] = None,
        user_type: Optional[str] = None,
        auth_token_version: Optional[int] = None,
    ):
        """
        Registra um novo WebSocket.
        CORREÇÃO DE SEGURANÇA: Bloqueia conexões ao modo global problemático.
        """
        # CORREÇÃO DE SEGURANÇA: Permitir modo global apenas para notificações autenticadas
        # O modo global é necessário para notificações de tarefas e outras funcionalidades do sistema
        if phone == "__global__":
            logger.info(
                f"[WebSocket] Conexão ao modo global permitida para notificações: "
                f"company_id={company_id}, client_id={client_id}"
            )

        new_connection = WSConnection(
            websocket=websocket,
            client_id=client_id,
            company_id=company_id,
            phone=phone,
            connected_at=datetime.now(),
            user_id=str(user_id) if user_id is not None else None,
            user_type=str(user_type) if user_type is not None else None,
            auth_token_version=(
                int(auth_token_version)
                if auth_token_version is not None
                else None
            ),
            access_epoch=access_epoch,
        )

        async with self.lock:
            if company_id not in self.connections:
                self.connections[company_id] = {}
            if client_id not in self.connections[company_id]:
                self.connections[company_id][client_id] = {}
            if phone not in self.connections[company_id][client_id]:
                self.connections[company_id][client_id][phone] = []

            self.connections[company_id][client_id][phone].append(new_connection)
            total_conns_for_phone = len(self.connections[company_id][client_id][phone])

        logger.info(
            f"[AUDIT] Nova conexão WebSocket => company_id={company_id}, "
            f"client_id={client_id}, phone={self._mask_phone(phone)}, "
            f"conexões ativas p/ este phone: {total_conns_for_phone}"
        )

        # Mensagem de boas-vindas (verificar se WebSocket ainda está aberto)
        try:
            if send_confirmation and websocket.client_state.name == "CONNECTED":
                await websocket.send_json({
                    "type": "connection_established",
                    "company_id": company_id,
                    "client_id": client_id,
                    "phone": phone,
                    "timestamp": datetime.now().isoformat()
                })

        except RuntimeError:
            # WebSocket já foi fechado, ignorar silenciosamente
            pass

    async def disconnect_websocket(
        self,
        websocket: WebSocket,
        client_id: str,
        company_id: int,
    ) -> None:
        """Remove one socket from every topic without leaving a late subscription."""
        async with self.lock:
            clients = self.connections.get(company_id)
            if not clients:
                return
            phones = clients.get(client_id)
            if not phones:
                return

            for phone in list(phones):
                phones[phone] = [
                    connection
                    for connection in phones[phone]
                    if connection.websocket != websocket
                ]
                if not phones[phone]:
                    del phones[phone]
            if not phones:
                del clients[client_id]
            if not clients:
                del self.connections[company_id]

    async def connect_with_access_barrier(
        self,
        websocket: WebSocket,
        client_id: str,
        company_id: int,
        phones: List[str],
        access_check: Callable[[], Awaitable[Optional[int]]],
        *,
        user_id: Optional[str] = None,
        user_type: Optional[str] = None,
        auth_token_version: Optional[int] = None,
    ) -> bool:
        """Register first, then recheck access while revocation can see the socket.

        If access is revoked before the recheck, the check rejects and removes
        the socket. If revocation happens after the recheck, the socket is
        already in `connections` and the revocation broadcast closes it.
        """
        normalized_phones = list(dict.fromkeys(str(phone) for phone in phones))
        for phone in normalized_phones:
            await self.connect(
                websocket,
                client_id,
                company_id,
                phone,
                send_confirmation=False,
                user_id=user_id,
                user_type=user_type,
                auth_token_version=auth_token_version,
            )

        try:
            access_epoch = await access_check()
        except Exception:
            logger.warning(
                "[WebSocket] Falha na revalidação pós-registro "
                "company_id=%s client_id=%s",
                company_id,
                client_id,
                exc_info=True,
            )
            access_epoch = None

        if access_epoch is not None:
            async with self.lock:
                for phones_by_client in self.connections.get(company_id, {}).values():
                    for connections in phones_by_client.values():
                        for connection in connections:
                            if connection.websocket == websocket:
                                connection.access_epoch = int(access_epoch)
            return True

        await self.disconnect_websocket(websocket, client_id, company_id)
        try:
            application_state = getattr(websocket, "application_state", None)
            if (
                application_state is None
                or getattr(application_state, "name", None) == "CONNECTED"
            ):
                await websocket.close(code=4003, reason="access_revoked")
        except Exception:
            logger.debug(
                "[WebSocket] Socket já encerrado durante barreira de acesso "
                "company_id=%s client_id=%s",
                company_id,
                client_id,
            )
        return False

    def _open_company_access_fence(
        self,
        company_id: int,
        connections: List[WSConnection] = (),
    ):
        """Try a shared DB fence and return its active epoch.

        The PostgreSQL acquisition is intentionally non-blocking. A successful
        shared fence linearizes principal checks and socket sends with company
        state changes without waiting synchronously in the event loop.
        """
        from backend.db import SessionLocal, mark_session_as_web_request
        from backend.services.company_access_control import (
            ensure_company_operational,
            get_company_operational_epoch,
            try_lock_entities_for_access,
        )

        client_ids = set()
        user_ids = set()
        for connection in connections:
            try:
                if connection.user_type is not None:
                    client_ids.add(int(connection.client_id))
                if (
                    connection.user_type == "user"
                    and connection.user_id is not None
                ):
                    user_ids.add(int(connection.user_id))
            except (TypeError, ValueError):
                # Invalid principal snapshots fail the validation below.  They
                # must not prevent fencing valid sockets for the same company.
                continue

        db = mark_session_as_web_request(SessionLocal())
        try:
            normalized_company_id = int(company_id)
            try_lock_entities_for_access(
                db,
                company_ids=[normalized_company_id],
                client_ids=client_ids,
                user_ids=user_ids,
            )
            ensure_company_operational(db, normalized_company_id)
            epoch = get_company_operational_epoch(db, normalized_company_id)
            if epoch is None:
                from backend.services.company_access_control import (
                    CompanyOperationallyBlockedError,
                )

                raise CompanyOperationallyBlockedError(
                    normalized_company_id,
                    "not_found",
                )
            return db, int(epoch)
        except Exception:
            try:
                db.rollback()
            finally:
                db.close()
            raise

    def _hold_company_access_fence_on_worker(
        self,
        company_id: int,
        connections: List[WSConnection],
        handle: _CompanyAccessFenceHandle,
    ) -> None:
        """Own the Session from open through cleanup on exactly one thread."""
        db = None
        try:
            if handle.release_event.is_set():
                raise RuntimeError("company_access_fence_released_before_prepare")
            db, current_epoch = self._open_company_access_fence(
                int(company_id),
                connections,
            )
            prepared = _PreparedCompanyAccessFence(
                current_epoch=int(current_epoch),
                active_connection_ids=frozenset(
                    id(connection)
                    for connection in connections
                    if (
                        connection.access_epoch == int(current_epoch)
                        and self._connection_principal_is_active(db, connection)
                    )
                ),
            )
            handle.prepared.set_result(prepared)
            handle.release_event.wait()
        except BaseException as exc:
            if not handle.prepared.done():
                handle.prepared.set_exception(exc)
            raise
        finally:
            if db is not None:
                self._cleanup_company_access_fence(db)

    @staticmethod
    def _cleanup_company_access_fence(db: Any) -> None:
        """Release a fence even if rollback or pool check-in is unhealthy."""
        cleanup_error: Optional[BaseException] = None
        try:
            db.rollback()
        except BaseException as exc:
            cleanup_error = exc
        try:
            db.close()
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc
        if cleanup_error is not None:
            raise cleanup_error

    async def _release_company_access_fence(
        self,
        handle: _CompanyAccessFenceHandle,
    ) -> None:
        """Signal the owning worker and wait until same-thread cleanup ends."""
        handle.release_event.set()
        completion = handle.completion
        if completion is None:
            return
        try:
            await asyncio.shield(completion)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(completion)
            except Exception:
                logger.warning(
                    "[WebSocket] Holder de fence falhou durante cancelamento"
                )
            raise

    async def _run_company_access_fence_preparation(
        self,
        company_id: int,
        connections: List[WSConnection],
    ) -> Tuple[_CompanyAccessFenceHandle, int, set[int]]:
        """Start a same-thread holder and await only its immutable DTO."""
        loop = asyncio.get_running_loop()
        handle = _CompanyAccessFenceHandle()
        completion = loop.run_in_executor(
            _FENCE_PREPARE_EXECUTOR,
            self._hold_company_access_fence_on_worker,
            int(company_id),
            list(connections),
            handle,
        )
        handle.completion = completion
        self._active_fence_handles.add(handle)

        def completed(done: asyncio.Future) -> None:
            self._active_fence_handles.discard(handle)
            if done.cancelled():
                return
            # Retrieve the exception even if request cancellation abandoned the
            # waiter; explicit awaits still receive the same result.
            done.exception()

        completion.add_done_callback(completed)
        prepared_waiter = asyncio.wrap_future(handle.prepared)
        try:
            prepared = await asyncio.shield(prepared_waiter)
            return (
                handle,
                int(prepared.current_epoch),
                set(prepared.active_connection_ids),
            )
        except BaseException:
            handle.release_event.set()
            try:
                await asyncio.shield(completion)
            except BaseException:
                pass
            raise

    async def _acquire_company_access_fence(
        self,
        company_id: int,
        connections: List[WSConnection],
    ):
        """Retry shared-fence contention with bounded asynchronous backoff."""
        attempts = max(1, int(self.access_fence_retry_attempts))
        for attempt in range(attempts):
            try:
                return await self._run_company_access_fence_preparation(
                    int(company_id),
                    list(connections),
                )
            except CompanyOperationalLockBusyError:
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(
                    self.access_fence_retry_delay_seconds * (attempt + 1)
                )

    async def _snapshot_phone_connections(
        self,
        company_id: int,
        phone: str,
    ) -> List[WSConnection]:
        async with self.lock:
            return [
                connection
                for phones_dict in self.connections.get(int(company_id), {}).values()
                for connection in phones_dict.get(phone, [])
            ]

    async def _snapshot_company_connections(
        self,
        company_id: int,
    ) -> List[WSConnection]:
        async with self.lock:
            return [
                connection
                for phones in self.connections.get(int(company_id), {}).values()
                for connections in phones.values()
                for connection in connections
            ]

    def _discard_connections_locked(
        self,
        company_id: int,
        connections: List[WSConnection],
    ) -> None:
        """Discard connection records while the caller owns ``self.lock``."""
        target_ids = {id(connection) for connection in connections}
        if not target_ids:
            return

        clients = self.connections.get(company_id, {})
        for client_id in list(clients):
            phones = clients[client_id]
            for phone in list(phones):
                kept = [
                    connection
                    for connection in phones[phone]
                    if id(connection) not in target_ids
                ]
                if kept:
                    phones[phone] = kept
                else:
                    del phones[phone]
            if not phones:
                del clients[client_id]
        if not clients:
            self.connections.pop(company_id, None)

    def _connection_principal_is_active(
        self,
        db,
        connection: WSConnection,
    ) -> bool:
        """Revalidate the durable principal behind one authenticated socket."""
        # Legacy/test-only connections have no signed-principal snapshot and
        # remain protected by the company epoch fence.
        if (
            connection.user_id is None
            or connection.user_type is None
            or connection.auth_token_version is None
        ):
            return True

        from backend.models import Client, User

        try:
            client_id = int(connection.client_id)
            user_id = int(connection.user_id)
        except (TypeError, ValueError):
            return False

        client = db.query(Client).filter(Client.id == client_id).first()
        if (
            client is None
            or not bool(client.is_active)
        ):
            return False

        if connection.user_type == "master":
            return (
                user_id == client_id
                and int(client.auth_token_version or 0)
                == int(connection.auth_token_version)
            )
        if connection.user_type != "user":
            return False

        user = (
            db.query(User)
            .filter(
                User.id == user_id,
                User.client_id == client_id,
            )
            .first()
        )
        return bool(
            user
            and user.is_active
            and int(user.auth_token_version or 0)
            == int(connection.auth_token_version)
        )

    async def _detach_stale_company_connections(
        self,
        company_id: int,
        current_epoch: int,
        active_connection_ids: Optional[set[int]] = None,
        candidates: Optional[List[WSConnection]] = None,
    ) -> List[WSConnection]:
        """Detach stale sockets using thread-prepared, ORM-free decisions."""
        if candidates is None:
            candidates = await self._snapshot_company_connections(company_id)
        stale = [
            connection
            for connection in candidates
            if (
                id(connection) not in active_connection_ids
                if active_connection_ids is not None
                else connection.access_epoch != int(current_epoch)
            )
        ]
        async with self.lock:
            self._discard_connections_locked(company_id, stale)
        return stale

    async def _close_connections_bounded(
        self,
        connections: List[WSConnection],
        *,
        code: int = 4003,
        reason: str = "access_revoked",
    ) -> int:
        """Close unique sockets concurrently without an unbounded network wait."""
        unique = {
            id(connection.websocket): connection
            for connection in connections
        }

        async def close_one(connection: WSConnection) -> bool:
            try:
                await asyncio.wait_for(
                    connection.websocket.close(
                        code=code,
                        reason=reason,
                    ),
                    timeout=self.websocket_close_timeout_seconds,
                )
                return True
            except asyncio.TimeoutError:
                logger.warning(
                    "[WebSocket] Timeout ao fechar socket revogado company_id=%s",
                    connection.company_id,
                )
            except Exception:
                logger.debug(
                    "[WebSocket] Socket já encerrado durante revogação company_id=%s",
                    connection.company_id,
                )
            return False

        if not unique:
            return 0
        results = await asyncio.gather(
            *(close_one(connection) for connection in unique.values())
        )
        return sum(results)

    async def reconcile_company_access(self, company_id: int) -> bool:
        """Reconcile local sockets against durable status+epoch, fail closed."""
        candidates = await self._snapshot_company_connections(int(company_id))
        if not candidates:
            return True

        company_lock = self._company_operation_lock(int(company_id))
        try:
            await asyncio.wait_for(
                company_lock.acquire(),
                timeout=self.company_broadcast_wait_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[WebSocket] Reconciliação adiada; empresa ocupada company_id=%s",
                company_id,
            )
            return False

        db = None
        stale_connections: List[WSConnection] = []
        access_confirmed = False
        try:
            candidates = await self._snapshot_company_connections(int(company_id))
            if not candidates:
                return True
            (
                db,
                current_epoch,
                active_connection_ids,
            ) = await self._acquire_company_access_fence(
                int(company_id),
                candidates,
            )
            stale_connections = await self._detach_stale_company_connections(
                int(company_id),
                current_epoch,
                active_connection_ids,
                candidates,
            )
            access_confirmed = True
        except CompanyOperationalLockBusyError:
            # A concurrent access mutation owns the exclusive fence. Its revocation
            # event (or the next reconciliation pass) decides socket state;
            # transient contention itself is not proof of revocation.
            logger.info(
                "[WebSocket] Reconciliação adiada por fence ocupado company_id=%s",
                company_id,
            )
            return False
        except Exception:
            logger.warning(
                "[WebSocket] Acesso durável não confirmado; fechando sockets company_id=%s",
                company_id,
                exc_info=True,
            )
        finally:
            try:
                if db is not None:
                    try:
                        await self._release_company_access_fence(db)
                    except Exception:
                        access_confirmed = False
                        logger.warning(
                            "[WebSocket] Falha ao liberar fence na reconciliação "
                            "company_id=%s",
                            company_id,
                            exc_info=True,
                        )
            finally:
                company_lock.release()

        if not access_confirmed:
            await self.close_company_connections([int(company_id)])
            return False

        await self._close_connections_bounded(stale_connections)
        return True

    async def disconnect(self, websocket: WebSocket, client_id: str, company_id: int, phone: str):
        """Remove uma conexão WebSocket específica."""
        async with self.lock:
            if company_id in self.connections:
                if client_id in self.connections[company_id]:
                    if phone in self.connections[company_id][client_id]:
                        conns = self.connections[company_id][client_id][phone]
                        self.connections[company_id][client_id][phone] = [
                            c for c in conns if c.websocket != websocket
                        ]

                        if not self.connections[company_id][client_id][phone]:
                            del self.connections[company_id][client_id][phone]
                    if not self.connections[company_id][client_id]:
                        del self.connections[company_id][client_id]
                if not self.connections[company_id]:
                    del self.connections[company_id]

        logger.info(
            "Conexão removida => company_id=%s client_id=%s phone=%s",
            company_id,
            client_id,
            self._mask_phone(phone),
        )

    async def close_company_connections(self, company_ids: List[int]) -> int:
        """Close every local socket for blocked companies in this worker."""
        return await self.close_access_connections(company_ids=company_ids)

    async def close_access_connections(
        self,
        *,
        company_ids: List[int] = (),
        client_ids: List[int] = (),
        user_ids: List[int] = (),
    ) -> int:
        """Close blocked companies or principals across every shared workspace."""
        targets: List[WSConnection] = []
        normalized_company_ids = {int(value) for value in company_ids}
        normalized_client_ids = {str(int(value)) for value in client_ids}
        normalized_user_ids = {str(int(value)) for value in user_ids}
        async with self.lock:
            for company_id in list(self.connections):
                clients = self.connections.get(company_id, {})
                for phones in clients.values():
                    for connections in phones.values():
                        for connection in connections:
                            if (
                                company_id in normalized_company_ids
                                or connection.client_id in normalized_client_ids
                                or (
                                    connection.user_id is not None
                                    and connection.user_id in normalized_user_ids
                                )
                            ):
                                targets.append(connection)
                self._discard_connections_locked(
                    int(company_id),
                    targets,
                )

        closed = await self._close_connections_bounded(targets)
        logger.info(
            "[WebSocket] Revogação aplicada companies=%s clients=%s users=%s closed=%s",
            sorted(normalized_company_ids),
            sorted(normalized_client_ids),
            sorted(normalized_user_ids),
            closed,
        )
        return closed

    async def publish_access_revocation(
        self,
        company_ids: List[int],
        *,
        client_ids: List[int] = (),
        user_ids: List[int] = (),
    ) -> None:
        """Broadcast revocation so every uvicorn worker closes its local sockets."""
        normalized_company_ids = sorted({int(value) for value in company_ids})
        normalized_client_ids = sorted({int(value) for value in client_ids})
        normalized_user_ids = sorted({int(value) for value in user_ids})
        if not (
            normalized_company_ids
            or normalized_client_ids
            or normalized_user_ids
        ):
            return
        await self.close_access_connections(
            company_ids=normalized_company_ids,
            client_ids=normalized_client_ids,
            user_ids=normalized_user_ids,
        )
        if self.redis:
            try:
                await asyncio.wait_for(
                    self.redis.publish(
                        self._websocket_channel("access_revocations"),
                        json.dumps(
                            {
                                "company_ids": normalized_company_ids,
                                "client_ids": normalized_client_ids,
                                "user_ids": normalized_user_ids,
                            }
                        ),
                    ),
                    timeout=REDIS_REVOCATION_PUBLISH_TIMEOUT_SECONDS,
                )
            except Exception:
                # Local sockets are already closed. Other workers converge from
                # durable principal state even when Pub/Sub is unavailable.
                logger.warning(
                    "[WebSocket] Redis indisponível ao publicar revogação; "
                    "reconciliação durável assumirá",
                    exc_info=True,
                )

    def _enqueue_busy_local_broadcast(
        self,
        company_id: int,
        phone: str,
        message: Dict[str, Any],
        channel: str,
    ) -> None:
        queued = self._enqueue_redis_dispatch_item(
            _RedisDispatchItem(
                company_id=int(company_id),
                channel=channel,
                steps=[(phone, message)],
            )
        )
        if queued:
            logger.info(
                "[WebSocket] Broadcast local reenfileirado por fence ocupado "
                "company_id=%s channel=%s event_id=%s",
                company_id,
                channel,
                message.get("event_id"),
            )
        else:
            self.release_event_delivery_claim(channel, message)

    async def broadcast_to_phone(
        self,
        company_id: int,
        phone: str,
        message: dict,
        *,
        _event_claimed: bool = False,
        _event_channel: Optional[str] = None,
        _requeue_on_busy: bool = True,
    ) -> str:
        """
        CORRIGIDO: Envia a mensagem APENAS para conexões do (company_id, phone) específico.
        Remove o modo global problemático que causava vazamento de mensagens entre contatos.
        """
        normalized_company_id = int(company_id)
        # Avoid opening a DB transaction for Redis events that have no local
        # consumer in this worker.
        if not await self._snapshot_phone_connections(normalized_company_id, phone):
            return BROADCAST_NO_LOCAL_SOCKET

        event_channel = _event_channel or self._websocket_channel(
            f"chat_messages:{normalized_company_id}"
        )
        if (
            not _event_claimed
            and not self.claim_event_for_local_delivery(event_channel, message)
        ):
            return BROADCAST_DEDUPLICATED

        company_lock = self._company_operation_lock(normalized_company_id)
        try:
            await asyncio.wait_for(
                company_lock.acquire(),
                timeout=self.company_broadcast_wait_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[WebSocket] Broadcast adiado; fila local ocupada company_id=%s",
                company_id,
            )
            if _requeue_on_busy:
                self._enqueue_busy_local_broadcast(
                    normalized_company_id,
                    phone,
                    message,
                    event_channel,
                )
            return BROADCAST_BUSY

        db = None
        stale_connections: List[WSConnection] = []
        targets: List[WSConnection] = []
        failed_connections: List[WSConnection] = []
        principal_check_failed = False
        try:
            candidates = await self._snapshot_phone_connections(
                normalized_company_id,
                phone,
            )
            if not candidates:
                return BROADCAST_NO_LOCAL_SOCKET
            try:
                (
                    db,
                    _current_epoch,
                    active_connection_ids,
                ) = await self._acquire_company_access_fence(
                    normalized_company_id,
                    candidates,
                )
            except CompanyOperationalLockBusyError:
                # Busy is a transient access-mutation race, not evidence that every
                # local socket was revoked.  Never convert it into code 4003.
                logger.info(
                    "[WebSocket] Broadcast adiado por fence ocupado company_id=%s",
                    company_id,
                )
                if _requeue_on_busy:
                    self._enqueue_busy_local_broadcast(
                        normalized_company_id,
                        phone,
                        message,
                        event_channel,
                    )
                return BROADCAST_BUSY
            except Exception:
                principal_check_failed = True
                logger.warning(
                    "[WebSocket] Broadcast bloqueado por acesso não confirmado company_id=%s",
                    company_id,
                    exc_info=True,
                )
            else:
                stale_connections = [
                    connection
                    for connection in candidates
                    if id(connection) not in active_connection_ids
                ]
                targets = [
                    connection
                    for connection in candidates
                    if id(connection) in active_connection_ids
                ]
                async with self.lock:
                    self._discard_connections_locked(
                        int(company_id),
                        stale_connections,
                    )

            async def send_one(connection: WSConnection) -> Optional[WSConnection]:
                try:
                    await asyncio.wait_for(
                        connection.websocket.send_json(message),
                        timeout=self.websocket_send_timeout_seconds,
                    )
                    logger.debug(
                        "[SEGURO] Mensagem enviada para phone=%s company=%s client=%s",
                        self._mask_phone(phone),
                        company_id,
                        connection.client_id,
                    )
                    return None
                except asyncio.TimeoutError:
                    logger.warning(
                        "[broadcast_to_phone] Timeout p/ phone=%s company=%s client=%s",
                        self._mask_phone(phone),
                        company_id,
                        connection.client_id,
                    )
                except Exception:
                    logger.error(
                        "[broadcast_to_phone] Erro p/ phone=%s company=%s client=%s",
                        self._mask_phone(phone),
                        company_id,
                        connection.client_id,
                        exc_info=True,
                    )
                return connection

            if targets and not principal_check_failed:
                results = await asyncio.gather(
                    *(send_one(connection) for connection in targets)
                )
                failed_connections = [
                    connection
                    for connection in results
                    if connection is not None
                ]
        except Exception:
            principal_check_failed = True
            logger.warning(
                "[WebSocket] Revalidação de principal falhou; fechando empresa "
                "company_id=%s",
                company_id,
                exc_info=True,
            )
        finally:
            try:
                if db is not None:
                    try:
                        await self._release_company_access_fence(db)
                    except Exception:
                        principal_check_failed = True
                        logger.warning(
                            "[WebSocket] Falha ao liberar fence de broadcast "
                            "company_id=%s",
                            company_id,
                            exc_info=True,
                        )
            finally:
                company_lock.release()

        if principal_check_failed:
            await self.close_company_connections([int(company_id)])
            return BROADCAST_FAILED

        if failed_connections:
            async with self.lock:
                self._discard_connections_locked(
                    int(company_id),
                    failed_connections,
                )
            await self._close_connections_bounded(
                failed_connections,
                code=1011,
                reason="send_failed",
            )

        await self._close_connections_bounded(stale_connections)

        logger.info(
            "[AUDIT] Mensagem processada: company_id=%s phone=%s type=%s fromMe=%s",
            company_id,
            self._mask_phone(phone),
            message.get('type', 'unknown'),
            message.get('fromMe', False),
        )
        return BROADCAST_DELIVERED

    async def publish_message(self, company_id: int, message: dict):
        """
        Publica no Redis para que _listen_to_redis() e outros serviços
        (ou instâncias do app) recebam a mensagem no canal chat_messages:<company_id>.
        """
        try:
            channel = self._websocket_channel(f"chat_messages:{company_id}")
            if 'momment' not in message:
                tz_sp = ZoneInfo("America/Sao_Paulo")
                message['momment'] = datetime.now(tz_sp).isoformat(timespec='seconds')

            await self._publish_redis(channel, json.dumps(message))
        except Exception as exc:
            logger.error(
                "Erro ao publicar msg no Redis error_type=%s",
                exc.__class__.__name__,
            )

    async def broadcast(self, message: str):
        """
        Envia 'message' (texto) para TODAS as conexões WebSocket,
        independentemente de company_id, phone etc. (um broadcast geral).
        """
        try:
            payload = json.loads(message) if isinstance(message, str) else message
        except (TypeError, json.JSONDecodeError):
            payload = {"type": "message", "content": str(message)}
        if not isinstance(payload, dict):
            payload = {"type": "message", "content": payload}

        async with self.lock:
            targets = {
                (company_id, phone)
                for company_id, clients in self.connections.items()
                for phones in clients.values()
                for phone in phones
            }
        event_channel = self._websocket_channel("local_broadcast")
        if not self.claim_event_for_local_delivery(event_channel, payload):
            return
        for company_id, phone in targets:
            await self.broadcast_to_phone(
                company_id,
                phone,
                payload,
                _event_claimed=True,
                _event_channel=event_channel,
            )

    async def send_task_notification(self, user_id: int, notification_data: dict):
        """
        Envia notificação de tarefa para um usuário específico
        notification_data deve conter: type, task, etc.
        """
        try:
            # Adicionar timestamp
            if 'timestamp' not in notification_data:
                tz_sp = ZoneInfo("America/Sao_Paulo")
                notification_data['timestamp'] = datetime.now(tz_sp).isoformat(timespec='seconds')

            # Publicar no canal de notificações do usuário
            channel = self._websocket_channel(f"task_notifications:{user_id}")
            await self._publish_redis(channel, json.dumps(notification_data))
            logger.info(f"[TaskNotification] Notificação enviada para usuário {user_id}: {notification_data['type']}")

        except Exception as exc:
            logger.error(
                "Erro ao enviar notificação de tarefa error_type=%s",
                exc.__class__.__name__,
            )

    async def send_personal_message(self, channel: str, message_data: dict):
        """
        Envia mensagem pessoal através de um canal específico
        Usado para lembretes e notificações de tarefas
        """
        try:
            # Adicionar timestamp se não existir
            if 'timestamp' not in message_data:
                tz_sp = ZoneInfo("America/Sao_Paulo")
                message_data['timestamp'] = datetime.now(tz_sp).isoformat(timespec='seconds')

            # Publicar no canal especificado
            published_channel = self._websocket_channel(channel)
            await self._publish_redis(published_channel, json.dumps(message_data))
            logger.info(
                f"[PersonalMessage] Mensagem enviada no canal {published_channel}"
            )

        except Exception as exc:
            logger.error(
                "Erro ao enviar mensagem pessoal error_type=%s",
                exc.__class__.__name__,
            )

    async def broadcast_global(self, company_id: int, message_data: dict):
        """
        Envia mensagem para todos os clientes conectados de uma empresa específica
        no tópico global (__global__)
        """
        try:
            # Adicionar company_id e tipo se não existir
            message_data['company_id'] = company_id
            if 'type' not in message_data:
                message_data['type'] = 'global_notification'

            # Adicionar timestamp se não existir
            if 'timestamp' not in message_data:
                tz_sp = ZoneInfo("America/Sao_Paulo")
                message_data['timestamp'] = datetime.now(tz_sp).isoformat(timespec='seconds')

            # Se temos Redis, usar publish/subscribe
            if self.redis:
                # Publicar no canal global da empresa
                channel = self._websocket_channel(
                    f"company_global:{company_id}"
                )
                await self._publish_redis(channel, json.dumps(message_data))
                logger.info(f"[GlobalBroadcast] Mensagem publicada no Redis para empresa {company_id}, canal: {channel}")
                return

            # O fallback local usa exatamente a mesma barreira durável, epoch e
            # timeout dos broadcasts recebidos via Redis. Nunca faça I/O de
            # rede diretamente enquanto ``self.lock`` estiver adquirido.
            await self.broadcast_to_phone(
                int(company_id),
                "__global__",
                message_data,
            )

        except Exception as exc:
            logger.error(
                "Erro ao fazer broadcast global error_type=%s",
                exc.__class__.__name__,
            )

    async def broadcast_task_update(self, company_id: int, task_data: dict):
        """
        Broadcast de atualização de tarefa para todos os usuários da empresa
        """
        try:
            # Adicionar timestamp se não existir
            if 'timestamp' not in task_data:
                tz_sp = ZoneInfo("America/Sao_Paulo")
                task_data['timestamp'] = datetime.now(tz_sp).isoformat(timespec='seconds')

            # Publicar no canal de tarefas da empresa
            channel = self._websocket_channel(f"task_updates:{company_id}")
            await self._publish_redis(channel, json.dumps(task_data))
            logger.info(f"[TaskUpdate] Atualização enviada para empresa {company_id}")

            # Também enviar para todos os clientes conectados à empresa no tópico global
            await self.broadcast_global(company_id, task_data)

        except Exception as exc:
            logger.error(
                "Erro ao enviar atualização de tarefa error_type=%s",
                exc.__class__.__name__,
            )

manager = ConnectionManager()

async def start_manager():
    """Inicia o manager (conexão Redis + listener)."""
    await manager.start()


async def stop_manager():
    """Release all WebSocket resources during FastAPI shutdown."""
    await manager.stop()
