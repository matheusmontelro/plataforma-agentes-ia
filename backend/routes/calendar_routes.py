from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import time, date, datetime, timedelta
from backend.db import get_db
from backend.models import Agenda, AgendaSchedule, Company, User
from backend.auth import get_current_user

router = APIRouter()

# --- Schemas ---

class ScheduleBase(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    morning_start: Optional[time] = None
    morning_end: Optional[time] = None
    afternoon_start: Optional[time] = None
    afternoon_end: Optional[time] = None
    night_start: Optional[time] = None
    night_end: Optional[time] = None

class AgendaBase(BaseModel):
    name: str
    slot_duration: int = Field(..., gt=0)
    active: bool = True
    timezone: str = "America/Sao_Paulo"
    safety_margin_minutes: int = Field(180, ge=0)
    google_calendar_id: Optional[str] = None
    google_calendar_summary: Optional[str] = None
    google_calendar_time_zone: Optional[str] = None

class AgendaCreate(AgendaBase):
    schedules: List[ScheduleBase]

class AgendaUpdate(AgendaBase):
    schedules: Optional[List[ScheduleBase]] = None

class ScheduleResponse(ScheduleBase):
    id: int
    agenda_id: int

    class Config:
        orm_mode = True

class AgendaResponse(AgendaBase):
    id: int
    company_id: int
    created_at: datetime
    schedules: List[ScheduleResponse]

    class Config:
        orm_mode = True

class Slot(BaseModel):
    start_time: datetime
    end_time: datetime

# --- Helper ---

def _company_id_from_user(current_user: User) -> Optional[int]:
    if hasattr(current_user, 'company_id') and current_user.company_id:
        return current_user.company_id

    if hasattr(current_user, 'companies') and current_user.companies:
        first_item = current_user.companies[0]
        return getattr(first_item, 'id', getattr(first_item, 'company_id', None))

    if hasattr(current_user, 'client') and current_user.client and current_user.client.companies:
        first_item = current_user.client.companies[0]
        return getattr(first_item, 'id', getattr(first_item, 'company_id', None))

    return None

def generate_slots_for_range(date_obj: date, start: time, end: time, duration: int) -> List[Slot]:
    slots = []
    if not start or not end:
        return slots

    current_dt = datetime.combine(date_obj, start)
    end_dt = datetime.combine(date_obj, end)

    while current_dt + timedelta(minutes=duration) <= end_dt:
        slot_end = current_dt + timedelta(minutes=duration)
        slots.append(Slot(start_time=current_dt, end_time=slot_end))
        current_dt = slot_end

    return slots

# --- Routes ---

@router.post("/", response_model=AgendaResponse)
def create_agenda(
    agenda: AgendaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    if not company_id:
        raise HTTPException(status_code=400, detail="User is not associated with a company")

    db_agenda = Agenda(
        company_id=company_id,
        name=agenda.name,
        slot_duration=agenda.slot_duration,
        active=agenda.active,
        timezone=agenda.timezone,
        safety_margin_minutes=agenda.safety_margin_minutes
    )
    db.add(db_agenda)
    db.commit()
    db.refresh(db_agenda)

    # Add schedules
    for sched in agenda.schedules:
        db_sched = AgendaSchedule(
            agenda_id=db_agenda.id,
            day_of_week=sched.day_of_week,
            morning_start=sched.morning_start,
            morning_end=sched.morning_end,
            afternoon_start=sched.afternoon_start,
            afternoon_end=sched.afternoon_end,
            night_start=sched.night_start,
            night_end=sched.night_end
        )
        db.add(db_sched)

    db.commit()
    db.refresh(db_agenda)
    return db_agenda

@router.get("/", response_model=List[AgendaResponse])
def list_agendas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    if not company_id:
        return []

    return db.query(Agenda).filter(Agenda.company_id == company_id).all()

@router.get("/{agenda_id}", response_model=AgendaResponse)
def get_agenda(
    agenda_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    agenda = db.query(Agenda).filter(Agenda.id == agenda_id, Agenda.company_id == company_id).first()
    if not agenda:
        raise HTTPException(status_code=404, detail="Agenda not found")
    return agenda

@router.put("/{agenda_id}", response_model=AgendaResponse)
def update_agenda(
    agenda_id: int,
    agenda_update: AgendaUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    db_agenda = db.query(Agenda).filter(Agenda.id == agenda_id, Agenda.company_id == company_id).first()
    if not db_agenda:
        raise HTTPException(status_code=404, detail="Agenda not found")

    db_agenda.name = agenda_update.name
    db_agenda.slot_duration = agenda_update.slot_duration
    db_agenda.active = agenda_update.active
    db_agenda.timezone = agenda_update.timezone # Added update for timezone.active
    db_agenda.safety_margin_minutes = agenda_update.safety_margin_minutes

    if agenda_update.schedules is not None:
        # Remove old schedules
        db.query(AgendaSchedule).filter(AgendaSchedule.agenda_id == agenda_id).delete()
        # Add new ones
        for sched in agenda_update.schedules:
            new_sched = AgendaSchedule(
                agenda_id=agenda_id,
                day_of_week=sched.day_of_week,
                morning_start=sched.morning_start,
                morning_end=sched.morning_end,
                afternoon_start=sched.afternoon_start,
                afternoon_end=sched.afternoon_end,
                night_start=sched.night_start,
                night_end=sched.night_end
            )
            db.add(new_sched)

    db.commit()
    db.refresh(db_agenda)
    return db_agenda

@router.get("/{agenda_id}/slots", response_model=List[Slot])
def get_available_slots(
    agenda_id: int,
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    company_id = _company_id_from_user(current_user)
    agenda = db.query(Agenda).filter(Agenda.id == agenda_id, Agenda.company_id == company_id).first()
    if not agenda:
        raise HTTPException(status_code=404, detail="Agenda not found")

    if not agenda.active:
        return []

    # Get schedules mapped by day_of_week
    schedules = {s.day_of_week: s for s in agenda.schedules}

    all_slots = []

    # Iterate through days
    delta = end_date - start_date
    for i in range(delta.days + 1):
        day = start_date + timedelta(days=i)
        weekday = day.weekday() # 0=Monday

        if weekday in schedules:
            sched = schedules[weekday]
            # Morning
            all_slots.extend(generate_slots_for_range(day, sched.morning_start, sched.morning_end, agenda.slot_duration))
            # Afternoon
            all_slots.extend(generate_slots_for_range(day, sched.afternoon_start, sched.afternoon_end, agenda.slot_duration))
            # Night
            all_slots.extend(generate_slots_for_range(day, sched.night_start, sched.night_end, agenda.slot_duration))

    return all_slots
