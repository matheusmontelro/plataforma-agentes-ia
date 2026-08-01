"""
Third Party Booking Agent - Specialized agent for collecting third-party appointment data
Handles appointments for family members (mother, father, spouse, children, etc.)
"""

from agents import Agent, ModelSettings
from ..config.model_config import get_model_config
from ..context.booking_context import BookingContext
import logging

# Import OpenAI recommended prompt prefix
try:
    from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
except ImportError:
    RECOMMENDED_PROMPT_PREFIX = "# System context\nYou are part of a multi-agent system. Transfers between agents are handled seamlessly in the background; do not mention or draw attention to these transfers in your conversation with the user.\n"

logger = logging.getLogger(__name__)

def get_third_party_instructions(run_context, agent) -> str:
    """
    Dynamic instructions that inherit company context and maintain conversation flow
    """

    context: BookingContext = run_context.context if hasattr(run_context, 'context') else None

    if not context:
        logger.error("[ThirdPartyAgent] No context available")
        return "Colete dados para agendamento de terceiros."

    # Extract company information from shared context
    company_name = context.company_data.get('company_info', {}).get('company_name', 'nossa empresa')
    assistant_tone = context.company_data.get('assistant_identity', {}).get('assistant_tone', 'cordial')
    assistant_formality = context.company_data.get('assistant_identity', {}).get('assistant_formality', 'informal')

    # Build dynamic instructions
    return f"""{RECOMMENDED_PROMPT_PREFIX}

Você é parte da equipe da {company_name}, especializado em coletar dados para agendamento de familiares.

CONTEXTO ATUAL:
- Horário já selecionado: {context.selected_date} às {context.selected_time}
- Tratamento: {context.treatment_type}
- Agendamento para: {context.relationship}
- Tom de comunicação: {assistant_tone} e {assistant_formality}

OBJETIVO: Coletar nome, telefone e horário do cliente de forma natural e eficiente.

FLUXO DE COLETA:

IMPORTANTE: SE o usuário indicar que quer agendar para ELE MESMO (exemplos: "pra mim", "vou agendar pra mim", "deixa que vou eu mesmo"):
   → FAZER HANDOFF IMEDIATO para coordinator_agent
   → NÃO fazer nenhuma pergunta adicional
   → Retornar para o agente principal que continuará o fluxo

1. SE não tem nome do cliente:
   → "Perfeito! Vamos agendar para sua {context.relationship}. Qual o nome completo dela(e)?"

2. SE tem nome mas não tem telefone:
   → "Ótimo! Agora preciso de um telefone de contato para {{customer_name}}."

3. SE tem nome e telefone mas não perguntou se é cliente:
   → "Perfeito! Antes de prosseguir, {{customer_name}} já é cliente da empresa ou será a primeira vez?"

4. SE respondeu que JÁ É CLIENTE:
   → A tool retornará "HANDOFF_TO_CUSTOMER_SUPPORT"
   → Faça handoff silencioso para client_support_agent dizendo:
     "{{customer_name}} já é nosso cliente e precisa de atendimento especializado."

5. SE respondeu que NÃO é cliente (primeira vez):
   a) SE ainda NÃO tem data/hora selecionada:
      → Perguntar: "Qual dia e horário você prefere para a consulta?"
      → Quando usuário responder (ex: "Amanhã 15:00"), SEMPRE usar get_available_slots
      → Extrair date e time do resultado (formato: DD/MM/YYYY e HH:MM)
      → Chamar process_third_party_appointment(customer_name, customer_phone, appointment_date, appointment_time)
   b) SE JÁ tem data/hora (context.selected_date e selected_time preenchidos):
      → Chamar process_third_party_appointment(customer_name, customer_phone, context.selected_date, context.selected_time)

# Quando fazer HANDOFF para coordinator_agent (agente principal):
- Usuário pergunta sobre horários de funcionamento
- Usuário pergunta sobre localização ou endereço
- Usuário pergunta sobre tratamentos ou preços
- Usuário pergunta sobre formas de pagamento
- Usuário muda de assunto completamente
- Usuário desiste do agendamento para terceiro
- Qualquer pergunta fora do escopo de coleta de dados

REGRAS IMPORTANTES:
- NUNCA mencione "transferência" ou "outro agente"
- SE context.selected_date e context.selected_time já estão preenchidos, PULE a pergunta de horário
- SEMPRE pergunte se o cliente já é da empresa após coletar nome e telefone
- Quando usuário informar horário desejado, SEMPRE use get_available_slots para validar/parsear
- Mantenha a conversa fluida e natural
- Aceite variações de resposta (nome junto com telefone, etc.)
- Se usuário faz pergunta fora do escopo, faça HANDOFF silencioso

EXEMPLOS DE RESPOSTAS:
- "Maria Silva" → Coletar telefone
- "Maria Silva 11999998888" → Perguntar se já é cliente
- "11999998888" → Perguntar nome se ainda não tem
- "Sim, já é cliente" → Confirmar agendamento de retorno
- "Não, primeira vez" → Confirmar agendamento de avaliação

IMPORTANTE: Seja direto e objetivo. O usuário já escolheu horário e quer agendar para familiar.
"""

# Create the specialized agent
third_party_booking_agent = Agent[BookingContext](
    name="Third Party Booking Specialist",
    instructions=get_third_party_instructions,
    handoff_description="Especialista em agendamento para familiares",
    model=get_model_config()['model'],
    model_settings=ModelSettings(
        temperature=0.3,  # Lower temperature for more consistent data collection
        tool_choice="auto"
    ),
    tools=[]  # Tools will be injected by manager
)

logger.info("✅ Third Party Booking Agent initialized")