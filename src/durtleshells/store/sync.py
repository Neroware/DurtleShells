"""Incremental sync and outbox flushing.

The UI never talks to the API: it writes to the outbox through :meth:`SyncEngine.enqueue_*`
and the engine sends entries whenever it's online.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..api.client import (
    ApiError,
    AuthError,
    NetworkError,
    RateLimited,
    UnprocessableError,
    WaniKaniClient,
)
from .repo import OutboxEntry, Repo

COLLECTIONS = ("subjects", "assignments", "study_materials")
LABELS = {"subjects": "subjects", "assignments": "assignments", "study_materials": "study materials"}


@dataclass
class StaleSubmission:
    """An outbox entry the server refused (e.g. already reviewed elsewhere)."""

    entry: OutboxEntry
    subject_label: str
    reason: str

    @property
    def message(self) -> str:
        what = "review" if self.entry.kind == "review" else "lesson"
        return f"1 {what} was discarded: {self.subject_label} — {self.reason}"


@dataclass
class FlushResult:
    sent: int = 0
    dropped: int = 0
    offline: bool = False


ProgressCallback = Callable[[str], None]
StaleCallback = Callable[[StaleSubmission], None]


class SyncEngine:
    def __init__(
        self,
        repo: Repo,
        client: WaniKaniClient,
        *,
        on_progress: ProgressCallback | None = None,
        on_stale: StaleCallback | None = None,
    ) -> None:
        self.repo = repo
        self.client = client
        self.on_progress = on_progress or (lambda _msg: None)
        self.on_stale = on_stale or (lambda _s: None)
        self.online: bool | None = None  # unknown until the first request

    @property
    def pending(self) -> int:
        return self.repo.outbox_count()

    # ---- queue -------------------------------------------------------------

    def enqueue_review(
        self, assignment_id: int, incorrect_meaning: int, incorrect_reading: int, created_at: str
    ) -> int:
        payload = {
            "assignment_id": assignment_id,
            "incorrect_meaning_answers": incorrect_meaning,
            "incorrect_reading_answers": incorrect_reading,
            "created_at": created_at,
        }
        return self.repo.outbox_add("review", assignment_id, payload, created_at)

    def enqueue_lesson_start(self, assignment_id: int, started_at: str) -> int:
        return self.repo.outbox_add("lesson_start", assignment_id, {"started_at": started_at}, started_at)

    # ---- sync --------------------------------------------------------------

    async def sync(self) -> None:
        """Fetch user + every collection updated since the last sync and upsert it."""
        try:
            user = await self.client.get_user()
            self.repo.set_user(user.data)
            for name in COLLECTIONS:
                await self._sync_collection(name)
        except NetworkError:
            self.online = False
            raise
        self.online = True
        self.on_progress("")

    async def _sync_collection(self, name: str) -> None:
        key = f"last_sync_{name}"
        since = self.repo.meta(key)
        fetch = getattr(self.client, name)
        newest: str | None = None
        upsert = getattr(self.repo, f"upsert_{name}")
        async for page in fetch(since):
            upsert(page.items)
            newest = page.data_updated_at or newest
            if page.total_pages > 1 or page.items:
                self.on_progress(f"Syncing {LABELS[name]} {page.index}/{page.total_pages}…")
        # Only move the cursor forward once the whole collection arrived.
        if newest:
            self.repo.set_meta(key, newest)

    # ---- outbox ------------------------------------------------------------

    async def flush(self) -> FlushResult:
        result = FlushResult()
        for entry in self.repo.outbox():
            try:
                await self._send(entry)
            except NetworkError as exc:
                self.repo.outbox_failed(entry.id, str(exc))
                self.online = False
                result.offline = True
                return result
            except (AuthError, RateLimited):
                raise
            except UnprocessableError as exc:
                self._drop(entry, "already reviewed elsewhere" if entry.kind == "review"
                           else "already started elsewhere", str(exc))
                result.dropped += 1
                continue
            except ApiError as exc:
                if exc.status is not None and 400 <= exc.status < 500:
                    self._drop(entry, f"rejected by WaniKani ({exc.status})", str(exc))
                    result.dropped += 1
                    continue
                # Server trouble: keep the entry and try again later.
                self.repo.outbox_failed(entry.id, str(exc))
                return result
            self.online = True
            self.repo.outbox_delete(entry.id)
            result.sent += 1
        return result

    async def _send(self, entry: OutboxEntry) -> None:
        if entry.kind == "review":
            p = entry.payload
            assignment = await self.client.create_review(
                p["assignment_id"],
                p["incorrect_meaning_answers"],
                p["incorrect_reading_answers"],
                p.get("created_at"),
            )
            if assignment:
                self.repo.upsert_assignments([assignment])
        elif entry.kind == "lesson_start":
            started = await self.client.start_assignment(entry.assignment_id, entry.payload.get("started_at"))
            self.repo.upsert_assignments([{"id": started.id, "data": started.data}])

    def _drop(self, entry: OutboxEntry, reason: str, detail: str) -> None:
        subject = self.repo.subject_for_assignment(entry.assignment_id)
        label = subject.display if subject else f"assignment {entry.assignment_id}"
        self.repo.outbox_delete(entry.id)
        self.on_stale(StaleSubmission(entry, label, reason))

    async def run_once(self) -> FlushResult:
        """Flush first, then sync, so local state isn't overwritten with stale server data."""
        result = await self.flush()
        if result.offline:
            raise NetworkError("offline")
        await self.sync()
        return result
