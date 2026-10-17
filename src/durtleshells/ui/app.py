"""DurtleApp: screens, the ``:`` command registry, status line and the sync worker."""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import App
from textual.screen import Screen

from .. import paths
from ..api.client import ApiError, AuthError, NetworkError, RateLimited, WaniKaniClient
from ..api.models import Assignment, Subject, User
from ..config import SETTINGS, Config, SettingError
from ..domain.ordering import order_lessons
from ..domain.session import ItemCompleted, Session, SessionItem
from ..store.db import connect
from ..store.repo import Repo
from ..store.sync import StaleSubmission, SyncEngine
from ..timefmt import iso, utcnow
from .commands import Command, CommandError, Registry, complete_set
from .screens.base import DurtleScreen
from .screens.confirm import ConfirmScreen
from .screens.dashboard import DashboardScreen
from .screens.help import HelpScreen
from .screens.lesson import LessonScreen
from .screens.onboarding import OnboardingScreen
from .screens.practice import MIN_PRACTICE_LEVEL, PracticeScreen
from .screens.quiz import QuizScreen

ClientFactory = Callable[[str], WaniKaniClient]

SYNC_INTERVAL = 300.0
BACKOFF_START = 30.0
BACKOFF_MAX = 300.0


class DurtleApp(App):
    TITLE = "durtleshells"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { background: $background; }
    """

    def __init__(
        self,
        config: Config,
        *,
        db_path: Path | str | None = None,
        token: str | None = None,
        client_factory: ClientFactory | None = None,
        clock: Callable[[], datetime] = utcnow,
        autosync: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.db_path = db_path or paths.db_file()
        self.token = token
        self.client_factory = client_factory or (lambda t: WaniKaniClient(t))
        self.now = clock
        self.autosync = autosync
        self.rng = rng or random.Random()
        self.repo: Repo | None = None
        self.client: WaniKaniClient | None = None
        self.sync: SyncEngine | None = None
        self.sync_progress = ""
        self._wake = asyncio.Event()
        self._want_sync = True
        self._syncing = False
        self._sync_task: asyncio.Task | None = None
        self.commands = Registry()
        self._register_commands()

    # ---- lifecycle ---------------------------------------------------------

    def on_mount(self) -> None:
        self.repo = Repo(connect(self.db_path))
        if self.token:
            self._start(self.token)
        else:
            self.push_screen(OnboardingScreen())

    def _start(self, token: str) -> None:
        assert self.repo is not None
        self.client = self.client_factory(token)
        self.sync = SyncEngine(self.repo, self.client, on_progress=self._on_progress, on_stale=self._on_stale)
        self.push_screen(DashboardScreen())
        if self.autosync:
            self._sync_task = asyncio.create_task(self._sync_loop())

    async def on_unmount(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
        if self.client:
            await self.client.aclose()

    async def validate_token(self, token: str) -> User:
        client = self.client_factory(token)
        try:
            return await client.get_user()
        finally:
            await client.aclose()

    async def token_accepted(self, token: str) -> None:
        self.config.api_token = token
        self.config.save()
        self.token = token
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None
        if self.client:
            await self.client.aclose()
        # Drop the onboarding screen(s) and start fresh.
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self._want_sync = True
        self._start(token)

    # ---- sync worker -------------------------------------------------------

    def _on_progress(self, text: str) -> None:
        self.sync_progress = text
        self.refresh_views(data=False)

    def _on_stale(self, stale: StaleSubmission) -> None:
        self.notify(stale.message, severity="warning", timeout=10, markup=False)

    def request_sync(self, manual: bool = False) -> None:
        self._want_sync = True
        self._wake.set()
        if manual and self.sync is not None:
            self.message("syncing…")

    def request_flush(self) -> None:
        self._wake.set()

    async def _sync_loop(self) -> None:
        backoff = BACKOFF_START
        while True:
            wait = SYNC_INTERVAL
            self._wake.clear()  # requests arriving during the sync wake the next round
            try:
                await self.sync_now(full=self._want_sync)
                backoff = BACKOFF_START
            except NetworkError:
                wait = backoff
                backoff = min(backoff * 2, BACKOFF_MAX)
            except AuthError:
                self._auth_failed()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep the worker alive whatever happens
                self.notify(f"sync failed: {exc}", severity="error", markup=False)
                wait = backoff
                backoff = min(backoff * 2, BACKOFF_MAX)
            try:
                await asyncio.wait_for(self._wake.wait(), wait)
            except TimeoutError:
                self._want_sync = True

    async def sync_now(self, full: bool = True) -> None:
        """Flush the outbox and (if ``full``) sync. Raises NetworkError when offline."""
        assert self.sync is not None and self.repo is not None
        if self._syncing:
            return
        self._syncing = True
        try:
            if full:
                await self.sync.run_once()
                self.repo.set_meta("last_sync_at", iso(self.now()))
                self._want_sync = False
            else:
                result = await self.sync.flush()
                if result.offline:
                    raise NetworkError("offline")
        except RateLimited:
            self.sync_progress = ""
            raise NetworkError("rate limited") from None
        except (NetworkError, ApiError):
            self.sync_progress = ""
            raise
        finally:
            self._syncing = False
            self.refresh_views()

    def _auth_failed(self) -> None:
        self.notify("WaniKani rejected the API token (401). Please enter a new one.", severity="error")
        self.push_screen(OnboardingScreen(error="Your token was rejected (invalid or revoked)."))

    # ---- state shown in views ---------------------------------------------

    @property
    def online(self) -> bool | None:
        return self.sync.online if self.sync else None

    def refresh_views(self, data: bool = True) -> None:
        screen = self.screen
        if isinstance(screen, DashboardScreen) and data:
            screen.refresh_data()
        elif isinstance(screen, DashboardScreen):
            screen.query_one("#sync-state").update(screen._sync_state())
        if isinstance(screen, DurtleScreen):
            screen.refresh_status()

    def status_info(self, screen: Screen) -> Text:
        t = Text()
        mode = screen.mode if isinstance(screen, DurtleScreen) else "NORMAL"
        if mode == "COMMAND":
            t.append("            ")
        else:
            t.append(f" -- {mode} -- ", style="bold reverse" if mode == "INSERT" else "bold")
            t.append(" ")
        name = getattr(screen, "NAME", "")
        if name:
            t.append(f"  {name}")
        progress = screen.progress_text() if isinstance(screen, DurtleScreen) else ""
        if progress:
            t.append(f"  {progress}")
        session = getattr(screen, "session", None)
        if isinstance(screen, QuizScreen) and session is not None and session.wrapup:
            t.append(f"  WRAP-UP · {session.wrapup_left} left", style="bold yellow")
        right = Text()
        pending = self.repo.outbox_count() if self.repo else 0
        if self._syncing:
            right.append("  ⇅ syncing", style="cyan")
        elif pending:
            right.append(f"  ⇅ {pending} pending", style="yellow")
        if self.online is False:
            right.append("  ○ offline", style="bold red")
        elif self.online:
            right.append("  ● online", style="green")
        user = self.repo.user() if self.repo else None
        if user:
            right.append(f"  Lv {user.level} ")
        width = max(0, screen.size.width - t.cell_len - right.cell_len)
        t.append(" " * width)
        t.append_text(right)
        return t

    def message(self, text: str, error: bool = False) -> None:
        screen = self.screen
        if isinstance(screen, DurtleScreen):
            screen.message(text, error)

    # ---- sessions ----------------------------------------------------------

    def lesson_candidates(self) -> list[Assignment]:
        assert self.repo is not None
        return [a for a in self.repo.available_lessons() if self.repo.subject(a.subject_id)]

    def _items(self, assignments: list[Assignment]) -> list[SessionItem]:
        assert self.repo is not None
        first = self.config.settings["first"]
        items = []
        for a in assignments:
            subject = self.repo.subject(a.subject_id)
            if subject is not None:
                items.append(SessionItem.build(a, subject, first, self.rng))
        return items

    def _session(self, items: list[SessionItem], kind: str, order: str) -> Session:
        s = self.config.settings
        return Session(
            items, kind=kind, order=order, rng=self.rng, clock=self.now,
            wrapup_mode=s["wrapup_mode"], wrapup_count=s["wrapup_count"], ignore_mode=s["ignore_mode"],
        )

    def _in_session(self) -> bool:
        return any(isinstance(s, (QuizScreen, LessonScreen)) for s in self.screen_stack)

    def start_reviews(self) -> None:
        assert self.repo is not None
        if self._in_session():
            self.message("E: already in a session", error=True)
            return
        items = self._items(self.repo.available_reviews(self.now()))
        if not items:
            self.message("No reviews available right now")
            return
        self.push_screen(QuizScreen(self._session(items, "review", self.config.settings["order"])))

    def start_lessons(self) -> None:
        assert self.repo is not None
        if self._in_session():
            self.message("E: already in a session", error=True)
            return
        candidates = self.lesson_candidates()
        if not candidates:
            self.message("No lessons available")
            return
        user = self.repo.user()
        size = self.config.settings["lesson_batch"] or (user.lessons_batch_size if user else 5)
        items = order_lessons(self._items(candidates), self.config.settings["lesson_order"], self.rng)
        by_id = {a.id: a for a in candidates}
        batch = [(by_id[item.assignment_id], item.subject) for item in items[:size]]
        self.push_screen(LessonScreen(batch))

    def start_practice(self) -> None:
        assert self.repo is not None
        if self._in_session() or isinstance(self.screen, PracticeScreen):
            self.message("E: finish the current session first", error=True)
            return
        user = self.repo.user()
        level = max(user.level if user else 1, MIN_PRACTICE_LEVEL)
        ids = self.repo.practice_subject_ids(level) or self.repo.practice_subject_ids(999)
        if not ids:
            self.message("No vocabulary synced yet — run :sync first", error=True)
            return
        self.push_screen(PracticeScreen(ids))

    def start_lesson_quiz(self, batch: list[tuple[Assignment, Subject]]) -> None:
        items = [SessionItem.build(a, s, self.config.settings["first"], self.rng) for a, s in batch]
        self.switch_screen(QuizScreen(self._session(items, "lesson", "random")))

    def record_completion(self, kind: str, done: ItemCompleted) -> None:
        assert self.sync is not None
        if kind == "review":
            self.sync.enqueue_review(done.assignment_id, done.incorrect_meaning,
                                     done.incorrect_reading, done.completed_at)
        else:
            self.sync.enqueue_lesson_start(done.assignment_id, done.completed_at)
        self.request_flush()

    def session_finished(self, kind: str) -> None:
        self.request_sync()

    # ---- quitting ----------------------------------------------------------

    def request_quit(self, force: bool = False) -> None:
        if force:
            self.exit()
            return
        self.run_worker(self._quit_flow(), exclusive=True, group="quit")

    async def _quit_flow(self) -> None:
        assert self.repo is not None
        if self.repo.outbox_count() and self.sync is not None and self.online is not False:
            self.message("sending queued answers…")
            with contextlib.suppress(NetworkError, ApiError, TimeoutError):
                await asyncio.wait_for(self.sync_now(full=False), 8)
        pending = self.repo.outbox_count()
        if not pending:
            self.exit()
            return

        def answer(ok: bool | None) -> None:
            if ok:
                self.exit()

        self.push_screen(
            ConfirmScreen(
                f"You're offline. {pending} answer(s) stay queued and will be sent "
                "the next time durtleshells is online.\n\nQuit anyway?"
            ),
            answer,
        )

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen())

    # ---- commands ----------------------------------------------------------

    async def run_command(self, line: str) -> None:
        try:
            await self.commands.run(line)
        except (CommandError, SettingError) as exc:
            self.message(str(exc), error=True)

    def _register_commands(self) -> None:
        r = self.commands
        r.register(Command("quit", self._cmd_quit, "leave the session / quit", aliases=("q",)))
        r.register(Command("sync", self._cmd_sync, "flush queued answers and sync"))
        r.register(Command("reviews", lambda a, b: self._cmd_start("review"), "start reviews"))
        r.register(Command("lessons", lambda a, b: self._cmd_start("lesson"), "start lessons"))
        r.register(Command("flick", self._cmd_flick, "practise the flick keyboard",
                           aliases=("practice",)))
        r.register(Command("wrap", self._cmd_wrap, "toggle wrap-up", aliases=("wrapup",)))
        r.register(Command("set", self._cmd_set, "change settings", args="key=value",
                           completions=complete_set))
        r.register(Command("help", lambda a, b: self.action_help(), "show help", aliases=("h",)))

    def _cmd_quit(self, arg: str, bang: bool) -> None:
        screen = self.screen
        if isinstance(screen, DurtleScreen):
            screen.close(force=bang)
        else:
            self.request_quit(bang)

    def _cmd_sync(self, arg: str, bang: bool) -> None:
        if self.sync is None:
            raise CommandError("E: not logged in yet")
        self.request_sync(manual=True)

    def _cmd_start(self, kind: str) -> None:
        if self.sync is None:
            raise CommandError("E: not logged in yet")
        if kind == "review":
            self.start_reviews()
        else:
            self.start_lessons()

    def _cmd_flick(self, arg: str, bang: bool) -> None:
        if self.repo is None:
            raise CommandError("E: not logged in yet")
        self.start_practice()

    def _cmd_wrap(self, arg: str, bang: bool) -> None:
        screen = self.screen
        if not isinstance(screen, QuizScreen):
            raise CommandError("E: wrap-up only works during a session")
        screen.toggle_wrapup()

    def _cmd_set(self, arg: str, bang: bool) -> None:
        if not arg:
            lines = [f"{n}={s.format(self.config.settings[n])}" for n, s in SETTINGS.items()]
            self.notify("\n".join(lines), title=":set", timeout=12, markup=False)
            return
        messages = []
        changed = []
        for part in arg.split():
            messages.append(self.config.apply_set_command(part))
            name = part.split("=")[0].rstrip("?!")
            if name.startswith("no") and name[2:] in SETTINGS:
                name = name[2:]
            if not part.endswith("?"):
                changed.append(name)
        if changed:
            self.config.save()
        self.message("  ".join(messages))
        screen = self.screen
        for name in changed:
            if isinstance(screen, QuizScreen):
                screen.settings_changed(name)
        if isinstance(screen, DashboardScreen):
            screen.refresh_data()
