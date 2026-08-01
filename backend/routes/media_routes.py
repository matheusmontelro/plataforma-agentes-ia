from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from backend.db import get_db
from backend.models import MediaSource, User
from backend.auth import get_current_user

router = APIRouter(
    prefix="/media-sources",
    tags=["media-sources"]
)

# Pydantic Models
class MediaSourceBase(BaseModel):
    name: str
    active: bool = True

class MediaSourceCreate(MediaSourceBase):
    pass

class MediaSourceUpdate(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None

class MediaSourceResponse(MediaSourceBase):
    id: int
    company_id: int

    class Config:
        from_attributes = True

@router.get("/", response_model=List[MediaSourceResponse])
def get_media_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = current_user.company_id
    start_sources = ["Facebook", "Instagram", "Google", "Indicação", "Outros"]

    # Check if we need to seed default sources
    existing = db.query(MediaSource).filter(MediaSource.company_id == company_id).first()
    if not existing:
        for name in start_sources:
            db.add(MediaSource(company_id=company_id, name=name))
        db.commit()

    return db.query(MediaSource).filter(MediaSource.company_id == company_id).order_by(MediaSource.name).all()

@router.post("/", response_model=MediaSourceResponse)
def create_media_source(
    source: MediaSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = current_user.company_id

    # Check duplicate
    existing = db.query(MediaSource).filter(
        MediaSource.company_id == company_id,
        MediaSource.name == source.name
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Mídia já existe")

    new_source = MediaSource(
        company_id=company_id,
        name=source.name,
        active=source.active
    )
    db.add(new_source)
    db.commit()
    db.refresh(new_source)
    return new_source

@router.put("/{source_id}", response_model=MediaSourceResponse)
def update_media_source(
    source_id: int,
    source: MediaSourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = current_user.company_id
    db_source = db.query(MediaSource).filter(
        MediaSource.id == source_id,
        MediaSource.company_id == company_id
    ).first()

    if not db_source:
        raise HTTPException(status_code=404, detail="Mídia não encontrada")

    if source.name is not None:
        # Check duplicate name if changing name
        if source.name != db_source.name:
            existing = db.query(MediaSource).filter(
                MediaSource.company_id == company_id,
                MediaSource.name == source.name
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Já existe uma mídia com este nome")
        db_source.name = source.name

    if source.active is not None:
        db_source.active = source.active

    db.commit()
    db.refresh(db_source)
    return db_source

@router.delete("/{source_id}")
def delete_media_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = current_user.company_id
    db_source = db.query(MediaSource).filter(
        MediaSource.id == source_id,
        MediaSource.company_id == company_id
    ).first()

    if not db_source:
        raise HTTPException(status_code=404, detail="Mídia não encontrada")

    db.delete(db_source)
    db.commit()
    return {"message": "Mídia removida com sucesso"}
