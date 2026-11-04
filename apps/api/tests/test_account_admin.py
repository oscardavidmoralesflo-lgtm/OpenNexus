"""Getting back in: the operator reset command and changing your own password."""

from fastapi.testclient import TestClient

from app import account_admin
from app.main import app
from conftest import TestingSession


def _sign_in(email: str, password: str) -> int:
    return TestClient(app).post("/api/auth/login", json={"email": email, "password": password}).status_code


def test_reset_password_sets_a_new_one_and_logs_it(authenticated_client: TestClient, monkeypatch, capsys):
    monkeypatch.setattr(account_admin, "new_session", TestingSession)
    assert account_admin.main(["reset-password", "ANA@prisma.com"]) == 0
    password = capsys.readouterr().out.split("ana@prisma.com: ")[1].split()[0]

    assert _sign_in("ana@prisma.com", "contrasena-segura") == 401
    assert _sign_in("ana@prisma.com", password) == 200
    actions = [e["action"] for e in authenticated_client.get("/api/audit").json()["events"]]
    assert "auth.password_reset_by_operator" in actions


def test_reset_can_turn_off_two_step_verification(authenticated_client: TestClient, monkeypatch, capsys):
    monkeypatch.setattr(account_admin, "new_session", TestingSession)
    from app.models import User

    with TestingSession() as db:
        user = db.query(User).filter_by(email="ana@prisma.com").one()
        user.totp_enabled, user.totp_secret, user.recovery_codes = True, "x", ["y"]
        db.commit()
    assert account_admin.main(["reset-password", "ana@prisma.com", "--disable-2fa"]) == 0
    with TestingSession() as db:
        user = db.query(User).filter_by(email="ana@prisma.com").one()
        assert not user.totp_enabled and user.totp_secret is None and user.recovery_codes == []


def test_users_and_unknown_emails(authenticated_client: TestClient, monkeypatch, capsys):
    monkeypatch.setattr(account_admin, "new_session", TestingSession)
    assert account_admin.main(["users"]) == 0
    assert "ana@prisma.com\towner\t2FA off" in capsys.readouterr().out
    assert account_admin.main(["reset-password", "nobody@example.com"]) == 1
    assert account_admin.main([]) == 2


def test_change_own_password(authenticated_client: TestClient):
    wrong = authenticated_client.post("/api/account/password", json={"current_password": "nope", "new_password": "otra-clave-larga"})
    assert wrong.status_code == 400
    same = authenticated_client.post("/api/account/password", json={"current_password": "contrasena-segura", "new_password": "contrasena-segura"})
    assert same.status_code == 400
    short = authenticated_client.post("/api/account/password", json={"current_password": "contrasena-segura", "new_password": "corta"})
    assert short.status_code == 422
    ok = authenticated_client.post("/api/account/password", json={"current_password": "contrasena-segura", "new_password": "otra-clave-larga"})
    assert ok.status_code == 204
    assert _sign_in("ana@prisma.com", "contrasena-segura") == 401
    assert _sign_in("ana@prisma.com", "otra-clave-larga") == 200
