"""
Agentes Inteligentes para Busca e Validação de Slots
===================================================

Implementa agentes que podem tomar decisões e usar ferramentas.
"""

from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
import logging
import json

from langchain.agents import Tool, AgentExecutor, create_openai_functions_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain.tools import StructuredTool
from pydantic import BaseModel, Field

from .models import SlotInfo, SchedulingIntent
from .utils import parse_slot_datetime

logger = logging.getLogger(__name__)


class SlotAvailabilityInput(BaseModel):
    """Input para ferramenta de verificação de disponibilidade"""
    slot_datetime: str = Field(description="Data/hora do slot no formato DD/MM/YYYY HH:MM")
    company_id: int = Field(description="ID da empresa")


class AlternativeSlotsInput(BaseModel):
    """Input para ferramenta de busca de alternativas"""
    original_slot: str = Field(description="Slot original indisponível")
    search_criteria: Dict[str, Any] = Field(
        description="Critérios para buscar alternativas (período, dia_semana, etc)"
    )
    max_alternatives: int = Field(default=5, description="Número máximo de alternativas")


class SchedulingTools:
    """Conjunto de ferramentas para o agente de agendamento"""

    def __init__(self, db_session, scheduling_service):
        self.db = db_session
        self.scheduling_service = scheduling_service

    def check_slot_real_availability(self, slot_datetime: str, company_id: int) -> Dict[str, Any]:
        """
        Verifica disponibilidade real-time de um slot específico.

        Returns:
            Dict com status de disponibilidade e detalhes
        """
        try:
            # Parse da data
            dt = parse_slot_datetime(slot_datetime)
            if not dt:
                return {
                    'available': False,
                    'reason': 'Formato de data inválido',
                    'checked_at': datetime.now().isoformat()
                }

            # Verifica no banco se o slot está livre
            from sqlalchemy import text

            # Verifica agendamentos existentes neste horário
            existing = self.db.execute(text("""
                SELECT COUNT(*) as count
                FROM agendamentos
                WHERE company_id = :company_id
                AND data = :date
                AND horario = :time
                AND status IN ('SCHEDULED', 'CONFIRMED')
            """), {
                'company_id': company_id,
                'date': dt.date(),
                'time': dt.time()
            }).fetchone()

            if existing and existing.count > 0:
                return {
                    'available': False,
                    'reason': 'Horário já ocupado',
                    'checked_at': datetime.now().isoformat()
                }

            # Verifica se está dentro do horário de funcionamento
            weekday = dt.weekday()
            hour = dt.hour

            # TODO: Buscar horário de funcionamento real da empresa
            business_hours = {
                0: (8, 18),  # Segunda
                1: (8, 18),  # Terça
                2: (8, 18),  # Quarta
                3: (8, 18),  # Quinta
                4: (8, 18),  # Sexta
                5: (8, 12),  # Sábado
                6: None      # Domingo fechado
            }

            if weekday not in business_hours or business_hours[weekday] is None:
                return {
                    'available': False,
                    'reason': 'Empresa fechada neste dia',
                    'checked_at': datetime.now().isoformat()
                }

            start_hour, end_hour = business_hours[weekday]
            if hour < start_hour or hour >= end_hour:
                return {
                    'available': False,
                    'reason': f'Fora do horário de funcionamento ({start_hour}h-{end_hour}h)',
                    'checked_at': datetime.now().isoformat()
                }

            # Se passou todas as verificações
            return {
                'available': True,
                'slot': slot_datetime,
                'checked_at': datetime.now().isoformat(),
                'details': {
                    'weekday': ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'][weekday],
                    'period': 'manhã' if hour < 12 else 'tarde'
                }
            }

        except Exception as e:
            logger.error(f"Erro ao verificar disponibilidade: {e}")
            return {
                'available': False,
                'reason': f'Erro ao verificar: {str(e)}',
                'checked_at': datetime.now().isoformat()
            }

    def find_alternative_slots(
        self,
        original_slot: str,
        search_criteria: Dict[str, Any],
        max_alternatives: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Busca slots alternativos quando o desejado não está disponível.

        Returns:
            Lista de alternativas ordenadas por relevância
        """
        try:
            original_dt = parse_slot_datetime(original_slot)
            if not original_dt:
                return []

            # Obtém todos os slots disponíveis
            all_slots = self.scheduling_service.get_next_available_slots()

            alternatives = []

            for slot_str in all_slots:
                slot_dt = parse_slot_datetime(slot_str)
                if not slot_dt:
                    continue

                # Calcula score de relevância
                score = 0
                reasons = []

                # Mesmo dia da semana
                if slot_dt.weekday() == original_dt.weekday():
                    score += 3
                    reasons.append("mesmo dia da semana")

                # Mesmo período do dia
                original_period = 'manhã' if original_dt.hour < 12 else 'tarde'
                slot_period = 'manhã' if slot_dt.hour < 12 else 'tarde'
                if slot_period == original_period:
                    score += 2
                    reasons.append("mesmo período")

                # Proximidade temporal (penaliza por diferença de dias)
                days_diff = abs((slot_dt.date() - original_dt.date()).days)
                if days_diff <= 3:
                    score += (4 - days_diff)
                    reasons.append(f"{days_diff} dias de diferença")

                # Aplica critérios de busca adicionais
                if search_criteria.get('prefer_morning') and slot_dt.hour < 12:
                    score += 1
                    reasons.append("manhã preferida")

                if search_criteria.get('prefer_afternoon') and slot_dt.hour >= 12:
                    score += 1
                    reasons.append("tarde preferida")

                # Adiciona à lista se tem score relevante
                if score > 0:
                    alternatives.append({
                        'slot': slot_str,
                        'datetime': slot_dt.isoformat(),
                        'score': score,
                        'reasons': reasons,
                        'days_difference': days_diff,
                        'weekday': ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'][slot_dt.weekday()],
                        'period': slot_period
                    })

            # Ordena por score e pega os melhores
            alternatives.sort(key=lambda x: (-x['score'], x['days_difference']))

            return alternatives[:max_alternatives]

        except Exception as e:
            logger.error(f"Erro ao buscar alternativas: {e}")
            return []

    def get_tools(self) -> List[Tool]:
        """Retorna lista de ferramentas para o agente"""
        return [
            StructuredTool(
                name="check_slot_availability",
                description="Verifica em tempo real se um horário específico está disponível para agendamento",
                func=lambda slot_datetime, company_id: self.check_slot_real_availability(slot_datetime, company_id),
                args_schema=SlotAvailabilityInput
            ),
            StructuredTool(
                name="find_alternative_slots",
                description="Busca horários alternativos quando o desejado não está disponível",
                func=lambda original_slot, search_criteria, max_alternatives=5: self.find_alternative_slots(
                    original_slot, search_criteria, max_alternatives
                ),
                args_schema=AlternativeSlotsInput
            )
        ]


def create_scheduling_agent(
    db_session,
    scheduling_service,
    llm: Optional[ChatOpenAI] = None,
    verbose: bool = True
) -> AgentExecutor:
    """
    Cria um agente inteligente para agendamento.

    Args:
        db_session: Sessão do banco de dados
        scheduling_service: Serviço de agendamento
        llm: Modelo LLM a usar
        verbose: Se deve logar ações do agente

    Returns:
        AgentExecutor configurado
    """

    if not llm:
        llm = ChatOpenAI(
            model="gpt-4-turbo-preview",
            temperature=0.1
        )

    # Ferramentas disponíveis
    tools_provider = SchedulingTools(db_session, scheduling_service)
    tools = tools_provider.get_tools()

    # Prompt do agente
    system_message = """Você é um agente especializado em agendamento de consultas de serviços.

Suas responsabilidades:
1. Verificar disponibilidade real de horários antes de sugerir
2. Buscar alternativas quando o horário desejado não está disponível
3. Explicar claramente as opções ao usuário
4. Priorizar horários que melhor atendem às preferências do usuário

Sempre verifique a disponibilidade real antes de confirmar um horário.
Se um horário não estiver disponível, busque alternativas similares.

Contexto atual:
- Data/hora: {current_datetime}
- Intenção do usuário: {user_intent}
- Slots pré-filtrados: {filtered_slots}"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_message),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad")
    ])

    # Cria o agente
    agent = create_openai_functions_agent(
        llm=llm,
        tools=tools,
        prompt=prompt
    )

    # Cria o executor
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=verbose,
        max_iterations=3,
        early_stopping_method="generate",
        handle_parsing_errors=True,
        return_intermediate_steps=True
    )

    return agent_executor


class SmartSlotSelector:
    """
    Seletor inteligente de slots usando embeddings e similaridade semântica.
    """

    def __init__(self, embeddings_model=None):
        if not embeddings_model:
            from langchain_openai import OpenAIEmbeddings
            self.embeddings = OpenAIEmbeddings()
        else:
            self.embeddings = embeddings_model

    def select_best_slots(
        self,
        user_preference: str,
        available_slots: List[SlotInfo],
        max_suggestions: int = 2
    ) -> List[SlotInfo]:
        """
        Seleciona os melhores slots usando similaridade semântica.

        Args:
            user_preference: Descrição em linguagem natural da preferência
            available_slots: Lista de slots disponíveis
            max_suggestions: Número máximo de sugestões

        Returns:
            Lista dos melhores slots ordenados por relevância
        """
        if not available_slots:
            return []

        # Cria descrições textuais dos slots
        slot_descriptions = []
        for slot in available_slots:
            desc = self._create_slot_description(slot)
            slot_descriptions.append(desc)

        # Gera embeddings
        try:
            preference_embedding = self.embeddings.embed_query(user_preference)
            slot_embeddings = self.embeddings.embed_documents(slot_descriptions)

            # Calcula similaridade
            from numpy import dot
            from numpy.linalg import norm

            similarities = []
            for i, slot_emb in enumerate(slot_embeddings):
                # Cosine similarity
                similarity = dot(preference_embedding, slot_emb) / (norm(preference_embedding) * norm(slot_emb))
                similarities.append((similarity, available_slots[i]))

            # Ordena por similaridade
            similarities.sort(key=lambda x: x[0], reverse=True)

            # Retorna os melhores
            return [slot for _, slot in similarities[:max_suggestions]]

        except Exception as e:
            logger.error(f"Erro no embedding: {e}")
            # Fallback para seleção simples
            return available_slots[:max_suggestions]

    def _create_slot_description(self, slot: SlotInfo) -> str:
        """Cria descrição textual rica de um slot"""
        parts = []

        # Dia e data
        parts.append(f"{slot.day_name_pt} dia {slot.datetime_obj.day}")

        # Contexto temporal
        if slot.is_today:
            parts.append("hoje")
        elif slot.is_tomorrow:
            parts.append("amanhã")
        elif slot.days_from_today <= 7:
            parts.append(f"esta semana")
        else:
            parts.append(f"daqui a {slot.days_from_today} dias")

        # Período e horário
        parts.append(f"período da {slot.period}")
        parts.append(f"às {slot.datetime_obj.strftime('%H:%M')}")

        # Características especiais
        if slot.datetime_obj.hour < 10:
            parts.append("horário bem cedo")
        elif slot.datetime_obj.hour >= 17:
            parts.append("final do dia")

        return " ".join(parts)