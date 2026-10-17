"""Answer input with live romaji→kana conversion for reading questions."""

from __future__ import annotations

from textual.widgets import Input

from ...domain.flick import cycle
from ...domain.kana import convert


class AnswerInput(Input):
    DEFAULT_CSS = """
    AnswerInput {
        width: 1fr;
        margin: 0 4;
        border: tall $accent;
        text-align: center;
    }
    AnswerInput:disabled { opacity: 100%; text-opacity: 100%; }
    AnswerInput.-correct { background: #1f7a3a; color: #ffffff; border: tall #2ecc71; }
    AnswerInput.-typo { background: #8a6d00; color: #ffffff; border: tall #f1c40f; }
    AnswerInput.-incorrect { background: #8e1b1b; color: #ffffff; border: tall #e74c3c; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(select_on_focus=False, **kwargs)
        self.kana = False

    def set_kana(self, kana: bool) -> None:
        self.kana = kana
        self.placeholder = "答え (romaji → kana)" if kana else "Answer (meaning)"

    def replace(self, text: str, start: int, end: int) -> None:
        super().replace(text, start, end)
        self._reconvert()

    def _reconvert(self) -> None:
        if not self.kana:
            return
        cursor = self.cursor_position
        left = convert(self.value[:cursor])
        new = left + self.value[cursor:]
        if new != self.value:
            self.value = new
            self.cursor_position = len(left)

    # ---- flick keyboard hooks ----------------------------------------------

    def insert_kana(self, kana: str) -> None:
        """Insert flicked kana at the cursor, flushing any pending romaji first."""
        cursor = self.cursor_position
        left = convert(self.value[:cursor], final=True) if self.kana else self.value[:cursor]
        right = self.value[cursor:]
        self.value = left + kana + right
        self.cursor_position = len(left) + len(kana)

    def cycle_last(self) -> None:
        cursor = self.cursor_position
        if cursor == 0:
            return
        before = self.value[: cursor - 1]
        self.value = before + cycle(self.value[cursor - 1]) + self.value[cursor:]
        self.cursor_position = cursor

    def backspace(self) -> None:
        cursor = self.cursor_position
        if cursor:
            self.value = self.value[: cursor - 1] + self.value[cursor:]
            self.cursor_position = cursor - 1

    def final_value(self) -> str:
        return convert(self.value, final=True) if self.kana else self.value

    def set_result(self, result: str | None) -> None:
        for cls in ("-correct", "-typo", "-incorrect"):
            self.remove_class(cls)
        if result:
            self.add_class(f"-{result}")
