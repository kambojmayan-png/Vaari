"""Error classes and handlers for Vaari adhering strictly to the contract error shape."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class VaariError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        http_status: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


def setup_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(VaariError)
    async def vaari_error_handler(request: Request, exc: VaariError) -> JSONResponse:
        headers = None
        retry = exc.details.get("retry_after_s") if exc.http_status == 429 else None
        if retry is not None:
            headers = {"Retry-After": str(retry)}
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict(), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first_field = None
        message = "Validation error."
        if errors:
            first_err = errors[0]
            loc = first_err.get("loc", ())
            # FastAPI's loc looks like ("body", "acres") or ("query", "date")
            if len(loc) > 1:
                first_field = str(loc[-1])
            elif len(loc) == 1:
                first_field = str(loc[0])
            message = first_err.get("msg", message)

        details = {"field": first_field} if first_field else {}
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "VALIDATION_ERROR",
                "message": message,
                "details": details,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if not request.url.path.startswith("/api"):
            # Leave non-API routes for SPA fallback / default handlers
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

        code_map = {
            401: "UNAUTHORIZED",
            403: "WRONG_SLOT" if exc.detail == "WRONG_SLOT" else "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "INVALID_TRANSITION",
            413: "PAYLOAD_TOO_LARGE",
            422: "VALIDATION_ERROR",
            503: "READER_UNAVAILABLE",
        }
        error_code = code_map.get(exc.status_code, "HTTP_ERROR")
        message = str(exc.detail) if exc.detail else "An error occurred."
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": error_code,
                "message": message,
                "details": {},
            },
        )
