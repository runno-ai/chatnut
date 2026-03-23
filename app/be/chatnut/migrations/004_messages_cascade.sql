-- 004_messages_cascade.sql: Add ON DELETE CASCADE to messages FK.
-- SQLite cannot ALTER foreign keys, so we rebuild the table.
-- Columns are listed explicitly (not SELECT *) to prevent breakage on schema changes.

-- Preserve AUTOINCREMENT sequence to avoid ID reuse after row deletions
CREATE TABLE messages_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'message',
    created_at TEXT NOT NULL,
    metadata TEXT
);

INSERT INTO messages_new (id, room_id, sender, content, message_type, created_at, metadata)
    SELECT id, room_id, sender, content, message_type, created_at, metadata FROM messages;

-- Transfer AUTOINCREMENT sequence before dropping old table
INSERT OR REPLACE INTO sqlite_sequence (name, seq)
    SELECT 'messages_new', seq FROM sqlite_sequence WHERE name = 'messages';

DROP TABLE messages;

ALTER TABLE messages_new RENAME TO messages;

-- Clean up any stale 'messages_new' entry
DELETE FROM sqlite_sequence WHERE name = 'messages_new';

CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, id);
