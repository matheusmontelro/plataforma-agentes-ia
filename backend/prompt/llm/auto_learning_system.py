# Sistema de Aprendizado Automático para Contexto
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
from backend.runtime_settings import AUTO_LEARNING_DIR

logger = logging.getLogger(__name__)

class ContextPatternLearner:
    """
    Sistema que aprende padrões de conversa automaticamente.
    """

    def __init__(self, company_id: int):
        self.company_id = company_id
        self.base_path = str(AUTO_LEARNING_DIR / f"company_{company_id}")
        Path(self.base_path).mkdir(parents=True, exist_ok=True)

        # Carrega padrões existentes
        self.patterns = self._load_patterns()
        self.statistics = self._load_statistics()

    def _load_patterns(self) -> Dict[str, Any]:
        """Carrega padrões aprendidos do arquivo."""
        patterns_file = f"{self.base_path}/learned_patterns.json"
        if os.path.exists(patterns_file):
            with open(patterns_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "successful_responses": {},
            "failed_responses": {},
            "pattern_frequency": {}
        }

    def _load_statistics(self) -> Dict[str, Any]:
        """Carrega estatísticas de aprendizado."""
        stats_file = f"{self.base_path}/statistics.json"
        if os.path.exists(stats_file):
            with open(stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "total_conversations": 0,
            "patterns_learned": 0,
            "success_rate": 0.0,
            "last_update": None
        }

    def detect_conversation_pattern(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        """
        Detecta o padrão da conversa atual.
        """
        pattern = {
            "has_oper_intervention": False,
            "user_response_type": None,
            "llm_response_quality": None,
            "pattern_hash": None,
            "context_type": None
        }

        # Analisa mensagens recentes
        for i in range(len(messages) - 3, len(messages)):
            if i < 0:
                continue

            msg = messages[i]

            # Detecta intervenção OPER
            if isinstance(msg, AIMessage) and '[operador]' in msg.content.lower():
                pattern["has_oper_intervention"] = True
                pattern["context_type"] = self._classify_oper_message(msg.content)

            # Analisa resposta do usuário
            elif isinstance(msg, HumanMessage) and pattern["has_oper_intervention"]:
                pattern["user_response_type"] = self._classify_user_response(msg.content)

        # Gera hash único para este padrão
        pattern_key = f"{pattern['context_type']}_{pattern['user_response_type']}"
        pattern["pattern_hash"] = hashlib.md5(pattern_key.encode()).hexdigest()[:8]

        return pattern

    def _classify_oper_message(self, content: str) -> str:
        """Classifica o tipo de mensagem do operador."""
        content_lower = content.lower()

        if any(word in content_lower for word in ['horário', 'hora', 'hrs', 'consulta', 'agendamento']):
            return "scheduling"
        elif any(word in content_lower for word in ['dr', 'dra', 'doutor', 'doutora']):
            return "professional_info"
        elif any(word in content_lower for word in ['valor', 'preço', 'pagamento', 'custo']):
            return "financial"
        elif any(word in content_lower for word in ['endereço', 'localização', 'como chegar']):
            return "location"
        else:
            return "general_info"

    def _classify_user_response(self, content: str) -> str:
        """Classifica o tipo de resposta do usuário."""
        content_lower = content.lower()

        positive_words = ['sim', 'ok', 'pode', 'combinado', 'certo', 'beleza', 'confirmo']
        negative_words = ['não', 'nao', 'negativo', 'cancela', 'desisto']
        question_words = ['?', 'como', 'quando', 'onde', 'qual']

        if any(word in content_lower for word in positive_words):
            return "positive_confirmation"
        elif any(word in content_lower for word in negative_words):
            return "negative_response"
        elif any(word in content_lower for word in question_words):
            return "question"
        else:
            return "neutral"

    def learn_from_conversation(self, messages: List[BaseMessage], llm_response: str, user_reaction: Optional[str] = None):
        """
        Aprende com uma conversa completa.
        """
        # Detecta o padrão
        pattern = self.detect_conversation_pattern(messages)

        if not pattern["pattern_hash"]:
            return

        # Avalia qualidade da resposta do LLM
        response_quality = self._evaluate_response_quality(llm_response, pattern, user_reaction)

        # Atualiza padrões aprendidos
        pattern_key = pattern["pattern_hash"]

        if pattern_key not in self.patterns["pattern_frequency"]:
            self.patterns["pattern_frequency"][pattern_key] = {
                "count": 0,
                "context_type": pattern["context_type"],
                "user_response_type": pattern["user_response_type"],
                "successful_responses": [],
                "failed_responses": []
            }

        self.patterns["pattern_frequency"][pattern_key]["count"] += 1

        # Armazena resposta como sucesso ou falha
        response_data = {
            "response": llm_response[:200],  # Primeiros 200 chars
            "timestamp": datetime.now().isoformat(),
            "quality_score": response_quality
        }

        if response_quality > 0.7:  # Threshold de qualidade
            self.patterns["pattern_frequency"][pattern_key]["successful_responses"].append(response_data)
        else:
            self.patterns["pattern_frequency"][pattern_key]["failed_responses"].append(response_data)

        # Atualiza estatísticas
        self._update_statistics()

        # Salva aprendizado
        self._save_patterns()

        logger.info(f"[AutoLearning] Padrão aprendido: {pattern_key} - Qualidade: {response_quality}")

    def _evaluate_response_quality(self, llm_response: str, pattern: Dict, user_reaction: Optional[str]) -> float:
        """
        Avalia a qualidade da resposta do LLM (0.0 a 1.0).
        """
        quality_score = 0.5  # Base
        response_lower = llm_response.lower()

        # Penaliza respostas genéricas após intervenção OPER
        if pattern["has_oper_intervention"]:
            generic_phrases = ['como posso ajudar', 'qual seu nome', 'gostaria de agendar',
                             'me chamo', 'sou a consultora']

            for phrase in generic_phrases:
                if phrase in response_lower:
                    quality_score -= 0.2

        # Bonifica respostas contextualizadas
        if pattern["context_type"] == "scheduling" and pattern["user_response_type"] == "positive_confirmation":
            if any(word in response_lower for word in ['confirmado', 'aguardo', 'agendado']):
                quality_score += 0.3
            if 'nome completo' in response_lower:  # Pedindo nome após confirmação
                quality_score -= 0.4

        # Considera reação do usuário se disponível
        if user_reaction:
            reaction_lower = user_reaction.lower()
            if any(word in reaction_lower for word in ['obrigado', 'perfeito', 'ótimo']):
                quality_score += 0.2
            elif any(word in reaction_lower for word in ['não', 'errado', 'já disse']):
                quality_score -= 0.3

        # Limita entre 0 e 1
        return max(0.0, min(1.0, quality_score))

    def get_best_approach(self, current_pattern: Dict) -> Optional[Dict[str, Any]]:
        """
        Retorna a melhor abordagem aprendida para um padrão.
        """
        pattern_key = current_pattern["pattern_hash"]

        if pattern_key not in self.patterns["pattern_frequency"]:
            return None

        pattern_data = self.patterns["pattern_frequency"][pattern_key]

        # Se temos respostas bem-sucedidas
        if pattern_data["successful_responses"]:
            # Ordena por qualidade
            successful = sorted(pattern_data["successful_responses"],
                              key=lambda x: x["quality_score"], reverse=True)

            return {
                "approach": "use_successful_pattern",
                "example_response": successful[0]["response"],
                "confidence": successful[0]["quality_score"],
                "avoid_phrases": self._extract_failed_phrases(pattern_data["failed_responses"])
            }

        # Se só temos falhas, pelo menos sabemos o que evitar
        elif pattern_data["failed_responses"]:
            return {
                "approach": "avoid_known_failures",
                "avoid_phrases": self._extract_failed_phrases(pattern_data["failed_responses"]),
                "confidence": 0.3
            }

        return None

    def _extract_failed_phrases(self, failed_responses: List[Dict]) -> List[str]:
        """Extrai frases comuns de respostas que falharam."""
        common_phrases = []

        for response_data in failed_responses:
            response = response_data["response"].lower()
            # Extrai frases problemáticas comuns
            if "nome completo" in response:
                common_phrases.append("pedir nome completo")
            if "como posso ajudar" in response:
                common_phrases.append("pergunta genérica")
            if "gostaria de agendar" in response:
                common_phrases.append("oferecer agendamento")

        return list(set(common_phrases))  # Remove duplicatas

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
        patterns_file = f"{self.base_path}/learned_patterns.json"
        with open(patterns_file, 'w', encoding='utf-8') as f:
            json.dump(self.patterns, f, ensure_ascii=False, indent=2)

    def _save_statistics(self):
        """Salva estatísticas."""
        stats_file = f"{self.base_path}/statistics.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(self.statistics, f, ensure_ascii=False, indent=2)

    def get_learning_report(self) -> Dict[str, Any]:
        """Retorna relatório de aprendizado."""
        report = {
            "company_id": self.company_id,
            "statistics": self.statistics,
            "most_common_patterns": [],
            "improvement_suggestions": []
        }

        # Padrões mais comuns
        sorted_patterns = sorted(self.patterns["pattern_frequency"].items(),
                               key=lambda x: x[1]["count"], reverse=True)[:5]

        for pattern_key, data in sorted_patterns:
            success_rate = len(data["successful_responses"]) / data["count"] if data["count"] > 0 else 0
            report["most_common_patterns"].append({
                "context": data["context_type"],
                "user_response": data["user_response_type"],
                "occurrences": data["count"],
                "success_rate": f"{success_rate:.1%}"
            })

        # Sugestões de melhoria
        for pattern_key, data in self.patterns["pattern_frequency"].items():
            if data["failed_responses"] and len(data["failed_responses"]) > len(data["successful_responses"]):
                report["improvement_suggestions"].append(
                    f"Melhorar respostas para: {data['context_type']} + {data['user_response_type']}"
                )

        return report


# Integração com o sistema atual
def integrate_auto_learning(db: Session, company_id: int, contact_phone: str,
                          messages: List[BaseMessage], llm_response: str,
                          user_input: str) -> Optional[str]:
    """
    Integra o aprendizado automático ao fluxo atual.
    Retorna instruções adicionais para o prompt se houver padrões aprendidos.
    """
    try:
        learner = ContextPatternLearner(company_id)

        # Detecta padrão atual
        current_pattern = learner.detect_conversation_pattern(messages + [HumanMessage(content=user_input)])

        # Busca melhor abordagem aprendida
        best_approach = learner.get_best_approach(current_pattern)

        if best_approach and best_approach["confidence"] > 0.6:
            instructions = f"\n[APRENDIZADO AUTOMÁTICO - Confiança: {best_approach['confidence']:.0%}]\n"

            if best_approach["approach"] == "use_successful_pattern":
                instructions += f"Exemplo de resposta bem-sucedida similar: {best_approach['example_response']}\n"

            if best_approach["avoid_phrases"]:
                instructions += f"EVITE: {', '.join(best_approach['avoid_phrases'])}\n"

            logger.info(f"[AutoLearning] Aplicando aprendizado: {current_pattern['pattern_hash']}")
            return instructions

        # Aprende com a interação atual (assíncrono)
        # Nota: Em produção, isso seria feito em background
        if llm_response:
            learner.learn_from_conversation(messages, llm_response, user_input)

    except Exception as e:
        logger.error(f"[AutoLearning] Erro: {e}")

    return None
