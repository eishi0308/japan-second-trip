"""Exception handlers: one consistent error envelope for every failure."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from jst_api.core.errors import JstError
from jst_api.core.logging import get_logger

log = get_logger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(JstError)
    async def _jst_error(request: Request, exc: JstError) -> JSONResponse:
        if exc.status_code >= 500:
            log.error("api.error", code=exc.code, path=request.url.path, message=exc.message)
        else:
            log.info("api.client_error", code=exc.code, path=request.url.path, message=exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": "Request body failed validation",
                    "details": {"errors": exc.errors()[:10]},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail), "details": {}}},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("api.unhandled", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {},
                }
            },
        )
