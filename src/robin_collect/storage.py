"""Only sanitized fields and keyed identifiers are persisted in SQLite."""
import sqlite3

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, status TEXT NOT NULL,
    input_count INTEGER NOT NULL DEFAULT 0, unique_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS findings (
    finding_id TEXT PRIMARY KEY, title TEXT NOT NULL, snippet TEXT NOT NULL,
    redaction_types TEXT NOT NULL, review_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    finding_id TEXT NOT NULL REFERENCES findings(finding_id),
    query_id TEXT NOT NULL, source_id TEXT NOT NULL, collected_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, finding_id, query_id, source_id)
);
"""


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    return connection
