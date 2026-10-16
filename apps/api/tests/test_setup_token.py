"""A fresh deploy is claimed only by whoever holds SETUP_TOKEN."""

from fastapi.testclient import TestClient

from app.config import get_settings

OWNER = {"agency_name": "Mi Agencia", "name": "Oscar", "email": "owner@example.com", "password": "contrasena-segura"}


def test_setup_requires_the_token_when_set(client: TestClient, monkeypatch):
    monkeypatch.setattr(get_settings(), "setup_token", "s3cret-setup")
    assert client.get("/api/auth/status").json()["setup_token_required"] is True
    assert client.post("/api/auth/register", json=OWNER).status_code == 403
    assert client.post("/api/auth/register", json={**OWNER, "setup_token": "wrong"}).status_code == 403
    assert client.post("/api/auth/register", json={**OWNER, "setup_token": "s3cret-setup"}).status_code == 201
    status = client.get("/api/auth/status").json()
    assert status["needs_setup"] is False and status["setup_token_required"] is False


def test_setup_stays_open_without_a_token(client: TestClient):
    assert client.get("/api/auth/status").json()["setup_token_required"] is False
    assert client.post("/api/auth/register", json=OWNER).status_code == 201
