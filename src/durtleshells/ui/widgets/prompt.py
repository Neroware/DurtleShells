"""The big prompt area and the question bar under it."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from ...api.models import Subject

COLORS = {"radical": "#00AAFF", "kanji": "#FF00AA", "vocabulary": "#AA00FF"}


def spaced(text: str) -> str:
    """Widen short prompts a little so they read as 'big'."""
    return " ".join(text) if len(text) <= 4 else text


class Prompt(Static):
    DEFAULT_CSS = """
    Prompt {
        height: 7;
        width: 1fr;
        content-align: center middle;
        text-style: bold;
        color: #ffffff;
        background: #444444;
    }
    Prompt.radical { background: #00AAFF; }
    Prompt.kanji { background: #FF00AA; }
    Prompt.vocabulary { background: #AA00FF; }
    """

    def show(self, subject: Subject) -> None:
        for group in COLORS:
            self.remove_class(group)
        self.add_class(subject.color_group)
        if subject.characters:
            text = Text(spaced(subject.characters), style="bold")
        else:
            text = Text.assemble(
                (f"[{subject.primary_meaning}]", "bold"),
                ("\n(image-only radical — not shown in a terminal)", "italic"),
            )
        self.update(text)


class PromptBar(Static):
    DEFAULT_CSS = """
    PromptBar { height: 1; width: 1fr; content-align: center middle; text-style: bold; }
    PromptBar.reading { background: #1e1e1e; color: #ffffff; }
    PromptBar.meaning { background: #e6e6e6; color: #1e1e1e; }
    """

    def show(self, subject: Subject, half: str) -> None:
        self.set_class(half == "reading", "reading")
        self.set_class(half == "meaning", "meaning")
        self.update(f"{subject.type_label} · {half.title()}")
