# Skill Migration: team-chat → team-chat-mcp

Post-merge migration plan for retiring the old Bun JSONL-based team-chat skill and switching to the new FastAPI/SQLite-backed team-chat-mcp server.

## Prerequisites

- PR merged to main
- Historical JSONL data already imported (796 messages, 96 rooms across runno/runno-agent-sdk/team-chat-mcp projects)

## Phase 1: Update launchd to run FastAPI instead of Bun

### Stop old server

```bash
launchctl unload ~/Library/LaunchAgents/com.portless.team-chat.plist
```

### Update plist

Edit `~/Library/LaunchAgents/com.portless.team-chat.plist`:

```xml
<key>ProgramArguments</key>
<array>
    <string>/path/to/portless</string>
    <string>team-chat</string>
    <string>/path/to/uv</string>
    <string>run</string>
    <string>--project</string>
    <string><repo-root>/app/be</string>
    <string>uvicorn</string>
    <string>team_chat_mcp.app:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>0</string>
</array>
```

Update the `project_root` if portless uses it, and adjust `PATH` to include uv.

### Start new server

```bash
launchctl load ~/Library/LaunchAgents/com.portless.team-chat.plist
```

### Verify

```bash
curl -s http://team-chat.localhost:1355/api/status
# Should return {"status": "ok"}

curl -s http://team-chat.localhost:1355/api/projects
# Should return {"projects": ["runno", "runno-agent-sdk", "team-chat-mcp"]}
```

## Phase 2: Update chat.sh

Replace JSONL file operations with HTTP calls to the running FastAPI server.

### Command mapping

| Old (JSONL) | New (HTTP/MCP) |
|---|---|
| `init <team>` | No-op (rooms auto-create on first `post_message`) |
| `post <team> <role> "msg"` | `curl -X POST /api/...` or MCP `post_message(project=<team>, room="chatroom", sender=<role>, content=<msg>)` |
| `read <team>` | `curl /api/chatrooms/{room_id}/messages` |
| `since <team> <line>` | `curl /api/chatrooms/{room_id}/messages?since_id=<id>` |
| `clear <team>` | MCP `clear_room(project=<team>, name="chatroom")` |
| `serve <team>` | Open `http://team-chat.localhost:1355` in browser (server is always running) |
| `stop <team>` | No-op (server is persistent via launchd) |
| `archive <team>` | MCP `archive_room(project=<team>, name="chatroom")` |

### New chat.sh approach

The script becomes a thin HTTP client wrapper. Each team maps to `project=<team-name>`, room name defaults to `"chatroom"`. The script:

1. Calls the FastAPI REST API for reads
2. Calls MCP tools (via HTTP transport) for writes
3. Opens the browser for `serve`

Alternatively, add REST write endpoints (`POST /api/chatrooms/{room_id}/messages`) to avoid MCP dependency in the shell script.

## Phase 3: Update SKILL.md

### Teammate instructions block

Replace bash commands with MCP tool calls:

```text
## Team Chatroom

**Post your findings (via MCP):**
  post_message(project="<team-name>", room="chatroom", sender="<your-role>", content="your message")

**Read messages (via MCP):**
  read_messages(project="<team-name>", room="chatroom")

**Read since last seen:**
  read_messages(project="<team-name>", room="chatroom", since_id=<last-id>)
```

### Storage section

```text
Storage: SQLite database at ~/.claude/team-chat.db
- Rooms table: UUID PK, project/name scoping, live/archived status
- Messages table: auto-increment ID, room_id FK, sender, content, timestamps
- WAL mode for concurrent SSE reads
```

### Remove

- References to JSONL files
- References to `~/.claude/team-chat/live/` and `~/.claude/team-chat/archived/`
- File-watching behavior descriptions

## Phase 4: Retire old components

### Delete

| Path | What |
|---|---|
| `~/.claude/skills/team-chat/web/server/index.ts` | Bun SSE server |
| `~/.claude/skills/team-chat/web/server/healthcheck.sh` | Health check script |
| `~/.claude/skills/team-chat/web/` (entire dir) | Old frontend + server + node_modules |

### Keep

| Path | What |
|---|---|
| `~/.claude/skills/team-chat/chat.sh` | Updated to use HTTP API |
| `~/.claude/skills/team-chat/SKILL.md` | Updated instructions |

### Archive old data directory

```bash
# Live dir should already be empty (no active chatrooms)
rmdir ~/.claude/team-chat/live/ 2>/dev/null

# Archived JSONL files — already imported to SQLite, keep as backup
# Move to a dated backup location after verifying DB is correct
mv ~/.claude/team-chat/archived ~/.claude/team-chat/archived-backup-$(date +%Y%m%d)
```

### Update healthcheck plist

Either update `com.portless.team-chat-healthcheck.plist` to hit the FastAPI `/api/status` endpoint, or remove it if portless handles health checks natively.

## Phase 5: Verify

1. Open `http://team-chat.localhost:1355` — should load the React SPA
2. Sidebar should show all 96 archived rooms across 3 projects
3. Click an archived room — messages should render with markdown
4. Run a test team with `chat.sh init test-migration && chat.sh post test-migration pm "hello"`
5. Verify message appears in the web UI
6. Archive: `chat.sh archive test-migration` — room moves to archived in sidebar
7. MCP tools work: `post_message`, `read_messages`, `list_rooms` via MCP HTTP transport

## API Shape Differences

The new server has a different message/room schema. Consuming skills that read messages need updating:

| Field | Old | New |
|---|---|---|
| Sender | `from` | `sender` |
| Content | `msg` | `content` |
| Timestamp | `ts` | `created_at` |
| Message ID | line number | `id` (auto-increment integer) |
| Room ID | name string | UUID string |

Skills that call `chat.sh read` and parse `{"ts","from","msg"}` will need to parse `{"id","room_id","sender","content","message_type","created_at","metadata"}` instead.

## Rollback

If issues arise, revert the launchd plist to point back at the Bun server. The old JSONL files are untouched (we only read them during import). The Bun server continues to work as before.
