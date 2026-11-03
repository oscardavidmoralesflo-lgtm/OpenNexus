"""WhatsApp campaigns: one approved template to many contacts.

A campaign is built as a draft (number, template, variables, audience),
then started now or at a set time. Starting it freezes the audience into
``campaign_recipients``; the follow-up timer then sends a batch per tick,
each one in the contact's open conversation or a new one, stored as the
agent's message so the agent answers the replies with it in its history.

Only the WhatsApp Cloud API can send templates, which Meta requires for
messages that start a conversation. Campaigns are not offered on numbers
linked by QR: mass messages from them get the number banned.
"""

import logging
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Campaign, CampaignRecipient, Contact, ContactTagLink, Conversation, Message, WhatsAppCloudChannel, now_utc,
)
from .contacts import display_name
from .conversation_state import note_reply, record_activity
from .pipeline import STAGES
from .routing import route_new_conversation_by_tags
from .template_webhooks import approved_template
from .whatsapp_coexistence import lock_chats_off_loop
from .whatsapp_templates import message_buttons, rendered_text, send_components, send_template, with_reply_buttons

logger = logging.getLogger(__name__)

BATCH = 60            # messages per campaign per timer tick
MAX_RECIPIENTS = 10_000
EDITABLE = ("draft", "scheduled")


def audience_query(client_id: uuid.UUID, audience: dict):
    """The contacts a campaign reaches: with a phone, not blocked, and in any
    of the chosen tags and stages (an empty list does not filter)."""
    query = select(Contact).where(Contact.client_id == client_id, Contact.phone.is_not(None), Contact.blocked_at.is_(None))
    tag_ids = [uuid.UUID(str(tag)) for tag in (audience or {}).get("tag_ids") or []]
    if tag_ids:
        query = query.where(Contact.id.in_(select(ContactTagLink.contact_id).where(ContactTagLink.tag_id.in_(tag_ids))))
    stages = [stage for stage in (audience or {}).get("stages") or [] if stage in STAGES]
    if stages:
        conditions = [Contact.stage.in_(stages)]
        if "new" in stages:
            conditions.append(Contact.stage.is_(None))
        query = query.where(or_(*conditions))
    return query


def audience_size(db: Session, client_id: uuid.UUID, audience: dict) -> int:
    return db.scalar(select(func.count()).select_from(audience_query(client_id, audience).subquery())) or 0


def personalize(value: str, contact_name: str) -> str:
    name = (contact_name or "").strip()
    first = name.split()[0] if name else ""
    return value.replace("{first_name}", first).replace("{name}", name).strip()


def stats(db: Session, campaign: Campaign) -> dict:
    """How the campaign went: queued, sent, failed, delivered, read and replied."""
    counts = dict(db.execute(
        select(CampaignRecipient.status, func.count()).where(CampaignRecipient.campaign_id == campaign.id)
        .group_by(CampaignRecipient.status)
    ).all())
    delivery = dict(db.execute(
        select(Message.delivery_status, func.count())
        .join(CampaignRecipient, CampaignRecipient.message_id == Message.id)
        .where(CampaignRecipient.campaign_id == campaign.id)
        .group_by(Message.delivery_status)
    ).all())
    reply = (
        select(func.count(func.distinct(CampaignRecipient.id)))
        .join(Message, Message.conversation_id == CampaignRecipient.conversation_id)
        .where(CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.sent_at.is_not(None),
               Message.role == "user", Message.kind == "message", Message.created_at > CampaignRecipient.sent_at)
    )
    read = delivery.get("read", 0)
    return {
        "total": sum(counts.values()),
        "pending": counts.get("pending", 0),
        "sent": counts.get("sent", 0),
        "failed": counts.get("failed", 0),
        "delivered": delivery.get("delivered", 0) + read,
        "read": read,
        "replied": db.scalar(reply) or 0,
    }


def start(db: Session, campaign: Campaign, *, at: datetime | None = None) -> int:
    """Freeze the audience and schedule the campaign. Returns the recipients."""
    if campaign.status not in EDITABLE:
        raise HTTPException(status_code=409, detail="This campaign already started")
    if campaign.whatsapp_cloud_channel_id is None:
        raise HTTPException(status_code=409, detail="Choose a WhatsApp API number")
    db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).delete()
    contacts = db.scalars(audience_query(campaign.client_id, campaign.audience).limit(MAX_RECIPIENTS + 1)).all()
    if not contacts:
        raise HTTPException(status_code=409, detail="No contact matches this audience")
    if len(contacts) > MAX_RECIPIENTS:
        raise HTTPException(status_code=409, detail=f"A campaign reaches at most {MAX_RECIPIENTS} contacts")
    for contact in contacts:
        db.add(CampaignRecipient(campaign_id=campaign.id, contact_id=contact.id, phone=contact.phone,
                                 name=display_name(contact)[:180]))
    campaign.status = "scheduled"
    campaign.scheduled_at = at or now_utc()
    campaign.last_error = None
    return len(contacts)


async def _send_one(db: Session, campaign: Campaign, channel: WhatsAppCloudChannel, template: dict, token: str,
                    recipient: CampaignRecipient) -> None:
    contact = db.get(Contact, recipient.contact_id) if recipient.contact_id else None
    name = display_name(contact) if contact else recipient.name
    values = [personalize(str((campaign.variables or {}).get(param, "")), name) for param in template["parameters"]]
    if any(not value for value in values):
        recipient.status, recipient.error = "failed", "A template variable is empty for this contact"
        return
    header = personalize(campaign.header_value or "", name)
    components = send_components(template, body_values=values, header_value=header)
    text = rendered_text(template, body_values=values, header_value=header)
    buttons = message_buttons(template)
    phone = recipient.phone
    await lock_chats_off_loop(db, channel.id, [phone])
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.whatsapp_cloud_channel_id == channel.id,
            or_(Conversation.external_chat_id == phone, Conversation.contact_id == recipient.contact_id),
            Conversation.status != "resolved",
        ).order_by(Conversation.created_at.desc()).limit(1)
    )
    started = conversation is None
    if started:
        conversation = Conversation(
            agency_id=channel.agency_id, client_id=campaign.client_id, agent_id=channel.agent_id,
            channel="whatsapp_cloud", whatsapp_cloud_channel_id=channel.id, external_chat_id=phone,
            contact_id=recipient.contact_id, contact_name=(name or "")[:180] or None, title=(name or phone)[:240],
        )
        db.add(conversation)
        db.flush()
        if contact is not None:
            route_new_conversation_by_tags(db, conversation, contact)
        record_activity(db, conversation, "started", actor=campaign.name)
    external_id = await send_template(token, channel.phone_number_id, phone, name=campaign.template_name,
                                      language=campaign.template_language, components=components)
    llm_text = with_reply_buttons(text, buttons)
    llm_text = (f"{llm_text}\n\n[The business sent the message above to many contacts as the campaign "
                f"\"{campaign.name}\". Answer the replies to it as usual.]")
    message = Message(
        conversation_id=conversation.id, role="assistant", content=text, llm_content=llm_text, buttons=buttons,
        sender_type="ai", sender_name=channel.agent.name, external_message_id=external_id,
    )
    db.add(message)
    db.flush()
    if started:
        note_reply(conversation)
    conversation.updated_at = now_utc()
    recipient.status, recipient.error = "sent", None
    recipient.conversation_id, recipient.message_id, recipient.sent_at = conversation.id, message.id, now_utc()


async def run_campaign(db: Session, campaign: Campaign, *, limit: int = BATCH) -> int:
    """Send the next batch of a due campaign. Returns how many went out."""
    channel = db.get(WhatsAppCloudChannel, campaign.whatsapp_cloud_channel_id) if campaign.whatsapp_cloud_channel_id else None
    if channel is None or not channel.is_enabled or not campaign.client.is_active:
        campaign.status, campaign.last_error, campaign.finished_at = "done", "The WhatsApp API number is off or gone.", now_utc()
        db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "pending") \
            .update({"status": "failed", "error": "Not sent: the number was off"})
        db.commit()
        return 0
    try:
        template, token = await approved_template(db, campaign.client, channel, campaign.template_name, campaign.template_language)
    except HTTPException as exc:
        # Meta paused or rejected the template: stop rather than fail every contact.
        campaign.status, campaign.last_error = "draft", str(exc.detail)[:500]
        db.commit()
        return 0
    if campaign.status == "scheduled":
        campaign.status, campaign.started_at = "sending", now_utc()
        db.commit()
    sent = 0
    for _ in range(limit):
        recipient = db.scalar(
            select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "pending")
            .limit(1).with_for_update(skip_locked=True)
        )
        if recipient is None:
            break
        recipient_id = recipient.id
        try:
            await _send_one(db, campaign, channel, template, token, recipient)
            sent += recipient.status == "sent"
            db.commit()
        except Exception as exc:  # noqa: BLE001 - one contact must not stop the campaign
            db.rollback()
            failed = db.get(CampaignRecipient, recipient_id)
            failed.status = "failed"
            failed.error = (str(getattr(exc, "detail", "")) or type(exc).__name__)[:300]
            db.commit()
    remaining = db.scalar(select(func.count()).where(
        CampaignRecipient.campaign_id == campaign.id, CampaignRecipient.status == "pending")) or 0
    if not remaining:
        campaign.status, campaign.finished_at = "done", now_utc()
        db.commit()
    return sent


async def run_due_campaigns(db: Session) -> int:
    """Called on the follow-up timer: a batch of every campaign that is due."""
    due = db.scalars(select(Campaign).where(
        Campaign.status.in_(("scheduled", "sending")), Campaign.scheduled_at <= now_utc(),
    ).order_by(Campaign.scheduled_at)).all()
    sent = 0
    for campaign in due:
        try:
            sent += await run_campaign(db, campaign)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Campaign %s failed this round", campaign.id)
    return sent
