"""
Advanced validation strategies using LangChain agents and chains.
Provides multi-step validation with reasoning and context awareness.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

try:
    from langchain.agents import AgentExecutor, create_openai_tools_agent
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.messages import HumanMessage, AIMessage
    from langchain_openai import ChatOpenAI
    from langchain.memory import ConversationBufferMemory
    from langgraph.graph import StateGraph, END
except ImportError:
    # Fallback for older versions
    from langchain.agents import AgentExecutor, create_openai_functions_agent as create_openai_tools_agent
    from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain.schema import HumanMessage, AIMessage
    from langchain_openai import ChatOpenAI
    from langchain.memory import ConversationBufferMemory

from .semantic_validator import (
    SemanticDateValidator,
    SemanticConfirmationValidator,
    TreatmentValidator,
    NameValidator
)

logger = logging.getLogger(__name__)


class ValidationAgent:
    """
    Advanced validation agent that uses multiple tools and reasoning.
    Provides context-aware validation with explanation capabilities.
    """

    def __init__(self, llm: Optional[ChatOpenAI] = None):
        """Initialize validation agent with tools"""
        self.llm = llm or ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)

        # Initialize validation tools
        self.tools = [
            SemanticDateValidator(),
            SemanticConfirmationValidator(),
            TreatmentValidator(),
            NameValidator()
        ]

        # Create agent
        self.agent = self._create_agent()
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )

        self.agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            memory=self.memory,
            verbose=True,
            max_iterations=3
        )

    def _create_agent(self):
        """Create the validation agent"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Você é um agente validador especializado em agendamentos de serviços.
Use as ferramentas disponíveis para validar informações com precisão.

Ferramentas disponíveis:
- semantic_date_validator: Valida e normaliza datas
- semantic_confirmation_validator: Detecta intenção de confirmação/cancelamento
- treatment_validator: Valida e categoriza tratamentos
- name_validator: Valida e formata nomes

Sempre forneça:
1. Se a validação passou ou falhou
2. O valor normalizado (se aplicável)
3. Explicação clara do resultado
4. Sugestões de correção (se falhou)

Seja rigoroso mas compreensivo com variações linguísticas."""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

        return create_openai_tools_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )

    def validate_complete_input(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate complete user input with all context.

        Args:
            user_input: Raw user input
            context: Current conversation context

        Returns:
            Complete validation results with all extracted data
        """
        validation_request = f"""
        Valide completamente esta entrada do usuário: "{user_input}"

        Contexto atual:
        - Etapa da conversa: {context.get('current_step', 0)}
        - Tratamento atual: {context.get('treatment', 'não definido')}
        - Tipo de cliente: {context.get('customer_type', 'não definido')}
        - Data/hora atual: {context.get('appointment_datetime', 'não definido')}

        Execute todas as validações relevantes e retorne um relatório completo.
        """

        try:
            result = self.agent_executor.run(validation_request)
            return self._parse_agent_result(result)
        except Exception as e:
            logger.error(f"Validation agent error: {e}")
            return {
                "success": False,
                "error": str(e),
                "validations": {}
            }

    def _parse_agent_result(self, result: str) -> Dict[str, Any]:
        """Parse agent result into structured format"""
        # This would ideally use a parser, but for simplicity:
        return {
            "success": True,
            "raw_result": result,
            "validations": {}  # Would be parsed from result
        }


class ChainedValidator:
    """
    Validator that chains multiple validation steps with dependencies.
    Uses LangChain's sequential chains for complex validation logic.
    """

    def __init__(self):
        """Initialize chained validator"""
        self.llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)

    def create_validation_chain(self, validation_steps: List[str]) -> Any:
        """
        Create a custom validation chain for specific steps.

        Args:
            validation_steps: List of validation steps to perform

        Returns:
            Configured validation chain
        """
        from langchain.chains import SequentialChain, LLMChain

        chains = []

        for step in validation_steps:
            if step == "appointment_readiness":
                chain = self._create_appointment_readiness_chain()
            elif step == "conflict_detection":
                chain = self._create_conflict_detection_chain()
            elif step == "data_consistency":
                chain = self._create_consistency_chain()
            else:
                continue

            chains.append(chain)

        if not chains:
            raise ValueError("No valid validation steps provided")

        return SequentialChain(
            chains=chains,
            input_variables=["user_data"],
            output_variables=["validation_result"],
            verbose=True
        )

    def _create_appointment_readiness_chain(self) -> Any:
        """Check if all data is ready for appointment creation"""
        prompt = ChatPromptTemplate.from_template("""
        Verifique se todos os dados necessários para criar um agendamento estão presentes e válidos:

        Dados: {user_data}

        Requisitos:
        1. Tratamento definido e válido
        2. Tipo de cliente (novo/existente)
        3. Nome completo do cliente
        4. Data e horário selecionados
        5. Confirmação explícita do usuário
        6. Preço informado ao cliente

        Retorne:
        - ready: true/false
        - missing: lista de campos faltantes
        - warnings: avisos importantes
        """)

        from langchain.chains import LLMChain
        return LLMChain(llm=self.llm, prompt=prompt, output_key="readiness_check")

    def _create_conflict_detection_chain(self) -> Any:
        """Detect potential conflicts in appointment data"""
        prompt = ChatPromptTemplate.from_template("""
        Detecte possíveis conflitos nos dados do agendamento:

        Dados: {readiness_check}

        Verifique:
        1. Horário em horário comercial válido
        2. Tratamento compatível com tipo de cliente
        3. Tempo suficiente para o tratamento
        4. Sem agendamentos duplos

        Retorne:
        - conflicts: lista de conflitos encontrados
        - severity: baixa/média/alta
        - suggestions: sugestões de resolução
        """)

        from langchain.chains import LLMChain
        return LLMChain(llm=self.llm, prompt=prompt, output_key="conflict_check")

    def _create_consistency_chain(self) -> Any:
        """Ensure data consistency across all fields"""
        prompt = ChatPromptTemplate.from_template("""
        Verifique a consistência dos dados:

        Dados: {conflict_check}

        Valide:
        1. Formato correto de todos os campos
        2. Dados fazem sentido juntos
        3. Nenhuma contradição entre campos

        Retorne resultado final da validação.
        """)

        from langchain.chains import LLMChain
        return LLMChain(llm=self.llm, prompt=prompt, output_key="validation_result")


class GraphValidator:
    """
    Advanced validator using LangGraph for complex validation flows.
    Provides stateful validation with conditional paths.
    """

    def __init__(self):
        """Initialize graph validator"""
        self.llm = ChatOpenAI(model="gpt-4.1-mini-2025-04-14", temperature=0)
        self.graph = self._build_validation_graph()

    def _build_validation_graph(self) -> StateGraph:
        """Build the validation graph"""
        from typing import TypedDict

        class ValidationState(TypedDict):
            user_input: str
            context: Dict[str, Any]
            validations: Dict[str, Any]
            errors: List[str]
            warnings: List[str]
            next_step: str

        # Create graph
        workflow = StateGraph(ValidationState)

        # Add nodes
        workflow.add_node("extract_intent", self._extract_intent)
        workflow.add_node("validate_data", self._validate_data)
        workflow.add_node("check_conflicts", self._check_conflicts)
        workflow.add_node("final_validation", self._final_validation)

        # Add edges
        workflow.set_entry_point("extract_intent")

        workflow.add_conditional_edges(
            "extract_intent",
            self._route_validation,
            {
                "needs_validation": "validate_data",
                "skip_validation": "final_validation"
            }
        )

        workflow.add_edge("validate_data", "check_conflicts")
        workflow.add_edge("check_conflicts", "final_validation")
        workflow.add_edge("final_validation", END)

        return workflow.compile()

    def _extract_intent(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Extract user intent from input"""
        # Implementation would extract intent
        state["next_step"] = "needs_validation"
        return state

    def _validate_data(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Validate extracted data"""
        # Implementation would validate data
        return state

    def _check_conflicts(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Check for conflicts in validated data"""
        # Implementation would check conflicts
        return state

    def _final_validation(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Final validation and summary"""
        # Implementation would finalize validation
        return state

    def _route_validation(self, state: Dict[str, Any]) -> str:
        """Route to next validation step"""
        return state.get("next_step", "skip_validation")

    def validate(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run validation through the graph.

        Args:
            user_input: User input to validate
            context: Current conversation context

        Returns:
            Validation results
        """
        initial_state = {
            "user_input": user_input,
            "context": context,
            "validations": {},
            "errors": [],
            "warnings": [],
            "next_step": ""
        }

        try:
            result = self.graph.invoke(initial_state)
            return result
        except Exception as e:
            logger.error(f"Graph validation error: {e}")
            return {
                "errors": [str(e)],
                "validations": {}
            }


# Factory function to get appropriate validator
def get_validator(strategy: str = "semantic") -> Any:
    """
    Get validator instance based on strategy.

    Args:
        strategy: Validation strategy - "semantic", "agent", "chain", or "graph"

    Returns:
        Validator instance
    """
    if strategy == "semantic":
        from .semantic_validator import SmartValidator
        return SmartValidator()
    elif strategy == "agent":
        return ValidationAgent()
    elif strategy == "chain":
        return ChainedValidator()
    elif strategy == "graph":
        return GraphValidator()
    else:
        raise ValueError(f"Unknown validation strategy: {strategy}")