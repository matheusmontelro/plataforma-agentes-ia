
import re
import json
import traceback
from typing import Dict, Any, Optional

def extract_json_from_response(response: str) -> Dict[str, Any]:
    """
    Extrai um bloco de JSON entre <json> e </json> do texto do LLM.
    Retorna um dicionário. Se não encontrar JSON, retorna {}.
    """
    try:
        json_match = re.search(r'<json>(.*?)</json>', response, re.DOTALL)
        if json_match:
            raw_json = json_match.group(1)
            return json.loads(raw_json)
    except json.JSONDecodeError:
        print("Erro ao decodificar JSON da resposta:")
        print(traceback.format_exc())

    return {}

def extract_info_from_invalid_json(json_str: str) -> Dict[str, Any]:
    """
    Se o JSON estiver inválido, tenta extrair manualmente
    algumas informações usando regex.
    Exemplo: 'tratamento', 'cliente', 'nome', etc.
    """
    info = {}
    patterns = {
        'tratamento': r'"tratamento":\s*"?([^",\}]+)"?',
        'cliente': r'"cliente":\s*"?([^",\}]+)"?',
        'nome': r'"nome":\s*"?([^",\}]+)"?',
        'data': r'"data":\s*"?([^",\}]+)"?',
        'horario': r'"horario":\s*"?([^",\}]+)"?',
        'agendamento_confirmado': r'"agendamento_confirmado":\s*(true|false)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, json_str)
        if match:
            info[key] = match.group(1)

    return info

def sanitize_user_input(text: str) -> str:
    """
    Exemplo de função para sanitizar texto de entrada do usuário,
    removendo caracteres indesejados ou normalizando.
    """
    return text.strip()

def debug_print(label: str, content: Any):
    """
    Exemplo de função auxiliar para imprimir logs de debug,
    caso deseje padronizar logs no seu projeto.
    """
    print(f"[DEBUG {label}]: {content}")
