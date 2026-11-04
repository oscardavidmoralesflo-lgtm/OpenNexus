"""The sales pipeline: a board of contacts by stage, moved by agents and people."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Agent, Appointment, Contact, Conversation
from app.services import booking, pipeline
from conftest import TestingSession
from tests.conftest import login_legacy_owner


def _setup(client: TestClient) -> tuple[dict, dict, str, str]:
    customer = client.post("/api/clients", json={"name": "Spa"}).json()
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Luna"}).json()
    conversation_id = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()["id"]
    with TestingSession() as db:
        contact = Contact(client_id=uuid.UUID(customer["id"]), name="Ana", phone="573001112233")
        db.add(contact)
        db.flush()
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        conversation.contact_id = contact.id
        conversation.channel = "whatsapp"
        db.commit()
        contact_id = str(contact.id)
    return customer, agent, conversation_id, contact_id


def test_board_lists_contacts_by_stage_and_people_move_them(authenticated_client: TestClient):
    client = authenticated_client
    customer, _, conversation_id, contact_id = _setup(client)
    board = client.get(f"/api/clients/{customer['id']}/pipeline").json()
    assert board["enabled"] is False
    assert [s["stage"] for s in board["stages"]] == list(pipeline.STAGES)
    new = board["stages"][0]
    assert new["total"] == 1 and new["contacts"][0]["name"] == "Ana"
    assert new["contacts"][0]["last_conversation_id"] == conversation_id

    url = f"/api/clients/{customer['id']}/pipeline/contacts/{contact_id}"
    with TestingSession() as db:  # a second contact with a value elsewhere must not count
        db.add(Contact(client_id=uuid.UUID(customer["id"]), name="Eva", phone="573009998877", stage="lost", deal_value=99))
        db.commit()
    moved = client.patch(url, json={"stage": "won", "deal_value": 250000}).json()
    assert moved["stage"] == "won" and moved["deal_value"] == 250000
    assert client.patch(url, json={"stage": "nope"}).status_code == 422
    board = client.get(f"/api/clients/{customer['id']}/pipeline").json()
    won = next(s for s in board["stages"] if s["stage"] == "won")
    assert won["total"] == 1 and won["value"] == 250000
    assert client.get(f"/api/clients/{customer['id']}/pipeline", params={"q": "zzz"}).json()["stages"][3]["total"] == 0

    stranger = TestClient(app)
    login_legacy_owner(stranger)
    assert stranger.get(f"/api/clients/{customer['id']}/pipeline").status_code == 404
    assert stranger.patch(url, json={"stage": "lost"}).status_code == 404


def test_agent_moves_the_contact_only_when_the_pipeline_is_on(authenticated_client: TestClient):
    client = authenticated_client
    customer, agent_out, conversation_id, contact_id = _setup(client)
    with TestingSession() as db:
        agent = db.get(Agent, uuid.UUID(agent_out["id"]))
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        assert pipeline.build_stage_spec(db, agent, conversation, pipeline.StageChanges()) == (None, "")

    assert client.put(f"/api/clients/{customer['id']}/pipeline/settings", json={"enabled": True}).json() == {"enabled": True}
    with TestingSession() as db:
        agent = db.get(Agent, uuid.UUID(agent_out["id"]))
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        holder = pipeline.StageChanges()
        spec, rules = pipeline.build_stage_spec(db, agent, conversation, holder)
        assert spec.name == "update_sales_stage" and "Etapa actual: new" in rules
        assert spec.handler({"stage": "new"})[1]  # agents never move a contact back to new
        assert not spec.handler({"stage": "qualified", "deal_value": "120000"})[1]
        pipeline.apply_stage(db, conversation, holder)
        db.commit()
        contact = db.get(Contact, uuid.UUID(contact_id))
        assert contact.stage == "qualified" and float(contact.deal_value) == 120000 and contact.stage_changed_at


def test_booking_moves_an_early_contact_to_booked(authenticated_client: TestClient):
    client = authenticated_client
    customer, agent_out, conversation_id, contact_id = _setup(client)
    every_day = [{"day": day, "start": "09:00", "end": "11:00"} for day in range(7)]
    client.put(f"/api/clients/{customer['id']}/booking", json={"enabled": True, "duration_minutes": 60, "slots": every_day, "min_notice_minutes": 0})
    day = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    with TestingSession() as db:
        agent = db.get(Agent, uuid.UUID(agent_out["id"]))
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        changes = booking.BookingChanges()
        specs, _ = booking.build_booking_specs(db, agent, conversation, changes)
        assert not specs[1].handler({"start": f"{day} 09:00", "name": "Ana"})[1]
        booking.apply_bookings(db, agent, conversation, changes)
        db.commit()
        assert db.scalar(select(Appointment)).phone == "573001112233"
        assert db.get(Contact, uuid.UUID(contact_id)).stage == "booked"
