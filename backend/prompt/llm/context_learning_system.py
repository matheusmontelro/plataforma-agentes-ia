# Sistema de Aprendizado Contextual para o Chat
import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.schema import Document
from langchain.prompts.example_selector import SemanticSimilarityExampleSelector
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from backend.runtime_settings import PATTERNS_DIR
import re

logger = logging.getLogger(__name__)

class ConversationPatternLearner:
    """
    Sistema que aprende padrões de conversação a partir do histórico
    e melhora as respostas do LLM com o tempo.
    """

    def __init__(self, company_id: int, embeddings_model: str = "text-embedding-ada-002"):
        self.company_id = company_id
        self.embeddings = OpenAIEmbeddings(model=embeddings_model)
        self.patterns_db_path = str(PATTERNS_DIR / f"company_{company_id}")
        self.vectorstore_path = f"{self.patterns_db_path}/vectorstore"

        # Criar diretórios se não existirem
        Path(self.patterns_db_path).mkdir(parents=True, exist_ok=True)

        # Carregar ou criar vectorstore
        self.vectorstore = self._load_or_create_vectorstore()

        # Padrões conhecidos
        self.known_patterns = self._load_known_patterns()

    def _load_or_create_vectorstore(self) -> FAISS:
        """Carrega vectorstore existente ou cria um novo."""
        try:
            if os.path.exists(f"{self.vectorstore_path}/index.faiss"):
                return FAISS.load_local(self.vectorstore_path, self.embeddings)
            else:
                # Criar vectorstore vazio
                return FAISS.from_texts(["início"], self.embeddings)
        except Exception as e:
            logger.error(f"Erro ao carregar vectorstore: {e}")
            return FAISS.from_texts(["início"], self.embeddings)

    def _load_known_patterns(self) -> Dict[str, Any]:
        """Carrega padrões conhecidos do arquivo."""
        patterns_file = f"{self.patterns_db_path}/patterns.json"
        if os.path.exists(patterns_file):
            with open(patterns_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            # Padrões iniciais básicos
            return {
                "confirmacao_manual": {
                    "triggers": ["confirmad", "agendad", "marcad", "às", "amanhã", "hoje"],
                    "examples": [],
                    "response_patterns": ["Perfeito!", "Ótimo!", "Confirmado!"]
                },
                "reagendamento": {
                    "triggers": ["reagend", "remarc", "mudar", "trocar horário"],
                    "examples": [],
                    "response_patterns": ["Claro!", "Sem problemas!", "Vamos reagendar"]
                }
            }

    def extract_conversation_pattern(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        """
        Extrai padrões importantes de uma conversa.
        """
        pattern = {
            "has_oper_intervention": False,
            "oper_message": None,
            "confirmation_present": False,
            "appointment_details": {},
            "conversation_flow": [],
            "successful_outcome": False
        }

        for i, msg in enumerate(messages):
            # Detecta intervenção OPER
            if isinstance(msg, AIMessage) and msg.content.startswith("[Operador]"):
                pattern["has_oper_intervention"] = True
                pattern["oper_message"] = msg.content

                # Extrai detalhes do agendamento
                details = self._extract_appointment_details(msg.content)
                if details:
                    pattern["appointment_details"] = details
                    pattern["confirmation_present"] = True

            # Rastreia o fluxo
            msg_type = "human" if isinstance(msg, HumanMessage) else "ai"
            pattern["conversation_flow"].append({
                "type": msg_type,
                "position": i,
                "has_confirmation": any(word in msg.content.lower()
                                      for word in ["confirmad", "agendad", "marcad"])
            })

        # Determina se foi bem-sucedido
        pattern["successful_outcome"] = self._check_successful_outcome(messages)

        return pattern

    def _extract_appointment_details(self, text: str) -> Optional[Dict[str, str]]:
        """Extrai detalhes de agendamento do texto."""
        details = {}

        # Busca horários
        time_pattern = r'\b(\d{1,2})[h:](\d{2})?\b'
        time_match = re.search(time_pattern, text)
        if time_match:
            details["time"] = time_match.group(0)

        # Busca datas
        date_keywords = ["hoje", "amanhã", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        for keyword in date_keywords:
            if keyword in text.lower():
                details["date_reference"] = keyword
                break

        # Busca nome do profissional
        dr_pattern = r'(Dr\.?|Dra\.?)\s+(\w+)'
        dr_match = re.search(dr_pattern, text, re.IGNORECASE)
        if dr_match:
            details["professional"] = dr_match.group(0)

        return details if details else None

    def _check_successful_outcome(self, messages: List[BaseMessage]) -> bool:
        """Verifica se a conversa teve um resultado bem-sucedido."""
        if len(messages) < 2:
            return False

        # Verifica se última mensagem humana é positiva
        last_human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
        if last_human_msgs:
            last_human = last_human_msgs[-1].content.lower()
            positive_indicators = ["obrigad", "perfeito", "ótimo", "ok", "sim", "confirma", "certinho"]
            return any(indicator in last_human for indicator in positive_indicators)

        return False

    def learn_from_conversation(self, messages: List[BaseMessage], contact_phone: str):
        """
        Aprende com uma conversa e adiciona aos exemplos se for bem-sucedida.
        """
        pattern = self.extract_conversation_pattern(messages)

        if pattern["successful_outcome"] and pattern["has_oper_intervention"]:
            # Criar documento para o vectorstore
            conversation_text = self._format_conversation_for_learning(messages, pattern)

            doc = Document(
                page_content=conversation_text,
                metadata={
                    "pattern_type": "oper_confirmation",
                    "contact_phone": contact_phone,
                    "timestamp": datetime.now().isoformat(),
                    "appointment_details": json.dumps(pattern["appointment_details"])
                }
            )

            # Adicionar ao vectorstore
            self.vectorstore.add_documents([doc])

            # Salvar vectorstore
            self.vectorstore.save_local(self.vectorstore_path)

            # Atualizar padrões conhecidos
            self._update_known_patterns(pattern)

            logger.info(f"Aprendido novo padrão de conversa bem-sucedida para {contact_phone}")

    def _format_conversation_for_learning(self, messages: List[BaseMessage], pattern: Dict) -> str:
        """Formata conversa para armazenamento e busca."""
        formatted = f"PADRÃO: Confirmação com intervenção manual\n"
        formatted += f"DETALHES: {json.dumps(pattern['appointment_details'])}\n\n"

        for msg in messages:
            role = "HUMAN" if isinstance(msg, HumanMessage) else "AI"
            formatted += f"{role}: {msg.content}\n"

        return formatted

    def _update_known_patterns(self, pattern: Dict):
        """Atualiza padrões conhecidos com nova informação."""
        # Adiciona exemplo aos padrões
        if pattern["oper_message"]:
            self.known_patterns["confirmacao_manual"]["examples"].append({
                "message": pattern["oper_message"],
                "details": pattern["appointment_details"],
                "timestamp": datetime.now().isoformat()
            })

        # Salva padrões atualizados
        patterns_file = f"{self.patterns_db_path}/patterns.json"
        with open(patterns_file, 'w', encoding='utf-8') as f:
            json.dump(self.known_patterns, f, ensure_ascii=False, indent=2)

    def get_similar_examples(self, current_context: str, k: int = 3) -> List[Document]:
        """
        Busca exemplos similares ao contexto atual.
        """
        try:
            similar_docs = self.vectorstore.similarity_search(current_context, k=k)
            return similar_docs
        except Exception as e:
            logger.error(f"Erro ao buscar exemplos similares: {e}")
            return []

    def analyze_context_for_response(self, messages: List[BaseMessage], user_input: str) -> Dict[str, Any]:
        """
        Analisa o contexto e sugere como responder.
        """
        # Extrai padrão atual
        current_pattern = self.extract_conversation_pattern(messages)

        # Busca exemplos similares
        context_str = f"{messages[-1].content if messages else ''}\n{user_input}"
        similar_examples = self.get_similar_examples(context_str, k=3)

        # Análise
        analysis = {
            "has_confirmation": current_pattern["confirmation_present"],
            "has_oper_message": current_pattern["has_oper_intervention"],
            "appointment_details": current_pattern["appointment_details"],
            "suggested_behavior": "normal_flow",
            "similar_examples": []
        }

        # Se há confirmação manual, muda comportamento sugerido
        if current_pattern["has_oper_intervention"] and current_pattern["confirmation_present"]:
            analysis["suggested_behavior"] = "acknowledge_confirmation"
            analysis["suggested_response_style"] = "grateful_and_helpful"

        # Adiciona exemplos similares
        for doc in similar_examples:
            analysis["similar_examples"].append({
                "content": doc.page_content[:200],  # Primeiros 200 chars
                "metadata": doc.metadata
            })

        return analysis


class ContextAwareLLMEnhancer:
    """
    Classe que melhora as respostas do LLM usando o sistema de aprendizado.
    """

    def __init__(self, company_id: int):
        self.learner = ConversationPatternLearner(company_id)
        self.company_id = company_id

    def enhance_prompt_with_context(
        self,
        messages: List[BaseMessage],
        user_input: str,
        original_prompt: str
    ) -> str:
        """
        Melhora o prompt original com contexto aprendido.
        """
        # Analisa contexto
        context_analysis = self.learner.analyze_context_for_response(messages, user_input)

        # Se detectou confirmação manual, adiciona instruções específicas
        if context_analysis["suggested_behavior"] == "acknowledge_confirmation":
            context_instructions = f"""
[CONTEXTO DETECTADO: Confirmação Manual de Agendamento]
Detalhes confirmados: {json.dumps(context_analysis['appointment_details'], ensure_ascii=False)}

IMPORTANTE: Um agendamento já foi confirmado pela equipe.
- NÃO pergunte sobre agendar novamente
- Agradeça a confirmação do cliente
- Pergunte se precisa de mais informações
- Seja cordial e prestativo

"""
            return context_instructions + original_prompt

        # Se há exemplos similares relevantes, adiciona
        if context_analysis["similar_examples"]:
            examples_text = "\n[EXEMPLOS SIMILARES DE CONVERSAS BEM-SUCEDIDAS]:\n"
            for ex in context_analysis["similar_examples"][:2]:  # Máximo 2 exemplos
                examples_text += f"- {ex['content']}\n"

            return original_prompt + "\n" + examples_text

        return original_prompt

    def post_process_response(self, ai_response: str, context_analysis: Dict) -> str:
        """
        Pós-processa a resposta do LLM se necessário.
        """
        # Se o LLM ainda assim perguntou sobre agendar após confirmação
        if (context_analysis["suggested_behavior"] == "acknowledge_confirmation" and
            any(word in ai_response.lower() for word in ["agendar", "marcar consulta", "horário disponível"])):

            # Substitui por resposta apropriada
            return (
                "Perfeito! Seu agendamento está confirmado conforme mencionado. "
                "Há algo mais que você gostaria de saber sobre sua consulta?"
            )

        return ai_response

    def learn_from_conversation_end(self, messages: List[BaseMessage], contact_phone: str):
        """
        Chamado ao final de uma conversa para aprender com ela.
        """
        self.learner.learn_from_conversation(messages, contact_phone)


# Função helper para integrar com o sistema atual
def create_context_aware_enhancer(company_id: int) -> ContextAwareLLMEnhancer:
    """
    Cria uma instância do melhorador de contexto para uma empresa.
    """
    return ContextAwareLLMEnhancer(company_id)
