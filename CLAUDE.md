# CLAUDE.md

## Project Overview

ChatNut — unified FastAPI server for agent team chatrooms. Serves MCP tools (HTTP transport), REST/SSE web API, and a React SPA from a single process. SQLite-backed with project/branch scoping, search, and real-time updates via SSE.

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12 |
| MCP framework | fastmcp 3.x (stdio + HTTP transport, mounted in FastAPI) |
| Web framework | FastAPI + sse-starlette |
| Storage | SQLite with WAL mode (path from `CHAT_DB_PATH` env var) |
| Frontend | React 19, Tailwind 4, Vite (single-file build) |
| Package manager | uv (backend), bun (frontend) |

## Project Structure

```text
app/
  be/
    chatnut/
      __init__.py
      app.py             # FastAPI app — mounts MCP + routes + static serving
      cli.py             # CLI entry point (stdio proxy, serve, open subcommands)
      mcp.py             # FastMCP tool definitions (thin wrappers over ChatService)
      service.py         # ChatService class — all business logic
      db.py              # SQLite schema, queries (UUID rooms, project scoping)
      models.py          # Dataclasses for Room, Message
      version_check.py   # GitHub releases API version check with TTL cache
    tests/
      conftest.py        # Shared fixtures (in-memory DB)
      test_models.py
      test_db.py
      test_service.py
      test_mcp.py
      test_routes.py
      test_cli.py
      test_integration.py
    pyproject.toml
    .python-version
  fe/
    src/
      components/        # React components (Sidebar, ChatView, Message, UpdateBanner, etc.)
      hooks/             # Custom hooks (useChatrooms, useSSE, useSearch, useProjects, useVersion)
      types.ts           # TypeScript interfaces
      App.tsx
    package.json
    vite.config.ts
    index.html
docs/
  plans/               # Implementation plans (active)
  plans/archived/      # Executed plans
README.md
CLAUDE.md
SKILL.md
```

## Commands

```bash
# Backend setup
cd app/be && uv sync --extra test

# Run all backend tests
cd app/be && uv run pytest -xvs

# Post-install: register MCP, install skill + protocol rules
chatnut install

# Start server (auto-selects free port, writes PID/port to ~/.chatnut/)
chatnut serve

# Start server on a specific port
chatnut serve --port 8000

# Run as stdio MCP proxy (auto-starts server if needed)
chatnut

# Open web UI in browser (auto-starts server if needed)
chatnut open

# Open a specific room
chatnut open <room-id>

# Frontend setup
cd app/fe && bun install

# Frontend dev (proxies to FastAPI on :8000)
cd app/fe && bun run dev

# Frontend build (single-file dist/index.html)
cd app/fe && bun run build

# Frontend tests
cd app/fe && bun run test
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CHAT_DB_PATH` | SQLite database file path | `~/.chatnut/chatnut.db` |
| `STATIC_DIR` | Path to built React SPA | `chatnut/static/` (bundled in wheel) |
| `CHATNUT_RUN_DIR` | Runtime dir for PID/port files | `~/.chatnut/` |
| `CHATNUT_OPEN_BROWSER` | Auto-open browser on `init_room` (`0` to suppress) | `1` |

## MCP Registration

stdio transport (recommended) — server starts automatically:

```json
{
  "chatnut": {
    "command": "chatnut"
  }
}
```

HTTP transport (alternative) — requires manually running `chatnut serve`:

```json
{
  "chatnut": {
    "url": "http://localhost:<port>/mcp/"
  }
}
```

## Architecture

```
Single FastAPI Process
├── /mcp/              ← FastMCP mounted (HTTP transport for agents)
├── /api/              ← REST endpoints (projects, search, chatrooms)
├── /api/stream/       ← SSE endpoints (room list, messages)
└── /*                 ← Static React SPA build (dist/)
```

Layered: `mcp.py` (tools) / `routes.py` (REST+SSE) -> `service.py` (ChatService) -> `db.py`, `models.py`

Tools and routes never touch the DB directly. Tests instantiate `ChatService` with an in-memory SQLite DB.

## Tools

| Tool | Signature | Purpose |
|------|-----------|---------|
| `ping` | `()` | Health check (DB path, version info, `web_url` if server running) |
| `init_room` | `(project, name, branch?, description?, team_name?)` | Create a chatroom (idempotent); auto-opens browser via `web_url`; when `team_name` provided, writes `chatroom.json` to `~/.claude/teams/{team_name}/` (sanitized to prevent path traversal; write failures are non-fatal) |
| `post_message` | `(room_id, sender, content, message_type?)` | Post a message by room_id; returns `mentions` for any @registered agents |
| `read_messages` | `(room_id, since_id?, limit?, message_type?)` | Read messages by room_id |
| `wait_for_messages` | `(room_id, since_id, timeout?, limit?, message_type?)` | Block until new messages arrive (long-poll, max 60s); returns `timed_out=True` on timeout |
| `list_rooms` | `(project?, status?)` | List rooms (filter by project, status) |
| `list_projects` | `()` | List distinct project names |
| `archive_room` | `(project, name)` | Archive a room (keeps messages) |
| `delete_room` | `(room_id)` | Permanently delete an archived room and its messages |
| `clear_room` | `(project, name)` | Delete all messages in a room |
| `mark_read` | `(room_id, reader, last_read_message_id)` | Mark messages as read (cursor only moves forward) |
| `search` | `(query, project?)` | Search room names + message content |
| `update_status` | `(room_id, sender, status)` | Update a sender's status in a room (UPSERT, max 500 chars); requires non-empty sender/status; rejects missing/archived rooms |
| `get_team_status` | `(room_id)` | Get current status of all team members; raises ValueError if room not found |
| `register_agent` | `(room_id, agent_name, task_id)` | Register agent for @mention notifications (UPSERT, case-insensitive) |
| `list_agents` | `(room_id)` | List registered agents in a room |

## SKILL.md

The in-repo `SKILL.md` documents all MCP tools, their signatures, and usage patterns. Keep it updated when adding or modifying MCP tools.

## REST Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/status` | REST | Health check + version info |
| `GET /api/projects` | REST | Distinct project list |
| `GET /api/chatrooms` | REST | Filtered room list (?project, ?branch, ?status) |
| `GET /api/chatrooms/{room_id}/messages` | REST | Messages for a room (?since_id, ?limit) |
| `POST /api/chatrooms/{room_id}/read` | REST | Mark messages as read (body: `{reader, last_read_message_id}`) |
| `DELETE /api/chatrooms/{room_id}` | REST | Delete an archived room (404 if not found, 422 if live) |
| `GET /api/search` | REST | Search rooms + messages (?q, ?project) |
| `GET /api/stream/chatrooms` | SSE | Room list updates (real-time, `?reader=` for unread counts) |
| `GET /api/stream/messages` | SSE | Message stream (?room_id, honors Last-Event-Id) |
| `GET /api/chatrooms/{room_id}/status` | REST | Current team status for a room |
| `GET /api/stream/status` | SSE | Status changes (room_id param, polling + hash dedup) |

## Schema

```sql
CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,                    -- generated UUID
    name TEXT NOT NULL,
    project TEXT NOT NULL,
    branch TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'live',
    created_at TEXT NOT NULL,
    archived_at TEXT,
    metadata TEXT,                          -- JSON blob
    UNIQUE(project, name)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',  -- 'message' | 'system'
    created_at TEXT NOT NULL,
    metadata TEXT                           -- JSON blob
);
CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, id);

CREATE TABLE IF NOT EXISTS read_cursors (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    reader TEXT NOT NULL,
    last_read_message_id INTEGER NOT NULL DEFAULT 0 CHECK(last_read_message_id >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (room_id, reader)
);

CREATE TABLE IF NOT EXISTS room_status (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    status TEXT NOT NULL CHECK(length(status) <= 500),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (room_id, sender)
);

CREATE TABLE IF NOT EXISTS agent_registry (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    task_id TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    PRIMARY KEY (room_id, agent_name)
);
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push to `main` and on PRs targeting `main`:

| Job | Steps |
|-----|-------|
| **Backend Tests** | `uv sync --extra test` + `pytest -x` |
| **Frontend** | `bun install` + `tsc --noEmit` + `vitest run` + `vite build` |

## E2E CI

`.github/workflows/e2e.yml` runs on push to `main` and via `workflow_dispatch`. Tests the full install-to-MCP-tool-execution flow:

| Step | What it does |
|------|-------------|
| Install from source | `uv tool install ./app/be` (tests HEAD, not PyPI) |
| Verify CLI | `chatnut --help`, `chatnut open --help` |
| Register MCP | `claude mcp add chatnut -- $(which chatnut)` |
| Headless Claude tests | `claude -p` calls `ping` and `init_room` tools |
| DB verification | Direct SQLite queries to verify room creation |
| Health check | `curl` to server `/api/status` endpoint |

Requires `CLAUDE_CODE_OAUTH_TOKEN` secret (OAuth token from `claude setup-token`).

## CD

`.github/workflows/cd.yml` is triggered **only via `workflow_dispatch`** — either by the `/deployment` skill or manually via `gh workflow run cd.yml --ref main`.

- Builds frontend, bundles into Python wheel
- Publishes to PyPI via OIDC Trusted Publishing
- Creates git tag + GitHub Release with auto-generated notes

Uses PyPI OIDC Trusted Publishing (no stored secrets). See [RELEASING.md](RELEASING.md).

## Server Lifecycle

### Startup

`chatnut serve` binds to an auto-selected port, writes `server.pid` and `server.port` to `CHATNUT_RUN_DIR`, and logs to `server.log` in the same directory. The stdio proxy (`chatnut` with no args) calls `_ensure_server()` which auto-starts a background server if none is running, polling the port file for up to 10 seconds.

### Shutdown

SIGTERM/SIGINT triggers a cleanup handler that removes PID/port files and exits. An `atexit` handler provides a fallback. Stale PID files (process dead) are auto-cleaned on the next `_is_server_running()` check.

### Health check

Two-step: PID alive (`os.kill(pid, 0)`) + HTTP `GET /api/status` returns 200.

### Runtime files

| File | Written | Purpose |
|------|---------|---------|
| `server.pid` | On startup | Server process ID |
| `server.port` | After bind | Bound port number |
| `server.log` | On auto-start | Subprocess stdout/stderr |

## Dev vs Prod

Dev and prod are fully isolated — different DBs, different runtime dirs, different start mechanisms.

|  | Prod | Dev |
|--|------|-----|
| **Start** | MCP stdio → `_ensure_server()` | `ss` → portless `chatnut-dev` |
| **Binary** | Global `chatnut` (PyPI via `uv tool install`) | Project venv (`app/be/.venv/bin/python`) |
| **DB** | `~/.chatnut/chatnut.db` | `data/dev.db` (committed fixture) |
| **Run dir** | `~/.chatnut/` | `data/` (via `CHATNUT_RUN_DIR`) |
| **URL** | `http://127.0.0.1:<auto-port>` | `http://chatnut-dev.localhost:1355` |

Both can run simultaneously without conflict.

### Dev fixture DB

```bash
# Seed/reset dev DB with demo data (2 projects, 5 rooms, 45 messages)
cd app/be && uv run python ../../data/seed.py --reset

# Start dev server via portless
ss  # select chatnut
```

The dev start script (`~/.claude/skills/chatnut/start-server-dev.sh`) sets `CHAT_DB_PATH`, `CHATNUT_RUN_DIR`, and `STATIC_DIR` to isolate from prod.

## Design Decisions

- **Single FastAPI process** — MCP + REST + SSE + static serving, one language, shared ChatService
- **MCP tools are write-oriented, REST API is read-oriented** — MCP tools (`post_message`, `init_room`, etc.) are designed for agent writes; REST endpoints (`GET /api/chatrooms`, `GET /api/stream/messages`) are designed for the web UI to read. The frontend does not use MCP tools directly.
- **MCP stdio transport (default)** — CLI auto-starts HTTP server on first connection, proxies via FastMCP ProxyProvider; PID/port files at `~/.chatnut/` for server discovery
- **MCP HTTP transport (alternative)** — direct HTTP registration when server is already running
- **UUID room PK** — same room name allowed across projects via `UNIQUE(project, name)`
- **SQLite WAL mode** — concurrent reads (SSE polling) don't block MCP writes
- **SSE for push** — unidirectional, auto-reconnect, Last-Event-Id for resume
- **`get_all_room_stats()` batch for SSE** — 3 queries total (not 3N per-room) via batch COUNT/MAX/GROUP BY
- **`_escape_like()` for search** — escapes SQL LIKE wildcards in user input
- **No ORM** — direct sqlite3, schema is 5 tables (rooms, messages, read_cursors, room_status, agent_registry)
- **`since_id` for incremental reads** — agents poll with last-seen message ID
- **Read cursors for unread tracking** — `(room_id, reader)` PK, forward-only via `MAX()` in UPSERT, `ON DELETE CASCADE` for cleanup
- **`wait_for_messages` for agent blocking** — asyncio.Queue per waiter; `post_message` notifies via `call_soon_threadsafe(_wake_all)` (all `_waiters` access event-loop-only); zero DB reads while waiting; agents call once instead of polling in a loop; timeout capped at 60s
- **Auto-open browser on `init_room`** — `init_room` reads `server.port` file, constructs `web_url`, and calls `webbrowser.open()` automatically; suppressed via `CHATNUT_OPEN_BROWSER=0` in tests/CI; `conftest.py` has autouse `_suppress_browser` fixture
- **Update notification via GitHub releases API** — `version_check.py` fetches latest release tag from GitHub with 1hr in-memory TTL cache; `get_version_info()` (async) populates cache, `get_cached_version_info()` (sync) reads it without I/O; three consumers: startup log warning, `ping()` tool, `/api/status` endpoint; frontend `useVersion` hook fetches `/api/status` on load and shows a dismissible amber banner
- **Decoupled status system** — `room_status` table is separate from `messages`; UPSERT semantics (one row per sender per room); frontend shows as sticky StatusBar above messages, not inline; polling-based SSE endpoint consistent with existing chatroom stream
- **@mention notification via agent registry** — `agent_registry` table stores `(room_id, agent_name, task_id)` per room; `post_message` parses `@<name>` patterns via `(?<!\w)@([\w-]+)` regex, resolves against registry (case-insensitive via lowercase normalization), and returns `mentions: [{name, task_id}]` in the response; chatnut provides data, the calling agent fires `SendMessage`; unregistered mentions are silently skipped
- **Single-worker only** — `_waiters` (asyncio.Queue per waiter) are process-local. Multi-worker deployment (e.g. gunicorn with multiple workers) breaks `wait_for_messages` silently — notifications from one worker are invisible to waiters in another. Always run with `uvicorn` directly, never behind a multi-worker process manager.

## E2E Testing Patterns

MCP E2E tests (`tests/test_mcp_e2e.py`) run the full FastAPI + FastMCP stack in-process using `anyio` and `fastmcp.Client`.

```python
import anyio
import pytest
from fastmcp import Client

@pytest.mark.anyio
async def test_something():
    from chatnut.app import app

    async with Client(app, raise_on_error=False) as client:
        # raise_on_error=False: client returns error results instead of raising
        result = await client.call_tool("ping", {})
        assert not result.is_error  # snake_case, not isError
        data = json.loads(result.content[0].text)
```

Key patterns:
- **`@pytest.mark.anyio`** — marks the test as async; requires `pytest-anyio` in test deps (already in `pyproject.toml`). Works alongside `asyncio_mode = "strict"` (pytest-asyncio setting) — no extra anyio config needed.
- **`fastmcp.Client(app)`** — takes the FastAPI `app` directly, no server needed
- **`result.is_error`** — snake_case attribute (not `isError`)
- **`raise_on_error=False`** on client constructor — keeps error-path tests from raising; inspect `result.is_error` instead
- **`result.content[0].text`** — MCP response content is a list of `TextContent` objects
- **Helper pattern** — define a `call()` helper to reduce boilerplate:

  ```python
  async def call(client, tool: str, args: dict | None = None) -> dict:
      result = await client.call_tool(tool, args or {})
      assert result.content, f"Tool {tool!r} returned empty content"
      return json.loads(result.content[0].text)
  ```
