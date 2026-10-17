import random
from datetime import UTC, datetime

import pytest

from durtleshells.api.models import Assignment, Subject
from durtleshells.domain.checker import Result, Verdict
from durtleshells.domain.ordering import order_lessons, order_reviews
from durtleshells.domain.session import Half, Session, SessionItem, State

OK = Verdict(Result.CORRECT)
TYPO = Verdict(Result.CORRECT_TYPO, "close")
BAD = Verdict(Result.INCORRECT)
SHAKE = Verdict(Result.SHAKE, "kana please")


def make_subject(sid, obj="kanji", level=1, position=0):
    data = {
        "level": level, "characters": f"字{sid}", "slug": str(sid), "lesson_position": position,
        "meanings": [{"meaning": "M", "primary": True, "accepted_answer": True}],
        "readings": [] if obj in ("radical", "kana_vocabulary")
        else [{"reading": "じ", "primary": True, "accepted_answer": True, "type": "onyomi"}],
    }
    return Subject.from_data(sid, obj, data)


def make_item(sid, obj="kanji", level=1, srs=1, available="2026-01-01T00:00:00.000000Z", first="meaning", position=0):
    a = Assignment.from_data(sid * 10, {
        "subject_id": sid, "subject_type": obj, "srs_stage": srs, "available_at": available,
    })
    return SessionItem.build(a, make_subject(sid, obj, level, position), first, random.Random(0))


def clock():
    return datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def session(items, **kw):
    kw.setdefault("rng", random.Random(1))
    return Session(items, clock=clock, **kw)


def answer(s, verdict):
    s.submit(verdict)
    return s.next()


def test_halves_back_to_back():
    s = session([make_item(i) for i in range(1, 6)])
    q1 = s.question
    assert q1.half is Half.MEANING
    answer(s, OK)
    q2 = s.question
    assert q2.item is q1.item and q2.half is Half.READING
    done = answer(s, OK)
    assert len(done) == 1 and done[0].assignment_id == q1.item.assignment_id
    assert done[0].incorrect_meaning == 0 and done[0].incorrect_reading == 0
    assert done[0].completed_at == "2026-10-17T12:00:00.000000Z"


def test_reading_first():
    s = session([make_item(1, first="reading")])
    assert s.question.half is Half.READING


def test_radical_and_kana_vocab_meaning_only():
    for obj in ("radical", "kana_vocabulary"):
        s = session([make_item(1, obj)])
        assert s.question.half is Half.MEANING
        done = answer(s, OK)
        assert len(done) == 1
        assert s.done


def test_wrong_half_comes_back_later_with_counts():
    items = [make_item(i) for i in range(1, 13)]
    s = session(items)
    first = s.question.item
    answer(s, BAD)  # meaning wrong → item goes back to the pool
    assert s.question.item is not first
    draws = 0
    while s.question.item is not first:
        q = s.question
        answer(s, OK)
        if s.question is None or s.question.item is not q.item:
            draws += 1
    assert 3 <= draws <= 10
    assert s.question.half is Half.MEANING
    answer(s, OK)
    answer(s, BAD)  # reading wrong once
    while s.question.item is not first:
        answer(s, OK)
    assert s.question.half is Half.READING  # meaning was already right
    done = answer(s, OK)
    assert done[0].incorrect_meaning == 1 and done[0].incorrect_reading == 1


def test_shake_stays_asking():
    s = session([make_item(1)])
    q = s.question
    s.submit(SHAKE)
    assert s.state is State.ASKING
    assert s.question.item is q.item and s.question.half is q.half
    assert s.questions_answered == 0


def test_stats():
    s = session([make_item(1, "radical"), make_item(2, "radical")])
    answer(s, BAD)
    answer(s, OK)
    answer(s, OK)
    assert s.done
    assert s.questions_answered == 3 and s.questions_correct == 2
    assert len(s.completed) == 2
    assert s.remaining == 0
    assert list(s.wrong_items) and len(s.wrong_items) == 1


def test_typo_counts_as_correct():
    s = session([make_item(1, "radical")])
    assert answer(s, TYPO)[0].incorrect_meaning == 0


# ---- ignore ---------------------------------------------------------------

@pytest.mark.parametrize("verdict", [OK, BAD])
@pytest.mark.parametrize("half_index", [0, 1])
def test_ignore_restores_state(verdict, half_index):
    s = session([make_item(1), make_item(2)])
    item = s.question.item
    if half_index == 1:
        answer(s, OK)
    before = (list(item.remaining), item.incorrect_meaning, item.incorrect_reading,
              s.questions_answered, s.questions_correct)
    q = s.question
    s.submit(verdict)
    assert s.ignore()
    assert s.state is State.ASKING
    after = (list(item.remaining), item.incorrect_meaning, item.incorrect_reading,
             s.questions_answered, s.questions_correct)
    assert after == before
    assert s.question.item is q.item and s.question.half is q.half


def test_ignored_completing_answer_never_completes():
    s = session([make_item(1, "radical"), make_item(2, "radical")])
    first = s.question.item
    s.submit(OK)
    s.ignore()
    assert s.completed == []
    assert s.question.item is first
    s.submit(BAD)
    assert s.next() == []
    assert s.completed == []


def test_ignore_only_in_answered_state():
    s = session([make_item(1)])
    assert not s.ignore()
    answer(s, OK)
    assert not s.ignore()  # already moved on


def test_ignore_later_requeues():
    items = [make_item(i, "radical") for i in range(1, 6)]
    s = session(items, ignore_mode="later")
    first = s.question.item
    s.submit(BAD)
    s.ignore()
    assert s.question.item is not first
    assert first.incorrect_meaning == 0


# ---- wrap-up --------------------------------------------------------------

def test_wrapup_started_mode():
    items = [make_item(i) for i in range(1, 11)]
    s = session(items)
    a = s.question.item
    answer(s, OK)            # a: meaning done, reading pending
    assert s.question.item is a
    s.submit(BAD)            # a reading wrong → back to the pool
    s.next()
    b = s.question.item
    s.toggle_wrapup()        # b was untouched → dropped from wrap-up
    assert s.question.item is a
    assert s.wrapup_left == 1
    done = answer(s, OK)
    assert done and done[0].assignment_id == a.assignment_id
    assert s.done
    assert b.assignment_id not in [c.assignment_id for c in s.completed]


def test_wrapup_finishes_half_done_current_item():
    s = session([make_item(i) for i in range(1, 6)])
    a = s.question.item
    answer(s, OK)
    s.toggle_wrapup()
    assert s.question.item is a
    answer(s, OK)
    assert s.done and len(s.completed) == 1


def test_wrapup_count_mode():
    s = session([make_item(i, "radical") for i in range(1, 11)], wrapup_mode="count", wrapup_count=2)
    s.toggle_wrapup()
    seen = 0
    while not s.done:
        answer(s, OK)
        seen += 1
    assert seen == 2


def test_wrapup_toggle_off_resumes():
    s = session([make_item(i, "radical") for i in range(1, 4)])
    s.toggle_wrapup()
    assert s.done
    s.toggle_wrapup()
    assert not s.done and s.question is not None


# ---- ordering -------------------------------------------------------------

def test_review_orderings():
    items = [
        make_item(1, "vocabulary", level=3, srs=4, available="2026-01-03T00:00:00.000000Z"),
        make_item(2, "radical", level=1, srs=2, available="2026-01-02T00:00:00.000000Z"),
        make_item(3, "kanji", level=2, srs=1, available="2026-01-01T00:00:00.000000Z"),
    ]
    rng = random.Random(0)
    ids = lambda xs: [x.subject_id for x in xs]  # noqa: E731
    assert ids(order_reviews(items, "level", rng)) == [2, 3, 1]
    assert ids(order_reviews(items, "level_desc", rng)) == [1, 3, 2]
    assert ids(order_reviews(items, "srs", rng)) == [3, 2, 1]
    assert ids(order_reviews(items, "type", rng)) == [2, 3, 1]
    assert ids(order_reviews(items, "oldest", rng)) == [3, 2, 1]
    assert sorted(ids(order_reviews(items, "random", rng))) == [1, 2, 3]
    with pytest.raises(ValueError):
        order_reviews(items, "nope")


def test_lesson_orderings():
    items = [
        make_item(1, "vocabulary", level=1, position=0),
        make_item(2, "kanji", level=1, position=1),
        make_item(3, "kanji", level=1, position=0),
        make_item(4, "radical", level=2, position=0),
    ]
    ids = lambda xs: [x.subject_id for x in xs]  # noqa: E731
    assert ids(order_lessons(items, "level")) == [3, 2, 1, 4]
    assert ids(order_lessons(items, "type")) == [4, 3, 2, 1]


def test_reorder_only_untouched_items():
    items = [make_item(i, "radical", level=10 - i) for i in range(1, 8)]
    s = session(items, order="random")
    s.reorder("level")
    levels = [i.level for i in s.queue]
    assert levels == sorted(levels)
