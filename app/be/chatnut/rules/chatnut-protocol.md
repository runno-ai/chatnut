# ChatNut Defensive Primitives

Wire-level rules for agents that interact with a chatnut room. These rules
apply regardless of which consuming skill spawned you (plan-draft,
code-review, or any other team-orchestration skill) — but **which
primitives apply depends on your role** (see §Roles).

> **Scope:** This file documents the universal primitives — things every
> chatnut agent MUST do to be safe and useful. Discussion protocol (rounds,
> facilitation, completion handshakes, engagement style) is **consumer-defined**
> by the spawning skill. See that skill's SKILL.md for protocol specifics.

## Roles

Two distinct roles touch chatnut. The primitives below apply differently
to each.

### Participant

Posts messages, may be @mentioned by peers, takes turns in a multi-round
discussion, idles between turns awaiting wakeups. Examples: domain
teammates in `/plan-draft` (Architect, Backend, Security, QA, DBA);
reviewers in any future round-based skill.

**All primitives below apply.**

### Read-only consumer

Calls `read_messages` once (or pages through with `has_more`) and emits a
final result as its Task return string, then exits. Does NOT post, does
NOT @mention or get @mentioned, does NOT idle, has NO peers or team
leader. Example: the Triage subagent in `/plan-draft` Phase 3.5.

Of the primitives below:

| Primitive | Read-only consumer |
|---|---|
| Room Discovery | Applies only if `room_id` is not already in spawn prompt (usually it is). |
| Read Before Write | N/A — no wake-up cycle. Read once at startup, then produce output. |
| @Mention dual-post | N/A — does not post. |
| Status Reporting | **Skip.** Not tracked by peers; status updates would be pointless noise. |
| Idle Is Informational | N/A — does not idle, has no peers waiting on idle signals. |
| MCP Fallback | **Override** — see that section. |

## Room Discovery

If `room_id` is not in your spawn prompt, read it from
`~/.claude/teams/{team_name}/chatroom.json`.

## Read Before Write

On every wake-up, read the full chatroom before responding:

```
read_messages(room_id="<ROOM_ID>")
```

React to everything new, not just the ping that woke you. Without this,
late messages from peers are silently missed — wire-truth, not style.

## @Mention Notifications (poster MUST dual-post)

`post_message` returns a `mentions` field listing each registered agent
referenced via `@<name>` in the message. The posting agent MUST then
`SendMessage` each mentioned agent — chatnut does NOT auto-deliver.
Without this dual-post, @mentions silently fail.

```python
result = post_message(room_id=ROOM_ID, sender="<role>", content="@security please review this")
for mention in result.get("mentions", []):
    SendMessage(to=mention["task_id"], message=f"You were @mentioned in the chatroom: {content}")
```

- `mentions` contains `[{name, task_id}]` for each registered agent
- Unregistered @mentions are silently skipped (empty list)

**Whoever creates the room** (typically the orchestrator) registers each
teammate before @mentions can resolve:

```
register_agent(room_id=ROOM_ID, agent_name="security", task_id="security")
register_agent(room_id=ROOM_ID, agent_name="architect", task_id="architect")
```

`agent_name` must match the `@name` used in messages. `task_id` is the
teammate's name (used in `SendMessage(to=...)`).

## Status Reporting (Mandatory for participants)

> **Read-only consumers skip this section.** Status is how peers and human
> observers track a participant's state across turns. A read-only consumer
> runs once and exits — there is no state worth reporting.

Report your status at every task transition via MCP:

```
update_status(room_id="<ROOM_ID>", sender="<your-role>", status="<current activity>")
```

**When to report:**
- Starting a task: `"Implementing X"`
- Blocked: `"Blocked on Y — waiting for Z"`
- Switching context: `"Moving to task B"`

Status is visible in the web UI as a sticky bar above messages. This is
how human observers track teammate state.

## Idle Is Informational

The team-system substrate emits `idle_notification` whenever a teammate
finishes a turn and is waiting for the next ping. **Idle is a wire-state,
not a completion signal.**

- Receiving an idle notification means: "this teammate's turn ended; they
  are waiting for the next message that wakes them."
- Idle does NOT mean: "this teammate is done with their work."
- Completion semantics (DONE handshake, orchestrator-declared end,
  timeout, etc.) are consumer-skill-defined. Whichever skill spawned the
  team owns the rule for what "done" means.

If you are an orchestrator waiting for teammate completion, do NOT treat
idle as completion. Read your consuming skill's SKILL.md for the actual
completion signal.

## MCP Fallback

### Participants

If `mcp__chatnut__*` tools fail or are unavailable:

1. Do NOT silently drop your findings — they are real work output
2. Send full content to the team leader via `SendMessage` with the
   `[CHATROOM FALLBACK]` prefix
3. The leader relays to the chatroom on your behalf when MCP recovers

```
SendMessage(
  to="<team-leader-name>",
  message="[CHATROOM FALLBACK] mcp__chatnut unavailable.\n\n<full content>"
)
```

### Read-only consumers (override)

A read-only consumer has no team leader to address — `SendMessage` is not
a usable channel. If `mcp__chatnut__read_messages` fails:

1. Do NOT silently drop the failure
2. Encode it in your **Task return string** — the consuming skill's
   SKILL.md defines the exact format (typically a `STATUS:` prefix on
   your final assistant message, e.g., `STATUS: CHATROOM_READ_FAILED`)
3. The consuming skill handles fallback (re-spawn, direct read by the
   orchestrator, etc.)

Do NOT call `SendMessage`. Do NOT call `mcp__chatnut__post_message`.
Failure is encoded in the return value, not in the chatroom or in DMs.

## What this file does NOT specify

The following are **consumer-skill responsibilities**, not chatnut
primitives:

- How many discussion rounds (zero, one, several, free-discuss)
- Who facilitates (orchestrator-in-room, orchestrator-silent, no orchestrator)
- How discussion ends (DONE handshake, orchestrator-declared, timeout-only,
  human-in-loop)
- Engagement style (debate-heavy "challenge, build on, dispute" vs
  independent parallel verdicts vs single-shot reviews)
- Triage / synthesis pattern (orchestrator reads chatroom directly,
  OR spawns a triage subagent, OR consumes per-teammate DM summaries)
- Lifecycle ordering (when to archive, when to teardown relative to
  artifact updates, etc.)

For each of these, read the SKILL.md of the skill that spawned you
(`/plan-draft`, `/code-review`, `/research`, etc.).
