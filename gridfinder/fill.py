"""Fillability proxy: how many word-list candidates fit each slot, given the
letters fixed by seeds."""

from __future__ import annotations

from dataclasses import dataclass, field

from .grid import Slot
from .wordlist import WordList


@dataclass
class SlotFill:
    slot: Slot
    pattern: str
    candidates: int
    good: int


@dataclass
class FillReport:
    score: float  # 0-100, 100 = no problem slots
    dead: list[SlotFill] = field(default_factory=list)  # 0 candidates
    tight: list[SlotFill] = field(default_factory=list)  # 1..few-1 candidates
    min_candidates: int = 0
    constrained: int = 0  # slots with at least one seed letter (excluding seed slots)


def fillability(
    slot_list: list[Slot],
    letters: list[str | None],
    seed_slots: set[Slot],
    wordlist: WordList,
    few: int = 5,
    dead_penalty: float = 25.0,
    tight_penalty: float = 8.0,
    good_bonus: float = 0.0,
) -> FillReport:
    penalty = 0.0
    dead: list[SlotFill] = []
    tight: list[SlotFill] = []
    min_c: int | None = None
    constrained = 0
    for s in slot_list:
        if s in seed_slots:
            continue
        pat = "".join(letters[i] or "." for i in s.cells)
        if pat.count(".") == len(pat):
            n_ok = wordlist.n_words(s.length)
            n_good = n_ok
        else:
            constrained += 1
            n_ok, n_good = wordlist.count(pat)
        sf = SlotFill(s, pat, n_ok, n_good)
        min_c = n_ok if min_c is None else min(min_c, n_ok)
        if n_ok == 0:
            dead.append(sf)
            penalty += dead_penalty
        elif n_ok < few:
            tight.append(sf)
            penalty += tight_penalty * (few - n_ok) / few
            if n_good:
                penalty -= min(good_bonus, tight_penalty * (few - n_ok) / few)
    return FillReport(max(0.0, 100.0 - penalty), dead, tight, min_c or 0, constrained)
