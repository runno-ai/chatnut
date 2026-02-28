# Team Chat MCP — Design Document

## Problem

1. Rooms have no project or branch context — they're just named strings
2. The sidebar offers no filtering or search
3. Two servers in two languages (Python MCP stdio + Bun/TS HTTP) for one product
4. The Bun server reads JSONL files, completely separate from the SQLite-backed MCP server

## Solution

1. Enhanced schema with `project`, `branch`, `description`, `metadata`, and `message_type`
2. UUID room PK with `UNIQUE(project, name)` — same room name allowed across projects
3. Single FastAPI process — MCP tools + REST + SSE + static file serving
4. Sidebar filter dropdowns (project/branch) and a search box in the React SPA

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

### Layering

```
mcp.py / routes.py  →  service.py (ChatService)  →  db.py, models.py
   ▲         ▲               ▲                          ▲
MCP tools  REST/SSE    business logic            schema + queries
(thin)     endpoints   (validation,              (sqlite3, WAL, UUIDs)
                       archiving rules)
```

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

## MCP Tools

| Tool | Args | Returns | Notes |
|------|------|---------|-------|
| `ping` | — | `{db_path, status}` | Health check |
| `init_room` | `project, name, branch?, description?` | `{id, name, project, ...}` | Idempotent |
| `post_message` | `room_id, sender, content, message_type?` | `{id, room_id, sender, ...}` | Requires room_id (use init_room first) |
| `read_messages` | `room_id, since_id?, limit?, message_type?` | `{messages[], has_more}` | Incremental polling by room_id |
| `list_rooms` | `project?, status?` | `{rooms[]}` | Filter by project/status |
| `list_projects` | — | `{projects[]}` | Distinct project names |
| `archive_room` | `project, name` | `{name, archived_at}` | Soft archive |
| `delete_room` | `room_id` | `{id, name, project, deleted_messages}` | Permanent delete (archived rooms only) |
| `clear_room` | `project, name` | `{name, deleted_count}` | Deletes messages |
| `mark_read` | `room_id, reader, last_read_message_id` | `{room_id, reader, last_read_message_id}` | Forward-only cursor per reader |
| `search` | `query, project?` | `{rooms[], message_rooms[]}` | Room names + message content |

### Breaking Changes

- **`post_message`** now requires `room_id` instead of `project` + `room`. Rooms are no longer auto-created; use `init_room()` first to get a room_id, then pass it to `post_message()`.
- **`read_messages`** now requires `room_id` instead of `project` + `room`. This prevents accidental room creation by agents and ensures messages are always routed to the correct room.

## FE Sidebar

```
┌─────────────────────────┐
│ [Project v] [Branch v]  │   ← filter dropdowns (derived from SSE chatroom data)
│ [🔍 Search rooms/msgs ] │   ← debounced search (300ms), hits /api/search
├─────────────────────────┤
│ ● planning-room    2m   │   ← filtered room list
│ ● dev-chat         5m   │
├─────────────────────────┤
│ ▸ Archived (3)          │
└─────────────────────────┘
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Server architecture | Single FastAPI process | One language, one codebase, shared ChatService |
| MCP transport | HTTP (mounted in FastAPI) | Always-on needed for web UI anyway |
| Room PK | UUID (generated) | Same room name allowed across projects |
| Push mechanism | SSE | Unidirectional, auto-reconnect, Last-Event-Id |
| SSE efficiency | `get_all_room_stats()` batch | 3 queries total (not 3N per-room) via batch COUNT/MAX/GROUP BY |
| SSE thread safety | `anyio.to_thread.run_sync()` | Offloads sync SQLite to thread pool, single hop per poll cycle |
| Search | SQL LIKE with `_escape_like()` | Simple, adequate for team chat volumes |
| Polling interval | 500ms | Balance between responsiveness and load |
| Keepalive | 15s comment | Prevents proxy/browser timeouts on idle SSE |
| message_type | `message`, `system` | Two types sufficient for team chat |
| metadata | JSON text column | Extensible without migrations |
| Read cursors | `(room_id, reader)` PK, forward-only `MAX()` UPSERT | Per-reader unread tracking without auth |
| Unread count query | `LEFT JOIN read_cursors` + `COUNT(id > cursor)` | Single query, all message types counted |
| Bun server | Deleted | Replaced entirely by FastAPI |

## What's NOT Changing

- React SPA frontend framework (React 19, Tailwind 4, Vite)
- Single-file build (`vite-plugin-singlefile`)
- Dark theme, role colors, markdown rendering
- Message rendering components (MarkdownRenderer, MentionChip)
