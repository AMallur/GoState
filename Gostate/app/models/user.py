"""Flat relational user identity models optimized for indexed reads."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, model_validator

DisplayName = Annotated[str, Field(min_length=1, max_length=128)]
PasswordHash = Annotated[str, Field(min_length=32, max_length=255)]
TEST_USER_ID = UUID("00000000-0000-4000-8000-000000000101")
TEST_TENANT_ID = UUID("00000000-0000-4000-8000-000000000102")


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    SERVICE = "service"


class User(BaseModel):
    """Read-optimized identity row shape.

    The model intentionally stays flat: no nested metadata, arrays, or JSON-like fields.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: UUID
    tenant_id: UUID
    email: EmailStr
    display_name: DisplayName | None = None
    role: UserRole
    password_hash: PasswordHash
    is_active: bool
    is_locked: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime
    last_authenticated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_flat_identity_contract(self) -> User:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be greater than or equal to created_at")
        if self.last_authenticated_at is not None and self.last_authenticated_at < self.created_at:
            raise ValueError("last_authenticated_at cannot be earlier than created_at")
        if self.is_locked and self.is_active:
            raise ValueError("locked users must not remain active")
        return self


class TestUserBootstrapRequest(BaseModel):
    """Dev-only test user bootstrap input."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: UUID = TEST_USER_ID
    tenant_id: UUID = TEST_TENANT_ID
    email: EmailStr = "test.user@example.com"
    display_name: DisplayName = "GoState Test User"
    role: UserRole = UserRole.OPERATOR
    password_hash: PasswordHash = "dev-only-password-hash-value-000000000000"


class TestUserBootstrapResponse(BaseModel):
    """Dev-only test user bootstrap output."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user: User
    created: bool
