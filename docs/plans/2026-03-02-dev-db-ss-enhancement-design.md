# Dev DB + ss Enhancement Design

**Date:** 2026-03-02
**Branch:** docs-ci
**Status:** Approved

## Problem

The agents-chat service uses a single SQLite database (`~/.agents-chat/agents-chat.db`) for all purposes. There is no dedicated development database for local testing, demos, or git-tracked fixture data. The `ss` alias treats agents-chat as a bare dev server with no PROD/DEV distinction, unlike runno and pbimate.

## Goals

1. Create a committed dev DB (`data/dev.db`) with curated demo data for development and demo purposes.
2. Provide a seed script (`data/seed.py`) to (re)generate the dev DB from scratch.
3. Add a separate `start-server-dev.sh` that points the server at the dev DB.
4. Enhance `ss` option 4 to show a PROD/DEV menu symmetric with runno/pbimate.

## Design

### 1. Dev DB — `main/data/dev.db`

- Location: `agents-chat-mcp/main/data/dev.db`
- Committed to git (not gitignored) — serves as a demo fixture and git artifact
- Schema: identical to prod (`rooms`, `messages`, `read_cursors` tables)
- Populated by `data/seed.py`

### 2. Seed Script — `main/data/seed.py`

Standalone Python script (stdlib + sqlite3 only):

```
python data/seed.py           # seed only if DB is empty
python data/seed.py --reset   # wipe and re-seed from scratch
```

Generates curated static demo data:
- 2–3 projects (e.g., `demo-project`, `runno-ai`)
- 4–6 rooms per project with realistic agent team names (`planning`, `backend`, `design-review`)
- 10–20 messages per room with realistic multi-agent conversations
- Read cursors showing mixed read/unread state

### 3. Dev Start Script — `~/.claude/skills/agents-chat/start-server-dev.sh`

Thin wrapper alongside `start-server.sh`. Sets `CHAT_DB_PATH` to the repo's dev DB:

```bash
#!/usr/bin/env bash
exec env CHAT_DB_PATH="$HOME/agents-chat-mcp/main/data/dev.db" \
  /Users/tushuyang/agents-chat-mcp/main/app/be/.venv/bin/python \
  -m uvicorn agents_chat_mcp.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}"
```

### 4. ss Enhancement — `portless.sh`

Replace the bare `_handle_dev` call for option 4 with a new `_agents_chat_ss` function:

```
agents-chat — Select mode:

  1) PROD  agents-chat        ● http://agents-chat.localhost:1355
  2) DEV   agents-chat-dev      http://agents-chat-dev.localhost:1355

Select (1-2):
```

Behavior:
- **PROD**: checks running status, opens URL — never starts/stops the always-on service
- **DEV**: calls `portless agents-chat-dev ./start-server-dev.sh` from `~/.claude/skills/agents-chat/`; handles force-restart if already running (same pattern as `_handle_dev`)

### 5. Files Changed

| File | Change |
|------|--------|
| `main/data/seed.py` | New — curated seed script |
| `main/data/dev.db` | New — seeded dev DB (committed) |
| `~/.claude/skills/agents-chat/start-server-dev.sh` | New — dev start script with dev DB path |
| `~/.claude/skills/shell/workspace/portless.sh` | Add `_agents_chat_ss`; update `ss` option 4 |

## Non-Goals

- Prod DB migration or modification
- Anonymizing prod data (seed is fully static/hardcoded)
- Making `agents-chat-dev` a persistent portless service (it's on-demand via `ss`)

## Testing

- Run `python data/seed.py --reset` → verify `data/dev.db` is created with expected rooms/messages
- Run `ss` → select `4) agents-chat` → verify PROD/DEV menu appears
- Select DEV → verify `agents-chat-dev` starts at `http://agents-chat-dev.localhost:1355` with demo data
- Select PROD → verify URL opens, prod service is untouched
