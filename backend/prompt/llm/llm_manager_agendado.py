
import os
import logging
from typing import Dict, Any, List
import re
import json
from sqlalchemy import text
import pytz
from dotenv import load_dotenv
from sqlalchemy.orm import Session
import tiktoken

# Novas importações
from langchain_openai import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableSequence

# Importamos a função que já retorna tudo escapado!
from ..db_integration.agent_config import get_agent_config_dict
from ..scheduling.scheduling_service import SchedulingService, SP_TZ
from ..memory.memory_manager import get_chat_history
from ..db_integration.agendamento_logic import processar_json_do_llm
from datetime import datetime, timedelta, date

# Nova arquitetura
from .states.state_machine import ConversationStateMachine
from .states.transitions import process_step_transition
from .states.step_definitions import get_step_definition

# Parser Chain (se quiser extrair dados do user_input via LLM)
from .parser_chain import create_extraction_chain, parse_user_input_with_llm, LLMUserData
from backend.prompt.llm.parser_chain import create_extraction_chain, parse_user_input_with_llm, LLMUserData
from backend.prompt.db_integration.agendamento_logic import processar_cancelamento

from backend.prompt.llm.states.cancelamento_flow import handle_cancellation_request
from backend.prompt.llm.states.reagendamento_flow import handle_reschedule_request
from backend.services.ai_provider_service import get_company_openai_api_key

# Contexto
from .states.customer_context import get_customer_context, format_customer_context_for_prompt

logger = logging.getLogger(__name__)

load_dotenv()
Z_API_PHONE = os.getenv("Z_API_PHONE", "")  # Número do assistente

def create_llm_chain_with_memory(
    db: Session,
    company_id: int,
    contact_phone: str,
    unavailable_times: List[Dict[str, str]] = [],
    available_slots: List[str] = None,  # NOVO: parâmetro para receber slots
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = "",
    lead_history: Dict = None,
    slot_request: Dict = None  # NOVO: Adicionamos parâmetro para a solicitação do slot
):
    """
    Cria um LLMChain com memória de conversação otimizada.

    Agora pode receber parâmetros extras:
    - msg_category: categoria prevista pelo modelo scikit-learn
    - funnel_stage: etapa do funil em que o lead se encontra (leads, agendamentos, comparecimentos, vendas)
    - funnel_status: status específico se estiver em agendamentos (ex: SCHEDULED, NO_SHOW)
    - slot_request: critérios de filtragem para slots

    Todo o restante do código foi mantido inalterado, exceto a adição dessas variáveis para uso no template.
    """
    logger.info(f"[LLMManager Agendado] Iniciando create_llm_chain_with_memory "
                f"(company_id={company_id}, contact_phone={contact_phone})")

    try:
        # 1) Obter configurações
        config_data = get_agent_config_dict(db, company_id)
        if not config_data:
            msg = f"[LLMManager Agendado] Não foram encontradas configurações para company_id={company_id}."
            logger.error(msg)
            raise ValueError(msg)

        #logger.info(f"[LLMManager Agendado] Configurações obtidas do agent_config: {config_data}")

        # 2) Instanciar o serviço de agendamento e obter slots disponíveis
        if available_slots is None:
            scheduling = SchedulingService(db, company_id)
            available_slots = scheduling.get_next_available_slots()

        # MUDANÇA IMPORTANTE: Filtrar slots ANTES de limitar
        if slot_request and slot_request.get("has_request"):
            # Filtra os slots de acordo com os critérios
            filtered_slots = get_filtered_slots(db, company_id, available_slots, slot_request)
            logger.info(f"[LLMManager Agendado] Filtrando {len(available_slots)} slots originais para {len(filtered_slots)} slots")
        else:
            # Se não há solicitação específica, usa todos os slots
            filtered_slots = available_slots

        # Agora limitamos APÓS a filtragem
        max_slots_in_prompt = 40  # Ajuste este valor conforme necessidade
        if len(filtered_slots) > max_slots_in_prompt:
            logger.info(f"[LLMManager Agendado] Limitando de {len(filtered_slots)} para {max_slots_in_prompt} slots no prompt")
            filtered_slots = filtered_slots[:max_slots_in_prompt]

        # Slots disponíveis para o prompt serão os filtrados
        slots_for_prompt = filtered_slots

        # 3) Carregar histórico do lead como lista de HumanMessage / AIMessage
        chat_history = get_chat_history(contact_phone=contact_phone, company_id=company_id)
        #logger.info(f"[LLMManager Agendado] Histórico de conversa para {contact_phone}: {chat_history}")

        # 4) Extrair seções do JSON (já escapado)
        assistant_identity   = config_data.get("assistant_identity", {})
        company_info          = config_data.get("company_info", {})
        team_and_specialties = config_data.get("team_and_specialties", {})
        scheduling_config    = config_data.get("scheduling_config", {})
        financial_config     = config_data.get("financial_config", {})
        conversation_flow    = config_data.get("conversation_flow", {})

        # 5) Variáveis do assistant_identity
        assistantName           = assistant_identity.get("assistant_name", "")
        assistantRole           = assistant_identity.get("assistant_role", "")
        assistantResponsibility = assistant_identity.get("assistant_responsibility", "")
        assistantTone           = assistant_identity.get("assistant_tone", "")
        assistantFormality      = assistant_identity.get("assistant_formality", "")
        assistantLanguage       = assistant_identity.get("assistant_language", "")

        # Dados do Financial Config
        payment_info = financial_config.get('payment_info', '')
        installment_conditions = financial_config.get('installment_conditions', '')
        treatment_prices = financial_config.get('treatment_prices', '')
        accepts_health_insurance = financial_config.get('accepts_health_insurance', False)
        health_insurance_plans = financial_config.get('health_insurance_plans', '')
        evaluation_price = financial_config.get('evaluation_price', '')

        # Dados do Conversation Flow
        step0 = conversation_flow.get('step0', '')
        step1First = conversation_flow.get('step1First', '')
        step1Second = conversation_flow.get('step1Second', '')
        step2 = conversation_flow.get('step2', '')
        step3 = conversation_flow.get('step3', '')

        # Dados dos redirecionamentos
        regular_redirect = conversation_flow.get('regular_redirect', {}).get('number', '')
        financial_redirect = conversation_flow.get('financial_redirect', {}).get('number', '')
        maintenance_redirect = conversation_flow.get('maintenance_redirect', {}).get('number', '')
        active_customers_redirect = conversation_flow.get('active_customers_redirect', {}).get('number', '')

        #logger.info(f"[LLMManager Agendado] assistantName={assistantName}, "
                    #f"assistantRole={assistantRole}, responsibility={assistantResponsibility}")

        # 6) Variáveis do company_info
        companyName      = company_info.get("company_name", "")
        companyLocation  = company_info.get("company_location", "")
        companyAddress   = company_info.get("company_address", "")
        companyPhoneFixed= company_info.get("company_phone_fixed", "")
        companyWhatsApp  = company_info.get("company_whatsapp", "")
        companyMaps      = company_info.get("company_maps", "")
        companyInstagram = company_info.get("company_instagram", "")
        companyFacebook  = company_info.get("company_facebook", "")
        companySite      = company_info.get("company_site", "")
        companyHistory   = company_info.get("company_history", "")

        # 7) Funções auxiliares de formatação
        def format_treatments(treatments_list: list) -> str:
            if not isinstance(treatments_list, list) or not treatments_list:
                return "Informações sobre tratamentos não disponíveis"

            formatted_treatments = []
            for treatment in treatments_list:
                if isinstance(treatment, dict):
                    title = treatment.get('treatmentTitle', 'Sem título')
                    desc = treatment.get('description', 'Sem descrição')
                    formatted_treatments.append(f"- {title}: {desc}")

            if not formatted_treatments:
                return "Informações sobre tratamentos não disponíveis"

            return "\n".join(formatted_treatments)

        def format_schedule_str(scheduling_config: dict) -> str:
            schedule_str = ""
            for day, config in scheduling_config.items():
                if day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                    if config.get('open'):
                        day_pt = {
                            'monday': 'Segunda-feira',
                            'tuesday': 'Terça-feira',
                            'wednesday': 'Quarta-feira',
                            'thursday': 'Quinta-feira',
                            'friday': 'Sexta-feira',
                            'saturday': 'Sábado',
                            'sunday': 'Domingo'
                        }[day]

                        periods = []
                        if config.get('morningEnabled'):
                            periods.append(f"Manhã: {config['morningStart']} às {config['morningEnd']}")
                        if config.get('afternoonEnabled'):
                            periods.append(f"Tarde: {config['afternoonStart']} às {config['afternoonEnd']}")

                        if periods:
                            schedule_str += f"{day_pt}: {' e '.join(periods)}\n"

            return schedule_str

        def format_financial(fin_config: dict) -> str:
            if not isinstance(fin_config, dict):
                return "Informações financeiras não disponíveis"

            sections = []
            if payment_info := fin_config.get('payment_info'):
                sections.append(f"Informações de pagamento: {payment_info}")

            payment_methods = fin_config.get('payment_methods', [])
            if payment_methods and payment_methods != ['']:
                methods_str = ", ".join(payment_methods)
                sections.append(f"Formas de pagamento aceitas: {methods_str}")

            if installment_info := fin_config.get('installment_info'):
                sections.append(f"Informações de parcelamento: {installment_info}")

            if treatment_prices := fin_config.get('treatment_prices'):
                sections.append(f"Preços dos tratamentos: {treatment_prices}")

            if price_explanation := fin_config.get('price_explanation'):
                sections.append(f"Explicação sobre preços: {price_explanation}")

            accepts_insurance = fin_config.get('accepts_health_insurance', False)
            sections.append(f"Aceita convênios: {'Sim' if accepts_insurance else 'Não'}")

            return "\n".join(sections) if sections else "Informações financeiras não disponíveis"

        def format_conversation_flow(conv_flow: dict) -> str:
            if not isinstance(conv_flow, dict):
                return "Fluxo de conversação não disponível"

            sections = []

            # Steps da conversação
            steps = []
            for i in range(4):
                step = conv_flow.get(f'step{i}')
                if step:
                    steps.append(f"Passo {i}: {step}")
            if steps:
                sections.append("Passos da conversa:")
                sections.extend(steps)

            # Redirecionamentos
            redirects = {
                'regular_redirect':     'Redirecionamento padrão',
                'financial_redirect':   'Redirecionamento financeiro',
                'maintenance_redirect': 'Redirecionamento manutenção',
                'active_customers_redirect': 'Redirecionamento clientes ativos'
            }

            redirect_info = []
            for key, label in redirects.items():
                redirect = conv_flow.get(key)
                if redirect:
                    redirect_type   = redirect.get('type', '')
                    redirect_number = redirect.get('number', '')
                    if redirect_type and redirect_number:
                        redirect_info.append(f"{label}: {redirect_type} - {redirect_number}")

            if redirect_info:
                sections.append("\nRedirecionamentos:")
                sections.extend(redirect_info)

            return "\n".join(sections) if sections else "Fluxo de conversação não disponível"

        def format_few_shots(few_shots: list) -> str:
            if not isinstance(few_shots, list) or not few_shots:
                return "Sem exemplos de conversas disponíveis"

            formatted_shots = []
            for shot in few_shots:
                if isinstance(shot, dict):
                    user_msg = shot.get('userMessage', '')
                    bot_msg  = shot.get('botResponse', '')
                    obj_type = shot.get('objectionType', '')

                    formatted_shot = f"Usuário: {user_msg}\n"
                    formatted_shot += f"Assistente: {bot_msg}\n"
                    if obj_type:
                        formatted_shot += f"Tipo de objeção: {obj_type}"

                    formatted_shots.append(formatted_shot)

            if not formatted_shots:
                return "Sem exemplos de conversas disponíveis"

            return "\n\n".join(formatted_shots)

        technical_responsible = team_and_specialties.get("technical_responsible", "")
        treatments_str        = format_treatments(team_and_specialties.get("treatments", []))
        schedule_str          = format_schedule_str(scheduling_config)
        financial_str         = format_financial(financial_config)
        conversation_flow_str = format_conversation_flow(conversation_flow)
        fewShots_str          = format_few_shots(conversation_flow.get("few_shots", []))
        max_tokens_in_db      = conversation_flow.get("max_tokens", 1000)

        #logger.info(f"[LLMManager Agendado] technicalResponsible={technical_responsible}, treatments_str={treatments_str}")
        #logger.info(f"[LLMManager Agendado] schedule_str={schedule_str}")
        #logger.info(f"[LLMManager Agendado] financial_str={financial_str}")
        #logger.info(f"[LLMManager Agendado] conversation_flow_str={conversation_flow_str}")
        #logger.info(f"[LLMManager Agendado] max_tokens_in_db={max_tokens_in_db}, fewShots_str={fewShots_str}")

        # 8) Formatadores para indisponíveis e disponíveis
        def format_unavailable_times(times: List[Dict[str, str]]) -> str:
            if not times:
                return "Nenhum horário indisponível."
            return "\n".join(f"- {t['start']} até {t['end']}" for t in times)

        def format_available_slots_by_period(
            slots: list[str],
            scheduling_config: dict,
            days_ahead: int = 30
        ) -> str:
            """
            Formata a lista de slots no estilo:

            Segunda-feira (DD/MM/YYYY) amanhã:
            Manhã:
            - HH:mm
            - HH:mm
            Tarde:
            - HH:mm
            - HH:mm

            Terça-feira (DD/MM/YYYY) depois de amanhã:
            FECHADO

            ...
            Se `open=False` no config, também mostra FECHADO.
            """

            from datetime import datetime, timedelta
            import logging
            logger = logging.getLogger(__name__)

            # Se não houver NENHUM slot, retorna mensagem genérica
            if not slots:
                return "Nenhum horário disponível no momento."

            # 1) Converte os slots em datetime e separa em {day_obj: {"morning": [...], "afternoon": [...]}}
            slots_by_day = {}
            for slot_str in slots:
                try:
                    # Correção defensiva: se slot_str for dict, extrai a string
                    if isinstance(slot_str, dict):
                        slot_str = slot_str.get("slot", str(slot_str))
                    dt = datetime.strptime(str(slot_str), "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)
                except ValueError:
                    logger.warning(f"Erro ao parsear slot_str='{slot_str}'")
                    continue

                day_obj = dt.date()
                if day_obj not in slots_by_day:
                    slots_by_day[day_obj] = {"morning": [], "afternoon": []}

                # Se for antes de meio-dia => morning, senão afternoon
                if dt.hour < 12:
                    slots_by_day[day_obj]["morning"].append(dt)
                else:
                    slots_by_day[day_obj]["afternoon"].append(dt)

            # 2) Geramos a lista de dias do intervalo (hoje até days_ahead).
            #    Se preferir "a partir de amanhã", use `+ timedelta(days=1)`.
            today = datetime.now(SP_TZ).date()
            # Se quiser começar a exibir "a partir de amanhã":
            # today = today + timedelta(days=1)

            # Mapeamento do dia da semana em PT-BR
            weekdays_pt = {
                0: "Segunda-feira",
                1: "Terça-feira",
                2: "Quarta-feira",
                3: "Quinta-feira",
                4: "Sexta-feira",
                5: "Sábado",
                6: "Domingo",
            }

            output_lines = []

            for i in range(days_ahead):
                day_obj = today + timedelta(days=i)
                weekday_idx = day_obj.weekday()
                weekday_pt = weekdays_pt.get(weekday_idx, "Desconhecido")
                date_str = day_obj.strftime("%d/%m/%Y")

                # Descobrimos quantos dias de diferença para exibir "amanhã", "depois de amanhã", etc.
                days_diff = (day_obj - today).days
                if days_diff == 0:
                    context = "hoje"
                elif days_diff == 1:
                    context = "amanhã"
                elif days_diff == 2:
                    context = "depois de amanhã"
                else:
                    context = f"daqui a {days_diff} dias"

                # Monta o cabeçalho ex.: "Segunda-feira (27/02/2025) amanhã:"
                header = f"{weekday_pt} ({date_str}) {context}:"
                output_lines.append(header)

                # Verifica se o dia está 'open' no config:
                day_name_en = weekday_pt.lower()  # ex.: "segunda-feira" => para mapear 'monday'?
                # Caso precise mapear por 'monday', 'tuesday'... adeque aqui:
                # Por ex. se scheduling_config tem chaves 'monday','tuesday', etc.,
                # precisamos converter 'segunda-feira' -> 'monday'.
                # Uma forma simples: crie um dict:
                day_map_en = {
                    "segunda-feira": "monday",
                    "terça-feira": "tuesday",
                    "quarta-feira": "wednesday",
                    "quinta-feira": "thursday",
                    "sexta-feira": "friday",
                    "sábado": "saturday",
                    "domingo": "sunday"
                }
                day_config_key = day_map_en.get(weekday_pt.lower(), "")
                day_cfg = scheduling_config.get(day_config_key, {})

                # Se open=False, já marcamos FECHADO e pula
                if not day_cfg.get("open", False):
                    output_lines.append("Dia indisponível pra agendamento\n")
                    continue

                # Se open=True, pegamos slots
                day_slots = slots_by_day.get(day_obj, {"morning": [], "afternoon": []})
                morning_slots = sorted(day_slots["morning"])
                afternoon_slots = sorted(day_slots["afternoon"])

                # Se não houver nada => FECHADO
                if not morning_slots and not afternoon_slots:
                    output_lines.append("Horário Indisponível\n")
                    continue

                # Senão, lista Manhã e Tarde
                if morning_slots:
                    output_lines.append("Manhã:")
                    for dt_obj in morning_slots:
                        output_lines.append(f"- {dt_obj.strftime('%H:%M')}")

                if afternoon_slots:
                    output_lines.append("Tarde:")
                    for dt_obj in afternoon_slots:
                        output_lines.append(f"- {dt_obj.strftime('%H:%M')}")

                output_lines.append("")  # quebra de linha no final de cada dia

            # Se ao final não tiver nada, retorna genérico
            if len(output_lines) <= 1:  # Significa que não teve slot
                return "Nenhum horário disponível no momento."

            return "\n".join(output_lines)

            # Ordenar as chaves (date_header) por data real, não somente por string
            def extract_sort_key(header: str):
                try:
                    left_part = header.split(" (")[1]
                    date_str  = left_part.split("),")[0]
                    dt_obj = datetime.strptime(date_str.strip(), "%d/%m/%Y")
                    return dt_obj
                except:
                    return datetime.min  # Fallback se der erro no parse

            sorted_headers = sorted(slots_by_day.keys(), key=extract_sort_key)

            for header in sorted_headers:
                formatted_output.append(f"\n{header}:")
                # Ordena as horas daquele dia
                day_slots = sorted(slots_by_day[header])
                for dt in day_slots:
                    hour_str = dt.strftime("%H:%M")
                    part_of_day = "manhã" if dt.hour < 12 else "tarde"
                    formatted_output.append(f"- {hour_str} ({part_of_day})")

            formatted_output.append("\nPara agendar, escolha um dos horários disponíveis.")
            return "\n".join(formatted_output)

        # 9) Montar 'unavailable_str' e 'available_str'
        unavailable_str = format_unavailable_times(unavailable_times)
        available_str = format_available_slots_by_period(
            available_slots,
            scheduling_config=scheduling_config
        )

        # --- INÍCIO DA MODIFICAÇÃO ---
        # Adiciona este log para vermos a string exata que vai para o prompt
        logger.info(f"[LLMManager Agendado] Conteúdo de 'available_str' formatado para o prompt:\n{available_str}")
        # --- FIM DA MODIFICAÇÃO ---

        # 10) Montar carimbo "hoje é Segunda-feira (02/01/2025) 09:35"
        now_dt = datetime.now(SP_TZ)
        weekday_pt_map = {
            0: "Segunda-feira",
            1: "Terça-feira",
            2: "Quarta-feira",
            3: "Quinta-feira",
            4: "Sexta-feira",
            5: "Sábado",
            6: "Domingo"
        }
        today_weekday = weekday_pt_map[now_dt.weekday()]
        today_str     = now_dt.strftime("%d/%m/%Y %H:%M")
        today_info    = f"{today_weekday} ({today_str})"

        # 11) Criar a memória
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )

        if chat_history:
            logger.info(f"[LLMManager Agendado] Carregando {len(chat_history)} mensagens no chat_history...")
            for msg in chat_history:
                memory.chat_memory.add_message(msg)
        else:
            logger.info("[LLMManager Agendado] Nenhum chat_history recebido (ou vazio).")

        # 11.5) Obter e formatar contexto do cliente
        customer_context = get_customer_context(db, contact_phone, company_id)
        formatted_customer_context = format_customer_context_for_prompt(customer_context)
        etapa_do_script_from_context = customer_context.get('etapa_do_script', 0)
        logger.info(f"[LLMManager Agendado] [CLIENTE] CONTEXTO DO CLIENTE:\n{formatted_customer_context}")

        # 12) Template do sistema
        SYSTEM_TEMPLATE = rf"""

        # Persona e Responsabilidade Essencial
        Você é {assistantName}, {assistantRole} da {companyName}. Atue como um humano conversando.
        Sua principal responsabilidade nesta interação é: **Confirmar a presença do cliente na consulta JÁ AGENDADA e auxiliá-lo com dúvidas, reagendamentos ou cancelamentos.** O cliente já passou pela fase inicial de agendamento.

        # Contexto Atual
        - Hoje é {today_info}.
        - Categoria da Mensagem: {msg_category}
        - Etapa do Funil: {funnel_stage} (Foco: AGENDAMENTO CONFIRMADO)
        - Status no Funil: {funnel_status}
        - Contexto do Cliente (incluindo consulta atual): {formatted_customer_context}
        - **IMPORTANTE: Consulta Agendada:** O cliente tem uma consulta marcada nos detalhes informados em 'Contexto do Cliente' acima. Use esta informação (data/hora) ao se referir à consulta dele!

        # Objetivo Principal da Interação
        Seu objetivo é garantir que o cliente **compareça** à consulta agendada. As interações podem envolver:
        1.  **Confirmação de Presença:** Verificar se o cliente mantém a intenção de vir.
        2.  **Tirar Dúvidas:** Responder perguntas sobre a consulta, preparo, localização, etc.
        3.  **Reagendamento:** Processar solicitações de mudança de data/hora, SE NECESSÁRIO.
        4.  **Cancelamento:** Processar solicitações de cancelamento, SE NECESSÁRIO.

        **NÃO trate este cliente como um novo lead. NÃO tente agendar uma consulta inicial, pois ele JÁ TEM UMA.**

        # Fluxo da Conversa Esperado
        1.  **Saudação e Confirmação:** Comece cumprimentando e perguntando no que pode ajudar (A data/hora da consulta está em `{formatted_customer_context}`). **NÃO consulte a lista de horários disponíveis `{available_str}` para confirmar o horário atual do cliente.**
        2.  **Resposta Positiva:** Tire dúvidas, forneça o endereço (`{companyAddress}, {companyLocation}`), link do Maps (`{companyMaps}`). Ou o que o usuário desejar.
        3.  **Pedido de Reagendamento:** Se o cliente indicar que não pode comparecer e desejar remarcar:
            * Mostre compreensão.
            * Pergunte qual o melhor dia ou período para ele(a).
            * **APLIQUE AS REGRAS DE REAGENDAMENTO ABAIXO.**
        4.  **Pedido de Cancelamento:** Se o cliente solicitar cancelamento:
            * Confirme o cancelamento.
            * Se apropriado e sutilmente, pergunte se gostaria de deixar uma data futura em aberto ou se há algo mais em que a empresa possa ajudar.
        5.  **Dúvidas:** Responda às dúvidas utilizando as `# INFORMAÇÕES DA EMPRESA`.
        6.  Se o cliente somente agradecer ou pedir informações gerais, responda cordialmente sem tentar reagendar ou confirmar novamente se não for necessário.
        7.  Se o cliente tiver somente tirando dúvidas ou agradecendo, responda adequadamente de acordo com o contexto e NUNCA pergunte ou insinue sobre agendamento perguntando sobre horários ou dias.

        # REGRAS DE REAGENDAMENTO (Aplicar SOMENTE SE o cliente pedir para remarcar)
        1.  **Entenda a Lista de Horários Disponíveis:** A lista `{available_str}` contém apenas os horários que estão **atualmente livres** na agenda. O horário atual do cliente (`{formatted_customer_context}`) **NÃO estará** nesta lista, pois já está reservado para ele. **Use `{available_str}` APENAS para sugerir NOVOS horários.**
        2.  Verifique os horários disponíveis em: `{available_str}`.
        3.  Considere o horário de funcionamento: `{schedule_str}`.
        4.  Sugira **APENAS {scheduling_config.get("number_of_suggestions", 2)}** opções de horário da lista `{available_str}`. É PROIBIDO SUGERIR MAIS QUE ISSO.
        5.  Use **APENAS** horários da lista `{available_str}` que estejam disponíveis e sejam pelo menos 1 hora após o horário atual (`{today_info}`).
        6.  Informe sempre a data completa (DD/MM/YYYY) e horário (HH:mm). Priorize datas/horas mais próximas da lista `{available_str}`.
        7.  **Se o cliente sugerir um dia/hora específico para reagendar:**
            * Primeiro, compare com o horário **atual** dele (`{formatted_customer_context}`). Se for o mesmo, apenas confirme que este já é o horário dele.
            * Se for **diferente** do horário atual, verifique se este horário sugerido está **presente** na lista de disponíveis `{available_str}`.
            * Se estiver disponível em `{available_str}`, confirme o reagendamento.
            * Se **NÃO** estiver disponível em `{available_str}`, informe educadamente que o horário sugerido não está livre e ofereça as {scheduling_config.get("number_of_suggestions", 2)} alternativas mais próximas da lista `{available_str}`.
        8.  Após a escolha de um novo horário disponível, confirme a alteração (não precisa pedir o nome novamente, pois já deve constar no `{formatted_customer_context}`).
        9.  Lembre-se que a avaliação é `{evaluation_price}` (se aplicável ao contexto).
        10. Duração da consulta: `{scheduling_config.get('consultation_duration')}` minutos.
        11. Os reagendamentos são para a empresa em `{companyAddress}, {companyLocation}`.

        # COMPORTAMENTOS ESPECIAIS (Redirecionamento)
        - Se o cliente perguntar sobre outros serviços (além da avaliação já agendada), questões financeiras complexas, manutenção de aparelho ou for um cliente ativo com dúvidas sobre tratamento em andamento, **redirecione** para o contato apropriado:
            - Atendimento Geral/Outros Serviços: `{regular_redirect}` (Telefone `{companyPhoneFixed}` ou WhatsApp `{companyWhatsApp}`)
            - Financeiro: `{financial_redirect}`
            - Manutenção: `{maintenance_redirect}`
            - Clientes Ativos (dúvidas sobre tratamento): `{active_customers_redirect}`
        - **Não tente resolver essas questões complexas diretamente.** Apenas forneça o contato correto.
        - Se o lead disser que não pode comparecer, desmarcar por qualquer motivo, busque entender melhor ou ser empático com ele mas sempre tentar reagendar logo.

        # INFORMAÇÕES DA EMPRESA (Para consulta e resposta a dúvidas)
        - Nome: `{companyName}`
        - Especialidade: ServiÃ§os completa
        - Horários: `{schedule_str}`
        - Tratamentos Oferecidos: `{treatments_str}` (Use para responder dúvidas básicas)
        - Pagamento: `{payment_info}`, `{installment_conditions}`
        - Preços: Avaliação é `{evaluation_price}`. Para outros tratamentos (`{treatment_prices}`), explique que o valor exato depende da avaliação.
        - Convênios: `{accepts_health_insurance}`. Se sim: `{health_insurance_plans}`.
        - Contatos: Telefone Fixo `{companyPhoneFixed}`, WhatsApp `{companyWhatsApp}`
        - Endereço: `{companyAddress}, {companyLocation}`
        - Maps: `{companyMaps}`
        - Social: Instagram `{companyInstagram}`, Facebook `{companyFacebook}`, Site `{companySite}`
        - Responsável Técnico: `{technical_responsible}`
        - História da Empresa: `{companyHistory}`

        # OBJEÇÕES COMUNS (Neste contexto, mais relacionadas à confirmação/comparecimento)
        - **Distância/Localização:** Reafirme o endereço, envie o link do Maps (`{companyMaps}`), talvez mencione pontos de referência se souber. Incentive o comparecimento.
        - **"Esqueci/Não lembrava":** Mencione novamente a data/hora (usando a informação de `{formatted_customer_context}`) e pergunte se ainda poderá comparecer.
        - **Imprevisto de última hora:** Ofereça a opção de reagendar (seguindo as regras acima) ou cancelar.
        - **Dúvidas sobre o que levar/preparo:** Forneça informações claras e simples.

        # RESTRIÇÕES IMPORTANTES
        1.  **NÃO INICIE UM NOVO AGENDAMENTO.** O cliente já tem um.
        2.  Ao reagendar, NUNCA liste mais de **{scheduling_config.get("number_of_suggestions", 2)}** horários da lista `{available_str}`.
        3.  NUNCA sugira horários/dias passados. Use apenas horários de `{available_str}`.
        4.  Faça UMA pergunta principal por mensagem.
        5.  Mantenha o tom `{assistantTone}` e formalidade `{assistantFormality}` no idioma `{assistantLanguage}`.
        6.  NÃO use termos técnicos complexos.
        7.  NÃO sugira endereços alternativos. A consulta é em `{companyAddress}, {companyLocation}`.
        8.  Confirme o REAGENDAMENTO apenas com [data, hora]. O nome já deve ser conhecido.
        9.  Seja claro sobre o custo da avaliação (`{evaluation_price}`), se pertinente.
        10. Não pergunte se o cliente quer agendar, não ofereça horários ou insista em agendar consulta para um apciente que só está tirando dúvidas ou agradecendo.

        # DIRETRIZES GERAIS
        1.  Respostas humanizadas, empáticas e concisas. Foco em ajudar o cliente com sua consulta *existente*.
        2.  Priorize confirmar a presença na consulta agendada (referencie a data/hora de `{formatted_customer_context}`).
        3.  Use as informações da empresa para tirar dúvidas.
        4.  Redirecione corretamente quando necessário.
        5.  Se reagendar, siga as regras estritamente, especialmente o limite de sugestões e o uso correto da lista `{available_str}` apenas para *novos* horários.
        6. Se o usuário perguntar ou quiser mandar áudio, diga que pode enviar e seja cordial.

        {fewShots_str}
        """

        # 13) Criar o prompt com mensagens
        prompt_messages = [
            ("system", SYSTEM_TEMPLATE),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}")
        ]
        prompt = ChatPromptTemplate.from_messages(prompt_messages)

        # 14) Instanciar LLM
        llm = ChatOpenAI(
            model_name="gpt-4o-mini",
            openai_api_key=get_company_openai_api_key(db, company_id),
            max_tokens=max_tokens_in_db,
            temperature=0.7
        )

        # 15) Criar LLMChain
        chain = prompt | llm
        logger.info("[LLMManager Agendado] LLMChain criado com sucesso.")

        # 16) Retornar chain + memória
        return {
            "chain": chain,
            "memory": memory,
            "prompt_template": prompt
        }

    except Exception as e:
        logger.error(f"[LLMManager Agendado] Erro ao criar LLMChain ou ao carregar dados: {e}")
        raise

def extract_json_from_llm_response(llm_text: str) -> dict:
    """
    Tenta capturar o conteúdo do JSON entre <json> e </json>.
    Exemplo de match:
        <json>{"tratamento": "implante", ...}</json>
    Retorna dicionário vazio se não conseguir fazer o parse.
    """
    pattern = r"<json>\s*(.*?)\s*</json>"
    match = re.search(pattern, llm_text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {}
    return {}
def handle_user_input(
    db: Session,
    company_id: int,
    contact_phone: str,
    user_input: str,
    msg_category: str = "",
    funnel_stage: str = "",
    funnel_status: str = ""
) -> str:
    """
    Processa a entrada do usuário através do LLM e gerencia o estado da conversa.
    Usa extração de dados somente da última interação (resposta do LLM + fala do usuário).
    """
    logger.info(f"[handle_user_input] Processando entrada: '{user_input}'")

    # 1) Carrega (ou cria) ConversationState
    state_machine = ConversationStateMachine(db_session=db, phone=contact_phone, company_id=company_id)
    current_step = state_machine.get_current_step()
    logger.info(f"[handle_user_input] Step inicial: {current_step}")

    # 2) Verificação de slots por padrão - obter todos os slots
    scheduling = SchedulingService(db, company_id)
    all_available_slots = scheduling.get_next_available_slots()

    # ORDENA os slots por proximidade com o dia atual
    today = datetime.now(SP_TZ).date()
    ordered_slots = []
    for slot_item in all_available_slots:
        try:
            # Tratamento defensivo para ambos os tipos (dict/string)
            if isinstance(slot_item, dict):
                slot_str = slot_item.get("slot", "")
            else:
                slot_str = str(slot_item)

            if not slot_str:
                continue

            # Correção defensiva: se slot_str for dict, extrai a string
            if isinstance(slot_str, dict):
                slot_str = slot_str.get("slot", str(slot_str))
            dt = datetime.strptime(str(slot_str), "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)
            # Calcula diferença em dias
            days_diff = (dt.date() - today).days
            # Adiciona à lista com prioridade por proximidade
            ordered_slots.append((days_diff, dt, slot_str))
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"[handle_user_input] Slot inválido ignorado: {slot_item} - Erro: {e}")
            continue

    # Ordena por proximidade (dias mais próximos primeiro)
    ordered_slots.sort(key=lambda x: x[0])

    # Extrai apenas as strings de slots na ordem correta
    all_available_slots = [slot_str for _, _, slot_str in ordered_slots]

    # IMPORTANTE: NÃO limitar aqui, manter todos os slots para a filtragem
    # Removida a linha: all_available_slots = all_available_slots[:40]

    # 3) Carrega memória/histórico antes de analisar slots
    # Carrega o histórico de mensagens para dar contexto
    memory_manager = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True
    )

    # Carrega mensagens do histórico
    try:
        from ..memory.memory_manager import get_chat_history
        chat_history = get_chat_history(contact_phone=contact_phone, company_id=company_id)
        if chat_history:
            for msg in chat_history:
                memory_manager.chat_memory.add_message(msg)
            # Extraímos as mensagens para análise
            conversation_history = [msg.content for msg in memory_manager.chat_memory.messages]
        else:
            conversation_history = []
    except Exception as e:
        logger.warning(f"[handle_user_input] Erro ao carregar histórico: {e}")
        conversation_history = []

    # 4) Analisa solicitação de horários usando o histórico de conversa
    try:
        slot_request = analyze_slot_request_with_llm(
            user_input,
            conversation_history,
            db=db,
            company_id=company_id,
        )
        logger.info(f"[handle_user_input] Análise LLM da solicitação: {slot_request}")

        # Se pediu horários específicos, filtra os slots
        if slot_request.get("has_request"):
            # IMPORTANTE: Passa TODOS os slots disponíveis para filtragem
            filtered_slots = get_filtered_slots(db, company_id, all_available_slots, slot_request)

            # Se encontrou slots filtrados, usa esses
            if filtered_slots:
                sample_slots = filtered_slots[:5] if len(filtered_slots) > 5 else filtered_slots
                logger.info(f"[handle_user_input] Filtrou slots: {len(filtered_slots)} slots. Exemplos: {sample_slots}")

                # IMPORTANTE: Só limita APÓS a filtragem
                slots_for_prompt = filtered_slots
                if len(slots_for_prompt) > 40:
                    logger.info(f"[handle_user_input] Limitando de {len(slots_for_prompt)} para 40 slots no prompt")
                    slots_for_prompt = slots_for_prompt[:40]

                # Usa os slots filtrados e limitados para o prompt
                all_available_slots = slots_for_prompt
            else:
                logger.info(f"[handle_user_input] Solicitação de slots, mas nenhum correspondente encontrado")
                # Mantém um conjunto vazio ou mínimo para informar ao usuário
                all_available_slots = []
    except Exception as e:
        logger.warning(f"[handle_user_input] Erro na análise de slots com LLM: {e}")
        # Continuamos com slots ordenados, mas limitamos para o prompt
        all_available_slots = all_available_slots[:10]

    # 2) Sincroniza com CRM, caso haja agendamento SCHEDULED (opcional)
    existing_agn = db.execute(text("""
        SELECT id, nome, status
        FROM agendamentos
        WHERE phone = :phone
          AND company_id = :cid
          AND status = 'SCHEDULED'
        ORDER BY id DESC
        LIMIT 1
    """), {"phone": contact_phone, "cid": company_id}).fetchone()

    if existing_agn:
        row_agn = existing_agn._mapping
        if row_agn["status"] == "SCHEDULED" and current_step < 7:
            logger.info("[handle_user_input] Forçando step=7 pois já existe agendamento (SCHEDULED).")
            state_machine.set_current_step(7)
            if row_agn["nome"]:
                state_machine.set_state_data("nome", row_agn["nome"])
            # Exemplo: se quiser marcar cliente="novo"
            state_machine.set_state_data("cliente", "novo")

    # 3) Se está em cooldown pós-confirmação, só responde normalmente, a menos que seja reagendamento
    if state_machine.has_recent_confirmation():
        cooldown_remaining = state_machine.get_confirmation_cooldown_remaining()
        logger.info(f"[handle_user_input] Em cooldown pós-confirmação. Faltam {cooldown_remaining}s.")
        lower_input = user_input.lower()
        if not any(word in lower_input for word in ["reagendar", "remarcar", "mudar horário", "outro dia"]):
            # Monta chain para só responder, sem processar
            chain_data = create_llm_chain_with_memory(
                db=db,
                company_id=company_id,
                contact_phone=contact_phone,
                msg_category=msg_category,
                funnel_stage=funnel_stage,
                funnel_status=funnel_status
            )
            chain = chain_data["chain"]
            memory = chain_data["memory"]

            return chain.invoke({
                "input": user_input,
                "chat_history": memory.chat_memory.messages
            }).content

    # 4) Caso normal: cria LLMChain e obtém a resposta do LLM
    chain_dict = create_llm_chain_with_memory(
        db=db,
        company_id=company_id,
        contact_phone=contact_phone,
        available_slots=all_available_slots,  # Passa TODOS os slots
        slot_request=slot_request,  # Passa a solicitação para filtrar lá dentro
        msg_category=msg_category,
        funnel_stage=funnel_stage,
        funnel_status=funnel_status
    )
    chain = chain_dict["chain"]
    memory = chain_dict["memory"]
    prompt_template = chain_dict["prompt_template"]

    # --- NOVO BLOCO: gerar prompt completo e contar tokens ---
    invoke_args = {
        "input": user_input,
        "chat_history": memory.chat_memory.messages
    }

    # Gera ChatPromptValue => converte em string final
    prompt_value = prompt_template.format_prompt(**invoke_args)
    final_prompt_str = prompt_value.to_string()

    # Escolha um model_name reconhecido por tiktoken.
    # Se "gpt-4o-mini" não for válido, use "gpt-3.5-turbo" ou "gpt-4".
    model_name = "gpt-4o-mini"
    try:
        enc = tiktoken.encoding_for_model(model_name)
    except:
        enc = tiktoken.get_encoding("cl100k_base")

    input_token_count = len(enc.encode(final_prompt_str))
    logger.info(f"[handle_user_input] prompt completo tem {input_token_count} tokens (modelo={model_name})")

    db.execute(text("""
        INSERT INTO tokens_input_usage (
            company_id,
            contact_phone,
            function_name,
            model_name,
            input_tokens
        )
        VALUES (
            :company_id,
            :contact_phone,
            :function_name,
            :model_name,
            :input_tokens
        )
    """), {
        "company_id": company_id,
        "contact_phone": contact_phone,
        "function_name": "handle_user_input",
        "model_name": model_name,
        "input_tokens": input_token_count
    })
    db.commit()
    # --- FIM DO BLOCO NOVO ---

    # Agora sim chamamos o LLM
    response = chain.invoke(invoke_args)
    chain_output = response.content
    # CRUCIAL: aplicar verificação e limitação de horários
    #chain_output = check_and_fix_suggestion_count(chain_output)

    logger.info(f"[handle_user_input] Resposta do LLM (após limitar horários):\n{chain_output}")

    # 5) Extrai (se houver) JSON <json>...</json> dentro da resposta
    llm_json = extract_json_from_llm_response(chain_output)
    logger.info(f"[handle_user_input] JSON extraído: {llm_json}")

    # 6) Se ainda em cooldown, só retorna a resposta
    if state_machine.has_recent_confirmation():
        return chain_output

    # 7) Prepara “conversa curta” (apenas última fala do LLM e do Usuário) para o parser
    conversation_context = (
        f"Assistente (LLM): {chain_output}\n"
        f"Usuário: {user_input}"
    )

    # 8) Roda o parser que extrai (tratamento, nome, data, etc.)
    extraction_chain, current_datetime = create_extraction_chain(
        model_name="gpt-4o-mini",
        api_key=get_company_openai_api_key(db, company_id),
    )
    try:
        extracted_data = parse_user_input_with_llm(conversation_context, (extraction_chain, current_datetime))
        logger.info(f"[handle_user_input] Dados extraídos: {extracted_data}")
    except Exception as e:
        logger.warning(f"[handle_user_input] Erro na extração: {e}")
        extracted_data = LLMUserData()

    # 9) Mescla os campos do llm_json (se existirem) com o extracted_data
    if llm_json:
        for key in ["tratamento", "cliente", "nome", "data", "horario"]:
            if llm_json.get(key):
                setattr(extracted_data, key, llm_json[key])

        if llm_json.get("agendamento_confirmado"):
            extracted_data.agendamento_confirmado = True
        if llm_json.get("cancelar_agendamento"):
            extracted_data.cancelar_agendamento = True
            if llm_json.get("motivo_cancelamento"):
                extracted_data.motivo_cancelamento = llm_json["motivo_cancelamento"]

    # 10) Atualiza dados no state_machine
    fields_to_update = [
        ("tratamento", "tratamento"),
        ("cliente", "cliente"),
        ("nome", "nome"),
        ("data", "data"),
        ("horario", "horario"),
    ]
    for attr, state_key in fields_to_update:
        val = getattr(extracted_data, attr, None)
        if val and val != state_machine.get_state_data(state_key):
            state_machine.set_state_data(state_key, val)
            logger.info(f"[handle_user_input] Atualizado {state_key}={val}")

    # 11) Ajusta flags especiais
    if extracted_data.cancelar_agendamento:
        state_machine.set_state_data("cancelar_agendamento", True)
        if extracted_data.motivo_cancelamento:
            state_machine.set_state_data("motivo_cancelamento", extracted_data.motivo_cancelamento)
    if extracted_data.agendamento_confirmado:
        state_machine.set_state_data("agendamento_confirmado", True)

    # 12) Processa transições / confirmações
    confirmation_msg = process_step_transition(state_machine, user_input)
    if confirmation_msg:
        logger.info("[handle_user_input] Retornando mensagem de confirmação")
        return confirmation_msg

    # 13) Se cancelamento e step=8, chama processar_cancelamento
    if extracted_data.cancelar_agendamento and state_machine.get_current_step() == 8:
        logger.info("[handle_user_input] Iniciando cancelamento via agendamento_logic")
        # Caso precise da api_key
        row_client_data = db.execute(text("""
            SELECT c.api_key
              FROM clients c
              JOIN client_companies cc ON cc.client_id = c.id
             WHERE cc.company_id = :company_id
             LIMIT 1
        """), {"company_id": company_id}).fetchone()
        api_key = row_client_data.api_key if (row_client_data and row_client_data.api_key) else None

        cancel_msg = processar_cancelamento(
            db=db,
            company_id=company_id,
            phone=contact_phone,
            api_key=api_key
        )
        logger.info("[handle_user_input] Retornando mensagem de cancelamento do agendamento_logic")
        return cancel_msg

    # 14) Checa missing_fields
    missing_fields = state_machine.get_state_data("missing_fields", [])
    if missing_fields:
        prompt_for_fields = (
            f"O cliente ainda precisa informar: {', '.join(missing_fields)}.\n"
            "Como um atendente virtual amigável e profissional, pergunte "
            "de forma educada esses campos, uma pergunta por vez."
        )
        fields_msg = chain.invoke({
            "input": prompt_for_fields,
            "chat_history": memory.chat_memory.messages
        }).content
        state_machine.set_state_data("missing_fields", [])
        return fields_msg

    # 15) Sem confirmações ou cancels => Retorna a resposta original do LLM
    logger.info(f"[handle_user_input] Retornando resposta do LLM (step={current_step})")
    return chain_output

def montar_confirmacao_json(state_machine: ConversationStateMachine) -> str:
    """
    Exemplo auxiliar de montagem do JSON <json> ... </json>.
    """
    tratamento = state_machine.get_state_data("tratamento", "")
    cliente = state_machine.get_state_data("cliente", "")
    nome = state_machine.get_state_data("nome", "")
    data_ = state_machine.get_state_data("data", "")
    horario_ = state_machine.get_state_data("horario", "")

    json_str = (
        f"<json>{{"
        f"\"tratamento\": \"{tratamento}\", "
        f"\"cliente\": \"{cliente}\", "
        f"\"nome\": \"{nome}\", "
        f"\"data\": \"{data_}\", "
        f"\"horario\": \"{horario_}\", "
        f"\"agendamento_confirmado\": true, "
        f"\"cancelar_agendamento\": false"
        f"}}"
        f"</json>"
    )
    return json_str

def build_full_conversation_text(memory, date_str: str) -> str:
    """
    Concatena todas as mensagens do histórico de conversa
    em um único texto, marcando quem falou e incluindo a data/hora de Brasília.
    """
    conversation_lines = [f"== Data/hora (Brasília): {date_str} =="]

    for msg in memory.chat_memory.messages:
        if msg.type == "human":
            speaker = "Usuário"
        else:
            speaker = "Assistente"
        conversation_lines.append(f"{speaker}: {msg.content}")

    # Por fim, retorna uma string com tudo
    return "\n".join(conversation_lines)

def analyze_slot_request_with_llm(
    user_input: str,
    conversation_history: list = None,
    *,
    db: Session,
    company_id: int,
) -> dict:
    """
    Usa LLM para analisar pedidos de horários com mais precisão.
    Inclui contexto de data atual para interpretar referências relativas como "próxima sexta".
    """
    from datetime import datetime, timedelta
    import json
    import re
    import logging

    logger = logging.getLogger(__name__)

    # Obtém a data atual
    today = datetime.now(SP_TZ)
    current_weekday = today.weekday()  # 0=Segunda, 1=Terça, ..., 6=Domingo

    # Calcula as datas para cada dia da semana atual e próxima
    weekday_names = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    date_references = {}

    # Para cada dia da semana, calcula a data desta semana e da próxima
    for i, name in enumerate(weekday_names):
        # Dias para o próximo dia da semana (esta semana)
        days_until = (i - current_weekday) % 7
        this_week_date = (today + timedelta(days=days_until)).date()

        # Dias para o dia da semana na próxima semana
        next_week_date = (today + timedelta(days=days_until + 7)).date()

        date_references[name] = {
            "this_week": this_week_date,
            "next_week": next_week_date
        }

    # Constrói um prompt rico em contexto para a análise de horários
    # Usando {{}} para escapar chaves em f-strings onde necessário
    system_prompt = f"""
    Você é um analisador de solicitações de agendamento. Sua tarefa é extrair informações específicas
    sobre horários solicitados pelo usuário. Analise com atenção a MENSAGEM ATUAL DO USUÁRIO, que deve
    ter prioridade sobre o histórico de conversa.

    HOJE É {weekday_names[current_weekday].upper()}-FEIRA, {today.strftime('%d/%m/%Y')}.

    REFERÊNCIAS DE DATAS PARA VOCÊ USAR:
    - Esta semana:
      {', '.join([f"{name}-feira: {info['this_week'].strftime('%d/%m/%Y')}" for name, info in date_references.items() if name not in ["sábado", "domingo"]])}
      {', '.join([f"{name}: {info['this_week'].strftime('%d/%m/%Y')}" for name, info in date_references.items() if name in ["sábado", "domingo"]])}

    - Próxima semana:
      {', '.join([f"{name}-feira: {info['next_week'].strftime('%d/%m/%Y')}" for name, info in date_references.items() if name not in ["sábado", "domingo"]])}
      {', '.join([f"{name}: {info['next_week'].strftime('%d/%m/%Y')}" for name, info in date_references.items() if name in ["sábado", "domingo"]])}

    IMPORTANTE: Quando o usuário mencionar apenas "na sexta", "na segunda", etc. sem especificar semana,
    considere SEMPRE a data mais próxima no futuro.

    Dê peso MUITO MAIOR à mensagem atual do que ao histórico. Se a mensagem atual mencionar
    "manhã", "cedo", etc., isso deve sobrescrever qualquer contexto anterior sobre período do dia.

    Se mencionar "semana que vem" ou "próxima semana", use as datas da próxima semana.

    Sua tarefa é identificar:
    1. Dias específicos (dia da semana, data específica)
    2. Períodos do dia (manhã, tarde, noite, fim do dia, após o expediente)
    3. Horários específicos
    4. Restrições (ex: "só posso após as 18h", "trabalho durante o dia")

    Priorize sempre a intenção mais recente do usuário.

    Termos específicos em português:
    - "manhã", "de manhã", "cedo" = período morning (antes das 12h)
    - "tarde" = período afternoon (12h-18h)
    - "fim do dia", "final da tarde" = período evening (17h-20h)
    - "noite" = período night (após 18h)

    Retorne sua análise APENAS em formato JSON como este exemplo:
    {{
      "has_request": true,
      "day_of_week": 4,
      "date": "2025-04-26",
      "period": "morning",
      "time_after": "08:00",
      "time_before": "12:00",
      "specific_time": null,
      "month": 4,
      "flexibility": "medium",
      "constraints": ["prefere horários mais cedo"]
    }}

    Não inclua explicações ou texto adicional, apenas o JSON.
    """

    # Contexto da conversa mais focado na mensagem atual
    if conversation_history and len(conversation_history) > 0:
        # Prioriza a mensagem atual com destaque
        user_context = f"""
        MENSAGEM ATUAL DO USUÁRIO: "{user_input}"

        Contexto recente (para referência apenas, dê prioridade à mensagem atual):
        {conversation_history[-2] if len(conversation_history) >= 2 else ''}
        {conversation_history[-1] if len(conversation_history) >= 1 else ''}
        """
    else:
        user_context = f'MENSAGEM DO USUÁRIO: "{user_input}"'

    # Log do prompt completo para diagnóstico
    logger.info(f"[analyze_slot_request_with_llm] Enviando prompt ao LLM para análise de slots")

    try:
        # Chama o LLM
        llm = ChatOpenAI(
            model_name="gpt-4o-mini",
            openai_api_key=get_company_openai_api_key(db, company_id),
            temperature=0.1
        )

        response = llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_context}
        ])

        logger.info(f"[analyze_slot_request_with_llm] Resposta do LLM: {response.content}")

        # Extrair JSON da resposta
        json_match = re.search(r'```json\s*(.*?)\s*```', response.content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response.content.strip()

        # Limpeza adicional do JSON se necessário
        json_str = re.sub(r'[\n\r\t]', '', json_str)
        json_match = re.search(r'{.*}', json_str, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)

        # Parse do JSON
        result = json.loads(json_str)

        # Conversão de data se necessário
        if result.get("date") and isinstance(result["date"], str):
            try:
                result["date"] = datetime.strptime(result["date"], "%Y-%m-%d").date()
            except ValueError:
                logger.warning(f"[analyze_slot_request_with_llm] Erro ao converter data: {result['date']}")

        logger.info(f"[analyze_slot_request_with_llm] Análise final: {result}")
        return result

    except Exception as e:
        logger.error(f"[analyze_slot_request_with_llm] Erro durante análise com LLM: {e}", exc_info=True)
        # Fallback para resultado vazio que não quebra o sistema
        return {
            "has_request": False,
            "day_of_week": None,
            "date": None,
            "period": None,
            "time_after": None,
            "time_before": None,
            "specific_time": None,
            "month": None,
            "flexibility": None,
            "constraints": []
        }

def get_filtered_slots(db, company_id, all_slots, filters):
    """
    Filtra slots disponíveis de acordo com os critérios solicitados pelo usuário,
    com estratégia de fallback melhorada para encontrar alternativas quando não há slots exatos.

    Parâmetros:
        db: Sessão do banco de dados
        company_id: ID da empresa
        all_slots: Lista de slots disponíveis no formato "DD/MM/YYYY HH:MM"
        filters: Dicionário com critérios de filtragem (data, período, etc.)
    """
    import datetime
    from datetime import timedelta
    import logging

    logger = logging.getLogger(__name__)

    # Convertemos todos os slots para objetos datetime para facilitar a filtragem
    slot_datetimes = []
    for slot_str in all_slots:
        try:
            # Correção defensiva: se slot_str for dict, extrai a string
            if isinstance(slot_str, dict):
                slot_str = slot_str.get("slot", str(slot_str))
            dt = datetime.datetime.strptime(str(slot_str), "%d/%m/%Y %H:%M").replace(tzinfo=SP_TZ)
            slot_datetimes.append((dt, slot_str))
        except ValueError:
            logger.warning(f"[get_filtered_slots] Formato de slot inválido: {slot_str}")
            continue

    # Começamos com todos os slots
    filtered_slots = slot_datetimes
    logger.info(f"[get_filtered_slots] Total de slots antes da filtragem: {len(filtered_slots)}")

    # Contadores para log
    total_inicial = len(filtered_slots)
    filtros_aplicados = []

    # ETAPA 1: Aplicar filtros específicos de data/dia da semana (priorizar data específica)
    if filters.get("date"):
        # Filtrar pela data específica
        slots_by_date = [(dt, slot_str) for dt, slot_str in filtered_slots if dt.date() == filters["date"]]
        filtros_aplicados.append(f"Data específica: {total_inicial} -> {len(slots_by_date)}")

        # Se encontramos slots, usamos esses
        if slots_by_date:
            filtered_slots = slots_by_date
        else:
            # Se não encontramos slots na data específica, buscamos datas próximas (+/- 3 dias)
            target_date = filters["date"]
            nearby_dates = []

            # Procura 3 dias antes e depois
            for delta in range(-3, 4):
                if delta == 0:  # Pulamos a data original que já sabemos não ter slots
                    continue
                search_date = target_date + timedelta(days=delta)
                slots_on_date = [(dt, slot_str) for dt, slot_str in slot_datetimes if dt.date() == search_date]
                if slots_on_date:
                    # Aplicar os outros filtros (período, horário) a estes slots
                    slots_filtered = slots_on_date

                    # Filtrar por período se aplicável
                    if filters.get("period"):
                        period_ranges = {
                            "morning": (6, 12),
                            "afternoon": (12, 18),
                            "evening": (17, 20),
                            "night": (18, 24)
                        }
                        start_hour, end_hour = period_ranges.get(filters["period"], (0, 24))
                        slots_filtered = [(dt, slot_str) for dt, slot_str in slots_filtered
                                        if start_hour <= dt.hour < end_hour]

                    # Aplicar filtros de horário
                    if filters.get("time_after") and slots_filtered:
                        try:
                            h, m = map(int, filters["time_after"].split(":"))
                            time_after = datetime.time(h, m)
                            slots_filtered = [(dt, slot_str) for dt, slot_str in slots_filtered
                                            if datetime.time(dt.hour, dt.minute) >= time_after]
                        except ValueError:
                            pass

                    if filters.get("time_before") and slots_filtered:
                        try:
                            h, m = map(int, filters["time_before"].split(":"))
                            time_before = datetime.time(h, m)
                            slots_filtered = [(dt, slot_str) for dt, slot_str in slots_filtered
                                            if datetime.time(dt.hour, dt.minute) <= time_before]
                        except ValueError:
                            pass

                    # Se ainda temos slots após aplicar todos os filtros
                    if slots_filtered:
                        nearby_dates.append((abs(delta), search_date, slots_filtered))

            # Ordenamos por proximidade da data original
            nearby_dates.sort(key=lambda x: x[0])

            if nearby_dates:
                # Usamos os slots da data mais próxima
                _, date_found, date_slots = nearby_dates[0]
                filtered_slots = date_slots
                logger.info(f"[get_filtered_slots] Usando data alternativa: {date_found} (diferença de {nearby_dates[0][0]} dias)")
                # Adiciona informação para o log de filtragem
                filtros_aplicados.append(f"Expandido para data próxima: {date_found}")

    elif filters.get("day_of_week") is not None:
        # Se não temos data específica, mas temos dia da semana
        slots_by_dow = [(dt, slot_str) for dt, slot_str in filtered_slots if dt.weekday() == filters["day_of_week"]]
        filtros_aplicados.append(f"Dia da semana: {len(filtered_slots)} -> {len(slots_by_dow)}")

        if slots_by_dow:
            filtered_slots = slots_by_dow

    # ETAPA 2: Aplicar filtros de período do dia
    total_apos_data = len(filtered_slots)
    if filters.get("period"):
        # Define intervalos de horas para cada período
        period_ranges = {
            "morning": (6, 12),   # 6:00 às 11:59
            "afternoon": (12, 18), # 12:00 às 17:59
            "evening": (17, 20),  # 17:00 às 19:59
            "night": (18, 24)     # 18:00 às 23:59
        }

        # Obtém o intervalo do período solicitado
        start_hour, end_hour = period_ranges.get(filters["period"], (0, 24))

        # Filtra por período
        slots_by_period = [(dt, slot_str) for dt, slot_str in filtered_slots
                          if start_hour <= dt.hour < end_hour]

        filtros_aplicados.append(f"Período ({filters['period']}): {total_apos_data} -> {len(slots_by_period)}")

        if slots_by_period:
            filtered_slots = slots_by_period

    # ETAPA 3: Aplicar filtros de horário específico
    total_apos_periodo = len(filtered_slots)
    if filters.get("time_after"):
        # Extrai apenas a hora
        try:
            h, m = map(int, filters["time_after"].split(":"))
            time_after = datetime.time(h, m)

            slots_after_time = [(dt, slot_str) for dt, slot_str in filtered_slots
                               if datetime.time(dt.hour, dt.minute) >= time_after]

            filtros_aplicados.append(f"Após {filters['time_after']}: {total_apos_periodo} -> {len(slots_after_time)}")

            if slots_after_time:
                filtered_slots = slots_after_time
        except ValueError:
            logger.warning(f"[get_filtered_slots] Formato de time_after inválido: {filters['time_after']}")

    if filters.get("time_before"):
        # Extrai apenas a hora
        try:
            h, m = map(int, filters["time_before"].split(":"))
            time_before = datetime.time(h, m)

            slots_before_time = [(dt, slot_str) for dt, slot_str in filtered_slots
                                if datetime.time(dt.hour, dt.minute) <= time_before]

            filtros_aplicados.append(f"Antes de {filters['time_before']}: {len(filtered_slots)} -> {len(slots_before_time)}")

            if slots_before_time:
                filtered_slots = slots_before_time
        except ValueError:
            logger.warning(f"[get_filtered_slots] Formato de time_before inválido: {filters['time_before']}")

    # Se após todos os filtros temos menos de 2 slots, usamos estratégias de expansão
    if len(filtered_slots) < 2:
        logger.info(f"[get_filtered_slots] Poucos slots encontrados. Tentando estratégias alternativas.")

        # Estratégia 1: Se filtramos por período, tentamos outros períodos
        if filters.get("period") and (filters.get("date") or filters.get("day_of_week") is not None):
            # Mantemos a data mas expandimos para qualquer período
            if filters.get("date"):
                expanded_slots = [(dt, slot_str) for dt, slot_str in slot_datetimes if dt.date() == filters["date"]]
            else:
                expanded_slots = [(dt, slot_str) for dt, slot_str in slot_datetimes if dt.weekday() == filters["day_of_week"]]

            if len(expanded_slots) > len(filtered_slots):
                logger.info(f"[get_filtered_slots] Expansão: removendo filtro de período. Encontrados {len(expanded_slots)} slots.")
                filtered_slots = expanded_slots

        # Estratégia 2: Se ainda temos poucos slots, buscamos dias próximos
        if len(filtered_slots) < 2 and filters.get("date"):
            target_date = filters["date"]
            today = datetime.datetime.now(SP_TZ).date()
            days_ahead = []

            # Procura até 10 dias para frente
            for delta in range(1, 11):
                future_date = today + timedelta(days=delta)
                if future_date == target_date:  # Pulamos a data que já checamos
                    continue

                slots_on_date = [(dt, slot_str) for dt, slot_str in slot_datetimes if dt.date() == future_date]
                if slots_on_date:
                    days_ahead.append((delta, future_date, slots_on_date))

            if days_ahead:
                # Pegamos o primeiro dia com slots disponíveis
                _, future_date, future_slots = days_ahead[0]
                logger.info(f"[get_filtered_slots] Sugerindo data futura: {future_date} com {len(future_slots)} slots.")
                filtered_slots = future_slots

    # Log do resumo da filtragem
    logger.info(f"[get_filtered_slots] Resumo da filtragem: {' -> '.join(filtros_aplicados)}")

    # Resultado final
    result = [slot_str for _, slot_str in filtered_slots]
    primeiros_slots = result[:5] if result else ["nenhum"]
    logger.info(f"[get_filtered_slots] Resultado final: {len(result)} slots. Primeiros 5: {primeiros_slots}")

    return result

def check_and_fix_suggestion_count(llm_response: str) -> str:
    """
    Verifica e corrige respostas do LLM que contém mais de 2 sugestões de horários.
    """
    import re

    # Conta quantos horários são listados usando regex para identificar linhas com padrão de horário
    time_pattern = r'^-\s*\d{1,2}[:.]\d{2}'
    lines = llm_response.split('\n')

    time_lines = []
    non_time_lines = []

    for line in lines:
        if re.match(time_pattern, line.strip()):
            time_lines.append(line)
        else:
            non_time_lines.append(line)

    # Se temos mais de 2 horários, mantemos apenas os 2 primeiros
    if len(time_lines) > 2:
        logger.warning(f"LLM sugeriu {len(time_lines)} horários, limitando para 2")
        time_lines = time_lines[:2]

    # Reconstruímos a resposta mantendo a estrutura original
    final_response = []
    time_added = False

    for line in non_time_lines:
        final_response.append(line)
        # Quando encontramos uma linha que menciona horários, inserimos os horários limitados
        if not time_added and ('horário' in line.lower() or 'opções' in line.lower()):
            final_response.append("")  # Linha em branco antes dos horários
            final_response.extend(time_lines)
            final_response.append("")  # Linha em branco após os horários
            time_added = True

    # Se não conseguimos encontrar o ponto certo para inserir os horários, apenas concatenamos
    if not time_added and time_lines:
        if 'Gostaria de agendar' not in final_response[-1]:
            final_response.extend([""] + time_lines + [""])
        else:
            # Inserimos antes da pergunta final
            final_response = final_response[:-1] + [""] + time_lines + ["", final_response[-1]]

    return '\n'.join(final_response)
