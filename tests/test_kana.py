import pytest

from durtleshells.domain.kana import TABLE, convert, to_hiragana, to_katakana


@pytest.mark.parametrize("romaji, kana", sorted(TABLE.items()))
def test_table_entries(romaji, kana):
    assert convert(romaji, final=True) == kana


@pytest.mark.parametrize(
    "romaji, kana",
    [
        ("kanji", "かんじ"),
        ("konnichiha", "こんにちは"),
        ("onna", "おんな"),
        ("kippu", "きっぷ"),
        ("shinbun", "しんぶん"),
        ("n'a", "んあ"),
        ("kan'i", "かんい"),
        ("hon", "ほん"),
        ("minna", "みんな"),
        ("tchi", "っち"),
        ("matcha", "まっちゃ"),
        ("kya", "きゃ"),
        ("jyo", "じょ"),
        ("ja", "じゃ"),
        ("cha", "ちゃ"),
        ("sha", "しゃ"),
        ("thi", "てぃ"),
        ("ti", "ち"),
        ("fa", "ふぁ"),
        ("ko-hi-", "こーひー"),
        ("KO-HI-", "コーヒー"),
        ("HOTERU", "ホテル"),
        ("xtu", "っ"),
        ("ltsu", "っ"),
        ("xya", "ゃ"),
        ("wo", "を"),
        ("shinnyuu", "しんにゅう"),
        ("kinnen", "きんねん"),
        ("hannnou", "はんのう"),
    ],
)
def test_words(romaji, kana):
    assert convert(romaji, final=True) == kana


def test_trailing_n_only_on_submit():
    assert convert("hon") == "ほn"
    assert convert("hon", final=True) == "ほん"
    assert convert("honn") == "ほnn"
    assert convert("honn", final=True) == "ほん"


@pytest.mark.parametrize("partial, shown", [("k", "k"), ("ky", "ky"), ("sh", "sh"), ("kak", "かk"), ("ts", "ts"), ("kk", "っk")])
def test_pending_tail_stays_romaji(partial, shown):
    assert convert(partial) == shown


def test_incremental_typing_matches_batch():
    """Re-running convert after each keystroke (as the widget does) gives the batch result."""
    for word in ["konnichiha", "onna", "shinbun", "kippu", "matcha", "kanji", "minna", "jyuu"]:
        value = ""
        for ch in word:
            value = convert(value + ch)
        assert convert(value, final=True) == convert(word, final=True), word


def test_idempotent_on_kana():
    assert convert("たべる") == "たべる"
    assert convert("たべn", final=True) == "たべん"
    assert convert("かnな") == "かんな"


def test_leftover_latin_on_final():
    assert convert("kq", final=True) == "kq"


def test_script_conversion():
    assert to_katakana("ほてる") == "ホテル"
    assert to_hiragana("コーヒー") == "こーひー"
