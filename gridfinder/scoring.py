"""Soft scoring: combine stats, fillability and flow into a 0-100 score."""

from __future__ import annotations

from dataclasses import dataclass, field

from .fill import FillReport, fillability
from .flow import grid_flow
from .grid import slots as get_slots
from .search import Candidate
from .stats import GridStats, compute_stats
from .wordlist import WordList


def band(x: float, lo: float, hi: float, ideal: float, falloff: float) -> float:
    """1.0 at ideal, 0.8 at the edges of [lo, hi], linear to 0 over `falloff` outside."""
    if lo <= x <= hi:
        half = max(ideal - lo, hi - ideal, 1e-9)
        return 1.0 - 0.2 * abs(x - ideal) / half
    d = lo - x if x < lo else x - hi
    return max(0.0, 0.8 * (1 - d / falloff))


def openness(slot_list, seed_slots, long_len: int, stack_len: int) -> tuple[int, int]:
    """(long non-seed entries, long parallel stack pairs).

    A stack pair = two parallel entries in adjacent rows (or columns), both at
    least stack_len long, overlapping by at least stack_len squares, not both
    seeds. Wide blocks of long parallel entries are the hardest areas to fill,
    and the per-slot candidate count can't see them."""
    long_nonseed = sum(1 for s in slot_list if s.length >= long_len and s not in seed_slots)
    by_line: dict[tuple[str, int], list] = {}
    for s in slot_list:
        if s.length >= stack_len:
            line = s.row if s.direction == "A" else s.col
            by_line.setdefault((s.direction, line), []).append(s)
    pairs = 0
    for (d, line), group in by_line.items():
        for a in group:
            for b in by_line.get((d, line + 1), []):
                if a in seed_slots and b in seed_slots:
                    continue
                a0 = a.col if d == "A" else a.row
                b0 = b.col if d == "A" else b.row
                overlap = min(a0 + a.length, b0 + b.length) - max(a0, b0)
                if overlap >= stack_len:
                    pairs += 1
    return long_nonseed, pairs


def rising(x: float, zero_at: float, full_at: float) -> float:
    if full_at <= zero_at:
        return 1.0 if x >= full_at else 0.0
    return min(1.0, max(0.0, (x - zero_at) / (full_at - zero_at)))


@dataclass
class Scored:
    cand: Candidate
    stats: GridStats
    flow: float
    fill: FillReport
    long_nonseed: int
    stack_pairs: int
    score: float
    parts: dict[str, float] = field(default_factory=dict)


def score_candidate(cand: Candidate, cfg: dict, wordlist: WordList | None) -> Scored:
    t, w, f = cfg["targets"], cfg["weights"], cfg["fill"]
    sl = get_slots(cand.grid, cfg["hard"]["min_entry"])
    st = compute_stats(cand.grid, sl)
    flow = grid_flow(cand.grid, sl, cfg["flow"]["weighting"])
    if wordlist is not None:
        fr = fillability(
            sl, cand.letters, set(cand.seed_slots.values()), wordlist,
            few=f["few"], dead_penalty=f["dead_penalty"], tight_penalty=f["tight_penalty"],
        )
    else:
        fr = FillReport(100.0)
    o = cfg["openness"]
    seed_set = set(cand.seed_slots.values())
    long_n, stacks = openness(sl, seed_set, o["long_len"], o["stack_len"])
    mt = t["max_threes"]
    parts = {
        "words": band(st.words, *t["words"], t["words_ideal"], 8),
        "blocks": band(st.blocks, *t["blocks"], t["blocks_ideal"], 8),
        "avg_len": rising(st.avg_len, t["avg_len_min"] - 0.5, t["avg_len_ideal"]),
        # 1.0 with no threes, 0.6 at the max, 0 at twice the max
        "threes": 1 - 0.4 * st.threes / mt if st.threes <= mt else max(0.0, 0.6 * (1 - (st.threes - mt) / mt)),
        "fill": fr.score / 100,
        # secondary: zero below half of flow_min, full at flow_ideal
        "flow": rising(flow, t["flow_min"] / 2, t["flow_ideal"]),
        # long non-seed entries and long parallel stacks are hard to fill
        "open": max(0.0, 1 - o["long_cost"] * max(0, long_n - o["long_free"]) - o["stack_cost"] * stacks),
    }
    total_w = sum(w[k] for k in parts)
    score = 100 * sum(w[k] * v for k, v in parts.items()) / total_w
    return Scored(cand, st, flow, fr, long_n, stacks, score, parts)
