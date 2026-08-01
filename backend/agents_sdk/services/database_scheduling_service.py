"""
Database-based Scheduling Service for Agents SDK
Replicates functionality from backend/prompt/scheduling/scheduling_service.py
but stores slots in database instead of Redis
"""

import logging
from typing import Set, List, Dict, Optional, Any
from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from sqlalchemy import and_, or_
import json

from ..database.models import CompanySlot
from ..tools.slots_service import SlotsService
from backend.models import Agenda, AgendaSchedule, Agendamento

logger = logging.getLogger(__name__)
SP_TZ = ZoneInfo("America/Sao_Paulo")


class DatabaseSchedulingService:
    """
    Database-based version of SchedulingService that:
    1. Fetches from integrations (Google Calendar, Clinicorp, local config)
    2. STORES in database table company_slots instead of Redis
    3. Provides slots to agents from database
    """

    def __init__(self, db: Session, company_id: int):
        self.db = db
        self.company_id = company_id
        self.company_tz = self._get_company_timezone()
        self.config = self._load_scheduling_config()
        self.integrations = self._load_calendar_integrations()
        self.slots_service = SlotsService(db)

        logger.info(f"[DatabaseSchedulingService] Iniciado para company_id={company_id}")
        logger.info(f"[DatabaseSchedulingService] Configurações: {self.config}")
        logger.info(f"[DatabaseSchedulingService] Integrações: {len(self.integrations)}")

    def _get_company_timezone(self) -> ZoneInfo:
        """Get company timezone from ai_response_windows table"""
        try:
            row = self.db.execute(
                text("""
                    SELECT timezone
                    FROM ai_response_windows
                    WHERE company_id = :cid
                    LIMIT 1
                """),
                {"cid": self.company_id}
            ).fetchone()

            if row and row.timezone:
                try:
                    tz = ZoneInfo(row.timezone)
                    logger.info(f"[DatabaseSchedulingService] Using custom timezone for company {self.company_id}: {row.timezone}")
                    return tz
                except Exception as tz_error:
                    logger.error(f"[DatabaseSchedulingService] Invalid timezone '{row.timezone}': {tz_error}")
        except Exception as e:
            logger.error(f"[DatabaseSchedulingService] Error getting timezone: {e}")

        logger.info(f"[DatabaseSchedulingService] Using default timezone: America/Sao_Paulo")
        return SP_TZ

    def _load_scheduling_config(self) -> Dict:
        """Load scheduling configuration from agent_config"""
        try:
            from backend.prompt.db_integration.agent_config import get_agent_config_dict
            config = get_agent_config_dict(self.db, self.company_id)
            return config.get("scheduling_config", {})
        except Exception as e:
            logger.error(f"[DatabaseSchedulingService] Error loading config: {e}")
            return {}

    def _load_calendar_integrations(self) -> List[Dict[str, Any]]:
        """Load calendar integrations from database"""
        try:
            agenda_links = self.db.execute(text("""
                SELECT id AS agenda_id,
                       google_calendar_id
                  FROM agendas
                 WHERE company_id = :cid
                   AND google_calendar_id IS NOT NULL
            """), {"cid": self.company_id}).fetchall()

            rows = self.db.execute(text("""
                SELECT provider,
                       google_calendar_id,
                       clinicorp_username,
                       clinicorp_password,
                       clinicorp_code_link,
                       clinicorp_subscriber_id
                  FROM calendar_integrations
                 WHERE company_id = :cid
            """), {"cid": self.company_id}).fetchall()

            results = []
            for link in agenda_links:
                results.append({
                    "provider": "google",
                    "google_calendar_id": link.google_calendar_id,
                    "agenda_id": link.agenda_id,
                })

            for r in rows:
                if r.provider == "google" and agenda_links:
                    continue
                results.append({
                    "provider": r.provider,
                    "google_calendar_id": r.google_calendar_id,
                    "agenda_id": None,
                    "clinicorp_username": r.clinicorp_username,
                    "clinicorp_password": r.clinicorp_password,
                    "clinicorp_code_link": r.clinicorp_code_link,
                    "clinicorp_subscriber_id": r.clinicorp_subscriber_id
                })
            return results
        except Exception as e:
            logger.error(f"[DatabaseSchedulingService] Error loading integrations: {e}")
            return []

    def fetch_and_store_availabilities(self) -> int:
        """
        Main method: Fetch from integrations and store in database
        Returns: Number of slots stored
        """
        logger.info(f"[DatabaseSchedulingService] Starting fetch and store for company {self.company_id}")

        has_clinicorp = any(conf["provider"] == "clinicorp" for conf in self.integrations)
        has_google = any(conf["provider"] == "google" for conf in self.integrations)

        all_slots_items = [] # List of Dicts or strings
        source = "local"  # default source

        # 0. Always get Agenda Slots (New Feature)
        try:
            agenda_slots = self._fetch_agenda_slots()
            if agenda_slots:
                logger.info(f"[DatabaseSchedulingService] Found {len(agenda_slots)} slots from Agendas")
                all_slots_items.extend(agenda_slots)
        except Exception as e:
            logger.error(f"[DatabaseSchedulingService] Error fetching agenda slots: {e}")

        # 1. Get base slots (Integration or Local)
        integration_slots = []
        if has_clinicorp:
            logger.info(f"[DatabaseSchedulingService] Fetching from Clinicorp...")
            clinicorp_dt_list = []
            for conf in self.integrations:
                if conf["provider"] == "clinicorp":
                    c_slots = self._fetch_clinicorp_available_slots(conf)
                    clinicorp_dt_list.extend(c_slots)

            # Filter and convert to strings
            filtered_strings = self._filter_clinicorp_with_config(clinicorp_dt_list)
            # Convert to dict items
            for s in filtered_strings:
                integration_slots.append({
                    "slot": s,
                    "professional": "Clinicorp",
                    "source": "clinicorp",
                    "metadata": {"origin": "clinicorp"}
                })
            source = "clinicorp"

        # Combine Integration slots
        if integration_slots:
             all_slots_items.extend(integration_slots)

        # Fallback to Local ONLY if nothing else found (Agendas or Integrations)
        if not all_slots_items:
            logger.info(f"[DatabaseSchedulingService] No Agenda or Integration slots. Generating local slots...")
            start_date = datetime.now(self.company_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            local_strings = self._generate_available_slots(start_date, days_ahead=30)
            for s in local_strings:
                all_slots_items.append({
                    "slot": s,
                    "professional": "",
                    "source": "local",
                    "metadata": {"origin": "local"}
                })
            source = "local"
        else:
            # If we have items, set source to 'mixed' or keep primarily what found.
            # But the storage method largely overwrites 'source' param for the batch,
            # unless we refactor it to respect item source.
            if has_clinicorp and agenda_slots:
                source = "mixed"
            elif has_clinicorp:
                source = "clinicorp"
            elif agenda_slots:
                source = "agenda"

        # 2. Apply Google Calendar blocks
        if has_google:
            logger.info(f"[DatabaseSchedulingService] Applying Google Calendar blocks...")
            google_blocks = []
            for conf in self.integrations:
                if conf["provider"] == "google":
                    g_blocks = self._fetch_google_unavailable_intervals(conf)
                    google_blocks.extend(g_blocks)

            if google_blocks:
                slots_before = len(all_slots_items)
                all_slots_items = self._apply_google_blocks_structured(all_slots_items, google_blocks)
                logger.info(f"[DatabaseSchedulingService] Removed {slots_before - len(all_slots_items)} slots due to Google blocks")

        # 3. Filter past slots
        now = datetime.now(self.company_tz)
        future_slots = []
        for item in all_slots_items:
            slot_str = item["slot"]
            try:
                slot_dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M").replace(tzinfo=self.company_tz)
                if slot_dt > now:
                    future_slots.append(item)
            except ValueError:
                continue

        # 4. Store in database
        # We need to be careful about clearing existing slots.
        # Ideally we replace all slots for this company that are locally managed.
        # For simplicity, we'll clear everything for this company and re-insert.
        stored_count = self._store_slots_in_database(future_slots, source)

        logger.info(f"[DatabaseSchedulingService] Stored {stored_count} slots in database for company {self.company_id}")
        return stored_count

    def _store_slots_in_database(self, slots: List[Dict], source: str) -> int:
        """
        Store slots in company_slots table.
        Args:
            slots: List of dicts, each must have 'slot' key. Can have 'professional', 'metadata', etc.
            source: Primary source of the slots (used for logging or defaults)
        """
        try:
            # Clear existing slots for this company (refresh all)
            # NOTE: We are refreshing ALL slots for the company to avoid staleness
            self.db.execute(text("""
                DELETE FROM company_slots
                WHERE company_id = :company_id
            """), {"company_id": self.company_id})

            # Prepare slots data for insertion
            slots_data = []
            for item in slots:
                try:
                    slot_str = item["slot"]
                    slot_dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M")

                    # Extract structured data
                    prof = item.get("professional", "")
                    meta = item.get("metadata", {})
                    item_source = item.get("source", source)

                    # Update metadata with generated_at
                    meta["generated_at"] = datetime.now().isoformat()

                    slots_data.append({
                        "date": slot_dt.strftime("%d/%m/%Y"),
                        "time": slot_dt.strftime("%H:%M"),
                        "professional": prof,
                        "available": True,
                        "service_type": "Consulta",
                        "metadata": meta,
                        # We might need to pass source to SlotsService if it uses it
                    })
                except ValueError:
                    continue

            # Use SlotsService to insert
            added_count = self.slots_service.add_slots_from_integration(
                company_id=self.company_id,
                slots_data=slots_data,
                source=source
            )

            self.db.commit()
            return added_count

        except Exception as e:
            self.db.rollback()
            logger.error(f"[DatabaseSchedulingService] Error storing slots: {e}")
            return 0

    def _apply_google_blocks_structured(self, slots_items: List[Dict], google_blocks: List[Dict[str, datetime]]) -> List[Dict]:
        """Remove slots that conflict with Google Calendar blocks"""
        result = []
        for item in slots_items:
            s = item["slot"]
            try:
                dt_obj = datetime.strptime(s, "%d/%m/%Y %H:%M").replace(tzinfo=self.company_tz)
            except ValueError:
                continue

            blocked = False
            for block in google_blocks:
                block_agenda_id = block.get("agenda_id")
                item_agenda_id = item.get("metadata", {}).get("agenda_id")
                if block_agenda_id and int(block_agenda_id) != int(item_agenda_id or 0):
                    continue
                block_start = block["start"]
                block_end = block["end"]
                if block_start <= dt_obj < block_end:
                    blocked = True
                    break
            if not blocked:
                result.append(item)
        return result

    def _fetch_agenda_slots(self) -> List[Dict]:
        """Fetch available slots from active Agendas"""
        try:
            active_agendas = self.db.query(Agenda).filter(
                Agenda.company_id == self.company_id,
                Agenda.active == True
            ).all()

            if not active_agendas:
                return []

            slots_result = []
            today = datetime.now(self.company_tz).date()

            # Pre-fetch ALL existing appointments for this company to minimize queries?
            # Or query per agenda. Let's query relevant range.
            start_check = datetime.now(self.company_tz)
            end_check = start_check + timedelta(days=30)

            existing_appointments = self.db.query(Agendamento).filter(
                Agendamento.company_id == self.company_id,
                Agendamento.consulta_data >= start_check,
                Agendamento.consulta_data <= end_check,
                Agendamento.status.notlike('CANCELLED%')
            ).all()

            # Map appointments by (agenda_id, date, time) -> occupied
            # Handle timezone carefully. Agendamento.consulta_data is TZ aware.
            occupied_slots = set()
            for appt in existing_appointments:
                if appt.consulta_data:
                    # Convert to company TZ
                    appt_dt = appt.consulta_data.astimezone(self.company_tz)
                    date_str = appt_dt.strftime("%d/%m/%Y")
                    time_str = appt_dt.strftime("%H:%M")
                    # If agenda_id is NULL, it blocks ALL agendas? Or just generic?
                    # For now, if agenda_id is set, it blocks that agenda.
                    # If agenda_id is NULL, it effectively blocks based on semantics,
                    # but current legacy system doesn't have agenda_id.
                    # Assumption: Legacy appointments (no agenda_id) might block nothing specific, or all?
                    # Let's assume they don't block specific agendas unless we implement "Default Agenda".
                    if appt.agenda_id:
                        occupied_slots.add((appt.agenda_id, date_str, time_str))

            for agenda in active_agendas:
                # Calculate slots for this agenda
                # This logic mimics _generate_available_slots but uses AgendaSchedule model

                # Fetch schedules for this agenda
                schedules = self.db.query(AgendaSchedule).filter(AgendaSchedule.agenda_id == agenda.id).all()
                if not schedules:
                    continue

                # Organize schedules by day of week (0=Monday, 6=Sunday)
                schedule_map = {s.day_of_week: s for s in schedules}

                for i in range(30):
                    current_date = today + timedelta(days=i)
                    day_of_week = current_date.weekday()

                    if day_of_week not in schedule_map:
                        continue

                    daily_schedule = schedule_map[day_of_week]

                    # Helper to generate slots for a period
                    def add_period(start_t, end_t):
                        if not start_t or not end_t: return

                        start_dt = datetime.combine(current_date, start_t).replace(tzinfo=self.company_tz)
                        end_dt = datetime.combine(current_date, end_t).replace(tzinfo=self.company_tz)

                        curr = start_dt
                        while curr + timedelta(minutes=agenda.slot_duration) <= end_dt:
                             # Check if occupied
                             d_str = curr.strftime("%d/%m/%Y")
                             t_str = curr.strftime("%H:%M")

                             if (agenda.id, d_str, t_str) not in occupied_slots:
                                 # Configurable safety margin check
                                 safety_margin = timedelta(minutes=agenda.safety_margin_minutes)
                                 if curr > datetime.now(self.company_tz) + safety_margin:
                                     slots_result.append({
                                         "slot": f"{d_str} {t_str}",
                                         "professional": agenda.name,
                                         "source": "agenda",
                                         "metadata": {
                                             "agenda_id": agenda.id,
                                             "origin": "agenda"
                                         }
                                     })

                             curr += timedelta(minutes=agenda.slot_duration)

                    # Morning
                    add_period(daily_schedule.morning_start, daily_schedule.morning_end)

                    # Afternoon
                    add_period(daily_schedule.afternoon_start, daily_schedule.afternoon_end)

                    # Night
                    add_period(daily_schedule.night_start, daily_schedule.night_end)

            return slots_result

        except Exception as e:
            logger.error(f"[DatabaseSchedulingService] Error in _fetch_agenda_slots: {e}")
            return []

    def get_available_slots_from_database(
        self,
        limit: int = 20,
        weekday_name: Optional[str] = None,
        time_period: Optional[str] = None,
        day_type: Optional[str] = None
    ) -> List[str]:
        """Get available slots from database with optional filters"""

        logger.info(f"[DatabaseSchedulingService] get_available_slots_from_database called with weekday_name='{weekday_name}', time_period='{time_period}', limit={limit}")

        # If filters are specified, use the filtered method
        if weekday_name or time_period or day_type:
            logger.info(f"[DatabaseSchedulingService] Using filtered search for weekday='{weekday_name}', period='{time_period}', day_type='{day_type}'")
            filtered_slots = self.slots_service.get_available_slots_filtered(
                company_id=self.company_id,
                weekday_name=weekday_name,
                time_period=time_period,
                day_type=day_type,
                limit=limit
            )

            # Convert from dict format to string format for compatibility
            result_slots = []
            for slot in filtered_slots:
                if isinstance(slot, dict) and "slot" in slot:
                    result_slots.append(slot["slot"])
                else:
                    result_slots.append(str(slot))

            logger.info(f"[DatabaseSchedulingService] Filtered search returned {len(result_slots)} slots")
            return result_slots
        else:
            # No filters, use generic search
            logger.info(f"[DatabaseSchedulingService] Using generic search (no filters)")
            return self.slots_service.get_available_slots(
                company_id=self.company_id,
                limit=limit,
                days_ahead=30
            )

    def _fetch_clinicorp_available_slots(self, integration_conf: Dict[str, str]) -> List[datetime]:
        """Fetch from Clinicorp API (same logic as original)"""
        try:
            from backend.prompt.scheduling.clinicorp_integration import ClinicorpIntegration

            code_link = integration_conf["clinicorp_code_link"]
            subscriber_id = integration_conf["clinicorp_subscriber_id"]
            username = integration_conf["clinicorp_username"]
            password = integration_conf["clinicorp_password"]

            if not code_link or not subscriber_id:
                logger.warning("[DatabaseSchedulingService] Missing Clinicorp credentials")
                return []

            clinicorp_api = ClinicorpIntegration(
                code_link=code_link,
                subscriber_id=subscriber_id,
                username=username,
                password=password
            )

            today = datetime.now(SP_TZ).date()
            start_date = today
            end_date = start_date + timedelta(days=30)

            all_avail_dt = []
            current = start_date
            while current <= end_date:
                daily_slots = clinicorp_api.get_available_times(current.strftime("%Y-%m-%d"))
                for slot in daily_slots:
                    from_str = slot.get("From")
                    if not from_str:
                        continue
                    try:
                        hour, minute = from_str.split(":")
                        slot_dt = datetime(
                            year=current.year,
                            month=current.month,
                            day=current.day,
                            hour=int(hour),
                            minute=int(minute)
                        ).replace(tzinfo=SP_TZ)
                        all_avail_dt.append(slot_dt)
                    except Exception:
                        continue
                current += timedelta(days=1)

            logger.info(f"[DatabaseSchedulingService] Fetched {len(all_avail_dt)} Clinicorp slots")
            return all_avail_dt

        except Exception as e:
            logger.error(f"[DatabaseSchedulingService] Error fetching Clinicorp slots: {e}")
            return []

    def _fetch_google_unavailable_intervals(self, integration_conf: Dict[str, str]) -> List[Dict[str, datetime]]:
        """Fetch Google Calendar unavailable intervals (same logic as original)"""
        try:
            from backend.models import CalendarIntegration
            from backend.prompt.scheduling.google_calendar_integration import obter_eventos_calendario
            from backend.routes.integrations.google_calendar_service import build_google_oauth_service

            calendar_id = integration_conf["google_calendar_id"]
            if not calendar_id:
                return []

            integration = self.db.query(CalendarIntegration).filter(
                CalendarIntegration.company_id == self.company_id,
                CalendarIntegration.provider == "google",
            ).first()
            if not integration or not integration.google_oauth_token:
                logger.warning("[DatabaseSchedulingService] Google Calendar OAuth not connected")
                return []

            service = build_google_oauth_service(integration, self.db)
            if not service:
                return []

            start_dt = datetime.now(self.company_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = start_dt + timedelta(days=30)

            events = obter_eventos_calendario(
                service,
                calendar_id,
                start_dt.isoformat(),
                end_dt.isoformat()
            )

            unavailable = []
            for evt in events:
                try:
                    start_info = evt.get("start", {})
                    end_info = evt.get("end", {})

                    start_str = start_info.get("dateTime") or start_info.get("date")
                    end_str = end_info.get("dateTime") or end_info.get("date")

                    if not start_str or not end_str:
                        continue

                    # Parse date/datetime
                    if "T" not in start_str:
                        # All day event
                        dt_start = datetime.fromisoformat(f"{start_str}T00:00:00").replace(tzinfo=self.company_tz)
                        end_day = datetime.fromisoformat(f"{end_str}T00:00:00").replace(tzinfo=self.company_tz)
                        dt_end = end_day - timedelta(seconds=1)
                        if dt_end < dt_start:
                            dt_end = dt_start.replace(hour=23, minute=59, second=59)
                    else:
                        # Specific time
                        dt_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        dt_end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                        dt_start = dt_start.astimezone(self.company_tz)
                        dt_end = dt_end.astimezone(self.company_tz)

                    unavailable.append({
                        "start": dt_start,
                        "end": dt_end,
                        "agenda_id": integration_conf.get("agenda_id"),
                    })

                except Exception:
                    continue

            # Sort and merge overlapping blocks
            if unavailable:
                unavailable.sort(key=lambda x: x["start"])
                merged = []
                current = unavailable[0]

                for next_block in unavailable[1:]:
                    if next_block["start"] <= current["end"]:
                        current["end"] = max(current["end"], next_block["end"])
                    else:
                        merged.append(current)
                        current = next_block

                merged.append(current)
                return merged

            return []

        except Exception as e:
            logger.error(f"[DatabaseSchedulingService] Error fetching Google blocks: {e}")
            return []

    def _filter_clinicorp_with_config(self, clinicorp_slots: List[datetime]) -> List[str]:
        """Filter Clinicorp slots using local config"""
        result = []
        for dt_obj in clinicorp_slots:
            day_of_week = dt_obj.weekday()
            day_map = {0: "monday", 1: "tuesday", 2: "wednesday", 3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"}
            day_name = day_map[day_of_week]
            day_config = self.config.get(day_name, {})

            if not day_config.get('open', False):
                continue

            # Check morning period
            if day_config.get('morningEnabled'):
                try:
                    morning_start_hour, morning_start_min = map(int, day_config['morningStart'].split(":"))
                    morning_end_hour, morning_end_min = map(int, day_config['morningEnd'].split(":"))

                    morning_start = dt_obj.replace(hour=morning_start_hour, minute=morning_start_min)
                    morning_end = dt_obj.replace(hour=morning_end_hour, minute=morning_end_min)

                    if morning_start <= dt_obj < morning_end:
                        result.append(dt_obj.strftime("%d/%m/%Y %H:%M"))
                        continue
                except Exception:
                    pass

            # Check afternoon period
            if day_config.get('afternoonEnabled'):
                try:
                    aft_start_hour, aft_start_min = map(int, day_config['afternoonStart'].split(":"))
                    aft_end_hour, aft_end_min = map(int, day_config['afternoonEnd'].split(":"))

                    afternoon_start = dt_obj.replace(hour=aft_start_hour, minute=aft_start_min)
                    afternoon_end = dt_obj.replace(hour=aft_end_hour, minute=aft_end_min)

                    if afternoon_start <= dt_obj < afternoon_end:
                        result.append(dt_obj.strftime("%d/%m/%Y %H:%M"))
                except Exception:
                    pass

        # Sort by actual date
        def sort_key(slot_str):
            try:
                return datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
            except:
                return datetime.max

        return sorted(result, key=sort_key)

    def _generate_available_slots(self, start_date: datetime, days_ahead: int = 30) -> List[str]:
        """Generate local slots based on config"""
        available_slots = []
        current_date = start_date

        for day_num in range(days_ahead):
            day_name = current_date.strftime("%A").lower()
            day_config = self.config.get(day_name, {})

            if day_config.get('open', False):
                # Morning slots
                if day_config.get('morningEnabled', False):
                    try:
                        morning_start = current_date.replace(
                            hour=int(day_config['morningStart'].split(":")[0]),
                            minute=int(day_config['morningStart'].split(":")[1]),
                            second=0, microsecond=0
                        )
                        morning_end = current_date.replace(
                            hour=int(day_config['morningEnd'].split(":")[0]),
                            minute=int(day_config['morningEnd'].split(":")[1]),
                            second=0, microsecond=0
                        )
                        self._generate_period_slots(morning_start, morning_end, available_slots)
                    except Exception:
                        pass

                # Afternoon slots
                if day_config.get('afternoonEnabled', False):
                    try:
                        afternoon_start = current_date.replace(
                            hour=int(day_config['afternoonStart'].split(":")[0]),
                            minute=int(day_config['afternoonStart'].split(":")[1]),
                            second=0, microsecond=0
                        )
                        afternoon_end = current_date.replace(
                            hour=int(day_config['afternoonEnd'].split(":")[0]),
                            minute=int(day_config['afternoonEnd'].split(":")[1]),
                            second=0, microsecond=0
                        )
                        self._generate_period_slots(afternoon_start, afternoon_end, available_slots)
                    except Exception:
                        pass

            current_date += timedelta(days=1)

        return available_slots

    def _generate_period_slots(self, period_start: datetime, period_end: datetime, available_slots: List[str]) -> None:
        """Generate slots for a specific period"""
        if period_start.tzinfo is None:
            period_start = period_start.replace(tzinfo=self.company_tz)
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=self.company_tz)

        now = datetime.now(self.company_tz)

        # Skip if period already passed - WITH 3 HOUR MARGIN
        min_booking_time = now + timedelta(hours=3)  # 3 hours safety margin
        if period_start.date() == now.date() and period_start < min_booking_time:
            consult_duration = self.config.get('consultation_duration', 30)

            # Adjust to next available slot at least 3 hours ahead
            period_start = min_booking_time
            # Round to next consultation duration slot
            if period_start.minute % consult_duration != 0:
                minutes_to_add = consult_duration - (period_start.minute % consult_duration)
                period_start = period_start + timedelta(minutes=minutes_to_add)

            period_start = period_start.replace(second=0, microsecond=0)

            if period_start >= period_end:
                return

        consult_duration = self.config.get('consultation_duration', 30)
        slot_dt = period_start

        while slot_dt + timedelta(minutes=consult_duration) <= period_end:
            # Apply 3-hour margin filter
            min_booking_time = now + timedelta(hours=3)
            if slot_dt < min_booking_time:
                slot_dt += timedelta(minutes=consult_duration)
                continue

            slot_str = slot_dt.strftime("%d/%m/%Y %H:%M")
            available_slots.append(slot_str)
            slot_dt += timedelta(minutes=consult_duration)

    def _apply_google_blocks(self, slot_strings: List[str], google_blocks: List[Dict[str, datetime]]) -> List[str]:
        """Remove slots that conflict with Google Calendar blocks"""
        result = []

        for s in slot_strings:
            try:
                dt_obj = datetime.strptime(s, "%d/%m/%Y %H:%M").replace(tzinfo=self.company_tz)
            except ValueError:
                continue

            blocked = False
            for block in google_blocks:
                block_start = block["start"]
                block_end = block["end"]
                if block_start <= dt_obj < block_end:
                    blocked = True
                    break
            if not blocked:
                result.append(s)

        return result

    def cleanup_expired_slots(self) -> int:
        """Clean up expired slots for this company"""
        return self.slots_service.cleanup_expired_slots(self.company_id)

    def get_slots_stats(self) -> Dict[str, Any]:
        """Get statistics about slots for this company"""
        return self.slots_service.get_slots_stats(self.company_id)

    def reserve_slot(
        self,
        company_id: int,
        slot_datetime: str,
        customer_info: Dict[str, Any] = None
    ) -> bool:
        """
        Reserve a slot - delegates to SlotsService

        Args:
            company_id: ID of the company
            slot_datetime: Slot in "dd/mm/yyyy HH:MM" format
            customer_info: Optional customer information

        Returns:
            True if reservation successful
        """
        return self.slots_service.reserve_slot(
            company_id=company_id,
            slot_datetime=slot_datetime,
            customer_info=customer_info
        )
