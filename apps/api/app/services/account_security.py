"""Second-factor checks shared by sign-in and by changes to one's own account."""

from sqlalchemy.orm import Session

from ..models import User
from ..security import decrypt_secret
from . import totp


def check_second_factor(db: Session, user: User, code: str) -> bool:
    """A valid authenticator code (not replayed) or an unused recovery code.

    A recovery code is spent when used. Commits on success."""
    if not user.totp_enabled or not user.totp_secret:
        return False
    step = totp.verify(decrypt_secret(user.totp_secret), code, user.totp_last_step)
    if step is not None:
        user.totp_last_step = step
        db.commit()
        return True
    hashed = totp.hash_recovery(code)
    remaining = list(user.recovery_codes or [])
    if hashed in remaining:
        remaining.remove(hashed)
        user.recovery_codes = remaining
        db.commit()
        return True
    return False
