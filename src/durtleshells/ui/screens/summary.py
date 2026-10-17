"""End-of-session summary."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.widgets import Static

from ...domain.session import Session
from .base import DurtleScreen


class SummaryScreen(DurtleScreen):
    NAME = "summary"
    DEFAULT_CSS = """
    SummaryScreen Center { height: 1fr; align: center middle; }
    SummaryScreen #summary { width: 70; height: auto; padding: 1 2; border: round $accent; }
    """
    BINDINGS = [
        Binding("enter", "continue", show=False),
        Binding("q", "leave", show=False),
        Binding("escape", "leave", show=False),
    ]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session

    def compose_body(self) -> ComposeResult:
        with Center(), Vertical(id="summary"):
            yield Static(self._content())

    def _content(self) -> Table:
        s = self.session
        lesson = s.kind == "lesson"
        t = Table.grid(padding=(0, 2))
        t.add_column()
        title = "Lesson batch done" if lesson else "Review session done"
        t.add_row(Text(title, style="bold"))
        acc = s.accuracy
        t.add_row(f"Completed: {len(s.completed)}/{s.total}")
        t.add_row(f"Correct answers: {round(acc * 100)}%" if acc is not None else "No answers given")
        wrong = [i for i in s.wrong_items.values()]
        if wrong:
            t.add_row(Text("\nAnswered wrong:", style="bold"))
            for item in wrong:
                parts = []
                if item.incorrect_meaning:
                    parts.append(f"meaning ×{item.incorrect_meaning}")
                if item.incorrect_reading:
                    parts.append(f"reading ×{item.incorrect_reading}")
                t.add_row(f"  {item.subject.display}  {item.subject.primary_meaning}  ({', '.join(parts)})")
        more = lesson and self.app.lesson_candidates()
        hint = "\nEnter: another batch · q: dashboard" if more else "\nEnter / q: back to the dashboard"
        t.add_row(Text(hint, style="dim"))
        return t

    def action_continue(self) -> None:
        if self.session.kind == "lesson" and self.app.lesson_candidates():
            self.app.pop_screen()
            self.app.start_lessons()
        else:
            self.app.pop_screen()

    def action_leave(self) -> None:
        self.app.pop_screen()

    def close(self, force: bool = False) -> None:
        self.app.pop_screen()
