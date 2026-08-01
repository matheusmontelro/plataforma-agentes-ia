"""
Detector de intervenções e mudanças de contexto em conversas.
"""

import logging
import re
from typing import List, Tuple, Optional, Dict, Set
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage

from .models import InterventionType

logger = logging.getLogger(__name__)


class InterventionDetector:
    """Detector especializado para diferentes tipos de intervenção em conversas"""

    # Padrões para detecção de operador
    OPERATOR_PATTERNS = [
        r'\[operador\]', r'\[Operador\]', r'\[OPERADOR\]',
        r'OPER:', r'oper:', r'Oper:',
        r'\[atendente\]', r'\[Atendente\]', r'\[ATENDENTE\]',
        r'\[suporte\]', r'\[Suporte\]', r'\[SUPORTE\]',
        r'\[humano\]', r'\[Humano\]', r'\[HUMANO\]',
        r'\[manual\]', r'\[Manual\]', r'\[MANUAL\]'
    ]

    # Frases de confirmação do usuário
    CONFIRMATION_PHRASES = {
        # Confirmações simples
        'ok', 'okay', 'sim', 'uhum', 'aham', 'certo', 'entendi',
        'beleza', 'blz', 'perfeito', 'ótimo', 'combinado', 'fechado',
        'pode ser', 'tá bom', 'ta bom', 'tudo bem', 'show', 'valeu',

        # Confirmações com ação
        'anotei', 'anotado', 'salvei', 'salvo', 'guardei',
        'pode deixar', 'deixa comigo', 'vou anotar', 'vou salvar',

        # Confirmações educadas
        'obrigado', 'obrigada', 'agradeço', 'grato', 'grata',
        'muito obrigado', 'muito obrigada', 'valeu mesmo',

        # Confirmações informais
        'blzinha', 'suave', 'tranquilo', 'de boa', 'fechou',
        'isso aí', 'isso ai', 'é isso', 'eh isso', 'isso mesmo',

        # Variações
        'ok entendi', 'certo obrigado', 'beleza valeu', 'perfeito obrigado',
        'ótimo agradeço', 'show de bola', 'maravilha', 'excelente'
    }

    # Indicadores de urgência
    URGENCY_INDICATORS = {
        'urgente', 'urgência', 'emergência', 'emergencial',
        'dor', 'doendo', 'muita dor', 'não aguento',
        'insuportável', 'forte', 'intensa', 'aguda',
        'socorro', 'ajuda', 'pelo amor', 'por favor',
        'agora', 'já', 'imediato', 'imediatamente',
        'hoje', 'ainda hoje', 'o quanto antes', 'rápido'
    }

    # Referências a conversas anteriores
    PREVIOUS_REFERENCE_PATTERNS = [
        r'como\s+(conversamos|falamos|combinamos)',
        r'conforme\s+(conversamos|falamos|combinamos)',
        r'como\s+(te\s+)?falei',
        r'como\s+(eu\s+)?disse',
        r'lembra\s+que',
        r'você\s+disse\s+que',
        r'(ontem|antes|anteriormente)\s+(você|vc)',
        r'na\s+(última|ultima)\s+(vez|conversa)',
        r'quando\s+(conversamos|falamos)',
        r'aquele\s+(horário|dia|tratamento|valor)',
        r'aquela\s+(consulta|data|informação)'
    ]

    def __init__(self):
        """Inicializa o detector com padrões compilados"""
        # Compila padrões regex para melhor performance
        self.operator_regex = re.compile(
            '|'.join(self.OPERATOR_PATTERNS),
            re.IGNORECASE
        )

        self.reference_regex = re.compile(
            '|'.join(self.PREVIOUS_REFERENCE_PATTERNS),
            re.IGNORECASE
        )

    def detect(self, messages: List[BaseMessage], user_input: str = "") -> Dict[str, any]:
        """
        Detecta diferentes tipos de intervenção nas mensagens.

        Args:
            messages: Histórico de mensagens
            user_input: Input atual do usuário

        Returns:
            Dict com resultados da detecção:
            {
                'type': InterventionType,
                'operator_info': {...} se operador detectado,
                'confirmation_info': {...} se confirmação detectada,
                'urgency_info': {...} se urgência detectada,
                'reference_info': {...} se referência anterior detectada
            }
        """
        result = {
            'type': InterventionType.NONE,
            'operator_info': None,
            'confirmation_info': None,
            'urgency_info': None,
            'reference_info': None
        }

        # 1. Detecta intervenção de operador
        operator_info = self._detect_operator(messages)
        if operator_info['detected']:
            result['type'] = InterventionType.OPERATOR
            result['operator_info'] = operator_info
            logger.info(f"[InterventionDetector] Operador detectado no índice {operator_info['index']}")
            return result

        # 2. Detecta confirmação do usuário
        if user_input:
            confirmation_info = self._detect_confirmation(user_input)
            if confirmation_info['detected']:
                result['type'] = InterventionType.USER_CONFIRMATION
                result['confirmation_info'] = confirmation_info
                logger.info(f"[InterventionDetector] Confirmação detectada: {confirmation_info['phrase']}")
                return result

            # 3. Detecta urgência
            urgency_info = self._detect_urgency(user_input)
            if urgency_info['detected']:
                result['type'] = InterventionType.URGENCY_DETECTED
                result['urgency_info'] = urgency_info
                logger.info(f"[InterventionDetector] Urgência detectada: {urgency_info['indicators']}")
                return result

            # 4. Detecta referência a conversa anterior
            reference_info = self._detect_previous_reference(user_input)
            if reference_info['detected']:
                result['type'] = InterventionType.REFERENCE_PREVIOUS
                result['reference_info'] = reference_info
                logger.info(f"[InterventionDetector] Referência anterior detectada")
                return result

        # 5. Detecta mudança de tópico (análise mais complexa)
        if len(messages) >= 2:
            topic_change = self._detect_topic_change(messages, user_input)
            if topic_change['detected']:
                result['type'] = InterventionType.TOPIC_CHANGE
                result['topic_change_info'] = topic_change
                logger.info(f"[InterventionDetector] Mudança de tópico detectada")
                return result

        return result

    def _detect_operator(self, messages: List[BaseMessage]) -> Dict[str, any]:
        """Detecta intervenção de operador nas mensagens"""
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, AIMessage) and self.operator_regex.search(msg.content):
                # Calcula se é primeira resposta após operador
                messages_after = len(messages) - i - 1
                is_first_response = messages_after <= 1

                # Extrai o conteúdo limpo (remove marcadores)
                clean_content = self.operator_regex.sub('', msg.content).strip()

                return {
                    'detected': True,
                    'index': i,
                    'content': msg.content,
                    'clean_content': clean_content,
                    'is_first_response': is_first_response,
                    'messages_after': messages_after
                }

        return {'detected': False}

    def _detect_confirmation(self, user_input: str) -> Dict[str, any]:
        """Detecta se o usuário está confirmando/aceitando algo"""
        user_lower = user_input.lower().strip()

        # Remove pontuação para melhor matching
        user_clean = re.sub(r'[.,!?;:]', '', user_lower)

        # Verifica match exato primeiro
        if user_clean in self.CONFIRMATION_PHRASES:
            return {
                'detected': True,
                'phrase': user_clean,
                'confidence': 1.0,
                'type': 'exact_match'
            }

        # Verifica se contém frase de confirmação e é curta
        words = user_clean.split()
        if len(words) <= 5:
            for phrase in self.CONFIRMATION_PHRASES:
                if phrase in user_clean:
                    return {
                        'detected': True,
                        'phrase': phrase,
                        'confidence': 0.8,
                        'type': 'contains'
                    }

        return {'detected': False}

    def _detect_urgency(self, user_input: str) -> Dict[str, any]:
        """Detecta indicadores de urgência no input"""
        user_lower = user_input.lower()
        found_indicators = []

        for indicator in self.URGENCY_INDICATORS:
            if indicator in user_lower:
                found_indicators.append(indicator)

        if found_indicators:
            # Calcula score de urgência baseado na quantidade de indicadores
            urgency_score = min(len(found_indicators) / 3.0, 1.0)

            return {
                'detected': True,
                'indicators': found_indicators,
                'score': urgency_score,
                'level': 'high' if urgency_score > 0.6 else 'medium'
            }

        return {'detected': False}

    def _detect_previous_reference(self, user_input: str) -> Dict[str, any]:
        """Detecta referências a conversas anteriores"""
        matches = self.reference_regex.findall(user_input.lower())

        if matches:
            return {
                'detected': True,
                'patterns': matches,
                'confidence': 0.9
            }

        # Verifica palavras-chave isoladas que podem indicar referência
        reference_words = ['aquele', 'aquela', 'aquilo', 'conforme', 'lembra']
        user_lower = user_input.lower()

        for word in reference_words:
            if word in user_lower and len(user_input.split()) < 10:
                return {
                    'detected': True,
                    'patterns': [word],
                    'confidence': 0.6
                }

        return {'detected': False}

    def _detect_topic_change(self, messages: List[BaseMessage], user_input: str) -> Dict[str, any]:
        """
        Detecta mudança significativa de tópico.
        Análise simples baseada em palavras-chave.
        """
        if not user_input or len(messages) < 2:
            return {'detected': False}

        # Pega conteúdo das últimas mensagens
        recent_contents = []
        for msg in messages[-3:]:  # Últimas 3 mensagens
            if hasattr(msg, 'content'):
                recent_contents.append(msg.content.lower())

        recent_text = ' '.join(recent_contents)
        user_lower = user_input.lower()

        # Define categorias de tópicos
        topic_categories = {
            'agendamento': ['agendar', 'marcar', 'consulta', 'horário', 'disponível'],
            'financeiro': ['valor', 'preço', 'quanto', 'pagamento', 'parcelar'],
            'tratamento': ['tratamento', 'procedimento', 'canal', 'implante', 'limpeza'],
            'sintoma': ['dor', 'doendo', 'inchaço', 'sangramento', 'sensível'],
            'localização': ['endereço', 'onde fica', 'localização', 'como chegar']
        }

        # Identifica tópico atual nas mensagens recentes
        current_topic = None
        for topic, keywords in topic_categories.items():
            if any(kw in recent_text for kw in keywords):
                current_topic = topic
                break

        # Identifica tópico no novo input
        new_topic = None
        for topic, keywords in topic_categories.items():
            if any(kw in user_lower for kw in keywords):
                new_topic = topic
                break

        # Detecta mudança se tópicos são diferentes e ambos foram identificados
        if current_topic and new_topic and current_topic != new_topic:
            return {
                'detected': True,
                'from_topic': current_topic,
                'to_topic': new_topic,
                'confidence': 0.7
            }

        return {'detected': False}
