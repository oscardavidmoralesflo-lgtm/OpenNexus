"""The agency's team (invitations, roles and their limits) and two-step verification."""

from fastapi.testclient import TestClient

from app.main import app
from app.services import team_roles, totp


def _invite(client: TestClient, email: str, role: str) -> dict:
    response = client.post("/api/team/invitations", json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


def _join(link: str, name: str = "Member") -> TestClient:
    """Accept an invitation in a fresh browser, as the invited person would."""
    token = link.rsplit("/invite/", 1)[1]
    browser = TestClient(app)
    preview = browser.get(f"/api/auth/invitations/{token}")
    assert preview.status_code == 200, preview.text
    accepted = browser.post(f"/api/auth/invitations/{token}/accept", json={"name": name, "password": "otra-contrasena"})
    assert accepted.status_code == 201, accepted.text
    return browser


def test_the_first_user_is_the_owner(authenticated_client: TestClient):
    me = authenticated_client.get("/api/auth/me").json()
    assert me["role"] == "owner" and me["two_factor_enabled"] is False
    team = authenticated_client.get("/api/team").json()
    assert [m["role"] for m in team["members"]] == ["owner"] and team["members"][0]["is_you"]


def test_invitation_link_works_once_and_can_be_revoked(authenticated_client: TestClient):
    invitation = _invite(authenticated_client, "Ops@Example.com", "operator")
    assert invitation["email"] == "ops@example.com" and "/invite/" in invitation["link"]
    assert [i["email"] for i in authenticated_client.get("/api/team").json()["invitations"]] == ["ops@example.com"]
    member = _join(invitation["link"], "Olga")
    assert member.get("/api/auth/me").json()["role"] == "operator"
    token = invitation["link"].rsplit("/", 1)[1]
    assert TestClient(app).get(f"/api/auth/invitations/{token}").status_code == 404
    assert authenticated_client.get("/api/team").json()["invitations"] == []

    revoked = _invite(authenticated_client, "late@example.com", "viewer")
    assert authenticated_client.delete(f"/api/team/invitations/{revoked['id']}").status_code == 204
    assert TestClient(app).get(f"/api/auth/invitations/{revoked['link'].rsplit('/', 1)[1]}").status_code == 404
    assert authenticated_client.post("/api/team/invitations", json={"email": "ana@prisma.com", "role": "viewer"}).status_code == 409


def test_roles_limit_what_members_can_do(authenticated_client: TestClient):
    owner = authenticated_client
    customer = owner.post("/api/clients", json={"name": "Cafe"}).json()
    agent = owner.post("/api/agents", json={"client_id": customer["id"], "name": "Luna"}).json()
    operator = _join(_invite(owner, "op@example.com", "operator")["link"])
    viewer = _join(_invite(owner, "view@example.com", "viewer")["link"])

    for member in (operator, viewer):
        assert member.get("/api/clients").status_code == 200
        assert member.get(f"/api/agents/{agent['id']}").status_code == 200
        assert member.post("/api/clients", json={"name": "Nope"}).status_code == 403
        assert member.patch(f"/api/agents/{agent['id']}", json={"name": "Hacked"}).status_code == 403
        # Secrets and money are for owners and admins.
        assert member.get("/api/providers").status_code == 403
        assert member.get("/api/mcp-access/tokens").status_code == 403
        assert member.post("/api/team/invitations", json={"email": "x@example.com", "role": "viewer"}).status_code == 403
    # The operator works the conversations; the viewer only reads them.
    assert operator.post("/api/conversations", json={"agent_id": agent["id"]}).status_code == 201
    assert viewer.post("/api/conversations", json={"agent_id": agent["id"]}).status_code == 403
    # The portal and public routes are untouched by the dashboard policy.
    assert viewer.get("/api/auth/status").status_code == 200


def test_admins_cannot_touch_owners_and_the_last_owner_stays(authenticated_client: TestClient):
    owner = authenticated_client
    admin = _join(_invite(owner, "admin@example.com", "admin")["link"])
    team = owner.get("/api/team").json()
    owner_id = next(m["id"] for m in team["members"] if m["role"] == "owner")
    admin_id = next(m["id"] for m in team["members"] if m["role"] == "admin")

    assert admin.post("/api/team/invitations", json={"email": "boss@example.com", "role": "owner"}).status_code == 403
    assert admin.post("/api/team/invitations", json={"email": "op2@example.com", "role": "operator"}).status_code == 201
    assert admin.patch(f"/api/team/members/{owner_id}", json={"role": "viewer"}).status_code == 403
    assert admin.delete(f"/api/team/members/{owner_id}").status_code == 403
    assert owner.patch(f"/api/team/members/{owner_id}", json={"role": "admin"}).status_code == 400
    assert admin.post("/api/billing/checkout", json={"plan_id": "launch"}).status_code == 403

    assert owner.patch(f"/api/team/members/{admin_id}", json={"role": "viewer"}).json()["role"] == "viewer"
    assert admin.get("/api/auth/me").json()["role"] == "viewer"
    assert owner.delete(f"/api/team/members/{admin_id}").status_code == 204
    assert admin.get("/api/auth/me").status_code == 401


def _enable_two_factor(client: TestClient) -> tuple[str, list[str]]:
    setup = client.post("/api/account/2fa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/") and setup["qr_svg"].startswith("data:image/svg+xml")
    codes = client.post("/api/account/2fa/enable", json={"code": totp.code_at(setup["secret"])}).json()["recovery_codes"]
    assert len(codes) == 10
    return setup["secret"], codes


def test_two_factor_sign_in(authenticated_client: TestClient):
    secret, codes = _enable_two_factor(authenticated_client)
    assert authenticated_client.get("/api/account/2fa").json() == {"enabled": True, "recovery_codes_left": 10, "required_by_agency": False}

    browser = TestClient(app)
    first = browser.post("/api/auth/login", json={"email": "ana@prisma.com", "password": "contrasena-segura"}).json()
    assert first["two_factor_required"] is True
    assert browser.get("/api/auth/me").status_code == 401, "no session before the second step"
    # The challenge is not a session.
    browser.cookies.set("access_token", first["challenge"])
    assert browser.get("/api/auth/me").status_code == 401
    browser.cookies.clear()

    assert browser.post("/api/auth/login/2fa", json={"challenge": first["challenge"], "code": "000000"}).status_code == 401
    # The code just used to enable it cannot be replayed.
    assert browser.post("/api/auth/login/2fa", json={"challenge": first["challenge"], "code": totp.code_at(secret)}).status_code == 401
    import time
    later = totp.code_at(secret, time.time() + totp.PERIOD)
    assert browser.post("/api/auth/login/2fa", json={"challenge": first["challenge"], "code": later}).status_code == 200
    assert browser.get("/api/auth/me").json()["two_factor_enabled"] is True

    # A recovery code works once.
    other = TestClient(app)
    challenge = other.post("/api/auth/login", json={"email": "ana@prisma.com", "password": "contrasena-segura"}).json()["challenge"]
    assert other.post("/api/auth/login/2fa", json={"challenge": challenge, "code": codes[0].upper()}).status_code == 200
    again = TestClient(app)
    challenge = again.post("/api/auth/login", json={"email": "ana@prisma.com", "password": "contrasena-segura"}).json()["challenge"]
    assert again.post("/api/auth/login/2fa", json={"challenge": challenge, "code": codes[0]}).status_code == 401
    assert authenticated_client.get("/api/account/2fa").json()["recovery_codes_left"] == 9


def test_disabling_needs_password_and_code(authenticated_client: TestClient):
    import time
    secret, codes = _enable_two_factor(authenticated_client)
    assert authenticated_client.post("/api/account/2fa/disable", json={"password": "wrong", "code": codes[1]}).status_code == 400
    code = totp.code_at(secret, time.time() + totp.PERIOD)
    disabled = authenticated_client.post("/api/account/2fa/disable", json={"password": "contrasena-segura", "code": code}).json()
    assert disabled["enabled"] is False


def test_agency_can_require_two_factor(authenticated_client: TestClient):
    owner = authenticated_client
    assert owner.put("/api/team/policy", json={"require_two_factor": True}).status_code == 400, "the owner sets it up first"
    _enable_two_factor(owner)
    assert owner.put("/api/team/policy", json={"require_two_factor": True}).json()["require_two_factor"] is True
    member = _join(_invite(owner, "new@example.com", "operator")["link"])
    # Until they set it up, members only reach their account and the agency's name.
    assert member.get("/api/clients").status_code == 403
    assert member.get("/api/agency").status_code == 200
    assert member.get("/api/account/2fa").json()["required_by_agency"] is True
    _enable_two_factor(member)
    assert member.get("/api/clients").status_code == 200


def test_policy_table():
    assert team_roles.allowed("admin", "POST", "/api/clients")
    assert not team_roles.allowed("admin", "POST", "/api/billing/topup")
    assert team_roles.allowed("operator", "POST", "/api/conversations/x/reply")
    assert not team_roles.allowed("operator", "PATCH", "/api/agents/x")
    assert not team_roles.allowed("viewer", "GET", "/api/providers")
    assert not team_roles.allowed("nobody", "GET", "/api/clients")


def test_totp_matches_rfc_6238_vectors():
    # RFC 6238 appendix B, SHA-1, secret "12345678901234567890", truncated to 6 digits.
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert totp.code_at(secret, 59) == "287082"
    assert totp.code_at(secret, 1111111109) == "081804"
    assert totp.verify(secret, "287082", at=59) == 1
