"""Lesson presentation: one item at a time, a few pages per item."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ...api.models import Assignment, Subject
from ..widgets.iteminfo import heading, meanings_text, readings_text, render_markup
from ..widgets.prompt import Prompt
from .base import DurtleScreen


def pages_for(subject: Subject) -> list[str]:
    if subject.object == "radical":
        return ["Name"]
    if subject.object == "kanji":
        return ["Radicals", "Meaning", "Reading"]
    if subject.object == "kana_vocabulary":
        return ["Meaning"]
    return ["Kanji", "Meaning", "Reading"]


class LessonScreen(DurtleScreen):
    NAME = "lessons"
    DEFAULT_CSS = """
    LessonScreen #lesson { height: 1fr; }
    LessonScreen #lesson-head { height: 1; padding: 0 2; background: $panel; }
    LessonScreen #lesson-tabs { height: 1; padding: 0 2; }
    LessonScreen #lesson-body { height: 1fr; padding: 1 4; }
    LessonScreen #lesson-keys { height: 1; padding: 0 2; color: $text-muted; }
    """
    BINDINGS = [
        Binding("l", "page(1)", show=False),
        Binding("right", "page(1)", show=False),
        Binding("h", "page(-1)", show=False),
        Binding("left", "page(-1)", show=False),
        Binding("j", "item(1)", show=False),
        Binding("n", "item(1)", show=False),
        Binding("down", "item(1)", show=False),
        Binding("k", "item(-1)", show=False),
        Binding("p", "item(-1)", show=False),
        Binding("up", "item(-1)", show=False),
        Binding("enter", "enter", show=False),
        Binding("q", "leave", show=False),
    ]

    def __init__(self, batch: list[tuple[Assignment, Subject]]) -> None:
        super().__init__()
        self.batch = batch
        self.index = 0
        self.page = 0

    def compose_body(self) -> ComposeResult:
        with Vertical(id="lesson"):
            yield Static(id="lesson-head")
            yield Prompt(id="lesson-prompt")
            yield Static(id="lesson-tabs")
            with VerticalScroll(id="lesson-body"):
                yield Static(id="lesson-text")
            yield Static(id="lesson-keys")

    def on_mount(self) -> None:
        self.render_page()

    @property
    def subject(self) -> Subject:
        return self.batch[self.index][1]

    def progress_text(self) -> str:
        return f"{self.index + 1}/{len(self.batch)}"

    def render_page(self) -> None:
        subject = self.subject
        pages = pages_for(subject)
        self.page = max(0, min(self.page, len(pages) - 1))
        self.query_one("#lesson-head", Static).update(
            f"Lesson {self.index + 1}/{len(self.batch)} · {subject.type_label} · level {subject.level}"
        )
        self.query_one(Prompt).show(subject)
        tabs = Text()
        for i, name in enumerate(pages):
            tabs.append(f" {name} ", style="bold reverse" if i == self.page else "dim")
            tabs.append(" ")
        self.query_one("#lesson-tabs", Static).update(tabs)
        self.query_one("#lesson-text", Static).update(self.page_text(subject, pages[self.page]))
        self.query_one("#lesson-body", VerticalScroll).scroll_home(animate=False)
        last = self.index == len(self.batch) - 1 and self.page == len(pages) - 1
        keys = "h/l page · j/k item · Enter " + ("start quiz" if last else "next") + " · q quit"
        self.query_one("#lesson-keys", Static).update(keys)
        self.refresh_status()

    def page_text(self, subject: Subject, page: str) -> Text:
        repo = self.app.repo
        t = Text()
        if page in ("Radicals", "Kanji"):
            t.append_text(heading("Made of", first=True))
            for sid in subject.component_subject_ids:
                comp = repo.subject(sid)
                if comp:
                    t.append(f"  {comp.display}  ", style="bold")
                    t.append(comp.primary_meaning + "\n")
            if not subject.component_subject_ids:
                t.append("—")
            return t
        if page in ("Name", "Meaning"):
            t.append_text(heading("Meaning" if page == "Meaning" else "Name", first=True))
            t.append_text(meanings_text(subject, repo.synonyms(subject.id)))
            if subject.object == "kana_vocabulary" and subject.characters:
                t.append_text(heading("Reading"))
                t.append(subject.characters, style="bold")
            t.append_text(heading("Mnemonic"))
            t.append_text(render_markup(subject.meaning_mnemonic))
            if subject.meaning_hint:
                t.append_text(heading("Hint"))
                t.append_text(render_markup(subject.meaning_hint))
            return t
        t.append_text(heading("Reading", first=True))
        t.append_text(readings_text(subject))
        if subject.reading_mnemonic:
            t.append_text(heading("Mnemonic"))
            t.append_text(render_markup(subject.reading_mnemonic))
        if subject.reading_hint:
            t.append_text(heading("Hint"))
            t.append_text(render_markup(subject.reading_hint))
        return t

    def action_page(self, delta: int) -> None:
        pages = pages_for(self.subject)
        new = self.page + delta
        if new < 0 and self.index > 0:
            self.index -= 1
            self.page = len(pages_for(self.subject)) - 1
        elif new >= len(pages) and self.index < len(self.batch) - 1:
            self.index += 1
            self.page = 0
        else:
            self.page = max(0, min(new, len(pages) - 1))
        self.render_page()

    def action_item(self, delta: int) -> None:
        self.index = max(0, min(self.index + delta, len(self.batch) - 1))
        self.page = 0
        self.render_page()

    def action_enter(self) -> None:
        pages = pages_for(self.subject)
        if self.page < len(pages) - 1:
            self.page += 1
        elif self.index < len(self.batch) - 1:
            self.index += 1
            self.page = 0
        else:
            self.app.start_lesson_quiz(self.batch)
            return
        self.render_page()

    def action_leave(self) -> None:
        self.close()

    def close(self, force: bool = False) -> None:
        self.app.pop_screen()
