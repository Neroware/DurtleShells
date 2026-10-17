"""Japanese 12-key flick keyboard: layout, gesture resolution, modifier cycling."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(Enum):
    CENTER = 0
    LEFT = 1
    UP = 2
    RIGHT = 3
    DOWN = 4


@dataclass(frozen=True)
class FlickKey:
    label: str
    # Candidates in Direction order: center, left, up, right, down (None = nothing).
    candidates: tuple[str | None, str | None, str | None, str | None, str | None] = (None,) * 5
    action: str = "kana"  # kana | modifier | backspace | space | submit

    def output(self, direction: Direction) -> str | None:
        return self.candidates[direction.value] if self.action == "kana" else None


def _k(chars: str) -> FlickKey:
    cands = tuple(None if c == "_" else c for c in chars)
    cands = cands + (None,) * (5 - len(cands))
    return FlickKey(chars[0], cands)  # type: ignore[arg-type]


KEYS: dict[str, FlickKey] = {
    "あ": _k("あいうえお"),
    "か": _k("かきくけこ"),
    "さ": _k("さしすせそ"),
    "た": _k("たちつてと"),
    "な": _k("なにぬねの"),
    "は": _k("はひふへほ"),
    "ま": _k("まみむめも"),
    "や": FlickKey("や", ("や", "（", "ゆ", "）", "よ")),
    "ら": _k("らりるれろ"),
    "mod": FlickKey("゛゜小", action="modifier"),
    "わ": FlickKey("わ", ("わ", "を", "ん", "ー", None)),
    "punct": FlickKey("、。?!", ("、", "。", "？", "！", None)),
    "bs": FlickKey("⌫", action="backspace"),
    "space": FlickKey("␣", action="space"),
    "enter": FlickKey("⏎", action="submit"),
}

# 4 rows × 4 columns: the 3×4 kana grid plus a side column of control keys.
GRID: tuple[tuple[str | None, ...], ...] = (
    ("あ", "か", "さ", "bs"),
    ("た", "な", "は", "space"),
    ("ま", "や", "ら", "enter"),
    ("mod", "わ", "punct", None),
)

ASPECT = 0.5  # cells are ~2× taller than wide: scale dx so diagonals feel fair


def resolve(dx: float, dy: float, threshold: float = 1.0) -> Direction:
    """Resolve a drag of (dx, dy) terminal cells into a flick direction."""
    sx = dx * ASPECT
    if max(abs(sx), abs(dy)) < threshold:
        return Direction.CENTER
    if abs(sx) >= abs(dy):
        return Direction.RIGHT if sx > 0 else Direction.LEFT
    return Direction.DOWN if dy > 0 else Direction.UP


# Modifier cycles: tapping ゛゜小 replaces the previous character with the next variant.
_CYCLES: list[str] = [
    "あぁ", "いぃ", "うぅゔ", "えぇ", "おぉ",
    "かが", "きぎ", "くぐ", "けげ", "こご",
    "さざ", "しじ", "すず", "せぜ", "そぞ",
    "ただ", "ちぢ", "つっづ", "てで", "とど",
    "はばぱ", "ひびぴ", "ふぶぷ", "へべぺ", "ほぼぽ",
    "やゃ", "ゆゅ", "よょ", "わゎ",
]
CYCLE: dict[str, str] = {}
for _group in _CYCLES:
    for _i, _c in enumerate(_group):
        CYCLE[_c] = _group[(_i + 1) % len(_group)]
    # katakana too
    _kata = "".join(chr(ord(c) + 0x60) for c in _group)
    for _i, _c in enumerate(_kata):
        CYCLE[_c] = _kata[(_i + 1) % len(_kata)]


def cycle(char: str) -> str:
    """Next variant of ``char`` (か→が→か, は→ば→ぱ→は, つ→っ→づ→つ…)."""
    return CYCLE.get(char, char)
