"""Appointment booking: free times, the agent's booking tools and reminders.

A client's ``BookingSettings`` describe the weekly hours appointments can
start in. A time is free while fewer than ``capacity`` confirmed appointments
overlap it. Agents get three built-in tools when the client's book is on:
look up free times, book one and cancel one. Like the other built-in tools,
the handlers only check and record; the caller writes the appointments with
``apply_bookings`` after the loop, so a rehearsal in the playground books
nothing.

Reminders go out on the follow-up timer through the conversation's channel,
as a fixed text: no model call, so they cost nothing.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Agent, Appointment, BookingSettings, Client, Contact, Conversation, now_utc
from .availability import check_slots, minutes_of
from .report_operations import safe_tz
from .tools.specs import ToolSpec

logger = logging.getLogger(__name__)

STATUSES = ("confirmed", "cancelled", "completed", "no_show")
# Channels a reminder can reach: the contact must be able to read it later.
REMINDER_CHANNELS = ("whatsapp", "whatsapp_cloud", "instagram", "messenger")
MAX_SLOTS_LISTED = 40
MAX_DAYS_LISTED = 14


def zone_of(client: Client) -> ZoneInfo:
    return ZoneInfo(safe_tz(client.timezone))


def settings_for(db: Session, client_id: uuid.UUID) -> BookingSettings | None:
    return db.scalar(select(BookingSettings).where(BookingSettings.client_id == client_id))


def validate(values: dict) -> dict:
    """Check the editable settings; raises ValueError with a readable message."""
    cleaned = dict(values)
    if "slots" in cleaned:
        cleaned["slots"] = check_slots(cleaned["slots"] or [])
    if "duration_minutes" in cleaned and not 5 <= int(cleaned["duration_minutes"]) <= 480:
        raise ValueError("An appointment lasts between 5 minutes and 8 hours")
    if "capacity" in cleaned and not 1 <= int(cleaned["capacity"]) <= 50:
        raise ValueError("Between 1 and 50 appointments can share a time")
    if "min_notice_minutes" in cleaned and not 0 <= int(cleaned["min_notice_minutes"]) <= 14 * 24 * 60:
        raise ValueError("The minimum notice is up to 14 days")
    if "max_days_ahead" in cleaned and not 1 <= int(cleaned["max_days_ahead"]) <= 365:
        raise ValueError("Appointments can be booked from 1 to 365 days ahead")
    if "reminder_hours" in cleaned and not 1 <= int(cleaned["reminder_hours"]) <= 72:
        raise ValueError("The reminder goes out between 1 and 72 hours before")
    return cleaned


def _overlapping(db: Session, client_id: uuid.UUID, start: datetime, end: datetime, *, ignore: uuid.UUID | None = None) -> int:
    query = select(func.count(Appointment.id)).where(
        Appointment.client_id == client_id, Appointment.status == "confirmed",
        Appointment.starts_at < end, Appointment.ends_at > start,
    )
    if ignore:
        query = query.where(Appointment.id != ignore)
    return db.scalar(query) or 0


def _bookable(settings: BookingSettings, client: Client, start: datetime, now: datetime) -> str | None:
    """Why ``start`` cannot be booked under the settings, or None when it can."""
    zone = zone_of(client)
    local = start.astimezone(zone)
    if start < now + timedelta(minutes=settings.min_notice_minutes):
        return "too_soon"
    if local.date() > (now.astimezone(zone) + timedelta(days=settings.max_days_ahead)).date():
        return "too_far"
    minute = local.hour * 60 + local.minute
    for slot in settings.slots or []:
        if slot["day"] != local.weekday():
            continue
        begin, end = minutes_of(slot["start"]), minutes_of(slot["end"])
        if begin <= minute and minute + settings.duration_minutes <= end and (minute - begin) % settings.duration_minutes == 0:
            return None
    return "outside_hours"


def free_slots(
    db: Session, settings: BookingSettings, client: Client, start_day: date, days: int, now: datetime | None = None,
    *, limit: int = MAX_SLOTS_LISTED, taken: list[tuple[datetime, datetime]] | None = None,
) -> list[datetime]:
    """Start times still free from ``start_day`` on, in order, up to ``limit``.
    ``taken`` adds times booked in this same exchange, not written yet."""
    now = now or now_utc()
    zone = zone_of(client)
    length = timedelta(minutes=settings.duration_minutes)
    days = max(1, min(days, MAX_DAYS_LISTED))
    window_start = datetime.combine(start_day, time.min, tzinfo=zone)
    window_end = datetime.combine(start_day + timedelta(days=days), time.min, tzinfo=zone)
    booked = [
        (row.starts_at, row.ends_at)
        for row in db.scalars(select(Appointment).where(
            Appointment.client_id == client.id, Appointment.status == "confirmed",
            Appointment.starts_at < window_end, Appointment.ends_at > window_start,
        ))
    ] + list(taken or [])
    found: list[datetime] = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        for slot in sorted((s for s in settings.slots or [] if s["day"] == day.weekday()), key=lambda s: s["start"]):
            minute, end = minutes_of(slot["start"]), minutes_of(slot["end"])
            while minute + settings.duration_minutes <= end:
                start = datetime.combine(day, time.min, tzinfo=zone) + timedelta(minutes=minute)
                minute += settings.duration_minutes
                if _bookable(settings, client, start, now):
                    continue
                overlap = sum(1 for begin, finish in booked if begin < start + length and finish > start)
                if overlap < settings.capacity:
                    found.append(start)
                    if len(found) >= limit:
                        return found
    return found


def reminder_due(settings: BookingSettings | None, starts_at: datetime, now: datetime | None = None) -> datetime | None:
    """When the reminder for an appointment goes out, or None for no reminder."""
    if not settings or not settings.reminder_enabled:
        return None
    due = starts_at - timedelta(hours=settings.reminder_hours)
    now = now or now_utc()
    # Booked inside the reminder window: a reminder now would repeat the
    # confirmation the contact just read, so there is none.
    return due if due > now else None


def create_appointment(
    db: Session, client: Client, settings: BookingSettings | None, *, starts_at: datetime, name: str, phone: str = "",
    notes: str = "", source: str, agent: Agent | None = None, conversation: Conversation | None = None,
    contact_id: uuid.UUID | None = None, duration_minutes: int | None = None,
) -> Appointment:
    length = duration_minutes or (settings.duration_minutes if settings else 30)
    appointment = Appointment(
        agency_id=client.agency_id, client_id=client.id, agent_id=agent.id if agent else None,
        conversation_id=conversation.id if conversation else None, contact_id=contact_id,
        name=name[:180], phone=phone[:40], notes=notes, starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=length), status="confirmed", source=source,
        reminder_due_at=reminder_due(settings, starts_at),
    )
    db.add(appointment)
    return appointment


def fits(db: Session, settings: BookingSettings | None, client_id: uuid.UUID, start: datetime, end: datetime,
         *, ignore: uuid.UUID | None = None) -> bool:
    capacity = settings.capacity if settings else 1
    return _overlapping(db, client_id, start, end, ignore=ignore) < capacity


# --- The agent's tools -------------------------------------------------------

@dataclass
class BookingChanges:
    """What the agent booked and cancelled in one exchange, applied after it."""
    booked: list[dict] = field(default_factory=list)
    cancelled: list[uuid.UUID] = field(default_factory=list)


_TEXT = {
    "es": {
        "rules": (
            "AGENDA DE CITAS: puedes agendar citas para el negocio con tus herramientas. Hoy es {today} y son las "
            "{now} (hora del negocio). Cada cita dura {duration} minutos.{location}\n"
            "- Antes de proponer horarios usa siempre check_availability; nunca inventes horarios ni prometas uno sin "
            "consultarlo.\n"
            "- Ofrece pocas opciones (dos o tres) y deja que la persona elija.\n"
            "- Antes de agendar confirma el día, la hora y el nombre de la persona. Luego usa book_appointment.\n"
            "- Si quiere cambiar una cita, cancela la anterior con cancel_appointment y agenda la nueva.\n"
            "- No digas que la cita quedó agendada si la herramienta no lo confirmó."
        ),
        "location": " Lugar o indicaciones: {location}.",
        "upcoming": "Citas próximas de esta persona: {items}.",
        "reminder": "Hola{name}, te recordamos tu cita {when}.{location} Si necesitas cambiarla o cancelarla, respóndenos por aquí.",
        "reminder_location": " Lugar: {location}.",
    },
    "en": {
        "rules": (
            "APPOINTMENT BOOKING: you can book appointments for the business with your tools. Today is {today} and it "
            "is {now} (business time). Each appointment lasts {duration} minutes.{location}\n"
            "- Before offering times always use check_availability; never make up times or promise one without "
            "checking it.\n"
            "- Offer a few options (two or three) and let the person choose.\n"
            "- Before booking confirm the day, the time and the person's name. Then use book_appointment.\n"
            "- To change an appointment, cancel the old one with cancel_appointment and book the new one.\n"
            "- Do not say the appointment is booked unless the tool confirmed it."
        ),
        "location": " Place or directions: {location}.",
        "upcoming": "This person's upcoming appointments: {items}.",
        "reminder": "Hi{name}, this is a reminder of your appointment {when}.{location} If you need to change or cancel it, just reply here.",
        "reminder_location": " Place: {location}.",
    },
}

_WEEKDAYS = {
    "es": ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}
_MONTHS = {
    "es": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
}


def _lang(agent: Agent | None) -> str:
    return agent.prompt_language if agent and agent.prompt_language in _TEXT else "es"


def spoken_day(moment: datetime, lang: str) -> str:
    """A day as people say it: "martes 4 de noviembre"."""
    day = _WEEKDAYS[lang][moment.weekday()]
    month = _MONTHS[lang][moment.month - 1]
    return f"{day}, {month} {moment.day}" if lang == "en" else f"{day} {moment.day} de {month}"


def spoken(moment: datetime, lang: str) -> str:
    """A time as people say it: "el martes 4 de noviembre a las 10:30"."""
    if lang == "en":
        return f"on {spoken_day(moment, lang)} at {moment:%H:%M}"
    return f"el {spoken_day(moment, lang)} a las {moment:%H:%M}"


def _contact_scope(conversation: Conversation):
    if conversation.contact_id:
        return or_(Appointment.contact_id == conversation.contact_id, Appointment.conversation_id == conversation.id)
    return Appointment.conversation_id == conversation.id


def upcoming_for(db: Session, conversation: Conversation, now: datetime | None = None) -> list[Appointment]:
    if conversation.id is None:
        return []
    return list(db.scalars(
        select(Appointment).where(
            Appointment.client_id == conversation.client_id, Appointment.status == "confirmed",
            Appointment.starts_at >= (now or now_utc()), _contact_scope(conversation),
        ).order_by(Appointment.starts_at).limit(5)
    ))


def booking_prompt(db: Session, agent: Agent, client: Client, settings: BookingSettings, conversation: Conversation) -> str:
    lang = _lang(agent)
    text = _TEXT[lang]
    local = now_utc().astimezone(zone_of(client))
    today = f"{spoken_day(local, lang)} ({local:%Y-%m-%d})"
    location = text["location"].format(location=settings.location.strip()) if settings.location.strip() else ""
    prompt = text["rules"].format(today=today, now=f"{local:%H:%M}", duration=settings.duration_minutes, location=location)
    upcoming = upcoming_for(db, conversation)
    if upcoming:
        items = "; ".join(f"{a.starts_at.astimezone(zone_of(client)):%Y-%m-%d %H:%M}" for a in upcoming)
        prompt += "\n" + text["upcoming"].format(items=items)
    return prompt


def _parse_local(value: str, client: Client) -> datetime | None:
    value = str(value or "").strip().replace("T", " ")
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=zone_of(client))
        except ValueError:
            continue
    return None


def build_booking_specs(
    db: Session, agent: Agent, conversation: Conversation, changes: BookingChanges,
) -> tuple[list[ToolSpec], str]:
    """The booking tools and their prompt, or ([], "") when the client's book is off."""
    client = agent.client
    settings = settings_for(db, agent.client_id)
    if not client or not settings or not settings.enabled or not settings.slots:
        return [], ""
    zone = zone_of(client)
    length = timedelta(minutes=settings.duration_minutes)

    def pending() -> list[tuple[datetime, datetime]]:
        return [(item["starts_at"], item["starts_at"] + length) for item in changes.booked]

    def check(args: dict) -> tuple[str, bool]:
        start_day = now_utc().astimezone(zone).date()
        if args.get("date"):
            try:
                start_day = max(start_day, date.fromisoformat(str(args["date"])[:10]))
            except ValueError:
                return "date must look like 2026-11-04", True
        try:
            days = int(args.get("days") or 3)
        except (TypeError, ValueError):
            days = 3
        slots = free_slots(db, settings, client, start_day, days, taken=pending())
        if not slots:
            return f"No free times from {start_day.isoformat()} for {days} day(s). Try later dates.", False
        by_day: dict[str, list[str]] = {}
        for slot in slots:
            local = slot.astimezone(zone)
            by_day.setdefault(f"{local:%Y-%m-%d} ({_WEEKDAYS['en'][local.weekday()]})", []).append(f"{local:%H:%M}")
        lines = [f"{day}: {', '.join(times)}" for day, times in by_day.items()]
        return "Free start times (business time):\n" + "\n".join(lines), False

    def book(args: dict) -> tuple[str, bool]:
        start = _parse_local(args.get("start", ""), client)
        if start is None:
            return "start must look like 2026-11-04 10:30, in business time", True
        name = str(args.get("name") or "").strip() or (conversation.contact_name or "").strip()
        if not name:
            return "Ask for the person's name first, then book.", True
        reason = _bookable(settings, client, start, now_utc())
        if reason:
            return f"That time cannot be booked ({reason}). Check availability and offer another time.", True
        overlap = _overlapping(db, client.id, start, start + length) + sum(
            1 for begin, end in pending() if begin < start + length and end > start)
        if overlap >= settings.capacity:
            return "That time was just taken. Check availability and offer another time.", True
        changes.booked.append({"starts_at": start, "name": name[:180], "notes": str(args.get("notes") or "")[:1000]})
        return f"Booked for {name} on {start:%Y-%m-%d %H:%M} (business time). Confirm it to the person in your own words.", False

    def cancel(args: dict) -> tuple[str, bool]:
        start = _parse_local(args.get("start", ""), client)
        if start is None:
            return "start must be the appointment's time, like 2026-11-04 10:30", True
        target = next((a for a in upcoming_for(db, conversation) if a.starts_at == start and a.id not in changes.cancelled), None)
        if target is None:
            return "This person has no upcoming appointment at that time.", True
        changes.cancelled.append(target.id)
        return "Appointment cancelled. Tell the person in your own words.", False

    when = "Business time, like 2026-11-04 10:30"
    specs = [
        ToolSpec(
            name="check_availability",
            description="List the free appointment times for the next days, in business time.",
            input_schema={"type": "object", "properties": {
                "date": {"type": "string", "description": "First day to look at, YYYY-MM-DD; today when left out"},
                "days": {"type": "integer", "description": "How many days to look at, 1 to 14 (3 by default)"},
            }},
            handler=check,
        ),
        ToolSpec(
            name="book_appointment",
            description="Book an appointment at a free time the person chose.",
            input_schema={"type": "object", "properties": {
                "start": {"type": "string", "description": when},
                "name": {"type": "string", "description": "The person's name"},
                "notes": {"type": "string", "description": "What the appointment is for, if the person said"},
            }, "required": ["start", "name"]},
            handler=book,
        ),
        ToolSpec(
            name="cancel_appointment",
            description="Cancel one of this person's upcoming appointments.",
            input_schema={"type": "object", "properties": {"start": {"type": "string", "description": when}}, "required": ["start"]},
            handler=cancel,
        ),
    ]
    return specs, booking_prompt(db, agent, client, settings, conversation)


def apply_bookings(db: Session, agent: Agent, conversation: Conversation, changes: BookingChanges) -> list[Appointment]:
    """Write what the agent booked and cancelled. A time taken meanwhile by
    someone else is skipped and logged rather than overbooked."""
    client = agent.client
    settings = settings_for(db, agent.client_id)
    made: list[Appointment] = []
    for appointment_id in changes.cancelled:
        appointment = db.get(Appointment, appointment_id)
        if appointment and appointment.client_id == agent.client_id and appointment.status == "confirmed":
            appointment.status = "cancelled"
            appointment.reminder_due_at = None
    if not client or not changes.booked:
        return made
    contact = db.get(Contact, conversation.contact_id) if conversation.contact_id else None
    for item in changes.booked:
        start = item["starts_at"]
        end = start + timedelta(minutes=settings.duration_minutes if settings else 30)
        if not fits(db, settings, client.id, start, end):
            logger.warning("Appointment at %s for client %s was taken before it was written", start, client.id)
            continue
        made.append(create_appointment(
            db, client, settings, starts_at=start, name=item["name"], phone=(contact.phone or "") if contact else "",
            notes=item["notes"], source="agent", agent=agent, conversation=conversation,
            contact_id=conversation.contact_id,
        ))
        db.flush()
    return made


# --- Reminders ---------------------------------------------------------------

def reminder_text(appointment: Appointment, agent: Agent | None, client: Client, settings: BookingSettings | None) -> str:
    lang = _lang(agent)
    text = _TEXT[lang]
    first = (appointment.name or "").split()[0] if (appointment.name or "").strip() else ""
    location = settings.location.strip() if settings else ""
    return text["reminder"].format(
        name=f" {first}" if first else "",
        when=spoken(appointment.starts_at.astimezone(zone_of(client)), lang),
        location=text["reminder_location"].format(location=location) if location else "",
    )


def _reminder_conversation(db: Session, appointment: Appointment) -> Conversation | None:
    """Where the reminder goes: the contact's latest conversation on the same
    line, so a reply lands in the current case, else the booking's own."""
    origin = appointment.conversation
    if origin is None or origin.channel not in REMINDER_CHANNELS:
        return None
    if not appointment.contact_id:
        return origin
    latest = db.scalar(
        select(Conversation).where(
            Conversation.contact_id == appointment.contact_id, Conversation.channel == origin.channel,
            Conversation.whatsapp_channel_id.is_not_distinct_from(origin.whatsapp_channel_id),
            Conversation.whatsapp_cloud_channel_id.is_not_distinct_from(origin.whatsapp_cloud_channel_id),
            Conversation.social_channel_id.is_not_distinct_from(origin.social_channel_id),
        ).order_by(Conversation.created_at.desc()).limit(1)
    )
    return latest or origin


async def send_due_reminders(db: Session, *, limit: int = 20) -> int:
    """Send the reminders that are due. Each is claimed before it is sent, so
    a failure is recorded on the appointment instead of retried forever."""
    from .follow_ups import _deliver, _reachable

    sent = 0
    for _ in range(limit):
        now = now_utc()
        appointment = db.scalar(
            select(Appointment)
            .where(Appointment.reminder_due_at <= now, Appointment.status == "confirmed")
            .order_by(Appointment.reminder_due_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if appointment is None:
            db.rollback()
            break
        appointment.reminder_due_at = None
        if appointment.starts_at <= now:
            db.commit()
            continue
        db.commit()
        client = db.get(Client, appointment.client_id)
        conversation = _reminder_conversation(db, appointment)
        agent = db.get(Agent, conversation.agent_id) if conversation else None
        if conversation is None or agent is None or not _reachable(db, conversation):
            appointment.reminder_error = "The contact cannot be reached on the conversation's channel right now."
            db.commit()
            continue
        try:
            message = await _deliver(db, conversation, agent, reminder_text(appointment, agent, client, settings_for(db, client.id)))
        except Exception as exc:  # noqa: BLE001 - one reminder must not stop the rest
            db.rollback()
            appointment = db.get(Appointment, appointment.id)
            message = None
            logger.warning("Reminder for appointment %s failed (%s)", appointment.id, type(exc).__name__)
        if message is None:
            appointment.reminder_error = "The channel did not accept the reminder."
        else:
            appointment.reminder_sent_at = now_utc()
            appointment.reminder_error = None
            sent += 1
        db.commit()
    return sent
