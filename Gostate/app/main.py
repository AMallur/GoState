"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast
from uuid import UUID

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, Response

from app.core.config import StorageBackend, load_app_settings
from app.core.problem_details import (
    VALIDATION_ERROR_TYPE,
    AppException,
    assign_trace_id,
    build_problem_response,
    problem_from_app_exception,
    problem_from_http_exception,
    problem_from_unhandled_exception,
    problem_from_validation_exception,
)
from app.core.security import load_security_settings
from app.models import (
    ContextCaptureRequest,
    ContextCaptureResponse,
    ContextRestorePlan,
    ContextState,
    TestUserBootstrapRequest,
    TestUserBootstrapResponse,
)
from app.repositories import (
    ContextRepository,
    MemoryContextRepository,
    MemoryUserRepository,
    SupabaseContextRepository,
    SupabaseUserRepository,
    UserRepository,
)

APP_TITLE: Final[str] = "Gostate API"
APP_VERSION: Final[str] = "0.1.0"
CONTEXT_NOT_FOUND_TYPE: Final[str] = "https://gostate.local/problems/context-not-found"
DEV_MODE_DISABLED_TYPE: Final[str] = "https://gostate.local/problems/dev-mode-disabled"
STATIC_INDEX_PATH: Final[Path] = Path(__file__).resolve().parent / "static" / "index.html"


class HealthResponse(BaseModel):
    """Typed health-check response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: str
    service: str
    version: str


def create_app() -> FastAPI:
    load_security_settings()
    settings = load_app_settings()

    @asynccontextmanager
    async def lifespan(lifespan_app: FastAPI) -> AsyncIterator[None]:
        repository: ContextRepository
        user_repository: UserRepository
        if settings.storage_backend is StorageBackend.SUPABASE:
            if settings.supabase_database_url is None:
                raise RuntimeError("Supabase storage selected without a database URL")
            pool = await SupabaseContextRepository.create_pool(settings.supabase_database_url)
            repository = SupabaseContextRepository(pool)
            user_repository = SupabaseUserRepository(pool)
        else:
            repository = MemoryContextRepository()
            user_repository = MemoryUserRepository()

        lifespan_app.state.context_repository = repository
        lifespan_app.state.user_repository = user_repository
        try:
            yield
        finally:
            await user_repository.close()
            await repository.close()

    app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=lifespan)
    if settings.storage_backend is StorageBackend.MEMORY:
        app.state.context_repository = MemoryContextRepository()
        app.state.user_repository = MemoryUserRepository()

    @app.middleware("http")
    async def problem_details_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        assign_trace_id(request)
        try:
            return await call_next(request)
        except Exception as exc:
            problem = problem_from_unhandled_exception(request, exc)
            return build_problem_response(problem)

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> Response:
        return build_problem_response(problem_from_app_exception(request, exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        return build_problem_response(problem_from_http_exception(request, exc))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> Response:
        return build_problem_response(problem_from_validation_exception(request, exc))

    @app.get(
        "/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        tags=["system"],
    )
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service=APP_TITLE, version=APP_VERSION)

    @app.get("/", include_in_schema=False)
    async def dev_console() -> FileResponse:
        require_dev_mode(settings.dev_mode)
        return FileResponse(STATIC_INDEX_PATH)

    @app.post(
        "/dev/test-user",
        response_model=TestUserBootstrapResponse,
        status_code=status.HTTP_200_OK,
        tags=["dev"],
    )
    async def bootstrap_test_user(request: Request) -> TestUserBootstrapResponse:
        require_dev_mode(settings.dev_mode)
        body = await request.body()
        try:
            bootstrap_request = (
                TestUserBootstrapRequest()
                if body.strip() == b""
                else TestUserBootstrapRequest.model_validate_json(body)
            )
        except ValidationError as exc:
            raise AppException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Request validation failed",
                detail="The request body, path, or query parameters failed validation.",
                type_uri=VALIDATION_ERROR_TYPE,
            ) from exc

        user_repository = get_user_repository(request)
        user, created = await user_repository.bootstrap_test_user(bootstrap_request)
        return TestUserBootstrapResponse(user=user, created=created)

    @app.post(
        "/contexts",
        response_model=ContextCaptureResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["contexts"],
    )
    async def capture_context(request: Request) -> ContextCaptureResponse:
        try:
            capture_request = ContextCaptureRequest.model_validate_json(await request.body())
        except ValidationError as exc:
            raise AppException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                title="Request validation failed",
                detail="The request body, path, or query parameters failed validation.",
                type_uri=VALIDATION_ERROR_TYPE,
            ) from exc

        repository = get_context_repository(request)
        state = await repository.capture(capture_request)
        return ContextCaptureResponse(
            state_id=state.state_id,
            status=state.status,
            file_count=len(state.payload.files),
            environment_count=len(state.payload.environment),
            process_count=len(state.payload.processes),
        )

    @app.get(
        "/contexts/{state_id}",
        response_model=ContextState,
        status_code=status.HTTP_200_OK,
        tags=["contexts"],
    )
    async def get_context(state_id: UUID) -> ContextState:
        repository = get_context_repository_from_app(app)
        state = await repository.get(state_id)
        if state is None:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                title="Context state not found",
                detail="No captured context exists for the requested state identifier.",
                type_uri=CONTEXT_NOT_FOUND_TYPE,
            )
        return state

    @app.post(
        "/contexts/{state_id}/restore",
        response_model=ContextRestorePlan,
        status_code=status.HTTP_200_OK,
        tags=["contexts"],
    )
    async def restore_context(state_id: UUID) -> ContextRestorePlan:
        repository = get_context_repository_from_app(app)
        state = await repository.get(state_id)
        if state is None:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                title="Context state not found",
                detail="No captured context exists for the requested state identifier.",
                type_uri=CONTEXT_NOT_FOUND_TYPE,
            )
        now = datetime.now(UTC)
        restore_allowed = state.expires_at is None or state.expires_at > now
        return ContextRestorePlan(
            state_id=state.state_id,
            workspace_id=state.workspace_id,
            environment=state.payload.environment,
            processes=state.payload.processes,
            file_count=len(state.payload.files),
            restore_allowed=restore_allowed,
        )

    return app


def get_context_repository(request: Request) -> ContextRepository:
    repository = getattr(request.app.state, "context_repository", None)
    if repository is None:
        raise RuntimeError("context repository is not initialized")
    return cast(ContextRepository, repository)


def get_context_repository_from_app(app: FastAPI) -> ContextRepository:
    repository = getattr(app.state, "context_repository", None)
    if repository is None:
        raise RuntimeError("context repository is not initialized")
    return cast(ContextRepository, repository)


def get_user_repository(request: Request) -> UserRepository:
    repository = getattr(request.app.state, "user_repository", None)
    if repository is None:
        raise RuntimeError("user repository is not initialized")
    return cast(UserRepository, repository)


def require_dev_mode(enabled: bool) -> None:
    if not enabled:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Development endpoint disabled",
            detail="This endpoint is only available when GOSTATE_DEV_MODE is enabled.",
            type_uri=DEV_MODE_DISABLED_TYPE,
        )


app = create_app()
