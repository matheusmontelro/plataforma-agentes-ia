from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.db import get_db
from backend.models import AdCampaignInvestmentPayload

router = APIRouter()

@router.get("/metrics/ad_campaigns")
def get_ad_campaign_performance(
    company_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:

    from datetime import datetime, timedelta
    parsed_start = None
    parsed_end = None
    if start_date:
        parsed_start = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        parsed_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

    sql = text("""
    WITH investment_sub AS (
        SELECT
          source_id,
          company_id,
          SUM(aci.investment) AS total_investment
        FROM ad_campaign_investment aci
        WHERE company_id = :company_id
          AND (:start_date IS NOT NULL OR :end_date IS NOT NULL)
          AND date_trunc('month', aci.reference_month) >= date_trunc('month', :start_date)
          AND date_trunc('month', aci.reference_month) <  date_trunc('month', :end_date)
        GROUP BY company_id, source_id
    )

    SELECT
      acm.id AS ad_id,
      acm.source_id,
      acm.file_name,
      acm.file_path,

      COUNT(DISTINCT l.id) AS total_leads,
      COUNT(DISTINCT a.id) AS total_agendamentos,
      COUNT(DISTINCT c.id) AS total_comparecimentos,
      COUNT(DISTINCT v.id) AS total_vendas,

      COALESCE(SUM(v.valor_faturado), 0) AS total_faturado,
      COALESCE(SUM(v.valor_pago), 0) AS total_valor_pago,
      COALESCE(SUM(v.valor_faturado), 0) AS total_valor_vendido,

      CASE
        WHEN COUNT(DISTINCT v.id)=0 THEN 0
        ELSE ROUND(SUM(v.valor_faturado)::numeric / COUNT(DISTINCT v.id), 2)
      END AS ticket_medio,

      COALESCE(isub.total_investment, 0) AS investment,

      CASE
        WHEN COALESCE(isub.total_investment, 0) = 0 THEN 0
        ELSE ROUND(SUM(v.valor_pago)::numeric / isub.total_investment, 2)
      END AS roas

    FROM ad_campaign_media acm
    LEFT JOIN leads l
           ON l.source_id = acm.source_id
          AND l.company_id = acm.company_id
          AND (:start_date IS NULL OR l.data_entrada >= :start_date)
          AND (:end_date   IS NULL OR l.data_entrada <  :end_date)

    LEFT JOIN agendamentos a
           ON a.lead_id = l.id
          AND (:start_date IS NULL OR a.consulta_data >= :start_date)
          AND (:end_date   IS NULL OR a.consulta_data <  :end_date)

    LEFT JOIN comparecimentos c
           ON c.lead_id = l.id
          AND (:start_date IS NULL OR c.compareceu_em >= :start_date)
          AND (:end_date   IS NULL OR c.compareceu_em <  :end_date)

    LEFT JOIN vendas v
           ON v.lead_id = l.id
          AND (:start_date IS NULL OR v.venda_data >= :start_date)
          AND (:end_date   IS NULL OR v.venda_data <  :end_date)

    LEFT JOIN investment_sub isub
           ON isub.source_id = acm.source_id
          AND isub.company_id = acm.company_id

    WHERE acm.company_id = :company_id
    GROUP BY acm.id, acm.source_id, acm.file_name, acm.file_path, isub.total_investment
    ORDER BY total_leads DESC
    """)

    rows = db.execute(sql, {
        "company_id": company_id,
        "start_date": parsed_start,
        "end_date": parsed_end
    }).fetchall()

    result = []
    for row in rows:
        result.append({
            "adId": row.ad_id,
            "sourceId": row.source_id,
            "fileName": row.file_name,
            "filePath": row.file_path,
            "totalLeads": int(row.total_leads or 0),
            "totalAgendamentos": int(row.total_agendamentos or 0),
            "totalComparecimentos": int(row.total_comparecimentos or 0),
            "totalVendas": int(row.total_vendas or 0),
            "valorFaturado": float(row.total_faturado or 0),
            "valorPago": float(row.total_valor_pago or 0),
            "valorVendido": float(row.total_valor_vendido or 0),
            "ticketMedio": float(row.ticket_medio or 0),
            "investment": float(row.investment or 0),
            "roas": float(row.roas or 0)
        })

    return result

@router.get("/metrics/ad_campaigns/media/{ad_id}")
def get_ad_campaign_media_image(
    ad_id: int,
    db: Session = Depends(get_db),
):
    """
    Serve a imagem do ad_campaign_media, se existir.
    """
    import os
    from fastapi.responses import FileResponse

    row = db.execute(
        text("SELECT file_path FROM ad_campaign_media WHERE id = :ad_id"),
        {"ad_id": ad_id}
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")

    file_path = row.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no servidor.")

    return FileResponse(path=file_path, media_type="image/jpeg")


@router.post("/metrics/ad_campaigns/investment")
def set_ad_campaign_investment(
    payload: AdCampaignInvestmentPayload,
    db: Session = Depends(get_db)
):
    """
    Armazena investimento mensal (reference_month) em ad_campaign_investment.
    Recebe via body JSON:
    {
      "company_id": 1,
      "source_id": "xyz",
      "investment": 500.0,
      "reference_month": "2025-03-20"
    }
    """
    sql = text("""
        INSERT INTO ad_campaign_investment
            (company_id, source_id, investment, reference_month)
        VALUES (:company_id, :source_id, :investment, :reference_month)
        ON CONFLICT (company_id, source_id, reference_month)
        DO UPDATE SET investment = EXCLUDED.investment, updated_at = now()
    """)

    db.execute(sql, {
        "company_id": payload.company_id,
        "source_id": payload.source_id,
        "investment": payload.investment,
        "reference_month": payload.reference_month
    })
    db.commit()

    return {"message": "Valor de investimento (mensal) atualizado com sucesso."}
