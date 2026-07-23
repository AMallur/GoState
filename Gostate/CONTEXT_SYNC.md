# GoState Context Sync

GoState is an enterprise-grade Context Preservation Engine for freezing,
serializing, restoring, and later querying volatile developer workspace state.

The MVP implements:
- A FastAPI gateway with RFC 7807 problem-details responses.
- Fail-closed security bootstrap requiring `JWT_SECRET_KEY`.
- Flat immutable user identity models optimized for relational indexed reads.
- Immutable JSONB-ready context models for workspace files, environment
  variables, process trees, and bounded metadata.
- In-memory capture, fetch, and restore-plan routes as the API contract before
  PostgreSQL JSONB persistence is introduced.

Persistence target for the next layer:
- `users`: flat relational identity table with a composite B-Tree index on
  `(user_id, is_active)`.
- `context_states`: state envelope columns plus a single `payload JSONB` column
  with a GIN index for nested workspace-footprint lookup.
