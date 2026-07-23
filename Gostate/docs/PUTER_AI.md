# Puter.js AI Integration Contract

Puter.js should stay in the client or local capture agent. GoState should receive
AI output as bounded context attributes, not run browser-side AI code inside the
Python API process.

Recommended flow:

1. The capture client builds a `WorkspaceFootprint`.
2. Puter.js summarizes or labels the workspace state locally.
3. The client sends those AI outputs as `payload.attributes` entries.
4. GoState stores the full payload in Supabase `context_states.payload`.

Example attribute keys:

- `ai.summary`
- `ai.risk_level`
- `ai.restore_hint`
- `ai.model`

Example browser-side shape:

```js
const summary = await puter.ai.chat(
  "Summarize this workspace capture for restore triage: " +
    JSON.stringify(workspaceFootprint)
);

await fetch("http://127.0.0.1:8000/contexts", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    owner_user_id: userId,
    tenant_id: tenantId,
    workspace_id: workspaceId,
    payload: {
      ...workspaceFootprint,
      attributes: [
        ...(workspaceFootprint.attributes ?? []),
        { key: "ai.summary", value: String(summary) },
        { key: "ai.model", value: "puter.js" }
      ]
    }
  })
});
```

Do not send raw secrets, environment variable values, or terminal tokens to
Puter.js. The GoState model expects hashed environment values.
