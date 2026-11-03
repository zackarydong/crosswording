"""Screen combinations of seeds: which subsets can share a fillable grid?

For each combination: run a short search, quick-check the best-scoring grids
for impossibility, then try a few full fills. Combinations are ranked by
verified grids, then by quick-check survival rate.
"""

from __future__ import annotations

import itertools
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from .config import load_config
from .fillcheck import FILLED, IMPOSSIBLE, Filler
from .scoring import score_candidate
from .search import Searcher
from .wordlist import WordList

_WL: WordList | None = None


@dataclass
class ComboResult:
    seeds: tuple[str, ...]
    valid: int
    checked: int
    survivors: int
    fills_tried: int
    verified: int
    impossible_full: int
    best_score: float

    @property
    def survival(self) -> float:
        return self.survivors / self.checked if self.checked else 0.0


def _init(wordlist_path: str, min_score: int, good_score: int) -> None:
    global _WL
    _WL = WordList.load(wordlist_path, min_score, good_score)


def screen_combo(seeds: tuple[str, ...], cfg: dict, attempts: int, check_top: int, fills: int, fill_time: float, rng_seed: int) -> ComboResult:
    wl = _WL
    s = Searcher(list(seeds), cfg, random.Random(rng_seed))
    cands = [c for c in (s.attempt() for _ in range(attempts)) if c]
    scored = sorted((score_candidate(c, cfg, wl) for c in cands), key=lambda x: -x.score)
    top = scored[:check_top]
    survivors = []
    for x in top:
        f = Filler(x.cand.grid, x.cand.letters, set(x.cand.seed_slots.values()), wl)
        if f.arc_check().status != IMPOSSIBLE:
            survivors.append((x, f))
    verified = impossible = tried = 0
    for x, f in survivors[:fills]:
        tried += 1
        r = f.fill(fill_time, cfg["fillcheck"]["branch"])
        verified += r.status == FILLED
        impossible += r.status == IMPOSSIBLE
    return ComboResult(
        tuple(seeds), len(cands), len(top), len(survivors), tried, verified, impossible,
        scored[0].score if scored else 0.0,
    )


def screen(
    seeds: list[str], size: int, wordlist_path: str, cfg: dict, attempts: int = 1500, check_top: int = 200,
    fills: int = 4, fill_time: float = 8.0, rng_seed: int = 1, workers: int | None = None, require: list[str] | None = None,
) -> list[ComboResult]:
    combos = [c for c in itertools.combinations(seeds, size) if not require or all(r in c for r in require)]
    f = cfg["fill"]
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(wordlist_path, f["min_score"], f["good_score"])) as ex:
        futs = [ex.submit(screen_combo, c, cfg, attempts, check_top, fills, fill_time, rng_seed) for c in combos]
        results = [x.result() for x in futs]
    results.sort(key=lambda r: (-r.verified, -r.survival, -r.best_score))
    return results
