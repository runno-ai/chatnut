"""ChatService — all business logic for team chatrooms."""

import sqlite3

from team_chat_mcp.db import (
    create_room,
    get_room,
    list_rooms as db_list_rooms,
    archive_room as db_archive_room,
    insert_message,
    get_messages as db_get_messages,
    delete_messages,
)


VALID_ROOM_STATUSES = {"live", "archived", "all"}


class ChatService:
    def __init__(self, db_conn: sqlite3.Connection):
        self.db = db_conn

    def init_room(self, name: str) -> dict:
        room = create_room(self.db, name)
        return room.to_dict()

    def post_message(self, room: str, sender: str, content: str) -> dict:
        room_obj = create_room(self.db, room)  # INSERT OR IGNORE — safe under concurrency
        if room_obj.status == "archived":
            raise ValueError(f"Room '{room}' is archived — cannot post messages")
        msg = insert_message(self.db, room, sender, content)
        return {"id": msg.id, "room": msg.room, "sender": msg.sender, "content": msg.content, "created_at": msg.created_at}

    def read_messages(self, room: str, since_id: int | None = None, limit: int = 100) -> dict:
        messages, has_more = db_get_messages(self.db, room, since_id=since_id, limit=limit)
        return {
            "messages": [m.to_dict() for m in messages],
            "has_more": has_more,
        }

    def list_rooms(self, status: str = "live") -> dict:
        if status not in VALID_ROOM_STATUSES:
            raise ValueError(f"Invalid status '{status}' — must be one of {VALID_ROOM_STATUSES}")
        rooms = db_list_rooms(self.db, status=status)
        return {"rooms": [r.to_dict() for r in rooms]}

    def archive_room(self, name: str) -> dict:
        room = db_archive_room(self.db, name)
        if room is None:
            raise ValueError(f"Room '{name}' not found")
        return {"name": room.name, "archived_at": room.archived_at}

    def clear_room(self, name: str) -> dict:
        room = get_room(self.db, name)
        if room is None:
            raise ValueError(f"Room '{name}' not found")
        count = delete_messages(self.db, name)
        return {"name": name, "deleted_count": count}
