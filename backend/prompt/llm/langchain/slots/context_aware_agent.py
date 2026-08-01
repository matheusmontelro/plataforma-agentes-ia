"""
Context-aware slots query agent using LangChain.
This agent maintains temporal context from conversation history.
"""

import os
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from langchain.tools import BaseTool, StructuredTool
from langchain.agents import create_openai_functions_agent, AgentExecutor
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field
import json

logger = logging.getLogger(__name__)

# Timezone configuration
try:
    from zoneinfo import ZoneInfo
    SP_TZ = ZoneInfo("America/Sao_Paulo")
except ImportError:
    import pytz
    SP_TZ = pytz.timezone("America/Sao_Paulo")


# Pydantic models for structured output
class FoundSlot(BaseModel):
    """Representa um slot encontrado"""
    date: str = Field(description="Data no formato DD/MM/YYYY")
    time: str = Field(description="Horário no formato HH:MM")
    weekday: str = Field(description="Dia da semana em português")
    full_slot: str = Field(description="Slot completo no formato DD/MM/YYYY HH:MM")
    formatted: str = Field(description="Slot formatado para exibição")


class SlotsSearchResult(BaseModel):
    """Resultado da busca de slots"""
    found_slots: List[FoundSlot] = Field(default_factory=list, description="Lista de slots encontrados")
    message: str = Field(description="Mensagem para o usuário")
    has_exact_match: bool = Field(description="Se encontrou exatamente o que foi pedido")


class SlotSearchParams(BaseModel):
    """Parameters for slot search based on user preference"""
    target_date: Optional[str] = Field(None, description="Target date in DD/MM/YYYY format")
    target_time: Optional[str] = Field(None, description="Target time in HH:MM format")
    period: Optional[str] = Field(None, description="Period of day: morning, afternoon, evening")
    weekday: Optional[str] = Field(None, description="Weekday name in Portuguese")
    relative_day: Optional[str] = Field(None, description="Relative day: hoje, amanhã, etc")


class TemporalContext(BaseModel):
    """Temporal context extracted from conversation"""
    offered_date: Optional[str] = Field(None, description="Date offered by assistant in last message")
    offered_times: List[str] = Field(default_factory=list, description="Times offered by assistant")
    user_choice: Optional[str] = Field(None, description="User's chosen time")


class ContextAwareSlotsTool(BaseTool):
    """Tool that searches for slots with temporal context awareness"""

    name: str = "search_slots_with_context"
    description: str = """Search for available appointment slots based on user preference.
    When user responds with just a time (e.g., "17:00") after being offered specific slots,
    search for that time on the same date that was offered."""

    db: Any = None
    company_id: int = None
    conversation_history: List[Dict[str, str]] = []

    def _extract_temporal_context(self) -> TemporalContext:
        """Extract temporal context from recent conversation"""
        context = TemporalContext()

        # Look at last 3 messages for context
        recent_msgs = self.conversation_history[-3:] if self.conversation_history else []

        for msg in reversed(recent_msgs):
            if msg.get('role') == 'assistant':
                content = msg.get('content', '')

                # Extract dates offered (format: DD/MM/YYYY)
                date_pattern = r'(\d{2}/\d{2}/\d{4})'
                dates = re.findall(date_pattern, content)

                # Extract times offered (format: HH:MM)
                time_pattern = r'(\d{1,2}:\d{2})'
                times = re.findall(time_pattern, content)

                # Look for "hoje", "amanhã", etc
                if 'hoje' in content.lower():
                    context.offered_date = datetime.now(SP_TZ).strftime('%d/%m/%Y')
                elif dates:
                    context.offered_date = dates[0]  # Use first date found

                if times:
                    context.offered_times = times

                # If we found context, stop looking
                if context.offered_date or context.offered_times:
                    break

        return context

    def _parse_user_input(self, query: str) -> SlotSearchParams:
        """Parse user input to extract slot preferences"""
        params = SlotSearchParams()
        query_lower = query.lower()

        # Check if it's just a time
        time_match = re.match(r'^(\d{1,2}):?(\d{2})?\s*$', query.strip())
        if time_match:
            hour = time_match.group(1)
            minute = time_match.group(2) or '00'
            params.target_time = f"{hour}:{minute}"
            return params

        # Extract specific date
        date_pattern = r'(\d{2}/\d{2}/\d{4})'
        date_match = re.search(date_pattern, query)
        if date_match:
            params.target_date = date_match.group(1)

        # Extract time
        time_pattern = r'(\d{1,2}):(\d{2})'
        time_match = re.search(time_pattern, query)
        if time_match:
            params.target_time = f"{time_match.group(1)}:{time_match.group(2)}"

        # Detect relative days
        if 'hoje' in query_lower:
            params.relative_day = 'hoje'
            params.target_date = datetime.now(SP_TZ).strftime('%d/%m/%Y')
        elif 'amanhã' in query_lower:
            params.relative_day = 'amanhã'
            params.target_date = (datetime.now(SP_TZ) + timedelta(days=1)).strftime('%d/%m/%Y')
        elif 'depois de amanhã' in query_lower:
            params.relative_day = 'depois de amanhã'
            params.target_date = (datetime.now(SP_TZ) + timedelta(days=2)).strftime('%d/%m/%Y')

        # Detect periods
        if any(word in query_lower for word in ['manhã', 'matutino', 'cedo']):
            params.period = 'morning'
        elif any(word in query_lower for word in ['tarde', 'vespertino']):
            params.period = 'afternoon'
        elif any(word in query_lower for word in ['noite', 'noturno', 'fim do dia']):
            params.period = 'evening'

        # Detect weekdays
        weekdays = {
            'segunda': 0, 'terça': 1, 'quarta': 2,
            'quinta': 3, 'sexta': 4, 'sábado': 5, 'domingo': 6
        }

        for day_name, day_num in weekdays.items():
            if day_name in query_lower:
                params.weekday = day_name
                # Calculate next occurrence of this weekday
                today = datetime.now(SP_TZ)
                days_ahead = (day_num - today.weekday()) % 7
                if days_ahead == 0 and 'próxim' in query_lower:
                    days_ahead = 7
                target = today + timedelta(days=days_ahead)
                params.target_date = target.strftime('%d/%m/%Y')
                break

        return params

    def _run(self, query: str) -> str:
        """Execute slot search with context awareness"""
        try:
            from ....scheduling.scheduling_service import SchedulingService

            # Extract context from conversation
            temporal_context = self._extract_temporal_context()

            # Parse user input
            search_params = self._parse_user_input(query)

            # If user only provided time and we have context, use context date
            if search_params.target_time and not search_params.target_date:
                if temporal_context.offered_date:
                    search_params.target_date = temporal_context.offered_date
                    logger.info(f"[ContextAware] Using date from context: {temporal_context.offered_date}")

            # Get all available slots
            scheduling = SchedulingService(self.db, self.company_id)
            all_slots = scheduling.get_next_available_slots()

            if not all_slots:
                return "Nenhum horário disponível no momento."

            # Filter slots based on search parameters
            filtered_slots = []

            # Se não há parâmetros específicos, priorizar slots mais próximos
            if not search_params.target_date and not search_params.target_time and not search_params.period and not search_params.weekday:
                logger.info("[ContextAware] No specific search parameters, prioritizing nearest slots")

                # Converter todos os slots para datetime e ordenar
                slots_with_datetime = []
                for slot_str in all_slots:
                    try:
                        dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
                        dt = dt.replace(tzinfo=SP_TZ)
                        slots_with_datetime.append((dt, slot_str))
                    except ValueError:
                        continue

                # Ordenar por data/hora mais próxima
                slots_with_datetime.sort(key=lambda x: x[0])

                # Pegar os próximos slots disponíveis
                now = datetime.now(SP_TZ)
                for dt, slot_str in slots_with_datetime:
                    if dt > now:
                        filtered_slots.append(slot_str)
                        if len(filtered_slots) >= 10:  # Limitar a 10 slots mais próximos
                            break

                logger.info(f"[ContextAware] Selected {len(filtered_slots)} nearest slots from {len(all_slots)} total")
            else:
                # Aplicar filtros específicos quando há critérios de busca
                for slot_str in all_slots:
                    try:
                        dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
                        dt = dt.replace(tzinfo=SP_TZ)

                        # Check date match
                        if search_params.target_date:
                            if dt.strftime('%d/%m/%Y') != search_params.target_date:
                                continue

                        # Check time match
                        if search_params.target_time:
                            if dt.strftime('%H:%M') != search_params.target_time:
                                continue

                        # Check period match
                        if search_params.period:
                            hour = dt.hour
                            if search_params.period == 'morning' and not (8 <= hour < 12):
                                continue
                            elif search_params.period == 'afternoon' and not (12 <= hour < 18):
                                continue
                            elif search_params.period == 'evening' and not (18 <= hour < 22):
                                continue

                        filtered_slots.append(slot_str)

                    except ValueError:
                        continue

            # Format results as structured data
            if not filtered_slots:
                # If no exact matches, find alternatives
                return self._find_alternatives_json(search_params, all_slots)

            # Build structured result
            slots_data = []
            weekday_names = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']

            for slot_str in filtered_slots[:5]:  # Show up to 5 matches
                try:
                    dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
                    dt = dt.replace(tzinfo=SP_TZ)
                    weekday = weekday_names[dt.weekday()]

                    slots_data.append(FoundSlot(
                        date=dt.strftime('%d/%m/%Y'),
                        time=dt.strftime('%H:%M'),
                        weekday=weekday,
                        full_slot=slot_str,
                        formatted=f"{weekday}, {dt.strftime('%d/%m/%Y')} às {dt.strftime('%H:%M')}"
                    ).model_dump())
                except Exception as e:
                    logger.warning(f"Error parsing slot {slot_str}: {e}")
                    continue

            result = SlotsSearchResult(
                found_slots=slots_data,
                message=f"Encontrei {len(slots_data)} horários disponíveis",
                has_exact_match=True
            )

            # Return as JSON string for compatibility
            return json.dumps(result.model_dump(), ensure_ascii=False)

        except Exception as e:
            logger.error(f"[ContextAware] Error searching slots: {e}")
            return "Erro ao buscar horários disponíveis."

    def _find_alternatives_json(self, params: SlotSearchParams, all_slots: List[str]) -> str:
        """Find alternative slots when exact match not found - returns JSON"""
        slots_data = []
        weekday_names = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
        message = "Não encontrei o horário exato solicitado. "

        if params.target_date and params.target_time:
            # Find slots on same date
            same_date_slots = []
            for slot in all_slots:
                if params.target_date in slot:
                    same_date_slots.append(slot)

            if same_date_slots:
                message += f"Horários disponíveis em {params.target_date}:"
                for slot_str in same_date_slots[:5]:
                    try:
                        dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
                        dt = dt.replace(tzinfo=SP_TZ)
                        weekday = weekday_names[dt.weekday()]

                        slots_data.append(FoundSlot(
                            date=dt.strftime('%d/%m/%Y'),
                            time=dt.strftime('%H:%M'),
                            weekday=weekday,
                            full_slot=slot_str,
                            formatted=f"{weekday}, {dt.strftime('%d/%m/%Y')} às {dt.strftime('%H:%M')}"
                        ).model_dump())
                    except:
                        continue
            else:
                # Find same time on different dates
                message += f"O horário {params.target_time} está disponível em:"
                for slot_str in all_slots:
                    if params.target_time in slot_str:
                        try:
                            dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
                            dt = dt.replace(tzinfo=SP_TZ)
                            weekday = weekday_names[dt.weekday()]

                            slots_data.append(FoundSlot(
                                date=dt.strftime('%d/%m/%Y'),
                                time=dt.strftime('%H:%M'),
                                weekday=weekday,
                                full_slot=slot_str,
                                formatted=f"{weekday}, {dt.strftime('%d/%m/%Y')} às {dt.strftime('%H:%M')}"
                            ).model_dump())
                        except:
                            continue

                        if len(slots_data) >= 5:
                            break

        result = SlotsSearchResult(
            found_slots=slots_data,
            message=message,
            has_exact_match=False
        )

        return json.dumps(result.dict(), ensure_ascii=False)

    def _find_alternatives(self, params: SlotSearchParams, all_slots: List[str]) -> str:
        """Find alternative slots when exact match not found"""
        result = "Não encontrei o horário exato solicitado. "

        if params.target_date and params.target_time:
            # Find slots on same date
            same_date_slots = []
            for slot in all_slots:
                if params.target_date in slot:
                    same_date_slots.append(slot)

            if same_date_slots:
                result += f"Horários disponíveis em {params.target_date}:\n"
                for slot in same_date_slots[:5]:
                    time = slot.split()[1]
                    result += f"- {time}\n"
            else:
                # Find same time on different dates
                result += f"O horário {params.target_time} está disponível em:\n"
                count = 0
                for slot in all_slots:
                    if params.target_time in slot:
                        date = slot.split()[0]
                        result += f"- {date}\n"
                        count += 1
                        if count >= 5:
                            break

        return result

    async def _arun(self, query: str) -> str:
        """Async version"""
        return self._run(query)


def create_context_aware_slots_agent(db: Any, company_id: int, conversation_history: List[Dict[str, str]] = None) -> Tuple[AgentExecutor, List[BaseTool]]:
    """Create a context-aware slots agent for the requested company."""

    # Create LLM
    llm = ChatOpenAI(
        model="gpt-4.1-mini-2025-04-14",
        temperature=0,
        max_tokens=500
    )

    # Create tool with context
    slots_tool = ContextAwareSlotsTool()
    slots_tool.db = db
    slots_tool.company_id = company_id
    slots_tool.conversation_history = conversation_history or []

    tools = [slots_tool]

    # Create prompt that includes conversation history
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Você é um assistente especializado em encontrar horários de agendamento.

IMPORTANTE: Quando o usuário responder apenas com um horário (ex: "17:00") após você ter oferecido
opções específicas, SEMPRE busque esse horário na mesma data que você ofereceu.

Analise cuidadosamente o contexto da conversa para entender:
1. Que data/horários foram oferecidos ao usuário
2. O que o usuário está escolhendo ou solicitando

Use a ferramenta search_slots_with_context para buscar os horários corretos."""),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad")
    ])

    # Create agent
    agent = create_openai_functions_agent(
        llm=llm,
        tools=tools,
        prompt=prompt
    )

    # Create executor
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=3,
        handle_parsing_errors=True
    )

    return agent_executor, tools


def handle_slots_context_aware(
    user_input: str,
    conversation_history: List[Dict[str, str]],
    db: Any,
    company_id: int
) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    Handle scheduling slots with conversation context for any company.

    Returns:
        - enriched_input: User input with slot information
        - selected_slots: List of specific slots to offer
    """
    try:
        # Create agent with conversation context
        agent_executor, tools = create_context_aware_slots_agent(
            db,
            company_id,
            conversation_history
        )

        # Prepare chat history for agent
        chat_history = []
        for msg in conversation_history[-5:]:  # Last 5 messages
            if msg['role'] == 'human':
                chat_history.append(HumanMessage(content=msg['content']))
            else:
                chat_history.append(AIMessage(content=msg['content']))

        # Run agent
        result = agent_executor.invoke({
            "input": f"Encontre os melhores horários para: {user_input}",
            "chat_history": chat_history
        })

        agent_output = result.get("output", "")
        logger.info(f"[ContextAware] Agent result: {agent_output}")

        # Try to parse as JSON first (new structured format)
        try:
            output_data = json.loads(agent_output)
            if isinstance(output_data, dict) and "found_slots" in output_data:
                slots_list = output_data.get("found_slots", [])
                if slots_list:
                    # Extract slots from structured data
                    selected_slots = [slot["full_slot"] for slot in slots_list[:2]]

                    # Create formatted message
                    formatted_msg = "Horários disponíveis:\n"
                    for slot in slots_list[:2]:
                        formatted_msg += f"- {slot['formatted']}\n"

                    enriched_input = f"{user_input}\n\n✅ **{formatted_msg}**"
                    logger.info(f"[ContextAware] Successfully parsed JSON output with {len(selected_slots)} slots")
                    return enriched_input, selected_slots
        except json.JSONDecodeError:
            logger.info("[ContextAware] Output is not JSON, falling back to regex parsing")

        # Fallback to regex parsing if not JSON
        # Try multiple patterns to be more flexible
        patterns = [
            r'(?:dia\s+)?(\d{2}/\d{2}/\d{4}),?\s+às\s+(\d{2}:\d{2})',  # With optional "dia"
            r'(\d{2}/\d{2}/\d{4})\s+às\s+(\d{2}:\d{2})',                # Without "dia"
            r'-\s+\w+,\s+(\d{2}/\d{2}/\d{4})\s+às\s+(\d{2}:\d{2})'      # With bullet point and weekday
        ]

        selected_slots = []
        for pattern in patterns:
            matches = re.findall(pattern, agent_output)
            for date, time in matches:
                slot = f"{date} {time}"
                if slot not in selected_slots:  # Avoid duplicates
                    selected_slots.append(slot)

        if selected_slots:
            enriched_input = f"{user_input}\n\n✅ **Horários sugeridos pelo assistente:**\n{agent_output}"
            logger.info(f"[ContextAware] Found {len(selected_slots)} slots via regex")
            return enriched_input, selected_slots[:2]  # Return top 2 slots

        logger.warning("[ContextAware] No slots found in agent output")
        return None, None

    except Exception as e:
        logger.error(f"[ContextAware] Error in slot handling: {e}")
        return None, None
