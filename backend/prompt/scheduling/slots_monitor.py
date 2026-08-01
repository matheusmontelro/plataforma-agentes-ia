import os
import json
from datetime import datetime
from typing import List, Dict, Any
from zoneinfo import ZoneInfo
from backend.runtime_settings import LOG_DIR

SP_TZ = ZoneInfo("America/Sao_Paulo")

class SlotsMonitor:
    """
    Monitor para registrar consultas de slots em arquivo .txt
    para debugs e análises de disponibilidade
    """

    def __init__(self, base_path: str | None = None):
        self.base_path = base_path
        self.logs_dir = str(
            LOG_DIR if base_path is None else os.path.join(base_path, "arquivos", "logs")
        )
        self._ensure_logs_dir()

    def _ensure_logs_dir(self):
        """Garante que o diretório de logs existe"""
        os.makedirs(self.logs_dir, exist_ok=True)

    def _get_log_filename(self, company_id: int) -> str:
        """Gera nome do arquivo de log para a empresa"""
        today = datetime.now(SP_TZ).strftime("%Y%m%d")
        return os.path.join(self.logs_dir, f"slots_monitor_company_{company_id}_{today}.txt")

    def log_slots_query(self,
                       company_id: int,
                       slots_data: List[str],
                       query_context: Dict[str, Any] = None):
        """
        Registra uma consulta de slots no arquivo de log

        Args:
            company_id: ID da empresa
            slots_data: Lista de slots disponíveis
            query_context: Contexto adicional da consulta (usuário, tipo, etc.)
        """
        try:
            timestamp = datetime.now(SP_TZ).strftime("%Y-%m-%d %H:%M:%S")
            log_filename = self._get_log_filename(company_id)

            # Prepara dados do contexto
            context_str = ""
            if query_context:
                context_items = []
                for key, value in query_context.items():
                    context_items.append(f"{key}={value}")
                context_str = f" | Contexto: {', '.join(context_items)}"

            # Filtra slots dos próximos 7 dias para análise
            next_7_days_slots = self._filter_next_7_days(slots_data)

            # Monta entrada do log
            log_entry = f"""
=== CONSULTA SLOTS ===
Timestamp: {timestamp}
Empresa ID: {company_id}
Total de slots: {len(slots_data)}
Slots próximos 7 dias: {len(next_7_days_slots)}{context_str}

Slots próximos 7 dias:
{self._format_slots_by_day(next_7_days_slots)}

Todos os slots (primeiros 50):
{', '.join(slots_data[:50])}{'...' if len(slots_data) > 50 else ''}

---
"""

            # Escreve no arquivo
            with open(log_filename, "a", encoding="utf-8") as f:
                f.write(log_entry)

        except Exception as e:
            # Log de erro em arquivo separado
            error_log = os.path.join(self.logs_dir, "slots_monitor_errors.txt")
            error_timestamp = datetime.now(SP_TZ).strftime("%Y-%m-%d %H:%M:%S")
            with open(error_log, "a", encoding="utf-8") as f:
                f.write(f"{error_timestamp} - Erro no SlotsMonitor para company_id {company_id}: {e}\n")

    def _filter_next_7_days(self, slots: List[str]) -> List[str]:
        """Filtra slots dos próximos 7 dias"""
        try:
            today = datetime.now(SP_TZ).date()
            next_7_days_slots = []

            for slot_str in slots:
                try:
                    slot_dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M").date()
                    days_diff = (slot_dt - today).days
                    if 0 <= days_diff <= 6:  # Próximos 7 dias
                        next_7_days_slots.append(slot_str)
                except ValueError:
                    continue

            return sorted(next_7_days_slots)
        except Exception:
            return []

    def _format_slots_by_day(self, slots: List[str]) -> str:
        """Formata slots agrupados por dia"""
        try:
            slots_by_day = {}

            for slot_str in slots:
                try:
                    date_part = slot_str.split(" ")[0]
                    time_part = slot_str.split(" ")[1]

                    if date_part not in slots_by_day:
                        slots_by_day[date_part] = []
                    slots_by_day[date_part].append(time_part)
                except (IndexError, ValueError):
                    continue

            formatted_lines = []
            for date, times in sorted(slots_by_day.items()):
                day_name = self._get_day_name(date)
                formatted_lines.append(f"  {date} ({day_name}): {', '.join(sorted(times))}")

            return '\n'.join(formatted_lines) if formatted_lines else "  Nenhum slot encontrado"

        except Exception:
            return "  Erro ao formatar slots"

    def _get_day_name(self, date_str: str) -> str:
        """Retorna nome do dia da semana"""
        try:
            dt = datetime.strptime(date_str, "%d/%m/%Y")
            days = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
            return days[dt.weekday()]
        except:
            return "N/A"

    def log_redis_cache_status(self, company_id: int, has_cache: bool, cache_size: int = 0):
        """Registra status do cache Redis"""
        try:
            timestamp = datetime.now(SP_TZ).strftime("%Y-%m-%d %H:%M:%S")
            log_filename = self._get_log_filename(company_id)

            status = "ENCONTRADO" if has_cache else "NÃO ENCONTRADO"
            cache_info = f" ({cache_size} slots)" if has_cache else ""

            log_entry = f"""
=== STATUS CACHE REDIS ===
Timestamp: {timestamp}
Empresa ID: {company_id}
Cache: {status}{cache_info}
---
"""

            with open(log_filename, "a", encoding="utf-8") as f:
                f.write(log_entry)

        except Exception as e:
            pass  # Ignora erros de log do cache

    def get_daily_stats(self, company_id: int) -> Dict[str, Any]:
        """Retorna estatísticas do dia para a empresa"""
        try:
            log_filename = self._get_log_filename(company_id)

            if not os.path.exists(log_filename):
                return {"queries": 0, "file_exists": False}

            with open(log_filename, "r", encoding="utf-8") as f:
                content = f.read()

            query_count = content.count("=== CONSULTA SLOTS ===")
            cache_checks = content.count("=== STATUS CACHE REDIS ===")
            file_size = os.path.getsize(log_filename)

            return {
                "queries": query_count,
                "cache_checks": cache_checks,
                "file_size": file_size,
                "file_exists": True,
                "log_file": log_filename
            }

        except Exception:
            return {"queries": 0, "file_exists": False, "error": True}

# Instância global para uso fácil
slots_monitor = SlotsMonitor()
