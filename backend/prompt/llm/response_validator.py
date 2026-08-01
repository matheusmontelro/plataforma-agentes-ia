import re
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
import pytz

from backend.prompt.llm.parser_chain import LLMUserData
from backend.prompt.scheduling.scheduling_service import SchedulingService
from backend.services.ai_provider_service import get_company_openai_api_key

# Importações do LangChain
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)

class ValidationResult:
    """
    Contém o resultado final da validação da resposta do LLM.
    """
    def __init__(self,
                 status: str,
                 final_response: str,
                 logs: Optional[dict] = None,
                 parsed_data: Optional[LLMUserData] = None):
        """
        :param status: "APPROVED", "NEEDS_REFORMULATION", ou "FIXED"
        :param final_response: Texto final do LLM (original ou corrigido)
        :param logs: Dicionário com detalhes adicionais (critérios falhos, etc.)
        :param parsed_data: LLMUserData validado e potencialmente corrigido
        """
        self.status = status
        self.final_response = final_response
        self.logs = logs or {}
        self.parsed_data = parsed_data

class EnhancedResponseValidator:
    """
    Validador aprimorado que lida com validação e correção de respostas do LLM.
    Resolve o problema do KeyError ao usar uma abordagem mais robusta para prompts.
    """
    def __init__(self, db_session, company_id: int, company_config: Dict[str, Any] = None):
        self.db_session = db_session
        self.company_id = company_id
        self.scheduling_service = SchedulingService(db=db_session, company_id=company_id)
        self.sp_tz = pytz.timezone("America/Sao_Paulo")

        # Armazenar configuração da empresa
        self.company_config = company_config or {}
        self.financial_config = self.company_config.get('financial_config', {})
        self.correct_evaluation_price = self.financial_config.get('evaluation_price', '')

        # Cache de validações para evitar processamento duplicado
        self._validation_cache = {}
        self._cache_ttl = 300  # 5 minutos
        company_api_key = get_company_openai_api_key(db_session, company_id)

        # Inicializar o LLM para validação (evitando templates problemáticos)
        self.validation_llm = ChatOpenAI(
            model_name="gpt-4o-mini",
            temperature=0.0,
            openai_api_key=company_api_key,
        )

        # Inicializar o LLM para correção
        self.correction_llm = ChatOpenAI(
            model_name="gpt-4o-mini",  # GPT em vez de Llama3 para consistência
            temperature=0.7,
            openai_api_key=company_api_key,
        )

    def validate_response(self,
                        response_text: str,
                        conversation_context: Dict[str, Any],
                        parsed_data: LLMUserData) -> ValidationResult:
        """
        Método principal de validação que combina todas as etapas.
        """
        # Verificar cache primeiro
        cache_key = f"{hash(response_text)}_{self.company_id}"
        if cache_key in self._validation_cache:
            cached_result, timestamp = self._validation_cache[cache_key]
            if (datetime.now() - timestamp).seconds < self._cache_ttl:
                logger.info("[ResponseValidator] Retornando resultado do cache")
                return cached_result

        failures = []
        logs = {
            "original_response": response_text,
            "failed_criteria": []
        }

        # NOVO: Corrigir preço ANTES de outras validações
        response_text, price_fixed = self._fix_price_in_response(response_text)
        if price_fixed:
            logs["price_corrected"] = True
            logger.info(f"[ResponseValidator] Preço corrigido para {self.correct_evaluation_price}")

        # Adicionar verificação de falsa confirmação
        user_message = conversation_context.get("user_message", "")
        state_data = conversation_context.get("state_data", {})
        has_confirmation = state_data.get("agendamento_confirmado", False)

        # Se resposta menciona confirmação mas não há confirmação no state_data
        if ("confirmada" in response_text.lower() or "confirmado" in response_text.lower()) and not has_confirmation:
            failures.append("FALSE_CONFIRMATION")

        # 1. Verificar se o texto contém slots de tempo indisponíveis
        if not self._check_suggested_slots(response_text):
            failures.append("INVALID_SLOT_SUGGESTION")

        # 2. Verificar formato dos dados analisados (data, hora)
        if not self._check_parsed_data_format(parsed_data):
            failures.append("PARSER_DATA_FORMAT_FAIL")
        else:
            # Se data e hora estiverem presentes, verificar se o slot está disponível
            if parsed_data.data and parsed_data.horario:
                full_slot = f"{parsed_data.data} {parsed_data.horario}"
                all_slots = self.scheduling_service.get_next_available_slots()
                if full_slot not in all_slots:
                    failures.append("PARSER_SLOT_UNAVAILABLE")

        # 3. Validar coerência mais profunda com LLM
        llm_result = self._check_coherence_with_llm(parsed_data, conversation_context)
        logs["parser_llm_result"] = llm_result

        if llm_result["status"] == "ERROR":
            failures.append(f"PARSER_DATA_LLM_ERROR: {llm_result['error']}")

        logs["failed_criteria"] = failures

        if not failures:
            logs["status"] = "APPROVED"
            return ValidationResult(status="APPROVED", final_response=response_text, logs=logs, parsed_data=parsed_data)

        # Se houver falhas, tenta corrigir a resposta
        fixed_response, fixed_data = self._fix_response(
            response_text,
            failures,
            conversation_context,
            parsed_data
        )

        # Se conseguiu corrigir
        if fixed_response != response_text:
            logs["status"] = "FIXED"
            logs["fixed_response"] = fixed_response
            return ValidationResult(
                status="FIXED",
                final_response=fixed_response,
                logs=logs,
                parsed_data=fixed_data or parsed_data
            )

        logs["status"] = "NEEDS_REFORMULATION"
        return ValidationResult(
            status="NEEDS_REFORMULATION",
            final_response=response_text,
            logs=logs,
            parsed_data=parsed_data
        )

    def _add_today_info(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adiciona informações de data/hora de hoje ao contexto.
        """
        now_dt = datetime.now(self.sp_tz)
        weekday_map_pt = {
            0: "Segunda-feira",
            1: "Terça-feira",
            2: "Quarta-feira",
            3: "Quinta-feira",
            4: "Sexta-feira",
            5: "Sábado",
            6: "Domingo"
        }
        wday_str = weekday_map_pt.get(now_dt.weekday(), "Desconhecido")
        today_str = now_dt.strftime("%d/%m/%Y %H:%M")

        context_copy = context.copy()
        context_copy["today_info"] = f"Hoje é {wday_str}, {today_str}"
        return context_copy

    def _check_suggested_slots(self, response_text: str) -> bool:
        """
        Verifica se os slots de tempo sugeridos no texto estão disponíveis.
        """
        pattern = r"\b\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}\b"
        found = re.findall(pattern, response_text)
        if not found:
            return True  # Se não encontrou nenhuma sugestão, está OK

        available_slots = self.scheduling_service.get_next_available_slots()
        for slot in found:
            if slot not in available_slots:
                logger.info(f"[EnhancedResponseValidator] Slot sugerido inválido: {slot}")
                return False
        return True

    def _check_parsed_data_format(self, parsed_data: LLMUserData) -> bool:
        """
        Verifica se a data e a hora estão em formato válido (DD/MM/YYYY, HH:mm)
        e se o cliente é 'novo' ou 'antigo' (se preenchido).
        """
        # Formato de data: DD/MM/YYYY
        if parsed_data.data:
            if not re.match(r"^\d{2}/\d{2}/\d{4}$", parsed_data.data):
                return False

        # Formato de hora: HH:mm
        if parsed_data.horario:
            if not re.match(r"^\d{2}:\d{2}$", parsed_data.horario):
                return False

        # Cliente: se preenchido, deve ser "novo" ou "antigo"
        if parsed_data.cliente and parsed_data.cliente not in ["novo", "antigo"]:
            return False

        return True

    def _check_coherence_with_llm(self,
                                parsed_data: LLMUserData,
                                conversation_context: dict) -> dict:
        """
        Usa um LLM para verificar se os campos em parsed_data fazem sentido.
        Retorna um dicionário com status ("OK" ou "ERROR") e mensagem de erro.
        EVITA o uso de templates problemáticos utilizando SystemMessage diretamente.
        """
        # Convertemos o contexto para um formato seguro
        context_json = json.dumps(conversation_context, ensure_ascii=False, indent=2)

        # Montamos o texto do prompt diretamente (sem template)
        prompt_text = f"""
        Você é um validador que verifica dados extraídos de uma conversa quanto à coerência.

        == DADOS EXTRAÍDOS ==
        tratamento: {parsed_data.tratamento or 'null'}
        cliente: {parsed_data.cliente or 'null'}
        nome: {parsed_data.nome or 'null'}
        data: {parsed_data.data or 'null'}
        horario: {parsed_data.horario or 'null'}
        agendamento_confirmado: {parsed_data.agendamento_confirmado}
        cancelar_agendamento: {parsed_data.cancelar_agendamento}
        motivo_cancelamento: {parsed_data.motivo_cancelamento or 'null'}

        == CONTEXTO ==
        {context_json}

        == REGRAS BÁSICAS ==
        1. 'tratamento' deve ser plausível (Implante, Canal, etc.).
        2. 'cliente' = 'novo' ou 'antigo' (ou null).
        3. 'nome' não pode ser vazio se fornecido.
        4. 'data' deve ser DD/MM/YYYY e não pode ser anterior a hoje, salvo em caso de reagendamento.
        5. 'horario' deve ser HH:mm coerente com a 'data'.
        6. Se agendamento_confirmado=true, então data/horario devem existir.
        7. Se cancelar_agendamento=true, podemos ter 'motivo_cancelamento', mas não data/horario novos.
        8. Se houver contradição com o contexto, sinalize erro.

        Analise esses dados e retorne um JSON com o seguinte formato:
        {{
          "status": "OK ou ERROR",
          "error": "mensagem de erro ou null"
        }}

        Se tudo estiver coerente, use "status":"OK" e "error":null. Se houver problema, use "status":"ERROR" e descreva o erro.
        """

        # Usamos SystemMessage diretamente para evitar problemas com templates
        system_message = SystemMessage(content=prompt_text)

        try:
            # Chamada direta ao LLM com mensagem, sem usar prompt template
            response = self.validation_llm.invoke([system_message])
            content = response.content

            # Extrair o JSON da resposta
            try:
                # Tentativa de encontrar JSON entre chaves
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    result = json.loads(json_str)
                    status = result.get("status", "").upper()
                    error = result.get("error")

                    if status == "OK":
                        return {"status": "OK", "error": None}
                    else:
                        return {"status": "ERROR", "error": error or "Erro não especificado"}
                else:
                    return {"status": "ERROR", "error": "Formato JSON não encontrado na resposta"}

            except json.JSONDecodeError:
                return {"status": "ERROR", "error": "Falha ao decodificar JSON da resposta"}

        except Exception as e:
            logger.error(f"[EnhancedResponseValidator] Erro ao validar coerência: {e}")
            return {"status": "ERROR", "error": f"Erro de validação: {str(e)}"}

    def _fix_response(self,
                    original_text: str,
                    failures: List[str],
                    conversation_context: Dict[str, Any],
                    parsed_data: LLMUserData) -> tuple:
        """
        Tenta corrigir uma resposta problemática usando análise contextual profunda.
        """
        try:
            # Obter contexto completo da conversa
            user_message = conversation_context.get("user_message", "")
            state_data = conversation_context.get("state_data", {})
            chat_history = conversation_context.get("chat_history", [])

            # Extrair slots disponíveis
            available_slots = self.scheduling_service.get_next_available_slots()

            # Verificar confirmação no estado
            has_confirmation = state_data.get("agendamento_confirmado", False)
            existing_date = state_data.get("data")
            existing_time = state_data.get("horario")

            # Número máximo de sugestões
            scheduling_config = self.scheduling_service.config
            number_of_suggestions = scheduling_config.get('number_of_suggestions', 2)

            # Slots limitados para a resposta
            limited_slots = available_slots[:number_of_suggestions]
            slots_str = "\n".join(limited_slots)

            # Formatar o histórico da conversa de forma clara
            conversation_history = ""
            if chat_history:
                for i, message in enumerate(chat_history[-10:]):  # Últimas 10 mensagens
                    role = "Usuário" if message.type == "human" else "Assistente"
                    conversation_history += f"{role}: {message.content}\n"
            else:
                conversation_history = "Histórico não disponível"

            # Montar prompt para correção
            prompt_text = f"""
            Você é um validador especializado para um chatbot de agendamento de serviços.

            A resposta original abaixo precisa ser validada:

            RESPOSTA ORIGINAL:
            {original_text}

            MENSAGEM ATUAL DO USUÁRIO:
            "{user_message}"

            HISTÓRICO DA CONVERSA (últimas interações):
            {conversation_history}

            ESTADO DO AGENDAMENTO:
            - Confirmado: {"SIM" if has_confirmation else "NÃO"}
            - Data registrada: {existing_date or "Não definida"}
            - Horário registrado: {existing_time or "Não definido"}
            - Última fase: {conversation_context.get("current_step", "Desconhecida")}

            SLOTS DISPONÍVEIS (limitados a {number_of_suggestions}):
            {slots_str}

            PROBLEMAS IDENTIFICADOS:
            {', '.join(failures)}

            INSTRUÇÕES CRÍTICAS:
            1. Analise cuidadosamente o histórico da conversa. Observe o que o usuário realmente confirmou ou não.

            2. É estritamente proibido inventar uma confirmação de agendamento que não tenha sido explicitamente feita pelo usuário. Se o usuário perguntou sobre disponibilidade mas não confirmou um horário, NÃO use frases como "está confirmada sua consulta".

            3. Se a resposta original menciona uma confirmação inexistente, CORRIJA IMEDIATAMENTE, substituindo por uma resposta sobre disponibilidade.

            4. Quando sugerir horários, limite-se a {number_of_suggestions} opções.

            5. Se o usuário está perguntando sobre uma data específica (como "tem dia 5?"), verifique nos slots disponíveis e responda APENAS sobre disponibilidade nessa data.

            6. Nunca mude uma data/hora já acordada a menos que o usuário peça explicitamente.

            7. Se um usuário pergunta "tem amanhã?" ou similar, sempre verifique a disponibilidade real antes de responder.

            Por favor, corrija a resposta apenas se necessário, mantendo o tom amigável do original.
            """

            # Usar SystemMessage diretamente
            system_message = SystemMessage(content=prompt_text)

            # Chamar o LLM de correção com temperatura baixa para ser mais preciso
            response = self.correction_llm.invoke([system_message], temperature=0.1)
            fixed_text = response.content.strip()

            # Log da correção para diagnóstico
            logger.info(f"[EnhancedResponseValidator] Resposta original: '{original_text}'")
            logger.info(f"[EnhancedResponseValidator] Resposta corrigida: '{fixed_text}'")

            return fixed_text, None

        except Exception as e:
            logger.error(f"[EnhancedResponseValidator] Erro ao corrigir resposta: {e}")
            return original_text, None

    def _fix_price_in_response(self, response: str) -> tuple[str, bool]:
        """
        Corrige preços incorretos na resposta baseado na configuração da empresa
        """
        if not self.correct_evaluation_price:
            return response, False

        # Padrões para encontrar preços em formato brasileiro
        price_patterns = [
            (r'R\$\s*\d+(?:\.\d{3})*(?:,\d{2})?', 'currency'),  # R$ 150,00
            (r'\d+(?:\.\d{3})*(?:,\d{2})?\s*reais', 'reais'),   # 150 reais
            (r'valor\s+de\s+R\$\s*\d+(?:\.\d{3})*(?:,\d{2})?', 'valor_de'),  # valor de R$ 150,00
        ]

        modified = False
        for pattern, pattern_type in price_patterns:
            matches = list(re.finditer(pattern, response, re.IGNORECASE))

            # Processar matches de trás para frente para não afetar índices
            for match in reversed(matches):
                found_price = match.group()

                # Verificar contexto ao redor do preço
                context_before = response[max(0, match.start()-100):match.start()].lower()
                context_after = response[match.end():min(len(response), match.end()+100)].lower()

                # Palavras-chave que indicam preço de consulta/avaliação
                price_keywords = [
                    'consulta', 'avaliação', 'avaliaçao', 'primeira',
                    'valor da consulta', 'preço da consulta', 'custa a consulta',
                    'valor da avaliação', 'preço da avaliação', 'custa a avaliação'
                ]

                # Verificar se é contexto de consulta/avaliação
                is_evaluation_price = any(keyword in context_before + context_after for keyword in price_keywords)

                if is_evaluation_price:
                    # Extrair apenas o valor numérico do preço encontrado
                    price_value = re.search(r'\d+(?:\.\d{3})*(?:,\d{2})?', found_price)
                    if price_value:
                        found_value = price_value.group()
                        # Extrair valor numérico da config também
                        config_value = re.search(r'\d+(?:\.\d{3})*(?:,\d{2})?', self.correct_evaluation_price)

                        if config_value and found_value != config_value.group():
                            # Substituir mantendo o formato original
                            if pattern_type == 'currency':
                                new_price = self.correct_evaluation_price
                            elif pattern_type == 'reais':
                                # Extrair apenas número da config e adicionar "reais"
                                new_price = f"{config_value.group()} reais"
                            elif pattern_type == 'valor_de':
                                new_price = f"valor de {self.correct_evaluation_price}"

                            response = response[:match.start()] + new_price + response[match.end():]
                            modified = True
                            logger.warning(f"[ResponseValidator] Preço corrigido de '{found_price}' para '{new_price}'")

        # Armazenar no cache se foi modificado
        if modified:
            cache_key = f"{hash(response)}_{self.company_id}"
            self._validation_cache[cache_key] = (response, datetime.now())

        return response, modified
