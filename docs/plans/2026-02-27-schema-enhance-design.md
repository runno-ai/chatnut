# Schema Enhancement + Unified Server + FE Filters/Search — Design Document

## Problem

1. Rooms have no project or branch context — they're just named strings
2. The sidebar offers no filtering or search
3. The FE server (Bun/TS) reads JSONL files, completely separate from the SQLite-backed MCP server
4. Two servers in two languages (Python + Bun/TS) for one product

## Solution

1. Enhance the schema with `project`, `branch`, `description`, `metadata`, and `message_type`
2. Switch room PK from `name` to generated UUID, with `UNIQUE(project, name)`
3. Merge everything into a single FastAPI process — MCP tools + REST + SSE + static file serving
4. Delete the Bun server entirely
5. Add sidebar filter dropdowns (project/branch) and a search box to the React SPA

## Architecture

```
Single FastAPI Process
├── /mcp/              ← FastMCP mounted (HTTP transport for agents)
├── /api/              ← REST endpoints (projects, search, chatrooms)
├── /api/stream/       ← SSE endpoints (room list, messages)
└── /*                 ← Static React SPA build (dist/)
```

```
Agents (Claude Code)                     Browser (React SPA)
 │                                        │
 │  MCP over HTTP (/mcp/)                 │  REST (/api/*)
 │                                        │  SSE  (/api/stream/*)
 ▼                                        ▼
┌──────────────────────────────────────────────┐
│              FastAPI Process                  │
│                                              │
│  mcp.py (FastMCP tools)                      │
│  routes.py (REST + SSE endpoints)            │
│       ↓              ↓                       │
│  ┌────────────────────────┐                  │
│  │     ChatService        │                  │
│  │   (shared instance)    │                  │
│  └──────────┬─────────────┘                  │
│             ↓                                │
│  ┌────────────────────────┐                  │
│  │  SQLite (WAL mode)     │                  │
│  │  ~/.claude/team-chat.db│                  │
│  └────────────────────────┘                  │
└──────────────────────────────────────────────┘
```

### Why Merge

| Aspect | Before (2 servers) | After (1 server) |
|--------|-------------------|-------------------|
| Languages | Python + TypeScript | Python only |
| Data sources | SQLite + JSONL | SQLite only |
| Processes | 2 (MCP stdio + Bun HTTP) | 1 (FastAPI HTTP) |
| Shared logic | None (duplicated queries) | `ChatService` used by MCP + REST |
| MCP transport | stdio (on-demand) | HTTP (always-on) |

Always-on is the right tradeoff — the web UI needs the server running anyway.

## Schema

### rooms

```sql
CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,                    -- generated UUID
    name TEXT NOT NULL,
    project TEXT NOT NULL,
    branch TEXT,                            -- nullable (not all rooms are branch-specific)
    description TEXT,
    status TEXT NOT NULL DEFAULT 'live',
    created_at TEXT NOT NULL,
    archived_at TEXT,
    metadata TEXT,                          -- JSON blob for extensibility
    UNIQUE(project, name)
);
```

### messages

```sql
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
```

### Key Changes from Current Schema

| Aspect | Before | After |
|--------|--------|-------|
| Room PK | `name TEXT` | `id TEXT` (UUID) |
| Room uniqueness | `name` alone | `UNIQUE(project, name)` |
| Messages FK | `room TEXT REFERENCES rooms(name)` | `room_id TEXT REFERENCES rooms(id)` |
| New room columns | — | `project`, `branch`, `description`, `metadata` |
| New message columns | — | `message_type`, `metadata` |

## MCP Tool Changes

Tools take `project: str` + `room: str` instead of bare `room: str`. Service layer resolves `(project, name)` → UUID internally.

| Tool | Old Signature | New Signature |
|------|--------------|---------------|
| `init_room` | `(name)` | `(project, name, branch?, description?)` |
| `post_message` | `(room, sender, content)` | `(project, room, sender, content, message_type?)` |
| `read_messages` | `(room, since_id?, limit?)` | `(project, room, since_id?, limit?, message_type?)` |
| `list_rooms` | `(status?)` | `(project?, status?)` |
| `archive_room` | `(name)` | `(project, name)` |
| `clear_room` | `(name)` | `(project, name)` |

`list_rooms` gets `project` as optional filter — omit to list all projects.

## Web Endpoints (FastAPI)

### REST

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/projects` | REST | Distinct project list (with branch lists per project) |
| `GET /api/chatrooms?project=X&branch=Y&status=live` | REST | Filtered room list |
| `GET /api/chatrooms/{room_id}/messages?since_id=N&limit=100` | REST | Messages for a room |
| `GET /api/search?q=term&project=X` | REST | Search room names + message content |
| `GET /api/status` | REST | Health check |

### SSE

| Endpoint | Purpose |
|----------|---------|
| `GET /api/stream/chatrooms?project=X&branch=Y` | Room list updates — pushes when rooms change |
| `GET /api/stream/messages?room_id=<uuid>` | Message stream — pushes new messages for a room |

### Push Strategy

SQLite polling replaces `fs.watch()`:
- Background task checks `MAX(id)` from messages table every 500ms
- On change detected, push new messages to connected SSE clients
- WAL mode ensures reads don't block MCP writes

## Project Structure

```
app/
  be/
    team_chat_mcp/
      __init__.py
      app.py             # FastAPI app — mounts MCP + routes + static
      mcp.py             # FastMCP tools (renamed from server.py)
      service.py         # ChatService (enhanced with project/branch)
      db.py              # SQLite schema + queries (enhanced)
      models.py          # Dataclasses (enhanced)
      routes.py          # REST + SSE endpoints
    tests/
    pyproject.toml
  fe/
    src/                 # React SPA (with sidebar enhancements)
    package.json
    vite.config.ts
    index.html
    (server/ deleted — no more Bun server)
```

## FE Sidebar Design

```
┌─────────────────────────┐
│ [Project v] [Branch v]  │   ← filter dropdowns (populated from /api/projects)
│ [🔍 Search rooms/msgs ] │   ← debounced search (300ms), hits /api/search
├─────────────────────────┤
│ ● planning-room    2m   │   ← filtered room list
│ ● dev-chat         5m   │
├─────────────────────────┤
│ ▸ Archived (3)          │
└─────────────────────────┘
```

### Filter Behavior

- **Project dropdown**: Lists all distinct projects. "All" option at top. Selecting a project populates the branch dropdown.
- **Branch dropdown**: Lists branches for the selected project. "All" option at top. Disabled when project = "All".
- **Search box**: Debounced 300ms. Searches room names + message content within current filter context. Results show matching rooms (highlighted) and rooms containing matching messages (with match count badge).
- **Room items**: Show `project` and `branch` as subtle tags when filter is set to "All".

## MCP Registration

Changes from stdio to HTTP:

```json
{
  "team-chat": {
    "url": "http://localhost:PORT/mcp/"
  }
}
```

Port managed by portless (stable URL: `http://team-chat.localhost:1355`).

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Server architecture | Single FastAPI process | One language, one codebase, shared ChatService |
| MCP transport | HTTP (mounted in FastAPI) | Always-on needed for web UI anyway |
| Room PK | UUID (generated) | Same room name allowed across projects |
| Push mechanism | SSE | Unidirectional (server→browser), auto-reconnect, FE already uses SSE |
| Search scope | Room names + message content | Covers primary use cases without noise |
| Search implementation | SQL LIKE queries | Simple, adequate for team chat volumes |
| Polling interval | 500ms | Balance between responsiveness and load |
| message_type values | `message`, `system` | Two types sufficient — system covers join/leave/task events |
| metadata format | JSON text column | Extensible without migrations |
| Bun server | Deleted | Replaced entirely by FastAPI |

## What's NOT Changing

- React SPA frontend framework (React 19, Tailwind 4, Vite)
- Single-file build (`vite-plugin-singlefile`)
- Dark theme, role colors, markdown rendering
- Message rendering components
