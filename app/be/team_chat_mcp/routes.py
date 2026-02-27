# team_chat_mcp/routes.py
"""REST + SSE endpoints for the web UI."""

import anyio
import hashlib
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse


POLL_INTERVAL = 0.5
KEEPALIVE_INTERVAL = 15  # seconds between keepalive comments

# Thread safety: Python's sqlite3 module serializes access internally
# (SQLITE_THREADSAFE=1 default). Combined with WAL mode + busy_timeout=5000,
# concurrent reads from multiple SSE generators are safe without a Python-level lock.


async def message_event_generator(
    svc,
    room_id: str,
    last_id: int = 0,
    is_disconnected=None,
) -> AsyncIterator[dict]:
    """Async generator for SSE message events.

    Yields initial history (if last_id == 0) then polls for new messages.
    DB calls are offloaded to a thread to avoid blocking the event loop.
    """
    keepalive_counter = 0

    if last_id == 0:
        result = await anyio.to_thread.run_sync(
            lambda: svc.read_messages_by_room_id(room_id, limit=1000)
        )
        for msg in result["messages"]:
            yield {"id": str(msg["id"]), "data": json.dumps(msg)}
            last_id = msg["id"]

    while True:
        if is_disconnected and await is_disconnected():
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
            if keepalive_counter >= int(KEEPALIVE_INTERVAL / POLL_INTERVAL):
                keepalive_counter = 0
                yield {"comment": "keepalive"}
        await anyio.sleep(POLL_INTERVAL)


async def chatroom_event_generator(
    svc,
    project: str | None = None,
    branch: str | None = None,
    is_disconnected=None,
) -> AsyncIterator[dict]:
    """Async generator for SSE chatroom list events.

    Uses batch stats query (3 queries total) instead of per-room stats (3N queries).
    DB calls are offloaded to a single thread hop per poll cycle.
    """
    last_hash = ""
    keepalive_counter = 0
    while True:
        if is_disconnected and await is_disconnected():
            break

        # Single thread hop: list rooms + batch stats together
        def _fetch_rooms_with_stats() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
            result = svc.list_rooms(status="all", project=project, branch=branch)
            rooms = result["rooms"]
            room_ids = [r["id"] for r in rooms]
            stats = svc.get_all_room_stats(room_ids) if room_ids else {}
            return rooms, stats

        rooms, all_stats = await anyio.to_thread.run_sync(_fetch_rooms_with_stats)
        active = [r for r in rooms if r["status"] == "live"]
        archived = [r for r in rooms if r["status"] == "archived"]

        # Enrich rooms with stats
        for room_dict in active + archived:
            stats = all_stats.get(room_dict["id"], {})
            room_dict["messageCount"] = stats.get("message_count", 0)
            room_dict["lastMessage"] = stats.get("last_message_content")
            room_dict["lastMessageTs"] = stats.get("last_message_ts")
            room_dict["roleCounts"] = stats.get("role_counts", {})

        payload = json.dumps({"active": active, "archived": archived}, sort_keys=True)
        content_hash = hashlib.sha256(payload.encode()).hexdigest()
        if content_hash != last_hash:
            last_hash = content_hash
            keepalive_counter = 0
            yield {"data": payload}
        else:
            keepalive_counter += 1
            if keepalive_counter >= int(KEEPALIVE_INTERVAL / POLL_INTERVAL):
                keepalive_counter = 0
                yield {"comment": "keepalive"}

        await anyio.sleep(POLL_INTERVAL)


def create_router(get_service) -> APIRouter:
    """Create API router with the provided service factory."""
    router = APIRouter(prefix="/api")

    @router.get("/status")
    def status():
        return {"status": "ok"}

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

    @router.get("/search")
    def search(q: str, project: str | None = None):
        return get_service().search(q, project=project)

    @router.get("/stream/chatrooms")
    async def stream_chatrooms(
        request: Request,
        project: str | None = None,
        branch: str | None = None,
    ):
        svc = get_service()
        gen = chatroom_event_generator(
            svc, project=project, branch=branch,
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
