"""SQLite schema and migrations (versioned with ``PRAGMA user_version``)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE subjects (
        id INTEGER PRIMARY KEY,
        object TEXT NOT NULL,
        level INTEGER NOT NULL,
        characters TEXT,
        data TEXT NOT NULL,
        hidden_at TEXT,
        updated_at TEXT
    );
    CREATE TABLE assignments (
        id INTEGER PRIMARY KEY,
        subject_id INTEGER NOT NULL,
        subject_type TEXT NOT NULL,
        srs_stage INTEGER NOT NULL,
        unlocked_at TEXT,
        started_at TEXT,
        available_at TEXT,
        burned_at TEXT,
        hidden INTEGER NOT NULL DEFAULT 0,
        data TEXT NOT NULL,
        updated_at TEXT
    );
    CREATE INDEX assignments_subject ON assignments(subject_id);
    CREATE INDEX assignments_available ON assignments(available_at);
    CREATE TABLE study_materials (
        id INTEGER PRIMARY KEY,
        subject_id INTEGER NOT NULL,
        meaning_synonyms TEXT NOT NULL,
        updated_at TEXT
    );
    CREATE INDEX study_materials_subject ON study_materials(subject_id);
    CREATE TABLE user (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    );
    CREATE TABLE meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL CHECK (kind IN ('review', 'lesson_start')),
        assignment_id INTEGER NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT
    );
    """,
]


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)  # autocommit; we use explicit tx
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(f"BEGIN; {script} PRAGMA user_version = {number}; COMMIT;")
