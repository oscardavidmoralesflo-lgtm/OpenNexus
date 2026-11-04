"""The agency's audit log: who changed what in the dashboard, and when.

Every successful write (POST, PUT, PATCH, DELETE) a signed-in person makes to
the dashboard API is recorded by ``AuditTrailMiddleware``, so a new route is
covered without remembering to log it. Sign-ins are recorded by the auth
routes themselves, since the request carries no session yet.

Writes that are the daily work of the inbox rather than a change to the
agency (sending a reply, marking a conversation read, testing a key) are left
out, so the log stays a record of changes people can scan.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..models import AuditEvent, User

logger = logging.getLogger("opennexus.audit")

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
VERBS = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}

# Areas of the API whose writes are recorded (prefixes under /api).
AUDITED_PREFIXES = (
    "/api/account", "/api/agency", "/api/agents", "/api/billing", "/api/clients", "/api/conversations",
    "/api/integrations", "/api/mcp-access", "/api/phone", "/api/providers", "/api/sandbox", "/api/social",
    "/api/team", "/api/webchat", "/api/whatsapp", "/api/whatsapp-cloud",
)
# Never recorded even though a prefix above matches.
NOT_AUDITED_PREFIXES = ("/api/billing/webhook", "/api/phone/public")
# Routine work, not a change to the agency: replies, reactions, reads, and
# checks that only test a key or a connection.
NOT_AUDITED_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"^/api/conversations/[^/]+/(read|messages|media|reply|reply-media)$",
    r"^/api/conversations/[^/]+/messages/[^/]+/reaction$",
    r"/(test|validate|test-mcp|voice-preview)$",
    r"^/api/whatsapp/channels/[^/]+/(inbound|status|session|auth)(/|$)",
))

UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def is_audited(method: str, path: str) -> bool:
    if method.upper() not in WRITE_METHODS:
        return False
    if not _under(path, AUDITED_PREFIXES) or _under(path, NOT_AUDITED_PREFIXES):
        return False
    return not any(pattern.search(path) for pattern in NOT_AUDITED_PATTERNS)


def describe(method: str, path: str) -> tuple[str, str | None]:
    """The action name and the target id for a request.

    ``PATCH /api/agents/<id>`` is ``agents.update`` on ``<id>``;
    ``POST /api/agents/<id>/documents`` is ``agents.documents.create``. Ids are
    dropped from the name, and the first one becomes the target.
    """
    parts = [part for part in path.removeprefix("/api/").split("/") if part]
    target = next((part for part in parts if UUID_PATTERN.match(part)), None)
    words = [part.replace("-", "_") for part in parts if not UUID_PATTERN.match(part)]
    verb = VERBS.get(method.upper(), method.lower())
    return ".".join([*words[:3], verb])[:120], target


def record(
    db: Session,
    *,
    agency_id: uuid.UUID,
    action: str,
    user: User | None = None,
    actor_email: str = "",
    method: str = "",
    path: str = "",
    status_code: int = 0,
    target_id: str | None = None,
    ip: str = "",
    user_agent: str = "",
) -> AuditEvent:
    """Add an event to ``db``. The caller commits it with its own work."""
    event = AuditEvent(
        agency_id=agency_id,
        user_id=user.id if user else None,
        actor_email=(user.email if user else actor_email)[:320],
        action=action[:120],
        method=method[:10],
        path=path[:500],
        status_code=status_code,
        target_id=target_id,
        ip=ip[:64],
        user_agent=user_agent[:300],
    )
    db.add(event)
    return event


def _cookie(scope: Scope, name: str) -> str | None:
    for key, value in scope.get("headers", []):
        if key == b"cookie":
            for item in value.decode("latin-1").split(";"):
                cookie_name, _, cookie_value = item.strip().partition("=")
                if cookie_name == name:
                    return cookie_value
    return None


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return ""


def _client_ip(scope: Scope) -> str:
    forwarded = _header(scope, b"x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else ""


class AuditTrailMiddleware:
    """Record each successful dashboard write once its response has started.

    The session comes from the app's ``get_db`` provider, honouring a
    substitution (the test suite swaps it), so the event lands in the same
    database as the change it describes.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_audited(scope["method"], scope["path"]):
            await self.app(scope, receive, send)
            return
        token = _cookie(scope, "access_token")
        if not token:
            await self.app(scope, receive, send)
            return

        status_holder: dict[str, int] = {}

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        await self.app(scope, receive, capture)
        status_code = status_holder.get("status", 0)
        if not 200 <= status_code < 400:
            return
        try:
            await run_in_threadpool(self._write, scope, token, status_code)
        except Exception:  # noqa: BLE001 - the change already happened; never fail the request over its log
            logger.exception("Could not record an audit event for %s %s", scope["method"], scope["path"])

    def _write(self, scope: Scope, token: str, status_code: int) -> None:
        from ..database import get_db
        from ..deps import user_from_token

        app = scope.get("app")
        provider = app.dependency_overrides.get(get_db, get_db) if app is not None else get_db
        sessions = provider()
        db = next(sessions)
        try:
            user = user_from_token(db, token)
            if user is None:
                return
            method, path = scope["method"], scope["path"]
            action, target = describe(method, path)
            record(
                db, agency_id=user.agency_id, user=user, action=action, method=method, path=path,
                status_code=status_code, target_id=target, ip=_client_ip(scope),
                user_agent=_header(scope, b"user-agent"),
            )
            db.commit()
        finally:
            sessions.close()
