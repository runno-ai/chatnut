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
        raise ValueError(
            f"Too many subscribers for channel '{channel}' (max {MAX_SUBSCRIBERS_PER_CHANNEL})"
        )
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
