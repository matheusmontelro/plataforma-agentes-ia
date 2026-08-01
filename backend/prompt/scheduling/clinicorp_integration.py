"""Módulo para integração com a API da Clinicorp, obtendo horários
disponíveis em uma data específica ou em um intervalo de datas.
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class ClinicorpIntegration:
    """
    Classe responsável por consultar a API da Clinicorp e obter
    horários disponíveis em um determinado dia ou intervalo de dias.
    """

    BASE_URL = "https://api.clinicorp.com/rest/v1/appointment/get_avaliable_times_calendar/"

    def __init__(
        self,
        code_link: str,
        subscriber_id: str,
        username: str,
        password: str
    ):
        """
        :param code_link: Valor da coluna clinicorp_code_link no BD.
        :param subscriber_id: Valor da coluna clinicorp_subscriber_id no BD.
        :param username: Valor da coluna clinicorp_username no BD.
        :param password: Valor da coluna clinicorp_password no BD.
        """
        self.code_link = code_link
        self.subscriber_id = subscriber_id
        self.username = username
        self.password = password

    def get_available_times(self, date_str: str) -> List[Dict[str, str]]:
        """
        Consulta a API da Clinicorp para obter horários disponíveis
        em uma data específica (formato 'YYYY-MM-DD').

        Exemplo de resposta:
            [
                {"From": "10:00", "To": "10:30"},
                {"From": "10:30", "To": "11:00"},
                ...
            ]

        :param date_str: Data no formato 'YYYY-MM-DD'.
        :return: Lista de dicionários, cada um representando um slot, ou lista vazia em caso de erro/sem slots.
        """
        logger.info(f"[Clinicorp] Buscando horários disponíveis para {date_str}...")

        params = {
            "code_link": self.code_link,
            "subscriber_id": self.subscriber_id,
            "date": date_str
        }

        try:
            response = requests.get(
                self.BASE_URL,
                params=params,
                auth=(self.username, self.password),
                timeout=(60, 60)
            )
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"[Clinicorp] Resposta para {date_str}: {data}")
                # Normalmente a API retorna uma lista de slots [{"From": "...", "To": "..."} ...]
                return data if isinstance(data, list) else []
            else:
                logger.warning(
                    f"[Clinicorp] Erro {response.status_code} ao buscar horários para {date_str}. "
                    f"Resposta: {response.text}"
                )
                return []
        except requests.exceptions.RequestException as e:
            logger.error(f"[Clinicorp] Exceção ao consultar API para {date_str}: {e}")
            return []

    def get_available_times_for_range(self, start_date: date, days: int = 30) -> List[Dict[str, str]]:
        """
        Obtém horários disponíveis para um intervalo de 'days' dias,
        iniciando em 'start_date'.

        :param start_date: Data inicial (objeto date).
        :param days: Número de dias a serem consultados (padrão = 30).
        :return: Lista de dicionários com todos os slots concatenados.
        """
        logger.info(f"[Clinicorp] Buscando horários disponíveis de {start_date} até {start_date + timedelta(days=days - 1)}...")
        all_slots: List[Dict[str, str]] = []

        for i in range(days):
            dia = start_date + timedelta(days=i)
            date_str = dia.strftime("%Y-%m-%d")
            slots_dia = self.get_available_times(date_str)
            # Se necessário, pode-se anotar a data em cada slot (slot["date"] = date_str) antes de extender
            all_slots.extend(slots_dia)

        logger.info(f"[Clinicorp] Total de slots obtidos para {days} dias a partir de {start_date}: {len(all_slots)}")
        return all_slots

    def get_available_times_next_30_days(self) -> List[Dict[str, str]]:
        """
        Retorna horários disponíveis para os próximos 30 dias,
        contando a partir de HOJE.

        :return: Lista de dicionários com os slots de todos os dias consultados.
        """
        hoje = date.today()
        logger.info("[Clinicorp] Obtendo horários para os próximos 30 dias, iniciando hoje.")
        return self.get_available_times_for_range(start_date=hoje, days=30)
