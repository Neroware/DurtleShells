"""Async WaniKani API v2 client built on httpx."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .models import Assignment, User

BASE_URL = "https://api.wanikani.com/v2/"
REVISION = "20170710"


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AuthError(ApiError):
    """401: token missing, invalid or revoked."""


class RateLimited(ApiError):
    """429 that persisted after retries."""


class UnprocessableError(ApiError):
    """422: the server rejected the submission (e.g. stale review)."""


class NetworkError(ApiError):
    """Connection failure or timeout — we are probably offline."""


Sleep = Callable[[float], Awaitable[None]]


class TokenBucket:
    """Client-side limiter for WaniKani's 60 requests/minute."""

    def __init__(
        self,
        capacity: int = 60,
        per_seconds: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.capacity = capacity
        self.rate = capacity / per_seconds
        self.tokens = float(capacity)
        self.clock = clock
        self.sleep = sleep
        self.updated = clock()

    def _refill(self) -> None:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    async def acquire(self) -> None:
        self._refill()
        while self.tokens < 1:
            await self.sleep((1 - self.tokens) / self.rate)
            self._refill()
        self.tokens -= 1


@dataclass
class Page:
    index: int  # 1-based
    total_pages: int
    data_updated_at: str | None
    items: list[dict[str, Any]]


class WaniKaniClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        bucket: TokenBucket | None = None,
        sleep: Sleep = asyncio.sleep,
        max_retries: int = 3,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Wanikani-Revision": REVISION,
                "User-Agent": "durtleshells",
            },
            timeout=timeout,
            transport=transport,
        )
        self.bucket = bucket or TokenBucket(sleep=sleep)
        self.sleep = sleep
        self.max_retries = max_retries

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> WaniKaniClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---- core --------------------------------------------------------------

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            await self.bucket.acquire()
            try:
                resp = await self._http.request(method, url, params=params, json=json)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                raise NetworkError(f"network error: {exc.__class__.__name__}") from exc
            if resp.status_code == 429:
                if attempt >= self.max_retries:
                    raise RateLimited("rate limited", 429)
                await self.sleep(self._retry_delay(resp))
                continue
            if resp.status_code == 401:
                raise AuthError("invalid or revoked API token", 401)
            if resp.status_code == 422:
                raise UnprocessableError(self._error_text(resp), 422)
            if resp.status_code >= 400:
                raise ApiError(f"HTTP {resp.status_code}: {self._error_text(resp)}", resp.status_code)
            return resp.json()
        raise RateLimited("rate limited", 429)  # pragma: no cover

    @staticmethod
    def _retry_delay(resp: httpx.Response) -> float:
        reset = resp.headers.get("RateLimit-Reset")
        if reset:
            try:
                return min(60.0, max(0.0, float(reset) - time.time()) + 0.5)
            except ValueError:
                pass
        return 5.0

    @staticmethod
    def _error_text(resp: httpx.Response) -> str:
        try:
            return str(resp.json().get("error") or resp.text)
        except ValueError:
            return resp.text

    async def pages(self, path: str, params: dict[str, Any] | None = None) -> AsyncIterator[Page]:
        """Follow ``pages.next_url`` until exhausted, yielding one page at a time."""
        url: str | None = path
        index = 0
        while url:
            body = await self.request("GET", url, params=params)
            params = None  # next_url already carries the query
            index += 1
            per_page = (body.get("pages") or {}).get("per_page") or len(body.get("data", [])) or 1
            total = max(1, -(-int(body.get("total_count", 0)) // per_page))
            yield Page(index, max(total, index), body.get("data_updated_at"), body.get("data", []))
            url = (body.get("pages") or {}).get("next_url")

    async def collect(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        async for page in self.pages(path, params):
            items.extend(page.items)
        return items

    # ---- endpoints ---------------------------------------------------------

    async def get_user(self) -> User:
        return User.from_resource(await self.request("GET", "user"))

    def subjects(self, updated_after: str | None = None) -> AsyncIterator[Page]:
        return self.pages("subjects", _since(updated_after))

    def assignments(self, updated_after: str | None = None) -> AsyncIterator[Page]:
        return self.pages("assignments", _since(updated_after))

    def study_materials(self, updated_after: str | None = None) -> AsyncIterator[Page]:
        return self.pages("study_materials", _since(updated_after))

    async def create_review(
        self,
        assignment_id: int,
        incorrect_meaning_answers: int,
        incorrect_reading_answers: int,
        created_at: str | None = None,
    ) -> dict[str, Any] | None:
        """POST /reviews. Returns the updated assignment resource, if the server sent one."""
        review: dict[str, Any] = {
            "assignment_id": assignment_id,
            "incorrect_meaning_answers": incorrect_meaning_answers,
            "incorrect_reading_answers": incorrect_reading_answers,
        }
        if created_at:
            review["created_at"] = created_at
        body = await self.request("POST", "reviews", json={"review": review})
        return (body.get("resources_updated") or {}).get("assignment")

    async def start_assignment(self, assignment_id: int, started_at: str | None = None) -> Assignment:
        payload = {"started_at": started_at} if started_at else {}
        body = await self.request("PUT", f"assignments/{assignment_id}/start", json=payload)
        return Assignment.from_resource(body)


def _since(updated_after: str | None) -> dict[str, Any] | None:
    return {"updated_after": updated_after} if updated_after else None
