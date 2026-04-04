"""Tests for the notification hub."""

import asyncio
from collections.abc import Iterator

import anyio
import pytest

from chatnut.notify import (
    ROOMS_CHANNEL,
    MAX_SUBSCRIBERS_PER_CHANNEL,
    _subscribers,
    msg_channel,
    notify,
    set_event_loop,
    status_channel,
    subscribe,
    unsubscribe,
)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _clean_hub() -> Iterator[None]:
    """Reset hub state between tests."""
    from chatnut import notify as mod

    mod._subscribers.clear()
    mod._loop = None
    yield
    mod._subscribers.clear()
    mod._loop = None


# ── Channel helpers ──────────────────────────────────────────────────────────


def test_msg_channel():
    assert msg_channel("abc-123") == "messages:abc-123"


def test_status_channel():
    assert status_channel("abc-123") == "status:abc-123"


def test_rooms_channel_constant():
    assert ROOMS_CHANNEL == "rooms"


# ── Subscribe / unsubscribe ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_subscribe_returns_queue():
    set_event_loop(asyncio.get_running_loop())
    q = subscribe("test:channel")
    assert isinstance(q, asyncio.Queue)
    unsubscribe("test:channel", q)


@pytest.mark.anyio
async def test_unsubscribe_cleans_up():
    set_event_loop(asyncio.get_running_loop())
    q = subscribe("room:x:status")
    unsubscribe("room:x:status", q)
    assert "room:x:status" not in _subscribers


@pytest.mark.anyio
async def test_subscribe_max_limit():
    set_event_loop(asyncio.get_running_loop())
    queues = [subscribe("flood:channel") for _ in range(MAX_SUBSCRIBERS_PER_CHANNEL)]
    with pytest.raises(ValueError, match="Too many subscribers"):
        subscribe("flood:channel")
    for q in queues:
        unsubscribe("flood:channel", q)


# ── Notify ───────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_notify_wakes_subscriber():
    loop = asyncio.get_running_loop()
    set_event_loop(loop)
    q = subscribe("room:abc:messages")
    notify("room:abc:messages")
    with anyio.fail_after(1.0):
        await q.get()
    unsubscribe("room:abc:messages", q)


@pytest.mark.anyio
async def test_notify_no_subscribers_is_noop():
    set_event_loop(asyncio.get_running_loop())
    notify("nonexistent:channel")  # should not raise


@pytest.mark.anyio
async def test_multiple_subscribers_all_notified():
    set_event_loop(asyncio.get_running_loop())
    q1 = subscribe("rooms")
    q2 = subscribe("rooms")
    notify("rooms")
    with anyio.fail_after(1.0):
        await q1.get()
    with anyio.fail_after(1.0):
        await q2.get()
    unsubscribe("rooms", q1)
    unsubscribe("rooms", q2)


@pytest.mark.anyio
async def test_notify_without_loop_is_noop():
    """notify() with no event loop set is a no-op, not an error."""
    # _loop is None from fixture cleanup
    notify("some:channel")  # should not raise


# ── Integration tests: MCP tool → notification → SSE subscriber ──────────────


@pytest.mark.anyio
async def test_post_message_notifies_message_and_rooms_channels(db):
    """Actual MCP post_message fires notifications on both messages:{room_id}
    and rooms channels, waking SSE subscribers."""
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService

    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        room = svc.init_room("test", "e2e-notify")
        room_id = room["id"]

        q_msg = subscribe(msg_channel(room_id))
        q_rooms = subscribe(ROOMS_CHANNEL)

        mcp_module.post_message(room_id=room_id, sender="test", content="hello")
        with anyio.fail_after(1.0):
            await q_msg.get()
        with anyio.fail_after(1.0):
            await q_rooms.get()

        unsubscribe(msg_channel(room_id), q_msg)
        unsubscribe(ROOMS_CHANNEL, q_rooms)
    finally:
        mcp_module.set_service_factory(original_factory)


@pytest.mark.anyio
async def test_update_status_notifies_status_channel(db):
    """Actual MCP update_status fires notification on status:{room_id} channel."""
    from chatnut import mcp as mcp_module
    from chatnut.service import ChatService

    loop = asyncio.get_running_loop()
    set_event_loop(loop)

    svc = ChatService(db)
    original_factory = mcp_module._service_factory
    mcp_module.set_service_factory(lambda: svc)
    try:
        room = svc.init_room("test", "e2e-status")
        room_id = room["id"]

        q = subscribe(status_channel(room_id))
        mcp_module.update_status(room_id=room_id, sender="alice", status="working")
        with anyio.fail_after(1.0):
            await q.get()

        unsubscribe(status_channel(room_id), q)
    finally:
        mcp_module.set_service_factory(original_factory)
