"""Start screen: counts, 24h forecast, SRS distribution and sync state."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from ...timefmt import parse
from .base import DurtleScreen

SRS_COLORS = {
    "Apprentice": "#dd0093", "Guru": "#882d9e", "Master": "#294ddb",
    "Enlightened": "#0093dd", "Burned": "#a0a0a0",
}


class DashboardScreen(DurtleScreen):
    NAME = "dashboard"
    DEFAULT_CSS = """
    DashboardScreen #dash { padding: 1 2; height: 1fr; }
    DashboardScreen #title { height: auto; margin-bottom: 1; }
    DashboardScreen #counts { height: 5; }
    DashboardScreen .count { width: 24; height: 5; content-align: center middle; text-style: bold; margin-right: 2; }
    DashboardScreen #lessons-count { background: #FF00AA; color: white; }
    DashboardScreen #reviews-count { background: #00AAFF; color: white; }
    DashboardScreen #details { height: 1fr; margin-top: 1; }
    DashboardScreen #forecast { width: 44; }
    DashboardScreen #srs { width: 1fr; }
    DashboardScreen #sync-state { height: auto; color: $text-muted; }
    DashboardScreen #footer { height: 2; color: $text-muted; }
    """
    BINDINGS = [
        Binding("r", "reviews", "reviews", show=False),
        Binding("l", "lessons", "lessons", show=False),
        Binding("s", "sync", "sync", show=False),
        Binding("k", "practice", "flick practice", show=False),
        Binding("q", "quit", "quit", show=False),
    ]

    def compose_body(self) -> ComposeResult:
        with Vertical(id="dash"):
            yield Static(id="title")
            with Horizontal(id="counts"):
                yield Static(id="lessons-count", classes="count")
                yield Static(id="reviews-count", classes="count")
            with Horizontal(id="details"):
                yield Static(id="forecast")
                yield Static(id="srs")
            yield Static(id="sync-state")
            yield Static(id="footer")

    def on_mount(self) -> None:
        self.refresh_data()

    def on_screen_resume(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        app = self.app
        repo = app.repo
        if repo is None:
            return
        now = app.now()
        user = repo.user()
        title = Text("durtleshells", style="bold")
        if user:
            title.append(f"  ·  {user.username}  ·  level {user.level}", style="dim")
        self.query_one("#title", Static).update(title)
        lessons = len(app.lesson_candidates())
        reviews = len(repo.available_reviews(now))
        self.query_one("#lessons-count", Static).update(Text(f"{lessons}\nLessons  [l]"))
        self.query_one("#reviews-count", Static).update(Text(f"{reviews}\nReviews  [r]"))
        self.query_one("#forecast", Static).update(self._forecast(now))
        self.query_one("#srs", Static).update(self._srs())
        self.query_one("#sync-state", Static).update(self._sync_state())
        s = app.config.settings
        self.query_one("#footer", Static).update(Text(
            "[r] reviews  [l] lessons  [k] flick practice  [s] sync  [?] help  [:] command  [q] quit\n"
            f"order: {s['order']} · lessons: {s['lesson_order']} · first: {s['first']}"
        ))

    def _forecast(self, now) -> Table:
        t = Table(title="Next 24 hours", title_justify="left", box=None, show_header=False, padding=(0, 1))
        t.add_column(justify="right", style="dim")
        t.add_column()
        t.add_column(justify="right")
        t.add_column(justify="right", style="dim")
        rows = [(h, c) for h, c in self.app.repo.forecast(now) if c]
        if not rows:
            t.add_row("", Text("no reviews coming up", style="dim"), "", "")
            return t
        peak = max(c for _, c in rows)
        total = 0
        for hour, count in rows[:16]:
            total += count
            bar = "█" * max(1, round(16 * count / peak))
            t.add_row(hour.astimezone().strftime("%a %H:00"), Text(bar, style="#00AAFF"),
                      f"+{count}", f"{total}")
        return t

    def _srs(self) -> Table:
        t = Table(title="SRS", title_justify="left", box=None, show_header=False, padding=(0, 1))
        t.add_column()
        t.add_column(justify="right")
        for name, count in self.app.repo.srs_distribution().items():
            t.add_row(Text(name, style=f"bold {SRS_COLORS[name]}"), str(count))
        return t

    def _sync_state(self) -> Text:
        app = self.app
        text = Text()
        if app.sync_progress:
            text.append(app.sync_progress + "  ", style="bold")
        last = app.repo.meta("last_sync_at")
        if last:
            dt = parse(last)
            text.append(f"Last sync: {dt.astimezone().strftime('%Y-%m-%d %H:%M:%S')}" if dt else "")
        elif not app.sync_progress:
            text.append("Not synced yet — press s")
        pending = app.repo.outbox_count()
        if pending:
            text.append(f"  ·  {pending} answer(s) queued", style="yellow")
        return text

    def action_reviews(self) -> None:
        self.app.start_reviews()

    def action_lessons(self) -> None:
        self.app.start_lessons()

    def action_practice(self) -> None:
        self.app.start_practice()

    def action_sync(self) -> None:
        self.app.request_sync(manual=True)

    def action_quit(self) -> None:
        self.app.request_quit()
