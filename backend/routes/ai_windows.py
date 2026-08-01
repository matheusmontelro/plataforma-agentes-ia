# backend/routes/ai_windows.py

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Dict

from backend.db import get_db
from backend.auth import get_current_user, ensure_user_can_access_company

# Importe os modelos Pydantic que representam
# os payloads de criação/atualização e a estrutura dos períodos:
from backend.models import (
    AIResponseWindowsCreate,
    AIResponseWindowsUpdate,
    DayTimeConfig
)

ai_windows_router = APIRouter()

@ai_windows_router.post("/ai-windows", response_model=dict)
def create_ai_window(
    payload: AIResponseWindowsCreate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Cria uma nova configuração de IA para horários de resposta,
    vinculada a uma company_id específica.

    Se você quiser APENAS 1 registro por empresa, verificar se já existe:
    """
    ensure_user_can_access_company(user, payload.company_id, db)

    row_exists = db.execute(
        text("SELECT id FROM ai_response_windows WHERE company_id = :cid"),
        {"cid": payload.company_id}
    ).fetchone()

    if row_exists:
        raise HTTPException(
            status_code=400,
            detail="Já existe configuração para esta empresa. Use PUT para atualizar."
        )

    insert_sql = text("""
        INSERT INTO ai_response_windows (company_id, timezone, time_windows)
        VALUES (:company_id, :tz, CAST(:tw AS jsonb))
        RETURNING id
    """)

    # time_windows -> payload.time_windows é um dict[str, DayTimeConfig].
    # Precisamos converter cada DayTimeConfig p/ dict normal,
    # depois serializar em JSON (str) antes de inserir no campo JSONB.
    tw_dict = {}
    for day_name, day_config in payload.time_windows.items():
        tw_dict[day_name] = day_config.dict()

    # Agora serializamos tw_dict para JSON:
    tw_json_str = json.dumps(tw_dict)

    result = db.execute(insert_sql, {
        "company_id": payload.company_id,
        "tz": payload.timezone,
        "tw": tw_json_str  # string JSON
    })
    new_id = result.fetchone()[0]
    db.commit()

    return {"id": new_id, "message": "Configuração criada com sucesso!"}


@ai_windows_router.get("/ai-windows/{company_id}", response_model=dict)
def get_ai_window(
    company_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Retorna a configuração de horários para a IA de uma empresa,
    buscando via company_id.
    """
    ensure_user_can_access_company(user, company_id, db)

    row = db.execute(
        text("""
            SELECT id, company_id, timezone, time_windows
              FROM ai_response_windows
             WHERE company_id = :cid
             ORDER BY id DESC
             LIMIT 1
        """),
        {"cid": company_id}
    ).fetchone()

    if not row:
        # Se não existir, podemos retornar um objeto "vazio" ou 404. Aqui retornamos "vazio":
        return {
            "id": None,
            "company_id": company_id,
            "timezone": "America/Sao_Paulo",
            "time_windows": {}
        }

    return {
        "id": row.id,
        "company_id": row.company_id,
        "timezone": row.timezone,
        "time_windows": row.time_windows,  # já é JSON do banco
    }


@ai_windows_router.put("/ai-windows/{id}", response_model=dict)
def update_ai_window(
    id: int,
    payload: AIResponseWindowsUpdate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Atualiza (parcial ou total) a configuração de horários da IA
    com base no ID do registro. O ID aqui não é o company_id, mas o PK da tabela.
    """
    row = db.execute(
        text("""
            SELECT id, company_id, timezone, time_windows
              FROM ai_response_windows
             WHERE id = :id
        """),
        {"id": id}
    ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Configuração não encontrada para este ID."
        )
    ensure_user_can_access_company(user, row.company_id, db)

    current_tz = row.timezone
    current_tw = row.time_windows  # Esse é um dict com a estrutura JSON do banco

    # Se payload.timezone foi enviado, substitui; senão mantemos o atual
    new_tz = payload.timezone if payload.timezone is not None else current_tz

    # Se payload.time_windows existe, converte cada DayTimeConfig -> dict; senão mantém o antigo
    if payload.time_windows is not None:
        new_tw = {}
        for day_name, day_config in payload.time_windows.items():
            new_tw[day_name] = day_config.dict()
    else:
        new_tw = current_tw

    # Precisamos novamente serializar em JSON para o campo JSONB
    new_tw_json_str = json.dumps(new_tw)

    update_sql = text("""
        UPDATE ai_response_windows
           SET timezone = :tz,
               time_windows = CAST(:tw AS jsonb),
               updated_at = NOW()
         WHERE id = :id
    """)

    db.execute(update_sql, {
        "tz": new_tz,
        "tw": new_tw_json_str,
        "id": id
    })
    db.commit()

    return {"message": "Configuração atualizada com sucesso."}


@ai_windows_router.delete("/ai-windows/{id}", response_model=dict)
def delete_ai_window(
    id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """
    Deleta a configuração de horários pelo ID (chave primária).
    """
    row = db.execute(
        text("SELECT id, company_id FROM ai_response_windows WHERE id = :id"),
        {"id": id}
    ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Configuração não encontrada para deletar."
        )
    ensure_user_can_access_company(user, row.company_id, db)

    db.execute(
        text("DELETE FROM ai_response_windows WHERE id = :id"),
        {"id": id}
    )

    db.commit()
    return {"message": "Configuração deletada com sucesso."}
