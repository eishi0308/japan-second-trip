"""Portable column types.

The production database is PostgreSQL + pgvector. Tests and offline demos run
the *same* SQLAlchemy models against SQLite, so vector and JSONB columns need a
dialect-aware implementation. Retrieval semantics differ by dialect (native
pgvector ANN vs. in-Python cosine) and that difference is confined to
``db/repositories/evidence_repo.py`` — see docs/adr/0004-postgres-pgvector.md.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import JSON, Operators, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import Float, TypeDecorator


class Vector(TypeDecorator):
    """``vector(n)`` on PostgreSQL, JSON-encoded float list on SQLite."""

    impl = Text
    cache_ok = True

    class Comparator(TypeDecorator.Comparator):
        """Expose pgvector's distance operators through the decorator.

        ``TypeDecorator`` does not proxy the wrapped type's comparator, so the
        operators have to be re-declared here. They are PostgreSQL-only; the
        SQLite path scores in NumPy instead and never reaches these.
        """

        def cosine_distance(self, other: object, /) -> Operators:
            return self.op("<=>", return_type=Float)(other)

        def l2_distance(self, other: object, /) -> Operators:
            return self.op("<->", return_type=Float)(other)

        def max_inner_product(self, other: object, /) -> Operators:
            return self.op("<#>", return_type=Float)(other)

    comparator_factory = Comparator

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector as PgVector

            return dialect.type_descriptor(PgVector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.dumps([float(v) for v in value])

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.loads(value)


class JSONBCompat(TypeDecorator):
    """``jsonb`` on PostgreSQL, ``json`` elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())
