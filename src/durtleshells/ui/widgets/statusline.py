"""Vim-style status line and command line."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static


class StatusLine(Static):
    DEFAULT_CSS = """
    StatusLine { height: 1; background: $panel; color: $text; }
    """

    def render(self) -> Text:
        app = self.app
        info = getattr(app, "status_info", None)
        if info is None:
            return Text("")
        return info(self.screen)


class CommandInput(Input):
    BINDINGS = [
        Binding("tab", "complete", "complete", show=False, priority=True),
        Binding("escape", "cancel", "cancel", show=False),
    ]

    class Cancelled(Message):
        pass

    class Completed(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(select_on_focus=False, **kwargs)
        self._cycle: list[str] = []
        self._cycle_index = 0
        self._completing = False

    def action_cancel(self) -> None:
        self.post_message(self.Cancelled())

    def action_complete(self) -> None:
        registry = getattr(self.app, "commands", None)
        if registry is None:
            return
        if not self._cycle or self.value not in self._cycle:
            self._cycle = registry.complete(self.value)
            self._cycle_index = -1
            if not self._cycle:
                self.app.bell()
                return
        self._cycle_index = (self._cycle_index + 1) % len(self._cycle)
        self.value = self._cycle[self._cycle_index]
        self.cursor_position = len(self.value)


class CommandLine(Widget):
    """Bottom row: shows messages, or the ``:`` input while a command is typed."""

    DEFAULT_CSS = """
    CommandLine { height: 1; layout: horizontal; }
    CommandLine #cmd-row { height: 1; display: none; }
    CommandLine.-active #cmd-row { display: block; }
    CommandLine.-active #cmd-msg { display: none; }
    CommandLine #cmd-colon { width: 1; height: 1; }
    CommandLine CommandInput { border: none; height: 1; padding: 0; width: 1fr; background: $surface; }
    CommandLine #cmd-msg { height: 1; width: 1fr; }
    CommandLine #cmd-msg.-error { color: $error; text-style: bold; }
    """

    class Submitted(Message):
        def __init__(self, line: str) -> None:
            super().__init__()
            self.line = line

    def compose(self):
        with Horizontal(id="cmd-row"):
            yield Static(":", id="cmd-colon")
            yield CommandInput(id="cmd-input", disabled=True)  # unfocusable until opened
        yield Static("", id="cmd-msg")

    def open(self, text: str = "") -> None:
        self._return_focus = self.screen.focused
        self.add_class("-active")
        inp = self.query_one(CommandInput)
        inp.disabled = False
        inp.value = text
        inp.cursor_position = len(text)
        inp.focus()

    def close(self) -> None:
        self.remove_class("-active")
        inp = self.query_one(CommandInput)
        inp.value = ""
        inp.disabled = True
        target = getattr(self, "_return_focus", None)
        if target is not None and target.is_attached and target.focusable:
            target.focus()
        else:
            self.screen.set_focus(None)

    @property
    def active(self) -> bool:
        return self.has_class("-active")

    def message(self, text: str, error: bool = False) -> None:
        msg = self.query_one("#cmd-msg", Static)
        msg.update(Text(text))
        msg.set_class(error, "-error")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        line = event.value
        self.close()
        self.post_message(self.Submitted(line))

    def on_command_input_cancelled(self, event: CommandInput.Cancelled) -> None:
        event.stop()
        self.close()
