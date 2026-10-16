"""Plans, AI credit and payments, for a deployment that bills its agency."""

import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.models import Agency
from app.routers import conversations as conversations_router
from app.services import ai as ai_service
from app.services import billing, providers, usage
from tests.conftest import TestingSession

WEBHOOK_SECRET = "whsec_test"


@pytest.fixture
def billed(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "billing_platform_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_credit_markup", 1.5)
    monkeypatch.setattr(settings, "billing_topup_bonus_percent", 30.0)
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "billing_default_plan", "launch")
    billing.install()
    yield settings
    providers.register_credential_fallback(None)
    if billing.meter in usage._usage_hooks:
        usage._usage_hooks.remove(billing.meter)


def _agency() -> Agency:
    with TestingSession() as db:
        return db.scalar(select(Agency))


def _event(client: TestClient, event: dict, secret: str = WEBHOOK_SECRET):
    payload = json.dumps(event).encode()
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return client.post("/api/billing/webhook", content=payload, headers={"Stripe-Signature": f"t={timestamp},v1={signature}", "Content-Type": "application/json"})


def test_disabled_billing_changes_nothing(authenticated_client: TestClient):
    overview = authenticated_client.get("/api/billing").json()
    assert overview["enabled"] is False
    assert authenticated_client.get("/api/auth/me").json()["agency"]["billing_enabled"] is False
    for index in range(7):
        assert authenticated_client.post("/api/clients", json={"name": f"Client {index}"}).status_code == 201
    assert authenticated_client.get("/api/billing/spend").status_code == 404


def test_plan_limits_clients_but_not_the_sandbox(authenticated_client: TestClient, billed):
    client = authenticated_client
    for index in range(5):
        assert client.post("/api/clients", json={"name": f"Client {index}"}).status_code == 201
    refused = client.post("/api/clients", json={"name": "Sixth"})
    assert refused.status_code == 402 and "Launch" in refused.json()["detail"]
    # The sandbox comes with the account and never counts.
    assert client.post("/api/sandbox").status_code == 200
    overview = client.get("/api/billing").json()
    assert overview["clients_used"] == 5 and overview["plan"]["id"] == "launch" and overview["plan"]["max_clients"] == 5
    assert [p["id"] for p in overview["plans"]] == ["launch", "growth", "unlimited"]


def test_no_default_plan_means_subscribe_first(authenticated_client: TestClient, billed, monkeypatch):
    monkeypatch.setattr(billed, "billing_default_plan", "")
    assert authenticated_client.post("/api/clients", json={"name": "Nope"}).status_code == 402


def test_platform_key_answers_on_credit_and_is_charged(authenticated_client: TestClient, billed, monkeypatch):
    client = authenticated_client
    agency = _agency()
    # No credit: the platform does not lend its key.
    with TestingSession() as db:
        assert providers.resolve_provider_credentials(db, agency.id, "openrouter") is None
        billing.grant(db, agency.id, Decimal("1"), "Welcome credit")
        assert providers.resolve_provider_credentials(db, agency.id, "openrouter")[1] == "sk-platform"

    customer = client.post("/api/clients", json={"name": "Cafe"}).json()
    agent = client.post("/api/agents", json={"client_id": customer["id"], "name": "Luna", "model": "openai/gpt-5.6-luna"}).json()
    conversation = client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    completion = ai_service.Completion(text="Hi", input_tokens=1000, output_tokens=1000, cost_usd=0.02)
    monkeypatch.setattr(conversations_router, "run_completion", AsyncMock(return_value=completion))
    assert client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "hola"}).status_code == 200

    # 0.02 at cost × 1.5 markup = 0.03 charged.
    overview = client.get("/api/billing").json()
    assert overview["credit_balance"] == pytest.approx(0.97)
    ledger = client.get("/api/billing/transactions").json()
    assert [t["kind"] for t in ledger] == ["usage", "adjustment"]
    assert ledger[0]["amount_usd"] == pytest.approx(-0.03)
    spend = client.get("/api/billing/spend?days=7").json()
    assert spend["platform"] == {"usd": pytest.approx(0.03), "replies": 1, "percent": 100}
    assert spend["own"]["replies"] == 0

    # With the agency's own key, replies are not charged.
    client.put("/api/providers/openrouter", json={"api_key": "sk-own"})
    client.post(f"/api/conversations/{conversation['id']}/messages", json={"content": "otra"})
    assert client.get("/api/billing").json()["credit_balance"] == pytest.approx(0.97)
    spend = client.get("/api/billing/spend?days=7").json()
    assert spend["own"]["replies"] == 1 and spend["own"]["usd"] == pytest.approx(0.02)


def test_unpriced_replies_are_charged_at_list_price(billed):
    from app.models import UsageRecord

    agency = None
    with TestingSession() as db:
        agency = Agency(name="Solo", slug="solo")
        db.add(agency)
        db.commit()
        billing.grant(db, agency.id, Decimal("5"), "")
        record = UsageRecord(agency_id=agency.id, provider="openrouter", model="openai/gpt-5.6-luna", input_tokens=10_000, output_tokens=1_000)
        db.add(record)
        billing.meter(db, record, None)
        db.commit()
        # (10 × 0.0002 + 1 × 0.0012) × 1.5 = 0.0048
        assert billing.balance(db.get(Agency, agency.id)) == Decimal("4.995200")


def test_webhook_topup_with_bonus_is_applied_once(authenticated_client: TestClient, billed):
    agency = _agency()
    event = {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_1", "customer": "cus_1", "payment_status": "paid", "client_reference_id": str(agency.id),
        "metadata": {"agency_id": str(agency.id), "kind": "topup", "amount_usd": "10"},
    }}}
    assert _event(authenticated_client, event).json()["outcome"] == "topup"
    assert _event(authenticated_client, event).json()["outcome"] == "duplicate"
    overview = authenticated_client.get("/api/billing").json()
    assert overview["credit_balance"] == pytest.approx(13.0)
    assert overview["customer_id"] == "cus_1"
    kinds = [t["kind"] for t in authenticated_client.get("/api/billing/transactions").json()]
    assert sorted(kinds) == ["bonus", "topup"]


def test_webhook_rejects_bad_signatures(authenticated_client: TestClient, billed):
    assert _event(authenticated_client, {"type": "x", "data": {"object": {}}}, secret="whsec_wrong").status_code == 400
    assert authenticated_client.post("/api/billing/webhook", content=b"{}").status_code == 400


def test_webhook_subscription_lifecycle(authenticated_client: TestClient, billed):
    agency = _agency()
    ref = {"agency_id": str(agency.id)}
    _event(authenticated_client, {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_sub", "customer": "cus_9", "subscription": "sub_9", "metadata": {**ref, "kind": "subscription", "plan": "growth"},
    }}})
    overview = authenticated_client.get("/api/billing").json()
    assert overview["plan"]["id"] == "growth" and overview["subscribed"] is True
    _event(authenticated_client, {"type": "invoice.payment_failed", "data": {"object": {"customer": "cus_9"}}})
    overview = authenticated_client.get("/api/billing").json()
    assert overview["subscription_status"] == "past_due" and overview["plan"]["id"] == "launch"
    _event(authenticated_client, {"type": "customer.subscription.updated", "data": {"object": {"id": "sub_9", "customer": "cus_9", "status": "active", "metadata": {"plan": "unlimited"}}}})
    assert authenticated_client.get("/api/billing").json()["plan"]["id"] == "unlimited"
    _event(authenticated_client, {"type": "customer.subscription.deleted", "data": {"object": {"id": "sub_9", "customer": "cus_9"}}})
    overview = authenticated_client.get("/api/billing").json()
    assert overview["subscribed"] is False and overview["subscription_status"] == "canceled"


def test_checkout_calls_stripe_with_the_plan_price(authenticated_client: TestClient, billed, monkeypatch):
    monkeypatch.setattr(billed, "billing_plans", json.dumps([{"id": "pro", "name": "Pro", "price_usd": 99, "max_clients": 10, "stripe_price_id": "price_pro"}]))
    monkeypatch.setattr(billed, "stripe_secret_key", "sk_test")
    calls = []

    async def fake_post(path, data):
        calls.append((path, data))
        return {"id": "cus_x"} if path == "customers" else {"url": f"https://checkout.example/{path}"}

    monkeypatch.setattr(billing, "stripe_post", fake_post)
    response = authenticated_client.post("/api/billing/checkout", json={"plan_id": "pro"})
    assert response.status_code == 200 and response.json()["url"].startswith("https://checkout.example/")
    session = calls[-1][1]
    assert session["mode"] == "subscription" and session["line_items"] == [{"price": "price_pro", "quantity": 1}]
    topup = authenticated_client.post("/api/billing/topup", json={"amount": 25})
    assert topup.status_code == 200 and calls[-1][1]["line_items"][0]["price_data"]["unit_amount"] == 2500
    assert authenticated_client.post("/api/billing/topup", json={"amount": 7}).status_code == 400


def test_stripe_form_encoding():
    pairs = billing._flatten({"mode": "payment", "line_items": [{"price_data": {"unit_amount": 100}}], "metadata": {"a": "b"}})
    assert ("line_items[0][price_data][unit_amount]", "100") in pairs and ("metadata[a]", "b") in pairs
