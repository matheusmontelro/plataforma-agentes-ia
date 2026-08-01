# Context Utilities for Agents SDK
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import pytz

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
SP_TZ = pytz.timezone('America/Sao_Paulo')


def get_company_timezone(db: Session, company_id: int) -> pytz.timezone:
    """
    Retorna o fuso horário configurado para a empresa na tabela ai_response_windows.
    Se não existir ou for inválido, usa o padrão SP_TZ.
    """
    try:
        row = db.execute(
            text("""
                SELECT timezone
                FROM ai_response_windows
                WHERE company_id = :cid
                LIMIT 1
            """),
            {"cid": company_id}
        ).fetchone()

        if row and row.timezone:
            try:
                # Tenta criar um objeto timezone para verificar se é válido
                tz = pytz.timezone(row.timezone)
                logger.info(f"[Timezone] Usando timezone personalizado para company_id={company_id}: {row.timezone}")
                return tz
            except Exception as tz_error:
                logger.error(f"[Timezone] Timezone inválido '{row.timezone}': {tz_error}, usando padrão")
    except Exception as e:
        logger.error(f"[Timezone] Erro ao obter timezone: {e}")

    # Fallback para o timezone padrão
    logger.info(f"[Timezone] Usando timezone padrão para company_id={company_id}: America/Sao_Paulo")
    return SP_TZ


def create_dynamic_instructions(
    company_config: Dict[str, Any],
    customer_context: Optional[Dict[str, Any]] = None,
    funnel_stage: str = "",
    funnel_status: str = ""
) -> str:
    """
    Cria instruções dinâmicas baseadas no contexto da empresa e do cliente.
    Usa o prompt legado consolidado na estrutura modular.
    """
    # Extrai todas as configurações da empresa
    company_info = company_config.get("company_info", {})
    assistant_identity = company_config.get("assistant_identity", {})
    conversation_flow = company_config.get("conversation_flow", {})
    scheduling_config = company_config.get("scheduling_config", {})
    financial_config = company_config.get("financial_config", {})
    team_specialties = company_config.get("team_specialties", {})

    # Informações básicas
    companyName = company_info.get("company_name", "Nossa empresa")
    assistantName = assistant_identity.get("assistant_name", "Assistente")
    assistantRole = assistant_identity.get("assistant_role", "assistente de atendimento")
    assistantResponsibility = assistant_identity.get("assistant_responsibility", "atender e agendar consultas")
    assistantTone = assistant_identity.get("assistant_tone", "amigável e profissional")
    assistantFormality = assistant_identity.get("assistant_formality", "semi-formal")
    assistantLanguage = assistant_identity.get("assistant_language", "português brasileiro")

    # Horários e agendamento
    schedule_str = scheduling_config.get("business_hours", "Segunda a Sexta: 8h às 18h")
    evaluation_price = financial_config.get("evaluation_price", "R$ 90,00")
    payment_info = financial_config.get("payment_options", "Dinheiro, cartão e PIX")
    installment_conditions = financial_config.get("installment_conditions", "parcelamos em até 12x")

    # Especialidades e tratamentos
    specialties = team_specialties.get("specialties", [])
    treatments_str = ", ".join(specialties) if specialties else "serviÃ§os completa"

    # Preços dos tratamentos
    treatment_prices = financial_config.get("treatment_prices", "Consulte valores específicos")

    # Convênios
    accepts_health_insurance = financial_config.get("accepts_health_insurance", "sim")
    health_insurance_plans = financial_config.get("health_insurance_plans", "principais planos de serviços")

    # Contatos
    companyPhoneFixed = company_info.get("company_phone_fixed", "")
    companyWhatsApp = company_info.get("company_whatsapp", "")
    companyAddress = company_info.get("company_address", "")
    companyLocation = company_info.get("company_location", "")
    companyMaps = company_info.get("company_maps", "")
    companyInstagram = company_info.get("company_instagram", "")
    companyFacebook = company_info.get("company_facebook", "")
    companySite = company_info.get("company_site", "")

    # Dentista responsável
    technical_responsible = team_specialties.get("technical_responsible", "Dr(a). Responsável")

    # História da empresa
    companyHistory = company_info.get("company_history", "")

    # Etapas do fluxo de conversa
    step0 = conversation_flow.get("step0", "")
    step1First = conversation_flow.get("step1First", "")
    step1Second = conversation_flow.get("step1Second", "")
    step2 = conversation_flow.get("step2", "")
    step3 = conversation_flow.get("step3", "")

    # Redirecionamentos
    regular_redirect = scheduling_config.get("regular_redirect", "atendimento geral")
    financial_redirect = scheduling_config.get("financial_redirect", "financeiro")
    maintenance_redirect = scheduling_config.get("maintenance_redirect", "manutenção")
    active_customers_redirect = scheduling_config.get("active_customers_redirect", "clientes ativos")

    # Few shots examples
    few_shots = conversation_flow.get("few_shots", [])
    few_shots_str = ""
    if few_shots:
        few_shots_str = "\n# EXEMPLOS DE CONVERSAS\n"
        for i, example in enumerate(few_shots, 1):
            few_shots_str += f"\n## Exemplo {i}:\n"
            if isinstance(example, dict):
                few_shots_str += f"Usuário: {example.get('user', '')}\n"
                few_shots_str += f"Assistente: {example.get('assistant', '')}\n"

    base_instructions = f"""
# INFORMAÇÕES DA EMPRESA
- Nome: {companyName}
- Especialidade: ServiÃ§os completa
- Horários: {schedule_str}
- Tratamentos oferecidos: {treatments_str}
- Pagamento: {payment_info}, {installment_conditions}
- Preços: {treatment_prices}
- Convênios: {accepts_health_insurance}, {health_insurance_plans}
- Contatos: {companyPhoneFixed}, {companyWhatsApp}
- Endereço: {companyAddress}, {companyLocation}
- Maps: {companyMaps}
- Social: {companyInstagram}, {companyFacebook}, {companySite}
- Dentista Responsável técnico: {technical_responsible}
- História da empresa: {companyHistory}
- Consulta de avaliação gratuita?: {evaluation_price}

# VALORES E PREÇOS - SEMPRE USE EXATAMENTE ESTES VALORES
- Preço da consulta de avaliação: {evaluation_price}
- NUNCA altere ou invente valores diferentes dos configurados
- Se questionado sobre preço, use EXATAMENTE: {evaluation_price}

# IDENTIDADE DO ASSISTENTE
Você é {assistantName}, {assistantRole}. Atue como um humano conversando.
Responsabilidade: {assistantResponsibility}
Tom da resposta: {assistantTone}, formalidade da resposta: {assistantFormality}, idioma da resposta: {assistantLanguage}

# FLUXO PRINCIPAL
0. **Boas-Vindas (etapa 0)**
- Base: "{step0}"
- Na primeira interação, apresente-se como {assistantName} da {companyName}. E pergunte como pode ajudar.
- Adapte a resposta de acordo com o histórico da conversa de maneira {assistantFormality}
- Transição: Ao demonstrar interesse → etapa 1.

1. **Identificação do Tratamento (etapa 1)**
- Base 1: "{step1First}"
- Ação: Capturar resposta como [VARIAVEL:dor=VALOR]
- Base 2: "{step1Second}"
- Ação: Capturar [VARIAVEL:tratamento=VALOR] → etapa 2
- Adapte a resposta de acordo com o histórico da conversa de maneira {assistantFormality}
- Se já respondido, avance.

2. **Situação do Cliente (etapa 2)**
- Base: "{step2}"
- Ação: Capturar [VARIAVEL:cliente=VALOR] → etapa 3
- Se já respondido, avance.

3. **Exploração e Benefícios (etapa 3)**
- Base: "{step3}"
- Objetivo: Elevar consciência, destacar benefícios
- Transição: Ao concordar → etapa 4

4. **Agendamento (etapa 4)**
- Sugira 2 horários próximos de hoje da lista disponível
- Informar claramente se avaliação é gratuita: {evaluation_price}
- Sempre usar formato: "[Dia da semana] dia (DD/MM/YYYY) às HH:mm"
- Exemplo: "Sábado dia (21/06/2025) às 09:00"
- Limite-se a APENAS {scheduling_config.get("number_of_suggestions", 2)} sugestões de horários. É PROIBIDO SUGERIR MAIS 2 HORÁRIOS.
- Transição: Ao confirmar horário → etapa 5

5. **Confirmação e Nome (etapa 5)**
- Solicite nome completo após escolha de horário
- Salve [VARIAVEL:nome=VALOR]
- IMPORTANTE: Após receber o nome, você DEVE chamar a função agendar_consulta com os parâmetros:
  - data_hora: no formato "DD/MM/YYYY HH:MM" (ex: "04/07/2025 08:30")
  - nome_completo: o nome que o usuário informou
- Só após o retorno da função, siga para etapa 6

6. **Encerramento (etapa 6)**
- Finalize amigavelmente APENAS após confirmar o agendamento via função

7. **Pós-agendamento (etapa 7)**
- Atenda dúvidas sem perguntar sobre novos horários
- Seja cordial para reagendamentos

# REGRAS DE AGENDAMENTO
1. Escolha 2 Horários disponíveis da lista fornecida
2. Horário de funcionamento: {schedule_str}
3. Limite-se a APENAS {scheduling_config.get("number_of_suggestions", 2)} sugestões de horários. É PROIBIDO SUGERIR MAIS 2 HORÁRIOS.
4. Use APENAS 2 horários da lista disponível
5. Informe sempre a data completa (DD/MM/YYYY) com horário (HH:mm) ao sugerir um dia pra agendamento.
6. SEMPRE ao sugerir horários, use o formato completo: "[Dia da semana] dia (DD/MM/YYYY) às HH:mm".
   Exemplo: "Sábado dia (21/06/2025) às 09:00" ou "Segunda-feira dia (23/06/2025) às 14:00"
7. Ao sugerir horários:
- Se não especificar dia: sugira 2 do dia mais próximo
- Se especificar dia: verifique disponibilidade  e sugira SOMENTE 2 HORÁRIOS
- Se escolher só dia: ofereça 2 opções de horários
8. Após escolha de horário, peça nome sem nova confirmação se o horário estiver disponível.
9. OBRIGATÓRIO: Após receber o nome completo, SEMPRE use a função agendar_consulta(data_hora, nome_completo) para efetivar o agendamento no sistema
10. Avaliação gratuita? {evaluation_price} (sempre informe)
11. Nunca sugira um Horário Indisponível ou que já passaram
12. Manhã: até 12:00, Tarde: 12:00 até 18:00.
13. Duração da consulta: {scheduling_config.get('consultation_duration')} minutos
14. Faça uma pergunta por mensagem
14. Só pergunte o nome completo do usuário após ele escolher o dia e horário para agendamento e você verificar que o mesmo está disponível.
15. Não é possível e não sugira agendar consultas que não sejam em {companyAddress}, {companyLocation} .
16. Sugira agendamentos sempre com 1 hora depois do horário atual.
17. Priorize SEMPRE os horários MAIS PRÓXIMOS da data atual
18. Ofereça primeiro os horários mais próximos disponíveis.
19. Só ofereça horários da próxima semana se não houver disponibilidade nos próximos 2-3 dias

# COMPORTAMENTOS ESPECIAIS

1. Reagendamento:
- Pergunte melhor dia
- Ofereça {scheduling_config.get("number_of_suggestions", 2)} opções, confirme nome

2. Casos de redirecionamento:
- Clientes que desejam outros serviços além de avaliação
- Questões financeiras, manutenção, etc.
- Redirecione para: {companyPhoneFixed} ou {companyWhatsApp}

3. Contato alternativo por tipo:
- Atendimento geral: {regular_redirect}
- Financeiro: {financial_redirect}
- Manutenção: {maintenance_redirect}
- Clientes ativos: {active_customers_redirect}

4. Se o cliente já:
- Agendou: foque na presença
- Compareceu: foque em vender
- Iniciou tratamento: direcione para canais de suporte

# OBJEÇÕES COMUNS
- Distância: Ofereça maps ({companyMaps}), continue agendamento
- Preço: Explique necessidade de avaliação prévia, tente agendar
- Convênio/SUS: Responda factualmente, tente agendar avaliação
- Adiamento: Explique limitação de agenda, tente agendar agora
- Cliente retornando: Seja receptivo, tente agendar
- Fotos/Exemplos: Direcione para redes sociais
- Reconhecimento de voz: Brinque pedindo áudio de teste
- Dúvidas sobre tratamentos: Explique como funciona o tratamento.

# RESTRIÇÕES
1. Nunca liste mais de {scheduling_config.get("number_of_suggestions", 2)} horários
2. Nunca agende em horários/dias indisponíveis
3. Nunca faça 2 perguntas na mesma mensagem
4. Nunca use termos técnicos no primeiro contato
5. Nunca sugira endereços alternativos
6. Nunca repita perguntas já respondidas
7. Nunca sugira datas e horários fora da lista disponível
8. Nunca confirme agendamentos sem coletar data, hora e nome
9. Nunca sugira um agendamento para um lead que já agendou.
10. Nunca envie mensagem robotizada
11. Nunca envie mensagens repetitivas
12. Nunca responda 'Desculpe pela confusão!' -> se sentir confuso responda naturalmente.

# DIRETRIZES GERAIS
1. Uma pergunta por vez
2. Respostas humanizadas e concisas
3. Confirme agendamentos apenas com [data, hora, nome]
4. Priorize coleta de informações na ordem: tratamento → se ja é cliente da empresa ou é a primeira vez → nome
5. Identifique e redirecione clientes atuais para canais apropriados
6. Contorne objeções para agendar avaliação
7. Se consulta não for gratuita, seja transparente
8. Salve "agendamento_confirmado" como 'true' após confirmar nome
9. Se usuário responde "Não sei" ao tratamento, defina como "Avaliação"
10. Se usuário já escolheu horário específico, primeiro verifique se esse horário está disponível e informe ao usuário a disponibilidade.
11. Identifique erros de digitação e grafia do idioma prinicipal e busque entender o que o usuário disse.
12. Limite-se a APENAS {scheduling_config.get("number_of_suggestions", 2)} sugestões de horários. É PROIBIDO SUGERIR MAIS 2 HORÁRIOS.
13. Se o usuário perguntar ou quiser mandar áudio, diga que pode enviar e seja cordial.

{few_shots_str}

Limite suas respostas até 300 tokens para evitar cortes.
"""

    # Adiciona contexto do cliente se disponível
    if customer_context:
        customer_info = format_customer_context_for_prompt(customer_context)
        base_instructions += f"\n\n# CONTEXTO DO CLIENTE\n{customer_info}"

    # Adiciona informações do funil se disponíveis
    if funnel_stage or funnel_status:
        base_instructions += f"\n\n# STATUS NO FUNIL"
        if funnel_stage:
            base_instructions += f"\n- Estágio: {funnel_stage}"
        if funnel_status:
            base_instructions += f"\n- Status: {funnel_status}"

    return base_instructions


def add_temporal_context_to_instructions(
    base_instructions: str,
    available_slots: Optional[List[str]] = None
) -> str:
    """
    Adiciona contexto temporal e disponibilidade às instruções.
    Similar à função create_dynamic_instructions do arquivo original.
    """
    temporal_context = get_temporal_context()
    now = datetime.now(SP_TZ)
    tomorrow = now + timedelta(days=1)
    day_after = now + timedelta(days=2)

    weekdays_pt = {
        0: "Segunda-feira",
        1: "Terça-feira",
        2: "Quarta-feira",
        3: "Quinta-feira",
        4: "Sexta-feira",
        5: "Sábado",
        6: "Domingo"
    }

    # Contexto temporal
    current_time = f"{weekdays_pt[now.weekday()]}, dia {now.strftime('%d/%m/%Y')} às {now.strftime('%H:%M')}"
    tomorrow_info = f"{weekdays_pt[tomorrow.weekday()]}, dia {tomorrow.strftime('%d/%m/%Y')}"
    day_after_info = f"{weekdays_pt[day_after.weekday()]}, dia {day_after.strftime('%d/%m/%Y')}"

    temporal_instructions = f"""

# CONTEXTO TEMPORAL ATUAL
- Agora: {current_time}
- Amanhã: {tomorrow_info}
- Depois de amanhã: {day_after_info}

IMPORTANTE: Use essas informações para entender corretamente quando o cliente diz "hoje", "amanhã", "quinta", etc.
"""

    # Adiciona resumo de disponibilidade se houver slots
    if available_slots:
        availability_summary = analyze_availability(available_slots)
        if availability_summary:
            temporal_instructions += f"""

# DISPONIBILIDADE ATUAL
{availability_summary}
"""

    return base_instructions + temporal_instructions


def analyze_availability(slots: List[str]) -> str:
    """
    Analisa slots disponíveis e cria um resumo da disponibilidade.
    """
    if not slots:
        return "Sem horários disponíveis no momento."

    # Agrupa por dia
    slots_by_day = {}
    for slot in slots[:20]:  # Analisa apenas os primeiros 20 slots
        try:
            dt = datetime.strptime(slot, "%d/%m/%Y %H:%M")
            day_key = dt.strftime("%d/%m")
            if day_key not in slots_by_day:
                slots_by_day[day_key] = []
            slots_by_day[day_key].append(dt.strftime("%H:%M"))
        except:
            continue

    # Cria resumo
    summary_parts = []
    for day, times in list(slots_by_day.items())[:5]:  # Primeiros 5 dias
        summary_parts.append(f"- {day}: {len(times)} horários disponíveis")

    return "\n".join(summary_parts) if summary_parts else "Horários disponíveis para os próximos dias."


def format_customer_context_for_prompt(customer_context: Dict[str, Any]) -> str:
    """
    Formata o contexto do cliente para incluir no prompt.
    """
    if not customer_context:
        return "Novo cliente (sem histórico)"

    formatted = []

    # Nome do cliente
    if customer_context.get("nome"):
        formatted.append(f"Nome: {customer_context['nome']}")

    # Último agendamento
    if customer_context.get("ultimo_agendamento"):
        ultimo = customer_context["ultimo_agendamento"]
        if isinstance(ultimo, dict):
            data = ultimo.get("data", "")
            procedimento = ultimo.get("procedimento", "")
            if data:
                formatted.append(f"Último agendamento: {data}")
            if procedimento:
                formatted.append(f"Procedimento: {procedimento}")

    # Tratamentos em andamento
    if customer_context.get("tratamento_em_andamento"):
        formatted.append(f"Tratamento em andamento: {customer_context['tratamento_em_andamento']}")

    # Observações
    if customer_context.get("observacoes"):
        formatted.append(f"Observações: {customer_context['observacoes']}")

    # Status do cliente
    if customer_context.get("status"):
        formatted.append(f"Status: {customer_context['status']}")

    return "\n".join(formatted) if formatted else "Novo cliente (sem histórico)"


def get_temporal_context() -> Dict[str, str]:
    """
    Retorna contexto temporal atual formatado.
    """
    now = datetime.now(SP_TZ)

    weekdays_pt = {
        0: "Segunda-feira",
        1: "Terça-feira",
        2: "Quarta-feira",
        3: "Quinta-feira",
        4: "Sexta-feira",
        5: "Sábado",
        6: "Domingo"
    }

    months_pt = {
        1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
        5: "maio", 6: "junho", 7: "julho", 8: "agosto",
        9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
    }

    return {
        "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "current_date": now.strftime("%d/%m/%Y"),
        "current_time": now.strftime("%H:%M"),
        "current_weekday": weekdays_pt[now.weekday()],
        "current_month": months_pt[now.month],
        "current_year": str(now.year),
        "formatted_full": f"{weekdays_pt[now.weekday()]}, {now.day} de {months_pt[now.month]} de {now.year}"
    }


def extract_time_preferences(user_message: str) -> Dict[str, Any]:
    """
    Extrai preferências de horário da mensagem do usuário.
    Complementa a análise semântica feita pelo LLM.
    """
    preferences = {
        "has_preference": False,
        "period": None,
        "specific_time": None,
        "weekday": None
    }

    message_lower = user_message.lower()

    # Períodos do dia
    if any(term in message_lower for term in ["manhã", "manha", "matutino"]):
        preferences["period"] = "manhã"
        preferences["has_preference"] = True
    elif any(term in message_lower for term in ["tarde", "vespertino"]):
        preferences["period"] = "tarde"
        preferences["has_preference"] = True
    elif any(term in message_lower for term in ["noite", "noturno"]):
        preferences["period"] = "noite"
        preferences["has_preference"] = True

    # Dias da semana
    weekdays = {
        "segunda": "segunda-feira",
        "terça": "terça-feira",
        "quarta": "quarta-feira",
        "quinta": "quinta-feira",
        "sexta": "sexta-feira",
        "sábado": "sábado",
        "domingo": "domingo"
    }

    for key, value in weekdays.items():
        if key in message_lower:
            preferences["weekday"] = value
            preferences["has_preference"] = True

    # Horários específicos (busca por padrões como "14h", "14:00", "2 da tarde")
    import re
    time_patterns = [
        r'(\d{1,2})[:\s]?h',  # 14h, 14:h
        r'(\d{1,2}):(\d{2})',  # 14:30
        r'(\d{1,2})\s*(?:da|de)\s*(?:manhã|tarde|noite)'  # 2 da tarde
    ]

    for pattern in time_patterns:
        match = re.search(pattern, message_lower)
        if match:
            preferences["has_preference"] = True
            # Aqui poderia extrair o horário específico se necessário
            break

    return preferences
