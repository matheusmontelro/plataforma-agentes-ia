"""
Analisador semântico de status do cliente usando LangChain.
Utiliza LLM para entender contexto sem regex.
"""

import logging
from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# Import da configuração otimizada
from ..llm_config import create_llm_for_use_case, log_cache_metrics

logger = logging.getLogger(__name__)


class CustomerStatusAnalysis(BaseModel):
    """Modelo para análise de status do cliente"""
    primary_status: str = Field(description="Status principal: new_lead, qualified_lead, appointment_confirmed, active_customer, emergency_customer")
    confidence: float = Field(description="Confiança da análise (0.0 a 1.0)")
    context_summary: str = Field(description="Resumo do contexto identificado")
    appointment_info: Optional[Dict[str, Any]] = Field(description="Informações sobre agendamento se aplicável")
    customer_history: Optional[Dict[str, Any]] = Field(description="Histórico do cliente se identificado")
    urgent_needs: List[str] = Field(description="Necessidades urgentes identificadas")
    financial_context: Optional[Dict[str, Any]] = Field(description="Contexto financeiro/orçamento")
    recommended_strategy: str = Field(description="Estratégia de resposta recomendada")
    requires_special_handling: bool = Field(description="Se requer tratamento especial")


class SemanticCustomerAnalyzer:
    """
    Analisador semântico que usa LLM para entender o status do cliente
    baseado no contexto da conversa de forma inteligente.
    """

    def __init__(self, model_name: str = "gpt-4.1-mini-2025-04-14", company_id: Optional[int] = None):
        """Inicializa o analisador com modelo LLM otimizado para cache"""
        # Usa configuração otimizada para análise de memória
        self.llm = create_llm_for_use_case(
            "memory",
            company_id=company_id,
            temperature=0.1,  # Sobrescreve para análise consistente
            model=model_name
        )
        self.company_id = company_id

        self.parser = JsonOutputParser(pydantic_object=CustomerStatusAnalysis)

        # Prompt especializado para análise de contexto de serviços
        self.analysis_prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            ("human", self._get_human_prompt())
        ])

        self.chain = self.analysis_prompt | self.llm | self.parser

        logger.info(f"[SemanticCustomerAnalyzer] Inicializado com modelo {model_name}")

    def _get_system_prompt(self) -> str:
        """Prompt do sistema especializado em contexto de serviços"""
        # IMPORTANTE: Conteúdo estático no início para maximizar cache hits
        return """Você é um especialista em análise de contexto para empresas de serviços.

Sua função é analisar conversas entre clientes/leads e identificar o status atual baseado no contexto.

TIPOS DE STATUS:
1. **new_lead**: Pessoa interessada que nunca veio à empresa
2. **qualified_lead**: Lead que já sabe sobre tratamentos/valores mas ainda não agendou
3. **appointment_confirmed**: Cliente com consulta já agendada
4. **active_customer**: Cliente com histórico na empresa
5. **emergency_customer**: Situação de urgência/emergência

CONTEXTOS IMPORTANTES:
- Intervenções de operadores (OPER:, [Operador]) são PRIORITÁRIAS
- Frases como "ta agendada", "te esperando" indicam consulta confirmada
- Referências a "como combinamos", "conforme falamos" indicam histórico
- Menções de dor, urgência indicam emergência
- Valores, orçamentos indicam lead qualificado

ESTRATÉGIAS DE RESPOSTA:
- confirm_and_assist: Para consultas agendadas
- prioritize_urgency: Para emergências
- close_conversion: Para leads qualificados
- educate_and_qualify: Para leads novos
- personalized_service: Para clientes ativos

REGRAS DE ANÁLISE:
- Analise SEMANTICAMENTE o contexto, não apenas palavras-chave
- Intervenções de operador têm PRIORIDADE máxima
- Considere o SIGNIFICADO completo das mensagens
- Se operador menciona consulta agendada, o status é "appointment_confirmed"
- Seja específico nas informações extraídas
- Avalie confiança baseado na clareza das evidências

FORMATO DE SAÍDA:
Você deve retornar uma análise estruturada em JSON com:
- Status principal identificado
- Nível de confiança (0.0 a 1.0)
- Resumo do contexto
- Informações de agendamento (se aplicável)
- Histórico do cliente (se identificado)
- Necessidades urgentes
- Contexto financeiro
- Estratégia recomendada
- Se requer tratamento especial"""

    def _get_human_prompt(self) -> str:
        """Prompt humano para análise"""
        # Formato instructions é estático e vai primeiro
        return """Forneça sua análise em JSON seguindo exatamente este formato:
{format_instructions}

--- DADOS DINÂMICOS DA CONVERSA ---

HISTÓRICO DA CONVERSA:
{conversation_history}

INPUT ATUAL DO USUÁRIO:
{user_input}

MENSAGENS DE OPERADORES IDENTIFICADAS:
{operator_messages}"""

    def analyze_customer_status(
        self,
        messages: List[BaseMessage],
        user_input: str = ""
    ) -> CustomerStatusAnalysis:
        """
        Analisa o status do cliente usando análise semântica.

        Args:
            messages: Histórico de mensagens
            user_input: Input atual do usuário

        Returns:
            Análise completa do status do cliente
        """
        try:
            # Extrai contexto estruturado
            conversation_history = self._format_conversation(messages)
            operator_messages = self._extract_operator_context(messages)

            # Executa análise via LLM
            result = self.chain.invoke({
                "conversation_history": conversation_history,
                "user_input": user_input,
                "operator_messages": operator_messages,
                "format_instructions": self.parser.get_format_instructions()
            })

            # Loga métricas de cache
            log_cache_metrics(result, f"semantic_analyzer_company_{self.company_id}")

            # Converte resultado para modelo Pydantic
            analysis = CustomerStatusAnalysis(**result)

            logger.info(f"[SemanticCustomerAnalyzer] Status: {analysis.primary_status} "
                       f"(confiança: {analysis.confidence:.2f})")

            return analysis

        except Exception as e:
            logger.error(f"[SemanticCustomerAnalyzer] Erro na análise: {e}")
            # Retorna análise padrão em caso de erro
            return CustomerStatusAnalysis(
                primary_status="unknown_status",
                confidence=0.0,
                context_summary="Erro na análise semântica",
                urgent_needs=[],
                recommended_strategy="gather_information",
                requires_special_handling=False
            )

    def _format_conversation(self, messages: List[BaseMessage]) -> str:
        """Formata histórico da conversa para análise"""
        formatted_messages = []

        for i, msg in enumerate(messages):
            if hasattr(msg, 'content'):
                msg_type = "USUÁRIO" if msg.__class__.__name__ == "HumanMessage" else "ASSISTENTE"
                formatted_messages.append(f"{i+1}. [{msg_type}]: {msg.content}")

        return "\n".join(formatted_messages)

    def _extract_operator_context(self, messages: List[BaseMessage]) -> str:
        """Extrai e formata mensagens de operadores"""
        operator_msgs = []

        for i, msg in enumerate(messages):
            if hasattr(msg, 'content') and msg.__class__.__name__ == "AIMessage":
                content = msg.content
                # Identifica mensagens de operador por padrões semânticos
                if any(marker in content.lower() for marker in ['oper:', '[operador]', 'atendente:', 'humano:']):
                    operator_msgs.append(f"Mensagem {i+1}: {content}")

        return "\n".join(operator_msgs) if operator_msgs else "Nenhuma mensagem de operador identificada"

    def get_context_enrichment(
        self,
        analysis: CustomerStatusAnalysis,
        company_config: Dict[str, Any]
    ) -> str:
        """
        Gera enriquecimento de contexto baseado na análise.

        Args:
            analysis: Análise do status do cliente
            company_config: Configurações da empresa

        Returns:
            Instrução contextual para o LLM
        """
        try:
            enrichment_prompt = ChatPromptTemplate.from_messages([
                ("system", """Você é um especialista em gerar instruções contextuais para assistentes de empresas de serviços.

Baseado na análise do cliente, gere uma instrução clara e específica que deve ser seguida pelo assistente.

A instrução deve:
- Ser específica para o status identificado
- Incluir informações relevantes do contexto
- Orientar sobre tom e abordagem
- Mencionar informações importantes a considerar
- Ser concisa mas completa"""),

                ("human", """ANÁLISE DO CLIENTE:
Status: {status}
Confiança: {confidence}
Contexto: {context_summary}
Estratégia: {strategy}
Tratamento Especial: {special_handling}

INFORMAÇÕES DA EMPRESA:
Nome: {company_name}
Assistente: {assistant_name}

INFORMAÇÕES DE AGENDAMENTO:
{appointment_info}

CONTEXTO FINANCEIRO:
{financial_context}

Gere uma instrução contextual específica para guiar a resposta do assistente:""")
            ])

            enrichment_chain = enrichment_prompt | self.llm

            # Prepara dados para o prompt
            company_name = company_config.get('company_info', {}).get('company_name', 'Empresa')
            assistant_name = company_config.get('assistant_identity', {}).get('assistant_name', 'Assistente')

            appointment_info = "Não identificado"
            if analysis.appointment_info:
                appointment_info = f"Consulta: {analysis.appointment_info}"

            financial_context = "Não identificado"
            if analysis.financial_context:
                financial_context = f"Financeiro: {analysis.financial_context}"

            instruction = enrichment_chain.invoke({
                "status": analysis.primary_status,
                "confidence": analysis.confidence,
                "context_summary": analysis.context_summary,
                "strategy": analysis.recommended_strategy,
                "special_handling": analysis.requires_special_handling,
                "company_name": company_name,
                "assistant_name": assistant_name,
                "appointment_info": appointment_info,
                "financial_context": financial_context
            })

            return instruction.content

        except Exception as e:
            logger.error(f"[SemanticCustomerAnalyzer] Erro no enriquecimento: {e}")
            return f"[CONTEXTO] Cliente com status: {analysis.primary_status}. Proceda adequadamente."


def test_semantic_analyzer():
    """Testa o analisador com exemplo do chat memory"""
    from langchain_core.messages import HumanMessage, AIMessage

    # Exemplo do chat memory
    messages = [
        AIMessage(content="OPER: Opa Cliente Exemplo"),
        AIMessage(content="OPER: A dona rose ta te esperando"),
        HumanMessage(content="beleza"),
        HumanMessage(content="obrigado"),
        AIMessage(content="OPER: sua consulta ta agendada hoje"),
        HumanMessage(content="ta certo")
    ]

    analyzer = SemanticCustomerAnalyzer()
    analysis = analyzer.analyze_customer_status(messages, "ta certo")

    print("=== ANÁLISE SEMÂNTICA ===")
    print(f"Status: {analysis.primary_status}")
    print(f"Confiança: {analysis.confidence}")
    print(f"Contexto: {analysis.context_summary}")
    print(f"Estratégia: {analysis.recommended_strategy}")
    print(f"Requer Especial: {analysis.requires_special_handling}")

    if analysis.appointment_info:
        print(f"Agendamento: {analysis.appointment_info}")

    return analysis


if __name__ == "__main__":
    test_semantic_analyzer()
