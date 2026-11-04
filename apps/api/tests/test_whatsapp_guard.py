"""The ban shield of WhatsApp QR lines: limits on what a line starts, the
warm-up of a new number, and a pause when WhatsApp pushes back."""

import asyncio
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models import Conversation, Message, WhatsAppChannel, WhatsAppSendEvent, now_utc
from app.services import follow_ups, whatsapp_guard as guard
from app.services import whatsapp_inbound as pipeline
from app.services.ai import Completion
from app.services.whatsapp import send_channel_message
from conftest import TestingSession

CHAT = "573001112233@s.whatsapp.net"


@pytest.fixture
def line(authenticated_client, monkeypatch):
    client = authenticated_client
    customer = client.post("/api/clients", json={"name": "Barber shop", "industry": "other"}).json()
    client.put("/api/providers/openrouter", json={"api_key": "sk-test"})
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Ana", "model": "openai/gpt-4.1-mini",
                                             "prompt_language": "en"}).json()
    channel = client.put(f"/api/whatsapp/channels/{customer['id']}", json={"agent_id": agent["id"]}).json()
    headers = {"X-Bridge-Token": get_settings().whatsapp_bridge_token}
    # The phone links: a number new to the line starts its warm-up today.
    assert client.put(f"/api/internal/whatsapp/channels/{channel['id']}/status", headers=headers,
                      json={"status": "connected", "phone_number": "573009990000"}).status_code == 204
    bridge = AsyncMock(side_effect=lambda *a, **k: {"external_message_id": f"wa-{uuid.uuid4().hex}"})
    monkeypatch.setattr("app.services.whatsapp.bridge_command", bridge)
    return client, customer, agent, channel, headers, bridge


def _conversation(line_, *, contact_wrote: bool, chat: str = CHAT) -> uuid.UUID:
    _, customer, agent, channel, _, _ = line_
    with TestingSession() as db:
        row = Conversation(agency_id=db.get(WhatsAppChannel, uuid.UUID(channel["id"])).agency_id,
                           client_id=uuid.UUID(customer["id"]), agent_id=uuid.UUID(agent["id"]), channel="whatsapp",
                           whatsapp_channel_id=uuid.UUID(channel["id"]), external_chat_id=chat, title="Chat")
        db.add(row)
        db.flush()
        if contact_wrote:
            db.add(Message(conversation_id=row.id, role="user", content="hi"))
        db.commit()
        return row.id


def _send(conversation_id, text, intent):
    with TestingSession() as db:
        conversation = db.get(Conversation, conversation_id)
        result = asyncio.run(send_channel_message(db, conversation, text, intent=intent))
        db.commit()
        return result


def _events(channel_id, n, kind="proactive", text=None, ago=timedelta(minutes=2)):
    with TestingSession() as db:
        for i in range(n):
            db.add(WhatsAppSendEvent(channel_id=uuid.UUID(channel_id), kind=kind,
                                     text_hash=guard.text_hash(text or f"message {i}"), created_at=now_utc() - ago))
        db.commit()


def test_a_new_number_warms_up_and_replies_always_go_out(line):
    client, _, _, channel, _, bridge = line
    chat = _conversation(line, contact_wrote=True)
    health = client.get(f"/api/whatsapp/channels/{channel['id']}/guard").json()
    assert health["warming_up"] and health["warmup_day"] == 1 and health["outreach_limit"] == 20

    _events(channel["id"], 20)
    with pytest.raises(HTTPException) as held:
        _send(chat, "Still interested?", "proactive")
    assert held.value.status_code == 429 and "warm-up day 1" in held.value.detail
    assert _send(chat, "Sure, 3 pm works", "reply")              # answering is never held
    assert bridge.await_count == 1

    # A week later the allowance is the full one.
    with TestingSession() as db:
        db.get(WhatsAppChannel, uuid.UUID(channel["id"])).warmup_started_at -= timedelta(days=8)
        db.commit()
    assert _send(chat, "Still interested?", "proactive")
    health = client.get(f"/api/whatsapp/channels/{channel['id']}/guard").json()
    assert not health["warming_up"] and health["outreach_limit"] == guard.DAILY
    assert health["outreach_today"] == 21 and health["replies_today"] == 1


def test_strangers_and_the_same_text_have_their_own_caps(line):
    _, _, _, channel, _, _ = line
    for n in range(guard.STRANGERS_EARLY):
        _send(_conversation(line, contact_wrote=False, chat=f"57300000000{n}@s.whatsapp.net"), f"Hello {n}", "operator")
    with pytest.raises(HTTPException) as held:
        _send(_conversation(line, contact_wrote=False, chat="573000000009@s.whatsapp.net"), "Hello again", "operator")
    assert "never wrote" in held.value.detail

    chat = _conversation(line, contact_wrote=True, chat="573111111111@s.whatsapp.net")
    _events(channel["id"], guard.IDENTICAL_PER_HOUR, text="Promo: 2x1 today!")
    with pytest.raises(HTTPException) as held:
        _send(chat, "PROMO 2x1 today", "proactive")             # the same words, other spacing and case
    assert "same message" in held.value.detail
    assert _send(chat, "Your order is ready", "proactive")


def test_failures_disconnects_and_bans_pause_the_line(line):
    client, _, _, channel, headers, bridge = line
    channel_id = uuid.UUID(channel["id"])
    chat = _conversation(line, contact_wrote=True)
    bridge.side_effect = HTTPException(status_code=502, detail="server returned error 463")
    for _ in range(guard.FAILED_PER_HOUR):
        with pytest.raises(HTTPException):
            _send(chat, "Hi there", "reply")
    health = client.get(f"/api/whatsapp/channels/{channel['id']}/guard").json()
    assert health["paused_until"] and health["pause_code"] == "failed" and "refused several" in health["pause_reason"] and health["failed_last_hour"] == 5

    bridge.side_effect = lambda *a, **k: {"external_message_id": "wa-1"}
    with pytest.raises(HTTPException) as held:
        _send(chat, "Following up", "proactive")
    assert "Paused by the ban shield" in held.value.detail
    assert _send(chat, "Yes, we open at 9", "reply")             # people who write still get answers

    resumed = client.post(f"/api/whatsapp/channels/{channel['id']}/guard/resume").json()
    assert resumed["paused_until"] is None
    assert _send(chat, "Following up", "proactive")

    for _ in range(guard.DISCONNECTS_PER_HOUR):
        client.put(f"/api/internal/whatsapp/channels/{channel_id}/status", headers=headers,
                   json={"status": "reconnecting", "error": "Connection interrupted. Retrying..."})
    assert "disconnected the number" in client.get(f"/api/whatsapp/channels/{channel_id}/guard").json()["pause_reason"]

    client.post(f"/api/whatsapp/channels/{channel_id}/guard/resume")
    client.put(f"/api/internal/whatsapp/channels/{channel_id}/status", headers=headers,
               json={"status": "error", "error": "WhatsApp temporarily banned this number: reason 101"})
    with TestingSession() as db:
        row = db.get(WhatsAppChannel, channel_id)
        assert row.guard_paused_until - now_utc() > timedelta(hours=23)

    # Switching the shield off is the operator's call.
    assert client.put(f"/api/whatsapp/channels/{channel_id}/guard", json={"enabled": False}).json()["enabled"] is False
    assert _send(chat, "Following up", "proactive")


def test_relinking_the_same_number_keeps_its_warm_up(line):
    client, _, _, channel, headers, _ = line
    channel_id = uuid.UUID(channel["id"])
    with TestingSession() as db:
        db.get(WhatsAppChannel, channel_id).warmup_started_at -= timedelta(days=10)
        db.commit()
    status = f"/api/internal/whatsapp/channels/{channel_id}/status"
    client.put(status, headers=headers, json={"status": "connected", "phone_number": "573009990000"})
    assert client.get(f"/api/whatsapp/channels/{channel_id}/guard").json()["warmup_day"] == 11
    client.put(status, headers=headers, json={"status": "connected", "phone_number": "573005550000"})
    assert client.get(f"/api/whatsapp/channels/{channel_id}/guard").json()["warmup_day"] == 1


def test_a_held_follow_up_waits_instead_of_being_lost(line, monkeypatch):
    client, _, agent, channel, headers, bridge = line
    client.put(f"/api/agents/{agent['id']}/follow-ups",
               json={"enabled": True, "first_minutes": 60, "second_minutes": 180, "close_minutes": 360})
    monkeypatch.setattr(pipeline, "run_completion", AsyncMock(return_value=Completion(text="Shall I book you?")))
    monkeypatch.setattr(follow_ups, "chat_completion", AsyncMock(return_value=Completion(text="Still want it?")))
    client.post(f"/api/internal/whatsapp/channels/{channel['id']}/inbound", headers=headers,
                json={"external_message_id": "in-1", "remote_jid": CHAT, "text": "A slot tomorrow?"})
    with TestingSession() as db:
        row = db.scalar(select(Conversation).where(Conversation.whatsapp_channel_id == uuid.UUID(channel["id"])))
        row.follow_up_anchor_at -= timedelta(minutes=61)
        row.follow_up_due_at -= timedelta(minutes=61)
        db.commit()
        conversation_id = row.id
    _events(channel["id"], 20)
    sent_before = bridge.await_count
    with TestingSession() as db:
        asyncio.run(follow_ups.run_due(db))
    with TestingSession() as db:
        row = db.get(Conversation, conversation_id)
        assert row.follow_up_step == 0 and row.follow_up_due_at > now_utc() + timedelta(hours=23)
    assert bridge.await_count == sent_before
