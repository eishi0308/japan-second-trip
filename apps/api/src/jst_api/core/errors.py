"""Domain error taxonomy mapped onto HTTP status codes at the API edge."""

from __future__ import annotations

from typing import Any


class JstError(Exception):
    """Base class for all application errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class NotFoundError(JstError):
    status_code = 404
    code = "not_found"


class ValidationFailedError(JstError):
    status_code = 422
    code = "validation_failed"


class UnauthorizedError(JstError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(JstError):
    status_code = 403
    code = "forbidden"


class RateLimitedError(JstError):
    status_code = 429
    code = "rate_limited"


class ConflictError(JstError):
    status_code = 409
    code = "conflict"


class ProviderError(JstError):
    """An external provider failed after retries."""

    status_code = 502
    code = "provider_error"


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"


class GuardrailViolation(JstError):
    """A guardrail refused to let a model output reach the user."""

    status_code = 422
    code = "guardrail_violation"


class SchemaRepairFailed(JstError):
    status_code = 502
    code = "schema_repair_failed"


class AgentBudgetExceeded(JstError):
    status_code = 503
    code = "agent_budget_exceeded"


class IngestionNotAllowed(JstError):
    """Attempted to ingest from a domain that is not on the allowlist."""

    status_code = 403
    code = "ingestion_not_allowed"
