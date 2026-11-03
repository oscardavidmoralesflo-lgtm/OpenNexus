"""The value numbers on Home: AI-resolved share, first reply time, AI replies and cost."""

from datetime import timedelta
from decimal import Decimal
import uuid

from fastapi.testclient import TestClient

from app.models import Conversation, Message, UsageRecord, now_utc
from conftest import TestingSession


def test_metrics_report_what_the_ai_did(authenticated_client: TestClient):
    client = authenticated_client
    customer = client.post("/api/clients", json={"name": "Cafe"}).json()
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Luna"}).json()
    empty = client.get("/api/dashboard/metrics", params={"days": 7}).json()
    assert empty["ai_resolved_pct"] == 0 and empty["first_reply_median_s"] is None and empty["ai_cost_usd"] == 0

    ids = [client.post("/api/conversations", json={"agent_id": agent["id"]}).json()["id"] for _ in range(2)]
    with TestingSession() as db:
        solved, handed = (db.get(Conversation, uuid.UUID(i)) for i in ids)
        solved.first_reply_at = solved.created_at + timedelta(seconds=4)
        solved.resolved_at = now_utc()
        handed.first_reply_at = handed.created_at + timedelta(seconds=10)
        handed.taken_over_at = now_utc()
        handed.resolved_at = now_utc()
        db.add(Message(conversation_id=solved.id, role="assistant", sender_type="ai", content="Hola"))
        db.add(UsageRecord(agency_id=solved.agency_id, agent_id=solved.agent_id, provider="openrouter", model="m",
                           input_tokens=10, output_tokens=5, cost_usd=Decimal("0.0125")))
        db.commit()

    metrics = client.get("/api/dashboard/metrics", params={"days": 7}).json()
    assert metrics["conversations"] == 2
    assert metrics["ai_resolved"] == 1 and metrics["ai_resolved_pct"] == 50.0
    assert metrics["first_reply_median_s"] == 7.0
    assert metrics["ai_replies"] == 1
    assert metrics["ai_cost_usd"] == 0.0125
