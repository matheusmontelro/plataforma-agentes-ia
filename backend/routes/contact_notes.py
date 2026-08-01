# backend/routes/contact_notes.py
import logging
from datetime import datetime, timezone
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel, Field

from ..db import get_db
from ..auth import get_current_user, User, Client
from ..models import ContactNote, Contact, User as UserModel, Client as ClientModel

# Import custom logger
try:
    from ..config_logging import api_logger as logger
except ImportError:
    logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic models
class NoteCreate(BaseModel):
    content: str = Field(..., min_length=1)

class NoteUpdate(BaseModel):
    content: str = Field(..., min_length=1)

class NoteResponse(BaseModel):
    id: int
    contact_id: int
    contact_name: str
    contact_phone: str
    content: str
    created_at: datetime
    updated_at: datetime
    created_by: dict

    class Config:
        from_attributes = True

def format_user(user: Union[UserModel, ClientModel, None]) -> dict:
    """Format user data for response - handles both User and Client types"""
    if user is None:
        return {
            "id": 0,
            "name": "Sistema",
            "email": "system@example.invalid",
            "type": "system"
        }

    if isinstance(user, ClientModel):
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "type": "client"
        }
    else:
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "type": "user"
        }

def format_note_response(note: ContactNote) -> NoteResponse:
    """Format note with all related data"""
    # Handle creator - could be a User or stored in metadata as Client
    created_by_info = None
    if note.creator:
        created_by_info = format_user(note.creator)
    elif note.note_metadata and 'created_by_client' in note.note_metadata:
        created_by_info = {
            **note.note_metadata['created_by_client'],
            'type': 'client'
        }

    # Ensure created_by is never None - provide default if missing
    if created_by_info is None:
        created_by_info = {
            "id": 0,
            "name": "Sistema",
            "email": "system@example.invalid",
            "type": "system"
        }

    return NoteResponse(
        id=note.id,
        contact_id=note.contact_id,
        contact_name=note.contact.name,
        contact_phone=note.contact.phone,
        content=note.content,
        created_at=note.created_at,
        updated_at=note.updated_at,
        created_by=created_by_info
    )

@router.get("/contacts/{contact_phone}/notes", response_model=List[NoteResponse])
async def get_contact_notes(
    contact_phone: str,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all notes for a specific contact"""
    # Verify contact exists and user has access
    contact = db.query(Contact).filter(
        Contact.phone == contact_phone,
        Contact.company_id == user.company_id
    ).first()

    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Get notes with relationships
    notes = db.query(ContactNote).filter(
        ContactNote.contact_id == contact.id,
        ContactNote.company_id == user.company_id
    ).options(
        joinedload(ContactNote.contact),
        joinedload(ContactNote.creator)
    ).order_by(ContactNote.created_at.desc()).all()

    return [format_note_response(note) for note in notes]

@router.post("/contacts/{contact_phone}/notes", response_model=NoteResponse)
async def create_note(
    contact_phone: str,
    note_data: NoteCreate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new note for a contact"""
    # Verify contact exists and user has access
    contact = db.query(Contact).filter(
        Contact.phone == contact_phone,
        Contact.company_id == user.company_id
    ).first()

    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Get creator info based on user type
    created_by_id = None
    note_metadata = None

    if isinstance(user, Client):
        # For Client, store in metadata field since created_by expects User ID
        note_metadata = {
            'created_by_client': {
                'id': user.id,
                'name': user.email,  # Client uses email as name
                'email': user.email
            }
        }
    else:
        created_by_id = user.id

    # Create note
    note = ContactNote(
        contact_id=contact.id,
        company_id=user.company_id,
        created_by=created_by_id,
        content=note_data.content,
        note_metadata=note_metadata
    )

    db.add(note)
    db.commit()
    db.refresh(note)

    # Load relationships
    note = db.query(ContactNote).options(
        joinedload(ContactNote.contact),
        joinedload(ContactNote.creator)
    ).filter(ContactNote.id == note.id).first()

    logger.info(f"Note created: {note.id} for contact {contact.id} by user {user.id}")

    return format_note_response(note)

@router.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: int,
    note_update: NoteUpdate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing note"""
    # Get note with relationships
    note = db.query(ContactNote).options(
        joinedload(ContactNote.contact),
        joinedload(ContactNote.creator)
    ).filter(
        ContactNote.id == note_id,
        ContactNote.company_id == user.company_id
    ).first()

    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Check if user can edit (only creator can edit)
    is_creator = False
    if isinstance(user, Client):
        # Check if this client created the note (stored in metadata)
        if note.note_metadata and 'created_by_client' in note.note_metadata:
            is_creator = note.note_metadata['created_by_client']['id'] == user.id
    else:
        # Regular user check
        is_creator = note.created_by == user.id

    if not is_creator and not getattr(user, 'is_master', False):
        raise HTTPException(status_code=403, detail="Only note creator or admin can edit")

    # Update content
    note.content = note_update.content
    note.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(note)

    logger.info(f"Note updated: {note_id} by user {user.id}")

    return format_note_response(note)

@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a note"""
    note = db.query(ContactNote).filter(
        ContactNote.id == note_id,
        ContactNote.company_id == user.company_id
    ).first()

    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Check if user can delete (only creator can delete)
    is_creator = False
    if isinstance(user, Client):
        # Check if this client created the note (stored in metadata)
        if note.note_metadata and 'created_by_client' in note.note_metadata:
            is_creator = note.note_metadata['created_by_client']['id'] == user.id
    else:
        # Regular user check
        is_creator = note.created_by == user.id

    if not is_creator and not getattr(user, 'is_master', False):
        raise HTTPException(status_code=403, detail="Only note creator or admin can delete")

    db.delete(note)
    db.commit()

    logger.info(f"Note deleted: {note_id} by user {user.id}")

    return {"success": True, "message": "Note deleted successfully"}

@router.get("/notes/all", response_model=List[NoteResponse])
async def get_all_user_notes(
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0
):
    """Get all notes created by the current user"""
    # Base query - notes in the user's company
    query = db.query(ContactNote).filter(
        ContactNote.company_id == user.company_id
    ).options(
        joinedload(ContactNote.contact),
        joinedload(ContactNote.creator)
    )

    # Filter by creator
    if isinstance(user, Client):
        # For Clients: check note_metadata for created_by_client
        query = query.filter(ContactNote.note_metadata.contains({'created_by_client': {'id': user.id}}))
    else:
        # For Users: standard filter
        query = query.filter(ContactNote.created_by == user.id)

    # Order by creation date (most recent first)
    notes = query.order_by(ContactNote.created_at.desc()).offset(offset).limit(limit).all()

    return [format_note_response(note) for note in notes]
