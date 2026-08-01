"""
Tags API Routes
CRUD operations for tag categories and tags, plus contact-tag associations
"""
import logging
from typing import Union, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from pydantic import BaseModel

from ..db import get_db
from ..auth import get_current_user, User, Client
from ..models import Tag, TagCategory, ContactTag, Contact

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Pydantic Schemas ====================

class TagCategoryCreate(BaseModel):
    company_id: int
    name: str
    color: str = "#6B7280"
    display_order: int = 0

class TagCategoryUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    display_order: Optional[int] = None

class TagCategoryResponse(BaseModel):
    id: int
    company_id: int
    name: str
    color: str
    display_order: int

    class Config:
        from_attributes = True

class TagCreate(BaseModel):
    company_id: int
    name: str
    color: str = "#49A5D9"
    category_id: Optional[int] = None

class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    category_id: Optional[int] = None

class TagResponse(BaseModel):
    id: int
    company_id: int
    name: str
    color: str
    category_id: Optional[int] = None
    category_name: Optional[str] = None

    class Config:
        from_attributes = True

class ContactTagsUpdate(BaseModel):
    tag_ids: List[int]


# ==================== Category Endpoints ====================

@router.get("/tag-categories")
async def list_tag_categories(
    company_id: int = Query(...),
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all tag categories for a company"""
    # Verify company access
    if hasattr(user, 'company_id') and user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    categories = db.query(TagCategory).filter(
        TagCategory.company_id == company_id
    ).order_by(TagCategory.display_order, TagCategory.name).all()

    return [
        {
            "id": cat.id,
            "company_id": cat.company_id,
            "name": cat.name,
            "color": cat.color,
            "display_order": cat.display_order
        }
        for cat in categories
    ]


@router.post("/tag-categories")
async def create_tag_category(
    data: TagCategoryCreate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new tag category"""
    if hasattr(user, 'company_id') and user.company_id != data.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    # Check for duplicate name
    existing = db.query(TagCategory).filter(
        TagCategory.company_id == data.company_id,
        TagCategory.name == data.name
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail=f"Categoria '{data.name}' já existe")

    category = TagCategory(
        company_id=data.company_id,
        name=data.name,
        color=data.color,
        display_order=data.display_order
    )

    db.add(category)
    db.commit()
    db.refresh(category)

    logger.info(f"[TAGS] Created category: {category.name} (ID: {category.id})")

    return {
        "id": category.id,
        "company_id": category.company_id,
        "name": category.name,
        "color": category.color,
        "display_order": category.display_order
    }


@router.put("/tag-categories/{category_id}")
async def update_tag_category(
    category_id: int,
    data: TagCategoryUpdate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a tag category"""
    category = db.query(TagCategory).filter(TagCategory.id == category_id).first()

    if not category:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    if hasattr(user, 'company_id') and user.company_id != category.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    if data.name is not None:
        # Check for duplicate name
        existing = db.query(TagCategory).filter(
            TagCategory.company_id == category.company_id,
            TagCategory.name == data.name,
            TagCategory.id != category_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Categoria '{data.name}' já existe")
        category.name = data.name

    if data.color is not None:
        category.color = data.color

    if data.display_order is not None:
        category.display_order = data.display_order

    db.commit()
    db.refresh(category)

    logger.info(f"[TAGS] Updated category: {category.name} (ID: {category.id})")

    return {
        "id": category.id,
        "company_id": category.company_id,
        "name": category.name,
        "color": category.color,
        "display_order": category.display_order
    }


@router.delete("/tag-categories/{category_id}")
async def delete_tag_category(
    category_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a tag category (tags will have category_id set to NULL)"""
    category = db.query(TagCategory).filter(TagCategory.id == category_id).first()

    if not category:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    if hasattr(user, 'company_id') and user.company_id != category.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    category_name = category.name
    db.delete(category)
    db.commit()

    logger.info(f"[TAGS] Deleted category: {category_name} (ID: {category_id})")

    return {"success": True, "message": f"Categoria '{category_name}' excluída"}


# ==================== Tag Endpoints ====================

@router.get("/tags")
async def list_tags(
    company_id: int = Query(...),
    category_id: Optional[int] = Query(None),
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all tags for a company, optionally filtered by category"""
    if hasattr(user, 'company_id') and user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    query = db.query(Tag).options(joinedload(Tag.category)).filter(Tag.company_id == company_id)

    if category_id is not None:
        query = query.filter(Tag.category_id == category_id)

    tags = query.order_by(Tag.name).all()

    return [
        {
            "id": tag.id,
            "company_id": tag.company_id,
            "name": tag.name,
            "color": tag.color,
            "category_id": tag.category_id,
            "category_name": tag.category.name if tag.category else None
        }
        for tag in tags
    ]


@router.post("/tags")
async def create_tag(
    data: TagCreate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new tag"""
    if hasattr(user, 'company_id') and user.company_id != data.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    # Check for duplicate name
    existing = db.query(Tag).filter(
        Tag.company_id == data.company_id,
        Tag.name == data.name
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail=f"Tag '{data.name}' já existe")

    # Validate category if provided
    if data.category_id:
        category = db.query(TagCategory).filter(
            TagCategory.id == data.category_id,
            TagCategory.company_id == data.company_id
        ).first()
        if not category:
            raise HTTPException(status_code=400, detail="Categoria não encontrada")

    tag = Tag(
        company_id=data.company_id,
        name=data.name,
        color=data.color,
        category_id=data.category_id
    )

    db.add(tag)
    db.commit()
    db.refresh(tag)

    logger.info(f"[TAGS] Created tag: {tag.name} (ID: {tag.id})")

    return {
        "id": tag.id,
        "company_id": tag.company_id,
        "name": tag.name,
        "color": tag.color,
        "category_id": tag.category_id,
        "category_name": tag.category.name if tag.category else None
    }


@router.put("/tags/{tag_id}")
async def update_tag(
    tag_id: int,
    data: TagUpdate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a tag"""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag não encontrada")

    if hasattr(user, 'company_id') and user.company_id != tag.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    if data.name is not None:
        existing = db.query(Tag).filter(
            Tag.company_id == tag.company_id,
            Tag.name == data.name,
            Tag.id != tag_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Tag '{data.name}' já existe")
        tag.name = data.name

    if data.color is not None:
        tag.color = data.color

    if data.category_id is not None:
        if data.category_id == 0:
            tag.category_id = None
        else:
            category = db.query(TagCategory).filter(
                TagCategory.id == data.category_id,
                TagCategory.company_id == tag.company_id
            ).first()
            if not category:
                raise HTTPException(status_code=400, detail="Categoria não encontrada")
            tag.category_id = data.category_id

    db.commit()
    db.refresh(tag)

    logger.info(f"[TAGS] Updated tag: {tag.name} (ID: {tag.id})")

    return {
        "id": tag.id,
        "company_id": tag.company_id,
        "name": tag.name,
        "color": tag.color,
        "category_id": tag.category_id,
        "category_name": tag.category.name if tag.category else None
    }


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a tag"""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag não encontrada")

    if hasattr(user, 'company_id') and user.company_id != tag.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    tag_name = tag.name
    db.delete(tag)
    db.commit()

    logger.info(f"[TAGS] Deleted tag: {tag_name} (ID: {tag_id})")

    return {"success": True, "message": f"Tag '{tag_name}' excluída"}


# ==================== Contact-Tag Association Endpoints ====================

@router.get("/contacts/{contact_id}/tags")
async def get_contact_tags(
    contact_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all tags for a contact"""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()

    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    if hasattr(user, 'company_id') and user.company_id != contact.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    contact_tags = db.query(ContactTag).options(
        joinedload(ContactTag.tag).joinedload(Tag.category)
    ).filter(ContactTag.contact_id == contact_id).all()

    return [
        {
            "id": ct.tag.id,
            "name": ct.tag.name,
            "color": ct.tag.color,
            "category_id": ct.tag.category_id,
            "category_name": ct.tag.category.name if ct.tag.category else None
        }
        for ct in contact_tags
    ]


@router.post("/contacts/{contact_id}/tags")
async def add_tags_to_contact(
    contact_id: int,
    data: ContactTagsUpdate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add tags to a contact (replaces existing tags)"""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()

    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    if hasattr(user, 'company_id') and user.company_id != contact.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    # Validate all tags exist and belong to the same company
    tags = db.query(Tag).filter(
        Tag.id.in_(data.tag_ids),
        Tag.company_id == contact.company_id
    ).all()

    if len(tags) != len(data.tag_ids):
        raise HTTPException(status_code=400, detail="Uma ou mais tags não encontradas")

    # Remove existing tags
    db.query(ContactTag).filter(ContactTag.contact_id == contact_id).delete()

    # Add new tags
    for tag_id in data.tag_ids:
        contact_tag = ContactTag(contact_id=contact_id, tag_id=tag_id)
        db.add(contact_tag)

    db.commit()

    logger.info(f"[TAGS] Updated tags for contact {contact_id}: {data.tag_ids}")

    return {"success": True, "message": f"{len(data.tag_ids)} tags atualizadas"}


@router.delete("/contacts/{contact_id}/tags/{tag_id}")
async def remove_tag_from_contact(
    contact_id: int,
    tag_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a specific tag from a contact"""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()

    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    if hasattr(user, 'company_id') and user.company_id != contact.company_id:
        raise HTTPException(status_code=403, detail="Acesso negado à empresa")

    contact_tag = db.query(ContactTag).filter(
        ContactTag.contact_id == contact_id,
        ContactTag.tag_id == tag_id
    ).first()

    if not contact_tag:
        raise HTTPException(status_code=404, detail="Tag não está associada ao contato")

    db.delete(contact_tag)
    db.commit()

    logger.info(f"[TAGS] Removed tag {tag_id} from contact {contact_id}")

    return {"success": True, "message": "Tag removida do contato"}
