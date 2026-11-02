"""The agency's audit log, newest first. Owners and admins read it."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import AuditEvent, User

router = APIRouter(prefix="/audit", tags=["Audit log"])

PAGE_LIMIT = 200


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    actor_email: str
    method: str
    path: str
    status_code: int
    target_id: str | None
    ip: str
    user_agent: str
    created_at: datetime


class AuditPage(BaseModel):
    events: list[AuditEventOut]
    has_more: bool


@router.get("", response_model=AuditPage)
def list_events(
    limit: int = Query(50, ge=1, le=PAGE_LIMIT),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, max_length=120, description="Only actions starting with this, e.g. `agents`"),
    actor: str | None = Query(None, max_length=320, description="Only this person's email"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(AuditEvent).where(AuditEvent.agency_id == user.agency_id)
    if action:
        query = query.where(AuditEvent.action.startswith(action.strip(), autoescape=True))
    if actor:
        query = query.where(AuditEvent.actor_email == actor.strip().lower())
    rows = db.scalars(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit + 1)).all()
    return AuditPage(events=[AuditEventOut.model_validate(row) for row in rows[:limit]], has_more=len(rows) > limit)
