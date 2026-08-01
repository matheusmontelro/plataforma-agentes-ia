# backend/prompt/memory/memory_manager.py

import logging
import os
from typing import List
from pathlib import Path
from langchain.schema import HumanMessage, AIMessage
import pytz
from datetime import datetime

from backend.runtime_settings import CHAT_MEMORY_DIR

logger = logging.getLogger(__name__)

BASE_PATH = CHAT_MEMORY_DIR


def _chatmemory_file(company_id: int, contact_phone: str) -> Path:
    return BASE_PATH / f"chatmemory_{company_id}_{contact_phone}.txt"


def _ensure_chatmemory_dir() -> None:
    BASE_PATH.mkdir(parents=True, exist_ok=True)

def get_chat_history(company_id: int, contact_phone: str) -> List:
    """
    Lê o histórico de conversa a partir de um arquivo .txt no diretório
    configurado por CHAT_MEMORY_DIR.

    Agora cada mensagem está em apenas uma linha, no formato:
        HUMAN:[DD/MM/YYYY HH:mm] Mensagem do usuário
        AI:[DD/MM/YYYY HH:mm]    Mensagem do assistente
        OPER:[DD/MM/YYYY HH:mm]  Mensagem do operador humano

    O parser abaixo extrai o prefixo (HUMAN, AI ou OPER),
    ignora o timestamp e converte o restante do texto em
    HumanMessage ou AIMessage, conforme apropriado.
    """
    chat_history = []
    file_path = _chatmemory_file(company_id, contact_phone)

    if not file_path.is_file():
        logger.info(f"[MemoryManager] Arquivo de histórico não encontrado: {file_path}")
        return chat_history

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue

                # As "tags" de prefixo esperadas:
                if line.startswith("HUMAN:[") or line.startswith("AI:[") or line.startswith("OPER:["):
                    # Pega a parte antes e depois do colchete ]
                    prefix_end = line.find("]")
                    if prefix_end != -1:
                        prefix_part = line[:prefix_end+1]  # ex.: "AI:[04/03/2025 10:15]"
                        content_part = line[prefix_end+1:].strip()  # resto da linha

                        if prefix_part.startswith("HUMAN:"):
                            # É mensagem do usuário
                            chat_history.append(HumanMessage(content=content_part))
                        elif prefix_part.startswith("OPER:"):
                            # Operador tratamos como 'assistente' para manter continuidade do contexto
                            chat_history.append(AIMessage(content=content_part))
                        elif prefix_part.startswith("AI:"):
                            # Mensagem do assistente
                            chat_history.append(AIMessage(content=content_part))
                        else:
                            logger.warning(f"[MemoryManager] Prefixo não reconhecido: {prefix_part}")
                    else:
                        logger.warning(f"[MemoryManager] Falha ao encontrar ']' na linha: {line}")
                # NOVO: Tratar OPER sem timestamp
                elif line.startswith("OPER:"):
                    # OPER sem timestamp - pega tudo após "OPER:"
                    content_part = line[5:].strip()  # Remove "OPER:" e espaços
                    chat_history.append(AIMessage(content=f"[Operador]: {content_part}"))
                    logger.info(f"[MemoryManager] OPER sem timestamp processado: {content_part[:50]}...")
                else:
                    logger.warning(f"[MemoryManager] Linha sem prefixo reconhecido: {line}")
    except Exception as e:
        logger.error(f"[MemoryManager] Erro ao ler arquivo {file_path}: {e}")
        return chat_history

    logger.info(f"[MemoryManager] {len(chat_history)} mensagens carregadas de {file_path}")
    return chat_history


def append_message_to_chat_file(company_id: int, contact_phone: str, from_me: bool, content: str):
    """
    Escreve uma mensagem no arquivo .txt de histórico, em apenas 1 linha.
    O formato agora é:
        AI:[DD/MM/YYYY HH:mm] Seu texto aqui...
    ou
        HUMAN:[DD/MM/YYYY HH:mm] Seu texto aqui...

    - from_me=False => HUMAN
    - from_me=True  => AI
    """
    file_path = _chatmemory_file(company_id, contact_phone)

    # Obtém data/hora atual no fuso São Paulo:
    sp_tz = pytz.timezone("America/Sao_Paulo")
    now_dt = datetime.now(sp_tz)
    timestamp_str = now_dt.strftime("%d/%m/%Y %H:%M")

    # Define o prefixo conforme quem enviou a mensagem
    if from_me:
        prefix = "AI:"
    else:
        prefix = "HUMAN:"

    # Se quiser tratar operador de outra forma, crie outro branch ou passe
    # um parâmetro extra. Ex.: prefix = "OPER:" se a mensagem for do operador.

    # Substitui quebras de linha internas por espaço,
    # para que tudo fique em um único "line".
    single_line_content = content.replace("\n", " ")

    # Monta a linha final com prefixo + timestamp + mensagem
    line_to_write = f"{prefix}[{timestamp_str}] {single_line_content}\n"

    try:
        _ensure_chatmemory_dir()
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line_to_write)
    except Exception as e:
        logger.error(f"[MemoryManager] Erro ao escrever no arquivo {file_path}: {e}")


def append_message_to_chat_file_as_operator(company_id: int, contact_phone: str, content: str):
    """
    Salva mensagem do operador humano (enviada pelo celular) no formato OPER:
    """
    file_path = _chatmemory_file(company_id, contact_phone)

    # Obtém data/hora atual no fuso São Paulo:
    sp_tz = pytz.timezone("America/Sao_Paulo")
    now_dt = datetime.now(sp_tz)
    timestamp_str = now_dt.strftime("%d/%m/%Y %H:%M")

    # Substitui quebras de linha por espaço
    single_line_content = content.replace("\n", " ")

    # Formato OPER: para diferenciar de AI:
    line_to_write = f"OPER:[{timestamp_str}] {single_line_content}\n"

    try:
        _ensure_chatmemory_dir()
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line_to_write)
        logger.info(f"[MemoryManager] Mensagem do operador salva para {contact_phone}")
    except Exception as e:
        logger.error(f"[MemoryManager] Erro ao escrever no arquivo {file_path}: {e}")
