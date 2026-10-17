"""Base screen: every screen gets the status line and the ``:`` command line."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen

from ..widgets.statusline import CommandLine, StatusLine


class DurtleScreen(Screen):
    NAME = ""
    AUTO_FOCUS = None  # screens focus explicitly; never the hidden command input

    BINDINGS = [
        Binding("colon", "command_line", "command", show=False),
        Binding("escape", "normal_mode", "normal mode", show=False),
        Binding("question_mark", "help", "help", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield from self.compose_body()
        yield StatusLine()
        yield CommandLine()

    def compose_body(self) -> ComposeResult:
        yield from ()

    # ---- mode / status -----------------------------------------------------

    @property
    def mode(self) -> str:
        from ..widgets.answer import AnswerInput
        from ..widgets.statusline import CommandInput

        focused = self.focused
        if isinstance(focused, CommandInput):
            return "COMMAND"
        if isinstance(focused, AnswerInput):
            return "INSERT"
        return "NORMAL"

    def refresh_status(self) -> None:
        for line in self.query(StatusLine):
            line.refresh()

    def on_descendant_focus(self, _event) -> None:
        self.refresh_status()

    def on_descendant_blur(self, _event) -> None:
        self.call_after_refresh(self.refresh_status)

    def message(self, text: str, error: bool = False) -> None:
        self.query_one(CommandLine).message(text, error)

    # ---- actions -----------------------------------------------------------

    def action_command_line(self) -> None:
        self.query_one(CommandLine).open()

    def action_normal_mode(self) -> None:
        self.set_focus(None)
        self.refresh_status()

    def action_help(self) -> None:
        self.app.action_help()

    async def on_command_line_submitted(self, event: CommandLine.Submitted) -> None:
        await self.app.run_command(event.line)

    def close(self, force: bool = False) -> None:
        """``:q`` on this screen. Overridden by session screens."""
        self.app.request_quit(force)

    def progress_text(self) -> str:
        return ""
