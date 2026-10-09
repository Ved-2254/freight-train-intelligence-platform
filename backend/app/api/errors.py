"""Consistent, sanitised API errors.

Every error response has the shape:
    {"error": {"code": "...", "message": "...", "details": {...}}, "request_id": "..."}
Messages are written for API clients; stack traces, filesystem paths and exception text stay
in the server logs.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("wagon.api")

# code -> HTTP status
ERROR_STATUS: dict[str, int] = {
    "BAD_REQUEST": 400,
    "EMPTY_UPLOAD": 400,
    "VIDEO_NOT_FOUND": 404,
    "JOB_NOT_FOUND": 404,
    "ARTIFACT_NOT_AVAILABLE": 404,
    "NOT_FOUND": 404,
    "METHOD_NOT_ALLOWED": 405,
    "VIDEO_NOT_AVAILABLE": 409,
    "VIDEO_IN_USE": 409,
    "JOB_ALREADY_ACTIVE": 409,
    "IDEMPOTENCY_KEY_REUSED": 409,
    "JOB_NOT_COMPLETED": 409,
    "JOB_FAILED": 409,
    "JOB_CANCELLED": 409,
    "JOB_NOT_CANCELLABLE": 409,
    "UPLOAD_TOO_LARGE": 413,
    "UNSUPPORTED_FILE_TYPE": 415,
    "UNSUPPORTED_VIDEO": 415,
    "VALIDATION_ERROR": 422,
    "INTERNAL_ERROR": 500,
    "DATABASE_UNAVAILABLE": 503,
    "SERVICE_NOT_READY": 503,
    "INSUFFICIENT_STORAGE": 507,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status or ERROR_STATUS.get(code, 400)


def error_body(code: str, message: str, request: Request, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details or {}},
        "request_id": getattr(request.state, "request_id", None),
    }


def _response(request: Request, status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    headers = {"X-Request-ID": getattr(request.state, "request_id", "") or ""}
    return JSONResponse(status_code=status, content=error_body(code, message, request, details), headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        if exc.status >= 500:
            log.error("API error %s: %s", exc.code, exc.message)
        return _response(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"location": [str(p) for p in e.get("loc", ())], "message": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return _response(request, 422, "VALIDATION_ERROR", "Request validation failed", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 413:
            limit = request.app.state.container.settings.max_upload_bytes
            return _response(request, 413, "UPLOAD_TOO_LARGE",
                             f"The upload exceeds the maximum size of {limit} bytes", {"max_upload_bytes": limit})
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "BAD_REQUEST")
        message = exc.detail if isinstance(exc.detail, str) else "Request could not be processed"
        return _response(request, exc.status_code, code, message)

    @app.exception_handler(sqlite3.OperationalError)
    async def _db_error(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        log.exception("Database error")
        return _response(request, 503, "DATABASE_UNAVAILABLE", "The database is temporarily unavailable")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _response(request, 500, "INTERNAL_ERROR", "An unexpected error occurred")
