"""Short, sortable, URL-safe identifiers."""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford-ish, no look-alikes


def _encode(n: int, width: int) -> str:
    out = []
    for _ in range(width):
        n, rem = divmod(n, len(_ALPHABET))
        out.append(_ALPHABET[rem])
    return "".join(reversed(out))


def new_id(prefix: str = "") -> str:
    """Time-prefixed random id: lexicographic order matches creation order."""
    ts = _encode(int(time.time() * 1000), 8)
    rand = _encode(secrets.randbits(40), 8)
    body = f"{ts}{rand}"
    return f"{prefix}_{body}" if prefix else body
