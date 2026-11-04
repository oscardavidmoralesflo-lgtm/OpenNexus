"""Operational alerts by e-mail: problems the agency should hear about before
its clients do, such as a WhatsApp line that disconnected, was banned or was
paused by the ban shield.

Alerts go to ``ALERT_EMAIL`` (comma-separated), or to the agency's owners
when it is empty, and need the SMTP settings. The same alert is sent at most
once an hour per line, so a flapping connection does not flood the inbox.
Sending runs in a background thread: callers never wait on the mail server.
"""

import logging
import threading
import time
import uuid

from sqlalchemy import select

from ..config import get_settings
from ..database import new_session
from ..models import Client, User, WhatsAppChannel
from .email import _send, email_enabled

logger = logging.getLogger(__name__)

REPEAT_SECONDS = 3600

_MESSAGES = {
    "es": {
        "error": ("⚠️ WhatsApp con problemas: {line}",
                  "La línea {line} del cliente {client} tiene un problema y puede que no esté respondiendo:\n\n{detail}\n\n"
                  "Revísala en Clientes → {client} → Canales → WhatsApp."),
        "logged_out": ("⚠️ WhatsApp desvinculado: {line}",
                       "La línea {line} del cliente {client} se desvinculó del teléfono y dejó de responder.\n\n"
                       "Si no lo hiciste tú, puede ser una señal de baneo. Vuelve a escanear el QR desde Clientes → {client} → Canales → WhatsApp."),
        "banned": ("🚫 WhatsApp baneó temporalmente: {line}",
                   "WhatsApp baneó temporalmente la línea {line} del cliente {client}:\n\n{detail}\n\n"
                   "El escudo anti-baneo pausó los mensajes que inicia durante 24 horas. No la fuerces: espera a que termine el baneo."),
        "paused": ("⏸️ Escudo anti-baneo en pausa: {line}",
                   "El escudo anti-baneo pausó los mensajes que inicia la línea {line} del cliente {client}:\n\n{detail}\n\n"
                   "Las respuestas a quien escribe siguen saliendo. Puedes ver el estado en Clientes → {client} → Canales → WhatsApp."),
    },
    "en": {
        "error": ("⚠️ WhatsApp line in trouble: {line}",
                  "Line {line} of client {client} has a problem and may not be answering:\n\n{detail}\n\n"
                  "Check it in Clients → {client} → Channels → WhatsApp."),
        "logged_out": ("⚠️ WhatsApp unlinked: {line}",
                       "Line {line} of client {client} was unlinked from the phone and stopped answering.\n\n"
                       "If you did not do it, it can be a sign of a ban. Scan the QR again from Clients → {client} → Channels → WhatsApp."),
        "banned": ("🚫 WhatsApp temporarily banned: {line}",
                   "WhatsApp temporarily banned line {line} of client {client}:\n\n{detail}\n\n"
                   "The ban shield paused the messages it starts for 24 hours. Do not force it: wait for the ban to end."),
        "paused": ("⏸️ Ban shield paused: {line}",
                   "The ban shield paused the messages line {line} of client {client} starts:\n\n{detail}\n\n"
                   "Replies to people who write still go out. See its state in Clients → {client} → Channels → WhatsApp."),
    },
}

_last_sent: dict[tuple[uuid.UUID, str], float] = {}
_lock = threading.Lock()


def _due(channel_id: uuid.UUID, kind: str) -> bool:
    now = time.monotonic()
    with _lock:
        last = _last_sent.get((channel_id, kind))
        if last is not None and now - last < REPEAT_SECONDS:
            return False
        _last_sent[(channel_id, kind)] = now
        return True


def _recipients(db, agency_id: uuid.UUID) -> list[str]:
    configured = [item.strip() for item in get_settings().alert_email.split(",") if item.strip()]
    if configured:
        return configured
    return list(db.scalars(select(User.email).where(
        User.agency_id == agency_id, User.role == "owner",
    )).all())


def _deliver(channel_id: uuid.UUID, kind: str, detail: str) -> None:
    db = new_session()
    try:
        channel = db.get(WhatsAppChannel, channel_id)
        if channel is None:
            return
        client = db.get(Client, channel.client_id)
        line = channel.label or (f"+{channel.phone_number}" if channel.phone_number else "WhatsApp")
        lang = "en" if get_settings().alert_language == "en" else "es"
        subject, body = _MESSAGES[lang][kind]
        values = {"line": line, "client": client.name if client else "", "detail": detail or "—"}
        for to in _recipients(db, channel.agency_id):
            try:
                _send(to, subject.format(**values), body.format(**values))
            except Exception as exc:  # noqa: BLE001 - an alert must never break the caller
                logger.warning("Alert e-mail was not sent (%s)", type(exc).__name__)
    finally:
        db.close()


# Lines the team unlinked on purpose: their logout is not news.
_expected_unlinks: dict[str, float] = {}


def expect_unlink(channel_id) -> None:
    with _lock:
        _expected_unlinks[str(channel_id)] = time.monotonic()


def _unlink_expected(channel_id) -> bool:
    with _lock:
        since = _expected_unlinks.pop(str(channel_id), None)
    return since is not None and time.monotonic() - since < 300


def line_alert(channel_id: uuid.UUID, kind: str, detail: str = "") -> bool:
    """Tell the agency about a problem with a QR line. Returns whether an
    alert was queued (it is not when e-mail is off or it went out recently)."""
    if kind not in _MESSAGES["es"] or not email_enabled():
        return False
    if kind == "logged_out" and _unlink_expected(channel_id):
        return False
    if not _due(channel_id, kind):
        return False
    threading.Thread(target=_deliver, args=(channel_id, kind, detail), daemon=True).start()
    return True
