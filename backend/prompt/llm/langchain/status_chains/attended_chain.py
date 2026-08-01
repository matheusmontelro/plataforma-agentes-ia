"""
Attended Customer Chain - For Customers Who Attended Consultations
===============================================================

Specialized chain for customers with ATTENDED status.
Handles: dúvidas pós-consulta, quebra de objeções, suporte ao tratamento.
Restrictions: Cannot schedule appointments - focus on post-consultation support.
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


class AttendedCustomerChain(BaseCustomerChain):
    """
    Chain for customers who attended consultations.

    Capabilities:
    - Answer questions about diagnosis/treatment plan
    - Handle pricing objections
    - Provide post-consultation support
    - Clarify treatment procedures
    - Address concerns about treatment

    Restrictions:
    - Cannot schedule new appointments
    - Cannot reschedule (they already attended)
    - Focus on consultation follow-up and support
    """

    def _create_prompt_template(self) -> ChatPromptTemplate:
        """Create prompt template for attended customers"""

        return ChatPromptTemplate.from_messages([
            ("system", """Você é {assistant_name}, especialista em suporte pós-consulta da {company_name}.

CONTEXTO DO CLIENTE:
Status: {customer_status_description}
Última consulta: {last_appointment}
Especialidades da empresa: {company_specialties}
{customer_context}

AÇÕES PERMITIDAS PARA ESTE CLIENTE:
{allowed_actions_list}

AÇÕES ESTRITAMENTE PROIBIDAS:
{restrictions_list}

DIRETRIZES ESPECÍFICAS PARA SUPORTE PÓS-CONSULTA:

1. QUEBRA DE OBJEÇÕES DE PREÇO:
   - Enfatize o valor do tratamento: "Investimento na sua saúde bucal"
   - Mencione consequências de não tratar: "Problemas podem se agravar"
   - Ofereça opções de pagamento: "Temos facilidades que podem ajudar"
   - Destaque expertise profissional: "Nossos especialistas garantem qualidade"
   - {pricing_objection_context}

2. DÚVIDAS SOBRE TRATAMENTO:
   - Explique procedimentos de forma simples e clara
   - Aborde medos comuns: "É um procedimento seguro e confortável"
   - Mencione tecnologia e cuidados: "Utilizamos equipamentos modernos"
   - Esclareça tempo de recuperação e cuidados pós-tratamento
   - {treatment_explanation_context}

3. SUPORTE PÓS-CONSULTA:
   - Ajude com dúvidas sobre orçamento recebido
   - Esclareça próximos passos do tratamento
   - Forneça orientações de preparação
   - Confirme dados para agendamento futuro (quando cliente decidir)
   - {post_consultation_context}

4. MOTIVAÇÃO PARA TRATAMENTO:
   - Use linguagem positiva: "Sua nova sorrise"
   - Enfatize benefícios: "Qualidade de vida", "autoestima", "saúde"
   - Crie senso de urgência moderado: "Quanto antes tratarmos, melhor"
   - Demonstre comprometimento: "Estaremos com você em todo processo"
   - {motivation_context}

ABORDAGEM CONSULTIVA:
- Seja consultora, não vendedora
- Foque em resolver dúvidas genuínas
- Demonstre conhecimento técnico de forma acessível
- Seja empática com preocupações financeiras
- Destaque benefícios sem pressionar

IMPORTANTE:
- Este cliente JÁ passou por consulta
- NÃO ofereça novos agendamentos
- Para continuidade do tratamento, oriente a entrar em contato quando decidir prosseguir
- Foque em agregar valor e quebrar resistências

Horário atual: {current_datetime}"""),

            MessagesPlaceholder(variable_name="conversation_history"),

            ("human", "{user_input}")
        ])

    def _get_allowed_actions(self) -> List[ActionType]:
        """Get actions allowed for attended customers"""
        return [
            ActionType.CLARIFY,
            ActionType.SUPPORT,
            ActionType.OBJECTION_HANDLING
        ]

    def _get_status_specific_context(self, customer_status: CustomerStatusResult) -> Dict[str, Any]:
        """Get context specific to attended customers"""

        # Calculate time since consultation
        days_since_consultation = 0
        if customer_status.last_appointment:
            days_since_consultation = (datetime.now() - customer_status.last_appointment).days

        # Determine consultation recency context
        recency_context = self._get_recency_context(days_since_consultation)

        # Get customer value context
        customer_value_context = self._get_customer_value_context(customer_status)

        return {
            "days_since_consultation": days_since_consultation,
            "recency_context": recency_context,
            "customer_value_context": customer_value_context,

            # Specific context for objection handling
            "pricing_objection_context": self._get_pricing_objection_context(days_since_consultation),
            "treatment_explanation_context": self._get_treatment_explanation_context(),
            "post_consultation_context": self._get_post_consultation_context(days_since_consultation),
            "motivation_context": self._get_motivation_context(days_since_consultation),

            # Customer context
            "customer_context": f"Cliente compareceu há {days_since_consultation} dias. {recency_context}",

            # Urgency and follow-up
            "is_hot_lead": days_since_consultation <= 3,  # Recent consultation
            "needs_follow_up": 3 < days_since_consultation <= 14,  # Medium term
            "is_cold_lead": days_since_consultation > 14,  # Older consultation
        }

    def _get_recency_context(self, days_since: int) -> str:
        """Get context based on consultation recency"""
        if days_since <= 1:
            return "Consulta muito recente - cliente provavelmente ainda processando informações."
        elif days_since <= 3:
            return "Consulta recente - momento ideal para esclarecimentos e quebra de objeções."
        elif days_since <= 7:
            return "Consulta na semana passada - cliente pode ter dúvidas após reflexão."
        elif days_since <= 14:
            return "Consulta há algumas semanas - importante reativar interesse."
        else:
            return "Consulta mais antiga - necessário recontextualizar benefícios."

    def _get_customer_value_context(self, customer_status: CustomerStatusResult) -> str:
        """Get context about customer value"""
        if customer_status.total_appointments > 1:
            return "Cliente com histórico na empresa - demonstra confiança."
        else:
            return "Primeira consulta na empresa - importante criar confiança."

    def _get_pricing_objection_context(self, days_since: int) -> str:
        """Get specific context for pricing objections"""
        if days_since <= 3:
            return """Consulta recente - normal ter dúvidas sobre investimento:
- "Entendo que é um valor significativo, vamos conversar sobre isso"
- "Nosso orçamento inclui todo acompanhamento necessário"
- "Qual aspecto do valor gostaria de esclarecer?"
- "Temos opções de pagamento que podem facilitar"
"""
        else:
            return """Consulta há mais tempo - renovar valor percebido:
- "Lembra dos benefícios que conversamos na consulta?"
- "Problemas dentários tendem a se agravar com o tempo"
- "O investimento hoje evita custos maiores no futuro"
- "Nossa equipe está preparada para oferecer o melhor resultado"
"""

    def _get_treatment_explanation_context(self) -> str:
        """Get context for treatment explanations"""
        return """Para esclarecimentos sobre tratamento:
- Use linguagem simples e acessível
- Explique benefícios específicos para o caso do cliente
- Aborde mitos e medos comuns
- Mencione tecnologia e conforto disponíveis
- Dê exemplos de casos similares (sem identificar outros clientes)
"""

    def _get_post_consultation_context(self, days_since: int) -> str:
        """Get context for post-consultation support"""
        if days_since <= 7:
            return """Suporte pós-consulta imediato:
- "Como você está se sentindo após nossa conversa?"
- "Surgiu alguma dúvida depois da consulta?"
- "Gostaria de revisar algum ponto do plano de tratamento?"
- "Posso ajudar com orientações para o próximo passo?"
"""
        else:
            return """Suporte pós-consulta tardio:
- "Como posso ajudar com seu plano de tratamento?"
- "Gostaria de relembrar os benefícios discutidos?"
- "Houve mudanças na sua situação desde a consulta?"
- "Posso esclarecer algum aspecto específico?"
"""

    def _get_motivation_context(self, days_since: int) -> str:
        """Get context for treatment motivation"""
        if days_since <= 3:
            return """Motivação pós-consulta imediata - foque em esclarecimentos:
- Não pressione, esclareça dúvidas
- Reforce benefícios mencionados na consulta
- Demonstre disponibilidade para suporte
"""
        else:
            return """Motivação pós-consulta tardia - reengage com benefícios:
- Relembre necessidade identificada na consulta
- Enfatize progressão de problemas não tratados
- Destaque resultados que outros clientes alcançaram
"""

    def _filter_restricted_content(self, response: str, allowed_actions) -> str:
        """Enhanced filtering for attended customers"""
        response = super()._filter_restricted_content(response, allowed_actions)

        # Specific filters for attended customers
        forbidden_phrases = [
            "agendar consulta",
            "marcar horário",
            "quando você pode vir",
            "disponibilidade para"
        ]

        for phrase in forbidden_phrases:
            if phrase in response.lower():
                response += "\n\n💡 Para dar continuidade ao seu tratamento, entre em contato conosco quando estiver pronto(a) para prosseguir. Estou aqui para esclarecer qualquer dúvida!"
                break

        return response

    def get_objection_handling_response(self, objection_type: str) -> str:
        """Get specific response for common objections"""

        objection_responses = {
            "price": """
Entendo sua preocupação com o investimento. É importante lembrar que:

💰 **Valor do tratamento:**
- Inclui todo acompanhamento necessário
- Evita custos maiores no futuro
- Investimento na sua qualidade de vida

💳 **Facilidades de pagamento:**
- Parcelamento sem juros
- Várias opções de pagamento
- Planos que cabem no seu orçamento

Qual aspecto específico gostaria de conversar?
""",

            "pain": """
Entendo sua preocupação com possível desconforto. Posso te tranquilizar:

😌 **Conforto durante tratamento:**
- Anestesia eficiente para eliminar dor
- Equipamentos modernos e menos invasivos
- Profissionais experientes e cuidadosos

🛡️ **Nosso compromisso:**
- Seu conforto é nossa prioridade
- Comunicação constante durante procedimento
- Paradas sempre que necessário

Que tal conversarmos sobre suas preocupações específicas?
""",

            "time": """
Entendo que tempo é precioso. Vamos otimizar ao máximo:

⏰ **Eficiência no tratamento:**
- Planejamento para mínimo de sessões
- Horários flexíveis quando possível
- Procedimentos otimizados

📅 **Flexibilidade:**
- Horários que se adequem à sua agenda
- Reagendamentos quando necessário
- Comunicação prévia sobre duração

Como podemos adequar melhor à sua rotina?
"""
        }

        return objection_responses.get(objection_type,
            "Entendo sua preocupação. Vamos conversar sobre isso e encontrar a melhor solução para você!")

    def provide_treatment_benefits(self, treatment_type: str = "geral") -> str:
        """Provide specific benefits for treatment"""

        benefits = {
            "geral": """
✨ **Benefícios do seu tratamento:**
• Melhora significativa na qualidade de vida
• Aumento da autoestima e confiança
• Prevenção de problemas mais graves
• Sorrir sem constrangimento
• Mastigação e digestão melhoradas
• Investimento duradouro na sua saúde
""",

            "implante": """
🦷 **Benefícios do implante:**
• Solução definitiva e duradoura
• Aparência e função como dente natural
• Preserva osso e dentes adjacentes
• Não compromete outros dentes
• Autoestima renovada
• Mastigação eficiente restaurada
""",

            "ortodontia": """
😊 **Benefícios da ortodontia:**
• Sorriso alinhado e harmônico
• Melhora na mastigação
• Facilita higienização
• Previne problemas articulares
• Aumento da autoestima
• Benefícios que duram toda vida
"""
        }

        return benefits.get(treatment_type, benefits["geral"])