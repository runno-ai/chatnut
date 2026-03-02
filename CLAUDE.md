# CLAUDE.md

## Project Overview

Agents Chat MCP — unified FastAPI server for agent team chatrooms. Serves MCP tools (HTTP transport), REST/SSE web API, and a React SPA from a single process. SQLite-backed with project/branch scoping, search, and real-time updates via SSE.

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12 |
| MCP framework | fastmcp 3.x (HTTP transport, mounted in FastAPI) |
| Web framework | FastAPI + sse-starlette |
| Storage | SQLite with WAL mode (path from `CHAT_DB_PATH` env var) |
| Frontend | React 19, Tailwind 4, Vite (single-file build) |
| Package manager | uv (backend), bun (frontend) |

## Project Structure

```text
app/
  be/
    agents_chat_mcp/
      __init__.py
      app.py             # FastAPI app — mounts MCP + routes + static serving
      mcp.py             # FastMCP tool definitions (thin wrappers over ChatService)
      service.py         # ChatService class — all business logic
      db.py              # SQLite schema, queries (UUID rooms, project scoping)
      models.py          # Dataclasses for Room, Message
    tests/
      conftest.py        # Shared fixtures (in-memory DB)
      test_models.py
      test_db.py
      test_service.py
      test_mcp.py
      test_routes.py
      test_integration.py
    pyproject.toml
    .python-version
  fe/
    src/
      components/        # React components (Sidebar, ChatView, Message, etc.)
      hooks/             # Custom hooks (useChatrooms, useSSE, useSearch, useProjects)
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

# Start unified server (MCP + REST + SSE + static)
cd app/be && uv run uvicorn agents_chat_mcp.app:app --port 8000

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
| `CHAT_DB_PATH` | SQLite database file path | `~/.agents-chat/agents-chat.db` |
| `STATIC_DIR` | Path to built React SPA | `agents_chat_mcp/static/` (bundled in wheel) |

## MCP Registration

HTTP transport — register the URL (server must be running):

```json
{
  "agents-chat": {
    "url": "http://localhost:8000/mcp/"
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
| `ping` | `()` | Health check (DB path) |
| `init_room` | `(project, name, branch?, description?)` | Create a chatroom (idempotent) |
| `post_message` | `(room_id, sender, content, message_type?)` | Post a message by room_id |
| `read_messages` | `(room_id, since_id?, limit?, message_type?)` | Read messages by room_id |
| `wait_for_messages` | `(room_id, since_id, timeout?, limit?, message_type?)` | Block until new messages arrive (long-poll, max 60s); returns `timed_out=True` on timeout |
| `list_rooms` | `(project?, status?)` | List rooms (filter by project, status) |
| `list_projects` | `()` | List distinct project names |
| `archive_room` | `(project, name)` | Archive a room (keeps messages) |
| `delete_room` | `(room_id)` | Permanently delete an archived room and its messages |
| `clear_room` | `(project, name)` | Delete all messages in a room |
| `mark_read` | `(room_id, reader, last_read_message_id)` | Mark messages as read (cursor only moves forward) |
| `search` | `(query, project?)` | Search room names + message content |

## SKILL.md

The in-repo `SKILL.md` documents all MCP tools, their signatures, and usage patterns. Keep it updated when adding or modifying MCP tools.

## REST Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/status` | REST | Health check |
| `GET /api/projects` | REST | Distinct project list |
| `GET /api/chatrooms` | REST | Filtered room list (?project, ?branch, ?status) |
| `GET /api/chatrooms/{room_id}/messages` | REST | Messages for a room (?since_id, ?limit) |
| `POST /api/chatrooms/{room_id}/read` | REST | Mark messages as read (body: `{reader, last_read_message_id}`) |
| `DELETE /api/chatrooms/{room_id}` | REST | Delete an archived room (404 if not found, 422 if live) |
| `GET /api/search` | REST | Search rooms + messages (?q, ?project) |
| `GET /api/stream/chatrooms` | SSE | Room list updates (real-time, `?reader=` for unread counts) |
| `GET /api/stream/messages` | SSE | Message stream (?room_id, honors Last-Event-Id) |

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
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push to `main` and `test`, and on PRs targeting either:

| Job | Steps |
|-----|-------|
| **Backend Tests** | `uv sync --extra test` + `pytest -x` |
| **Frontend** | `bun install` + `tsc --noEmit` + `vitest run` + `vite build` |

## CD

`.github/workflows/cd.yml` triggers on push to `test` (pre-release) and `main` (stable):

- **test branch push** → publishes `{version}rc{run_number}` pre-release to PyPI + GitHub pre-release
- **main branch push** → publishes `{version}` stable to PyPI + tags `v{version}` + GitHub Release

Uses PyPI OIDC Trusted Publishing (no stored secrets). Requires one-time Trusted Publisher setup — see [RELEASING.md](RELEASING.md).

## Design Decisions

- **Single FastAPI process** — MCP + REST + SSE + static serving, one language, shared ChatService
- **MCP HTTP transport** — always-on (web UI needs server running anyway)
- **UUID room PK** — same room name allowed across projects via `UNIQUE(project, name)`
- **SQLite WAL mode** — concurrent reads (SSE polling) don't block MCP writes
- **SSE for push** — unidirectional, auto-reconnect, Last-Event-Id for resume
- **`get_all_room_stats()` batch for SSE** — 3 queries total (not 3N per-room) via batch COUNT/MAX/GROUP BY
- **`_escape_like()` for search** — escapes SQL LIKE wildcards in user input
- **No ORM** — direct sqlite3, schema is 2 tables
- **`since_id` for incremental reads** — agents poll with last-seen message ID
- **Read cursors for unread tracking** — `(room_id, reader)` PK, forward-only via `MAX()` in UPSERT, `ON DELETE CASCADE` for cleanup
- **`wait_for_messages` for agent blocking** — asyncio.Queue per waiter; `post_message` notifies via `call_soon_threadsafe(_wake_all)` (all `_waiters` access event-loop-only); zero DB reads while waiting; agents call once instead of polling in a loop; timeout capped at 60s
