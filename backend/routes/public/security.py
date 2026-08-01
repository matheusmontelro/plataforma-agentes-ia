"""
Configurações de segurança para rotas públicas
"""

import os
from fastapi import HTTPException, Header, Depends
from typing import Optional
import hashlib
import hmac
import time
from functools import lru_cache

ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
PUBLIC_API_KEY = os.getenv("PUBLIC_API_KEY")
PUBLIC_API_SECRET = os.getenv("PUBLIC_API_SECRET")

if ENVIRONMENT == "production" and (not PUBLIC_API_KEY or not PUBLIC_API_SECRET):
    raise RuntimeError("PUBLIC_API_KEY and PUBLIC_API_SECRET are required in production")

# Rate limiting simples (em produção, use Redis)
request_timestamps = {}
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # segundos
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "10"))  # requisições por janela


def validate_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """
    Valida a API Key do header da requisição
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="API Key não fornecida. Use o header X-API-Key"
        )

    if x_api_key != PUBLIC_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="API Key inválida"
        )

    return True


def validate_api_signature(
    x_api_key: Optional[str] = Header(None),
    x_api_signature: Optional[str] = Header(None),
    x_api_timestamp: Optional[str] = Header(None)
) -> bool:
    """
    Valida a assinatura HMAC da requisição para segurança adicional
    """
    if not all([x_api_key, x_api_signature, x_api_timestamp]):
        raise HTTPException(
            status_code=401,
            detail="Headers de autenticação incompletos"
        )

    # Verifica se o timestamp não é muito antigo (5 minutos)
    try:
        timestamp = int(x_api_timestamp)
        current_time = int(time.time())
        if abs(current_time - timestamp) > 300:  # 5 minutos
            raise HTTPException(
                status_code=401,
                detail="Timestamp da requisição expirado"
            )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Timestamp inválido"
        )

    # Valida a assinatura HMAC
    message = f"{x_api_key}:{x_api_timestamp}"
    expected_signature = hmac.new(
        PUBLIC_API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(x_api_signature, expected_signature):
        raise HTTPException(
            status_code=401,
            detail="Assinatura inválida"
        )

    return True


def rate_limit_check(
    x_api_key: Optional[str] = Header(None),
    x_forwarded_for: Optional[str] = Header(None)
) -> bool:
    """
    Implementa rate limiting básico por API Key ou IP
    """
    # Usa API Key ou IP como identificador
    identifier = x_api_key or x_forwarded_for or "unknown"

    current_time = time.time()

    # Limpa timestamps antigos
    if identifier in request_timestamps:
        request_timestamps[identifier] = [
            ts for ts in request_timestamps[identifier]
            if current_time - ts < RATE_LIMIT_WINDOW
        ]
    else:
        request_timestamps[identifier] = []

    # Verifica limite
    if len(request_timestamps[identifier]) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Limite de requisições excedido. Máximo {RATE_LIMIT_MAX_REQUESTS} requisições por {RATE_LIMIT_WINDOW} segundos"
        )

    # Adiciona timestamp atual
    request_timestamps[identifier].append(current_time)

    return True


# Dependência combinada para usar em rotas que precisam de todas as validações
async def full_security_check(
    api_key_valid: bool = Depends(validate_api_key),
    rate_limit_ok: bool = Depends(rate_limit_check)
) -> bool:
    """
    Combina todas as validações de segurança
    """
    return api_key_valid and rate_limit_ok


# Função auxiliar para gerar exemplo de assinatura
def generate_signature_example():
    """
    Gera um exemplo de como criar a assinatura HMAC
    """
    api_key = "your-api-key"
    timestamp = str(int(time.time()))
    message = f"{api_key}:{timestamp}"
    signature = hmac.new(
        "your-api-secret".encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    return {
        "headers": {
            "X-API-Key": api_key,
            "X-API-Timestamp": timestamp,
            "X-API-Signature": signature
        }
    }
