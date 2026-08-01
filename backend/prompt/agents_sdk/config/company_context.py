# Company Context Definition
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from ...scheduling.scheduling_service import SchedulingService
from ..utils.state_manager import AgentsSDKStateManager, ConversationState

@dataclass
class CompanyContext:
    """
    Contexto local para o agent run.
    Contém todas as dependências e dados necessários para execução.
    """
    # Dados da sessão
    db: Session
    company_id: int
    contact_phone: str

    # Configurações da empresa
    company_config: Dict[str, Any]

    # Serviços
    scheduling_service: Optional[SchedulingService] = None

    # Contexto do cliente
    customer_context: Optional[Dict[str, Any]] = None

    # Slots disponíveis
    available_slots: Optional[List[str]] = None

    # Histórico de chat
    chat_history: Optional[List[Dict[str, str]]] = None

    # Metadados da conversa
    msg_category: str = ""
    funnel_stage: str = ""
    funnel_status: str = ""

    # API key para webhooks e integrações
    api_key: Optional[str] = None

    # State management
    conversation_state: ConversationState = field(default_factory=ConversationState)
    _state_manager: Optional[AgentsSDKStateManager] = field(default=None, init=False)

    def get_company_name(self) -> str:
        """Retorna o nome da empresa"""
        return self.company_config.get("company_info", {}).get("company_name", "Nossa empresa")

    def get_assistant_name(self) -> str:
        """Retorna o nome do assistente"""
        return self.company_config.get("assistant_identity", {}).get("assistant_name", "Assistente")

    async def get_state_manager(self) -> AgentsSDKStateManager:
        """
        Retorna o gerenciador de estado, criando se necessário.
        """
        if self._state_manager is None:
            self._state_manager = AgentsSDKStateManager(
                db=self.db,
                company_id=self.company_id,
                contact_phone=self.contact_phone
            )
            await self._state_manager.load_state()
            # Sincroniza o estado local com o carregado
            self.conversation_state = self._state_manager.state
        return self._state_manager

    async def sync_state(self) -> None:
        """
        Sincroniza o estado local com o gerenciador de estado.
        """
        if self._state_manager:
            self.conversation_state = self._state_manager.state

    def get_current_step(self) -> int:
        """Retorna o step atual da conversa."""
        return self.conversation_state.current_step

    def get_step_description(self) -> str:
        """Retorna descrição do step atual."""
        if self._state_manager:
            return self._state_manager.get_step_description()
        return f"Step {self.conversation_state.current_step}"