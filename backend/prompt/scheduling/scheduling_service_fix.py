"""
Correção para o SchedulingService
=================================

Este arquivo contém a correção para filtrar slots passados
ao ler do cache Redis.
"""

from datetime import datetime, timedelta
from typing import List
import logging

logger = logging.getLogger(__name__)


def create_fixed_get_next_available_slots(scheduling_service):
    """
    Cria uma versão corrigida de get_next_available_slots que filtra
    slots que já passaram.
    """
    original_method = scheduling_service.get_next_available_slots

    def fixed_get_next_available_slots() -> List[str]:
        """
        Versão corrigida que filtra slots passados.
        """
        # Chama o método original
        all_slots = original_method()

        if not all_slots:
            return []

        # Filtra slots passados
        now = datetime.now(scheduling_service.company_tz)
        valid_slots = []

        for slot_str in all_slots:
            try:
                # Parse do slot no formato "DD/MM/YYYY HH:MM"
                slot_dt = datetime.strptime(slot_str, "%d/%m/%Y %H:%M")
                # Para ZoneInfo, usa replace com o timezone
                slot_dt = slot_dt.replace(tzinfo=scheduling_service.company_tz)

                # Só inclui se for futuro (com margem de 1 hora)
                if slot_dt > now + timedelta(hours=1):
                    valid_slots.append(slot_str)

            except ValueError as e:
                logger.warning(f"[SchedulingService] Erro ao parsear slot '{slot_str}': {e}")
                continue

        logger.info(f"[SchedulingService] Filtrado {len(all_slots)} slots do cache para {len(valid_slots)} slots válidos (futuros)")

        # Log de debug se muitos slots foram filtrados
        filtered_count = len(all_slots) - len(valid_slots)
        if filtered_count > 10:
            logger.warning(f"[SchedulingService] ATENÇÃO: {filtered_count} slots passados foram filtrados do cache!")

            # Mostra alguns exemplos dos slots filtrados
            past_slots = []
            for slot_str in all_slots[:5]:
                if slot_str not in valid_slots:
                    past_slots.append(slot_str)

            if past_slots:
                logger.warning(f"[SchedulingService] Exemplos de slots passados removidos: {past_slots}")

        # Ordena os slots válidos cronologicamente
        valid_slots.sort(key=lambda x: datetime.strptime(x, "%d/%m/%Y %H:%M"))

        return valid_slots

    return fixed_get_next_available_slots


def patch_scheduling_service():
    """
    Exemplo de código para aplicar o filtro a qualquer workspace.
    """
    return '''
# Após criar o SchedulingService, aplica a correção
from backend.prompt.scheduling.scheduling_service_fix import create_fixed_get_next_available_slots

scheduling = SchedulingService(db, company_id)
scheduling.get_next_available_slots = create_fixed_get_next_available_slots(scheduling)
logger.info("[SchedulingService] Aplicado filtro de slots passados")
'''


# Importação necessária (adicionar no topo do arquivo original)
from datetime import timedelta
