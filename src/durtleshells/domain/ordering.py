"""Ordering strategies for review and lesson pools."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar


class Orderable(Protocol):
    level: int
    srs_stage: int
    subject_type: str
    available_at: str | None
    lesson_position: int
    subject_id: int


T = TypeVar("T", bound=Orderable)

TYPE_RANK = {"radical": 0, "kanji": 1, "vocabulary": 2, "kana_vocabulary": 2}


def _shuffled(items: Sequence[T], rng: random.Random) -> list[T]:
    out = list(items)
    rng.shuffle(out)
    return out


def _stable(items: Sequence[T], rng: random.Random, key: Callable[[T], object]) -> list[T]:
    """Sort by ``key`` with random tie-breaking."""
    return sorted(_shuffled(items, rng), key=key)  # type: ignore[arg-type]


def order_reviews(items: Sequence[T], strategy: str, rng: random.Random | None = None) -> list[T]:
    rng = rng or random.Random()
    match strategy:
        case "random":
            return _shuffled(items, rng)
        case "level":
            return _stable(items, rng, lambda i: i.level)
        case "level_desc":
            return _stable(items, rng, lambda i: -i.level)
        case "srs":
            return _stable(items, rng, lambda i: i.srs_stage)
        case "type":
            return _stable(items, rng, lambda i: TYPE_RANK.get(i.subject_type, 9))
        case "oldest":
            return _stable(items, rng, lambda i: i.available_at or "")
    raise ValueError(f"unknown review order: {strategy}")


def order_lessons(items: Sequence[T], strategy: str, rng: random.Random | None = None) -> list[T]:
    rng = rng or random.Random()
    match strategy:
        case "level":
            return sorted(items, key=lambda i: (i.level, TYPE_RANK.get(i.subject_type, 9),
                                                i.lesson_position, i.subject_id))
        case "type":
            return sorted(items, key=lambda i: (TYPE_RANK.get(i.subject_type, 9), i.level,
                                                i.lesson_position, i.subject_id))
        case "random":
            return _shuffled(items, rng)
    raise ValueError(f"unknown lesson order: {strategy}")
