"""Flag likely-weak "constructed" words for review (never changes scores).

Each rule targets a way big word lists inflate themselves with words that are
valid but rarely lively: a prefix or suffix bolted onto another word in the
same list (RECOMPOSES = RE + COMPOSES, UNRULINESS, AEROSOLIZE, RECORDISTS).

Usage:
  python -m gridfinder.flagwords data/XwiWordList-joined.dict --out data/flagged.dict --report data/flagged-report.txt
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from .joinscores import read_list

# Kept only prefixes that fired far more often on weak words than on good ones
# when calibrated against the words XWI already rated (OUT-, SUB-, UNDER-,
# ANTI-, OVER- fired about equally and were dropped; DE- mostly matched
# coincidences like DEFINED = DE + FINED).
PREFIXES = ["RE", "UN", "NON", "MIS", "PRE", "DIS", "INTER", "SEMI"]  # DE- dropped: DE+FINED, DE+LIVERED
SUFFIX_RULES = [
    ("-NESS noun", re.compile(r"NESS(ES)?$")),
    ("-IZE verb", re.compile(r"IZ(E|ES|ED|ING|ER|ERS)$")),
    ("-IZATION noun", re.compile(r"IZATIONS?$")),
    ("-IST/-ISM plural", re.compile(r"(ISTS|ISMS)$")),
    ("-IER/-IEST", re.compile(r"I(ER|EST)$")),
    ("-ESCE verb form", re.compile(r"ESC(ES|ED|ING)$")),
    ("-LY from -ABLE/-FUL", re.compile(r"(ABLY|FULLY|LESSLY)$")),
]


SMALL_WORDS = {"A", "I", "OF", "IN", "ON", "TO", "AN", "AT", "BY", "MY", "ME", "IT", "IS", "NO", "SO",
               "UP", "US", "WE", "GO", "DO", "OR", "BE", "HE", "OH", "OK"}


def is_phrase(w: str, keys: set[str]) -> bool:
    """True if w splits into 2+ words: list words of 3+ letters or short
    function words (COVER+OF+DARKNESS, CAN+I+GET+A+WITNESS). Such entries are
    phrases whose last word merely carries the suffix."""
    n = len(w)
    # parts[i] = fewest pieces covering w[:i] (0 = unreachable except i=0)
    best = [0] + [10**9] * n
    for i in range(n):
        if best[i] >= 10**9:
            continue
        for j in range(i + 1, n + 1):
            if i == 0 and j == n:
                continue  # the whole word is not a split
            piece = w[i:j]
            if (len(piece) >= 3 and piece in keys) or piece in SMALL_WORDS:
                best[j] = min(best[j], best[i] + 1)
    return 2 <= best[n] < 10**9


def _other_split(w: str, prefix_len: int, keys: set[str]) -> bool:
    """True if w reads as a phrase split somewhere other than right after the
    prefix (UNCUT+GEMS, RED+ALES): then the prefix match is a coincidence. The
    prefix split itself never counts, since DIS, NON, MIS, PRE are words too."""
    for i in range(4, len(w) - 3):  # both halves 4+ letters: 3-letter coincidences (UND+REAMED) don't count
        if i == prefix_len:
            continue
        head, tail = w[:i], w[i:]
        if head in keys and (tail in keys or is_phrase(tail, keys)):
            return True
    return False


def flag(words: dict[str, int], unreviewed: int = 50, min_len: int = 7) -> dict[str, str]:
    """Return {WORD: reason} for unreviewed words that match a rule."""
    keys = set(words)
    out: dict[str, str] = {}
    for w, s in words.items():
        if s != unreviewed or len(w) < min_len:
            continue
        reason = None
        for p in PREFIXES:
            rest = w[len(p):]
            if w.startswith(p) and len(rest) >= 4 and rest in keys and not _other_split(w, len(p), keys):
                reason = f"{p}- + {rest}"
                break
        if reason is None and not is_phrase(w, keys):
            for name, rx in SUFFIX_RULES:
                if rx.search(w):
                    reason = name
                    break
        if reason:
            out[w] = reason
    return out


def rule_of(reason: str) -> str:
    return reason.split(" + ")[0] if " + " in reason else reason


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wordlist")
    ap.add_argument("--out", required=True, help="flagged words as word;score, grouped by rule (load into the grader)")
    ap.add_argument("--report", help="word, score and reason per line")
    ap.add_argument("--unreviewed", type=int, default=50)
    a = ap.parse_args(argv)
    rows = read_list(a.wordlist)
    words: dict[str, int] = {}
    orig: dict[str, str] = {}
    for w, key, s in rows:
        if key:
            words[key] = s
            orig.setdefault(key, w)
    flags = flag(words, a.unreviewed)
    order = sorted(flags, key=lambda w: (rule_of(flags[w]), w))
    Path(a.out).write_text("".join(f"{orig[w]};{words[w]}\n" for w in order))
    if a.report:
        Path(a.report).write_text("".join(f"{orig[w]};{words[w]};{flags[w]}\n" for w in order))
    c = Counter(rule_of(r) for r in flags.values())
    for k, v in c.most_common():
        print(f"{k:24s} {v:>7,}")
    print(f"{'total flagged':24s} {len(flags):>7,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
