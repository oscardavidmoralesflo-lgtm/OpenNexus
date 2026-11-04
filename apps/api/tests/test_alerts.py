"""E-mail alerts when a WhatsApp QR line is in trouble."""

import uuid

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.services import alerts, whatsapp_guard as guard
from tests.test_whatsapp_guard import _conversation, _send, line  # noqa: F401 - the fixture


class _Inline:
    """Runs the alert where it is queued, so the test can read what was sent."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def mailbox(monkeypatch):
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(alerts, "email_enabled", lambda: True)
    monkeypatch.setattr(alerts, "_send", lambda to, subject, text: sent.append((to, subject, text)))
    monkeypatch.setattr(alerts.threading, "Thread", _Inline)
    monkeypatch.setattr(alerts, "_last_sent", {})
    monkeypatch.setattr(alerts, "_expected_unlinks", {})
    return sent


def test_a_ban_and_an_error_reach_the_owner_once_an_hour(line, mailbox):  # noqa: F811
    client, _, _, channel, headers, _ = line
    status = f"/api/internal/whatsapp/channels/{channel['id']}/status"
    owner = client.get("/api/auth/me").json()["email"]
    for _ in range(2):
        client.put(status, headers=headers, json={"status": "error", "error": "WhatsApp temporarily banned this number: 101"})
    assert len(mailbox) == 1
    to, subject, text = mailbox[0]
    assert to == owner and "baneó temporalmente" in subject and "Barber shop" in text and "101" in text

    client.put(status, headers=headers, json={"status": "error", "error": "Could not process an incoming message"})
    assert len(mailbox) == 2 and "problemas" in mailbox[1][1]


def test_only_an_unexpected_unlink_is_news(line, mailbox):  # noqa: F811
    client, _, _, channel, headers, _ = line
    auth = f"/api/internal/whatsapp/channels/{channel['id']}/auth"
    client.put(auth, headers=headers, json={"auth_state": {"provider": "whatsmeow", "device_jid": "1@s.whatsapp.net"}})

    # The team disconnects the line: the bridge logs out and clears the session.
    alerts.expect_unlink(channel["id"])  # what bridge_command does on /disconnect
    client.delete(auth, headers=headers)
    assert mailbox == []

    client.put(auth, headers=headers, json={"auth_state": {"provider": "whatsmeow", "device_jid": "1@s.whatsapp.net"}})
    client.put(f"/api/internal/whatsapp/channels/{channel['id']}/status", headers=headers,
               json={"status": "connected", "phone_number": "573009990000"})
    client.delete(auth, headers=headers)  # the phone unlinked it
    assert len(mailbox) == 1 and "desvinculado" in mailbox[0][1]


def test_a_shield_pause_sends_one_alert_to_the_configured_address(line, mailbox, monkeypatch):  # noqa: F811
    _, _, _, _, _, bridge = line
    monkeypatch.setattr(get_settings(), "alert_email", "ops@agency.com, me@agency.com")
    chat = _conversation(line, contact_wrote=True)
    bridge.side_effect = HTTPException(status_code=502, detail="error 463")
    for _ in range(guard.FAILED_PER_HOUR + 2):
        with pytest.raises(HTTPException):
            _send(chat, "Hi", "reply")
    assert [to for to, _, _ in mailbox] == ["ops@agency.com", "me@agency.com"]
    assert "pausa" in mailbox[0][1] and "rechazó" not in mailbox[0][2]


def test_no_mail_server_means_no_alert(line, monkeypatch):  # noqa: F811
    assert alerts.line_alert(uuid.uuid4(), "banned") is False
