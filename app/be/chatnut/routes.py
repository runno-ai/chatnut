# chatnut/routes.py
"""REST + SSE endpoints for the web UI."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import anyio
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from chatnut.notify import ROOMS_CHANNEL, msg_channel, status_channel, subscribe, unsubscribe
from chatnut.service import ChatService
from chatnut.version_check import get_cached_version_info


# Per-stream poll intervals — fallback when no notification arrives.
# Event-driven notifications wake generators instantly; these are safety nets.
MESSAGE_POLL_INTERVAL = 0.5    # real-time messages — keep fast
STATUS_POLL_INTERVAL = 2.0     # status changes are low-frequency
CHATROOM_POLL_INTERVAL = 2.0   # room list changes are low-frequency

KEEPALIVE_INTERVAL = 15  # seconds between keepalive comments

# Thread safety: Python's sqlite3 module serializes access internally
# (SQLITE_THREADSAFE=1 default). Combined with WAL mode + busy_timeout=5000,
# concurrent reads from multiple SSE generators are safe without a Python-level lock.


def _drain_queue(q: asyncio.Queue[None]) -> None:
    """Drain all pending signals from a queue (coalesce rapid notifications)."""
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


async def message_event_generator(
    svc: ChatService,
    room_id: str,
    last_id: int = 0,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[dict]:
    """Event-driven message generator — subscribes to notifications, falls back to polling.

    Yields initial history (if last_id == 0) then waits for notifications or poll timeout.
    DB calls are offloaded to a thread to avoid blocking the event loop.
    """
    keepalive_counter = 0
    q = subscribe(msg_channel(room_id))
    try:
        if last_id == 0:
            result = await anyio.to_thread.run_sync(
                lambda: svc.read_messages_by_room_id(room_id, limit=1000)
            )
            for msg in result["messages"]:
                yield {"id": str(msg["id"]), "data": json.dumps(msg)}
                last_id = msg["id"]

        # Drain stale signals accumulated during initial history burst
        _drain_queue(q)

        while True:
            if is_disconnected and await is_disconnected():
                break

            # Wait for notification OR fallback poll timeout
            with anyio.move_on_after(MESSAGE_POLL_INTERVAL):
                await q.get()

            _drain_queue(q)

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


async def status_event_generator(
    svc: ChatService,
    room_id: str,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[dict]:
    """Event-driven status generator — subscribes to notifications, falls back to polling.

    Polls for status changes and yields new data when the hash changes.
    DB calls are offloaded to a thread to avoid blocking the event loop.
    """
    last_hash = ""
    keepalive_counter = 0
    q = subscribe(status_channel(room_id))
    try:
        while True:
            if is_disconnected and await is_disconnected():
                break

            try:
                result = await anyio.to_thread.run_sync(
                    lambda: svc.get_team_status(room_id)
                )
            except ValueError:
                break
            payload = json.dumps(result, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            if content_hash != last_hash:
                last_hash = content_hash
                keepalive_counter = 0
                yield {"data": payload}
            else:
                keepalive_counter += 1
                if keepalive_counter >= int(KEEPALIVE_INTERVAL / STATUS_POLL_INTERVAL):
                    keepalive_counter = 0
                    yield {"comment": "keepalive"}

            # Wait for notification OR fallback poll timeout
            with anyio.move_on_after(STATUS_POLL_INTERVAL):
                await q.get()

            _drain_queue(q)
    finally:
        unsubscribe(status_channel(room_id), q)


async def chatroom_event_generator(
    svc: ChatService,
    project: str | None = None,
    branch: str | None = None,
    reader: str | None = None,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[dict]:
    """Event-driven chatroom list generator — subscribes to notifications, falls back to polling.

    Uses batch stats query (3 queries total) instead of per-room stats (3N queries).
    DB calls are offloaded to a single thread hop per poll cycle.
    If reader is provided, each room is enriched with unreadCount for that reader.
    """
    last_hash = ""
    keepalive_counter = 0
    q = subscribe(ROOMS_CHANNEL)
    try:
        while True:
            if is_disconnected and await is_disconnected():
                break

            # Single thread hop: list rooms + batch stats + unread counts together
            def _fetch_rooms_with_stats() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
                result = svc.list_rooms(status="all", project=project, branch=branch)
                rooms = result["rooms"]
                room_ids = [r["id"] for r in rooms]
                stats = svc.get_all_room_stats(room_ids) if room_ids else {}
                unread = svc.get_unread_counts(room_ids, reader) if reader and room_ids else {}
                return rooms, stats, unread

            rooms, all_stats, unread_counts = await anyio.to_thread.run_sync(_fetch_rooms_with_stats)
            active = [r for r in rooms if r["status"] == "live"]
            archived = [r for r in rooms if r["status"] == "archived"]

            # Enrich rooms with stats
            for room_dict in active + archived:
                stats = all_stats.get(room_dict["id"], {})
                room_dict["messageCount"] = stats.get("message_count", 0)
                room_dict["lastMessage"] = stats.get("last_message_content")
                room_dict["lastMessageTs"] = stats.get("last_message_ts")
                room_dict["roleCounts"] = stats.get("role_counts", {})
                if reader:
                    room_dict["unreadCount"] = unread_counts.get(room_dict["id"], 0)

            payload = json.dumps({"active": active, "archived": archived}, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            if content_hash != last_hash:
                last_hash = content_hash
                keepalive_counter = 0
                yield {"data": payload}
            else:
                keepalive_counter += 1
                if keepalive_counter >= int(KEEPALIVE_INTERVAL / CHATROOM_POLL_INTERVAL):
                    keepalive_counter = 0
                    yield {"comment": "keepalive"}

            # Wait for notification OR fallback poll timeout
            with anyio.move_on_after(CHATROOM_POLL_INTERVAL):
                await q.get()

            _drain_queue(q)
    finally:
        unsubscribe(ROOMS_CHANNEL, q)


class MarkReadRequest(BaseModel):
    reader: str
    last_read_message_id: int


def create_router(get_service: Callable[[], ChatService]) -> APIRouter:
    """Create API router with the provided service factory."""
    router = APIRouter(prefix="/api")

    @router.get("/status")
    def status():
        result = {"status": "ok"}
        result.update(get_cached_version_info().to_dict())
        return result

    @router.get("/projects")
    def projects():
        return get_service().list_projects()

    @router.get("/chatrooms")
    def chatrooms(
        project: str | None = None,
        branch: str | None = None,
        status: str = "live",
    ):
        try:
            return get_service().list_rooms(status=status, project=project, branch=branch)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.get("/chatrooms/{room_id}/messages")
    def room_messages(
        room_id: str,
        since_id: int | None = None,
        limit: int = 100,
        message_type: str | None = None,
    ):
        return get_service().read_messages_by_room_id(
            room_id, since_id=since_id, limit=limit, message_type=message_type
        )

    @router.delete("/chatrooms/{room_id}")
    def delete_chatroom(room_id: str) -> dict:
        try:
            return get_service().delete_room(room_id)
        except ValueError as e:
            msg = str(e)
            status = 404 if "not found" in msg else 422
            raise HTTPException(status_code=status, detail=msg) from e

    @router.post("/chatrooms/{room_id}/read")
    def mark_read(room_id: str, body: MarkReadRequest):
        try:
            return get_service().mark_read(room_id, body.reader, body.last_read_message_id)
        except ValueError as e:
            msg = str(e)
            status = 404 if "not found" in msg else 422
            raise HTTPException(status_code=status, detail=msg) from e

    @router.get("/search")
    def search(q: str, project: str | None = None):
        try:
            return get_service().search(q, project=project)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @router.get("/chatrooms/{room_id}/status")
    def room_status(room_id: str):
        svc = get_service()
        try:
            return svc.get_team_status(room_id)
        except ValueError as e:
            msg = str(e)
            status_code = 404 if "not found" in msg else 422
            raise HTTPException(status_code=status_code, detail=msg) from e

    @router.get("/stream/status")
    async def stream_status(
        request: Request,
        room_id: str = Query(..., min_length=1),
    ):
        svc = get_service()
        if not await anyio.to_thread.run_sync(lambda: svc.room_exists(room_id)):
            raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
        gen = status_event_generator(
            svc, room_id,
            is_disconnected=request.is_disconnected,
        )
        return EventSourceResponse(gen)

    @router.get("/stream/chatrooms")
    async def stream_chatrooms(
        request: Request,
        project: str | None = None,
        branch: str | None = None,
        reader: str | None = None,
    ):
        svc = get_service()
        gen = chatroom_event_generator(
            svc, project=project, branch=branch, reader=reader,
            is_disconnected=request.is_disconnected,
        )
        return EventSourceResponse(gen)

    @router.get("/stream/messages")
    async def stream_messages(
        request: Request,
        room_id: str = Query(...),
        last_event_id: str | None = Header(None, alias="Last-Event-Id"),
    ):
        svc = get_service()
        try:
            last_id = int(last_event_id) if last_event_id else 0
        except (ValueError, TypeError):
            last_id = 0
        gen = message_event_generator(
            svc, room_id, last_id=last_id,
            is_disconnected=request.is_disconnected,
        )
        return EventSourceResponse(gen)

    return router
