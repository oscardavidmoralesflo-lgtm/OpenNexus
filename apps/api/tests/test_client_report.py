"""The monthly client report: one client's month next to the one before."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.models import Conversation, Message, UsageRecord
from conftest import TestingSession
from tests.conftest import login_legacy_owner


def _at(month_start: datetime, conversation_id: str, **fields) -> None:
    """Move a conversation into a month, with one AI reply and $0.50 of usage."""
    with TestingSession() as db:
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        conversation.created_at = month_start + timedelta(days=3)
        for key, value in fields.items():
            setattr(conversation, key, value)
        db.add(Message(conversation_id=conversation.id, role="assistant", sender_type="ai", content="Hola",
                       created_at=month_start + timedelta(days=3, minutes=1)))
        db.add(UsageRecord(agency_id=conversation.agency_id, agent_id=conversation.agent_id, provider="openrouter",
                           model="m", input_tokens=1, output_tokens=1, cost_usd=Decimal("0.5"), conversation_id=conversation.id,
                           created_at=month_start + timedelta(days=3)))
        db.commit()


def test_report_counts_one_client_month_without_rehearsals(authenticated_client: TestClient):
    client = authenticated_client
    customer = client.post("/api/clients", json={"name": "Cafe"}).json()
    other = client.post("/api/clients", json={"name": "Otro"}).json()
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Luna"}).json()
    other_agent = client.post("/api/agents", json={"client_id": other["id"], "name": "Sol"}).json()

    october = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    solved = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    _at(october, solved["id"], channel="widget", resolved_at=october + timedelta(days=3, hours=1),
        first_reply_at=october + timedelta(days=3, seconds=5))
    rehearsal = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    _at(october, rehearsal["id"])  # playground: left out
    elsewhere = client.post("/api/conversations", json={"agent_id": other_agent["id"]}).json()
    _at(october, elsewhere["id"], channel="widget")
    september = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    _at(datetime(2026, 9, 1, 12, tzinfo=timezone.utc), september["id"], channel="widget")

    report = client.get(f"/api/clients/{customer['id']}/monthly-report", params={"month": "2026-10"}).json()
    assert report["client"]["name"] == "Cafe"
    current = report["current"]
    assert current["month"] == "2026-10"
    assert current["totals"]["conversations"] == 1 and current["totals"]["ai_resolved"] == 1
    assert current["by_channel"] == [{"channel": "widget", "conversations": 1}]
    assert current["ai_cost_usd"] == 0.5  # the rehearsal's usage is the agency's, not the client's
    assert report["previous"]["month"] == "2026-09" and report["previous"]["totals"]["conversations"] == 1

    assert client.get(f"/api/clients/{customer['id']}/monthly-report", params={"month": "octubre"}).status_code == 422
    stranger = TestClient(app)
    login_legacy_owner(stranger)
    assert stranger.get(f"/api/clients/{customer['id']}/monthly-report").status_code == 404
