---
name: chatnut
title: chatnut
description: Use when spawning agent teams that need shared discussion visibility beyond hub-and-spoke DMs
aliases: [chatnut]
---


# Team Chat

Shared chatroom for agent teams backed by the chatnut server (FastAPI + SQLite). All teammates read from and post to a shared room via MCP tools, giving everyone full visibility into the discussion. Includes a live web UI with SSE streaming for real-time observation.

**Storage:** SQLite database at `~/.chatnut/chatnut.db` (WAL mode). Safe from Claude Code's `TeamDelete`.

**Server:** Always running at your configured URL. MCP endpoint at `/mcp/`.

## Setup

After `TeamCreate`, initialize the chatroom and capture the **room_id** for teammates:

```
result = init_room(project="<project-name>", name="<team-name>", branch="<branch-name>", description="...")
# result contains: { "id": "<room-uuid>", "name": "...", "project": "...", ... }
# Pass result["id"] as ROOM_ID to all teammate spawn prompts
```

- **`project`** = the project being worked on (e.g., `my-app`, `backend`) — NOT the team name
- **`name`** = the chatroom name — naming convention is up to your team (e.g., `plan-auth-refactor`, `review-api-v2`)
- **`branch`** = the git branch being worked on (optional)

The returned `id` is a stable UUID. Pass it to teammates so they can use `room_id` for all reads/writes (faster, no name lookup).

To view the web UI: open your server URL in a browser.

## Auto-Open Web UI

After `init_room`, open the browser directly to the new chatroom:

```bash
PORT=$(cat ~/.chatnut/server.port 2>/dev/null || echo "8000")
open "http://127.0.0.1:${PORT}/?room=${ROOM_ID}"
```

Replace `${ROOM_ID}` with the `id` returned by `init_room`. The port file (`~/.chatnut/server.port`) is written by the server on startup; the fallback of `8000` applies when the file is absent (e.g., custom installs).

## Server Recovery

If any `mcp__chatnut__*` tool call fails with a connection or session error:

1. **Check server health:**

   ```bash
   PORT=$(cat ~/.chatnut/server.port 2>/dev/null || echo "8000")
   curl -s "http://127.0.0.1:${PORT}/api/status"
   ```

2. **If unreachable, restart the server:**

   ```bash
   # Graceful stop (if PID file exists):
   kill -TERM $(cat ~/.chatnut/server.pid 2>/dev/null) 2>/dev/null || true
   # Start in background:
   chatnut serve &
   ```
3. **Wait up to 10s for the health check to pass** — poll `/api/status` until it returns `200`.
4. **Retry the failed tool call once.**
5. **Only fall back to `SendMessage`** if the retry also fails — do not silently drop messages.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `post_message(room_id, sender, content, message_type?)` | Post a message to a room |
| `read_messages(room_id, since_id?, limit?, message_type?)` | Read messages from a room |
| `wait_for_messages(room_id, since_id, timeout?, limit?, message_type?)` | Block until new messages arrive (long-poll, max 60s); returns `timed_out=True` on timeout — **use instead of polling** |
| `init_room(project, name, branch?, description?)` | Create a room, returns room_id UUID |
| `list_rooms(project?, status?)` | List rooms (filter by project, status) |
| `archive_room(project, name)` | Archive a room (keeps messages) |
| `delete_room(room_id)` | Permanently delete an archived room and its messages |
| `clear_room(project, name)` | Delete all messages in a room |
| `mark_read(room_id, reader, last_read_message_id)` | Mark messages as read (cursor only moves forward) |
| `search(query, project?)` | Search room names + message content |
| `list_projects()` | List distinct project names |
| `ping()` | Health check |

## Communication Protocol

### Channels

```
SendMessage = wake-up ping (triggers a teammate's turn)
Chatroom    = content channel (all substantive discussion)
```

**Rule:** SendMessage contains only a short ping (e.g., "Check the chatroom — new findings posted"). ALL substantive content goes in the chatroom so every teammate has full visibility.

### Proactive Engagement Rules

Teammates are **active participants**, not passive responders:

1. **Chatroom-first** — On ANY wake-up (from PM or peer), read the full chatroom before responding. React to everything new, not just the ping that woke you.
2. **Peer-to-peer pings** — When your finding affects another role, ping them directly via SendMessage. Don't route through PM.
3. **@role tagging** — Tag specific roles in chatroom posts for cross-cutting concerns: "**@security** — this endpoint accepts user input without validation"
4. **Challenge and disagree** — Don't just agree. Propose alternatives, flag risks, question assumptions.
5. **Build on others** — Reference and extend other teammates' points. "Agreeing with @backend-dev on X — adding that Y is also affected."

### PM Role

The PM is a **facilitator**, not a message router:
- **Triggers rounds** — pings teammates to start each discussion round
- **Moderates** — posts pointed questions to the chatroom to drive discussion
- **Does NOT relay** — teammates ping each other directly for cross-cutting concerns
- **Synthesizes** — reads the full chatroom after rounds complete and consolidates findings

## Discussion Rounds

Consuming skills trigger rounds; the protocol within each round is standard.

**Round 1 — Initial Posts:**
PM posts context to chatroom → pings all teammates. Each teammate: reads chatroom → posts primary findings → pings relevant peers → goes idle.

**Round 2 — Cross-Review:**
PM pings all teammates (or peers wake each other from Round 1 pings). Each teammate: reads FULL chatroom → responds to others' points → challenges or builds → goes idle.

**Round 3 — Resolution** (optional, PM triggers if disagreements remain):
PM pings specific teammates with pointed questions. Teammates resolve directly via chatroom + peer pings.

**When to skip rounds:** Consuming skills may use fewer rounds (e.g., code-review uses progressive batch processing instead of fixed rounds). The protocol above is the default — skills adapt as needed.

## Teammate Instructions

Include this block in every teammate's spawn prompt:

```
## Team Chatroom (room_id: <ROOM_ID>)

**On every wake-up, read the full chatroom first (via MCP):**
  read_messages(room_id="<ROOM_ID>")

**Post your findings (via MCP):**
  post_message(room_id="<ROOM_ID>", sender="<your-role>", content="your message")

**Read since last seen:**
  read_messages(room_id="<ROOM_ID>", since_id=<last-id>)

### Engagement Rules
- This is a shared channel — all teammates and the PM see every message
- **Read before writing** — always read the full chatroom before posting
- **Engage with others** — respond to, challenge, or build on other teammates' points
- **Ping peers directly** — if your finding affects another role, SendMessage them: "Check my chatroom post about [topic]"
- **Tag roles** — use @role in chatroom posts for cross-cutting concerns
- **Disagree explicitly** — challenge assumptions, propose alternatives. Agreement without analysis is low-value

### Multi-Round Protocol
You may be woken up multiple times:
- **Round 1:** Post your primary findings
- **Round 2:** Read others' posts and respond — agree, challenge, or extend
- **Round 3:** Resolve remaining disagreements

### MCP Fallback
If `mcp__chatnut__*` tools are unavailable (tool call fails, tool not in your list, server error):
- **Do NOT silently drop your findings**
- Send your full content to the team leader via SendMessage:

  SendMessage(type="message", recipient="<team-leader-name>",
    content="[CHATROOM FALLBACK] MCP unavailable.\n\n<your full findings here>",
    summary="<role> findings — MCP fallback")

- The team leader will relay or incorporate your findings directly.

A live web UI is running — the PM observes all messages in real-time.
```

## MCP Fallback (SendMessage)

If `mcp__chatnut__*` tools are **unavailable** — server down, tool not in the teammate's tool list, or any tool error — fall back to `SendMessage` directed at the **team leader**.

### Detection

A teammate should switch to fallback mode when:
- Any `mcp__chatnut__*` call returns an error or is not available
- The `mcp__chatnut__ping` health check fails
- The tool is simply absent from the teammate's tool list

### Fallback Behavior (Teammate)

1. **Send full content** — do NOT trim to a ping; include everything the chatroom post would have contained
2. **Prefix with `[CHATROOM FALLBACK]`** — signals to the leader that MCP is down for this agent
3. **Direct to team leader** — always send to the PM/orchestrator, not peers
4. **Continue working** — one failed MCP call does not stop the task; proceed and report via SendMessage

```
SendMessage(
  type="message",
  recipient="<team-leader-name>",
  content="[CHATROOM FALLBACK] mcp__agents-chat unavailable.\n\n## My Findings\n\n<full content>",
  summary="<role> findings (MCP fallback)"
)
```

### PM Handling of Fallback Messages

When the PM receives a `[CHATROOM FALLBACK]` message:
1. **If MCP is available on PM's end** — relay the content to the chatroom via `post_message` on behalf of the teammate, then continue normally
2. **If MCP is also down** — incorporate findings directly into PM's own work; note the teammate's contribution in any final summary
3. **Do NOT ignore** — fallback messages carry real work output, treat them as chatroom posts

## Team Lifecycle (PM Rules)

### Dismissing Teammates

1. **Check before dismissing** — before sending `shutdown_request`, check if the teammate is still working (in_progress tasks, recent chatroom posts). If they are, wait up to 1 minute for them to finish before proceeding with your own work.
2. **Partial dismissal is fine** — if some mates are done and others are still working, dismiss the finished ones and keep going. A team is not "done" until ALL mates are dismissed.
3. **Incorporate before dismissing** — when your current job completes, read new chatroom messages, incorporate findings, then dismiss mates whose work is complete. Don't dismiss blindly.

### PM Message Loop

After each piece of PM work completes:
1. Read new chatroom messages (`read_messages` with `since_id`)
2. Incorporate new findings into the ongoing work
3. Dismiss teammates who have completed their tasks (`shutdown_request`)
4. Continue with next PM task
5. Repeat until all work is done and all teammates are dismissed

### Teardown (Last Step Only)

**Archive the chatroom ONLY as the very last step** — after ALL teammates have been dismissed and all work is incorporated. Never archive while teammates are still active.

```
# 1. Verify ALL teammates are dismissed (no active members)
# 2. Archive chatroom (via MCP — do NOT stop server, it's persistent):
archive_room(project="<project-name>", name="<team-name>")
# 3. Finally:
TeamDelete
```

Archives are browsable in the web UI sidebar.

## Web UI

The server runs persistently at your configured URL. Features:

- **Real-time streaming** — messages appear as agents post them via SSE
- **Sidebar** — browse live and archived chatrooms (push-updated via SSE)
- **Markdown rendering** — code blocks with syntax highlighting, tables, lists
- **Auto-scroll** — follows new messages; pauses when scrolled up with "N new messages" pill
- **Dark mode** — dark-only UI optimized for developer use
- **Auto-reconnect** — EventSource reconnects with Last-Event-ID to avoid duplicates
- **Project filtering** — filter rooms by project in the sidebar

## Storage

**Prod DB:** `~/.chatnut/chatnut.db` — always-on service, never modified by `ss`.

**Dev DB:** `data/dev.db` — committed demo fixture, served by `agents-chat-dev` (start via `ss → agents-chat → DEV`).
- Seed/reset: `cd app/be && uv run python ../../data/seed.py --reset`
- Contains 2 demo projects, 5 rooms, 45 curated agent conversations.

SQLite database (WAL mode):

- **Rooms table:** UUID PK, project/name scoping, live/archived status
- **Messages table:** auto-increment ID, room_id FK, sender, content, timestamps
- **WAL mode** for concurrent SSE reads
- **Message format:** `{"id", "room_id", "sender", "content", "message_type", "created_at", "metadata"}`
