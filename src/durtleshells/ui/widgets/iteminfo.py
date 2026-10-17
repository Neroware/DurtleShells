"""Item details: meanings, readings and mnemonics with WaniKani markup rendered."""

from __future__ import annotations

import re
from collections.abc import Callable

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ...api.models import Subject

TAG_STYLES = {
    "radical": "bold #ffffff on #00AAFF",
    "kanji": "bold #ffffff on #FF00AA",
    "vocabulary": "bold #ffffff on #AA00FF",
    "reading": "bold reverse",
    "meaning": "bold underline",
    "ja": "",
}
_TAG = re.compile(r"<(/?)([a-z]+)>")
READING_TYPES = {"onyomi": "on'yomi", "kunyomi": "kun'yomi", "nanori": "nanori"}


def render_markup(source: str | None) -> Text:
    """Turn WaniKani's ``<kanji>…</kanji>`` style tags into styled Rich text."""
    text = Text()
    if not source:
        return text
    stack: list[str] = []
    pos = 0
    for match in _TAG.finditer(source):
        text.append(source[pos:match.start()], style=" ".join(s for s in stack if s) or None)
        closing, tag = match.groups()
        if tag in TAG_STYLES:
            if closing:
                if stack:
                    stack.pop()
            else:
                stack.append(TAG_STYLES[tag])
        pos = match.end()
    text.append(source[pos:], style=" ".join(s for s in stack if s) or None)
    return text


def heading(title: str, first: bool = False) -> Text:
    t = Text("" if first else "\n\n")
    t.append(title, style="bold underline")
    t.append("\n")
    return t


def meanings_text(subject: Subject, synonyms: list[str] = ()) -> Text:
    t = Text()
    primary = [m.meaning for m in subject.meanings if m.primary]
    others = [m.meaning for m in subject.meanings if not m.primary and m.accepted_answer]
    t.append(", ".join(primary), style="bold")
    if others:
        t.append(", " + ", ".join(others))
    if synonyms:
        t.append("\nSynonyms: ", style="dim")
        t.append(", ".join(synonyms))
    return t


def readings_text(subject: Subject) -> Text:
    t = Text()
    if subject.object == "kanji":
        by_type: dict[str, list] = {}
        for r in subject.readings:
            by_type.setdefault(r.type or "", []).append(r)
        for kind in ("onyomi", "kunyomi", "nanori"):
            if kind not in by_type:
                continue
            t.append(f"{READING_TYPES[kind]}: ", style="dim")
            for i, r in enumerate(by_type[kind]):
                if i:
                    t.append("、")
                t.append(r.reading, style="bold" if r.accepted_answer else "dim")
            t.append("\n")
    else:
        t.append("、".join(r.reading for r in subject.readings if r.accepted_answer), style="bold")
    return t


def subject_details(
    subject: Subject,
    synonyms: list[str] = (),
    lookup: Callable[[int], Subject | None] | None = None,
) -> Text:
    t = Text()
    t.append(f"{subject.display}  ", style="bold")
    t.append(f"{subject.type_label} · level {subject.level}", style="dim")
    t.append_text(heading("Meaning"))
    t.append_text(meanings_text(subject, list(synonyms)))
    if subject.readings:
        t.append_text(heading("Reading"))
        t.append_text(readings_text(subject))
    if lookup and subject.component_subject_ids:
        t.append_text(heading("Radicals" if subject.object == "kanji" else "Kanji"))
        parts = []
        for sid in subject.component_subject_ids:
            comp = lookup(sid)
            if comp:
                parts.append(f"{comp.display} {comp.primary_meaning}")
        t.append("  ·  ".join(parts))
    t.append_text(heading("Meaning mnemonic"))
    t.append_text(render_markup(subject.meaning_mnemonic))
    if subject.meaning_hint:
        t.append("\nHint: ", style="dim italic")
        t.append_text(render_markup(subject.meaning_hint))
    if subject.reading_mnemonic:
        t.append_text(heading("Reading mnemonic"))
        t.append_text(render_markup(subject.reading_mnemonic))
        if subject.reading_hint:
            t.append("\nHint: ", style="dim italic")
            t.append_text(render_markup(subject.reading_hint))
    return t


class ItemInfo(VerticalScroll):
    DEFAULT_CSS = """
    ItemInfo { height: 1fr; display: none; padding: 0 2; border-top: solid $panel-lighten-2; }
    ItemInfo.-visible { display: block; }
    """

    def compose(self):
        yield Static(id="info-body")

    def show(self, subject: Subject, synonyms: list[str] = (), lookup=None) -> None:
        self.query_one("#info-body", Static).update(subject_details(subject, synonyms, lookup))
        self.scroll_home(animate=False)

    @property
    def visible(self) -> bool:
        return self.has_class("-visible")

    def set_visible(self, visible: bool) -> None:
        self.set_class(visible, "-visible")
