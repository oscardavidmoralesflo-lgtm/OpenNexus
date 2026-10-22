"""Who in the agency's team may do what in the dashboard.

* ``owner``: everything, including billing and the other owners and admins.
* ``admin``: everything but paying, and cannot touch owners or other admins.
* ``operator``: reads everything and works the conversations (inbox, takeover,
  replies, playground); changes nothing else.
* ``viewer``: reads; changes nothing.

The policy is applied once, to every request on the dashboard's API, so a new
route is covered without remembering to protect it. Personal account routes
(``/api/account``) and sign-in (``/api/auth``) are outside it.
"""

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User

ROLES = ("owner", "admin", "operator", "viewer")
MANAGERS = ("owner", "admin")

# Areas of the dashboard API the policy applies to (prefixes under /api).
DASHBOARD_PREFIXES = (
    "/api/agency", "/api/agents", "/api/billing", "/api/catalog", "/api/clients", "/api/conversations",
    "/api/dashboard", "/api/industries", "/api/integrations", "/api/mcp-access", "/api/providers", "/api/reports", "/api/sandbox",
    "/api/social", "/api/team", "/api/webchat", "/api/whatsapp/", "/api/whatsapp-cloud",
)
# Never under the policy even though a prefix above matches: Stripe calls it.
EXEMPT = ("/api/billing/webhook",)
# Readable only by owners and admins: secrets and money.
MANAGER_READS = ("/api/integrations", "/api/providers", "/api/mcp-access", "/api/billing")
# The writes an operator may make.
OPERATOR_WRITES = ("/api/conversations",)
# Paying is the owner's.
OWNER_WRITES = ("/api/billing",)
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    """``path`` is a prefix itself or below one (``/api/whatsapp`` never matches ``/api/whatsapp-cloud``)."""
    return any(path == base or path.startswith(base + "/") for base in (prefix.rstrip("/") for prefix in prefixes))


def allowed(role: str, method: str, path: str) -> bool:
    if role not in ROLES:
        return False
    reading = method.upper() in SAFE_METHODS
    if role == "owner":
        return True
    if role == "admin":
        return reading or not _under(path, OWNER_WRITES)
    if _under(path, MANAGER_READS):
        return False
    if reading:
        return True
    return role == "operator" and _under(path, OPERATOR_WRITES)


def needs_two_factor_setup(user: User) -> bool:
    return bool(user.agency and user.agency.require_two_factor and not user.totp_enabled)


def enforce(request: Request, access_token: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> None:
    """App-wide dependency: apply the role policy to dashboard requests.

    It only judges requests that carry a valid dashboard session; anything
    else is left to the route's own authentication (public, portal, bridge).
    """
    path = request.url.path
    if not access_token or not _under(path, DASHBOARD_PREFIXES) or _under(path, EXEMPT):
        return
    from ..deps import user_from_token

    user = user_from_token(db, access_token)
    if user is None:
        return
    if needs_two_factor_setup(user) and not (request.method in SAFE_METHODS and path == "/api/agency"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Set up two-step verification in Settings → Security to continue")
    if not allowed(user.role, request.method, path):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role cannot do this")
