"""The agency's workspace addresses: a branded subdomain and its own domain."""

from urllib.parse import urlparse

from ..config import get_settings
from ..models import Agency
from ..schemas import WorkspaceDomainOut
from . import dns as dns_service


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def primary_host() -> str:
    return _host(get_settings().frontend_url)


def cname_target() -> str | None:
    settings = get_settings()
    return (settings.workspace_cname_target or primary_host() or "").strip().lower() or None


def branded_host(agency: Agency) -> str | None:
    base = get_settings().workspace_base_domain.strip().lower().strip(".")
    return f"{agency.slug}.{base}" if base else None


def _scheme() -> str:
    return urlparse(get_settings().frontend_url).scheme or "https"


def describe(agency: Agency, check_dns: bool = False) -> WorkspaceDomainOut:
    """The domain tab's state. DNS is only looked up when asked, since it is slow."""
    scheme = _scheme()
    branded = branded_host(agency)
    domain = agency.workspace_domain
    verified = bool(domain and agency.workspace_domain_verified)
    target = cname_target()
    dns_ok = bool(domain and check_dns and dns_service.points_to(domain, target or ""))
    if verified:
        primary = f"https://{domain}"
    elif branded:
        primary = f"{scheme}://{branded}"
    else:
        primary = get_settings().frontend_url.rstrip("/")
    return WorkspaceDomainOut(
        branded_url=f"{scheme}://{branded}" if branded else None,
        domain=domain,
        verified=verified,
        txt_host=dns_service.challenge_host(domain) if domain else None,
        txt_value=(agency.workspace_domain_token or None) if domain else None,
        cname_target=target,
        dns_ok=dns_ok,
        ssl_ready=verified,
        primary_url=primary,
    )


def serves(agency: Agency, host: str) -> bool:
    """Whether ``host`` is one of this agency's workspace addresses."""
    host = host.strip().lower()
    if not host:
        return False
    if agency.workspace_domain_verified and agency.workspace_domain == host:
        return True
    return branded_host(agency) == host
