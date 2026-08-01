import logging
import os
import json
import redis
from datetime import datetime, timedelta # <--- Adicionar/Verificar
from zoneinfo import ZoneInfo # <--- Adicionar
from typing import Set # <--- Adicionar (se não estiver presente)
from backend.db import SessionLocal
from backend.worker.celery_app import app
from backend.prompt.scheduling.scheduling_service import SchedulingService
from sqlalchemy.sql import text

logger = logging.getLogger(__name__)

# --- Definir ou Importar SP_TZ ---
# Opção A: Definir localmente (se não for compartilhado/importado de outro lugar)
SP_TZ = ZoneInfo("America/Sao_Paulo")
# Opção B: Se SP_TZ já estiver definido em scheduling_service.py, importe-o
# from backend.prompt.scheduling.scheduling_service import SP_TZ
# Escolha a opção que fizer mais sentido para a organização do seu código.

@app.task
def update_one_company_availabilities(company_id: int):
    """
    Task que efetivamente busca as disponibilidades/indisponibilidades
    para a empresa 'company_id' usando as integrações (Google, Clinicorp),
    e salva no Redis (chave: availability:{company_id}).

    Esta versão utiliza uma abordagem de "atualização atômica" para evitar
    perda de dados durante a atualização.
    """
    db = SessionLocal()
    try:
        logger.info(f"[update_one_company_availabilities] Iniciando atualização para company_id={company_id}")

        # Configuração do Redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = redis.from_url(redis_url)
        key_name = f"availability:{company_id}"
        temp_key_name = f"availability_temp:{company_id}"

        # Primeiro, verifica se já existe um cache válido
        existing_data = redis_client.get(key_name)

        # Busca novos dados
        service = SchedulingService(db, company_id)
        slots = service.fetch_availabilities_from_integrations()

        # --- INÍCIO DA VERIFICAÇÃO INTERNA ---

        try:

            logger.info(f"[update_one_company_availabilities] Iniciando verificação interna para company_id={company_id}")



            start_range = datetime.now(SP_TZ)

            end_range = start_range + timedelta(days=30)



            # 1. Buscar slots agendados internamente

            booked_datetimes = service._get_internally_booked_slots(db, start_range, end_range) # Retorna Set[datetime]

            logger.info(f"DEBUG: booked_datetimes (interno): {booked_datetimes}") # LOG DETALHADO DO SET INTERNO



            # 2. Converter slots externos (List[str]) para Set[datetime]

            potential_external_slots = set()

            for slot_str in slots:

                try:

                    dt_obj = datetime.strptime(slot_str, "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)

                    potential_external_slots.add(dt_obj)

                except ValueError:

                    logger.warning(f"[update_one_company_availabilities] Ignorando slot inválido: {slot_str}")

            logger.info(f"DEBUG: potential_external_slots (externo): {potential_external_slots}") # LOG DETALHADO DO SET EXTERNO



            # *** LOGS ESPECÍFICOS PARA O SLOT PROBLEMÁTICO ***

            target_dt_str = "28/04/2025 13:00"

            try:

                target_dt_obj = datetime.strptime(target_dt_str, "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)



                is_in_external = target_dt_obj in potential_external_slots

                is_in_booked = target_dt_obj in booked_datetimes

                logger.info(f"DEBUG: Slot {target_dt_str} ({repr(target_dt_obj)}) está em potential_external_slots? {is_in_external}")

                logger.info(f"DEBUG: Slot {target_dt_str} ({repr(target_dt_obj)}) está em booked_datetimes? {is_in_booked}")



                # Logar a representação exata se encontrado nos sets

                for ext_dt in potential_external_slots:

                    if ext_dt.date() == target_dt_obj.date() and ext_dt.hour == target_dt_obj.hour and ext_dt.minute == target_dt_obj.minute:

                        logger.info(f"DEBUG: Representação exata em potential_external_slots: {repr(ext_dt)}")

                for book_dt in booked_datetimes:

                    if book_dt.date() == target_dt_obj.date() and book_dt.hour == target_dt_obj.hour and book_dt.minute == target_dt_obj.minute:

                        logger.info(f"DEBUG: Representação exata em booked_datetimes: {repr(book_dt)}")

            except Exception as log_err:

                logger.error(f"DEBUG: Erro ao logar detalhes do slot {target_dt_str}: {log_err}")

            # *** FIM DOS LOGS ESPECÍFICOS ***



            # 3. Filtrar

            truly_available_datetimes = potential_external_slots - booked_datetimes

            logger.info(f"DEBUG: Tamanho de potential_external_slots: {len(potential_external_slots)}")

            logger.info(f"DEBUG: Tamanho de booked_datetimes: {len(booked_datetimes)}")

            logger.info(f"DEBUG: Tamanho de truly_available_datetimes (após diferença): {len(truly_available_datetimes)}")



            # 4. Converter de volta para lista de strings ordenada

            final_slots_list = sorted([dt.strftime("%d/%m/%Y %H:%M") for dt in truly_available_datetimes])

            logger.debug(f"DEBUG: final_slots_list (antes de salvar no Redis): {final_slots_list[:20]}...") # Logar início da lista final



            logger.info(f"[update_one_company_availabilities] Verificação interna concluída. Slots disponíveis finais: {len(final_slots_list)}")



        except Exception as verification_error:

            # LOG MELHORADO NO ERRO

            logger.error(f"[update_one_company_availabilities] ERRO CRÍTICO durante verificação interna para company_id={company_id}: {verification_error}", exc_info=True)

            final_slots_list = slots # Mantém fallback, mas agora logamos o erro

        # --- FIM DA VERIFICAÇÃO INTERNA ---

        # Salva os novos dados em uma chave temporária primeiro
        redis_client.set(temp_key_name, json.dumps(final_slots_list), ex=3600)  # TTL de 1 hora para a chave temporária

        # Se for a primeira vez (não havia dados), apenas renomeia a chave
        if not existing_data:
            redis_client.rename(temp_key_name, key_name)
            redis_client.expire(key_name, 3600)  # TTL de 1 hora
            logger.info(f"[update_one_company_availabilities] Criados {len(final_slots_list)} slots no cache p/ company_id={company_id}")
        else:
            # Se já existiam dados, mescla os dados antigos com os novos
            # (isso depende da lógica específica do seu negócio -
            # aqui estou apenas substituindo, mas você pode implementar uma mesclagem)
            redis_client.rename(temp_key_name, key_name)
            redis_client.expire(key_name, 3600)  # TTL de 1 hora
            logger.info(f"[update_one_company_availabilities] Atualizados {len(final_slots_list)} slots no cache p/ company_id={company_id}")

    except Exception as e:
        logger.error(f"[update_one_company_availabilities] Erro ao atualizar {company_id}: {e}", exc_info=True)
    finally:
        db.close()

@app.task
def update_all_companies_availabilities():
    """
    Task que itera sobre TODAS as empresas que usam Google/Clinicorp,
    disparando a task 'update_one_company_availabilities' para cada uma.
    """
    db = SessionLocal()
    try:
        logger.info("[update_all_companies_availabilities] Iniciando atualização de TODAS as empresas.")

        # Selecionar todas as companies que tenham provider google ou clinicorp
        rows = db.execute(text("""
            SELECT DISTINCT company_id
              FROM calendar_integrations
             WHERE provider IN ('google','clinicorp')
        """))
        company_ids = [r[0] for r in rows]

        logger.info(f"[update_all_companies_availabilities] Encontradas {len(company_ids)} empresas a atualizar.")

        for cid in company_ids:
            # Disparo assíncrono (worker Celery executa em background)
            update_one_company_availabilities.delay(cid)

        logger.info("[update_all_companies_availabilities] Disparo de atualizações concluído.")

    except Exception as e:
        logger.error(f"[update_all_companies_availabilities] Erro ao atualizar todas as empresas: {e}", exc_info=True)
    finally:
        db.close()

# Classe auxiliar (opcional) para implementar uma mesclagem mais sofisticada
class CacheManager:
    """
    Gerenciador para operações de cache relacionadas ao agendamento.
    Implementa lógicas mais complexas como mesclagem inteligente de dados.
    """

    def __init__(self, redis_client):
        self.redis = redis_client

    def merge_availability_data(self, old_data_json, new_data_json):
        """
        Mescla dados antigos e novos de disponibilidade.

        Implementação depende da estrutura específica dos seus dados.
        Este é apenas um exemplo baseado em slots de data/hora.
        """
        if not old_data_json:
            return new_data_json

        try:
            old_data = json.loads(old_data_json)
            new_data = json.loads(new_data_json)

            # Converte listas para sets para facilitar operações
            old_set = set(old_data)
            new_set = set(new_data)

            # Mantém slots antigos que não estão no novo conjunto
            # (isso pode variar conforme sua regra de negócio)
            old_valid = old_set - new_set

            # Resultado final: mantém slots antigos válidos + todos os novos
            result = list(old_valid.union(new_set))

            return json.dumps(result)
        except Exception as e:
            logging.error(f"Erro ao mesclar dados: {e}")
            # Em caso de erro, usa os novos dados
            return new_data_json