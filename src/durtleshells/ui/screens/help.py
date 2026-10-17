"""Help screen: every key and command."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from ...config import SETTINGS
from .base import DurtleScreen

KEYS = [
    ("Dashboard", [
        ("r", "start reviews"), ("l", "start lessons"), ("k", "flick practice"),
        ("s", "sync now"),
        ("?", "this help"), ("q", "quit"),
    ]),
    ("Quiz (while asking)", [
        ("Enter", "submit answer"), ("Esc", "NORMAL mode (leave the input)"),
        ("i / a", "back to INSERT mode"), ("q", "leave the session (NORMAL mode)"),
        ("w", "toggle wrap-up (NORMAL mode)"),
        ("romaji", "converts live to kana in reading questions; UPPERCASE → katakana"),
        ("nn / n'", "ん (a final n becomes ん on submit)"),
    ]),
    ("Quiz (after answering)", [
        ("Enter", "next question"), ("u", "ignore answer (undo it)"),
        ("f", "toggle item info"), ("w", "toggle wrap-up"), (":", "command line"),
    ]),
    ("Lessons", [
        ("h / l  ← →", "previous / next page"), ("j / k  n / p", "next / previous item"),
        ("Enter", "next page; on the last item: start the quiz"), ("q", "back to the dashboard"),
    ]),
    ("Flick keyboard", [
        ("press + drag", "drag left/up/right/down from a key and release to type"),
        ("tap", "the key's centre kana"),
        ("゛゜小", "cycles the previous kana: か→が, は→ば→ぱ, つ→っ→づ, や→ゃ"),
        ("⌫ ␣ ⏎", "backspace, space (ignored), submit/next"),
        ("Konsole", "Shift+drag selects text instead of flicking — drag without Shift"),
    ]),
]

COMMANDS = [
    (":q  :quit", "leave the session / quit (:q! skips confirmation)"),
    (":sync", "flush queued answers, then sync with WaniKani"),
    (":reviews  :lessons", "start a review / lesson session"),
    (":flick  :practice", "type vocabulary readings with the flick keyboard (nothing is sent)"),
    (":wrap", "toggle wrap-up"),
    (":set key=value", "change a setting (saved immediately); :set key? shows it"),
    (":set flick  :set noflick  :set flick!", "booleans: on / off / toggle"),
    (":set", "list all settings"),
    (":help", "this help"),
]


def help_text() -> Table:
    outer = Table.grid(padding=(0, 2))
    outer.add_column()
    for title, rows in KEYS:
        t = Table(title=Text(title, style="bold"), title_justify="left", box=None, show_header=False)
        t.add_column(style="bold cyan", min_width=14)
        t.add_column()
        for k, v in rows:
            t.add_row(k, v)
        outer.add_row(t)
    t = Table(title=Text("Commands", style="bold"), title_justify="left", box=None, show_header=False)
    t.add_column(style="bold cyan", min_width=14)
    t.add_column()
    for k, v in COMMANDS:
        t.add_row(k, v)
    outer.add_row(t)
    t = Table(title=Text("Settings", style="bold"), title_justify="left", box=None, show_header=False)
    t.add_column(style="bold cyan", min_width=14)
    t.add_column()
    for s in SETTINGS.values():
        values = "|".join(s.choices) if s.choices else s.kind.__name__
        t.add_row(s.name, f"{s.help}  [{values}]")
    outer.add_row(t)
    return outer


class HelpScreen(DurtleScreen):
    NAME = "help"
    BINDINGS = [
        Binding("q", "dismiss_help", "close", show=False),
        Binding("escape", "dismiss_help", "close", show=False),
        Binding("enter", "dismiss_help", "close", show=False),
        Binding("j", "scroll(1)", show=False),
        Binding("k", "scroll(-1)", show=False),
    ]

    def compose_body(self) -> ComposeResult:
        with VerticalScroll(id="help"):
            yield Static(help_text())

    def action_dismiss_help(self) -> None:
        self.app.pop_screen()

    def action_scroll(self, delta: int) -> None:
        self.query_one("#help").scroll_relative(y=delta, animate=False)

    def action_help(self) -> None:
        pass

    def close(self, force: bool = False) -> None:
        self.app.pop_screen()
