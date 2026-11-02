"""Randomized, symmetry-preserving grid search.

Each attempt:
  1. Lay out the seeds: pick a random legal position for each seed (longest
     first). Its squares become locked white, the squares just before/after it
     become locked black, and the 180-degree mirror of all of that is applied.
     Seeds may land in each other's mirror slot or cross at matching letters;
     positions that would cross another seed at a different letter are
     rejected and tallied for the report.
  2. Repair: black out any 1-2 letter runs created by the seed caps.
  3. Fill: repeatedly add a mirrored pair of blocks, chosen with Friday-style
     biases, keeping every run either 0 or >=3 long, no 3x3 black square, and
     all white squares connected, until a sampled target word count is hit.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from .grid import ACROSS, DOWN, Grid, Slot, has_solid_block, is_connected, slots as get_slots, violations

FREE, WHITE, BLACK = 0, 1, 2


@dataclass
class SeedSpot:
    word: str
    direction: str
    row: int
    col: int
    cells: tuple[int, ...]


@dataclass
class Candidate:
    grid: Grid
    spots: list[SeedSpot]
    letters: list[str | None]
    seed_slots: dict[str, Slot]


@dataclass
class SearchLog:
    attempts: int = 0
    layout_failed: int = 0
    repair_failed: int = 0
    fill_failed: int = 0
    fill_reasons: Counter = field(default_factory=Counter)
    invalid: int = 0
    produced: int = 0
    duplicates: int = 0


class Searcher:
    def __init__(self, seeds: list[str], cfg: dict, rng: random.Random):
        self.seeds = seeds
        self.cfg = cfg
        self.rng = rng
        self.n = n = cfg["hard"]["size"]
        self.nn = n * n
        self.rows = [[r * n + c for c in range(n)] for r in range(n)]
        self.cols = [[r * n + c for r in range(n)] for c in range(n)]
        self.log = SearchLog()
        s = cfg["search"]
        self.bias = s
        self.min_len = cfg["hard"]["min_entry"]
        self._pos_cache: dict[int, list] = {}
        from .grid import neighbors

        self._orth = neighbors(n)
        self._diag = []
        self._static_w = []
        for i in range(self.nn):
            r, c = divmod(i, n)
            self._diag.append(tuple(
                (r + dr) * n + c + dc
                for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1))
                if 0 <= r + dr < n and 0 <= c + dc < n
            ))
            sw = 0.0
            if abs(r - c) <= 1 or abs(r + c - (n - 1)) <= 1:
                sw += s["x_pattern"]
            if r in (0, n - 1) or c in (0, n - 1):
                sw += s["edge"]
            self._static_w.append(sw)

    # ----- helpers -----------------------------------------------------------
    def m(self, i: int) -> int:
        return self.nn - 1 - i

    def _line_ok(self, black: bytearray, line: list[int]) -> bool:
        run = 0
        for i in line:
            if black[i]:
                if 0 < run < self.min_len:
                    return False
                run = 0
            else:
                run += 1
        return not (0 < run < self.min_len)

    def _word_count(self, black: bytearray) -> int:
        total = 0
        for line in self.rows + self.cols:
            run = 0
            for i in line:
                if black[i]:
                    if run >= self.min_len:
                        total += 1
                    run = 0
                else:
                    run += 1
            if run >= self.min_len:
                total += 1
        return total

    def _solid_near(self, black: bytearray, i: int) -> bool:
        n = self.n
        r0, c0 = divmod(i, n)
        for r in range(max(0, r0 - 2), min(n - 3, r0) + 1):
            for c in range(max(0, c0 - 2), min(n - 3, c0) + 1):
                if all(black[(r + dr) * n + c + dc] for dr in range(3) for dc in range(3)):
                    return True
        return False

    # ----- step 1: seeds -----------------------------------------------------
    def _positions(self, L: int):
        """All in-bounds positions for a length-L entry (cached). Positions whose
        end caps would land on their own mirror image are dropped up front."""
        if L in self._pos_cache:
            return self._pos_cache[L]
        n, last = self.n, self.nn - 1
        out = []
        for d in (ACROSS, DOWN):
            for a in range(n):  # row for across, col for down
                for b in range(n - L + 1):
                    if d == ACROSS:
                        cells = tuple(a * n + b + k for k in range(L))
                        before = a * n + b - 1 if b > 0 else None
                        after = a * n + b + L if b + L < n else None
                    else:
                        cells = tuple((b + k) * n + a for k in range(L))
                        before = (b - 1) * n + a if b > 0 else None
                        after = (b + L) * n + a if b + L < n else None
                    caps = tuple(x for x in (before, after) if x is not None)
                    own_mirror = {last - i for i in cells}
                    if any(cap in own_mirror for cap in caps):
                        continue
                    mirror = tuple(sorted(own_mirror))
                    out.append((d, a, b, cells, caps, mirror))
        self._pos_cache[L] = out
        return out

    def _seed_positions(self, word, black, lock, letters, placed):
        last = self.nn - 1
        placed_cells = {sp.cells for sp in placed}
        placed_same_len = {sp.cells for sp in placed if len(sp.word) == len(word)}
        cross_bias, pair_bias = self.bias["cross_bias"], self.bias["pair_bias"]
        out = []
        for d, a, b, cells, caps, mirror in self._positions(len(word)):
            if cells in placed_cells:
                continue
            ok = True
            crossings = 0
            for ch, i in zip(word, cells):
                if black[i] or black[last - i]:
                    ok = False
                    break
                li = letters[i]
                if li is not None:
                    if li != ch:
                        ok = False
                        break
                    crossings += 1
            if not ok:
                continue
            if any(lock[cap] == WHITE or lock[last - cap] == WHITE for cap in caps):
                continue
            w = 1.0 + cross_bias * crossings
            if mirror in placed_same_len:
                w *= pair_bias
            out.append((w, d, a, b, cells, caps))
        return out

    def _layout(self):
        n = self.n
        black = bytearray(self.nn)
        lock = bytearray(self.nn)
        letters: list[str | None] = [None] * self.nn
        owner: list[str | None] = [None] * self.nn
        placed: list[SeedSpot] = []
        order = sorted(self.seeds, key=lambda w: (-len(w), self.rng.random()))
        for word in order:
            opts = self._seed_positions(word, black, lock, letters, placed)
            if not opts:
                return None
            # Weighted random order; take the first position whose caps can be repaired.
            opts.sort(key=lambda o: self.rng.random() ** (1.0 / o[0]), reverse=True)
            for w, d, a, b, cells, caps in opts[:40]:
                nb, nl, nlet, nown = bytearray(black), bytearray(lock), letters[:], owner[:]
                for ch, i in zip(word, cells):
                    nlet[i] = ch
                    nown[i] = nown[i] or word
                    nl[i] = WHITE
                    nl[self.m(i)] = WHITE
                for cap in caps:
                    for j in (cap, self.m(cap)):
                        nl[j] = BLACK
                        nb[j] = 1
                if self._repair(nb, nl) and not has_solid_block(nb, n):
                    black, lock, letters, owner = nb, nl, nlet, nown
                    r, c = (a, b) if d == ACROSS else (b, a)
                    placed.append(SeedSpot(word, d, r, c, cells))
                    break
            else:
                self.log.repair_failed += 1
                return None
        return black, lock, letters, placed

    # ----- step 2: repair ----------------------------------------------------
    def _repair(self, black, lock) -> bool:
        for _ in range(60):
            bad = None
            for line in self.rows + self.cols:
                run: list[int] = []
                for i in line + [None]:
                    if i is None or black[i]:
                        if 0 < len(run) < self.min_len:
                            bad = run
                            break
                        run = []
                    else:
                        run.append(i)
                if bad:
                    break
            if not bad:
                return True
            for i in bad:
                if lock[i] == WHITE or lock[self.m(i)] == WHITE:
                    return False
                black[i] = black[self.m(i)] = 1
        return False

    # ----- step 3: fill ------------------------------------------------------
    def _weight(self, black, i) -> float:
        b = self.bias
        orth = 0
        for j in self._orth[i]:
            orth += black[j]
        w = b["base"]
        if orth == 0:
            for j in self._diag[i]:
                if black[j]:
                    w += b["diag"]
                    break
        elif orth == 1:
            w += b["extend"]
        w += self._static_w[i]
        if orth >= 2:
            w *= b["clump"]
        return w

    def _threes(self, black, lines) -> int:
        k = 0
        for line in lines:
            run = 0
            for i in line:
                if black[i]:
                    k += run == 3
                    run = 0
                else:
                    run += 1
            k += run == 3
        return k

    def _try_block(self, black, i) -> bool:
        n = self.n
        j = self.m(i)
        lines = [self.rows[i // n], self.cols[i % n], self.rows[j // n], self.cols[j % n]]
        before = self._threes(black, lines) if self.bias["three_reject"] > 0 else 0
        black[i] = black[j] = 1
        if before is not None and self.bias["three_reject"] > 0:
            if self._threes(black, lines) > before and self.rng.random() < self.bias["three_reject"]:
                black[i] = black[j] = 0
                return False
        ok = (
            self._line_ok(black, self.rows[i // n])
            and self._line_ok(black, self.cols[i % n])
            and self._line_ok(black, self.rows[j // n])
            and self._line_ok(black, self.cols[j % n])
            and not self._solid_near(black, i)
            and not self._solid_near(black, j)
            and is_connected(black, n)
        )
        if not ok:
            black[i] = black[j] = 0
        return ok

    def _fill(self, black, lock) -> bool:
        h = self.cfg["hard"]
        t = self.cfg["targets"]
        lo, hi = t["words"]
        hi = min(hi, h["max_words"])
        lo = min(lo, hi)
        target = self.rng.randint(lo, hi)
        accept_floor = lo - self.bias["stuck_slack"]  # stuck below target: keep if words >= this
        half = self.nn // 2
        if not is_connected(black, self.n):
            self.fill_reason("disconnected after seeds")
            return False
        words = self._word_count(black)
        for _ in range(400):
            nb = sum(black)
            if words >= target and nb >= h["min_blocks"]:
                return True
            cands = [i for i in range(half + 1) if not black[i] and lock[i] == FREE and lock[self.m(i)] == FREE]
            keyed = sorted(cands, key=lambda i: self.rng.random() ** (1.0 / self._weight(black, i)), reverse=True)
            for i in keyed[:80]:
                if nb + (1 if i == self.m(i) else 2) > h["max_blocks"]:
                    continue
                if self._try_block(black, i):
                    w2 = self._word_count(black)
                    if w2 <= h["max_words"]:
                        words = w2
                        break
                    black[i] = black[self.m(i)] = 0
            else:
                if words >= accept_floor and nb >= h["min_blocks"]:
                    return True
                self.fill_reason("stuck below target")
                return False
        self.fill_reason("too many moves")
        return False

    def fill_reason(self, r: str) -> None:
        self.log.fill_reasons[r] += 1

    # ----- one attempt ----------------------------------------------------------
    def attempt(self) -> Candidate | None:
        self.log.attempts += 1
        lay = self._layout()
        if lay is None:
            self.log.layout_failed += 1
            return None
        black, lock, letters, spots = lay
        if not self._fill(black, lock):
            self.log.fill_failed += 1
            return None
        g = Grid(self.n, black)
        v = violations(g, self.cfg["hard"]["max_words"], self.min_len)
        if v:
            self.log.invalid += 1
            self.log.fill_reasons["invalid: " + v[0].split(",")[0]] += 1
            return None
        slot_by_cells = {s.cells: s for s in get_slots(g, self.min_len)}
        seed_slots = {}
        for sp in spots:
            s = slot_by_cells.get(sp.cells)
            if s is None:  # should not happen: seed squares locked and capped
                self.log.invalid += 1
                return None
            seed_slots[sp.word] = s
        self.log.produced += 1
        return Candidate(g, spots, letters, seed_slots)
