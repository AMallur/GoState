# GoState

GoState is a context preservation backend for capturing and restoring developer
workspace state. The current MVP provides:

- FastAPI API gateway with RFC 7807 problem-details errors.
- Supabase Postgres schema for flat users and JSONB context snapshots.
- Local memory backend for fast laptop testing.
- Local CLI capture client for hashing workspace files, selected environment
  variables, and the active CLI process.

## Run Locally

Start the API in memory mode:

```bash
JWT_SECRET_KEY=local-dev-secret-key-with-at-least-32-bytes \
GOSTATE_STORAGE_BACKEND=memory \
GOSTATE_DEV_MODE=true \
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use the browser test console:

```text
http://127.0.0.1:8000/
```

Check the API:

```bash
python3 -m app.cli health
```

Capture this workspace:

```bash
python3 -m app.cli capture . --workspace-id gostate-local --max-files 250
```

Restore-plan lookup:

```bash
python3 -m app.cli restore <state_id>
```

The restore command only returns a deterministic plan. It does not mutate files,
spawn processes, or write environment variables.

The browser test console can bootstrap the deterministic test user, hash selected
files in the browser, attach Puter.js AI attributes when available, capture a
context, and inspect the restore plan.

## Supabase Mode

The Supabase schema has been applied to project `ckycjyekdndpfcvjundh`.

Run the backend against Supabase by setting:

```bash
JWT_SECRET_KEY=local-dev-secret-key-with-at-least-32-bytes \
GOSTATE_STORAGE_BACKEND=supabase \
SUPABASE_DATABASE_URL='postgresql://postgres:<password>@db.ckycjyekdndpfcvjundh.supabase.co:5432/postgres' \
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

For Supabase mode, the `context_states.owner_user_id` must reference an existing
`public.users.user_id`.

## Validation

```bash
python3 -m pytest
mypy app
ruff check .
```
