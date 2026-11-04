"""Ban shield for WhatsApp lines linked by QR.

WhatsApp bans numbers that behave like bulk senders: many messages nobody
asked for, a new number that sends a lot on day one, the same text to many
people, or carrying on while WhatsApp is already pushing back. Answering
people who wrote is what a person does, so replies always go out; the
shield only holds back what the line starts on its own:

- ``proactive``: follow-ups, reminders and other messages the line sends
  without the contact having just written;
- ``stranger``: any message to a chat where the contact never wrote.

For those it applies, per line: a daily allowance that ramps up over the
first week after a number is linked (the warm-up), hourly and per-minute
caps, a lower daily cap for strangers, a cap on the same text going to many
chats in an hour, and a random gap of a few seconds between two of them.
Repeated failures, disconnections or a temporary ban pause them for hours.

The numbers follow the defaults of the community anti-ban libraries for
Baileys and whatsmeow. They lower the risk; nothing removes it, since
reports and blocks by the people who receive the messages weigh the most.
"""

import asyncio
import hashlib
import random
import re
import time
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..database import new_session
from ..models import Conversation, Message, WhatsAppChannel, WhatsAppSendEvent, now_utc

OUTREACH = ("proactive", "stranger")
SENT = ("reply", "operator", "proactive", "stranger")
SIGNALS = ("failed", "disconnect", "banned")

WARMUP = (20, 36, 65, 117, 210, 378, 680)   # outreach a day, days 1 to 7
DAILY = 1000                                # after the warm-up
PER_HOUR = 200
PER_MINUTE = 8
STRANGERS_EARLY = 3                         # a day, first three days
STRANGERS = 10
IDENTICAL_PER_HOUR = 5
GAP_SECONDS = (2.5, 7.0)                    # between two outreach messages
FAILED_PER_HOUR = 5
DISCONNECTS_PER_HOUR = 3
PAUSE = timedelta(hours=6)
BAN_PAUSE = timedelta(hours=24)
KEEP = timedelta(days=2)

_WORD = re.compile(r"\W+", re.UNICODE)


class SendHeld(HTTPException):
    """The shield holds this message back until ``until``."""

    def __init__(self, reason: str, until: datetime):
        super().__init__(status_code=429, detail=reason)
        self.until = until


def text_hash(text: str | None) -> str | None:
    clean = _WORD.sub(" ", (text or "").lower()).strip()
    return hashlib.sha256(clean.encode()).hexdigest() if clean else None


def warmup_day(channel: WhatsAppChannel, now: datetime | None = None) -> int:
    """1 on the day the number was linked, 2 the next one, and so on."""
    start = channel.warmup_started_at or channel.created_at or now_utc()
    return max(1, ((now or now_utc()) - start).days + 1)


def daily_limit(channel: WhatsAppChannel, now: datetime | None = None) -> int:
    day = warmup_day(channel, now)
    return WARMUP[day - 1] if day <= len(WARMUP) else DAILY


def stranger_limit(channel: WhatsAppChannel, now: datetime | None = None) -> int:
    return STRANGERS_EARLY if warmup_day(channel, now) <= 3 else STRANGERS


def classify(db: Session, conversation: Conversation, intent: str) -> str:
    """``stranger`` when the contact never wrote in this chat, else ``intent``."""
    wrote = db.scalar(
        select(Message.id).where(Message.conversation_id == conversation.id, Message.role == "user").limit(1)
    ) if conversation.id else None
    return intent if wrote else "stranger"


def _events(db: Session, channel_id: uuid.UUID, kinds, since: datetime, digest: str | None = None):
    query = select(func.count(), func.min(WhatsAppSendEvent.created_at)).where(
        WhatsAppSendEvent.channel_id == channel_id, WhatsAppSendEvent.kind.in_(kinds), WhatsAppSendEvent.created_at > since,
    )
    if digest:
        query = query.where(WhatsAppSendEvent.text_hash == digest)
    count, oldest = db.execute(query).one()
    return count or 0, oldest


def held_until(db: Session, channel: WhatsAppChannel, kind: str, text: str | None = None,
               now: datetime | None = None) -> tuple[str, datetime] | None:
    """Why and until when this message must wait, or None to send it now."""
    if kind not in OUTREACH or not channel.guard_enabled:
        return None
    now = now or now_utc()
    if channel.guard_paused_until and channel.guard_paused_until > now:
        return f"Paused by the ban shield: {channel.guard_pause_reason or 'risk signals'}", channel.guard_paused_until

    checks = [
        (timedelta(days=1), OUTREACH, daily_limit(channel, now), None,
         "This number reached today's allowance of messages it starts (warm-up day {day})"),
        (timedelta(hours=1), OUTREACH, PER_HOUR, None, "This number reached its hourly allowance of messages it starts"),
        (timedelta(minutes=1), OUTREACH, PER_MINUTE, None, "Too many messages this minute"),
    ]
    if kind == "stranger":
        checks.append((timedelta(days=1), ("stranger",), stranger_limit(channel, now), None,
                       "This number reached today's allowance of messages to people who never wrote"))
    digest = text_hash(text)
    if digest:
        checks.append((timedelta(hours=1), OUTREACH, IDENTICAL_PER_HOUR, digest,
                       "The same message already went to many chats this hour"))
    for window, kinds, limit, match, reason in checks:
        count, oldest = _events(db, channel.id, kinds, now - window, match)
        if count >= limit:
            return reason.format(day=warmup_day(channel, now)), (oldest or now) + window
    return None


# The last outreach message of each line, in this process: the gap between
# two of them is drawn at random so they never leave in a machine rhythm.
_last_outreach: dict[uuid.UUID, float] = {}
_locks: dict[uuid.UUID, asyncio.Lock] = {}


async def pace(channel_id: uuid.UUID) -> None:
    lock = _locks.setdefault(channel_id, asyncio.Lock())
    async with lock:
        gap = random.uniform(*GAP_SECONDS)
        wait = _last_outreach.get(channel_id, 0.0) + gap - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_outreach[channel_id] = time.monotonic()


def hold_for(db: Session, conversation: Conversation, intent: str, text: str | None = None) -> datetime | None:
    """For work that can wait (follow-ups, reminders): when to try again if the
    shield would hold this message back now, else None. Only QR lines."""
    if conversation.channel != "whatsapp" or not conversation.whatsapp_channel_id:
        return None
    channel = db.get(WhatsAppChannel, conversation.whatsapp_channel_id)
    held = held_until(db, channel, classify(db, conversation, intent), text) if channel else None
    return held[1] if held else None


async def before_send(db: Session, conversation: Conversation, text: str | None, intent: str) -> str:
    """Check a QR line's message before it leaves. Returns its kind, to record
    once sent; raises ``SendHeld`` when it must wait."""
    channel = db.get(WhatsAppChannel, conversation.whatsapp_channel_id)
    if channel is None:
        return intent
    kind = classify(db, conversation, intent)
    held = held_until(db, channel, kind, text)
    if held:
        raise SendHeld(*held)
    if kind in OUTREACH and channel.guard_enabled:
        await pace(channel.id)
    return kind


def record_sent(db: Session, channel_id: uuid.UUID, kind: str, text: str | None) -> None:
    db.add(WhatsAppSendEvent(channel_id=channel_id, kind=kind, text_hash=text_hash(text) if kind in OUTREACH else None))


def record_signal(channel_id: uuid.UUID, kind: str, detail: str = "") -> None:
    """Note a risk signal in its own transaction, so it is kept even when the
    caller's work is rolled back, and pause the line when they pile up."""
    db = new_session()
    try:
        channel = db.get(WhatsAppChannel, channel_id)
        if channel is None:
            return
        now = now_utc()
        db.add(WhatsAppSendEvent(channel_id=channel_id, kind=kind))
        db.flush()
        pause = None
        if kind == "banned":
            pause = (BAN_PAUSE, "WhatsApp temporarily banned this number")
        elif kind == "failed" and _events(db, channel_id, ("failed",), now - timedelta(hours=1))[0] >= FAILED_PER_HOUR:
            pause = (PAUSE, "WhatsApp refused several messages in the last hour")
        elif kind == "disconnect" and _events(db, channel_id, ("disconnect",), now - timedelta(hours=1))[0] >= DISCONNECTS_PER_HOUR:
            pause = (PAUSE, "WhatsApp disconnected the number several times in the last hour")
        newly_paused = None
        if pause and channel.guard_enabled:
            until = now + pause[0]
            if not channel.guard_paused_until or channel.guard_paused_until < until:
                if not channel.guard_paused_until or channel.guard_paused_until <= now:
                    newly_paused = pause[1]
                channel.guard_paused_until, channel.guard_pause_reason = until, (pause[1] + (f": {detail}" if detail else ""))[:300]
        # Old events only matter for the counts above; keep the table small.
        db.execute(delete(WhatsAppSendEvent).where(WhatsAppSendEvent.channel_id == channel_id, WhatsAppSendEvent.created_at < now - KEEP))
        db.commit()
    finally:
        db.close()
    if newly_paused and kind != "banned":  # a ban has its own alert
        from .alerts import line_alert
        line_alert(channel_id, "paused", newly_paused)


def health(db: Session, channel: WhatsAppChannel) -> dict:
    """What the shield sees for a line, for the dashboard."""
    now = now_utc()
    day_ago, hour_ago = now - timedelta(days=1), now - timedelta(hours=1)
    counts = dict(db.execute(
        select(WhatsAppSendEvent.kind, func.count()).where(
            WhatsAppSendEvent.channel_id == channel.id, WhatsAppSendEvent.created_at > day_ago,
        ).group_by(WhatsAppSendEvent.kind)
    ).all())
    recent = dict(db.execute(
        select(WhatsAppSendEvent.kind, func.count()).where(
            WhatsAppSendEvent.channel_id == channel.id, WhatsAppSendEvent.created_at > hour_ago,
            WhatsAppSendEvent.kind.in_(SIGNALS),
        ).group_by(WhatsAppSendEvent.kind)
    ).all())
    paused = channel.guard_paused_until if channel.guard_paused_until and channel.guard_paused_until > now else None
    day = warmup_day(channel, now)
    return {
        "enabled": channel.guard_enabled,
        "warmup_day": day,
        "warmup_days": len(WARMUP),
        "warming_up": day <= len(WARMUP),
        "outreach_today": counts.get("proactive", 0) + counts.get("stranger", 0),
        "outreach_limit": daily_limit(channel, now),
        "strangers_today": counts.get("stranger", 0),
        "stranger_limit": stranger_limit(channel, now),
        "replies_today": counts.get("reply", 0) + counts.get("operator", 0),
        "failed_last_hour": recent.get("failed", 0),
        "disconnects_last_hour": recent.get("disconnect", 0),
        "paused_until": paused.isoformat() if paused else None,
        "pause_reason": channel.guard_pause_reason if paused else None,
        "pause_code": _pause_code(channel.guard_pause_reason) if paused else None,
    }


def _pause_code(reason: str | None) -> str:
    """A stable name for the pause, which the dashboard translates."""
    text = (reason or "").lower()
    for code, marker in (("banned", "banned"), ("failed", "refused"), ("disconnects", "disconnected")):
        if marker in text:
            return code
    return "other"
