CREATE TABLE native_reply_operations (
    request_key TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
