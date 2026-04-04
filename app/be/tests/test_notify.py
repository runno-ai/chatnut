"""Tests for the notification hub."""

import asyncio

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
def _clean_hub():
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
    queues = []
    for _ in range(MAX_SUBSCRIBERS_PER_CHANNEL):
        queues.append(subscribe("flood:channel"))
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
    await anyio.sleep(0.05)
    assert not q.empty()
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
    await anyio.sleep(0.05)
    assert not q1.empty()
    assert not q2.empty()
    unsubscribe("rooms", q1)
    unsubscribe("rooms", q2)


@pytest.mark.anyio
async def test_notify_without_loop_is_noop():
    """notify() with no event loop set is a no-op, not an error."""
    # _loop is None from fixture cleanup
    notify("some:channel")  # should not raise
