# backend/routes/arquivos.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from backend.db import get_db
from backend.auth import get_current_user, ensure_user_can_access_company
from backend.models import Client, MediaFile, FileType, User
from typing import List, Union
import os
from pathlib import Path
import uuid
from uuid import UUID
import shutil
from datetime import datetime
import logging
import mimetypes
from pydantic import BaseModel
from typing import Optional
from backend.runtime_settings import MEDIA_BASE_PATH

# Configuração do logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

router = APIRouter()

class MediaFileResponse(BaseModel):
    id: str
    file_name: str
    file_type: str
    mime_type: str
    file_size: int
    relative_path: str
    created_at: datetime

@router.post("/upload/{client_id}/{company_id}")
async def upload_file(
    client_id: int,
    company_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    try:
        ensure_user_can_access_company(current_user, company_id, db)
        if isinstance(current_user, Client) and current_user.id != client_id:
            raise HTTPException(status_code=403, detail="Acesso negado para este cliente")

        # Remova o logger que estava causando o erro
        logger.info(f"Iniciando upload - client_id: {client_id}, company_id: {company_id}")
        logger.info(f"Arquivo recebido - nome: {file.filename}, tipo: {file.content_type}")
        # Validar tipo de arquivo e tamanho
        content_type = file.content_type
        file_type = None

        if content_type.startswith('image/'):
            file_type = FileType.image
            max_size = 10 * 1024 * 1024  # 10MB
        elif content_type == 'video/mp4':
            file_type = FileType.video
            max_size = 15 * 1024 * 1024  # 15MB
        elif content_type == 'audio/mpeg':
            file_type = FileType.audio
            max_size = 15 * 1024 * 1024  # 15MB
        else:
            raise HTTPException(status_code=400, detail="Tipo de arquivo não suportado")

        # Criar estrutura de pastas
        file_dir = os.path.join(str(MEDIA_BASE_PATH), f"client_{client_id}", f"company_{company_id}", file_type.value)
        os.makedirs(file_dir, exist_ok=True)

        # Gerar nome único para o arquivo
        file_extension = mimetypes.guess_extension(content_type)
        file_name = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(file_dir, file_name)
        relative_path = os.path.join(f"client_{client_id}", f"company_{company_id}", file_type.value, file_name)

        # Salvar arquivo
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Criar registro no banco
        arquivos_file = MediaFile(
            client_id=client_id,
            company_id=company_id,
            file_name=file_name,
            original_name=file.filename,
            file_type=file_type,
            mime_type=content_type,
            file_size=os.path.getsize(file_path),
            file_path=file_path,
            relative_path=relative_path,
        )

        db.add(arquivos_file)
        db.commit()
        db.refresh(arquivos_file)

        return {"id": str(arquivos_file.id), "path": arquivos_file.relative_path}

    except Exception as e:
        logger.error(f"Erro detalhado no upload: {str(e)}")
        logger.exception(e)  # Isso vai logar o stack trace completo
        raise HTTPException(
            status_code=422,
            detail={"error": str(e), "context": "Upload falhou"}
        )

@router.get("/files/{client_id}/{company_id}", response_model=List[MediaFileResponse])
async def list_files(
    client_id: int,
    company_id: int,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    ensure_user_can_access_company(current_user, company_id, db)
    if isinstance(current_user, Client) and current_user.id != client_id:
        raise HTTPException(status_code=403, detail="Acesso negado para este cliente")

    files = db.query(MediaFile).filter(
        MediaFile.client_id == client_id,
        MediaFile.company_id == company_id
    ).all()

    return [MediaFileResponse(
        id=str(file.id),
        file_name=file.file_name,
        file_type=file.file_type.value,
        mime_type=file.mime_type,
        file_size=file.file_size,
        relative_path=file.relative_path,
        created_at=file.created_at,
    ) for file in files]

@router.delete("/files/{file_name}")
async def delete_file(
    file_name: str,
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user)
):
    """
    Deleta o arquivo buscando pelo file_name
    """
    try:
        safe_name = Path(file_name).name
        if safe_name != file_name:
            raise HTTPException(status_code=400, detail="Nome de arquivo inválido")

        # Busca pelo campo file_name (com extensão), ex: "c24465ac-...7007.jpg"
        file_record = db.query(MediaFile).filter(
            MediaFile.file_name == safe_name
        ).first()

        if not file_record:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        ensure_user_can_access_company(current_user, file_record.company_id, db)

        # Remove arquivo físico do disco
        if os.path.exists(file_record.file_path):
            os.remove(file_record.file_path)

        # Remove registro do banco
        db.delete(file_record)
        db.commit()

        return {"message": "Arquivo removido com sucesso"}

    except Exception as e:
        logger.error(f"Erro ao deletar arquivo: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/view/{company_id}/{client_id}/{file_name}")
async def serve_file_by_name(
    company_id: int,
    client_id: int,
    file_name: str,        # <--- agora é string, não UUID
    db: Session = Depends(get_db),
    current_user: Union[Client, User] = Depends(get_current_user),
):
    """
    Retorna o arquivo buscando pelo 'file_name' (e company_id / client_id),
    validando se o arquivo realmente pertence a esses IDs.
    """

    logger.info(
        "Iniciando serve_file_by_name com company_id=%d, client_id=%d, file_name=%s",
        company_id,
        client_id,
        file_name
    )
    ensure_user_can_access_company(current_user, company_id, db)
    if isinstance(current_user, Client) and current_user.id != client_id:
        raise HTTPException(status_code=403, detail="Acesso negado para este cliente")

    safe_name = Path(file_name).name
    if safe_name != file_name:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")

    # Consulta por file_name, company_id e client_id
    file_record = (
        db.query(MediaFile)
        .filter(
            MediaFile.file_name == safe_name,   # <--- filtra por file_name
            MediaFile.company_id == company_id,
            MediaFile.client_id == client_id
        )
        .first()
    )

    if not file_record:
        logger.warning(
            "Arquivo não encontrado no banco ou não pertence a company_id=%d, client_id=%d, file_name=%s",
            company_id,
            client_id,
            file_name
        )
        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado ou não pertence a esse company/client"
        )

    logger.info(
        "Arquivo encontrado no banco: file_name=%s, path=%s, mime=%s",
        file_record.file_name,
        file_record.file_path,
        file_record.mime_type
    )

    if not os.path.exists(file_record.file_path):
        logger.error(
            "Arquivo físico não encontrado no disco: %s",
            file_record.file_path
        )
        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado no disco"
        )

    logger.info(
        "Servindo arquivo '%s' para company_id=%d, client_id=%d",
        file_record.file_name,
        company_id,
        client_id
    )

    return FileResponse(
        file_record.file_path,
        media_type=file_record.mime_type,
        filename=file_record.original_name  # ou file_record.file_name
    )
