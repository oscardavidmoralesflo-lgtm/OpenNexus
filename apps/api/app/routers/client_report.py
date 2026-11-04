"""The monthly report an agency hands each client: what the AI did for them.

One month of one client's conversations (playground rehearsals left out),
next to the month before, with the AI cost and an estimate of the time saved.
The web app prints it with the client's logo as a page or a PDF.
"""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, Client, Conversation, UsageRecord, User
from ..services.report_operations import ConversationFilters, operations, safe_tz

router = APIRouter(prefix="/clients", tags=["Client report"])

# The estimate shown as "time saved": what a person takes to read a message
# and write a reply. Stated on the report, so the client sees the assumption.
MINUTES_PER_REPLY = 2


def _month(value: str | None, today: date) -> date:
    if not value:
        return (today.replace(day=1) - timedelta(days=1)).replace(day=1)  # last full month
    try:
        year, month = (int(part) for part in value.split("-"))
        return date(year, month, 1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="month must look like 2026-10") from exc


def _month_end(start: date) -> date:
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _summary(db: Session, client: Client, start: date) -> dict:
    end = _month_end(start)
    filters = ConversationFilters(
        client.agency_id, date_from=start, date_to=end, client_id=client.id, agent_id=None, channel=None,
        tz=client.timezone, bucket="day", exclude_channel="playground",
    )
    report = operations(db, filters)
    zone = ZoneInfo(safe_tz(client.timezone))
    since = datetime.combine(start, time.min, tzinfo=zone)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone)
    cost = db.scalar(
        select(func.coalesce(func.sum(UsageRecord.cost_usd), 0))
        .join(Agent, Agent.id == UsageRecord.agent_id)
        .outerjoin(Conversation, Conversation.id == UsageRecord.conversation_id)
        # The agency's own rehearsals and quality tests are not the client's cost.
        .where(Agent.client_id == client.id, UsageRecord.agency_id == client.agency_id,
               UsageRecord.created_at >= since, UsageRecord.created_at < until, UsageRecord.purpose != "test",
               or_(Conversation.id.is_(None), Conversation.channel != "playground"))
    ) or 0
    totals = report["totals"]
    return {
        "month": start.strftime("%Y-%m"),
        "totals": totals,
        "by_channel": [{"channel": row["id"], "conversations": row["conversations"]} for row in report["by_channel"]],
        "by_day": [{"day": row["day"], "conversations": row["conversations"]} for row in report["by_period"]],
        "ai_cost_usd": round(float(cost), 4),
        "hours_saved": round(totals["ai_replies"] * MINUTES_PER_REPLY / 60, 1),
    }


@router.get("/{client_id}/monthly-report")
def monthly_report(
    client_id: uuid.UUID,
    month: str | None = Query(default=None, description="YYYY-MM; defaults to the last full month"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    client = db.scalar(select(Client).where(Client.id == client_id, Client.agency_id == user.agency_id))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    today = datetime.now(ZoneInfo(safe_tz(client.timezone))).date()
    start = _month(month, today)
    previous = (start - timedelta(days=1)).replace(day=1)
    return {
        "client": {"id": str(client.id), "name": client.name, "logo_url": client.logo_url},
        "agency": {"name": user.agency.name, "logo_url": user.agency.logo_url, "brand_color": user.agency.brand_color},
        "minutes_per_reply": MINUTES_PER_REPLY,
        "current": _summary(db, client, start),
        "previous": _summary(db, client, previous),
    }
