"""The ``:`` command line: parsing, a name → handler registry and tab completion."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..config import SETTINGS

Handler = Callable[[str, bool], Awaitable[None] | None]  # (argument, bang)


class CommandError(Exception):
    """Shown Vim-style on the command line."""


@dataclass
class Command:
    name: str
    handler: Handler
    help: str
    aliases: tuple[str, ...] = ()
    args: str = ""
    completions: Callable[[str], list[str]] | None = field(default=None, repr=False)


def parse(line: str) -> tuple[str, bool, str]:
    """Split ``"set order=level"`` into ``("set", False, "order=level")``; ``"q!"`` → bang."""
    line = line.strip().lstrip(":").strip()
    if not line:
        return "", False, ""
    head, _, arg = line.partition(" ")
    bang = head.endswith("!")
    if bang:
        head = head[:-1]
    return head, bang, arg.strip()


class Registry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}
        self._names: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        self._commands[command.name] = command
        for name in (command.name, *command.aliases):
            self._names[name] = command

    def __iter__(self):
        return iter(self._commands.values())

    def resolve(self, name: str) -> Command:
        if name in self._names:
            return self._names[name]
        matches = {c.name for n, c in self._names.items() if n.startswith(name)}
        if len(matches) == 1:
            return self._commands[matches.pop()]
        raise CommandError(f"E492: Not an editor command: {name}")

    async def run(self, line: str) -> None:
        name, bang, arg = parse(line)
        if not name:
            return
        command = self.resolve(name)
        result = command.handler(arg, bang)
        if result is not None:
            await result

    def complete(self, line: str) -> list[str]:
        """Candidate full lines for ``line`` (without the leading ``:``)."""
        if " " not in line:
            return sorted({c.name for n, c in self._names.items() if n.startswith(line)})
        head, _, arg = line.partition(" ")
        try:
            command = self.resolve(head.rstrip("!"))
        except CommandError:
            return []
        if command.completions is None:
            return []
        return [f"{head} {c}" for c in command.completions(arg)]


def complete_set(arg: str) -> list[str]:
    if "=" in arg:
        key, _, value = arg.partition("=")
        setting = SETTINGS.get(key)
        if setting is None:
            return []
        choices = setting.choices or (("true", "false") if setting.kind is bool else ())
        return [f"{key}={c}" for c in choices if c.startswith(value)]
    return sorted(n for n in SETTINGS if n.startswith(arg))
