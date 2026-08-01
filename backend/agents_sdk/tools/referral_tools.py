"""
Referral Tools - Tools para processamento de indicações
Compatível com OpenAI Agents SDK
"""

import logging
from typing import Annotated
from pydantic import Field
from sqlalchemy.orm import Session

# Import OpenAI Agents SDK decorator
from agents import function_tool, trace, RunContextWrapper

# Import serviço de indicações
from ..services.referral_service import ReferralService

logger = logging.getLogger(__name__)


@function_tool
def process_referral_response(
    company_id: Annotated[int, Field(description="ID da empresa")],
    phone: Annotated[str, Field(description="Telefone do indicador (formato: 5500000000009)")],
    referral_text: Annotated[str, Field(description="Texto enviado pelo usuário com as indicações")]
) -> str:
    """
    Processa resposta do usuário com indicações de amigos/familiares.

    Esta tool:
    1. Faz parse das indicações no texto
    2. Valida e formata os telefones
    3. Cria leads no CRM com source_id="Indicação"
    4. Agenda mensagens de boas-vindas para os indicados
    5. Retorna confirmação para o indicador

    Formatos aceitos no texto:
    - "Nome - Telefone"
    - "Nome: Telefone"
    - "Nome (telefone)"
    - "Nome telefone"

    Args:
        company_id: ID numérico da empresa
        phone: Telefone de quem está indicando
        referral_text: Texto com as indicações

    Returns:
        Mensagem de confirmação para enviar ao indicador

    Example:
        >>> result = process_referral_response(
        ...     company_id=42,
        ...     phone="5500000000009",
        ...     referral_text="João Silva - (11) 99999-8888\\nMaria Santos - (11) 88888-7777"
        ... )
        >>> print(result)
        "Obrigado pelas 2 indicações! João Silva e Maria Santos receberão..."
    """

    # Enhanced tracing
    with trace("process_referral_response"):
        logger.info(f"[ReferralTool] Processando indicações de {phone} para empresa {company_id}")

        # Log entrada (sem dados sensíveis)
        logger.info(
            f"[ENHANCED_TRACING] process_referral_response called",
            extra={
                "event": "tool_call",
                "tool": "process_referral_response",
                "company_id": company_id,
                "phone": phone,
                "referral_text_length": len(referral_text),
                "lines_count": len(referral_text.split('\n'))
            }
        )

        try:
            # Import database session
            from backend.db import get_db

            # Get database session
            db = next(get_db())

            # Criar service de indicações
            referral_service = ReferralService(db)

            # Verificar se empresa tem campanha ativa
            campaign = referral_service.get_active_campaign(company_id)
            if not campaign:
                logger.warning(f"[ReferralTool] Empresa {company_id} não tem campanha ativa")
                return (
                    "Obrigado pelo interesse em indicar pessoas! "
                    "No momento não temos uma campanha de indicações ativa. "
                    "Entre em contato conosco para mais informações."
                )

            # Parse das indicações
            referral_data = referral_service.parse_referral_text(referral_text)

            if referral_data.valid_count == 0:
                logger.info(f"[ReferralTool] Nenhuma indicação válida encontrada")
                return (
                    "Não consegui identificar as indicações no formato correto. "
                    "Por favor, envie no formato:\n"
                    "Nome - Telefone\n\n"
                    "Exemplo:\n"
                    "João Silva - (11) 99999-8888\n"
                    "Maria Santos - (11) 88888-7777"
                )

            # Verificar limite da campanha
            if referral_data.valid_count > campaign.max_referrals_per_request:
                logger.info(f"[ReferralTool] Muitas indicações ({referral_data.valid_count}), limite: {campaign.max_referrals_per_request}")
                return (
                    f"Obrigado pelas indicações! Por nossa política, podemos processar "
                    f"no máximo {campaign.max_referrals_per_request} indicações por vez. "
                    f"Por favor, envie as {campaign.max_referrals_per_request} principais indicações."
                )

            # Criar leads e agendar boas-vindas
            created_count = referral_service.create_referral_leads(
                company_id=company_id,
                referrer_phone=phone,
                referral_data=referral_data,
                campaign=campaign
            )

            if created_count == 0:
                logger.warning(f"[ReferralTool] Nenhum lead foi criado")
                return (
                    "Obrigado pelas indicações! Parece que essas pessoas já estão "
                    "em nossa base de dados. Agradecemos mesmo assim pela lembrança!"
                )

            # Gerar mensagem de confirmação personalizada
            if created_count == 1:
                confirmation = (
                    f"🎉 Obrigado pela indicação de {referral_data.names[0]}! "
                    f"Em breve ela receberá uma mensagem especial da nossa empresa. "
                    f"Agradecemos sua confiança em recomendar nossos serviços!"
                )
            else:
                names_list = ", ".join(referral_data.names[:created_count])
                confirmation = (
                    f"🎉 Muito obrigado pelas {created_count} indicações: {names_list}! "
                    f"Todas receberão uma mensagem especial da nossa empresa em breve. "
                    f"Sua confiança em recomendar nossos serviços é muito importante para nós!"
                )

            # Log sucesso
            logger.info(
                f"[SUCCESS] Indicações processadas com sucesso",
                extra={
                    "event": "referrals_processed",
                    "tool": "process_referral_response",
                    "company_id": company_id,
                    "phone": phone,
                    "referrals_found": referral_data.valid_count,
                    "leads_created": created_count,
                    "campaign_name": campaign.campaign_name
                }
            )

            return confirmation

        except Exception as e:
            # Log error
            logger.error(
                f"[ERROR] Erro ao processar indicações",
                extra={
                    "event": "referral_processing_failed",
                    "tool": "process_referral_response",
                    "company_id": company_id,
                    "phone": phone,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            )

            return (
                "Ocorreu um erro interno ao processar suas indicações. "
                "Nossa equipe foi notificada e entrará em contato em breve. "
                "Obrigado pela paciência!"
            )
        finally:
            # Ensure database session is closed
            try:
                db.close()
            except:
                pass


@function_tool
def check_referral_campaign_status(
    company_id: Annotated[int, Field(description="ID da empresa")]
) -> str:
    """
    Verifica se a empresa tem campanha de indicações ativa.

    Tool auxiliar para outros agents verificarem se devem mencionar
    indicações em suas conversas.

    Args:
        company_id: ID da empresa

    Returns:
        Status da campanha e instruções se ativa
    """

    with trace("check_referral_campaign_status"):
        logger.info(f"[ReferralTool] Verificando status campanha empresa {company_id}")

        try:
            from backend.db import get_db
            db = next(get_db())

            referral_service = ReferralService(db)
            campaign = referral_service.get_active_campaign(company_id)

            if not campaign:
                return "inactive"

            return f"active:{campaign.campaign_name}:{campaign.referrer_campaign_description[:100]}"

        except Exception as e:
            logger.error(f"[ReferralTool] Erro ao verificar campanha: {e}")
            return "error"
        finally:
            try:
                db.close()
            except:
                pass


@function_tool
def store_partial_referral_data(
    context: RunContextWrapper,
    data_type: Annotated[str, Field(description="Tipo de dados: 'phone', 'name', 'both'")],
    data_value: Annotated[str, Field(description="Valor dos dados fornecidos pelo usuário")]
) -> str:
    """
    Armazena dados parciais de indicação no contexto para processar posteriormente.

    Args:
        context: Contexto do agent para armazenar estado
        data_type: Tipo de dado fornecido
        data_value: Valor fornecido pelo usuário

    Returns:
        Mensagem guiando próximo passo ou processando se completo
    """

    with trace("store_partial_referral_data"):
        logger.info(f"[ReferralCollector] Armazenando {data_type}: {data_value}")

        try:
            # Acessar contexto do agent
            if not hasattr(context.context, 'current_collection'):
                context.context.current_collection = {}

            if data_type == "phone":
                # Usuário enviou telefone - armazenar e pedir nome
                context.context.current_collection["phone"] = data_value
                return (
                    f"Perfeito! Vi o telefone {data_value}. "
                    f"Agora preciso do nome da pessoa para completar a indicação. "
                    f"Qual o nome?"
                )

            elif data_type == "name":
                # Usuário enviou nome - verificar se já temos telefone
                if "phone" in context.context.current_collection:
                    # Temos telefone + nome = processar indicação
                    phone = context.context.current_collection["phone"]
                    complete_referral = f"{data_value} - {phone}"

                    # Limpar contexto
                    context.context.current_collection = {}

                    # Processar indicação completa
                    return process_referral_response(
                        company_id=context.context.company_id,
                        phone=context.context.phone,
                        referral_text=complete_referral
                    )
                else:
                    # Só nome, pedir telefone
                    context.context.current_collection["name"] = data_value
                    return (
                        f"Ótimo! Agora preciso do telefone do {data_value}. "
                        f"Pode me passar?"
                    )

            elif data_type == "both":
                # Dados completos - processar diretamente
                return process_referral_response(
                    company_id=context.context.company_id,
                    phone=context.context.phone,
                    referral_text=data_value
                )

            else:
                return (
                    "Para processar sua indicação, preciso de nome completo e telefone. "
                    "Pode enviar no formato: Nome - (DD) NNNNN-NNNN?"
                )

        except Exception as e:
            logger.error(f"[ReferralCollector] Erro ao armazenar dados: {e}")
            return (
                "Houve um problema ao processar. "
                "Pode enviar no formato: Nome - Telefone?"
            )


@function_tool
def ask_for_missing_referral_info(
    company_id: Annotated[int, Field(description="ID da empresa")],
    phone: Annotated[str, Field(description="Telefone do usuário")],
    missing_info_type: Annotated[str, Field(description="Tipo de informação faltante: 'names', 'phones', 'ddd', 'format'")],
    partial_data: Annotated[str, Field(description="Dados parciais já fornecidos pelo usuário")]
) -> str:
    """
    Solicita informações faltantes para completar indicações.

    Args:
        company_id: ID da empresa
        phone: Telefone do usuário
        missing_info_type: Tipo de info faltante
        partial_data: Dados que já foram fornecidos

    Returns:
        Mensagem solicitando informações faltantes
    """

    with trace("ask_for_missing_referral_info"):
        logger.info(f"[ReferralCollector] Solicitando {missing_info_type} para {phone}")

        try:
            if missing_info_type == "names":
                return (
                    f"Ótimo! Vi os telefones que você enviou. "
                    f"Agora preciso dos nomes das pessoas para completar as indicações. "
                    f"Pode me dizer quem são?"
                )

            elif missing_info_type == "phones":
                return (
                    f"Perfeito! Vi os nomes que você mencionou. "
                    f"Agora preciso dos telefones para entrar em contato com eles. "
                    f"Pode compartilhar?"
                )

            elif missing_info_type == "ddd":
                return (
                    f"Quase lá! Só preciso completar os DDDs dos telefones. "
                    f"Pode me dizer de qual cidade/estado são? "
                    f"Ex: São Paulo (11), Rio (21), BH (31)..."
                )

            elif missing_info_type == "format":
                return (
                    f"Vi que você quer indicar pessoas! Para eu processar corretamente, "
                    f"pode enviar no formato:\n"
                    f"Nome Completo - (DD) NNNNN-NNNN\n\n"
                    f"Exemplo:\n"
                    f"João Silva - (11) 99999-8888\n"
                    f"Maria Santos - (11) 88888-7777"
                )

            else:
                return (
                    f"Para completar suas indicações, preciso de nome completo e telefone "
                    f"de cada pessoa. Pode enviar no formato: Nome - Telefone?"
                )

        except Exception as e:
            logger.error(f"[ReferralCollector] Erro ao solicitar info: {e}")
            return (
                "Para processar suas indicações, preciso de nome completo e telefone. "
                "Pode enviar no formato: Nome - (DD) NNNNN-NNNN?"
            )


@function_tool
def confirm_referral_data(
    company_id: Annotated[int, Field(description="ID da empresa")],
    phone: Annotated[str, Field(description="Telefone do usuário")],
    collected_data: Annotated[str, Field(description="Dados coletados para confirmação")]
) -> str:
    """
    Confirma dados de indicação antes de processar.

    Args:
        company_id: ID da empresa
        phone: Telefone do usuário
        collected_data: Dados para confirmar

    Returns:
        Mensagem de confirmação
    """

    with trace("confirm_referral_data"):
        logger.info(f"[ReferralCollector] Confirmando dados para {phone}")

        return (
            f"Vou confirmar os dados das indicações:\n\n"
            f"{collected_data}\n\n"
            f"Está tudo correto? Se sim, vou processar as indicações. "
            f"Se precisar corrigir algo, me avise!"
        )


@function_tool
def handoff_back_to_main_agent(
    company_id: Annotated[int, Field(description="ID da empresa")],
    phone: Annotated[str, Field(description="Telefone do usuário")],
    completion_message: Annotated[str, Field(description="Mensagem de finalização")]
) -> str:
    """
    Finaliza coleta de indicações e retorna controle ao agent principal.

    Args:
        company_id: ID da empresa
        phone: Telefone do usuário
        completion_message: Mensagem final

    Returns:
        Mensagem de despedida antes do handoff
    """

    with trace("referral_collection_complete"):
        logger.info(f"[ReferralCollector] Finalizando coleta para {phone}")

        return (
            f"{completion_message}\n\n"
            f"Pronto! Suas indicações foram processadas com sucesso. "
            f"Posso ajudar com mais alguma coisa sobre sua consulta ou tem outras dúvidas?"
        )


# Tool registration for OpenAI Agents SDK - APENAS auxiliares
REFERRAL_TOOLS = [
    check_referral_campaign_status  # Apenas tool auxiliar, removendo process_referral_response
]

# Import da tool inteligente
from .smart_referral_collector import SMART_REFERRAL_TOOLS

# Tools específicas do collector - APENAS a tool inteligente
REFERRAL_COLLECTOR_TOOLS = [
    *SMART_REFERRAL_TOOLS  # APENAS a tool inteligente
]
