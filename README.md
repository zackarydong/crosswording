# crosswording

Grid Finder + Better Fills.

## gridfinder (in progress)

A Python CLI that finds 15x15 black-square layouts for an NYT-style Friday
themeless puzzle that can hold a few long "marquee" seed entries.

### Setup (on your Mac)

```bash
mkdir -p ~/Projects
cd ~/Projects && git clone https://github.com/zackarydong/crosswording.git
cd crosswording
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Word list

Put your scored word list (`word;score` per line) in `data/`, e.g.
`data/XwiWordList.dict`. The `data/` folder and all `*.dict` files are
git-ignored, so your list never gets committed.

### Seeds

One entry per line, letters only, 7-15 letters. See `seeds.example.txt`.
