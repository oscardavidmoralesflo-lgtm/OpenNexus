"""The agency's audit log: what gets recorded, who may read it, and isolation."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import audit
from tests.conftest import login_legacy_owner


def _actions(client: TestClient, **params) -> list[str]:
    response = client.get("/api/audit", params=params)
    assert response.status_code == 200, response.text
    return [event["action"] for event in response.json()["events"]]


def test_dashboard_writes_are_recorded_newest_first(authenticated_client: TestClient):
    customer = authenticated_client.post("/api/clients", json={"name": "Cafe"}).json()
    agent = authenticated_client.post("/api/agents", json={"client_id": customer["id"], "name": "Luna"}).json()
    assert authenticated_client.patch(f"/api/agents/{agent['id']}", json={"name": "Luna 2"}).status_code == 200

    events = authenticated_client.get("/api/audit").json()["events"]
    assert [e["action"] for e in events[:3]] == ["agents.update", "agents.create", "clients.create"]
    latest = events[0]
    assert latest["actor_email"] == "ana@prisma.com"
    assert latest["method"] == "PATCH" and latest["path"] == f"/api/agents/{agent['id']}"
    assert latest["target_id"] == agent["id"] and latest["status_code"] == 200


def test_reads_failures_and_routine_inbox_work_are_not_recorded(authenticated_client: TestClient):
    customer = authenticated_client.post("/api/clients", json={"name": "Cafe"}).json()
    before = _actions(authenticated_client)
    authenticated_client.get("/api/clients")
    # A rejected write changed nothing, so it is not a change to log.
    assert authenticated_client.post("/api/agents", json={"client_id": customer["id"]}).status_code == 422
    agent = authenticated_client.post("/api/agents", json={"client_id": customer["id"], "name": "Luna"}).json()
    conversation = authenticated_client.post("/api/conversations", json={"agent_id": agent["id"]}).json()
    authenticated_client.post(f"/api/conversations/{conversation['id']}/read")
    assert _actions(authenticated_client) == ["conversations.create", "agents.create", *before]


def test_sign_ins_and_wrong_passwords_are_recorded(client: TestClient):
    login_legacy_owner(client)
    stranger = TestClient(app)
    assert stranger.post("/api/auth/login", json={"email": "legacy-owner@example.com", "password": "wrong-password"}).status_code == 401
    # An unknown email has no agency to log against.
    assert stranger.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}).status_code == 401
    assert _actions(client)[:2] == ["auth.sign_in_failed", "auth.sign_in"]


def test_only_owners_and_admins_read_it(authenticated_client: TestClient):
    from tests.test_team_security import _invite, _join

    operator = _join(_invite(authenticated_client, "op@example.com", "operator")["link"])
    admin = _join(_invite(authenticated_client, "boss@example.com", "admin")["link"], "Bea")
    assert operator.get("/api/audit").status_code == 403
    assert admin.get("/api/audit").status_code == 200
    assert "team.invitations.create" in _actions(authenticated_client)


def test_each_agency_sees_only_its_own_events(authenticated_client: TestClient):
    authenticated_client.post("/api/clients", json={"name": "Cafe"})
    other = TestClient(app)
    login_legacy_owner(other)
    assert "clients.create" not in _actions(other)
    assert _actions(other) == ["auth.sign_in"]


def test_filters_and_paging(authenticated_client: TestClient):
    for name in ("A", "B", "C"):
        authenticated_client.post("/api/clients", json={"name": name})
    page = authenticated_client.get("/api/audit", params={"limit": 2}).json()
    assert len(page["events"]) == 2 and page["has_more"] is True
    assert _actions(authenticated_client, action="clients") == ["clients.create"] * 3
    assert _actions(authenticated_client, actor="nobody@example.com") == []


def test_action_names_drop_ids():
    agent_id = "3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90"
    assert audit.describe("POST", f"/api/agents/{agent_id}/documents") == ("agents.documents.create", agent_id)
    assert audit.describe("DELETE", "/api/providers/openai") == ("providers.openai.delete", None)
    assert audit.is_audited("PATCH", "/api/agents/x")
    assert not audit.is_audited("GET", "/api/agents/x")
    assert not audit.is_audited("POST", "/api/conversations/x/messages")
    assert not audit.is_audited("POST", "/api/providers/openai/test")
    assert not audit.is_audited("POST", "/api/billing/webhook")
