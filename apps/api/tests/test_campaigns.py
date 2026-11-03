"""WhatsApp campaigns: an approved template to a filtered list of contacts."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Campaign, Contact, Conversation, Message
from app.services import campaigns as campaigns_service
from app.services import template_webhooks as webhook_service
from conftest import TestingSession
from tests.conftest import login_legacy_owner
from tests.test_template_webhooks import PENDING, PROMO, REMINDER, _contact_writes, _setup


def _contacts(client_id: str) -> tuple[str, str, str]:
    with TestingSession() as db:
        ana = Contact(client_id=uuid.UUID(client_id), name="Ana Pérez", phone="573001112233", stage="qualified")
        eva = Contact(client_id=uuid.UUID(client_id), name="Eva", phone="573004445566")
        gone = Contact(client_id=uuid.UUID(client_id), name="Bloqueado", phone="573007778899", blocked_at=datetime.now(timezone.utc))
        db.add_all([ana, eva, gone, Contact(client_id=uuid.UUID(client_id), name="Sin número")])
        db.commit()
        return str(ana.id), str(eva.id), str(gone.id)


def _run() -> int:
    with TestingSession() as db:
        return asyncio.run(campaigns_service.run_due_campaigns(db))


def test_campaign_reaches_its_audience_once(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    customer, _, channel, _ = _setup(client, monkeypatch)
    sent = AsyncMock(side_effect=[f"wamid.c{n}" for n in range(1, 10)])
    monkeypatch.setattr(campaigns_service, "send_template", sent)
    ana_id, _, _ = _contacts(customer["id"])
    base = f"/api/clients/{customer['id']}/campaigns"

    assert client.post(f"{base}/audience", json={}).json() == {"count": 2}  # blocked and phoneless left out
    assert client.post(f"{base}/audience", json={"stages": ["qualified"]}).json() == {"count": 1}
    assert client.post(f"{base}/audience", json={"stages": ["new"]}).json() == {"count": 1}

    body = {"name": "Promo noviembre", "channel_id": channel["id"], "template_name": "appointment_reminder",
            "template_language": "es", "variables": {"nombre": "{first_name}", "fecha": "viernes", "hora": "10 am"}}
    assert client.post(base, json={**body, "template_name": "promo"}).status_code == 409  # not approved
    created = client.post(base, json=body)
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert campaign["status"] == "draft" and campaign["stats"]["total"] == 0

    started = client.post(f"{base}/{campaign['id']}/start", json={}).json()
    assert started["status"] == "scheduled" and started["stats"]["pending"] == 2
    assert client.put(f"{base}/{campaign['id']}", json=body).status_code == 409  # no edits once started

    assert _run() == 2
    assert _run() == 0  # nothing left: each contact got it once
    assert sent.await_count == 2
    first_call = sent.await_args_list[0]
    params = first_call.kwargs["components"][0]["parameters"]
    assert {p["text"] for p in params} >= {"viernes", "10 am"}

    out = client.get(base).json()[0]
    assert out["status"] == "done" and out["stats"]["sent"] == 2 and out["stats"]["failed"] == 0
    with TestingSession() as db:
        conversation = db.scalar(select(Conversation).where(Conversation.contact_id == uuid.UUID(ana_id)))
        message = db.scalar(select(Message).where(Message.conversation_id == conversation.id, Message.role == "assistant"))
        assert message.content.startswith("Hola Ana,") and "Promo noviembre" in message.llm_content

    # A reply counts, and lands in the same conversation for the agent to answer.
    monkeypatch.setattr("app.services.whatsapp_inbound.run_completion", AsyncMock(side_effect=RuntimeError("no model")))
    _contact_writes(client, channel, "¡Me interesa!", "wamid.reply1")
    assert client.get(base).json()[0]["stats"]["replied"] == 1

    recipients = client.get(f"{base}/{campaign['id']}/recipients").json()
    assert {r["status"] for r in recipients} == {"sent"}

    stranger = TestClient(app)
    login_legacy_owner(stranger)
    assert stranger.get(f"{base}/{campaign['id']}/recipients").status_code == 404


def test_scheduled_campaign_waits_and_can_be_stopped(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    customer, _, channel, _ = _setup(client, monkeypatch)
    sent = AsyncMock(return_value="wamid.x")
    monkeypatch.setattr(campaigns_service, "send_template", sent)
    _contacts(customer["id"])
    base = f"/api/clients/{customer['id']}/campaigns"
    campaign = client.post(base, json={"name": "Venta", "channel_id": channel["id"], "template_name": "spring_sale",
                                       "template_language": "es"}).json()
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert client.post(f"{base}/{campaign['id']}/start", json={"scheduled_at": later}).json()["status"] == "scheduled"
    assert _run() == 0 and sent.await_count == 0
    stopped = client.post(f"{base}/{campaign['id']}/cancel").json()
    assert stopped["status"] == "cancelled" and stopped["stats"]["failed"] == 2
    assert client.delete(f"{base}/{campaign['id']}").status_code == 204


def test_paused_template_puts_the_campaign_back_to_draft(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    customer, _, channel, _ = _setup(client, monkeypatch)
    monkeypatch.setattr(campaigns_service, "send_template", AsyncMock(return_value="wamid.x"))
    _contacts(customer["id"])
    base = f"/api/clients/{customer['id']}/campaigns"
    campaign = client.post(base, json={"name": "Venta", "channel_id": channel["id"], "template_name": "spring_sale",
                                       "template_language": "es"}).json()
    client.post(f"{base}/{campaign['id']}/start", json={})
    monkeypatch.setattr(webhook_service, "list_templates", AsyncMock(return_value=[REMINDER, PENDING]))  # Meta paused it
    assert _run() == 0
    with TestingSession() as db:
        stored = db.get(Campaign, uuid.UUID(campaign["id"]))
        assert stored.status == "draft" and "not approved" in stored.last_error
    assert PROMO["status"] == "APPROVED"
