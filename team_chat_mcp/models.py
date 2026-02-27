"""Dataclasses for Room and Message."""

from dataclasses import dataclass, asdict


@dataclass
class Room:
    name: str
    status: str            # 'live' | 'archived'
    created_at: str
    archived_at: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    id: int
    room: str
    sender: str
    content: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)
