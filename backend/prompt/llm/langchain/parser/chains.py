"""
Chains LangChain para diferentes tipos de parsing
"""
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from .models import ExtractedData
from ..llm_config import create_llm_for_use_case, log_cache_metrics
import logging

logger = logging.getLogger(__name__)


def create_simple_confirmation_chain(company_id: int = None):
    """Chain para validar confirmações simples com cache otimizado"""
    # Prompt estático primeiro para maximizar cache
    prompt = ChatPromptTemplate.from_template(
        "Analise se a resposta do usuário é uma confirmação.\n\n"
        "Responda apenas SIM ou NÃO.\n\n"
        "--- DADOS DA CONVERSA ---\n"
        "O usuário disse '{user_input}' em resposta a '{assistant_message}'."
    )

    llm = create_llm_for_use_case(
        "validator",
        company_id=company_id,
        user_context=f"simple_confirmation_company_{company_id}" if company_id else "simple_confirmation"
    )
    return prompt | llm


def create_explicit_choice_chain(company_id: int = None):
    """Chain para extrair escolhas explícitas de horários com cache otimizado"""

    parser = PydanticOutputParser(pydantic_object=ExtractedData)

    # Conteúdo estático primeiro
    prompt = ChatPromptTemplate.from_template(
        "Extraia APENAS a escolha específica do usuário:\n"
        "- Se escolheu 'primeiro' ou '1', extraia a primeira opção oferecida\n"
        "- Se escolheu 'segundo' ou '2', extraia a segunda opção oferecida\n"
        "- Se mencionou horário específico (ex: '14h', 'às 9'), extraia esse horário\n"
        "- Se mencionou dia específico, extraia a data\n\n"
        "IMPORTANTE: \n"
        "- NÃO extraia se o usuário não fez uma escolha clara\n"
        "- Formato data: DD/MM/YYYY\n"
        "- Formato horário: HH:MM\n\n"
        "{format_instructions}\n\n"
        "--- DADOS DA CONVERSA ---\n"
        "O assistente ofereceu opções: {assistant_message}\n\n"
        "O usuário respondeu: {user_choice}"
    )

    prompt = prompt.partial(format_instructions=parser.get_format_instructions())

    llm = create_llm_for_use_case(
        "parser",
        company_id=company_id,
        user_context=f"explicit_choice_company_{company_id}" if company_id else "explicit_choice"
    )
    return prompt | llm | parser


def create_full_extraction_chain(company_id: int = None):
    """Chain completa para casos complexos - último recurso com cache otimizado"""

    parser = PydanticOutputParser(pydantic_object=ExtractedData)

    # Conteúdo estático primeiro para cache
    prompt = ChatPromptTemplate.from_template(
        "Analise a conversa e extraia APENAS informações confirmadas pelo usuário:\n\n"
        "Regras CRÍTICAS:\n"
        "1. NUNCA extraia data/hora se o usuário apenas disse 'sim', 'ok', etc\n"
        "2. Nome: extraia APENAS se o usuário disse explicitamente\n"
        "3. Tratamento: \n"
        "   - Se o usuário mencionou um tratamento específico (ex: implante, clareamento, limpeza), extraia exatamente o que foi mencionado\n"
        "   - Use 'Consulta de Avaliação' APENAS quando o usuário explicitamente não sabe ou não especificou nenhum tratamento\n"
        "   - Palavras como 'implante', 'clareamento', 'limpeza', 'canal', 'prótese' devem ser reconhecidas como tratamentos específicos\n"
        "4. Data/Hora: APENAS se usuário escolheu especificamente\n"
        "5. Cliente: 'novo' se primeira vez, 'antigo' se já é cliente\n\n"
        "{format_instructions}\n\n"
        "--- CONVERSA ---\n"
        "Assistente: {assistant_message}\n"
        "Usuário: {user_input}"
    )

    prompt = prompt.partial(format_instructions=parser.get_format_instructions())

    llm = create_llm_for_use_case(
        "parser",
        company_id=company_id,
        user_context=f"full_extraction_company_{company_id}" if company_id else "full_extraction"
    )
    return prompt | llm | parser