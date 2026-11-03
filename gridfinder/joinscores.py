"""Borrow ratings from an older/bigger word list for words your main list hasn't rated.

Only words at the main list's "unreviewed" score (default 50) are touched, and
by default only DOWNGRADED: testing showed the old list is a reliable junk
detector (low old score -> weak word) but a poor sparkle detector (its high
scores include plain words like LESS and RIPS).

Usage:
  python -m gridfinder.joinscores data/XwiWordList.dict data/xwordlist-old.dict --out data/XwiWordList-joined.dict
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

# (old score upper bound inclusive, new score); first match wins. Old scores
# above the last bound leave the word unchanged.
DEFAULT_MAP = [(30, 25), (44, 40)]
# Raises: (old score lower bound inclusive, new score); first match wins.
# Old 100 = fresh, lively entries; old 80-90 = solid real words, so they go
# to 55 (above unreviewed 50, below the main list's curated 60s).
DEFAULT_UP = [(100, 60), (80, 55)]


def read_list(path: str | Path) -> list[tuple[str, str, int]]:
    """[(original word text, UPPER letters-only key, score)] in file order."""
    out = []
    for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or ";" not in ln:
            continue
        w, s = ln.rsplit(";", 1)
        try:
            score = int(s)
        except ValueError:
            continue
        out.append((w, w.upper() if re.fullmatch(r"[A-Za-z]+", w) else "", score))
    return out


def join(main, old, unreviewed: int = 50, mapping=DEFAULT_MAP, up=DEFAULT_UP, no_raise: set[str] | None = None):
    """Returns (new rows [(word, score)], unmatched [word], stats Counter).
    Words in `no_raise` (e.g. flagged as constructed) are never raised."""
    no_raise = no_raise or set()
    old_scores: dict[str, int] = {}
    for _, key, s in old:
        if key:
            old_scores[key] = max(s, old_scores.get(key, s))
    rows, unmatched, stats = [], [], Counter()
    for word, key, s in main:
        if s != unreviewed:
            stats["kept: already rated"] += 1
            rows.append((word, s))
            continue
        o = old_scores.get(key) if key else None
        if o is None:
            stats["kept: no match in old list"] += 1
            unmatched.append(word)
            rows.append((word, s))
            continue
        new = s
        for bound, target in mapping:
            if o <= bound:
                new = target
                break
        if new == s and key not in no_raise:
            for bound, target in up:
                if o >= bound:
                    new = target
                    break
        stats[f"changed {s} -> {new}" if new != s else "kept: old list agrees"] += 1
        rows.append((word, new))
    return rows, unmatched, stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("main")
    p.add_argument("old")
    p.add_argument("--out", required=True, help="joined list to write (word;score)")
    p.add_argument("--unmatched", help="also write unmatched words here (word;score)")
    p.add_argument("--unreviewed", type=int, default=50)
    p.add_argument("--no-raise", action="store_true", help="only lower scores, never raise them")
    a = p.parse_args(argv)
    main_rows = read_list(a.main)
    no_raise: set[str] = set()
    if not a.no_raise:
        from .flagwords import flag  # constructed words wait for review instead of being raised

        no_raise = set(flag({k: s for _, k, s in main_rows if k}, a.unreviewed))
    rows, unmatched, stats = join(main_rows, read_list(a.old), a.unreviewed,
                                  up=[] if a.no_raise else DEFAULT_UP, no_raise=no_raise)
    Path(a.out).write_text("".join(f"{w};{s}\n" for w, s in rows))
    if a.unmatched:
        Path(a.unmatched).write_text("".join(f"{w};{a.unreviewed}\n" for w in unmatched))
    for k, v in sorted(stats.items()):
        print(f"{k:32s} {v:>8,}")
    print(f"{'total':32s} {len(rows):>8,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
