"""WhatsApp campaigns of a client: build, preview, start, cancel and follow."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Campaign, CampaignRecipient, User, now_utc
from ..services import campaigns as service
from ..services.template_webhooks import approved_template, client_channel
from .clients import _client

router = APIRouter(prefix="/clients/{client_id}/campaigns", tags=["Campaigns"])


class Audience(BaseModel):
    tag_ids: list[uuid.UUID] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel_id: uuid.UUID
    template_name: str = Field(min_length=1, max_length=512)
    template_language: str = Field(min_length=2, max_length=10)
    variables: dict[str, str] = Field(default_factory=dict)
    header_value: str = Field(default="", max_length=1000)
    audience: Audience = Field(default_factory=Audience)


class StartIn(BaseModel):
    scheduled_at: datetime | None = None


def _campaign(db: Session, client_id: uuid.UUID, campaign_id: uuid.UUID) -> Campaign:
    campaign = db.scalar(select(Campaign).where(Campaign.id == campaign_id, Campaign.client_id == client_id))
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _out(db: Session, campaign: Campaign) -> dict:
    channel = campaign.channel
    return {
        "id": str(campaign.id), "name": campaign.name,
        "channel_id": str(campaign.whatsapp_cloud_channel_id) if campaign.whatsapp_cloud_channel_id else None,
        "channel_label": (channel.label or channel.display_name or channel.phone_number or "") if channel else "",
        "template_name": campaign.template_name, "template_language": campaign.template_language,
        "variables": campaign.variables or {}, "header_value": campaign.header_value,
        "audience": campaign.audience or {}, "status": campaign.status,
        "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "finished_at": campaign.finished_at.isoformat() if campaign.finished_at else None,
        "last_error": campaign.last_error, "created_at": campaign.created_at.isoformat(),
        "stats": service.stats(db, campaign),
    }


def _apply(db: Session, client, campaign: Campaign, payload: CampaignIn) -> None:
    channel = client_channel(db, client, payload.channel_id)
    campaign.whatsapp_cloud_channel_id = channel.id
    campaign.name = payload.name.strip()
    campaign.template_name = payload.template_name
    campaign.template_language = payload.template_language.strip()
    campaign.variables = {str(k): str(v) for k, v in payload.variables.items()}
    campaign.header_value = payload.header_value
    campaign.audience = {"tag_ids": [str(t) for t in payload.audience.tag_ids],
                         "stages": [s for s in payload.audience.stages if s in service.STAGES]}


@router.get("")
def list_campaigns(client_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    client = _client(db, user, client_id)
    rows = db.scalars(select(Campaign).where(Campaign.client_id == client.id).order_by(Campaign.created_at.desc()).limit(100)).all()
    return [_out(db, row) for row in rows]


@router.post("/audience")
def preview_audience(client_id: uuid.UUID, payload: Audience, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """How many contacts an audience reaches, before saving anything."""
    client = _client(db, user, client_id)
    audience = {"tag_ids": [str(t) for t in payload.tag_ids], "stages": payload.stages}
    return {"count": service.audience_size(db, client.id, audience)}


@router.post("", status_code=201)
async def create_campaign(client_id: uuid.UUID, payload: CampaignIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    client = _client(db, user, client_id)
    campaign = Campaign(agency_id=client.agency_id, client_id=client.id, name="", template_name="", template_language="")
    _apply(db, client, campaign, payload)
    await approved_template(db, client, client_channel(db, client, payload.channel_id),
                            campaign.template_name, campaign.template_language)
    db.add(campaign)
    db.commit()
    return _out(db, campaign)


@router.put("/{campaign_id}")
async def update_campaign(
    client_id: uuid.UUID, campaign_id: uuid.UUID, payload: CampaignIn, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    campaign = _campaign(db, client.id, campaign_id)
    if campaign.status not in ("draft",):
        raise HTTPException(status_code=409, detail="Only a draft can be edited")
    _apply(db, client, campaign, payload)
    await approved_template(db, client, client_channel(db, client, payload.channel_id), campaign.template_name, campaign.template_language)
    db.commit()
    return _out(db, campaign)


@router.post("/{campaign_id}/start")
def start_campaign(
    client_id: uuid.UUID, campaign_id: uuid.UUID, payload: StartIn, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    campaign = _campaign(db, client.id, campaign_id)
    at = payload.scheduled_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    service.start(db, campaign, at=at if at and at > now_utc() else None)
    db.commit()
    return _out(db, campaign)


@router.post("/{campaign_id}/cancel")
def cancel_campaign(client_id: uuid.UUID, campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    client = _client(db, user, client_id)
    campaign = _campaign(db, client.id, campaign_id)
    if campaign.status not in ("scheduled", "sending"):
        raise HTTPException(status_code=409, detail="Only a scheduled or sending campaign can be stopped")
    campaign.status, campaign.finished_at = "cancelled", now_utc()
    db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "pending") \
        .update({"status": "failed", "error": "Not sent: the campaign was stopped"})
    db.commit()
    return _out(db, campaign)


@router.get("/{campaign_id}/recipients")
def list_recipients(
    client_id: uuid.UUID, campaign_id: uuid.UUID, status: str | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    campaign = _campaign(db, client.id, campaign_id)
    query = select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id)
    if status:
        query = query.where(CampaignRecipient.status == status)
    rows = db.scalars(query.order_by(CampaignRecipient.sent_at.desc().nulls_last(), CampaignRecipient.name).limit(500)).all()
    return [{
        "id": str(row.id), "name": row.name, "phone": row.phone, "status": row.status, "error": row.error,
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
    } for row in rows]


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(client_id: uuid.UUID, campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    client = _client(db, user, client_id)
    campaign = _campaign(db, client.id, campaign_id)
    if campaign.status == "sending":
        raise HTTPException(status_code=409, detail="Stop the campaign before deleting it")
    db.delete(campaign)
    db.commit()
    return Response(status_code=204)
