# Scheduling Tools for Agents SDK
import logging
import json
from datetime import datetime, timedelta
import pytz
from agents import function_tool, RunContextWrapper, Agent, Runner, ModelSettings
from ..config.company_context import CompanyContext

logger = logging.getLogger(__name__)
SP_TZ = pytz.timezone('America/Sao_Paulo')

@function_tool
async def buscar_horarios_disponiveis(wrapper: RunContextWrapper[CompanyContext], preferencia: str = None) -> str:
    """
    Busca horários disponíveis para agendamento.

    Args:
        preferencia: Preferência opcional do usuário (ex: "sábado", "manhã", "próxima semana")

    IMPORTANTE: Salva automaticamente os slots oferecidos no estado da conversa.
    """
    context = wrapper.context

    if not context.scheduling_service:
        return "Serviço de agendamento não disponível no momento."

    try:
        # Busca TODOS os slots disponíveis
        all_slots = context.scheduling_service.get_next_available_slots()

        if not all_slots:
            return "Não há horários disponíveis no momento. Por favor, entre em contato pelo WhatsApp."

        # Se tem preferência, filtra os slots
        if preferencia:
            logger.info(f"[SchedulingTool] Analisando preferência: {preferencia}")

            # Análise simples da preferência
            preferencia_lower = preferencia.lower()
            filtered_slots = []

            # Mapeamento de dias da semana
            weekday_map = {
                "segunda": 0, "segunda-feira": 0,
                "terça": 1, "terça-feira": 1, "terca": 1,
                "quarta": 2, "quarta-feira": 2,
                "quinta": 3, "quinta-feira": 3,
                "sexta": 4, "sexta-feira": 4,
                "sábado": 5, "sabado": 5,
                "domingo": 6
            }

            # Verifica se é dia da semana
            target_weekday = None
            for day, weekday_num in weekday_map.items():
                if day in preferencia_lower:
                    target_weekday = weekday_num
                    break

            # Verifica se é período do dia
            target_period = None
            if "manhã" in preferencia_lower or "manha" in preferencia_lower:
                target_period = "manhã"
            elif "tarde" in preferencia_lower:
                target_period = "tarde"
            elif "noite" in preferencia_lower:
                target_period = "noite"

            # Filtra slots
            for slot in all_slots:
                try:
                    # Suporte para slots com metadata ou string simples
                    if isinstance(slot, dict):
                        slot_string = slot["slot"]
                        metadata = slot.get("metadata", {})
                    else:
                        slot_string = slot
                        metadata = {}

                    dt = datetime.strptime(slot_string, "%d/%m/%Y %H:%M")
                    dt_localized = SP_TZ.localize(dt)

                    # Filtro por dia da semana usando metadata se disponível
                    if target_weekday is not None:
                        # Usa metadata se disponível
                        if metadata and "weekday_name" in metadata:
                            weekday_names_pt = {
                                0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
                                3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
                            }
                            expected_weekday = weekday_names_pt.get(target_weekday)
                            if metadata["weekday_name"] != expected_weekday:
                                continue
                        else:
                            # Fallback para cálculo manual
                            if dt.weekday() != target_weekday:
                                continue

                    # Filtro por período usando metadata se disponível
                    if target_period:
                        if metadata and "time_period" in metadata:
                            # Usa metadata se disponível
                            metadata_period = metadata["time_period"].lower()
                            if target_period == "manhã" and metadata_period != "manha":
                                continue
                            elif target_period == "tarde" and metadata_period != "tarde":
                                continue
                            elif target_period == "noite" and metadata_period != "noite":
                                continue
                        else:
                            # Fallback para cálculo manual
                            hour = dt.hour
                            if target_period == "manhã" and not (6 <= hour < 12):
                                continue
                            elif target_period == "tarde" and not (12 <= hour < 18):
                                continue
                            elif target_period == "noite" and not (18 <= hour < 22):
                                continue

                    # Só inclui se passou em todos os filtros (sempre retorna string)
                    filtered_slots.append(slot_string)
                except:
                    continue

            if filtered_slots:
                # Limita a 10 slots
                slots_to_show = filtered_slots[:10]
                extra_msg = ""
                logger.info(f"[SchedulingTool] Encontrados {len(filtered_slots)} slots para preferência '{preferencia}'")
            else:
                # Se não encontrou slots com a preferência, usa diversificação
                logger.info(f"[SchedulingTool] Nenhum slot encontrado para preferência '{preferencia}'")
                from ..utils.slot_utils import smart_slot_selection
                slots_to_show = smart_slot_selection(all_slots, limit=10)
                extra_msg = f"\n\n💡 Não encontrei horários {preferencia}. Aqui estão outras opções:"
        else:
            # Sem preferência: usa diversificação inteligente
            from ..utils.slot_utils import smart_slot_selection
            slots_to_show = smart_slot_selection(all_slots, limit=10)
            extra_msg = ""

        if not slots_to_show:
            return "Não há horários disponíveis no momento. Por favor, entre em contato pelo WhatsApp."

        # 🎯 SALVA OS SLOTS OFERECIDOS NO ESTADO DA CONVERSA
        state_manager = await context.get_state_manager()
        await state_manager.set_offered_slots(slots_to_show)
        logger.info(f"[SchedulingTool] Salvou {len(slots_to_show)} slots oferecidos no estado")

        # Formata os horários para exibição
        formatted_slots = []
        for slot in slots_to_show:
            try:
                dt = datetime.strptime(slot, "%d/%m/%Y %H:%M")
                weekday = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][dt.weekday()]
                formatted_slots.append(f"• {weekday} {dt.strftime('%d/%m às %H:%M')}")
            except:
                formatted_slots.append(f"• {slot}")

        response = f"Horários disponíveis{extra_msg}:\n" + "\n".join(formatted_slots)
        return response

    except Exception as e:
        logger.error(f"Erro ao buscar horários: {e}")
        return "Ocorreu um erro ao buscar os horários. Por favor, tente novamente."


@function_tool
async def analyze_scheduling_intent(wrapper: RunContextWrapper[CompanyContext], user_message: str) -> str:
    """
    Analisa semanticamente a intenção do usuário em relação ao agendamento.
    Usa o poder do LLM para entender a mensagem em vez de regex.

    Args:
        user_message: Mensagem do usuário para análise
    """
    # Obtém contexto temporal atual
    context = wrapper.context
    current_dt = datetime.now(SP_TZ)

    # Prepara informações temporais para o LLM
    weekdays_pt = {
        0: "segunda-feira", 1: "terça-feira", 2: "quarta-feira",
        3: "quinta-feira", 4: "sexta-feira", 5: "sábado", 6: "domingo"
    }

    current_weekday = weekdays_pt[current_dt.weekday()]
    current_date = current_dt.strftime("%d/%m/%Y")
    current_time = current_dt.strftime("%H:%M")

    tomorrow = current_dt + timedelta(days=1)
    tomorrow_weekday = weekdays_pt[tomorrow.weekday()]
    tomorrow_date = tomorrow.strftime("%d/%m/%Y")

    # Cria prompt para análise semântica
    analysis_prompt = f"""
    Analise a seguinte mensagem e extraia a intenção de agendamento.

    CONTEXTO TEMPORAL:
    - Hoje é {current_weekday}, {current_date} às {current_time}
    - Amanhã será {tomorrow_weekday}, {tomorrow_date}

    MENSAGEM DO USUÁRIO: "{user_message}"

    Identifique e retorne em formato JSON:
    1. has_scheduling_request: se há pedido de agendamento (true/false)
    2. temporal_reference: referência temporal ("hoje", "amanhã", "próxima_semana", etc)
    3. specific_date: data específica se mencionada (formato DD/MM/YYYY)
    4. weekday: dia da semana específico ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
    5. period: período do dia ("manhã", "tarde", "noite")
    6. time_constraint: restrição de horário ({{"type": "before/after", "time": "HH:MM"}})
    7. urgency: nível de urgência ("urgente", "normal", "flexível")
    8. flexibility: flexibilidade ("alta", "normal", "baixa")

    Exemplos:
    - "tem amanhã?" → temporal_reference: "amanhã", specific_date: "{tomorrow_date}"
    - "tem pra hoje?" → temporal_reference: "hoje", urgency: "urgente"
    - "pode ser depois das 14h" → time_constraint: {{"type": "after", "time": "14:00"}}
    - "tem sábado?" → weekday: "sábado"
    - "prefiro pela manhã" → period: "manhã"

    Retorne APENAS o JSON, sem explicações.
    """

    # Usa um mini-agent para análise
    analyzer = Agent(
        name="intent_analyzer",
        instructions="Você é um analisador de intenções. Retorne apenas JSON válido.",
        model="gpt-4.1-mini-2025-04-14",
        model_settings=ModelSettings(
            temperature=0.1,
            max_tokens=200
        )
    )

    try:
        result = await Runner.run(
            agent=analyzer,
            input=analysis_prompt
        )

        if result and result.final_output:
            # Tenta parsear o JSON retornado
            intent_data = json.loads(result.final_output)

            # Adiciona campo has_scheduling_request se não existir
            if "has_scheduling_request" not in intent_data:
                intent_data["has_scheduling_request"] = any([
                    intent_data.get("temporal_reference"),
                    intent_data.get("specific_date"),
                    intent_data.get("period"),
                    "horário" in user_message.lower(),
                    "agendar" in user_message.lower(),
                    "marcar" in user_message.lower()
                ])

            return json.dumps(intent_data, ensure_ascii=False)
        else:
            # Fallback para análise básica
            return json.dumps({
                "has_scheduling_request": False,
                "error": "Falha na análise"
            }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Erro na análise semântica: {e}")
        # Retorna análise básica em caso de erro
        return json.dumps({
            "has_scheduling_request": any(word in user_message.lower()
                for word in ["tem", "horário", "agendar", "marcar", "consulta", "quando", "disponível"]),
            "temporal_reference": None,
            "specific_date": None,
            "period": None,
            "time_constraint": None,
            "urgency": "normal",
            "flexibility": "normal"
        }, ensure_ascii=False)


@function_tool
async def filter_slots_by_intent(wrapper: RunContextWrapper[CompanyContext], intent_json: str) -> str:
    """
    Filtra slots disponíveis baseado na intenção identificada do usuário.
    Usa algoritmos inteligentes para encontrar os melhores horários.

    Args:
        intent_json: JSON com a intenção analisada do usuário
    """
    context = wrapper.context

    try:
        intent = json.loads(intent_json)
    except:
        return json.dumps({"error": "Intenção inválida"}, ensure_ascii=False)

    # Obtém todos os slots disponíveis
    if not context.available_slots:
        return json.dumps({"slots": [], "message": "Nenhum horário disponível"}, ensure_ascii=False)

    all_slots = context.available_slots
    filtered_slots = []

    # Obtém data/hora atual
    current_dt = datetime.now(SP_TZ)
    tomorrow_start = current_dt.replace(hour=0, minute=0, second=0) + timedelta(days=1)

    # Converte slots para datetime para facilitar filtragem
    slot_datetimes = []
    for slot in all_slots:
        try:
            # Suporte para slots com metadata ou string simples
            if isinstance(slot, dict):
                slot_string = slot["slot"]
                metadata = slot.get("metadata", {})
            else:
                slot_string = slot
                metadata = {}

            dt = datetime.strptime(slot_string, "%d/%m/%Y %H:%M")
            dt = SP_TZ.localize(dt)
            # Só considera slots a partir de amanhã
            if dt >= tomorrow_start:
                slot_datetimes.append((dt, slot_string, metadata))
        except:
            continue

    # Ordena por proximidade temporal (mais próximos primeiro)
    slot_datetimes.sort(key=lambda x: x[0])

    # Filtra por data específica
    if intent.get("specific_date"):
        target_date = datetime.strptime(intent["specific_date"], "%d/%m/%Y").date()
        slot_datetimes = [(dt, slot_string, metadata) for dt, slot_string, metadata in slot_datetimes if dt.date() == target_date]

    # Filtra por dia da semana
    elif intent.get("weekday"):
        weekday_map = {
            "segunda": 0, "terça": 1, "quarta": 2, "quinta": 3,
            "sexta": 4, "sábado": 5, "domingo": 6
        }
        target_weekday = weekday_map.get(intent["weekday"])
        if target_weekday is not None:
            weekday_names_pt = {
                0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
                3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
            }
            expected_weekday = weekday_names_pt.get(target_weekday)

            filtered_slots = []
            for dt, slot_string, metadata in slot_datetimes:
                # Usa metadata se disponível
                if metadata and "weekday_name" in metadata:
                    if metadata["weekday_name"] == expected_weekday:
                        filtered_slots.append((dt, slot_string, metadata))
                else:
                    # Fallback para cálculo manual
                    if dt.weekday() == target_weekday:
                        filtered_slots.append((dt, slot_string, metadata))
            slot_datetimes = filtered_slots

    # Filtra por período do dia
    if intent.get("period"):
        target_period = intent["period"].lower()
        filtered_slots = []
        for dt, slot_string, metadata in slot_datetimes:
            # Usa metadata se disponível
            if metadata and "time_period" in metadata:
                metadata_period = metadata["time_period"].lower()
                if target_period == "manhã" and metadata_period == "manha":
                    filtered_slots.append((dt, slot_string, metadata))
                elif target_period == "tarde" and metadata_period == "tarde":
                    filtered_slots.append((dt, slot_string, metadata))
                elif target_period == "noite" and metadata_period == "noite":
                    filtered_slots.append((dt, slot_string, metadata))
            else:
                # Fallback para cálculo manual
                period_filters = {
                    "manhã": lambda dt: dt.hour < 12,
                    "tarde": lambda dt: 12 <= dt.hour < 18,
                    "noite": lambda dt: dt.hour >= 18
                }
                filter_func = period_filters.get(target_period)
                if filter_func and filter_func(dt):
                    filtered_slots.append((dt, slot_string, metadata))
        slot_datetimes = filtered_slots

    # Aplica preferências de horário
    for pref in intent.get("preferences", []):
        if pref.startswith("próximo_de_"):
            target_time = pref.replace("próximo_de_", "")
            try:
                target_hour, target_minute = map(int, target_time.split(":"))
                # Ordena por proximidade ao horário desejado
                slot_datetimes.sort(key=lambda x: abs(
                    x[0].hour * 60 + x[0].minute - (target_hour * 60 + target_minute)
                ))
            except:
                pass

    # Prioriza por urgência
    if intent.get("urgency") == "urgente":
        # Pega apenas slots das próximas 48 horas
        cutoff = datetime.now(SP_TZ) + timedelta(hours=48)
        slot_datetimes = [(dt, slot_string, metadata) for dt, slot_string, metadata in slot_datetimes if dt <= cutoff]

    # Limita resultados baseado na flexibilidade
    max_results = {
        "alta": 15,  # Mais opções para quem é flexível
        "normal": 10,
        "baixa": 5   # Menos opções para quem tem restrições
    }.get(intent.get("flexibility", "normal"), 10)

    # Aplica estratégia de diversificação se muitos resultados
    if len(slot_datetimes) > max_results:
        # Agrupa por dia e pega alguns de cada
        slots_by_day = {}
        for dt, slot_string, metadata in slot_datetimes:
            day_key = dt.date()
            if day_key not in slots_by_day:
                slots_by_day[day_key] = []
            slots_by_day[day_key].append((dt, slot_string, metadata))

        # Distribui slots entre os dias
        slots_per_day = max(2, max_results // len(slots_by_day)) if slots_by_day else max_results

        for day in sorted(slots_by_day.keys())[:7]:  # Máximo 7 dias
            day_slots = slots_by_day[day]
            # Pega slots distribuídos no dia
            morning = [s for s in day_slots if s[0].hour < 12]
            afternoon = [s for s in day_slots if s[0].hour >= 12]

            if morning:
                filtered_slots.extend([s[1] for s in morning[:slots_per_day//2]])
            if afternoon:
                filtered_slots.extend([s[1] for s in afternoon[:slots_per_day//2]])

            if len(filtered_slots) >= max_results:
                break
    else:
        # Se poucos resultados, pega todos
        filtered_slots = [slot_string for _, slot_string, _ in slot_datetimes]

    # Prepara resposta com metadados úteis
    response = {
        "slots": filtered_slots[:max_results],
        "total_found": len(slot_datetimes),
        "applied_filters": [],
        "suggestions": []
    }

    # Adiciona informações sobre filtros aplicados
    if intent.get("specific_date"):
        response["applied_filters"].append(f"Data: {intent['specific_date']}")
    if intent.get("weekday"):
        response["applied_filters"].append(f"Dia: {intent['weekday']}")
    if intent.get("period"):
        response["applied_filters"].append(f"Período: {intent['period']}")

    # Adiciona sugestões se poucos resultados
    if len(filtered_slots) < 3:
        response["suggestions"].append("Tente ampliar sua busca para outros dias ou períodos")
        if intent.get("period"):
            response["suggestions"].append("Considere outros períodos do dia")

    return json.dumps(response, ensure_ascii=False)