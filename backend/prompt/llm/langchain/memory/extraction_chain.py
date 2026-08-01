"""
Chain para extração inteligente de contexto usando LangChain.
"""

import logging
from typing import List, Dict, Any
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnablePassthrough

from .models import ContextAnalysis, InterventionType, Entity

logger = logging.getLogger(__name__)


class ContextExtractionChain:
    """Chain para extrair contexto importante de mensagens de chat"""

    def __init__(self, model_name: str = "gpt-4.1-mini-2025-04-14", temperature: float = 0):
        """
        Inicializa a chain de extração de contexto.

        Args:
            model_name: Modelo OpenAI a usar
            temperature: Temperatura para geração (0 = mais determinístico)
        """
        self.model_name = model_name
        self.temperature = temperature
        self.llm = ChatOpenAI(model=model_name, temperature=temperature)
        self.parser = PydanticOutputParser(pydantic_object=ContextAnalysis)

        # Prompt principal para análise de contexto
        self.extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um especialista em análise de contexto conversacional em ambiente de serviços.

Analise a conversa e extraia informações contextuais importantes, focando em:

1. **Mudanças de Contexto**:
   - Intervenções de operador humano (marcadas com [operador], [Operador], OPER:, etc)
   - Mudanças abruptas de tópico
   - Referências a conversas anteriores
   - Mudanças no tom emocional

2. **Entidades Importantes**:
   - Nomes de pessoas (clientes, dentistas, familiares)
   - Tratamentos de serviços mencionados
   - Valores monetários
   - Datas e horários
   - Localizações

3. **Referências Temporais**:
   - Datas específicas
   - Períodos (manhã, tarde, noite)
   - Referências relativas (ontem, semana que vem, etc)

4. **Ações e Intenções**:
   - O que o usuário quer fazer
   - Procedimentos mencionados
   - Próximos passos discutidos

5. **Tom Emocional**:
   - Urgência
   - Frustração
   - Satisfação
   - Ansiedade

Determine se a conversa requer uma mudança significativa de contexto baseado em:
- Presença de intervenção manual
- Mudança drástica de assunto
- Referência a informações não presentes no contexto atual
- Indicadores de urgência ou importância

{format_instructions}"""),

            MessagesPlaceholder(variable_name="messages"),

            ("human", """Analise o contexto desta conversa, especialmente as últimas mensagens.

Preste atenção especial a:
- Intervenções de operador (texto com [operador] ou similar)
- Confirmações do usuário ("ok", "entendi", "anotei", etc)
- Mudanças de tópico
- Referências a conversas anteriores

Retorne uma análise estruturada do contexto.""")
        ])

        # Cria a chain completa
        self.chain = (
            RunnablePassthrough.assign(
                format_instructions=lambda x: self.parser.get_format_instructions()
            )
            | self.extraction_prompt
            | self.llm
            | self.parser
        )

    def analyze(self, messages: List[BaseMessage], max_messages: int = 10) -> ContextAnalysis:
        """
        Analisa mensagens e retorna análise de contexto.

        Args:
            messages: Lista de mensagens para analisar
            max_messages: Número máximo de mensagens a considerar

        Returns:
            ContextAnalysis com o resultado da análise
        """
        try:
            # Pega apenas as últimas N mensagens para análise
            messages_to_analyze = messages[-max_messages:] if len(messages) > max_messages else messages

            logger.info(f"[ContextExtraction] Analisando {len(messages_to_analyze)} mensagens")

            # Invoca a chain
            result = self.chain.invoke({
                "messages": messages_to_analyze
            })

            logger.info(f"[ContextExtraction] Análise completa - Tipo: {result.intervention_type}, "
                       f"Requer shift: {result.requires_context_shift}")

            return result

        except Exception as e:
            logger.error(f"[ContextExtraction] Erro na análise: {e}")
            # Retorna análise vazia em caso de erro
            return ContextAnalysis(
                intervention_type=InterventionType.NONE,
                metadata={"error": str(e)}
            )

    def extract_entities_only(self, text: str) -> List[Entity]:
        """
        Extrai apenas entidades de um texto específico.

        Args:
            text: Texto para extrair entidades

        Returns:
            Lista de entidades encontradas
        """
        entity_prompt = ChatPromptTemplate.from_messages([
            ("system", """Extraia todas as entidades importantes do texto de serviços.

Tipos de entidades:
- PESSOA: nomes de pessoas
- TRATAMENTO: procedimentos de serviços
- DATA: datas e horários
- VALOR: valores monetários
- LOCAL: localizações
- SINTOMA: sintomas relatados

Retorne no formato JSON:
[
    {"text": "entidade", "type": "TIPO", "confidence": 0.9},
    ...
]"""),
            ("human", "{text}")
        ])

        try:
            response = self.llm.invoke(entity_prompt.format_messages(text=text))
            # Parse manual do JSON retornado
            import json
            entities_data = json.loads(response.content)

            return [
                Entity(
                    text=e["text"],
                    type=e["type"],
                    confidence=e.get("confidence", 1.0)
                )
                for e in entities_data
            ]
        except Exception as e:
            logger.error(f"[ContextExtraction] Erro ao extrair entidades: {e}")
            return []


# Função auxiliar para testes
def test_extraction():
    """Testa a extraction chain com mensagens de exemplo"""
    from langchain_core.messages import HumanMessage, AIMessage

    messages = [
        HumanMessage(content="Olá, gostaria de agendar uma consulta"),
        AIMessage(content="Olá! Sou a assistente virtual. Como posso ajudar?"),
        AIMessage(content="[Operador] Cliente já conversou comigo sobre implante business, valor R$ 3.500 à vista ou 10x no cartão. Quer marcar para próxima terça-feira às 14h"),
        HumanMessage(content="Sim, como combinamos")
    ]

    extractor = ContextExtractionChain()
    analysis = extractor.analyze(messages)

    print(f"Tipo de intervenção: {analysis.intervention_type}")
    print(f"Entidades: {[e.text for e in analysis.key_entities]}")
    print(f"Requer mudança de contexto: {analysis.requires_context_shift}")

    return analysis


if __name__ == "__main__":
    # Executa teste se rodado diretamente
    test_extraction()
