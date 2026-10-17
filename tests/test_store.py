from datetime import UTC, datetime

import httpx
import pytest
import respx

from durtleshells.api.client import BASE_URL, NetworkError, TokenBucket, WaniKaniClient
from durtleshells.store.db import connect
from durtleshells.store.repo import Repo
from durtleshells.store.sync import SyncEngine

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


async def _nosleep(_s):
    return None


def coll(items, ts="2026-10-17T10:00:00.000000Z"):
    return {"object": "collection", "data_updated_at": ts, "total_count": len(items),
            "pages": {"per_page": 500, "next_url": None}, "data": items}


def assignment(aid, sid, stage=1, available="2026-10-17T11:00:00.000000Z", started="2026-10-01T00:00:00.000000Z", **extra):
    data = {"subject_id": sid, "subject_type": "kanji", "srs_stage": stage, "unlocked_at": "2026-10-01T00:00:00.000000Z",
            "started_at": started, "available_at": available, "burned_at": None, "hidden": False}
    data.update(extra)
    return {"id": aid, "object": "assignment", "data_updated_at": "2026-10-17T10:00:00.000000Z", "data": data}


USER = {"data": {"id": "u", "username": "x", "level": 1, "preferences": {"lessons_batch_size": 5},
                 "subscription": {"max_level_granted": 3}}}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "d.db"


def engine(db_path, **kw):
    repo = Repo(connect(db_path))
    client = WaniKaniClient("t", sleep=_nosleep, bucket=TokenBucket(sleep=_nosleep))
    return SyncEngine(repo, client, **kw)


def mock_server(subject_resources, assignments):
    respx.get(BASE_URL + "user").respond(json=USER)
    respx.get(BASE_URL + "subjects").respond(json=coll(subject_resources))
    respx.get(BASE_URL + "assignments").respond(json=coll(assignments))
    respx.get(BASE_URL + "study_materials").respond(json=coll([
        {"id": 1, "data_updated_at": "2026-10-17T10:00:00.000000Z", "data": {"subject_id": 453, "meaning_synonyms": ["huge"]}}
    ]))


@respx.mock
async def test_initial_then_incremental_sync(db_path, subject_resources):
    mock_server(subject_resources, [assignment(1, 453), assignment(2, 444, started=None, available=None)])
    progress = []
    eng = engine(db_path, on_progress=progress.append)
    await eng.sync()
    repo = eng.repo
    assert repo.subject_count() == len(subject_resources)
    assert repo.user().level == 1
    assert repo.synonyms(453) == ["huge"]
    assert [a.id for a in repo.available_reviews(NOW)] == [1]
    assert [a.id for a in repo.available_lessons()] == [2]
    assert any("Syncing subjects" in p for p in progress)
    assert eng.online is True

    await eng.sync()
    sub_req = [c.request for c in respx.calls if c.request.url.path.endswith("/subjects")][-1]
    assert sub_req.url.params["updated_after"] == "2026-10-17T10:00:00.000000Z"


def test_queries(db_path, subject_resources):
    repo = Repo(connect(db_path))
    repo.upsert_subjects(subject_resources)
    repo.upsert_assignments([
        assignment(1, 453, stage=1, available="2026-10-17T11:00:00.000000Z"),
        assignment(2, 444, stage=5, available="2026-10-17T12:30:00.000000Z"),
        assignment(3, 440, stage=9, available=None, burned_at="2026-01-01T00:00:00.000000Z"),
        assignment(4, 1, stage=7, available="2026-10-17T14:10:00.000000Z", hidden=True),
        assignment(5, 18, stage=8, available="2026-10-17T13:00:00.000000Z"),
    ])
    assert [a.id for a in repo.available_reviews(NOW)] == [1]
    fc = repo.forecast(NOW, hours=24)
    assert len(fc) == 24
    assert fc[0][1] == 2 and fc[1][1] == 0 and sum(c for _, c in fc) == 2  # 12:30 and 13:00 → the 13h bucket
    assert fc[0][0].hour == 13
    dist = repo.srs_distribution()
    assert dist == {"Apprentice": 1, "Guru": 1, "Master": 0, "Enlightened": 1, "Burned": 1}


def test_outbox_survives_restart_and_hides_reviews(db_path, subject_resources):
    repo = Repo(connect(db_path))
    repo.upsert_subjects(subject_resources)
    repo.upsert_assignments([assignment(1, 453)])
    eng = SyncEngine(repo, WaniKaniClient("t"))
    eng.enqueue_review(1, 1, 0, "2026-10-17T11:30:00.000000Z")
    assert repo.available_reviews(NOW) == []
    repo2 = Repo(connect(db_path))
    entries = repo2.outbox()
    assert len(entries) == 1 and entries[0].payload["incorrect_meaning_answers"] == 1


@respx.mock
async def test_flush_success_stale_and_offline(db_path, subject_resources):
    stale = []
    eng = engine(db_path, on_stale=stale.append)
    eng.repo.upsert_subjects(subject_resources)
    eng.repo.upsert_assignments([assignment(1, 453), assignment(2, 444), assignment(3, 2477)])
    eng.enqueue_review(1, 0, 0, "2026-10-17T11:01:00.000000Z")
    eng.enqueue_review(2, 0, 1, "2026-10-17T11:02:00.000000Z")
    eng.enqueue_lesson_start(3, "2026-10-17T11:03:00.000000Z")

    def review(request):
        import json
        aid = json.loads(request.content)["review"]["assignment_id"]
        if aid == 2:
            return httpx.Response(422, json={"error": "stale"})
        updated = assignment(aid, 453, stage=2, available="2026-10-17T15:00:00.000000Z")
        return httpx.Response(201, json={"id": 1, "data": {}, "resources_updated": {"assignment": updated}})

    respx.post(BASE_URL + "reviews").mock(side_effect=review)
    respx.put(BASE_URL + "assignments/3/start").mock(side_effect=httpx.ConnectError("offline"))

    result = await eng.flush()
    assert (result.sent, result.dropped, result.offline) == (1, 1, True)
    assert eng.repo.assignment(1).srs_stage == 2
    assert len(stale) == 1 and "人" in stale[0].message
    left = eng.repo.outbox()
    assert [e.kind for e in left] == ["lesson_start"] and left[0].attempts == 1
    assert eng.online is False

    with pytest.raises(NetworkError):
        await eng.run_once()


@respx.mock
async def test_lesson_start_flush(db_path, subject_resources):
    eng = engine(db_path)
    eng.repo.upsert_subjects(subject_resources)
    eng.repo.upsert_assignments([assignment(3, 2477, started=None, available=None)])
    eng.enqueue_lesson_start(3, "2026-10-17T11:03:00.000000Z")
    assert eng.repo.available_lessons() == []
    route = respx.put(BASE_URL + "assignments/3/start").respond(json=assignment(3, 2477, started="2026-10-17T11:03:00.000000Z", available="2026-10-17T15:03:00.000000Z"))
    await eng.flush()
    import json
    assert json.loads(route.calls.last.request.content) == {"started_at": "2026-10-17T11:03:00.000000Z"}
    assert eng.repo.assignment(3).started_at == "2026-10-17T11:03:00.000000Z"
    assert eng.pending == 0
