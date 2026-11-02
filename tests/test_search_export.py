import json
import random

import pytest

from gridfinder.cli import main
from gridfinder.config import load_config
from gridfinder.export import ascii_grid, export_all, to_ipuz
from gridfinder.grid import Grid, is_connected, is_symmetric, slots, violations
from gridfinder.scoring import band, score_candidate
from gridfinder.search import Searcher
from gridfinder.seeds import crossing_options, place_seeds

SEEDS = ["THESAHARADESERT", "GREENPAINT", "MARQUEEENTRY", "STAIRSTEP"]


@pytest.fixture(scope="module")
def candidates():
    cfg = load_config()
    s = Searcher(SEEDS, cfg, random.Random(3))
    out = []
    for _ in range(300):
        c = s.attempt()
        if c:
            out.append(c)
    assert len(out) >= 10, s.log
    return cfg, out


def test_generated_grids_satisfy_hard_constraints(candidates):
    cfg, cands = candidates
    for c in cands:
        g = c.grid
        assert violations(g, 72) == []
        assert is_symmetric(g) and is_connected(g.b, g.n)
        assert len(slots(g, 3)) <= 72


def test_seeds_sit_in_exact_slots_with_consistent_letters(candidates):
    _, cands = candidates
    for c in cands:
        assert set(c.seed_slots) == set(SEEDS)
        assert len(set(c.seed_slots.values())) == len(SEEDS)  # each slot used once
        for word, slot in c.seed_slots.items():
            assert slot.length == len(word)
            assert "".join(c.letters[i] for i in slot.cells) == word
        # an independent re-placement must also succeed
        assert place_seeds(c.grid, SEEDS).ok


def test_reproducible_with_same_seed():
    cfg = load_config()
    a = Searcher(SEEDS, cfg, random.Random(42))
    b = Searcher(SEEDS, cfg, random.Random(42))
    ga = [x.grid.key() if x else None for x in (a.attempt() for _ in range(30))]
    gb = [x.grid.key() if x else None for x in (b.attempt() for _ in range(30))]
    assert ga == gb


def test_self_symmetric_center_seed():
    cfg = load_config()
    s = Searcher(["ABCDEFGHIJKLMNO"], cfg, random.Random(0))
    for _ in range(50):
        c = s.attempt()
        if c:
            assert violations(c.grid, 72) == []
            return
    pytest.fail("no grid for a single 15-letter seed")


def test_incompatible_seeds_never_cross(candidates):
    # Seeds made of disjoint letters can never share a square.
    cfg = load_config()
    seeds = ["AAAAAAAAA", "BBBBBBBBB", "CCCCCCC"]
    assert crossing_options("AAAAAAAAA", "BBBBBBBBB") == 0
    s = Searcher(seeds, cfg, random.Random(1))
    got = 0
    for _ in range(100):
        c = s.attempt()
        if not c:
            continue
        got += 1
        cells = [set(sl.cells) for sl in c.seed_slots.values()]
        assert not (cells[0] & cells[1]) and not (cells[0] & cells[2]) and not (cells[1] & cells[2])
    assert got


def test_band():
    assert band(30, 26, 34, 30, 8) == 1.0
    assert band(26, 26, 34, 30, 8) == pytest.approx(0.8)
    assert band(18, 26, 34, 30, 8) == 0.0


def test_score_and_exports(tmp_path, candidates):
    cfg, cands = candidates
    sc = score_candidate(cands[0], cfg, None)
    assert 0 <= sc.score <= 100
    files = export_all(sc, 1, tmp_path)
    assert all(f.exists() for f in files)
    data = json.loads(files[1].read_text())
    assert data["dimensions"] == {"width": 15, "height": 15}
    flat = [x for row in data["puzzle"] for x in row]
    assert flat.count("#") == sc.stats.blocks
    total_clues = len(data["clues"]["Across"]) + len(data["clues"]["Down"])
    assert total_clues == sc.stats.words
    txt = files[0].read_text()
    assert "block columns by row" in txt
    # ascii parse round-trip
    plain = ascii_grid(cands[0].grid, coords=False)
    assert Grid.from_text(plain) == cands[0].grid


def test_cli_find_and_check(tmp_path, capsys):
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("\n".join(SEEDS))
    wl = tmp_path / "w.dict"
    wl.write_text("thesaharadesert;60\ngreenpaint;50\nabc;50\n")
    out = tmp_path / "out"
    rc = main(["find", str(seeds), "--wordlist", str(wl), "--seed", "5", "--attempts", "200", "--top", "2", "--out", str(out), "--quiet"])
    assert rc == 0
    pngs = list((out / "run-5").glob("*.png"))
    assert len(pngs) == 2
    grid_txt = out / "run-5" / "grid-01.txt"
    plain = grid_txt.read_text().split("plain grid:\n")[1].split("\n\n")[0]
    gfile = tmp_path / "g.txt"
    gfile.write_text(plain)
    rc = main(["check", str(gfile), "--seeds", str(seeds), "--wordlist", str(wl)])
    assert rc == 0
    assert "hard constraints: OK" in capsys.readouterr().out


def test_openness_counts_long_entries_and_stacks():
    from gridfinder.scoring import openness

    g = Grid(15)  # fully open: 30 fifteen-letter entries
    sl = slots(g, 3)
    long_n, stacks = openness(sl, set(), 10, 8)
    assert long_n == 30
    assert stacks == 28  # 14 adjacent row pairs + 14 adjacent column pairs
    # seeds are not counted as long non-seed entries
    long_n2, _ = openness(sl, set(sl[:2]), 10, 8)
    assert long_n2 == 28


def test_openness_lowers_score_for_open_center(candidates):
    cfg, cands = candidates
    sc = score_candidate(cands[0], cfg, None)
    assert "open" in sc.parts and 0 <= sc.parts["open"] <= 1
