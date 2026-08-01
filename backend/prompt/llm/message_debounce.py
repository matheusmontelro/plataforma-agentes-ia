import logging
import threading
from collections import defaultdict
from typing import Dict, List, Callable

logger = logging.getLogger(__name__)

# Buffer global { contact_phone: [mensagens_pendentes] }
message_buffers: Dict[str, List[str]] = defaultdict(list)

# Timers em andamento { contact_phone: threading.Timer }
debounce_timers: Dict[str, threading.Timer] = {}

# Intervalo de debounce em segundos
DEBOUNCE_INTERVAL = 15.0

# Define o tipo de função callback: recebe (contact_phone, lista_de_mensagens)
ProcessCallbackType = Callable[[str, List[str]], None]


def init_message_buffer():
    """
    Se quiser limpar ou resetar os buffers em algum momento específico.
    """
    message_buffers.clear()
    debounce_timers.clear()


def _execute_debounce(contact_phone: str, callback: ProcessCallbackType):
    """
    Função chamada ao expirar o timer.
    - Consolida as mensagens pendentes daquele telefone
    - Chama o callback
    - Limpa o buffer
    """
    pending_messages = message_buffers.get(contact_phone, [])
    if not pending_messages:
        return

    logger.info(f"[debounce] Disparando callback para {contact_phone} (total {len(pending_messages)} msgs).")

    # Chama a função de processamento (ex.: LLM, etc.)
    callback(contact_phone, pending_messages)

    # Limpa o buffer deste contato
    message_buffers[contact_phone].clear()
    logger.info(f"[debounce] Buffer limpo para {contact_phone}")


def debounce_new_message(
    contact_phone: str,
    message_text: str,
    callback: ProcessCallbackType
):
    """
    Quando chega uma nova mensagem, chamamos esta função:
      1. Adiciona a mensagem no buffer do contact_phone
      2. Cancela eventual timer anterior (se houver)
      3. Cria um novo timer com threading.Timer

    Se não chegarem novas mensagens dentro de DEBOUNCE_INTERVAL,
    o timer expira e chamamos 'callback(contact_phone, lista_de_msgs)'.
    """

    # Adiciona a mensagem ao buffer
    message_buffers[contact_phone].append(message_text)

    # Se havia um timer em andamento para este phone, cancelamos
    if contact_phone in debounce_timers:
        old_timer = debounce_timers[contact_phone]
        old_timer.cancel()

    # Cria e inicia um novo timer
    timer = threading.Timer(
        DEBOUNCE_INTERVAL,
        _execute_debounce,
        args=[contact_phone, callback]
    )
    timer.start()

    # Armazena a referência do timer
    debounce_timers[contact_phone] = timer
