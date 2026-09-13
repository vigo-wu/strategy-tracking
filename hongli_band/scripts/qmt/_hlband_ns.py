# coding: utf-8
"""同一 ns exec config.py + catalog.py。deploy / grid_spec 共用。"""
from __future__ import annotations

from pathlib import Path

HLBAND = Path(__file__).resolve().parent / "hlband"
_RELS = ("config.py", "factors/catalog.py")


def load_hlband_ns() -> dict:
    ns: dict = {}
    for rel in _RELS:
        path = HLBAND / rel
        if not path.is_file():
            raise FileNotFoundError(path)
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), ns, ns)
    return ns
