"""
Lead Customer Chain - For New Leads Without History
=================================================

Specialized chain for customers with LEAD status.
Handles: agendamento inicial, qualificação, informações sobre empresa.
Full capabilities: Can schedule, qualify, inform, clarify.
"""

import logging
from typing import Dict, Any, List
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from .base_chain import BaseCustomerChain
from ..customer_routing.models import (
    CustomerStatusResult,
    ActionType
)

logger = logging.getLogger(__name__)


class LeadCustomerChain(BaseCustomerChain):
    """
    Chain for new leads without history.

    Capabilities:
    - Schedule new appointments
    - Qualify lead needs and interests
    - Provide company information
    - Answer general questions
    - Guide through scheduling process

    No restrictions - full conversation capabilities.
    """

    def _create_prompt_template(self) -> ChatPromptTemplate:
        """Create prompt template for lead customers"""

        return ChatPromptTemplate.from_messages([
            ("system", """Você é {assistant_name}, assistente especializada em agendamentos da {company_name}.

CONTEXTO DO CLIENTE:
Status: {customer_status_description}
Especialidades da empresa: {company_specialties}
{company_context}

AÇÕES PERMITIDAS PARA ESTE LEAD:
{allowed_actions_list}

DIRETRIZES ESPECÍFICAS PARA NOVOS LEADS:

1. QUALIFICAÇÃO DO LEAD:
   - Identifique necessidade: "Qual tratamento você tem interesse?"
   - Entenda urgência: "É algo que está incomodando?"
   - Qualifique expectativas: "Já fez algum tratamento similar?"
   - Identifique orçamento aproximado: Não pergunte diretamente, mas contextualize
   - {qualification_context}

2. AGENDAMENTO EFICIENTE:
   - Seja proativa: "Posso verificar nossa disponibilidade para você"
   - Ofereça opções: "Temos alguns horários disponíveis"
   - Confirme dados: "Qual seu nome completo?"
   - Facilite processo: "É bem simples, posso fazer agora"
   - {scheduling_context}

3. INFORMAÇÕES DA EMPRESA:
   - Apresente especialidades: "{company_specialties}"
   - Destaque diferenciais: "Nossa empresa se destaca por..."
   - Tranquilize sobre qualidade: "Profissionais experientes"
   - Mencione tecnologia: "Equipamentos modernos"
   - {company_info_context}

4. QUEBRA DE OBJEÇÕES INICIAIS:
   - Preço: "Investimento em sua saúde bucal"
   - Tempo: "Consulta inicial é rápida e sem compromisso"
   - Medo: "Ambiente acolhedor e profissionais cuidadosos"
   - Dúvidas: "Primeiro vamos entender sua necessidade"
   - {objection_handling_context}

5. CRIAÇÃO DE URGÊNCIA POSITIVA:
   - Disponibilidade: "Temos alguns horários ainda disponíveis"
   - Benefícios: "Quanto antes tratarmos, melhor será o resultado"
   - Facilidade: "Aproveitando que está em contato, já posso agendar"
   - {urgency_context}

FLUXO DE CONVERSA IDEAL:
1. Cumprimento caloroso e identificação da necessidade
2. Qualificação da necessidade e expectativas
3. Apresentação da empresa e diferenciais
4. Oferecimento de agendamento
5. Facilitação do processo de marcação

ABORDAGEM:
- Seja acolhedora e profissional
- Demonstre interesse genuíno
- Facilite ao máximo o agendamento
- Transmita confiança e credibilidade
- Seja educativa sobre tratamentos

IMPORTANTE: Este é um novo lead - todas as ações são permitidas!
Foque em converter o lead em agendamento através de excelente atendimento.

Horários disponíveis próximos: {available_slots_preview}
Horário atual: {current_datetime}"""),

            MessagesPlaceholder(variable_name="conversation_history"),

            ("human", "{user_input}")
        ])

    def _get_allowed_actions(self) -> List[ActionType]:
        """Get actions allowed for lead customers - all actions permitted"""
        return [
            ActionType.SCHEDULE_NEW,
            ActionType.QUALIFY,
            ActionType.INFORM,
            ActionType.CLARIFY
        ]

    def _get_status_specific_context(self, customer_status: CustomerStatusResult) -> Dict[str, Any]:
        """Get context specific to lead customers"""

        # Get available slots preview
        available_slots_preview = self._get_available_slots_preview()

        return {
            # Lead-specific contexts
            "qualification_context": self._get_qualification_context(),
            "scheduling_context": self._get_scheduling_context(),
            "company_info_context": self._get_company_info_context(),
            "objection_handling_context": self._get_objection_handling_context(),
            "urgency_context": self._get_urgency_context(),

            # Company and scheduling context
            "company_context": "Novo lead - foque em qualificação e agendamento",
            "available_slots_preview": available_slots_preview,

            # Lead qualification flags
            "is_new_lead": True,
            "can_schedule": True,
            "needs_qualification": True,
            "conversion_priority": "high",

            # Conversion tracking
            "lead_source": "whatsapp_chat",
            "interaction_goal": "schedule_appointment"
        }

    def _get_qualification_context(self) -> str:
        """Get context for lead qualification"""
        return """Qualificação eficiente do lead:
- "Qual tratamento tem interesse?" (necessidade principal)
- "Já fez algum orçamento em outro lugar?" (comparação)
- "É algo que está incomodando ou é preventivo?" (urgência)
- "Já conhece nossa empresa?" (awareness)
- "Que tipo de resultado está buscando?" (expectativas)
"""

    def _get_scheduling_context(self) -> str:
        """Get context for scheduling new appointments"""
        return """Agendamento proativo e facilitado:
- "Posso verificar nossa disponibilidade agora mesmo"
- "Que período funciona melhor: manhã ou tarde?"
- "Que tal agendarmos para esta semana ainda?"
- "É bem rápido, preciso apenas confirmar alguns dados"
- "A consulta inicial é sem compromisso"
"""

    def _get_company_info_context(self) -> str:
        """Get context for providing company information"""
        company_info = self.agent_config.get("company_info", {})

        return f"""Apresentação atrativa da empresa:
- "Nossa empresa se especializa em {company_info.get('specialties', ['Serviços gerais'])[0]}"
- "Profissionais experientes e qualificados"
- "Equipamentos modernos e ambiente confortável"
- "Atendimento personalizado e humanizado"
- "Ótima localização e facilidade de acesso"
"""

    def _get_objection_handling_context(self) -> str:
        """Get context for handling common lead objections"""
        return """Quebra de objeções comuns:

PREÇO: "Vamos primeiro entender sua necessidade, depois falamos sobre investimento"
TEMPO: "A consulta inicial é rápida, cerca de 30-45 minutos"
MEDO: "Nossa equipe é muito cuidadosa e o ambiente é acolhedor"
DÚVIDA: "Exatamente por isso a consulta é importante, para esclarecer tudo"
URGÊNCIA: "Entendo, vamos priorizar um horário mais próximo para você"
"""

    def _get_urgency_context(self) -> str:
        """Get context for creating positive urgency"""
        return """Criação de urgência positiva (sem pressão):
- "Temos alguns horários ainda disponíveis esta semana"
- "Problemas dentários tendem a se agravar se não tratados"
- "Quanto antes avaliarmos, melhor será o prognóstico"
- "Aproveitando que está em contato, já posso separar um horário"
- "A consulta inicial não tem compromisso, é para entendermos sua necessidade"
"""

    def _get_available_slots_preview(self) -> str:
        """Get preview of available slots for scheduling"""
        if not self.scheduling_service:
            return "Entre em contato para verificar disponibilidade"

        try:
            slots = self.scheduling_service.get_next_available_slots()
            if slots:
                # Show first 3 slots as preview
                preview = "\n".join([f"• {slot}" for slot in slots[:3]])
                if len(slots) > 3:
                    preview += f"\n• + {len(slots) - 3} outras opções"
                return preview
            else:
                return "Verificando disponibilidade..."
        except Exception as e:
            logger.error(f"[LeadChain] Error getting slots preview: {e}")
            return "Posso verificar disponibilidade em tempo real"

    def _filter_restricted_content(self, response: str, allowed_actions) -> str:
        """No filtering needed for leads - all actions allowed"""
        # Lead chains have no restrictions, but we can enhance responses

        # Add helpful scheduling prompts if appropriate
        if any(word in response.lower() for word in ["agendar", "marcar", "consulta", "horário"]):
            if "posso verificar" not in response.lower():
                response += "\n\nPosso verificar nossa disponibilidade agora mesmo, que período funciona melhor para você?"

        return response

    def get_qualification_questions(self) -> List[str]:
        """Get list of qualification questions for leads"""
        return [
            "Qual tratamento você tem interesse?",
            "É algo que está incomodando ou é preventivo?",
            "Já fez algum orçamento em outro lugar?",
            "Que tipo de resultado está buscando?",
            "Já conhece nossa empresa?",
            "Que período funciona melhor para você: manhã ou tarde?"
        ]

    def provide_company_overview(self) -> str:
        """Provide comprehensive company overview for leads"""
        company_info = self.agent_config.get("company_info", {})
        assistant_info = self.agent_config.get("assistant_identity", {})

        return f"""
🏥 **Sobre a {company_info.get('name', 'Nossa Empresa')}:**

✨ **Especialidades:**
{chr(10).join([f"• {spec}" for spec in company_info.get('specialties', ['Serviços gerais'])])}

👩‍⚕️ **Nossa Equipe:**
• Profissionais experientes e qualificados
• Atendimento humanizado e personalizado
• Educação continuada e técnicas modernas

🏢 **Estrutura:**
• Equipamentos de última geração
• Ambiente acolhedor e confortável
• Protocolos rigorosos de segurança

⏰ **Atendimento:**
{company_info.get('working_hours', 'Segunda a Sexta: 8h às 18h')}

🎯 **Nosso Diferencial:**
Combinamos expertise técnica com atendimento humanizado para oferecer a melhor experiência em cuidados de serviços.

Gostaria de agendar uma consulta para conhecer nossa empresa?
""".strip()

    def handle_scheduling_interest(self) -> str:
        """Handle when lead shows scheduling interest"""
        return """
📅 **Ótimo! Vamos agendar sua consulta**

Para facilitar seu agendamento, preciso de algumas informações:

✅ **Que período funciona melhor?**
• Manhã (8h às 12h)
• Tarde (13h às 17h)

✅ **Preferência de dias:**
• Durante a semana
• Sábado (se disponível)

✅ **Urgência:**
• Esta semana
• Próxima semana
• Sem pressa

Posso verificar nossa disponibilidade agora mesmo!
Qual seu nome completo para o agendamento?
""".strip()

    def provide_consultation_details(self) -> str:
        """Provide details about initial consultation"""
        return """
🔍 **Sobre sua Consulta Inicial:**

📋 **O que acontece na primeira consulta:**
• Avaliação completa da sua necessidade
• Análise detalhada
• Explicação do diagnóstico
• Apresentação das opções de tratamento
• Orçamento personalizado

⏱️ **Duração:** Aproximadamente 45 minutos
💰 **Investimento:** Consulta inicial sem compromisso
📝 **Documentos:** Apenas RG ou CNH

✨ **Nosso Compromisso:**
• Avaliação honesta e transparente
• Explicação clara de todas as opções
• Orçamento justo e detalhado
• Sem pressão para fechar

Está pronto(a) para agendar? Posso separar um horário agora!
""".strip()
