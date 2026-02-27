# team_chat_mcp/routes.py
"""REST + SSE endpoints for the web UI."""

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Header, Query, Request
from sse_starlette.sse import EventSourceResponse


POLL_INTERVAL = 0.5
KEEPALIVE_INTERVAL = 15  # seconds between keepalive comments


async def message_event_generator(
    svc,
    room_id: str,
    last_id: int = 0,
    is_disconnected=None,
) -> AsyncIterator[dict]:
    """Async generator for SSE message events.

    Yields initial history (if last_id == 0) then polls for new messages.
    Extracted from the route handler for testability.
    """
    keepalive_counter = 0

    if last_id == 0:
        # Send full history first
        result = svc.read_messages_by_room_id(room_id, limit=1000)
        for msg in result["messages"]:
            yield {"id": str(msg["id"]), "data": json.dumps(msg)}
            last_id = msg["id"]

    # Then poll for new messages
    while True:
        if is_disconnected and await is_disconnected():
            break
        result = svc.read_messages_by_room_id(room_id, since_id=last_id, limit=100)
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
        await asyncio.sleep(POLL_INTERVAL)


async def chatroom_event_generator(
    svc,
    project: str | None = None,
    branch: str | None = None,
    is_disconnected=None,
) -> AsyncIterator[dict]:
    """Async generator for SSE chatroom list events.

    Polls room list with stats, uses content hash for change detection.
    Extracted from the route handler for testability.
    """
    last_hash = ""
    keepalive_counter = 0
    while True:
        if is_disconnected and await is_disconnected():
            break
        result = svc.list_rooms(status="all", project=project, branch=branch)
        rooms = result["rooms"]
        active = [r for r in rooms if r["status"] == "live"]
        archived = [r for r in rooms if r["status"] == "archived"]

        # Enrich with message stats via efficient DB queries (no full message fetch)
        for room_dict in active + archived:
            stats = svc.get_room_stats(room_dict["id"])
            room_dict["messageCount"] = stats["message_count"]
            room_dict["lastMessage"] = stats["last_message_content"]
            room_dict["lastMessageTs"] = stats["last_message_ts"]
            room_dict["roleCounts"] = stats["role_counts"]

        # Detect changes via content hash
        payload = json.dumps({"active": active, "archived": archived}, sort_keys=True)
        content_hash = str(hash(payload))
        if content_hash != last_hash:
            last_hash = content_hash
            keepalive_counter = 0
            yield {"data": payload}
        else:
            keepalive_counter += 1
            # Send keepalive comment to prevent proxy/browser timeouts
            if keepalive_counter >= int(KEEPALIVE_INTERVAL / POLL_INTERVAL):
                keepalive_counter = 0
                yield {"comment": "keepalive"}

        await asyncio.sleep(POLL_INTERVAL)


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
        return get_service().list_rooms(status=status, project=project, branch=branch)

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
        last_id = int(last_event_id) if last_event_id else 0
        gen = message_event_generator(
            svc, room_id, last_id=last_id,
            is_disconnected=request.is_disconnected,
        )
        return EventSourceResponse(gen)

    return router
