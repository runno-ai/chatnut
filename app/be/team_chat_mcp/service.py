"""ChatService — all business logic for team chatrooms."""

import sqlite3

from team_chat_mcp.db import (
    create_room,
    get_room,
    get_room_by_id,
    list_rooms as db_list_rooms,
    list_projects as db_list_projects,
    archive_room as db_archive_room,
    insert_message,
    get_messages as db_get_messages,
    delete_messages,
    search_rooms_and_messages,
    get_room_stats as db_get_room_stats,
)


VALID_ROOM_STATUSES = {"live", "archived", "all"}


class ChatService:
    def __init__(self, db_conn: sqlite3.Connection):
        self.db = db_conn

    def init_room(
        self,
        project: str,
        name: str,
        branch: str | None = None,
        description: str | None = None,
    ) -> dict:
        room = create_room(self.db, project=project, name=name, branch=branch, description=description)
        return room.to_dict()

    def post_message(
        self,
        project: str,
        room: str,
        sender: str,
        content: str,
        message_type: str = "message",
    ) -> dict:
        room_obj = create_room(self.db, project=project, name=room)
        if room_obj.status == "archived":
            raise ValueError(f"Room '{room}' in project '{project}' is archived — cannot post messages")
        msg = insert_message(self.db, room_obj.id, sender, content, message_type=message_type)
        return msg.to_dict()

    def read_messages(
        self,
        project: str,
        room: str,
        since_id: int | None = None,
        limit: int = 100,
        message_type: str | None = None,
    ) -> dict:
        room_obj = get_room(self.db, project=project, name=room)
        if room_obj is None:
            return {"messages": [], "has_more": False}
        messages, has_more = db_get_messages(
            self.db, room_obj.id, since_id=since_id, limit=limit, message_type=message_type
        )
        return {
            "messages": [m.to_dict() for m in messages],
            "has_more": has_more,
        }

    def read_messages_by_room_id(
        self,
        room_id: str,
        since_id: int | None = None,
        limit: int = 100,
        message_type: str | None = None,
    ) -> dict:
        messages, has_more = db_get_messages(
            self.db, room_id, since_id=since_id, limit=limit, message_type=message_type
        )
        return {
            "messages": [m.to_dict() for m in messages],
            "has_more": has_more,
        }

    def get_room_stats(self, room_id: str) -> dict:
        return db_get_room_stats(self.db, room_id)

    def list_rooms(self, status: str = "live", project: str | None = None, branch: str | None = None) -> dict:
        if status not in VALID_ROOM_STATUSES:
            raise ValueError(f"Invalid status '{status}' — must be one of {VALID_ROOM_STATUSES}")
        rooms = db_list_rooms(self.db, status=status, project=project, branch=branch)
        return {"rooms": [r.to_dict() for r in rooms]}

    def list_projects(self) -> dict:
        projects = db_list_projects(self.db)
        return {"projects": projects}

    def archive_room(self, project: str, name: str) -> dict:
        room = db_archive_room(self.db, project=project, name=name)
        if room is None:
            raise ValueError(f"Room '{name}' in project '{project}' not found")
        return {"name": room.name, "project": room.project, "archived_at": room.archived_at}

    def clear_room(self, project: str, name: str) -> dict:
        room_obj = get_room(self.db, project=project, name=name)
        if room_obj is None:
            raise ValueError(f"Room '{name}' in project '{project}' not found")
        count = delete_messages(self.db, room_obj.id)
        return {"name": name, "project": project, "deleted_count": count}

    def search(self, query: str, project: str | None = None) -> dict:
        result = search_rooms_and_messages(self.db, query, project=project)
        return {
            "rooms": [r.to_dict() for r in result["rooms"]],
            "message_rooms": result["message_rooms"],
        }
