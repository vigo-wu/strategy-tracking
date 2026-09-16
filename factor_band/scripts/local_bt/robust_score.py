# coding: utf-8
"""实盘评估评分：复用网格四维综合分；GO = 中位总分 ≥ go_floor。"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SKILL_SCRIPTS = REPO / ".cursor" / "skills" / "qmt-local-bt-grid" / "scripts"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

from grid_score import (  # noqa: E402
    fill_score as grid_fill_score,
    score_cell,
    score_for_json,
    validate_score as grid_validate_score,
)

GO_FLOOR = 50.0
EPS = 1e-6


def _as_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _unwrap(raw: Mapping[str, Any] | None) -> Mapping[str, Any]:
    src = raw if isinstance(raw, Mapping) else {}
    if "score" in src and isinstance(src.get("score"), Mapping) and "w_def" not in src:
        return src["score"]  # type: ignore[return-value]
    return src


def default_score() -> dict[str, Any]:
    out = grid_fill_score(None)
    out["go_floor"] = GO_FLOOR
    return out


def fill_score(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    src = _unwrap(raw)
    out = grid_fill_score(src)
    out["go_floor"] = _as_float(src.get("go_floor"), GO_FLOOR)
    return out


def validate_score(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    src = _unwrap(raw)
    grid_validate_score(src)
    filled = fill_score(src)
    gf = float(filled["go_floor"])
    if gf <= 0.0 or gf > 100.0:
        raise ValueError("score.go_floor 须在 (0, 100]")
    return filled


def score_cfg_for_json(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return deepcopy(fill_score(raw))


def book_from_windows(blocks: Mapping[str, Any] | None) -> dict[str, Any]:
    src = blocks if isinstance(blocks, Mapping) else {}

    def _block(key: str) -> dict[str, Any]:
        raw = src.get(key)
        return dict(raw) if isinstance(raw, Mapping) else {}

    deploy = _block("deploy")
    return {
        "windows": {
            "all": _block("all"),
            "tune": _block("tune"),
            "check": _block("check"),
        },
        "holdout_windows": {
            "all": dict(deploy),
            "tune": {},
            "check": dict(deploy),
        },
    }


def score_basket(
    blocks: Mapping[str, Any] | None,
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    used = fill_score(cfg)
    return score_for_json(score_cell(book_from_windows(blocks), space_on=True, cfg=used))


def _median(vals: Sequence[float]) -> float | None:
    xs = sorted(float(x) for x in vals)
    if not xs:
        return None
    mid = len(xs) // 2
    if len(xs) % 2:
        return xs[mid]
    return 0.5 * (xs[mid - 1] + xs[mid])


def eval_run_score(
    baskets: Sequence[Mapping[str, Any]],
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    used = validate_score(cfg)
    rows = list(baskets or [])
    totals: list[float] = []
    for row in rows:
        if row.get("scored") is False:
            continue
        tot = row.get("total")
        if tot is None:
            continue
        try:
            totals.append(float(tot))
        except (TypeError, ValueError):
            continue
    n_scored = len(totals)
    med = _median(totals)
    go_floor = float(used["go_floor"])
    go = bool(n_scored > 0 and med is not None and med + EPS >= go_floor)
    reasons: list[str] = []
    if n_scored <= 0 or med is None:
        reasons.append("无组可评分")
    elif not go:
        reasons.append("中位总分 %.2f < %.2f" % (med, go_floor))
    return {
        "verdict": "GO" if go else "NO-GO",
        "go": go,
        "n_baskets": len(rows),
        "n_scored": n_scored,
        "median_total": None if med is None else round(med, 4),
        "go_floor": go_floor,
        "reasons": reasons or None,
        "reason": "；".join(reasons) if reasons else ("通过" if go else "未通过"),
        "score": score_cfg_for_json(used),
    }
