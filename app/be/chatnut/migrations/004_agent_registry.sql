CREATE TABLE IF NOT EXISTS agent_registry (
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    task_id TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    PRIMARY KEY (room_id, agent_name)
);
