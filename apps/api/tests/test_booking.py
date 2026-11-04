"""Appointment booking: the client's book, the agent's tools and reminders."""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Agent, Appointment, Conversation
from app.services import booking, follow_ups
from conftest import TestingSession
from tests.conftest import login_legacy_owner

EVERY_DAY = [{"day": day, "start": "09:00", "end": "11:00"} for day in range(7)]


def _setup(client: TestClient, **settings) -> tuple[dict, dict]:
    customer = client.post("/api/clients", json={"name": "Spa"}).json()
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Luna"}).json()
    body = {"enabled": True, "duration_minutes": 60, "slots": EVERY_DAY, "min_notice_minutes": 0, **settings}
    response = client.put(f"/api/clients/{customer['id']}/booking", json=body)
    assert response.status_code == 200, response.text
    return customer, agent


def _next_week() -> date:
    return datetime.now(timezone.utc).date() + timedelta(days=7)


def test_settings_defaults_and_validation(authenticated_client: TestClient):
    client = authenticated_client
    customer = client.post("/api/clients", json={"name": "Spa"}).json()
    defaults = client.get(f"/api/clients/{customer['id']}/booking").json()
    assert defaults["enabled"] is False and defaults["slots"] == [] and defaults["duration_minutes"] == 30

    url = f"/api/clients/{customer['id']}/booking"
    assert client.put(url, json={"enabled": True}).status_code == 422  # no hours yet
    assert client.put(url, json={"slots": [{"day": 9, "start": "09:00", "end": "10:00"}]}).status_code == 422
    assert client.put(url, json={"duration_minutes": 2}).status_code == 422
    saved = client.put(url, json={"enabled": True, "slots": EVERY_DAY[:1], "location": "Calle 1"}).json()
    assert saved["enabled"] is True and saved["location"] == "Calle 1"

    stranger = TestClient(app)
    login_legacy_owner(stranger)
    assert stranger.get(url).status_code == 404


def test_free_times_shrink_as_the_team_books(authenticated_client: TestClient):
    client = authenticated_client
    customer, _ = _setup(client)
    day = _next_week()
    slots = client.get(f"/api/clients/{customer['id']}/booking/slots", params={"date": day.isoformat(), "days": 1}).json()["slots"]
    assert [datetime.fromisoformat(s).strftime("%H:%M") for s in slots] == ["09:00", "10:00"]

    start = f"{day.isoformat()}T09:00:00+00:00"
    made = client.post(f"/api/clients/{customer['id']}/appointments", json={"starts_at": start, "name": "Ana"})
    assert made.status_code == 201 and made.json()["source"] == "team"
    assert made.json()["reminder_due_at"]  # 24 h before by default
    assert client.post(f"/api/clients/{customer['id']}/appointments", json={"starts_at": start, "name": "Eva"}).status_code == 409

    slots = client.get(f"/api/clients/{customer['id']}/booking/slots", params={"date": day.isoformat(), "days": 1}).json()["slots"]
    assert [datetime.fromisoformat(s).strftime("%H:%M") for s in slots] == ["10:00"]

    listed = client.get(f"/api/clients/{customer['id']}/appointments", params={"from": day.isoformat()}).json()
    assert [item["name"] for item in listed["appointments"]] == ["Ana"]

    cancelled = client.patch(f"/api/clients/{customer['id']}/appointments/{made.json()['id']}", json={"status": "cancelled"}).json()
    assert cancelled["status"] == "cancelled" and cancelled["reminder_due_at"] is None
    slots = client.get(f"/api/clients/{customer['id']}/booking/slots", params={"date": day.isoformat(), "days": 1}).json()["slots"]
    assert len(slots) == 2


def test_agent_tools_book_and_cancel(authenticated_client: TestClient):
    client = authenticated_client
    customer, agent_out = _setup(client, location="Calle 1")
    conversation_id = client.post("/api/conversations", json={"agent_id": agent_out["id"]}).json()["id"]
    day = _next_week()
    with TestingSession() as db:
        agent = db.get(Agent, uuid.UUID(agent_out["id"]))
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        changes = booking.BookingChanges()
        specs, rules = booking.build_booking_specs(db, agent, conversation, changes)
        assert [spec.name for spec in specs] == ["check_availability", "book_appointment", "cancel_appointment"]
        assert "check_availability" in rules and "Calle 1" in rules
        check, book, cancel = (spec.handler for spec in specs)

        listed, failed = check({"date": day.isoformat(), "days": 1})
        assert not failed and "09:00, 10:00" in listed
        assert book({"start": f"{day.isoformat()} 09:30", "name": "Ana"})[1]  # not on the grid
        assert book({"start": f"{day.isoformat()} 09:00"})[1]  # no name yet
        assert not book({"start": f"{day.isoformat()} 09:00", "name": "Ana", "notes": "Masaje"})[1]
        # Booked in this exchange already: the time is no longer offered or bookable.
        assert "09:00" not in check({"date": day.isoformat(), "days": 1})[0]
        assert book({"start": f"{day.isoformat()} 09:00", "name": "Eva"})[1]

        made = booking.apply_bookings(db, agent, conversation, changes)
        db.commit()
        assert len(made) == 1 and made[0].notes == "Masaje" and made[0].source == "agent"

        changes = booking.BookingChanges()
        specs, rules = booking.build_booking_specs(db, agent, conversation, changes)
        assert f"{day.isoformat()} 09:00" in rules  # the agent sees the upcoming appointment
        assert not specs[2].handler({"start": f"{day.isoformat()} 09:00"})[1]
        booking.apply_bookings(db, agent, conversation, changes)
        db.commit()
        assert db.get(Appointment, made[0].id).status == "cancelled"


def test_book_off_gives_no_tools(authenticated_client: TestClient):
    client = authenticated_client
    customer, agent_out = _setup(client)
    client.put(f"/api/clients/{customer['id']}/booking", json={"enabled": False, "slots": EVERY_DAY})
    conversation_id = client.post("/api/conversations", json={"agent_id": agent_out["id"]}).json()["id"]
    with TestingSession() as db:
        agent = db.get(Agent, uuid.UUID(agent_out["id"]))
        specs, rules = booking.build_booking_specs(db, agent, db.get(Conversation, uuid.UUID(conversation_id)), booking.BookingChanges())
        assert specs == [] and rules == ""


def test_due_reminder_goes_out_once(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    customer, agent_out = _setup(client, location="Calle 1")
    conversation_id = client.post("/api/conversations", json={"agent_id": agent_out["id"]}).json()["id"]
    sent: list[str] = []

    async def deliver(db, conversation, agent, text):
        sent.append(text)
        return object()

    monkeypatch.setattr(follow_ups, "_reachable", lambda db, conversation: True)
    monkeypatch.setattr(follow_ups, "_deliver", deliver)
    with TestingSession() as db:
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        conversation.channel = "whatsapp"
        start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=3)
        db.add(Appointment(agency_id=conversation.agency_id, client_id=conversation.client_id, conversation_id=conversation.id,
                           name="Ana Pérez", starts_at=start, ends_at=start + timedelta(hours=1),
                           reminder_due_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        db.commit()
        assert asyncio.run(booking.send_due_reminders(db)) == 1
        assert asyncio.run(booking.send_due_reminders(db)) == 0
        item = db.scalars(select(Appointment)).first()
    assert len(sent) == 1 and sent[0].startswith("Hola Ana,") and "Calle 1" in sent[0]
    assert item.reminder_sent_at is not None and item.reminder_due_at is None


def test_reminder_skips_unreachable_channels(authenticated_client: TestClient):
    client = authenticated_client
    customer, agent_out = _setup(client)
    conversation_id = client.post("/api/conversations", json={"agent_id": agent_out["id"]}).json()["id"]
    with TestingSession() as db:
        conversation = db.get(Conversation, uuid.UUID(conversation_id))  # playground: nobody to remind
        start = datetime.now(timezone.utc) + timedelta(hours=3)
        db.add(Appointment(agency_id=conversation.agency_id, client_id=conversation.client_id, conversation_id=conversation.id,
                           name="Ana", starts_at=start, ends_at=start + timedelta(hours=1),
                           reminder_due_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        db.commit()
        assert asyncio.run(booking.send_due_reminders(db)) == 0
        item = db.scalars(select(Appointment)).first()
    assert item.reminder_error and item.reminder_sent_at is None
