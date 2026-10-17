"""Pilot tests driving the whole app headless against a mocked WaniKani."""

import json
import random
from datetime import UTC, datetime

import httpx
import pytest

from durtleshells.api.client import TokenBucket, WaniKaniClient
from durtleshells.config import Config
from durtleshells.domain.flick import Direction
from durtleshells.domain.session import Half, State
from durtleshells.store.db import connect
from durtleshells.store.repo import Repo
from durtleshells.ui.app import DurtleApp
from durtleshells.ui.screens.dashboard import DashboardScreen
from durtleshells.ui.screens.lesson import LessonScreen
from durtleshells.ui.screens.quiz import QuizScreen
from durtleshells.ui.screens.summary import SummaryScreen
from durtleshells.ui.widgets.answer import AnswerInput
from durtleshells.ui.widgets.flick import KEY_H, KEY_W, FlickKeyboard, key_origin
from durtleshells.ui.widgets.statusline import CommandLine

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
SIZE = (110, 48)


def assignment(aid, sid, obj, started=True):
    return {"id": aid, "object": "assignment", "data_updated_at": "2026-10-17T10:00:00.000000Z", "data": {
        "subject_id": sid, "subject_type": obj, "srs_stage": 1 if started else 0,
        "unlocked_at": "2026-10-01T00:00:00.000000Z",
        "started_at": "2026-10-01T00:00:00.000000Z" if started else None,
        "available_at": "2026-10-17T11:00:00.000000Z" if started else None,
        "burned_at": None, "hidden": False}}


async def _nosleep(_s):
    return None


class FakeWaniKani:
    """httpx MockTransport handler: offline unless ``online`` is set."""

    def __init__(self):
        self.online = False
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.online:
            raise httpx.ConnectError("offline", request=request)
        path = request.url.path.removeprefix("/v2/")
        if path == "user":
            return httpx.Response(200, json={"data": {"id": "u", "username": "tester", "level": 1,
                                                      "preferences": {"lessons_batch_size": 3},
                                                      "subscription": {"max_level_granted": 3}}})
        if request.method == "GET":
            return httpx.Response(200, json={"object": "collection", "data_updated_at": None,
                                             "total_count": 0, "pages": {"per_page": 500, "next_url": None},
                                             "data": []})
        if path == "reviews":
            body = json.loads(request.content)["review"]
            return httpx.Response(201, json={"id": 1, "data": body, "resources_updated": {}})
        if path.endswith("/start"):
            aid = int(path.split("/")[1])
            return httpx.Response(200, json=assignment(aid, 1, "radical"))
        return httpx.Response(404)


@pytest.fixture
def env(tmp_path, subject_resources):
    db = tmp_path / "d.db"
    repo = Repo(connect(db))
    repo.upsert_subjects(subject_resources)
    repo.set_user({"id": "u", "username": "tester", "level": 1,
                   "preferences": {"lessons_batch_size": 3}, "subscription": {"max_level_granted": 3}})
    # reviews: 大 (kanji), 一人 (vocab), これ (kana vocab); lessons: 人 kanji, 一 radical, ホテル
    repo.upsert_assignments([
        assignment(1, 453, "kanji"), assignment(2, 2477, "vocabulary"), assignment(3, 9179, "kana_vocabulary"),
        assignment(11, 444, "kanji", started=False), assignment(12, 1, "radical", started=False),
        assignment(13, 9178, "kana_vocabulary", started=False),
    ])
    server = FakeWaniKani()

    def factory(token):
        return WaniKaniClient(token, transport=httpx.MockTransport(server), sleep=_nosleep,
                              bucket=TokenBucket(sleep=_nosleep))

    def make(autosync=False, **settings):
        cfg = Config(path=tmp_path / "config.toml", api_token="tok")
        cfg.settings.update(settings)
        return DurtleApp(cfg, db_path=db, token="tok", client_factory=factory, clock=lambda: NOW,
                         autosync=autosync, rng=random.Random(3))

    make.server = server
    make.db = db
    make.tmp = tmp_path
    return make


async def type_text(pilot, text):
    from textual.keys import _character_to_key

    await pilot.press(*[_character_to_key(c) if not c.isalnum() else c for c in text])


def quiz(app) -> QuizScreen:
    assert isinstance(app.screen, QuizScreen), app.screen
    return app.screen


async def answer_current(pilot, app, correct=True):
    """Type the right (or a wrong) answer for whatever is being asked."""
    q = quiz(app).session.question
    subject = q.item.subject
    if q.half is Half.MEANING:
        text = subject.primary_meaning.lower() if correct else "zzzzzz"
    else:
        reading = subject.primary_reading
        text = reading if correct else "ぬぬぬ"
    app.screen.answer.value = text
    await pilot.press("enter")


# ---- dashboard / shell ------------------------------------------------------

async def test_dashboard_offline(env):
    app = env(autosync=True)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.2)
        assert isinstance(app.screen, DashboardScreen)
        text = str(app.screen.query_one("#reviews-count").render())
        assert "3" in text
        assert "3" in str(app.screen.query_one("#lessons-count").render())
        assert app.online is False
        status = app.status_info(app.screen).plain
        assert "offline" in status and "NORMAL" in status


async def test_set_persists(env):
    app = env()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("colon")
        assert app.screen.mode == "COMMAND"
        await type_text(pilot, "set order=level")
        await pilot.press("enter")
        assert app.config.settings["order"] == "level"
    assert Config.load(env.tmp / "config.toml").settings["order"] == "level"


async def test_unknown_command_and_bad_value(env):
    app = env()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("colon")
        await type_text(pilot, "frobnicate")
        await pilot.press("enter")
        msg = app.screen.query_one("#cmd-msg")
        assert "E492" in str(msg.render()) and msg.has_class("-error")
        await pilot.press("colon")
        await type_text(pilot, "set order=sideways")
        await pilot.press("enter")
        assert "E474" in str(msg.render())


async def test_tab_completion(env):
    app = env()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("colon")
        await type_text(pilot, "set ord")
        await pilot.press("tab")
        inp = app.screen.query_one("#cmd-input")
        assert inp.value == "set order"
        await type_text(pilot, "=le")
        await pilot.press("tab")
        assert inp.value == "set order=level"
        await pilot.press("tab")
        assert inp.value == "set order=level_desc"
        await pilot.press("escape")
        assert not app.screen.query_one(CommandLine).active


# ---- reviews ----------------------------------------------------------------

async def test_modes_in_quiz(env):
    app = env()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        q = quiz(app)
        assert q.mode == "INSERT"
        await pilot.press("escape")
        assert q.mode == "NORMAL"
        await pilot.press("i")
        assert q.mode == "INSERT"


async def test_review_session_end_to_end(env):
    app = env(order="type", first="meaning")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        s = quiz(app).session
        # shake: kana in a meaning answer
        assert s.question.half is Half.MEANING
        app.screen.answer.value = "だい"
        await pilot.press("enter")
        assert s.state is State.ASKING
        assert "meaning" in str(app.screen.query_one("#feedback").render())
        # incorrect, then move on
        await answer_current(pilot, app, correct=False)
        assert s.state is State.ANSWERED
        assert app.screen.answer.has_class("-incorrect")
        assert app.screen.query_one("#info").visible
        await pilot.press("enter")
        # finish everything correctly; use a typo once on a meaning
        typo_done = False
        while not s.done:
            q = s.question
            if q.half is Half.MEANING and not typo_done and len(q.item.subject.primary_meaning) >= 5:
                app.screen.answer.value = q.item.subject.primary_meaning.lower()[:-1] + "x"
                await pilot.press("enter")
                assert app.screen.answer.has_class("-typo")
                typo_done = True
                await pilot.press("enter")
                continue
            await answer_current(pilot, app)
            await pilot.press("enter")
        await pilot.pause()
        assert typo_done
        assert isinstance(app.screen, SummaryScreen)
        repo = Repo(connect(env.db))
        entries = repo.outbox()
        assert [e.kind for e in entries] == ["review"] * 3
        assert sum(e.payload["incorrect_meaning_answers"] for e in entries) == 1
        assert all(e.payload["created_at"] == "2026-10-17T12:00:00.000000Z" for e in entries)
        await pilot.press("enter")
        assert isinstance(app.screen, DashboardScreen)
        assert app.repo.available_reviews(NOW) == []


async def test_romaji_live_conversion(env):
    app = env(first="reading", order="type")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        s = quiz(app).session
        assert s.question.item.subject.characters == "大" and s.question.half is Half.READING
        await type_text(pilot, "dai")
        assert app.screen.answer.value == "だい"
        await type_text(pilot, "n")
        assert app.screen.answer.value == "だいn"
        await pilot.press("enter")  # trailing n → ん on submit → wrong, but in kana
        assert s.state is State.ANSWERED
        assert app.screen.answer.value == "だいん"


async def test_ignore_answer(env):
    app = env(order="type")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        s = quiz(app).session
        item = s.question.item
        await answer_current(pilot, app, correct=False)
        assert item.incorrect_meaning + item.incorrect_reading == 1
        await pilot.press("u")
        assert s.state is State.ASKING
        assert item.incorrect_meaning + item.incorrect_reading == 0
        assert app.screen.answer.value == ""
        assert "ignored" in str(app.screen.query_one("#cmd-msg").render())


async def test_wrapup_command(env):
    app = env(order="type")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        s = quiz(app).session
        await answer_current(pilot, app)
        await pilot.press("enter")  # first item half done (kanji has a reading)
        await pilot.press("escape", "colon")
        await type_text(pilot, "wrap")
        await pilot.press("enter")
        assert s.wrapup
        assert "WRAP-UP" in app.status_info(app.screen).plain
        await answer_current(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SummaryScreen)
        assert len(s.completed) == 1


async def test_leave_session_confirm(env):
    app = env()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        await answer_current(pilot, app)
        await pilot.press("q")
        await pilot.press("y")
        assert isinstance(app.screen, DashboardScreen)


# ---- flick keyboard ---------------------------------------------------------

async def _flick(pilot, widget, row, col, dx=0, dy=0):
    x0, y0 = key_origin(row, col)
    cx, cy = x0 + KEY_W // 2, y0 + KEY_H // 2
    await pilot.mouse_down(widget, offset=(cx, cy))
    if dx or dy:
        await pilot.hover(widget, offset=(cx + dx, cy + dy))
    await pilot.mouse_up(widget, offset=(cx + dx, cy + dy))


async def test_flick_input(env):
    app = env(first="reading", order="type", flick=True)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        s = quiz(app).session
        assert s.question.half is Half.READING
        flick = app.screen.query_one(FlickKeyboard)
        assert flick.display and app.screen.query_one("#flick-wrap").display
        ans: AnswerInput = app.screen.answer
        await type_text(pilot, "ta")                 # romaji → た
        await _flick(pilot, flick, 1, 2, dx=4)       # は → へ
        await _flick(pilot, flick, 3, 0)             # modifier: へ → べ
        await _flick(pilot, flick, 2, 2, dy=-2)      # ら ↑ る
        assert ans.value == "たべる"
        await _flick(pilot, flick, 0, 3)             # ⌫
        assert ans.value == "たべ"
        await _flick(pilot, flick, 0, 0, dx=-4)      # あ ← い
        assert ans.value == "たべい"
        assert ans.has_focus  # flicking never steals focus


async def test_flick_hidden_for_meaning(env):
    app = env(first="meaning", order="type", flick=True)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        assert not app.screen.query_one("#flick-wrap").display


def test_flick_press_mapping():
    assert FlickKeyboard.press(0, 0, Direction.UP).text == "う"
    assert FlickKeyboard.press(3, 1, Direction.DOWN).text is None  # わ↓ has nothing
    assert FlickKeyboard.press(3, 0, Direction.CENTER).action == "modifier"
    assert FlickKeyboard.press(2, 3, Direction.CENTER).action == "submit"


# ---- lessons ----------------------------------------------------------------

async def test_lesson_flow(env):
    app = env(lesson_order="level")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("l")
        assert isinstance(app.screen, LessonScreen)
        lesson = app.screen
        assert len(lesson.batch) == 3
        assert lesson.batch[0][1].object == "radical"  # level order: radical → kanji → vocab
        await pilot.press("l", "h", "j", "k")
        for _ in range(10):
            if not isinstance(app.screen, LessonScreen):
                break
            await pilot.press("enter")
        s = quiz(app).session
        assert s.kind == "lesson"
        while not s.done:
            await answer_current(pilot, app)
            await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SummaryScreen)
        repo = Repo(connect(env.db))
        assert sorted(e.assignment_id for e in repo.outbox()) == [11, 12, 13]
        assert {e.kind for e in repo.outbox()} == {"lesson_start"}
        assert app.lesson_candidates() == []


# ---- offline → online --------------------------------------------------------

async def test_queued_answers_sent_when_back_online(env):
    app = env()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r")
        s = quiz(app).session
        while not s.done:
            await answer_current(pilot, app)
            await pilot.press("enter")
        await pilot.pause()
        assert app.repo.outbox_count() == 3
        env.server.online = True
        start = len(env.server.requests)
        await app.sync_now(full=True)
        assert app.repo.outbox_count() == 0
        posted = [json.loads(r.content)["review"] for r in env.server.requests
                  if r.url.path.endswith("/reviews")]
        assert len(posted) == 3
        assert all(p["created_at"] == "2026-10-17T12:00:00.000000Z" for p in posted)
        # the outbox is flushed before the incremental sync starts
        online = env.server.requests[start:]
        first_get = next(i for i, r in enumerate(online) if r.method == "GET")
        last_post = max(i for i, r in enumerate(online) if r.method == "POST")
        assert last_post < first_get


async def test_onboarding_rejects_then_accepts(env, tmp_path):
    cfg = Config(path=tmp_path / "fresh.toml")
    server = env.server

    def factory(token):
        def handler(request):
            if token != "good":
                return httpx.Response(401, json={"error": "Unauthorized"})
            server.online = True
            return server(request)
        return WaniKaniClient(token, transport=httpx.MockTransport(handler), sleep=_nosleep,
                              bucket=TokenBucket(sleep=_nosleep))

    app = DurtleApp(cfg, db_path=env.db, token=None, client_factory=factory, autosync=False, clock=lambda: NOW)
    async with app.run_test(size=SIZE) as pilot:
        await type_text(pilot, "bad")
        await pilot.press("enter")
        await pilot.pause(0.1)
        status = app.screen.query_one("#token-status")
        assert "401" in str(status.render())
        inp = app.screen.query_one("#token")
        inp.value = "good"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, DashboardScreen)
    saved = Config.load(tmp_path / "fresh.toml")
    assert saved.api_token == "good"
    import stat
    assert stat.S_IMODE((tmp_path / "fresh.toml").stat().st_mode) == 0o600


async def test_quit_from_dashboard(env):
    app = env()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("q")
        await pilot.pause(0.1)
    assert app.return_code == 0 or app.return_code is None
    assert not app.is_running


async def test_quit_offline_with_pending_asks_first(env):
    app = env(autosync=True)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.1)
        app.sync.enqueue_review(1, 0, 0, "2026-10-17T11:30:00.000000Z")
        await pilot.press("colon")
        await type_text(pilot, "q")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert "queued" in str(app.screen.query_one("Static").render())
        await pilot.press("n")
        assert app.is_running
        await pilot.press("colon")
        await type_text(pilot, "q!")
        await pilot.press("enter")
        await pilot.pause(0.1)
    assert not app.is_running


# ---- flick practice ---------------------------------------------------------

async def test_flick_practice(env):
    from durtleshells.ui.screens.practice import PracticeScreen

    app = env()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("k")
        screen = app.screen
        assert isinstance(screen, PracticeScreen)
        assert screen.query_one("#flick-wrap").display
        subject = screen.subject
        assert subject is not None and subject.object == "vocabulary"
        await type_text(pilot, "zzz")
        await pilot.press("enter")
        assert not screen.solved and screen.attempted == 1
        screen.answer.value = subject.primary_reading
        await pilot.press("enter")
        assert screen.solved and screen.correct == 1
        await pilot.press("enter")  # next word
        assert not screen.solved
        await pilot.press("escape", "q")
        assert isinstance(app.screen, DashboardScreen)
        assert app.repo.outbox_count() == 0  # practice never reaches WaniKani
