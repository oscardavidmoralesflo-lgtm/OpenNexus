"""Password reset by e-mail: a one-time link that expires."""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config import get_settings
from app.routers import auth as auth_router


def _mail(monkeypatch) -> list[tuple[str, str, str]]:
    sent: list[tuple[str, str, str]] = []

    async def fake_send(to, subject, text):
        sent.append((to, subject, text))
        return True

    monkeypatch.setattr(auth_router, "email_enabled", lambda: True)
    monkeypatch.setattr(auth_router, "send_email", fake_send)
    return sent


def _token(text: str) -> str:
    link = next(line for line in text.splitlines() if "login?reset=" in line)
    return parse_qs(urlparse(link.strip()).query)["reset"][0]


def test_reset_is_hidden_without_smtp(client: TestClient, authenticated_client: TestClient):
    assert get_settings().smtp_host == ""
    assert TestClient(authenticated_client.app).get("/api/auth/status").json()["password_reset"] is False
    assert client.post("/api/auth/password/forgot", json={"email": "x@y.com"}).status_code == 409


def test_reset_link_works_once(authenticated_client: TestClient, monkeypatch):
    sent = _mail(monkeypatch)
    me = authenticated_client.get("/api/auth/me").json()
    anonymous = TestClient(authenticated_client.app)
    assert anonymous.get("/api/auth/status").json()["password_reset"] is True

    # An unknown address gets the same answer and no mail.
    assert anonymous.post("/api/auth/password/forgot", json={"email": "nobody@example.com"}).status_code == 204
    assert sent == []

    assert anonymous.post("/api/auth/password/forgot", json={"email": me["email"].upper(), "lang": "en"}).status_code == 204
    assert len(sent) == 1 and sent[0][0] == me["email"] and sent[0][1] == "Reset your Agentaria password"
    token = _token(sent[0][2])

    assert anonymous.post("/api/auth/password/reset", json={"token": "nonsense-token", "new_password": "newpass123"}).status_code == 400
    assert anonymous.post("/api/auth/password/reset", json={"token": token, "new_password": "newpass123"}).status_code == 204
    # Used: the password changed, so the same link no longer works.
    assert anonymous.post("/api/auth/password/reset", json={"token": token, "new_password": "other12345"}).status_code == 400
    signed = anonymous.post("/api/auth/login", json={"email": me["email"], "password": "newpass123"})
    assert signed.status_code == 200
