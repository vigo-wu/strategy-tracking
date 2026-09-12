# coding: utf-8
"""实盘评估 spec：年份窗（含 deploy）、overrides 从网格 summary 反查。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from analyze import DEFAULT_DIVIDEND_TYPE, normalize_dividend_type, normalize_ma_type
from asset_split import DEFAULT_UNIVERSE_DIR
from grid_spec import GridSpecError, _as_year, reject_deleted_factor_keys, year_range_set
from robust_gate import fill_gate, validate_gate

REPO = Path(__file__).resolve().parents[3]
THEME = REPO / "hongli_band"
ROBUST_ROOT = THEME / "report" / "robust"

YEAR_DEFAULTS: dict[str, int] = {
    "year_start": 2018,
    "year_end": 2026,
    "tune_start": 2018,
    "tune_end": 2021,
    "check_start": 2022,
    "check_end": 2023,
    "deploy_start": 2024,
    "deploy_end": 2026,
}

DEFAULT_N_BASKETS = 40
DEFAULT_BASKET_SIZE = 10
DEFAULT_SEED = 42
WARN_BASKETS_SOFT = 60


class RobustSpecError(ValueError):
    """spec / overrides 解析错误。"""


def fill_year_windows(spec: Mapping[str, Any] | None) -> dict[str, int]:
    src = spec if isinstance(spec, Mapping) else {}
    out: dict[str, int] = {}
    for key, default in YEAR_DEFAULTS.items():
        out[key] = _as_year(src.get(key), default)
    return out


def validate_year_windows(win: Mapping[str, Any]) -> dict[str, int]:
    filled = fill_year_windows(win)
    ys, ye = filled["year_start"], filled["year_end"]
    ts, te = filled["tune_start"], filled["tune_end"]
    cs, ce = filled["check_start"], filled["check_end"]
    ds, de = filled["deploy_start"], filled["deploy_end"]
    if ys > ye:
        raise RobustSpecError("回测年起必须 ≤ 止")
    run = year_range_set(ys, ye)
    tune = year_range_set(ts, te)
    check = year_range_set(cs, ce)
    deploy = year_range_set(ds, de)
    if not tune:
        raise RobustSpecError("调参期为空")
    if not check:
        raise RobustSpecError("验收期为空")
    if not deploy:
        raise RobustSpecError("上线盲测窗为空")
    if not tune <= run:
        raise RobustSpecError("调参期必须落在回测年内")
    if not check <= run:
        raise RobustSpecError("验收期必须落在回测年内")
    if not deploy <= run:
        raise RobustSpecError("上线盲测窗必须落在回测年内")
    if tune & check:
        raise RobustSpecError("调参期与验收期不能重叠")
    if check & deploy:
        raise RobustSpecError("验收期与上线盲测窗不能重叠")
    if tune & deploy:
        raise RobustSpecError("调参期与上线盲测窗不能重叠")
    if int(ds) <= int(ce):
        raise RobustSpecError("deploy_start 须 > check_end")
    return filled


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cells_from_bundle(data: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(data, Mapping):
        return []
    cells = data.get("cells")
    if isinstance(cells, list):
        return [c for c in cells if isinstance(c, Mapping)]
    return []


def resolve_overrides_from_summary(
    summary_path: str | Path,
    *,
    recommend_id: str | None = None,
) -> dict[str, Any]:
    """recommend.id → cells[].overrides；base 可为空对象。"""
    path = Path(summary_path)
    if not path.is_absolute():
        path = REPO / path
    path = path.resolve()
    if not path.is_file():
        raise RobustSpecError("overrides_from 不存在: %s" % path)
    summary = _load_json(path)
    if not isinstance(summary, Mapping):
        raise RobustSpecError("summary.json 格式无效")

    rec = summary.get("recommend") if isinstance(summary.get("recommend"), Mapping) else {}
    rid = str(recommend_id or rec.get("id") or "").strip()
    if not rid:
        raise RobustSpecError("summary 无 recommend.id")

    cells = _cells_from_bundle(summary)
    if not cells:
        # sibling freeze/spec
        for name in ("freeze.json", "spec.json"):
            sib = path.parent / name
            if sib.is_file():
                try:
                    cells = _cells_from_bundle(_load_json(sib))
                except Exception:
                    cells = []
                if cells:
                    break
    if not cells:
        raise RobustSpecError("无法从 summary/spec 找到 cells 以解析 overrides")

    by_id = {str(c.get("id") or "").strip(): c for c in cells if str(c.get("id") or "").strip()}
    cell = by_id.get(rid)
    if cell is None:
        raise RobustSpecError("cells 中无 recommend.id=%s" % rid)
    ov = cell.get("overrides")
    if ov is None:
        ov = {}
    if not isinstance(ov, Mapping):
        raise RobustSpecError("cell overrides 不是对象: %s" % rid)
    return {
        "id": rid,
        "kind": cell.get("kind"),
        "label": cell.get("label") or rid,
        "overrides": dict(ov),
        "reason": rec.get("reason"),
        "summary_path": str(path),
    }


def resolve_overrides(spec: Mapping[str, Any]) -> dict[str, Any]:
    """显式非空 overrides → overrides_from → 空则现行 config（空 overrides）。"""
    src = spec if isinstance(spec, Mapping) else {}
    raw_ov = src.get("overrides")
    meta = src.get("_overrides_meta") if isinstance(src.get("_overrides_meta"), Mapping) else None
    if isinstance(raw_ov, Mapping) and (len(raw_ov) > 0 or meta is not None):
        return {
            "id": str((meta or {}).get("id") or src.get("overrides_id") or "manual").strip()
            or "manual",
            "kind": (meta or {}).get("kind") or src.get("overrides_kind") or "other",
            "label": (meta or {}).get("label") or src.get("overrides_label") or "manual",
            "overrides": dict(raw_ov),
            "reason": (meta or {}).get("reason") or "spec.overrides",
            "summary_path": (meta or {}).get("summary_path"),
        }
    ofrom = str(src.get("overrides_from") or "").strip()
    if ofrom:
        return resolve_overrides_from_summary(ofrom)
    return {
        "id": "config",
        "kind": "base",
        "label": "现行 config",
        "overrides": {},
        "reason": "未指定 overrides，使用片段/config 现行常量",
        "summary_path": None,
    }


def fill_sampling(spec: Mapping[str, Any] | None) -> dict[str, Any]:
    src = spec if isinstance(spec, Mapping) else {}
    try:
        n = int(src.get("n_baskets") if src.get("n_baskets") is not None else DEFAULT_N_BASKETS)
    except (TypeError, ValueError):
        n = DEFAULT_N_BASKETS
    try:
        k = int(src.get("basket_size") if src.get("basket_size") is not None else DEFAULT_BASKET_SIZE)
    except (TypeError, ValueError):
        k = DEFAULT_BASKET_SIZE
    try:
        seed = int(src.get("seed") if src.get("seed") is not None else DEFAULT_SEED)
    except (TypeError, ValueError):
        seed = DEFAULT_SEED
    uni = str(src.get("universe_dir") or DEFAULT_UNIVERSE_DIR).strip() or DEFAULT_UNIVERSE_DIR
    return {
        "n_baskets": max(1, n),
        "basket_size": max(1, k),
        "seed": seed,
        "universe_dir": uni,
    }


def load_spec(path: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(path, Mapping):
        raw = dict(path)
    else:
        p = Path(path)
        if not p.is_absolute():
            p = REPO / p
        raw = _load_json(p.resolve())
        if not isinstance(raw, Mapping):
            raise RobustSpecError("spec 须为 JSON 对象")
        raw = dict(raw)

    try:
        reject_deleted_factor_keys(raw)
    except GridSpecError as e:
        raise RobustSpecError(str(e)) from e
    win = validate_year_windows(raw)
    raw.update(win)
    sampling = fill_sampling(raw)
    raw.update(sampling)
    gate = validate_gate(raw.get("gate"))
    raw["gate"] = gate

    resolved = resolve_overrides(raw)
    raw["overrides"] = dict(resolved["overrides"])
    raw["_overrides_meta"] = {
        "id": resolved["id"],
        "kind": resolved.get("kind"),
        "label": resolved.get("label"),
        "reason": resolved.get("reason"),
        "summary_path": resolved.get("summary_path"),
    }

    raw["theme"] = str(raw.get("theme") or "hongli_band").strip() or "hongli_band"
    run_id = str(raw.get("run_id") or raw.get("sweep") or "").strip()
    if not run_id:
        raise RobustSpecError("须提供 run_id")
    raw["run_id"] = run_id
    raw["compare_div"] = (
        normalize_dividend_type(raw.get("compare_div")) or DEFAULT_DIVIDEND_TYPE
    )
    raw["ma_type"] = normalize_ma_type(raw.get("ma_type")) or "EMA"
    raw["compound_backtest"] = bool(raw.get("compound_backtest", True))
    return raw


def run_dir(spec: Mapping[str, Any]) -> Path:
    return ROBUST_ROOT / str(spec.get("run_id") or "run")


def json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(x) for x in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj
