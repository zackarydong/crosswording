"""gridfinder command line.

  gridfinder find seeds.txt [--wordlist data/XwiWordList.dict] [--top 5] [--seed 1] ...
  gridfinder check grid.txt --seeds seeds.txt   (score a grid you drew yourself)
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

from .config import load_config
from .export import export_all, report
from .fillcheck import FILLED, IMPOSSIBLE, Filler
from .grid import Grid, violations
from .scoring import score_candidate
from .search import Candidate, Searcher
from .seeds import crossing_report, letters_for, load_seeds, place_seeds
from .wordlist import AmbiguousFormat, WordList


def _default_wordlist() -> Path | None:
    data = Path("data")
    found = sorted(data.glob("*.dict")) + sorted(data.glob("*.txt")) if data.is_dir() else []
    return found[0] if found else None


def _load_wordlist(args, cfg) -> WordList | None:
    path = Path(args.wordlist) if args.wordlist else _default_wordlist()
    if path is None:
        print("note: no word list given (--wordlist) and none in data/; skipping fillability", file=sys.stderr)
        return None
    try:
        t = time.time()
        wl = WordList.load(path, cfg["fill"]["min_score"], cfg["fill"]["good_score"])
        print(f"word list: {path} ({wl.total:,} entries, score >= {wl.min_score} used) [{time.time() - t:.1f}s]")
        return wl
    except AmbiguousFormat as e:
        sys.exit(f"word list format unclear: {e}\nPlease tell me the format (e.g. WORD;SCORE).")


def _apply_overrides(cfg, args) -> None:
    h = cfg["hard"]
    if args.min_blocks is not None:
        h["min_blocks"] = args.min_blocks
    if args.max_blocks is not None:
        h["max_blocks"] = args.max_blocks
    if args.max_words is not None:
        h["max_words"] = args.max_words
    if getattr(args, "attempts", None) is not None:
        cfg["search"]["attempts"] = args.attempts


def cmd_find(args) -> int:
    cfg = load_config(args.config)
    _apply_overrides(cfg, args)
    seeds = load_seeds(args.seeds, cfg["hard"]["size"])
    if not 3 <= len(seeds) <= 6:
        print(f"note: {len(seeds)} seeds given (3-6 expected); continuing")
    wl = _load_wordlist(args, cfg)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    rng = random.Random(seed)
    searcher = Searcher(seeds, cfg, rng)
    attempts = cfg["search"]["attempts"]
    print(f"seeds: {', '.join(seeds)} | rng seed {seed} | {attempts} attempts")
    print("seed crossings (placements where two seeds would cross at different letters are rejected):")
    for line in crossing_report(seeds):
        print("  " + line)
    best: dict[bytes, object] = {}
    t = time.time()
    reject_dead = cfg["fill"]["reject_dead"]
    for k in range(attempts):
        cand = searcher.attempt()
        if cand is None:
            continue
        key = cand.grid.key()
        if key in best:
            searcher.log.duplicates += 1
            continue
        sc = score_candidate(cand, cfg, wl)
        if reject_dead and sc.fill.dead:
            continue
        o = cfg["openness"]
        if 0 <= o["max_long_nonseed"] < sc.long_nonseed or 0 <= o["max_stack_pairs"] < sc.stack_pairs:
            continue
        best[key] = sc
        if not args.quiet and (k + 1) % 1000 == 0:
            print(f"  {k + 1} attempts, {len(best)} valid grids, {time.time() - t:.1f}s")
    dt = time.time() - t
    log = searcher.log
    print(
        f"done in {dt:.1f}s: {log.attempts} attempts, {log.produced} valid grids "
        f"({len(best)} unique), {log.attempts / max(dt, 1e-9):.0f} attempts/s"
    )
    if log.fill_reasons:
        print("  rejected attempts: " + ", ".join(f"{k} {v}" for k, v in log.fill_reasons.most_common()))
    if not best:
        print("no valid grids found; try more --attempts, other seeds, or a wider --max-blocks")
        return 1
    ranked_all = sorted(best.values(), key=lambda s: -s.score)
    ranked = _apply_fillcheck(ranked_all, cfg, wl, args) if wl is not None else ranked_all[: args.top]
    if not ranked:
        print("no grid passed the fill check; try more --attempts, different seeds, or fewer seeds")
        return 1
    outdir = Path(args.out) / f"run-{seed}"
    for rank, s in enumerate(ranked, 1):
        print()
        print(report(s, rank))
        files = export_all(s, rank, outdir)
        print("files: " + ", ".join(str(f) for f in files))
    return 0


def _apply_fillcheck(ranked_all, cfg, wl, args):
    fc = cfg["fillcheck"]
    if not fc["enabled"] or getattr(args, "no_fillcheck", False):
        return ranked_all[: args.top]
    time_limit = args.fill_time if getattr(args, "fill_time", None) is not None else fc["time_limit"]
    t = time.time()
    keep_unproven = fc["keep_unproven"] or getattr(args, "allow_unproven", False)
    show_fill = fc["show_sample_fill"] or getattr(args, "show_fill", False)
    survivors, impossible, checked, unknown, fills = [], 0, 0, 0, 0
    for s in ranked_all[: fc["max_checked"]]:
        if fills >= fc["max_fill_attempts"]:
            break
        checked += 1
        f = Filler(s.cand.grid, s.cand.letters, set(s.cand.seed_slots.values()), wl)
        r = f.arc_check()
        if r.status == IMPOSSIBLE:
            impossible += 1
            continue
        if fc["sample_fill"] and time_limit > 0:
            fills += 1
            r = f.fill(time_limit, fc["branch"])
            if r.status == IMPOSSIBLE:
                impossible += 1
                continue
            if r.status != FILLED:
                unknown += 1
                if not keep_unproven:
                    continue
            if not show_fill:
                r.letters = None
        elif not keep_unproven:
            continue
        s.fillcheck = r
        survivors.append(s)
        if len(survivors) >= args.top:
            break
    filled = sum(1 for s in survivors if s.fillcheck.status == FILLED)
    print(
        f"fill check: {checked} best-scoring grids checked: {impossible} impossible, "
        f"{unknown} unproven (time limit), {filled} verified fillable [{time.time() - t:.1f}s]"
    )
    return survivors


def cmd_check(args) -> int:
    cfg = load_config(args.config)
    _apply_overrides(cfg, args)
    grid = Grid.from_text(Path(args.grid).read_text())
    v = violations(grid, cfg["hard"]["max_words"], cfg["hard"]["min_entry"])
    print("hard constraints: " + ("OK" if not v else "VIOLATED"))
    for x in v:
        print("  - " + x)
    seeds = load_seeds(args.seeds, grid.n) if args.seeds else []
    letters: list = [None] * (grid.n * grid.n)
    seed_slots = {}
    if seeds:
        pl = place_seeds(grid, seeds)
        if not pl.ok:
            print("seeds do NOT fit this grid")
            for u in pl.unplaceable:
                print(f"  - no slot for {u}")
            for c in pl.conflicts:
                print("  - conflict: " + c.describe())
            return 1
        seed_slots = pl.assignment
        letters = letters_for(pl.assignment, grid.n * grid.n)
        if pl.conflicts:
            print("note: some seed positions were rejected because they cross at different letters:")
            for c in pl.conflicts[:10]:
                print("  - " + c.describe())
    wl = _load_wordlist(args, cfg)
    cand = Candidate(grid, [], letters, seed_slots)
    sc = score_candidate(cand, cfg, wl)
    if wl is not None and not args.no_fillcheck:
        time_limit = args.fill_time if args.fill_time is not None else cfg["fillcheck"]["time_limit"]
        sc.fillcheck = Filler(grid, letters, set(seed_slots.values()), wl).fill(time_limit, cfg["fillcheck"]["branch"])
        if not (cfg["fillcheck"]["show_sample_fill"] or args.show_fill):
            sc.fillcheck.letters = None
    print(report(sc, 1))
    if args.export:
        files = export_all(sc, 1, Path(args.export))
        print("files: " + ", ".join(str(f) for f in files))
    return 0 if not v else 2


def cmd_screen(args) -> int:
    from .screen import screen

    cfg = load_config(args.config)
    _apply_overrides(cfg, args)
    seeds = load_seeds(args.seeds, cfg["hard"]["size"])
    path = Path(args.wordlist) if args.wordlist else _default_wordlist()
    if path is None:
        sys.exit("screen needs a word list (--wordlist or data/*.dict)")
    require = [w.upper() for w in (args.require or [])]
    t = time.time()
    print(f"screening {len(seeds)} seeds in groups of {args.size} ({args.attempts} attempts each, rng seed {args.seed})...")
    res = screen(seeds, args.size, str(path), cfg, args.attempts, args.check_top, args.fills, args.fill_time, args.seed, require=require)
    print(f"done in {time.time() - t:.0f}s\n")
    print(f"{'verified':>8} {'quick-check pass':>17} {'best score':>10}  seeds")
    for r in res:
        print(f"{r.verified:>4}/{r.fills_tried:<3} {r.survivors:>7}/{r.checked:<3} ({r.survival:4.0%}) {r.best_score:>8.1f}  {' + '.join(r.seeds)}")
    print("\nverified = grids fully filled from your list (of fills tried); quick-check pass = not provably impossible.")
    print("Next: run `gridfinder find` on a promising combination for verified grids.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gridfinder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--wordlist", help="scored word list (default: first *.dict in data/)")
        sp.add_argument("--config", help="TOML file overriding gridfinder/default_config.toml")
        sp.add_argument("--min-blocks", type=int)
        sp.add_argument("--max-blocks", type=int)
        sp.add_argument("--max-words", type=int)
        sp.add_argument("--no-fillcheck", action="store_true", help="skip the word-list fill check")
        sp.add_argument("--fill-time", type=float, help="seconds per full-fill attempt (0 = quick check only)")
        sp.add_argument("--show-fill", action="store_true", help="print/save the machine-made sample fill")
        sp.add_argument("--allow-unproven", action="store_true", help="also show grids not yet proven fillable")

    f = sub.add_parser("find", help="search for grids that hold your seeds")
    f.add_argument("seeds", help="seeds file, one entry per line")
    common(f)
    f.add_argument("--top", type=int, default=5, help="number of grids to show/export (default 5)")
    f.add_argument("--seed", type=int, help="RNG seed for reproducible runs")
    f.add_argument("--attempts", type=int, help="candidate grids to try (default from config)")
    f.add_argument("--out", default="out", help="output folder (default out/)")
    f.add_argument("--quiet", action="store_true")
    f.set_defaults(func=cmd_find)

    sc = sub.add_parser("screen", help="try every combination of your seeds to see which can share a fillable grid")
    sc.add_argument("seeds", help="seeds file with all the entries you'd like to use")
    sc.add_argument("--size", type=int, default=3, help="seeds per combination (default 3)")
    sc.add_argument("--require", nargs="*", help="only combinations containing these seeds")
    sc.add_argument("--attempts", type=int, default=1500)
    sc.add_argument("--check-top", type=int, default=200, help="best-scoring grids to quick-check per combination")
    sc.add_argument("--fills", type=int, default=4, help="full fill attempts per combination")
    sc.add_argument("--seed", type=int, default=1)
    common(sc)
    sc.set_defaults(func=cmd_screen)

    c = sub.add_parser("check", help="validate and score a grid you drew (# = block, . = white)")
    c.add_argument("grid")
    c.add_argument("--seeds")
    c.add_argument("--export", help="folder to write txt/ipuz/png into")
    common(c)
    c.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
