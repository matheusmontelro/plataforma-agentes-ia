
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
import json

logger = logging.getLogger(__name__)

def get_customer_context(db: Session, contact_phone: str, company_id: int) -> Dict[str, Any]:
    """
    Recupera o contexto completo do cliente a partir das tabelas de agendamentos,
    comparecimentos e vendas, fornecendo um histórico de interações para o LLM.

    Args:
        db: Sessão do banco de dados
        contact_phone: Número do telefone do cliente
        company_id: ID da empresa

    Returns:
        Um dicionário com o contexto completo do cliente
    """
    try:
        logger.info(f"[CustomerContext] Buscando contexto para cliente: {contact_phone} na empresa: {company_id}")

        context = {
            "agendamentos": get_agendamentos(db, contact_phone, company_id),
            "comparecimentos": get_comparecimentos(db, contact_phone, company_id),
            "vendas": get_vendas(db, contact_phone, company_id),
            "lead_info": get_lead_info(db, contact_phone, company_id)
        }

        # Adiciona flags e resumos úteis
        context.update(build_context_summary(context))

        logger.info(f"[CustomerContext] Contexto recuperado com sucesso: {len(context)} categorias")
        return context

    except Exception as e:
        logger.error(f"[CustomerContext] Erro ao recuperar contexto do cliente: {e}")
        return {
            "error": str(e),
            "agendamentos": [],
            "comparecimentos": [],
            "vendas": [],
            "lead_info": {},
            "is_new_customer": True,
            "has_appointments": False,
            "has_attendance": False,
            "has_sales": False,
            "last_interaction_date": None,
            "total_appointments": 0,
            "total_attendance": 0,
            "total_sales": 0,
            "total_spent": 0,
            "etapa_do_script": 0  # Default para clientes novos
        }

def get_agendamentos(db: Session, phone: str, company_id: int) -> list:
    """
    Recupera os agendamentos do cliente.
    """
    try:
        query = text("""
            SELECT
                a.id,
                a.agendamento_realizado_em,
                a.nome,
                a.phone,
                a.consulta_data,
                a.midia,
                a.interesse as tratamento_interesse,
                a.status,
                a.event_id,
                a.id_agendamento
            FROM
                agendamentos a
            WHERE
                a.phone = :phone
                AND a.company_id = :company_id
            ORDER BY
                a.consulta_data DESC
        """)

        result = db.execute(query, {"phone": phone, "company_id": company_id})
        agendamentos = []

        now = datetime.now()
        for row in result:
            agendamento = dict(row._mapping)

            # Converter datetime para string no formato brasileiro
            if agendamento.get('consulta_data'):
                dt = agendamento['consulta_data']
                agendamento['consulta_data_formatada'] = dt.strftime('%d/%m/%Y %H:%M')
                # Cálculo para verificar se o agendamento é para o futuro sem usar comparação de timezone
                agendamento['is_future'] = dt.replace(tzinfo=None) > now.replace(tzinfo=None)

            if agendamento.get('agendamento_realizado_em'):
                agendamento['agendamento_realizado_em_formatado'] = agendamento['agendamento_realizado_em'].strftime('%d/%m/%Y %H:%M')

            agendamentos.append(agendamento)

        return agendamentos

    except Exception as e:
        logger.error(f"[CustomerContext] Erro ao recuperar agendamentos: {e}")
        return []

def get_comparecimentos(db: Session, phone: str, company_id: int) -> list:
    """
    Recupera os comparecimentos do cliente.
    """
    try:
        query = text("""
            SELECT
                c.id,
                c.compareceu_em,
                c.nome,
                c.phone,
                c.midia,
                c.interesse,
                c.tratamento_orcado,
                c.valor_orcamento,
                a.consulta_data
            FROM
                comparecimentos c
            JOIN
                agendamentos a ON c.agendamento_id = a.id
            WHERE
                c.phone = :phone
                AND c.company_id = :company_id
            ORDER BY
                c.compareceu_em DESC
        """)

        result = db.execute(query, {"phone": phone, "company_id": company_id})
        comparecimentos = []

        for row in result:
            comparecimento = dict(row._mapping)

            # Converter datetime para string no formato brasileiro
            if comparecimento.get('compareceu_em'):
                comparecimento['compareceu_em_formatado'] = comparecimento['compareceu_em'].strftime('%d/%m/%Y %H:%M')

            if comparecimento.get('consulta_data'):
                comparecimento['consulta_data_formatada'] = comparecimento['consulta_data'].strftime('%d/%m/%Y %H:%M')

            comparecimentos.append(comparecimento)

        return comparecimentos

    except Exception as e:
        logger.error(f"[CustomerContext] Erro ao recuperar comparecimentos: {e}")
        return []

def get_vendas(db: Session, phone: str, company_id: int) -> list:
    """
    Recupera as vendas do cliente.
    """
    try:
        query = text("""
            SELECT
                v.id,
                v.venda_data,
                v.nome,
                v.phone,
                v.tratamento_fechado,
                v.valor_faturado,
                v.valor_pago,
                c.compareceu_em,
                c.tratamento_orcado
            FROM
                vendas v
            JOIN
                comparecimentos c ON v.comparecimento_id = c.id
            WHERE
                v.phone = :phone
                AND v.company_id = :company_id
            ORDER BY
                v.venda_data DESC
        """)

        result = db.execute(query, {"phone": phone, "company_id": company_id})
        vendas = []

        for row in result:
            venda = dict(row._mapping)

            # Converter datetime para string no formato brasileiro
            if venda.get('venda_data'):
                venda['venda_data_formatada'] = venda['venda_data'].strftime('%d/%m/%Y %H:%M')

            if venda.get('compareceu_em'):
                venda['compareceu_em_formatado'] = venda['compareceu_em'].strftime('%d/%m/%Y %H:%M')

            vendas.append(venda)

        return vendas

    except Exception as e:
        logger.error(f"[CustomerContext] Erro ao recuperar vendas: {e}")
        return []

def get_lead_info(db: Session, phone: str, company_id: int) -> Dict[str, Any]:
    """
    Recupera informações básicas do lead.
    """
    try:
        query = text("""
            SELECT
                l.id,
                l.name,
                l.phone,
                l.data_entrada,
                l.client_id,
                l.follow_up_sequence_id,
                l.source_id,
                fs.name as sequence_name
            FROM
                leads l
            LEFT JOIN
                follow_up_sequences fs ON l.follow_up_sequence_id = fs.id
            WHERE
                l.phone = :phone
                AND l.company_id = :company_id
            ORDER BY
                l.data_entrada DESC
            LIMIT 1
        """)

        result = db.execute(query, {"phone": phone, "company_id": company_id}).fetchone()

        if not result:
            return {}

        lead_info = dict(result._mapping)

        # Converter datetime para string no formato brasileiro
        if lead_info.get('data_entrada'):
            if isinstance(lead_info['data_entrada'], str):
                try:
                    # Tenta converter string para datetime se necessário
                    dt = datetime.fromisoformat(lead_info['data_entrada'].replace('Z', '+00:00'))
                    lead_info['data_entrada_formatada'] = dt.strftime('%d/%m/%Y %H:%M')
                except ValueError:
                    lead_info['data_entrada_formatada'] = lead_info['data_entrada']
            else:
                lead_info['data_entrada_formatada'] = lead_info['data_entrada'].strftime('%d/%m/%Y %H:%M')

        # Adiciona etapa do script (valor default)
        lead_info['etapa_do_script'] = 0

        return lead_info

    except Exception as e:
        logger.error(f"[CustomerContext] Erro ao recuperar informações do lead: {e}")
        return {}

def build_context_summary(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Constrói um resumo do contexto com flags e contagens úteis.
    """
    summary = {}

    # Flags de existência
    summary["is_new_customer"] = len(context["agendamentos"]) == 0 and len(context["comparecimentos"]) == 0
    summary["has_appointments"] = len(context["agendamentos"]) > 0
    summary["has_attendance"] = len(context["comparecimentos"]) > 0
    summary["has_sales"] = len(context["vendas"]) > 0

    # Contadores
    summary["total_appointments"] = len(context["agendamentos"])
    summary["total_attendance"] = len(context["comparecimentos"])
    summary["total_sales"] = len(context["vendas"])

    # Valor total gasto
    total_spent = 0
    for venda in context["vendas"]:
        if venda.get("valor_pago"):
            try:
                total_spent += float(venda["valor_pago"])
            except (ValueError, TypeError):
                pass
    summary["total_spent"] = total_spent

    # Data da última interação
    last_interaction = None

    # Verifica agendamentos
    for agendamento in context["agendamentos"]:
        if agendamento.get("agendamento_realizado_em"):
            if not last_interaction or agendamento["agendamento_realizado_em"] > last_interaction:
                last_interaction = agendamento["agendamento_realizado_em"]

    # Verifica comparecimentos
    for comparecimento in context["comparecimentos"]:
        if comparecimento.get("compareceu_em"):
            if not last_interaction or comparecimento["compareceu_em"] > last_interaction:
                last_interaction = comparecimento["compareceu_em"]

    # Verifica vendas
    for venda in context["vendas"]:
        if venda.get("venda_data"):
            if not last_interaction or venda["venda_data"] > last_interaction:
                last_interaction = venda["venda_data"]

    summary["last_interaction_date"] = last_interaction

    # Determina a etapa do script baseado no contexto
    summary["etapa_do_script"] = determine_script_stage(context)

    return summary

def determine_script_stage(context: Dict[str, Any]) -> int:
    """
    Determina a etapa adequada do script com base no histórico do cliente.

    Regras:
    - Se nunca teve contato: etapa 0 (boas-vindas)
    - Se tem agendamento futuro: etapa 7 (comunicação pós-agendamento)
    - Se tem agendamento passado sem comparecimento: etapa 8 (reagendamento)
    - Se tem comparecimento sem venda: etapa 3 (exploração do problema)
    - Se já é cliente com venda realizada: etapa 7 (comunicação pós-agendamento)
    """
    # Verifica se é um cliente novo (sem histórico)
    if not context["agendamentos"] and not context["comparecimentos"] and not context["vendas"]:
        return 0

    # Verifica se tem agendamento futuro
    for agendamento in context["agendamentos"]:
        if agendamento.get("is_future") and agendamento.get("status") == "SCHEDULED":
            return 7

    # Verifica se tem agendamento passado sem comparecimento (potencial no-show)
    has_past_appointment_without_attendance = False
    for agendamento in context["agendamentos"]:
        if not agendamento.get("is_future"):
            # Verifica se este agendamento tem um comparecimento associado
            has_attendance = False
            for comparecimento in context["comparecimentos"]:
                if comparecimento.get("agendamento_id") == agendamento.get("id"):
                    has_attendance = True
                    break

            if not has_attendance:
                has_past_appointment_without_attendance = True

    if has_past_appointment_without_attendance:
        return 8  # Reagendamento

    # Verifica se tem comparecimento sem venda
    if context["comparecimentos"] and not context["vendas"]:
        return 3  # Exploração do problema

    # Se tem vendas, é um cliente estabelecido
    if context["vendas"]:
        return 7  # Comunicação pós-agendamento

    # Caso padrão
    return 0

def format_customer_context_for_prompt(context: Dict[str, Any]) -> str:
    """
    Formata o contexto do cliente para ser incluído no prompt do LLM.
    Retorna um texto formatado com informações relevantes.
    """
    sections = []

    # Resumo geral
    summary = [
        "### RESUMO DO CLIENTE ###",
        f"• É cliente novo: {'Sim' if context.get('is_new_customer', True) else 'Não'}",
        f"• Total de agendamentos: {context.get('total_appointments', 0)}",
        f"• Total de comparecimentos: {context.get('total_attendance', 0)}",
        f"• Total de vendas: {context.get('total_sales', 0)}",
        f"• Valor total gasto: R$ {context.get('total_spent', 0):.2f}",
        f"• Etapa do script recomendada: {context.get('etapa_do_script', 0)}"
    ]

    if context.get('last_interaction_date'):
        if isinstance(context['last_interaction_date'], datetime):
            formatted_date = context['last_interaction_date'].strftime('%d/%m/%Y %H:%M')
        else:
            formatted_date = str(context['last_interaction_date'])
        summary.append(f"• Última interação: {formatted_date}")

    sections.append("\n".join(summary))

    # Informações do lead
    if context.get('lead_info'):
        lead_info = [
            "### INFORMAÇÕES DO LEAD ###"
        ]

        lead_data = context['lead_info']
        if lead_data.get('name'):
            lead_info.append(f"• Nome: {lead_data['name']}")
        if lead_data.get('data_entrada_formatada'):
            lead_info.append(f"• Data de entrada: {lead_data['data_entrada_formatada']}")
        if lead_data.get('source_id'):
            lead_info.append(f"• Origem: {lead_data['source_id']}")
        if lead_data.get('sequence_name'):
            lead_info.append(f"• Sequência de follow-up: {lead_data['sequence_name']}")

        sections.append("\n".join(lead_info))

    # Agendamentos recentes (até 3)
    if context.get('agendamentos'):
        agendamentos_info = [
            "### AGENDAMENTOS RECENTES ###"
        ]

        for idx, agendamento in enumerate(context['agendamentos'][:3]):
            status_map = {
                "SCHEDULED": "Agendado",
                "COMPLETED": "Concluído",
                "CANCELED": "Cancelado",
                "NO_SHOW": "Não compareceu"
            }
            status = status_map.get(agendamento.get('status'), agendamento.get('status', 'Desconhecido'))

            agendamento_text = [
                f"Agendamento #{idx+1}:",
                f"• Data/hora: {agendamento.get('consulta_data_formatada', 'N/A')}",
                f"• Status: {status}",
                f"• Tratamento: {agendamento.get('tratamento_interesse', 'N/A')}"
            ]

            if agendamento.get('is_future'):
                agendamento_text.append(f"• Agendamento futuro: Sim")

            agendamentos_info.append("\n".join(agendamento_text))

        sections.append("\n".join(agendamentos_info))

    # Comparecimentos recentes (até 2)
    if context.get('comparecimentos'):
        comparecimentos_info = [
            "### COMPARECIMENTOS RECENTES ###"
        ]

        for idx, comparecimento in enumerate(context['comparecimentos'][:2]):
            comparecimento_text = [
                f"Comparecimento #{idx+1}:",
                f"• Data/hora: {comparecimento.get('compareceu_em_formatado', 'N/A')}",
                f"• Tratamento orçado: {comparecimento.get('tratamento_orcado', 'N/A')}",
            ]

            if comparecimento.get('valor_orcamento'):
                comparecimento_text.append(f"• Valor orçado: R$ {float(comparecimento['valor_orcamento']):.2f}")

            comparecimentos_info.append("\n".join(comparecimento_text))

        sections.append("\n".join(comparecimentos_info))

    # Vendas recentes (até 2)
    if context.get('vendas'):
        vendas_info = [
            "### VENDAS RECENTES ###"
        ]

        for idx, venda in enumerate(context['vendas'][:2]):
            venda_text = [
                f"Venda #{idx+1}:",
                f"• Data/hora: {venda.get('venda_data_formatada', 'N/A')}",
                f"• Tratamento: {venda.get('tratamento_fechado', 'N/A')}",
            ]

            if venda.get('valor_faturado'):
                venda_text.append(f"• Valor faturado: R$ {float(venda['valor_faturado']):.2f}")
            if venda.get('valor_pago'):
                venda_text.append(f"• Valor pago: R$ {float(venda['valor_pago']):.2f}")

            vendas_info.append("\n".join(venda_text))

        sections.append("\n".join(vendas_info))

    return "\n\n".join(sections)

# Adicione esta função ao customer_context.py

def integrate_with_conversation_state(db: Session, contact_phone: str, company_id: int) -> None:
    """
    Integra os dados do próximo agendamento ao conversation_state,
    evitando que informações extraídas incorretamente sobreponham
    agendamentos reais já confirmados no banco.
    """
    try:
        # 1. Obtém o contexto do cliente
        customer_context = get_customer_context(db, contact_phone, company_id)
        next_appointment = customer_context.get('next_appointment')

        if not next_appointment:
            logger.info(f"[CustomerContext] Sem agendamento futuro para sincronizar com conversation_state")
            return

        # 2. Carrega o estado atual
        result = db.execute(
            text("""
                SELECT current_step, state_data
                FROM conversation_state
                WHERE phone = :phone AND company_id = :company_id
                LIMIT 1
            """),
            {"phone": contact_phone, "company_id": company_id}
        ).fetchone()

        if not result:
            logger.info(f"[CustomerContext] Conversation state não encontrado para sincronização")
            return

        current_step, state_data_json = result

        try:
            state_data = json.loads(state_data_json) if state_data_json else {}
        except json.JSONDecodeError:
            state_data = {}

        # 3. Sincroniza apenas se tiver um agendamento futuro confirmado
        if (next_appointment.get('status') == 'SCHEDULED' and
            next_appointment.get('is_future') and
            next_appointment.get('consulta_data')):

            # Formato da data
            appointment_date = next_appointment['consulta_data']
            date_str = appointment_date.strftime('%d/%m/%Y')
            time_str = appointment_date.strftime('%H:%M')

            # Atualiza os campos críticos com dados confiáveis do banco
            updates = {
                'data': date_str,
                'horario': time_str,
                'nome': next_appointment.get('nome') or state_data.get('nome'),
                'status': next_appointment.get('status'),
                'next_appointment_id': next_appointment.get('id'),
                'tratamento': next_appointment.get('tratamento_interesse') or state_data.get('tratamento'),
                'last_db_sync': datetime.now().isoformat()
            }

            # Mescla os dados
            state_data.update(updates)

            # Atualiza current_step para 7 se estivermos em um step menor,
            # sinalizando que já existe um agendamento confirmado
            new_step = max(current_step, 7) if current_step != 8 else 8

            # Salva as alterações no banco
            db.execute(
                text("""
                    UPDATE conversation_state
                    SET current_step = :step,
                        state_data = CAST(:data as JSONB),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE phone = :phone
                      AND company_id = :company_id
                """),
                {
                    "step": new_step,
                    "data": json.dumps(state_data),
                    "phone": contact_phone,
                    "company_id": company_id
                }
            )
            db.commit()

            logger.info(f"[CustomerContext] Conversation state sincronizado com agendamento: "
                       f"data={date_str}, horario={time_str}, step={new_step}")

    except Exception as e:
        logger.error(f"[CustomerContext] Erro ao sincronizar agendamento com conversation_state: {e}")
