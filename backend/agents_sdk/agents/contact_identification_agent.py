"""
Customer Identification Agent - Specialized agent for identifying existing customers
Uses LLM for semantic analysis following the same pattern as other agents_sdk tools
"""

import logging
from typing import Dict, Any
from pydantic import BaseModel
from datetime import datetime

from agents import Agent, function_tool, handoff, RunContextWrapper
import openai

from ..context.contact_context import CustomerContext
from backend.services.ai_provider_service import get_company_openai_api_key

# Import OpenAI recommended prompt prefix
try:
    from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
except ImportError:
    RECOMMENDED_PROMPT_PREFIX = "# System context\nYou are part of a multi-agent system. Transfers between agents are handled seamlessly in the background; do not mention or draw attention to these transfers in your conversation with the user.\n"

logger = logging.getLogger(__name__)

class CustomerStatusRequest(BaseModel):
    """Request for customer status verification"""
    user_response: str

class CustomerStatusResult(BaseModel):
    """Result of customer status verification"""
    claims_to_be_customer: bool
    confidence: float
    reasoning: str
    user_intent: str
    recently_evaluated: bool = False  # NEW: Flag if customer recently had evaluation

class CustomerIntentRequest(BaseModel):
    """Request for customer intent classification"""
    user_response: str

class CustomerIntentResult(BaseModel):
    """Result of customer intent analysis"""
    intent_category: str  # 'scheduling_evaluation', 'support_needed', 'unclear'
    confidence: float
    reasoning: str
    suggested_action: str


def _get_context_openai_api_key(
    context: RunContextWrapper[CustomerContext],
) -> str:
    runtime_context = context.context
    return get_company_openai_api_key(
        runtime_context.db,
        int(runtime_context.company_id),
    )


@function_tool
def analyze_customer_status_with_llm(
    context: RunContextWrapper[CustomerContext],
    request: CustomerStatusRequest,
) -> CustomerStatusResult:
    """
    Uses LLM to analyze if user claims to be an existing customer of the company

    Args:
        request: User response to analyze

    Returns:
        CustomerStatusResult with LLM analysis
    """
    try:
        client = openai.OpenAI(
            api_key=_get_context_openai_api_key(context),
        )

        analysis_prompt = f"""
Você é um especialista em análise de intenções de clientes de empresas de serviços.

Analise a seguinte resposta do usuário e determine:
1. O usuário AFIRMA ser um cliente existente da empresa?
2. Qual o nível de confiança (0.0 a 1.0)?
3. Qual a intenção principal do usuário?
4. IMPORTANTE: O cliente menciona que JÁ FEZ AVALIAÇÃO RECENTEMENTE?
5. IMPORTANTE: O cliente menciona DENTISTA ESPECÍFICO por nome? (ex: Dr. Letícia, Dra. Maria)
6. IMPORTANTE: O cliente menciona TRATAMENTO ESPECÍFICO? (restauração, canal, implante, limpeza, manutenção)

RESPOSTA DO USUÁRIO: "{request.user_response}"

EXEMPLOS DE RESPOSTAS QUE INDICAM SER CLIENTE (confidence >= 0.7):
- "Já sou cliente da empresa"
- "Sou cliente de vocês"
- "Já fiz tratamento aí"
- "Já consulto com vocês"
- "Sou cadastrado na empresa"
- "Já vim aí antes"

EXEMPLOS DE RESPOSTAS AMBÍGUAS (confidence < 0.7 - PRECISA CLARIFICAÇÃO):
- "estou buscando atendimento" → NÃO deixa claro se é cliente ou não
- "quero consulta" → NÃO especifica se é primeira vez ou retorno
- "preciso de ajuda" → Muito vago
- "quero agendar" → Não indica se é cliente existente
- "to precisando" → Muito informal e vago

EXEMPLOS DE CLIENTE QUE JÁ FEZ AVALIAÇÃO (recently_evaluated=true):
- "Já fiz avaliação"
- "Fiz avaliação semana passada"
- "Fiz avaliação com o doutor"
- "O doutor já me avaliou"
- "Já passei pela avaliação"
- "Fiz exame/avaliação recentemente"
- "Quero agendar RETORNO com Dr./Dra. [nome]" (contexto de retorno)
- "Gostaria de marcar MANUTENÇÃO com a Dra. Letícia" (contexto de manutenção)
- "Preciso agendar retorno com Dr. João"
- "O Dr. João me atendeu" (contexto passado)
- "Meu dentista é o Dr. Carlos" (afirma ser cliente)
- "Quero agendar MINHA restauração" (tratamento específico já definido)
- "Preciso fazer o canal que o doutor passou"
- "Vim fazer a limpeza de rotina"
- "Quero marcar minha manutenção"

EXEMPLOS QUE NÃO INDICAM AVALIAÇÃO PRÉVIA (recently_evaluated=false E claims_to_be_customer=false):
- "Quero fazer AVALIAÇÃO com Dr./Dra. [nome]" (nova avaliação, preferência de dentista) → NÃO É CLIENTE
- "Preciso de AVALIAÇÃO para prótese com Dra. Ana" (nova consulta) → NÃO É CLIENTE
- "Preciso de uma avaliação para prótese protocolo com a Dra. Ana" → NÃO É CLIENTE (solicita avaliação)
- "Gostaria de consultar com Dr./Dra. [nome]" (pode ser primeira vez) → NÃO É CLIENTE
- "Quero agendar consulta com [dentista]" (sem contexto de retorno) → NÃO É CLIENTE
- "Quero ser cliente" → NÃO É CLIENTE AINDA
- "Gostaria de conhecer a empresa" → NÃO É CLIENTE
- "Nunca fui aí" → NÃO É CLIENTE
- "É a primeira vez" → NÃO É CLIENTE
- "Primeira consulta" → NÃO É CLIENTE
- "Não conheço a empresa" → NÃO É CLIENTE

REGRA CRÍTICA PARA MENSAGENS AMBÍGUAS:
- Se a mensagem NÃO deixa CLARO se é cliente existente ou novo → confidence DEVE ser < 0.7
- Exemplos: "estou buscando atendimento", "quero consulta", "preciso de ajuda" → confidence = 0.3~0.5
- Apenas use confidence >= 0.7 quando houver AFIRMAÇÃO EXPLÍCITA de ser cliente

REGRAS ESPECIAIS:
1. Se o usuário mencionar dentista específico + CONTEXTO DE RETORNO/MANUTENÇÃO = recently_evaluated: true
2. Se o usuário mencionar "fazer AVALIAÇÃO com Dr./Dra." = recently_evaluated: FALSE + claims_to_be_customer: FALSE (nova avaliação, NÃO é cliente)
3. Se o usuário mencionar "preciso de avaliação" em QUALQUER contexto = claims_to_be_customer: FALSE (solicitação de nova avaliação)
4. Se o usuário mencionar tratamento específico com possessivo ("minha restauração", "meu canal") = recently_evaluated: true
5. Se mencionar "limpeza de rotina" ou "manutenção" = recently_evaluated: true
6. IMPORTANTE: Diferencie entre:
   - "Quero FAZER uma avaliação [com Dr./Dra. X]" = Nova avaliação (claims_to_be_customer: FALSE, recently_evaluated: false)
   - "PRECISO de avaliação para [tratamento]" = Nova avaliação (claims_to_be_customer: FALSE, recently_evaluated: false)
   - "Quero AGENDAR restauração/canal/implante" = Tratamento definido (recently_evaluated: true)
   - "Quero agendar RETORNO com Dr./Dra." = Retorno (recently_evaluated: true)

🔴 REGRA CRÍTICA DE OURO:
Palavra-chave "AVALIAÇÃO" em qualquer contexto = SEMPRE claims_to_be_customer: FALSE (é um lead/novo cliente querendo avaliação)
EXCEÇÃO ÚNICA: "JÁ fiz avaliação" = claims_to_be_customer: TRUE + recently_evaluated: true

Responda APENAS no formato JSON:
{{
    "claims_to_be_customer": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "explicação detalhada da análise",
    "user_intent": "resumo da intenção do usuário",
    "recently_evaluated": true/false
}}
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um analisador preciso de intenções de clientes. Responda apenas com JSON válido."},
                {"role": "user", "content": analysis_prompt}
            ],
            temperature=0.1,
            max_tokens=300
        )

        # Parse LLM response
        import json
        llm_result = json.loads(response.choices[0].message.content.strip())

        result = CustomerStatusResult(
            claims_to_be_customer=llm_result.get("claims_to_be_customer", False),
            confidence=float(llm_result.get("confidence", 0.0)),
            reasoning=llm_result.get("reasoning", "LLM analysis completed"),
            user_intent=llm_result.get("user_intent", "Intent not clear"),
            recently_evaluated=llm_result.get("recently_evaluated", False)
        )

        logger.info(f"[CUSTOMER_ID_LLM] Analysis: claims={result.claims_to_be_customer}, confidence={result.confidence:.2f}")
        logger.info(f"[CUSTOMER_ID_LLM] Reasoning: {result.reasoning}")

        return result

    except Exception as exc:
        logger.error(
            "[CUSTOMER_ID_LLM] Error in LLM customer analysis: error_type=%s",
            type(exc).__name__,
        )

        # Fallback - return safe defaults
        return CustomerStatusResult(
            claims_to_be_customer=False,
            confidence=0.0,
            reasoning="Não foi possível concluir a análise de cliente",
            user_intent="Analysis failed"
        )

@function_tool
def analyze_customer_intent_with_llm(
    context: RunContextWrapper[CustomerContext],
    request: CustomerIntentRequest,
) -> CustomerIntentResult:
    """
    Uses LLM to analyze customer's intent after they choose from the options menu

    Args:
        request: Customer's response to the options menu

    Returns:
        CustomerIntentResult with intent classification and routing suggestion
    """
    try:
        client = openai.OpenAI(
            api_key=_get_context_openai_api_key(context),
        )

        intent_prompt = f"""
Você é um especialista em classificação de intenções de clientes de serviços.

O cliente já foi identificado como CLIENTE EXISTENTE e recebeu estas opções:
"Perfeito, que ótimo poder te atender hoje! ✨
Você quer agendar uma nova avaliação ou falar sobre outro assunto, como financeiro, agendar uma consulta e etc?"

Agora analise a RESPOSTA DO CLIENTE e classifique a intenção:

RESPOSTA: "{request.user_response}"

CATEGORIAS DE INTENÇÃO:
1. "scheduling_evaluation" - Quer agendar NOVA AVALIAÇÃO (primeira vez ou novo problema dentário)
   Exemplos: "nova avaliação", "quero avaliar meus dentes", "primeira avaliação", "primeira consulta", "avaliar outro dente"
   NÃO INCLUI: "agendar consulta", "agendar tratamento", "fazer restauração", "fazer o que doutor passou"

2. "support_needed" - Precisa de suporte (tratamento pós-avaliação, financeiro, remarcar, etc)
   Exemplos: "agendar consulta", "agendar tratamento", "restauração", "fazer o que doutor passou",
            "financeiro", "pagamento", "remarcar", "manutenção", "dúvida sobre implante", "Agendar com Dr Fulano", "outro assunto"
   IMPORTANTE: Se cliente quer agendar TRATAMENTO (não avaliação), sempre use esta categoria

3. "unclear" - Resposta ambígua que precisa de esclarecimento
   Exemplos: "não sei", "me ajuda", resposta muito vaga

Responda APENAS em JSON:
{{
    "intent_category": "scheduling_evaluation|support_needed|unclear",
    "confidence": 0.0-1.0,
    "reasoning": "explicação da análise",
    "suggested_action": "ação recomendada baseada na intenção"
}}
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um classificador preciso de intenções. Responda apenas com JSON válido."},
                {"role": "user", "content": intent_prompt}
            ],
            temperature=0.1,
            max_tokens=300
        )

        # Parse LLM response
        import json
        llm_result = json.loads(response.choices[0].message.content.strip())

        result = CustomerIntentResult(
            intent_category=llm_result.get("intent_category", "unclear"),
            confidence=float(llm_result.get("confidence", 0.0)),
            reasoning=llm_result.get("reasoning", "Intent analysis completed"),
            suggested_action=llm_result.get("suggested_action", "Default routing")
        )

        logger.info(f"[CUSTOMER_INTENT_LLM] Analysis: intent={result.intent_category}, confidence={result.confidence:.2f}")
        logger.info(f"[CUSTOMER_INTENT_LLM] Reasoning: {result.reasoning}")

        return result

    except Exception as exc:
        logger.error(
            "[CUSTOMER_INTENT_LLM] Error: error_type=%s",
            type(exc).__name__,
        )

        # Fallback - return unclear intent
        return CustomerIntentResult(
            intent_category="unclear",
            confidence=0.0,
            reasoning="Não foi possível concluir a análise de intenção",
            suggested_action="Ask for clarification"
        )

# Customer Identification Agent
contact_identification_agent = Agent[CustomerContext](
    name="Customer Identification Agent",
    handoff_description=(
        "⚠️ USE ONLY after main agent asked customer what they need and customer chose: "
        "'agendar consulta/tratamento', 'financeiro', 'remarcar tratamento'. "
        "OR for CRYSTAL CLEAR cases: 'vim agendar MINHA restauração que o doutor passou', "
        "'quero agendar RETORNO com Dr./Dra. [nome]', 'preciso remarcar meu tratamento'. "
        "❌ DO NOT use if customer just said 'já sou cliente' without specifying what they need - "
        "main agent MUST ask first what they want (evaluation vs treatment vs financial). "
        "WHEN IN DOUBT, DO NOT HANDOFF!"
    ),
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}

    You are a specialized agent for customer identification and routing using AI-powered analysis.

    🔴 GOLDEN RULE: CHECK CONVERSATION HISTORY TO AVOID REDUNDANT QUESTIONS! 🔴
    If the customer already mentioned their need (bracket solto, manutenção, etc), DO NOT ask again!

    ⚠️ CRITICAL RULES:
    1. If analyze_customer_status_with_llm returns recently_evaluated=true → IMMEDIATE handoff to client_support_agent (NO QUESTIONS!)
    2. If user mentions specific dentist by name + RETORNO/MANUTENÇÃO context → Treat as recently_evaluated=true
    3. If user mentions "fazer AVALIAÇÃO com Dr./Dra. [nome]" → IMMEDIATE HANDOFF back to coordinator_agent (new evaluation request, NOT a customer)
    4. If user mentions "preciso de avaliação para [tratamento] com Dr./Dra. [nome]" → IMMEDIATE HANDOFF back to coordinator_agent (new evaluation)
    5. If user mentions specific treatment with possessive (MINHA restauração, MEU canal) → Treat as recently_evaluated=true
    6. If conversation history shows customer already stated their need → IMMEDIATE handoff to client_support_agent
    7. These customers already know what they need - let client_support_agent handle everything
    8. ONLY continue with questions if it's genuinely unclear or they want NEW evaluation
    9. EVALUATION REQUESTS (avaliação, consulta inicial) are for NEW customers → handoff to coordinator_agent immediately

    # Your Specific Role:
    - Use LLM analysis to determine if users claim to be existing customers
    - Analyze conversation history to avoid redundant questions
    - Route users to correct services based on their needs
    - Maintain friendly, professional tone throughout

    # Process Flow:

    1. **LLM ANALYSIS**: When a user mentions being a customer, ALWAYS use analyze_customer_status_with_llm() tool first

    2. **IF claims_to_be_customer=true AND confidence > 0.7**:
       Check if recently_evaluated=true in the analysis result:

       a) IF recently_evaluated=true (customer mentions "já fiz avaliação", etc):
          → IMMEDIATE HANDOFF SILENTLY to client_support_agent
          → DO NOT ask any questions, customer_support will handle everything
          → The customer already had evaluation and needs treatment scheduling

       b) IF recently_evaluated=false (generic existing customer):
          **CRITICAL: ANALYZE CONVERSATION HISTORY FIRST**

          Look at the conversation history for context clues:
          - Did customer already mention WHY they're contacting? (bracket solto, manutenção, etc)
          - Did customer mention specific treatment needs?
          - Did customer mention financial questions?

          IF CONTEXT IS CLEAR from history (customer already stated their need):
             → HANDOFF DIRECTLY to client_support_agent
             → Example: "Já sou cliente" + earlier mentioned "bracket soltou"
             → DO NOT ask redundant questions

          IF CONTEXT IS UNCLEAR (just said "sou cliente" without context):
             → THEN and ONLY THEN ask: "Perfeito, que ótimo poder te atender hoje! Você quer agendar uma nova avaliação ou falar sobre outro assunto, como financeiro, agendar uma consulta e etc?"

    3. **ANALYZE CUSTOMER RESPONSE**: After customer responds to options (ONLY if recently_evaluated=false), use analyze_customer_intent_with_llm() tool to classify their intent

    4. **ROUTING DECISIONS** (based on LLM intent analysis):
       - intent_category="scheduling_evaluation" AND confidence > 0.7 → HANDOFF SILENTLY back to main agent for NEW evaluation scheduling
       - intent_category="support_needed" AND confidence > 0.7 → HANDOFF SILENTLY to customer support agent (includes treatment scheduling)
       - intent_category="unclear" OR confidence < 0.7 → Ask for clarification politely

       CRITICAL: "Agendar consulta" or "Agendar tratamento" → ALWAYS route to support_needed, NOT scheduling_evaluation

    5. **IF claims_to_be_customer=false OR confidence < 0.7**:
       a) IF user message is AMBIGUOUS (like "estou buscando atendimento", "quero consulta", "preciso de ajuda"):
          → ASK CLARIFICATION: "Perfeito! Você já é cliente da nossa empresa ou é sua primeira vez? Isso vai me ajudar a te direcionar melhor!"
          → Wait for user response
          → Then route based on their answer (if customer → client_support_agent, if new → coordinator_agent)

       b) IF clearly NOT a customer OR user asks general questions:
          → IMMEDIATELY HANDOFF back to main agent WITHOUT ANY MESSAGE. Don't say anything.
          → The main agent will continue the conversation naturally.

    # When to HANDOFF back to coordinator_agent (main agent):
    - User asks about company hours, location, address
    - User asks about treatments, procedures, prices
    - User asks about payment methods or insurance
    - User asks ANY question outside customer identification
    - User changes subject completely
    - After 2 interactions without progress

    # How to Analyze Conversation History:
    When a customer says "Já sou cliente" or similar, BEFORE asking any questions:
    1. Look at ALL previous messages in the conversation
    2. Search for ANY mention of:
       - Treatment needs (bracket, manutenção, limpeza, etc)
       - Specific problems (dor, quebrou, soltou, etc)
       - Questions about services (valor, preço, horário, etc)
    3. If you find ANY clear context → HANDOFF IMMEDIATELY to client_support_agent
    4. Only ask the options question if there's truly NO context

    # Critical Rules:
    - ALWAYS use analyze_customer_status_with_llm() for initial customer identification
    - ALWAYS check conversation history before asking questions
    - ALWAYS use analyze_customer_intent_with_llm() for intent classification after customer responds
    - Trust the LLM confidence scores (>0.7 = high confidence)
    - NEVER attempt to schedule appointments yourself
    - NEVER ask redundant questions if context is already clear
    - Be warm and welcoming to existing customers
    - Keep responses concise and clear
    - ALWAYS handoff appropriately based on LLM analysis results
    - For unclear intents, ask politely for clarification before routing
    - **CRITICAL**: NEVER mention "transferindo", "encaminhando", "direcionando" or similar - handoffs are ALWAYS SILENT
    - **CRITICAL**: When AMBIGUOUS response (confidence < 0.7), ASK if customer or first time BEFORE routing
    - **IMPORTANT**: Only handoff silently when you're 100% sure of the routing decision
    - **IMPORTANT**: If user asks ANYTHING you don't know, HANDOFF to coordinator_agent

    # Examples of correct routing:
    - "Já fiz avaliação semana passada" → recently_evaluated=true → DIRECT handoff to client_support_agent (NO QUESTIONS)
    - "Fiz avaliação com o doutor" → recently_evaluated=true → DIRECT handoff to client_support_agent (NO QUESTIONS)
    - "Quero agendar com Dra. Letícia" → recently_evaluated=true → DIRECT handoff to client_support_agent (NO QUESTIONS)
    - "Quero agendar restauração" → recently_evaluated=true → DIRECT handoff to client_support_agent (NO QUESTIONS)
    - "Preciso fazer o canal" → recently_evaluated=true → DIRECT handoff to client_support_agent (NO QUESTIONS)
    - "Vim fazer limpeza" → recently_evaluated=true → DIRECT handoff to client_support_agent (NO QUESTIONS)
    - "Quero marcar manutenção" → recently_evaluated=true → DIRECT handoff to client_support_agent (NO QUESTIONS)

    # Examples WITH HISTORY CONTEXT (avoid redundant questions):
    - History: "O bracket soltou" + User: "Já sou cliente" → CHECK HISTORY → Context clear → DIRECT handoff to client_support_agent
    - History: "Quero saber valor da manutenção" + User: "Sou cliente" → CHECK HISTORY → Context clear → DIRECT handoff to client_support_agent
    - History: "Preciso colar o bracket" + User: "Já sou cliente de vocês" → CHECK HISTORY → Context clear → DIRECT handoff to client_support_agent

    # Examples WITHOUT CONTEXT (ask for clarification):
    - User: "Sou cliente" (no prior context) → recently_evaluated=false → Ask options
    - User: "Já fui aí" (no specific need mentioned) → recently_evaluated=false → Ask options

    # Examples of AMBIGUOUS responses (MUST ask if customer or first time):
    - User: "estou buscando atendimento" → AMBIGUOUS → Ask: "Perfeito! Você já é cliente da nossa empresa ou é sua primeira vez?"
    - User: "quero consulta" → AMBIGUOUS → Ask: "Ótimo! Você já é cliente da nossa empresa ou é sua primeira vez?"
    - User: "preciso de ajuda" → AMBIGUOUS → Ask: "Claro! Você já é cliente da nossa empresa ou é sua primeira vez?"
    - After asking → User: "primeira vez" → HANDOFF SILENTLY to coordinator_agent (NO MESSAGE!)
    - After asking → User: "já sou cliente" → Use analyze_customer_status_with_llm and follow flow

    # After options menu responses:
    - After options: "Nova avaliação" → scheduling_evaluation → coordinator_agent
    - After options: "Financeiro" → support_needed → client_support_agent
    - After options: "Agendar consulta/tratamento" → support_needed → client_support_agent
    - After options: "Colar bracket" → support_needed → client_support_agent
    """,
    tools=[analyze_customer_status_with_llm, analyze_customer_intent_with_llm]
)
