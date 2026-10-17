"""Flick keyboard widget: press a key, drag in a direction, release to type.

It never takes focus, so romaji typing keeps working while it's visible.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

from ...domain.flick import GRID, KEYS, Direction, FlickKey, resolve

KEY_W, KEY_H, GAP_X, GAP_Y = 10, 3, 1, 1
PAD_X, PAD_Y = 2, 1  # room for the popup cross around edge keys
COLS = len(GRID[0])
ROWS = len(GRID)
WIDTH = PAD_X * 2 + COLS * KEY_W + (COLS - 1) * GAP_X
HEIGHT = PAD_Y * 2 + ROWS * KEY_H + (ROWS - 1) * GAP_Y

KEY_BG = Style(color="#e0e0e0", bgcolor="#3a3a3a")
KEY_FAINT = Style(color="#8a8a8a", bgcolor="#3a3a3a")
CTRL_BG = Style(color="#e0e0e0", bgcolor="#2a2f3a")
PRESSED_BG = Style(color="#ffffff", bgcolor="#5a5a5a")
POPUP = Style(color="#202020", bgcolor="#d0d0d0", bold=True)
POPUP_HOT = Style(color="#ffffff", bgcolor="#e0218a", bold=True)
EMPTY = Style()

# Direction → (dx, dy) of the popup cell relative to the key's centre cell.
POPUP_OFFSETS = {
    Direction.CENTER: (0, 0),
    Direction.LEFT: (-4, 0),
    Direction.UP: (0, -2),
    Direction.RIGHT: (4, 0),
    Direction.DOWN: (0, 2),
}


class _Canvas:
    """A grid of terminal cells that understands double-width characters."""

    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = width, height
        self.cells: list[list[tuple[str | None, Style]]] = [
            [(" ", EMPTY) for _ in range(width)] for _ in range(height)
        ]

    def _clear(self, x: int, y: int) -> None:
        row = self.cells[y]
        ch, style = row[x]
        if ch is None and x > 0:  # right half of a wide char
            row[x - 1] = (" ", row[x - 1][1])
        elif ch and cell_len(ch) == 2 and x + 1 < self.w:
            row[x + 1] = (" ", row[x + 1][1])

    def fill(self, x: int, y: int, w: int, h: int, style: Style) -> None:
        for yy in range(max(0, y), min(self.h, y + h)):
            for xx in range(max(0, x), min(self.w, x + w)):
                self._clear(xx, yy)
                self.cells[yy][xx] = (" ", style)

    def text(self, x: int, y: int, text: str, style: Style) -> None:
        if not 0 <= y < self.h:
            return
        for ch in text:
            width = cell_len(ch)
            if x < 0 or x + width > self.w:
                x += width
                continue
            self._clear(x, y)
            if width == 2:
                self._clear(x + 1, y)
                self.cells[y][x] = (ch, style)
                self.cells[y][x + 1] = (None, style)
            else:
                self.cells[y][x] = (ch, style)
            x += width

    def render(self) -> Text:
        out = Text(no_wrap=True, overflow="crop")
        for i, row in enumerate(self.cells):
            if i:
                out.append("\n")
            for ch, style in row:
                if ch is not None:
                    out.append(ch, style)
        return out


def key_origin(row: int, col: int) -> tuple[int, int]:
    return PAD_X + col * (KEY_W + GAP_X), PAD_Y + row * (KEY_H + GAP_Y)


def key_at(x: int, y: int) -> tuple[int, int] | None:
    gx, gy = x - PAD_X, y - PAD_Y
    if gx < 0 or gy < 0:
        return None
    col, ox = divmod(gx, KEY_W + GAP_X)
    row, oy = divmod(gy, KEY_H + GAP_Y)
    if col >= COLS or row >= ROWS or ox >= KEY_W or oy >= KEY_H:
        return None
    if GRID[row][col] is None:
        return None
    return row, col


class FlickKeyboard(Widget):
    ALLOW_SELECT = False
    can_focus = False

    DEFAULT_CSS = f"""
    FlickKeyboard {{ width: {WIDTH}; height: {HEIGHT}; }}
    """

    class Pressed(Message):
        """``action`` is kana | modifier | backspace | space | submit."""

        def __init__(self, action: str, text: str | None = None) -> None:
            super().__init__()
            self.action = action
            self.text = text

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._drag: tuple[int, int, int, int] | None = None  # row, col, screen x, screen y
        self._direction = Direction.CENTER

    # ---- rendering ---------------------------------------------------------

    def render(self) -> Text:
        canvas = _Canvas(WIDTH, HEIGHT)
        for r, row in enumerate(GRID):
            for c, name in enumerate(row):
                if name is not None:
                    pressed = self._drag is not None and self._drag[:2] == (r, c)
                    self._draw_key(canvas, r, c, KEYS[name], pressed)
        if self._drag is not None:
            r, c = self._drag[:2]
            key = KEYS[GRID[r][c]]  # type: ignore[index]
            if key.action == "kana":
                self._draw_popup(canvas, r, c, key)
        return canvas.render()

    def _draw_key(self, canvas: _Canvas, r: int, c: int, key: FlickKey, pressed: bool) -> None:
        x0, y0 = key_origin(r, c)
        bg = PRESSED_BG if pressed else (KEY_BG if key.action == "kana" else CTRL_BG)
        canvas.fill(x0, y0, KEY_W, KEY_H, bg)
        if key.action != "kana":
            label = key.label
            canvas.text(x0 + (KEY_W - cell_len(label)) // 2, y0 + 1, label, bg + Style(bold=True))
            return
        cands = key.candidates
        centre = cands[0] or key.label
        canvas.text(x0 + 4, y0 + 1, centre, bg + Style(bold=True))
        if pressed:
            return  # the popup cross shows the candidates
        faint = KEY_FAINT
        if cands[Direction.UP.value]:
            canvas.text(x0 + 4, y0, cands[Direction.UP.value], faint)
        if cands[Direction.LEFT.value]:
            canvas.text(x0 + 1, y0 + 1, cands[Direction.LEFT.value], faint)
        if cands[Direction.RIGHT.value]:
            canvas.text(x0 + 7, y0 + 1, cands[Direction.RIGHT.value], faint)
        if cands[Direction.DOWN.value]:
            canvas.text(x0 + 4, y0 + 2, cands[Direction.DOWN.value], faint)

    def _draw_popup(self, canvas: _Canvas, r: int, c: int, key: FlickKey) -> None:
        x0, y0 = key_origin(r, c)
        cx, cy = x0 + 4, y0 + 1
        for direction, (dx, dy) in POPUP_OFFSETS.items():
            kana = key.candidates[direction.value]
            if not kana:
                continue
            style = POPUP_HOT if direction is self._direction else POPUP
            canvas.text(cx + dx - 1, cy + dy, f" {kana} ", style)

    # ---- mouse -------------------------------------------------------------

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        hit = key_at(event.x, event.y)
        if hit is None:
            return
        event.stop()
        self._drag = (hit[0], hit[1], event.screen_x, event.screen_y)
        self._direction = Direction.CENTER
        self.capture_mouse()
        self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag is None:
            return
        event.stop()
        direction = resolve(event.screen_x - self._drag[2], event.screen_y - self._drag[3])
        if direction is not self._direction:
            self._direction = direction
            self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag is None:
            return
        event.stop()
        self.release_mouse()
        r, c, sx, sy = self._drag
        self._drag = None
        direction = resolve(event.screen_x - sx, event.screen_y - sy)
        self._direction = Direction.CENTER
        self.refresh()
        self.post_message(self.press(r, c, direction))

    @staticmethod
    def press(row: int, col: int, direction: Direction) -> FlickKeyboard.Pressed:
        key = KEYS[GRID[row][col]]  # type: ignore[index]
        if key.action == "kana":
            return FlickKeyboard.Pressed("kana", key.output(direction))
        return FlickKeyboard.Pressed(key.action)
