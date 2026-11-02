"""Configuration loading: packaged defaults deep-merged with a user TOML file."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).with_name("default_config.toml")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = tomllib.loads(DEFAULT_PATH.read_text())
    if path:
        cfg = _merge(cfg, tomllib.loads(Path(path).read_text()))
    return cfg
