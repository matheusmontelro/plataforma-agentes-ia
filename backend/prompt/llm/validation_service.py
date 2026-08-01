
"""
Serviço de validação contextual para dados de agendamento.

Este módulo fornece funções para validar os dados extraídos durante
uma conversa de agendamento, analisando o contexto completo da conversa
para evitar erros de extração e agendamentos incorretos.
"""

import logging
import json
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from sqlalchemy.sql import text
from langchain_openai import ChatOpenAI
from backend.services.ai_provider_service import get_company_openai_api_key

logger = logging.getLogger(__name__)

def get_full_conversation_history(db, phone: str, company_id: int) -> list:
    """
    Obtém o histórico completo de conversa do banco de dados.

    Args:
        db: Sessão de banco de dados SQLAlchemy
        phone: Número de telefone do contato
        company_id: ID da empresa

    Returns:
        Lista de mensagens formatadas com sender, content e timestamp
    """
    try:
        messages = db.execute(text("""
            SELECT
                from_me,
                content,
                timestamp,
                CASE WHEN from_me THEN 'assistant' ELSE 'user' END as sender
            FROM messages
            WHERE contact_phone = :phone
              AND company_id = :company_id
            ORDER BY timestamp ASC
        """), {"phone": phone, "company_id": company_id}).fetchall()

        # Converter para lista de dicionários
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "sender": msg.sender,
                "content": msg.content,
                "timestamp": msg.timestamp.strftime("%d/%m/%Y %H:%M")
            })

        logger.info(f"[ValidationService] Recuperadas {len(formatted_messages)} mensagens da conversa")
        return formatted_messages

    except Exception as e:
        logger.error(f"[ValidationService] Erro ao recuperar histórico da conversa: {e}")
        return []

def validate_all_extracted_data(state_machine, conversation_history: list) -> dict:
    """
    Valida todos os dados extraídos no state_machine usando o contexto completo da conversa.

    Args:
        state_machine: Instância de ConversationStateMachine
        conversation_history: Lista de mensagens da conversa

    Returns:
        Dicionário com os campos validados e suas pontuações de confiança
    """
    # Coletar todos os dados relevantes do state_machine
    extracted_data = {
        "nome": state_machine.get_state_data("nome"),
        "tratamento": state_machine.get_state_data("tratamento"),
        "cliente": state_machine.get_state_data("cliente"),
        "data": state_machine.get_state_data("data"),
        "horario": state_machine.get_state_data("horario")
    }

    # Formatar o histórico da conversa
    formatted_history = "\n".join([
        f"{'Usuário' if msg['sender'] == 'user' else 'Assistente'} [{msg['timestamp']}]: {msg['content']}"
        for msg in conversation_history
    ])

    # Prompt aprimorado para validar todos os campos
    prompt = f"""
    Você está analisando uma conversa entre um usuário e um assistente virtual de agendamento de serviços.

    DADOS EXTRAÍDOS DA CONVERSA:
    - Nome: {extracted_data['nome'] or 'Não extraído'}
    - Tratamento de interesse: {extracted_data['tratamento'] or 'Não extraído'}
    - Tipo de cliente: {extracted_data['cliente'] or 'Não extraído'}
    - Data agendada: {extracted_data['data'] or 'Não extraído'}
    - Horário agendado: {extracted_data['horario'] or 'Não extraído'}

    HISTÓRICO COMPLETO DA CONVERSA:
    {formatted_history}

    Com base no histórico COMPLETO da conversa, valide cada um dos campos extraídos.

    Para cada campo, determine:
    1. Se o valor está explicitamente mencionado na conversa
    2. Se outro valor diferente deveria ter sido extraído
    3. Se há confusão, ambiguidade ou contradição sobre esse valor

    Diretrizes importantes:
    - Analise o contexto completo e a sequência da conversa, não apenas menções isoladas
    - Valores mencionados pelo assistente NÃO significam que o usuário concordou com eles
    - Para datas e horários, verifique se o usuário explicitamente aceitou ou escolheu
    - Se o usuário rejeitou uma data/horário, esta deve ter confiança 0
    - Se o usuário manifestou preferência por outra data/horário, ajuste o valor para refletir isso
    - Não considere respostas como "pode ser", "ok", "sim" como aceitações do último valor sugerido, o usuário deve escolher explicitamente o horário e data que foi sugerido.
    - Se o usuário mostrou preferênciar por agendar de manhã, de tarde de um dia específico você deve confirmar o horário correto, não adivinhe nada.

    RETORNE SUA ANÁLISE NO SEGUINTE FORMATO JSON:
    {{
      "nome": {{ "valor": "nome_correto_ou_null", "confianca": 0-100, "obs": "breve observação" }},
      "tratamento": {{ "valor": "tratamento_correto_ou_null", "confianca": 0-100, "obs": "breve observação" }},
      "cliente": {{ "valor": "cliente_correto_ou_null", "confianca": 0-100, "obs": "breve observação" }},
      "data": {{ "valor": "data_correta_ou_null", "confianca": 0-100, "obs": "breve observação" }},
      "horario": {{ "valor": "horario_correto_ou_null", "confianca": 0-100, "obs": "breve observação" }}
    }}

    Onde:
    - "valor" deve ser o valor correto baseado na conversa, ou null se não puder ser determinado
    - "confianca" é uma pontuação de 0-100 indicando sua confiança no valor
    - "obs" é uma breve justificativa da sua avaliação

    Seja rigoroso na avaliação, especialmente em relação a datas e horários.
    """

    try:
        # Usar modelo mais robusto para análise profunda
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.0,
            openai_api_key=get_company_openai_api_key(
                state_machine.db_session,
                state_machine.company_id,
            ),
        )
        response = llm.predict(prompt)

        # Extrair o JSON da resposta
        match = re.search(r"({.*})", response, re.DOTALL)
        if match:
            json_str = match.group(1)
            validation_result = json.loads(json_str)

            # Logar resultado para debug
            logger.info(f"[ValidationService] Resultado da validação: {json.dumps(validation_result, indent=2)}")

            return validation_result
        else:
            logger.warning(f"[ValidationService] Não foi possível extrair JSON da resposta: {response}")
            return {}
    except Exception as e:
        logger.error(f"[ValidationService] Erro ao processar resposta: {e}")
        return {}

def analyze_appointment_confirmation(state_machine, conversation_history: list) -> Tuple[bool, dict]:
    """
    Analisa especificamente se um agendamento foi confirmado pelo usuário.

    Args:
        state_machine: Instância de ConversationStateMachine
        conversation_history: Lista de mensagens da conversa

    Returns:
        Tupla com (confirmação_válida, detalhes)
        - confirmação_válida: boolean indicando se o agendamento pode ser confirmado
        - detalhes: dicionário com informações sobre a análise
    """
    # Obter dados críticos para agendamento
    data = state_machine.get_state_data("data")
    horario = state_machine.get_state_data("horario")
    nome = state_machine.get_state_data("nome")

    # Se faltam dados essenciais, não podemos confirmar
    if not (data and horario and nome):
        return False, {
            "error": "missing_fields",
            "message": "Dados essenciais incompletos",
            "missing": [f for f in ["data", "horario", "nome"] if not state_machine.get_state_data(f)]
        }

    # Validação completa do contexto
    validation_result = validate_all_extracted_data(state_machine, conversation_history)

    # Se não obtivemos resultados de validação
    if not validation_result:
        return False, {
            "error": "validation_failed",
            "message": "Falha na validação contextual"
        }

    # Verificar confiança nos campos críticos
    critical_fields = ["data", "horario", "nome"]
    low_confidence_fields = []

    for field in critical_fields:
        if field in validation_result:
            confidence = validation_result[field].get("confianca", 0)
            if confidence < 75:  # Threshold rigoroso para agendamento
                low_confidence_fields.append({
                    "field": field,
                    "confidence": confidence,
                    "obs": validation_result[field].get("obs", "")
                })

    # Se algum campo crítico tem baixa confiança, abortar confirmação
    if low_confidence_fields:
        return False, {
            "error": "low_confidence",
            "message": "Baixa confiança em campos críticos",
            "fields": low_confidence_fields
        }

    # Aplicar possíveis correções dos valores
    updated_fields = {}
    for field in critical_fields:
        if field in validation_result:
            suggested_value = validation_result[field].get("valor")
            current_value = state_machine.get_state_data(field)

            if suggested_value and suggested_value != current_value:
                updated_fields[field] = {
                    "old": current_value,
                    "new": suggested_value,
                    "confidence": validation_result[field].get("confianca", 0)
                }

    # Se tudo está ok, podemos confirmar
    return True, {
        "status": "confirmation_valid",
        "message": "Dados validados com alta confiança",
        "updated_fields": updated_fields
    }

def handle_data_validation(state_machine, validation_result: dict) -> Optional[str]:
    """
    Processa os resultados da validação e toma ações apropriadas.

    Args:
        state_machine: Instância de ConversationStateMachine
        validation_result: Resultado da validação contextual

    Returns:
        Mensagem para o usuário se necessário, ou None para continuar fluxo normal
    """
    if not validation_result:
        return None

    # Flags para controlar o que fazer
    needs_correction = False
    fields_to_correct = []
    fields_corrected = False

    # Verificar cada campo crítico
    for field in ["data", "horario", "nome"]:
        if field in validation_result:
            field_data = validation_result[field]
            extracted_value = state_machine.get_state_data(field)

            # Se o valor extraído existe mas tem baixa confiança (<70)
            if extracted_value and field_data.get("confianca", 0) < 70:
                fields_to_correct.append(field)
                needs_correction = True

            # Se o valor correto é diferente do extraído e tem alta confiança (>80)
            elif (field_data.get("valor") and
                  field_data.get("valor") != extracted_value and
                  field_data.get("confianca", 0) > 80):
                # Corrigir o valor no state_machine
                state_machine.set_state_data(field, field_data["valor"])
                fields_corrected = True
                logger.info(f"[ValidationService] Campo {field} corrigido: '{extracted_value}' -> '{field_data['valor']}'")

    # Se precisamos corrigir campos mas sem valores claros para substituir
    if needs_correction and not fields_corrected:
        # Limpar os campos com problema
        for field in fields_to_correct:
            state_machine.set_state_data(field, None)

        # Voltar para o step apropriado
        if "data" in fields_to_correct or "horario" in fields_to_correct:
            state_machine.set_current_step(4)  # Voltar para coleta de data/hora
        elif "nome" in fields_to_correct:
            state_machine.set_current_step(5)  # Voltar para coleta de nome

        # Gerar mensagem contextualizada para o usuário
        field_names = {"data": "data", "horario": "horário", "nome": "nome completo"}
        fields_str = ", ".join(field_names[f] for f in fields_to_correct)

        if len(fields_to_correct) > 1:
            return f"Desculpe, parece que ficaram faltando ou não entendi corretamente as seguintes informações: {fields_str}. Poderia confirmar, por favor?"
        else:
            return f"Desculpe, parece que ficou faltando ou não entendi corretamente a seguinte informação: {fields_str}. Poderia confirmar, por favor?"

    return None

def validate_specific_field(state_machine, conversation_history: list, field_name: str) -> dict:
    """
    Valida um campo específico no contexto da conversa.

    Args:
        state_machine: Instância de ConversationStateMachine
        conversation_history: Lista de mensagens da conversa
        field_name: Nome do campo a ser validado (ex: "data", "horario")

    Returns:
        Dicionário com resultado da validação
    """
    current_value = state_machine.get_state_data(field_name)

    # Formatar o histórico da conversa
    formatted_history = "\n".join([
        f"{'Usuário' if msg['sender'] == 'user' else 'Assistente'} [{msg['timestamp']}]: {msg['content']}"
        for msg in conversation_history
    ])

    # Criar prompt especializado para o campo
    prompt = f"""
    Você está analisando uma conversa entre um usuário e um assistente virtual de agendamento de serviços.

    CAMPO A VERIFICAR: {field_name}
    VALOR EXTRAÍDO: {current_value or 'Não extraído'}

    HISTÓRICO COMPLETO DA CONVERSA:
    {formatted_history}

    Com base no histórico COMPLETO da conversa, valide se o valor extraído para {field_name} está correto.

    Determine:
    1. Se o valor está explicitamente mencionado/aceito pelo USUÁRIO (não apenas pelo assistente)
    2. Se outro valor diferente deveria ter sido extraído
    3. Se há confusão, ambiguidade ou contradição sobre esse valor
    4. A data e horário deve ter sido confirmado explicitamente pelo usuário.

    Atenção especial para:
    - Se for "data": formato deve ser DD/MM/YYYY
    - Se for "horario": formato deve ser HH:MM, deve ter sido EXPLICITAMENTE escolhido pelo usuário!
    - Se for "nome": deve ser nome completo que o USUÁRIO forneceu
    - Se for "tratamento": deve ser o tratamento de serviços escolhido pelo usuário ou simplesmente uma Consulta de Avaliação, caso o usuário não saiba o taratmento que ele deseja avaliar.
    - Se for "cliente": deve sinalizar se é um 'novo' cliente ou já é um cliente da empresa e deseja uma avaliação.
    RETORNE SUA ANÁLISE NO SEGUINTE FORMATO:
    {{
      "valor": "valor_correto_ou_null",
      "confianca": 0-100,
      "obs": "justificativa detalhada"
    }}
    """

    try:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.0,
            openai_api_key=get_company_openai_api_key(
                state_machine.db_session,
                state_machine.company_id,
            ),
        )
        response = llm.predict(prompt)

        # Extrair o JSON da resposta
        match = re.search(r"({.*})", response, re.DOTALL)
        if match:
            json_str = match.group(1)
            result = json.loads(json_str)

            logger.info(f"[ValidationService] Validação de '{field_name}': {json.dumps(result, indent=2)}")
            return result
        else:
            logger.warning(f"[ValidationService] Não foi possível extrair JSON da resposta: {response}")
            return {}
    except Exception as e:
        logger.error(f"[ValidationService] Erro ao validar campo '{field_name}': {e}")
        return {}

def check_evaluation_price_disclosure(db, state_machine, conversation_history: list) -> Tuple[bool, str]:
    """
    Verifica se o preço da consulta de avaliação foi divulgado ao cliente.

    Args:
        db: Sessão de banco de dados
        state_machine: Instância de ConversationStateMachine
        conversation_history: Lista de mensagens da conversa

    Returns:
        Tupla com (preço_divulgado, mensagem_para_usuário)
        - preço_divulgado: True se preço foi divulgado ou é gratuito, False caso contrário
        - mensagem_para_usuário: Mensagem para informar o preço (vazia se já divulgado)
    """
    company_id = state_machine.company_id

    # Buscar preço da avaliação na configuração
    try:
        result = db.execute(text("""
            SELECT financial_config->>'evaluation_price' as evaluation_price
            FROM agent_configurations
            WHERE company_id = :company_id
        """), {"company_id": company_id}).fetchone()

        evaluation_price = result.evaluation_price if result else ""
    except Exception as e:
        logger.error(f"[ValidationService] Erro ao buscar preço da avaliação: {e}")
        return True, ""  # Em caso de erro, continuar com o agendamento

    # Verificar se a avaliação é gratuita usando LLM
    is_free_prompt = f"""
    Analise o texto: "{evaluation_price}"
    Este texto indica que a consulta de avaliação é gratuita/gratuito ou paga?
    Responda apenas "gratuita" ou "paga".
    """

    try:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.0,
            openai_api_key=get_company_openai_api_key(db, company_id),
        )
        is_free_response = llm.predict(is_free_prompt).strip().lower()

        if "gratuita" in is_free_response:
            logger.info(f"[ValidationService] Avaliação é gratuita: '{evaluation_price}'")
            return True, ""  # Se gratuita, não precisa verificar divulgação
    except Exception as e:
        logger.error(f"[ValidationService] Erro ao verificar gratuidade: {e}")

    # Formatar o histórico da conversa
    formatted_history = "\n".join([
        f"{'Usuário' if msg['sender'] == 'user' else 'Assistente'} [{msg['timestamp']}]: {msg['content']}"
        for msg in conversation_history
    ])

    # Verificar se o preço foi divulgado na conversa
    prompt = f"""
    Você está analisando uma conversa entre um usuário e um assistente virtual de agendamento de serviços.

    O assistente deve informar ao cliente que a consulta de avaliação custa {evaluation_price} antes de confirmar o agendamento.

    HISTÓRICO DA CONVERSA:
    {formatted_history}

    Pergunta: O assistente informou claramente ao cliente que a consulta de avaliação custa {evaluation_price}?
    Responda apenas "sim" ou "não".
    """

    try:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.5,
            openai_api_key=get_company_openai_api_key(db, company_id),
        )
        price_disclosed = llm.predict(prompt).strip().lower()

        if "sim" in price_disclosed:
            logger.info("[ValidationService] Preço já foi divulgado na conversa")
            return True, ""
        else:
            logger.info("[ValidationService] Preço NÃO foi divulgado, gerando mensagem informativa")

            # Criar mensagem informando o preço
            price_message_prompt = f"""
            Crie uma mensagem humanizada, curta e simpática informando ao cliente que a consulta de avaliação custa {evaluation_price}. Não seja formal!
            Não precisa de saudação seja prático reformulando de forma humanizada e finalize a explicação com um ponto final.
            Pergunte se ele deseja prosseguir com o agendamento. Não invente moda, simplesmente crie uma mensagem melhorada pra explicar o preço e pergunte no final se pode prosseguri com o agendamento.
            """

            price_message = llm.predict(price_message_prompt)
            return False, price_message

    except Exception as e:
        logger.error(f"[ValidationService] Erro ao verificar divulgação de preço: {e}")
        return True, ""  # Em caso de erro, continuar com o agendamento
