from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Body
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.core.problem_details import PROBLEM_JSON, AppException
from app.main import create_app
from app.models import ContextState


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    value: int


PayloadBody = Annotated[Payload, Body()]


def test_health_returns_typed_payload() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Gostate API",
        "version": "0.1.0",
    }


def test_unknown_route_returns_problem_details() -> None:
    client = TestClient(create_app())

    response = client.get("/missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["type"] == "about:blank"
    assert body["title"] == "HTTP request failed"
    assert body["status"] == 404
    assert body["instance"] == "/missing"
    assert "trace_id" in body


def test_app_exception_returns_problem_details() -> None:
    app = create_app()

    @app.get("/blocked")
    async def blocked() -> None:
        raise AppException(
            status_code=403,
            title="Forbidden",
            detail="The principal is not authorized to access this resource.",
            type_uri="https://gostate.local/problems/forbidden",
        )

    client = TestClient(app)

    response = client.get("/blocked")

    assert response.status_code == 403
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert response.json()["type"] == "https://gostate.local/problems/forbidden"


def test_unexpected_exception_does_not_leak_internal_detail() -> None:
    app = create_app()

    @app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("secret-token-value")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/explode")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["title"] == "Internal server error"
    assert body["detail"] == "An internal error occurred while processing the request."
    assert "secret-token-value" not in response.text


def test_validation_error_returns_problem_details() -> None:
    app = create_app()

    @app.post("/payload")
    async def accept_payload(payload: PayloadBody) -> Payload:
        return payload

    client = TestClient(app)

    response = client.post("/payload", json={"value": "not-an-int"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert response.json()["type"] == "https://gostate.local/problems/request-validation"


def test_context_capture_fetch_and_restore_flow() -> None:
    client = TestClient(create_app())
    digest = "a" * 64
    payload = {
        "owner_user_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "workspace_id": "workspace-alpha",
        "payload": {
            "root_path": "/workspace/gostate",
            "files": [
                {
                    "path": "/workspace/gostate/app/main.py",
                    "node_type": "file",
                    "size_bytes": 4096,
                    "content_sha256": digest,
                    "modified_at": datetime.now(UTC).isoformat(),
                }
            ],
            "environment": [
                {
                    "name": "PATH",
                    "value_sha256": digest,
                    "is_secret": False,
                }
            ],
            "processes": [
                {
                    "pid": 1000,
                    "parent_pid": 1,
                    "command": "uvicorn app.main:app",
                    "command_sha256": digest,
                    "cwd": "/workspace/gostate",
                    "environment_sha256": digest,
                    "started_at": datetime.now(UTC).isoformat(),
                }
            ],
            "attributes": [
                {
                    "key": "branch",
                    "value": "main",
                }
            ],
        },
    }

    capture_response = client.post("/contexts", json=payload)

    assert capture_response.status_code == 201
    capture_body = capture_response.json()
    assert capture_body["status"] == "captured"
    assert capture_body["file_count"] == 1
    assert capture_body["environment_count"] == 1
    assert capture_body["process_count"] == 1

    state_id = capture_body["state_id"]
    fetch_response = client.get(f"/contexts/{state_id}")

    assert fetch_response.status_code == 200
    fetched_state = ContextState.model_validate_json(fetch_response.text)
    assert str(fetched_state.state_id) == state_id
    assert fetched_state.payload.root_path == "/workspace/gostate"

    restore_response = client.post(f"/contexts/{state_id}/restore")

    assert restore_response.status_code == 200
    restore_body = restore_response.json()
    assert restore_body["state_id"] == state_id
    assert restore_body["restore_allowed"] is True
    assert restore_body["file_count"] == 1


def test_missing_context_returns_problem_details() -> None:
    client = TestClient(create_app())
    state_id = uuid4()

    response = client.get(f"/contexts/{state_id}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert response.json()["type"] == "https://gostate.local/problems/context-not-found"
