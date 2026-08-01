# Sistema de Aprendizado Automático V2 - Integrado com Validação e Fluxo
import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
from collections import defaultdict
import numpy as np
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from backend.runtime_settings import AUTO_LEARNING_V2_DIR

logger = logging.getLogger(__name__)

# Constantes do fluxo
STEP_NAMES = {
    0: "boas_vindas",
    1: "recepcao_identificacao",
    2: "situacao_cliente",
    3: "exploracao_problema",
    4: "necessidade_solucao",
    5: "confirmacao_agendamento",
    6: "encerramento",
    7: "pos_agendamento",
    8: "cancelamento",
    9: "reagendamento"
}

REQUIRED_FIELDS = ["tratamento", "cliente", "nome", "data", "horario"]

class EnhancedContextPatternLearner:
    """
    Sistema aprimorado que aprende padrões de conversa integrando:
    - Validação de respostas
    - Fluxo de conversa (steps)
    - Few-shots configurados
    """

    def __init__(self, company_id: int):
        self.company_id = company_id
        self.base_path = str(AUTO_LEARNING_V2_DIR / f"company_{company_id}")
        Path(self.base_path).mkdir(parents=True, exist_ok=True)

        # Carrega dados existentes
        self.patterns = self._load_patterns()
        self.statistics = self._load_statistics()
        self.few_shots_loaded = self.statistics.get("few_shots_loaded", False)

    def _load_patterns(self) -> Dict[str, Any]:
        """Carrega padrões aprendidos do arquivo."""
        patterns_file = f"{self.base_path}/learned_patterns_v2.json"
        if os.path.exists(patterns_file):
            with open(patterns_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "successful_responses": {},
            "failed_responses": {},
            "pattern_frequency": {},
            "step_patterns": {}  # Novo: padrões por step
        }

    def _load_statistics(self) -> Dict[str, Any]:
        """Carrega estatísticas de aprendizado."""
        stats_file = f"{self.base_path}/statistics_v2.json"
        if os.path.exists(stats_file):
            with open(stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "total_conversations": 0,
            "patterns_learned": 0,
            "success_rate": 0.0,
            "last_update": None,
            "few_shots_loaded": False,
            "performance_by_step": {}
        }

    def learn_from_few_shots(self, agent_config: Dict):
        """Aprende dos few-shots configurados para a empresa."""
        if self.few_shots_loaded:
            return

        # Valida se agent_config é um dicionário
        if not isinstance(agent_config, dict):
            logger.error(f"[AutoLearning] agent_config não é um dicionário: {type(agent_config)}")
            return

        conversation_flow = agent_config.get('conversation_flow', {})
        if not isinstance(conversation_flow, dict):
            logger.error(f"[AutoLearning] conversation_flow não é um dicionário: {type(conversation_flow)}")
            return

        few_shots = conversation_flow.get('few_shots', [])

        for example in few_shots:
            # Criar padrão baseado no few-shot
            objection_type = example.get('objectionType', 'general')
            pattern_key = f"fewshot_{objection_type}"

            # Classificar resposta do usuário
            user_response_type = self._classify_user_response(example['userMessage'])

            # Adicionar como padrão bem-sucedido com alta prioridade
            self.patterns["pattern_frequency"][pattern_key] = {
                "count": 100,  # Alta contagem para prioridade
                "context_type": objection_type,
                "user_response_type": user_response_type,
                "successful_responses": [{
                    "response": example['botResponse'],
                    "timestamp": datetime.now().isoformat(),
                    "quality_score": 1.0,
                    "source": "few_shot_config"
                }],
                "failed_responses": [],
                "is_few_shot": True
            }

        self.statistics["few_shots_loaded"] = True
        self._save_patterns()
        self._save_statistics()
        logger.info(f"[AutoLearning] Carregados {len(few_shots)} few-shots para empresa {self.company_id}")

    def detect_conversation_pattern_enhanced(self, messages: List[BaseMessage],
                                           current_step: int,
                                           extracted_data: Dict) -> Dict[str, Any]:
        """
        Detecta padrão da conversa considerando step e dados extraídos.
        """
        # Padrão base
        pattern = self.detect_conversation_pattern(messages)

        # Adicionar contexto do step
        pattern["step"] = current_step
        pattern["step_name"] = STEP_NAMES.get(current_step, "unknown")

        # Adicionar campos preenchidos
        if isinstance(extracted_data, dict):
            pattern["filled_fields"] = [k for k, v in extracted_data.items() if v]
            pattern["missing_fields"] = [k for k in REQUIRED_FIELDS if not extracted_data.get(k)]
        else:
            logger.warning(f"[AutoLearning] extracted_data não é dict: {type(extracted_data)}")
            pattern["filled_fields"] = []
            pattern["missing_fields"] = REQUIRED_FIELDS.copy()

        # Detectar situações específicas
        if current_step == 5 and "nome" in pattern["filled_fields"]:
            pattern["situation"] = "confirming_appointment"
        elif current_step == 3 and "tratamento" not in pattern["filled_fields"]:
            pattern["situation"] = "exploring_treatment"
        elif current_step == 4 and len(pattern["filled_fields"]) >= 3:
            pattern["situation"] = "ready_to_schedule"
        else:
            pattern["situation"] = "general_conversation"

        # Gerar hash único incluindo step
        pattern_key = f"{pattern['step']}_{pattern['context_type']}_{pattern['user_response_type']}_{pattern['situation']}"
        pattern["pattern_hash"] = hashlib.md5(pattern_key.encode()).hexdigest()[:8]

        return pattern

    def detect_conversation_pattern(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        """
        Detecta o padrão básico da conversa.
        """
        pattern = {
            "has_oper_intervention": False,
            "user_response_type": None,
            "llm_response_quality": None,
            "pattern_hash": None,
            "context_type": None,
            "last_oper_message": None,
            "is_first_response_after_oper": False  # NOVO: flag para primeira resposta
        }

        # Analisa mensagens recentes (últimas 6 mensagens)
        recent_messages = messages[-6:] if len(messages) > 6 else messages

        # Verifica se a última resposta é a primeira após OPER mais recente
        if len(messages) >= 2:
            # Procura a última mensagem OPER
            last_oper_index = -1
            for i in range(len(messages) - 1, -1, -1):
                if isinstance(messages[i], AIMessage) and '[operador]' in messages[i].content.lower():
                    last_oper_index = i
                    break

            # Se encontrou OPER
            if last_oper_index >= 0:
                # Conta quantas mensagens AI existem após o último OPER
                ai_count_after_oper = 0
                for i in range(last_oper_index + 1, len(messages)):
                    if isinstance(messages[i], AIMessage):
                        ai_count_after_oper += 1

                # Se esta é a primeira AI após OPER (considerando que estamos avaliando uma nova resposta)
                if ai_count_after_oper == 0:
                    pattern["has_oper_intervention"] = True
                    pattern["is_first_response_after_oper"] = True
                    pattern["last_oper_message"] = messages[last_oper_index].content
                    pattern["context_type"] = self._classify_oper_message(messages[last_oper_index].content)

                    logger.info(f"[AutoLearning] Detectada primeira resposta após OPER. Índice OPER: {last_oper_index}")
                    logger.info(f"[AutoLearning] Contexto OPER: {pattern['context_type']}")

                    # Pega a resposta do usuário após OPER (se houver)
                    for i in range(last_oper_index + 1, len(messages)):
                        if isinstance(messages[i], HumanMessage):
                            pattern["user_response_type"] = self._classify_user_response(messages[i].content)
                            break
                else:
                    # Teve OPER mas não é a primeira resposta
                    pattern["has_oper_intervention"] = True
                    pattern["is_first_response_after_oper"] = False
                    logger.debug(f"[AutoLearning] OPER detectado mas não é primeira resposta. AI count após OPER: {ai_count_after_oper}")

        # Análise geral se não detectou padrão OPER direto
        if not pattern["is_first_response_after_oper"]:
            for i, msg in enumerate(recent_messages):
                # Detecta se teve OPER recente (mas não é primeira resposta)
                if isinstance(msg, AIMessage) and '[operador]' in msg.content.lower():
                    pattern["has_oper_intervention"] = True
                    pattern["context_type"] = self._classify_oper_message(msg.content)
                    pattern["last_oper_message"] = msg.content

        # Se não tem intervenção OPER, classifica contexto pela última mensagem do usuário
        if not pattern["has_oper_intervention"] and messages:
            last_human_msg = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
            if last_human_msg:
                pattern["context_type"] = self._classify_general_context(last_human_msg.content)
                pattern["user_response_type"] = self._classify_user_response(last_human_msg.content)

        return pattern

    def _classify_oper_message(self, content: str) -> str:
        """Classifica o tipo de mensagem do operador."""
        content_lower = content.lower()

        if any(word in content_lower for word in ['horário', 'hora', 'hrs', 'consulta', 'agendamento', 'agenda']):
            return "scheduling"
        elif any(word in content_lower for word in ['dr', 'dra', 'doutor', 'doutora', 'profissional']):
            return "professional_info"
        elif any(word in content_lower for word in ['valor', 'preço', 'pagamento', 'custo', 'r$']):
            return "financial"
        elif any(word in content_lower for word in ['endereço', 'localização', 'como chegar', 'local']):
            return "location"
        elif any(word in content_lower for word in ['cancelar', 'cancela', 'desmarcar']):
            return "cancellation"
        elif any(word in content_lower for word in ['remarcar', 'reagendar', 'mudar horário']):
            return "reschedule"
        else:
            return "general_info"

    def _classify_general_context(self, content: str) -> str:
        """Classifica o contexto geral da mensagem do usuário."""
        content_lower = content.lower()

        if any(word in content_lower for word in ['dor', 'doendo', 'dói', 'machucado', 'problema']):
            return "pain_complaint"
        elif any(word in content_lower for word in ['quanto', 'valor', 'preço', 'custa']):
            return "price_inquiry"
        elif any(word in content_lower for word in ['horário', 'quando', 'disponível', 'vaga']):
            return "availability_inquiry"
        elif any(word in content_lower for word in ['tratamento', 'procedimento', 'fazer']):
            return "treatment_inquiry"
        else:
            return "general_inquiry"

    def _classify_user_response(self, content: str) -> str:
        """Classifica o tipo de resposta do usuário."""
        content_lower = content.lower()

        # Respostas positivas
        positive_words = ['sim', 'ok', 'pode', 'combinado', 'certo', 'beleza', 'confirmo',
                         'aceito', 'quero', 'vamos', 'fechado', 'topo']

        # Respostas negativas
        negative_words = ['não', 'nao', 'negativo', 'cancela', 'desisto', 'deixa',
                         'depois', 'pensar', 'ainda']

        # Perguntas
        question_indicators = ['?', 'como', 'quando', 'onde', 'qual', 'quanto',
                              'que horas', 'cadê', 'tem']

        # Dúvidas/incertezas
        doubt_words = ['não sei', 'nao sei', 'talvez', 'acho', 'será']

        # Contagem de indicadores
        has_positive = any(word in content_lower for word in positive_words)
        has_negative = any(word in content_lower for word in negative_words)
        has_question = any(indicator in content_lower for indicator in question_indicators)
        has_doubt = any(word in content_lower for word in doubt_words)

        # Lógica de classificação
        if has_doubt:
            return "uncertain"
        elif has_positive and not has_negative:
            return "positive_confirmation"
        elif has_negative and not has_positive:
            return "negative_response"
        elif has_question:
            return "question"
        elif len(content.strip()) < 10:  # Respostas muito curtas
            return "brief_response"
        else:
            return "neutral"

    def learn_from_conversation_with_validation(self, messages: List[BaseMessage],
                                              llm_response: str,
                                              current_step: int,
                                              extracted_data: Dict,
                                              validation_passed: bool,
                                              quality_bonus: float = 0.0,
                                              user_reaction: Optional[str] = None):
        """
        Aprende com uma conversa incluindo resultado da validação.
        """
        # Detecta o padrão aprimorado
        pattern = self.detect_conversation_pattern_enhanced(messages, current_step, extracted_data)

        if not pattern["pattern_hash"]:
            return

        # Avalia qualidade considerando validação
        base_quality = self._evaluate_response_quality(llm_response, pattern, user_reaction)
        final_quality = max(0.0, min(1.0, base_quality + quality_bonus))

        # Se não passou na validação, sempre considera como falha
        if not validation_passed:
            final_quality = min(final_quality, 0.3)

        # Atualiza padrões
        pattern_key = pattern["pattern_hash"]

        if pattern_key not in self.patterns["pattern_frequency"]:
            self.patterns["pattern_frequency"][pattern_key] = {
                "count": 0,
                "step": pattern["step"],
                "step_name": pattern["step_name"],
                "context_type": pattern["context_type"],
                "user_response_type": pattern["user_response_type"],
                "situation": pattern.get("situation", "unknown"),
                "successful_responses": [],
                "failed_responses": []
            }

        self.patterns["pattern_frequency"][pattern_key]["count"] += 1

        # Dados da resposta
        response_data = {
            "response": llm_response[:300],  # Aumentado para 300 chars
            "timestamp": datetime.now().isoformat(),
            "quality_score": final_quality,
            "validation_passed": validation_passed,
            "filled_fields": pattern.get("filled_fields", []),
            "missing_fields": pattern.get("missing_fields", [])
        }

        # Armazena como sucesso ou falha
        if final_quality > 0.7:
            self.patterns["pattern_frequency"][pattern_key]["successful_responses"].append(response_data)
            # Limita a 10 melhores exemplos
            self.patterns["pattern_frequency"][pattern_key]["successful_responses"] = sorted(
                self.patterns["pattern_frequency"][pattern_key]["successful_responses"],
                key=lambda x: x["quality_score"],
                reverse=True
            )[:10]
        else:
            self.patterns["pattern_frequency"][pattern_key]["failed_responses"].append(response_data)
            # Limita a 5 piores exemplos
            self.patterns["pattern_frequency"][pattern_key]["failed_responses"] = sorted(
                self.patterns["pattern_frequency"][pattern_key]["failed_responses"],
                key=lambda x: x["quality_score"]
            )[:5]

        # Atualiza estatísticas por step
        self._update_step_statistics(pattern["step"], final_quality > 0.7)

        # Atualiza estatísticas gerais
        self._update_statistics()

        # Salva dados
        self._save_patterns()

        logger.info(f"[AutoLearning] Padrão aprendido: {pattern_key} - Step: {pattern['step']} - Qualidade: {final_quality:.2f}")

    def _evaluate_response_quality(self, llm_response: str, pattern: Dict, user_reaction: Optional[str]) -> float:
        """
        Avalia a qualidade da resposta do LLM (0.0 a 1.0).
        """
        quality_score = 0.5  # Base
        response_lower = llm_response.lower()

        # NOVO: Avaliação de relevância contextual APENAS na primeira resposta após OPER
        if pattern.get("is_first_response_after_oper") and pattern.get("last_oper_message"):
            context_relevance = self._evaluate_context_relevance(
                llm_response,
                pattern["last_oper_message"],
                pattern.get("user_response_type", "")
            )

            # Ajusta qualidade baseado na relevância (não apenas penaliza)
            if context_relevance >= 0.7:
                quality_score += 0.3  # BONIFICA respostas muito relevantes
                logger.info(f"[AutoLearning] Alta relevância contextual após OPER: {context_relevance:.2f}")
            elif context_relevance >= 0.4:
                quality_score += 0.1  # Pequena bonificação para relevância moderada
            elif context_relevance < 0.3:
                quality_score -= 0.3  # Só penaliza se for muito irrelevante
                logger.info(f"[AutoLearning] Baixa relevância contextual após OPER: {context_relevance:.2f}")

        # Avaliação baseada no step
        step = pattern.get("step", 0)

        # Step 5 (Confirmação) - Crítico
        if step == 5:
            # Penaliza fortemente pedir nome quando já tem
            if "nome" in pattern.get("filled_fields", []) and any(phrase in response_lower for phrase in ['nome completo', 'seu nome', 'como você se chama']):
                quality_score -= 0.5

            # Bonifica confirmação clara
            if pattern.get("user_response_type") == "positive_confirmation":
                if any(word in response_lower for word in ['confirmado', 'agendado', 'marcado']):
                    quality_score += 0.3
                if any(word in response_lower for word in ['aguardamos', 'esperamos', 'até']):
                    quality_score += 0.2

        # Step 3 (Exploração) - Importante entender o problema
        elif step == 3:
            if "tratamento" not in pattern.get("filled_fields", []):
                # Bonifica perguntas exploratórias
                if any(word in response_lower for word in ['qual', 'onde', 'quando', 'como está']):
                    quality_score += 0.2
                # Penaliza assumir tratamento
                if any(word in response_lower for word in ['vamos agendar', 'marcar consulta']):
                    quality_score -= 0.3

        # Penaliza respostas genéricas após intervenção OPER
        if pattern.get("has_oper_intervention"):
            generic_phrases = ['como posso ajudar', 'qual seu nome', 'gostaria de agendar',
                             'me chamo', 'sou a', 'prazer', 'boa tarde', 'boa noite']

            for phrase in generic_phrases:
                if phrase in response_lower:
                    quality_score -= 0.2
                    break

        # Avalia baseado no tipo de contexto
        context_type = pattern.get("context_type")

        # NOVO: Bonifica respostas que atendem solicitações de horários
        if context_type in ["availability_inquiry", "scheduling"] or "horário" in response_lower:
            # Se está oferecendo horários quando solicitado
            import re
            has_time_pattern = bool(re.search(r'\d{2}:\d{2}', response_lower))
            has_period = any(word in response_lower for word in ['manhã', 'tarde', 'disponível'])

            if has_time_pattern or has_period:
                quality_score += 0.2
                logger.info("[AutoLearning] Bonificando resposta que oferece horários")

        if context_type == "scheduling" and pattern.get("user_response_type") == "positive_confirmation":
            # Deve reconhecer a confirmação
            if not any(word in response_lower for word in ['confirmado', 'agendado', 'marcado', 'reservado']):
                quality_score -= 0.3

        elif context_type == "financial":
            # Deve mencionar valor se disponível
            if 'r$' not in response_lower and 'valor' not in response_lower and 'avaliação' not in response_lower:
                quality_score -= 0.2

        # Considera reação do usuário
        if user_reaction:
            reaction_lower = user_reaction.lower()

            # Reações positivas
            positive_reactions = ['obrigado', 'obrigada', 'perfeito', 'ótimo', 'legal',
                                'show', 'massa', 'valeu', 'ok então']
            if any(word in reaction_lower for word in positive_reactions):
                quality_score += 0.2

            # Reações negativas
            negative_reactions = ['não', 'errado', 'já disse', 'já falei', 'de novo',
                                'quantas vezes', 'pare', 'chega']
            if any(word in reaction_lower for word in negative_reactions):
                quality_score -= 0.4

            # Usuário repete informação (sinal de que bot não entendeu)
            if pattern.get("filled_fields"):
                for field in pattern["filled_fields"]:
                    if field in reaction_lower:
                        quality_score -= 0.2
                        break

        # Penaliza respostas muito longas ou muito curtas
        response_length = len(response_lower.split())
        if response_length > 100:
            quality_score -= 0.1
        elif response_length < 5:
            quality_score -= 0.2

        # Limita entre 0 e 1
        return max(0.0, min(1.0, quality_score))

    def _evaluate_context_relevance(self, llm_response: str, oper_message: str, user_response_type: str) -> float:
        """
        Avalia se a resposta do LLM é relevante ao contexto da conversa.
        Retorna um valor entre 0.0 (irrelevante) e 1.0 (totalmente relevante).
        """
        # Normaliza textos
        response_lower = llm_response.lower()
        oper_lower = oper_message.lower()

        # Casos especiais de alta relevância
        # 1. OPER fornece informação de horário e AI responde sobre horário
        if any(word in oper_lower for word in ['horário', 'hora', ':']) and \
           any(word in response_lower for word in ['horário', 'disponível', ':']):
            return 0.9  # Alta relevância

        # 2. OPER menciona nome/pessoa e AI usa o nome
        import re
        # Extrai possíveis nomes próprios (palavras com inicial maiúscula)
        oper_names = re.findall(r'\b[A-Z][a-z]+\b', oper_message)
        if oper_names:
            for name in oper_names:
                if name.lower() in response_lower:
                    return 0.8  # Boa relevância por usar o nome

        # 3. Análise geral de palavras-chave
        # Remove pontuação e palavras muito comuns
        stop_words = {'o', 'a', 'de', 'da', 'do', 'em', 'para', 'com', 'por', 'que', 'e', 'é', 'um', 'uma',
                     'vai', 'está', 'aqui', 'você', 'voce', 'opa', 'oi', 'olá'}

        # Tokeniza e filtra
        oper_words = [w for w in re.findall(r'\b\w{3,}\b', oper_lower) if w not in stop_words]

        if not oper_words:
            return 0.5  # Neutro se não há palavras relevantes

        # Conta quantas palavras-chave aparecem na resposta
        mentioned_keywords = 0
        for word in oper_words:
            if word in response_lower:
                mentioned_keywords += 1

        # Calcula taxa de relevância
        relevance_ratio = mentioned_keywords / len(oper_words)

        # Verifica se é resposta completamente genérica após contexto específico
        generic_intros = ['me chamo', 'sou a consultora', 'como posso ajudar', 'prazer em conhecê']
        is_generic_intro = any(phrase in response_lower for phrase in generic_intros)

        # Se OPER deu informação específica e AI respondeu com intro genérica
        if is_generic_intro and len(oper_words) > 3:
            return max(0.2, relevance_ratio)  # Penaliza respostas genéricas

        # Escala ajustada de relevância
        if relevance_ratio >= 0.4:
            return 0.9  # Alta relevância
        elif relevance_ratio >= 0.25:
            return 0.6  # Relevância moderada
        elif relevance_ratio >= 0.1:
            return 0.4  # Baixa relevância
        else:
            return 0.3  # Muito baixa relevância

    def get_best_approach(self, current_pattern: Dict) -> Optional[Dict[str, Any]]:
        """
        Retorna a melhor abordagem aprendida para um padrão.
        """
        pattern_key = current_pattern["pattern_hash"]

        # Primeiro, tenta padrão exato
        if pattern_key in self.patterns["pattern_frequency"]:
            pattern_data = self.patterns["pattern_frequency"][pattern_key]

            if pattern_data["successful_responses"]:
                # Pega melhor resposta
                best_response = pattern_data["successful_responses"][0]

                # Gera instruções baseadas no aprendizado
                instructions = self._generate_instructions_from_pattern(pattern_data, best_response)

                return {
                    "approach": "use_successful_pattern",
                    "instructions": instructions,
                    "confidence": best_response["quality_score"],
                    "pattern_key": pattern_key,
                    "examples_count": len(pattern_data["successful_responses"])
                }

        # Se não encontrou padrão exato, busca similar
        similar_patterns = self._find_similar_patterns(current_pattern)

        if similar_patterns:
            best_similar = similar_patterns[0]
            pattern_data = self.patterns["pattern_frequency"][best_similar["key"]]

            if pattern_data["successful_responses"]:
                best_response = pattern_data["successful_responses"][0]
                instructions = self._generate_instructions_from_pattern(pattern_data, best_response, is_similar=True)

                return {
                    "approach": "use_similar_pattern",
                    "instructions": instructions,
                    "confidence": best_response["quality_score"] * best_similar["similarity"],
                    "pattern_key": best_similar["key"],
                    "similarity": best_similar["similarity"]
                }

        # Se só tem falhas conhecidas, pelo menos evita erros
        failed_patterns = self._find_failed_patterns_to_avoid(current_pattern)
        if failed_patterns:
            avoid_instructions = self._generate_avoid_instructions(failed_patterns)
            return {
                "approach": "avoid_known_failures",
                "instructions": avoid_instructions,
                "confidence": 0.4
            }

        return None

    def _generate_instructions_from_pattern(self, pattern_data: Dict, best_response: Dict, is_similar: bool = False) -> str:
        """Gera instruções baseadas no padrão aprendido."""
        instructions = []

        # Cabeçalho
        confidence_text = f"{best_response['quality_score']:.0%}"
        if is_similar:
            instructions.append(f"[PADRÃO SIMILAR - Confiança: {confidence_text}]")
        else:
            instructions.append(f"[PADRÃO EXATO - Confiança: {confidence_text}]")

        # Contexto
        instructions.append(f"Situação: {pattern_data.get('situation', 'unknown')}")
        instructions.append(f"Step atual: {pattern_data.get('step_name', 'unknown')}")

        # Exemplo de sucesso
        instructions.append(f"\nExemplo bem-sucedido:")
        instructions.append(f'"{best_response["response"]}"')

        # Campos que devem estar preenchidos
        if best_response.get("filled_fields"):
            instructions.append(f"\nCampos já preenchidos neste ponto: {', '.join(best_response['filled_fields'])}")

        # O que evitar
        if pattern_data.get("failed_responses"):
            common_failures = self._extract_common_failures(pattern_data["failed_responses"])
            if common_failures:
                instructions.append(f"\nEVITE: {', '.join(common_failures)}")

        # Dicas específicas por step
        step_tips = self._get_step_specific_tips(pattern_data.get("step", 0), pattern_data)
        if step_tips:
            instructions.append(f"\nDica: {step_tips}")

        return "\n".join(instructions)

    def _generate_avoid_instructions(self, failed_patterns: List[Dict]) -> str:
        """Gera instruções sobre o que evitar."""
        instructions = ["[EVITAR ERROS CONHECIDOS]"]

        all_failures = []
        for pattern in failed_patterns:
            pattern_data = self.patterns["pattern_frequency"][pattern["key"]]
            failures = self._extract_common_failures(pattern_data["failed_responses"])
            all_failures.extend(failures)

        # Remove duplicatas e lista
        unique_failures = list(set(all_failures))
        instructions.append(f"NÃO FAÇA: {', '.join(unique_failures[:5])}")  # Limita a 5

        return "\n".join(instructions)

    def _extract_common_failures(self, failed_responses: List[Dict]) -> List[str]:
        """Extrai erros comuns das respostas que falharam."""
        failures = []

        for response_data in failed_responses:
            response = response_data["response"].lower()

            # Erros comuns identificados
            if "nome completo" in response and response_data.get("filled_fields") and "nome" in response_data["filled_fields"]:
                failures.append("pedir nome quando já tem")

            if "como posso ajudar" in response:
                failures.append("pergunta genérica após contexto")

            if "gostaria de agendar" in response and response_data.get("filled_fields") and len(response_data["filled_fields"]) > 3:
                failures.append("oferecer agendamento quando já está agendando")

            if "qual o seu nome" in response and response_data.get("filled_fields") and "nome" in response_data["filled_fields"]:
                failures.append("pedir informação já fornecida")

            if not response_data.get("validation_passed", True):
                failures.append("resposta que falhou na validação")

        return failures

    def _get_step_specific_tips(self, step: int, pattern_data: Dict) -> str:
        """Retorna dicas específicas para cada step."""
        tips = {
            3: "Explore o problema antes de sugerir tratamento",
            4: "Mencione benefícios da solução e crie urgência gentilmente",
            5: "Confirme claramente o agendamento com data e hora",
            6: "Seja caloroso no encerramento e reforce o compromisso"
        }

        return tips.get(step, "")

    def _find_similar_patterns(self, current_pattern: Dict) -> List[Dict[str, Any]]:
        """Encontra padrões similares ao atual."""
        similar = []

        for key, data in self.patterns["pattern_frequency"].items():
            if key == current_pattern["pattern_hash"]:
                continue

            # Calcula similaridade
            similarity = 0.0

            # Mesmo step (muito importante)
            if data.get("step") == current_pattern.get("step"):
                similarity += 0.4

            # Mesmo tipo de contexto
            if data.get("context_type") == current_pattern.get("context_type"):
                similarity += 0.3

            # Mesmo tipo de resposta do usuário
            if data.get("user_response_type") == current_pattern.get("user_response_type"):
                similarity += 0.2

            # Mesma situação
            if data.get("situation") == current_pattern.get("situation"):
                similarity += 0.1

            if similarity > 0.5 and data.get("successful_responses"):
                similar.append({
                    "key": key,
                    "similarity": similarity,
                    "success_rate": len(data["successful_responses"]) / data["count"] if data["count"] > 0 else 0
                })

        # Ordena por similaridade e taxa de sucesso
        similar.sort(key=lambda x: (x["similarity"], x["success_rate"]), reverse=True)

        return similar[:3]  # Top 3

    def _find_failed_patterns_to_avoid(self, current_pattern: Dict) -> List[Dict[str, Any]]:
        """Encontra padrões de falha relevantes."""
        failed = []

        for key, data in self.patterns["pattern_frequency"].items():
            # Só considera se tem mais falhas que sucessos
            if len(data.get("failed_responses", [])) > len(data.get("successful_responses", [])):
                # Verifica relevância
                if (data.get("step") == current_pattern.get("step") or
                    data.get("context_type") == current_pattern.get("context_type")):

                    failed.append({
                        "key": key,
                        "failure_rate": len(data["failed_responses"]) / data["count"] if data["count"] > 0 else 1
                    })

        # Ordena por taxa de falha
        failed.sort(key=lambda x: x["failure_rate"], reverse=True)

        return failed[:5]  # Top 5 falhas

    def _update_step_statistics(self, step: int, success: bool):
        """Atualiza estatísticas específicas do step."""
        step_key = str(step)

        if step_key not in self.statistics["performance_by_step"]:
            self.statistics["performance_by_step"][step_key] = {
                "total": 0,
                "successful": 0,
                "failed": 0
            }

        self.statistics["performance_by_step"][step_key]["total"] += 1

        if success:
            self.statistics["performance_by_step"][step_key]["successful"] += 1
        else:
            self.statistics["performance_by_step"][step_key]["failed"] += 1

    def _update_statistics(self):
        """Atualiza estatísticas gerais."""
        total_patterns = len(self.patterns["pattern_frequency"])
        total_responses = sum(len(p["successful_responses"]) + len(p["failed_responses"])
                            for p in self.patterns["pattern_frequency"].values())

        successful_responses = sum(len(p["successful_responses"])
                                 for p in self.patterns["pattern_frequency"].values())

        self.statistics["total_conversations"] = total_responses
        self.statistics["patterns_learned"] = total_patterns
        self.statistics["success_rate"] = successful_responses / total_responses if total_responses > 0 else 0
        self.statistics["last_update"] = datetime.now().isoformat()

        self._save_statistics()

    def _save_patterns(self):
        """Salva padrões aprendidos."""
        patterns_file = f"{self.base_path}/learned_patterns_v2.json"
        with open(patterns_file, 'w', encoding='utf-8') as f:
            json.dump(self.patterns, f, ensure_ascii=False, indent=2)

    def _save_statistics(self):
        """Salva estatísticas."""
        stats_file = f"{self.base_path}/statistics_v2.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(self.statistics, f, ensure_ascii=False, indent=2)

    def get_company_specific_report(self) -> Dict[str, Any]:
        """Gera relatório detalhado para a empresa."""
        report = {
            "company_id": self.company_id,
            "statistics": self.statistics,
            "most_common_patterns": [],
            "performance_by_step": {},
            "recommendations": [],
            "top_failures": []
        }

        # Padrões mais comuns
        sorted_patterns = sorted(self.patterns["pattern_frequency"].items(),
                               key=lambda x: x[1]["count"], reverse=True)[:10]

        for pattern_key, data in sorted_patterns:
            success_rate = len(data["successful_responses"]) / data["count"] if data["count"] > 0 else 0
            report["most_common_patterns"].append({
                "step": data.get("step_name", "unknown"),
                "context": data["context_type"],
                "user_response": data["user_response_type"],
                "situation": data.get("situation", "unknown"),
                "occurrences": data["count"],
                "success_rate": f"{success_rate:.1%}",
                "has_few_shot": data.get("is_few_shot", False)
            })

        # Performance por step
        for step, stats in self.statistics.get("performance_by_step", {}).items():
            total = stats["total"]
            if total > 0:
                report["performance_by_step"][STEP_NAMES.get(int(step), f"step_{step}")] = {
                    "total_interactions": total,
                    "success_rate": f"{stats['successful'] / total:.1%}",
                    "failure_rate": f"{stats['failed'] / total:.1%}"
                }

        # Top falhas
        all_failures = []
        for pattern_key, data in self.patterns["pattern_frequency"].items():
            if data["failed_responses"]:
                failure_rate = len(data["failed_responses"]) / data["count"] if data["count"] > 0 else 0
                if failure_rate > 0.3:  # Mais de 30% de falha
                    all_failures.append({
                        "step": data.get("step_name", "unknown"),
                        "context": data["context_type"],
                        "failure_rate": f"{failure_rate:.1%}",
                        "common_errors": self._extract_common_failures(data["failed_responses"])[:3]
                    })

        report["top_failures"] = sorted(all_failures,
                                      key=lambda x: float(x["failure_rate"].strip('%')) / 100,
                                      reverse=True)[:5]

        # Recomendações automáticas
        self._generate_recommendations(report)

        return report

    def _generate_recommendations(self, report: Dict):
        """Gera recomendações baseadas nos dados."""
        recommendations = []

        # Analisa performance por step
        for step_name, stats in report["performance_by_step"].items():
            success_rate = float(stats["success_rate"].strip('%')) / 100

            if success_rate < 0.7:
                if step_name == "confirmacao_agendamento":
                    recommendations.append(
                        f"⚠️ Taxa de sucesso baixa em confirmação ({stats['success_rate']}). "
                        "Revisar few-shots de confirmação e validar se está pedindo informações já fornecidas."
                    )
                elif step_name == "exploracao_problema":
                    recommendations.append(
                        f"⚠️ Dificuldade em exploração ({stats['success_rate']}). "
                        "Adicionar mais exemplos de perguntas exploratórias nos few-shots."
                    )

        # Analisa falhas comuns
        for failure in report["top_failures"][:3]:
            if "pedir nome quando já tem" in failure["common_errors"]:
                recommendations.append(
                    "🔴 Bot está pedindo informações já fornecidas. "
                    "Revisar lógica de memória e extração de dados."
                )
            elif "resposta que falhou na validação" in failure["common_errors"]:
                recommendations.append(
                    "🔴 Muitas respostas falhando na validação. "
                    "Verificar integração com sistema de validação."
                )

        # Sugestões gerais
        if report["statistics"]["total_conversations"] < 50:
            recommendations.append(
                "💡 Ainda em fase inicial de aprendizado. "
                f"Apenas {report['statistics']['total_conversations']} interações analisadas."
            )

        if report["statistics"]["success_rate"] > 0.8:
            recommendations.append(
                f"✅ Excelente performance geral! Taxa de sucesso: {report['statistics']['success_rate']:.1%}"
            )

        report["recommendations"] = recommendations


# Função auxiliar para integração simples
def create_learner_for_company(company_id: int) -> EnhancedContextPatternLearner:
    """Cria uma instância do learner para uma empresa específica."""
    return EnhancedContextPatternLearner(company_id)
