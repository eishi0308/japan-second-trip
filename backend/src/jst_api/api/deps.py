"""FastAPI dependency wiring.

Singletons (provider registry, MCP backend, rate limiter) are built once during
app startup and stashed on ``app.state``; per-request objects (database session)
come from a dependency. Nothing reaches for a global at call time, which is what
makes the app testable with a substituted registry.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.config import Settings, get_settings
from jst_api.db.base import get_session
from jst_api.providers.registry import ProviderRegistry
from jst_api.security.auth import Principal, client_key, get_principal, require_admin
from jst_api.security.ratelimit import RateLimiter
from jst_api.services.analysis_service import AnalysisService
from jst_api.services.mcp_backend import JstTravelBackend


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


def get_backend(request: Request) -> JstTravelBackend:
    return request.app.state.backend


def get_session_factory(request: Request) -> Any:
    return request.app.state.session_factory


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


async def enforce_rate_limit(
    request: Request,
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    await limiter.check(client_key(request))


async def enforce_analysis_rate_limit(
    request: Request,
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    """Analysis endpoints cost real money; they consume a larger share of the budget."""
    await limiter.check(client_key(request), cost=5)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]
AnalysisDep = Annotated[AnalysisService, Depends(get_analysis_service)]
BackendDep = Annotated[JstTravelBackend, Depends(get_backend)]
SessionFactoryDep = Annotated[Any, Depends(get_session_factory)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
AdminDep = Annotated[Principal, Depends(require_admin)]
RateLimitDep = Annotated[None, Depends(enforce_rate_limit)]
AnalysisRateLimitDep = Annotated[None, Depends(enforce_analysis_rate_limit)]
