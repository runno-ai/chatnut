CREATE TABLE IF NOT EXISTS room_status (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    sender TEXT NOT NULL,
    status TEXT NOT NULL CHECK(length(status) <= 500),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (room_id, sender)
);
