# Company Agent System
import logging
from typing import Dict, Any
from dataclasses import dataclass

from agents import Agent, handoff, ModelSettings, RunContextWrapper
from ..config.company_context import CompanyContext
from ..tools.scheduling_tools import buscar_horarios_disponiveis
from ..tools.customer_tools import obter_informacoes_cliente, agendar_consulta, cancelar_agendamento, reagendar_consulta
from ..utils.context_utils import create_dynamic_instructions

logger = logging.getLogger(__name__)


async def create_state_aware_instructions(wrapper: RunContextWrapper[CompanyContext], agent: Agent[CompanyContext]) -> str:
    """
    Cria instruções state-aware que se adaptam ao estado atual da conversa.
    Substitui instruções genéricas por comportamento baseado no estado.
    """
    context = wrapper.context

    # Obtém o gerenciador de estado
    state_manager = await context.get_state_manager()
    current_step = state_manager.state.current_step

    # Usa as instruções base salvadas no agent
    base_instructions = agent._base_instructions

    # Adiciona contexto temporal e disponibilidade
    from ..utils.context_utils import add_temporal_context_to_instructions
    enhanced_instructions = add_temporal_context_to_instructions(
        base_instructions,
        context.available_slots
    )

    # Adiciona instruções específicas do estado atual
    state_specific_instructions = get_step_specific_instructions(current_step, state_manager)

    # Adiciona informações do estado atual
    state_context = f"""

# ESTADO ATUAL DA CONVERSA
- Step atual: {current_step} ({state_manager.get_step_description()})
- Dados coletados: {list(state_manager.state.state_data.keys())}
- Campos faltando: {state_manager._get_missing_required_fields()}

{state_specific_instructions}
"""

    return enhanced_instructions + state_context


def get_step_specific_instructions(current_step: int, state_manager) -> str:
    """
    Retorna instruções específicas para cada step da conversa.
    Remove a necessidade de instruções genéricas no prompt.
    """
    state_data = state_manager.state.state_data

    # Instrução global sobre respostas terminais
    terminal_instruction = """
# IMPORTANTE: RESPOSTAS DE FERRAMENTAS
Quando uma ferramenta retornar uma mensagem com "__TERMINAL_RESPONSE__", você DEVE:
1. Usar EXATAMENTE a resposta retornada pela ferramenta
2. NÃO adicionar texto antes ou depois
3. NÃO reformatar ou modificar a mensagem
4. Apenas retornar a mensagem como sua resposta final
"""

    if current_step == 0:
        return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 0 (Boas-vindas)
- Apresente-se como assistente da empresa
- Pergunte como pode ajudar
- Seja caloroso e acolhedor
"""

    elif current_step == 1:
        if not state_manager.is_field_filled("tratamento"):
            return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 1 (Identificação do tratamento)
- Foque em descobrir que tipo de tratamento o cliente precisa
- Seja específico: dor, limpeza, clareamento, ortodontia, etc.
- Capture a resposta e salve como "tratamento"
"""
        else:
            return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 1 (Transição)
- Tratamento já identificado, avance para próximo step
- Pergunte sobre a situação do cliente
"""

    elif current_step == 2:
        if not state_manager.is_field_filled("cliente"):
            return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 2 (Situação do cliente)
- Descubra se é cliente novo ou retorno
- Capture se já foi atendido na empresa antes
- Salve como "cliente"
- IMPORTANTE: NÃO chame agendar_consulta ainda - dados incompletos
"""
        else:
            return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 2 (Transição)
- Situação do cliente já identificada, avance
- Foque em elevar consciência sobre o tratamento
- IMPORTANTE: NÃO chame agendar_consulta ainda - falta nome completo
"""

    elif current_step == 3:
        return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 3 (Exploração e benefícios)
- Eleve a consciência sobre a importância do tratamento
- Destaque os benefícios específicos
- Prepare o terreno para o agendamento
- Quando o cliente concordar, sugira agendar uma avaliação
"""

    elif current_step == 4:
        # Verifica se tem preferência salva
        preference = state_data.get("scheduling_preference")
        if preference:
            return terminal_instruction + f"""
# COMPORTAMENTO ESPECÍFICO - STEP 4 (Agendamento com preferência)
- Preferência detectada: {preference}
- Use buscar_horarios_disponiveis com a preferência: buscar_horarios_disponiveis(preferencia="{preference}")
- Sugira APENAS 2-3 horários que atendam a preferência
- Se não houver horários com a preferência, ofereça alternativas próximas
- Informe se a avaliação é gratuita
- Use formato: "[Dia da semana] dia (DD/MM/YYYY) às HH:mm"
- Quando o cliente escolher um horário, salve "data" e "horario"
"""
        else:
            return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 4 (Agendamento)
- Use buscar_horarios_disponiveis para obter slots diversos
- Sugira APENAS 2-3 horários distribuídos em diferentes dias
- Informe se a avaliação é gratuita
- Use formato: "[Dia da semana] dia (DD/MM/YYYY) às HH:mm"
- Quando o cliente escolher um horário, salve "data" e "horario"
- Se o cliente expressar preferência (ex: "tem sábado?"), use buscar_horarios_disponiveis(preferencia="sábado")
"""

    elif current_step == 5:
        if not state_manager.is_field_filled("nome"):
            return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 5 (Coleta do nome)
- O horário foi escolhido, agora precisa do nome completo
- Seja direto: "Para confirmar o agendamento, preciso do seu nome completo"
- NÃO chame nenhuma função ainda - apenas colete o nome
"""
        else:
            return terminal_instruction + f"""
# COMPORTAMENTO ESPECÍFICO - STEP 5 (Agendamento automático)
- Nome coletado: {state_data.get('nome')}
- Data: {state_data.get('data')} às {state_data.get('horario')}
- CHAME agendar_consulta com os dados coletados
- A função retornará a mensagem de confirmação completa com todos os detalhes
"""

    elif current_step == 6:
        return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 6 (Encerramento)
- Agendamento foi confirmado pelo sistema
- Finalize de forma amigável
- Forneça informações úteis (endereço, como chegar, etc.)
- Deseje boa sorte
"""

    elif current_step == 7:
        return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 7 (Pós-agendamento)
- Cliente já tem agendamento confirmado
- Responda dúvidas sem oferecer novos agendamentos
- Seja útil para reagendamentos se necessário
- Mantenha tom cordial
"""

    elif current_step == 8:
        return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 8 (Cancelamento)
- Cliente quer cancelar
- Use cancelar_agendamento se necessário
- Seja compreensivo
- IMPORTANTE: Após cancelar com sucesso, o sistema voltará automaticamente para step 4
- Você pode oferecer novo agendamento imediatamente
"""

    elif current_step == 9:
        if not state_manager.is_field_filled("reagendamento_data"):
            # Verifica se tem preferência salva
            preference = state_data.get("scheduling_preference")
            if preference:
                return terminal_instruction + f"""
# COMPORTAMENTO ESPECÍFICO - STEP 9 (Reagendamento com preferência)
- Cliente quer reagendar
- Preferência detectada: {preference}
- Use buscar_horarios_disponiveis(preferencia="{preference}")
- Sugira APENAS 2-3 horários que atendam a preferência
- Quando o cliente escolher, salve "reagendamento_data" e "reagendamento_horario"
"""
            else:
                return terminal_instruction + """
# COMPORTAMENTO ESPECÍFICO - STEP 9 (Reagendamento)
- Cliente quer reagendar
- Use buscar_horarios_disponiveis para obter novos slots diversos
- Sugira APENAS 2-3 horários distribuídos em diferentes dias
- Quando o cliente escolher, salve "reagendamento_data" e "reagendamento_horario"
- Se o cliente expressar preferência (ex: "tem sábado?"), use buscar_horarios_disponiveis(preferencia="sábado")
"""
        else:
            return terminal_instruction + f"""
# COMPORTAMENTO ESPECÍFICO - STEP 9 (Reagendamento automático)
- Nova data escolhida: {state_data.get('reagendamento_data')} às {state_data.get('reagendamento_horario')}
- CHAME reagendar_consulta com os dados coletados
- A função cuidará de cancelar o antigo e criar o novo
"""

    return terminal_instruction


class CompanyAgentSystem:
    """Sistema principal de agents para a empresa com suporte a contexto."""

    def __init__(self, context: CompanyContext):
        self.context = context
        self.config = context.company_config
        self.agents = self._create_agents()

    def _create_agents(self) -> Dict[str, Agent[CompanyContext]]:
        """Cria todos os agents necessários com contexto tipado."""
        # Primeiro cria os agents sem handoffs
        scheduling_agent = self._create_scheduling_agent()
        parser_agent = self._create_parser_agent()
        smart_scheduling_agent = self._create_smart_scheduling_agent()

        # Depois cria o main agent com handoffs para os outros
        main_agent = self._create_main_agent(scheduling_agent, parser_agent, smart_scheduling_agent)

        return {
            "main": main_agent,
            "scheduling": scheduling_agent,
            "parser": parser_agent,
            "smart_scheduling": smart_scheduling_agent
        }

    def _create_main_agent(self, scheduling_agent: Agent[CompanyContext], parser_agent: Agent[CompanyContext], smart_scheduling_agent: Agent[CompanyContext]) -> Agent[CompanyContext]:
        """Agent principal de conversação."""
        # Gera instruções completas usando a função do context_utils
        base_instructions = create_dynamic_instructions(
            company_config=self.config,
            customer_context=self.context.customer_context,
            funnel_stage=self.context.funnel_stage,
            funnel_status=self.context.funnel_status
        )

        # Cria o agent com instruções state-aware
        agent = Agent[CompanyContext](
            name="main",
            instructions=create_state_aware_instructions,  # Usa função state-aware
            model="gpt-4.1-mini-2025-04-14",
            model_settings=ModelSettings(
                temperature=0.7,
                max_tokens=300,
                top_p=0.9
            ),
            tools=[
                buscar_horarios_disponiveis,
                obter_informacoes_cliente,
                agendar_consulta,
                cancelar_agendamento,
                reagendar_consulta
            ],
            handoffs=[
                handoff(
                    agent=scheduling_agent,
                    tool_name_override="delegar_agendamento",
                    tool_description_override="Delegar para especialista em agendamento quando necessário"
                ),
                handoff(
                    agent=smart_scheduling_agent,
                    tool_name_override="agendamento_inteligente",
                    tool_description_override="Usar agendamento inteligente quando o usuário tiver preferências específicas de horário (manhã, tarde, dias específicos, etc)"
                )
            ]
        )

        # Salva instruções base para uso na função dinâmica
        agent._base_instructions = base_instructions

        return agent

    def _create_scheduling_agent(self) -> Agent[CompanyContext]:
        """Agent especializado em agendamento."""
        scheduling_config = self.config.get("scheduling_config", {})
        assistant_name = self.config.get("assistant_identity", {}).get("assistant_name", "Assistente")
        company_name = self.config.get("company_info", {}).get("company_name", "Nossa empresa")

        instructions = f"""
Você é especialista em agendamento da empresa.

CONFIGURAÇÕES:
- Horários: {scheduling_config.get('scheduling_hours', 'conforme disponibilidade')}
- Intervalo de agendamento: {scheduling_config.get('scheduling_interval_days', 30)} dias

IMPORTANTE: Sempre sugira no MÁXIMO 2 horários.
Use a ferramenta buscar_horarios_disponiveis quando necessário.
"""

        return Agent[CompanyContext](
            name="scheduling",
            instructions=instructions,
            model="gpt-4.1-mini-2025-04-14",
            model_settings=ModelSettings(temperature=0.3, max_tokens=300),
            tools=[buscar_horarios_disponiveis, agendar_consulta, cancelar_agendamento, reagendar_consulta]
        )

    def _create_parser_agent(self) -> Agent[CompanyContext]:
        """Agent para parsing e extração de informações."""
        instructions = """
Extraia informações estruturadas das mensagens:
- nome do cliente
- tipo de tratamento
- data/horário desejado
- se é cliente novo ou retorno

Retorne JSON estruturado.
"""

        return Agent[CompanyContext](
            name="parser",
            instructions=instructions,
            model="gpt-4.1-mini-2025-04-14",
            model_settings=ModelSettings(temperature=0.1, max_tokens=200)
        )

    def _create_smart_scheduling_agent(self) -> Agent[CompanyContext]:
        """Agent inteligente para análise de preferências de agendamento."""
        from datetime import datetime, timedelta
        import pytz

        SP_TZ = pytz.timezone('America/Sao_Paulo')
        now = datetime.now(SP_TZ)

        weekdays_pt = {
            0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
            3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
        }

        assistant_name = self.config.get("assistant_identity", {}).get("assistant_name", "Assistente")
        company_name = self.config.get("company_info", {}).get("company_name", "Nossa empresa")

        instructions = f"""
Você é um especialista em agendamento médico com habilidades avançadas de análise.

CONTEXTO TEMPORAL:
- Hoje é {weekdays_pt[now.weekday()]}, {now.strftime('%d/%m/%Y')}
- Amanhã será {weekdays_pt[(now + timedelta(days=1)).weekday()]}, {(now + timedelta(days=1)).strftime('%d/%m/%Y')}

SUAS RESPONSABILIDADES:
1. Analisar detalhadamente o que o cliente deseja em termos de horário
2. Identificar preferências explícitas e implícitas
3. Filtrar e sugerir os melhores horários disponíveis
4. Explicar suas escolhas de forma clara

PROCESSO DE ANÁLISE:
1. Use analyze_scheduling_intent para entender a intenção
2. Use filter_slots_by_intent com a intenção identificada
3. Apresente os horários de forma organizada e clara

FORMATO DE APRESENTAÇÃO:
- Agrupe por dia quando possível
- Mostre dia da semana + data + horário
- Explique porque escolheu esses horários
- Máximo 5 sugestões, idealmente 2-3

EXEMPLO:
"Entendi que você prefere horários pela manhã! Encontrei estas opções:

📅 Quinta-feira (04/01) - Manhã:
• 09:00
• 10:30

📅 Sexta-feira (05/01) - Manhã:
• 08:00
• 11:00

Qual horário ficaria melhor para você?"

IMPORTANTE: Seja preciso com as datas e dias da semana!
"""

        return Agent[CompanyContext](
            name="smart_scheduling",
            instructions=instructions,
            model="gpt-4.1-mini-2025-04-14",
            model_settings=ModelSettings(temperature=0.5, max_tokens=400),
            tools=[buscar_horarios_disponiveis]
        )

    def _format_treatments(self, treatments_list: list) -> str:
        """Formata lista de tratamentos para exibição."""
        if not treatments_list:
            return "tratamentos de serviços diversos"
        return ", ".join(treatments_list)

    def _format_schedule(self, schedule_config: dict) -> str:
        """Formata configuração de horários para exibição."""
        days_pt = {
            'monday': 'Segunda',
            'tuesday': 'Terça',
            'wednesday': 'Quarta',
            'thursday': 'Quinta',
            'friday': 'Sexta',
            'saturday': 'Sábado',
            'sunday': 'Domingo'
        }

        schedule_parts = []
        for day_en, day_pt in days_pt.items():
            if day_en in schedule_config:
                day_config = schedule_config[day_en]
                if day_config.get('open'):
                    morning = f"{day_config.get('morningStart', '')}-{day_config.get('morningEnd', '')}" if day_config.get('morningEnabled') else ""
                    afternoon = f"{day_config.get('afternoonStart', '')}-{day_config.get('afternoonEnd', '')}" if day_config.get('afternoonEnabled') else ""

                    if morning and afternoon:
                        schedule_parts.append(f"{day_pt}: {morning} e {afternoon}")
                    elif morning:
                        schedule_parts.append(f"{day_pt}: {morning}")
                    elif afternoon:
                        schedule_parts.append(f"{day_pt}: {afternoon}")

        return "; ".join(schedule_parts) if schedule_parts else "Segunda a Sexta: 8h-18h"

    def _format_few_shots(self, few_shots: list) -> str:
        """Formata exemplos few-shot."""
        if not few_shots:
            return ""

        formatted = "\n# EXEMPLOS DE CONVERSAS\n"
        for i, shot in enumerate(few_shots, 1):
            if isinstance(shot, dict):
                user_msg = shot.get("userMessage", "")
                bot_resp = shot.get("botResponse", "")
                formatted += f"\n## Exemplo {i}:\nUsuário: {user_msg}\nAssistente: {bot_resp}\n"

        return formatted