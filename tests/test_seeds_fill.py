import pytest

from gridfinder.fill import fillability
from gridfinder.grid import Grid, slots
from gridfinder.seeds import letters_for, parse_seeds, place_seeds
from gridfinder.wordlist import AmbiguousFormat, WordList, detect_format


def test_parse_seeds():
    assert parse_seeds("the sahara desert\n\ngreenpaint\n") == ["THESAHARADESERT", "GREENPAINT"]
    with pytest.raises(ValueError):
        parse_seeds("SHORT")
    with pytest.raises(ValueError):
        parse_seeds("ABC123DEF")
    with pytest.raises(ValueError):
        parse_seeds("ABCDEFG\nabcdefg")


def test_detect_format():
    assert detect_format(["aaa;50", "bbb;60"]) == ";"
    assert detect_format(["aaa\t50", "bbb\t60"]) == "\t"
    assert detect_format(["aaa", "bbb"]) is None
    with pytest.raises(AmbiguousFormat):
        detect_format(["aaa;50", "bbb", "ccc,3", "ddd"])


def test_wordlist_count(tmp_path):
    p = tmp_path / "w.dict"
    p.write_text("apple;50\nample;60\nangle;30\nmaple;50\nab;50\n")
    wl = WordList.load(p, min_score=50, good_score=60)
    assert wl.n_words(5) == 3  # angle filtered by score; "ab" too short
    assert wl.count("A...E") == (2, 1)
    assert wl.count(".....") == (3, 1)
    assert wl.count("Z....") == (0, 0)
    assert wl.count("...") == (0, 0)


# 7x7 with two 7-letter rows (0 and 6), one 7-letter centre row and 3x3 corner-ish blocks.
G7 = """
.......
.......
.......
...#...
.......
.......
.......
"""


def test_place_seeds_basic():
    g = Grid.from_text(G7)
    res = place_seeds(g, ["ABCDEFG", "HIJKLMN"])
    assert res.ok
    slots_used = set(res.assignment.values())
    assert len(slots_used) == 2
    for w, s in res.assignment.items():
        assert s.length == len(w)


def test_place_seeds_crossing_conflict_reported():
    # 7x7 where the only 7-slots are row 0 across and col 0 down ... build it.
    g = Grid.from_text(
        """
        .......
        .##.##.
        .##.##.
        .......
        .##.##.
        .##.##.
        .......
        """
    )
    # Every 7-slot crosses others at corners; force incompatible letters everywhere:
    # three across + three down; words all of one letter can't cross different-letter words.
    seeds = ["AAAAAAA", "BBBBBBB", "CCCCCCC", "DDDDDDD"]
    res = place_seeds(g, seeds)
    assert not res.ok
    assert res.conflicts
    assert "cross at row" in res.conflicts[0].describe()


def test_place_seeds_compatible_crossing():
    g = Grid.from_text(
        """
        .......
        .##.##.
        .##.##.
        .......
        .##.##.
        .##.##.
        .......
        """
    )
    res = place_seeds(g, ["AXXXXXA", "AYYYYYA"])
    assert res.ok


def test_place_seeds_no_slot_of_length():
    res = place_seeds(Grid.from_text(G7), ["ABCDEFGH"[:7], "ABCDEFG"[:3] + "XXXX", "QQQQQQQ"])
    assert res.ok or res.unplaceable or res.conflicts  # runs without error
    g = Grid(9)
    res = place_seeds(g, ["ABCDEFGHIJ"])  # 10 letters in a 9x9 grid
    assert not res.ok and res.unplaceable


def test_fillability_dead_slot(tmp_path):
    p = tmp_path / "w.dict"
    p.write_text("abc;50\nabd;50\nxyz;50\n")
    wl = WordList.load(p)
    g = Grid(3)
    sl = slots(g, 3)
    seed_slot = [s for s in sl if s.direction == "A" and s.row == 0][0]
    letters = letters_for({"QQQ": seed_slot}, 9)
    rep = fillability(sl, letters, {seed_slot}, wl, few=5)
    # All 3 downs start with Q -> no candidates; 2 unconstrained acrosses have 3 words (tight).
    assert len(rep.dead) == 3
    assert rep.score < 100
    letters = letters_for({"AQA": seed_slot}, 9)
    rep2 = fillability(sl, letters, {seed_slot}, wl, few=1)
    assert len(rep2.dead) == 1  # the Q column


def test_joinscores_downgrades_only_unreviewed(tmp_path):
    from gridfinder.joinscores import join, read_list

    m = tmp_path / "m.dict"
    o = tmp_path / "o.dict"
    m.write_text("junk;50\nmeh;50\nfine;50\nrated;60\nnew;50\n")
    o.write_text("junk;20\nmeh;40\nfine;90\nrated;5\n")
    rows, unmatched, stats = join(read_list(m), read_list(o), up=[])
    assert dict(rows) == {"junk": 25, "meh": 40, "fine": 50, "rated": 60, "new": 50}
    assert unmatched == ["new"]
    rows, _, _ = join(read_list(m), read_list(o))  # default raises: old 80-90 -> 55
    assert dict(rows)["fine"] == 55 and dict(rows)["rated"] == 60
    rows, _, _ = join(read_list(m), read_list(o), no_raise={"FINE"})
    assert dict(rows)["fine"] == 50


def test_flagwords_rules_and_phrase_exemption():
    from gridfinder.flagwords import flag, is_phrase

    words = {w: 50 for w in ["COMPOSES", "RECOMPOSES", "UNRULINESS", "PLOT", "TWISTS", "PLOTTWISTS",
                             "COVER", "DARKNESS", "COVEROFDARKNESS", "ENERGIZED", "MAPLESYRUP"]}
    words["REPAIRMEN"] = 60  # already rated: never flagged
    f = flag(words)
    assert f["RECOMPOSES"] == "RE- + COMPOSES"
    assert f["UNRULINESS"] == "-NESS noun"
    assert f["ENERGIZED"] == "-IZE verb"
    assert "PLOTTWISTS" not in f and "COVEROFDARKNESS" not in f  # phrases exempt from suffix rules
    assert "REPAIRMEN" not in f and "MAPLESYRUP" not in f
    assert is_phrase("COVEROFDARKNESS", set(words)) and not is_phrase("COMPOSES", set(words))


def test_flagwords_prefix_rule_skips_phrases():
    from gridfinder.flagwords import flag

    words = {w: 50 for w in ["UNCUT", "GEMS", "CUTGEMS", "UNCUTGEMS", "RED", "ALES", "DALES", "REDALES",
                             "COMPOSES", "RECOMPOSES"]}
    f = flag(words)
    assert "UNCUTGEMS" not in f  # UNCUT + GEMS: real phrase split
    assert "RECOMPOSES" in f
