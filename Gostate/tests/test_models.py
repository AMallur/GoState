from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import (
    ContextCaptureRequest,
    ContextState,
    ContextStatus,
    EnvironmentVariable,
    FileSystemEntry,
    FileSystemNodeType,
    TerminalProcess,
    User,
    UserRole,
    WorkspaceFootprint,
)


def aware_now() -> datetime:
    return datetime.now(UTC)


def test_user_accepts_flat_relational_shape() -> None:
    now = aware_now()

    user = User(
        user_id=uuid4(),
        tenant_id=uuid4(),
        email="operator@example.com",
        role=UserRole.OPERATOR,
        password_hash="x" * 64,
        is_active=True,
        is_locked=False,
        created_at=now,
        updated_at=now,
        last_authenticated_at=now,
    )

    assert user.role is UserRole.OPERATOR


def test_user_rejects_nested_or_extra_identity_metadata() -> None:
    now = aware_now()

    with pytest.raises(ValidationError):
        User(
            user_id=uuid4(),
            tenant_id=uuid4(),
            email="operator@example.com",
            role=UserRole.OPERATOR,
            password_hash="x" * 64,
            is_active=True,
            is_locked=False,
            created_at=now,
            updated_at=now,
            metadata={"unsafe": True},
        )


def test_user_rejects_locked_active_state() -> None:
    now = aware_now()

    with pytest.raises(ValidationError):
        User(
            user_id=uuid4(),
            tenant_id=uuid4(),
            email="operator@example.com",
            role=UserRole.OPERATOR,
            password_hash="x" * 64,
            is_active=True,
            is_locked=True,
            created_at=now,
            updated_at=now,
        )


def test_models_are_frozen() -> None:
    now = aware_now()
    user = User(
        user_id=uuid4(),
        tenant_id=uuid4(),
        email="operator@example.com",
        role=UserRole.OPERATOR,
        password_hash="x" * 64,
        is_active=True,
        is_locked=False,
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(ValidationError):
        user.is_active = False


def test_context_state_accepts_jsonb_ready_workspace_payload() -> None:
    captured_at = aware_now()
    digest = "b" * 64
    footprint = WorkspaceFootprint(
        root_path="/workspace/gostate",
        files=(
            FileSystemEntry(
                path="/workspace/gostate/app/main.py",
                node_type=FileSystemNodeType.FILE,
                size_bytes=512,
                content_sha256=digest,
                modified_at=captured_at,
            ),
        ),
        environment=(EnvironmentVariable(name="PATH", value_sha256=digest),),
        processes=(
            TerminalProcess(
                pid=9001,
                parent_pid=1,
                command="pytest",
                command_sha256=digest,
                cwd="/workspace/gostate",
                environment_sha256=digest,
                started_at=captured_at,
            ),
        ),
    )

    state = ContextState(
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
        workspace_id="workspace-alpha",
        captured_at=captured_at,
        status=ContextStatus.CAPTURED,
        payload=footprint,
        expires_at=captured_at + timedelta(hours=1),
    )

    dumped = state.model_dump(mode="json")
    assert dumped["payload"]["root_path"] == "/workspace/gostate"
    assert dumped["payload"]["files"][0]["content_sha256"] == digest


def test_context_capture_rejects_extra_fields() -> None:
    digest = "c" * 64

    with pytest.raises(ValidationError):
        ContextCaptureRequest(
            owner_user_id=uuid4(),
            tenant_id=uuid4(),
            workspace_id="workspace-alpha",
            payload=WorkspaceFootprint(
                root_path="/workspace/gostate",
                environment=(EnvironmentVariable(name="PATH", value_sha256=digest),),
            ),
            unsafe=True,
        )


def test_context_payload_rejects_duplicate_files() -> None:
    now = aware_now()
    digest = "d" * 64
    entry = FileSystemEntry(
        path="/workspace/gostate/app/main.py",
        node_type=FileSystemNodeType.FILE,
        size_bytes=512,
        content_sha256=digest,
        modified_at=now,
    )

    with pytest.raises(ValidationError):
        WorkspaceFootprint(root_path="/workspace/gostate", files=(entry, entry))


def test_file_entry_rejects_missing_digest_for_file() -> None:
    with pytest.raises(ValidationError):
        FileSystemEntry(
            path="/workspace/gostate/app/main.py",
            node_type=FileSystemNodeType.FILE,
            size_bytes=512,
            modified_at=aware_now(),
        )


def test_terminal_process_rejects_self_parenting() -> None:
    digest = "e" * 64

    with pytest.raises(ValidationError):
        TerminalProcess(
            pid=100,
            parent_pid=100,
            command="pytest",
            command_sha256=digest,
            cwd="/workspace/gostate",
            environment_sha256=digest,
            started_at=aware_now(),
        )
