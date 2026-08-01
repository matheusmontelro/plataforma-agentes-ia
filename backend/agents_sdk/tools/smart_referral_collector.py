"""
Smart Referral Collector Tool - Tool inteligente para coletar indicações
Usa a API interna de leads para criar leads em tempo real
"""

import json
import logging
import re
from typing import Annotated, List, Dict, Any
from datetime import datetime
from pydantic import Field
from sqlalchemy.orm import Session

# Import OpenAI Agents SDK
from agents import RunContextWrapper, function_tool, trace

# Import rota interna para criar leads
from backend.models import Lead, Contact, Client
from backend.services.ai_provider_service import get_company_openai_api_key

logger = logging.getLogger(__name__)


@function_tool
def collect_referral_data_incrementally(
    context: RunContextWrapper,
    user_input: Annotated[str, Field(description="Entrada atual do usuário (nome, telefone ou combinação)")]
) -> str:
    """
    Coleta dados de indicação de forma incremental e inteligente.

    Esta tool analisa o histórico da conversa e combina informações
    para criar leads automaticamente conforme os dados ficam completos.

    Funcionalidades:
    - Detecta telefones, nomes ou combinações
    - Combina dados do histórico da conversa
    - Cria leads via API interna em tempo real
    - Valida formato e previne duplicação
    - Feedback imediato para o usuário

    Args:
        context: Contexto de execução com empresa, telefone e sessão do banco
        user_input: Dados fornecidos pelo usuário

    Returns:
        Feedback sobre o processamento ou solicitação de dados faltantes
    """

    with trace("collect_referral_data_incrementally", disabled=True):
        db = None
        company_id = 0
        phone = ""
        try:
            runtime_context = context.context
            company_id = int(runtime_context.company_id)
            phone = str(runtime_context.phone)
            db = runtime_context.db
            if db is None:
                raise RuntimeError("Contexto de banco indisponível")

            logger.info(
                "[SmartReferralCollector] Processando indicação para company_id=%s",
                company_id,
            )

            if not _check_referral_eligibility(db, company_id, phone):
                logger.info("[SmartReferralCollector] User not eligible for referral request")
                return "Obrigado por seu interesse! No momento não estamos coletando indicações."

            api_key = get_company_openai_api_key(db, company_id)

            # Marcar contexto como coleta ativa de indicações
            # Isso será usado pelo manager.py para ajustar o prompt
            _set_referral_collection_mode(db, company_id, phone, active=True)

            # Analisar entrada atual
            analysis = _analyze_user_input(user_input, api_key=api_key)

            # Buscar dados pendentes no histórico (via session ou contexto)
            pending_data = _get_pending_referral_data(
                db,
                company_id,
                phone,
                api_key=api_key,
            )

            # Combinar dados e processar
            result = _process_combined_data(
                db=db,
                company_id=company_id,
                referrer_phone=phone,
                current_input=analysis,
                pending_data=pending_data,
                api_key=api_key,
            )

            # Se todas as indicações foram coletadas, limpar modo de coleta
            if result.get('status') == 'complete':
                _set_referral_collection_mode(db, company_id, phone, active=False)

            logger.info(f"[SmartReferralCollector] Resultado: {result['status']}")
            return result['message']

        except Exception as exc:
            logger.error(
                "[SmartReferralCollector] Falha: error_type=%s",
                type(exc).__name__,
            )
            # Em caso de erro, limpar modo de coleta
            try:
                if db is not None:
                    _set_referral_collection_mode(
                        db,
                        company_id,
                        phone,
                        active=False,
                    )
            except Exception:
                pass
            return (
                "Houve um problema ao processar sua indicação. "
                "Pode tentar enviar no formato: Nome - Telefone?"
            )


def _analyze_user_input(
    user_input: str,
    *,
    api_key: str,
) -> Dict[str, Any]:
    """
    Analisa entrada do usuário usando LLM para detectar nomes e telefones
    """
    try:
        import openai

        prompt = f"""Analise este texto e extraia informações de indicação:

TEXTO: "{user_input}"

Identifique:
1. NOMES de pessoas (pelo menos primeiro e último nome)
2. TELEFONES em qualquer formato (números com 8-15 dígitos)
3. PARES completos (nome + telefone da mesma pessoa)

Responda APENAS o JSON, sem explicações, sem markdown, sem ```json:
{{
  "type": "complete|phones_only|names_only|single_name|unknown",
  "complete_pairs": [{{"name": "Nome Completo", "phone": "telefone"}}],
  "phones": ["telefone1"],
  "names": ["Nome1"]
}}

Regras:
- type="complete" se tem pelo menos 1 par nome+telefone
- type="phones_only" se só tem telefones
- type="names_only" se só tem nomes completos (2+ palavras)
- type="single_name" se só tem 1 nome único (ex: "Carlos", "Maria")
- type="unknown" se não identificar nada
- Telefone: aceitar qualquer sequência de 8-15 dígitos
- IMPORTANTE: Retorne APENAS o JSON, sem nenhum texto adicional"""

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300
        )

        # Extrair conteúdo da resposta de forma mais segura
        response_content = response.choices[0].message.content

        # Limpar resposta - remover caracteres extras que podem vir antes/depois do JSON
        response_content = response_content.strip()

        # Se a resposta começar com ```json ou ``` remover
        if response_content.startswith('```json'):
            response_content = response_content[7:]
        elif response_content.startswith('```'):
            response_content = response_content[3:]

        # Remover ``` no final se houver
        if response_content.endswith('```'):
            response_content = response_content[:-3]

        # Fazer trim novamente após remoção
        response_content = response_content.strip()

        # Se houver texto antes do JSON, pegar apenas o JSON
        if '{' in response_content and not response_content.startswith('{'):
            json_start = response_content.index('{')
            response_content = response_content[json_start:]
            logger.debug(f"[SmartReferralCollector] Removido texto antes do JSON")

        # Tentar parsear o JSON
        try:
            result = json.loads(response_content)
        except json.JSONDecodeError as json_err:
            logger.error("[SmartReferralCollector] Resposta LLM não é JSON válido")
            raise json_err

        result['raw_input'] = user_input

        logger.info(f"[SmartReferralCollector] LLM analysis: type={result['type']}, pairs={len(result.get('complete_pairs', []))}")
        return result

    except json.JSONDecodeError:
        logger.error("[SmartReferralCollector] Resposta LLM não é JSON válido")
    except Exception as exc:
        logger.error(
            "[SmartReferralCollector] Erro na análise LLM: error_type=%s",
            type(exc).__name__,
        )

    # Fallback robusto - análise simples baseada em regex
    import re

    result = {
        'type': 'unknown',
        'phones': [],
        'names': [],
        'complete_pairs': [],
        'raw_input': user_input
    }

    # Detectar telefones com regex
    phone_pattern = r'\b\d{8,15}\b|\(\d{2}\)\s*\d{4,5}-?\d{4}|\d{2}\s*\d{4,5}-?\d{4}'
    phones_found = re.findall(phone_pattern, user_input)
    if phones_found:
        result['phones'] = phones_found
        result['type'] = 'phones_only'

    # Detectar se é só um nome simples
    cleaned_input = user_input.strip()
    words = cleaned_input.split()

    # Se tem apenas 1-2 palavras e não tem números, provavelmente é um nome
    if len(words) <= 2 and not any(char.isdigit() for char in cleaned_input):
        result['names'] = [cleaned_input]
        result['type'] = 'single_name' if len(words) == 1 else 'names_only'

    # Se tem múltiplas palavras sem números
    elif len(words) > 2 and not any(char.isdigit() for char in cleaned_input):
        result['names'] = [cleaned_input]
        result['type'] = 'names_only'

    logger.info(f"[SmartReferralCollector] Usando fallback regex: type={result['type']}")
    return result


def _get_pending_referral_data(
    db: Session,
    company_id: int,
    phone: str,
    *,
    api_key: str,
) -> Dict[str, Any]:
    """
    Busca dados pendentes de indicação no histórico recente usando LLM
    """
    try:
        import openai
        from sqlalchemy import text

        # Buscar últimas mensagens da conversa
        recent_messages = db.execute(text("""
            SELECT content, from_me, timestamp
            FROM messages
            WHERE contact_phone = :phone AND company_id = :company_id
            ORDER BY timestamp DESC
            LIMIT 6
        """), {"phone": phone, "company_id": company_id}).fetchall()

        if not recent_messages:
            return {'pending_phones': [], 'pending_names': [], 'last_request_type': None}

        # Formar histórico para análise
        conversation = ""
        for msg in reversed(recent_messages):  # Ordem cronológica
            role = "Assistente" if msg.from_me else "Usuario"
            conversation += f"{role}: {msg.content}\n"

        # Usar LLM para detectar dados pendentes
        prompt = f"""Analise esta conversa e identifique dados PENDENTES de indicação:

CONVERSA:
{conversation}

Busque:
1. TELEFONES mencionados sem nome correspondente
2. NOMES mencionados sem telefone correspondente
3. Qual foi o último tipo de solicitação (nome ou telefone)

Responda APENAS em JSON:
{{
  "pending_phones": ["telefone1", "telefone2"],
  "pending_names": ["Nome1", "Nome2"],
  "last_request_type": "phone|name|null"
}}

Regras:
- Só incluir dados que ainda não foram COMBINADOS
- Se assistente pediu telefone, last_request_type="phone"
- Se assistente pediu nome, last_request_type="name"""

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200
        )

        result = json.loads(response.choices[0].message.content)
        logger.info(f"[PendingData] LLM detectou: {result}")
        return result

    except Exception as exc:
        logger.warning(
            "[PendingData] LLM falhou: error_type=%s",
            type(exc).__name__,
        )
        return {'pending_phones': [], 'pending_names': [], 'last_request_type': None}


def _process_combined_data(
    db: Session,
    company_id: int,
    referrer_phone: str,
    current_input: Dict[str, Any],
    pending_data: Dict[str, Any],
    *,
    api_key: str,
) -> Dict[str, str]:
    """
    Processa dados combinados e cria leads quando possível
    """

    try:
        if current_input['type'] == 'complete':
            # Dados completos - criar leads imediatamente
            created_count = 0
            created_names = []

            for pair in current_input['complete_pairs']:
                name = pair['name']
                ref_phone = _format_phone(pair['phone'], api_key=api_key)

                if ref_phone and _create_referral_lead(db, company_id, name, ref_phone, referrer_phone):
                    created_count += 1
                    created_names.append(name)

            if created_count > 0:
                names_text = ', '.join(created_names)

                # Mensagem base de sucesso
                base_message = f"🎉 Perfeito! {created_count} indicação(ões) processada(s): {names_text}. Eles receberão nossa mensagem especial em breve!"

                # Adicionar CTA se foram menos de 3 indicações
                if created_count < 3:
                    cta_message = f"\n\nVocê ainda pode indicar mais {3 - created_count} pessoa(s)! Tem mais alguém que precisa de tratamento de serviços?"
                else:
                    cta_message = "\n\nObrigado por suas indicações! Se lembrar de mais alguém, é só me enviar!"

                return {
                    'status': 'success',
                    'message': base_message + cta_message
                }
            else:
                return {
                    'status': 'error',
                    'message': "Não consegui processar as indicações. Pode verificar se os telefones estão corretos?"
                }

        elif current_input['type'] == 'phones_only':
            # Só telefones - verificar se há nomes pendentes para combinar
            if pending_data.get('pending_names'):
                # Combinar telefone atual com nome pendente
                for i, name in enumerate(pending_data['pending_names']):
                    if i < len(current_input['phones']):
                        phone = current_input['phones'][i]
                        ref_phone = _format_phone(phone, api_key=api_key)

                        if ref_phone and _create_referral_lead(db, company_id, name, ref_phone, referrer_phone):
                            # Contar quantas indicações já foram feitas (estimativa baseada em contexto)
                            # Como processamos 1 por vez quando combina com pendente, adicionar CTA
                            return {
                                'status': 'success',
                                'message': f"🎉 Perfeito! Indicação do {name} processada com sucesso! Ele receberá nossa mensagem especial em breve.\n\nVocê ainda pode indicar mais 2 pessoas! Tem mais alguém que precisa de tratamento de serviços?"
                            }

            # Sem nomes pendentes - pedir nomes
            phone_count = len(current_input['phones'])
            return {
                'status': 'need_names',
                'message': f"Ótimo! Vi {phone_count} telefone(s). Agora preciso dos nomes das pessoas para completar as indicações."
            }

        elif current_input['type'] in ['names_only', 'single_name']:
            # Só nomes - verificar se há telefones pendentes para combinar
            if pending_data.get('pending_phones'):
                # Combinar nome atual com telefone pendente
                for i, name in enumerate(current_input['names']):
                    if i < len(pending_data['pending_phones']):
                        phone = pending_data['pending_phones'][i]
                        ref_phone = _format_phone(phone, api_key=api_key)

                        if ref_phone and _create_referral_lead(db, company_id, name, ref_phone, referrer_phone):
                            # Contar quantas indicações já foram feitas (estimativa baseada em contexto)
                            # Como processamos 1 por vez quando combina com pendente, adicionar CTA
                            return {
                                'status': 'success',
                                'message': f"🎉 Perfeito! Indicação do {name} processada com sucesso! Ele receberá nossa mensagem especial em breve.\n\nVocê ainda pode indicar mais 2 pessoas! Tem mais alguém que precisa de tratamento de serviços?"
                            }

            # Sem telefones pendentes - pedir telefones
            name_count = len(current_input['names'])
            names_text = ', '.join(current_input['names'])
            return {
                'status': 'need_phones',
                'message': f"Perfeito! Agora preciso do(s) telefone(s) do(a) {names_text}."
            }

        else:
            # Formato não reconhecido
            return {
                'status': 'format_help',
                'message': (
                    "Para processar suas indicações, pode enviar:\n"
                    "• Nome completo e telefone: João Silva - (11) 99999-8888\n"
                    "• Ou apenas os dados que tem, que eu vou ajudando a completar!"
                )
            }

    except Exception as exc:
        logger.error(
            "[SmartReferralCollector] Erro ao processar dados: error_type=%s",
            type(exc).__name__,
        )
        return {
            'status': 'error',
            'message': "Houve um problema. Pode tentar novamente?"
        }


def _format_phone(phone: str, *, api_key: str) -> str:
    """Formata telefone para padrão 55ddd912345678 usando LLM"""
    try:
        import openai

        prompt = f"""Formate este telefone brasileiro para o padrão 55ddd912345678:

TELEFONE: "{phone}"

REGRAS:
- Sempre começar com 55 (código do Brasil)
- DDD com 2 dígitos (11, 21, 31, etc)
- NUNCA MUDAR O DDD - se já tem DDD válido, MANTER O MESMO DDD
- Se telefone já tem 13 dígitos começando com 55, retornar EXATAMENTE como está
- Para celular: adicionar 9 após DDD se não tiver
- Para fixo: NÃO adicionar 9 (fixos começam com 2,3,4,5)
- Resultado final: sempre 13 dígitos

EXEMPLOS SINTÉTICOS:
- "00000000001" → "5500000000001" (celular com 9)
- "00000000002" → "5500000000002" (segundo DDD sintético)
- "5500000000003" → "5500000000003" (já formatado, retornar igual)
- "0000000004" → "5500000000004" (celular sem 9, adicionar)
- "0000000005" → "550000000005" (fixo, não adicionar 9)
- "0000000006" → "550000000006" (segundo fixo sintético)

Responda APENAS o telefone formatado, sem explicações."""

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=50
        )

        formatted = response.choices[0].message.content.strip()

        # Validar resultado (deve ter 13 dígitos e começar com 55)
        if len(formatted) == 13 and formatted.startswith('55') and formatted.isdigit():
            logger.info(f"[PhoneFormatter] LLM: {phone} → {formatted}")
            return formatted
        else:
            raise Exception(f"LLM retornou formato inválido: {formatted}")

    except Exception as exc:
        logger.warning(
            "[PhoneFormatter] LLM falhou; usando fallback: error_type=%s",
            type(exc).__name__,
        )

        # Fallback regex
        digits = re.sub(r'\D', '', phone)

        if len(digits) == 11:
            return f"55{digits}"
        elif len(digits) == 10:
            if digits[2] in ['2', '3', '4', '5']:
                return f"55{digits}"  # Fixo
            else:
                return f"55{digits[:2]}9{digits[2:]}"  # Celular
        elif len(digits) == 12 and digits.startswith('55'):
            return digits
        elif len(digits) == 13 and digits.startswith('55'):
            return digits
        else:
            return None


def _set_referral_collection_mode(db: Session, company_id: int, phone: str, active: bool) -> None:
    """
    Define o estado de coleta de indicações no contexto do cliente.
    Isso previne que o agente interprete nomes como novas conversas.
    """
    try:
        # Armazenar estado em cache/session temporariamente
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

        key = f"referral_collection:{company_id}:{phone}"
        if active:
            # Marcar como ativo por 10 minutos
            r.setex(key, 600, "active")
            logger.info(f"[REFERRAL_MODE] Ativado modo coleta para {phone}")
        else:
            # Limpar estado
            r.delete(key)
            logger.info(f"[REFERRAL_MODE] Desativado modo coleta para {phone}")

    except Exception as e:
        logger.warning(f"[REFERRAL_MODE] Erro ao definir modo de coleta: {e}")
        # Não falhar se Redis não estiver disponível


def _create_referral_lead(db: Session, company_id: int, name: str, phone: str, referrer_phone: str = None) -> bool:
    """
    Cria lead usando lógica da API interna
    """
    try:
        # Verificar se já existe
        existing = db.query(Lead).filter(
            Lead.phone == phone,
            Lead.company_id == company_id
        ).first()

        if existing:
            logger.info(f"[SmartReferralCollector] Lead já existe (provavelmente via vCard): {name} ({phone})")

            # Atualizar informações do lead existente se necessário
            updated = False
            if not existing.name or existing.name == "Sem nome":
                existing.name = name
                updated = True

            # Garantir que source_id seja Indicação
            if existing.source_id != "Indicação":
                existing.source_id = "Indicação"
                updated = True

            if updated:
                db.commit()
                logger.info(f"[SmartReferralCollector] Lead existente atualizado com informações da indicação")

            # Continuar o fluxo para agendar boas-vindas se necessário
            # Não retornamos False aqui - continuamos o processo

        # Buscar client_id via relacionamento
        from sqlalchemy import text
        client_result = db.execute(text("""
            SELECT c.id FROM clients c
            JOIN client_companies cc ON cc.client_id = c.id
            WHERE cc.company_id = :company_id LIMIT 1
        """), {"company_id": company_id}).fetchone()

        if not client_result:
            logger.error(f"[SmartReferralCollector] Client não encontrado para empresa {company_id}")
            return False

        # Criar lead apenas se não existir
        if not existing:
            new_lead = Lead(
                client_id=str(client_result.id),
                company_id=company_id,
                name=name,
                phone=phone,
                source_id="Indicação",
                created_at=datetime.utcnow(),
                data_entrada=datetime.utcnow()
            )
            db.add(new_lead)
            logger.info(f"[SmartReferralCollector] Novo lead criado: {name} ({phone})")

        # Criar/atualizar contato
        contact = db.query(Contact).filter(
            Contact.phone == phone,
            Contact.company_id == company_id
        ).first()

        if not contact:
            contact = Contact(
                client_id=client_result.id,
                company_id=company_id,
                phone=phone,
                name=name
            )
            db.add(contact)

        db.commit()

        # Agendar mensagem de boas-vindas para indicado
        if referrer_phone:
            try:
                from ..services.referral_service import ReferralService

                referral_service = ReferralService(db)
                campaign = referral_service.get_active_campaign(company_id)

                if campaign and campaign.contact_referees_immediately:
                    # Buscar nome do indicador
                    referrer_contact = db.query(Contact).filter(
                        Contact.phone == referrer_phone,
                        Contact.company_id == company_id
                    ).first()
                    referrer_name = referrer_contact.name if referrer_contact else "Um cliente"

                    success = referral_service._schedule_referee_welcome(
                        company_id=company_id,
                        referee_phone=phone,
                        referee_name=name,
                        referrer_name=referrer_name,
                        campaign=campaign
                    )
                    if success:
                        logger.info(f"[SmartReferralCollector] ✅ Mensagem de boas-vindas agendada para {name}")
                    else:
                        logger.warning(f"[SmartReferralCollector] ❌ Falha ao agendar boas-vindas para {name}")
                else:
                    logger.info(f"[SmartReferralCollector] Campanha não configurada para contato imediato")

            except Exception as e:
                logger.error(f"[SmartReferralCollector] Erro ao agendar boas-vindas: {e}")

        logger.info(f"[SmartReferralCollector] ✅ Lead processado com sucesso: {name} ({phone})")

        # Update referral history
        _update_referral_history(db, company_id, referrer_phone, name, phone)

        return True

    except Exception as e:
        logger.error(f"[SmartReferralCollector] Erro ao criar lead {name}: {e}")
        db.rollback()
        return False


def _check_referral_eligibility(db: Session, company_id: int, phone: str) -> bool:
    """
    Check if user is eligible for referral request using smart rules
    """
    try:
        from backend.models import Lead, ReferralCampaign
        from backend.agents_sdk.models.referral_history import ReferralHistory
        import datetime

        # Get lead info
        lead = db.query(Lead).filter(
            Lead.phone == phone,
            Lead.company_id == company_id
        ).first()

        if not lead:
            return False

        # Check if there's an active campaign
        campaign = db.query(ReferralCampaign).filter(
            ReferralCampaign.company_id == company_id,
            ReferralCampaign.active == True
        ).first()

        if not campaign:
            logger.info(f"[ReferralCheck] No active campaign for company {company_id}")
            return False

        # Check referral history
        history = db.query(ReferralHistory).filter(
            ReferralHistory.lead_phone == phone,
            ReferralHistory.company_id == company_id,
            ReferralHistory.campaign_id == campaign.id
        ).first()

        # Rule 1: Never asked before for this campaign
        if not history:
            logger.info(f"[ReferralCheck] First time asking for lead {phone}")
            return True

        # Rule 2: Check time since last referral
        if history.last_referral_date:
            days_since_last = (datetime.datetime.now() - history.last_referral_date).days

            # Don't ask if less than 30 days
            if days_since_last < 30:
                logger.info(f"[ReferralCheck] Too soon since last referral ({days_since_last} days)")
                return False

        # Rule 3: Check referral count limits
        max_referrals_per_lead = getattr(campaign, 'max_referrals_per_lead', 5)
        if history.referrals_count >= max_referrals_per_lead:
            logger.info(f"[ReferralCheck] Lead reached max referrals ({history.referrals_count}/{max_referrals_per_lead})")
            return False

        logger.info(f"[ReferralCheck] All checks passed, can ask for referrals")
        return True

    except Exception as e:
        logger.error(f"[ReferralCheck] Error checking referral eligibility: {e}")
        return True  # Default to True if error to avoid blocking


def _update_referral_history(
    db: Session,
    company_id: int,
    referrer_phone: str,
    referred_name: str,
    referred_phone: str
):
    """
    Update referral history when a lead provides referrals
    """
    try:
        from backend.models import ReferralCampaign
        from backend.agents_sdk.models.referral_history import ReferralHistory
        import json
        from datetime import datetime

        # Get active campaign
        campaign = db.query(ReferralCampaign).filter(
            ReferralCampaign.company_id == company_id,
            ReferralCampaign.active == True
        ).first()

        if not campaign:
            return

        # Find or create history record
        history = db.query(ReferralHistory).filter(
            ReferralHistory.lead_phone == referrer_phone,
            ReferralHistory.company_id == company_id,
            ReferralHistory.campaign_id == campaign.id
        ).first()

        if not history:
            history = ReferralHistory(
                lead_phone=referrer_phone,
                company_id=company_id,
                campaign_id=campaign.id,
                referrals_count=0,
                referral_names="[]"
            )
            db.add(history)

        # Update referral data
        history.referrals_count += 1
        history.last_referral_date = datetime.now()

        # Add name to referral list
        existing_names = json.loads(history.referral_names or "[]")
        existing_names.append({
            "name": referred_name,
            "phone": referred_phone,
            "date": datetime.now().isoformat()
        })
        history.referral_names = json.dumps(existing_names)

        db.commit()
        logger.info(f"[ReferralHistory] Updated history for {referrer_phone}: {history.referrals_count} referrals")

    except Exception as e:
        logger.error(f"[ReferralHistory] Error updating history: {e}")
        db.rollback()


# Tool registration
SMART_REFERRAL_TOOLS = [collect_referral_data_incrementally]
