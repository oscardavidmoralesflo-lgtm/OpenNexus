from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Agency, Client
from ..services import workspace_domain


# Public, unauthenticated: consumed by the gateway's on-demand TLS "ask" hook
# and by the frontend middleware that maps a custom host to its portal.
public_router = APIRouter(prefix="/public", tags=["Public"])


@public_router.get("/portal-domain")
def resolve_portal_domain(domain: str, db: Session = Depends(get_db)):
    host = domain.strip().lower()
    client = db.scalar(
        select(Client).where(
            Client.portal_domain == host,
            Client.portal_domain_verified.is_(True),
            Client.portal_enabled.is_(True),
        )
    )
    if not client:
        # Non-2xx tells Caddy not to issue a certificate for this host.
        raise HTTPException(status_code=404, detail="Unknown domain")
    return {"portal_slug": client.portal_slug}


@public_router.get("/tls-ask")
def tls_ask(domain: str, db: Session = Depends(get_db)):
    """The gateway's on-demand TLS gate: 2xx only for a host this install serves.

    A verified client portal domain, a verified workspace domain, or an
    agency's branded subdomain. Anything else gets no certificate.
    """
    host = domain.strip().lower()
    portal = db.scalar(
        select(Client.id).where(
            Client.portal_domain == host,
            Client.portal_domain_verified.is_(True),
            Client.portal_enabled.is_(True),
        )
    )
    if portal:
        return {"kind": "portal"}
    if any(workspace_domain.serves(agency, host) for agency in db.scalars(select(Agency))):
        return {"kind": "workspace"}
    raise HTTPException(status_code=404, detail="Unknown domain")
