# ChatNut Team Protocol

Rules for all agents participating in a chatnut team chatroom. These rules apply whenever you have a `room_id` and `mcp__chatnut__*` tools are available.

## Room Discovery

If `room_id` is not in your spawn prompt, read it from `~/.claude/teams/{team_name}/chatroom.json`.

## Read Before Write

On every wake-up, read the full chatroom before responding:

```
read_messages(room_id="<ROOM_ID>")
```

React to everything new, not just the ping that woke you.

## Status Reporting (Mandatory)

Report your status at every task transition via MCP:

```
update_status(room_id="<ROOM_ID>", sender="<your-role>", status="<current activity>")
```

**When to report:**
- Starting a task: `"Implementing X"`
- Blocked: `"Blocked on Y — waiting for Z"`
- Completed: `"Finished X — ready for review"`
- Switching context: `"Moving to task B"`

Status is visible in the web UI as a sticky bar above messages.

## Engagement Rules

- **Shared channel** — all teammates and the PM see every message
- **Engage with others** — respond to, challenge, or build on other teammates' points
- **Ping peers directly** — if your finding affects another role, SendMessage them
- **Tag roles** — use `@role` in chatroom posts for cross-cutting concerns
- **Disagree explicitly** — challenge assumptions, propose alternatives

## MCP Fallback

If `mcp__chatnut__*` tools fail or are unavailable:

1. Do NOT silently drop your findings
2. Send full content to the team leader via SendMessage with `[CHATROOM FALLBACK]` prefix
3. The leader will relay to the chatroom on your behalf
