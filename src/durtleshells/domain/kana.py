"""IME-style romaji→kana conversion.

``convert`` is idempotent on kana, so the answer widget can re-run it over the whole
input after every keystroke: converted kana pass through untouched and only the
unresolved romaji tail stays Latin until it can be resolved.
"""

from __future__ import annotations

VOWELS = "aeiou"

_BASE: dict[str, str] = {
    "a": "あ", "i": "い", "u": "う", "e": "え", "o": "お",
    "ka": "か", "ki": "き", "ku": "く", "ke": "け", "ko": "こ",
    "ga": "が", "gi": "ぎ", "gu": "ぐ", "ge": "げ", "go": "ご",
    "sa": "さ", "si": "し", "shi": "し", "su": "す", "se": "せ", "so": "そ",
    "za": "ざ", "zi": "じ", "ji": "じ", "zu": "ず", "ze": "ぜ", "zo": "ぞ",
    "ta": "た", "ti": "ち", "chi": "ち", "tu": "つ", "tsu": "つ", "te": "て", "to": "と",
    "da": "だ", "di": "ぢ", "du": "づ", "de": "で", "do": "ど",
    "na": "な", "ni": "に", "nu": "ぬ", "ne": "ね", "no": "の",
    "ha": "は", "hi": "ひ", "hu": "ふ", "fu": "ふ", "he": "へ", "ho": "ほ",
    "ba": "ば", "bi": "び", "bu": "ぶ", "be": "べ", "bo": "ぼ",
    "pa": "ぱ", "pi": "ぴ", "pu": "ぷ", "pe": "ぺ", "po": "ぽ",
    "ma": "ま", "mi": "み", "mu": "む", "me": "め", "mo": "も",
    "ya": "や", "yu": "ゆ", "yo": "よ",
    "ra": "ら", "ri": "り", "ru": "る", "re": "れ", "ro": "ろ",
    "la": "ぁ", "li": "ぃ", "lu": "ぅ", "le": "ぇ", "lo": "ぉ",
    "wa": "わ", "wi": "うぃ", "we": "うぇ", "wo": "を",
    "xa": "ぁ", "xi": "ぃ", "xu": "ぅ", "xe": "ぇ", "xo": "ぉ",
    "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ", "lya": "ゃ", "lyu": "ゅ", "lyo": "ょ",
    "xtu": "っ", "ltu": "っ", "xtsu": "っ", "ltsu": "っ",
    "xwa": "ゎ", "lwa": "ゎ", "xka": "ゕ", "xke": "ゖ",
    "nn": "ん", "n'": "ん", "xn": "ん",
    "vu": "ゔ", "va": "ゔぁ", "vi": "ゔぃ", "ve": "ゔぇ", "vo": "ゔぉ",
    "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ", "fyu": "ふゅ",
    "she": "しぇ", "je": "じぇ", "che": "ちぇ",
    "thi": "てぃ", "dhi": "でぃ", "thu": "てゅ", "dhu": "でゅ",
    "twu": "とぅ", "dwu": "どぅ", "tsa": "つぁ", "tsi": "つぃ", "tse": "つぇ", "tso": "つぉ",
    "-": "ー",
}

_YOON_ROWS = {
    "ky": "き", "gy": "ぎ", "sy": "し", "zy": "じ", "ty": "ち", "dy": "ぢ", "cy": "ち",
    "ny": "に", "hy": "ひ", "by": "び", "py": "ぴ", "my": "み", "ry": "り",
}
_SMALL = {"a": "ゃ", "u": "ゅ", "o": "ょ", "e": "ぇ", "i": "ぃ"}
for _prefix, _kana in _YOON_ROWS.items():
    for _v, _small in _SMALL.items():
        _BASE.setdefault(_prefix + _v, _kana + _small)
for _prefix, _kana in {"sh": "し", "ch": "ち", "j": "じ"}.items():
    for _v in "auo":
        _BASE.setdefault(_prefix + _v, _kana + _SMALL[_v])
for _v in "auo":
    _BASE.setdefault("jy" + _v, "じ" + _SMALL[_v])

TABLE: dict[str, str] = _BASE
_MAX_KEY = max(len(k) for k in TABLE)
_PREFIXES: frozenset[str] = frozenset(k[:i] for k in TABLE for i in range(1, len(k) + 1))


def to_katakana(text: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


def to_hiragana(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def _is_latin(c: str) -> bool:
    return ("a" <= c <= "z") or ("A" <= c <= "Z")


def convert(buffer: str, final: bool = False) -> str:
    """Convert romaji in ``buffer`` to kana.

    With ``final=False`` an unresolved tail (``k``, ``ky``, ``n``, ``nn``) stays as
    romaji so the next keystroke can complete it. With ``final=True`` a trailing
    ``n``/``nn`` becomes ``ん`` and any other leftovers stay Latin (the checker
    then asks the user to answer in kana). Uppercase input produces katakana.
    """
    out: list[str] = []
    i = 0
    n = len(buffer)
    while i < n:
        ch = buffer[i]
        if not (_is_latin(ch) or ch in "-'"):
            out.append(ch)
            i += 1
            continue
        if ch == "'":
            out.append(ch)
            i += 1
            continue
        katakana = ch.isupper()
        low = buffer[i:i + _MAX_KEY + 1].lower()
        c = low[0]
        nxt = low[1] if len(low) > 1 else ""

        def emit(kana: str, katakana: bool = katakana) -> None:
            out.append(to_katakana(kana) if katakana else kana)

        if c == "n":
            if nxt == "":
                if final:
                    emit("ん")
                else:
                    out.append(ch)
                i += 1
                continue
            if nxt == "'":
                emit("ん")
                i += 2
                continue
            if nxt == "n":
                after = low[2] if len(low) > 2 else ""
                if after and (after in VOWELS or after == "y"):
                    # "onna": the first n is ん, the second starts な
                    emit("ん")
                    i += 1
                    continue
                if after == "" and not final:
                    out.append(buffer[i:i + 2])  # wait: "nn" + vowel → ん + な…
                    i += 2
                    continue
                emit("ん")
                i += 2
                continue
            if nxt not in VOWELS and nxt != "y":
                emit("ん")
                i += 1
                continue
        # Sokuon: doubled consonant (kka → っか) or t before ch (tchi → っち).
        if c not in VOWELS and c != "n" and c.isalpha() and (nxt == c or (c == "t" and nxt == "c")):
            emit("っ")
            i += 1
            continue
        for length in range(min(_MAX_KEY, len(low)), 0, -1):
            kana = TABLE.get(low[:length])
            if kana is not None:
                emit(kana)
                i += length
                break
        else:
            rest = low
            if rest in _PREFIXES and not final:
                out.append(buffer[i:])  # incomplete syllable: wait for more input
                break
            out.append(ch)
            i += 1
    return "".join(out)
