# crosswording

Grid Finder + Better Fills.

## gridfinder

A Python CLI that finds 15x15 black-square layouts for an NYT-style **Friday
themeless** that can hold a few long "marquee" seed entries you choose. It
ranks candidates by Friday norms, a fillability check against your word
list, and Grid Flow, then exports each top grid as text, `.ipuz` and PNG so
you can rebuild it by hand in Crosserville.

### Setup (on your Mac)

```bash
mkdir -p ~/Projects
cd ~/Projects && git clone https://github.com/zackarydong/crosswording.git
cd crosswording
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Requires Python 3.11+. Dependencies: numpy, Pillow.

### Inputs

- **Seeds file**: 3-6 entries, 7-15 letters, one per line (letters only;
  spaces are removed, `#` lines are comments). See `seeds.example.txt`.
- **Word list**: put it in `data/` (e.g. `data/XwiWordList.dict`). The first
  `*.dict` there is used by default, or pass `--wordlist PATH`. Format is
  auto-detected: `WORD;SCORE`, `WORD,SCORE`, `WORD<TAB>SCORE`, `WORD SCORE`, or
  bare words (score 50). If the format is unclear the tool stops and asks.
  `data/` and `*.dict` are git-ignored so your list is never committed.

### Usage

```bash
# Find grids (5000 attempts, top 5, reproducible with --seed)
gridfinder find seeds.txt --seed 7

# More options
gridfinder find seeds.txt --top 10 --attempts 20000 --min-blocks 26 --max-blocks 36 --max-words 70 --seed 1

# Check / score a grid you drew yourself ('#' = block, '.' = white)
gridfinder check mygrid.txt --seeds seeds.txt --export out/mine
```

| Flag | Meaning | Default |
|---|---|---|
| `--top N` | grids to print and export | 5 |
| `--seed N` | RNG seed (same seed + same inputs = same results) | random, printed |
| `--attempts N` | candidate grids to try | 5000 |
| `--min-blocks` / `--max-blocks` | hard block-count limits | 20 / 40 |
| `--max-words` | hard word-count limit | 72 |
| `--wordlist PATH` | scored word list | first `data/*.dict` |
| `--config PATH` | TOML overriding any default | — |
| `--out DIR` | output folder | `out/` |

Speed: about 250 attempts/s on one core (5000 attempts in ~20 s), with
roughly 40% of attempts producing a valid grid.

### Output

For each ranked grid, printed and written to `out/run-<seed>/grid-NN.*`:

- **stats**: blocks, words, average word length, 3-letter count, Grid Flow,
  fillability score, length histogram, any dead (0-candidate) or tight slots
- **seeds**: clue number, direction, row/col of each seed, and where seeds cross
- **ASCII** with row/column numbers 1-15 (plain, and with seed letters)
- `grid-NN.txt`: all of the above plus the plain `#`/`.` grid and a
  **"block columns by row"** list, e.g. `row  1: 5, 6, 11, 12`, which is
  the quickest way to place blocks in Crosserville
- `grid-NN.png`: preview with row/column numbers, clue numbers, seed letters
  shaded blue, and red guide lines every 5 squares
- `grid-NN.ipuz`: ipuz v2 crossword; seed letters filled in the solution,
  other squares empty; seed clues are marked `[seed: WORD]`

At the start of a run the tool also lists, for every pair of seeds, how many
of their possible crossing points are letter-compatible. Placements where two
seeds would cross at different letters are always rejected; pairs with no
shared letters can never cross.

### Hard constraints (a grid is rejected if any fail)

15x15, 180° rotational symmetry; no entry shorter than 3; no unchecked
squares; all white squares connected; no solid 3x3 black block; words ≤ 72;
every seed in a distinct slot of exactly its length (seeds may share a
symmetric slot pair, or sit in a self-symmetric slot like a centered row-8
entry), with consistent letters wherever seeds cross.

### Scoring (soft; `gridfinder/default_config.toml`)

Score is a weighted average (0-100) of:

| Component | Target (approved Friday norms) | Weight |
|---|---|---|
| words | 64-72, ideal 69 | 1.0 |
| blocks | 26-34, ideal 30 | 1.0 |
| average word length | ≥ 5.4, ideal 5.6+ | 1.5 |
| 3-letter entries | ≤ 12, fewer is better | 1.5 |
| fillability | no dead/tight slots | 2.0 |
| Grid Flow (secondary) | ≥ 25, ideal ≥ 40 | 0.5 |

Sources for the targets: the
[Grid Flow article](https://xwordblog.com/2025/10/21/crossword-flow/) (reference
grids at 70 words / avg 5.40 and 62 words / avg 6.29; Flow 8 = "abysmal",
35 = "modest", 133 = "stratospheric"), and
[Alex Beals' grid builder write-up](https://blog.alexbeals.com/posts/crossword-grid-builder)
(Fri/Sat grids "tend towards more X patterns and central dividers, with more
open grids", with fewer, longer words). The block and 3-letter ranges are
from general knowledge of NYT Friday puzzles and were approved by hand.

**Fillability**: for each non-seed slot, count word-list entries (score ≥ 50)
matching its length and any letters fixed by seeds. 0 candidates costs 25
points, fewer than 5 costs up to 8. Set `reject_dead = true` to discard grids
with any dead slot.

To change weights or targets, copy the defaults and edit:

```bash
cp gridfinder/default_config.toml config.toml
gridfinder find seeds.txt --config config.toml
```

### Fill check (does the grid actually fill?)

The per-slot fillability count can't see conflicts between crossing slots,
so after ranking, `find` checks grids against your word list in rank order:

1. **Quick impossibility check** (~40 ms/grid): repeatedly remove words
   that don't fit any word in a crossing slot. If a slot runs out of words,
   the grid is **impossible** with this list and is skipped.
2. **Full fill attempt** (`time_limit`, default 10 s): backtracking with
   randomized restarts, most-constrained slot first, best-scored words first,
   no repeated answers. Results are **FILLED** (with a machine-made sample
   fill, printed and saved in the `.txt`), **IMPOSSIBLE** (search exhausted),
   or **UNKNOWN** (time ran out; may still be fillable).

By default `find` shows **only grids verified fillable** (the filler found a
complete fill with your word list) and **hides the fill**, so you fill the
grid yourself. It stops after `--top` verified grids or `max_fill_attempts`
fill attempts. Flags: `--show-fill` (reveal the machine fill),
`--allow-unproven` (also show grids that timed out), `--fill-time N`
(seconds per attempt; 0 = quick check only), `--no-fillcheck`.
`gridfinder check` runs the same check on your own grid. Settings are in
`[fillcheck]`.

Rule of thumb from testing: 4 seeds with several crossings are usually
impossible; 2-3 seeds leave most grids fillable. The filler is pure Python,
so wide-open grids often come back UNKNOWN rather than FILLED. Crosserville's
autofill is the final word.

### Grid Flow: implementation and assumptions

Per the article: build a graph with one node per entry and an edge wherever
two entries cross; Grid Flow = the Fiedler value (second-smallest eigenvalue
of the graph Laplacian) × the number of checked squares.

Assumptions (please review):

1. **Unweighted crossings**: each crossing is one edge of weight 1.
2. **No length weighting**: plain Laplacian L = D − A; every entry is a rod
   with equal "heat capacity". A length-weighted variant is available with
   `[flow] weighting = "length"`; it is off by default because the article
   doesn't mention it.
3. **Checked squares** = squares in both an across and a down entry; in a
   valid grid that is every white square.
4. **Disconnected** slot graph → Flow 0.
5. **Calibration**: the published values for specific NYT grids (133, 8, 35)
   couldn't be reproduced here without those grids. Tests check the math on
   graphs with known spectra (e.g. an open 3x3 grid is K3,3, λ₂ = 3,
   Flow = 27). To calibrate, draw a published grid into a text file and run
   `gridfinder check` on it, then compare with XWord Info or Crosserville.

### Search

Each attempt (seeded RNG):

1. **Seed layout**: longest seed first, choose a random legal position. Its
   squares are locked white, the squares just before and after it become
   blocks, and everything is mirrored. Positions that put a seed in another
   seed's mirror slot (`pair_bias`) or cross another seed at a matching
   letter (`cross_bias`) are favored, since crossing marquee entries raises
   Flow.
2. **Repair**: any 1-2 letter runs created by those end blocks are blacked out.
3. **Fill**: add mirrored block pairs until a target word count (sampled from
   64-72) is reached. Every move must keep runs ≥ 3, avoid 3x3 black squares,
   and keep the grid connected. Moves are weighted toward Friday-style
   shapes: diagonal staircases, short bars, cells near the X diagonals, and
   edge notches. Moves that create a new 3-letter entry are usually refused
   (`three_reject`).

All biases live in the `[search]` section of the config.

### Project layout

```
gridfinder/
  grid.py      grid model, slots, numbering, hard-constraint checks
  stats.py     blocks / words / avg length / 3-letter counts
  flow.py      Grid Flow
  wordlist.py  word list format detection, pattern counting
  fill.py      fillability proxy (per-slot candidate counts)
  fillcheck.py real fill check (impossibility proof + sample fill)
  seeds.py     seed parsing, placement on a grid, crossing reports
  search.py    randomized symmetric search
  scoring.py   soft scoring
  export.py    ASCII / txt / ipuz / PNG
  cli.py       command line
  default_config.toml
tests/         pytest suite
```
