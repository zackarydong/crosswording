import itertools
import random

from gridfinder.fillcheck import FILLED, IMPOSSIBLE, Filler
from gridfinder.grid import Grid, slots
from gridfinder.wordlist import WordList


def wordlist(words):
    return WordList({w: 50 for w in words})


def brute_force_fillable_3x3(words):
    """Open 3x3: choose three rows, derive the columns, all six distinct."""
    ws = set(words)
    for rows in itertools.product(words, repeat=3):
        cols = ["".join(r[k] for r in rows) for k in range(3)]
        if all(c in ws for c in cols) and len(set(list(rows) + cols)) == 6:
            return True
    return False


def test_fills_word_square():
    g = Grid(3)
    # rows BAD/ORE/ATE, columns BOA/ART/DEE (not symmetric, so no repeats)
    wl = wordlist(["BAD", "ORE", "ATE", "BOA", "ART", "DEE", "CAT", "ZZZ"])
    r = Filler(g, [None] * 9, set(), wl).fill(5)
    assert r.status == FILLED
    rows = ["".join(r.letters[i] for i in range(k * 3, k * 3 + 3)) for k in range(3)]
    cols = ["".join(r.letters[i] for i in range(k, 9, 3)) for k in range(3)]
    assert len(set(rows + cols)) == 6  # no repeated answers


def test_impossible_detected():
    g = Grid(3)
    wl = wordlist(["AAA", "BBB", "CCC", "ABC"])
    r = Filler(g, [None] * 9, set(), wl).fill(5)
    assert r.status == IMPOSSIBLE


def test_fixed_letters_respected():
    g = Grid(3)
    wl = wordlist(["BAT", "ARE", "TEN", "ART", "BAD", "ODE", "ATE", "TOT", "EAT", "DEN"])
    letters = [None] * 9
    letters[0] = "Z"
    assert Filler(g, letters, set(), wl).fill(5).status == IMPOSSIBLE


def test_matches_brute_force_on_random_small_lists():
    rng = random.Random(0)
    g = Grid(3)
    alphabet = "ABCDE"
    for trial in range(150):
        words = list({"".join(rng.choice(alphabet) for _ in range(3)) for _ in range(rng.randint(6, 25))})
        expected = brute_force_fillable_3x3(words)
        r = Filler(g, [None] * 9, set(), wordlist(words)).fill(5, branch=1000)
        assert (r.status == FILLED) == expected, (words, r.status)
        assert r.status in (FILLED, IMPOSSIBLE)
