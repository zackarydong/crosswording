"""Seed entries: loading, and assigning seeds to slots of an existing grid."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .grid import Grid, Slot, slots as get_slots

MIN_SEED, MAX_SEED = 7, 15


def parse_seeds(text: str, n: int = 15) -> list[str]:
    seeds: list[str] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        w = raw.upper().replace(" ", "")
        if not re.fullmatch(r"[A-Z]+", w):
            raise ValueError(f"seed {raw!r} must contain letters only")
        if not (MIN_SEED <= len(w) <= min(MAX_SEED, n)):
            raise ValueError(f"seed {w} has {len(w)} letters; seeds must be {MIN_SEED}-{min(MAX_SEED, n)}")
        seeds.append(w)
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate seed entries")
    if not seeds:
        raise ValueError("no seeds given")
    return seeds


def load_seeds(path: str | Path, n: int = 15) -> list[str]:
    return parse_seeds(Path(path).read_text(encoding="utf-8"), n)


@dataclass
class Conflict:
    seed_a: str
    slot_a: Slot
    seed_b: str
    slot_b: Slot
    row: int
    col: int
    letter_a: str
    letter_b: str

    def describe(self) -> str:
        return (
            f"{self.seed_a} ({self.slot_a.label()}) and {self.seed_b} ({self.slot_b.label()}) "
            f"cross at row {self.row + 1}, col {self.col + 1}: {self.letter_a} vs {self.letter_b}"
        )


@dataclass
class Placement:
    ok: bool
    assignment: dict[str, Slot] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)
    unplaceable: list[str] = field(default_factory=list)  # no slot of that length at all


def letters_for(assignment: dict[str, Slot], n_cells: int) -> list[str | None]:
    out: list[str | None] = [None] * n_cells
    for word, slot in assignment.items():
        for ch, i in zip(word, slot.cells):
            out[i] = ch
    return out


def place_seeds(grid: Grid, seeds: list[str], max_conflicts: int = 50) -> Placement:
    """Assign every seed to a distinct slot of exactly its length with consistent
    crossings (backtracking). Conflicting crossings encountered are reported."""
    all_slots = get_slots(grid, 3)
    by_len: dict[int, list[Slot]] = {}
    for s in all_slots:
        by_len.setdefault(s.length, []).append(s)
    unplaceable = [w for w in seeds if not by_len.get(len(w))]
    if unplaceable:
        return Placement(False, unplaceable=unplaceable)
    # Also need enough slots of each length.
    order = sorted(seeds, key=lambda w: len(by_len[len(w)]))
    n_cells = grid.n * grid.n
    letters: list[str | None] = [None] * n_cells
    owner: list[str | None] = [None] * n_cells
    used: set[Slot] = set()
    assignment: dict[str, Slot] = {}
    conflicts: dict[tuple, Conflict] = {}

    def fits(word: str, slot: Slot) -> bool:
        ok = True
        for ch, i in zip(word, slot.cells):
            if letters[i] is not None and letters[i] != ch:
                ok = False
                other = owner[i]
                key = (word, slot.cells, other, i)
                if key not in conflicts and len(conflicts) < max_conflicts:
                    r, c = divmod(i, grid.n)
                    conflicts[key] = Conflict(other, assignment[other], word, slot, r, c, letters[i], ch)
        return ok

    def rec(k: int) -> bool:
        if k == len(order):
            return True
        word = order[k]
        for slot in by_len[len(word)]:
            if slot in used or not fits(word, slot):
                continue
            prev = [letters[i] for i in slot.cells]
            prev_owner = [owner[i] for i in slot.cells]
            for ch, i in zip(word, slot.cells):
                letters[i] = ch
                owner[i] = owner[i] or word
            used.add(slot)
            assignment[word] = slot
            if rec(k + 1):
                return True
            del assignment[word]
            used.discard(slot)
            for i, p, o in zip(slot.cells, prev, prev_owner):
                letters[i] = p
                owner[i] = o
        return False

    ok = rec(0)
    if not ok:
        # Not enough slots of some length?
        from collections import Counter

        need = Counter(len(w) for w in seeds)
        short = [f"{L}-letter (need {c}, have {len(by_len.get(L, []))})" for L, c in need.items() if len(by_len.get(L, [])) < c]
        if short:
            unplaceable = short
    return Placement(ok, dict(assignment) if ok else {}, list(conflicts.values()), unplaceable)
