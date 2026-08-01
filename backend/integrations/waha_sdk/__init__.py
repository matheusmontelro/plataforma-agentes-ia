"""
WAHA SDK - WhatsApp HTTP API com Engine GOWS

Documentação oficial: https://waha.devlike.pro/docs/

Engine GOWS (Go WebSocket):
- Mais leve: 30-50 MB RAM (vs 200 MB WEBJS, 70 MB NOWEB)
- Mais rápida: Golang é ~10x mais rápido que Node.js
- Mais estável: Concorrência nativa do Go
- Vídeos funcionam: Sem problemas de timeout ✅

Exemplo de uso:
    >>> from backend.integrations.waha_sdk import get_client
    >>> client = get_client("http://localhost:3000", "api_key_aqui")
    >>> client.send_text("default", "5500000000004", "Olá!")
    >>> client.send_video("default", "5500000000004", "http://servidor/video.mp4")
"""

import requests
import logging
import os
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class WAHAEngine(str, Enum):
    """Engines disponíveis no WAHA"""
    WEBJS = "WEBJS"  # Browser-based (Puppeteer + Chrome)
    NOWEB = "NOWEB"  # WebSocket Node.js
    GOWS = "GOWS"    # WebSocket Golang ⭐ Recomendado


class SessionStatus(str, Enum):
    """Status possíveis de uma sessão WAHA"""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    SCAN_QR_CODE = "SCAN_QR_CODE"
    WORKING = "WORKING"
    FAILED = "FAILED"


@dataclass
class WAHASession:
    """Informações de uma sessão WAHA"""
    name: str
    status: SessionStatus
    engine: WAHAEngine
    me: Optional[Dict[str, Any]] = None


class WAHAException(Exception):
    """Exceção base para erros WAHA"""
    pass


class WAHAConnectionError(WAHAException):
    """Erro de conexão com WAHA"""
    pass


class WAHASessionError(WAHAException):
    """Erro relacionado a sessão"""
    pass


class WAHAClient:
    """
    Cliente para WAHA WhatsApp HTTP API

    Args:
        base_url: URL base do servidor WAHA (ex: http://localhost:3000)
        api_key: Chave de API (X-Api-Key header)
        timeout: Timeout padrão em segundos (default: 60)
        default_engine: Engine padrão para novas sessões (default: GOWS)

    Exemplo:
        >>> client = WAHAClient("http://localhost:3000", "sua_api_key")
        >>> client.create_session("default", engine=WAHAEngine.GOWS)
        >>> client.send_text("default", "5500000000004", "Olá!")
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 60,
        default_engine: WAHAEngine = WAHAEngine.GOWS
    ):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.default_engine = default_engine

        self.session = requests.Session()
        self.session.headers.update({
            'X-Api-Key': api_key,
            'Content-Type': 'application/json'
        })

    def _request(
        self,
        method: str,
        endpoint: str,
        timeout: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Faz requisição HTTP para WAHA

        Args:
            method: Método HTTP (GET, POST, DELETE, etc)
            endpoint: Endpoint da API (ex: /health, /api/sessions)
            timeout: Timeout customizado (opcional)
            **kwargs: Argumentos adicionais para requests (json, params, etc)

        Returns:
            Resposta JSON da API

        Raises:
            WAHAConnectionError: Erro de conexão ou timeout
            WAHAException: Erro genérico da API
        """
        url = f"{self.base_url}{endpoint}"
        timeout = timeout or self.timeout

        try:
            logger.debug(f"[WAHA] {method} {url}")
            response = self.session.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()

            if response.content:
                return response.json()
            return {}

        except requests.exceptions.Timeout as e:
            logger.error(f"[WAHA] Timeout após {timeout}s: {url}")
            raise WAHAConnectionError(f"Timeout após {timeout}s") from e

        except requests.exceptions.RequestException as e:
            logger.error(f"[WAHA] Erro na requisição {method} {url}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    raise WAHAException(f"Erro WAHA: {error_detail}") from e
                except:
                    pass
            raise WAHAConnectionError(f"Erro na requisição: {e}") from e

    # ==========================================
    # Health Check
    # ==========================================

    def health(self) -> Dict[str, Any]:
        """
        Verifica saúde da API WAHA

        Returns:
            {"status": "ok", "version": "2025.1.0", "engine": "GOWS"}

        Example:
            >>> client.health()
            {'status': 'ok', 'version': '2025.1.0'}
        """
        return self._request('GET', '/health', timeout=5)

    # ==========================================
    # Session Management
    # ==========================================

    def create_session(
        self,
        session_name: str,
        engine: Optional[WAHAEngine] = None,
        proxy_config: Optional[Dict[str, str]] = None
    ) -> WAHASession:
        """
        Cria nova sessão WhatsApp

        Args:
            session_name: Nome único da sessão (ex: "default", "companya_68")
            engine: Engine a usar (padrão: GOWS)
            proxy_config: Configuração de proxy (opcional, padrão: None)
                Ex: {'server': 'host.docker.internal:9050', 'username': 'user', 'password': 'pass'}

        Returns:
            WAHASession com informações da sessão criada

        Example:
            # Sem proxy (comportamento original)
            >>> session = client.create_session("default", engine=WAHAEngine.GOWS)

            # Com proxy (novo recurso)
            >>> proxy = {'server': 'host.docker.internal:9050'}
            >>> session = client.create_session("cobbusiness", proxy_config=proxy)
        """
        engine = engine or self.default_engine

        logger.info(f"[WAHA] Criando sessão '{session_name}' com engine {engine}")
        if proxy_config:
            logger.info(f"[WAHA] Sessão '{session_name}' usará proxy: {proxy_config.get('server', 'configurado')}")

        # Montar configuração base
        config = {'engine': engine.value}

        # 🎯 REGRA SIMPLES: Se tiver proxy no ambiente, usa automaticamente
        default_proxy = get_default_proxy_config()
        if default_proxy:
            config['proxy'] = default_proxy
            logger.info(f"[WAHA] Proxy automático detectado: {default_proxy.get('server')}")
        elif proxy_config:
            # Se não tem proxy default, usa o específico (se passado)
            config['proxy'] = proxy_config
            logger.info(f"[WAHA] Proxy específico usado: {proxy_config.get('server')}")

        result = self._request('POST', '/api/sessions', json={
            'name': session_name,
            'config': config
        })

        return WAHASession(
            name=result['name'],
            status=SessionStatus(result['status']),
            engine=self._parse_engine_from_config(result.get('config') or result.get('engine')),
            me=result.get('me')
        )

    def _parse_engine(self, engine_value: Any) -> WAHAEngine:
        """
        Parse engine value que pode ser string ou dict

        Args:
            engine_value: Valor do campo engine (string ou dict)

        Returns:
            WAHAEngine enum

        Note:
            Algumas versões do WAHA retornam engine como dict
            {'grpc': {...}, 'gows': {...}} ao invés de string "GOWS"
        """
        # Se for None, retornar padrão
        if engine_value is None:
            return WAHAEngine.GOWS

        # Se já for string, converter diretamente
        if isinstance(engine_value, str):
            try:
                return WAHAEngine(engine_value.upper())
            except ValueError:
                logger.warning(f"[WAHA] Engine inválida '{engine_value}', usando GOWS")
                return WAHAEngine.GOWS

        # Se for dict (nova API do WAHA), tentar detectar qual engine está ativa
        if isinstance(engine_value, dict):
            # Verificar se algum engine está connected
            for engine_name in ['gows', 'noweb', 'webjs']:
                if engine_name in engine_value:
                    engine_info = engine_value[engine_name]
                    # Se for dict e tem 'connected': True, usar esse engine
                    if isinstance(engine_info, dict) and engine_info.get('connected'):
                        logger.info(f"[WAHA] Engine detectada no dict: {engine_name.upper()}")
                        return WAHAEngine(engine_name.upper())

            # Se nenhum está connected, usar GOWS como padrão
            logger.warning(f"[WAHA] Engine dict sem connected, usando GOWS: {engine_value}")
            return WAHAEngine.GOWS

        # Fallback: retornar GOWS
        logger.warning(f"[WAHA] Tipo de engine desconhecido: {type(engine_value)}, usando GOWS")
        return WAHAEngine.GOWS

    def get_session(self, session_name: str) -> WAHASession:
        """
        Obtém informações da sessão

        Args:
            session_name: Nome da sessão

        Returns:
            WAHASession com status e informações

        Example:
            >>> session = client.get_session("default")
            >>> if session.status == SessionStatus.WORKING:
            ...     print("Conectado!")
        """
        result = self._request('GET', f'/api/sessions/{session_name}')

        return WAHASession(
            name=result['name'],
            status=SessionStatus(result['status']),
            engine=self._parse_engine_from_config(result.get('config') or result.get('engine')),
            me=result.get('me')
        )

    def list_sessions(self) -> List[WAHASession]:
        """
        Lista todas as sessões

        Returns:
            Lista de WAHASession

        Example:
            >>> sessions = client.list_sessions()
            >>> for session in sessions:
            ...     print(f"{session.name}: {session.status}")
        """
        results = self._request('GET', '/api/sessions')

        return [
            WAHASession(
                name=s['name'],
                status=SessionStatus(s['status']),
                engine=self._parse_engine_from_config(s.get('config') or s.get('engine')),
                me=s.get('me')
            )
            for s in results
        ]

    def _parse_engine_from_config(self, config: Any) -> WAHAEngine:
        """
        Parse engine da config da sessão WAHA (estrutura real da API)

        Args:
            config: Objeto config da resposta da API

        Returns:
            WAHAEngine enum

        Note:
            A API real retorna engine dentro de config:
            {
              "name": "default",
              "status": "WORKING",
              "config": {"engine": "GOWS"}  // ou null
            }
        """
        # Se config for null ou não tiver engine, usar GOWS como padrão
        if not config or not isinstance(config, dict):
            return WAHAEngine.GOWS

        engine_value = config.get('engine')

        # Se não tiver engine explicita, usar GOWS
        if not engine_value:
            return WAHAEngine.GOWS

        # Usar o método existente para parsear
        return self._parse_engine(engine_value)

    def delete_session(self, session_name: str, logout: bool = True) -> Dict[str, Any]:
        """Faz logout opcional e remove a sessão."""
        logger.info(f"[WAHA] Deletando sessão '{session_name}' (logout={logout})")

        if logout:
            try:
                self.logout_session(session_name)
            except WAHAException as e:
                logger.warning("[WAHA] Logout antes de deletar falhou para '%s': %s", session_name, e)

        return self._request('DELETE', f'/api/sessions/{session_name}')

    def stop_session(self, session_name: str) -> Dict[str, Any]:
        """Para sessão (sem deletar)"""
        logger.info(f"[WAHA] Parando sessão '{session_name}'")
        return self._request('POST', f'/api/sessions/{session_name}/stop')

    def start_session(self, session_name: str) -> Dict[str, Any]:
        """Inicia sessão parada"""
        logger.info(f"[WAHA] Iniciando sessão '{session_name}'")
        return self._request('POST', f'/api/sessions/{session_name}/start')

    def restart_session(self, session_name: str) -> Dict[str, Any]:
        """Reinicia sessão"""
        logger.info(f"[WAHA] Reiniciando sessão '{session_name}'")
        return self._request('POST', f'/api/sessions/{session_name}/restart')

    def logout_session(self, session_name: str) -> Dict[str, Any]:
        """Faz logout da sessão"""
        logger.info(f"[WAHA] Fazendo logout da sessão '{session_name}'")
        return self._request('POST', f'/api/sessions/{session_name}/logout')

    # ==========================================
    # Authentication
    # ==========================================

    def get_qr_code(self, session_name: str) -> str:
        """
        Obtém QR Code para conectar

        Args:
            session_name: Nome da sessão

        Returns:
            Base64 PNG do QR Code (data:image/png;base64,...)

        Example:
            >>> qr = client.get_qr_code("default")
            >>> # qr contém: "data:image/png;base64,iVBORw0KGgo..."
        """
        import base64

        # WAHA retorna PNG binário diretamente no endpoint /api/{session}/auth/qr
        url = f"{self.base_url}/api/{session_name}/auth/qr"

        try:
            logger.debug(f"[WAHA] GET {url}")
            response = self.session.request(
                'GET',
                url,
                timeout=self.timeout,
                headers={'Accept': 'image/png'}
            )

            # Se retornou 200, é a imagem PNG
            if response.status_code == 200:
                # Converter bytes PNG para base64
                qr_base64 = base64.b64encode(response.content).decode('utf-8')
                # Retornar com prefixo data URI
                return f"data:image/png;base64,{qr_base64}"

            # Se não for 200, tratar como erro
            response.raise_for_status()
            return ""

        except requests.exceptions.RequestException as e:
            logger.error(f"[WAHA] Erro ao obter QR Code: {e}")
            raise WAHAException(f"Erro ao obter QR Code: {e}") from e

    def request_code(self, session_name: str, phone: str) -> Dict[str, Any]:
        """
        Solicita código via SMS (alternativa ao QR Code)

        Args:
            session_name: Nome da sessão
            phone: Número de telefone com código país

        Returns:
            Resposta da API

        Note:
            Nem sempre disponível, depende da conta WhatsApp
        """
        return self._request(
            'POST',
            f'/api/{session_name}/auth/request-code',
            json={'phoneNumber': phone}
        )

    def get_profile(self, session_name: str) -> Dict[str, Any]:
        """
        Obtém perfil do usuário conectado (com foto de perfil)

        Args:
            session_name: Nome da sessão

        Returns:
            Dict com id, name e picture (URL da foto)
            Exemplo: {
                "id": "550000000010@c.us",
                "name": "Usuário de Exemplo",
                "picture": "https://pps.whatsapp.net/v/..."
            }

        Example:
            >>> profile = client.get_profile("default")
            >>> print(profile['picture'])  # URL da foto de perfil
        """
        logger.info(f"[WAHA] Obtendo perfil da sessão '{session_name}'")
        return self._request('GET', f'/api/{session_name}/profile')

    # ==========================================
    # Messaging - Core Functions
    # ==========================================

    def check_number_status(
        self,
        session: str,
        phone: str
    ) -> Dict[str, Any]:
        """
        Verifica status do número e obtém chatId correto.

        IMPORTANTE para números brasileiros que podem ter formato diferente
        no WhatsApp (números antigos de 8 dígitos vs novos de 9 dígitos).

        Args:
            session: Nome da sessão
            phone: Telefone a verificar (5500000000004)

        Returns:
            Dict com:
                - numberExists: bool
                - chatId: str (chatId correto para envio)

        Example:
            >>> result = client.check_number_status("default", "5500000000011")
            >>> print(result)
            {'numberExists': True, 'chatId': '550000000012@c.us'}
        """
        # Limpar número
        clean_phone = ''.join(filter(str.isdigit, str(phone)))

        logger.info(f"[WAHA] Verificando número {clean_phone}")

        try:
            result = self._request(
                'GET',
                '/api/checkNumberStatus',
                params={'session': session, 'phone': clean_phone}
            )
            logger.info(f"[WAHA] Número {clean_phone} -> chatId: {result.get('chatId')}")
            return result
        except Exception as e:
            logger.warning(f"[WAHA] Erro ao verificar número {clean_phone}: {e}")
            # Em caso de erro, retorna o formato padrão
            return {
                'numberExists': True,
                'chatId': f"{clean_phone}@c.us"
            }

    def _format_chat_id(self, phone: str) -> str:
        """
        Formata número de telefone para formato WAHA

        Args:
            phone: Número com código país (5500000000004)

        Returns:
            Chat ID no formato WAHA (5500000000004@c.us)

        Example:
            >>> client._format_chat_id("5500000000004")
            '5500000000004@c.us'
            >>> client._format_chat_id("+55 00 00000-0000")
            '5500000000004@c.us'
        """
        # Remover caracteres não numéricos
        phone = phone.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', '')

        # Adicionar sufixo @c.us se não tiver
        if not phone.endswith('@c.us'):
            phone = f"{phone}@c.us"

        return phone

    def get_phone_by_lid(
        self,
        session: str,
        lid: str
    ) -> Optional[str]:
        """
        Obtém o número de telefone associado a um LID (Linked Device ID).

        Args:
            session: Nome da sessão
            lid: LID para resolver (ex: 123456@lid)

        Returns:
            Número de telefone (ex: 550000000013) ou None se não encontrado
        """
        try:
            # Documentação diz para escapar @ com %40 ou usar apenas o número
            # Vamos tentar usar apenas o número se contiver @
            clean_lid = lid
            if "@" in lid:
                clean_lid = lid.split("@")[0]

            logger.info(f"[WAHA] Resolvendo LID {lid} (clean: {clean_lid})")

            # 🔥 CORREÇÃO: Endpoint correto é /api/{session}/lids/{lid}
            response = self._request('GET', f'/api/{session}/lids/{clean_lid}')

            if response and 'pn' in response:
                pn = response['pn']
                # Remover sufixo @c.us se existir
                clean_pn = pn.split('@')[0] if '@' in pn else pn
                logger.info(f"[WAHA] LID {lid} resolvido para {clean_pn}")
                return clean_pn

            return None

        except Exception as e:
            # Não falhar se não encontrar, apenas retornar None
            logger.warning(f"[WAHA] Falha ao resolver LID {lid}: {e}")
            return None

    def get_correct_chat_id(
        self,
        session: str,
        phone: str
    ) -> str:
        """
        Obtém o chatId correto para um número, usando checkNumberStatus.

        Essencial para números brasileiros que podem ter formato diferente.

        Args:
            session: Nome da sessão
            phone: Telefone do destinatário

        Returns:
            chatId correto para envio

        Example:
            >>> chat_id = client.get_correct_chat_id("default", "5500000000011")
            >>> print(chat_id)  # Pode retornar '550000000012@c.us' (sem um 9)
        """
        result = self.check_number_status(session, phone)
        return result.get('chatId', self._format_chat_id(phone))

    def resolve_chat_id(self, session: str, phone: str) -> str:
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if clean_phone.startswith('55'):
            return self.get_correct_chat_id(session, clean_phone)
        return self._format_chat_id(phone)

    def start_typing(self, session: str, phone: str) -> Dict[str, Any]:
        chat_id = self.resolve_chat_id(session, phone)
        logger.info(f"[WAHA] Iniciando digitacao para {chat_id}")
        return self._request('POST', '/api/startTyping', json={
            'session': session,
            'chatId': chat_id
        })

    def stop_typing(self, session: str, phone: str) -> Dict[str, Any]:
        chat_id = self.resolve_chat_id(session, phone)
        logger.info(f"[WAHA] Parando digitacao para {chat_id}")
        return self._request('POST', '/api/stopTyping', json={
            'session': session,
            'chatId': chat_id
        })

    def send_text(
        self,
        session: str,
        phone: str,
        text: str,
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Envia mensagem de texto

        Args:
            session: Nome da sessão
            phone: Telefone do destinatário (5500000000004)
            text: Texto da mensagem

        Returns:
            Resposta com ID da mensagem enviada

        Example:
            >>> result = client.send_text("default", "5500000000004", "Olá!")
            >>> print(result['id'])  # ID da mensagem
        """
        chat_id = self.resolve_chat_id(session, phone)

        logger.info(f"[WAHA] Enviando texto para {chat_id}")

        payload = {
            'session': session,
            'chatId': chat_id,
            'text': text,
            'linkPreview': True,
            'linkPreviewHighQuality': True,
        }
        if reply_to:
            payload['reply_to'] = reply_to

        return self._request('POST', '/api/sendText', json=payload)

    def send_contact_vcard(
        self,
        session: str,
        phone: str,
        contacts: List[Dict[str, Any]],
        reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Envia um ou mais cards de contato/vCard para o chat informado.
        """
        if not contacts:
            raise WAHAException("contacts é obrigatório para enviar vCard")

        chat_id = self.resolve_chat_id(session, phone)
        payload = {
            'session': session,
            'chatId': chat_id,
            'contacts': contacts,
        }
        if reply_to:
            payload['reply_to'] = reply_to

        logger.info("[WAHA] Enviando card de contato para %s (%s contato(s))", chat_id, len(contacts))
        return self._request('POST', '/api/sendContactVcard', json=payload)

    def send_reaction(
        self,
        session: str,
        message_id: str,
        reaction: str = "",
    ) -> Dict[str, Any]:
        """
        Envia ou remove uma reação de mensagem via WAHA.
        Uma string vazia em reaction remove a reação existente.
        """
        if not message_id:
            raise WAHAException("message_id é obrigatório para enviar reação")

        logger.info("[WAHA] Atualizando reação para message_id=%s", message_id)
        return self._request('PUT', '/api/reaction', json={
            'session': session,
            'messageId': message_id,
            'reaction': reaction or "",
        })

    def send_image(
        self,
        session: str,
        phone: str,
        image_url: str,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Envia imagem via URL

        Args:
            session: Nome da sessão
            phone: Telefone do destinatário
            image_url: URL da imagem (acessível pelo WAHA)
            caption: Legenda opcional

        Returns:
            Resposta com ID da mensagem

        Example:
            >>> client.send_image(
            ...     "default",
            ...     "5500000000004",
            ...     "http://servidor/imagem.jpg",
            ...     "Minha imagem!"
            ... )
        """
        # Para números brasileiros (começam com 55), usar checkNumberStatus
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if clean_phone.startswith('55'):
            chat_id = self.get_correct_chat_id(session, clean_phone)
        else:
            chat_id = self._format_chat_id(phone)

        # ⚠️ CORREÇÃO: RemoteFile schema exige "mimetype" obrigatório
        # Detectar mimetype baseado na extensão da URL
        mimetype = 'image/jpeg'  # padrão
        if image_url.lower().endswith(('.png', '.PNG')):
            mimetype = 'image/png'
        elif image_url.lower().endswith(('.gif', '.GIF')):
            mimetype = 'image/gif'
        elif image_url.lower().endswith(('.webp', '.WEBP')):
            mimetype = 'image/webp'

        payload = {
            'session': session,
            'chatId': chat_id,
            'file': {
                'url': image_url,
                'mimetype': mimetype  # ⚠️ OBRIGATÓRIO no RemoteFile schema
            }
        }

        if caption:
            payload['caption'] = caption

        logger.info(f"[WAHA] Enviando imagem para {chat_id}: {image_url}")
        logger.debug(f"[WAHA] Payload send_image: {payload}")

        return self._request('POST', '/api/sendImage', json=payload)

    def send_video(
        self,
        session: str,
        phone: str,
        video_url: str,
        caption: Optional[str] = None,
        timeout: int = 120
    ) -> Dict[str, Any]:
        """
        Envia vídeo via URL (funciona sem timeout! ✅)

        Args:
            session: Nome da sessão
            phone: Telefone do destinatário
            video_url: URL do vídeo (acessível pelo WAHA)
            caption: Legenda opcional
            timeout: Timeout em segundos (padrão: 120s = 2 minutos)

        Returns:
            Resposta com ID da mensagem enviada

        Note:
            WAHA (GOWS) envia vídeos sem timeout, ao contrário do WPPConnect.
            O WAHA baixa o vídeo da URL e depois envia para o WhatsApp.

        Example:
            >>> client.send_video(
            ...     "default",
            ...     "5500000000004",
            ...     "http://servidor/video.mp4",
            ...     "Seu vídeo!"
            ... )
        """
        # Para números brasileiros (começam com 55), usar checkNumberStatus
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if clean_phone.startswith('55'):
            chat_id = self.get_correct_chat_id(session, clean_phone)
        else:
            chat_id = self._format_chat_id(phone)

        # ⚠️ CORREÇÃO: VideoRemoteFile schema exige campos obrigatórios
        # Detectar mimetype e filename baseado na extensão da URL
        mimetype = 'video/mp4'  # padrão
        filename = 'video.mp4'  # padrão

        if video_url.lower().endswith(('.mov', '.MOV')):
            mimetype = 'video/quicktime'
            filename = 'video.mov'
        elif video_url.lower().endswith(('.avi', '.AVI')):
            mimetype = 'video/x-msvideo'
            filename = 'video.avi'
        elif video_url.lower().endswith(('.webm', '.WEBM')):
            mimetype = 'video/webm'
            filename = 'video.webm'

        payload = {
            'session': session,
            'chatId': chat_id,
            'file': {
                'url': video_url,
                'mimetype': mimetype,      # ⚠️ OBRIGATÓRIO no VideoRemoteFile schema
                'filename': filename      # ⚠️ OBRIGATÓRIO no VideoRemoteFile schema
            },
            'convert': True  # ⚠️ OBRIGATÓRIO no MessageVideoRequest schema
        }

        if caption:
            payload['caption'] = caption

        logger.info(f"[WAHA GOWS] Enviando vídeo para {chat_id}: {video_url}")
        logger.debug(f"[WAHA] Payload send_video: {payload}")

        return self._request(
            'POST',
            '/api/sendVideo',
            json=payload,
            timeout=timeout
        )

    def send_voice(
        self,
        session: str,
        phone: str,
        audio_url: str
    ) -> Dict[str, Any]:
        """
        Envia áudio como nota de voz

        Args:
            session: Nome da sessão
            phone: Telefone do destinatário
            audio_url: URL do áudio (formato .ogg ou .mp3)

        Returns:
            Resposta com ID da mensagem

        Example:
            >>> client.send_voice(
            ...     "default",
            ...     "5500000000004",
            ...     "http://servidor/audio.ogg"
            ... )
        """
        # Para números brasileiros (começam com 55), usar checkNumberStatus
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if clean_phone.startswith('55'):
            chat_id = self.get_correct_chat_id(session, clean_phone)
        else:
            chat_id = self._format_chat_id(phone)

        # Detectar mimetype baseado na extensão da URL
        mimetype = 'audio/mpeg'  # padrão
        if audio_url.lower().endswith(('.ogg', '.OGG')):
            mimetype = 'audio/ogg'
        elif audio_url.lower().endswith(('.mp3', '.MP3')):
            mimetype = 'audio/mpeg'
        elif audio_url.lower().endswith(('.webm', '.WEBM')):
            mimetype = 'audio/webm'

        logger.info(f"[WAHA] Enviando áudio para {chat_id} (formato: {mimetype})")

        return self._request('POST', '/api/sendVoice', json={
            'session': session,
            'chatId': chat_id,
            'file': {
                'url': audio_url,
                'mimetype': mimetype
            },
            'convert': True
        })

    def send_voice_base64(
        self,
        session: str,
        phone: str,
        audio_data: str,
        filename: str = "voice-message.mp3",
        mimetype: str = "audio/mpeg"
    ) -> Dict[str, Any]:
        """
        Envia áudio como nota de voz usando base64 com conversão WAHA

        Este método usa VoiceBinaryFile com convert=true para WAHA fazer
        conversão automática para o formato otimizado de WhatsApp.

        Args:
            session: Nome da sessão WAHA
            phone: Telefone do destinatário (ex: "5500000000004")
            audio_data: Conteúdo do áudio em base64 sem prefixo data:
            filename: Nome do arquivo (default: "voice-message.mp3")
            mimetype: MIME type (default: "audio/mpeg")

        Returns:
            Dict[str, Any]: Resposta da API WAHA com ID da mensagem

        Example:
            >>> client.send_voice_base64(
            ...     "default",
            ...     "5500000000004",
            ...     "SUQzBAAAAA...",
            ...     "voice-message.mp3",
            ...     "audio/mpeg"
            ... )
        """
        chat_id = self.resolve_chat_id(session, phone)

        logger.info(f"[WAHA] Enviando áudio base64 para {chat_id} (formato: {mimetype})")
        return self._request('POST', '/api/sendVoice', json={
            'session': session,
            'chatId': chat_id,
            'file': {
                'mimetype': mimetype,
                'filename': filename,
                'data': audio_data
            },
            'convert': True
        })

    def send_file(
        self,
        session: str,
        phone: str,
        file_url: str,
        filename: Optional[str] = None,
        caption: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Envia arquivo/documento

        Args:
            session: Nome da sessão
            phone: Telefone do destinatário
            file_url: URL do arquivo
            filename: Nome do arquivo (opcional)
            caption: Legenda opcional

        Returns:
            Resposta com ID da mensagem
        """
        chat_id = self._format_chat_id(phone)

        payload = {
            'session': session,
            'chatId': chat_id,
            'file': {'url': file_url}
        }

        if filename:
            payload['file']['filename'] = filename
        if caption:
            payload['caption'] = caption

        logger.info(f"[WAHA] Enviando arquivo para {chat_id}")

        return self._request('POST', '/api/sendFile', json=payload)

    def send_poll(
        self,
        session: str,
        phone: str,
        poll_name: str,
        poll_options: List[str],
        multiple_answers: bool = False
    ) -> Dict[str, Any]:
        """
        Envia enquete/poll via WhatsApp

        Args:
            session: Nome da sessão
            phone: Telefone do destinatário
            poll_name: Título da enquete
            poll_options: Lista de opções da enquete
            multiple_answers: Se permite múltiplas respostas

        Returns:
            Resposta com ID da mensagem da enquete

        Example:
            >>> client.send_poll(
            ...     "default",
            ...     "5500000000004",
            ...     "Como você avalia nosso atendimento?",
            ...     ["1 ⭐", "2 ⭐", "3 ⭐", "4 ⭐", "5 ⭐"],
            ...     multiple_answers=False
            ... )
        """
        chat_id = self._format_chat_id(phone)

        payload = {
            'session': session,
            'chatId': chat_id,
            'poll': {
                'name': poll_name,
                'options': poll_options,
                'multipleAnswers': multiple_answers
            }
        }

        logger.info(f"[WAHA] Enviando enquete para {chat_id}: {poll_name}")
        logger.debug(f"[WAHA] Opções: {poll_options}")

        return self._request('POST', '/api/sendPoll', json=payload)

    def send_nps_poll(
        self,
        session: str,
        phone: str,
        question: str = "De 0 a 10, como você avalia nosso atendimento?",
        scale_type: str = "stars",  # "stars" ou "numbers"
        delay_message: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Envia enquete NPS (Net Promoter Score) via WhatsApp

        Args:
            session: Nome da sessão
            phone: Telefone do destinatário
            question: Pergunta NPS
            scale_type: Tipo de escala ("stars" para 1-5 estrelas, "numbers" para 0-10)
            delay_message: Tempo de digitação antes de enviar (opcional)

        Returns:
            Resposta com ID da mensagem NPS

        Example:
            >>> client.send_nps_poll(
            ...     "default",
            ...     "5500000000004",
            ...     scale_type="stars"
            ... )
        """

        if scale_type == "stars":
            # Escala de 1 a 5 estrelas (compatível com Z-API)
            poll_options = [f"{i} ⭐" for i in range(1, 6)]
        elif scale_type == "numbers":
            # Escala de 0 a 10 (padrão NPS tradicional)
            poll_options = [str(i) for i in range(0, 11)]
        else:
            raise ValueError("scale_type deve ser 'stars' ou 'numbers'")

        if delay_message:
            import time
            logger.info(f"[WAHA] Aguardando {delay_message}s antes de enviar NPS")
            time.sleep(delay_message)

        return self.send_poll(
            session=session,
            phone=phone,
            poll_name=question,
            poll_options=poll_options,
            multiple_answers=False
        )


# ==========================================
# Factory Function
# ==========================================

def get_client(
    base_url: str,
    api_key: str,
    timeout: int = 60
) -> WAHAClient:
    """
    Cria cliente WAHA (factory function)

    Args:
        base_url: URL do servidor WAHA (ex: http://localhost:3000)
        api_key: Chave de API (X-Api-Key)
        timeout: Timeout padrão em segundos

    Returns:
        Instância configurada de WAHAClient

    Example:
        >>> from backend.integrations.waha_sdk import get_client
        >>> client = get_client("http://localhost:3000", "sua_api_key")
        >>> client.send_text("default", "5500000000004", "Olá!")
    """
    engine_name = (
        os.getenv("WAHA_DEFAULT_ENGINE")
        or os.getenv("WHATSAPP_DEFAULT_ENGINE")
        or WAHAEngine.GOWS.value
    ).upper()

    try:
        default_engine = WAHAEngine(engine_name)
    except ValueError:
        logger.warning("[WAHA] Engine padrão inválida '%s', usando GOWS", engine_name)
        default_engine = WAHAEngine.GOWS

    return WAHAClient(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        default_engine=default_engine
    )



def get_default_proxy_config() -> Optional[Dict[str, str]]:
    """
    Obtém configuração de proxy padrão do ambiente com seleção inteligente

    Estratégia de seleção de proxy:
    1. WAHA_PROXY_SERVER: usa proxy configurado manualmente
    2. Testa proxy otimizado (9051) - se disponível e com IP BR
    3. Fallback para proxy atual (9050)
    4. Retorna None se nenhum funcionar

    Returns:
        Dict com configuração de proxy ou None se não configurado

    Example:
        >>> proxy = get_default_proxy_config()
        >>> print(proxy)
        {"server": "host.docker.internal:9051", "optimized": true}
    """
    # 1. Proxy configurado manualmente tem prioridade
    proxy_server = os.getenv("WAHA_PROXY_SERVER")
    if proxy_server:
        logger.info(f"[WAHA Proxy] Usando proxy configurado: {proxy_server}")
        proxy_config = {"server": proxy_server}

        # Adicionar credenciais se disponíveis
        username = os.getenv("WAHA_PROXY_USERNAME")
        password = os.getenv("WAHA_PROXY_PASSWORD")
        if username and password:
            proxy_config["username"] = username
            proxy_config["password"] = password

        return proxy_config

    # 2. Testar seleção automática inteligente
    logger.info("[WAHA Proxy] Testando seleção automática de proxy...")
    best_proxy = _get_best_available_proxy()

    if best_proxy:
        logger.info(f"[WAHA Proxy] Proxy selecionado automaticamente: {best_proxy['server']}")
        return best_proxy

    # 3. Nenhum proxy disponível
    logger.warning("[WAHA Proxy] Nenhum proxy disponível")
    return None


def _get_best_available_proxy() -> Optional[Dict[str, str]]:
    """
    Testa proxies disponíveis e retorna o melhor

    Returns:
        Dict com melhor proxy ou None
    """
    proxies_to_test = [
        {"server": "host.docker.internal:9051", "name": "Tor Otimizado", "optimized": True},
        {"server": "host.docker.internal:9050", "name": "Tor Atual", "optimized": False}
    ]

    for proxy in proxies_to_test:
        if _test_proxy_connection(proxy["server"]):
            logger.info(f"[WAHA Proxy] ✅ {proxy['name']} funcionando: {proxy['server']}")
            return proxy
        else:
            logger.warning(f"[WAHA Proxy] ❌ {proxy['name']} falhou: {proxy['server']}")

    return None


def _test_proxy_connection(proxy_server: str, timeout: int = 10) -> bool:
    """
    Testa se um proxy está funcional

    Teste simples: se o container Tor está respondendo na porta
    Como WAHA está funcionando com proxy atual, assumimos que
    se o container estiver up, o proxy funciona.

    Args:
        proxy_server: Formato "host.docker.internal:porta"
        timeout: Timeout em segundos

    Returns:
        True se proxy funciona, False caso contrário
    """
    try:
        import socket
        from urllib.parse import urlparse

        # Extrair porta do proxy_server
        if ':' in proxy_server:
            _, port_str = proxy_server.split(':')
            port = int(port_str)
        else:
            return False

        # Teste simples: tentar conectar ao proxy
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        # host.docker.internal => localhost (estamos no mesmo host)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()

        # Se conectar, proxy está funcionando
        is_working = result == 0

        if is_working:
            logger.debug(f"[WAHA Proxy] ✅ Proxy {proxy_server} está respondendo")
        else:
            logger.debug(f"[WAHA Proxy] ❌ Proxy {proxy_server} não responde (porta {port})")

        return is_working

    except Exception as e:
        logger.debug(f"[WAHA Proxy] Teste {proxy_server} falhou: {e}")
        return False


def create_session_with_auto_proxy(
    client: WAHAClient,
    session_name: str,
    engine: Optional[WAHAEngine] = None,
    force_proxy: bool = False
) -> WAHASession:
    """
    Cria sessão WAHA com proxy automático (baseado em environment)

    Função helper que usa configuração de proxy do ambiente se disponível.
    Mantém compatibilidade total com código existente.

    Args:
        client: Instância do WAHAClient
        session_name: Nome da sessão
        engine: Engine (padrão: GOWS)
        force_proxy: Força uso de proxy mesmo que não seja default

    Returns:
        WAHASession criada

    Example:
        >>> client = get_client("http://localhost:3000", "api_key")
        >>> session = create_session_with_auto_proxy(client, "cobbusiness")
        # Se WAHA_PROXY_SERVER estiver configurado, usará proxy
    """
    # Obter configuração de proxy do ambiente
    proxy_config = get_default_proxy_config()

    # Se não houver proxy configurado e não for forçado, criar sem proxy
    if not proxy_config and not force_proxy:
        logger.info(f"[WAHA] Criando sessão '{session_name}' SEM proxy (padrão)")
        return client.create_session(session_name, engine)

    # Forçar proxy específico para testes
    if force_proxy and not proxy_config:
        proxy_config = {"server": "host.docker.internal:9050"}
        logger.info(f"[WAHA] Criando sessão '{session_name}' COM proxy forçado (Tor)")

    logger.info(f"[WAHA] Criando sessão '{session_name}' COM proxy automático: {proxy_config.get('server')}")
    return client.create_session(session_name, engine, proxy_config)
