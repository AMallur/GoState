"""Immutable JSONB-ready workspace context models."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

ContextKey = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
ContextValue = str | int | float | bool | None
Digest = Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")]
FilesystemPath = Annotated[str, Field(min_length=1, max_length=4096)]
ProcessCommand = Annotated[str, Field(min_length=1, max_length=2048)]
WorkspaceId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class ContextStatus(StrEnum):
    CAPTURED = "captured"
    RESTORED = "restored"
    EXPIRED = "expired"


class FileSystemNodeType(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"


class ContextAttribute(BaseModel):
    """Bounded metadata tuple item, avoiding unstructured dict transport."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    key: ContextKey
    value: ContextValue


class EnvironmentVariable(BaseModel):
    """Captured environment variable metadata.

    Values are represented by digests to avoid persisting raw secrets in API payloads.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: ContextKey
    value_sha256: Digest
    is_secret: bool = False


class FileSystemEntry(BaseModel):
    """Single file-system node captured into the workspace footprint."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: FilesystemPath
    node_type: FileSystemNodeType
    size_bytes: int = Field(ge=0)
    content_sha256: Digest | None = None
    modified_at: AwareDatetime

    @model_validator(mode="after")
    def validate_file_digest_contract(self) -> FileSystemEntry:
        if self.node_type is FileSystemNodeType.FILE and self.content_sha256 is None:
            raise ValueError("file entries require content_sha256")
        return self


class TerminalProcess(BaseModel):
    """Captured process-tree node."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    pid: int = Field(ge=1)
    parent_pid: int | None = Field(default=None, ge=1)
    command: ProcessCommand
    command_sha256: Digest
    cwd: FilesystemPath
    environment_sha256: Digest
    started_at: AwareDatetime

    @model_validator(mode="after")
    def validate_process_tree_contract(self) -> TerminalProcess:
        if self.parent_pid == self.pid:
            raise ValueError("parent_pid cannot equal pid")
        return self


class WorkspaceFootprint(BaseModel):
    """Hybrid JSONB payload for high-throughput context capture."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    root_path: FilesystemPath
    files: tuple[FileSystemEntry, ...] = Field(default_factory=tuple, max_length=100_000)
    environment: tuple[EnvironmentVariable, ...] = Field(default_factory=tuple, max_length=10_000)
    processes: tuple[TerminalProcess, ...] = Field(default_factory=tuple, max_length=10_000)
    attributes: tuple[ContextAttribute, ...] = Field(default_factory=tuple, max_length=1_000)

    @model_validator(mode="after")
    def validate_unique_collections(self) -> WorkspaceFootprint:
        file_paths = {entry.path for entry in self.files}
        if len(file_paths) != len(self.files):
            raise ValueError("file paths must be unique within a footprint")

        env_names = {entry.name for entry in self.environment}
        if len(env_names) != len(self.environment):
            raise ValueError("environment variable names must be unique within a footprint")

        process_ids = {entry.pid for entry in self.processes}
        if len(process_ids) != len(self.processes):
            raise ValueError("process ids must be unique within a footprint")

        return self


class ContextCaptureRequest(BaseModel):
    """Inbound context capture command."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    owner_user_id: UUID
    tenant_id: UUID
    workspace_id: WorkspaceId
    payload: WorkspaceFootprint
    expires_at: AwareDatetime | None = None


class ContextState(BaseModel):
    """Persistable JSONB state envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    state_id: UUID = Field(default_factory=uuid4)
    owner_user_id: UUID
    tenant_id: UUID
    workspace_id: WorkspaceId
    captured_at: AwareDatetime
    status: ContextStatus
    payload: WorkspaceFootprint
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_expiration_contract(self) -> ContextState:
        if self.expires_at is not None and self.expires_at <= self.captured_at:
            raise ValueError("expires_at must be later than captured_at")
        return self


class ContextCaptureResponse(BaseModel):
    """Capture acknowledgement returned by the gateway."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    state_id: UUID
    status: ContextStatus
    file_count: int = Field(ge=0)
    environment_count: int = Field(ge=0)
    process_count: int = Field(ge=0)


class ContextRestorePlan(BaseModel):
    """Deterministic restore plan derived from a captured context."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    state_id: UUID
    workspace_id: WorkspaceId
    environment: tuple[EnvironmentVariable, ...]
    processes: tuple[TerminalProcess, ...]
    file_count: int = Field(ge=0)
    restore_allowed: bool
