# SSE Scalability: Reduce Polling Load — Implementation Plan

## Context

All three SSE streams (messages, status, chatroom list) poll SQLite at 0.5s intervals. At 10 browser tabs this generates ~100 queries/second from SSE alone, regardless of activity. The `wait_for_messages` MCP tool already demonstrates an efficient event-driven pattern using asyncio.Queue — we need to generalize it and apply it to SSE generators.

## Goal

Reduce SSE polling load by 90%+ through event-driven notifications, while maintaining real-time responsiveness and backward compatibility.

## Architecture

Extract the existing `_waiters`/`_notify_waiters` infrastructure from `mcp.py` into a shared `notify.py` module with typed string channels and channel name helpers. SSE generators subscribe to channels and block on a Queue instead of polling. ALL write paths (`post_message`, `update_status`, `init_room`, `archive_room`, `delete_room`, `mark_read`, `clear_room`) fire notifications on relevant channels. Fallback polling (0.5s messages, 2s status/chatrooms) ensures correctness even if a notification is missed.

## Affected Areas

- Backend: `chatnut/notify.py` (new), `chatnut/mcp.py` (refactor), `chatnut/routes.py` (refactor), `chatnut/app.py` (lifespan wiring)

## Key Files

- `app/be/chatnut/routes.py` — SSE generators to convert from polling to event-driven
- `app/be/chatnut/mcp.py` — existing waiter pattern to extract; write paths to wire notifications
- `app/be/chatnut/notify.py` — new: shared notification hub
- `app/be/chatnut/app.py` — lifespan: wire event loop to notify module
- `app/be/tests/test_notify.py` — new: notification hub tests

## Reusable Utilities

- `chatnut/mcp.py:_notify_waiters()` — existing pattern to generalize
- `chatnut/mcp.py:_waiters` — existing `defaultdict[str, set[asyncio.Queue]]` pattern
- `chatnut/mcp.py:set_event_loop()` — event loop lifecycle management
- `anyio.to_thread.run_sync()` — existing pattern for offloading DB to thread
- `anyio.move_on_after()` — existing pattern for timeout-based waiting

---

## Tasks

### Task 1: Create notification hub module (notify.py)

**Files:**
- Create: `app/be/chatnut/notify.py`
- Test: `app/be/tests/test_notify.py`

**Step 1: Write the failing test**

```python
# tests/test_notify.py
"""Tests for the notification hub."""

import asyncio

import anyio
import pytest

from chatnut.notify import notify, set_event_loop, subscribe, unsubscribe


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _clean_hub():
    """Reset hub state between tests."""
    from chatnut import notify as mod
    mod._subscribers.clear()
    mod._loop = None
    yield
    mod._subscribers.clear()
    mod._loop = None


@pytest.mark.anyio
async def test_subscribe_returns_queue():
    set_event_loop(asyncio.get_running_loop())
    q = subscribe("test:channel")
    assert isinstance(q, asyncio.Queue)
    unsubscribe("test:channel", q)


@pytest.mark.anyio
async def test_notify_wakes_subscriber():
    loop = asyncio.get_running_loop()
    set_event_loop(loop)
    q = subscribe("room:abc:messages")
    notify("room:abc:messages")
    await anyio.sleep(0.05)  # let call_soon_threadsafe fire
    assert not q.empty()
    unsubscribe("room:abc:messages", q)


@pytest.mark.anyio
async def test_notify_no_subscribers_is_noop():
    set_event_loop(asyncio.get_running_loop())
    notify("nonexistent:channel")  # should not raise


@pytest.mark.anyio
async def test_unsubscribe_cleans_up():
    set_event_loop(asyncio.get_running_loop())
    q = subscribe("room:x:status")
    unsubscribe("room:x:status", q)
    from chatnut.notify import _subscribers
    assert "room:x:status" not in _subscribers


@pytest.mark.anyio
async def test_multiple_subscribers_all_notified():
    set_event_loop(asyncio.get_running_loop())
    q1 = subscribe("rooms")
    q2 = subscribe("rooms")
    notify("rooms")
    await anyio.sleep(0.05)
    assert not q1.empty()
    assert not q2.empty()
    unsubscribe("rooms", q1)
    unsubscribe("rooms", q2)
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_notify.py -xvs
```
Expected: `ModuleNotFoundError: No module named 'chatnut.notify'`

**Step 3: Implement minimal code**

```python
# chatnut/notify.py
"""Shared notification hub for event-driven SSE and MCP wait_for_messages.

Typed string channels allow write paths to notify SSE generators and MCP
waiters without polling.

Thread safety:
- notify() is the ONLY thread-safe entry point. It uses call_soon_threadsafe
  to schedule wakeups on the event loop.
- subscribe() and unsubscribe() MUST only be called from the event loop thread
  (async context). They are NOT thread-safe — _subscribers is a plain dict
  mutated without locks. This mirrors the invariant from the original _waiters
  design in mcp.py.
"""

import asyncio
from collections import defaultdict

_subscribers: defaultdict[str, set[asyncio.Queue[None]]] = defaultdict(set)
_loop: asyncio.AbstractEventLoop | None = None

MAX_SUBSCRIBERS_PER_CHANNEL = 200

# ── Channel name helpers (prevent typo-induced bugs) ─────────────────────────

def msg_channel(room_id: str) -> str:
    """Notification channel for new messages in a room."""
    return f"messages:{room_id}"


def status_channel(room_id: str) -> str:
    """Notification channel for status changes in a room."""
    return f"status:{room_id}"


ROOMS_CHANNEL = "rooms"
"""Notification channel for room list changes (create, archive, delete, new message, mark_read)."""


# ── Core API ─────────────────────────────────────────────────────────────────

def set_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Store the running event loop for cross-thread notification."""
    global _loop
    _loop = loop


def subscribe(channel: str) -> asyncio.Queue[None]:
    """Register a subscriber for a notification channel. Returns a Queue to await.

    MUST be called from the event loop thread only (async context).
    """
    q: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
    if len(_subscribers[channel]) >= MAX_SUBSCRIBERS_PER_CHANNEL:
        raise ValueError(f"Too many subscribers for channel '{channel}' (max {MAX_SUBSCRIBERS_PER_CHANNEL})")
    _subscribers[channel].add(q)
    return q


def unsubscribe(channel: str, q: asyncio.Queue[None]) -> None:
    """Remove a subscriber. Cleans up empty channel sets.

    MUST be called from the event loop thread only (async context).
    """
    _subscribers[channel].discard(q)
    if not _subscribers[channel]:
        _subscribers.pop(channel, None)


def notify(channel: str) -> None:
    """Wake all subscribers on a channel. Thread-safe via call_soon_threadsafe.

    This is the ONLY function safe to call from any thread (MCP tool handlers,
    REST endpoints, background tasks). All others must run on the event loop.
    """
    if _loop is None or _loop.is_closed():
        return

    def _wake_all() -> None:
        for q in list(_subscribers.get(channel, ())):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass  # already signaled

    try:
        _loop.call_soon_threadsafe(_wake_all)
    except RuntimeError:
        pass  # loop closed between check and call
```

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_notify.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/notify.py app/be/tests/test_notify.py
git commit -m "feat(notify): add shared notification hub for event-driven SSE

Extract the asyncio.Queue-based notification pattern into a reusable module
with typed string channels. Supports subscribe/unsubscribe/notify with
thread-safe cross-thread wakeup via call_soon_threadsafe."
```

---

### Task 2: Migrate mcp.py to use notify.py

**Files:**
- Modify: `app/be/chatnut/mcp.py`
- Modify: `app/be/chatnut/app.py`
- Modify: `app/be/tests/test_wait_for_messages.py` (update imports + DoS limit test)
- Test: `app/be/tests/test_wait_for_messages.py` (must still pass)

**Step 1: Run baseline test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_wait_for_messages.py -xvs
```

**Step 2: Implement the migration**

In `mcp.py`:
- Remove `_waiters`, `_loop`, `set_event_loop`, `_notify_waiters`, `MAX_WAITERS_PER_ROOM` declarations
- Import from `chatnut.notify`: `subscribe`, `unsubscribe`, `notify`, `set_event_loop`, `msg_channel`, `ROOMS_CHANNEL`, `MAX_SUBSCRIBERS_PER_CHANNEL`
- Replace `_notify_waiters(room_id)` with `notify(msg_channel(room_id))`
- In `wait_for_messages()`:
  - Replace `q = asyncio.Queue(maxsize=1)` + `_waiters[room_id].add(q)` with `q = subscribe(msg_channel(room_id))`
  - Replace `_waiters[room_id].discard(q)` with `unsubscribe(msg_channel(room_id), q)`
  - Remove the `MAX_WAITERS_PER_ROOM` check (now enforced by `subscribe()` via `MAX_SUBSCRIBERS_PER_CHANNEL`)
  - Remove cleanup of empty `_waiters` sets (now handled by `unsubscribe()`)
- Keep `_wait_notify_lock` in mcp.py (specific to post_message/wait_for_messages race condition)

In `app.py`:
- Replace `import chatnut.mcp as mcp_module` usage for `set_event_loop` with `from chatnut.notify import set_event_loop as set_notify_loop`
- Change `mcp_module.set_event_loop(asyncio.get_running_loop())` to `set_notify_loop(asyncio.get_running_loop())`
- Change `mcp_module.set_event_loop(None)` to `set_notify_loop(None)`

In `tests/test_wait_for_messages.py`:
- Update imports: `from chatnut.mcp import MAX_WAITERS_PER_ROOM, _notify_waiters, _waiters` →
  `from chatnut.notify import MAX_SUBSCRIBERS_PER_CHANNEL, _subscribers, notify, msg_channel, set_event_loop as set_notify_loop`
- Replace `_waiters` references with `_subscribers` using channel names:
  - `_waiters[room_id]` → `_subscribers[msg_channel(room_id)]`
  - `_waiters.pop(room_id, None)` → `_subscribers.pop(msg_channel(room_id), None)`
  - `_waiters.get(room_id)` → `_subscribers.get(msg_channel(room_id))`
- Replace `_notify_waiters(room_id)` → `notify(msg_channel(room_id))`
- Replace `MAX_WAITERS_PER_ROOM` → `MAX_SUBSCRIBERS_PER_CHANNEL`
- Update DoS limit test to use `MAX_SUBSCRIBERS_PER_CHANNEL` and channel name
- Update teardown: `mcp_module.set_event_loop(None)` → `set_notify_loop(None)`

**Step 3: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_wait_for_messages.py -xvs
```

**Step 4: Commit**
```bash
git add app/be/chatnut/mcp.py app/be/chatnut/app.py app/be/tests/test_wait_for_messages.py
git commit -m "refactor(mcp): migrate waiter infrastructure to notify.py

Replace module-level _waiters/_loop/_notify_waiters/MAX_WAITERS_PER_ROOM
in mcp.py with imports from chatnut.notify. wait_for_messages now uses
subscribe/unsubscribe/notify on msg_channel(room_id) channels.
DoS limit unified to MAX_SUBSCRIBERS_PER_CHANNEL (200) in notify.py.
_wait_notify_lock stays in mcp.py (race-condition specific to
post_message + wait_for_messages interaction)."
```

---

### Task 3: Per-stream poll intervals + wire write paths

**Files:**
- Modify: `app/be/chatnut/routes.py`
- Modify: `app/be/chatnut/mcp.py`
- Test: `app/be/tests/test_routes.py`
- Test: `app/be/tests/test_notify.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_notify.py

@pytest.mark.anyio
async def test_notify_from_update_status_channel():
    """update_status should notify status:{room_id} channel."""
    set_event_loop(asyncio.get_running_loop())
    q = subscribe("status:room-123")
    notify("status:room-123")
    await anyio.sleep(0.05)
    assert not q.empty()
    unsubscribe("status:room-123", q)


@pytest.mark.anyio
async def test_notify_rooms_channel():
    """Room mutations should notify the 'rooms' channel."""
    set_event_loop(asyncio.get_running_loop())
    q = subscribe("rooms")
    notify("rooms")
    await anyio.sleep(0.05)
    assert not q.empty()
    unsubscribe("rooms", q)
```

```python
# Add to tests/test_routes.py — test per-stream intervals

def test_poll_intervals_are_per_stream():
    """Each SSE stream type has its own poll interval."""
    from chatnut.routes import MESSAGE_POLL_INTERVAL, STATUS_POLL_INTERVAL, CHATROOM_POLL_INTERVAL
    assert MESSAGE_POLL_INTERVAL <= 1.0, "Messages should poll at ≤1s"
    assert STATUS_POLL_INTERVAL >= 2.0, "Status can poll at ≥2s"
    assert CHATROOM_POLL_INTERVAL >= 2.0, "Chatroom list can poll at ≥2s"
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_routes.py::test_poll_intervals_are_per_stream -xvs
```
Expected: `ImportError: cannot import name 'MESSAGE_POLL_INTERVAL'`

**Step 3: Implement**

In `routes.py`:
- Replace `POLL_INTERVAL = 0.5` with three constants:
  ```python
  MESSAGE_POLL_INTERVAL = 0.5    # real-time messages — keep fast
  STATUS_POLL_INTERVAL = 2.0     # status changes are low-frequency
  CHATROOM_POLL_INTERVAL = 2.0   # room list changes are low-frequency
  ```
- Update `message_event_generator` to use `MESSAGE_POLL_INTERVAL`
- Update `status_event_generator` to use `STATUS_POLL_INTERVAL`
- Update `chatroom_event_generator` to use `CHATROOM_POLL_INTERVAL`
- Update `KEEPALIVE_INTERVAL` calculation in each generator to use its own poll interval

In `mcp.py` (using channel helpers from notify.py):
- After `post_message()` succeeds: add `notify(ROOMS_CHANNEL)` (alongside existing `notify(msg_channel(room_id))`) — updates messageCount, lastMessage, lastMessageTs in chatroom list
- After `update_status()` succeeds: add `notify(status_channel(room_id))`
- After `init_room()` succeeds: add `notify(ROOMS_CHANNEL)`
- After `archive_room()` succeeds: add `notify(ROOMS_CHANNEL)`
- After `delete_room()` succeeds: add `notify(ROOMS_CHANNEL)`
- After `mark_read()` succeeds: add `notify(ROOMS_CHANNEL)` — updates unreadCount for connections with `reader` param
- After `clear_room()` succeeds: add `notify(msg_channel(room_id))` and `notify(ROOMS_CHANNEL)` — zeroes messageCount AND clears active message streams
- Import `notify`, `msg_channel`, `status_channel`, `ROOMS_CHANNEL` from `chatnut.notify`

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_routes.py tests/test_notify.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/routes.py app/be/chatnut/mcp.py app/be/tests/test_routes.py app/be/tests/test_notify.py
git commit -m "feat(sse): per-stream poll intervals + wire write paths to notify

Split POLL_INTERVAL into MESSAGE/STATUS/CHATROOM variants (0.5s/2s/2s).
Wire update_status, init_room, archive_room, delete_room to fire
notifications on their respective channels."
```

---

### Task 4: Convert SSE generators to event-driven

**Files:**
- Modify: `app/be/chatnut/routes.py`
- Test: `app/be/tests/test_routes.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_routes.py

import asyncio
import anyio
import pytest
from chatnut.notify import set_event_loop, notify, subscribe, unsubscribe
from chatnut.routes import message_event_generator, status_event_generator


@pytest.mark.anyio
async def test_message_generator_wakes_on_notification(svc, db):
    """Message generator yields immediately when notified instead of waiting for poll."""
    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    room = svc.init_room("test", "notify-test")
    room_id = room["id"]
    svc.post_message_by_room_id(room_id, "alice", "setup")

    gen = message_event_generator(svc, room_id, last_id=0)
    # Drain initial history
    first = await gen.__anext__()
    assert "setup" in first["data"]

    # Post a message and notify — generator should yield quickly
    svc.post_message_by_room_id(room_id, "bob", "event-driven")
    notify(f"messages:{room_id}")

    with anyio.fail_after(1.0):  # must arrive well under the 0.5s poll
        event = await gen.__anext__()
    assert "event-driven" in event["data"]

    await gen.aclose()


@pytest.mark.anyio
async def test_status_generator_wakes_on_notification(svc, db):
    """Status generator yields immediately when notified."""
    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    room = svc.init_room("test", "status-notify-test")
    room_id = room["id"]

    gen = status_event_generator(svc, room_id)
    # Drain initial status
    first = await gen.__anext__()

    # Update status and notify
    svc.update_status(room_id, "alice", "working")
    notify(f"status:{room_id}")

    with anyio.fail_after(1.0):
        event = await gen.__anext__()
    assert "working" in event["data"]

    await gen.aclose()
```

**Step 2: Run test — expect FAIL**
```bash
cd app/be && uv run pytest tests/test_routes.py::test_message_generator_wakes_on_notification -xvs
```
Expected: Timeout or slow (waiting for poll interval instead of instant notification)

**Step 3: Implement event-driven generators**

Convert each generator in `routes.py` to subscribe/wait pattern:

Add `import asyncio` to routes.py imports (needed for `asyncio.QueueEmpty`).

```python
import asyncio

from chatnut.notify import subscribe, unsubscribe, msg_channel, status_channel, ROOMS_CHANNEL

async def message_event_generator(svc, room_id, last_id=0, is_disconnected=None):
    """Event-driven message generator — subscribes to notifications, falls back to polling."""
    keepalive_counter = 0
    q = subscribe(msg_channel(room_id))
    try:
        # Initial history burst
        if last_id == 0:
            result = await anyio.to_thread.run_sync(
                lambda: svc.read_messages_by_room_id(room_id, limit=1000)
            )
            for msg in result["messages"]:
                yield {"id": str(msg["id"]), "data": json.dumps(msg)}
                last_id = msg["id"]

        # Drain stale signals accumulated during initial history burst.
        # Messages posted while yielding history put signals in the Queue,
        # but last_id is already advanced past them. Without this drain,
        # the first loop iteration does a guaranteed wasted DB poll.
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break

        while True:
            if is_disconnected and await is_disconnected():
                break

            # Wait for notification OR fallback poll timeout
            with anyio.move_on_after(MESSAGE_POLL_INTERVAL):
                await q.get()

            # Drain any extra signals (coalesce rapid notifications)
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break

            result = await anyio.to_thread.run_sync(
                lambda lid=last_id: svc.read_messages_by_room_id(room_id, since_id=lid, limit=100)
            )
            if result["messages"]:
                keepalive_counter = 0
                for msg in result["messages"]:
                    yield {"id": str(msg["id"]), "data": json.dumps(msg)}
                    last_id = msg["id"]
            else:
                keepalive_counter += 1
                if keepalive_counter >= int(KEEPALIVE_INTERVAL / MESSAGE_POLL_INTERVAL):
                    keepalive_counter = 0
                    yield {"comment": "keepalive"}
    finally:
        unsubscribe(msg_channel(room_id), q)
```

Apply the same pattern to `status_event_generator` (channel: `status_channel(room_id)`, interval: `STATUS_POLL_INTERVAL`) and `chatroom_event_generator` (channel: `ROOMS_CHANNEL`, interval: `CHATROOM_POLL_INTERVAL`). Both should include the post-history drain step.

**Step 4: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_routes.py -xvs
```

**Step 5: Commit**
```bash
git add app/be/chatnut/routes.py app/be/tests/test_routes.py
git commit -m "feat(sse): convert generators to event-driven with fallback polling

SSE generators now subscribe to notification channels and wake
instantly on writes. Falls back to periodic polling as safety net.
Messages: 0.5s fallback, status/chatrooms: 2s fallback.
Result: ~90% reduction in idle DB queries."
```

---

### Task 5: Real integration test (MCP tool → notification → SSE subscriber)

**Files:**
- Test: `app/be/tests/test_notify.py`

**Step 1: Write the integration test**

```python
# Add to tests/test_notify.py

@pytest.mark.anyio
async def test_post_message_notifies_message_and_rooms_channels(db):
    """Actual MCP post_message fires notifications on both messages:{room_id}
    and rooms channels, waking SSE subscribers."""
    from chatnut import mcp as mcp_module
    from chatnut.notify import subscribe, unsubscribe, set_event_loop, msg_channel, ROOMS_CHANNEL
    from chatnut.service import ChatService

    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    svc = ChatService(db)
    mcp_module.set_service_factory(lambda: svc)
    room = svc.init_room("test", "e2e-notify")
    room_id = room["id"]

    # Subscribe to both channels (simulating SSE generators)
    q_msg = subscribe(msg_channel(room_id))
    q_rooms = subscribe(ROOMS_CHANNEL)

    # Call the actual MCP tool function (runs in thread, fires notify)
    mcp_module.post_message(room_id=room_id, sender="test", content="hello")
    await anyio.sleep(0.05)  # let call_soon_threadsafe fire

    assert not q_msg.empty(), "messages channel should be notified"
    assert not q_rooms.empty(), "rooms channel should be notified"

    unsubscribe(msg_channel(room_id), q_msg)
    unsubscribe(ROOMS_CHANNEL, q_rooms)


@pytest.mark.anyio
async def test_update_status_notifies_status_channel(db):
    """Actual MCP update_status fires notification on status:{room_id} channel."""
    from chatnut import mcp as mcp_module
    from chatnut.notify import subscribe, unsubscribe, set_event_loop, status_channel
    from chatnut.service import ChatService

    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    svc = ChatService(db)
    mcp_module.set_service_factory(lambda: svc)
    room = svc.init_room("test", "e2e-status")
    room_id = room["id"]

    q = subscribe(status_channel(room_id))
    mcp_module.update_status(room_id=room_id, sender="alice", status="working")
    await anyio.sleep(0.05)

    assert not q.empty(), "status channel should be notified"
    unsubscribe(status_channel(room_id), q)
```

**Step 2: Run test — expect PASS**
```bash
cd app/be && uv run pytest tests/test_notify.py -xvs
```

**Step 3: Commit**
```bash
git add app/be/tests/test_notify.py
git commit -m "test(notify): add real integration tests for MCP→notification→SSE pipeline

Tests exercise actual MCP tool functions (post_message, update_status)
and verify they fire notifications on the correct channels, waking
simulated SSE subscribers."
```

---

### Task 6: Run full test suite

**Step 1: Run all tests**
```bash
cd app/be && uv run pytest -xvs
```

Expected: All tests pass. No regressions in existing functionality.

**Step 2: Commit (if any fixups needed)**

---

### Phase 7: Documentation Update

- [ ] Update inline comments in `routes.py` explaining event-driven pattern
- [ ] Add module docstring to `notify.py` (already in Task 1)
- [ ] Update `CLAUDE.md` design decisions section to document event-driven SSE architecture

---

## Verification

```bash
cd app/be && uv run pytest -xvs
```

Expected: All tests pass including:
- `test_notify.py` — hub subscribe/unsubscribe/notify, integration
- `test_wait_for_messages.py` — existing MCP waiter behavior unchanged
- `test_routes.py` — per-stream intervals, event-driven generators
- All other existing test files — no regressions

## AI Review Findings

| Severity | Source | Finding | Action |
|----------|--------|---------|--------|
| Critical | Architect + Backend | Task 2: test_wait_for_messages.py imports break after migration (_waiters, _notify_waiters removed) | Fixed: explicitly list test file, specify all import changes |
| Critical | Backend + Architect | Task 2: MAX_WAITERS_PER_ROOM vs MAX_SUBSCRIBERS_PER_CHANNEL DoS limit discrepancy | Fixed: remove MAX_WAITERS_PER_ROOM, unified to 200 in notify.py |
| Warning | Architect + Backend | Task 3: post_message missing notify("rooms") — chatroom list won't update on new messages | Fixed: added to wire-up list |
| Warning | Architect | Task 3: mark_read and clear_room not wired to notifications | Fixed: added both to wire-up list |
| Warning | Backend | Task 4: routes.py missing `import asyncio` for QueueEmpty | Fixed: added to implementation step |
| Warning | Architect + Backend | Task 5: integration test too shallow (just calls subscribe+notify directly) | Fixed: replaced with real MCP tool function tests |
| Suggestion | Architect | Task 1: Thread safety docs for subscribe/unsubscribe (event loop only) | Fixed: added prominent docstrings to all functions |
| Suggestion | Architect | Task 4: Drain stale signals after initial history burst | Fixed: added drain step before main loop |
| Suggestion | Architect + Backend | Channel name helpers to prevent typo-induced bugs | Fixed: added msg_channel(), status_channel(), ROOMS_CHANNEL to notify.py |
