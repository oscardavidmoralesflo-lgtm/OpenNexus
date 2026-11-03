"""Operator commands for dashboard sign-in, run inside the API container.

Use them to get back into an installation whose password was lost, since the
dashboard has no email-based reset.

    python -m app.account_admin users
    python -m app.account_admin reset-password owner@example.com
    python -m app.account_admin reset-password owner@example.com --disable-2fa

``reset-password`` sets a new random password, prints it once, and records
the change in the activity log. ``--disable-2fa`` also turns off two-step
verification for that person, for when the authenticator app is lost too.
"""

import secrets
import sys

from sqlalchemy import func, select

from .database import new_session
from .models import User
from .security import hash_password
from .services import audit


def new_password() -> str:
    # About 96 bits, URL-safe so it survives copy and paste anywhere.
    return secrets.token_urlsafe(12)


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("users", "reset-password"):
        print(__doc__)
        return 2
    with new_session() as db:
        if argv[0] == "users":
            users = db.scalars(select(User).order_by(User.created_at)).all()
            if not users:
                print("No users yet. Open the app to run first-run setup.")
            for user in users:
                two_factor = "2FA on" if user.totp_enabled else "2FA off"
                print(f"{user.email}\t{user.role}\t{two_factor}")
            return 0

        emails = [arg for arg in argv[1:] if not arg.startswith("--")]
        if len(emails) != 1:
            print("Usage: reset-password <email> [--disable-2fa]")
            return 2
        user = db.scalar(select(User).where(func.lower(User.email) == emails[0].strip().lower()))
        if user is None:
            print(f"No user with email {emails[0]}. Run 'users' to list them.")
            return 1
        password = new_password()
        user.password_hash = hash_password(password)
        action = "auth.password_reset_by_operator"
        if "--disable-2fa" in argv:
            user.totp_enabled = False
            user.totp_secret = None
            user.recovery_codes = []
            action = "auth.password_and_2fa_reset_by_operator"
        audit.record(db, agency_id=user.agency_id, action=action, user=user, method="CLI", path="app.account_admin")
        db.commit()
        print(f"New password for {user.email}: {password}")
        print("Sign in with it and change it under Settings > Security.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
