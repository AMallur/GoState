from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import ContextState
from app.repositories.contexts import context_state_from_record


def test_context_state_from_record_parses_supabase_jsonb_payload() -> None:
    now = datetime.now(UTC)
    digest = "f" * 64
    record = {
        "state_id": uuid4(),
        "owner_user_id": uuid4(),
        "tenant_id": uuid4(),
        "workspace_id": "workspace-alpha",
        "captured_at": now,
        "status": "captured",
        "payload": {
            "root_path": "/workspace/gostate",
            "files": [
                {
                    "path": "/workspace/gostate/app/main.py",
                    "node_type": "file",
                    "size_bytes": 1024,
                    "content_sha256": digest,
                    "modified_at": now.isoformat(),
                }
            ],
            "environment": [],
            "processes": [],
            "attributes": [],
        },
        "expires_at": now + timedelta(hours=1),
    }

    state = context_state_from_record(record)

    assert isinstance(state, ContextState)
    assert state.payload.files[0].content_sha256 == digest
