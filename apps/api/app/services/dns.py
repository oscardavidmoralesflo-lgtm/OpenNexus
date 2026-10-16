"""DNS helpers for custom-domain verification.

Isolated behind a thin function so it can be monkeypatched in tests without
hitting a real resolver.
"""

import dns.resolver

CHALLENGE_PREFIX = "_opennexus-challenge"


def challenge_host(domain: str) -> str:
    return f"{CHALLENGE_PREFIX}.{domain}"


def resolve_txt(name: str) -> list[str]:
    """Return the TXT record strings for ``name`` (empty list on any failure)."""
    try:
        answers = dns.resolver.resolve(name, "TXT")
    except Exception:
        return []
    values: list[str] = []
    for record in answers:
        # Each TXT record can be split into multiple quoted strings.
        values.append(b"".join(getattr(record, "strings", [])).decode("utf-8", "ignore"))
    return values


def txt_contains(domain: str, token: str) -> bool:
    return token in resolve_txt(challenge_host(domain))


def resolve_addresses(name: str) -> set[str]:
    """The A and AAAA addresses ``name`` resolves to, following CNAMEs (empty on failure)."""
    found: set[str] = set()
    for kind in ("A", "AAAA"):
        try:
            answers = dns.resolver.resolve(name, kind)
        except Exception:
            continue
        found.update(record.to_text() for record in answers)
    return found


def points_to(domain: str, target: str) -> bool:
    """Whether ``domain`` reaches the same server as ``target``.

    Compared by address rather than by CNAME, so an apex record, or a proxy in
    front that keeps the same addresses, counts as pointing correctly.
    """
    if not domain or not target:
        return False
    mine = resolve_addresses(domain)
    return bool(mine) and bool(mine & resolve_addresses(target))
