import httpx
import pytest
import respx

from durtleshells.api.client import (
    BASE_URL,
    AuthError,
    NetworkError,
    TokenBucket,
    UnprocessableError,
    WaniKaniClient,
)
from durtleshells.api.models import Subject


async def no_sleep(_s):
    no_sleep.calls.append(_s)


no_sleep.calls = []


def client():
    return WaniKaniClient("tok", sleep=no_sleep, bucket=TokenBucket(sleep=no_sleep))


def collection(items, next_url=None, total=None, per_page=2):
    return {
        "object": "collection", "data_updated_at": "2026-10-17T10:00:00.000000Z",
        "total_count": total if total is not None else len(items),
        "pages": {"per_page": per_page, "next_url": next_url}, "data": items,
    }


@respx.mock
async def test_headers_and_user():
    route = respx.get(BASE_URL + "user").respond(json={"data": {
        "id": "u", "username": "x", "level": 4,
        "preferences": {"lessons_batch_size": 7}, "subscription": {"max_level_granted": 60},
    }})
    async with client() as c:
        user = await c.get_user()
    assert user.level == 4 and user.lessons_batch_size == 7 and user.max_level_granted == 60
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.headers["Wanikani-Revision"] == "20170710"


@respx.mock
async def test_pagination():
    respx.get(BASE_URL + "subjects", params={"updated_after": "T0"}).respond(
        json=collection([{"id": 1}, {"id": 2}], next_url=BASE_URL + "subjects?page_after_id=2", total=3))
    respx.get(BASE_URL + "subjects", params={"page_after_id": "2"}).respond(
        json=collection([{"id": 3}], total=3))
    async with client() as c:
        pages = [p async for p in c.subjects("T0")]
    assert [p.index for p in pages] == [1, 2]
    assert [p.total_pages for p in pages] == [2, 2]
    assert [i["id"] for p in pages for i in p.items] == [1, 2, 3]


@respx.mock
async def test_429_then_retry():
    route = respx.get(BASE_URL + "user")
    route.side_effect = [
        httpx.Response(429, headers={"RateLimit-Reset": "0"}),
        httpx.Response(200, json={"data": {"id": "u", "level": 1}}),
    ]
    no_sleep.calls.clear()
    async with client() as c:
        user = await c.get_user()
    assert user.level == 1
    assert route.call_count == 2
    assert no_sleep.calls  # we waited before retrying


@respx.mock
async def test_401():
    respx.get(BASE_URL + "user").respond(401, json={"error": "Unauthorized"})
    async with client() as c:
        with pytest.raises(AuthError):
            await c.get_user()


@respx.mock
async def test_422():
    respx.post(BASE_URL + "reviews").respond(422, json={"error": "not available"})
    async with client() as c:
        with pytest.raises(UnprocessableError):
            await c.create_review(1, 0, 0, "2026-10-17T10:00:00.000000Z")


@respx.mock
async def test_network_error():
    respx.get(BASE_URL + "user").mock(side_effect=httpx.ConnectError("down"))
    async with client() as c:
        with pytest.raises(NetworkError):
            await c.get_user()


@respx.mock
async def test_create_review_body():
    route = respx.post(BASE_URL + "reviews").respond(201, json={
        "id": 9, "data": {}, "resources_updated": {"assignment": {"id": 5, "data": {"subject_id": 1}}}})
    async with client() as c:
        assignment = await c.create_review(5, 1, 2, "2026-10-17T10:00:00.000000Z")
    assert assignment["id"] == 5
    import json
    body = json.loads(route.calls.last.request.content)
    assert body == {"review": {"assignment_id": 5, "incorrect_meaning_answers": 1,
                               "incorrect_reading_answers": 2, "created_at": "2026-10-17T10:00:00.000000Z"}}


async def test_token_bucket_waits():
    t = [0.0]
    waits = []

    async def sleep(s):
        waits.append(s)
        t[0] += s

    bucket = TokenBucket(2, 2.0, clock=lambda: t[0], sleep=sleep)
    for _ in range(3):
        await bucket.acquire()
    assert waits and waits[0] == pytest.approx(1.0)


def test_parse_each_subject_type(subject_resources):
    kinds = {Subject.from_resource(r).object for r in subject_resources}
    assert kinds == {"radical", "kanji", "vocabulary", "kana_vocabulary"}
