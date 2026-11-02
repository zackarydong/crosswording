"""Core grid representation, slot extraction and hard-constraint checks.

A grid is an n x n board of black ("#") and white (".") squares, stored as a
flat bytearray where 1 = black and 0 = white. Cell index i = r * n + c.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

ACROSS = "A"
DOWN = "D"


@dataclass(frozen=True)
class Slot:
    """A maximal run of white squares in one direction."""

    direction: str  # "A" or "D"
    row: int
    col: int
    length: int
    cells: tuple[int, ...]

    def label(self) -> str:
        word = "Across" if self.direction == ACROSS else "Down"
        return f"{word} at row {self.row + 1}, col {self.col + 1} ({self.length} letters)"


class Grid:
    def __init__(self, n: int = 15, blocks: Iterable[int] | None = None):
        self.n = n
        self.b = bytearray(n * n) if blocks is None else bytearray(blocks)
        if len(self.b) != n * n:
            raise ValueError("block array has wrong size")

    # ----- construction / IO -------------------------------------------------
    @classmethod
    def from_text(cls, text: str) -> "Grid":
        """Parse rows of '#' (block) and '.'/letters (white). Spaces ignored."""
        rows = []
        for line in text.splitlines():
            line = line.replace(" ", "").strip()
            if not line:
                continue
            rows.append(line)
        n = len(rows)
        if n == 0 or any(len(r) != n for r in rows):
            raise ValueError(f"grid must be square; got {n} rows of lengths {[len(r) for r in rows]}")
        blocks = [1 if ch == "#" else 0 for r in rows for ch in r]
        return cls(n, blocks)

    def to_text(self) -> str:
        n = self.n
        return "\n".join(
            "".join("#" if self.b[r * n + c] else "." for c in range(n)) for r in range(n)
        )

    def copy(self) -> "Grid":
        return Grid(self.n, self.b)

    def key(self) -> bytes:
        return bytes(self.b)

    # ----- basic accessors ---------------------------------------------------
    def is_block(self, r: int, c: int) -> bool:
        return bool(self.b[r * self.n + c])

    def mirror(self, i: int) -> int:
        return self.n * self.n - 1 - i

    def set_block(self, r: int, c: int, value: bool = True, symmetric: bool = True) -> None:
        i = r * self.n + c
        self.b[i] = 1 if value else 0
        if symmetric:
            self.b[self.mirror(i)] = 1 if value else 0

    @property
    def block_count(self) -> int:
        return sum(self.b)

    @property
    def white_count(self) -> int:
        return self.n * self.n - self.block_count

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Grid) and self.n == other.n and self.b == other.b

    def __hash__(self) -> int:
        return hash(self.key())

    def __repr__(self) -> str:
        return f"Grid(n={self.n}, blocks={self.block_count})\n{self.to_text()}"


# ----- slot extraction -------------------------------------------------------
def all_runs(blocks: bytes | bytearray, n: int) -> list[Slot]:
    """Every maximal white run (any length >= 1), across then down."""
    slots: list[Slot] = []
    for r in range(n):
        c = 0
        while c < n:
            if blocks[r * n + c]:
                c += 1
                continue
            start = c
            while c < n and not blocks[r * n + c]:
                c += 1
            cells = tuple(r * n + k for k in range(start, c))
            slots.append(Slot(ACROSS, r, start, c - start, cells))
    for c in range(n):
        r = 0
        while r < n:
            if blocks[r * n + c]:
                r += 1
                continue
            start = r
            while r < n and not blocks[r * n + c]:
                r += 1
            cells = tuple(k * n + c for k in range(start, r))
            slots.append(Slot(DOWN, start, c, r - start, cells))
    return slots


def slots(grid: Grid, min_len: int = 2) -> list[Slot]:
    """Entries: runs of length >= min_len (crossword convention: 1-letter runs aren't words)."""
    return [s for s in all_runs(grid.b, grid.n) if s.length >= min_len]


def numbering(grid: Grid) -> dict[int, int]:
    """Clue numbers: cell index -> number, standard top-left reading order."""
    n = grid.n
    starts = {s.cells[0] for s in slots(grid, 2)}
    nums: dict[int, int] = {}
    k = 0
    for i in range(n * n):
        if i in starts:
            k += 1
            nums[i] = k
    return nums


# ----- hard constraints ------------------------------------------------------
def is_symmetric(grid: Grid) -> bool:
    b = grid.b
    last = len(b) - 1
    return all(b[i] == b[last - i] for i in range(len(b) // 2 + 1))


_NEIGHBORS: dict[int, list[tuple[int, ...]]] = {}


def neighbors(n: int) -> list[tuple[int, ...]]:
    """Orthogonal neighbor indices of every cell (cached per grid size)."""
    if n not in _NEIGHBORS:
        out = []
        for i in range(n * n):
            r, c = divmod(i, n)
            out.append(tuple(j for j, ok in ((i - n, r > 0), (i + n, r < n - 1), (i - 1, c > 0), (i + 1, c < n - 1)) if ok))
        _NEIGHBORS[n] = out
    return _NEIGHBORS[n]


def is_connected(blocks: bytes | bytearray, n: int) -> bool:
    nb = neighbors(n)
    total = len(blocks) - sum(blocks)
    if total == 0:
        return False
    start = blocks.index(0)
    seen = bytearray(blocks)  # blacks count as seen
    seen[start] = 1
    stack = [start]
    count = 1
    while stack:
        for j in nb[stack.pop()]:
            if not seen[j]:
                seen[j] = 1
                count += 1
                stack.append(j)
    return count == total


def has_solid_block(blocks: bytes | bytearray, n: int, k: int = 3) -> bool:
    """True if any k x k square is entirely black."""
    for r in range(n - k + 1):
        for c in range(n - k + 1):
            if all(blocks[(r + dr) * n + c + dc] for dr in range(k) for dc in range(k)):
                return True
    return False


def short_runs(grid: Grid, min_len: int = 3) -> list[Slot]:
    """Runs shorter than min_len. Length-1 runs mean an unchecked square."""
    return [s for s in all_runs(grid.b, grid.n) if s.length < min_len]


def violations(grid: Grid, max_words: int = 72, min_len: int = 3) -> list[str]:
    """All hard-constraint violations (empty list = valid)."""
    out: list[str] = []
    if not is_symmetric(grid):
        out.append("not 180-degree rotationally symmetric")
    shorts = short_runs(grid, min_len)
    unchecked = [s for s in shorts if s.length == 1]
    too_short = [s for s in shorts if s.length > 1]
    if unchecked:
        out.append(f"{len(unchecked)} unchecked square run(s), e.g. {unchecked[0].label()}")
    if too_short:
        out.append(f"{len(too_short)} entry(ies) shorter than {min_len}, e.g. {too_short[0].label()}")
    if not is_connected(grid.b, grid.n):
        out.append("white squares are not all connected")
    if has_solid_block(grid.b, grid.n, 3):
        out.append("contains a solid 3x3 black block")
    words = len(slots(grid, min_len))
    if words > max_words:
        out.append(f"{words} words exceeds max {max_words}")
    return out


def is_valid(grid: Grid, max_words: int = 72, min_len: int = 3) -> bool:
    return not violations(grid, max_words, min_len)
