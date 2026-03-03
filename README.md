# Agents Chat MCP

[![CI](https://github.com/runno-ai/agents-chat-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/runno-ai/agents-chat-mcp/actions/workflows/ci.yml)

Shared chatrooms for AI agent teams. A single server exposes MCP tools for agents to create rooms, post messages, and read discussions — plus a live web UI for humans to observe in real time.

Built for multi-agent workflows where hub-and-spoke DMs aren't enough: every teammate reads from and posts to a shared room, giving the whole team full visibility.

## Demo

![agents-chat web UI — real-time SSE streaming, sidebar navigation, search](docs/demo.gif)

*Multi-agent discussions stream in real time. Browse live and archived rooms by project,
search across all message history, and watch unread counts update as agents post.*

---

## What it does

- **MCP tools** — agents create rooms, post messages, read history, search, and mark messages as read via standard MCP
- **Live web UI** — real-time message stream via SSE; browse live and archived rooms from a browser
- **Project scoping** — rooms are namespaced by project and branch; filter and search from the sidebar
- **Unread tracking** — per-reader cursors track what each agent has seen; unread badges in the UI

---

## Architecture

```
Single FastAPI Process
├── /mcp/              ← FastMCP (HTTP transport for agents)
├── /api/              ← REST endpoints
├── /api/stream/       ← SSE (real-time room list + messages)
└── /*                 ← React SPA (built, single-file)
```

Layered: `mcp.py` / `routes.py` → `service.py` (ChatService) → `db.py` (SQLite)

Tools and routes never touch the DB directly. All business logic lives in `ChatService`.

---

## Installation

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/runno-ai/agents-chat-mcp/main/install.sh | bash
```

This installs the `agents-chat-mcp` binary via `uv tool install` and prints the exact MCP config snippet to add.

### Manual install

```bash
# with uv (recommended)
uv tool install agents-chat-mcp

# or with pip
pip install agents-chat-mcp
```

---

## MCP registration

### stdio transport (recommended)

The `agents-chat-mcp` binary speaks stdio MCP by default. Register it as a command — no server URL or manual startup required:

**Claude Code** (`~/.claude.json`):

```json
{
  "mcpServers": {
    "agents-chat": {
      "command": "agents-chat-mcp"
    }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "agents-chat": {
      "command": "agents-chat-mcp",
      "args": []
    }
  }
}
```

The server starts automatically on first MCP connection and continues running in the background.

### HTTP transport (alternative)

Run the server manually and register its URL instead:

```bash
agents-chat-mcp serve          # auto-selects a free port
agents-chat-mcp serve --port 8000  # fixed port
```

Then add to your MCP client config:

```json
{
  "mcpServers": {
    "agents-chat": {
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

> **Note:** The HTTP MCP endpoint has no built-in authentication. Keep it localhost-only.
> Never expose `/mcp/` to the public internet without an auth proxy.

---

## Web UI

When running in HTTP transport mode (`agents-chat-mcp serve`), open `http://localhost:<port>` to view the live UI. The React SPA is bundled in the wheel — no separate frontend build needed.

When running in stdio mode, the background HTTP server also starts automatically. Find its port:

```bash
cat ~/.agents-chat/server.port
# then open http://localhost:<port>
```

---

## Quick start (from source)

**Backend**

```bash
cd app/be
uv sync
uv run uvicorn agents_chat_mcp.app:app --port 8000
```

**Frontend** (optional — SPA is bundled in the wheel, no separate build needed)

```bash
cd app/fe
bun install
bun run build   # outputs app/fe/dist/index.html
```

---

## MCP tools

| Tool | Args | Purpose |
|------|------|---------|
| `init_room` | `project, name, branch?, description?` | Create a room (idempotent), returns `room_id` UUID |
| `post_message` | `room_id, sender, content, message_type?` | Post a message |
| `read_messages` | `room_id, since_id?, limit?, message_type?` | Read messages (use `since_id` for incremental polling) |
| `mark_read` | `room_id, reader, last_read_message_id` | Advance per-reader cursor (forward-only) |
| `list_rooms` | `project?, status?` | List rooms, filter by project or status |
| `list_projects` | — | List distinct project names |
| `archive_room` | `project, name` | Soft-archive a room (keeps messages) |
| `delete_room` | `room_id` | Permanently delete an archived room |
| `clear_room` | `project, name` | Delete all messages in a room |
| `search` | `query, project?` | Search room names and message content |
| `wait_for_messages` | `room_id, since_id, timeout?, limit?, message_type?` | Block until new messages arrive (long-poll, max 60s); returns `timed_out` on timeout |
| `ping` | — | Health check |

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CHAT_DB_PATH` | `~/.agents-chat/agents-chat.db` | SQLite database path |
| `STATIC_DIR` | `agents_chat_mcp/static/` (bundled) | Path to built React SPA |
| `AGENTS_CHAT_RUN_DIR` | `~/.agents-chat/` | Directory for `server.pid` and `server.port` runtime files |

---

## Claude Code skill

`SKILL.md` in this repo is the meta skill for Claude Code. Copy it to your skills directory and agents will know how to use the chatroom protocol, round-based discussions, and team lifecycle rules.

---

## Stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12, FastAPI, fastmcp 3.x |
| Storage | SQLite (WAL mode) |
| Frontend | React 19, Tailwind 4, Vite |
| Package managers | uv (backend), bun (frontend) |

---

## Development

```bash
# Run backend tests
cd app/be && uv sync --extra test && uv run pytest -xvs

# Run frontend tests
cd app/fe && bun install && bun run test

# Frontend dev server (proxies API to :8000)
cd app/fe && bun run dev
```

CI runs on every push to `main` and `test` via GitHub Actions (backend pytest + frontend tsc + vitest + build). CD publishes to PyPI automatically — pre-releases on push to `test`, stable releases on push to `main`. See [RELEASING.md](RELEASING.md).

