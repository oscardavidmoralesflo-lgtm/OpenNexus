"""The agency's own domain for the whole workspace, and the gateway's TLS gate."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services import dns as dns_service


@pytest.fixture
def base_domain(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "workspace_base_domain", "app.example.com")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")
    return settings


def test_branded_subdomain_needs_no_setup(authenticated_client: TestClient, base_domain):
    state = authenticated_client.get("/api/agency/domain").json()
    assert state["branded_url"] == "https://agencia-prisma.app.example.com"
    assert state["primary_url"] == state["branded_url"]
    assert state["domain"] is None and state["verified"] is False
    assert authenticated_client.get("/api/public/tls-ask", params={"domain": "agencia-prisma.app.example.com"}).status_code == 200
    assert authenticated_client.get("/api/public/tls-ask", params={"domain": "someone-else.app.example.com"}).status_code == 404


def test_own_domain_is_routed_only_once_verified(authenticated_client: TestClient, base_domain, monkeypatch):
    created = authenticated_client.put("/api/agency/domain", json={"domain": "Panel.Agencia.com"}).json()
    assert created["domain"] == "panel.agencia.com"
    assert created["txt_host"] == "_opennexus-challenge.panel.agencia.com"
    assert created["txt_value"] and created["verified"] is False
    assert created["cname_target"] == "app.example.com"
    assert authenticated_client.get("/api/public/tls-ask", params={"domain": "panel.agencia.com"}).status_code == 404

    monkeypatch.setattr(dns_service, "txt_contains", lambda domain, token: False)
    assert authenticated_client.post("/api/agency/domain/verify").status_code == 400

    monkeypatch.setattr(dns_service, "txt_contains", lambda domain, token: token == created["txt_value"])
    monkeypatch.setattr(dns_service, "points_to", lambda domain, target: True)
    verified = authenticated_client.post("/api/agency/domain/verify").json()
    assert verified["verified"] and verified["ssl_ready"] and verified["dns_ok"]
    assert verified["primary_url"] == "https://panel.agencia.com"
    assert authenticated_client.get("/api/public/tls-ask", params={"domain": "panel.agencia.com"}).json() == {"kind": "workspace"}

    # Changing the domain starts the verification over with a new token.
    changed = authenticated_client.put("/api/agency/domain", json={"domain": "chat.agencia.com"}).json()
    assert changed["verified"] is False and changed["txt_value"] != created["txt_value"]

    cleared = authenticated_client.delete("/api/agency/domain").json()
    assert cleared["domain"] is None
    assert authenticated_client.get("/api/public/tls-ask", params={"domain": "chat.agencia.com"}).status_code == 404


def test_platform_and_portal_domains_cannot_be_claimed(authenticated_client: TestClient, base_domain):
    assert authenticated_client.put("/api/agency/domain", json={"domain": "app.example.com"}).status_code == 400
    client_id = authenticated_client.post("/api/clients", json={"name": "Cafe Norte"}).json()["id"]
    assert authenticated_client.put(f"/api/clients/{client_id}/domain", json={"domain": "chat.cafe.com"}).status_code == 200
    assert authenticated_client.put("/api/agency/domain", json={"domain": "chat.cafe.com"}).status_code == 409


def test_domain_requires_a_session(client: TestClient):
    assert client.get("/api/agency/domain").status_code == 401
