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
    }
    total_w = sum(w[k] for k in parts)
    score = 100 * sum(w[k] * v for k, v in parts.items()) / total_w
    return Scored(cand, st, flow, fr, score, parts)
