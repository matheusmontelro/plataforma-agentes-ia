from fastapi import APIRouter, Depends
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone as datetime_timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy.orm import Session
from sqlalchemy import DateTime, and_, case, cast, func, or_, text
from backend.logging_config import logger
from backend.db import get_db
from backend.models import Lead, Agendamento, Comparecimento, Venda, ConversationState, LeadPipelineHistory, Pipeline, PipelineStage, NoShowEvent

router = APIRouter()


def get_metric_pipeline_stages(db: Session, company_id: Optional[int]) -> List[PipelineStage]:
    """
    Busca as etapas do pipeline ativo usado pelo dashboard.
    Evita usar um pipeline fixo, porque cada empresa pode ter funis próprios.
    """
    pipeline_query = db.query(Pipeline).filter(Pipeline.is_active == True)
    if company_id:
        pipeline_query = pipeline_query.filter(Pipeline.company_id == company_id)

    pipeline = pipeline_query.order_by(Pipeline.id.asc()).first()
    if not pipeline:
        return []

    return (
        db.query(PipelineStage)
        .filter(PipelineStage.pipeline_id == pipeline.id)
        .order_by(PipelineStage.order.asc(), PipelineStage.id.asc())
        .all()
    )


def apply_lead_source_filter(query, fonte: Optional[str]):
    if not fonte:
        return query

    if fonte == "Meta Ads":
        return query.filter(Lead.source_id.op("~")('^[0-9]+$'))

    if fonte == "Orgânico":
        return query.filter(or_(Lead.source_id == None, Lead.source_id == "Orgânico"))

    return query.filter(Lead.source_id == fonte)

@router.get("/metrics/funnels")
def get_funnel_metrics(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    fonte: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retorna métricas de funil (Leads, Agendamentos, Comparecimentos, Vendas, etc.)
    filtradas por company_id (opcional) e intervalo de datas (opcional).
    """

    # 1) Converter datas (caso sejam fornecidas) para objetos datetime
    #    Formato esperado: 'YYYY-MM-DD'
    parsed_start = None
    parsed_end = None
    date_format = "%Y-%m-%d"

    if start_date:
        parsed_start = datetime.strptime(start_date, date_format)
    if end_date:
        # Ajuste para incluir todo o dia final (até 23:59:59). Soma 1 dia e filtra "<" em vez de "<=".
        parsed_end = datetime.strptime(end_date, date_format) + timedelta(days=1)

    # 2) Montar filtros básicos de data e de empresa
    #    - Para Leads: usar Lead.data_entrada
    #    - Para Agendamentos: usar Agendamento.agendamento_realizado_em
    #    - Para Comparecimentos: usar Comparecimento.compareceu_em
    #    - Para Vendas: usar Venda.venda_data
    def date_filter(query, column):
        """Aplica filtro de datas (start e end) ao query."""
        if parsed_start and parsed_end:
            # Filtra >= start e < end (ou seja, até um dia a mais, mas não incluindo)
            query = query.filter(column >= parsed_start, column < parsed_end)
        elif parsed_start:
            query = query.filter(column >= parsed_start)
        elif parsed_end:
            query = query.filter(column < parsed_end)
        return query

    def build_leads_subquery():
        """Constrói subquery de leads com filtros aplicados."""
        subquery = db.query(Lead.id)
        if company_id:
            subquery = subquery.filter(Lead.company_id == company_id)
        if fonte:
            if fonte == "Meta Ads":
                # PostgreSQL: Use regex ~ '^[0-9]+$' (similar to GLOB '[0-9]*')
                subquery = subquery.filter(Lead.source_id.op("~")('^[0-9]+$'))
            elif fonte == "Orgânico":
                subquery = subquery.filter(
                    or_(Lead.source_id == None, Lead.source_id == "Orgânico")
                )
            else:
                subquery = subquery.filter(Lead.source_id == fonte)
        return subquery

    # 3) Consultas - Leads
    leads_query = db.query(func.count(Lead.id))
    if company_id:
        leads_query = leads_query.filter(Lead.company_id == company_id)
    if fonte:
        # Aplica filtro baseado na fonte selecionada
        if fonte == "Meta Ads":
            # PostgreSQL: Use regex ~ '^[0-9]+$'
            leads_query = leads_query.filter(Lead.source_id.op("~")('^[0-9]+$'))
        elif fonte == "Orgânico":
            # Para Orgânico, filtra por NULL ou fonte == "Orgânico"
            leads_query = leads_query.filter(
                or_(Lead.source_id == None, Lead.source_id == "Orgânico")
            )
        else:
            # Para outras fontes específicas (Facebook, Instagram, etc.)
            leads_query = leads_query.filter(Lead.source_id == fonte)
    leads_query = date_filter(leads_query, Lead.data_entrada)
    qtd_leads = leads_query.scalar() or 0

    # 4) Consultas - Agendamentos
    agendamentos_query = db.query(func.count(Agendamento.id))
    if company_id:
        agendamentos_query = agendamentos_query.filter(Agendamento.company_id == company_id)
    if fonte:
        # Filtra agendamentos baseados nos leads da fonte específica
        agendamentos_query = agendamentos_query.filter(
            Agendamento.lead_id.in_(build_leads_subquery())
        )
    agendamentos_query = date_filter(agendamentos_query, Agendamento.consulta_data)
    qtd_agendamentos = agendamentos_query.scalar() or 0

    # 5) Consultas - Comparecimentos
    comparecimentos_query = db.query(func.count(Comparecimento.id))
    if company_id:
        comparecimentos_query = comparecimentos_query.filter(Comparecimento.company_id == company_id)
    if fonte:
        # Filtra comparecimentos baseados nos leads da fonte específica
        comparecimentos_query = comparecimentos_query.filter(
            Comparecimento.lead_id.in_(build_leads_subquery())
        )
    comparecimentos_query = date_filter(comparecimentos_query, Comparecimento.compareceu_em)
    qtd_comparecimentos = comparecimentos_query.scalar() or 0

    # 6) Consultas - Vendas
    vendas_query = db.query(func.count(Venda.id))
    if company_id:
        vendas_query = vendas_query.filter(Venda.company_id == company_id)
    if fonte:
        # Filtra vendas baseadas nos leads da fonte específica
        vendas_query = vendas_query.filter(
            Venda.lead_id.in_(build_leads_subquery())
        )
    vendas_query = date_filter(vendas_query, Venda.venda_data)
    qtd_vendas = vendas_query.scalar() or 0

    # 7) Valores Financeiros (exemplo: valor_faturado, valor_pago, valor_orcamento)
    #    - Venda: SUM(Venda.valor_faturado) e SUM(Venda.valor_pago)
    #    - Comparecimento: SUM(Comparecimento.valor_orcamento)

    # Valor Faturado
    faturado_query = db.query(func.sum(Venda.valor_faturado))
    if company_id:
        faturado_query = faturado_query.filter(Venda.company_id == company_id)
    if fonte:
        # Filtra vendas baseadas nos leads da fonte específica
        faturado_query = faturado_query.filter(
            Venda.lead_id.in_(build_leads_subquery())
        )
    faturado_query = date_filter(faturado_query, Venda.venda_data)
    total_faturado = faturado_query.scalar() or 0

    # Valor Pago
    valor_pago_query = db.query(func.sum(Venda.valor_pago))
    if company_id:
        valor_pago_query = valor_pago_query.filter(Venda.company_id == company_id)
    if fonte:
        # Filtra vendas baseadas nos leads da fonte específica
        valor_pago_query = valor_pago_query.filter(
            Venda.lead_id.in_(build_leads_subquery())
        )
    valor_pago_query = date_filter(valor_pago_query, Venda.venda_data)
    total_valor_pago = valor_pago_query.scalar() or 0

    # Valor Orçado
    orcamento_query = db.query(func.sum(Comparecimento.valor_orcamento))
    if company_id:
        orcamento_query = orcamento_query.filter(Comparecimento.company_id == company_id)
    if fonte:
        # Filtra comparecimentos baseados nos leads da fonte específica
        orcamento_query = orcamento_query.filter(
            Comparecimento.lead_id.in_(build_leads_subquery())
        )
    orcamento_query = date_filter(orcamento_query, Comparecimento.compareceu_em)
    total_orcado = orcamento_query.scalar() or 0

    # 8) Calcular Percentuais e Ticket Médio
    percent_agendamentos = (qtd_agendamentos / qtd_leads * 100) if qtd_leads else 0
    percent_comparecimentos = (qtd_comparecimentos / qtd_agendamentos * 100) if qtd_agendamentos else 0
    percent_vendas = (qtd_vendas / qtd_comparecimentos * 100) if qtd_comparecimentos else 0

    # Ticket médio = total_faturado / qtd_vendas
    ticket_medio = (total_faturado / qtd_vendas) if qtd_vendas else 0

    # 9) Retornar tudo em um dicionário
    metrics = {
        "totalLeads": qtd_leads,
        "totalAgendamentos": qtd_agendamentos,
        "percentAgendamentos": round(percent_agendamentos, 2),
        "totalComparecimentos": qtd_comparecimentos,
        "percentComparecimentos": round(percent_comparecimentos, 2),
        "totalVendas": qtd_vendas,
        "percentVendas": round(percent_vendas, 2),
        "valorFaturado": float(total_faturado),
        "valorPago": float(total_valor_pago),
        "valorOrcado": float(total_orcado),
        "ticketMedio": round(ticket_medio, 2),
    }

    # ---------------------------
    #    AVISOS DE BOAS PRÁTICAS
    # ---------------------------
    boas_praticas = []

    # Exemplo de algumas condições básicas:
    if percent_agendamentos < 20:
        boas_praticas.append(
            "Conversão de Leads em Agendamentos está abaixo de 20%. "
            "Reforce a abordagem inicial ou verifique a qualidade dos leads."
        )

    if percent_comparecimentos < 30:
        boas_praticas.append(
            "Taxa de Comparecimentos abaixo de 30%. "
            "Considere lembretes de consulta (WhatsApp, SMS, etc.) para reduzir faltas."
        )

    if percent_vendas < 50:
        boas_praticas.append(
            "Conversão de Comparecimentos em Vendas abaixo de 50%. "
            "Avalie se o cliente está recebendo a proposta de valor adequada."
        )

    if ticket_medio < 500:
        boas_praticas.append(
            "Ticket médio abaixo de R$ 500. "
            "Pode ser interessante revisar planos de tratamento e oferta de procedimentos de maior valor agregado."
        )

    # Adiciona a lista de boas práticas ao dicionário final
    metrics["boasPraticas"] = boas_praticas

    return metrics

# ------------------------------------------------------------------------------
# FUNÇÃO UTILITÁRIA PARA FILTRO DE DATAS
# ------------------------------------------------------------------------------
def date_filter(query, column, start_date: Optional[str], end_date: Optional[str]):
    """
    Aplica filtro de data à query de forma semelhante ao que é feito no /metrics/funnels.
    Formato esperado de data: 'YYYY-MM-DD'.
    """
    parsed_start = None
    parsed_end = None
    date_format = "%Y-%m-%d"

    if start_date:
        parsed_start = datetime.strptime(start_date, date_format)
    if end_date:
        # Ajuste para incluir todo o dia final (até 23:59:59). Soma 1 dia e filtra "<" em vez de "<=".
        parsed_end = datetime.strptime(end_date, date_format) + timedelta(days=1)

    if parsed_start and parsed_end:
        query = query.filter(column >= parsed_start, column < parsed_end)
    elif parsed_start:
        query = query.filter(column >= parsed_start)
    elif parsed_end:
        query = query.filter(column < parsed_end)

    return query


# ------------------------------------------------------------------------------
# 1) /metrics/funnel_by_source
#    Quantidade de leads agrupados por "fonte" (source_id).
#    Regras:
#      - se source_id for só dígitos => "Meta Ads"
#      - se source_id == NULL => "Orgânico"
#      - caso contrário => source_id
# ------------------------------------------------------------------------------
@router.get("/metrics/funnel_by_source")
def get_funnel_by_source(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    fonte: Optional[str] = None,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Retorna a quantidade de leads por fonte, considerando as regras acima.
    É possível filtrar por company_id e intervalo de datas (sobre o campo Lead.data_entrada).
    """
    fonte_case = case(
        (Lead.source_id == None, "Orgânico"),
        (Lead.source_id.op("~")('^[0-9]+$'), "Meta Ads"),
        else_=Lead.source_id
    ).label("fonte")

    query = db.query(
        fonte_case,
        func.count(Lead.id).label("total_leads")
    )

    if company_id:
        query = query.filter(Lead.company_id == company_id)

    query = apply_lead_source_filter(query, fonte)

    # Aplicar filtro de data (Lead.data_entrada)
    query = date_filter(query, Lead.data_entrada, start_date, end_date)
    query = query.group_by(fonte_case).order_by(func.count(Lead.id).desc())

    results = query.all()

    # Montar resposta
    response = []
    for row in results:
        response.append({
            "fonte": row[0] if row[0] else "Sem Fonte",
            "totalLeads": row[1]
        })

    return response

# ------------------------------------------------------------------------------
# 3) /metrics/daily_funnel - Dados diários do funil
# ------------------------------------------------------------------------------
@router.get("/metrics/daily_funnel")
def get_daily_funnel(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    fonte: Optional[str] = None,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Retorna dados diários do funil baseados nos estágios do pipeline.
    """

    # 1. Obter estágios do pipeline
    stages = get_metric_pipeline_stages(db, company_id)
    stage_names = {s.id: s.name for s in stages}
    first_stage_id = stages[0].id if stages else None
    first_stage_name = stages[0].name if stages else None

    # Filtros de data
    parsed_start = None
    parsed_end = None
    date_format = "%Y-%m-%d"

    if start_date:
        parsed_start = datetime.strptime(start_date, date_format)
    if end_date:
        parsed_end = datetime.strptime(end_date, date_format) + timedelta(days=1)

    # Inicializar dicionário de dados por data
    data_dict = {}

    # Helper para inicializar data
    def init_date_entry(date_str):
        if date_str not in data_dict:
            data_dict[date_str] = {
                'date': date_str,
                # 'leads': 0, # Removido para evitar duplicidade
                **{s.name: 0 for s in stages} # Chaves dinâmicas para cada estágio
            }

    # 1. Novos Leads (Lead.data_entrada) -> Mapear para o PRIMEIRO ESTÁGIO
    leads_query = db.query(
        func.date(Lead.data_entrada).label('data'),
        func.count(Lead.id).label('count')
    )
    if company_id:
        leads_query = leads_query.filter(Lead.company_id == company_id)

    leads_query = apply_lead_source_filter(leads_query, fonte)
    leads_query = date_filter(leads_query, Lead.data_entrada, start_date, end_date)
    leads_query = leads_query.group_by(func.date(Lead.data_entrada))

    for row in leads_query.all():
        date_str = row.data.strftime('%Y-%m-%d')
        init_date_entry(date_str)
        # Se temos um primeiro estágio identificado, usamos a contagem de criação para ele
        if first_stage_name:
            data_dict[date_str][first_stage_name] = row.count

    # 2. Movimentações de Estágio (LeadPipelineHistory) -> Para OUTROS estágios
    history_query = db.query(
        func.date(LeadPipelineHistory.moved_at).label('data'),
        LeadPipelineHistory.to_stage_id,
        func.count(func.distinct(LeadPipelineHistory.lead_id)).label('count')
    )

    if company_id:
        history_query = history_query.filter(LeadPipelineHistory.company_id == company_id)

    if fonte:
        history_query = history_query.join(Lead, Lead.id == LeadPipelineHistory.lead_id)
        history_query = apply_lead_source_filter(history_query, fonte)

    history_query = date_filter(history_query, LeadPipelineHistory.moved_at, start_date, end_date)
    history_query = history_query.group_by(func.date(LeadPipelineHistory.moved_at), LeadPipelineHistory.to_stage_id)

    for row in history_query.all():
        # Ignorar movimentações para o primeiro estágio para evitar dupla contagem com a criação
        if row.to_stage_id == first_stage_id:
            continue

        date_str = row.data.strftime('%Y-%m-%d')
        stage_name = stage_names.get(row.to_stage_id)

        if stage_name:
            init_date_entry(date_str)
            # Somar ao invés de substituir, caso haja múltiplos eventos (embora group by cuide disso)
            # Mas aqui estamos atribuindo o count do group by
            data_dict[date_str][stage_name] = row.count

    # Converter para lista ordenada
    result = sorted(data_dict.values(), key=lambda x: x['date'])

    return result


# ------------------------------------------------------------------------------
# 2) /metrics/timeline
#    "Linha do tempo" de atividades recentes (leads, agendamentos, comparecimentos, no-show, vendas, etc.)
#    Ordenamos pela data desc e podemos limitar a exibição (ex: últimos 20 ou 50 eventos).
# ------------------------------------------------------------------------------
def _resolve_timeline_timezone(timezone_name: Optional[str]) -> tzinfo:
    """Resolve um timezone IANA, preservando UTC como fallback retrocompatível."""
    if not timezone_name:
        return datetime_timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        logger.warning("Timezone inválido na timeline; usando UTC")
        return datetime_timezone.utc


def _timeline_date_bounds(
    start_date: Optional[str],
    end_date: Optional[str],
    timezone_name: Optional[str],
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Converte limites de calendário do navegador em instantes UTC."""
    browser_timezone = _resolve_timeline_timezone(timezone_name)
    parsed_start = None
    parsed_end = None

    if start_date:
        local_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=browser_timezone)
        parsed_start = local_start.astimezone(datetime_timezone.utc)
    if end_date:
        local_end = (
            datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        ).replace(tzinfo=browser_timezone)
        parsed_end = local_end.astimezone(datetime_timezone.utc)

    return parsed_start, parsed_end


def _normalize_timeline_datetime(value: datetime) -> datetime:
    """Normaliza timestamps aware/naive para um instante UTC comparável."""
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime_timezone.utc)
    return value.astimezone(datetime_timezone.utc)


def _serialize_timeline_datetime(value: datetime) -> str:
    return _normalize_timeline_datetime(value).isoformat().replace("+00:00", "Z")


@router.get("/metrics/timeline")
def get_timeline(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timezone: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Retorna uma linha do tempo de eventos (Leads, Agendamentos, Comparecimentos, NoShow, Vendas).
    Cada item contém: data do evento, tipo do evento, nome/descrição etc.

    Parâmetros:
    - company_id: filtra a empresa (se não informado, traz de todas).
    - start_date, end_date: datas de calendário no fuso informado pelo navegador.
    - timezone: timezone IANA opcional; usa UTC como fallback.
    - limit: limita a quantidade total de eventos retornados (default=20).
    """
    source_limit = max(1, min(limit, 100))
    parsed_start, parsed_end = _timeline_date_bounds(start_date, end_date, timezone)
    events = []

    def fetch_events(model, date_col, type_str, text_col, date_expression=None):
        effective_date = date_expression if date_expression is not None else date_col
        q = db.query(model.id, effective_date, text_col)
        if company_id:
            if hasattr(model, 'company_id'):
                q = q.filter(model.company_id == company_id)

        if parsed_start:
            q = q.filter(effective_date >= parsed_start)
        if parsed_end:
            q = q.filter(effective_date < parsed_end)

        results = q.order_by(effective_date.desc(), model.id.desc()).limit(source_limit).all()
        for r in results:
            if r[1] is None:
                continue
            normalized_date = _normalize_timeline_datetime(r[1])
            events.append({
                "entity_id": r[0],
                "event_date": _serialize_timeline_datetime(normalized_date),
                "event_type": type_str,
                "descricao": r[2] or "",
                "_sort_date": normalized_date,
            })

    # O schema legado de produção ainda mantém leads.created_at como varchar.
    # Todos os valores atuais são timestamps válidos; o cast local preserva o contrato
    # sem exigir migration ou reescrita histórica nesta entrega.
    lead_created_at = cast(Lead.created_at, DateTime(timezone=True))
    fetch_events(Lead, Lead.created_at, 'novo_lead', Lead.name, lead_created_at)
    fetch_events(Agendamento, Agendamento.agendamento_realizado_em, 'agendamento', Agendamento.nome)
    fetch_events(Comparecimento, Comparecimento.compareceu_em, 'comparecimento', Comparecimento.nome)
    fetch_events(NoShowEvent, NoShowEvent.marcado_em, 'no_show', NoShowEvent.nome)
    fetch_events(Venda, Venda.venda_data, 'venda', Venda.nome)

    events.sort(
        key=lambda event: (event["_sort_date"], event["entity_id"]),
        reverse=True,
    )
    response = events[:source_limit]
    for event in response:
        event.pop("_sort_date", None)
    return response


# ------------------------------------------------------------------------------
# 3) /metrics/projections
#    Projeção do mês corrente (exemplo) para leads, agendamentos etc.
#    Baseado na média diária do que já aconteceu no mês.
# ------------------------------------------------------------------------------
@router.get("/metrics/projections")
def get_projections(
    company_id: Optional[int] = None,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Retorna projeções para o mês atual baseadas nos estágios do pipeline.
    """

    now = datetime.now()

    # 1) Primeiro dia do mês
    first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 2) Próximo mês, para descobrir último dia
    if first_day_of_month.month == 12:
        next_month = first_day_of_month.replace(
            year=first_day_of_month.year + 1, month=1
        )
    else:
        next_month = first_day_of_month.replace(month=first_day_of_month.month + 1)
    last_day_of_month = next_month - timedelta(days=1)
    total_days_in_month = last_day_of_month.day

    current_day = now.day
    days_passed = current_day if current_day > 0 else 1

    # Obter estágios
    stages = get_metric_pipeline_stages(db, company_id)
    first_stage_id = stages[0].id if stages else None

    projections = {
        "mes": now.strftime("%Y-%m"),
        "diasNoMes": total_days_in_month,
        "diaAtual": current_day,
        "stages": {},
        "faturadoSoFar": 0,
        "faturadoProjection": 0
    }

    # 1. Projeção de Leads (Entrada) - Usado para o PRIMEIRO ESTÁGIO
    leads_so_far = db.query(func.count(Lead.id)).filter(
        Lead.data_entrada >= first_day_of_month,
        Lead.data_entrada < now,
        Lead.company_id == company_id if company_id else True
    ).scalar() or 0

    leads_per_day = leads_so_far / days_passed

    # REMOVIDO: projections["stages"]["Leads"] = ... (Será inserido no loop com o nome real do estágio)

    # 2. Projeção por Estágio
    for stage in stages:
        if stage.id == first_stage_id:
            # Para o primeiro estágio, usamos a contagem de criação de leads
            count_so_far = leads_so_far
            per_day = leads_per_day
        else:
            # Para outros estágios, usamos histórico
            count_so_far = db.query(func.count(func.distinct(LeadPipelineHistory.lead_id))).filter(
                LeadPipelineHistory.to_stage_id == stage.id,
                LeadPipelineHistory.moved_at >= first_day_of_month,
                LeadPipelineHistory.moved_at < now,
                LeadPipelineHistory.company_id == company_id if company_id else True
            ).scalar() or 0

            per_day = count_so_far / days_passed

        projections["stages"][stage.name] = {
            "soFar": count_so_far,
            "projection": int(per_day * total_days_in_month)
        }

    # 3. Faturamento (Vendas)
    faturado_so_far = db.query(func.sum(Venda.valor_faturado)).filter(
        Venda.venda_data >= first_day_of_month,
        Venda.venda_data < now,
        Venda.company_id == company_id if company_id else True
    ).scalar() or 0

    faturado_per_day = faturado_so_far / days_passed

    projections["faturadoSoFar"] = float(faturado_so_far)
    projections["faturadoProjection"] = float(faturado_per_day * total_days_in_month)

    return projections

@router.get("/metrics/time_between_stages")
def get_time_between_stages(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Calcula o tempo médio (em dias) para:
      - Lead -> 1º agendamento_realizado_em
      - Lead -> 1º compareceu_em
      - Lead -> 1º venda_data

    Ignora casos em que (evento_data - data_entrada) é negativo (dados inconsistentes).
    Filtra leads pela data_entrada, caso start_date e end_date sejam fornecidos.
    """

    from datetime import datetime, timedelta
    from sqlalchemy import text

    def make_naive(dt: Optional[datetime]) -> Optional[datetime]:
        """Remove timezone (tzinfo) se presente, para evitar erro de subtração."""
        if dt and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt

    # Converter start_date/end_date
    parsed_start = None
    parsed_end = None
    date_fmt = "%Y-%m-%d"

    if start_date:
        parsed_start = datetime.strptime(start_date, date_fmt)
    if end_date:
        # soma 1 dia => filtra < end_date
        parsed_end = datetime.strptime(end_date, date_fmt) + timedelta(days=1)

    # Consulta SQL usando agendamento_realizado_em
    sql = text("""
        SELECT
          l.id AS lead_id,
          l.data_entrada AS lead_date,
          MIN(a.agendamento_realizado_em) AS first_agendamento_date,
          MIN(c.compareceu_em) AS first_compareceu_em,
          MIN(v.venda_data) AS first_venda_data
        FROM leads l
          LEFT JOIN agendamentos a ON a.lead_id = l.id
          LEFT JOIN comparecimentos c ON c.lead_id = l.id
          LEFT JOIN vendas v ON v.lead_id = l.id
        WHERE
          (:company_id IS NULL OR l.company_id = :company_id)
          AND (:start_date IS NULL OR l.data_entrada >= :start_date)
          AND (:end_date   IS NULL OR l.data_entrada <  :end_date)
        GROUP BY l.id, l.data_entrada
    """)

    params = {
        "company_id": company_id,
        "start_date": parsed_start,
        "end_date": parsed_end
    }

    rows = db.execute(sql, params).fetchall()

    sum_lead_to_agendamento = timedelta(0)
    sum_lead_to_comparecimento = timedelta(0)
    sum_lead_to_venda = timedelta(0)

    count_lead_to_agendamento = 0
    count_lead_to_comparecimento = 0
    count_lead_to_venda = 0

    for row in rows:
        lead_date = make_naive(row.lead_date)
        ag_date = make_naive(row.first_agendamento_date)
        comp_date = make_naive(row.first_compareceu_em)
        venda_date = make_naive(row.first_venda_data)

        # Lead -> Agendamento (agendamento_realizado_em)
        if lead_date and ag_date:
            delta_ag = ag_date - lead_date
            if delta_ag.total_seconds() >= 0:
                sum_lead_to_agendamento += delta_ag
                count_lead_to_agendamento += 1

        # Lead -> Comparecimento (compareceu_em)
        if lead_date and comp_date:
            delta_comp = comp_date - lead_date
            if delta_comp.total_seconds() >= 0:
                sum_lead_to_comparecimento += delta_comp
                count_lead_to_comparecimento += 1

        # Lead -> Venda (venda_data)
        if lead_date and venda_date:
            delta_venda = venda_date - lead_date
            if delta_venda.total_seconds() >= 0:
                sum_lead_to_venda += delta_venda
                count_lead_to_venda += 1

    def avg_in_days(total_delta: timedelta, n: int) -> float:
        if n == 0:
            return 0.0
        return round(total_delta.total_seconds() / 86400 / n, 2)

    metrics = {
        "leadToAgendamento": avg_in_days(sum_lead_to_agendamento, count_lead_to_agendamento),
        "leadToComparecimento": avg_in_days(sum_lead_to_comparecimento, count_lead_to_comparecimento),
        "leadToVenda": avg_in_days(sum_lead_to_venda, count_lead_to_venda),
    }

    return metrics

@router.get("/metrics/funnels/timeseries")
def get_timeseries(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Retorna uma série temporal (agrupada por mês) de Leads, Agendamentos, Comparecimentos e Vendas.
    - Leads: usar leads.data_entrada
    - Agendamentos: agendamentos.agendamento_realizado_em
    - Comparecimentos: comparecimentos.compareceu_em
    - Vendas: vendas.venda_data
    """
    # 1) Converter datas (se fornecidas) para datetime
    parsed_start = None
    parsed_end = None
    date_fmt = "%Y-%m-%d"
    if start_date:
        parsed_start = datetime.strptime(start_date, date_fmt)
    if end_date:
        parsed_end = datetime.strptime(end_date, date_fmt)

    # 2) Função auxiliar para agrupar (tabela, campo de data, nome do label no dicionário)
    def group_by_month(model, date_column, label_name):
        query = db.query(
            func.date_trunc('month', date_column).label("month"),
            func.count(model.id).label(label_name)
        )

        # Filtro por company_id (se existir no model)
        if company_id and hasattr(model, 'company_id'):
            query = query.filter(model.company_id == company_id)

        # Filtro de data (>= start_date e <= end_date)
        if parsed_start:
            query = query.filter(date_column >= parsed_start)
        if parsed_end:
            query = query.filter(date_column <= parsed_end)

        query = query.group_by(func.date_trunc('month', date_column))
        return query.all()

    # 3) Obter dados de cada entidade
    leads_data = group_by_month(Lead, Lead.data_entrada, "total_leads")
    ag_data = group_by_month(Agendamento, Agendamento.agendamento_realizado_em, "total_agendamentos")
    comp_data = group_by_month(Comparecimento, Comparecimento.compareceu_em, "total_comparecimentos")
    vendas_data = group_by_month(Venda, Venda.venda_data, "total_vendas")

    # 4) Combinar resultados em um só dicionário por mês
    #    Convertendo date_trunc('month', ...) em string "YYYY-MM"
    from collections import defaultdict
    monthly_dict = defaultdict(lambda: {"total_leads": 0, "total_agendamentos": 0, "total_comparecimentos": 0, "total_vendas": 0})

    def process_result(rows, field_name):
        for row in rows:
            month_str = row.month.strftime("%Y-%m")
            monthly_dict[month_str][field_name] = row[1]  # row[1] é o label_count

    process_result(leads_data, "total_leads")
    process_result(ag_data, "total_agendamentos")
    process_result(comp_data, "total_comparecimentos")
    process_result(vendas_data, "total_vendas")

    # 5) Montar lista final ordenada por mês
    sorted_months = sorted(monthly_dict.keys())
    result = []
    for month in sorted_months:
        row = monthly_dict[month]
        result.append({
            "month": month,
            "totalLeads": row["total_leads"],
            "totalAgendamentos": row["total_agendamentos"],
            "totalComparecimentos": row["total_comparecimentos"],
            "totalVendas": row["total_vendas"],
        })
    return result

@router.get("/metrics/ai_vs_humano")
def get_ai_vs_humano(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Retorna contagens e valores financeiros (ex: valor_faturado) para Agendamentos,
    Comparecimentos e Vendas, segmentados em IA vs Humano.

    Critérios "IA":
      1) (event_id IS NOT NULL) OU
      2) (id_agendamento e customer_id != NULL) OU
      3) se conversation_state indicar que a IA concluiu o agendamento
         (ex.: state_data->>'last_confirmation_timestamp' IS NOT NULL)
    """

    # A) Parse datas
    parsed_start = None
    parsed_end = None
    fmt = "%Y-%m-%d"

    if start_date:
        parsed_start = datetime.strptime(start_date, fmt)
    if end_date:
        # se for estritamente "menor que" end_date, não é preciso +1 dia
        # mas se você quiser "<= end_date", some 1 dia.
        parsed_end = datetime.strptime(end_date, fmt)  # + timedelta(days=0)

    # B) Subquery: verifica se existe conversation_state em que
    # conversation_state.phone == Agendamento.phone,
    # conversation_state.company_id == Agendamento.company_id,
    # e state_data->>'last_confirmation_timestamp' IS NOT NULL
    #
    # Esse subquery retorna True se encontrarmos um conversation_state
    # sinalizando que a IA concluiu o fluxo de agendamento com o cliente.
    cs_subq = db.query(ConversationState.phone).filter(
        ConversationState.company_id == Agendamento.company_id,
        ConversationState.phone == Agendamento.phone,
        text("conversation_state.state_data ->> 'last_confirmation_timestamp' IS NOT NULL")
    ).exists()

    # C) Expressão booleana "agendamento_ia_expr" (AJUSTADA):
    #    Agora baseada unicamente na subconsulta (cs_subq) que verifica
    #    se a IA concluiu o fluxo no conversation_state (presença de
    #    'last_confirmation_timestamp'). Removemos as verificações de
    #    event_id e ids externos (id_agendamento/customer_id) pois não são
    #    mais indicadores exclusivos da IA.
    #
    #    A condição agora é simplesmente se a subconsulta encontrou
    #    o registro correspondente em conversation_state com o timestamp.
    agendamento_ia_expr = cs_subq

    # ================================
    # 1) Agendamentos
    # ================================
    ag_query = db.query(
        func.sum(
            case((agendamento_ia_expr, 1), else_=0)
        ).label("ia_count"),
        func.sum(
            case((agendamento_ia_expr, 0), else_=1)
        ).label("humano_count")
    )

    if company_id:
        ag_query = ag_query.filter(Agendamento.company_id == company_id)
    if parsed_start:
        ag_query = ag_query.filter(Agendamento.agendamento_realizado_em >= parsed_start)
    if parsed_end:
        ag_query = ag_query.filter(Agendamento.agendamento_realizado_em < parsed_end)

    ag_counts = ag_query.one()
    ag_ia_count = ag_counts.ia_count or 0
    ag_humano_count = ag_counts.humano_count or 0

    # ================================
    # 2) Comparecimentos
    # ================================
    # Precisamos de select_from(Comparecimento) e JOIN com Agendamento
    comp_query = db.query(
        func.sum(
            case((agendamento_ia_expr, 1), else_=0)
        ).label("ia_count"),
        func.sum(
            case((agendamento_ia_expr, 0), else_=1)
        ).label("humano_count")
    ).select_from(Comparecimento) \
     .join(Agendamento, Comparecimento.agendamento_id == Agendamento.id)

    if company_id:
        comp_query = comp_query.filter(Comparecimento.company_id == company_id)
    if parsed_start:
        comp_query = comp_query.filter(Comparecimento.compareceu_em >= parsed_start)
    if parsed_end:
        comp_query = comp_query.filter(Comparecimento.compareceu_em < parsed_end)

    comp_counts = comp_query.one()
    comp_ia_count = comp_counts.ia_count or 0
    comp_humano_count = comp_counts.humano_count or 0

    # ================================
    # 3) Vendas
    # ================================
    # Partindo de Venda e fazendo join em Comparecimento -> Agendamento
    vendas_query = db.query(
        func.sum(
            case((agendamento_ia_expr, 1), else_=0)
        ).label("ia_count"),
        func.sum(
            case((agendamento_ia_expr, 0), else_=1)
        ).label("humano_count"),
        func.sum(
            case((agendamento_ia_expr, Venda.valor_faturado), else_=0)
        ).label("ia_faturado"),
        func.sum(
            case((agendamento_ia_expr, 0), else_=Venda.valor_faturado)
        ).label("humano_faturado"),
    ).select_from(Venda) \
     .join(Comparecimento, Comparecimento.id == Venda.comparecimento_id) \
     .join(Agendamento, Comparecimento.agendamento_id == Agendamento.id)

    if company_id:
        vendas_query = vendas_query.filter(Venda.company_id == company_id)
    if parsed_start:
        vendas_query = vendas_query.filter(Venda.venda_data >= parsed_start)
    if parsed_end:
        vendas_query = vendas_query.filter(Venda.venda_data < parsed_end)

    vendas_counts = vendas_query.one()

    vendas_ia_count = vendas_counts.ia_count or 0
    vendas_humano_count = vendas_counts.humano_count or 0
    ia_faturado = vendas_counts.ia_faturado or 0
    humano_faturado = vendas_counts.humano_faturado or 0

    return {
        "agendamentos": {
            "ia": ag_ia_count,
            "humano": ag_humano_count
        },
        "comparecimentos": {
            "ia": comp_ia_count,
            "humano": comp_humano_count
        },
        "vendas": {
            "ia": vendas_ia_count,
            "humano": vendas_humano_count
        },
        "faturamento": {
            "ia": float(ia_faturado),
            "humano": float(humano_faturado)
        }
    }

@router.get("/metrics/time_distribution")
def get_time_distribution(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Retorna a quantidade de Leads e Agendamentos agrupados por hora do dia.
    - Leads: leads.data_entrada
    - Agendamentos: agendamentos.agendamento_realizado_em
    """
    # Parse datas
    fmt = "%Y-%m-%d"
    parsed_start = datetime.strptime(start_date, fmt) if start_date else None
    parsed_end = datetime.strptime(end_date, fmt) if end_date else None

    # 1) Leads agrupados por EXTRACT(HOUR FROM data_entrada)
    leads_query = db.query(
        func.extract('hour', Lead.data_entrada).label('hour'),
        func.count(Lead.id).label('total_leads')
    )
    if company_id:
        leads_query = leads_query.filter(Lead.company_id == company_id)
    if parsed_start:
        leads_query = leads_query.filter(Lead.data_entrada >= parsed_start)
    if parsed_end:
        leads_query = leads_query.filter(Lead.data_entrada < parsed_end)

    leads_query = leads_query.group_by(func.extract('hour', Lead.data_entrada))
    leads_results = leads_query.all()

    # 2) Agendamentos agrupados por hora
    ag_query = db.query(
        func.extract('hour', Agendamento.agendamento_realizado_em).label('hour'),
        func.count(Agendamento.id).label('total_agendamentos')
    )
    if company_id:
        ag_query = ag_query.filter(Agendamento.company_id == company_id)
    if parsed_start:
        ag_query = ag_query.filter(Agendamento.agendamento_realizado_em >= parsed_start)
    if parsed_end:
        ag_query = ag_query.filter(Agendamento.agendamento_realizado_em < parsed_end)

    ag_query = ag_query.group_by(func.extract('hour', Agendamento.agendamento_realizado_em))
    ag_results = ag_query.all()

    # Montar dict para combinar
    from collections import defaultdict
    hour_dict = defaultdict(lambda: {"leads": 0, "agendamentos": 0})

    for row in leads_results:
        hour_key = int(row.hour)
        hour_dict[hour_key]["leads"] = row.total_leads

    for row in ag_results:
        hour_key = int(row.hour)
        hour_dict[hour_key]["agendamentos"] = row.total_agendamentos

    # Ordenar por hora e montar lista final
    sorted_hours = sorted(hour_dict.keys())
    response = []
    for h in sorted_hours:
        response.append({
            "hora": f"{h}-{h+1}",
            "leads": hour_dict[h]["leads"],
            "agendamentos": hour_dict[h]["agendamentos"]
        })

    return response

@router.get("/metrics/weekly_heatmap")
def get_weekly_heatmap(
    company_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Retorna dados de leads agregados por dia da semana e faixa de horas (ou bloco fixo).
    - leads.data_entrada

    Exemplo de saída:
    [
      { "diaSemana": 1, "faixa": "8-10", "totalLeads": 25 },
      ...
    ]
    """
    fmt = "%Y-%m-%d"
    parsed_start = datetime.strptime(start_date, fmt) if start_date else None
    parsed_end = datetime.strptime(end_date, fmt) if end_date else None

    # Exemplo: agrupar em blocos fixos (8-10, 10-12...) via CASE ou gerar "hour" e consolidar depois.
    # Para simplificar, vamos gerar "day_of_week" e "hour" e depois agrupar no Python
    from sqlalchemy import case, and_

    query = db.query(
        func.extract('dow', Lead.data_entrada).label('dow'),     # 0=domingo, 1=segunda,...
        func.extract('hour', Lead.data_entrada).label('hour'),
        func.count(Lead.id).label('count_leads')
    )
    if company_id:
        query = query.filter(Lead.company_id == company_id)
    if parsed_start:
        query = query.filter(Lead.data_entrada >= parsed_start)
    if parsed_end:
        query = query.filter(Lead.data_entrada < parsed_end)

    query = query.group_by(func.extract('dow', Lead.data_entrada), func.extract('hour', Lead.data_entrada))
    results = query.all()

    # Agora precisamos mapear hour -> Faixa (8-10, 10-12, etc.)
    def hour_to_faixa(h):
        # Ajuste livre. Aqui é apenas um exemplo
        if 8 <= h < 10:
            return "8-10"
        elif 10 <= h < 12:
            return "10-12"
        elif 12 <= h < 14:
            return "12-14"
        elif 14 <= h < 16:
            return "14-16"
        elif 16 <= h < 18:
            return "16-18"
        elif 18 <= h < 20:
            return "18-20"
        else:
            return "outro"  # Se quiser ignorar ou tratar fora

    # Montar dict => { (dow, faixa): total }
    from collections import defaultdict
    heatmap_dict = defaultdict(int)

    for row in results:
        dow = int(row.dow)
        h = int(row.hour)
        faixa = hour_to_faixa(h)
        heatmap_dict[(dow, faixa)] += row.count_leads

    # Montar lista final
    # Ex.: se quiser [ { "diaSemana": 1, "faixa": "8-10", "totalLeads": 25}, ... ]
    response = []
    for (dow, faixa), total_leads in heatmap_dict.items():
        response.append({
            "diaSemana": dow,       # 0=domingo, 1=segunda, etc.
            "faixa": faixa,
            "totalLeads": total_leads
        })

    # Se quiser ordenar: response.sort(key=lambda x: (x["diaSemana"], x["faixa"]))
    return response
