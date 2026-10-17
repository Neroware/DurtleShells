"""Typed queries over the local cache. Everything here works offline."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..api.models import Assignment, StudyMaterial, Subject, User
from ..timefmt import iso, parse, utcnow

SRS_GROUPS = (
    ("Apprentice", range(1, 5)),
    ("Guru", range(5, 7)),
    ("Master", range(7, 8)),
    ("Enlightened", range(8, 9)),
    ("Burned", range(9, 10)),
)


@dataclass
class OutboxEntry:
    id: int
    kind: str  # "review" | "lesson_start"
    assignment_id: int
    payload: dict[str, Any]
    created_at: str
    attempts: int
    last_error: str | None


class Repo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._subject_cache: dict[int, Subject] = {}

    # ---- upserts -----------------------------------------------------------

    def upsert_subjects(self, resources: Iterable[dict[str, Any]]) -> int:
        rows = [
            (r["id"], r["object"], r["data"].get("level", 0), r["data"].get("characters"),
             json.dumps(r["data"], ensure_ascii=False), r["data"].get("hidden_at"),
             r.get("data_updated_at"))
            for r in resources
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO subjects VALUES (?, ?, ?, ?, ?, ?, ?)", rows
            )
        for row in rows:
            self._subject_cache.pop(row[0], None)
        return len(rows)

    def upsert_assignments(self, resources: Iterable[dict[str, Any]]) -> int:
        rows = []
        for r in resources:
            d = r["data"]
            rows.append((
                r["id"], d["subject_id"], d["subject_type"], d.get("srs_stage", 0),
                d.get("unlocked_at"), d.get("started_at"), d.get("available_at"),
                d.get("burned_at"), int(bool(d.get("hidden"))), json.dumps(d, ensure_ascii=False),
                r.get("data_updated_at"),
            ))
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
        return len(rows)

    def upsert_study_materials(self, resources: Iterable[dict[str, Any]]) -> int:
        rows = [
            (r["id"], r["data"]["subject_id"],
             json.dumps(r["data"].get("meaning_synonyms") or [], ensure_ascii=False),
             r.get("data_updated_at"))
            for r in resources
        ]
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO study_materials VALUES (?, ?, ?, ?)", rows)
        return len(rows)

    def set_user(self, user_data: dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM user")
            self.conn.execute(
                "INSERT INTO user VALUES (?, ?)",
                (user_data["id"], json.dumps(user_data, ensure_ascii=False)),
            )

    # ---- meta --------------------------------------------------------------

    def meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str | None) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    # ---- reads -------------------------------------------------------------

    def user(self) -> User | None:
        row = self.conn.execute("SELECT data FROM user").fetchone()
        return User.from_data(json.loads(row[0])) if row else None

    def subject(self, subject_id: int) -> Subject | None:
        if subject_id in self._subject_cache:
            return self._subject_cache[subject_id]
        row = self.conn.execute(
            "SELECT id, object, data FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if not row:
            return None
        subject = Subject.from_data(row["id"], row["object"], json.loads(row["data"]))
        self._subject_cache[subject_id] = subject
        return subject

    def subjects(self, ids: Iterable[int]) -> dict[int, Subject]:
        result = {}
        for sid in ids:
            s = self.subject(sid)
            if s is not None:
                result[sid] = s
        return result

    def practice_subject_ids(self, max_level: int) -> list[int]:
        """Vocabulary ids up to ``max_level`` for the flick practice screen."""
        rows = self.conn.execute(
            """SELECT id FROM subjects
               WHERE object = 'vocabulary' AND hidden_at IS NULL
                 AND level <= ? ORDER BY id""",
            (max_level,),
        ).fetchall()
        return [r[0] for r in rows]

    def subject_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]

    def assignment(self, assignment_id: int) -> Assignment | None:
        row = self.conn.execute("SELECT id, data FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        return Assignment.from_data(row["id"], json.loads(row["data"])) if row else None

    def synonyms(self, subject_id: int) -> list[str]:
        row = self.conn.execute(
            "SELECT meaning_synonyms FROM study_materials WHERE subject_id = ?", (subject_id,)
        ).fetchone()
        return json.loads(row[0]) if row else []

    def _assignments(self, where: str, params: tuple[Any, ...] = ()) -> list[Assignment]:
        rows = self.conn.execute(
            f"""SELECT a.id, a.data FROM assignments a
                JOIN subjects s ON s.id = a.subject_id
                WHERE s.hidden_at IS NULL AND a.hidden = 0 AND {where}
                ORDER BY a.available_at, a.id""",
            params,
        ).fetchall()
        return [Assignment.from_data(r["id"], json.loads(r["data"])) for r in rows]

    def available_reviews(self, now: datetime | None = None) -> list[Assignment]:
        now_s = iso(now or utcnow())
        return self._assignments(
            """a.started_at IS NOT NULL AND a.burned_at IS NULL
               AND a.available_at IS NOT NULL AND a.available_at <= ?
               AND a.id NOT IN (SELECT assignment_id FROM outbox WHERE kind = 'review')""",
            (now_s,),
        )

    def available_lessons(self) -> list[Assignment]:
        return self._assignments(
            """a.unlocked_at IS NOT NULL AND a.started_at IS NULL
               AND a.id NOT IN (SELECT assignment_id FROM outbox WHERE kind = 'lesson_start')"""
        )

    def forecast(self, now: datetime | None = None, hours: int = 24) -> list[tuple[datetime, int]]:
        """Reviews becoming available per hour over the next ``hours`` hours."""
        now = now or utcnow()
        start = now.replace(minute=0, second=0, microsecond=0)
        buckets = [(start + timedelta(hours=h), 0) for h in range(1, hours + 1)]
        counts = [0] * hours
        rows = self.conn.execute(
            """SELECT a.available_at FROM assignments a JOIN subjects s ON s.id = a.subject_id
               WHERE s.hidden_at IS NULL AND a.hidden = 0 AND a.started_at IS NOT NULL
               AND a.burned_at IS NULL AND a.available_at > ? AND a.available_at <= ?""",
            (iso(now), iso(buckets[-1][0])),
        ).fetchall()
        for (available_at,) in rows:
            at = parse(available_at)
            assert at is not None
            # bucket h covers (start+h-1h, start+h]
            idx = int(((at - start).total_seconds() - 1e-6) // 3600)
            counts[max(0, min(hours - 1, idx))] += 1
        return [(t, c) for (t, _), c in zip(buckets, counts, strict=True)]

    def srs_distribution(self) -> dict[str, int]:
        dist = {name: 0 for name, _ in SRS_GROUPS}
        rows = self.conn.execute(
            """SELECT a.srs_stage, COUNT(*) FROM assignments a JOIN subjects s ON s.id = a.subject_id
               WHERE s.hidden_at IS NULL AND a.hidden = 0 AND a.started_at IS NOT NULL
               GROUP BY a.srs_stage"""
        ).fetchall()
        for stage, count in rows:
            for name, stages in SRS_GROUPS:
                if stage in stages:
                    dist[name] += count
        return dist

    # ---- outbox ------------------------------------------------------------

    def outbox_add(self, kind: str, assignment_id: int, payload: dict[str, Any], created_at: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO outbox (kind, assignment_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (kind, assignment_id, json.dumps(payload), created_at),
            )
        return int(cur.lastrowid or 0)

    def outbox(self) -> list[OutboxEntry]:
        rows = self.conn.execute(
            "SELECT * FROM outbox ORDER BY created_at, id"
        ).fetchall()
        return [
            OutboxEntry(r["id"], r["kind"], r["assignment_id"], json.loads(r["payload"]),
                        r["created_at"], r["attempts"], r["last_error"])
            for r in rows
        ]

    def outbox_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def outbox_delete(self, entry_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM outbox WHERE id = ?", (entry_id,))

    def outbox_failed(self, entry_id: int, error: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE outbox SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                (error, entry_id),
            )

    def subject_for_assignment(self, assignment_id: int) -> Subject | None:
        row = self.conn.execute(
            "SELECT subject_id FROM assignments WHERE id = ?", (assignment_id,)
        ).fetchone()
        return self.subject(row[0]) if row else None


# Re-exported for typing convenience.
__all__ = ["Repo", "OutboxEntry", "SRS_GROUPS", "StudyMaterial"]
