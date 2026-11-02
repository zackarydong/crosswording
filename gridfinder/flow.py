"""Grid Flow (Fritz Juhnke), as described at
https://xwordblog.com/2025/10/21/crossword-flow/

Definition from the article: build a graph whose nodes are the grid's slots
(entries) and whose edges join slots that intersect. Grid Flow is the Fiedler
value (algebraic connectivity = second-smallest eigenvalue of the graph
Laplacian) multiplied by the number of checked squares.

Assumptions (also listed in the README):
  1. Each crossing is one unweighted edge (heat moves "at a rate proportional
     to the difference in temperature" with one contact per crossing).
  2. Plain combinatorial Laplacian L = D - A: every slot is a rod with equal
     "heat capacity" regardless of length. A length-weighted variant
     (generalized problem L x = lambda M x with M = diag(length)) is
     available via weighting="length" but is off by default.
  3. Checked squares = white squares belonging to both an across and a down
     entry of length >= 3. In a valid grid this is every white square.
  4. A disconnected slot graph has Fiedler value 0, so Flow = 0.
"""

from __future__ import annotations

import numpy as np

from .grid import Grid, slots as get_slots, Slot


def slot_laplacian(slot_list: list[Slot], n_cells: int) -> np.ndarray:
    across = [-1] * n_cells
    down = [-1] * n_cells
    for k, s in enumerate(slot_list):
        target = across if s.direction == "A" else down
        for i in s.cells:
            target[i] = k
    m = len(slot_list)
    L = np.zeros((m, m))
    for i in range(n_cells):
        a, d = across[i], down[i]
        if a >= 0 and d >= 0:
            L[a, d] -= 1
            L[d, a] -= 1
            L[a, a] += 1
            L[d, d] += 1
    return L


def fiedler_value(L: np.ndarray, masses: np.ndarray | None = None) -> float:
    if L.shape[0] < 2:
        return 0.0
    if masses is not None:
        s = 1.0 / np.sqrt(masses)
        L = L * s[:, None] * s[None, :]
    vals = np.linalg.eigvalsh(L)
    lam = float(vals[1])
    return 0.0 if lam < 1e-9 else lam


def checked_squares(slot_list: list[Slot], n_cells: int) -> int:
    a = bytearray(n_cells)
    d = bytearray(n_cells)
    for s in slot_list:
        tgt = a if s.direction == "A" else d
        for i in s.cells:
            tgt[i] = 1
    return sum(1 for i in range(n_cells) if a[i] and d[i])


def grid_flow(grid: Grid, slot_list: list[Slot] | None = None, weighting: str = "none") -> float:
    if slot_list is None:
        slot_list = get_slots(grid, 3)
    n_cells = grid.n * grid.n
    L = slot_laplacian(slot_list, n_cells)
    masses = None
    if weighting == "length":
        masses = np.array([s.length for s in slot_list], dtype=float)
    elif weighting != "none":
        raise ValueError(f"unknown flow weighting {weighting!r}")
    return fiedler_value(L, masses) * checked_squares(slot_list, n_cells)
