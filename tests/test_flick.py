import pytest

from durtleshells.domain.flick import GRID, KEYS, Direction, cycle, resolve


@pytest.mark.parametrize(
    "dx, dy, d",
    [
        (0, 0, Direction.CENTER),
        (1, 0, Direction.CENTER),  # 1 column = 0.5 after aspect correction
        (-1, 0, Direction.CENTER),
        (0, 0.9, Direction.CENTER),
        (2, 0, Direction.RIGHT),
        (-2, 0, Direction.LEFT),
        (0, 1, Direction.DOWN),
        (0, -1, Direction.UP),
        (4, 1, Direction.RIGHT),  # 2 vs 1 → horizontal wins
        (2, 1, Direction.RIGHT),  # tie → horizontal
        (2, 3, Direction.DOWN),
        (-3, -2, Direction.UP),
        (-6, -2, Direction.LEFT),
    ],
)
def test_resolve(dx, dy, d):
    assert resolve(dx, dy) is d


def test_full_layout():
    rows = {
        "あ": "あいうえお", "か": "かきくけこ", "さ": "さしすせそ", "た": "たちつてと",
        "な": "なにぬねの", "は": "はひふへほ", "ま": "まみむめも", "ら": "らりるれろ",
    }
    order = [Direction.CENTER, Direction.LEFT, Direction.UP, Direction.RIGHT, Direction.DOWN]
    for key, kana in rows.items():
        assert [KEYS[key].output(d) for d in order] == list(kana)
    assert [KEYS["や"].output(d) for d in order] == ["や", "（", "ゆ", "）", "よ"]
    assert [KEYS["わ"].output(d) for d in order] == ["わ", "を", "ん", "ー", None]
    assert KEYS["punct"].output(Direction.CENTER) == "、"
    assert KEYS["punct"].output(Direction.LEFT) == "。"
    assert KEYS["mod"].output(Direction.CENTER) is None
    assert KEYS["mod"].action == "modifier"


def test_grid_keys_exist():
    for row in GRID:
        for name in row:
            assert name is None or name in KEYS


@pytest.mark.parametrize(
    "chain",
    ["かがか", "はばぱは", "つっづつ", "やゃや", "あぁあ", "うぅゔう", "カガカ", "ツッヅツ", "よょよ"],
)
def test_cycle(chain):
    for a, b in zip(chain, chain[1:], strict=False):
        assert cycle(a) == b


def test_cycle_noop():
    assert cycle("ん") == "ん"
    assert cycle("x") == "x"
