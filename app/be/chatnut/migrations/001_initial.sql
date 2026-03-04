-- 001_initial.sql: Base schema for team chat.

CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project TEXT NOT NULL,
    branch TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'live',
    created_at TEXT NOT NULL,
    archived_at TEXT,
    metadata TEXT,
    UNIQUE(project, name)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL REFERENCES rooms(id),
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    created_at TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, id);
