"""ChatService — all business logic for team chatrooms."""

import re
import sqlite3
import threading

from chatnut.db import (
    create_room,
    get_room,
    get_room_by_id,
    list_rooms as db_list_rooms,
    list_projects as db_list_projects,
    archive_room as db_archive_room,
    auto_archive_stale_rooms as db_auto_archive_stale_rooms,
    delete_room as db_delete_room,
    insert_message,
    get_messages as db_get_messages,
    delete_messages,
    search_rooms_and_messages,
    get_all_room_stats as db_get_all_room_stats,
    upsert_read_cursor,
    get_read_cursor,
    get_unread_counts as db_get_unread_counts,
    upsert_room_status,
    get_room_statuses,
    delete_room_statuses,
    upsert_agent_registration,
    get_agent_registrations,
)


VALID_ROOM_STATUSES = {"live", "archived", "all"}
VALID_MESSAGE_TYPES = {"message", "system"}
_MENTION_RE = re.compile(r'(?<!\w)@([\w-]+)')


class ChatService:
    def __init__(self, db_conn: sqlite3.Connection):
        self.db = db_conn
        self.lock = threading.Lock()

    def db_path(self) -> str:
        """Return the database file path used by this service instance.

        Returns empty string for in-memory databases.
        """
        # PRAGMA database_list returns rows of (seq, name, file_path).
        # seq=0 is always the main database. Returns empty string for :memory: DBs.
        row = self.db.execute("PRAGMA database_list").fetchone()
        return row[2] if row else ""

    def init_room(
        self,
        project: str,
        name: str,
        branch: str | None = None,
        description: str | None = None,
    ) -> dict:
        # team_name is intentionally absent from the service layer — it is a
        # Claude-specific concern (writing chatroom.json to ~/.claude/teams/)
        # and is handled exclusively at the MCP tool layer in mcp.py.
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
        if message_type not in VALID_MESSAGE_TYPES:
            raise ValueError(f"Invalid message_type '{message_type}' — must be one of {VALID_MESSAGE_TYPES}")
        room_obj = get_room(self.db, project=project, name=room)
        if room_obj is None:
            raise ValueError(f"Room '{room}' in project '{project}' not found — use init_room() to create it first")
        if room_obj.status == "archived":
            raise ValueError(f"Room '{room}' in project '{project}' is archived — cannot post messages")
        mentions = self._detect_mentions(room_obj.id, content)
        msg = insert_message(self.db, room_obj.id, sender, content, message_type=message_type)
        result = msg.to_dict()
        result["mentions"] = mentions
        return result

    def post_message_by_room_id(
        self,
        room_id: str,
        sender: str,
        content: str,
        message_type: str = "message",
    ) -> dict:
        if message_type not in VALID_MESSAGE_TYPES:
            raise ValueError(f"Invalid message_type '{message_type}' — must be one of {VALID_MESSAGE_TYPES}")
        room_obj = get_room_by_id(self.db, room_id)
        if room_obj is None:
            raise ValueError(f"Room '{room_id}' not found")
        if room_obj.status == "archived":
            raise ValueError(f"Room '{room_obj.name}' is archived — cannot post messages")
        mentions = self._detect_mentions(room_id, content)
        msg = insert_message(self.db, room_id, sender, content, message_type=message_type)
        result = msg.to_dict()
        result["mentions"] = mentions
        return result

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

    def room_exists(self, room_id: str) -> bool:
        """Return True if a room with the given ID exists."""
        return get_room_by_id(self.db, room_id) is not None

    def get_all_room_stats(self, room_ids: list[str]) -> dict[str, dict]:
        """Get message stats for multiple rooms in batch (3 queries total).

        Returns a dict keyed by room_id with stats for all input room_ids,
        including rooms with no messages (zeroed stats).
        """
        return db_get_all_room_stats(self.db, room_ids)

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

    def delete_room(self, room_id: str) -> dict:
        """Permanently delete a room and all its messages.

        Only archived rooms can be deleted; attempting to delete a live room
        raises ValueError. The room must exist (raises ValueError if not found).
        """
        room_obj = get_room_by_id(self.db, room_id)
        if room_obj is None:
            raise ValueError(f"Room '{room_id}' not found")
        if room_obj.status == "live":
            raise ValueError(f"Room '{room_obj.name}' is live — archive it first before deleting")
        msg_count = db_delete_room(self.db, room_id)
        return {"id": room_id, "name": room_obj.name, "project": room_obj.project, "deleted_messages": msg_count}

    def clear_room(self, project: str, name: str) -> dict:
        room_obj = get_room(self.db, project=project, name=name)
        if room_obj is None:
            raise ValueError(f"Room '{name}' in project '{project}' not found")
        count = delete_messages(self.db, room_obj.id)
        delete_room_statuses(self.db, room_obj.id)
        return {"name": name, "project": project, "deleted_count": count}

    def auto_archive_stale_rooms(self, max_inactive_seconds: int = 7200) -> list[dict]:
        """Archive live rooms inactive for longer than max_inactive_seconds (default 2h).

        Returns list of rooms that were archived.
        """
        rooms = db_auto_archive_stale_rooms(self.db, max_inactive_seconds=max_inactive_seconds)
        return [r.to_dict() for r in rooms]

    def mark_read(self, room_id: str, reader: str, last_read_message_id: int) -> dict:
        """Mark messages as read up to the given message ID for a reader."""
        if not reader or not reader.strip():
            raise ValueError("reader must be a non-empty string")
        if last_read_message_id < 0:
            raise ValueError("last_read_message_id must be >= 0")
        room_obj = get_room_by_id(self.db, room_id)
        if room_obj is None:
            raise ValueError(f"Room '{room_id}' not found")
        upsert_read_cursor(self.db, room_id, reader, last_read_message_id)
        cursor = get_read_cursor(self.db, room_id, reader)
        return {"room_id": room_id, "reader": reader, "last_read_message_id": cursor}

    def get_unread_counts(self, room_ids: list[str], reader: str) -> dict[str, int]:
        """Get unread message counts for multiple rooms for a given reader."""
        return db_get_unread_counts(self.db, room_ids, reader)

    def update_status(self, room_id: str, sender: str, status: str) -> dict:
        """Set or update a sender's status in a room.

        Raises ValueError if the room does not exist or is archived,
        or if sender/status are empty, or if status exceeds 500 chars.
        """
        if not sender or not sender.strip():
            raise ValueError("sender must be a non-empty string")
        if not status or not status.strip():
            raise ValueError("status must be a non-empty string")
        if len(status) > 500:
            raise ValueError("status must be 500 characters or fewer")
        room_obj = get_room_by_id(self.db, room_id)
        if room_obj is None:
            raise ValueError(f"Room '{room_id}' not found")
        if room_obj.status == "archived":
            raise ValueError(f"Room '{room_obj.name}' is archived — cannot update status")
        return upsert_room_status(self.db, room_id, sender, status)

    def get_team_status(self, room_id: str) -> dict:
        """Get all current statuses for all senders in a room.

        Returns {"statuses": [...]} dict.
        Raises ValueError if the room does not exist.
        """
        room_obj = get_room_by_id(self.db, room_id)
        if room_obj is None:
            raise ValueError(f"Room '{room_id}' not found")
        return {"statuses": get_room_statuses(self.db, room_id)}

    def register_agent(self, room_id: str, agent_name: str, task_id: str) -> dict:
        """Register an agent's task_id in a room for @mention notifications.

        agent_name is normalized to lowercase (strip + lower) for case-insensitive matching.
        Must match the mention regex pattern (letters, digits, underscores, hyphens).
        """
        if not agent_name or not agent_name.strip():
            raise ValueError("agent_name must be a non-empty string")
        normalized_name = agent_name.strip().lower()
        if not re.fullmatch(r'[\w-]+', normalized_name):
            raise ValueError("agent_name must contain only letters, numbers, underscores, or hyphens")
        if not task_id or not task_id.strip():
            raise ValueError("task_id must be a non-empty string")
        room_obj = get_room_by_id(self.db, room_id)
        if room_obj is None:
            raise ValueError(f"Room '{room_id}' not found")
        if room_obj.status == "archived":
            raise ValueError(f"Room '{room_obj.name}' is archived — cannot register agents")
        return upsert_agent_registration(self.db, room_id, normalized_name, task_id.strip())

    def list_agents(self, room_id: str) -> dict:
        """List all registered agents in a room.

        Read-only — works on both live and archived rooms.
        """
        room_obj = get_room_by_id(self.db, room_id)
        if room_obj is None:
            raise ValueError(f"Room '{room_id}' not found")
        return {"agents": get_agent_registrations(self.db, room_id)}

    def _detect_mentions(self, room_id: str, content: str) -> list[dict]:
        """Parse @mentions from content and resolve against agent registry.

        Names are lowercased before lookup for case-insensitive matching.
        Unregistered @mentions are silently skipped.
        """
        names = set(n.lower() for n in _MENTION_RE.findall(content))
        if not names:
            return []
        registrations = get_agent_registrations(self.db, room_id)
        registry = {r["agent_name"]: r["task_id"] for r in registrations}
        return [{"name": name, "task_id": registry[name]} for name in sorted(names) if name in registry]

    def search(self, query: str, project: str | None = None) -> dict:
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        result = search_rooms_and_messages(self.db, query, project=project)
        return {
            "rooms": [r.to_dict() for r in result["rooms"]],
            "message_rooms": result["message_rooms"],
        }
