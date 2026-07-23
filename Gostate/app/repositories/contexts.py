"""Context-state repository implementations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

import asyncpg

from app.models import ContextCaptureRequest, ContextState
from app.models.context import ContextStatus

INSERT_CONTEXT_STATE_SQL = """
insert into public.context_states (
    state_id,
    owner_user_id,
    tenant_id,
    workspace_id,
    captured_at,
    status,
    payload,
    expires_at
) values (
    $1,
    $2,
    $3,
    $4,
    $5,
    $6,
    $7::jsonb,
    $8
)
returning
    state_id,
    owner_user_id,
    tenant_id,
    workspace_id,
    captured_at,
    status,
    payload,
    expires_at
"""

SELECT_CONTEXT_STATE_BY_ID_SQL = """
select
    state_id,
    owner_user_id,
    tenant_id,
    workspace_id,
    captured_at,
    status,
    payload,
    expires_at
from public.context_states
where state_id = $1
limit 1
"""


class ContextRepository(Protocol):
    async def capture(self, request: ContextCaptureRequest) -> ContextState:
        """Persist and return a captured context state."""

    async def get(self, state_id: UUID) -> ContextState | None:
        """Return a captured context by ID."""

    async def close(self) -> None:
        """Release repository resources."""


class MemoryContextRepository:
    """Concurrency-safe local storage for tests and no-database development."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._states: dict[UUID, ContextState] = {}

    async def capture(self, request: ContextCaptureRequest) -> ContextState:
        captured_at = datetime.now(UTC)
        state = ContextState(
            owner_user_id=request.owner_user_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            captured_at=captured_at,
            status=ContextStatus.CAPTURED,
            payload=request.payload,
            expires_at=request.expires_at,
        )
        async with self._lock:
            self._states[state.state_id] = state
        return state

    async def get(self, state_id: UUID) -> ContextState | None:
        async with self._lock:
            return self._states.get(state_id)

    async def close(self) -> None:
        return None


class SupabaseContextRepository:
    """Supabase Postgres JSONB persistence for context states."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create_pool(cls, database_url: str) -> asyncpg.Pool:
        return await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=5)

    @classmethod
    async def create(cls, database_url: str) -> SupabaseContextRepository:
        pool = await cls.create_pool(database_url)
        return cls(pool)

    async def capture(self, request: ContextCaptureRequest) -> ContextState:
        captured_at = datetime.now(UTC)
        state_id = uuid4()
        payload_json = request.payload.model_dump_json()
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                INSERT_CONTEXT_STATE_SQL,
                state_id,
                request.owner_user_id,
                request.tenant_id,
                request.workspace_id,
                captured_at,
                ContextStatus.CAPTURED.value,
                payload_json,
                request.expires_at,
            )
        if row is None:
            raise RuntimeError("context capture insert did not return a row")
        return context_state_from_record(row)

    async def get(self, state_id: UUID) -> ContextState | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(SELECT_CONTEXT_STATE_BY_ID_SQL, state_id)
        if row is None:
            return None
        return context_state_from_record(row)

    async def close(self) -> None:
        await self._pool.close()


def context_state_from_record(record: Mapping[str, Any]) -> ContextState:
    payload = record["payload"]
    if isinstance(payload, str):
        payload_data = json.loads(payload)
    else:
        payload_data = payload

    raw_expires_at = record["expires_at"]
    state_data = {
        "state_id": record["state_id"],
        "owner_user_id": record["owner_user_id"],
        "tenant_id": record["tenant_id"],
        "workspace_id": record["workspace_id"],
        "captured_at": record["captured_at"].isoformat(),
        "status": record["status"],
        "payload": payload_data,
        "expires_at": raw_expires_at.isoformat() if raw_expires_at is not None else None,
    }
    return ContextState.model_validate_json(json.dumps(state_data, default=str))
