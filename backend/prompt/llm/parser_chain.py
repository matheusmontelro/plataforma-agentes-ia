
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import pytz
from datetime import datetime
import logging

# Novas importações do LangChain
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableSequence

logger = logging.getLogger(__name__)

class LLMUserData(BaseModel):
    """
    Define os campos que queremos extrair via LLM.
    """
    tratamento: Optional[str] = Field(
        default=None,
        description="Tipo de tratamento (ex.: implante, canal, clareamento, etc.)"
    )
    cliente: Optional[str] = Field(
        default=None,
        description="novo ou antigo (ex.: 'novo' se for a primeira vez na empresa, 'antigo' se já for cliente)."
    )
    nome: Optional[str] = Field(
        default=None,
        description="Nome completo do cliente."
    )
    data: Optional[str] = Field(
        default=None,
        description="Data para agendamento, formato DD/MM/YYYY."
    )
    horario: Optional[str] = Field(
        default=None,
        description="Horário para agendamento, formato HH:mm."
    )
    agendamento_confirmado: bool = Field(
        default=False,
        description="True se o cliente confirmou o agendamento (novo ou reagendamento)."
    )
    cancelar_agendamento: bool = Field(
        default=False,
        description="True se o cliente solicitou cancelamento."
    )
    motivo_cancelamento: Optional[str] = Field(
        default=None,
        description="Razão do cancelamento, caso cancelar_agendamento=True."
    )

# Instanciamos o parser Pydantic
llm_user_data_parser = PydanticOutputParser(pydantic_object=LLMUserData)

# Exemplo JSON + explicações
JSON_EXAMPLE_AND_EXPLANATION = """
Exemplo de JSON que queremos extrair (use null se não souber o valor):

<json>
{{
    "tratamento": "implante",
    "cliente": "novo",
    "nome": "João Silva",
    "data": "15/01/2025",
    "horario": "09:15",
    "agendamento_confirmado": true,
    "cancelar_agendamento": false
}}
</json>

- Se o usuário digitar horário em formatos não convencionais (ex.: "9 e 15", "9h15", "nove e quinze", "9:15h"),
  converta para HH:mm (por ex.: "09:15").

- Se não tiver certeza de como converter, ou se for algo fora do normal (ex.: "nove e sessenta"), tente pedir
  esclarecimentos ao usuário ou retorne null.

Campo         | Descrição
--------------|------------------------------------------------
tratamento    | tipo de tratamento (ex.: Implante, Canal, etc.)
cliente      | 'novo' se for primeira vez, 'antigo' se já for cliente
nome          | nome completo do cliente
data          | data agendada (DD/MM/YYYY)
horario       | horário agendado (HH:mm)
agendamento_confirmado | true se o cliente confirmou
cancelar_agendamento   | true se o cliente solicitou cancelar
motivo_cancelamento    | razão do cancelamento, caso cancelar_agendamento=true
"""

# Aqui criamos um PromptTemplate que permite inserir dinamicamente
# a data/hora atual (fuso de Brasília) ao início do prompt.
EXTRACTION_PROMPT = PromptTemplate(
    template=(
        # Incluir data/hora no prompt:
        "Atualmente é {current_datetime} (Horário de Brasília). NÃO EXTRAIA ESSA DATA E HORÁRIO, ela serve somente pra consulta e saber qual a data de hoje e horario.\n\n"
        "Sua tarefa é analisar a conversa abaixo e extrair APENAS um objeto JSON com dados estruturados.\n"
        "Forneça APENAS um objeto JSON válido, sem texto adicional.\n\n"
        "IMPORTANTE:\n"
        "- Para salvar o nome do usuário o assistente sempre irá perguntar por exemplo: 'pode me confirmar seu nome completo?' e a resposta do usuario na maioria das vezes será o nome dele. Não extraia se não for o nome de uma pessoa.\n"
        "- Se a conversa indicar 'primeira vez', ou 'Nunca fui' e etc. => cliente='novo'; 'já sou cliente' => cliente='antigo'. SEMPRE extraia essa informação da fala do Usuário e NUNCA do Assistente.\n"
        "- Se não tiver nenhuma pista, use null.\n"
        "- O horário deve ter formato HH:mm. Converta de '9 e quinze', '9h15', 'nove e 15' para '09:15'.\n"
        "- Se a data ou horário forem incoerentes (por ex.: '25/13/2025' ou '9 e 60'), retorne null.\n"
        "- O tratamento você pode extrair avaliando o contexto da conversa, por exemplo: as vezes o usuário não irá saber qual o tratamento ele deve fazer ou que ele busca, nesses casos que o cliente não souber marque como =Consulta de Avaliação, caso contrário extraia somente do Usuário."
        "- o horário sempre deve ter o formato HH:mm e a data sempre o formato DD/MM/YYYY. Nunca extraia uma data DD/MM/YYYY ou horário HH:mm sem que o usuário tenha confirmado explicitamente. Ou uma data retroativa que jápassou de {current_datetime}.\n"
        "- Se na conversa for mencionado 'implante', 'canal', 'clareamento', 'limpeza', ou outro tratamento, extraia para o campo 'tratamento'.\n"
        "- Campos como o nome deve ser extraido da fala do usuário. NUNCA EXTRAIA o nome da fala o Assistente, SEMPRE extraia da fala do Usuário.\n"
        "- A data (DD/MM/YYYY) e horário (HH:mm) você deve extrair após o usuário escolher o melhor horário ou dia pra ele, NUNCA extraia cem por cento uma data e horário de uma mensagem enviada pelo Assistente. Essa extração deve ser feita após uma interação explicita do usuário onde ele mesmo escolhe o horário HH:mm que deseja após uma pergunta do assistente com opções de data e horário para o usuário e então o usuário escolher explícitamente uma das 2 opções de horários sugeridas pelo Asssitente.\n"
        "- O agendamento_confirmado = true somente após coletar todos os dados seguindo rigorosamente as regras. a data (DD/MM/YYYY) e horário (HH:mm) deve ter sido escolhido explicitamente pelo usuário.NUNCA extraia cem por cento uma data e horário de uma mensagem enviada pelo Assistente.\n"
        "- O cancelar_agendamento = true se o cliente desejar cancelar a consulta agendada\n"
        "- Use o formato JSON abaixo, sem texto extra.\n"
        f"{JSON_EXAMPLE_AND_EXPLANATION}\n\n"
        "Conversa (Assistente + Usuário): {input}\n\n"
        "{format_instructions}"
    ),
    input_variables=["input", "current_datetime"],
    partial_variables={
        "format_instructions": llm_user_data_parser.get_format_instructions()
    }
)

def create_extraction_chain(
    model_name: str = "gpt-4o-mini",
    *,
    api_key: str,
) -> RunnableSequence:
    """
    Cria a chain que usará o prompt e o parser Pydantic para extrair
    campos do texto combinado do Assistente e do Usuário,
    incluindo a data/hora atual no prompt.
    """
    # Captura data/hora atual em fuso de Brasília
    sp_tz = pytz.timezone("America/Sao_Paulo")
    now_dt = datetime.now(sp_tz)
    date_str = now_dt.strftime("%d/%m/%Y %H:%M")

    # Cria o modelo LLM
    llm = ChatOpenAI(
        model_name=model_name,
        temperature=0.0,
        openai_api_key=api_key,
    )

    # Cria a cadeia de processamento usando a nova sintaxe de pipe
    chain = EXTRACTION_PROMPT | llm | llm_user_data_parser

    logger.debug(f"[create_extraction_chain] Instanciando chain com model={model_name}. Data/hora SP={date_str}")

    return chain, date_str

def parse_user_input_with_llm(conversation_text: str, chain_tuple) -> LLMUserData:
    """
    Roda a chain e faz o parse Pydantic do output.
    Retorna um objeto LLMUserData (tratamento, cliente, data, horario, etc.).
    """
    chain, current_datetime = chain_tuple

    try:
        # Usando a nova API de invoke
        result = chain.invoke({
            "input": conversation_text,
            "current_datetime": current_datetime
        })

        logger.debug(f"[parser_chain] Resultado da extração: {result}")

        # O resultado já é um objeto LLMUserData validado
        return result

    except Exception as e:
        logger.warning(f"[parser_chain] Erro ao fazer parse: {e}")

        # Retorna diretamente um LLMUserData vazio, sem regex de fallback
        return LLMUserData()
