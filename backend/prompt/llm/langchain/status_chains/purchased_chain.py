"""
Purchased Customer Chain - For Customers Who Made Purchases
========================================================

Specialized chain for customers with PURCHASED status.
Handles: suporte pós-venda, orientações de tratamento, dúvidas sobre procedimentos.
Restrictions: Cannot schedule appointments - focus on post-sale support and care.
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


class PurchasedCustomerChain(BaseCustomerChain):
    """
    Chain for customers who made purchases.

    Capabilities:
    - Post-sale support and guidance
    - Treatment preparation instructions
    - Answer questions about procedures
    - Provide care instructions
    - Address post-treatment concerns
    - Upselling (if configured)

    Restrictions:
    - Cannot schedule new consultations
    - Focus on supporting existing treatment
    - Provide premium customer service experience
    """

    def _create_prompt_template(self) -> ChatPromptTemplate:
        """Create prompt template for purchased customers"""

        return ChatPromptTemplate.from_messages([
            ("system", """Você é {assistant_name}, especialista em suporte premium pós-venda da {company_name}.

CONTEXTO DO CLIENTE:
Status: {customer_status_description}
Última compra: {last_appointment}
Especialidades da empresa: {company_specialties}
{customer_context}

AÇÕES PERMITIDAS PARA ESTE CLIENTE:
{allowed_actions_list}

AÇÕES ESTRITAMENTE PROIBIDAS:
{restrictions_list}

DIRETRIZES ESPECÍFICAS PARA SUPORTE PÓS-VENDA:

1. ATENDIMENTO PREMIUM:
   - Trate como cliente VIP: "É um prazer atendê-lo(a)"
   - Demonstre gratidão: "Agradecemos por confiar em nosso trabalho"
   - Seja proativa: "Como posso garantir a melhor experiência?"
   - Mantenha relacionamento: "Estamos sempre aqui para você"
   - {premium_service_context}

2. ORIENTAÇÕES PRÉ-TRATAMENTO:
   - Explique preparação necessária de forma detalhada
   - Oriente sobre medicações e cuidados
   - Esclareça o que esperar no dia do procedimento
   - Confirme orientações recebidas na empresa
   - {pre_treatment_context}

3. SUPORTE DURANTE TRATAMENTO:
   - Responda dúvidas sobre processo em andamento
   - Forneça encorajamento e tranquilização
   - Explique etapas do tratamento
   - Oriente sobre cuidados entre sessões
   - {during_treatment_context}

4. CUIDADOS PÓS-TRATAMENTO:
   - Forneça instruções de cuidados específicos
   - Explique sinais normais vs. preocupantes
   - Oriente sobre higienização e medicamentos
   - Acompanhe recuperação e satisfação
   - {post_treatment_context}

5. RELACIONAMENTO CONTINUADO:
   - Mantenha contato para satisfação
   - Ofereça dicas de manutenção
   - Lembre sobre retornos e avaliações
   - {upselling_context}
   - {relationship_context}

ABORDAGEM DE EXCELÊNCIA:
- Demonstre conhecimento técnico avançado
- Seja consultiva e educativa
- Mantenha tom caloroso e próximo
- Antecipe necessidades do cliente
- Resolva problemas proativamente

IMPORTANTE:
- Este é um CLIENTE que investiu conosco
- Priorize satisfação e experiência premium
- NÃO ofereça novos agendamentos de consulta
- Para novos tratamentos, qualifique necessidade primeiro
- Foque em agregar valor ao tratamento atual

Horário atual: {current_datetime}"""),

            MessagesPlaceholder(variable_name="conversation_history"),

            ("human", "{user_input}")
        ])

    def _get_allowed_actions(self) -> List[ActionType]:
        """Get actions allowed for purchased customers"""
        return [
            ActionType.CLARIFY,
            ActionType.SUPPORT,
            ActionType.POST_SALE_SUPPORT,
            ActionType.OBJECTION_HANDLING  # For potential additional treatments
        ]

    def _get_status_specific_context(self, customer_status: CustomerStatusResult) -> Dict[str, Any]:
        """Get context specific to purchased customers"""

        # Calculate time since purchase
        days_since_purchase = 0
        if customer_status.last_appointment:
            days_since_purchase = (datetime.now() - customer_status.last_appointment).days

        # Determine treatment phase context
        treatment_phase = self._get_treatment_phase(days_since_purchase)

        # Get customer value context
        customer_value_context = self._get_customer_value_context(customer_status)

        return {
            "days_since_purchase": days_since_purchase,
            "treatment_phase": treatment_phase,
            "customer_value_context": customer_value_context,

            # Specific contexts for different support types
            "premium_service_context": self._get_premium_service_context(),
            "pre_treatment_context": self._get_pre_treatment_context(treatment_phase),
            "during_treatment_context": self._get_during_treatment_context(treatment_phase),
            "post_treatment_context": self._get_post_treatment_context(treatment_phase),
            "upselling_context": self._get_upselling_context(customer_status),
            "relationship_context": self._get_relationship_context(days_since_purchase),

            # Customer context
            "customer_context": f"Cliente há {days_since_purchase} dias. {treatment_phase}",

            # Support priority levels
            "is_recent_customer": days_since_purchase <= 7,
            "is_active_treatment": 7 < days_since_purchase <= 60,
            "is_maintenance_phase": days_since_purchase > 60,

            # Premium customer flags
            "high_value_customer": customer_status.total_purchases > 1,
            "loyal_customer": customer_status.total_appointments > 3,
        }

    def _get_treatment_phase(self, days_since: int) -> str:
        """Determine current treatment phase"""
        if days_since <= 0:
            return "Fase de preparação - cliente acabou de adquirir tratamento"
        elif days_since <= 7:
            return "Fase inicial - cliente pode estar se preparando ou iniciando tratamento"
        elif days_since <= 30:
            return "Fase ativa - cliente provavelmente em tratamento"
        elif days_since <= 90:
            return "Fase de finalização - tratamento pode estar terminando"
        else:
            return "Fase de manutenção - tratamento concluído, foco em cuidados"

    def _get_customer_value_context(self, customer_status: CustomerStatusResult) -> str:
        """Get context about customer value and history"""
        context_parts = []

        if customer_status.total_purchases > 1:
            context_parts.append("Cliente fidelizado com múltiplas compras")

        if customer_status.total_appointments > 3:
            context_parts.append("Cliente engajado com histórico extenso")

        if not context_parts:
            context_parts.append("Novo cliente - importante criar experiência excepcional")

        return ". ".join(context_parts) + "."

    def _get_premium_service_context(self) -> str:
        """Get context for premium service approach"""
        return """Atendimento premium para clientes:
- "Fico feliz em atendê-lo(a) como nosso cliente"
- "Como posso garantir a melhor experiência possível?"
- "Seu investimento conosco é muito valorizado"
- "Estamos comprometidos com sua total satisfação"
- "Qualquer dúvida, estou à disposição imediatamente"
"""

    def _get_pre_treatment_context(self, treatment_phase: str) -> str:
        """Get context for pre-treatment guidance"""
        if "preparação" in treatment_phase.lower():
            return """Orientações pré-tratamento detalhadas:
- Confirme todas as instruções recebidas na empresa
- Esclareça dúvidas sobre preparação específica
- Oriente sobre medicações e jejum se necessário
- Tranquilize sobre o procedimento
- Confirme data e horário do tratamento
"""
        else:
            return """Orientações gerais de preparação:
- Revise cuidados específicos para seu tratamento
- Esclareça qualquer dúvida sobre preparação
- Confirme se seguiu todas as orientações
"""

    def _get_during_treatment_context(self, treatment_phase: str) -> str:
        """Get context for support during treatment"""
        if "ativa" in treatment_phase.lower():
            return """Suporte durante tratamento ativo:
- "Como está se sentindo com o tratamento?"
- "Alguma dúvida sobre as etapas em andamento?"
- "Os cuidados entre sessões estão claros?"
- "Precisa de orientação sobre algo específico?"
- "Está seguindo todas as recomendações?"
"""
        else:
            return """Suporte geral durante tratamento:
- Esclareça dúvidas sobre processo
- Confirme cuidados entre etapas
- Tranquilize sobre normalidade de sintomas
"""

    def _get_post_treatment_context(self, treatment_phase: str) -> str:
        """Get context for post-treatment care"""
        if "manutenção" in treatment_phase.lower():
            return """Cuidados de manutenção e satisfação:
- "Como está seu sorriso após o tratamento?"
- "Está satisfeito(a) com os resultados?"
- "Alguma dúvida sobre manutenção dos resultados?"
- "Precisa de orientação sobre cuidados contínuos?"
- "Como podemos melhorar sua experiência?"
"""
        else:
            return """Cuidados pós-tratamento:
- Forneça instruções específicas de cuidados
- Explique sinais normais de recuperação
- Oriente sobre medicamentos e higienização
- Acompanhe evolução e conforto
"""

    def _get_upselling_context(self, customer_status: CustomerStatusResult) -> str:
        """Get context for potential upselling (if enabled)"""
        if customer_status.total_purchases > 1:
            return """Upselling para cliente fidelizado (se apropriado):
- Primeiro garanta satisfação total com tratamento atual
- Apenas mencione outros tratamentos se cliente demonstrar interesse
- Foque em complementaridade com tratamento realizado
- "Após finalizar este tratamento, posso apresentar outras opções"
"""
        else:
            return """Foco em satisfação (sem upselling ativo):
- Priorize totalmente satisfação com tratamento atual
- Apenas responda se cliente perguntar sobre outros tratamentos
- "Vamos focar em garantir o melhor resultado do seu tratamento atual"
"""

    def _get_relationship_context(self, days_since: int) -> str:
        """Get context for ongoing relationship building"""
        if days_since <= 30:
            return """Relacionamento inicial - construir confiança:
- Demonstre comprometimento com seu sucesso
- Seja proativa em suporte e orientações
- Mantenha comunicação regular e calorosa
"""
        else:
            return """Relacionamento de longo prazo - manter satisfação:
- Acompanhe satisfação contínua
- Lembre sobre retornos e avaliações
- Mantenha porta aberta para futuras necessidades
"""

    def _filter_restricted_content(self, response: str, allowed_actions) -> str:
        """Enhanced filtering for purchased customers"""
        response = super()._filter_restricted_content(response, allowed_actions)

        # Specific filters for purchased customers
        forbidden_phrases = [
            "agendar consulta",
            "nova consulta",
            "primeira consulta",
            "consulta de avaliação"
        ]

        for phrase in forbidden_phrases:
            if phrase in response.lower():
                response += "\n\n💎 Como nosso cliente, você pode entrar em contato diretamente conosco para qualquer necessidade adicional. Estamos sempre aqui para você!"
                break

        return response

    def provide_premium_care_instructions(self, treatment_type: str = "geral") -> str:
        """Provide premium care instructions"""

        instructions = {
            "geral": """
🌟 **Cuidados Premium para seu Tratamento:**

✅ **Cuidados Essenciais:**
• Siga rigorosamente as orientações médicas
• Mantenha higiene bucal impecável
• Evite alimentos muito quentes ou duros
• Use medicamentos conforme prescrito

📞 **Suporte Exclusivo:**
• Contato direto conosco para qualquer dúvida
• Retornos prioritários quando necessário
• Acompanhamento personalizado da evolução

💎 **Nosso Compromisso:**
• Garantia de satisfação total
• Resultados excepcionais
• Cuidado contínuo com sua saúde bucal
""",

            "implante": """
🦷 **Cuidados Premium - Implante:**

✅ **Primeiras 48h:**
• Gelo para reduzir inchaço
• Medicação rigorosamente no horário
• Alimentação líquida/pastosa
• Evitar esforço físico

📞 **Acompanhamento VIP:**
• Retorno em 7 dias para avaliação
• Contato imediato para emergências
• Orientação personalizada 24h

💎 **Resultado Garantido:**
• Integração óssea perfeita
• Sorriso natural e duradouro
• Satisfação 100% garantida
""",

            "ortodontia": """
😊 **Cuidados Premium - Ortodontia:**

✅ **Cuidados Diários:**
• Higiene reforçada com escova específica
• Uso de fio business ortodôntico
• Evitar alimentos duros/pegajosos
• Cera ortodôntica para conforto

📞 **Acompanhamento Personalizado:**
• Consultas regulares rigorosamente agendadas
• Ajustes com máximo conforto
• Evolução monitorada mensalmente

💎 **Sorriso dos Sonhos:**
• Alinhamento perfeito garantido
• Resultado que transforma vidas
• Autoestima renovada
"""
        }

        return instructions.get(treatment_type, instructions["geral"])

    def handle_satisfaction_check(self) -> str:
        """Generate satisfaction check response"""
        return """
🌟 **Verificação de Satisfação VIP**

Como nosso cliente valorizado, sua satisfação é nossa prioridade máxima!

✅ **Gostaria de saber:**
• Como você está se sentindo com o tratamento?
• Os resultados estão atendendo suas expectativas?
• Algum aspecto que podemos melhorar?
• Precisa de orientação adicional sobre algo?

💎 **Nosso Compromisso:**
Estamos comprometidos em garantir que você tenha a melhor experiência possível e resultados excepcionais!

Como posso ajudar você hoje?
""".strip()

    def provide_maintenance_guidance(self) -> str:
        """Provide long-term maintenance guidance"""
        return """
🔄 **Guia de Manutenção Premium**

Para manter seus resultados excepcionais:

✅ **Cuidados Contínuos:**
• Higiene bucal rigorosa diariamente
• Retornos preventivos regulares
• Alimentação consciente
• Proteção contra traumas

📅 **Agenda de Manutenção:**
• Avaliações semestrais
• Limpezas profissionais
• Ajustes quando necessário
• Acompanhamento personalizado

💎 **Garantia Vitalícia:**
Seus resultados são um investimento duradouro. Estamos aqui para preservá-los!

Precisa agendar sua próxima avaliação de manutenção?
""".strip()