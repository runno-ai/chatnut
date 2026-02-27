"""Dataclasses for Room and Message."""

from dataclasses import dataclass, asdict


@dataclass
class Room:
    id: str
    name: str
    project: str
    branch: str | None
    description: str | None
    status: str                # 'live' | 'archived'
    created_at: str
    archived_at: str | None
    metadata: str | None       # JSON blob

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    id: int
    room_id: str
    sender: str
    content: str
    message_type: str          # 'message' | 'system'
    created_at: str
    metadata: str | None       # JSON blob

    def to_dict(self) -> dict:
        return asdict(self)
