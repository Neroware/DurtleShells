import pytest

from durtleshells.domain.checker import Result, check_meaning, check_reading, tolerance


@pytest.mark.parametrize("n, tol", [(1, 0), (3, 0), (4, 1), (5, 1), (6, 2), (7, 2), (8, 3), (14, 4), (21, 5)])
def test_tolerance_table(n, tol):
    assert tolerance(n) == tol


def test_meaning_exact_and_alternative(subjects):
    big = subjects["kanji:大"]
    assert check_meaning(big, "big").result is Result.CORRECT
    assert check_meaning(big, "  LARGE ").result is Result.CORRECT


def test_meaning_whitelist(subjects):
    assert check_meaning(subjects["kanji:人"], "people").result is Result.CORRECT
    assert check_meaning(subjects["vocabulary:一人"], "1 person").result is Result.CORRECT


def test_meaning_punctuation_normalized(subjects):
    fuji = subjects["vocabulary:ふじ山"]
    assert check_meaning(fuji, "mt. fuji").result is Result.CORRECT
    assert check_meaning(fuji, "mount-fuji").result is Result.CORRECT


def test_meaning_typo(subjects):
    v = check_meaning(subjects["vocabulary:一人"], "alnoe")
    assert v.result is Result.INCORRECT  # 2 edits on a 5-letter word: too many
    v = check_meaning(subjects["vocabulary:一人"], "alome")
    assert v.result is Result.CORRECT_TYPO
    assert "Alone" in v.message


def test_meaning_typo_disabled(subjects):
    assert check_meaning(subjects["vocabulary:一人"], "alome", typo_tolerance=False).result is Result.INCORRECT


def test_short_answers_have_no_tolerance(subjects):
    assert check_meaning(subjects["kanji:大"], "bog").result is Result.INCORRECT


def test_blacklist(subjects):
    kore = subjects["kana_vocabulary:これ"]
    assert check_meaning(kore, "that one").result is Result.INCORRECT
    assert check_meaning(kore, "this one").result is Result.CORRECT
    assert check_meaning(subjects["kana_vocabulary:いつ"], "then").result is Result.INCORRECT


def test_blacklist_beats_typo(subjects):
    # "those" is blacklisted for これ; "thise" is 1 edit from both "this" (whitelist, no
    # tolerance at 4 chars → 1) and "those" (blacklist).
    assert check_meaning(subjects["kana_vocabulary:これ"], "thosee").result is Result.INCORRECT


def test_user_synonym(subjects):
    assert check_meaning(subjects["kanji:大"], "huge").result is Result.INCORRECT
    assert check_meaning(subjects["kanji:大"], "huge", synonyms=["Huge"]).result is Result.CORRECT


def test_meaning_in_kana_shakes(subjects):
    v = check_meaning(subjects["kanji:大"], "だい")
    assert v.result is Result.SHAKE
    assert check_meaning(subjects["kanji:大"], "").result is Result.SHAKE


def test_reading_correct(subjects):
    big = subjects["kanji:大"]
    assert check_reading(big, "tai").result is Result.CORRECT
    assert check_reading(big, "だい").result is Result.CORRECT
    assert check_reading(big, "ダイ").result is Result.CORRECT


def test_reading_trailing_n(subjects):
    assert check_reading(subjects["kanji:人"], "nin").result is Result.CORRECT
    assert check_reading(subjects["kanji:人"], "jin").result is Result.CORRECT


def test_reading_wrong_type_shakes(subjects):
    v = check_reading(subjects["kanji:大"], "おお")
    assert v.result is Result.SHAKE
    assert "on'yomi" in v.message
    v = check_reading(subjects["kanji:人"], "hito")
    assert v.result is Result.SHAKE


def test_reading_latin_shakes(subjects):
    assert check_reading(subjects["kanji:大"], "big").result is Result.SHAKE


def test_vocab_reading(subjects):
    hitori = subjects["vocabulary:一人"]
    assert check_reading(hitori, "hitori").result is Result.CORRECT
    assert check_reading(hitori, "ichinin").result is Result.INCORRECT
    assert check_reading(subjects["vocabulary:人"], "jin").result is Result.INCORRECT


def test_subject_parsing(subjects):
    img = subjects["radical:8766"]
    assert img.characters is None
    assert img.display.startswith("[")
    assert not img.has_reading
    assert not subjects["kana_vocabulary:ホテル"].has_reading
    assert subjects["vocabulary:一人"].has_reading
    assert {r.type for r in subjects["kanji:大"].readings} == {"onyomi", "kunyomi", "nanori"}
