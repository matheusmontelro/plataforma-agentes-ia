# Sistema Universal de Aprendizado de Contexto
import os
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
import hashlib
from collections import defaultdict
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.schema import Document
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from backend.runtime_settings import ADAPTIVE_PATTERNS_DIR
import re

logger = logging.getLogger(__name__)

class UniversalContextPattern:
    """
    Representa um padrão universal de conversa, independente do domínio.
    """
    def __init__(self):
        self.pattern_id = None
        self.context_before = []  # Mensagens antes do ponto crítico
        self.trigger_message = None  # Mensagem que mudou o contexto
        self.response_type = None  # Como o assistente respondeu
        self.user_reaction = None  # Como o usuário reagiu
        self.success_indicators = []  # Indicadores de sucesso
        self.failure_indicators = []  # Indicadores de falha
        self.metadata = {}

class UniversalPatternDetector:
    """
    Detecta padrões universais em conversas, independente do contexto específico.
    """

    def __init__(self):
        # Indicadores universais de mudança de contexto
        self.context_shift_indicators = {
            "intervention": ["OPER:", "[Operador]", "[Manual]", "[Humano]"],
            "confirmation": ["confirmad", "agendad", "marcad", "ok", "perfeito", "ótimo"],
            "correction": ["não é isso", "errado", "na verdade", "correção", "retificando"],
            "new_info": ["acabei de", "descobri que", "mudou", "alterou", "novo"],
            "clarification": ["quero dizer", "ou seja", "explicando melhor", "na real"],
            "emotional_shift": ["desculp", "obrigad", "que bom", "que pena", "nossa"],
            "topic_change": ["mudando de assunto", "outra coisa", "aliás", "aproveitando"],
            "urgency": ["urgente", "rápido", "agora", "imediato", "pressa"],
            "conclusion": ["então tá", "fechado", "combinado", "resolvido", "pronto"]
        }

        # Padrões de resposta inadequada
        self.inadequate_response_patterns = [
            r"como posso (te |lhe )?ajudar",  # Pergunta genérica após contexto específico
            r"qual seu nome",  # Perguntando algo já informado
            r"gostaria de agendar",  # Oferecendo algo já confirmado
            r"em que posso",  # Resposta genérica de início
            r"bom dia|boa tarde|boa noite",  # Saudação fora de hora
        ]

    def detect_context_shift(self, messages: List[BaseMessage]) -> List[Dict[str, Any]]:
        """
        Detecta mudanças de contexto em uma conversa.
        Retorna lista de momentos onde o contexto mudou significativamente.
        """
        context_shifts = []

        for i in range(1, len(messages)):
            current_msg = messages[i]
            previous_msg = messages[i-1] if i > 0 else None

            # Analisa cada tipo de mudança de contexto
            for shift_type, indicators in self.context_shift_indicators.items():
                if self._contains_indicators(current_msg.content, indicators):
                    shift = {
                        "position": i,
                        "type": shift_type,
                        "message": current_msg.content,
                        "is_ai": isinstance(current_msg, AIMessage),
                        "context_before": self._get_context_window(messages, i, before=3),
                        "context_after": self._get_context_window(messages, i, after=3)
                    }

                    # Verifica se a próxima resposta foi adequada
                    if i + 1 < len(messages):
                        next_msg = messages[i + 1]
                        shift["response_adequate"] = self._check_response_adequacy(
                            current_msg, next_msg, shift_type
                        )

                    context_shifts.append(shift)
                    break

        return context_shifts

    def _contains_indicators(self, text: str, indicators: List[str]) -> bool:
        """Verifica se o texto contém algum dos indicadores."""
        text_lower = text.lower()
        return any(indicator.lower() in text_lower for indicator in indicators)

    def _get_context_window(self, messages: List[BaseMessage], position: int,
                           before: int = 0, after: int = 0) -> List[str]:
        """Obtém janela de contexto ao redor de uma posição."""
        start = max(0, position - before)
        end = min(len(messages), position + after + 1)

        window = []
        for i in range(start, end):
            if i != position:  # Não inclui a mensagem atual
                role = "Human" if isinstance(messages[i], HumanMessage) else "AI"
                window.append(f"{role}: {messages[i].content[:100]}")

        return window

    def _check_response_adequacy(self, trigger_msg: BaseMessage,
                                response_msg: BaseMessage,
                                shift_type: str) -> bool:
        """
        Verifica se a resposta foi adequada ao contexto.
        """
        response_lower = response_msg.content.lower()

        # Verifica padrões de resposta inadequada
        for pattern in self.inadequate_response_patterns:
            if re.search(pattern, response_lower):
                return False

        # Regras específicas por tipo de mudança
        if shift_type == "confirmation":
            # Resposta adequada não deve perguntar sobre o que foi confirmado
            if any(word in response_lower for word in ["agendar", "marcar", "horário disponível"]):
                return False

        elif shift_type == "correction":
            # Resposta deve reconhecer a correção
            if not any(word in response_lower for word in ["entendi", "compreendo", "desculpe"]):
                return False

        elif shift_type == "new_info":
            # Resposta deve mostrar que processou a nova informação
            if len(response_msg.content) < 20:  # Resposta muito curta
                return False

        return True

    def extract_universal_patterns(self, messages: List[BaseMessage]) -> List[UniversalContextPattern]:
        """
        Extrai padrões universais de uma conversa.
        """
        patterns = []
        context_shifts = self.detect_context_shift(messages)

        for shift in context_shifts:
            pattern = UniversalContextPattern()
            pattern.pattern_id = self._generate_pattern_id(shift)
            pattern.context_before = shift["context_before"]
            pattern.trigger_message = shift["message"]
            pattern.response_type = "adequate" if shift.get("response_adequate", True) else "inadequate"

            # Analisa reação do usuário (se houver)
            if shift["position"] + 2 < len(messages):
                user_reaction_msg = messages[shift["position"] + 2]
                if isinstance(user_reaction_msg, HumanMessage):
                    pattern.user_reaction = self._classify_user_reaction(user_reaction_msg.content)

            # Metadados
            pattern.metadata = {
                "shift_type": shift["type"],
                "position": shift["position"],
                "timestamp": datetime.now().isoformat()
            }

            patterns.append(pattern)

        return patterns

    def _generate_pattern_id(self, shift: Dict) -> str:
        """Gera ID único para um padrão."""
        content = f"{shift['type']}_{shift['message'][:50]}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _classify_user_reaction(self, reaction: str) -> str:
        """Classifica a reação do usuário."""
        reaction_lower = reaction.lower()

        if any(word in reaction_lower for word in ["obrigad", "perfeito", "ótimo", "valeu"]):
            return "positive"
        elif any(word in reaction_lower for word in ["não", "errado", "mas", "?"]):
            return "questioning"
        elif len(reaction) < 10:
            return "brief"
        else:
            return "neutral"


class AdaptiveContextLearner:
    """
    Sistema adaptativo que aprende qualquer tipo de padrão contextual.
    """

    def __init__(self, company_id: int):
        self.company_id = company_id
        self.embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
        self.pattern_detector = UniversalPatternDetector()

        # Paths
        self.base_path = str(ADAPTIVE_PATTERNS_DIR / f"company_{company_id}")
        Path(self.base_path).mkdir(parents=True, exist_ok=True)

        # Armazenamentos
        self.pattern_stats = self._load_pattern_stats()
        self.vectorstore = self._load_or_create_vectorstore()

    def _load_pattern_stats(self) -> Dict[str, Any]:
        """Carrega estatísticas de padrões."""
        stats_file = f"{self.base_path}/pattern_stats.json"
        if os.path.exists(stats_file):
            with open(stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "patterns_by_type": defaultdict(int),
            "success_rate_by_pattern": defaultdict(lambda: {"success": 0, "total": 0}),
            "common_mistakes": defaultdict(int)
        }

    def _load_or_create_vectorstore(self) -> FAISS:
        """Carrega ou cria vectorstore."""
        vs_path = f"{self.base_path}/universal_vectorstore"
        try:
            if os.path.exists(f"{vs_path}/index.faiss"):
                return FAISS.load_local(vs_path, self.embeddings)
        except:
            pass
        return FAISS.from_texts(["início"], self.embeddings)

    def learn_from_any_conversation(self, messages: List[BaseMessage], metadata: Dict = None):
        """
        Aprende de qualquer conversa, identificando padrões universais.
        """
        # Detecta padrões
        patterns = self.pattern_detector.extract_universal_patterns(messages)

        for pattern in patterns:
            # Cria documento para o vectorstore
            pattern_text = self._serialize_pattern(pattern)

            doc = Document(
                page_content=pattern_text,
                metadata={
                    "pattern_id": pattern.pattern_id,
                    "pattern_type": pattern.metadata["shift_type"],
                    "response_adequate": pattern.response_type == "adequate",
                    "user_reaction": pattern.user_reaction or "unknown",
                    "company_id": self.company_id,
                    **pattern.metadata
                }
            )

            # Adiciona ao vectorstore
            self.vectorstore.add_documents([doc])

            # Atualiza estatísticas
            self._update_statistics(pattern)

            logger.info(f"Aprendido padrão universal: {pattern.metadata['shift_type']}")

        # Salva
        self._save_data()

    def _serialize_pattern(self, pattern: UniversalContextPattern) -> str:
        """Serializa padrão para busca."""
        return f"""
TIPO: {pattern.metadata['shift_type']}
GATILHO: {pattern.trigger_message}
CONTEXTO_ANTES: {' | '.join(pattern.context_before[-2:])}
RESPOSTA_FOI: {pattern.response_type}
REAÇÃO_USUÁRIO: {pattern.user_reaction}
"""

    def _update_statistics(self, pattern: UniversalContextPattern):
        """Atualiza estatísticas de padrões."""
        ptype = pattern.metadata["shift_type"]

        # Conta tipo de padrão
        self.pattern_stats["patterns_by_type"][ptype] += 1

        # Taxa de sucesso
        stats = self.pattern_stats["success_rate_by_pattern"][ptype]
        stats["total"] += 1
        if pattern.response_type == "adequate" and pattern.user_reaction in ["positive", "neutral"]:
            stats["success"] += 1

        # Erros comuns
        if pattern.response_type == "inadequate":
            error_key = f"{ptype}_inadequate_response"
            self.pattern_stats["common_mistakes"][error_key] += 1

    def _save_data(self):
        """Salva dados atualizados."""
        # Salva vectorstore
        vs_path = f"{self.base_path}/universal_vectorstore"
        self.vectorstore.save_local(vs_path)

        # Salva estatísticas
        stats_file = f"{self.base_path}/pattern_stats.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            # Converte defaultdict para dict normal
            stats_to_save = {
                "patterns_by_type": dict(self.pattern_stats["patterns_by_type"]),
                "success_rate_by_pattern": dict(self.pattern_stats["success_rate_by_pattern"]),
                "common_mistakes": dict(self.pattern_stats["common_mistakes"]),
                "last_updated": datetime.now().isoformat()
            }
            json.dump(stats_to_save, f, ensure_ascii=False, indent=2)

    def get_context_recommendations(self, current_messages: List[BaseMessage],
                                   next_user_input: str) -> Dict[str, Any]:
        """
        Obtém recomendações baseadas em padrões aprendidos.
        """
        # Detecta se há mudança de contexto
        temp_messages = current_messages + [HumanMessage(content=next_user_input)]
        current_shifts = self.pattern_detector.detect_context_shift(temp_messages)

        recommendations = {
            "detected_shifts": [],
            "similar_successful_patterns": [],
            "avoid_responses": [],
            "suggested_approach": "standard"
        }

        if current_shifts:
            latest_shift = current_shifts[-1]
            recommendations["detected_shifts"].append({
                "type": latest_shift["type"],
                "confidence": 0.8  # Pode ser calculado com base em indicadores
            })

            # Busca padrões similares bem-sucedidos
            search_query = f"TIPO: {latest_shift['type']} GATILHO: {latest_shift['message']}"
            similar_docs = self.vectorstore.similarity_search(search_query, k=5)

            for doc in similar_docs:
                if doc.metadata.get("response_adequate") and doc.metadata.get("user_reaction") in ["positive", "neutral"]:
                    recommendations["similar_successful_patterns"].append({
                        "pattern": doc.page_content,
                        "metadata": doc.metadata
                    })

            # Sugere abordagem baseada no tipo
            recommendations["suggested_approach"] = self._suggest_approach(latest_shift["type"])

            # Lista respostas a evitar
            recommendations["avoid_responses"] = self._get_responses_to_avoid(latest_shift["type"])

        return recommendations

    def _suggest_approach(self, shift_type: str) -> str:
        """Sugere abordagem baseada no tipo de mudança."""
        approaches = {
            "intervention": "acknowledge_and_adapt",
            "confirmation": "confirm_and_move_forward",
            "correction": "apologize_and_correct",
            "new_info": "process_and_confirm",
            "clarification": "understand_and_respond",
            "emotional_shift": "empathize_and_continue",
            "topic_change": "acknowledge_and_switch",
            "urgency": "prioritize_and_act",
            "conclusion": "wrap_up_gracefully"
        }
        return approaches.get(shift_type, "standard")

    def _get_responses_to_avoid(self, shift_type: str) -> List[str]:
        """Retorna tipos de resposta a evitar."""
        avoid_map = {
            "confirmation": ["asking_again", "offering_confirmed_service"],
            "correction": ["ignoring_correction", "repeating_error"],
            "new_info": ["generic_response", "not_acknowledging"],
            "urgency": ["slow_response", "asking_too_many_questions"]
        }
        return avoid_map.get(shift_type, [])

    def get_learning_insights(self) -> Dict[str, Any]:
        """Retorna insights sobre o aprendizado."""
        insights = {
            "total_patterns_learned": sum(self.pattern_stats["patterns_by_type"].values()),
            "pattern_distribution": dict(self.pattern_stats["patterns_by_type"]),
            "success_rates": {},
            "most_common_mistakes": [],
            "recommendations": []
        }

        # Calcula taxas de sucesso
        for ptype, stats in self.pattern_stats["success_rate_by_pattern"].items():
            if stats["total"] > 0:
                rate = stats["success"] / stats["total"]
                insights["success_rates"][ptype] = f"{rate:.2%}"

        # Erros mais comuns
        mistakes = sorted(self.pattern_stats["common_mistakes"].items(),
                         key=lambda x: x[1], reverse=True)[:5]
        insights["most_common_mistakes"] = mistakes

        # Recomendações
        if insights["total_patterns_learned"] < 100:
            insights["recommendations"].append("Precisa de mais dados para melhor aprendizado")

        for ptype, rate in insights["success_rates"].items():
            if float(rate.strip('%')) < 70:
                insights["recommendations"].append(f"Melhorar respostas para '{ptype}'")

        return insights
