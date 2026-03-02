# Team Chat MCP — Design

## Summary

SQLite-backed MCP server that replaces `chat.sh` (JSONL + bash) as the source of truth for agent team chatrooms. Provides structured tools for room lifecycle and message operations. The existing Bun/TS web UI reads from the same SQLite file (migration out of scope here).

## Schema

```sql
CREATE TABLE IF NOT EXISTS rooms (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'live',  -- 'live' | 'archived'
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room TEXT NOT NULL REFERENCES rooms(name),
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room, id);
```

Timestamps are ISO 8601 UTC strings (e.g., `2026-02-27T10:00:00Z`).

## Architecture

```
server.py  ->  service.py (ChatService)  ->  db.py, models.py
   ^               ^                          ^
MCP tools    business logic            schema + queries
(thin)       (validation,              (sqlite3, no ORM)
             archiving rules)
```

Mirrors issue-tracker-mcp layering:
- `server.py`: `FastMCP("team-chat")` app, `@lru_cache(maxsize=1)` service factory, thin `@mcp.tool()` wrappers
- `service.py`: `ChatService(db_conn)` — all business logic
- `db.py`: `init_db(db_path)` returning `sqlite3.Connection`, schema as module constant, `PRAGMA journal_mode=WAL`
- `models.py`: `@dataclass` for `Room` and `Message`, with `to_dict()` methods

## Tools

| Tool | Args | Returns | Notes |
|------|------|---------|-------|
| `ping` | — | `{db_path, status}` | Health check |
| `init_room` | `name` | `{name, status, created_at}` | Idempotent — no-op if exists |
| `post_message` | `room, sender, content` | `{id, room, sender, created_at}` | Auto-creates room if missing. Rejects posts to archived rooms. |
| `read_messages` | `room, since_id?, limit?` | `{messages[], has_more}` | `since_id` for incremental polling. Default limit 100. |
| `list_rooms` | `status?` | `{rooms[]}` | Filter by `live`/`archived`/all (default: `live`) |
| `archive_room` | `name` | `{name, archived_at}` | Sets `status='archived'`, keeps messages |
| `clear_room` | `name` | `{name, deleted_count}` | Deletes messages, keeps room record |

## Behavioral Decisions

- **Post to archived room:** Rejected with error. Un-archive first if needed.
- **Room auto-create:** `post_message` creates the room if it doesn't exist (reduces friction).
- **Archiving:** Soft status change. Messages preserved, queryable forever.
- **Timestamps:** ISO 8601 UTC via `datetime.now(timezone.utc).isoformat()`.
- **`read_messages` default limit:** 100, with `has_more` boolean for pagination.
- **`init_room` idempotent:** Returns existing room if already created.
- **Storage path:** `CHAT_DB_PATH` env var, defaults to `~/.claude/team-chat.db`.
- **WAL mode:** Enables concurrent reads from web UI process.
- **No ORM:** Direct `sqlite3`, schema is 2 tables.

## Test Strategy

- `ChatService` instantiated with `init_db(":memory:")` — no file I/O in tests
- No external dependencies to mock (unlike issue-tracker's GitHub client)
- Test each tool's happy path + edge cases (archived room rejection, idempotent init, since_id pagination, etc.)

## Out of Scope

- Web UI migration (reads from same SQLite file, separate effort)
- `chat.sh` removal (done after MCP server + web UI migration both land)
- Skill updates (`SKILL.md`, `code-review/SKILL.md`, `plan-write/SKILL.md` — separate PR)
