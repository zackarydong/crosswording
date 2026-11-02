"""Scored word list loading and pattern counting.

Supported line formats (detected from a sample of the file):
  WORD;SCORE   WORD,SCORE   WORD<TAB>SCORE   WORD SCORE   WORD (no score)
Words are uppercased and reduced to letters A-Z (so "AAA BATTERY" -> "AAABATTERY").
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

DEFAULT_SCORE = 50
_DELIMS = [";", "\t", ",", " "]


class AmbiguousFormat(ValueError):
    pass


def detect_format(lines: list[str]) -> str | None:
    """Return the delimiter, or None for a bare word list. Raises if unclear."""
    sample = [ln for ln in lines if ln.strip() and not ln.startswith("#")][:2000]
    if not sample:
        raise AmbiguousFormat("word list is empty")
    votes: Counter[str | None] = Counter()
    for ln in sample:
        ln = ln.strip()
        found = None
        for d in _DELIMS:
            if d in ln:
                tail = ln.rsplit(d, 1)[1].strip()
                if re.fullmatch(r"-?\d+(\.\d+)?", tail):
                    found = d
                    break
        votes[found] += 1
    delim, count = votes.most_common(1)[0]
    if count / len(sample) < 0.95:
        raise AmbiguousFormat(
            "could not tell the word list format; saw these line styles: "
            + ", ".join(f"{d!r}: {c}" for d, c in votes.most_common())
            + ". Expected e.g. WORD;SCORE on every line."
        )
    return delim


class WordList:
    def __init__(self, words: dict[str, int], min_score: int = 50, good_score: int = 60):
        self.min_score = min_score
        self.good_score = good_score
        self.total = len(words)
        by_len: dict[int, list[tuple[str, int]]] = {}
        for w, s in words.items():
            if s >= min_score:
                by_len.setdefault(len(w), []).append((w, s))
        self._mats: dict[int, np.ndarray] = {}
        self._good: dict[int, np.ndarray] = {}
        for n, items in by_len.items():
            arr = np.frombuffer("".join(w for w, _ in items).encode("ascii"), dtype=np.uint8)
            self._mats[n] = arr.reshape(len(items), n)
            self._good[n] = np.array([s >= good_score for _, s in items], dtype=bool)
        self.count = lru_cache(maxsize=200_000)(self._count)

    @classmethod
    def load(cls, path: str | Path, min_score: int = 50, good_score: int = 60) -> "WordList":
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        delim = detect_format(lines)
        words: dict[str, int] = {}
        for ln in lines:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if delim is None:
                w, s = ln, DEFAULT_SCORE
            else:
                parts = ln.rsplit(delim, 1)
                if len(parts) != 2:
                    continue
                w = parts[0]
                try:
                    s = int(float(parts[1]))
                except ValueError:
                    continue
            w = re.sub(r"[^A-Z]", "", w.upper())
            if len(w) >= 3:
                words[w] = max(s, words.get(w, s))
        return cls(words, min_score, good_score)

    def n_words(self, length: int) -> int:
        m = self._mats.get(length)
        return 0 if m is None else m.shape[0]

    def _count(self, pattern: str) -> tuple[int, int]:
        """(usable, good) counts for a pattern like 'A..E.' ('.' = open)."""
        m = self._mats.get(len(pattern))
        if m is None:
            return (0, 0)
        mask = None
        for i, ch in enumerate(pattern):
            if ch == ".":
                continue
            col = m[:, i] == ord(ch)
            mask = col if mask is None else (mask & col)
        if mask is None:
            return (m.shape[0], int(self._good[len(pattern)].sum()))
        return (int(mask.sum()), int((mask & self._good[len(pattern)]).sum()))
