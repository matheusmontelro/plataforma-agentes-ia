# Agent Factory for Agents SDK
import logging
from typing import Dict, Any, Optional
from agents import Agent, ModelSettings

from ..config.company_context import CompanyContext
from ..utils.context_utils import create_dynamic_instructions

logger = logging.getLogger(__name__)


class AgentFactory:
    """
    Factory para criar agents configurados para cada empresa.
    Centraliza a criação e configuração de agents.
    """

    @staticmethod
    def create_main_agent(context: CompanyContext) -> Agent:
        """
        Cria o agent principal para atendimento.
        """
        instructions = create_dynamic_instructions(
            company_config=context.company_config,
            customer_context=context.customer_context,
            funnel_stage=context.funnel_stage,
            funnel_status=context.funnel_status
        )

        # Adiciona instruções específicas para leads
        instructions += """

OBJETIVO PRINCIPAL:
Seu objetivo é converter leads em agendamentos, fornecendo informações sobre a empresa
e seus serviços de forma acolhedora e profissional.

DIRETRIZES PARA AGENDAMENTO:
1. Quando o cliente demonstrar interesse, ofereça horários disponíveis
2. Use a ferramenta check_available_slots para buscar horários
3. Apresente no máximo 5-10 opções de horários
4. Seja flexível e tente acomodar as preferências do cliente
5. Confirme todos os detalhes antes de finalizar

IMPORTANTE:
- Sempre use as ferramentas disponíveis quando necessário
- Mantenha as respostas concisas e focadas
- Seja proativo em oferecer agendamento quando apropriado
"""

        return Agent(
            name="main_agent",
            instructions=instructions,
            model="gpt-4.1-mini-2025-04-14",
            model_settings=ModelSettings(
                temperature=0.7,
                max_tokens=500
            )
        )

    @staticmethod
    def create_scheduling_agent(context: CompanyContext) -> Agent:
        """
        Cria agent especializado em agendamento.
        """
        company_name = context.get_company_name()
        assistant_name = context.get_assistant_name()

        instructions = f"""
Você é {assistant_name}, especialista em agendamento da {company_name}.

SUAS RESPONSABILIDADES:
1. Buscar e apresentar horários disponíveis
2. Entender as preferências do cliente (dia, horário, período)
3. Confirmar dados do agendamento
4. Processar o agendamento no sistema

PROCESSO DE AGENDAMENTO:
1. Use check_available_slots para buscar horários
2. Filtre baseado nas preferências do cliente
3. Apresente opções de forma clara e organizada
4. Confirme a escolha do cliente
5. Use schedule_appointment para finalizar

DICAS:
- Seja flexível com horários alternativos
- Explique claramente cada opção
- Confirme nome e telefone antes de agendar
"""

        return Agent(
            name="scheduling_specialist",
            instructions=instructions,
            model="gpt-4.1-mini-2025-04-14",
            model_settings=ModelSettings(
                temperature=0.5,
                max_tokens=400
            )
        )

    @staticmethod
    def create_objection_handler_agent(context: CompanyContext) -> Agent:
        """
        Cria agent para lidar com objeções.
        """
        company_config = context.company_config
        financial_config = company_config.get("financial_config", {})

        instructions = f"""
Você é um especialista em lidar com objeções e preocupações de clientes.

OBJEÇÕES COMUNS E RESPOSTAS:

1. PREÇO/CUSTO:
- Destaque o valor do tratamento para a saúde
- Mencione opções de pagamento: {financial_config.get('payment_options', 'diversas formas de pagamento')}
- Enfatize a qualidade do atendimento

2. TEMPO/URGÊNCIA:
- Mostre horários próximos disponíveis
- Explique a importância do cuidado preventivo
- Seja flexível com alternativas

3. MEDO/ANSIEDADE:
- Demonstre empatia e compreensão
- Explique os procedimentos de forma simples
- Destaque o ambiente acolhedor da empresa

4. LOCALIZAÇÃO:
- Forneça instruções claras de como chegar
- Mencione facilidades de acesso e estacionamento

SEMPRE:
- Mantenha tom empático e compreensivo
- Foque nos benefícios para o cliente
- Ofereça soluções, não apenas respostas
"""

        return Agent(
            name="objection_handler",
            instructions=instructions,
            model="gpt-4.1-mini-2025-04-14",
            model_settings=ModelSettings(
                temperature=0.8,
                max_tokens=400
            )
        )

    @staticmethod
    def create_parser_agent() -> Agent:
        """
        Cria agent para parsing e análise.
        """
        instructions = """
Você é um analisador especializado em extrair informações estruturadas.
Retorne SEMPRE em formato JSON válido.
Seja preciso e objetivo em suas análises.
"""

        return Agent(
            name="parser_agent",
            instructions=instructions,
            model="gpt-4.1-mini-2025-04-14",
            model_settings=ModelSettings(
                temperature=0.1,
                max_tokens=200
            )
        )

    @staticmethod
    def create_smart_agent(
        name: str,
        role: str,
        context: CompanyContext,
        additional_instructions: str = "",
        model: str = "gpt-4.1-mini-2025-04-14",
        temperature: float = 0.7
    ) -> Agent:
        """
        Cria um agent customizado com configurações específicas.
        """
        base_instructions = create_dynamic_instructions(
            company_config=context.company_config,
            customer_context=context.customer_context
        )

        full_instructions = f"""
{base_instructions}

SEU PAPEL: {role}

{additional_instructions}
"""

        return Agent(
            name=name,
            instructions=full_instructions,
            model=model,
            model_settings=ModelSettings(
                temperature=temperature,
                max_tokens=500
            )
        )