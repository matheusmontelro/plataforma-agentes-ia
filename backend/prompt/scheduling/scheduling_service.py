
import logging
from typing import Set
from datetime import datetime, timedelta, date, timezone
from typing import List, Dict, Optional, Any
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
import os
import redis
import json
from backend.models import CalendarIntegration
from backend.routes.integrations.google_calendar_service import build_google_oauth_service
from ..db_integration.agent_config import get_agent_config_dict
from .google_calendar_integration import obter_eventos_calendario
from .clinicorp_integration import ClinicorpIntegration
from .slots_monitor import slots_monitor

logger = logging.getLogger(__name__)
SP_TZ = ZoneInfo("America/Sao_Paulo")


class SchedulingService:
    """
    Nesta versão, get_next_available_slots() apenas consulta o cache Redis
    para a empresa em questão (company_id). Se o cache não existir, retorna
    uma lista vazia (ou outro fallback).

    Métodos privados como _fetch_google_unavailable_intervals e
    _fetch_clinicorp_available_slots ficam disponíveis caso as tasks Celery
    quebrem a lógica de busca externa, mas não são chamados diretamente
    durante a interação do chatbot.
    """

    def __init__(self, db: Session, company_id: int):
        self.db = db
        self.company_id = company_id
        self.config = self._load_scheduling_config()
        self.company_tz = self._get_company_timezone()
        logger.info(f"[SchedulingService] Iniciado para company_id={company_id}")
        logger.info(f"[SchedulingService] Configurações carregadas: {self.config}")

        # Carrega informações de integrações apenas se precisar usar
        # (ex.: nas tasks de background).
        self.integrations = self._load_calendar_integrations()
        logger.info(f"[SchedulingService] Integrações de calendário encontradas: {self.integrations}")

        # Configuração do Redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_client = redis.from_url(redis_url)

    def _get_company_timezone(self) -> ZoneInfo:
        """
        Retorna o fuso horário configurado para a empresa na tabela ai_response_windows.
        Se não existir ou for inválido, usa o padrão SP_TZ.
        """
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
                    # Tenta criar um objeto ZoneInfo para verificar se é válido
                    tz = ZoneInfo(row.timezone)
                    logger.info(f"[SchedulingService] Usando timezone personalizado para company_id={self.company_id}: {row.timezone}")
                    return tz
                except Exception as tz_error:
                    logger.error(f"[SchedulingService] Timezone inválido '{row.timezone}': {tz_error}, usando padrão")
        except Exception as e:
            logger.error(f"[SchedulingService] Erro ao obter timezone: {e}")

        # Fallback para o timezone padrão
        logger.info(f"[SchedulingService] Usando timezone padrão para company_id={self.company_id}: America/Sao_Paulo")
        return SP_TZ

    def _load_scheduling_config(self) -> Dict:
        """Carrega as configurações de agendamento do agent_config (JSONB) no BD."""
        config = get_agent_config_dict(self.db, self.company_id)
        return config.get("scheduling_config", {})

    def _load_calendar_integrations(self) -> List[Dict[str, Any]]:
        """
        Carrega as integrações de calendário (google, clinicorp, etc.)
        da tabela calendar_integrations.
        Retorna lista de dicionários, cada um representando uma integração.
        """
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

    # --------------------------------------------------------------
    # FUNÇÃO PRINCIPAL PARA BUSCA EXTERNA (CHAMADA PELAS TASKS)
    # --------------------------------------------------------------
    def fetch_availabilities_from_integrations(self) -> List[str]:
        """
        Busca dados das integrações configuradas e retorna slots livres no formato "DD/MM/YYYY HH:MM".
        1. Se houver Clinicorp, busca disponibilidades de lá.
        2. Se não houver Clinicorp, mas houver config local, gera localmente.
        3. Se houver Google, busca blocos indisponíveis e remove dos slots obtidos acima.
        4. Filtra horários já passados.
        5. Retorna a lista final.
        """
        has_clinicorp = any(conf["provider"] == "clinicorp" for conf in self.integrations)
        has_google = any(conf["provider"] == "google" for conf in self.integrations)

        logger.info(f"[fetch_availabilities] Iniciando para company_id={self.company_id}, has_clinicorp={has_clinicorp}, has_google={has_google}")

        all_slots = []

        # 1) Se existe Clinicorp, pega do Clinicorp:
        if has_clinicorp:
            clinicorp_slots = []
            for conf in self.integrations:
                if conf["provider"] == "clinicorp":
                    c_slots = self._fetch_clinicorp_available_slots(conf)
                    clinicorp_slots.extend(c_slots)
            # filtra usando config local:
            all_slots = self._filter_clinicorp_with_config(clinicorp_slots)
        else:
            # se não tem Clinicorp, gera localmente (caso queira):
            start_date = datetime.now(SP_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            logger.info(f"[fetch_availabilities] Gerando slots localmente a partir de {start_date}")
            all_slots = self.generate_available_slots(start_date, days_ahead=30)
            logger.info(f"[fetch_availabilities] Slots gerados localmente: {len(all_slots)} slots")

        # 2) Se existe Google, busca blocos e remove do all_slots
        if has_google:
            google_blocks = []
            for conf in self.integrations:
                if conf["provider"] == "google":
                    g_indisp = self._fetch_google_unavailable_intervals(conf)
                    google_blocks.extend(g_indisp)

            logger.info(f"[fetch_availabilities] Eventos Google Calendar encontrados: {len(google_blocks)}")
            if google_blocks:
                slots_before = len(all_slots)
                all_slots = self._apply_google_block_on_clinicorp_slots(all_slots, google_blocks)
                logger.info(f"[fetch_availabilities] Slots após aplicar bloqueios Google: {len(all_slots)} (removidos: {slots_before - len(all_slots)})")

        # 3) Filtrar horários que já passaram
        now = datetime.now(self.company_tz)
        future_slots = []

        logger.info(f"[fetch_availabilities] Filtrando slots passados. Horário atual: {now}")

        for slot_str in all_slots:
            try:
                slot_dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M").replace(tzinfo=self.company_tz)
                # Só incluir slots futuros
                if slot_dt > now:
                    future_slots.append(slot_str)
                else:
                    logger.debug(f"[fetch_availabilities] Slot removido (já passou): {slot_str}")
            except ValueError:
                logger.warning(f"[fetch_availabilities] Slot inválido ignorado: {slot_str}")
                continue

        logger.info(f"[fetch_availabilities] Total final após filtragem: {len(future_slots)} slots disponíveis")

        # Ordenar por data real, não alfabeticamente
        def sort_key(slot_str):
            try:
                return datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
            except:
                return datetime.max

        return sorted(future_slots, key=sort_key)

    def _apply_google_block_on_clinicorp_slots(
        self,
        slot_strings: List[str],
        google_blocks: List[Dict[str, datetime]]
    ) -> List[str]:
        """
        Remove slots (DD/MM/YYYY HH:MM) que colidem com
        algum bloco de indisponibilidade do Google (start/end).
        """
        result = []

        for s in slot_strings:
            try:
                dt_obj = datetime.strptime(s, "%d/%m/%Y %H:%M").replace(tzinfo=self.company_tz)
            except ValueError:
                continue

            blocked = False
            for block in google_blocks:
                block_start = block["start"]
                block_end   = block["end"]
                # Se dt_obj está dentro do intervalo [block_start, block_end)
                if block_start <= dt_obj < block_end:
                    blocked = True
                    break
            if not blocked:
                result.append(s)

        return result

    # --------------------------------------------------------------
    # Integração com Google Calendar (obtém INDISPONIBILIDADES)
    # --------------------------------------------------------------
    def _fetch_google_unavailable_intervals(self, integration_conf: Dict[str, str]) -> List[Dict[str, datetime]]:
        """
        Puxa do Google Calendar os eventos entre amanhã e +7 dias,
        gera uma lista de dicionários: [{"start": datetime, "end": datetime}, ...]
        respeitando o fuso 'America/Sao_Paulo' e distinguindo eventos day-long.
        """
        calendar_id = integration_conf["google_calendar_id"]
        if not calendar_id:
            logger.warning("[SchedulingService] google_calendar_id vazio ou None.")
            return []

        integration = self.db.query(CalendarIntegration).filter(
            CalendarIntegration.company_id == self.company_id,
            CalendarIntegration.provider == "google",
        ).first()
        if not integration or not integration.google_oauth_token:
            logger.warning("[SchedulingService] Google Agenda sem OAuth conectado.")
            return []

        service = build_google_oauth_service(integration, self.db)
        if not service:
            logger.error("[SchedulingService] Não foi possível obter service do Google Calendar.")
            return []

        # Período de captura (amanhã até +7 dias)
        start_dt = datetime.now(self.company_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=30)

        try:
            # Pega os eventos brutos
            events = obter_eventos_calendario(
                service,
                calendar_id,
                start_dt.isoformat(),
                end_dt.isoformat()
            )
            logger.info(f"[DEBUG] Eventos brutos do Google Calendar: {events}")

            # Converte cada evento para {start: datetime, end: datetime}
            unavailable = []
            for evt in events:
                try:
                    start_info = evt.get("start", {})
                    end_info = evt.get("end", {})

                    start_str = start_info.get("dateTime") or start_info.get("date")
                    end_str = end_info.get("dateTime") or end_info.get("date")

                    if not start_str or not end_str:
                        continue

                    # Verifica se é evento all-day (sem "T" no meio)
                    if "T" not in start_str:
                        # Dia inteiro => 00:00 até 23:59:59 do MESMO dia.
                        dt_start = datetime.fromisoformat(f"{start_str}T00:00:00").replace(tzinfo=self.company_tz)
                        end_day = datetime.fromisoformat(f"{end_str}T00:00:00").replace(tzinfo=self.company_tz)
                        dt_end = end_day - timedelta(seconds=1)
                        # Proteção caso end_str seja o mesmo dia:
                        if dt_end < dt_start:
                            dt_end = dt_start.replace(hour=23, minute=59, second=59)
                    else:
                        # É dateTime => parse iso
                        dt_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        dt_end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

                        # Força/faz astimezone
                        dt_start = dt_start.astimezone(self.company_tz)
                        dt_end = dt_end.astimezone(self.company_tz)

                    if dt_start.tzinfo is None:
                        dt_start = dt_start.replace(tzinfo=self.company_tz)
                    if dt_end.tzinfo is None:
                        dt_end = dt_end.replace(tzinfo=self.company_tz)

                    block = {"start": dt_start, "end": dt_end}
                    unavailable.append(block)
                    logger.info(f"[DEBUG] Processado evento '{evt.get('summary','Sem título')}': {block}")

                except Exception as e:
                    logger.error(f"[DEBUG] Erro ao processar evento: {e}, Event data: {evt}")
                    continue

            # Ordenar e mesclar sobrepostos
            if not unavailable:
                return []

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
            logger.info(f"[DEBUG] Total de eventos indisponíveis após mesclagem: {merged}")
            return merged

        except Exception as e:
            logger.error(f"[SchedulingService] Erro ao obter eventos do Google: {e}")
            return []

    # --------------------------------------------------------------
    # Métodos para Clinicorp (obtém DISPONIBILIDADES)
    # --------------------------------------------------------------
    def _fetch_clinicorp_available_slots(self, integration_conf: Dict[str, str]) -> List[datetime]:
        """
        Usa a class ClinicorpIntegration para puxar horários disponíveis nos próximos 7 dias.
        Retorna lista de datetimes (cada um indicando slot disponível).
        """
        code_link = integration_conf["clinicorp_code_link"]
        subscriber_id = integration_conf["clinicorp_subscriber_id"]
        username = integration_conf["clinicorp_username"]
        password = integration_conf["clinicorp_password"]

        if not code_link or not subscriber_id:
            logger.warning("[SchedulingService] code_link ou subscriber_id faltando.")
            return []

        clinicorp_api = ClinicorpIntegration(
            code_link=code_link,
            subscriber_id=subscriber_id,
            username=username,
            password=password
        )

        # Ajustamos para 7 dias ao invés de 30
        today = datetime.now(SP_TZ).date()
        start_date = today
        end_date = start_date + timedelta(days=30)  # total 7 dias (amanhã + 6)

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
                except Exception as ee:
                    logger.warning(f"[SchedulingService] Erro ao parse slot Clinicorp: {ee}")
            current += timedelta(days=1)

        logger.info(f"[SchedulingService] Total de slots disponíveis do Clinicorp (30 dias): {len(all_avail_dt)}")
        return all_avail_dt

    def _filter_clinicorp_with_config(self, clinicorp_slots: List[datetime]) -> List[str]:
        """
        Filtra os horários do Clinicorp segundo a config local (dias e horários abertos),
        retornando a lista no formato 'DD/MM/YYYY HH:MM'.
        """
        result = []
        for dt_obj in clinicorp_slots:
            day_of_week = dt_obj.weekday()  # 0=Monday ... 6=Sunday
            day_map = {
                0: "monday",
                1: "tuesday",
                2: "wednesday",
                3: "thursday",
                4: "friday",
                5: "saturday",
                6: "sunday"
            }
            day_name = day_map[day_of_week]
            day_config = self.config.get(day_name, {})

            if not day_config.get('open', False):
                continue

            # Verifica período da manhã
            if day_config.get('morningEnabled'):
                try:
                    morning_start_hour, morning_start_min = map(int, day_config['morningStart'].split(":"))
                    morning_end_hour, morning_end_min = map(int, day_config['morningEnd'].split(":"))

                    morning_start = dt_obj.replace(hour=morning_start_hour, minute=morning_start_min)
                    morning_end = dt_obj.replace(hour=morning_end_hour, minute=morning_end_min)

                    if morning_start <= dt_obj < morning_end:
                        result.append(dt_obj.strftime("%d/%m/%Y %H:%M"))
                        continue
                except Exception as ee:
                    logger.warning(f"[SchedulingService] Erro horário da manhã: {ee}")

            # Verifica período da tarde
            if day_config.get('afternoonEnabled'):
                try:
                    aft_start_hour, aft_start_min = map(int, day_config['afternoonStart'].split(":"))
                    aft_end_hour, aft_end_min = map(int, day_config['afternoonEnd'].split(":"))

                    afternoon_start = dt_obj.replace(hour=aft_start_hour, minute=aft_start_min)
                    afternoon_end = dt_obj.replace(hour=aft_end_hour, minute=aft_end_min)

                    if afternoon_start <= dt_obj < afternoon_end:
                        result.append(dt_obj.strftime("%d/%m/%Y %H:%M"))
                except Exception as ee:
                    logger.warning(f"[SchedulingService] Erro horário da tarde: {ee}")

        # Ordenar por data real, não alfabeticamente
        def sort_key(slot_str):
            try:
                return datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
            except:
                return datetime.max

        return sorted(result, key=sort_key)

    def _get_internally_booked_slots(self, db: Session, start_range: datetime, end_range: datetime) -> Set[datetime]:

        """

        Consulta agendamentos internos DENTRO DO RANGE e interpreta

        o timestamp armazenado COMO SE FOSSE HORA LOCAL (SP_TZ), ignorando o TZ original.

        """ # <--- Docstring MUITO IMPORTANTE atualizada

        logger.info(f"[_get_internally_booked_slots] Buscando agendamentos internos para company_id={self.company_id} entre {start_range.isoformat()} e {end_range.isoformat()} e INTERPRETANDO COMO HORA LOCAL") # <--- Log atualizado

        booked_slots_set = set()



        try:

            # A query SQL permanece a mesma (sem filtro de status, conforme solicitado anteriormente)

            rows = db.execute(text("""

                SELECT consulta_data

                FROM agendamentos

                WHERE company_id = :cid

                  AND consulta_data >= :start

                  AND consulta_data < :end

            """), {"cid": self.company_id, "start": start_range, "end": end_range}).fetchall()



            for row in rows:

                consulta_dt_original = row.consulta_data # Ex: datetime(2025, 4, 28, 13, 0, tzinfo=timezone.utc)



                # *** LÓGICA MODIFICADA PARA IGNORAR TZ DO BANCO ***

                try:

                    # 1. Torna o datetime "naive" (sem timezone), mantendo os números H:M:S

                    naive_dt = consulta_dt_original.replace(tzinfo=None)

                    # 2. Atribui o timezone local (SP_TZ) a esses números H:M:S

                    dt_interpreted_as_local = naive_dt.replace(tzinfo=SP_TZ) # Para zoneinfo (Python >= 3.9)

                     # Se estivesse usando pytz, seria: dt_interpreted_as_local = SP_TZ.localize(naive_dt)



                    logger.debug(f"DEBUG: DB Original={repr(consulta_dt_original)} -> Interpretado como Local={repr(dt_interpreted_as_local)}")

                    booked_slots_set.add(dt_interpreted_as_local)

                except Exception as conversion_err:

                    logger.error(f"Erro ao reinterpretar timezone para {consulta_dt_original}: {conversion_err}")

                # *** FIM DA LÓGICA MODIFICADA ***



            logger.info(f"[_get_internally_booked_slots] Encontrados e interpretados {len(booked_slots_set)} slots internos.")

            return booked_slots_set



        except Exception as e:

            logger.error(f"[_get_internally_booked_slots] Erro ao buscar agendamentos internos: {e}", exc_info=True)

            return set()

    # --------------------------------------------------------------
    # Geração local de slots + remoção de indisponíveis
    # --------------------------------------------------------------
    def generate_available_slots(
        self,
        start_date: datetime,
        days_ahead: int = 7,  # agora padrão 7 dias
        unavailable_slots: Optional[List[Dict[str, datetime]]] = None
    ) -> List[str]:
        """
        Gera slots (manhã/tarde) para os próximos 'days_ahead' dias,
        removendo os que colidem com 'unavailable_slots'.
        """
        if unavailable_slots is None:
            unavailable_slots = []

        available_slots = []
        current_date = start_date

        logger.info(f"[generate_available_slots] Iniciando geração: start_date={start_date}, days_ahead={days_ahead}")
        logger.info(f"[generate_available_slots] Config de agendamento: {self.config}")

        for day_num in range(days_ahead):
            day_name = current_date.strftime("%A").lower()  # monday, tuesday, etc.
            day_config = self.config.get(day_name, {})

            logger.debug(f"[generate_available_slots] Dia {day_num+1}/{days_ahead}: {current_date.strftime('%d/%m/%Y')} ({day_name}), config={day_config}")

            if day_config.get('open', False):
                if day_config.get('morningEnabled', False):
                    try:
                        morning_start = current_date.replace(
                            hour=int(day_config['morningStart'].split(":")[0]),
                            minute=int(day_config['morningStart'].split(":")[1]),
                            second=0,
                            microsecond=0
                        )
                        morning_end = current_date.replace(
                            hour=int(day_config['morningEnd'].split(":")[0]),
                            minute=int(day_config['morningEnd'].split(":")[1]),
                            second=0,
                            microsecond=0
                        )
                        self._generate_period_slots(
                            morning_start,
                            morning_end,
                            unavailable_slots,
                            available_slots
                        )
                    except Exception as e:
                        logger.warning(f"[SchedulingService] Invalid morning config for {day_name}: {e}")

                if day_config.get('afternoonEnabled', False):
                    try:
                        afternoon_start = current_date.replace(
                            hour=int(day_config['afternoonStart'].split(":")[0]),
                            minute=int(day_config['afternoonStart'].split(":")[1]),
                            second=0,
                            microsecond=0
                        )
                        afternoon_end = current_date.replace(
                            hour=int(day_config['afternoonEnd'].split(":")[0]),
                            minute=int(day_config['afternoonEnd'].split(":")[1]),
                            second=0,
                            microsecond=0
                        )
                        self._generate_period_slots(
                            afternoon_start,
                            afternoon_end,
                            unavailable_slots,
                            available_slots
                        )
                    except Exception as e:
                        logger.warning(f"[SchedulingService] Invalid afternoon config for {day_name}: {e}")

            current_date += timedelta(days=1)

        logger.info(f"[generate_available_slots] Total de slots gerados: {len(available_slots)}")
        if available_slots:
            logger.info(f"[generate_available_slots] Primeiro slot: {available_slots[0] if available_slots else 'N/A'}")
            logger.info(f"[generate_available_slots] Último slot: {available_slots[-1] if available_slots else 'N/A'}")

        return available_slots

    def _is_slot_available(
        self,
        slot_dt: datetime,
        slot_end: datetime,
        unavailable_slots: List[Dict[str, Any]]
    ) -> bool:
        """
        Verifica se o slot (slot_dt -> slot_end) colide com algum período indisponível.
        """
        if slot_dt.tzinfo is None:
            slot_dt = slot_dt.replace(tzinfo=SP_TZ)
        if slot_end.tzinfo is None:
            slot_end = slot_end.replace(tzinfo=SP_TZ)

        slot_dt_utc = slot_dt.astimezone(timezone.utc)
        slot_end_utc = slot_end.astimezone(timezone.utc)

        for block in unavailable_slots:
            block_start = block["start"]
            block_end = block["end"]

            # Se block_start/block_end vierem como string, converte
            if isinstance(block_start, str):
                try:
                    block_start = datetime.strptime(block_start, "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)
                except ValueError:
                    logger.warning(f"Não foi possível parsear block_start={block_start}. Ignorando.")
                    continue

            if isinstance(block_end, str):
                try:
                    block_end = datetime.strptime(block_end, "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)
                except ValueError:
                    logger.warning(f"Não foi possível parsear block_end={block_end}. Ignorando.")
                    continue

            block_start_utc = block_start.astimezone(timezone.utc)
            block_end_utc = block_end.astimezone(timezone.utc)

            # Teste de sobreposição (A < B && X < Y)
            if slot_dt_utc < block_end_utc and block_start_utc < slot_end_utc:
                logger.debug(f"Slot {slot_dt} - {slot_end} BLOQUEADO por {block_start} - {block_end}")
                return False

        return True

    def _generate_period_slots(
        self,
        period_start: datetime,
        period_end: datetime,
        unavailable_slots: List[Dict[str, datetime]],
        available_slots: List[str]
    ) -> None:
        """
        Gera slots de 'consultation_duration' dentro do período [period_start, period_end),
        removendo os que colidem com 'unavailable_slots' ou que já passaram.
        """
        if period_start.tzinfo is None:
            period_start = period_start.replace(tzinfo=SP_TZ)
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=SP_TZ)

        # Verificar horário atual para slots de hoje
        now = datetime.now(SP_TZ)

        # Se o período começa hoje, ajustar para não gerar slots passados
        if period_start.date() == now.date() and period_start < now:
            # Ajustar para o próximo slot válido
            consult_duration = self.config.get('consultation_duration', 30)
            minutes_to_add = 0
            if now.minute % consult_duration != 0:
                minutes_to_add = consult_duration - (now.minute % consult_duration)

            # Novo período de início, arredondado para o próximo slot
            period_start = (now + timedelta(minutes=minutes_to_add)).replace(second=0, microsecond=0)
            logger.info(f"[SchedulingService] Ajustando período inicial para hoje: {period_start}")

            # Se o período inteiro já passou
            if period_start >= period_end:
                logger.info(f"[SchedulingService] Período inteiro já passou: {period_start} >= {period_end}")
                return

        consult_duration = self.config.get('consultation_duration', 30)
        slot_dt = period_start

        while slot_dt + timedelta(minutes=consult_duration) <= period_end:
            slot_end = slot_dt + timedelta(minutes=consult_duration)

            # Verificar se o slot já passou (redundante mas seguro)
            if slot_dt.date() == now.date() and slot_dt <= now:
                logger.debug(f"[SchedulingService] Slot já passou: {slot_dt.strftime('%d/%m/%Y %H:%M')}")
                slot_dt += timedelta(minutes=consult_duration)
                continue

            if self._is_slot_available(slot_dt, slot_end, unavailable_slots):
                slot_str = slot_dt.strftime("%d/%m/%Y %H:%M")
                available_slots.append(slot_str)
                logger.debug(f"[SchedulingService] Slot adicionado: {slot_str}")
            else:
                logger.debug(f"[SchedulingService] Slot bloqueado: {slot_dt.strftime('%d/%m/%Y %H:%M')}")

            slot_dt += timedelta(minutes=consult_duration)

    # --------------------------------------------------------------
    # Método principal para obter slots (7 dias)
    # --------------------------------------------------------------
    def get_next_available_slots(self) -> List[str]:
        """
        Retorna lista de slots disponíveis (no formato "DD/MM/YYYY HH:MM"),
        buscando diretamente da tabela company_slots no banco de dados.

        - Busca slots disponíveis dos próximos 30 dias
        - Filtra por data atual e validade
        - Retorna no formato esperado pelo sistema
        """
        logger.info(f"[SchedulingService] Buscando slots disponíveis no banco para company_id={self.company_id}")

        try:
            from backend.agents_sdk.tools.slots_service import SlotsService
            slots_service = SlotsService(self.db)

            # Busca slots disponíveis (máximo 30 slots, próximos 30 dias)
            slots = slots_service.get_available_slots(
                company_id=self.company_id,
                limit=30,
                days_ahead=30
            )

            logger.info(f"[SchedulingService] Encontrados {len(slots)} slots disponíveis para company_id={self.company_id}")

            # Registra a consulta no monitor
            slots_monitor.log_slots_query(
                company_id=self.company_id,
                slots_data=slots,
                query_context={
                    "source": "database",
                    "total_slots": len(slots)
                }
            )

            return slots

        except Exception as e:
            logger.error(f"[SchedulingService] Erro ao buscar slots no banco para company_id={self.company_id}: {e}")
            return []

    # ---------------------------------------------------------
    # Métodos auxiliares de formatação (opcionais)
    # ---------------------------------------------------------
    def format_available_slots(self, slots: List[str]) -> str:
        """
        Formata a lista de slots no estilo:
          Segunda-feira (31/01/2025), Daqui a X dias:
          - 08:30
          - 08:45
          ...
        """
        if not slots:
            return "Nenhum horário disponível no momento."

        organized = {}
        reference_date = datetime.now(SP_TZ).date()

        for slot_str in slots:
            try:
                dt_obj = datetime.strptime(slot_str, "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)
            except ValueError:
                continue

            date_key = dt_obj.strftime("%d/%m/%Y")
            if date_key not in organized:
                organized[date_key] = []
            organized[date_key].append(dt_obj)

        output_lines = ["Horários disponíveis nos próximos dias:"]

        for date_key, dt_list in sorted(organized.items()):
            dt_list.sort()
            if not dt_list:
                continue

            first_dt = dt_list[0]
            weekday_pt = self._format_weekday(first_dt)
            day_context = self._get_day_context(first_dt.date(), reference_date)

            output_lines.append(f"\n{weekday_pt} ({date_key}), {day_context}:")
            for slot_dt in dt_list:
                output_lines.append(f"- {slot_dt.strftime('%H:%M')}")

        output_lines.append("\nPara agendar, escolha um dos horários disponíveis.")
        return "\n".join(output_lines)

    def _format_weekday(self, dt: datetime) -> str:
        """Retorna o nome do dia da semana em português."""
        weekdays_pt = {
            0: "Segunda-feira",
            1: "Terça-feira",
            2: "Quarta-feira",
            3: "Quinta-feira",
            4: "Sexta-feira",
            5: "Sábado",
            6: "Domingo",
        }
        return weekdays_pt.get(dt.weekday(), "Desconhecido")

    def _get_day_context(self, slot_date: date, reference_date: date) -> str:
        """Retorna se é 'Hoje', 'Amanhã', 'Depois de amanhã' ou 'Daqui a X dias'."""
        days_diff = (slot_date - reference_date).days
        if days_diff == 0:
            return "Hoje"
        elif days_diff == 1:
            return "Amanhã"
        elif days_diff == 2:
            return "Depois de amanhã"
        else:
            return f"Daqui a {days_diff} dias"
