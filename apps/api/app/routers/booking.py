"""A client's appointment book: its settings, its free times and the
appointments themselves, booked by agents or by the team."""

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, Appointment, BookingSettings, Client, User, now_utc
from ..services import booking

router = APIRouter(prefix="/clients", tags=["Booking"])


class Slot(BaseModel):
    day: int
    start: str
    end: str


class BookingSettingsIn(BaseModel):
    enabled: bool = False
    duration_minutes: int = 30
    slots: list[Slot] = Field(default_factory=list)
    capacity: int = 1
    min_notice_minutes: int = 120
    max_days_ahead: int = 30
    location: str = Field(default="", max_length=500)
    reminder_enabled: bool = True
    reminder_hours: int = 24


class AppointmentIn(BaseModel):
    starts_at: datetime
    name: str = Field(min_length=1, max_length=180)
    phone: str = Field(default="", max_length=40)
    notes: str = Field(default="", max_length=2000)


class AppointmentPatch(BaseModel):
    status: str | None = None
    starts_at: datetime | None = None
    name: str | None = Field(default=None, min_length=1, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)


def _client(db: Session, user: User, client_id: uuid.UUID) -> Client:
    client = db.scalar(select(Client).where(Client.id == client_id, Client.agency_id == user.agency_id))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _settings_out(settings: BookingSettings | None) -> dict:
    defaults = BookingSettingsIn()
    source = settings or defaults
    return {
        "enabled": source.enabled, "duration_minutes": source.duration_minutes,
        "slots": list(source.slots or []) if settings else [], "capacity": source.capacity,
        "min_notice_minutes": source.min_notice_minutes, "max_days_ahead": source.max_days_ahead,
        "location": source.location, "reminder_enabled": source.reminder_enabled, "reminder_hours": source.reminder_hours,
    }


def _appointment_out(item: Appointment, agents: dict[uuid.UUID, str]) -> dict:
    return {
        "id": str(item.id), "name": item.name, "phone": item.phone, "notes": item.notes,
        "starts_at": item.starts_at.isoformat(), "ends_at": item.ends_at.isoformat(),
        "status": item.status, "source": item.source,
        "agent_name": agents.get(item.agent_id) if item.agent_id else None,
        "conversation_id": str(item.conversation_id) if item.conversation_id else None,
        "reminder_due_at": item.reminder_due_at.isoformat() if item.reminder_due_at else None,
        "reminder_sent_at": item.reminder_sent_at.isoformat() if item.reminder_sent_at else None,
        "reminder_error": item.reminder_error,
        "created_at": item.created_at.isoformat(),
    }


def _agent_names(db: Session, client: Client) -> dict[uuid.UUID, str]:
    return {agent.id: agent.name for agent in db.scalars(select(Agent).where(Agent.client_id == client.id))}


@router.get("/{client_id}/booking")
def get_settings(client_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    client = _client(db, user, client_id)
    return _settings_out(booking.settings_for(db, client.id))


@router.put("/{client_id}/booking")
def save_settings(
    client_id: uuid.UUID, payload: BookingSettingsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    try:
        values = booking.validate(payload.model_dump())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if values["enabled"] and not values["slots"]:
        raise HTTPException(status_code=422, detail="Add at least one day with hours before turning the book on")
    settings = booking.settings_for(db, client.id)
    if settings is None:
        settings = BookingSettings(agency_id=client.agency_id, client_id=client.id)
        db.add(settings)
    reminder_changed = (settings.reminder_enabled, settings.reminder_hours) != (values["reminder_enabled"], values["reminder_hours"])
    for key, value in values.items():
        setattr(settings, key, value)
    db.flush()
    if reminder_changed:
        # Upcoming reminders follow the new setting; ones already sent stay sent.
        for item in db.scalars(select(Appointment).where(
            Appointment.client_id == client.id, Appointment.status == "confirmed",
            Appointment.starts_at > now_utc(), Appointment.reminder_sent_at.is_(None),
        )):
            item.reminder_due_at = booking.reminder_due(settings, item.starts_at)
    db.commit()
    # Phone lines carry the booking tools in their setup: write them again.
    from ..services.phone_calls import refresh_lines_soon
    refresh_lines_soon(db, client_id=client.id)
    return _settings_out(settings)


@router.get("/{client_id}/booking/slots")
def list_free_slots(
    client_id: uuid.UUID,
    day: date | None = Query(default=None, alias="date"),
    days: int = Query(default=7, ge=1, le=14),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    settings = booking.settings_for(db, client.id)
    if not settings or not settings.slots:
        return {"timezone": booking.safe_tz(client.timezone), "slots": []}
    start_day = day or now_utc().astimezone(booking.zone_of(client)).date()
    slots = booking.free_slots(db, settings, client, start_day, days, limit=200)
    return {"timezone": booking.safe_tz(client.timezone), "slots": [slot.isoformat() for slot in slots]}


@router.get("/{client_id}/appointments")
def list_appointments(
    client_id: uuid.UUID,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    zone = booking.zone_of(client)
    today = now_utc().astimezone(zone).date()
    start = datetime.combine(date_from or today, datetime.min.time(), tzinfo=zone)
    end = datetime.combine((date_to or (date_from or today) + timedelta(days=30)) + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    query = select(Appointment).where(
        Appointment.client_id == client.id, Appointment.starts_at >= start, Appointment.starts_at < end,
    )
    if status:
        query = query.where(Appointment.status == status)
    rows = db.scalars(query.order_by(Appointment.starts_at).limit(500)).all()
    names = _agent_names(db, client)
    return {"timezone": booking.safe_tz(client.timezone), "appointments": [_appointment_out(row, names) for row in rows]}


@router.post("/{client_id}/appointments", status_code=201)
def create_appointment(
    client_id: uuid.UUID, payload: AppointmentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    settings = booking.settings_for(db, client.id)
    starts_at = payload.starts_at if payload.starts_at.tzinfo else payload.starts_at.replace(tzinfo=booking.zone_of(client))
    length = timedelta(minutes=settings.duration_minutes if settings else 30)
    # The team may book outside the published hours (a favour, an extra
    # shift), but never past the capacity of a time.
    if not booking.fits(db, settings, client.id, starts_at, starts_at + length):
        raise HTTPException(status_code=409, detail="That time is already full")
    item = booking.create_appointment(
        db, client, settings, starts_at=starts_at, name=payload.name.strip(), phone=payload.phone.strip(),
        notes=payload.notes.strip(), source="team",
    )
    db.commit()
    return _appointment_out(item, _agent_names(db, client))


@router.patch("/{client_id}/appointments/{appointment_id}")
def update_appointment(
    client_id: uuid.UUID, appointment_id: uuid.UUID, payload: AppointmentPatch,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    item = db.scalar(select(Appointment).where(Appointment.id == appointment_id, Appointment.client_id == client.id))
    if not item:
        raise HTTPException(status_code=404, detail="Appointment not found")
    settings = booking.settings_for(db, client.id)
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes:
        if changes["status"] not in booking.STATUSES:
            raise HTTPException(status_code=422, detail="Unknown status")
        if changes["status"] == "confirmed" and item.status != "confirmed" and not booking.fits(
                db, settings, client.id, item.starts_at, item.ends_at, ignore=item.id):
            raise HTTPException(status_code=409, detail="That time is already full")
        item.status = changes["status"]
    if changes.get("starts_at"):
        starts_at = changes["starts_at"] if changes["starts_at"].tzinfo else changes["starts_at"].replace(tzinfo=booking.zone_of(client))
        length = item.ends_at - item.starts_at
        if item.status == "confirmed" and not booking.fits(db, settings, client.id, starts_at, starts_at + length, ignore=item.id):
            raise HTTPException(status_code=409, detail="That time is already full")
        item.starts_at, item.ends_at = starts_at, starts_at + length
        item.reminder_sent_at = None
        item.reminder_error = None
    for key in ("name", "phone", "notes"):
        if changes.get(key) is not None:
            setattr(item, key, changes[key].strip())
    item.reminder_due_at = (
        booking.reminder_due(settings, item.starts_at)
        if item.status == "confirmed" and item.reminder_sent_at is None else None
    )
    db.commit()
    return _appointment_out(item, _agent_names(db, client))


@router.delete("/{client_id}/appointments/{appointment_id}", status_code=204)
def delete_appointment(
    client_id: uuid.UUID, appointment_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    item = db.scalar(select(Appointment).where(Appointment.id == appointment_id, Appointment.client_id == client.id))
    if not item:
        raise HTTPException(status_code=404, detail="Appointment not found")
    db.delete(item)
    db.commit()
    return Response(status_code=204)

