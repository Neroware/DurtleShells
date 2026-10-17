"""Answer checking with WaniKani-style close-match tolerance."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from rapidfuzz.distance import Levenshtein

from ..api.models import Subject
from .kana import convert, to_hiragana


class Result(Enum):
    CORRECT = "correct"
    CORRECT_TYPO = "typo"
    INCORRECT = "incorrect"
    SHAKE = "shake"

    @property
    def is_correct(self) -> bool:
        return self in (Result.CORRECT, Result.CORRECT_TYPO)


@dataclass(frozen=True)
class Verdict:
    result: Result
    message: str = ""
    matched: str | None = None

    @property
    def is_correct(self) -> bool:
        return self.result.is_correct


_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACE = re.compile(r"\s+")
_JAPANESE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ々〆ー]")
_LATIN = re.compile(r"[A-Za-z]")


def normalize_meaning(text: str) -> str:
    text = text.lower().replace("-", " ")
    text = _PUNCT.sub("", text)
    return _SPACE.sub(" ", text).strip()


def _key(text: str) -> str:
    return normalize_meaning(text).replace(" ", "")


def tolerance(length: int) -> int:
    """WaniKani's allowed edit distance for an answer of ``length`` characters."""
    if length <= 3:
        return 0
    if length <= 5:
        return 1
    if length <= 7:
        return 2
    return 2 + length // 7


def check_meaning(
    subject: Subject,
    answer: str,
    synonyms: Iterable[str] = (),
    typo_tolerance: bool = True,
) -> Verdict:
    given = _key(answer)
    if not answer.strip():
        return Verdict(Result.SHAKE, "Type an answer first")
    if _JAPANESE.search(answer):
        return Verdict(Result.SHAKE, "We want the meaning, not the reading")
    if not given:
        return Verdict(Result.SHAKE, "Type an answer first")

    blacklist = [a.meaning for a in subject.auxiliary_meanings if a.type == "blacklist"]
    accepted = [m.meaning for m in subject.meanings if m.accepted_answer]
    accepted += [a.meaning for a in subject.auxiliary_meanings if a.type == "whitelist"]
    accepted += list(synonyms)

    for bad in blacklist:
        if _key(bad) == given:
            return Verdict(Result.INCORRECT, f"“{bad}” is not accepted here")
    for good in accepted:
        if _key(good) == given:
            return Verdict(Result.CORRECT, matched=good)

    if typo_tolerance:
        best: tuple[int, str] | None = None
        for good in accepted:
            k = _key(good)
            dist = Levenshtein.distance(given, k)
            if dist <= tolerance(len(k)) and (best is None or dist < best[0]):
                best = (dist, good)
        if best is not None:
            # A blacklisted meaning that is at least as close wins over the typo.
            if any(Levenshtein.distance(given, _key(b)) <= best[0] for b in blacklist):
                return Verdict(Result.INCORRECT)
            return Verdict(Result.CORRECT_TYPO, f"Close enough — it's “{best[1]}”", matched=best[1])

    return Verdict(Result.INCORRECT)


_READING_NAMES = {"onyomi": "on'yomi", "kunyomi": "kun'yomi", "nanori": "nanori"}


def check_reading(subject: Subject, answer: str) -> Verdict:
    converted = convert(answer.strip(), final=True)
    if not converted:
        return Verdict(Result.SHAKE, "Type an answer first")
    if _LATIN.search(converted):
        return Verdict(Result.SHAKE, "Answer in kana")
    given = to_hiragana(converted).replace(" ", "")

    accepted = [r for r in subject.readings if r.accepted_answer]
    for r in accepted:
        if to_hiragana(r.reading) == given:
            return Verdict(Result.CORRECT, matched=r.reading)

    if subject.object == "kanji":
        for r in subject.readings:
            if not r.accepted_answer and to_hiragana(r.reading) == given:
                wanted = sorted({_READING_NAMES.get(a.type or "", a.type or "") for a in accepted})
                which = " or ".join(w for w in wanted if w) or "other"
                return Verdict(Result.SHAKE, f"We want the {which} reading")

    return Verdict(Result.INCORRECT)
