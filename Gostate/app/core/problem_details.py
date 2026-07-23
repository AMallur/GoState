"""RFC 7807 problem-details infrastructure."""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

PROBLEM_JSON: Final[str] = "application/problem+json"
DEFAULT_PROBLEM_TYPE: Final[str] = "about:blank"
INTERNAL_ERROR_TYPE: Final[str] = "https://gostate.local/problems/internal-server-error"
VALIDATION_ERROR_TYPE: Final[str] = "https://gostate.local/problems/request-validation"
UNPROCESSABLE_ENTITY_STATUS: Final[int] = 422
INTERNAL_SERVER_ERROR_STATUS: Final[int] = 500


class ProblemDetails(BaseModel):
    """Client-safe RFC 7807 response body with a trace extension."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    type: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    status: int = Field(ge=400, le=599)
    detail: str = Field(min_length=1, max_length=512)
    instance: str = Field(min_length=1, max_length=2048)
    trace_id: UUID


class AppException(Exception):
    """Application exception intended for safe problem-details serialization."""

    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str,
        type_uri: str = DEFAULT_PROBLEM_TYPE,
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type_uri = type_uri
        super().__init__(title)


def get_trace_id(request: Request) -> UUID:
    """Return the existing per-request trace ID or create a fail-closed fallback."""

    candidate = getattr(request.state, "trace_id", None)
    if isinstance(candidate, UUID):
        return candidate
    trace_id = uuid4()
    request.state.trace_id = trace_id
    return trace_id


def assign_trace_id(request: Request) -> UUID:
    """Set request trace ID from a valid correlation header or generate one."""

    raw_trace_id = request.headers.get("x-correlation-id")
    if raw_trace_id is not None:
        try:
            trace_id = UUID(raw_trace_id)
        except ValueError:
            trace_id = uuid4()
    else:
        trace_id = uuid4()

    request.state.trace_id = trace_id
    return trace_id


def build_problem_response(problem: ProblemDetails) -> JSONResponse:
    return JSONResponse(
        content=problem.model_dump(mode="json"),
        status_code=problem.status,
        media_type=PROBLEM_JSON,
    )


def problem_from_app_exception(request: Request, exc: AppException) -> ProblemDetails:
    return ProblemDetails(
        type=exc.type_uri,
        title=exc.title,
        status=exc.status_code,
        detail=exc.detail,
        instance=str(request.url.path),
        trace_id=get_trace_id(request),
    )


def problem_from_http_exception(
    request: Request,
    exc: StarletteHTTPException,
) -> ProblemDetails:
    detail = exc.detail if isinstance(exc.detail, str) else "HTTP request failed."
    return ProblemDetails(
        type=DEFAULT_PROBLEM_TYPE,
        title="HTTP request failed",
        status=exc.status_code,
        detail=detail,
        instance=str(request.url.path),
        trace_id=get_trace_id(request),
    )


def problem_from_validation_exception(
    request: Request,
    exc: RequestValidationError,
) -> ProblemDetails:
    return ProblemDetails(
        type=VALIDATION_ERROR_TYPE,
        title="Request validation failed",
        status=UNPROCESSABLE_ENTITY_STATUS,
        detail="The request body, path, or query parameters failed validation.",
        instance=str(request.url.path),
        trace_id=get_trace_id(request),
    )


def problem_from_unhandled_exception(request: Request, exc: Exception) -> ProblemDetails:
    return ProblemDetails(
        type=INTERNAL_ERROR_TYPE,
        title="Internal server error",
        status=INTERNAL_SERVER_ERROR_STATUS,
        detail="An internal error occurred while processing the request.",
        instance=str(request.url.path),
        trace_id=get_trace_id(request),
    )
