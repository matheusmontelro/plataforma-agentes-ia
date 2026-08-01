
"""
Módulo responsável por descrever cada etapa (0 a 9) do fluxo conversacional.
Armazena mensagens base, variáveis esperadas, e orientações específicas.
"""

STEP_DEFINITIONS = {
    0: {
        "name": "Boas-Vindas e Contexto",
        "description": (
            "Se for a primeira interação, cumprimente o cliente, falando que seu "
            "nome é {assistantName} e que você é atendente da {companyName}. "
            "Assim que o lead demonstrar interesse em melhorar o sorriso ou solicitar "
            "mais informações, o backend atualiza para etapa 1."
        ),
        "base_message_key": "step0",  # Indica qual campo no agent_config guarda a mensagem base
        "expected_variables": [],  # Neste step, não coletamos nada oficialmente, só passamos pra step 1 quando houver interesse
    },

    1: {
        "name": "Recepção Amigável e Identificação do Tratamento",
        "description": (
            "Mensagem Base 1: {step1First}. "
            "Aguardar a resposta sobre o que deseja melhorar (VARIAVEL: dor=valor). "
            "Depois faça a pergunta da Mensagem Base 2: {step1Second}."
            "Armazene o tratamento de interesse em [tratamento=valor]. Ao receber o tratamento, "
            "o backend atualiza para etapa 2."
        ),
        "base_message_key": "step1First",  # Mensagem base 1
        "extra_message_key": "step1Second",  # Mensagem base 2 (pode ser tratada no transitions.py se preferir)
        "expected_variables": ["dor", "tratamento"],
    },

    2: {
        "name": "Identificação da Situação do Cliente",
        "description": (
            "Mensagem Base: {step2}. Verificar se o cliente é novo ou já é cliente. "
            "Armazenar [cliente=valor]. Se o usuário já tiver respondido, pule. "
            "Ao obter essa info, backend => etapa 3."
        ),
        "base_message_key": "step2",
        "expected_variables": ["cliente"],
    },

    3: {
        "name": "Exploração do Problema e Implicações",
        "description": (
            "Mensagem Base: {step3}. Elevar nivel de consciencia, explicar benefícios. "
            "Se o usuário já respondeu, não repita. "
            "Assim que o cliente concordar, backend => etapa 4."
        ),
        "base_message_key": "step3",
        "expected_variables": [],
    },

    4: {
        "name": "Necessidade de Solução e Agendamento",
        "description": (
            "Sugira uma consulta de avaliação. Só confirme se o cliente escolher data e horário "
            "disponíveis em {available_str}, sem exceder {scheduling_config.number_of_suggestions} sugestões. "
            "Se confirmar data e horário, backend => etapa 5."
        ),
        "base_message_key": None,  # Você pode não ter mensagem base fixa
        "expected_variables": ["data", "horario"],  # Exemplo de dados a coletar, mas a confirmação real só acontece no step 5
    },

    5: {
        "name": "Confirmação do Nome Completo e Agendamento",
        "description": (
            "Solicitar nome completo. Armazenar em [nome]. "
            "Depois de confirmar, set agendamento_confirmado=true e envie JSON. => etapa 6."
        ),
        "base_message_key": None,
        "expected_variables": ["nome", "agendamento_confirmado"],  # Quando o LLM confirmar "agendamento_confirmado"
    },

    6: {
        "name": "Encerramento com Porta Aberta",
        "description": (
            "Após confirmar o agendamento, não envie mais JSON. "
            "Se o usuário não tiver outras dúvidas, finalize cordialmente. => etapa 7"
        ),
        "base_message_key": None,
        "expected_variables": [],
    },

    7: {
        "name": "Comunicação após Agendamento (se já agendou)",
        "description": (
            "Responda dúvidas adicionais de forma humanizada, sem enviar JSON. "
            "Se houver pedido de reagendamento, vá para step 9. "
            "Se houver pedido de cancelamento, gerar JSON com cancelar_agendamento=true."
        ),
        "base_message_key": None,
        "expected_variables": [],
    },

    8: {
        "name": "Communicação em caso de Cancelamento (caso precise)",
        "description": (
            "Na verdade, o script unificou o cancelamento dentro do step 7. "
            "Mas se desejar, pode usar step 8 para tratar especificamente do fluxo de cancelamento. "
            "Pergunte o motivo, gere JSON. => Encerrar ou reagendar."
        ),
        "base_message_key": None,
        "expected_variables": ["cancelar_agendamento", "motivo_cancelamento"],
    },

    9: {
        "name": "Comunicação em caso de Reagendamento",
        "description": (
            "Pergunte o melhor dia para reagendar, sugira {scheduling_config.number_of_suggestions} horários. "
            "Atualizar data, horario e set agendamento_confirmado=true novamente => final."
        ),
        "base_message_key": None,
        "expected_variables": ["data", "horario", "nome", "agendamento_confirmado"],
    },
}

def get_step_definition(step: int) -> dict:
    """
    Retorna o dicionário com as informações do step fornecido.
    Se o step não existir, retorna um step 'desconhecido'.
    """
    return STEP_DEFINITIONS.get(step, {
        "name": "Desconhecido",
        "description": "Step não definido.",
        "base_message_key": None,
        "expected_variables": []
    })
