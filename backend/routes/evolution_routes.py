# backend/routes/evolution_routes.py

"""
Rotas para gestão de instâncias Evolution API
Seguindo o mesmo padrão das rotas Z-API (webhook.py)
"""

import os
import logging
import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.db import get_db
from backend.auth import get_current_user
from backend.runtime_settings import PUBLIC_BASE_URL

logger = logging.getLogger(__name__)

router = APIRouter()

# API Key global da Evolution (mesma para todas as empresas)
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8081")
BACKEND_URL = os.getenv("BACKEND_URL", PUBLIC_BASE_URL)

# Cache em memória para QR codes (instance_name -> qrcode_base64)
qrcode_cache = {}


# ==========================================
# MODELOS
# ==========================================

class EvolutionConnectRequest(BaseModel):
    instance_name: str  # Nome da instância (ex: "companya-9-business")


class EvolutionDisconnectRequest(BaseModel):
    pass  # Não precisa de params, usa os dados da empresa


# ==========================================
# ENDPOINTS
# ==========================================

@router.post("/evolution/connect")
def connect_evolution(
    data: EvolutionConnectRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Conecta uma empresa ao Evolution API

    1. Cria instância na Evolution API
    2. Salva credenciais no banco (companies table)

    Equivalente ao /whatsapp/connect para Z-API
    """
    logger.info(f"Conectando Evolution API para {user.email}, instância: {data.instance_name}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    if not EVOLUTION_API_KEY:
        raise HTTPException(status_code=500, detail="Evolution API Key não configurada no servidor.")

    # 1. Criar instância na Evolution API
    try:
        url = f"{EVOLUTION_API_URL}/instance/create"
        headers = {
            "apikey": EVOLUTION_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "instanceName": data.instance_name,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS"
        }

        logger.info(f"Criando instância na Evolution API: {url}")
        response = requests.post(url, headers=headers, json=payload)
        logger.info(f"Status: {response.status_code}, Response: {response.text}")

        if response.status_code not in [200, 201]:
            error_msg = response.json().get("message", "Erro desconhecido")
            raise HTTPException(
                status_code=400,
                detail=f"Falha ao criar instância na Evolution API: {error_msg}"
            )

        evolution_data = response.json()
        logger.info(f"Instância criada com sucesso: {evolution_data}")

        # 1.5. Configurar webhook para receber QR code
        try:
            webhook_url = f"{BACKEND_URL}/webhook/evolution/webhook/{data.instance_name}"
            webhook_payload = {
                "webhook": {
                    "enabled": True,
                    "url": webhook_url,
                    "byEvents": False,
                    "base64": True,
                    "events": [
                        "QRCODE_UPDATED",
                        "CONNECTION_UPDATE"
                    ]
                }
            }

            webhook_config_url = f"{EVOLUTION_API_URL}/webhook/set/{data.instance_name}"
            logger.info(f"Configurando webhook: {webhook_config_url}")
            webhook_response = requests.post(webhook_config_url, headers=headers, json=webhook_payload)
            logger.info(f"Webhook configurado: {webhook_response.status_code} - {webhook_response.text}")
        except Exception as webhook_err:
            logger.warning(f"Erro ao configurar webhook (continuando): {str(webhook_err)}")

        # 1.6. Iniciar conexão (gerar QR code)
        try:
            connect_url = f"{EVOLUTION_API_URL}/instance/connect/{data.instance_name}"
            logger.info(f"Iniciando conexão: {connect_url}")
            connect_response = requests.get(connect_url, headers=headers)
            logger.info(f"Conexão iniciada: {connect_response.status_code}")

            # Aguardar e tentar obter QR code
            import time
            time.sleep(3)  # Aguardar 3 segundos para o QR code ser gerado

            # Buscar QR code da instância
            qr_url = f"{EVOLUTION_API_URL}/instance/connect/{data.instance_name}"
            for attempt in range(5):  # Tentar 5 vezes
                qr_response = requests.get(qr_url, headers=headers)
                qr_data = qr_response.json()
                logger.info(f"Tentativa {attempt + 1} de obter QR code: {qr_data}")

                if qr_data.get("base64"):
                    # Armazenar no cache
                    qrcode_cache[data.instance_name] = qr_data["base64"]
                    logger.info(f"QR Code armazenado no cache para {data.instance_name}")
                    break
                elif qr_data.get("pairingCode"):
                    # Se tiver pairingCode, também armazenar
                    qrcode_cache[data.instance_name] = f"pairing:{qr_data['pairingCode']}"
                    logger.info(f"Pairing code armazenado para {data.instance_name}")
                    break

                time.sleep(2)  # Aguardar 2 segundos antes de tentar novamente

        except Exception as conn_err:
            logger.warning(f"Erro ao iniciar conexão (continuando): {str(conn_err)}")

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao conectar com Evolution API: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao conectar com Evolution API: {str(e)}"
        )

    # 2. Salvar no banco de dados
    try:
        result = db.execute(
            text("""
                UPDATE companies
                SET evolution_instance_id = :instance_id,
                    evolution_api_key = :api_key,
                    evolution_api_url = :api_url
                WHERE id = :company_id
            """),
            {
                "instance_id": data.instance_name,
                "api_key": EVOLUTION_API_KEY,
                "api_url": EVOLUTION_API_URL,
                "company_id": user.company_id
            }
        )
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(
                status_code=400,
                detail="Não foi possível salvar as configurações (empresa não encontrada?)."
            )

        logger.info(f"Configurações Evolution salvas para empresa {user.company_id}")

    except Exception as e:
        logger.error(f"Erro ao salvar no banco: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao salvar configurações: {str(e)}"
        )

    return {
        "message": "Instância Evolution criada e configurada com sucesso!",
        "instance_name": data.instance_name
    }


@router.get("/evolution/config")
def get_evolution_config(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtém configuração Evolution da empresa
    Equivalente ao /whatsapp/config para Z-API
    """
    logger.info(f"Obtendo config Evolution para {user.email}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    company_data = db.execute(
        text("""
            SELECT evolution_instance_id, evolution_api_key, evolution_api_url
            FROM companies
            WHERE id = :cid
        """),
        {"cid": user.company_id}
    ).fetchone()

    if not company_data:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")

    if not company_data.evolution_instance_id:
        raise HTTPException(status_code=400, detail="Configuração Evolution não encontrada.")

    return {
        "instance_id": company_data.evolution_instance_id,
        "api_url": company_data.evolution_api_url
    }


@router.post("/evolution/webhook/{instance_name}")
async def evolution_webhook(instance_name: str, payload: dict, db: Session = Depends(get_db)):
    """
    Webhook para receber eventos da Evolution API
    - qrcode.updated: Armazena QR code em cache
    - connection.update: Detecta conexão/desconexão
    - messages.upsert: Enfileira mensagens para processamento
    """
    event = payload.get("event")

    logger.info(f"[EVOLUTION_WEBHOOK] instance={instance_name}, event={event}")
    logger.info(f"[EVOLUTION_WEBHOOK] payload completo: {payload}")

    if event == "qrcode.updated":
        qrcode_data = payload.get("data", {})
        qrcode_base64 = qrcode_data.get("qrcode")

        if qrcode_base64:
            qrcode_cache[instance_name] = qrcode_base64
            logger.info(f"[EVOLUTION_WEBHOOK] QR Code armazenado para {instance_name}")
        else:
            logger.warning(f"[EVOLUTION_WEBHOOK] QR Code vazio para {instance_name}")

    elif event == "connection.update":
        connection_data = payload.get("data", {})
        state = connection_data.get("state")

        if state == "open":
            # Limpar QR code do cache quando conectar
            if instance_name in qrcode_cache:
                del qrcode_cache[instance_name]
                logger.info(f"[EVOLUTION_WEBHOOK] QR Code removido do cache (conectado): {instance_name}")

    elif event == "messages.upsert":
        # Processar mensagens recebidas
        logger.info(f"[EVOLUTION_WEBHOOK] Mensagem recebida, enfileirando para processamento")

        message_data = payload.get("data", {})

        # Validar se empresa existe
        company_row = db.execute(
            text("SELECT id FROM companies WHERE evolution_instance_id = :instance_name"),
            {"instance_name": instance_name}
        ).fetchone()

        if not company_row:
            logger.error(f"[EVOLUTION_WEBHOOK] Empresa não encontrada para instance={instance_name}")
            return {"status": "error", "detail": "Company not found"}

        company_id = company_row.id
        logger.info(f"[EVOLUTION_WEBHOOK] Empresa encontrada: company_id={company_id}")

        # Importar task de processamento Evolution
        from backend.worker.process_evolution_message import process_incoming_evolution_message

        # Enfileirar na fila dedicada Evolution
        try:
            task = process_incoming_evolution_message.apply_async(
                args=[message_data, instance_name],
                queue='evolution_messages_queue',
                retry=True,
                retry_policy={
                    'max_retries': 3,
                    'interval_start': 0,
                    'interval_step': 0.2,
                    'interval_max': 0.2,
                }
            )

            task_id = task.id if task else None
            logger.info(f"[EVOLUTION_WEBHOOK] Mensagem enfileirada: task_id={task_id}, company_id={company_id}")

        except Exception as e:
            logger.error(f"[EVOLUTION_WEBHOOK] Erro ao enfileirar no Celery: {e}")
            return {"status": "error", "detail": str(e)}

    return {"status": "ok"}


@router.get("/evolution/qrcode")
def get_evolution_qrcode(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtém QR Code da instância Evolution
    1. Verifica se já está conectado (não precisa de QR Code)
    2. Tenta buscar do cache (webhook)
    3. Se não estiver no cache, busca diretamente da Evolution API
    """
    logger.info(f"Obtendo QR Code Evolution para {user.email}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    company_data = db.execute(
        text("""
            SELECT evolution_instance_id, evolution_api_key, evolution_api_url
            FROM companies
            WHERE id = :cid
        """),
        {"cid": user.company_id}
    ).fetchone()

    if not company_data or not company_data.evolution_instance_id:
        raise HTTPException(status_code=400, detail="Configuração Evolution não encontrada.")

    instance_name = company_data.evolution_instance_id

    # 0. Verificar se já está conectado antes de buscar QR Code
    try:
        status_url = f"{company_data.evolution_api_url}/instance/connectionState/{instance_name}"
        status_headers = {"apikey": company_data.evolution_api_key}
        status_response = requests.get(status_url, headers=status_headers)

        if status_response.status_code == 200:
            status_data = status_response.json()
            # O state está dentro de "instance"
            instance_data = status_data.get("instance", {})
            if instance_data.get("state") == "open":
                logger.info(f"Instância {instance_name} já está conectada, não precisa de QR Code")
                raise HTTPException(
                    status_code=400,
                    detail="WhatsApp já está conectado. QR Code não é necessário."
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Erro ao verificar status antes de buscar QR Code: {e}")

    # 1. Tentar buscar do cache primeiro (mais rápido)
    qrcode_base64 = qrcode_cache.get(instance_name)

    if qrcode_base64:
        logger.info(f"QR Code encontrado no cache para {instance_name}")
        return {"qrcode": qrcode_base64}

    # 2. Se não estiver no cache, buscar diretamente da Evolution API
    logger.info(f"QR Code não está no cache, buscando da Evolution API para {instance_name}")

    try:
        url = f"{company_data.evolution_api_url}/instance/connect/{instance_name}"
        headers = {"apikey": company_data.evolution_api_key}

        logger.info(f"Buscando QR Code: {url}")
        response = requests.get(url, headers=headers)
        logger.info(f"Status: {response.status_code}")

        if response.status_code != 200:
            logger.warning(f"Falha ao obter QR Code: {response.text}")
            raise HTTPException(
                status_code=400,
                detail="QR Code não disponível ainda. Aguarde alguns segundos e tente novamente."
            )

        data = response.json()

        # Verificar se tem QR code na resposta
        qrcode_base64 = data.get("base64")

        if qrcode_base64:
            # Armazenar no cache para próximas requisições
            qrcode_cache[instance_name] = qrcode_base64
            logger.info(f"QR Code obtido e armazenado no cache para {instance_name}")
            return {"qrcode": qrcode_base64}

        # Se não tiver base64, verificar se tem pairingCode
        pairing_code = data.get("pairingCode")
        if pairing_code:
            logger.info(f"Pairing code disponível para {instance_name}: {pairing_code}")
            # Retornar indicação de pairing code (frontend pode exibir diferente)
            return {"qrcode": f"data:text/plain;base64,{pairing_code}", "pairingCode": pairing_code}

        # Se não tiver nem QR nem pairing code
        logger.warning(f"Resposta da Evolution API sem QR code ou pairing code: {data}")
        raise HTTPException(
            status_code=400,
            detail="QR Code não disponível ainda. Aguarde alguns segundos e tente novamente."
        )

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao buscar QR Code da Evolution API: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao conectar com Evolution API: {str(e)}"
        )


@router.get("/evolution/status")
def get_evolution_status(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtém status da conexão Evolution
    Equivalente ao /whatsapp/status para Z-API
    """
    logger.info(f"Obtendo status Evolution para {user.email}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    company_data = db.execute(
        text("""
            SELECT evolution_instance_id, evolution_api_key, evolution_api_url
            FROM companies
            WHERE id = :cid
        """),
        {"cid": user.company_id}
    ).fetchone()

    if not company_data or not company_data.evolution_instance_id:
        raise HTTPException(status_code=400, detail="Configuração Evolution não encontrada.")

    try:
        url = f"{company_data.evolution_api_url}/instance/connectionState/{company_data.evolution_instance_id}"
        headers = {"apikey": company_data.evolution_api_key}

        logger.info(f"Obtendo status: {url}")
        response = requests.get(url, headers=headers)
        logger.info(f"Status: {response.status_code}, Response: {response.text}")

        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Falha ao obter status da Evolution API."
            )

        data = response.json()
        # O state está dentro de "instance"
        instance_data = data.get("instance", {})
        state = instance_data.get("state", "unknown")

        return {
            "connected": state == "open",
            "state": state
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao obter status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao conectar com Evolution API: {str(e)}"
        )


@router.get("/evolution/device")
def get_evolution_device(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtém dados do device conectado na Evolution
    Equivalente ao /whatsapp/device para Z-API
    """
    logger.info(f"Obtendo device Evolution para {user.email}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    company_data = db.execute(
        text("""
            SELECT evolution_instance_id, evolution_api_key, evolution_api_url
            FROM companies
            WHERE id = :cid
        """),
        {"cid": user.company_id}
    ).fetchone()

    if not company_data or not company_data.evolution_instance_id:
        raise HTTPException(status_code=400, detail="Configuração Evolution não encontrada.")

    try:
        url = f"{company_data.evolution_api_url}/instance/fetchInstances"
        headers = {"apikey": company_data.evolution_api_key}
        params = {"instanceName": company_data.evolution_instance_id}

        logger.info(f"Obtendo device: {url}")
        response = requests.get(url, headers=headers, params=params)
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Response: {response.text}")

        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Falha ao obter dados do device."
            )

        data = response.json()

        # Normalizar resposta para formato compatível com Z-API
        if isinstance(data, list) and len(data) > 0:
            instance = data[0]
        else:
            instance = data

        return {
            "id": instance.get("name", ""),
            "name": instance.get("profileName", ""),
            "phone": instance.get("ownerJid", "").split("@")[0],
            "imgUrl": instance.get("profilePicUrl", ""),  # Corrigido: profilePicUrl em vez de profilePictureUrl
            "isBusiness": instance.get("businessId") is not None,
            "device": {
                "sessionName": instance.get("name", ""),
                "device_model": instance.get("integration", "")  # WHATSAPP-BAILEYS
            }
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao obter device: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao conectar com Evolution API: {str(e)}"
        )


@router.post("/evolution/disconnect")
def disconnect_evolution(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Desconecta instância Evolution (logout do WhatsApp)
    Equivalente ao /whatsapp/disconnect para Z-API
    """
    logger.info(f"Desconectando Evolution para {user.email}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    company_data = db.execute(
        text("""
            SELECT evolution_instance_id, evolution_api_key, evolution_api_url
            FROM companies
            WHERE id = :cid
        """),
        {"cid": user.company_id}
    ).fetchone()

    if not company_data or not company_data.evolution_instance_id:
        raise HTTPException(status_code=400, detail="Configuração Evolution não encontrada.")

    try:
        url = f"{company_data.evolution_api_url}/instance/logout/{company_data.evolution_instance_id}"
        headers = {"apikey": company_data.evolution_api_key}

        logger.info(f"Desconectando: {url}")
        response = requests.delete(url, headers=headers)
        logger.info(f"Status: {response.status_code}")

        if response.status_code not in [200, 204]:
            raise HTTPException(
                status_code=400,
                detail="Falha ao desconectar da Evolution API."
            )

        return {"message": "Instância desconectada com sucesso!"}

    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao desconectar: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao conectar com Evolution API: {str(e)}"
        )


@router.post("/evolution/reset")
def reset_evolution(
    user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Remove completamente a configuração Evolution da empresa
    Equivalente ao /whatsapp/reset para Z-API
    """
    logger.info(f"Resetando Evolution para {user.email}")

    if not user.company_id:
        raise HTTPException(status_code=400, detail="Usuário sem empresa associada.")

    company_data = db.execute(
        text("""
            SELECT evolution_instance_id, evolution_api_key, evolution_api_url
            FROM companies
            WHERE id = :cid
        """),
        {"cid": user.company_id}
    ).fetchone()

    # Tentar deletar instância na Evolution API (se existir)
    if company_data and company_data.evolution_instance_id:
        try:
            url = f"{company_data.evolution_api_url}/instance/delete/{company_data.evolution_instance_id}"
            headers = {"apikey": company_data.evolution_api_key}

            logger.info(f"Deletando instância: {url}")
            response = requests.delete(url, headers=headers)
            logger.info(f"Status: {response.status_code}")

        except Exception as e:
            logger.warning(f"Erro ao deletar instância (continuando): {str(e)}")

    # Limpar do banco de dados
    try:
        result = db.execute(
            text("""
                UPDATE companies
                SET evolution_instance_id = NULL,
                    evolution_api_key = NULL,
                    evolution_api_url = NULL
                WHERE id = :company_id
            """),
            {"company_id": user.company_id}
        )
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(
                status_code=400,
                detail="Não foi possível resetar as configurações."
            )

        logger.info(f"Configurações Evolution removidas para empresa {user.company_id}")
        return {"message": "Configuração Evolution resetada com sucesso!"}

    except Exception as e:
        logger.error(f"Erro ao resetar: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao resetar configurações: {str(e)}"
        )
