"""Small yes/no modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: 64; height: auto; padding: 1 2;
        border: thick $warning; background: $surface;
    }
    ConfirmScreen #confirm-hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [
        Binding("y", "answer(True)", show=False),
        Binding("enter", "answer(True)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("escape", "answer(False)", show=False),
        Binding("q", "answer(False)", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.question)
            yield Static("[b]y[/b]/Enter = yes · [b]n[/b]/Esc = no", id="confirm-hint")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)
