"""Flick practice: type vocabulary readings with the flick keyboard, nothing is sent."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.widgets import Input, Static

from ...api.models import Subject
from ...domain.checker import Result, check_reading
from ..widgets.answer import AnswerInput
from ..widgets.flick import FlickKeyboard
from ..widgets.prompt import Prompt
from .base import DurtleScreen
from .quiz import MIN_ROWS_FOR_FLICK

# Words come from levels up to max(user level, this), so level-1 accounts get some variety.
MIN_PRACTICE_LEVEL = 5


class PracticeScreen(DurtleScreen):
    NAME = "flick practice"
    DEFAULT_CSS = """
    PracticeScreen #practice { height: 1fr; }
    PracticeScreen #target { height: 2; width: 1fr; content-align: center middle; }
    PracticeScreen #answer-row { height: 3; margin-top: 1; }
    PracticeScreen #feedback { height: 2; width: 1fr; content-align: center middle; }
    PracticeScreen #feedback.-good { color: #2ecc71; }
    PracticeScreen #feedback.-bad { color: #e74c3c; }
    PracticeScreen #spacer { height: 1fr; }
    PracticeScreen #flick-wrap { height: auto; width: 1fr; }
    PracticeScreen #flick-wrap.-hidden { display: none; }
    PracticeScreen #flick-hint { height: 1; width: 1fr; color: $text-muted; content-align: center middle; display: none; }
    PracticeScreen #flick-hint.-visible { display: block; }
    """
    BINDINGS = [
        Binding("enter", "enter", "next", show=False),
        Binding("n", "skip", "skip", show=False),
        Binding("q", "leave", "leave", show=False),
        Binding("i", "insert", "insert", show=False),
        Binding("a", "insert", "insert", show=False),
    ]

    def __init__(self, subject_ids: list[int]) -> None:
        super().__init__()
        self.subject_ids = subject_ids
        self.subject: Subject | None = None
        self.solved = False
        self.correct = 0
        self.attempted = 0

    def compose_body(self) -> ComposeResult:
        with Vertical(id="practice"):
            yield Prompt(id="prompt")
            yield Static(id="target")
            with Vertical(id="answer-row"):
                yield AnswerInput(id="answer")
            yield Static(id="feedback")
            yield Static(id="spacer")
            yield Static("terminal too small for the flick keyboard (needs "
                         f"{MIN_ROWS_FOR_FLICK} rows)", id="flick-hint")
            with Center(id="flick-wrap"):
                yield FlickKeyboard(id="flick")

    def on_mount(self) -> None:
        self.next_word()

    @property
    def answer(self) -> AnswerInput:
        return self.query_one("#answer", AnswerInput)

    def progress_text(self) -> str:
        return f"{self.correct}/{self.attempted}" if self.attempted else ""

    def _feedback(self, text: str | Text, kind: str | None = None) -> None:
        fb = self.query_one("#feedback", Static)
        fb.update(text)
        fb.set_class(kind == "good", "-good")
        fb.set_class(kind == "bad", "-bad")

    def _update_flick(self) -> None:
        fits = self.size.height >= MIN_ROWS_FOR_FLICK or self.size.height == 0
        self.query_one("#flick-wrap").set_class(not fits, "-hidden")
        self.query_one("#flick-hint").set_class(not fits, "-visible")

    def on_resize(self, _event) -> None:
        self._update_flick()

    def next_word(self) -> None:
        app = self.app
        subject = None
        for _ in range(20):  # skip ids whose subject vanished or has no reading
            candidate = app.repo.subject(app.rng.choice(self.subject_ids))
            if candidate is not None and candidate.readings:
                subject = candidate
                break
        self.subject = subject
        self.solved = False
        if subject is None:
            self.message("no vocabulary with readings found", error=True)
            return
        self.query_one(Prompt).show(subject)
        target = Text(subject.primary_reading or "", style="bold")
        target.append(f"   {subject.primary_meaning}", style="dim")
        self.query_one("#target", Static).update(target)
        ans = self.answer
        ans.disabled = False
        ans.set_kana(True)
        ans.value = ""
        ans.set_result(None)
        self._feedback("")
        self._update_flick()
        ans.focus()
        self.refresh_status()

    def submit_answer(self) -> None:
        if self.subject is None or self.solved:
            return
        ans = self.answer
        value = ans.final_value()
        if not value:
            return
        verdict = check_reading(self.subject, value)
        self.attempted += 1
        if verdict.result is Result.CORRECT:
            self.correct += 1
            self.solved = True
            ans.value = value
            ans.set_result("correct")
            ans.disabled = True
            self._feedback("✓ correct · Enter for the next word", "good")
            self.set_focus(None)
        else:
            ans.set_result("incorrect")
            self._feedback("✗ not quite · fix it and press Enter, or n to skip", "bad")
        self.refresh_status()

    # ---- events ------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "answer" and not self.solved:
            event.input.set_result(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "answer":
            event.stop()
            self.submit_answer()

    def on_flick_keyboard_pressed(self, event: FlickKeyboard.Pressed) -> None:
        event.stop()
        if self.solved:
            if event.action == "submit":
                self.next_word()
            return
        ans = self.answer
        if event.action == "kana" and event.text:
            ans.insert_kana(event.text)
        elif event.action == "modifier":
            ans.cycle_last()
        elif event.action == "backspace":
            ans.backspace()
        elif event.action == "submit":
            self.submit_answer()
        if not ans.has_focus and not self.query_one("CommandLine").active:
            ans.focus()

    # ---- actions -----------------------------------------------------------

    def action_enter(self) -> None:
        if self.solved:
            self.next_word()
        elif self.answer.value.strip():
            self.submit_answer()
        else:
            self.answer.focus()

    def action_skip(self) -> None:
        self.next_word()

    def action_insert(self) -> None:
        if not self.solved:
            self.answer.focus()

    def action_leave(self) -> None:
        self.close()

    def close(self, force: bool = False) -> None:
        self.app.pop_screen()
