from gridfinder.grid import (
    Grid,
    all_runs,
    has_solid_block,
    is_connected,
    is_symmetric,
    numbering,
    slots,
    violations,
)

OPEN5 = """
.....
.....
.....
.....
.....
"""

# 5x5 with symmetric corner blocks: all runs >= 3? Row 0: "#...." -> run of 4; fine.
CORNERS5 = """
#....
.....
.....
.....
....#
"""


def test_parse_roundtrip():
    g = Grid.from_text(CORNERS5)
    assert g.n == 5
    assert g.to_text() == CORNERS5.strip()
    assert g.block_count == 2


def test_symmetry():
    assert is_symmetric(Grid.from_text(CORNERS5))
    asym = Grid.from_text("#....\n.....\n.....\n.....\n.....")
    assert not is_symmetric(asym)


def test_set_block_mirrors():
    g = Grid(5)
    g.set_block(0, 1)
    assert g.is_block(4, 3)
    assert is_symmetric(g)


def test_connectivity():
    assert is_connected(Grid.from_text(OPEN5).b, 5)
    split = Grid.from_text(
        """
        ..#..
        ..#..
        #####
        ..#..
        ..#..
        """
    )
    assert not is_connected(split.b, 5)


def test_slot_extraction_open():
    g = Grid.from_text(OPEN5)
    s = slots(g, 3)
    assert len(s) == 10
    assert all(x.length == 5 for x in s)
    across = [x for x in s if x.direction == "A"]
    assert across[0].cells == (0, 1, 2, 3, 4)
    down = [x for x in s if x.direction == "D"]
    assert down[0].cells == (0, 5, 10, 15, 20)


def test_slot_extraction_with_blocks():
    g = Grid.from_text(CORNERS5)
    s = slots(g, 3)
    lengths = sorted(x.length for x in s)
    # rows 0 and 4 have 4-letter runs, cols 0 and 4 too; the rest are 5.
    assert lengths == [4, 4, 4, 4, 5, 5, 5, 5, 5, 5]
    first = [x for x in s if x.direction == "A" and x.row == 0][0]
    assert first.col == 1 and first.length == 4


def test_unchecked_and_short_detected():
    g = Grid.from_text(
        """
        .#...
        .....
        .....
        .....
        ...#.
        """
    )
    v = violations(g, max_words=100)
    assert any("unchecked" in x for x in v)  # (0,0) across run of length 1


def test_solid_block():
    g = Grid(5, [1] * 25)
    assert has_solid_block(g.b, 5)
    assert not has_solid_block(Grid.from_text(CORNERS5).b, 5)


def test_valid_small_grid():
    assert violations(Grid.from_text(CORNERS5), max_words=100) == []


def test_word_limit():
    v = violations(Grid.from_text(OPEN5), max_words=9)
    assert any("exceeds max" in x for x in v)


def test_numbering():
    nums = numbering(Grid.from_text(CORNERS5))
    assert nums[1] == 1  # first white square of row 0
    assert nums[5] == 5  # row 1 col 0 starts 5-Across (and 5-Down)
    assert len(all_runs(Grid.from_text(OPEN5).b, 5)) == 10
