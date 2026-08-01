
import logging
from sqlalchemy.orm import Session
from backend.models import AgentConfiguration

logger = logging.getLogger(__name__)

def recursively_escape_braces(value):
    """
    Converte qualquer '{' em '{{' e '}' em '}}' dentro de strings,
    impedindo o LangChain de interpretar como placeholders.
    É aplicado recursivamente a listas e dicionários.
    """
    if isinstance(value, str):
        return value.replace("{", "{{").replace("}", "}}")
    elif isinstance(value, list):
        return [recursively_escape_braces(v) for v in value]
    elif isinstance(value, dict):
        return {k: recursively_escape_braces(v) for k, v in value.items()}
    else:
        return value

def process_treatments(team_and_specialties: dict) -> dict:
    """
    Processa o campo team_and_specialties para garantir formato adequado dos tratamentos.

    Args:
        team_and_specialties (dict): Dicionário contendo treatments e technical_responsible

    Returns:
        dict: Dicionário processado com treatments formatados
    """
    processed = team_and_specialties.copy()

    # Garante que treatments é uma lista
    if not isinstance(processed.get('treatments'), list):
        processed['treatments'] = []

    # Processa cada tratamento
    formatted_treatments = []
    for treatment in processed.get('treatments', []):
        if isinstance(treatment, dict):
            formatted_treatment = {
                'treatmentTitle': treatment.get('treatmentTitle', 'Sem título'),
                'description': treatment.get('description', 'Sem descrição')
            }
            formatted_treatments.append(formatted_treatment)

    processed['treatments'] = formatted_treatments
    return processed

def process_few_shots(conversation_flow: dict) -> dict:
    """
    Processa o campo few_shots dentro do conversation_flow para garantir formato adequado.

    Args:
        conversation_flow (dict): Dicionário contendo few_shots e outras configs

    Returns:
        dict: Dicionário processado com few_shots formatados
    """
    processed = conversation_flow.copy()

    # Garante que few_shots é uma lista
    if not isinstance(processed.get('few_shots'), list):
        processed['few_shots'] = []

    # Processa cada exemplo
    formatted_shots = []
    for shot in processed.get('few_shots', []):
        if isinstance(shot, dict):
            formatted_shot = {
                'userMessage': shot.get('userMessage', ''),
                'botResponse': shot.get('botResponse', ''),
                'objectionType': shot.get('objectionType', '')
            }
            formatted_shots.append(formatted_shot)

    processed['few_shots'] = formatted_shots
    return processed

def process_financial_config(financial_config: dict) -> dict:
    """
    Processa o campo financial_config para garantir formato e campos adequados.

    Args:
        financial_config (dict): Dicionário contendo as configurações financeiras

    Returns:
        dict: Dicionário processado com os campos formatados
    """
    processed = financial_config.copy() if isinstance(financial_config, dict) else {}

    # Garante que payment_methods é uma lista
    if not isinstance(processed.get('payment_methods'), list):
        processed['payment_methods'] = []
    else:
        # Remove espaços extras e pontuação no final
        processed['payment_methods'] = [
            method.strip().rstrip('.').rstrip(',')
            for method in processed.get('payment_methods', [])
            if method and isinstance(method, str)
        ]

    # Campos de string - remover pontuação desnecessária no final
    text_fields = [
        'evaluation_price',
        'treatment_prices',
        'health_insurance_plans',
        'installment_conditions'
    ]
    for field in text_fields:
        if isinstance(processed.get(field), str):
            processed[field] = processed[field].strip().rstrip('.')

    # Garante que accepts_health_insurance é boolean
    processed['accepts_health_insurance'] = bool(processed.get('accepts_health_insurance', False))

    # Formata um texto amigável sobre planos de saúde
    health_plans = processed.get('health_insurance_plans', '').strip()
    if processed['accepts_health_insurance'] and health_plans:
        processed['insurance_info'] = f"Sim, aceitamos os seguintes convênios: {health_plans}"
    elif processed['accepts_health_insurance']:
        processed['insurance_info'] = "Sim, aceitamos convênios"
    else:
        processed['insurance_info'] = "Não aceitamos convênios no momento"

    # Monta texto de condições de pagamento
    payment_methods_str = ", ".join(processed.get('payment_methods', []))
    installment_info = processed.get('installment_conditions', '')
    processed['payment_info'] = (
        f"Formas de pagamento aceitas: {payment_methods_str}. "
        f"{installment_info}" if payment_methods_str else "Informações de pagamento não disponíveis"
    ).strip()

    return processed

def process_conversation_flow(conversation_flow: dict) -> dict:
    """
    Processa o campo conversation_flow para garantir formato e campos adequados.

    Args:
        conversation_flow (dict): Dicionário contendo as configurações do fluxo de conversa

    Returns:
        dict: Dicionário processado com os campos formatados
    """
    processed = conversation_flow.copy() if isinstance(conversation_flow, dict) else {}

    # Processa steps básicos (0-3)
    step_keys = ['step0', 'step1First', 'step1Second', 'step2', 'step3']
    for key in step_keys:
        if isinstance(processed.get(key), str):
            processed[key] = processed[key].strip()
            # Substituir placeholders comuns com formato mais padronizado
            processed[key] = processed[key].replace('[nome-assistente]', '{{assistantName}}')
            processed[key] = processed[key].replace('[nome-da-empresa]', '{{companyName}}')
            processed[key] = processed[key].replace('[nome_da_companya]', '{{companyName}}')
            processed[key] = processed[key].replace('[nome-da-companya]', '{{companyName}}')
            processed[key] = processed[key].replace('[Nome]', '{{name}}')
            processed[key] = processed[key].replace('[dor]', '{{painPoint}}')
            processed[key] = processed[key].replace('[tratamento]', '{{treatment}}')
        else:
            processed[key] = ''

    # Processa redirecionamentos
    redirect_keys = [
        'regular_redirect',
        'financial_redirect',
        'maintenance_redirect',
        'active_customers_redirect'
    ]

    for key in redirect_keys:
        redirect = processed.get(key, {})
        if isinstance(redirect, dict):
            # Garante que tem type e number
            redirect_type = redirect.get('type', '').strip().lower()
            if redirect_type not in ['fixo', 'whatsapp']:
                redirect_type = 'fixo'

            number = redirect.get('number', '').strip()
            # Formata o número removendo caracteres desnecessários
            number = ''.join(c for c in number if c.isdigit() or c in '()+-')

            processed[key] = {
                'type': redirect_type,
                'number': number
            }
        else:
            processed[key] = {
                'type': 'fixo',
                'number': ''
            }

    # Processa few_shots (mantendo a função existente)
    if not isinstance(processed.get('few_shots'), list):
        processed['few_shots'] = []

    formatted_shots = []
    for shot in processed.get('few_shots', []):
        if isinstance(shot, dict):
            formatted_shot = {
                'userMessage': shot.get('userMessage', '').strip(),
                'botResponse': shot.get('botResponse', '').strip(),
                'objectionType': shot.get('objectionType', '').strip()
            }
            formatted_shots.append(formatted_shot)

    processed['few_shots'] = formatted_shots

    # Garante que max_tokens é um número válido
    try:
        processed['max_tokens'] = int(processed.get('max_tokens', 300))
    except (TypeError, ValueError):
        processed['max_tokens'] = 300

    return processed

# Atualização da função principal para incluir o novo processor
def get_agent_config_dict(db: Session, company_id: int) -> dict:
    """
    Busca a configuração de agent_configurations para a empresa 'company_id'
    e retorna um dicionário contendo as colunas JSONB processadas.
    """
    logger.info(f"[AgentConfig] Buscando registro para company_id={company_id}...")

    record = db.query(AgentConfiguration).filter_by(company_id=company_id).first()
    if not record:
        logger.warning(f"[AgentConfig] Nenhum registro encontrado para company_id={company_id}. Retornando {{}}.")
        return {}

    logger.info(f"[AgentConfig] Registro encontrado com ID={record.id}. Montando dict...")

    # Monta o dicionário cru
    config_raw = {
        "assistant_identity": record.assistant_identity or {},
        "company_info": record.company_info or {},
        "team_and_specialties": process_treatments(record.team_and_specialties or {}),
        "scheduling_config": record.scheduling_config or {},
        "financial_config": process_financial_config(record.financial_config or {}),
        "conversation_flow": process_conversation_flow(record.conversation_flow or {})  # Usando o novo processor
    }

    logger.debug(f"[AgentConfig] Dicionário RAW (antes do escape): {config_raw}")
    logger.info(f"[AgentConfig] Dicionário RAW (antes do escape): {config_raw}")

    config_escaped = recursively_escape_braces(config_raw)

    logger.debug(f"[AgentConfig] Dicionário ESCAPADO (final): {config_escaped}")
    logger.info(f"[AgentConfig] Dicionário ESCAPADO (final): {config_escaped}")

    logger.info(f"[AgentConfig] Retornando config_escaped para company_id={company_id}.")
    return config_escaped
