---
scope: backend-reliability
issues:
  - id: MCP-21
    title: "Backend: server startup race condition and lock clarity"
    status: Backlog
    blocked_by: []
  - id: MCP-22
    title: "Database: schema integrity gaps (FK cascade, TOCTOU, timestamps)"
    status: Backlog
    blocked_by: []
execution_order:
  - [MCP-21, MCP-22]
out_of_scope: []
affected_crates:
  - app/be/chatnut/cli.py
  - app/be/chatnut/db.py
  - app/be/chatnut/service.py
  - app/be/chatnut/mcp.py
---

# Working Scope: backend-reliability

## Issues in Scope

- **MCP-21**: Backend: server startup race condition and lock clarity (High)
  1. Fix `_ensure_server()` race condition — use `fcntl.flock` on `server.lock`
  2. Rename `svc.lock` to `_wait_notify_lock` with docstring, move to `mcp.py`
  3. Document single-worker requirement (uvicorn only, no gunicorn multi-worker)

- **MCP-22**: Database: schema integrity gaps (FK cascade, TOCTOU, timestamps) (High)
  1. Add `ON DELETE CASCADE` to `messages` FK (or document why not)
  2. Fix TOCTOU race in `create_room()` UUID generation — log when UUID discarded
  3. Enforce `+00:00` timestamp format explicitly in `_now()`

## Execution Order

1. MCP-21 and MCP-22 in parallel — no dependencies between them

## Affected Files

- `app/be/chatnut/cli.py` (MCP-21: startup race)
- `app/be/chatnut/mcp.py` (MCP-21: lock rename/move)
- `app/be/chatnut/service.py` (MCP-21: lock rename)
- `app/be/chatnut/db.py` (MCP-22: FK cascade, TOCTOU, timestamps)

## Validation

```bash
cd app/be && uv run pytest -xvs
```
