"""Quiz screen, shared by reviews and lesson quizzes."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.widgets import Input, Static

from ...domain.checker import Result, Verdict, check_meaning, check_reading
from ...domain.session import Half, Session, State
from ..widgets.answer import AnswerInput
from ..widgets.flick import FlickKeyboard
from ..widgets.iteminfo import ItemInfo
from ..widgets.prompt import Prompt, PromptBar
from .base import DurtleScreen
from .confirm import ConfirmScreen

MIN_ROWS_FOR_FLICK = 34


class QuizScreen(DurtleScreen):
    DEFAULT_CSS = """
    QuizScreen #quiz { height: 1fr; }
    QuizScreen #answer-row { height: 3; margin-top: 1; }
    QuizScreen #feedback { height: 2; width: 1fr; content-align: center middle; }
    QuizScreen #feedback.-good { color: #2ecc71; }
    QuizScreen #feedback.-typo { color: #f1c40f; }
    QuizScreen #feedback.-bad { color: #e74c3c; }
    QuizScreen #feedback.-shake { color: #f39c12; text-style: bold; }
    QuizScreen #flick-wrap { height: auto; width: 1fr; }
    QuizScreen #flick-wrap.-hidden { display: none; }
    QuizScreen #flick-hint { height: 1; width: 1fr; color: $text-muted; content-align: center middle; display: none; }
    QuizScreen #flick-hint.-visible { display: block; }
    QuizScreen #spacer { height: 1fr; }
    QuizScreen.-info #spacer { display: none; }
    """

    BINDINGS = [
        Binding("enter", "enter", "next", show=False),
        Binding("u", "ignore", "ignore answer", show=False),
        Binding("f", "info", "item info", show=False),
        Binding("w", "wrapup", "wrap-up", show=False),
        Binding("q", "leave", "leave", show=False),
        Binding("i", "insert", "insert", show=False),
        Binding("a", "insert", "insert", show=False),
    ]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.kind = session.kind
        self.NAME = "reviews" if self.kind == "review" else "lesson quiz"

    def compose_body(self) -> ComposeResult:
        with Vertical(id="quiz"):
            yield Prompt(id="prompt")
            yield PromptBar(id="promptbar")
            with Vertical(id="answer-row"):
                yield AnswerInput(id="answer")
            yield Static(id="feedback")
            yield ItemInfo(id="info")
            yield Static(id="spacer")
            yield Static("terminal too small for the flick keyboard (needs "
                         f"{MIN_ROWS_FOR_FLICK} rows)", id="flick-hint")
            with Center(id="flick-wrap"):
                yield FlickKeyboard(id="flick")

    def on_mount(self) -> None:
        self.show_question()

    # ---- helpers -----------------------------------------------------------

    @property
    def answer(self) -> AnswerInput:
        return self.query_one("#answer", AnswerInput)

    def progress_text(self) -> str:
        s = self.session
        done = len(s.completed)
        acc = s.accuracy
        pct = f" ✓{round(acc * 100)}%" if acc is not None else ""
        return f"{done}/{s.total}{pct}"

    def _feedback(self, text: str | Text, kind: str | None = None) -> None:
        fb = self.query_one("#feedback", Static)
        fb.update(text)
        for cls in ("-good", "-typo", "-bad", "-shake"):
            fb.remove_class(cls)
        if kind:
            fb.add_class(f"-{kind}")

    def _update_flick(self) -> None:
        q = self.session.question
        want = (
            bool(self.app.config.settings["flick"])
            and q is not None
            and q.half is Half.READING
            and self.session.state is State.ASKING
        )
        fits = self.size.height >= MIN_ROWS_FOR_FLICK or self.size.height == 0
        self.query_one("#flick-wrap").set_class(not (want and fits), "-hidden")
        self.query_one("#flick-hint").set_class(want and not fits, "-visible")

    def _set_info(self, visible: bool) -> None:
        self.query_one(ItemInfo).set_visible(visible)
        self.set_class(visible, "-info")

    def on_resize(self, _event) -> None:
        self._update_flick()

    def settings_changed(self, name: str) -> None:
        if name == "flick":
            self._update_flick()
        elif name == "order" and self.kind == "review":
            self.session.reorder(self.app.config.settings["order"])

    # ---- question flow -----------------------------------------------------

    def show_question(self) -> None:
        s = self.session
        if s.done:
            self.finish()
            return
        q = s.question
        assert q is not None
        subject = q.item.subject
        self.query_one(Prompt).show(subject)
        self.query_one(PromptBar).show(subject, q.half.value)
        ans = self.answer
        ans.disabled = False
        ans.set_kana(q.half is Half.READING)
        ans.value = ""
        ans.set_result(None)
        self._feedback("")
        self._set_info(False)
        self.query_one(ItemInfo).show(subject, self.app.repo.synonyms(subject.id), self.app.repo.subject)
        self._update_flick()
        ans.focus()
        self.refresh_status()

    def check(self, value: str) -> Verdict:
        q = self.session.question
        assert q is not None
        subject = q.item.subject
        if q.half is Half.MEANING:
            return check_meaning(subject, value, self.app.repo.synonyms(subject.id),
                                 self.app.config.settings["typo_tolerance"])
        return check_reading(subject, value)

    def submit_answer(self) -> None:
        s = self.session
        if s.state is not State.ASKING:
            return
        ans = self.answer
        value = ans.final_value()
        verdict = self.check(value)
        if verdict.result is Result.SHAKE:
            self._feedback(verdict.message, "shake")
            self._shake()
            return
        s.submit(verdict)
        ans.value = value
        ans.disabled = True
        q = s.question
        assert q is not None
        if verdict.result is Result.CORRECT:
            ans.set_result("correct")
            self._feedback("✓ correct", "good")
        elif verdict.result is Result.CORRECT_TYPO:
            ans.set_result("typo")
            self._feedback(f"✓ {verdict.message}", "typo")
        else:
            ans.set_result("incorrect")
            msg = Text("✗ ")
            if verdict.message:
                msg.append(verdict.message + " · ")
            msg.append("answer: ")
            msg.append(self._expected(q.half), style="bold")
            self._feedback(msg, "bad")
            self._set_info(True)
        self._update_flick()
        self.set_focus(None)
        self.refresh_status()

    def _expected(self, half: Half) -> str:
        subject = self.session.question.item.subject  # type: ignore[union-attr]
        if half is Half.MEANING:
            return ", ".join(m.meaning for m in subject.meanings if m.accepted_answer)
        return "、".join(r.reading for r in subject.readings if r.accepted_answer)

    def _shake(self) -> None:
        row = self.query_one("#answer-row")
        steps = [(2, 0), (-2, 0), (1, 0), (-1, 0), (0, 0)]
        for i, (x, y) in enumerate(steps):
            self.set_timer(0.04 * i, lambda x=x, y=y: setattr(row.styles, "offset", (x, y)))

    def advance(self) -> None:
        if self.session.state is not State.ANSWERED:
            return
        for completion in self.session.next():
            self.app.record_completion(self.kind, completion)
        self.show_question()

    def finish(self) -> None:
        from .summary import SummaryScreen

        self.app.session_finished(self.kind)
        self.app.switch_screen(SummaryScreen(self.session))

    # ---- events ------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "answer":
            event.stop()
            self.submit_answer()

    def on_flick_keyboard_pressed(self, event: FlickKeyboard.Pressed) -> None:
        event.stop()
        if self.session.state is State.ANSWERED:
            if event.action == "submit":
                self.advance()
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
        if self.session.state is State.ANSWERED:
            self.advance()
        elif self.answer.value.strip():
            self.submit_answer()
        else:
            self.answer.focus()

    def action_insert(self) -> None:
        if self.session.state is State.ASKING:
            self.answer.focus()

    def action_ignore(self) -> None:
        if self.session.ignore():
            self.show_question()
            self.message("answer ignored")
        else:
            self.message("nothing to ignore", error=True)

    def action_info(self) -> None:
        if self.session.state is State.ANSWERED:
            info = self.query_one(ItemInfo)
            self._set_info(not info.visible)

    def action_wrapup(self) -> None:
        self.toggle_wrapup()

    def toggle_wrapup(self) -> None:
        s = self.session
        was_asking = s.state is State.ASKING
        before = s.question.item if s.question else None
        on = s.toggle_wrapup()
        self.message(f"wrap-up {'on' if on else 'off'}")
        if s.done:
            self.finish()
            return
        if was_asking and (s.question is None or s.question.item is not before):
            self.show_question()
        self.refresh_status()

    def action_leave(self) -> None:
        self.close()

    def close(self, force: bool = False) -> None:
        def leave(ok: bool | None) -> None:
            if ok:
                self.app.session_finished(self.kind)
                self.app.pop_screen()

        if force or not self.session.questions_answered:
            leave(True)
            return
        done = len(self.session.completed)
        what = "reviews" if self.kind == "review" else "lessons"
        self.app.push_screen(
            ConfirmScreen(
                f"Leave the session?\n{done} completed {what} are saved; "
                "half-answered items are dropped."
            ),
            leave,
        )
