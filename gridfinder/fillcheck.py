"""Real fillability check: can the grid actually be filled from the word list?

Two layers:
  1. Arc consistency (AC-3): every slot keeps only words whose letter at each
     crossing is still possible for the crossing slot. If any slot runs out of
     words, the grid is provably impossible with this word list.
  2. Time-limited backtracking fill (most-constrained slot first, best-scored
     words first, no repeated answers). Success gives a sample fill that proves
     the grid is fillable; a timeout means "unknown", not impossible.

Seed squares are fixed letters; seed slots themselves are not filled from the list
(seeds need not be in the word list).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from .grid import Grid, Slot, slots as get_slots
from .wordlist import WordList

FILLED, IMPOSSIBLE, UNKNOWN = "filled", "impossible", "unknown (time limit)"


class _Timeout(Exception):
    pass


@dataclass
class FillResult:
    status: str
    seconds: float
    letters: list[str | None] | None = None  # full fill when status == FILLED
    words: dict[Slot, str] = field(default_factory=dict)
    dead_slot: Slot | None = None  # a slot left with no words, when IMPOSSIBLE
    min_domain: int = 0  # smallest candidate count after pruning
    nodes: int = 0

    def summary(self) -> str:
        if self.status == FILLED:
            shown = " (sample fill below)" if self.letters else " (fill hidden; --show-fill to see it)"
            return f"VERIFIED FILLABLE with your word list, found in {self.seconds:.1f}s{shown}"
        if self.status == IMPOSSIBLE:
            where = f": no words left for {self.dead_slot.label()}" if self.dead_slot else ""
            return f"IMPOSSIBLE with this word list{where}"
        return f"UNKNOWN: no fill found within {self.seconds:.0f}s (may still be fillable)"


class Filler:
    def __init__(self, grid: Grid, letters: list[str | None], seed_slots: set[Slot], wordlist: WordList):
        self.grid = grid
        self.wl = wordlist
        self.fixed = letters
        self.slots = [s for s in get_slots(grid, 3) if s not in seed_slots]
        self.mats = [wordlist.matrix(s.length) for s in self.slots]
        self.colsT = [[np.ascontiguousarray(m[:, p]) for p in range(m.shape[1])] for m in self.mats]
        index: dict[int, list[tuple[int, int]]] = {}
        for k, s in enumerate(self.slots):
            for p, i in enumerate(s.cells):
                index.setdefault(i, []).append((k, p))
        # cross[k] = list of (pos in k, other slot, pos in other)
        self.cross: list[list[tuple[int, int, int]]] = [[] for _ in self.slots]
        for i, entries in index.items():
            if len(entries) == 2:
                (a, pa), (b, pb) = entries
                self.cross[a].append((pa, b, pb))
                self.cross[b].append((pb, a, pa))

    # ----- domains -------------------------------------------------------------
    def initial_domains(self) -> list[np.ndarray] | int:
        doms = []
        for k, s in enumerate(self.slots):
            m = self.mats[k]
            mask = np.ones(m.shape[0], dtype=bool)
            for p, i in enumerate(s.cells):
                ch = self.fixed[i]
                if ch:
                    mask &= m[:, p] == ord(ch)
            idx = np.nonzero(mask)[0]
            # best-scored first (stable)
            sc = self.wl.scores(s.length)
            if len(idx):
                idx = idx[np.argsort(-sc[idx], kind="stable")]
            if len(idx) == 0:
                return k
            doms.append(idx)
        return doms

    def _pres(self, k: int, dom: np.ndarray) -> np.ndarray:
        """(length, 128) bool: which letters are still possible at each position."""
        L = self.slots[k].length
        out = np.zeros((L, 128), dtype=bool)
        cols = self.colsT[k]
        for p in range(L):
            out[p, cols[p][dom]] = True
        return out

    def propagate(self, doms: list[np.ndarray], pres: list[np.ndarray], queue: set[int], cascade: bool = True) -> int:
        """AC-3 over (domains, letter-presence) lists, updated in place.
        Returns -1 if consistent, else the index of a wiped-out slot."""
        while queue:
            k = queue.pop()
            pk = pres[k]
            for p, o, q in self.cross[k]:
                allowed = pk[p]
                if not (pres[o][q] & ~allowed).any():
                    continue
                do = doms[o]
                do = do[allowed[self.colsT[o][q][do]]]
                if len(do) == 0:
                    return o
                doms[o] = do
                pres[o] = self._pres(o, do)
                if cascade:
                    queue.add(o)
        return -1

    # ----- API -----------------------------------------------------------------
    def arc_check(self) -> FillResult:
        t = time.time()
        doms = self.initial_domains()
        if isinstance(doms, int):
            return FillResult(IMPOSSIBLE, time.time() - t, dead_slot=self.slots[doms])
        pres = [self._pres(k, d) for k, d in enumerate(doms)]
        dead = self.propagate(doms, pres, set(range(len(self.slots))))
        if dead >= 0:
            return FillResult(IMPOSSIBLE, time.time() - t, dead_slot=self.slots[dead])
        self._doms = doms
        self._pres_root = pres
        return FillResult(UNKNOWN, time.time() - t, min_domain=min((len(d) for d in doms), default=0))

    def fill(
        self, time_limit: float = 20.0, branch: int = 40, restart_nodes: int = 400, seed: int = 0, cascade: bool = True
    ) -> FillResult:
        """Randomized restarts: each run explores at most `restart_nodes` nodes,
        trying well-scored words first with some shuffling, then starts over.
        A run that finishes without hitting any limit is a full search, so a
        failure there proves the grid impossible."""
        import random

        t0 = time.time()
        res = self.arc_check()
        if res.status == IMPOSSIBLE:
            return res
        deadline = t0 + time_limit
        rng = random.Random(seed)
        total_nodes = 0

        def word_of(k: int, idx: int) -> str:
            return self.mats[k][idx].tobytes().decode("ascii")

        class _Budget(Exception):
            pass

        def run(budget: int | None, shuffle: bool):
            state = {"nodes": 0, "truncated": False}

            def order(d: np.ndarray) -> np.ndarray:
                if len(d) > branch:
                    state["truncated"] = True
                top = d[: branch * 3] if shuffle else d[:branch]
                if shuffle and len(top) > 1:
                    # mostly score order, with noise: sort by rank + random jitter
                    keys = np.arange(len(top)) + rng.random() * len(top) * np.array([rng.random() for _ in range(len(top))])
                    top = top[np.argsort(keys, kind="stable")][:branch]
                return top

            def rec(doms, pres, used):
                state["nodes"] += 1
                if time.time() > deadline:
                    raise _Timeout
                if budget is not None and state["nodes"] > budget:
                    raise _Budget
                best, best_n = -1, None
                for k, d in enumerate(doms):
                    n = len(d)
                    if n > 1 and (best_n is None or n < best_n):
                        best, best_n = k, n
                if best < 0:
                    words = [word_of(k, d[0]) for k, d in enumerate(doms)]
                    return doms if len(set(words)) == len(words) else None
                for idx in order(doms[best]):
                    w = word_of(best, idx)
                    if w in used:
                        continue
                    nd = list(doms)
                    npres = list(pres)
                    nd[best] = np.array([idx])
                    npres[best] = self._pres(best, nd[best])
                    if self.propagate(nd, npres, {best}, cascade) >= 0:
                        continue
                    out = rec(nd, npres, used | {w})
                    if out is not None:
                        return out
                return None

            try:
                return rec(self._doms, self._pres_root, frozenset()), state
            except _Budget:
                return "budget", state

        out = None
        attempt = 0
        try:
            while True:
                # first run: plain score order with a budget; later runs shuffled
                out, state = run(restart_nodes * (1 + attempt // 10), shuffle=attempt > 0)
                total_nodes += state["nodes"]
                attempt += 1
                if out is None and not state["truncated"]:
                    return FillResult(IMPOSSIBLE, time.time() - t0, min_domain=res.min_domain, nodes=total_nodes)
                if out is not None and out != "budget":
                    break
        except _Timeout:
            return FillResult(UNKNOWN, time.time() - t0, min_domain=res.min_domain, nodes=total_nodes)
        dt = time.time() - t0
        letters = list(self.fixed)
        words = {}
        for k, d in enumerate(out):
            w = word_of(k, d[0])
            words[self.slots[k]] = w
            for ch, i in zip(w, self.slots[k].cells):
                letters[i] = ch
        return FillResult(FILLED, dt, letters=letters, words=words, nodes=total_nodes)
