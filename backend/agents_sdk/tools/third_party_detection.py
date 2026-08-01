"""
Third Party Detection - LLM-based detection for third-party appointment intent
Differentiates between appointments for family members vs referrals
"""

import logging
from typing import Dict, Any, Optional, List
from openai import OpenAI
import json
from sqlalchemy.orm import Session

from backend.services.ai_provider_service import get_company_openai_api_key

logger = logging.getLogger(__name__)

def detect_third_party_booking_intent(
    message: str,
    context: Dict[str, Any],
    conversation_history: Optional[List[Dict]] = None,
    *,
    db: Session,
    company_id: int,
) -> Dict[str, Any]:
    """
    Detects if user wants to schedule appointment for a third party (family member).
    Uses LLM for accurate intent detection based on real patterns.

    Args:
        message: Current user message
        context: Current conversation context (stage, selected slot, etc.)
        conversation_history: Recent conversation history

    Returns:
        Dict with detection results including intent, relationship, confidence
    """

    try:
        client = OpenAI(
            api_key=get_company_openai_api_key(db, company_id),
        )

        # Extract context information
        current_stage = context.get('current_stage', '')
        has_selected_slot = bool(context.get('selected_appointment_time'))
        selected_date = context.get('selected_appointment_date', '')
        selected_time = context.get('selected_appointment_time', '')
        in_scheduling = current_stage in ['etapa_4', 'etapa_5']

        # Build conversation context
        recent_context = ""
        if conversation_history and len(conversation_history) > 0:
            last_messages = conversation_history[-4:]
            for msg in last_messages:
                role = "Assistente" if msg.get('role') == 'assistant' else "Usuário"
                content = msg.get('content', '')[:200]  # Limit length
                recent_context += f"{role}: {content}\n"

        prompt = f"""Analise esta mensagem e determine se o usuário quer agendar consulta para um FAMILIAR/TERCEIRO.

MENSAGEM ATUAL: "{message}"

CONTEXTO:
- Em fluxo de agendamento: {in_scheduling}
- Horário selecionado: {selected_date} {selected_time if selected_time else '(não selecionado)'}
- Etapa atual: {current_stage}

HISTÓRICO RECENTE:
{recent_context}

EXEMPLOS DE AUTO-IDENTIFICAÇÃO (NÃO é terceiro, é o próprio usuário):
❌ "meu nome é Dona Vilma"
❌ "me chamo João Silva"
❌ "sou a Maria"
❌ "eu sou o Pedro"
❌ "pode me chamar de Ana"
❌ "aqui é o Carlos"
❌ "falando com Dona Rosa"
❌ "Dona Vilma" (quando está se referindo a si mesma)

EXEMPLOS DE AGENDAMENTO PARA TERCEIRO (ação imediata):
✅ "quero agendar para minha mãe"
✅ "queria agendar uma consulta pra minha irmã"
✅ "gostaria de marcar consulta para meu pai"
✅ "a consulta é para meu filho"
✅ "não é pra mim, é para minha esposa"
✅ "vou levar meu pai"
✅ "é para minha filha de 10 anos"
✅ "meu marido que precisa"
✅ "preciso agendar para meu filho"
✅ "quero marcar pra minha mãe Dona Vilma" (especificando que é para outra pessoa)

EXEMPLOS DE INDICAÇÃO (NÃO é agendamento para terceiro):
❌ "vou indicar minha amiga"
❌ "tenho uma vizinha que precisa"
❌ "conheço alguém interessado"
❌ "posso passar o contato de vocês?"
❌ "vou falar para minha irmã ligar aí"
❌ "meu primo vai entrar em contato"

FALSOS POSITIVOS COMUNS (NÃO é agendamento para terceiro):
❌ "sexta ou sábado que é a folga do meu filho" - Apenas mencionando disponibilidade
❌ "quando meu marido pode me levar" - Logística de transporte
❌ "meu filho não chegou para me levar" - Explicando atraso/problema
❌ "preciso remarcar pois meu filho não chegou" - Contexto de reagendamento
❌ "minha filha vai me acompanhar" - Acompanhante, não cliente
❌ "dependo do meu filho para ir" - Dependência de transporte

ANÁLISE IMPORTANTE:
1. PRIORIDADE: Se usuário está SE IDENTIFICANDO ("meu nome é", "me chamo", "sou") = self_booking
2. Se usuário expressa intenção IMEDIATA de agendar para familiar = third_party_booking
3. Se é apenas menção ou indicação futura = referral
4. Detecte mesmo FORA do fluxo de agendamento (usuário pode mencionar logo no início)
5. Foque em palavras-chave: "agendar para", "marcar para", "consulta para", "é para meu/minha"
6. "Dona" ou "Seu" sozinhos NÃO indicam terceiro - podem ser auto-identificação
7. CONTEXTO DE REAGENDAMENTO: Se já tem agendamento e menciona familiar, provavelmente é contexto/logística, NÃO terceiro
8. REGRA CRÍTICA: Só considere third_party se EXPLICITAMENTE disser "para meu/minha [familiar]"

Responda SOMENTE em JSON:
{{
  "intent": "third_party_booking|referral|self_booking|unclear",
  "is_third_party": true/false,
  "relationship": "mãe|pai|filho|filha|esposa|marido|avó|avô|irmão|irmã|tio|tia|primo|prima|outro|null",
  "confidence": 0.0 a 1.0,
  "reasoning": "explicação breve"
}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200
        )

        # Extract JSON from response (handle markdown code blocks)
        response_text = response.choices[0].message.content

        # Remove markdown code blocks if present
        if '```json' in response_text:
            response_text = response_text.split('```json')[1].split('```')[0]
        elif '```' in response_text:
            response_text = response_text.split('```')[1].split('```')[0]

        result = json.loads(response_text.strip())

        # Add context information
        result['message'] = message
        result['context_stage'] = current_stage
        result['has_slot'] = has_selected_slot

        logger.info(f"[ThirdPartyDetection] Result: intent={result['intent']}, "
                   f"confidence={result['confidence']}, relationship={result.get('relationship')}")

        return result

    except Exception as exc:
        logger.error(
            "[ThirdPartyDetection] LLM fallback: error_type=%s",
            type(exc).__name__,
        )

        # Fallback with pattern matching
        import re

        # Check for self-identification patterns FIRST
        self_identification_patterns = [
            r"meu\s+nome\s+é",
            r"me\s+chamo",
            r"eu\s+sou",
            r"sou\s+(a|o)",
            r"aqui\s+é\s+(a|o)",
            r"falando\s+com",
        ]

        message_lower = message.lower()

        # Check self-identification first
        for pattern in self_identification_patterns:
            if re.search(pattern, message_lower):
                return {
                    "intent": "self_booking",
                    "is_third_party": False,
                    "relationship": None,
                    "confidence": 0.8,
                    "reasoning": "Self-identification detected"
                }

        # Common patterns for third-party booking
        third_party_patterns = [
            (r"(agendar|marcar|consulta)\s+(para|pra)\s+(minha?|meu)\s+(\w+)", True),
            (r"não\s+é\s+(pra|para)\s+mim", True),
            (r"é\s+(pra|para)\s+(minha?|meu)\s+(\w+)", True),
            (r"(minha?|meu)\s+(mãe|pai|filho|filha|esposa|marido)", True),
        ]

        for pattern, is_third_party in third_party_patterns:
            match = re.search(pattern, message_lower)
            if match:
                # Try to extract relationship
                relationship = None
                family_terms = {
                    'mãe': 'mãe', 'mae': 'mãe',
                    'pai': 'pai',
                    'filho': 'filho', 'filha': 'filha',
                    'esposa': 'esposa', 'mulher': 'esposa',
                    'marido': 'marido', 'esposo': 'marido',
                    'avó': 'avó', 'avo': 'avó', 'avô': 'avô',
                    'irmão': 'irmão', 'irmao': 'irmão', 'irmã': 'irmã', 'irma': 'irmã'
                }

                for term, rel in family_terms.items():
                    if term in message_lower:
                        relationship = rel
                        break

                return {
                    "intent": "third_party_booking" if is_third_party else "unclear",
                    "is_third_party": is_third_party,
                    "relationship": relationship,
                    "confidence": 0.7,
                    "reasoning": "Pattern matching fallback"
                }

        # No clear pattern found
        return {
            "intent": "unclear",
            "is_third_party": False,
            "relationship": None,
            "confidence": 0.3,
            "reasoning": "No clear third-party pattern detected"
        }
