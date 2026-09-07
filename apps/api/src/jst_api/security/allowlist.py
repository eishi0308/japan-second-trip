"""Ingestion domain allowlist and URL validation.

Ingestion is admin-triggered and restricted to approved domains. This prevents
two distinct problems: pulling content the site's terms do not permit, and
letting an attacker choose which page enters the knowledge base.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from jst_api.core.errors import IngestionNotAllowed

BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "javascript"}


def _is_private_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # unresolvable: refuse rather than guess
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def domain_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def assert_ingestable(url: str, allowlist: list[str], *, check_dns: bool = True) -> str:
    """Validate a URL for ingestion. Returns the normalised domain.

    Raises ``IngestionNotAllowed`` for anything that is not an https URL on an
    approved domain resolving to a public address (SSRF defence).
    """
    parsed = urlparse(url)
    if parsed.scheme in BLOCKED_SCHEMES or parsed.scheme not in {"http", "https"}:
        raise IngestionNotAllowed(
            f"scheme '{parsed.scheme}' is not permitted", details={"url": url}
        )
    if parsed.scheme != "https":
        raise IngestionNotAllowed("only https sources may be ingested", details={"url": url})

    host = (parsed.hostname or "").lower()
    if not host:
        raise IngestionNotAllowed("URL has no host", details={"url": url})

    normalised = host.removeprefix("www.")
    permitted = any(normalised == d or normalised.endswith(f".{d}") for d in allowlist)
    if not permitted:
        raise IngestionNotAllowed(
            f"domain '{normalised}' is not on the ingestion allowlist",
            details={"domain": normalised, "allowlist": allowlist},
        )
    if check_dns and _is_private_host(host):
        raise IngestionNotAllowed(
            "host resolves to a private address", details={"domain": normalised}
        )
    return normalised
