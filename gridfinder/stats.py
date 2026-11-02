"""Basic grid statistics."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .grid import Grid, Slot, slots as get_slots


@dataclass
class GridStats:
    blocks: int
    words: int
    avg_len: float
    threes: int
    longest: int
    length_hist: dict[int, int] = field(default_factory=dict)


def compute_stats(grid: Grid, slot_list: list[Slot] | None = None) -> GridStats:
    if slot_list is None:
        slot_list = get_slots(grid, 3)
    lengths = [s.length for s in slot_list]
    words = len(lengths)
    return GridStats(
        blocks=grid.block_count,
        words=words,
        avg_len=(sum(lengths) / words) if words else 0.0,
        threes=sum(1 for x in lengths if x == 3),
        longest=max(lengths, default=0),
        length_hist=dict(sorted(Counter(lengths).items())),
    )
