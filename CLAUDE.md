# CLAUDE.md

## Project Overview

Team Chat MCP Server — SQLite-backed MCP server for agent team chatrooms. Provides structured tooling for creating rooms, posting messages, reading history, and archiving. Replaces the `chat.sh` shell script with MCP tools as the source of truth for team communication.

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.12 |
| MCP framework | fastmcp 3.x |
| Storage | SQLite (path from `CHAT_DB_PATH` env var) |
| Package manager | uv |

## Project Structure

```text
team_chat_mcp/
  __init__.py
  server.py            # MCP server entry point (FastMCP app, thin tool wrappers)
  service.py           # ChatService class — all business logic
  db.py                # SQLite schema, migrations, queries
  models.py            # Dataclasses for Room, Message
tests/
  conftest.py          # Shared fixtures (in-memory DB)
pyproject.toml
.python-version
```

## Commands

```bash
# Setup
uv sync --extra test

# Run server (stdio mode for Claude Code)
uv run fastmcp run team_chat_mcp/server.py

# Run tests
uv run pytest -xvs
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CHAT_DB_PATH` | SQLite database file path | `~/.claude/team-chat.db` |

## MCP Registration

Registered in `~/.claude.json` under `mcpServers`:

```json
{
  "team-chat": {
    "command": "uv",
    "args": ["run", "--directory", "/Users/tushuyang/team-chat-mcp", "fastmcp", "run", "team_chat_mcp/server.py"],
    "env": {
      "CHAT_DB_PATH": "~/.claude/team-chat.db"
    }
  }
}
```

## Architecture

Layered: `server.py` (tools) -> `service.py` (ChatService) -> `db.py`, `models.py`

Tools never touch the DB directly. Tests instantiate `ChatService` with an in-memory SQLite DB.

## Tools

| Tool | Purpose |
|------|---------|
| `ping` | Health check (DB path) |
| `init_room` | Create a new chatroom |
| `post_message` | Post a message to a room |
| `read_messages` | Read messages from a room, supports `since_id` for incremental reads |
| `list_rooms` | List rooms by status (live/archived/all) |
| `archive_room` | Archive a live room |
| `clear_room` | Delete all messages in a room |

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

## Design Decisions

- **`CHAT_DB_PATH` env var** — same pattern as issue-tracker-mcp for portability
- **SQLite** — zero infrastructure, single file, queryable (vs JSONL)
- **fastmcp** — minimal boilerplate, matches issue-tracker-mcp
- **No ORM** — direct sqlite3, schema is 2 tables
- **`since_id` for incremental reads** — agents poll with last-seen message ID, replaces `chat.sh since <N>` line counting
- **Separate web server** — the existing Bun/TS web UI reads from the same SQLite file; MCP server does not serve HTTP
