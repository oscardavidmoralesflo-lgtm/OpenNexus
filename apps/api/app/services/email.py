"""Outgoing e-mail over SMTP.

Configured with the SMTP_* settings. Sending runs in a worker thread, so a
slow mail server never blocks the event loop.
"""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from ..config import get_settings

logger = logging.getLogger(__name__)


def email_enabled() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and (settings.smtp_from or settings.smtp_username))


def _send(to: str, subject: str, text: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_username
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
    with server:
        if settings.smtp_security == "starttls":
            server.starttls(context=context)
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


async def send_email(to: str, subject: str, text: str) -> bool:
    """Send a plain-text e-mail. Returns False (and logs) when it could not."""
    if not email_enabled():
        return False
    try:
        await asyncio.to_thread(_send, to, subject, text)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("E-mail to a user was not sent (%s)", type(exc).__name__)
        return False
    return True
