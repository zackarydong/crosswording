# CLAUDE.md

Context for Claude sessions working in this repo. See README.md for usage.

## Project
`gridfinder`: Python CLI that finds 15x15 black-square layouts for an
NYT-style **Friday themeless** that hold 3-6 long seed entries. The owner
rebuilds the chosen grid by hand in Crosserville, so ASCII/PNG output must
stay easy to read (row/col numbers, "block columns by row" list).

## Workflow (owner's preferences)
- Push directly to `main`. No pull requests, no feature branches,
  unless a change would significantly alter the current process (ask first then).
- Small steps; add/adjust pytest tests with each change; run `pytest` before pushing.
- Profile before optimizing (`python -m cProfile -s tottime -m gridfinder.cli find ...`).
- Commit author: zackarydong <zackarydong@gmail.com>.
- Never commit word lists: `data/` and `*.dict` are git-ignored. The owner's
  list is `data/XwiWordList.dict` (local only; ask for it if missing).
- The owner's Mac uses a work GitHub/Claude login for other things; this
  project uses the personal account (`zackarydong`). Don't touch work setup.

## Approved decisions (Step 0, confirmed by owner)
- Hard: 15x15, 180° symmetry, entries >= 3, no unchecked squares, connected,
  no 3x3 black block, words <= 72, each seed in a distinct exact-length slot,
  seeds may cross only at matching letters.
- Soft Friday targets: words 64-72 (ideal 69), blocks 26-34 (ideal 30),
  avg word length >= 5.4 (ideal 5.6), 3-letter entries <= 12 (fewer better).
- **Grid Flow is a secondary qualification** (low weight): min 25, ideal 40.
  Implemented per xwordblog.com/2025/10/21/crossword-flow: Fiedler value of
  the slot-crossing graph x checked squares. Assumptions (unweighted edges,
  no length weighting by default) are listed in README; not yet calibrated
  against published XWord Info values.
- Word list format `word;score` (scores 5-60; 50 = default/unreviewed,
  60 = curated good). Fillability counts words with score >= 50.
- Don't scrape XWord Info (it returns 403 to automated requests; owner said skip it).

## Code map
gridfinder/: grid.py (model, slots, constraints), stats.py, flow.py,
wordlist.py, fill.py, fillcheck.py (pruning + backtracking fill check), seeds.py, search.py (randomized symmetric search),
scoring.py, export.py (ascii/txt/ipuz/png), cli.py (`find`, `check`),
default_config.toml (all weights/targets/biases).

## Findings
- Crosserville said the Set A Flow-132 grid was impossible; fillcheck agrees.
  Before fillcheck, most top-ranked grids were unfillable. 4 crossing seeds is
  usually impossible; 2-3 seeds works much better.
- Full-pruning propagation in the filler beats forward checking (proves
  impossibility fast). Filler speed (~50 nodes/s) is the bottleneck on
  open grids. Next speedups: bitset domains, or a compiled filler.

## Browser tools
- `tools/word-grader.html` (+ `studio.js`, `fillworker.js`) is published at https://claude.ai/artifact/DC1N4zGX2guDPYmphyVLnn : Grade words tab + Fill grid tab. Grades live in the artifact's db (`grades/<letter>` docs, owner-only); read them with ArtifactData and rebuild the master list with `python -m gridfinder.joinscores data/XwiWordList.dict data/xwordlist-old.dict --grades data/grades.json --out data/XwiWordList-graded.dict`.

## Open items / ideas
- Calibrate Flow: run `gridfinder check` on a few published grids and compare
  with Crosserville/XWord Info.
- Verify the .ipuz imports into Crosserville (only seed letters are filled).
- Grids may finish slightly under 64 words when the fill gets stuck
  (`stuck_slack`); scoring penalizes them.
