import numpy as np
import pytest

from gridfinder.flow import fiedler_value, grid_flow, slot_laplacian
from gridfinder.grid import Grid, slots
from gridfinder.stats import compute_stats

CORNERS5 = "#....\n.....\n.....\n.....\n....#"


def test_stats_open_grid():
    st = compute_stats(Grid(5))
    assert st.words == 10 and st.blocks == 0
    assert st.avg_len == 5 and st.threes == 0 and st.longest == 5


def test_stats_corners():
    st = compute_stats(Grid.from_text(CORNERS5))
    assert st.words == 10
    assert st.avg_len == pytest.approx(46 / 10)
    assert st.length_hist == {4: 4, 5: 6}


def test_stats_threes():
    g = Grid.from_text(
        """
        ...#...
        ...#...
        ...#...
        .......
        ...#...
        ...#...
        ...#...
        """
    )
    st = compute_stats(g)
    assert st.threes == 12  # 6 rows x 2 across threes
    assert st.words == 12 + 1 + 6  # centre column cell is a 1-letter run, not a word


def test_fiedler_two_nodes():
    L = np.array([[1.0, -1.0], [-1.0, 1.0]])
    assert fiedler_value(L) == pytest.approx(2.0)


def test_flow_open_3x3_is_k33():
    # 3 across x 3 down slots, every pair crosses: K_{3,3}, eigenvalues 0,3,3,3,3,6.
    g = Grid(3)
    assert grid_flow(g) == pytest.approx(3.0 * 9)


def test_flow_open_5x5():
    # K_{5,5}: lambda2 = 5, 25 checked squares.
    assert grid_flow(Grid(5)) == pytest.approx(125.0)


def test_laplacian_rows_sum_to_zero():
    g = Grid.from_text(CORNERS5)
    L = slot_laplacian(slots(g, 3), 25)
    assert np.allclose(L.sum(axis=1), 0)


def test_flow_disconnected_is_zero():
    g = Grid.from_text(
        """
        ...#...
        ...#...
        ...#...
        #######
        ...#...
        ...#...
        ...#...
        """
    )
    assert grid_flow(g) == 0.0


def test_flow_choke_point_lower_than_open():
    open7 = Grid(7)
    choke = Grid.from_text(
        """
        ...#...
        ...#...
        ...#...
        .......
        ...#...
        ...#...
        ...#...
        """
    )
    assert 0 < grid_flow(choke) < grid_flow(open7)


def test_flow_length_weighting_runs():
    assert grid_flow(Grid(5), weighting="length") == pytest.approx(25.0)  # 5/5 * 25
