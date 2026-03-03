# Server Lifecycle & Auto-Open Browser

**Date:** 2026-03-03
**Status:** Approved

## Problem

The SKILL.md and consuming skills hardcode portless URLs (`agents-chat.localhost:1355`) for opening the web UI. General users don't have portless. The server lifecycle should be self-contained — agents need a standard way to open the chatroom browser without depending on external proxy infrastructure.

## Design

### 1. New CLI subcommand: `chatnut open [room_id]`

Primary mechanism for agents to open the web UI.

```
chatnut open                    # opens web UI home
chatnut open <room_id>          # opens directly to that room
chatnut open --url-only         # prints base URL without opening
chatnut open --url-only <id>    # prints room URL without opening
```

Implementation in `cli.py`:
- Read `~/.chatnut/server.port` to get port
- If server not running, auto-start it first (reuse `_ensure_server()`)
- Use `webbrowser.open(url)` (stdlib, cross-platform)
- `--url-only` prints URL to stdout for agents that want to use it differently

### 2. Fallback: `web_url` in MCP responses

`init_room` and `ping` responses include a `web_url` field so agents can get the URL without CLI access.

```json
{"id": "abc-123", "name": "plan-auth", ..., "web_url": "http://127.0.0.1:8321/?room=abc-123"}
```

Server reads its own port from `~/.chatnut/server.port`. When unavailable (tests, in-memory), `web_url` is omitted.

### 3. SKILL.md: replace portless references

```bash
# Before (portless-dependent):
open "http://agents-chat.localhost:1355/?room=${ROOM_ID}"

# After (standard):
chatnut open ${ROOM_ID}
```

Same update in `/code-review` and `/plan-write` skill instructions.

### 4. Remove portless scripts

Delete:
- `scripts/start_full_stack.sh` (repo)
- `~/.claude/skills/agents-chat/start-server.sh` (local)
- `~/.claude/skills/agents-chat/start-server-dev.sh` (local)

### 5. DB migration (done manually)

Copied `~/.agents-chat/agents-chat.db` → `~/.chatnut/chatnut.db`. No migration script — one-time manual operation.

## Scope

| Change | Location |
|--------|----------|
| `chatnut open` subcommand | `app/be/chatnut/cli.py` |
| `web_url` in init_room/ping | `app/be/chatnut/mcp.py` |
| Tests for both | `app/be/tests/` |
| SKILL.md update | `SKILL.md` |
| Code-review skill update | `~/.claude/skills/code-review/SKILL.md` |
| Plan-write skill update | `~/.claude/skills/plan-write/SKILL.md` |
| Delete portless scripts | `scripts/start_full_stack.sh`, `~/.claude/skills/agents-chat/start-server*.sh` |

## Out of scope

- Changing the dev DB workflow (still use `ss` locally)
- Server auto-discovery across machines (localhost only)
- Browser auto-open on server startup (only on `init_room` via agent)
