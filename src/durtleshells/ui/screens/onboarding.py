"""First launch: ask for the API token and validate it with GET /user."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.widgets import Input, Static

from ...api.client import ApiError, AuthError, NetworkError
from .base import DurtleScreen

INTRO = """[b]Welcome to durtleshells[/b]

Paste your WaniKani [b]API token (v2)[/b] and press Enter.
Create one at https://www.wanikani.com/settings/personal_access_tokens with the
permissions [i]reviews:create[/i] and [i]assignments:start[/i] so reviews and lessons can be sent.

The token is stored in ~/.config/durtleshells/config.toml (mode 0600).
WANIKANI_API_TOKEN in the environment overrides it."""


class OnboardingScreen(DurtleScreen):
    NAME = "setup"
    DEFAULT_CSS = """
    OnboardingScreen #onboarding { width: 90; height: auto; padding: 1 2; border: round $accent; }
    OnboardingScreen #token { margin-top: 1; }
    OnboardingScreen #token-status { margin-top: 1; height: auto; }
    OnboardingScreen #token-status.-error { color: $error; }
    OnboardingScreen Center { height: 1fr; align: center middle; }
    """

    def __init__(self, error: str | None = None) -> None:
        super().__init__()
        self.initial_error = error

    def compose_body(self) -> ComposeResult:
        with Center(), Vertical(id="onboarding"):
            yield Static(INTRO)
            yield Input(placeholder="API token", password=True, id="token")
            yield Static(self.initial_error or "", id="token-status",
                         classes="-error" if self.initial_error else "")

    def on_mount(self) -> None:
        self.query_one("#token", Input).focus()

    def _status(self, text: str, error: bool = False) -> None:
        status = self.query_one("#token-status", Static)
        status.update(text)
        status.set_class(error, "-error")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "token":
            return
        event.stop()
        token = event.value.strip()
        if not token:
            self._status("Please paste a token.", error=True)
            return
        self._status("Checking token with WaniKani…")
        event.input.disabled = True
        try:
            user = await self.app.validate_token(token)
        except AuthError:
            self._status("WaniKani rejected this token (401). Check it and try again.", error=True)
        except NetworkError:
            self._status("Can't reach WaniKani — are you online? Try again.", error=True)
        except ApiError as exc:
            self._status(f"WaniKani error: {exc}", error=True)
        else:
            self._status(f"Hello {user.username}! Saving token…")
            await self.app.token_accepted(token)
            return
        finally:
            if event.input.is_attached:
                event.input.disabled = False
                event.input.focus()

    def close(self, force: bool = False) -> None:
        self.app.exit()
