# backend/routes/revenue_metrics_routes.py
"""
API REST para Métricas de Receita.
Inspirado nas métricas do ChartMogul: MRR, ARR, LTV, Churn.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract, case
from typing import List, Optional
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta

from backend.db import get_db
from backend.auth import verify_client_or_bearer_api_key
from backend.models import Client
from backend.models.revenue_models import Contract, ContractItem, Invoice, Payment, Plan

logger = logging.getLogger("agentive.revenue_metrics")

router = APIRouter(
    prefix="/clients/{client_id}/companies/{company_id}/revenue",
    tags=["Revenue Metrics - Métricas de Receita"]
)


# -----------------------------------------------------------------------------
# Autenticação via API Key
# -----------------------------------------------------------------------------
async def verify_api_key(
    api_key: str = Header(..., alias="X-API-Key"),
    client_id: int = None,
    db: Session = Depends(get_db)
):
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key não fornecida"
        )

    client = db.query(Client).filter(
        Client.id == client_id,
        Client.api_key == api_key
    ).first()

    if not client:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida"
        )

    return client


# -----------------------------------------------------------------------------
# Schemas de Resposta
# -----------------------------------------------------------------------------

class RevenueSummary(BaseModel):
    """Resumo geral de receita."""
    total_contracts: int
    active_contracts: int
    total_value: Decimal
    total_paid: Decimal
    total_pending: Decimal
    average_contract_value: Decimal
    currency: str = "BRL"


class MRRMetrics(BaseModel):
    """Métricas de MRR (Monthly Recurring Revenue)."""
    mrr: Decimal
    mrr_growth: Optional[Decimal] = None
    mrr_growth_percent: Optional[Decimal] = None
    new_mrr: Decimal  # Novos contratos
    expansion_mrr: Decimal  # Upgrades (não implementado ainda)
    churned_mrr: Decimal  # Cancelamentos
    net_mrr: Decimal
    currency: str = "BRL"


class ARRMetrics(BaseModel):
    """Métricas de ARR (Annual Recurring Revenue)."""
    arr: Decimal
    arr_growth: Optional[Decimal] = None
    currency: str = "BRL"


class ChurnMetrics(BaseModel):
    """Métricas de Churn."""
    churned_contracts: int
    total_at_start: int
    churn_rate: Decimal  # Percentual
    churned_value: Decimal
    period_start: date
    period_end: date


class LTVMetrics(BaseModel):
    """Métricas de LTV (Lifetime Value)."""
    average_ltv: Decimal
    average_lifetime_days: int
    average_contract_value: Decimal
    total_customers: int
    currency: str = "BRL"


class RevenueByPeriod(BaseModel):
    """Receita por período."""
    period: str  # YYYY-MM
    total_value: Decimal
    total_paid: Decimal
    new_contracts: int
    canceled_contracts: int


class RevenueByPlan(BaseModel):
    """Receita por plano."""
    plan_id: Optional[int]
    plan_name: str
    total_value: Decimal
    contract_count: int
    average_value: Decimal


# -----------------------------------------------------------------------------
# Rotas de Métricas
# -----------------------------------------------------------------------------

@router.get("/summary", response_model=RevenueSummary)
async def resumo_receita(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Retorna resumo geral de receita da empresa.
    """
    logger.info(f"[resumo_receita] company_id={company_id}")

    try:
        # Totais de contratos
        total_contracts = db.query(func.count(Contract.id)).filter(
            Contract.company_id == company_id
        ).scalar() or 0

        active_contracts = db.query(func.count(Contract.id)).filter(
            Contract.company_id == company_id,
            Contract.status == "active"
        ).scalar() or 0

        # Valores
        values = db.query(
            func.coalesce(func.sum(Contract.total_value), 0).label('total_value'),
            func.coalesce(func.sum(Contract.total_paid), 0).label('total_paid')
        ).filter(
            Contract.company_id == company_id
        ).first()

        total_value = Decimal(str(values.total_value))
        total_paid = Decimal(str(values.total_paid))

        # Média
        avg_value = Decimal('0')
        if total_contracts > 0:
            avg_value = total_value / total_contracts

        return RevenueSummary(
            total_contracts=total_contracts,
            active_contracts=active_contracts,
            total_value=total_value,
            total_paid=total_paid,
            total_pending=total_value - total_paid,
            average_contract_value=avg_value.quantize(Decimal('0.01'))
        )

    except Exception as e:
        logger.exception("[resumo_receita] Erro")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mrr", response_model=MRRMetrics)
async def mrr_metrics(
    client_id: int,
    company_id: int,
    reference_date: Optional[date] = Query(None, description="Data de referência (default: hoje)"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Calcula MRR (Monthly Recurring Revenue).

    MRR é calculado somando valores de contratos ativos,
    normalizados para valor mensal baseado no billing_interval.
    """
    logger.info(f"[mrr_metrics] company_id={company_id}")

    ref_date = reference_date or date.today()
    prev_month = ref_date - relativedelta(months=1)

    try:
        # Função para calcular MRR de contratos
        def calculate_mrr_for_date(target_date: date) -> tuple:
            # Contratos ativos na data
            active_contracts = db.query(Contract).filter(
                Contract.company_id == company_id,
                Contract.status.in_(["active", "paused"]),
                Contract.start_date <= target_date
            ).all()

            total_mrr = Decimal('0')

            for contract in active_contracts:
                # Buscar itens do contrato
                items = db.query(ContractItem).filter(
                    ContractItem.contract_id == contract.id
                ).all()

                for item in items:
                    # Normalizar para valor mensal
                    if item.billing_interval == "monthly":
                        total_mrr += item.total_price
                    elif item.billing_interval == "quarterly":
                        total_mrr += item.total_price / 3
                    elif item.billing_interval == "yearly":
                        total_mrr += item.total_price / 12
                    elif item.billing_interval == "once":
                        # Tratamentos únicos: distribuir pelo período médio (12 meses)
                        # Ou ignorar se preferir MRR puro de recorrência
                        pass  # Não inclui one-time no MRR

            return total_mrr, len(active_contracts)

        # MRR atual
        current_mrr, _ = calculate_mrr_for_date(ref_date)

        # MRR mês anterior (para calcular growth)
        prev_mrr, _ = calculate_mrr_for_date(prev_month)

        # Novos contratos no mês atual
        month_start = ref_date.replace(day=1)
        new_contracts = db.query(Contract).filter(
            Contract.company_id == company_id,
            Contract.start_date >= month_start,
            Contract.start_date <= ref_date
        ).all()

        new_mrr = Decimal('0')
        for contract in new_contracts:
            items = db.query(ContractItem).filter(ContractItem.contract_id == contract.id).all()
            for item in items:
                if item.billing_interval == "monthly":
                    new_mrr += item.total_price
                elif item.billing_interval == "quarterly":
                    new_mrr += item.total_price / 3
                elif item.billing_interval == "yearly":
                    new_mrr += item.total_price / 12

        # Cancelamentos no mês
        churned = db.query(Contract).filter(
            Contract.company_id == company_id,
            Contract.status == "canceled",
            Contract.canceled_at >= month_start,
            func.date(Contract.canceled_at) <= ref_date
        ).all()

        churned_mrr = Decimal('0')
        for contract in churned:
            items = db.query(ContractItem).filter(ContractItem.contract_id == contract.id).all()
            for item in items:
                if item.billing_interval == "monthly":
                    churned_mrr += item.total_price
                elif item.billing_interval == "quarterly":
                    churned_mrr += item.total_price / 3
                elif item.billing_interval == "yearly":
                    churned_mrr += item.total_price / 12

        # Calcular growth
        mrr_growth = current_mrr - prev_mrr
        mrr_growth_percent = Decimal('0')
        if prev_mrr > 0:
            mrr_growth_percent = ((current_mrr - prev_mrr) / prev_mrr * 100).quantize(Decimal('0.01'))

        return MRRMetrics(
            mrr=current_mrr.quantize(Decimal('0.01')),
            mrr_growth=mrr_growth.quantize(Decimal('0.01')),
            mrr_growth_percent=mrr_growth_percent,
            new_mrr=new_mrr.quantize(Decimal('0.01')),
            expansion_mrr=Decimal('0'),  # TODO: implementar upgrades
            churned_mrr=churned_mrr.quantize(Decimal('0.01')),
            net_mrr=(new_mrr - churned_mrr).quantize(Decimal('0.01'))
        )

    except Exception as e:
        logger.exception("[mrr_metrics] Erro")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/arr", response_model=ARRMetrics)
async def arr_metrics(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Calcula ARR (Annual Recurring Revenue).

    ARR = MRR × 12
    """
    # Reaproveitar cálculo de MRR
    mrr_data = await mrr_metrics(client_id, company_id, None, db, _)

    arr = mrr_data.mrr * 12
    arr_growth = None
    if mrr_data.mrr_growth is not None:
        arr_growth = mrr_data.mrr_growth * 12

    return ARRMetrics(
        arr=arr.quantize(Decimal('0.01')),
        arr_growth=arr_growth.quantize(Decimal('0.01')) if arr_growth else None
    )


@router.get("/churn", response_model=ChurnMetrics)
async def churn_metrics(
    client_id: int,
    company_id: int,
    period_months: int = Query(default=1, ge=1, le=12, description="Período em meses"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Calcula taxa de Churn.

    Churn Rate = (Contratos cancelados no período / Contratos ativos no início) × 100
    """
    logger.info(f"[churn_metrics] company_id={company_id}, period_months={period_months}")

    today = date.today()
    period_start = today - relativedelta(months=period_months)

    try:
        # Contratos ativos no início do período
        active_at_start = db.query(func.count(Contract.id)).filter(
            Contract.company_id == company_id,
            Contract.start_date < period_start,
            (Contract.canceled_at.is_(None)) | (func.date(Contract.canceled_at) >= period_start)
        ).scalar() or 0

        # Contratos cancelados no período
        canceled_in_period = db.query(Contract).filter(
            Contract.company_id == company_id,
            Contract.status == "canceled",
            func.date(Contract.canceled_at) >= period_start,
            func.date(Contract.canceled_at) <= today
        ).all()

        churned_count = len(canceled_in_period)
        churned_value = sum(c.total_value for c in canceled_in_period)

        # Calcular taxa
        churn_rate = Decimal('0')
        if active_at_start > 0:
            churn_rate = (Decimal(str(churned_count)) / Decimal(str(active_at_start)) * 100).quantize(Decimal('0.01'))

        return ChurnMetrics(
            churned_contracts=churned_count,
            total_at_start=active_at_start,
            churn_rate=churn_rate,
            churned_value=churned_value,
            period_start=period_start,
            period_end=today
        )

    except Exception as e:
        logger.exception("[churn_metrics] Erro")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ltv", response_model=LTVMetrics)
async def ltv_metrics(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Calcula LTV (Lifetime Value).

    LTV = Receita média por contrato × Tempo médio de vida
    """
    logger.info(f"[ltv_metrics] company_id={company_id}")

    try:
        # Contratos completos ou cancelados (para calcular lifetime)
        finished_contracts = db.query(Contract).filter(
            Contract.company_id == company_id,
            Contract.status.in_(["completed", "canceled"])
        ).all()

        total_customers = len(finished_contracts)

        if total_customers == 0:
            # Se não há contratos finalizados, usar contratos ativos como aproximação
            active_contracts = db.query(Contract).filter(
                Contract.company_id == company_id,
                Contract.status == "active"
            ).all()

            if not active_contracts:
                return LTVMetrics(
                    average_ltv=Decimal('0'),
                    average_lifetime_days=0,
                    average_contract_value=Decimal('0'),
                    total_customers=0
                )

            avg_value = sum(c.total_paid for c in active_contracts) / len(active_contracts)
            avg_days = sum(
                (date.today() - c.start_date).days for c in active_contracts
            ) // len(active_contracts)

            return LTVMetrics(
                average_ltv=avg_value.quantize(Decimal('0.01')),
                average_lifetime_days=avg_days,
                average_contract_value=avg_value.quantize(Decimal('0.01')),
                total_customers=len(active_contracts)
            )

        # Calcular médias dos contratos finalizados
        total_revenue = sum(c.total_paid for c in finished_contracts)
        avg_value = total_revenue / total_customers

        # Calcular tempo médio de vida
        total_days = 0
        for c in finished_contracts:
            if c.canceled_at:
                end_date = c.canceled_at.date() if isinstance(c.canceled_at, datetime) else c.canceled_at
            else:
                end_date = c.end_date or date.today()
            lifetime = (end_date - c.start_date).days
            total_days += max(lifetime, 1)  # Mínimo 1 dia

        avg_days = total_days // total_customers

        return LTVMetrics(
            average_ltv=avg_value.quantize(Decimal('0.01')),
            average_lifetime_days=avg_days,
            average_contract_value=avg_value.quantize(Decimal('0.01')),
            total_customers=total_customers
        )

    except Exception as e:
        logger.exception("[ltv_metrics] Erro")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-period", response_model=List[RevenueByPeriod])
async def receita_por_periodo(
    client_id: int,
    company_id: int,
    months: int = Query(default=12, ge=1, le=24, description="Número de meses"),
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Retorna receita agrupada por mês.
    """
    logger.info(f"[receita_por_periodo] company_id={company_id}, months={months}")

    try:
        today = date.today()
        start_date = today - relativedelta(months=months-1)
        start_date = start_date.replace(day=1)

        result = []

        current = start_date
        while current <= today:
            month_end = (current + relativedelta(months=1)) - timedelta(days=1)

            period = current.strftime("%Y-%m")

            # Contratos do período
            contracts_in_period = db.query(Contract).filter(
                Contract.company_id == company_id,
                func.date(Contract.created_at) >= current,
                func.date(Contract.created_at) <= month_end
            ).all()

            total_value = sum(c.total_value for c in contracts_in_period)
            total_paid = sum(c.total_paid for c in contracts_in_period)
            new_count = len(contracts_in_period)

            # Cancelamentos do período
            canceled = db.query(func.count(Contract.id)).filter(
                Contract.company_id == company_id,
                Contract.status == "canceled",
                func.date(Contract.canceled_at) >= current,
                func.date(Contract.canceled_at) <= month_end
            ).scalar() or 0

            result.append(RevenueByPeriod(
                period=period,
                total_value=total_value,
                total_paid=total_paid,
                new_contracts=new_count,
                canceled_contracts=canceled
            ))

            current = current + relativedelta(months=1)

        return result

    except Exception as e:
        logger.exception("[receita_por_periodo] Erro")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-plan", response_model=List[RevenueByPlan])
async def receita_por_plano(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    _: Client = Depends(verify_client_or_bearer_api_key)
):
    """
    Retorna receita agrupada por plano.
    """
    logger.info(f"[receita_por_plano] company_id={company_id}")

    try:
        # Agrupar itens de contrato por plano
        items_by_plan = db.query(
            ContractItem.plan_id,
            func.sum(ContractItem.total_price).label('total_value'),
            func.count(func.distinct(ContractItem.contract_id)).label('contract_count')
        ).join(
            Contract, ContractItem.contract_id == Contract.id
        ).filter(
            Contract.company_id == company_id
        ).group_by(
            ContractItem.plan_id
        ).all()

        result = []

        for item in items_by_plan:
            plan_name = "Sem plano específico"

            if item.plan_id:
                plan = db.query(Plan).filter(Plan.id == item.plan_id).first()
                if plan:
                    plan_name = plan.name

            avg_value = Decimal('0')
            if item.contract_count > 0:
                avg_value = Decimal(str(item.total_value)) / item.contract_count

            result.append(RevenueByPlan(
                plan_id=item.plan_id,
                plan_name=plan_name,
                total_value=Decimal(str(item.total_value)),
                contract_count=item.contract_count,
                average_value=avg_value.quantize(Decimal('0.01'))
            ))

        # Ordenar por total_value desc
        result.sort(key=lambda x: x.total_value, reverse=True)

        return result

    except Exception as e:
        logger.exception("[receita_por_plano] Erro")
        raise HTTPException(status_code=500, detail=str(e))
