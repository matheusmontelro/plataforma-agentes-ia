"""
Database Manager for Agents SDK
Handles database-based slot management and tool integration
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from ..services.database_scheduling_service import DatabaseSchedulingService
from ..tools.slots_service import SlotsService

logger = logging.getLogger(__name__)


class DatabaseAgentsManager:
    """
    Manager that integrates database-based scheduling into agents workflow
    Replaces Redis-based approach with database operations
    """

    def __init__(self, db: Session, company_id: int, phone: str):
        self.db = db
        self.company_id = company_id
        self.phone = phone
        self.scheduling_service = DatabaseSchedulingService(db, company_id)
        self.slots_service = SlotsService(db)

        logger.info(f"[DatabaseAgentsManager] Initialized for company {company_id}, phone {phone}")

    def handle_get_available_slots(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle get_available_slots tool call using database

        Args:
            request_data: Tool request parameters

        Returns:
            Dict with available slots from database
        """
        try:
            logger.info(f"[DatabaseAgentsManager] Getting available slots for company {self.company_id}")

            # Get slots from database
            available_slots = self.scheduling_service.get_available_slots_from_database(limit=10)

            if not available_slots:
                return {
                    "available_slots": [],
                    "message": "Não há horários disponíveis no momento. Por favor, entre em contato para verificar outras opções.",
                    "total_count": 0
                }

            # Format response for LLM
            return {
                "available_slots": available_slots,
                "message": f"Encontrei {len(available_slots)} horários disponíveis nos próximos dias.",
                "total_count": len(available_slots),
                "formatted_slots": self._format_slots_for_llm(available_slots)
            }

        except Exception as e:
            logger.error(f"[DatabaseAgentsManager] Error getting slots: {e}")
            return {
                "available_slots": [],
                "error": "Erro ao consultar horários disponíveis",
                "message": "Houve um problema técnico. Por favor, tente novamente ou entre em contato conosco."
            }

    def handle_schedule_appointment(self, scheduling_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle schedule_appointment tool call using database

        Args:
            scheduling_data: Appointment data

        Returns:
            Dict with scheduling result
        """
        try:
            slot_datetime = scheduling_data.get("slot_datetime", "")
            customer_name = scheduling_data.get("customer_name", "")
            customer_phone = scheduling_data.get("customer_phone", self.phone)

            logger.info(f"[DatabaseAgentsManager] Scheduling appointment: {slot_datetime} for {customer_name}")

            if not slot_datetime or not customer_name:
                return {
                    "success": False,
                    "message": "Dados incompletos para agendamento. Preciso do horário e seu nome completo."
                }

            # Reserve the slot in database
            reservation_success = self.slots_service.reserve_slot(
                company_id=self.company_id,
                slot_datetime=slot_datetime,
                customer_info={
                    "name": customer_name,
                    "phone": customer_phone,
                    "service_type": scheduling_data.get("service_type", "Consulta"),
                    "notes": scheduling_data.get("notes", ""),
                    "scheduled_via": "agents_sdk"
                }
            )

            if reservation_success:
                # Also create in main agendamentos table for compatibility
                self._create_main_appointment_record(scheduling_data)

                return {
                    "success": True,
                    "message": f"✅ Agendamento confirmado para {slot_datetime}! Aguardamos você na empresa.",
                    "appointment_details": {
                        "customer_name": customer_name,
                        "slot_datetime": slot_datetime,
                        "service_type": scheduling_data.get("service_type", "Consulta"),
                        "company_id": self.company_id
                    }
                }
            else:
                return {
                    "success": False,
                    "message": "Este horário não está mais disponível. Por favor, escolha outro horário da lista."
                }

        except Exception as e:
            logger.error(f"[DatabaseAgentsManager] Error scheduling appointment: {e}")
            return {
                "success": False,
                "message": "Erro ao processar agendamento. Tente novamente ou entre em contato conosco.",
                "error": str(e)
            }

    def _format_slots_for_llm(self, slots: List[str]) -> str:
        """
        Format slots in a LLM-friendly way

        Args:
            slots: List of slot strings in "dd/mm/yyyy HH:MM" format

        Returns:
            Formatted string for LLM consumption
        """
        if not slots:
            return "Nenhum horário disponível"

        try:
            # Group by date
            date_groups = {}

            for slot in slots[:8]:  # Limit to first 8 slots
                try:
                    date_part, time_part = slot.split(" ")
                    if date_part not in date_groups:
                        date_groups[date_part] = []
                    date_groups[date_part].append(time_part)
                except ValueError:
                    continue

            # Format output
            formatted_lines = []

            for date_str, times in sorted(date_groups.items()):
                try:
                    # Parse date for better formatting
                    dt = datetime.strptime(date_str, "%d/%m/%Y")
                    weekday = dt.strftime("%A")

                    # Translate weekday to Portuguese
                    weekdays_pt = {
                        "Monday": "Segunda-feira",
                        "Tuesday": "Terça-feira",
                        "Wednesday": "Quarta-feira",
                        "Thursday": "Quinta-feira",
                        "Friday": "Sexta-feira",
                        "Saturday": "Sábado",
                        "Sunday": "Domingo"
                    }

                    weekday_pt = weekdays_pt.get(weekday, weekday)

                    # Get day context
                    today = datetime.now().date()
                    days_diff = (dt.date() - today).days

                    if days_diff == 0:
                        day_context = "Hoje"
                    elif days_diff == 1:
                        day_context = "Amanhã"
                    elif days_diff == 2:
                        day_context = "Depois de amanhã"
                    else:
                        day_context = f"Daqui a {days_diff} dias"

                    formatted_lines.append(f"{weekday_pt} ({date_str}) - {day_context}:")

                    # Add times
                    times_formatted = ", ".join(sorted(times))
                    formatted_lines.append(f"  {times_formatted}")

                except ValueError:
                    # Fallback formatting
                    times_formatted = ", ".join(sorted(times))
                    formatted_lines.append(f"{date_str}: {times_formatted}")

            return "\n".join(formatted_lines)

        except Exception as e:
            logger.error(f"[DatabaseAgentsManager] Error formatting slots: {e}")
            # Fallback to simple format
            return "\n".join(slots[:6])

    def _create_main_appointment_record(self, scheduling_data: Dict[str, Any]) -> bool:
        """
        Create appointment record in main agendamentos table for system compatibility

        Args:
            scheduling_data: Appointment data

        Returns:
            True if created successfully
        """
        try:
            from sqlalchemy import text

            # Parse datetime
            slot_datetime = scheduling_data.get("slot_datetime", "")
            dt = datetime.strptime(slot_datetime, "%d/%m/%Y %H:%M")

            # Insert into agendamentos table
            self.db.execute(text("""
                INSERT INTO agendamentos (
                    company_id,
                    nome_cliente,
                    telefone_cliente,
                    consulta_data,
                    servico,
                    status,
                    origem,
                    notas,
                    created_at
                ) VALUES (
                    :company_id,
                    :nome_cliente,
                    :telefone_cliente,
                    :consulta_data,
                    :servico,
                    'agendado',
                    'agents_sdk_database',
                    :notas,
                    NOW()
                )
            """), {
                "company_id": self.company_id,
                "nome_cliente": scheduling_data.get("customer_name", ""),
                "telefone_cliente": scheduling_data.get("customer_phone", self.phone),
                "consulta_data": dt,
                "servico": scheduling_data.get("service_type", "Consulta"),
                "notas": scheduling_data.get("notes", "Agendado via Agents SDK (Database)")
            })

            self.db.commit()
            logger.info(f"[DatabaseAgentsManager] Created appointment record in main table")
            return True

        except Exception as e:
            logger.error(f"[DatabaseAgentsManager] Error creating main appointment record: {e}")
            self.db.rollback()
            return False

    def get_company_stats(self) -> Dict[str, Any]:
        """Get current company slots statistics"""
        return self.slots_service.get_slots_stats(self.company_id)

    def refresh_company_slots(self) -> int:
        """Manually refresh slots for this company"""
        return self.scheduling_service.fetch_and_store_availabilities()

    def handle_suggest_available_slots(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle suggest_available_slots tool with LLM-powered intelligent ranking
        """
        try:
            logger.info(f"[DatabaseAgentsManager] LLM-powered slot suggestions for company {self.company_id}")

            # Get all available slots with metadata
            from sqlalchemy import text
            result = self.db.execute(text("""
                SELECT slot_date, slot_time, slot_metadata
                FROM company_slots
                WHERE company_id = :company_id
                AND is_available = true
                AND slot_date >= CURRENT_DATE
                ORDER BY slot_date, slot_time
                LIMIT 15
            """), {"company_id": self.company_id}).fetchall()

            if not result:
                return {
                    "suggestions": [],
                    "total_available": 0,
                    "message": "Não há horários disponíveis no momento.",
                    "reasoning": "Nenhum slot encontrado na agenda",
                    "success": True
                }

            # Use LLM to intelligently rank and suggest slots
            suggestions = self._llm_rank_slots(result, request_data)

            # Generate response
            max_suggestions = request_data.get("max_suggestions", 2)
            top_suggestions = suggestions[:max_suggestions]

            if top_suggestions:
                if len(top_suggestions) == 1:
                    message = f"Encontrei o horário perfeito: {top_suggestions[0]['human_description']}"
                else:
                    message = f"Selecionei os {len(top_suggestions)} melhores horários para você:"

                reasoning = f"Analisado por IA considerando suas preferências"
            else:
                message = "Não consegui encontrar horários adequados."
                reasoning = "IA não encontrou matches satisfatórios"

            return {
                "suggestions": top_suggestions,
                "total_available": len(result),
                "message": message,
                "reasoning": reasoning,
                "success": True
            }

        except Exception as e:
            logger.error(f"[DatabaseAgentsManager] Error in LLM slot suggestions: {e}")
            return {
                "suggestions": [],
                "total_available": 0,
                "message": "Erro ao processar sugestões inteligentes.",
                "reasoning": f"Erro técnico: {str(e)}",
                "success": False
            }

    def _llm_rank_slots(self, slots_data, request_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Enhanced intelligent slot ranking using contextual analysis (NO LLM)"""

        try:
            logger.info(f"[DatabaseAgentsManager] Enhanced ranking for {len(slots_data)} slots")

            # Extract semantic preferences from request
            preferences = self._extract_semantic_preferences(request_data)

            # Get company scheduling patterns for context
            company_patterns = self._get_company_scheduling_patterns()

            # Score and rank all slots
            scored_slots = []
            for row in slots_data:
                metadata = row.slot_metadata or {}
                score = self._calculate_enhanced_slot_score(row, metadata, preferences, company_patterns)

                date_str = row.slot_date.strftime("%d/%m/%Y")
                time_str = row.slot_time.strftime("%H:%M")

                scored_slots.append({
                    "slot_datetime": f"{date_str} {time_str}",
                    "score": score,
                    "metadata": metadata,
                    "slot_data": row
                })

            # Sort by score (highest first)
            scored_slots.sort(key=lambda x: x["score"], reverse=True)

            # Create final suggestions
            max_suggestions = request_data.get("max_suggestions", 2)
            suggestions = []

            for i, slot_info in enumerate(scored_slots[:max_suggestions]):
                metadata = slot_info["metadata"]
                suggestions.append({
                    "slot_datetime": slot_info["slot_datetime"],
                    "human_description": self._generate_human_description(metadata),
                    "day_type": metadata.get("day_type", ""),
                    "time_period": metadata.get("time_period", ""),
                    "is_weekend": metadata.get("is_weekend", False),
                    "relative_days": metadata.get("relative_days", 0),
                    "confidence_score": round(slot_info["score"], 2),
                    "reasoning": self._generate_smart_reasoning(slot_info, preferences, i+1)
                })

            logger.info(f"[DatabaseAgentsManager] Enhanced ranking completed: {len(suggestions)} suggestions")
            return suggestions

        except Exception as e:
            logger.error(f"[DatabaseAgentsManager] Enhanced ranking failed, falling back to rule-based: {e}")
            # Fallback to original rule-based ranking
            return self._fallback_rule_based_ranking(slots_data, request_data)

    def _create_ranking_prompt(self, slots: List[Dict], request: Dict[str, Any]) -> str:
        """Create optimized prompt for LLM slot ranking"""

        import json

        # Extract request context
        preferred_period = request.get("preferred_period", "")
        preferred_day = request.get("preferred_day", "")
        urgent = request.get("urgent", False)
        flexible = request.get("flexible", True)
        max_suggestions = request.get("max_suggestions", 2)

        # Format current time context
        now = datetime.now()
        current_context = f"Hoje é {now.strftime('%A, %d/%m/%Y às %H:%M')} (referência temporal)"

        prompt = f"""
TAREFA: Selecionar os {max_suggestions} melhores horários para agendamento de serviços.

CONTEXTO TEMPORAL:
{current_context}

PREFERÊNCIAS DO CLIENTE:
- Período preferido: "{preferred_period}"
- Dia preferido: "{preferred_day}"
- Urgente: {urgent}
- Flexível: {flexible}

HORÁRIOS DISPONÍVEIS:
{json.dumps(slots, indent=2, ensure_ascii=False)}

INSTRUÇÕES:
1. Analise as preferências do cliente em linguagem natural
2. Considere o contexto temporal de cada slot
3. Priorize matches exatos, mas seja inteligente com alternativas
4. Se urgente: priorize proximidade temporal
5. Se não urgente: considere conveniência (dias úteis, horários populares)

FORMATO DE RESPOSTA (JSON válido):
{{
  "top_suggestions": [
    {{
      "slot_datetime": "DD/MM/YYYY HH:MM",
      "confidence_score": 0.95,
      "reasoning": "Explicação clara do por que foi escolhido",
      "human_description": "Segunda-feira amanhã de manhã"
    }}
  ],
  "analysis": "Breve análise das preferências vs disponibilidade"
}}

Seja preciso e considerado na seleção. Qualidade > quantidade.
"""
        return prompt

    def _parse_llm_ranking_response(self, llm_response: str, original_slots: List[Dict]) -> List[Dict[str, Any]]:
        """Parse LLM response into structured suggestions"""

        try:
            import json
            import re

            # Extract JSON from LLM response
            json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
            if json_match:
                llm_data = json.loads(json_match.group())

                suggestions = []
                for llm_suggestion in llm_data.get("top_suggestions", []):
                    slot_datetime = llm_suggestion.get("slot_datetime", "")

                    # Find corresponding slot metadata
                    for slot in original_slots:
                        if slot["slot_datetime"] == slot_datetime:
                            suggestions.append({
                                "slot_datetime": slot_datetime,
                                "human_description": llm_suggestion.get("human_description", slot.get("weekday_name", "")),
                                "day_type": slot.get("day_type", ""),
                                "time_period": slot.get("time_period", ""),
                                "is_weekend": slot.get("is_weekend", False),
                                "relative_days": slot.get("relative_days", 0),
                                "confidence_score": llm_suggestion.get("confidence_score", 0.8),
                                "reasoning": llm_suggestion.get("reasoning", "Selecionado por IA")
                            })
                            break

                return suggestions

        except Exception as e:
            logger.error(f"[DatabaseAgentsManager] Error parsing LLM response: {e}")

        # Fallback to first 2 slots if parsing fails
        return self._fallback_rule_based_ranking(original_slots, {})

    def _fallback_rule_based_ranking(self, slots_data, request_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fallback rule-based ranking if LLM fails"""

        suggestions = []
        max_suggestions = request_data.get("max_suggestions", 2)

        for row in slots_data[:max_suggestions]:
            metadata = row.slot_metadata or {} if hasattr(row, 'slot_metadata') else {}
            date_str = row.slot_date.strftime("%d/%m/%Y")
            time_str = row.slot_time.strftime("%H:%M")

            suggestions.append({
                "slot_datetime": f"{date_str} {time_str}",
                "human_description": self._generate_human_description(metadata),
                "day_type": metadata.get("day_type", ""),
                "time_period": metadata.get("time_period", ""),
                "is_weekend": metadata.get("is_weekend", False),
                "relative_days": metadata.get("relative_days", 0),
                "confidence_score": 0.6,  # Default fallback score
                "reasoning": "Sugestão baseada em proximidade temporal"
            })

        return suggestions

    def _calculate_slot_confidence(self, metadata: Dict[str, Any], request: Dict[str, Any]) -> float:
        """Calculate 0.0-1.0 confidence score for slot based on preferences"""

        confidence = 0.5  # Base score

        # Time period matching
        preferred_period = request.get("preferred_period", "")
        slot_period = metadata.get("time_period", "")

        if preferred_period in ["manha", "tarde", "noite"] and slot_period == preferred_period:
            confidence += 0.3

        # Day type matching
        slot_day_type = metadata.get("day_type", "")
        if preferred_period in ["hoje", "amanha", "semana_que_vem"] and slot_day_type == preferred_period:
            confidence += 0.4

        # Urgency bonus
        if request.get("urgent", False):
            relative_days = metadata.get("relative_days", 99)
            if relative_days == 0:  # Today
                confidence += 0.4
            elif relative_days == 1:  # Tomorrow
                confidence += 0.2

        # Proximity bonus (sooner is generally better)
        relative_days = metadata.get("relative_days", 99)
        if relative_days <= 7:
            proximity_bonus = (7 - relative_days) * 0.03
            confidence += proximity_bonus

        # Weekend handling
        is_weekend = metadata.get("is_weekend", False)
        if not request.get("urgent", False) and not is_weekend:
            confidence += 0.1  # Slight preference for weekdays

        return min(1.0, max(0.0, confidence))

    def _generate_human_description(self, metadata: Dict[str, Any]) -> str:
        """Generate human-readable description of the slot"""

        weekday = metadata.get("weekday_name", "")
        day_type = metadata.get("day_type", "")
        time_period = metadata.get("time_period", "")

        parts = []

        if weekday:
            parts.append(weekday)

        if day_type == "hoje":
            parts.append("hoje")
        elif day_type == "amanha":
            parts.append("amanhã")
        elif day_type == "depois_amanha":
            parts.append("depois de amanhã")
        elif day_type == "essa_semana":
            parts.append("ainda esta semana")
        elif day_type == "semana_que_vem":
            parts.append("semana que vem")

        if time_period == "manha":
            parts.append("de manhã")
        elif time_period == "tarde":
            parts.append("à tarde")
        elif time_period == "noite":
            parts.append("à noite")

        return " ".join(parts) if parts else "horário disponível"

    def _extract_semantic_preferences(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract semantic preferences from request using NLP patterns"""

        # Get raw text input if available
        user_input = request_data.get("user_input", "").lower()

        preferences = {
            "urgency_level": 0.0,  # 0.0 = not urgent, 1.0 = very urgent
            "time_flexibility": 1.0,  # 0.0 = very specific, 1.0 = very flexible
            "preferred_periods": [],  # ["manha", "tarde", "noite"]
            "preferred_days": [],     # ["hoje", "amanha", "semana_que_vem"]
            "preferred_weekdays": [], # ["segunda", "terca", etc.]
            "specific_times": [],     # ["09:00", "14:00", etc.]
            "avoid_weekend": False,
            "parsed_from_text": user_input != ""
        }

        # Extract from explicit request fields first
        if request_data.get("preferred_period"):
            period = request_data["preferred_period"].lower()
            if period in ["manha", "tarde", "noite"]:
                preferences["preferred_periods"].append(period)
            elif period in ["hoje", "amanha", "semana_que_vem"]:
                preferences["preferred_days"].append(period)

        if request_data.get("urgent", False):
            preferences["urgency_level"] = 0.8

        if not request_data.get("flexible", True):
            preferences["time_flexibility"] = 0.3

        # Semantic extraction from text
        if user_input:
            # Urgency patterns
            urgency_patterns = [
                "urgente", "o mais rápido", "assim que possível", "hoje mesmo",
                "emergência", "dor", "problema", "preciso hoje"
            ]
            for pattern in urgency_patterns:
                if pattern in user_input:
                    preferences["urgency_level"] = max(preferences["urgency_level"], 0.7)
                    break

            # Time period patterns
            period_patterns = {
                "manha": ["manhã", "manha", "cedo", "9h", "10h", "11h", "9:00", "10:00", "11:00"],
                "tarde": ["tarde", "14h", "15h", "16h", "17h", "14:00", "15:00", "16:00", "17:00"],
                "noite": ["noite", "18h", "19h", "20h", "18:00", "19:00", "20:00", "final do dia"]
            }

            for period, patterns in period_patterns.items():
                if any(p in user_input for p in patterns):
                    preferences["preferred_periods"].append(period)

            # Day patterns
            day_patterns = {
                "hoje": ["hoje", "hoje mesmo", "ainda hoje"],
                "amanha": ["amanhã", "amanha", "tomorrow"],
                "semana_que_vem": ["semana que vem", "próxima semana", "week"]
            }

            for day, patterns in day_patterns.items():
                if any(p in user_input for p in patterns):
                    preferences["preferred_days"].append(day)

            # Weekday patterns
            weekday_patterns = {
                "segunda": ["segunda", "monday"],
                "terca": ["terça", "terca", "tuesday"],
                "quarta": ["quarta", "wednesday"],
                "quinta": ["quinta", "thursday"],
                "sexta": ["sexta", "friday"],
                "sabado": ["sábado", "sabado", "saturday"],
                "domingo": ["domingo", "sunday"]
            }

            for weekday, patterns in weekday_patterns.items():
                if any(p in user_input for p in patterns):
                    preferences["preferred_weekdays"].append(weekday)

            # Flexibility patterns
            flexibility_patterns = [
                "qualquer horário", "tanto faz", "flexível", "qualquer dia",
                "qualquer coisa", "não tenho preferência"
            ]
            if any(p in user_input for p in flexibility_patterns):
                preferences["time_flexibility"] = 1.0

            # Specific time extraction (regex for HH:MM)
            import re
            time_matches = re.findall(r'\b([0-2]?[0-9]):([0-5][0-9])\b', user_input)
            for hour, minute in time_matches:
                preferences["specific_times"].append(f"{hour.zfill(2)}:{minute}")

        return preferences

    def _get_company_scheduling_patterns(self) -> Dict[str, Any]:
        """Get company scheduling patterns from historical data"""

        try:
            from sqlalchemy import text

            # Get popular time periods from last 3 months
            result = self.db.execute(text("""
                SELECT
                    EXTRACT(hour FROM slot_time) as hour,
                    EXTRACT(dow FROM slot_date) as weekday,
                    COUNT(*) as frequency
                FROM company_slots cs
                WHERE cs.company_id = :company_id
                AND cs.created_at >= NOW() - INTERVAL '3 months'
                AND cs.is_available = false  -- booked slots
                GROUP BY EXTRACT(hour FROM slot_time), EXTRACT(dow FROM slot_date)
                ORDER BY frequency DESC
                LIMIT 20
            """), {"company_id": self.company_id}).fetchall()

            popular_hours = [int(row.hour) for row in result[:5]] if result else [9, 14, 15, 16, 10]
            popular_weekdays = [int(row.weekday) for row in result[:3]] if result else [1, 2, 3]  # Mon, Tue, Wed

            return {
                "popular_hours": popular_hours,
                "popular_weekdays": popular_weekdays,
                "peak_morning": 9 in popular_hours or 10 in popular_hours,
                "peak_afternoon": 14 in popular_hours or 15 in popular_hours,
                "weekday_preference": len([w for w in popular_weekdays if w < 5]) > len([w for w in popular_weekdays if w >= 5])
            }

        except Exception as e:
            logger.warning(f"Could not get company patterns: {e}")
            return {
                "popular_hours": [9, 14, 15, 16, 10],
                "popular_weekdays": [1, 2, 3, 4, 5],  # Mon-Fri
                "peak_morning": True,
                "peak_afternoon": True,
                "weekday_preference": True
            }

    def _calculate_enhanced_slot_score(self, slot_row, metadata: Dict, preferences: Dict, company_patterns: Dict) -> float:
        """Calculate enhanced score for slot based on multiple factors"""

        base_score = 0.5

        # 1. TIME PERIOD MATCHING (30% weight)
        time_score = 0.0
        slot_hour = slot_row.slot_time.hour
        slot_period = metadata.get("time_period", "")

        # Direct period match
        if preferences["preferred_periods"]:
            if slot_period in preferences["preferred_periods"]:
                time_score += 0.4

        # Specific time match
        slot_time_str = slot_row.slot_time.strftime("%H:%M")
        if preferences["specific_times"]:
            if slot_time_str in preferences["specific_times"]:
                time_score += 0.5

        # Popular hour bonus
        if slot_hour in company_patterns["popular_hours"]:
            time_score += 0.1

        # 2. DAY TYPE MATCHING (25% weight)
        day_score = 0.0
        slot_day_type = metadata.get("day_type", "")
        relative_days = metadata.get("relative_days", 99)

        # Direct day type match
        if preferences["preferred_days"]:
            if slot_day_type in preferences["preferred_days"]:
                day_score += 0.4

        # Weekday preference
        slot_weekday = slot_row.slot_date.weekday()  # 0=Monday
        if preferences["preferred_weekdays"]:
            weekday_names = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
            if slot_weekday < len(weekday_names):
                slot_weekday_name = weekday_names[slot_weekday]
                if slot_weekday_name in preferences["preferred_weekdays"]:
                    day_score += 0.3

        # Popular weekday bonus
        if slot_weekday in company_patterns["popular_weekdays"]:
            day_score += 0.1

        # 3. URGENCY HANDLING (25% weight)
        urgency_score = 0.0
        urgency_level = preferences["urgency_level"]

        if urgency_level > 0.5:  # Urgent request
            if relative_days == 0:  # Today
                urgency_score += 0.5
            elif relative_days == 1:  # Tomorrow
                urgency_score += 0.3
            elif relative_days <= 3:  # This week
                urgency_score += 0.2
        else:  # Not urgent
            # Prefer reasonable timeframe (not too soon, not too far)
            if 1 <= relative_days <= 7:
                urgency_score += 0.3
            elif 8 <= relative_days <= 14:
                urgency_score += 0.2

        # 4. FLEXIBILITY BONUS (10% weight)
        flexibility_score = 0.0
        if preferences["time_flexibility"] > 0.7:
            # High flexibility - bonus for any reasonable slot
            if not metadata.get("is_weekend", False) and 9 <= slot_hour <= 17:
                flexibility_score += 0.2

        # 5. WEEKEND HANDLING (10% weight)
        weekend_score = 0.0
        is_weekend = metadata.get("is_weekend", False)
        if preferences.get("avoid_weekend", False) and not is_weekend:
            weekend_score += 0.2
        elif not preferences.get("avoid_weekend", False):
            weekend_score += 0.1  # Neutral

        # Calculate final weighted score
        final_score = (
            base_score +
            time_score * 0.30 +
            day_score * 0.25 +
            urgency_score * 0.25 +
            flexibility_score * 0.10 +
            weekend_score * 0.10
        )

        return min(1.0, max(0.0, final_score))

    def _generate_smart_reasoning(self, slot_info: Dict, preferences: Dict, rank: int) -> str:
        """Generate intelligent reasoning for slot selection"""

        metadata = slot_info["metadata"]
        score = slot_info["score"]

        reasons = []

        # Primary match reasons
        if preferences["preferred_periods"]:
            slot_period = metadata.get("time_period", "")
            if slot_period in preferences["preferred_periods"]:
                reasons.append(f"corresponde ao período '{slot_period}' preferido")

        if preferences["preferred_days"]:
            day_type = metadata.get("day_type", "")
            if day_type in preferences["preferred_days"]:
                reasons.append(f"atende à preferência '{day_type}'")

        # Urgency reasons
        if preferences["urgency_level"] > 0.5:
            relative_days = metadata.get("relative_days", 99)
            if relative_days <= 1:
                reasons.append("disponível rapidamente para caso urgente")
            elif relative_days <= 3:
                reasons.append("disponível em breve para sua necessidade")

        # Company pattern reasons
        if score > 0.7:
            reasons.append("horário popular e conveniente")
        elif score > 0.5:
            reasons.append("boa opção considerando disponibilidade")

        # Rank-based reasoning
        if rank == 1:
            primary = "Melhor opção"
        elif rank == 2:
            primary = "Alternativa recomendada"
        else:
            primary = f"{rank}ª opção"

        if reasons:
            return f"{primary}: {', '.join(reasons[:2])}"
        else:
            return f"{primary}: horário disponível conforme solicitado"

    def _generate_suggestion_reasoning(self, metadata: Dict[str, Any], request: Dict[str, Any], score: float) -> str:
        """Generate explanation for why this slot was suggested"""

        reasons = []

        # Period match
        preferred_period = request.get("preferred_period", "")
        if preferred_period in ["manha", "tarde", "noite"]:
            if metadata.get("time_period") == preferred_period:
                reasons.append(f"corresponde ao período '{preferred_period}' solicitado")

        # Day match
        if preferred_period in ["hoje", "amanha", "semana_que_vem"]:
            if metadata.get("day_type") == preferred_period:
                reasons.append(f"atende a preferência '{preferred_period}'")

        # Urgency
        if request.get("urgent") and metadata.get("relative_days", 99) <= 1:
            reasons.append("atende urgência")

        # Proximity
        relative_days = metadata.get("relative_days", 99)
        if relative_days == 0:
            reasons.append("disponível hoje")
        elif relative_days == 1:
            reasons.append("disponível amanhã")
        elif relative_days <= 3:
            reasons.append("próximo disponível")

        # High confidence
        if score >= 0.8:
            reasons.append("excelente match")
        elif score >= 0.6:
            reasons.append("bom match")

        if not reasons:
            return "horário disponível"

        return f"Sugerido: {', '.join(reasons[:3])}"

    def process_tool_call(self, tool_name: str, tool_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main method to process tool calls from agents
        """
        try:
            if tool_name == "get_available_slots":
                return self.handle_get_available_slots(tool_data)

            elif tool_name == "schedule_appointment":
                return self.handle_schedule_appointment(tool_data)

            elif tool_name == "suggest_available_slots":
                return self.handle_suggest_available_slots(tool_data)

            else:
                logger.warning(f"[DatabaseAgentsManager] Unknown tool: {tool_name}")
                return {
                    "error": f"Tool '{tool_name}' not supported",
                    "available_tools": ["get_available_slots", "schedule_appointment", "suggest_available_slots"]
                }

        except Exception as e:
            logger.error(f"[DatabaseAgentsManager] Error processing tool {tool_name}: {e}")
            return {
                "error": "Erro interno ao processar solicitação",
                "tool_name": tool_name
            }