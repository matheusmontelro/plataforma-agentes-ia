
import requests
from fastapi import HTTPException, status
from backend.logging_config import logger
from typing import List, Dict, Any, Optional
import base64
from datetime import datetime, timezone, timedelta # Adicionar timezone

CLINICORP_BASE_URL = "https://api.clinicorp.com/rest/v1"

# -----------------------------------------
# Função Auxiliar Central para Requisições
# -----------------------------------------
def _make_clinicorp_request(
    method: str,
    endpoint: str,
    params: Optional[Dict] = None,
    data_payload: Optional[Dict] = None, # Renomeado, usado para 'files' agora
    subscriber_id: Optional[str] = None,
    api_token: Optional[str] = None
) -> Any:
    """
    Função auxiliar para API Clinicorp. Usa Basic Auth.
    Envia 'params' como query string.
    Envia 'data_payload' como form data (data=) para POST/PUT etc.
    """
    url = f"{CLINICORP_BASE_URL}{endpoint}"
    query_params = params or {}

    # --- Configurar Cabeçalhos ---
    headers = {
        'Accept': 'application/json'
    }
    if subscriber_id and api_token:
        auth_string = f"{subscriber_id}:{api_token}"
        encoded_auth = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
        headers['Authorization'] = f'Basic {encoded_auth}'
    else:
        logger.warning(f"Tentando chamada Clinicorp sem credenciais: {method} {url}")

    # --- Montar argumentos para requests.request ---
    request_args = {
        "method": method.upper(),
        "url": url,
        "params": query_params,
        "headers": headers,
        "timeout": 60
    }

    # --- Usar abordagem híbrida: multipart para customer, JSON para appointment ---
    if method.upper() not in ["GET", "HEAD", "OPTIONS"] and data_payload is not None:
        # IDs que precisam ser enviados como inteiros
        integer_fields = ['Company_BusinessId', 'Dentist_PersonId', 'Customer_PersonId']

        # Para endpoints de appointment, usar JSON
        if "/appointment/" in endpoint:
            # Converter campos inteiros para int no JSON
            json_payload = {}
            for key, value in data_payload.items():
                if value is not None:
                    if key in integer_fields:
                        try:
                            json_payload[key] = int(value)
                        except (ValueError, TypeError):
                            json_payload[key] = value
                    else:
                        json_payload[key] = value
                else:
                    json_payload[key] = None

            request_args["json"] = json_payload
            headers['Content-Type'] = 'application/json'
            logger.info(f"[CLINICORP APPOINTMENT] Enviando via JSON para {url}: {json_payload}")
        else:
            # Para outros endpoints (customer/create), usar multipart
            files_payload = {}
            for key, value in data_payload.items():
                if value is not None:
                    files_payload[key] = (None, str(value))
                else:
                    files_payload[key] = (None, '')

            request_args["files"] = files_payload
            logger.info(f"[CLINICORP] Enviando via multipart para {url}")
    # --- FIM DA MUDANÇA ---

    try:
        # ... (log dos args como antes, mas agora pode mostrar 'files' em vez de 'has_data') ...
        log_args_display = {k: v for k, v in request_args.items() if k not in ['headers', 'data']}
        log_args_display['headers'] = list(headers.keys())
        log_args_display['has_data_payload'] = 'data' in request_args
        logger.debug(f"Executando Clinicorp Request: {log_args_display}")

        response = requests.request(**request_args)
        response.raise_for_status()

        # --- Tratamento da Resposta de Sucesso (2xx) ---
        if response.status_code == 204 or not response.text:
            return None
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            logger.error(f"Clinicorp - Resposta 2xx não é JSON (Status: {response.status_code}) para {method} {url}. Text: {response.text[:500]}...")
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Resposta inválida (não JSON) da API Clinicorp.")

    except requests.exceptions.RequestException as e:
        # --- Tratamento de Erros ---
        # ... (lógica de tratamento de erro e logging como antes) ...
        status_code = getattr(e.response, 'status_code', 502)
        detail_msg = f"Erro ao comunicar com Clinicorp: {e}"
        response_text = e.response.text[:500] + "..." if e.response is not None and e.response.text else "N/A"

        if status_code == 400:
            # Tenta extrair a mensagem de erro do JSON se a resposta 400 for JSON
            try:
                error_json = e.response.json()
                if isinstance(error_json, dict) and error_json.get("Message"):
                     detail_msg = f"Erro 400 da API Clinicorp: {error_json['Message']}"
                else:
                     detail_msg = f"Erro 400: Requisição malformada ou ilegal enviada para a API Clinicorp. Resposta não JSON ou sem Message: {response_text}"
            except: # Se a resposta 400 não for JSON (como o HTML visto antes)
                detail_msg = f"Erro 400: Requisição malformada ou ilegal enviada para a API Clinicorp. Resposta HTML ou inválida: {response_text}"
            logger.error(f"Clinicorp retornou 400 Bad Request. Detalhe: {detail_msg}")
        elif status_code == 401:
             detail_msg = "Erro 401: Não autorizado pela API Clinicorp. Verifique Credenciais."
        # ...(outros status codes)

        logger.error(f"Erro na chamada à API Clinicorp ({request_args.get('method')} {request_args.get('url')}): {detail_msg}")
        if e.request:
            try: logger.error(f"Headers ENVIADOS pelo Backend: {e.request.headers}") # Headers ainda são úteis
            except: pass
            # Logar o body preparado para 'files' pode ser complexo, focamos nos headers
            # try: logger.error(f"Payload (files) preparado: {request_args.get('files')}")
            # except: pass
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail_msg)

# --- Funções Específicas ---

def get_clinicorp_business_units(subscriber_id: str, api_token: str) -> List[Dict[str, Any]]:
    """Busca empresas. GET /business/list"""
    endpoint = "/business/list" # SEM barra no final para GET
    response_data = _make_clinicorp_request(
        method="GET", endpoint=endpoint, params={"subscriber_id": subscriber_id},
        subscriber_id=subscriber_id, api_token=api_token
    )
    if not isinstance(response_data, list): return []
    logger.info(f"Sucesso: GET {endpoint}. Count: {len(response_data)}")
    return response_data

def get_clinicorp_professionals(subscriber_id: str, api_token: str) -> List[Dict[str, Any]]:
    """Busca profissionais. GET /professional/list_all_professionals"""
    endpoint = "/professional/list_all_professionals" # SEM barra no final para GET
    response_data = _make_clinicorp_request(
        method="GET", endpoint=endpoint, params={"subscriber_id": subscriber_id},
        subscriber_id=subscriber_id, api_token=api_token
    )
    if not isinstance(response_data, list): return []
    logger.info(f"Sucesso: GET {endpoint}. Count: {len(response_data)}")
    return response_data

def get_clinicorp_customer(subscriber_id: str, api_token: str, identifier_field: str, identifier_value: str) -> Optional[Dict[str, Any]]:
    """Busca cliente. GET /customer/get"""
    endpoint = "/customer/get" # SEM barra no final para GET
    params = {"subscriber_id": subscriber_id, identifier_field: identifier_value}
    logger.debug(f"Executando: GET {endpoint} com params {params}")
    try:
        response_data = _make_clinicorp_request(
            method="GET", endpoint=endpoint, params=params,
            subscriber_id=subscriber_id, api_token=api_token
        )
        # Trata lista ou dict na resposta
        customer_dict = None
        if isinstance(response_data, list) and len(response_data) > 0 and isinstance(response_data[0], dict):
            if len(response_data) > 1: logger.warning(f"Clinicorp retornou múltiplos clientes para {identifier_field}={identifier_value}. Usando o primeiro.")
            customer_dict = response_data[0]
        elif isinstance(response_data, dict) and response_data: customer_dict = response_data
        elif isinstance(response_data, dict) and not response_data: return None # {} = não encontrado

        if customer_dict:
            customer_id = customer_dict.get("id") or customer_dict.get("CustomerId")
            if customer_id is not None:
                logger.info(f"Cliente encontrado Clinicorp: ID={customer_id}")
                if "CustomerId" not in customer_dict: customer_dict["CustomerId"] = customer_id
                return customer_dict
        return None
    except HTTPException as e:
        if e.status_code == 404: return None
        raise

def create_clinicorp_customer(subscriber_id: str, api_token: str, customer_data: Dict[str, Any]) -> Dict[str, Any]:
    """Cria cliente. POST /customer/create/"""
    endpoint = "/customer/create/" # COM barra no final
    # Payload como form data, incluindo subscriber_id e flags de ignore
    payload = {
        **customer_data,
        "subscriber_id": subscriber_id,
        "IgnoreSameName": "X", # Adicionado para replicar Make.com
        "IgnoreSameDoc": "X"   # Adicionado para replicar Make.com
    }
    payload = {k: v for k, v in payload.items() if v is not None} # Remover Nones, API pode não gostar

    logger.info(f"[CLINICORP CREATE CUSTOMER] Executando: POST {endpoint}. Payload (data): {payload}")
    response_data = _make_clinicorp_request(
        method="POST", endpoint=endpoint, data_payload=payload, # Usar data_payload
        subscriber_id=subscriber_id, api_token=api_token
    )
    # Verifica 'id' na resposta
    created_customer_id = response_data.get("id") if isinstance(response_data, dict) else None
    if created_customer_id is not None:
         logger.info(f"Sucesso: POST {endpoint}. ID Cliente Criado: {created_customer_id}")
         if "CustomerId" not in response_data: response_data["CustomerId"] = created_customer_id
         return response_data
    else:
         error_message = response_data.get("Message", "Resposta inesperada") if isinstance(response_data, dict) else "Resposta inesperada ou vazia"
         logger.error(f"Falha: POST {endpoint}. Resposta: {response_data}")
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Erro ao criar cliente no Clinicorp: {error_message}")

def create_clinicorp_appointment(subscriber_id: str, api_token: str, appointment_data: Dict[str, Any]) -> Dict[str, Any]:
    """Cria agendamento. POST /appointment/create_appointment_by_api/"""
    endpoint = "/appointment/create_appointment_by_api/" # COM barra no final
    logger.debug(f"Executando: POST {endpoint}. Payload (data): {appointment_data}")
    response_data = _make_clinicorp_request(
        method="POST", endpoint=endpoint, data_payload=appointment_data, # Usar data_payload
        subscriber_id=subscriber_id, api_token=api_token
    )
    # Verifica 'id' na resposta (pode ser lista ou dict)
    appointment_info = None
    if isinstance(response_data, list) and len(response_data) > 0: appointment_info = response_data[0]
    elif isinstance(response_data, dict): appointment_info = response_data

    created_appointment_id = appointment_info.get("id") if appointment_info else None
    if created_appointment_id is not None:
         logger.info(f"Sucesso: POST {endpoint}. ID Agendamento Criado: {created_appointment_id}")
         return appointment_info
    else:
         error_message = appointment_info.get("Message", "Resposta inesperada") if appointment_info else "Resposta inesperada ou vazia"
         logger.error(f"Falha: POST {endpoint}. Resposta: {response_data}")
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Erro ao criar agendamento no Clinicorp: {error_message}")

def cancel_clinicorp_appointment_api(subscriber_id: str, api_token: str, clinicorp_appointment_id: int) -> bool:
    """Cancela agendamento. POST /appointment/cancel_appointment/"""
    endpoint = "/appointment/cancel_appointment/" # COM barra no final
    payload = {"subscriber_id": subscriber_id, "id": clinicorp_appointment_id}
    logger.debug(f"Executando: POST {endpoint}. Payload (data): {payload}")
    try:
        response_data = _make_clinicorp_request(
            method="POST", endpoint=endpoint, data_payload=payload, # Usar data_payload
            subscriber_id=subscriber_id, api_token=api_token
        )
        # Verifica flag 'Deleted'
        cancellation_info = None
        if isinstance(response_data, list) and len(response_data) > 0: cancellation_info = response_data[0]
        elif isinstance(response_data, dict): cancellation_info = response_data

        if cancellation_info and cancellation_info.get('Deleted') == 'X':
             logger.info(f"Sucesso: POST {endpoint} para ID {clinicorp_appointment_id}.")
             return True
        else:
             logger.warning(f"POST {endpoint} não confirmou cancelamento ('Deleted' != 'X'). Resposta: {response_data}")
             return False
    except HTTPException as e:
        logger.error(f"Erro HTTP ao cancelar agendamento Clinicorp ID={clinicorp_appointment_id}: {e.detail}")
        return False
    except Exception as e:
        logger.exception(f"Erro inesperado ao cancelar agendamento Clinicorp ID={clinicorp_appointment_id}: {e}")
        return False
