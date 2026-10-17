"""The quiz session engine, shared by reviews and lesson quizzes.

State machine per question: ``ASKING → ANSWERED → (next | ignore)``. ``SHAKE``
verdicts never leave ``ASKING``. Completions are only reported by :meth:`Session.next`,
so an ignored answer can never have produced an outbox entry.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..api.models import Assignment, Subject
from ..timefmt import iso, utcnow
from .checker import Result, Verdict
from .ordering import order_lessons, order_reviews


class Half(Enum):
    MEANING = "meaning"
    READING = "reading"


class State(Enum):
    ASKING = "asking"
    ANSWERED = "answered"
    DONE = "done"


@dataclass
class SessionItem:
    assignment_id: int
    subject: Subject
    srs_stage: int = 0
    available_at: str | None = None
    remaining: list[Half] = field(default_factory=list)
    incorrect_meaning: int = 0
    incorrect_reading: int = 0
    answered: int = 0  # non-shake answers given so far

    @classmethod
    def build(cls, assignment: Assignment, subject: Subject, first: str, rng: random.Random) -> SessionItem:
        halves = [Half.MEANING]
        if subject.has_reading:
            reading_first = first == "reading" or (first == "random" and rng.random() < 0.5)
            halves = [Half.READING, Half.MEANING] if reading_first else [Half.MEANING, Half.READING]
        return cls(assignment.id, subject, assignment.srs_stage, assignment.available_at, halves)

    # ordering protocol
    @property
    def level(self) -> int:
        return self.subject.level

    @property
    def subject_type(self) -> str:
        return self.subject.object

    @property
    def subject_id(self) -> int:
        return self.subject.id

    @property
    def lesson_position(self) -> int:
        return self.subject.lesson_position

    @property
    def started(self) -> bool:
        return self.answered > 0


@dataclass(frozen=True)
class ItemCompleted:
    assignment_id: int
    subject_id: int
    incorrect_meaning: int
    incorrect_reading: int
    completed_at: str


@dataclass
class Question:
    item: SessionItem
    half: Half


@dataclass
class _Undo:
    item: SessionItem  # deep copy of the item before the answer
    verdict: Verdict
    completed_at: str


class Session:
    def __init__(
        self,
        items: Iterable[SessionItem],
        *,
        kind: str = "review",
        order: str = "random",
        rng: random.Random | None = None,
        clock: Callable[[], datetime] = utcnow,
        wrapup_mode: str = "started",
        wrapup_count: int = 10,
        ignore_mode: str = "immediate",
    ) -> None:
        self.kind = kind
        self.rng = rng or random.Random()
        self.clock = clock
        self.order = order
        self.wrapup_mode = wrapup_mode
        self.wrapup_count = wrapup_count
        self.ignore_mode = ignore_mode
        items = list(items)
        self.total = len(items)
        self.queue: list[SessionItem] = self._sorted(items)
        self.current: SessionItem | None = None
        self.state = State.ASKING
        self.last_verdict: Verdict | None = None
        self.wrapup = False
        self._wrapup_allowance = 0
        self._undo: _Undo | None = None
        self._answered_half = Half.MEANING
        self._pending_completion: ItemCompleted | None = None
        self.completed: list[ItemCompleted] = []
        self.wrong_items: dict[int, SessionItem] = {}
        self.questions_answered = 0
        self.questions_correct = 0
        self._draw()

    # ---- ordering ----------------------------------------------------------

    def _sorted(self, items: list[SessionItem]) -> list[SessionItem]:
        if self.kind == "lesson":
            return order_lessons(items, self.order, self.rng)
        return order_reviews(items, self.order, self.rng)

    def reorder(self, order: str) -> None:
        """Change the order of items that haven't been drawn yet."""
        self.order = order
        slots = [i for i, item in enumerate(self.queue) if not item.started]
        fresh = self._sorted([self.queue[i] for i in slots])
        for slot, item in zip(slots, fresh, strict=True):
            self.queue[slot] = item

    # ---- queries -----------------------------------------------------------

    @property
    def question(self) -> Question | None:
        """The question on screen (in ANSWERED state: the one just answered)."""
        if self.current is None:
            return None
        if self.state is State.ANSWERED:
            return Question(self.current, self._answered_half)
        return Question(self.current, self.current.remaining[0]) if self.current.remaining else None

    @property
    def done(self) -> bool:
        return self.state is State.DONE

    @property
    def remaining(self) -> int:
        """Items not yet completed (including the current one)."""
        return self.total - len(self.completed) - (1 if self._pending_completion else 0)

    @property
    def accuracy(self) -> float | None:
        if not self.questions_answered:
            return None
        return self.questions_correct / self.questions_answered

    @property
    def wrapup_left(self) -> int:
        """Items still to finish during wrap-up."""
        started = sum(1 for i in self.queue if i.started)
        current = 1 if self.current is not None and self.current.remaining else 0
        return started + current + (self._wrapup_allowance if self.wrapup_mode == "count" else 0)

    # ---- answering ---------------------------------------------------------

    def submit(self, verdict: Verdict) -> Verdict:
        if self.state is not State.ASKING or self.current is None:
            raise RuntimeError(f"cannot submit in state {self.state}")
        if verdict.result is Result.SHAKE:
            return verdict
        item = self.current
        half = item.remaining[0]
        now = iso(self.clock())
        self._undo = _Undo(copy.deepcopy(item), verdict, now)
        self._answered_half = half
        item.answered += 1
        self.questions_answered += 1
        if verdict.is_correct:
            self.questions_correct += 1
            item.remaining.pop(0)
            if not item.remaining:
                self._pending_completion = ItemCompleted(
                    item.assignment_id, item.subject.id,
                    item.incorrect_meaning, item.incorrect_reading, now,
                )
        else:
            if half is Half.MEANING:
                item.incorrect_meaning += 1
            else:
                item.incorrect_reading += 1
            self.wrong_items[item.assignment_id] = item
        self.state = State.ANSWERED
        self.last_verdict = verdict
        return verdict

    @property
    def answered_half(self) -> Half | None:
        return self._answered_half if self.state is State.ANSWERED else None

    def next(self) -> list[ItemCompleted]:
        """Commit the shown answer and advance. Returns items completed by it."""
        if self.state is not State.ANSWERED:
            raise RuntimeError(f"cannot advance in state {self.state}")
        assert self.current is not None and self.last_verdict is not None
        done: list[ItemCompleted] = []
        item = self.current
        if self._pending_completion is not None:
            done.append(self._pending_completion)
            self.completed.append(self._pending_completion)
            self._pending_completion = None
            self.current = None
        elif not self.last_verdict.is_correct:
            self._requeue(item)
            self.current = None
        # else: correct with a half left → ask it straight away (back to back)
        self._undo = None
        self.state = State.ASKING
        if self.current is None:
            self._draw()
        return done

    def ignore(self) -> bool:
        """Undo the shown answer. Returns False if there is nothing to undo."""
        if self.state is not State.ANSWERED or self._undo is None or self.current is None:
            return False
        undo = self._undo
        restored = undo.item
        # Restore in place so references to the current item stay valid.
        self.current.__dict__.update(copy.deepcopy(restored.__dict__))
        self.questions_answered -= 1
        if undo.verdict.is_correct:
            self.questions_correct -= 1
        if restored.incorrect_meaning == 0 and restored.incorrect_reading == 0:
            self.wrong_items.pop(restored.assignment_id, None)
        self._pending_completion = None
        self._undo = None
        self.last_verdict = None
        self.state = State.ASKING
        if self.ignore_mode == "later" and len(self.queue) > 0:
            self._requeue(self.current)
            self.current = None
            self._draw()
        return True

    # ---- wrap-up -----------------------------------------------------------

    def toggle_wrapup(self) -> bool:
        self.wrapup = not self.wrapup
        self._wrapup_allowance = self.wrapup_count if self.wrapup and self.wrapup_mode == "count" else 0
        if self.state in (State.ASKING, State.DONE) and self.current is None:
            self._draw()
        elif (
            self.wrapup
            and self.state is State.ASKING
            and self.current is not None
            and not self.current.started
            and not self._take_allowance()
        ):
            # The current question wasn't touched yet: it's "new", so wrap-up drops it.
            self.queue.insert(0, self.current)
            self.current = None
            self._draw()
        return self.wrapup

    def _take_allowance(self) -> bool:
        if self.wrapup_mode == "count" and self._wrapup_allowance > 0:
            self._wrapup_allowance -= 1
            return True
        return False

    # ---- internals ---------------------------------------------------------

    def _requeue(self, item: SessionItem) -> None:
        """Put a wrong (or postponed) item back 3–10 draws ahead."""
        if not self.queue:
            self.queue.append(item)
            return
        low = min(3, len(self.queue))
        high = min(10, len(self.queue))
        self.queue.insert(self.rng.randint(low, high), item)

    def _draw(self) -> None:
        self.current = None
        for idx, item in enumerate(self.queue):
            if not self.wrapup or item.started or self._take_allowance():
                self.current = self.queue.pop(idx)
                self.state = State.ASKING
                return
        self.state = State.DONE
