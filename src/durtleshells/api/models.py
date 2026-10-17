"""Dataclasses parsed from WaniKani API v2 resources.

Every model keeps the raw ``data`` dict so the store can persist it verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SUBJECT_TYPES = ("radical", "kanji", "vocabulary", "kana_vocabulary")


@dataclass(frozen=True)
class Meaning:
    meaning: str
    primary: bool
    accepted_answer: bool


@dataclass(frozen=True)
class AuxiliaryMeaning:
    meaning: str
    type: str  # "whitelist" | "blacklist"


@dataclass(frozen=True)
class Reading:
    reading: str
    primary: bool
    accepted_answer: bool
    type: str | None = None  # kanji only: onyomi | kunyomi | nanori


@dataclass
class Subject:
    id: int
    object: str
    level: int
    characters: str | None
    slug: str
    meanings: list[Meaning]
    auxiliary_meanings: list[AuxiliaryMeaning]
    readings: list[Reading]
    component_subject_ids: list[int]
    meaning_mnemonic: str
    meaning_hint: str | None
    reading_mnemonic: str | None
    reading_hint: str | None
    lesson_position: int
    hidden_at: str | None
    data: dict[str, Any] = field(repr=False)

    @classmethod
    def from_resource(cls, resource: dict[str, Any]) -> Subject:
        return cls.from_data(resource["id"], resource["object"], resource["data"])

    @classmethod
    def from_data(cls, id: int, object: str, data: dict[str, Any]) -> Subject:
        return cls(
            id=id,
            object=object,
            level=data.get("level", 0),
            characters=data.get("characters"),
            slug=data.get("slug", ""),
            meanings=[
                Meaning(m["meaning"], m.get("primary", False), m.get("accepted_answer", True))
                for m in data.get("meanings", [])
            ],
            auxiliary_meanings=[
                AuxiliaryMeaning(a["meaning"], a["type"]) for a in data.get("auxiliary_meanings", [])
            ],
            readings=[
                Reading(r["reading"], r.get("primary", False), r.get("accepted_answer", True), r.get("type"))
                for r in data.get("readings", []) or []
            ],
            component_subject_ids=list(data.get("component_subject_ids", []) or []),
            meaning_mnemonic=data.get("meaning_mnemonic", ""),
            meaning_hint=data.get("meaning_hint"),
            reading_mnemonic=data.get("reading_mnemonic"),
            reading_hint=data.get("reading_hint"),
            lesson_position=data.get("lesson_position", 0),
            hidden_at=data.get("hidden_at"),
            data=data,
        )

    # ---- convenience -------------------------------------------------------

    @property
    def has_reading(self) -> bool:
        """Radicals and kana-only vocabulary are asked for their meaning only."""
        return self.object in ("kanji", "vocabulary") and bool(self.readings)

    @property
    def primary_meaning(self) -> str:
        for m in self.meanings:
            if m.primary:
                return m.meaning
        return self.meanings[0].meaning if self.meanings else self.slug

    @property
    def primary_reading(self) -> str | None:
        for r in self.readings:
            if r.primary:
                return r.reading
        return self.readings[0].reading if self.readings else None

    @property
    def display(self) -> str:
        """Text to show as the prompt. Image-only radicals fall back to their meaning."""
        return self.characters or f"[{self.primary_meaning}]"

    @property
    def type_label(self) -> str:
        return {
            "radical": "Radical",
            "kanji": "Kanji",
            "vocabulary": "Vocabulary",
            "kana_vocabulary": "Vocabulary",
        }.get(self.object, self.object.title())

    @property
    def color_group(self) -> str:
        """WaniKani colour family: radical, kanji or vocabulary."""
        return "vocabulary" if self.object == "kana_vocabulary" else self.object


@dataclass
class Assignment:
    id: int
    subject_id: int
    subject_type: str
    srs_stage: int
    unlocked_at: str | None
    started_at: str | None
    available_at: str | None
    burned_at: str | None
    hidden: bool
    data: dict[str, Any] = field(repr=False)

    @classmethod
    def from_resource(cls, resource: dict[str, Any]) -> Assignment:
        return cls.from_data(resource["id"], resource["data"])

    @classmethod
    def from_data(cls, id: int, data: dict[str, Any]) -> Assignment:
        return cls(
            id=id,
            subject_id=data["subject_id"],
            subject_type=data["subject_type"],
            srs_stage=data.get("srs_stage", 0),
            unlocked_at=data.get("unlocked_at"),
            started_at=data.get("started_at"),
            available_at=data.get("available_at"),
            burned_at=data.get("burned_at"),
            hidden=bool(data.get("hidden", False)),
            data=data,
        )


@dataclass
class StudyMaterial:
    id: int
    subject_id: int
    meaning_synonyms: list[str]
    data: dict[str, Any] = field(repr=False)

    @classmethod
    def from_resource(cls, resource: dict[str, Any]) -> StudyMaterial:
        data = resource["data"]
        return cls(resource["id"], data["subject_id"], list(data.get("meaning_synonyms", []) or []), data)


@dataclass
class User:
    id: str
    username: str
    level: int
    lessons_batch_size: int
    max_level_granted: int
    data: dict[str, Any] = field(repr=False)

    @classmethod
    def from_resource(cls, resource: dict[str, Any]) -> User:
        return cls.from_data(resource["data"])

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> User:
        prefs = data.get("preferences", {}) or {}
        sub = data.get("subscription", {}) or {}
        return cls(
            id=data["id"],
            username=data.get("username", ""),
            level=data.get("level", 1),
            lessons_batch_size=prefs.get("lessons_batch_size", 5) or 5,
            max_level_granted=sub.get("max_level_granted", 3) or 3,
            data=data,
        )
