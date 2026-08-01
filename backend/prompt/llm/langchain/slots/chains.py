"""
Chains LangChain para Processamento de Agendamento
=================================================

Define as chains sequenciais para cada etapa do processo.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging

from langchain.chains import LLMChain, TransformChain, SequentialChain
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from langchain.callbacks.manager import CallbackManagerForChainRun

from .models import SchedulingIntent, SlotSelection, SlotInfo
from .utils import parse_slot_datetime, get_period_from_hour, get_weekday_name_pt

logger = logging.getLogger(__name__)


def create_intent_detection_chain(
    llm: Optional[ChatOpenAI] = None,
    callbacks: Optional[list] = None
) -> LLMChain:
    """
    Chain para detectar intenção de agendamento na mensagem do usuário.

    Args:
        llm: Modelo LLM a usar (default: gpt-4.1-mini-2025-04-14)
        callbacks: Lista de callbacks

    Returns:
        LLMChain configurada para detecção de intenção
    """
    if not llm:
        llm = ChatOpenAI(
            model="gpt-4.1-mini-2025-04-14",
            temperature=0.1,  # Baixa temperatura para consistência
            callbacks=callbacks
        )

    # Parser para output estruturado
    parser = PydanticOutputParser(pydantic_object=SchedulingIntent)

    # Template do prompt
    system_template = """Você é um especialista em análise de intenções de agendamento.
Analise a mensagem do usuário e o contexto da conversa para extrair informações sobre agendamento.

IMPORTANTE: Você DEVE retornar APENAS um objeto JSON válido, sem nenhum texto adicional antes ou depois.

Data/Hora atual: {current_datetime}
Dia da semana atual: {current_weekday}

REFERÊNCIAS TEMPORAIS IMPORTANTES:
- "semana que vem" ou "próxima semana" = dias entre {next_week_start} e {next_week_end}
- "esse mês" = qualquer dia até {end_of_month}
- "próximo mês" = dias entre {next_month_start} e {next_month_end}
- "amanhã" = {tomorrow_date}
- "depois de amanhã" = {day_after_tomorrow}

RESTRIÇÕES DE HORÁRIO PRÉ-EXTRAÍDAS:
{extracted_time_constraints}

Se há restrições pré-extraídas, USE-AS diretamente no time_constraints.

PERÍODOS DO DIA:
- "Manhã" ou "de manhã" = preferred_period: "morning" (06:00-11:59)
- "Tarde" = preferred_period: "afternoon" (12:00-17:59)
- "Final da tarde" ou "fim do dia" = preferred_period: "evening" (17:00-20:00)
- "Noite" = preferred_period: "night" (18:00-21:00)

DIAS DA SEMANA:
- Segunda = 0, Terça = 1, Quarta = 2, Quinta = 3, Sexta = 4, Sábado = 5, Domingo = 6

IMPORTANTE:
- Use as datas calculadas fornecidas
- Use as restrições de horário pré-extraídas quando disponíveis
- NÃO refaça cálculos de data/hora que já foram fornecidos
- Se mencionar "semana que vem", defina preferred_date com a segunda-feira da próxima semana
- Se mencionar "próximo [dia]", calcule a data correta
- extraction_reasoning deve explicar como interpretou as referências temporais

{format_instructions}"""

    human_template = """Histórico recente da conversa:
{conversation_history}

Mensagem atual do usuário: {user_message}

Extraia a intenção de agendamento com base na mensagem atual, considerando o contexto do histórico."""

    # Monta o prompt
    prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(system_template),
        HumanMessagePromptTemplate.from_template(human_template)
    ])

    # Cria a chain
    chain = LLMChain(
        llm=llm,
        prompt=prompt,
        output_parser=parser,
        output_key="scheduling_intent"
    )

    return chain


def create_slot_filtering_chain() -> TransformChain:
    """
    Chain de transformação para filtrar slots baseado na intenção.

    Returns:
        TransformChain para filtragem de slots
    """

    def filter_slots(inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Função de transformação que filtra slots"""
        intent: SchedulingIntent = inputs["scheduling_intent"]
        all_slots: List[str] = inputs["available_slots"]

        logger.info(f"Filtrando {len(all_slots)} slots baseado na intenção")

        # Converte slots para objetos SlotInfo
        slot_infos = []
        now = datetime.now()

        for slot_str in all_slots:
            try:
                dt = parse_slot_datetime(slot_str)
                if not dt:
                    continue

                slot_info = SlotInfo(
                    datetime_obj=dt,
                    formatted_string=slot_str,
                    period=get_period_from_hour(dt.hour),
                    day_of_week=dt.weekday(),
                    day_name_pt=get_weekday_name_pt(dt.weekday()),
                    is_today=(dt.date() == now.date()),
                    is_tomorrow=(dt.date() == (now + timedelta(days=1)).date()),
                    days_from_today=(dt.date() - now.date()).days
                )
                slot_infos.append(slot_info)

            except Exception as e:
                logger.warning(f"Erro ao processar slot {slot_str}: {e}")
                continue

        # Aplica filtros baseados na intenção
        filtered_slots = slot_infos
        filters_applied = []

        # Filtro por data específica
        if intent.preferred_date:
            target_date = intent.preferred_date.date()
            date_filtered = [s for s in filtered_slots if s.datetime_obj.date() == target_date]

            if date_filtered:
                filtered_slots = date_filtered
                filters_applied.append(f"Data específica: {target_date}")
            else:
                # Fallback: busca datas próximas
                for delta in range(1, intent.date_flexibility_days + 1):
                    for direction in [1, -1]:  # Futuro e passado
                        check_date = target_date + timedelta(days=delta * direction)
                        if check_date < now.date():  # Não permite datas passadas
                            continue

                        nearby_slots = [s for s in slot_infos if s.datetime_obj.date() == check_date]
                        if nearby_slots:
                            filtered_slots = nearby_slots
                            filters_applied.append(f"Data próxima: {check_date} (±{delta} dias)")
                            break
                    if filtered_slots != slot_infos:
                        break

        # Filtro por dia da semana
        elif intent.preferred_day_of_week is not None:
            dow_filtered = [s for s in filtered_slots if s.day_of_week == intent.preferred_day_of_week]
            if dow_filtered:
                filtered_slots = dow_filtered
                filters_applied.append(f"Dia da semana: {intent.preferred_day_of_week}")

        # Filtro por período
        if intent.preferred_period and len(filtered_slots) > 2:
            period_filtered = [s for s in filtered_slots if s.period == intent.preferred_period]
            if period_filtered:
                filtered_slots = period_filtered
                filters_applied.append(f"Período: {intent.preferred_period}")

        # Filtro por restrições de horário
        if intent.time_constraints:
            tc = intent.time_constraints

            if tc.earliest_time:
                time_filtered = [s for s in filtered_slots
                               if s.datetime_obj.time() >= tc.earliest_time]
                if time_filtered:
                    filtered_slots = time_filtered
                    filters_applied.append(f"Após: {tc.earliest_time}")

            if tc.latest_time:
                time_filtered = [s for s in filtered_slots
                               if s.datetime_obj.time() <= tc.latest_time]
                if time_filtered:
                    filtered_slots = time_filtered
                    filters_applied.append(f"Antes: {tc.latest_time}")

        # Calcula scores de compatibilidade
        for slot in filtered_slots:
            score = 1.0

            # Penaliza por distância temporal
            if intent.preferred_date:
                days_diff = abs((slot.datetime_obj.date() - intent.preferred_date.date()).days)
                score -= (days_diff * 0.1)  # -0.1 por dia de diferença

            # Bonus por urgência
            if intent.urgency_level == "high" and slot.days_from_today <= 2:
                score += 0.2
            elif intent.urgency_level == "low" and slot.days_from_today > 7:
                score += 0.1

            slot.compatibility_score = max(0.0, min(1.0, score))

        # Ordena por score e proximidade
        filtered_slots.sort(key=lambda s: (-s.compatibility_score, s.days_from_today))

        # Monta resultado
        result = SlotSelection(
            selected_slots=filtered_slots,  # Retorna todos os filtrados
            total_available=len(all_slots),
            total_filtered=len(filtered_slots),
            filters_applied=filters_applied,
            used_fallback=len(filters_applied) > 1 and any("próxima" in f for f in filters_applied),
            fallback_reason="Não encontrou slots na data exata" if len(filters_applied) > 1 else None,
            suggested_count=len(filtered_slots)  # Ajusta contagem
        )

        return {"slot_selection": result}

    return TransformChain(
        input_variables=["scheduling_intent", "available_slots"],
        output_variables=["slot_selection"],
        transform=filter_slots
    )


def create_slot_suggestion_chain(
    llm: Optional[ChatOpenAI] = None,
    callbacks: Optional[list] = None
) -> LLMChain:
    """
    Chain para formatar sugestões de horários de forma natural.

    Args:
        llm: Modelo LLM a usar
        callbacks: Lista de callbacks

    Returns:
        LLMChain para gerar texto de sugestão
    """
    if not llm:
        llm = ChatOpenAI(
            model="gpt-4.1-mini-2025-04-14",
            temperature=0.7,
            callbacks=callbacks
        )

    system_template = """Você é um assistente de agendamento amigável.
Com base nos slots filtrados e no contexto, sugira {suggested_count} horários de forma natural e conversacional.

Regras importantes:
1. SEMPRE sugira exatamente {suggested_count} horários, nem mais nem menos
2. Use o formato: "dia (DD/MM) às HH:MM"
3. Seja natural, mas conciso
4. Se houver poucos slots disponíveis, mencione isso
5. Inclua o raciocínio da sugestão quando relevante"""

    human_template = """Slots disponíveis após filtros:
{available_slots_info}

Intenção do usuário:
{user_intent_summary}

Filtros aplicados: {filters_applied}
Usou fallback: {used_fallback}

Sugira {suggested_count} horários de forma natural."""

    prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(system_template),
        HumanMessagePromptTemplate.from_template(human_template)
    ])

    chain = LLMChain(
        llm=llm,
        prompt=prompt,
        output_key="suggestion_text"
    )

    return chain


def create_scheduling_chain(
    llm: Optional[ChatOpenAI] = None,
    callbacks: Optional[list] = None
) -> SequentialChain:
    """
    Cria a chain completa de agendamento.

    Args:
        llm: Modelo LLM a usar
        callbacks: Lista de callbacks

    Returns:
        SequentialChain completa para processamento de agendamento
    """

    # Chains individuais
    intent_chain = create_intent_detection_chain(llm, callbacks)
    filter_chain = create_slot_filtering_chain()
    suggestion_chain = create_slot_suggestion_chain(llm, callbacks)

    # Chain sequencial
    overall_chain = SequentialChain(
        chains=[intent_chain, filter_chain, suggestion_chain],
        input_variables=[
            "user_message",
            "conversation_history",
            "current_datetime",
            "current_weekday",
            "available_slots",
            "suggested_count"
        ],
        output_variables=[
            "scheduling_intent",
            "slot_selection",
            "suggestion_text"
        ],
        verbose=True  # Para debugging
    )

    return overall_chain