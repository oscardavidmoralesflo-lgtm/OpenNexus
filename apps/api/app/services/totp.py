"""Two-step verification with time-based one-time codes (RFC 6238).

Any authenticator app works (Google Authenticator, 1Password, Authy…): a
base32 secret, SHA-1, 6 digits, 30-second steps. One step of clock drift is
accepted either way, and a step is never accepted twice.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30
DRIFT_STEPS = 1
RECOVERY_CODES = 10


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // PERIOD)


def code_at(secret: str, at: float | None = None) -> str:
    return _code(secret, current_step(at))


def verify(secret: str, code: str, last_step: int = 0, at: float | None = None) -> int | None:
    """The step ``code`` belongs to, if it is valid and newer than ``last_step``."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    now = current_step(at)
    for step in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        if step > last_step and hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"


def qr_svg_data_uri(uri: str) -> str:
    import segno

    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)


def new_recovery_codes() -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)) for _ in range(RECOVERY_CODES)]


def hash_recovery(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()
