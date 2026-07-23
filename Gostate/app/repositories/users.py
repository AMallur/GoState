"""User repository implementations for dev bootstrap and Supabase persistence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from app.models import TestUserBootstrapRequest, User

UPSERT_TEST_USER_SQL = """
insert into public.users (
    user_id,
    tenant_id,
    email,
    display_name,
    role,
    password_hash,
    is_active,
    is_locked,
    created_at,
    updated_at
) values (
    $1,
    $2,
    $3,
    $4,
    $5,
    $6,
    true,
    false,
    $7,
    $7
)
on conflict (user_id) do update set
    tenant_id = excluded.tenant_id,
    email = excluded.email,
    display_name = excluded.display_name,
    role = excluded.role,
    password_hash = excluded.password_hash,
    is_active = true,
    is_locked = false,
    updated_at = excluded.updated_at
returning
    user_id,
    tenant_id,
    email,
    display_name,
    role,
    password_hash,
    is_active,
    is_locked,
    created_at,
    updated_at,
    last_authenticated_at
"""


class UserRepository(Protocol):
    async def bootstrap_test_user(self, request: TestUserBootstrapRequest) -> tuple[User, bool]:
        """Create or update a deterministic dev/test user."""

    async def close(self) -> None:
        """Release repository resources."""


class MemoryUserRepository:
    """Concurrency-safe local user store."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._users: dict[UUID, User] = {}

    async def bootstrap_test_user(self, request: TestUserBootstrapRequest) -> tuple[User, bool]:
        now = datetime.now(UTC)
        user = User(
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            email=request.email,
            display_name=request.display_name,
            role=request.role,
            password_hash=request.password_hash,
            is_active=True,
            is_locked=False,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            created = request.user_id not in self._users
            self._users[user.user_id] = user
        return user, created

    async def close(self) -> None:
        return None


class SupabaseUserRepository:
    """Supabase Postgres persistence for users."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def bootstrap_test_user(self, request: TestUserBootstrapRequest) -> tuple[User, bool]:
        now = datetime.now(UTC)
        async with self._pool.acquire() as connection:
            existing = await connection.fetchval(
                "select exists(select 1 from public.users where user_id = $1)",
                request.user_id,
            )
            row = await connection.fetchrow(
                UPSERT_TEST_USER_SQL,
                request.user_id,
                request.tenant_id,
                request.email,
                request.display_name,
                request.role.value,
                request.password_hash,
                now,
            )
        if row is None:
            raise RuntimeError("test user bootstrap did not return a row")
        return user_from_record(row), not bool(existing)

    async def close(self) -> None:
        return None


def user_from_record(record: Mapping[str, Any]) -> User:
    data = {
        "user_id": record["user_id"],
        "tenant_id": record["tenant_id"],
        "email": record["email"],
        "display_name": record["display_name"],
        "role": record["role"],
        "password_hash": record["password_hash"],
        "is_active": record["is_active"],
        "is_locked": record["is_locked"],
        "created_at": record["created_at"].isoformat(),
        "updated_at": record["updated_at"].isoformat(),
        "last_authenticated_at": (
            record["last_authenticated_at"].isoformat()
            if record["last_authenticated_at"] is not None
            else None
        ),
    }
    return User.model_validate_json(json.dumps(data, default=str))
