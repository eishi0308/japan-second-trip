"""Authentication and authorisation.

Two identities exist:

* **traveller** — anonymous by default. A trip is addressed by an unguessable
  id and an opaque access token returned once at creation. There are no
  passwords, because the product does not need an account to be useful and every
  credential stored is a credential that can leak.
* **admin** — a bearer token (``ADMIN_TOKEN``) or a signed JWT. Required for
  every ingestion, verification and inspection endpoint.

Admin credentials are compared in constant time, and the default development
token is refused outright outside local/test environments.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Header, Request
from jose import JWTError, jwt

from jst_api.core.config import Settings, get_settings
from jst_api.core.errors import ForbiddenError, UnauthorizedError
from jst_api.core.ids import new_id
from jst_api.core.logging import get_logger

log = get_logger(__name__)

ALGORITHM = "HS256"
INSECURE_DEFAULT_ADMIN_TOKEN = "dev-admin-token"


@dataclass
class Principal:
    subject: str
    role: str
    trip_ids: list[str]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def issue_trip_token(trip_id: str, settings: Settings | None = None) -> str:
    """Opaque capability token for one trip. Scoped, expiring, no PII."""
    settings = settings or get_settings()
    payload = {
        "sub": new_id("anon"),
        "role": "traveller",
        "trips": [trip_id],
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(days=90)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


async def get_principal(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Optional identity. Anonymous callers are allowed on public endpoints."""
    token = _bearer(authorization)
    if not token:
        return Principal(subject="anonymous", role="anonymous", trip_ids=[])

    if hmac.compare_digest(token, settings.admin_token):
        _assert_admin_token_safe(settings)
        return Principal(subject="admin", role="admin", trip_ids=[])

    claims = decode_token(token, settings)
    return Principal(
        subject=str(claims.get("sub", "anonymous")),
        role=str(claims.get("role", "traveller")),
        trip_ids=list(claims.get("trips", [])),
    )


async def require_admin(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Principal:
    token = _bearer(authorization)
    if not token:
        raise UnauthorizedError("Admin endpoints require a bearer token")

    if hmac.compare_digest(token, settings.admin_token):
        _assert_admin_token_safe(settings)
        return Principal(subject="admin", role="admin", trip_ids=[])

    claims = decode_token(token, settings)
    if claims.get("role") != "admin":
        raise ForbiddenError("Admin role required")
    return Principal(subject=str(claims.get("sub", "admin")), role="admin", trip_ids=[])


def _assert_admin_token_safe(settings: Settings) -> None:
    """The development token must never authenticate a deployed environment."""
    if settings.admin_token == INSECURE_DEFAULT_ADMIN_TOKEN and settings.environment in (
        "staging",
        "production",
    ):
        log.error("security.default_admin_token_in_deployed_env", environment=settings.environment)
        raise ForbiddenError("The default admin token is not accepted in this environment")


def assert_trip_access(principal: Principal, trip_id: str) -> None:
    if principal.is_admin or trip_id in principal.trip_ids:
        return
    # Trip ids are unguessable capabilities; an anonymous caller who holds one
    # may read it. A *named* traveller principal scoped to other trips may not.
    if principal.role == "anonymous":
        return
    raise ForbiddenError("This token does not grant access to that trip")


def client_key(request: Request) -> str:
    """Rate-limit identity. Prefers the authenticated subject, else client IP."""
    token = _bearer(request.headers.get("authorization"))
    if token:
        return f"tok:{hash(token) & 0xFFFFFFFF:x}"
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    return f"ip:{ip}"
