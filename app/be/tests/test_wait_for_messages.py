"""Tests for wait_for_messages long-polling MCP tool."""

import asyncio

import anyio
import pytest

from team_chat_mcp import mcp as mcp_module
from team_chat_mcp.mcp import _notify_waiters, _waiters, wait_for_messages
from team_chat_mcp.service import ChatService


# wait_for_messages uses asyncio.Queue and call_soon_threadsafe — asyncio only.
@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


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

    svc.post_message_by_room_id(room_id, "alice", "hello")
    result = await wait_for_messages(room_id=room_id, since_id=0, timeout=9999)
    assert result["timed_out"] is False


# ── Cancellation ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_waiter_cleanup_on_cancellation(room_id):
    """Waiter queue is removed from _waiters when the task is externally cancelled."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)

    task = asyncio.create_task(wait_for_messages(room_id=room_id, since_id=0, timeout=30))
    # Wait until the task has registered its waiter queue in _waiters.
    # wait_for_messages does two anyio.to_thread.run_sync calls before blocking,
    # so we poll briefly until the queue appears.
    for _ in range(100):
        await asyncio.sleep(0.01)
        if _waiters.get(room_id):
            break
    assert _waiters.get(room_id), "waiter was never registered"

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
    assert not _waiters.get(room_id)
    _notify_waiters(room_id)
    await asyncio.sleep(0)
    assert not _waiters.get(room_id)


# ── since_id ahead of existing messages ──────────────────────────────────────

@pytest.mark.anyio
async def test_wait_for_messages_since_id_ahead_blocks(room_id):
    """When since_id is at the latest message id, blocks until the next new message arrives."""
    loop = asyncio.get_running_loop()
    mcp_module.set_event_loop(loop)
    svc = mcp_module._get_service()

    msg = svc.post_message_by_room_id(room_id, "alice", "old message")
    # since_id = msg["id"]: no messages have id > msg["id"] yet, so initial check returns nothing
    # and the waiter blocks. The new message (id = msg["id"]+1) satisfies id > since_id.
    blocking_since_id = msg["id"]

    def _post_and_notify() -> None:
        svc.post_message_by_room_id(room_id, "bob", "new message")
        _notify_waiters(room_id)

    async def delayed_post():
        await asyncio.sleep(0.05)
        await anyio.to_thread.run_sync(_post_and_notify)

    waiter = asyncio.create_task(
        wait_for_messages(room_id=room_id, since_id=blocking_since_id, timeout=5)
    )
    poster = asyncio.create_task(delayed_post())
    result = await waiter
    await poster

    assert result["timed_out"] is False
    assert any(m["content"] == "new message" for m in result["messages"])
