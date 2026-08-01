"""
Scheduling Tools - Function tools for appointment management
Enhanced with structured context and detailed tracing
"""

import json
import logging
from typing import Dict, Any, List
from datetime import datetime
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agents import function_tool, RunContextWrapper, trace
from backend.services.ai_provider_service import get_company_openai_api_key

# Import structured context
try:
    from ..context.contact_context import CustomerContext
except ImportError:
    # Fallback for backwards compatibility
    CustomerContext = None

logger = logging.getLogger(__name__)

async def _analyze_scheduling_preferences_with_context(
    current_message: str,
    conversation_history: List[str] = None,
    phone: str = None,
    company_id: int = None,
    db: Session = None,
) -> Dict[str, Any]:
    """
    Use LLM to analyze user scheduling preferences with conversation context

    Args:
        current_message: Current user message
        conversation_history: Recent conversation context

    Returns:
        Dict with semantic analysis results
    """
    if not current_message.strip():
        return {}

    # LATENCY OPTIMIZATION: Try "Fast Pass" heuristic analysis first
    # If code can understand the date reliably, skip the expensive LLM call (~1.5s saved)
    try:
        fast_pass_result = _fallback_simple_analysis(current_message, conversation_history)

        # Criteria for using Fast Pass result:
        # 1. Has specific date (e.g. "10/12") OR
        # 2. Has clear urgency (e.g. "amanhã", "semana que vem") AND isn't just "flexible" OR
        # 3. Has specific weekday ("segunda")
        if (fast_pass_result.get("specific_date") or
            (fast_pass_result.get("urgency") != "flexible") or
            fast_pass_result.get("weekday_name")):

            logger.info(f"[FastPass] Latency Optimization: Bypassed LLM for '{current_message}' -> {fast_pass_result}")
            return fast_pass_result

    except Exception as e:
        logger.warning(f"[FastPass] optimization check failed: {e}")
        # Continue to LLM if fast pass fails

    # NEW: Handle specific date format (dd/mm/yyyy) directly
    import re
    if re.match(r'\d{2}/\d{2}/\d{4}', current_message.strip()):
        try:
            from datetime import datetime
            date_obj = datetime.strptime(current_message.strip(), "%d/%m/%Y")
            weekday_names = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
            weekday_name = weekday_names[date_obj.weekday()]

            # Calculate urgency based on date
            today = datetime.now().date()
            target_date = date_obj.date()
            days_diff = (target_date - today).days

            if days_diff == 0:
                urgency = "today"
            elif days_diff == 1:
                urgency = "tomorrow"
            elif 2 <= days_diff <= 6:
                urgency = "this_week"
            elif 7 <= days_diff <= 13:
                urgency = "next_week"
            else:
                urgency = "flexible"

            logger.info(f"[DateSpecific] {current_message} → {weekday_name}, urgency={urgency}, days_diff={days_diff}")

            return {
                "weekday_name": weekday_name,
                "time_periods": [],
                "time_preference": "flexible",
                "specific_times": [],
                "time_restrictions": {"type": "none", "min_time": None, "max_time": None},
                "urgency": urgency
            }

        except ValueError:
            logger.warning(f"[DateSpecific] Failed to parse date: {current_message}")
            pass  # Fall through to normal LLM analysis

    try:
        from openai import AsyncOpenAI
        import asyncio
        from backend.db import get_db
        from sqlalchemy.sql import text

        client = AsyncOpenAI(
            api_key=get_company_openai_api_key(db, company_id),
        )

        # Build context-aware prompt
        context_str = ""
        if conversation_history:
            recent_messages = conversation_history[-6:]  # Last 3 exchanges
            context_str = f"CONVERSATION CONTEXT: {' | '.join(recent_messages)}\n\n"

        # Get current temporal context
        from datetime import datetime, timedelta
        now = datetime.now()
        today = now.strftime("%d/%m/%Y")
        tomorrow = (now + timedelta(days=1)).strftime("%d/%m/%Y")
        day_after = (now + timedelta(days=2)).strftime("%d/%m/%Y")

        weekday_names = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
        today_weekday = weekday_names[now.weekday()]
        tomorrow_weekday = weekday_names[(now + timedelta(days=1)).weekday()]
        dayafter_weekday = weekday_names[(now + timedelta(days=2)).weekday()]

        # Calculate specific dates for each weekday (this week and next week)
        weekday_this_week = {}
        weekday_next_week = {}
        for i in range(7):
            # This week
            days_ahead = i - now.weekday()
            if days_ahead < 0:  # Day already passed this week
                # Calculate for next week
                days_ahead += 7
                date = now + timedelta(days=days_ahead)
                weekday_next_week[weekday_names[i]] = date.strftime("%d/%m/%Y")
            else:
                # This week
                date = now + timedelta(days=days_ahead)
                weekday_this_week[weekday_names[i]] = date.strftime("%d/%m/%Y")
                # Also calculate next week version
                next_week_date = date + timedelta(days=7)
                weekday_next_week[weekday_names[i]] = next_week_date.strftime("%d/%m/%Y")

        current_time = now.strftime("%H:%M")
        current_month = now.strftime("%B")
        current_year = now.year

        # Determine current period
        hour = now.hour
        if hour < 12:
            current_period = "manhã"
        elif hour < 18:
            current_period = "tarde"
        else:
            current_period = "noite"

        # Check if user has future appointment (for context)
        # Run DB query in thread to avoid blocking
        def _get_current_appointment():
            info = "- AGENDAMENTO ATUAL: Nenhum agendamento encontrado"
            try:
                db_temp = next(get_db())
                result = db_temp.execute(text("""
                    SELECT consulta_data
                    FROM agendamentos
                    WHERE phone = :phone AND company_id = :company_id
                    AND status NOT LIKE 'CANCELLED%'
                    ORDER BY id DESC
                    LIMIT 1
                """), {"phone": phone, "company_id": company_id})

                row = result.fetchone()
                if row and row.consulta_data:
                    appt_date = row.consulta_data.date()
                    appt_weekday = weekday_names[appt_date.weekday()]
                    info = f"- AGENDAMENTO ATUAL: {appt_date.strftime('%d/%m/%Y')} ({appt_weekday})"
                db_temp.close()
            except Exception as e:
                info = f"- AGENDAMENTO ATUAL: Erro ao buscar ({e})"
            return info

        appointment_info = await asyncio.to_thread(_get_current_appointment) if phone and company_id else "- AGENDAMENTO ATUAL: Nenhum agendamento encontrado"

        # Build mapping strings for the prompt
        this_week_mapping = ""
        for weekday, date in weekday_this_week.items():
            this_week_mapping += f'  * "{weekday}" → specific_date: "{date}", urgency: "this_week"\n'

        next_week_mapping = ""
        for weekday, date in weekday_next_week.items():
            next_week_mapping += f'  * "{weekday}" (próxima semana) → specific_date: "{date}", urgency: "next_week"\n'

        analysis_prompt = f"""Analyze this scheduling request with complete temporal context:

CURRENT TEMPORAL CONTEXT:
- NOW: {today} ({today_weekday}), {current_time}, {current_period}, {current_month}/{current_year}
- HOJE: {today} ({today_weekday})
- AMANHÃ: {tomorrow} ({tomorrow_weekday})
{appointment_info}
- DEPOIS DE AMANHÃ: {day_after} ({dayafter_weekday})

{context_str}CURRENT REQUEST: "{current_message}"

PADRÕES TEMPORAIS MELHORADOS (baseados em conversas reais):

1. PERÍODOS ESTENDIDOS:
- "semana que vem" → próxima semana (urgency: "next_week")
- "outra semana" → próxima semana ou futura (urgency: "next_week")
- "na próxima semana" → próxima semana
- "mês que vem" → próximo mês (urgency: "next_month")

2. RESTRIÇÕES DE HORÁRIO (CRÍTICO - DETECTE SEMPRE):
- "depois das 11" → horário mínimo 12:00 (NOTA: "depois de 11" = 12:00 ou mais tarde)
- "depois das 14h" → horário mínimo 15:00 (NOTA: "depois de 14" = 15:00 ou mais tarde)
- "depois das 15" → horário mínimo 16:00 (NOTA: "depois de 15" = 16:00 ou mais tarde)
- "só posso depois das 15" → horário mínimo 16:00
- "após às 15h" → horário mínimo 16:00
- "a partir das 16h" → horário mínimo 16:00
- "só se for depois das X" → horário mínimo X+1
- "só posso depois das 11" → horário mínimo 12:00

3. VARIAÇÕES ORTOGRÁFICAS:
- "segunda feira" (sem hífen) → "Segunda-feira"
- "terca feira" → "Terça-feira"
- "quarta feira" → "Quarta-feira"

Map relative terms correctly:
- "hoje" → {today_weekday} (urgency: "today")
- "amanhã" → {tomorrow_weekday} (urgency: "tomorrow")
- "depois de amanhã" → {dayafter_weekday} (urgency: "tomorrow")

CRITICAL: Para dias da semana (segunda, terça, quarta, quinta, sexta, sábado, domingo):
- HOJE é {today_weekday} ({today})
- Mapeamento exato para ESTA SEMANA (dias que ainda não passaram):
{this_week_mapping}
- Mapeamento exato para PRÓXIMA SEMANA (dias que já passaram ou pedidos para próxima semana):
{next_week_mapping}

- "semana que vem" → urgency: "next_week"
- "outra semana" → urgency: "next_week"
- "próxima semana" → urgency: "next_week"

Extract scheduling preferences considering conversation context and temporal mapping.

CRITICAL RULES FOR TIME RESTRICTIONS:
- If user says "depois das X" or "só posso depois das X", you MUST set time_restrictions.type="after"
- "depois das 15" means min_time="16:00" (NOT 15:00 - they want AFTER 15, not AT 15)
- "depois das 14" means min_time="15:00" (NOT 14:00 - they want AFTER 14, not AT 14)
- Always add 1 hour to the mentioned time for "depois das" phrases

Return ONLY a JSON object with these EXPANDED fields:
{{
  "weekday_name": "Segunda-feira" | "Terça-feira" | "Quarta-feira" | "Quinta-feira" | "Sexta-feira" | "Sábado" | "Domingo" | null,
  "specific_date": "DD/MM/YYYY" | null,  // CRÍTICO: SEMPRE inclua quando mencionar dia específico
  "time_periods": ["manha", "tarde", "noite"],
  "time_preference": "early" | "late" | "flexible" | "specific" | "restricted",
  "specific_times": ["08:00", "14:00"],
  "time_restrictions": {{
    "type": "after" | "before" | "none",
    "min_time": "14:00" | null,
    "max_time": "18:00" | null
  }},
  "urgency": "today" | "tomorrow" | "this_week" | "next_week" | "next_month" | "flexible"
}}

REGRA FUNDAMENTAL:
- Quando usuário menciona um dia da semana (segunda, terça, quarta, quinta, sexta, sábado, domingo):
  SEMPRE inclua "specific_date" com a data DD/MM/YYYY correspondente baseada nos mapeamentos acima
- Use os mapeamentos ESTA SEMANA / PRÓXIMA SEMANA para determinar a data correta

Examples:
- "sábado" → USE O MAPEAMENTO ACIMA para determinar specific_date, então retorne algo como {{"weekday_name": "Sábado", "specific_date": "[data do sábado]", "time_periods": [], "time_preference": "flexible", "urgency": "this_week" ou "next_week"}}
- "tarde no fim do dia" → {{"weekday_name": null, "time_periods": ["tarde", "noite"], "time_preference": "late"}}
- "fim da manhã" → {{"weekday_name": null, "time_periods": ["manha"], "time_preference": "late"}}
- "bem cedo" → {{"weekday_name": null, "time_periods": ["manha"], "time_preference": "early"}}

NOVOS EXEMPLOS (baseados em conversas reais):
- "semana que vem" → {{"urgency": "next_week", "time_preference": "flexible"}}
- "outra semana" → {{"urgency": "next_week", "time_preference": "flexible"}}
- "depois das 11" → {{"time_periods": ["tarde"], "time_preference": "restricted", "time_restrictions": {{"type": "after", "min_time": "12:00", "max_time": null}}}}
- "só posso depois das 11" → {{"time_periods": ["tarde"], "time_preference": "restricted", "time_restrictions": {{"type": "after", "min_time": "12:00", "max_time": null}}}}
- "depois das 14h" → {{"time_periods": ["tarde", "noite"], "time_preference": "restricted", "time_restrictions": {{"type": "after", "min_time": "15:00", "max_time": null}}}}
- "só posso depois das 15" → {{"time_periods": ["tarde", "noite"], "time_preference": "restricted", "time_restrictions": {{"type": "after", "min_time": "16:00", "max_time": null}}}}
- "segunda feira pela manhã" → {{"weekday_name": "Segunda-feira", "time_periods": ["manha"], "time_preference": "flexible", "time_restrictions": {{"type": "none", "min_time": null, "max_time": null}}}}
- "só se for depois das 15h" → {{"time_preference": "restricted", "time_restrictions": {{"type": "after", "min_time": "16:00", "max_time": null}}}}
- "na próxima semana de tarde" → {{"urgency": "next_week", "time_periods": ["tarde"], "time_preference": "flexible", "time_restrictions": {{"type": "none", "min_time": null, "max_time": null}}}}
- "Tem segunda depois das 11?" → {{"weekday_name": "Segunda-feira", "specific_date": "[usar mapeamento]", "time_preference": "restricted", "time_restrictions": {{"type": "after", "min_time": "12:00", "max_time": null}}}}

TEMPORAL MAPPING Examples (baseado em HOJE {today_weekday} {today}):
- "hoje" → {{"specific_date": "{today}", "weekday_name": "{today_weekday}", "urgency": "today"}}
- "amanhã" → {{"specific_date": "{tomorrow}", "weekday_name": "{tomorrow_weekday}", "urgency": "tomorrow"}}
- "depois de amanhã" → {{"specific_date": "{day_after}", "weekday_name": "{dayafter_weekday}", "urgency": "tomorrow"}}

WEEKDAY Examples (use os mapeamentos acima para determinar a data correta):
- Se hoje é {today_weekday} e usuário pede "sexta", veja o mapeamento acima para determinar se é esta semana ou próxima
- Se usuário pede "na sexta" ou "sexta-feira", use o mapeamento para pegar a data específica
- SEMPRE inclua specific_date com a data DD/MM/YYYY correspondente

CONTEXTUAL Examples (CRÍTICO - mantenha contexto temporal):
- Context: "tem de tarde, no fim do dia?" | Current: "na proxima segunda tem?" → {{"weekday_name": "Segunda-feira", "time_periods": ["tarde", "noite"], "time_preference": "late"}}
- Context: "manhã cedo" | Current: "e na terça?" → {{"weekday_name": "Terça-feira", "time_periods": ["manha"], "time_preference": "early"}}
- Context: "Previous user request: tem na outra semana?" | Current: "quarta" → {{"weekday_name": "Quarta-feira", "urgency": "next_week", "time_restrictions": {{"type": "none", "min_time": null, "max_time": null}}}}
- Context: "Previous user request: semana que vem" | Current: "na sexta semana que vem" → {{"weekday_name": "Sexta-feira", "urgency": "next_week", "time_restrictions": {{"type": "none", "min_time": null, "max_time": null}}}}
- Current: "tem depois de amanhã" → {{"weekday_name": "{dayafter_weekday}", "time_preference": "flexible", "time_restrictions": {{"type": "none", "min_time": null, "max_time": null}}}}
- Current: "semana que vem depois das 16h" → {{"urgency": "next_week", "time_preference": "restricted", "time_restrictions": {{"type": "after", "min_time": "16:00", "max_time": null}}}}

REGRAS DE CONTEXTO TEMPORAL:
1. Se a mensagem ATUAL contém explicitamente "semana que vem", "próxima semana", "outra semana" → urgency: "next_week"
2. IMPORTANTE: Se usuário tem agendamento futuro confirmado, interpretar dias da semana isolados ("quinta", "terça") como APÓS o agendamento atual → urgency: "next_week"
3. Se usuário SEM agendamento menciona dia da semana → interpretar como próximo disponível
4. Para perguntas tipo "e no [dia]?" → considerar se há agendamento futuro para determinar referência

PRIORIDADE: Agendamento futuro existente > Mensagem atual para determinação de contexto temporal

Return ONLY the JSON, no explanations."""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": analysis_prompt}],
            max_tokens=200,
            temperature=0.1
        )

        result_text = response.choices[0].message.content.strip()

        # Clean JSON response (remove markdown if present)
        if result_text.startswith('```json'):
            result_text = result_text.replace('```json', '').replace('```', '').strip()

        import json
        analysis_result = json.loads(result_text)

        logger.info(f"[SemanticAnalysis] Request: '{current_message}' (with context) → Analysis: {analysis_result}")
        return analysis_result

    except Exception as exc:
        logger.error(
            "[SemanticAnalysis] Falling back after LLM error: error_type=%s",
            type(exc).__name__,
        )
        # Fallback to enhanced keyword matching with context
        return _fallback_simple_analysis(current_message, conversation_history)

def _fallback_simple_analysis(user_request: str, conversation_history: List[str] = None) -> Dict[str, Any]:
    """Enhanced fallback analysis with new patterns from real conversations"""
    request_lower = user_request.lower()

    # Calculate specific dates for temporal references
    from datetime import datetime, timedelta
    today = datetime.now()
    tomorrow = (today + timedelta(days=1)).strftime("%d/%m/%Y")
    day_after = (today + timedelta(days=2)).strftime("%d/%m/%Y")

    specific_date = None  # NOVO: Data específica para filtrar

    # Enhanced weekday detection (including variations found in real conversations)
    weekday_name = None
    weekday_mapping = {
        "segunda": "Segunda-feira",
        "segunda-feira": "Segunda-feira",
        "segunda feira": "Segunda-feira",  # sem hífen (padrão real)
        "terça": "Terça-feira",
        "terça-feira": "Terça-feira",
        "terca": "Terça-feira",  # sem acento
        "terca feira": "Terça-feira",  # sem acento e hífen
        "quarta": "Quarta-feira",
        "quarta-feira": "Quarta-feira",
        "quarta feira": "Quarta-feira",  # sem hífen
        "quinta": "Quinta-feira",
        "quinta-feira": "Quinta-feira",
        "quinta feira": "Quinta-feira",  # sem hífen
        "sexta": "Sexta-feira",
        "sexta-feira": "Sexta-feira",
        "sexta feira": "Sexta-feira",  # sem hífen
        "sábado": "Sábado",
        "sabado": "Sábado",  # sem acento
        "domingo": "Domingo"
    }

    for key, value in weekday_mapping.items():
        if key in request_lower:
            weekday_name = value
            break

    # Enhanced time period detection
    time_periods = []
    if any(word in request_lower for word in ["manhã", "manha", "cedo", "bem cedo", "manhã cedo"]):
        time_periods.append("manha")
    if any(word in request_lower for word in ["tarde", "meio dia", "depois do almoço", "parte da tarde"]):
        time_periods.append("tarde")
    if any(word in request_lower for word in ["noite", "fim do dia", "final", "tarde da noite"]):
        time_periods.extend(["tarde", "noite"])

    # NEW: Detect time restrictions (based on real conversations)
    time_restrictions = {"type": None, "min_time": None, "max_time": None}
    time_preference = "flexible"

    # Detect "depois das X" patterns
    import re
    if any(phrase in request_lower for phrase in ["depois das", "após às", "a partir das", "só se for depois"]):
        time_restrictions["type"] = "after"
        time_preference = "restricted"

        # Try to extract specific time (14h, 14:00, etc.)
        time_match = re.search(r'(\d{1,2}):?(\d{2})?[h:]?', user_request)
        if time_match:
            hour = time_match.group(1).zfill(2)
            minute = time_match.group(2) or "00"
            time_restrictions["min_time"] = f"{hour}:{minute}"

            # If after 14h, likely afternoon/evening
            if int(hour) >= 14:
                time_periods.extend(["tarde", "noite"])

    # NEW: Detect urgency patterns (including from conversation context)
    urgency = "flexible"

    # First check current message
    if any(phrase in request_lower for phrase in ["semana que vem", "outra semana", "próxima semana"]):
        urgency = "next_week"
    elif any(phrase in request_lower for phrase in ["mês que vem", "próximo mês"]):
        urgency = "next_month"
    elif "hoje" in request_lower:
        urgency = "today"
        specific_date = today.strftime("%d/%m/%Y")  # NOVO: Define data específica
    elif "amanhã" in request_lower:
        urgency = "tomorrow"
        specific_date = tomorrow  # NOVO: Define data específica para amanhã
    elif any(phrase in request_lower for phrase in ["essa semana", "esta semana"]):
        urgency = "this_week"

    # NEW: Check conversation context for temporal clues
    elif conversation_history:
        for context_msg in conversation_history:
            if isinstance(context_msg, str):
                context_lower = context_msg.lower()
                if any(phrase in context_lower for phrase in ["outra semana", "semana que vem", "próxima semana"]):
                    urgency = "next_week"
                    logger.info(f"[FallbackContext] Found 'next_week' urgency from context: '{context_msg}'")
                    break
                elif any(phrase in context_lower for phrase in ["mês que vem", "próximo mês"]):
                    urgency = "next_month"
                    break

    # Enhanced time preference detection
    if "fim" in request_lower:
        time_preference = "late"
    elif any(word in request_lower for word in ["cedo", "bem cedo"]):
        time_preference = "early"
    elif time_restrictions["type"] == "after":
        time_preference = "restricted"

    # Remove duplicates from time_periods
    time_periods = list(set(time_periods))

    # Ensure time_restrictions always has proper structure
    if not time_restrictions or not isinstance(time_restrictions, dict):
        time_restrictions = {"type": "none", "min_time": None, "max_time": None}
    elif "type" not in time_restrictions:
        time_restrictions["type"] = "none"

    return {
        "weekday_name": weekday_name,
        "specific_date": specific_date,  # NOVO: Retorna data específica
        "time_periods": time_periods,
        "time_preference": time_preference,
        "specific_times": [],
        "time_restrictions": time_restrictions,
        "urgency": urgency
    }

class SlotRequest(BaseModel):
    """Request for available slots"""
    preferred_date: str = ""     # dd/mm/yyyy format
    preferred_time: str = ""     # HH:MM format
    professional: str = ""       # Professional name preference

class SchedulingData(BaseModel):
    """Appointment scheduling data"""
    customer_name: str
    customer_phone: str
    slot_datetime: str          # "dd/mm/yyyy HH:MM" format
    service_type: str = "Consulta"
    professional: str = ""
    notes: str = ""

def create_scheduling_tools(slots_service, company_id: int, phone: str = "", agenda_id: int = None):
    """
    Create scheduling tools with proper context injection
    Following openai-agents-python patterns
    """

    @function_tool
    async def get_available_slots(
        context: RunContextWrapper,
        preferred_date: str = "",
        preferred_time: str = "",
        professional: str = ""
    ) -> Dict[str, Any]:
        """
        🚨 MANDATORY TOOL - MUST BE CALLED FIRST for ANY scheduling question!

        IMMEDIATELY call this tool when customer mentions:
        ✅ ANY DAY OF WEEK: "quinta", "sexta", "segunda", "sábado", etc.
        ✅ TIME PERIODS: "semana que vem", "outra semana", "próxima semana", "amanhã", "hoje"
        ✅ SCHEDULING WORDS: "horários", "disponível", "agendar", "consulta", "quando"
        ✅ AVAILABILITY QUESTIONS: "tem", "atendem", "funcionam", "trabalham"

        EXAMPLES that REQUIRE this tool:
        - "e na quinta da outra semana?" → CALL get_available_slots(preferred_date="quinta da outra semana")
        - "tem sábado?" → CALL get_available_slots(preferred_date="sábado")
        - "horários de manhã?" → CALL get_available_slots(preferred_time="manhã")
        - "atendem na próxima semana?" → CALL get_available_slots(preferred_date="próxima semana")
        - "na segunda às 11 tem?" → CALL get_available_slots(preferred_date="segunda", preferred_time="11:00")
        - "tem às 14h?" → CALL get_available_slots(preferred_time="14:00")
        - "só posso depois das 11" → CALL get_available_slots(preferred_time="depois das 11")
        - "É que só posso depois das 11" → CALL get_available_slots(preferred_time="depois das 11")

        🚨 CRITICAL USER CONSTRAINT SCENARIOS:
        If user adds time restriction AFTER seeing slots, you MUST call this tool again!
        Example conversation:
        1. You: "Temos 10:30 e 19:00 na segunda"
        2. User: "só posso depois das 11"
        3. You: MUST CALL get_available_slots(preferred_date="segunda", preferred_time="depois das 11")
        4. DO NOT say "não temos" without calling - the restriction changed!

        🚫 NEVER assume no availability without calling this tool first!
        🚫 NEVER say "não temos horários" without checking this tool!

        This tool searches the real database with intelligent semantic analysis.

        Args:
            preferred_date: Customer's preferred date - can be "sábado", "segunda", etc. (optional)
            preferred_time: Customer's preferred time like "manhã", "tarde" (optional)
            professional: Specific professional requested (optional)

        Returns:
            Dict with available slots organized by date and time
        """
        import asyncio
        from backend.db import get_db
        from sqlalchemy.sql import text

        # Use closure phone if valid, otherwise try context
        current_phone = phone
        if not current_phone and hasattr(context, 'context') and hasattr(context.context, 'phone'):
             current_phone = context.context.phone
        elif not current_phone:
             current_phone = "unknown"

        logger.critical(f"[TOOL_ENTRY] get_available_slots called with: preferred_date='{preferred_date}', preferred_time='{preferred_time}', professional='{professional}'")

        # NEW: Enhanced tracing with structured context
        with trace("get_available_slots", disabled=True):
            # Get structured context if available
            structured_context = None
            if hasattr(context, 'context'):
                structured_context = getattr(context.context, 'structured_context', None)

            # Log initial parameters for tracing
            ctx_company_id = getattr(context.context, 'company_id', 'unknown') if hasattr(context, 'context') else 'unknown'
            ctx_phone = getattr(context.context, 'phone', 'unknown') if hasattr(context, 'context') else 'unknown'

            logger.info(f"[TRACE] Starting get_available_slots - company_id: {company_id}, phone: {current_phone} (ctx_company: {ctx_company_id}, ctx_phone: {ctx_phone}), preferred_date: {preferred_date}, preferred_time: {preferred_time}")

            # Log structured context info if available
            if structured_context and CustomerContext and isinstance(structured_context, CustomerContext):
                logger.info(f"[TRACE] Structured context - stage: {structured_context.current_stage}, step: {structured_context.conversation_step}, pain: {bool(structured_context.pain_description)}, interest: {bool(structured_context.treatment_interest)}, type: {structured_context.customer_type or 'unknown'}")

            try:
                # Extract conversation history from context
                conversation_history = []
                if hasattr(context, '_input_items') and context._input_items:
                    # Extract last few messages for context
                    for item in context._input_items[-10:]:  # Last 5 exchanges
                        if hasattr(item, 'content') and item.content:
                            conversation_history.append(item.content)

                # NEW: Enhanced context preparation - include recent user messages for better temporal context
                enhanced_context = []
                if conversation_history:
                    # Extract only user messages from recent history for temporal context
                    for msg in conversation_history:
                        if isinstance(msg, str):
                            # Check if this was a user message asking about scheduling
                            if any(word in msg.lower() for word in ["semana", "outra", "próxima", "depois", "amanha", "hoje"]):
                                enhanced_context.append(f"Previous user request: {msg}")

                # Use LLM for enhanced semantic analysis with temporal context
                user_request = f"{preferred_date} {preferred_time}".strip()

                # SPECIAL CASE: Handle tomorrow_and_dayafter directive for non-specific preferences
                if preferred_date == "tomorrow_and_dayafter":
                    logger.info(f"[SPECIAL_STRATEGY] User has no specific preference - will suggest tomorrow + day after")
                    semantic_analysis = {
                        "weekday_name": None,
                        "time_periods": [],
                        "time_preference": "flexible",
                        "specific_times": [],
                        "time_restrictions": {"type": "none", "min_time": None, "max_time": None},
                        "urgency": "tomorrow_and_dayafter"  # Special urgency for this case
                    }
                else:
                    logger.info(f"[ContextualAnalysis] Current: '{user_request}', Enhanced context: {enhanced_context}")

                    semantic_analysis = await _analyze_scheduling_preferences_with_context(
                        current_message=user_request,
                        conversation_history=enhanced_context,  # Use enhanced context instead
                        phone=current_phone,
                        company_id=company_id,
                        db=getattr(slots_service, "db", None),
                    )

                logger.critical(f"[SEMANTIC_RESULT] Analysis complete: {semantic_analysis}")

                weekday_name = semantic_analysis.get("weekday_name")
                time_periods = semantic_analysis.get("time_periods", [])
                specific_times = semantic_analysis.get("specific_times", [])
                time_preference = semantic_analysis.get("time_preference")

                # NEW: Extract enhanced semantic fields
                time_restrictions = semantic_analysis.get("time_restrictions") or {}
                urgency = semantic_analysis.get("urgency", "flexible")
                specific_date = semantic_analysis.get("specific_date")  # NOVO: Data específica do LLM

                logger.info(f"[EnhancedSemantics] urgency={urgency}, time_restrictions={time_restrictions}")

                # Execute intelligent searches based on enhanced semantic analysis
                all_slots = []

                # ALWAYS check for current appointment first (for both urgency=next_week AND weekday context)
                current_appointment_date = None

                def _check_current_appt():
                    date_found = None
                    try:
                        db_temp = next(get_db())
                        result = db_temp.execute(text("""
                            SELECT consulta_data
                            FROM agendamentos
                            WHERE phone = :phone AND company_id = :company_id
                            AND status NOT LIKE 'CANCELLED%'
                            ORDER BY id DESC
                            LIMIT 1
                        """), {"phone": current_phone, "company_id": company_id})
                        row = result.fetchone()
                        if row and row.consulta_data:
                            date_found = row.consulta_data.date()
                            logger.info(f"[AppointmentContext] Found current appointment: {date_found}")
                        db_temp.close()
                    except Exception as e:
                        logger.warning(f"[AppointmentContext] Could not find appointment date: {e}")
                    return date_found

                current_appointment_date = await asyncio.to_thread(_check_current_appt)

                # NEW: Adjust search parameters based on urgency
                # RELAXED CONSTRAINTS: Increased default limit to 10
                days_ahead = 30  # default
                search_limit = 10   # default: increased from 2 to 10
                days_offset = 0   # NEW: offset to start search from a future date

                if urgency == "today":
                    days_ahead = 1
                    search_limit = 10
                elif urgency == "tomorrow":
                    days_ahead = 2
                    search_limit = 10
                elif urgency == "tomorrow_and_dayafter":
                    # SPECIAL STRATEGY: Get 1 slot from tomorrow + 1 slot from day after
                    days_ahead = 3
                    search_limit = 20  # Get more slots to filter from
                    logger.info(f"[TOMORROW_DAYAFTER] Special strategy activated - searching next 3 days")
                elif urgency == "this_week":
                    # INTELIGENTE: Se tem horário específico, buscar próximo ao solicitado
                    if specific_times:
                        days_ahead = 14  # Buscar 2 semanas para ter opções
                        search_limit = 10  # Mais slots para filtrar proximidade
                    else:
                        days_ahead = 7
                        search_limit = 10  # Follow company standard: suggest only 2 options
                elif urgency == "next_week":
                    # FIXED: Use already found appointment date as reference
                    from datetime import datetime, timedelta

                    today = datetime.now().date()
                    reference_date = current_appointment_date if current_appointment_date else today

                    # Calculate "next week" based on appointment date (if found) or today
                    days_until_next_week = 7 - reference_date.weekday()  # Days until next Monday from reference
                    days_offset = (reference_date - today).days + days_until_next_week  # Offset from today

                    # Ensure minimum offset is reasonable
                    if days_offset < 1:
                        days_offset = 7  # Default to next week from today

                    days_ahead = days_offset + 7  # Search one week starting from next week
                    search_limit = 10
                    logger.info(f"[NextWeekSearch] Reference date: {reference_date}, today: {today}, offset={days_offset} days to reach next week")
                elif urgency == "next_month":
                    days_ahead = 60  # 2 months
                    search_limit = 10

                # PRIORIZAÇÃO INTELIGENTE: Quando usuário não especifica nada (caso genérico)
                # Detecta quando é uma solicitação genérica sem dia/horário específico
                if not weekday_name and not time_periods and urgency == "flexible":
                    # Priorizar D+1 e D+2 para melhor conversão
                    days_ahead = 3  # Buscar apenas D+1, D+2 e D+3
                    search_limit = 10  # Pegar mais slots para escolher os 2 melhores distribuídos
                    logger.info(f"[PRIORITY_NEAR] Caso genérico detectado - priorizando D+1 e D+2 com days_ahead={days_ahead}, limit={search_limit}")

                # SPECIAL: If weekday_name is requested AND user has appointment, apply smart context
                # This handles cases like "terça" after "outra semana" where urgency becomes 'flexible' or 'this_week'
                # but we still want to consider it relative to the appointment date
                if weekday_name and current_appointment_date and urgency in ["flexible", "this_week"]:
                    from datetime import datetime, timedelta
                    today = datetime.now().date()

                    # Find the next occurrence of the requested weekday from appointment date
                    weekday_names = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
                    target_weekday_index = weekday_names.index(weekday_name)
                    current_weekday_index = current_appointment_date.weekday()

                    # Calculate days to next occurrence from appointment date
                    days_to_target = (target_weekday_index - current_weekday_index) % 7
                    if days_to_target == 0:  # Same weekday as appointment
                        days_to_target = 7  # Next week's occurrence

                    target_date = current_appointment_date + timedelta(days=days_to_target)
                    days_offset = (target_date - today).days

                    # If target is very close to appointment, move to next week's occurrence
                    if abs(days_offset) < 3:  # Within 3 days of appointment
                        days_offset += 7

                    logger.info(f"[WeekdayContext] {weekday_name} after appointment {current_appointment_date} → target offset={days_offset} days")

                logger.info(f"[SearchParams] urgency={urgency} → days_ahead={days_ahead}, limit={search_limit}")

                # Use DatabaseSchedulingService method for real data
                if hasattr(slots_service, 'get_available_slots_from_database'):
                    # DatabaseSchedulingService - use real data with filters
                    logger.critical(f"[DB_SERVICE_DEBUG] Calling get_available_slots_from_database with weekday_name='{weekday_name}', time_periods={time_periods}")

                    def _fetch_db_slots():
                         try:
                             return slots_service.get_available_slots_from_database(
                                limit=200,  # High limit to ensure we reach future weeks (slots are at position 159+)
                                weekday_name=weekday_name,
                                time_period=time_periods[0] if time_periods else None,
                                day_type=None  # Could be added later if needed
                            )
                         except Exception as e:
                             logger.error(f"Error fetching DB slots: {e}")
                             return []

                    all_slots = await asyncio.to_thread(_fetch_db_slots)

                    # --- FALLBACK STRATEGY START ---
                    if not all_slots and hasattr(slots_service, 'get_available_slots_from_database'):
                        logger.warning(f"[FallbackStrategy] Primary search returned 0 slots for {weekday_name} {time_periods}")

                        # Strategy 1: Relax Time Constraint (Same day, any time)
                        if weekday_name and time_periods:
                            logger.info(f"[FallbackStrategy] Attempting Strategy 1: Relax Time Constraint (keep {weekday_name}, ignore {time_periods})")
                            def _fetch_fallback_1():
                                return slots_service.get_available_slots_from_database(
                                    limit=10,
                                    weekday_name=weekday_name,
                                    time_period=None, # Relaxed
                                    day_type=None
                                )
                            fallback_slots = await asyncio.to_thread(_fetch_fallback_1)
                            if fallback_slots:
                                for s in fallback_slots:
                                    s['metadata']['is_fallback'] = True
                                    s['metadata']['fallback_reason'] = f"Relaxed time constraint (found for {weekday_name})"
                                all_slots.extend(fallback_slots)
                                logger.info(f"[FallbackStrategy] Strategy 1 success: found {len(fallback_slots)} slots")

                        # Strategy 2: Broad Search (Next 7 days, any time)
                        if not all_slots:
                            logger.info(f"[FallbackStrategy] Attempting Strategy 2: Broad Search (Next 7 days)")
                            def _fetch_fallback_2():
                                # Searching generally without weekday filter implies searching next available days
                                return slots_service.get_available_slots_from_database(
                                    limit=10,
                                    weekday_name=None, # Relaxed
                                    time_period=None,  # Relaxed
                                    day_type=None
                                )
                            fallback_slots = await asyncio.to_thread(_fetch_fallback_2)
                            if fallback_slots:
                                for s in fallback_slots:
                                    s['metadata']['is_fallback'] = True
                                    s['metadata']['fallback_reason'] = "No slots found for specific request. Showing next available."
                                all_slots.extend(fallback_slots)
                                logger.info(f"[FallbackStrategy] Strategy 2 success: found {len(fallback_slots)} slots")
                    # --- FALLBACK STRATEGY END ---

                    # Filtering is now handled inside DatabaseSchedulingService
                    logger.critical(f"[DB_SERVICE_DEBUG] DatabaseSchedulingService returned {len(all_slots) if isinstance(all_slots, list) else 'not_list'} slots")
                else:
                    # Fallback for SlotsService (testing)
                    if weekday_name:
                        logger.critical(f"[WEEKDAY_DEBUG] Searching for weekday_name='{weekday_name}' with limit={search_limit}")

                        def _fetch_filtered_weekday():
                            return slots_service.get_available_slots_filtered(
                                company_id=company_id,
                                weekday_name=weekday_name,
                                limit=search_limit,
                                agenda_id=agenda_id
                            )
                        weekday_slots = await asyncio.to_thread(_fetch_filtered_weekday)

                        logger.critical(f"[WEEKDAY_DEBUG] get_available_slots_filtered returned: {len(weekday_slots) if isinstance(weekday_slots, list) else 'not_list'} items")
                        if weekday_slots:
                            logger.critical(f"[WEEKDAY_DEBUG] First few slots: {weekday_slots[:3] if isinstance(weekday_slots, list) else weekday_slots}")
                        else:
                            logger.critical(f"[WEEKDAY_DEBUG] NO WEEKDAY SLOTS FOUND! Checking why...")
                        all_slots.extend(weekday_slots)

                        for period in time_periods:
                            def _fetch_period_slots(p=period):
                                return slots_service.get_available_slots_filtered(
                                    company_id=company_id,
                                    weekday_name=weekday_name,
                                    time_period=p,
                                    limit=search_limit // 2,
                                    agenda_id=agenda_id
                                )
                            period_slots = await asyncio.to_thread(_fetch_period_slots)
                            all_slots.extend(period_slots)

                    elif time_periods:
                        for period in time_periods:
                            def _fetch_period_only(p=period):
                                return slots_service.get_available_slots_filtered(
                                    company_id=company_id,
                                    time_period=p,
                                    limit=search_limit,
                                    agenda_id=agenda_id
                                )
                            period_slots = await asyncio.to_thread(_fetch_period_only)
                            all_slots.extend(period_slots)

                # Use generic search for fallback cases (GENERIC FOR ALL SERVICES)
                if not all_slots:
                    logger.warning(f"[FallbackStrategy] Primary search returned 0 slots. Active Service: {type(slots_service).__name__}")

                    # --- Service-Agnostic Fallback Logic ---

                    # 1. Decide on fallback method based on service capabilities
                    fallback_method = None
                    is_legacy_service = not hasattr(slots_service, 'get_available_slots_from_database')

                    # Strategy 1: Relax Time Constraint (Same day, any time)
                    if weekday_name and time_periods:
                        logger.info(f"[FallbackStrategy] Attempting Strategy 1: Relax Time Constraint (keep {weekday_name}, ignore {time_periods})")

                        def _fetch_fallback_1():
                            if is_legacy_service:
                                return slots_service.get_available_slots_filtered(
                                    company_id=company_id,
                                    weekday_name=weekday_name,
                                    time_period=None, # Relaxed
                                    limit=10,
                                    agenda_id=agenda_id
                                )
                            else:
                                return slots_service.get_available_slots_from_database(
                                    limit=10,
                                    weekday_name=weekday_name,
                                    time_period=None,
                                    day_type=None
                                )

                        fallback_slots = await asyncio.to_thread(_fetch_fallback_1)
                        if fallback_slots:
                            for s in fallback_slots:
                                # Ensure metadata dict exists
                                if 'metadata' not in s: s['metadata'] = {}
                                s['metadata']['is_fallback'] = True
                                s['metadata']['fallback_reason'] = f"Relaxed time constraint (found for {weekday_name})"
                            all_slots.extend(fallback_slots)
                            logger.info(f"[FallbackStrategy] Strategy 1 success: found {len(fallback_slots)} slots")

                    # Strategy 2: Broad Search (Next 7 days/General)
                    if not all_slots:
                        logger.info(f"[FallbackStrategy] Attempting Strategy 2: Broad Search (Next available)")

                        def _fetch_fallback_2():
                            if is_legacy_service:
                                # Legacy service: "None" parameters usually trigger default/broad search or next available
                                return slots_service.get_available_slots_filtered(
                                    company_id=company_id,
                                    weekday_name=None, # Relaxed
                                    time_period=None,  # Relaxed
                                    limit=10,
                                    agenda_id=agenda_id
                                )
                            else:
                                return slots_service.get_available_slots_from_database(
                                    limit=10,
                                    weekday_name=None,
                                    time_period=None,
                                    day_type=None
                                )

                        fallback_slots = await asyncio.to_thread(_fetch_fallback_2)
                        if fallback_slots:
                            for s in fallback_slots:
                                if 'metadata' not in s: s['metadata'] = {}
                                s['metadata']['is_fallback'] = True
                                s['metadata']['fallback_reason'] = "No slots found for specific request. Showing next available."
                            all_slots.extend(fallback_slots)
                            logger.info(f"[FallbackStrategy] Strategy 2 success: found {len(fallback_slots)} slots")

                    # Only use legacy SlotsService fallback if still no slots after strategies
                    if not all_slots and is_legacy_service:
                        # Fallback to SlotsService for testing
                        logger.critical(f"[FALLBACK_DEBUG] Using SlotsService fallback with days_ahead={days_ahead}, limit={search_limit}")

                        def _fetch_fallback_slots():
                            return slots_service.get_available_slots(
                                company_id=company_id,
                                limit=search_limit,
                                days_ahead=days_ahead,
                                agenda_id=agenda_id
                            )
                        generic_slots = await asyncio.to_thread(_fetch_fallback_slots)

                        logger.critical(f"[FALLBACK_DEBUG] Generic slots returned: {len(generic_slots) if isinstance(generic_slots, list) else 'not_list'} items")
                        all_slots.extend(generic_slots if isinstance(generic_slots, list) else [])

                # NOVO: Filter by specific date if provided by LLM
                from datetime import datetime, timedelta
                today = datetime.now().date()

                if specific_date:
                    # LLM provided a specific date (e.g., "17/09/2025" for tomorrow)
                    logger.critical(f"[SPECIFIC_DATE_FILTER] LLM provided specific_date: {specific_date}")
                    logger.critical(f"[DEBUG_DATE_FORMAT] Total slots before filter: {len(all_slots)}")

                    specific_filtered_slots = []
                    for i, slot in enumerate(all_slots):
                        slot_str = slot["slot"] if isinstance(slot, dict) and "slot" in slot else slot
                        if isinstance(slot_str, str) and " " in slot_str:
                            date_part = slot_str.split(" ")[0]  # "dd/mm/yyyy"
                            # Log primeiros 3 slots para debug
                            if i < 3:
                                logger.critical(f"[DEBUG_DATE] Slot #{i}: '{slot_str}' → date_part='{date_part}' vs specific_date='{specific_date}'")

                            if date_part == specific_date:
                                specific_filtered_slots.append(slot)
                                logger.debug(f"[SPECIFIC_DATE] KEPT: {slot_str} matches {specific_date}")
                            else:
                                logger.debug(f"[SPECIFIC_DATE] FILTERED: {slot_str} doesn't match {specific_date}")

                    all_slots = specific_filtered_slots
                    logger.critical(f"[SPECIFIC_DATE_RESULT] Filtered to {len(specific_filtered_slots)} slots for date {specific_date}")

                else:
                    # Original filtering logic when no specific date
                    # CRITICAL FIX: Always filter out TODAY'S appointments (12/09/2025 issue)
                    minimum_date = today + timedelta(days=1)  # Tomorrow at minimum

                    # Apply additional offset if specified
                    if days_offset > 0:
                        cutoff_date_obj = today + timedelta(days=days_offset)
                        if cutoff_date_obj > minimum_date:
                            minimum_date = cutoff_date_obj

                    logger.critical(f"[DATE_FILTER_FIX] Filtering out TODAY ({today}) - minimum date: {minimum_date}")

                    date_filtered_slots = []
                    for slot in all_slots:
                        slot_str = slot["slot"] if isinstance(slot, dict) and "slot" in slot else slot
                        if isinstance(slot_str, str) and " " in slot_str:
                            date_part = slot_str.split(" ")[0]  # "dd/mm/yyyy"
                            try:
                                # Convert dates to datetime objects for proper comparison
                                slot_date = datetime.strptime(date_part, "%d/%m/%Y").date()

                                # CRITICAL: Filter out same-day appointments
                                if slot_date >= minimum_date:
                                    date_filtered_slots.append(slot)
                                    logger.debug(f"[DATE_FILTER_FIX] KEPT: {slot_str} (>= {minimum_date})")
                                else:
                                    logger.debug(f"[DATE_FILTER_FIX] FILTERED: {slot_str} (< {minimum_date}) - same day blocked")
                            except:
                                # Keep slot if date comparison fails
                                date_filtered_slots.append(slot)
                                logger.warning(f"[DATE_FILTER_FIX] Date comparison failed for {slot_str}, keeping slot")

                    all_slots = date_filtered_slots
                    logger.critical(f"[DATE_FILTER_FIX_RESULT] Filtered from original to {len(date_filtered_slots)} slots (blocked same-day appointments)")

                # NEW: Apply time restrictions filtering (depois das X)
                if time_restrictions.get("type") == "after" and time_restrictions.get("min_time"):
                    min_time = time_restrictions["min_time"]
                    logger.info(f"[TimeRestriction] Filtering slots after {min_time}")

                    filtered_slots = []
                    all_slots_count_before = len(all_slots)
                    for slot in all_slots:
                        slot_str = slot["slot"] if isinstance(slot, dict) and "slot" in slot else slot
                        if isinstance(slot_str, str) and " " in slot_str:
                            time_part = slot_str.split(" ")[1]  # "HH:MM"
                            try:
                                # Compare times (HH:MM format)
                                logger.critical(f"[TIME_DEBUG] Comparing '{time_part}' >= '{min_time}'")
                                if time_part >= min_time:
                                    filtered_slots.append(slot)
                                    # logger.debug(f"[TimeRestriction] KEPT: {slot_str} (>= {min_time})")
                                else:
                                    logger.critical(f"[TIME_DEBUG] FILTERED: '{time_part}' < '{min_time}'")
                            except:
                                # Keep slot if time comparison fails
                                filtered_slots.append(slot)
                                logger.error(f"[TIME_DEBUG] Exception comparing time, keeping slot")

                    all_slots = filtered_slots
                    logger.critical(f"[TIME_FILTER_RESULT] Filtered from {all_slots_count_before} to {len(all_slots)} slots")


                # RELAXED LOGIC: Simply return all valid filtered slots up to the limit
                # Removed "Smart selection" that truncated list to 2 items artificially


                # RELAXED LOGIC: Simply return all valid filtered slots up to the limit
                if urgency == "tomorrow_and_dayafter":
                     logger.info(f"[TOMORROW_DAYAFTER] Returning all slots found for next 3 days")
                     # No special logic needed, simple search covers it

                slots = all_slots[:search_limit]
                logger.info(f"[RELAXED_SELECTION] Returning {len(slots)} slots (limit={search_limit})")


                logger.critical(f"[SMART_SELECTION] Selected {len(slots)} slots")

                if not slots:
                    logger.critical(f"[AGGRESSIVE_FALLBACK] specific filters resulted in 0 slots. Triggering 'Last Resort' broad search.")

                    # --- LAST RESORT FALLBACK ---
                    # Search broadly for the next 7 days
                    def _fetch_last_resort():
                         return slots_service.get_available_slots_filtered(
                             company_id=company_id,
                             limit=50,  # Get ALL available slots (requested by user)
                             weekday_name=None,
                             time_period=None,
                             agenda_id=agenda_id
                         )

                    last_resort_slots = await asyncio.to_thread(_fetch_last_resort)

                    if last_resort_slots:
                        # LOGIC: Return ALL found slots (previously limited to 2)
                        slots = last_resort_slots
                        logger.critical(f"[AGGRESSIVE_FALLBACK] Found {len(last_resort_slots)} slots, returning ALL for suggestion.")

                        # Build message: "I didn't find [X], but I found [Y]"
                        filter_parts = []
                        if weekday_name: filter_parts.append(f"no dia {weekday_name}")
                        if time_periods:
                             period_names = {"manha": "de manhã", "tarde": "à tarde", "noite": "à noite"}
                             period_str = " ou ".join([period_names.get(p, p) for p in time_periods])
                             filter_parts.append(period_str)
                        if urgency in ["today", "tomorrow"]: filter_parts.append(f"para {urgency}")

                        not_found_msg = f"Não encontrei horários disponíveis {' '.join(filter_parts)}." if filter_parts else "Não há horários disponíveis com esses filtros."

                        # Construct a suggestive message
                        first_slot_str = slots[0]["slot"] if isinstance(slots[0], dict) else slots[0]
                        specific_message = f"{not_found_msg} Mas tenho horários disponíveis a partir de {first_slot_str.split(' ')[0]}. Veja as opções abaixo."

                        # Continue to normal flow to format and return these slots
                    else:
                        # Truly no slots even broadly
                        logger.critical(f"[TOOL_RESULT] NO SLOTS EVEN WARNING WITH FALLBACK")
                        return {
                            "available_slots": [],
                            "message": "Não há horários disponíveis em nenhum dia próximo."
                        }

                # Skip complex grouping - we now return exactly 2 slots maximum

                # SIMPLIFIED: Build concise response with exactly 2 slots
                # SIMPLIFIED: Build concise response with period context
                def format_slot(slot_str):
                    """Convert slot string to verbose natural language format for TTS"""
                    if " " in slot_str:
                        date_part, time_part = slot_str.split(" ", 1)
                        try:
                            # Helper for number to text conversion (0-59)
                            nums_0_19 = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez",
                                        "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
                            tens = ["", "", "vinte", "trinta", "quarenta", "cinquenta"]

                            def num_to_text(n):
                                if 0 <= n <= 19: return nums_0_19[n]
                                if 20 <= n <= 59:
                                    t = n // 10
                                    u = n % 10
                                    return f"{tens[t]} e {nums_0_19[u]}" if u > 0 else tens[t]
                                return str(n)

                            def year_to_text(y):
                                # Simplified for 2024-2030 range
                                if 2000 <= y < 2100:
                                    rem = y - 2000
                                    if rem == 0: return "dois mil"
                                    if rem < 20: return f"dois mil e {nums_0_19[rem]}"
                                    t = rem // 10
                                    u = rem % 10
                                    rem_text = f"{tens[t]} e {nums_0_19[u]}" if u > 0 else tens[t]
                                    return f"dois mil e {rem_text}"
                                return str(y)

                            date_obj = datetime.strptime(date_part, "%d/%m/%Y")

                            # Mapeamento de dias e meses
                            weekdays = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
                            months = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                                     "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

                            weekday = weekdays[date_obj.weekday()]
                            day = date_obj.day
                            day_text = num_to_text(day)
                            month = months[date_obj.month - 1]
                            year = date_obj.year
                            year_text = year_to_text(year)

                            # Format time
                            hour = int(time_part.split(":")[0])
                            minute = int(time_part.split(":")[1])

                            hour_text = num_to_text(hour)
                            minute_text = num_to_text(minute)

                            # Period logic
                            if hour < 12: period = "da manhã"
                            elif hour < 18: period = "da tarde"
                            else: period = "da noite"

                            # Time string construction
                            # Special handling: "uma hora" instead of "um horas"
                            if hour == 1: hour_text = "uma"
                            elif hour == 2: hour_text = "duas"

                            time_str = f"{hour_text} horas"
                            if hour == 1: time_str = "uma hora"

                            if minute > 0:
                                time_str += f" e {minute_text} minutos"
                                if minute == 30: time_str = time_str.replace("trinta minutos", "meia")

                            # Full verbose string matching user preference for "data discursiva"
                            return f"{weekday}, dia {day_text} de {month} de {year_text} às {time_str} {period}"
                        except Exception as e:
                            logger.error(f"Error formatting slot {slot_str}: {e}")
                            return f"{date_part} às {time_part}"
                    return slot_str

                response_lines = []

                # Return raw slots data - let agent create natural conversation
                # Return raw slots data - let agent create natural conversation
                if slots:
                    formatted_slots = []
                    for s in slots:
                        s_val = s["slot"] if isinstance(s, dict) and "slot" in s else s
                        formatted_slots.append(format_slot(s_val))

                    # Join all slots with pipe separator
                    slots_str = " | ".join(formatted_slots)

                    # INSTRUCTION INJECTION: Guide the agent to limit suggestions in speech
                    instruction = "\n\n[INSTRUÇÃO DO SISTEMA: Selecione mentalmente apenas 2 (duas) melhores opções para oferecer ao cliente. NÃO leia a lista completa de horários.]"

                    final_response = f"SLOTS_DISPONÍVEIS: {slots_str}{instruction}"
                else:
                    final_response = "SEM_HORÁRIOS_DISPONÍVEIS"

                logger.critical(f"[RESPONSE_BUILT] Final response constructed: '{final_response}'")

                # SIMPLIFIED DEBUGGING: Log the complete flow
                logger.info(f"[SIMPLE_FLOW] Initial slots: {len(all_slots)}, Final slots: {len(slots)}")
                if slots:
                    logger.info(f"[SIMPLE_FLOW] Selected slots: {[slot['slot'] if isinstance(slot, dict) and 'slot' in slot else slot for slot in slots]}")

                # Enhanced logging for new features
                logger.info(f"[ToolResponse] Returning to agent: {final_response[:200]}...")
                logger.info(f"[ToolResponse] Enhanced semantics: weekday={weekday_name}, periods={time_periods}")
                logger.info(f"[ToolResponse] NEW: urgency={urgency}, time_restrictions={time_restrictions}")
                logger.info(f"[ToolResponse] Search params: days_ahead={days_ahead}, limit={search_limit}")
                logger.info(f"[ToolResponse] Results: {len(slots)} slots")

                logger.critical(f"[TOOL_EXIT] Returning response length: {len(final_response)} chars, first 100 chars: '{final_response[:100]}'")

                # NEW: Enhanced tracing - log results
                logger.info(f"[TRACE] Success - slots_found: {len(slots)}, response_length: {len(final_response)}")

                # Update structured context if available
                if structured_context:
                    # Save suggested slots to context for time interpretation
                    if slots:
                        # Extract just the time strings from slots
                        slot_times = []
                        for slot in slots:
                            if isinstance(slot, dict) and 'slot' in slot:
                                # Format: "DD/MM/YYYY HH:MM" - extract just HH:MM
                                slot_str = slot['slot']
                                if ' ' in slot_str:
                                    time_part = slot_str.split(' ')[1]  # Get HH:MM part
                                    slot_times.append(time_part)
                            elif isinstance(slot, str) and ' ' in slot:
                                time_part = slot.split(' ')[1]  # Get HH:MM part
                                slot_times.append(time_part)

                        # Update suggested_slots in context
                        structured_context.suggested_slots = slot_times
                        logger.info(f"[CONTEXT_UPDATE] Saved suggested slots to context: {slot_times}")

                    # Advance stage if we found slots and this was a scheduling query
                    if slots and structured_context.current_stage in ["etapa_1", "etapa_2", "etapa_3"]:
                        structured_context.advance_stage(
                            "etapa_4_agendamento",
                            f"found {len(slots)} slots",
                            f"preferred_date={preferred_date}, preferred_time={preferred_time}"
                        )

                    # Log successful slot search
                    logger.info(
                        f"[CONTEXT_UPDATE] Updated customer context after slot search",
                        extra={
                            "event": "context_updated_after_tool",
                            "tool": "get_available_slots",
                            "company_id": context.context.company_id,
                            "phone": context.context.phone,
                            "slots_found": len(slots),
                            "new_stage": structured_context.current_stage,
                            "conversation_step": structured_context.conversation_step
                        }
                    )

                return final_response

            except Exception as e:
                # NEW: Enhanced tracing for errors
                logger.critical(f"[TRACE] Error - type: {type(e).__name__}, message: {str(e)}")

                logger.critical(f"[TOOL_EXCEPTION] Error in get_available_slots: {e}")
                import traceback
                logger.critical(f"[TOOL_EXCEPTION] Traceback: {traceback.format_exc()}")

                # Log error with structured context
                if structured_context:
                    logger.error(
                        f"[TOOL_ERROR] get_available_slots failed with context",
                        extra={
                            "event": "tool_error",
                            "tool": "get_available_slots",
                            "company_id": context.context.company_id,
                            "phone": context.context.phone,
                            "error": str(e),
                            "current_stage": structured_context.current_stage,
                            "conversation_step": structured_context.conversation_step
                        }
                    )

            return "Erro ao consultar horários disponíveis. Tente novamente."

    # REMOVED schedule_appointment - use process_appointment_confirmation instead
    # Having two similar tools was confusing the AI model

    return [get_available_slots]

def _get_day_info(date_str: str) -> str:
    """Get day of week info for date string"""
    try:
        date_obj = datetime.strptime(date_str, "%d/%m/%Y")
        days = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        return days[date_obj.weekday()]
    except:
        return ""
