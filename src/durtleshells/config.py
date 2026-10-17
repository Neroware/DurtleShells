"""TOML config, token resolution and the typed settings schema used by ``:set``."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from . import paths

TOKEN_ENV = "WANIKANI_API_TOKEN"


class SettingError(ValueError):
    """Raised for unknown keys or invalid values (shown Vim-style on the command line)."""


@dataclass(frozen=True)
class Setting:
    name: str
    kind: type  # bool, int or str (enum when choices is set)
    default: Any
    help: str
    choices: tuple[str, ...] = ()
    minimum: int | None = None

    def parse(self, raw: str) -> Any:
        raw = raw.strip()
        if self.kind is bool:
            low = raw.lower()
            if low in ("true", "on", "yes", "1"):
                return True
            if low in ("false", "off", "no", "0"):
                return False
            raise SettingError(f"E474: Invalid argument: {self.name}={raw} (expected true/false)")
        if self.kind is int:
            try:
                value = int(raw)
            except ValueError:
                raise SettingError(f"E521: Number required: {self.name}={raw}") from None
            if self.minimum is not None and value < self.minimum:
                raise SettingError(f"E474: Invalid argument: {self.name} must be ≥ {self.minimum}")
            return value
        if self.choices and raw not in self.choices:
            raise SettingError(
                f"E474: Invalid argument: {self.name}={raw} (one of {', '.join(self.choices)})"
            )
        return raw

    def validate(self, value: Any) -> Any:
        """Validate a value loaded from TOML; fall back to the default when it's bad."""
        if value is None:
            return self.default
        if self.kind is bool:
            return value if isinstance(value, bool) else self.default
        if self.kind is int:
            if isinstance(value, bool) or not isinstance(value, int):
                return self.default
            if self.minimum is not None and value < self.minimum:
                return self.default
            return value
        if not isinstance(value, str) or (self.choices and value not in self.choices):
            return self.default
        return value

    def format(self, value: Any) -> str:
        if value is None:
            return "(WaniKani default)"
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)


REVIEW_ORDERS = ("random", "level", "level_desc", "srs", "type", "oldest")
LESSON_ORDERS = ("level", "type", "random")

SETTINGS: dict[str, Setting] = {
    s.name: s
    for s in (
        Setting("flick", bool, True, "show the flick keyboard during reading questions"),
        Setting("order", str, "random", "review order", REVIEW_ORDERS),
        Setting("lesson_order", str, "level", "lesson order", LESSON_ORDERS),
        Setting("first", str, "meaning", "which half is asked first", ("meaning", "reading", "random")),
        Setting("lesson_batch", int, None, "lessons per batch (default: WaniKani preference)", minimum=1),
        Setting("wrapup_mode", str, "started", "started = finish half-done items; count = also N more", ("started", "count")),
        Setting("wrapup_count", int, 10, "extra items in wrapup_mode=count", minimum=0),
        Setting("typo_tolerance", bool, True, "accept close matches for meanings"),
        Setting("ignore_mode", str, "immediate", "after ignoring: re-ask immediately or later", ("immediate", "later")),
    )
}


def default_settings() -> dict[str, Any]:
    return {name: s.default for name, s in SETTINGS.items()}


@dataclass
class Config:
    path: Path
    api_token: str | None = None
    settings: dict[str, Any] = field(default_factory=default_settings)

    # ---- persistence -------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or paths.config_file()
        data: dict[str, Any] = {}
        if path.exists():
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        settings = default_settings()
        raw = data.get("settings", {})
        if isinstance(raw, Mapping):
            for name, setting in SETTINGS.items():
                settings[name] = setting.validate(raw.get(name))
        token = data.get("api_token")
        return cls(path=path, api_token=token if isinstance(token, str) and token else None,
                   settings=settings)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc: dict[str, Any] = {}
        if self.api_token:
            doc["api_token"] = self.api_token
        # TOML has no null: omit unset (None) values.
        doc["settings"] = {k: v for k, v in self.settings.items() if v is not None}
        data = tomli_w.dumps(doc).encode()
        # Create with 0600 from the start so the token is never world-readable.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.chmod(self.path, 0o600)

    # ---- token -------------------------------------------------------------

    def resolve_token(self, env: Mapping[str, str] | None = None) -> str | None:
        env = os.environ if env is None else env
        token = env.get(TOKEN_ENV, "").strip()
        return token or self.api_token

    # ---- settings ----------------------------------------------------------

    def get(self, name: str) -> Any:
        if name not in SETTINGS:
            raise SettingError(f"E518: Unknown option: {name}")
        return self.settings[name]

    def set(self, name: str, raw: str) -> Any:
        if name not in SETTINGS:
            raise SettingError(f"E518: Unknown option: {name}")
        value = SETTINGS[name].parse(raw)
        self.settings[name] = value
        return value

    def apply_set_command(self, arg: str) -> str:
        """Apply one ``:set`` argument Vim-style and return the message to display.

        Supports ``key=value``, ``key?``, ``key`` (bool on / show value), ``nokey``,
        ``key!`` (toggle bool).
        """
        arg = arg.strip()
        if "=" in arg:
            name, raw = arg.split("=", 1)
            name = name.strip()
            value = self.set(name, raw)
            return f"{name}={SETTINGS[name].format(value)}"
        if arg.endswith("?"):
            name = arg[:-1]
            return f"{name}={SETTINGS[name].format(self.get(name))}" if name in SETTINGS else self._unknown(name)
        if arg.endswith("!"):
            name = arg[:-1]
            self._require_bool(name)
            self.settings[name] = not self.settings[name]
            return f"{name}={SETTINGS[name].format(self.settings[name])}"
        if arg.startswith("no") and arg[2:] in SETTINGS:
            name = arg[2:]
            self._require_bool(name)
            self.settings[name] = False
            return f"{name}=false"
        if arg in SETTINGS:
            if SETTINGS[arg].kind is bool:
                self.settings[arg] = True
            return f"{arg}={SETTINGS[arg].format(self.settings[arg])}"
        return self._unknown(arg)

    def _require_bool(self, name: str) -> None:
        if name not in SETTINGS:
            raise SettingError(f"E518: Unknown option: {name}")
        if SETTINGS[name].kind is not bool:
            raise SettingError(f"E474: Invalid argument: {name} is not a boolean")

    @staticmethod
    def _unknown(name: str) -> str:
        raise SettingError(f"E518: Unknown option: {name}")
