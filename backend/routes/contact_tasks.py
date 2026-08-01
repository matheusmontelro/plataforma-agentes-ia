# backend/routes/contact_tasks.py
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func, text
from pydantic import BaseModel, Field
import pytz

from ..db import get_db
from ..auth import get_current_user, User, Client, verify_company_access
from ..models import ContactTask, ContactTaskComment, Contact, User as UserModel, Client as ClientModel
from ..services.company_access_control import (
    CompanyOperationallyBlockedError,
    enqueue_company_job_if_active,
    fence_company_job_mutation,
)

# Import custom logger
try:
    from ..config_logging import api_logger as logger
except ImportError:
    logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic models
class TaskCreate(BaseModel):
    task_type: str = Field(..., pattern="^(message|call|email|scheduled_message)$")
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    scheduled_for: datetime
    reminder_minutes: int = Field(default=15, ge=0)
    assigned_to: Optional[int] = None
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")
    tags: Optional[List[str]] = None
    task_metadata: Optional[dict] = None
    # Campos para mensagem agendada
    message_type: Optional[str] = Field(None, pattern="^(text|image|audio|video)$")
    message_content: Optional[str] = None
    message_file_path: Optional[str] = None

class TaskUpdate(BaseModel):
    task_type: Optional[str] = Field(None, pattern="^(message|call|email|scheduled_message)$")
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    reminder_minutes: Optional[int] = Field(None, ge=0)
    assigned_to: Optional[int] = None
    status: Optional[str] = Field(None, pattern="^(pending|in_progress|completed|canceled)$")
    priority: Optional[str] = Field(None, pattern="^(low|medium|high|urgent)$")
    tags: Optional[List[str]] = None
    task_metadata: Optional[dict] = None
    # Campos para mensagem agendada
    message_type: Optional[str] = Field(None, pattern="^(text|image|audio|video)$")
    message_content: Optional[str] = None
    message_file_path: Optional[str] = None

class CommentCreate(BaseModel):
    comment: str = Field(..., min_length=1)

class TaskResponse(BaseModel):
    id: int
    contact_id: int
    contact_name: str
    contact_phone: str
    task_type: str
    title: str
    description: Optional[str]
    scheduled_for: datetime
    reminder_minutes: int
    status: str
    priority: str
    tags: Optional[List[str]]
    task_metadata: Optional[dict]
    created_at: datetime
    updated_at: datetime
    created_by: dict
    assigned_to: Optional[dict]
    completed_at: Optional[datetime]
    completed_by: Optional[dict]
    comments_count: int

    class Config:
        from_attributes = True

def format_user(user: Union[UserModel, ClientModel, None]) -> dict:
    """Format user data for response - handles both User and Client types"""
    if user is None:
        return None

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

def format_task_response(task: ContactTask, db: Session) -> TaskResponse:
    """Format task with all related data"""
    comments_count = db.query(func.count(ContactTaskComment.id)).filter(
        ContactTaskComment.task_id == task.id
    ).scalar()

    # Handle creator - could be a User or stored in metadata as Client
    created_by_info = None
    if task.creator:
        created_by_info = format_user(task.creator)
    elif task.task_metadata and 'created_by_client' in task.task_metadata:
        created_by_info = {
            **task.task_metadata['created_by_client'],
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

    return TaskResponse(
        id=task.id,
        contact_id=task.contact_id,
        contact_name=task.contact.name,
        contact_phone=task.contact.phone,
        task_type=task.task_type,
        title=task.title,
        description=task.description,
        scheduled_for=task.scheduled_for,
        reminder_minutes=task.reminder_minutes,
        status=task.status,
        priority=task.priority,
        tags=task.tags,
        task_metadata=task.task_metadata,
        created_at=task.created_at,
        updated_at=task.updated_at,
        created_by=created_by_info,
        assigned_to=format_user(task.assignee) if task.assignee else None,
        completed_at=task.completed_at,
        completed_by=format_user(task.completer) if task.completer else (
            {**task.task_metadata['completed_by_client'], 'type': 'client'}
            if task.task_metadata and 'completed_by_client' in task.task_metadata
            else None
        ),
        comments_count=comments_count
    )

@router.get("/contacts/{contact_phone}/tasks", response_model=List[TaskResponse])
async def get_contact_tasks(
    contact_phone: str,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, pattern="^(pending|in_progress|completed|canceled)$"),
    priority: Optional[str] = Query(None, pattern="^(low|medium|high|urgent)$"),
    task_type: Optional[str] = Query(None, pattern="^(message|call|email|custom)$"),
    assigned_to_me: bool = Query(False)
):
    """Get all tasks for a specific contact"""
    # Verify contact exists and user has access
    contact = db.query(Contact).filter(
        Contact.phone == contact_phone,
        Contact.company_id == user.company_id
    ).first()

    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Build query
    query = db.query(ContactTask).filter(
        ContactTask.contact_id == contact.id,
        ContactTask.company_id == user.company_id
    ).options(
        joinedload(ContactTask.contact),
        joinedload(ContactTask.creator),
        joinedload(ContactTask.assignee),
        joinedload(ContactTask.completer)
    )

    # Apply filters
    if status:
        query = query.filter(ContactTask.status == status)
    if priority:
        query = query.filter(ContactTask.priority == priority)
    if task_type:
        query = query.filter(ContactTask.task_type == task_type)
    if assigned_to_me:
        query = query.filter(ContactTask.assigned_to == user.id)

    # Order by scheduled date
    tasks = query.order_by(ContactTask.scheduled_for.asc()).all()

    return [format_task_response(task, db) for task in tasks]

@router.post("/contacts/{contact_phone}/tasks", response_model=TaskResponse)
async def create_task(
    contact_phone: str,
    task_data: TaskCreate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_timezone: Optional[str] = Header(None)
):
    """Create a new task for a contact"""
    # Verify contact exists and user has access
    contact = db.query(Contact).filter(
        Contact.phone == contact_phone,
        Contact.company_id == user.company_id
    ).first()

    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Verify assigned user if provided
    if task_data.assigned_to:
        assigned_user = db.query(UserModel).filter(
            UserModel.id == task_data.assigned_to,
            UserModel.company_id == user.company_id
        ).first()
        if not assigned_user:
            raise HTTPException(status_code=404, detail="Assigned user not found")

    # Create task
    task_dict = task_data.dict()
    task_dict.pop('contact_id', None)  # Remove contact_id if present

    # Handle timezone conversion
    if task_dict.get('scheduled_for'):
        scheduled_dt = task_dict['scheduled_for']

        logger.info(f"Received scheduled_for: {scheduled_dt}, timezone header: {x_timezone}")

        # If client sent timezone header and datetime is naive
        if x_timezone and not scheduled_dt.tzinfo:
            try:
                # Parse the timezone
                client_tz = pytz.timezone(x_timezone)
                # Localize the naive datetime to client timezone
                localized_dt = client_tz.localize(scheduled_dt)
                # Convert to UTC
                task_dict['scheduled_for'] = localized_dt.astimezone(pytz.UTC)
                logger.info(f"Converted to UTC: {task_dict['scheduled_for']}")
            except Exception as e:
                logger.warning(f"Failed to parse timezone {x_timezone}: {e}")
                # Fallback: assume UTC
                task_dict['scheduled_for'] = scheduled_dt.replace(tzinfo=timezone.utc)
        elif not scheduled_dt.tzinfo:
            # No timezone info, assume UTC
            task_dict['scheduled_for'] = scheduled_dt.replace(tzinfo=timezone.utc)
            logger.info(f"No timezone header, assumed UTC: {task_dict['scheduled_for']}")

    # Get creator info based on user type
    creator_info = None
    if isinstance(user, Client):
        # For Client, store in a metadata field since created_by expects User ID
        task_dict['task_metadata'] = task_dict.get('task_metadata', {}) or {}
        task_dict['task_metadata']['created_by_client'] = {
            'id': user.id,
            'name': user.email,  # Client uses email as name
            'email': user.email
        }
        # Use a system user ID or NULL for created_by field
        created_by_id = None
    else:
        created_by_id = user.id

    if task_data.task_type == "scheduled_message":
        try:
            fence_company_job_mutation(db, int(user.company_id))
        except CompanyOperationallyBlockedError as exc:
            raise HTTPException(status_code=423, detail="Acesso da empresa suspenso") from exc

    task = ContactTask(
        contact_id=contact.id,
        company_id=user.company_id,
        created_by=created_by_id,
        **task_dict
    )

    db.add(task)
    db.commit()
    db.refresh(task)

    # Agendar task Celery para mensagem agendada
    if task_data.task_type == 'scheduled_message':
        # Validações específicas para mensagem agendada
        if not task_data.message_type:
            raise HTTPException(status_code=400, detail="message_type é obrigatório para mensagem agendada")

        if task_data.message_type == 'text' and not task_data.message_content:
            raise HTTPException(status_code=400, detail="message_content é obrigatório para mensagem de texto")

        if task_data.message_type in ['image', 'audio', 'video'] and not task_data.message_file_path:
            raise HTTPException(status_code=400, detail="message_file_path é obrigatório para mensagem de mídia")

        try:
            from backend.worker.tasks_scheduled_messages import enviar_mensagem_agendada

            enqueued, _ = enqueue_company_job_if_active(
                db,
                int(task.company_id),
                is_still_pending=lambda: (
                    db.query(ContactTask.status)
                    .filter(ContactTask.id == task.id)
                    .scalar()
                    == "pending"
                ),
                enqueue=lambda: enviar_mensagem_agendada.apply_async(
                    args=[task.id],
                    eta=task.scheduled_for,
                ),
            )
            if not enqueued:
                raise HTTPException(status_code=423, detail="Mensagem cancelada por suspensão de acesso")
            logger.info(f"Mensagem agendada para task {task.id} em {task.scheduled_for}")

        except CompanyOperationallyBlockedError as exc:
            raise HTTPException(status_code=423, detail="Acesso da empresa suspenso") from exc
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Erro ao agendar mensagem para task {task.id}: {str(e)}")
            # Não falha a criação da task, apenas loga o erro

    # Load relationships
    db.query(ContactTask).options(
        joinedload(ContactTask.contact),
        joinedload(ContactTask.creator),
        joinedload(ContactTask.assignee),
        joinedload(ContactTask.completer)
    ).filter(ContactTask.id == task.id).first()

    logger.info(f"Task created: {task.id} for contact {contact.id} by user {user.id}")

    return format_task_response(task, db)

@router.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    task_update: TaskUpdate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing task"""
    # Get task with relationships
    task = db.query(ContactTask).options(
        joinedload(ContactTask.contact),
        joinedload(ContactTask.creator),
        joinedload(ContactTask.assignee),
        joinedload(ContactTask.completer)
    ).filter(
        ContactTask.id == task_id,
        ContactTask.company_id == user.company_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Update fields
    update_data = task_update.dict(exclude_unset=True)

    # Handle status changes
    if "status" in update_data:
        if update_data["status"] == "completed" and task.status != "completed":
            update_data["completed_at"] = datetime.now(timezone.utc)
            if isinstance(user, Client):
                # Store client info in metadata for completed_by
                if not task.task_metadata:
                    task.task_metadata = {}
                task.task_metadata['completed_by_client'] = {
                    'id': user.id,
                    'name': user.email,  # Client uses email as name
                    'email': user.email
                }
                update_data["completed_by"] = None
            else:
                update_data["completed_by"] = user.id
        elif update_data["status"] != "completed" and task.status == "completed":
            update_data["completed_at"] = None
            update_data["completed_by"] = None
            if task.task_metadata and 'completed_by_client' in task.task_metadata:
                del task.task_metadata['completed_by_client']

    # Verify assigned user if being updated
    if "assigned_to" in update_data and update_data["assigned_to"]:
        assigned_user = db.query(UserModel).filter(
            UserModel.id == update_data["assigned_to"],
            UserModel.company_id == user.company_id
        ).first()
        if not assigned_user:
            raise HTTPException(status_code=404, detail="Assigned user not found")

    # Apply updates
    for field, value in update_data.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)

    logger.info(f"Task updated: {task_id} by user {user.id}")

    return format_task_response(task, db)

@router.post("/tasks/{task_id}/complete", response_model=TaskResponse)
async def complete_task(
    task_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark a task as completed"""
    task = db.query(ContactTask).options(
        joinedload(ContactTask.contact),
        joinedload(ContactTask.creator),
        joinedload(ContactTask.assignee),
        joinedload(ContactTask.completer)
    ).filter(
        ContactTask.id == task_id,
        ContactTask.company_id == user.company_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "completed":
        raise HTTPException(status_code=400, detail="Task is already completed")

    task.status = "completed"
    task.completed_at = datetime.now(timezone.utc)

    if isinstance(user, Client):
        # Store client info in metadata for completed_by
        if not task.task_metadata:
            task.task_metadata = {}
        task.task_metadata['completed_by_client'] = {
            'id': user.id,
            'name': user.email,  # Client uses email as name
            'email': user.email
        }
        task.completed_by = None
    else:
        task.completed_by = user.id

    db.commit()
    db.refresh(task)

    logger.info(f"Task completed: {task_id} by user {user.id}")

    return format_task_response(task, db)

@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a task"""
    task = db.query(ContactTask).filter(
        ContactTask.id == task_id,
        ContactTask.company_id == user.company_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Only creator or admin can delete
    is_creator = False

    if isinstance(user, Client):
        # Check if this client created the task (stored in metadata)
        if task.task_metadata and 'created_by_client' in task.task_metadata:
            is_creator = task.task_metadata['created_by_client']['id'] == user.id
    else:
        # Regular user check
        is_creator = task.created_by == user.id

    if not is_creator and not getattr(user, 'is_master', False):
        raise HTTPException(status_code=403, detail="Only task creator or admin can delete")

    db.delete(task)
    db.commit()

    logger.info(f"Task deleted: {task_id} by user {user.id}")

    return {"success": True, "message": "Task deleted successfully"}

@router.get("/tasks/upcoming", response_model=List[TaskResponse])
async def get_upcoming_tasks(
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=100),
    include_overdue: bool = Query(True),
    assigned_to_me: bool = Query(False)
):
    """Get upcoming tasks for the current user"""
    query = db.query(ContactTask).filter(
        ContactTask.company_id == user.company_id,
        ContactTask.status.in_(["pending", "in_progress"])
    ).options(
        joinedload(ContactTask.contact),
        joinedload(ContactTask.creator),
        joinedload(ContactTask.assignee),
        joinedload(ContactTask.completer)
    )

    # Filter by assignment
    if assigned_to_me:
        query = query.filter(ContactTask.assigned_to == user.id)

    # Filter by time
    if not include_overdue:
        query = query.filter(ContactTask.scheduled_for >= datetime.now(timezone.utc))

    # Order by scheduled date and priority
    tasks = query.order_by(
        ContactTask.scheduled_for.asc(),
        func.field(ContactTask.priority, 'urgent', 'high', 'medium', 'low')
    ).limit(limit).all()

    return [format_task_response(task, db) for task in tasks]

@router.post("/tasks/{task_id}/comments")
async def add_task_comment(
    task_id: int,
    comment_data: CommentCreate,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a comment to a task"""
    # Verify task exists and user has access
    task = db.query(ContactTask).filter(
        ContactTask.id == task_id,
        ContactTask.company_id == user.company_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Create comment
    comment = ContactTaskComment(
        task_id=task_id,
        user_id=user.id,
        comment=comment_data.comment
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    logger.info(f"Comment added to task {task_id} by user {user.id}")

    return {
        "id": comment.id,
        "comment": comment.comment,
        "created_at": comment.created_at,
        "user": format_user(comment.user)
    }

@router.get("/tasks/{task_id}/comments")
async def get_task_comments(
    task_id: int,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all comments for a task"""
    # Verify task exists and user has access
    task = db.query(ContactTask).filter(
        ContactTask.id == task_id,
        ContactTask.company_id == user.company_id
    ).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Get comments with user info
    comments = db.query(ContactTaskComment).filter(
        ContactTaskComment.task_id == task_id
    ).options(
        joinedload(ContactTaskComment.user)
    ).order_by(ContactTaskComment.created_at.desc()).all()

    return [{
        "id": comment.id,
        "comment": comment.comment,
        "created_at": comment.created_at,
        "user": format_user(comment.user)
    } for comment in comments]

@router.get("/tasks/all", response_model=List[TaskResponse])
async def get_all_user_tasks(
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, pattern="^(pending|in_progress|completed|canceled)$"),
    priority: Optional[str] = Query(None, pattern="^(low|medium|high|urgent)$"),
    task_type: Optional[str] = Query(None, pattern="^(message|call|email|custom)$"),
    search: Optional[str] = Query(None),
    overdue: Optional[bool] = Query(None, description="Filter overdue tasks only"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """Get all tasks created by or assigned to the current user"""
    # Base query - tasks in the user's company
    query = db.query(ContactTask).filter(
        ContactTask.company_id == user.company_id
    ).options(
        joinedload(ContactTask.contact),
        joinedload(ContactTask.creator),
        joinedload(ContactTask.assignee),
        joinedload(ContactTask.completer)
    )

    # Filter by creator OR assignee (tasks created by user or assigned to user)
    # Also include orphaned tasks (created_by = None AND assigned_to = None)
    if isinstance(user, Client):
        # For Clients: check created_by, assigned_to, metadata, or orphaned tasks
        query = query.filter(
            or_(
                ContactTask.created_by == user.id,
                ContactTask.assigned_to == user.id,
                ContactTask.task_metadata.contains({'created_by_client': {'id': user.id}}),
                and_(ContactTask.created_by.is_(None), ContactTask.assigned_to.is_(None))
            )
        )
    else:
        # For Users: standard filter + orphaned tasks
        query = query.filter(
            or_(
                ContactTask.created_by == user.id,
                ContactTask.assigned_to == user.id,
                and_(ContactTask.created_by.is_(None), ContactTask.assigned_to.is_(None))
            )
        )

    # Apply overdue filter (takes precedence over status filter)
    if overdue is not None:
        current_time = datetime.now(timezone.utc)
        if overdue:
            # Get only overdue tasks (past scheduled time with pending/in_progress status)
            query = query.filter(
                ContactTask.scheduled_for < current_time,
                ContactTask.status.in_(['pending', 'in_progress'])
            )
        else:
            # Exclude overdue tasks (future scheduled time or completed/canceled)
            query = query.filter(
                or_(
                    ContactTask.scheduled_for >= current_time,
                    ContactTask.status.in_(['completed', 'canceled'])
                )
            )
    # Apply status filter (only if overdue filter is not set)
    elif status:
        query = query.filter(ContactTask.status == status)

    # Apply priority filter
    if priority:
        query = query.filter(ContactTask.priority == priority)

    # Apply task type filter
    if task_type:
        query = query.filter(ContactTask.task_type == task_type)

    # Apply search filter
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                ContactTask.title.ilike(search_pattern),
                ContactTask.description.ilike(search_pattern),
                ContactTask.contact.has(Contact.name.ilike(search_pattern)),
                ContactTask.contact.has(Contact.phone.ilike(search_pattern))
            )
        )

    # Order by scheduled date (most recent first for overdue, oldest first for upcoming)
    query = query.order_by(ContactTask.scheduled_for.asc())

    # Apply pagination
    tasks = query.offset(offset).limit(limit).all()

    return [format_task_response(task, db) for task in tasks]

@router.get("/tasks/statistics")
async def get_task_statistics(
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get task statistics for the company"""
    # Base query
    base_query = db.query(ContactTask).filter(
        ContactTask.company_id == user.company_id
    )

    # Get counts by status
    status_counts = {}
    for status in ["pending", "in_progress", "completed", "canceled"]:
        count = base_query.filter(ContactTask.status == status).count()
        status_counts[status] = count

    # Get overdue count
    overdue_count = base_query.filter(
        ContactTask.status.in_(["pending", "in_progress"]),
        ContactTask.scheduled_for < datetime.now(timezone.utc)
    ).count()

    # Get today's tasks
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start.replace(hour=23, minute=59, second=59)
    today_count = base_query.filter(
        ContactTask.scheduled_for.between(today_start, today_end)
    ).count()

    # Get this week's tasks
    week_start = today_start
    while week_start.weekday() != 0:  # Monday
        week_start = week_start.replace(day=week_start.day - 1)
    week_end = week_start.replace(day=week_start.day + 6, hour=23, minute=59, second=59)
    week_count = base_query.filter(
        ContactTask.scheduled_for.between(week_start, week_end)
    ).count()

    return {
        "status_counts": status_counts,
        "overdue_count": overdue_count,
        "today_count": today_count,
        "week_count": week_count,
        "total_count": sum(status_counts.values())
    }

# Notification models
class TaskNotification(BaseModel):
    type: str  # 'task_reminder' or 'overdue_tasks'
    message: str
    count: int
    tasks: List[TaskResponse]

@router.get("/notifications/pending", response_model=TaskNotification)
async def get_pending_notifications(
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db),
    x_timezone: Optional[str] = Header(None)
):
    """Get pending task notifications (reminders and overdue tasks)"""
    # Use client timezone if provided, otherwise UTC
    if x_timezone:
        try:
            client_tz = pytz.timezone(x_timezone)
            now = datetime.now(client_tz)
            logger.info(f"Using client timezone {x_timezone}: {now}")
        except Exception as e:
            logger.warning(f"Invalid timezone {x_timezone}: {e}, falling back to UTC")
            now = datetime.now(timezone.utc)
    else:
        now = datetime.now(timezone.utc)
        logger.info(f"No timezone provided, using UTC: {now}")

    # Get all tasks and filter considering timezone
    all_tasks = db.query(ContactTask).filter(
        ContactTask.company_id == user.company_id,
        ContactTask.status.in_(["pending", "in_progress"])
    ).options(
        joinedload(ContactTask.contact),
        joinedload(ContactTask.creator),
        joinedload(ContactTask.assignee),
        joinedload(ContactTask.completer)
    ).order_by(ContactTask.scheduled_for.asc()).all()

    # Filter tasks considering client timezone
    reminder_tasks = []
    overdue_tasks = []

    for task in all_tasks:
        # Convert task scheduled time to client timezone for comparison
        task_scheduled_utc = task.scheduled_for
        if x_timezone:
            try:
                client_tz = pytz.timezone(x_timezone)
                # Convert UTC task time to client timezone
                task_scheduled_local = task_scheduled_utc.replace(tzinfo=pytz.UTC).astimezone(client_tz)
                now_local = now  # now is already in client timezone
            except Exception:
                # Fallback to UTC comparison
                task_scheduled_local = task_scheduled_utc
                now_local = now.astimezone(pytz.UTC) if now.tzinfo else now
        else:
            # UTC comparison
            task_scheduled_local = task_scheduled_utc
            now_local = now

        # Check if task is overdue (scheduled time < now)
        if task_scheduled_local < now_local:
            overdue_tasks.append(task)
        else:
            # Check if reminder time has arrived (scheduled_time - reminder_minutes <= now)
            reminder_time_local = task_scheduled_local - timedelta(minutes=task.reminder_minutes)
            if reminder_time_local <= now_local:
                reminder_tasks.append(task)

    # Determine notification type and message
    if overdue_tasks:
        notification_type = "overdue_tasks"
        count = len(overdue_tasks)
        if count == 1:
            message = f"Você tem 1 tarefa em atraso"
        else:
            message = f"Você tem {count} tarefas em atraso"
        tasks_to_return = overdue_tasks
    elif reminder_tasks:
        notification_type = "task_reminder"
        count = len(reminder_tasks)
        if count == 1:
            message = f"Lembrete: 1 tarefa agendada em breve"
        else:
            message = f"Lembrete: {count} tarefas agendadas em breve"
        tasks_to_return = reminder_tasks
    else:
        # No notifications
        return TaskNotification(
            type="none",
            message="Nenhuma notificação pendente",
            count=0,
            tasks=[]
        )

    # Format tasks for response
    formatted_tasks = [format_task_response(task, db) for task in tasks_to_return]

    logger.info(f"Pending notifications for company {user.company_id}: {notification_type} with {count} tasks")

    return TaskNotification(
        type=notification_type,
        message=message,
        count=count,
        tasks=formatted_tasks
    )


# Pydantic model for batch request
class BatchTasksRequest(BaseModel):
    phones: List[str] = Field(..., min_items=1, max_items=500, description="Lista de telefones para buscar tarefas")

class BatchTasksResponse(BaseModel):
    phone: str
    task_id: int
    title: str
    task_type: str
    scheduled_for: datetime

@router.post("/leads/next-tasks-batch")
async def get_leads_next_tasks_batch(
    request: BatchTasksRequest,
    user: Union[Client, User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get next tasks for multiple leads in optimized single query.
    Returns only the next upcoming task for each phone number.
    """
    try:
        company_id = user.company_id if hasattr(user, 'company_id') else getattr(user, 'company_id', None)

        if not company_id:
            raise HTTPException(status_code=400, detail="Company ID not found for user")

        # SQL query com window function para obter apenas a próxima tarefa por lead
        query = text("""
        WITH ranked_tasks AS (
            SELECT
                c.phone,
                ct.id,
                ct.title,
                ct.scheduled_for,
                ct.task_type,
                ct.status,
                ROW_NUMBER() OVER (PARTITION BY c.phone ORDER BY ct.scheduled_for ASC) as rn
            FROM contact_tasks ct
            JOIN contacts c ON ct.contact_id = c.id
            WHERE c.phone = ANY(:phones)
              AND ct.company_id = :company_id
              AND ct.status IN ('pending', 'in_progress')
              AND ct.scheduled_for >= NOW()
        )
        SELECT
            phone,
            id,
            title,
            task_type,
            scheduled_for
        FROM ranked_tasks
        WHERE rn = 1
        ORDER BY scheduled_for ASC
        """)

        # Execute query with parameters
        result = db.execute(query, {
            "phones": request.phones,
            "company_id": company_id
        }).fetchall()

        # Format response
        tasks_by_phone = []
        for row in result:
            tasks_by_phone.append(BatchTasksResponse(
                phone=row.phone,
                task_id=row.id,
                title=row.title,
                task_type=row.task_type,
                scheduled_for=row.scheduled_for
            ))

        logger.info(f"Retrieved {len(tasks_by_phone)} next tasks for {len(request.phones)} leads in company {company_id}")

        return tasks_by_phone

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting next tasks batch: {str(e)}")
        logger.error(f"SQL Query failed: {query}")
        logger.error(f"Parameters: phones={request.phones}, company_id={company_id}")
        logger.error(f"User: {user.id if hasattr(user, 'id') else 'unknown'}")
        raise HTTPException(status_code=500, detail="Internal server error")
