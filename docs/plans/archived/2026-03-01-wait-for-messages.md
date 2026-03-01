# wait_for_messages — Long-Polling MCP Tool

## Context

Agents using `read_messages` to wait for peer responses are busy-polling — calling it in a
tight loop with no delay, producing 30+ identical empty responses per turn. This hammers the
SQLite database and wastes API credits. The fix is a new blocking MCP tool that holds the
server-side connection open until a message actually arrives, eliminating poll storms entirely.

## Goal

Add a `wait_for_messages(room_id, since_id, timeout, limit, message_type)` MCP tool that
blocks server-side until a new message is posted to the room (or `timeout` seconds elapse),
using an in-process asyncio.Queue waiter registry with zero unnecessary DB reads while waiting.

## Architecture

When `wait_for_messages` is called, it first validates the room exists, then registers an
`asyncio.Queue` in a module-level `_waiters` dict keyed by `room_id` **before** doing the
early-exit DB check (TOCTOU-safe: any message posted after registration fires a notification).
If messages already exist it returns immediately; otherwise it blocks on `await q.get()`. When
any caller invokes `post_message`, `_notify_waiters` schedules a `_wake_all` closure onto the
event loop via `loop.call_soon_threadsafe(_wake_all)`, so all `_waiters` mutations happen
exclusively on the event loop thread — no cross-thread shared mutable state. Each woken waiter
does one DB read and returns. Timeout is capped at 60s to prevent indefinitely held connections.

## Affected Areas

- Backend: `team_chat_mcp/mcp.py`, `team_chat_mcp/app.py`, `team_chat_mcp/service.py`
- Tests: `tests/test_mcp.py`, `tests/test_wait_for_messages.py` (new)
- Config: `pyproject.toml` (pytest anyio_backend pin)

## Key Files

- `app/be/team_chat_mcp/mcp.py` — all MCP tool definitions; waiter registry + new tool here
- `app/be/team_chat_mcp/service.py` — add `room_exists()` helper used by `wait_for_messages`
- `app/be/team_chat_mcp/app.py` — lifespan wires event loop; add `set_event_loop` call
- `app/be/tests/test_wait_for_messages.py` — 13 behavioral tests (create)
- `app/be/pyproject.toml` — add `anyio_backend = "asyncio"` to pytest config

## Reusable Utilities

- `anyio.move_on_after(timeout)` — deadline-based cancellation for the blocking wait
- `anyio.to_thread.run_sync(fn)` — bridge sync DB calls from async tool context
- `asyncio.get_running_loop()` — capture event loop in lifespan for `call_soon_threadsafe`
- `loop.call_soon_threadsafe(fn)` — schedule callback onto event loop from worker thread
- `_get_service()` — existing service accessor in `mcp.py`

---

## Tasks

### Task 1: Waiter Registry + `wait_for_messages` Tool (TDD)

**Files:**
- Modify: `app/be/team_chat_mcp/mcp.py`
- Modify: `app/be/team_chat_mcp/service.py`
- Modify: `app/be/team_chat_mcp/app.py`
- Modify: `app/be/pyproject.toml`
- Modify: `app/be/tests/test_mcp.py`
- Create: `app/be/tests/test_wait_for_messages.py`

---

**Step 1: Write the failing tests**

*Update `app/be/tests/test_mcp.py`* — replace `test_all_tools_registered` to include `wait_for_messages` and standardize to `@pytest.mark.anyio`:

```python
@pytest.mark.anyio
async def test_all_tools_registered():
    """Verify all expected MCP tools are registered."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    expected = {
        "ping", "init_room", "post_message", "read_messages",
        "list_rooms", "archive_room", "delete_room", "clear_room",
        "search", "list_projects", "mark_read", "wait_for_messages",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
```

*Create `app/be/tests/test_wait_for_messages.py`*:

```python
"""Tests for wait_for_messages long-polling MCP tool."""

import asyncio

import anyio
import pytest

from team_chat_mcp import mcp as mcp_module
from team_chat_mcp.mcp import _notify_waiters, _waiters, wait_for_messages
from team_chat_mcp.service import ChatService


@pytest.fixture()
def room_id(db):
    """Create an in-memory room and wire the service factory. Cleans up on teardown."""
    svc = ChatService(db)
    mcp_module.set_service_factory(lambda: svc)
    result = svc.init_room("test-proj", "test-room")
    yield result["id"]
    _waiters.pop(result["id"], None)
    mcp_module.set_event_loop(None)


# ── Early exit (messages already exist) ──────────────────────────────────────

@pytest.mark.anyio
async def test_wait_for_messages_returns_existing(room_id):
    """Returns immediately when messages already exist after since_id."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)
    mcp_module._get_service().post_message_by_room_id(room_id, "alice", "already here")

    result = await wait_for_messages(room_id=room_id, since_id=0, timeout=5)
    assert len(result["messages"]) == 1
    assert result["messages"][0]["content"] == "already here"
    assert result["timed_out"] is False


@pytest.mark.anyio
async def test_wait_for_messages_early_exit_cleans_up_waiter(room_id):
    """Waiter queue is removed from _waiters after the early-exit path."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)
    mcp_module._get_service().post_message_by_room_id(room_id, "alice", "exists")

    await wait_for_messages(room_id=room_id, since_id=0, timeout=5)
    assert not _waiters.get(room_id)


# ── Blocking + wakeup ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_wait_for_messages_unblocks_on_cross_thread_notify(room_id):
    """Notification from a worker thread (simulating FastMCP sync tool) unblocks the waiter."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)
    svc = mcp_module._get_service()

    def _post_and_notify() -> None:
        svc.post_message_by_room_id(room_id, "bob", "arrives from thread")
        _notify_waiters(room_id)

    async def delayed_post():
        await asyncio.sleep(0.05)
        await anyio.to_thread.run_sync(_post_and_notify)

    waiter = asyncio.create_task(wait_for_messages(room_id=room_id, since_id=0, timeout=5))
    poster = asyncio.create_task(delayed_post())

    result = await waiter
    await poster

    assert result["timed_out"] is False
    assert len(result["messages"]) >= 1
    assert result["messages"][0]["content"] == "arrives from thread"


@pytest.mark.anyio
async def test_multiple_concurrent_waiters_all_wake(room_id):
    """Multiple waiters on the same room all unblock when one message is posted."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)
    svc = mcp_module._get_service()

    def _post_and_notify() -> None:
        svc.post_message_by_room_id(room_id, "alice", "broadcast")
        _notify_waiters(room_id)

    async def delayed_post():
        await asyncio.sleep(0.05)
        await anyio.to_thread.run_sync(_post_and_notify)

    waiter1 = asyncio.create_task(wait_for_messages(room_id=room_id, since_id=0, timeout=5))
    waiter2 = asyncio.create_task(wait_for_messages(room_id=room_id, since_id=0, timeout=5))
    poster = asyncio.create_task(delayed_post())

    results = await asyncio.gather(waiter1, waiter2)
    await poster

    assert all(r["timed_out"] is False for r in results)
    assert all(len(r["messages"]) >= 1 for r in results)


# ── Timeout ───────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_wait_for_messages_timeout(room_id):
    """Returns timed_out=True when no message arrives within timeout."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)

    # timeout=0.001 is deterministic with asyncio backend (cancels at first checkpoint)
    result = await wait_for_messages(room_id=room_id, since_id=0, timeout=0.001)
    assert result["timed_out"] is True
    assert result["messages"] == []
    assert result["has_more"] is False


@pytest.mark.anyio
async def test_wait_for_messages_cleans_up_waiter_on_timeout(room_id):
    """Waiter queue is removed from _waiters after timeout."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)

    await wait_for_messages(room_id=room_id, since_id=0, timeout=0.001)
    assert not _waiters.get(room_id)


@pytest.mark.anyio
async def test_wait_for_messages_timeout_capped_at_60(room_id):
    """timeout > 60 is silently capped at 60 seconds."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)
    svc = mcp_module._get_service()

    # Post a message so it returns immediately (we can't actually wait 60s in a test)
    svc.post_message_by_room_id(room_id, "alice", "hello")
    result = await wait_for_messages(room_id=room_id, since_id=0, timeout=9999)
    assert result["timed_out"] is False  # capped but still returned normally


# ── Cancellation ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_waiter_cleanup_on_cancellation(room_id):
    """Waiter queue is removed from _waiters when the task is externally cancelled."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)

    task = asyncio.create_task(wait_for_messages(room_id=room_id, since_id=0, timeout=30))
    await asyncio.sleep(0)  # yield so task can register its waiter
    assert _waiters.get(room_id)  # waiter is registered

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not _waiters.get(room_id)


# ── Error handling ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_wait_for_messages_invalid_room_id(db):
    """Raises ValueError immediately for a non-existent room_id."""
    svc = ChatService(db)
    mcp_module.set_service_factory(lambda: svc)
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)

    with pytest.raises(ValueError, match="not found"):
        await wait_for_messages(room_id="nonexistent-uuid", since_id=0, timeout=5)


@pytest.mark.anyio
async def test_wait_for_messages_negative_since_id(room_id):
    """Raises ValueError for since_id < 0."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)

    with pytest.raises(ValueError, match="since_id"):
        await wait_for_messages(room_id=room_id, since_id=-1, timeout=5)


# ── _notify_waiters edge cases ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_notify_waiters_no_loop():
    """_notify_waiters is a no-op when event loop is not set."""
    mcp_module.set_event_loop(None)
    _notify_waiters("nonexistent-room")  # must not raise


@pytest.mark.anyio
async def test_notify_waiters_loop_set_no_waiters(room_id):
    """_notify_waiters with loop set but no waiters for the room is a no-op."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)
    assert not _waiters.get(room_id)  # no waiters
    _notify_waiters(room_id)  # must not raise or create a _waiters entry
    await asyncio.sleep(0)   # let any scheduled callbacks run
    assert not _waiters.get(room_id)  # still no entry created


# ── since_id ahead of existing messages ──────────────────────────────────────

@pytest.mark.anyio
async def test_wait_for_messages_since_id_ahead_blocks(room_id):
    """When since_id is ahead of all messages, blocks until new message arrives."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)
    svc = mcp_module._get_service()

    # Post a message so there are some messages, but use a high since_id
    msg = svc.post_message_by_room_id(room_id, "alice", "old message")
    high_since_id = msg["id"] + 1000  # ahead of everything

    def _post_and_notify() -> None:
        svc.post_message_by_room_id(room_id, "bob", "new message")
        _notify_waiters(room_id)

    async def delayed_post():
        await asyncio.sleep(0.05)
        await anyio.to_thread.run_sync(_post_and_notify)

    waiter = asyncio.create_task(
        wait_for_messages(room_id=room_id, since_id=high_since_id, timeout=5)
    )
    poster = asyncio.create_task(delayed_post())
    result = await waiter
    await poster

    assert result["timed_out"] is False
    assert any(m["content"] == "new message" for m in result["messages"])
```

**Step 2: Run tests — expect FAIL**

```bash
cd /Users/tushuyang/team-chat-mcp/.worktrees/cc-140-wait-for-messages-long-polling/app/be
uv run pytest tests/test_mcp.py tests/test_wait_for_messages.py -xvs 2>&1 | head -40
```

Expected failures:
- `test_all_tools_registered` — `wait_for_messages` not in tool set
- `test_wait_*` — `ImportError: cannot import name 'wait_for_messages'`

**Step 3: Implement**

*Add to `app/be/pyproject.toml`* — new section at end:

```toml
[tool.pytest.ini_options]
anyio_backend = "asyncio"
```

*Add to `app/be/team_chat_mcp/service.py`* — after `read_messages_by_room_id`:

```python
def room_exists(self, room_id: str) -> bool:
    """Return True if a room with the given ID exists."""
    return get_room_by_id(self.db, room_id) is not None
```

*Replace `app/be/team_chat_mcp/mcp.py`* with:

```python
"""FastMCP tool definitions — thin wrappers over ChatService."""

import asyncio
import os
from collections import defaultdict
from typing import Callable

import anyio
from fastmcp import FastMCP

from team_chat_mcp.service import ChatService

mcp = FastMCP("team-chat")

DB_PATH = os.path.expanduser(os.environ.get("CHAT_DB_PATH", "~/.claude/team-chat.db"))

_service_factory: Callable[[], ChatService] | None = None

# Waiter registry: room_id → set of asyncio.Queue objects
# All mutations happen exclusively on the event loop thread (via _wake_all callback).
_waiters: defaultdict[str, set[asyncio.Queue]] = defaultdict(set)

# Running event loop — set from app_lifespan for thread-safe notification
_loop: asyncio.AbstractEventLoop | None = None


def set_service_factory(factory: Callable[[], ChatService]) -> None:
    """Set the service factory used by all MCP tool handlers."""
    global _service_factory
    _service_factory = factory


def set_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Store the running event loop for cross-thread waiter notification."""
    global _loop
    _loop = loop


def _get_service() -> ChatService:
    if _service_factory is None:
        raise RuntimeError("Service factory not set — call set_service_factory() before using MCP tools")
    return _service_factory()


def _notify_waiters(room_id: str) -> None:
    """Wake up all wait_for_messages callers blocked on room_id.

    Thread-safe: schedules _wake_all onto the event loop via call_soon_threadsafe so
    _waiters is only ever touched on the event loop thread.

    IMPORTANT: Do NOT call from a finally block — must only fire on successful inserts.
    """
    if _loop is None:
        return

    def _wake_all() -> None:
        # Runs on the event loop thread — safe to read/iterate _waiters here
        for q in list(_waiters.get(room_id, ())):
            q.put_nowait(None)

    _loop.call_soon_threadsafe(_wake_all)


@mcp.tool()
def ping() -> dict:
    """Health check — returns DB path and status."""
    return {"db_path": DB_PATH, "status": "ok"}


@mcp.tool()
def init_room(
    project: str,
    name: str,
    branch: str | None = None,
    description: str | None = None,
) -> dict:
    """Create a new chatroom. Idempotent — returns existing room if already created."""
    return _get_service().init_room(project, name, branch=branch, description=description)


@mcp.tool()
def post_message(
    room_id: str,
    sender: str,
    content: str,
    message_type: str = "message",
) -> dict:
    """Post a message to a room by room_id (from init_room). Rejects posts to archived rooms."""
    result = _get_service().post_message_by_room_id(room_id, sender, content, message_type=message_type)
    _notify_waiters(room_id)  # only reached on successful insert
    return result


@mcp.tool()
def read_messages(
    room_id: str,
    since_id: int | None = None,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Read messages from a room by room_id. Use since_id for incremental reads. Default limit 100."""
    return _get_service().read_messages_by_room_id(room_id, since_id=since_id, limit=limit, message_type=message_type)


@mcp.tool()
async def wait_for_messages(
    room_id: str,
    since_id: int,
    timeout: float = 30.0,
    limit: int = 100,
    message_type: str | None = None,
) -> dict:
    """Block until new messages arrive in room_id after since_id, or timeout seconds.

    Raises ValueError for unknown room_id or negative since_id (fail fast — don't silently
    hang 30s on a typo). Timeout is capped at 60s to prevent holding connections indefinitely.

    The queue is registered BEFORE the early-exit DB check — TOCTOU-safe: any message posted
    after registration fires _notify_waiters which puts an item in the queue, so it's picked
    up either by the early-exit check or by await q.get(), with no gap.

    Returns:
        messages: list of new messages (may be empty if woken then no new msg at since_id)
        has_more: whether more messages exist beyond limit
        timed_out: True if no message arrived within timeout; False otherwise
    """
    if since_id < 0:
        raise ValueError(f"since_id must be >= 0, got {since_id}")

    exists = await anyio.to_thread.run_sync(lambda: _get_service().room_exists(room_id))
    if not exists:
        raise ValueError(f"Room '{room_id}' not found")

    timeout = min(timeout, 60.0)

    q: asyncio.Queue = asyncio.Queue()
    # Register BEFORE the DB check — see TOCTOU note in docstring
    _waiters[room_id].add(q)
    try:
        # Early exit: return immediately if messages already exist after since_id
        existing = await anyio.to_thread.run_sync(
            lambda: _get_service().read_messages_by_room_id(
                room_id, since_id=since_id, limit=limit, message_type=message_type
            )
        )
        if existing["messages"]:
            existing["timed_out"] = False
            return existing

        # Block until _notify_waiters fires _wake_all or timeout elapses
        woken = False
        with anyio.move_on_after(timeout):
            await q.get()
            woken = True

        if not woken:
            return {"messages": [], "has_more": False, "timed_out": True}

        result = await anyio.to_thread.run_sync(
            lambda: _get_service().read_messages_by_room_id(
                room_id, since_id=since_id, limit=limit, message_type=message_type
            )
        )
        result["timed_out"] = False
        return result
    finally:
        _waiters[room_id].discard(q)
        # Clean up empty sets to avoid unbounded memory growth in long-running server
        if not _waiters[room_id]:
            _waiters.pop(room_id, None)


@mcp.tool()
def list_rooms(project: str | None = None, status: str = "live") -> dict:
    """List rooms by status. Options: 'live' (default), 'archived', 'all'. Filter by project."""
    return _get_service().list_rooms(status=status, project=project)


@mcp.tool()
def list_projects() -> dict:
    """List all distinct project names across all rooms."""
    return _get_service().list_projects()


@mcp.tool()
def archive_room(project: str, name: str) -> dict:
    """Archive a room. Sets status to 'archived', keeps all messages."""
    return _get_service().archive_room(project, name)


@mcp.tool()
def delete_room(room_id: str) -> dict:
    """Permanently delete a room and all its messages. Only archived rooms can be deleted."""
    return _get_service().delete_room(room_id)


@mcp.tool()
def clear_room(project: str, name: str) -> dict:
    """Delete all messages in a room. Keeps the room record."""
    return _get_service().clear_room(project, name)


@mcp.tool()
def search(query: str, project: str | None = None) -> dict:
    """Search room names and message content. Optionally filter by project."""
    return _get_service().search(query, project=project)


@mcp.tool()
def mark_read(
    room_id: str,
    reader: str,
    last_read_message_id: int,
) -> dict:
    """Mark messages as read up to the given message ID for a reader. Cursor only moves forward."""
    return _get_service().mark_read(room_id, reader, last_read_message_id)
```

*Modify `app/be/team_chat_mcp/app.py`* — add one line in `app_lifespan`:

```python
@asynccontextmanager
async def app_lifespan(app):
    _get_service()
    mcp_module.set_event_loop(asyncio.get_running_loop())  # ← add this line
    task = asyncio.create_task(_auto_archive_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

**Step 4: Run new tests — expect PASS**

```bash
cd /Users/tushuyang/team-chat-mcp/.worktrees/cc-140-wait-for-messages-long-polling/app/be
uv run pytest tests/test_mcp.py tests/test_wait_for_messages.py -xvs
```

Expected: all 15 tests pass (2 updated in test_mcp.py + 13 new in test_wait_for_messages.py).

**Step 5: Run full suite**

```bash
cd /Users/tushuyang/team-chat-mcp/.worktrees/cc-140-wait-for-messages-long-polling/app/be
uv run pytest -xvs
```

Expected: all tests pass, no regressions.

**Step 6: Commit**

```bash
cd /Users/tushuyang/team-chat-mcp/.worktrees/cc-140-wait-for-messages-long-polling
git add app/be/team_chat_mcp/mcp.py \
        app/be/team_chat_mcp/service.py \
        app/be/team_chat_mcp/app.py \
        app/be/pyproject.toml \
        app/be/tests/test_mcp.py \
        app/be/tests/test_wait_for_messages.py
git commit -m "feat(mcp): add wait_for_messages long-polling tool (CC-140)"
```

---

### Task 2: Documentation Update

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add `wait_for_messages` to the Tools table**

After the `read_messages` row in the Tools table, add:

```markdown
| `wait_for_messages` | `(room_id, since_id, timeout?, limit?, message_type?)` | Block until new messages arrive (long-poll, max 60s); returns `timed_out=True` on timeout |
```

**Step 2: Add to Design Decisions**

```markdown
- **`wait_for_messages` for agent blocking** — asyncio.Queue per waiter; `post_message` notifies via `call_soon_threadsafe(_wake_all)` (all `_waiters` access event-loop-only); zero DB reads while waiting; agents call once instead of polling in a loop; timeout capped at 60s
```

**Step 3: Add SKILL.md dual-update rule to CLAUDE.md**

Add a new section to `CLAUDE.md` after the Tools table (before REST Endpoints):

```markdown
## SKILL.md Dual-Update Rule

When adding or modifying MCP tools:

1. Update `SKILL.md` in this repo (the in-repo copy)
2. Update `~/.claude-chan/skills/team-chat/SKILL.md` (the global skill copy)

Both files must stay in sync. The in-repo `SKILL.md` is the source of truth; copy relevant sections to the global skill after each change.
```

**Step 4: Commit**

```bash
cd /Users/tushuyang/team-chat-mcp/.worktrees/cc-140-wait-for-messages-long-polling
git add CLAUDE.md
git commit -m "docs: add wait_for_messages to CLAUDE.md tool table and design decisions"
```

---

### Task 3: Sync SKILL.md (In-repo and Global)

**Files:**
- Modify: `SKILL.md` (in-repo)
- Modify: `~/.claude-chan/skills/team-chat/SKILL.md` (global skill)

Both files have an identical MCP Tools table. Add `wait_for_messages` to both.

**Step 1: Add to in-repo `SKILL.md`**

In the MCP Tools table (after the `read_messages` row), add:

```markdown
| `wait_for_messages(room_id, since_id, timeout?, limit?, message_type?)` | Block until new messages arrive (long-poll, max 60s); returns `timed_out=True` on timeout — **use instead of polling** |
```

**Step 2: Add the same row to `~/.claude-chan/skills/team-chat/SKILL.md`**

The global skill file lives at `~/.claude-chan/skills/team-chat/SKILL.md`. Apply the same addition to its MCP Tools table.

**Step 3: Commit in-repo SKILL.md**

```bash
cd /Users/tushuyang/team-chat-mcp/.worktrees/cc-140-wait-for-messages-long-polling
git add SKILL.md
git commit -m "docs(skill): add wait_for_messages to SKILL.md MCP tools table"
```

> **Note:** The global skill file (`~/.claude-chan/skills/team-chat/SKILL.md`) lives outside the git repo and is updated directly — no commit needed for that file.

---

## Verification

```bash
cd /Users/tushuyang/team-chat-mcp/.worktrees/cc-140-wait-for-messages-long-polling/app/be
uv run pytest -xvs
```

Expected: all tests pass, including all 13 new `test_wait_for_messages.py` tests.

Manual smoke test (server running):

```bash
# Terminal 1: start server
cd app/be && uv run uvicorn team_chat_mcp.app:app --port 8000

# Terminal 2: call wait_for_messages via MCP and expect timed_out=true
curl -s -X POST http://localhost:8000/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"wait_for_messages","arguments":{"room_id":"<a-real-room-id>","since_id":0,"timeout":1}}}' \
  | python3 -m json.tool | grep timed_out
```

Expected: `"timed_out": true` appears in the response after ~1 second.

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Backend/Architect | `timeout: int` prevents sub-second values | Changed to `float`, default `30.0` |
| Critical | Architect | No timeout cap — agents could hold connections indefinitely | Cap at `min(timeout, 60.0)` |
| Critical | Codex/Gemini/Backend/Architect | Non-existent `room_id` silently blocks for full timeout | Added `room_exists()` check + `ValueError` |
| Warning | Codex/Gemini/Architect | `_notify_waiters` iterates `_waiters` from thread — cross-thread mutation | `call_soon_threadsafe(_wake_all)` pattern; `_waiters` event-loop-only |
| Warning | All reviewers | `_waiters` accumulates empty sets; defaultdict creates entries in notify path | `finally` cleanup with `.pop()`; `.get(room_id, ())` in `_wake_all` |
| Warning | Codex/Gemini | `anyio_backend` not pinned — `move_on_after(0)` behavior varies by backend | Added `anyio_backend = "asyncio"` to `pyproject.toml` |
| Warning | QA/Architect | No test for multiple concurrent waiters — core broadcast semantic unverified | Added `test_multiple_concurrent_waiters_all_wake` |
| Warning | QA | No test for cancellation cleanup via `finally` block | Added `test_waiter_cleanup_on_cancellation` |
| Warning | QA | Test called `_notify_waiters` from async context — didn't exercise cross-thread path | Updated to use `anyio.to_thread.run_sync` in test |
| Suggestion | Architect | Forward `limit`/`message_type` for consistency with `read_messages` | Added both params |
| Suggestion | Architect | Validate `since_id >= 0` | Added check + `ValueError` |
| Suggestion | Backend | Mixed `@pytest.mark.asyncio`/`anyio` in test_mcp.py | Standardized to `@pytest.mark.anyio` |
| False alarm | Codex | `RuntimeError` from set iteration under CPython GIL | `list()` snapshot is safe; moot with `_wake_all` fix anyway |
| False alarm | Gemini | `_notify_waiters` in `finally` is a risk | Already not in finally; added inline comment |
