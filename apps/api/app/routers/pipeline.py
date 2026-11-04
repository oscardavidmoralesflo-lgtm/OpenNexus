"""A client's sales pipeline as a board: contacts by stage, with their value."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Client, Contact, Conversation, User
from ..services.contacts import display_name
from ..services.pipeline import STAGES, set_stage, stage_of

router = APIRouter(prefix="/clients", tags=["Sales pipeline"])

PER_STAGE = 100


class PipelineSettingsIn(BaseModel):
    enabled: bool


class StageIn(BaseModel):
    stage: str | None = None
    deal_value: float | None = Field(default=None, ge=0, le=1_000_000_000)
    clear_value: bool = False


def _client(db: Session, user: User, client_id: uuid.UUID) -> Client:
    client = db.scalar(select(Client).where(Client.id == client_id, Client.agency_id == user.agency_id))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _card(contact: Contact, last: tuple | None) -> dict:
    return {
        "id": str(contact.id), "name": display_name(contact), "phone": contact.phone, "email": contact.email,
        "stage": stage_of(contact),
        "deal_value": float(contact.deal_value) if contact.deal_value is not None else None,
        "stage_changed_at": contact.stage_changed_at.isoformat() if contact.stage_changed_at else None,
        "last_conversation_id": str(last[0]) if last else None,
        "last_activity_at": last[1].isoformat() if last and last[1] else contact.created_at.isoformat(),
        "last_channel": last[2] if last else None,
        "tags": [{"name": tag.name, "color": tag.color} for tag in contact.tags],
    }


@router.get("/{client_id}/pipeline")
def get_pipeline(
    client_id: uuid.UUID, q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    # The latest conversation of each contact: where to jump, and the last activity.
    latest = (
        select(Conversation.contact_id, Conversation.id, Conversation.updated_at, Conversation.channel,
               func.row_number().over(partition_by=Conversation.contact_id, order_by=Conversation.updated_at.desc()).label("n"))
        .where(Conversation.client_id == client.id, Conversation.contact_id.is_not(None), Conversation.channel != "playground")
        .subquery()
    )
    activity = func.coalesce(latest.c.updated_at, Contact.created_at)
    stages = []
    for stage in STAGES:
        query = (
            select(Contact, latest.c.id, latest.c.updated_at, latest.c.channel)
            .outerjoin(latest, (latest.c.contact_id == Contact.id) & (latest.c.n == 1))
            .where(Contact.client_id == client.id, Contact.blocked_at.is_(None))
        )
        query = query.where(or_(Contact.stage.is_(None), Contact.stage == "new")) if stage == "new" else query.where(Contact.stage == stage)
        if q:
            like = f"%{q.strip().lower()}%"
            query = query.where(or_(func.lower(Contact.name).like(like), Contact.phone.like(like), func.lower(Contact.email).like(like)))
        total = db.scalar(select(func.count()).select_from(query.with_only_columns(Contact.id).subquery())) or 0
        values = query.with_only_columns(Contact.deal_value).subquery()
        value = db.scalar(select(func.coalesce(func.sum(values.c.deal_value), 0))) or 0
        rows = db.execute(query.order_by(activity.desc()).limit(PER_STAGE)).all()
        stages.append({
            "stage": stage, "total": total, "value": float(value),
            "contacts": [_card(row[0], (row[1], row[2], row[3]) if row[1] else None) for row in rows],
        })
    return {"enabled": client.pipeline_enabled, "stages": stages}


@router.put("/{client_id}/pipeline/settings")
def save_pipeline_settings(
    client_id: uuid.UUID, payload: PipelineSettingsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    client.pipeline_enabled = payload.enabled
    db.commit()
    from ..services.phone_calls import refresh_lines_soon
    refresh_lines_soon(db, client_id=client.id)
    return {"enabled": client.pipeline_enabled}


@router.patch("/{client_id}/pipeline/contacts/{contact_id}")
def move_contact(
    client_id: uuid.UUID, contact_id: uuid.UUID, payload: StageIn,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    contact = db.scalar(select(Contact).where(Contact.id == contact_id, Contact.client_id == client.id))
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if payload.stage is not None:
        if payload.stage not in STAGES:
            raise HTTPException(status_code=422, detail="Unknown stage")
        set_stage(contact, payload.stage)
    if payload.clear_value:
        contact.deal_value = None
    elif payload.deal_value is not None:
        contact.deal_value = round(payload.deal_value, 2)
    db.commit()
    return _card(contact, None)
