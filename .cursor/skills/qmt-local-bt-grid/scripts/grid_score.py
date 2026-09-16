# coding: utf-8
"""网格四维综合分：防御 / 结构 / 复原 / 泛化。不参与回放，只吃窗 KPI。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

W_DEF = 0.30
W_STR = 0.25
W_RES = 0.25
W_GEN = 0.20
W_NO_GEN = W_DEF + W_STR + W_RES  # 0.80

DD_CAP = 0.35
PF_CAP = 5.0
FACTOR_TARGET = 0.5
SHARPE_TARGET = 0.5
SHIELD_MAX = 30.0
SHIELD_PENALTY = 15.0
N_TRADES_FLOOR = 30.0
N_TRADES_FULL = 80.0
STR_FACTOR_SCALE = 0.70
N_TRADES_AT_FLOOR = 15.0
N_TRADES_AT_FULL = 30.0
SCORE_CLOSE_PAD = 1.0
EPS_SHARPE = 1e-12

_KPI_PERIODS = ("all", "tune", "check")
_KPI_FIELDS = (
    "max_dd",
    "avg_year_pnl",
    "win_rate",
    "profit_factor",
    "n_trades",
    "sharpe",
    "avg_ann_pct",
)
_WEIGHT_KEYS = ("w_def", "w_str", "w_res", "w_gen")


def default_score() -> dict[str, Any]:
    return {
        "w_def": W_DEF,
        "w_str": W_STR,
        "w_res": W_RES,
        "w_gen": W_GEN,
        "dd_cap": DD_CAP,
        "factor_target": FACTOR_TARGET,
        "pf_cap": PF_CAP,
        "sharpe_target": SHARPE_TARGET,
        "n_trades_floor": N_TRADES_FLOOR,
        "n_trades_full": N_TRADES_FULL,
    }


def _as_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _num(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _unwrap_score_src(raw: Mapping[str, Any] | None) -> Mapping[str, Any]:
    src = raw if isinstance(raw, Mapping) else {}
    if "score" in src and isinstance(src.get("score"), Mapping) and "w_def" not in src:
        return src["score"]  # type: ignore[return-value]
    return src


def _normalize_weights(src: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, float]:
    raw = [_as_float(src.get(k), float(base[k])) for k in _WEIGHT_KEYS]
    if any(v < 0.0 for v in raw):
        return {k: float(base[k]) for k in _WEIGHT_KEYS}
    if raw and max(raw) > 1.0:
        raw = [v / 100.0 for v in raw]
    total = sum(raw)
    if total <= 0.0:
        return {k: float(base[k]) for k in _WEIGHT_KEYS}
    return {k: v / total for k, v in zip(_WEIGHT_KEYS, raw)}


def fill_score(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """缺字段回落默认；权重归一成 1。不抛错。"""
    out = default_score()
    src = _unwrap_score_src(raw)
    out.update(_normalize_weights(src, out))
    dd = _as_float(src.get("dd_cap"), out["dd_cap"])
    if dd > 1.0:
        dd = dd / 100.0
    out["dd_cap"] = dd
    out["factor_target"] = _as_float(src.get("factor_target"), out["factor_target"])
    out["pf_cap"] = _as_float(src.get("pf_cap"), out["pf_cap"])
    out["sharpe_target"] = _as_float(src.get("sharpe_target"), out["sharpe_target"])
    out["n_trades_floor"] = _as_float(src.get("n_trades_floor"), out["n_trades_floor"])
    out["n_trades_full"] = _as_float(src.get("n_trades_full"), out["n_trades_full"])
    return out


def validate_score(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    src = _unwrap_score_src(raw)
    weights = [_as_float(src.get(k), float(default_score()[k])) for k in _WEIGHT_KEYS]
    if any(v < 0.0 for v in weights) or sum(max(v, 0.0) for v in weights) <= 0.0:
        raise ValueError("score 权重不能全为 0 或为负")
    filled = fill_score(raw)
    if filled["dd_cap"] <= 0.0:
        raise ValueError("score.dd_cap 必须 > 0")
    if filled["factor_target"] <= 0.0:
        raise ValueError("score.factor_target 必须 > 0")
    if filled["pf_cap"] <= 0.0:
        raise ValueError("score.pf_cap 必须 > 0")
    if filled["sharpe_target"] <= 0.0:
        raise ValueError("score.sharpe_target 必须 > 0")
    if filled["n_trades_floor"] < 0.0:
        raise ValueError("score.n_trades_floor 不能为负")
    if filled["n_trades_floor"] >= filled["n_trades_full"]:
        raise ValueError("score.n_trades_floor 必须 < n_trades_full")
    return filled


def score_cfg_for_json(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return deepcopy(fill_score(raw))


def load_score_from_sweep(root: Any, override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """override 优先，否则 freeze/spec 的 score，再默认。"""
    if override is not None:
        return validate_score(override)
    from pathlib import Path

    root_p = Path(root)
    for name in ("freeze.json", "spec.json"):
        path = root_p / name
        if not path.is_file():
            continue
        try:
            data = json_loads_safe(path)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("score"), dict):
            return validate_score(data["score"])
    return validate_score(None)


def json_loads_safe(path: Any) -> Any:
    import json
    from pathlib import Path

    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cfg(cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    return fill_score(cfg)


def _win(
    book: Mapping[str, Any],
    period: str,
    *,
    windows_key: str = "windows",
) -> dict[str, Any]:
    block = (book.get(windows_key) or {}).get(period)
    return block if isinstance(block, dict) else {}


def _lerp(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x1 == x0:
        return float(y1)
    t = (float(x) - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def _round4(val: float | None) -> float | None:
    if val is None:
        return None
    return round(float(val), 4)


def _book_scored(book: Mapping[str, Any]) -> bool:
    for key in ("windows", "holdout_windows"):
        block = book.get(key)
        if not isinstance(block, Mapping) or not block:
            continue
        for period in _KPI_PERIODS:
            w = block.get(period)
            if not isinstance(w, Mapping):
                continue
            if any(_num(w.get(f)) is not None for f in _KPI_FIELDS):
                return True
    return False


def _s_dd(book: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> float:
    dds: list[float] = []
    for period in _KPI_PERIODS:
        v = _num(_win(book, period).get("max_dd"))
        if v is not None:
            dds.append(abs(v))
    if not dds:
        return 0.0
    dd_max = max(dds)
    cap = float(_cfg(cfg)["dd_cap"])
    if cap <= 0.0:
        return 0.0
    return max(0.0, 100.0 * (1.0 - dd_max / cap))


def _s_shield(book: Mapping[str, Any], *, space_on: bool) -> float:
    pnls: list[float | None] = [
        _num(_win(book, "tune").get("avg_year_pnl")),
        _num(_win(book, "check").get("avg_year_pnl")),
    ]
    if space_on:
        pnls.append(_num(_win(book, "check", windows_key="holdout_windows").get("avg_year_pnl")))
    n_neg = sum(1 for p in pnls if p is None or p <= 0.0)
    return max(0.0, SHIELD_MAX - SHIELD_PENALTY * n_neg)


def s_def(
    book: Mapping[str, Any],
    *,
    space_on: bool,
    cfg: Mapping[str, Any] | None = None,
) -> float:
    return 0.70 * _s_dd(book, cfg) + _s_shield(book, space_on=space_on)


def _s_factor(check: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> float:
    wr = _num(check.get("win_rate"))
    pf = _num(check.get("profit_factor"))
    if wr is None or pf is None:
        return 0.0
    c = _cfg(cfg)
    factor = (wr / 100.0) * min(pf, float(c["pf_cap"]))
    target = float(c["factor_target"])
    if target <= 0.0:
        return 0.0
    s100 = min(100.0, max(0.0, factor / target * 100.0))
    return s100 * STR_FACTOR_SCALE


def _s_trades(check: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> float:
    n = _num(check.get("n_trades"))
    c = _cfg(cfg)
    floor = float(c["n_trades_floor"])
    full = float(c["n_trades_full"])
    if n is None or n < floor:
        return 0.0
    if n >= full:
        return N_TRADES_AT_FULL
    return _lerp(n, floor, N_TRADES_AT_FLOOR, full, N_TRADES_AT_FULL)


def s_str(book: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> float:
    check = _win(book, "check")
    return _s_factor(check, cfg) + _s_trades(check, cfg)


def _clip_sharpe(raw: float | None, cfg: Mapping[str, Any] | None = None) -> float:
    if raw is None:
        return 0.0
    target = float(_cfg(cfg)["sharpe_target"])
    if target <= 0.0:
        return 0.0
    return min(1.0, max(0.0, float(raw) / target))


def _s_sharpe(book: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> float:
    a = _clip_sharpe(_num(_win(book, "tune").get("sharpe")), cfg)
    b = _clip_sharpe(_num(_win(book, "check").get("sharpe")), cfg)
    return 50.0 * (a + b) / 2.0


def _s_decay(book: Mapping[str, Any]) -> float:
    tune = _num(_win(book, "tune").get("avg_ann_pct"))
    check = _num(_win(book, "check").get("avg_ann_pct"))
    if tune is None or check is None:
        return 0.0
    if tune < 0.0 or check < 0.0 or tune <= 0.0:
        return 0.0
    r = check / tune
    if r >= 1.0:
        return 50.0
    if r >= 0.5:
        return _lerp(r, 0.5, 25.0, 1.0, 50.0)
    return _lerp(max(r, 0.0), 0.0, 0.0, 0.5, 25.0)


def s_res(book: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> float:
    return _s_sharpe(book, cfg) + _s_decay(book)


def s_gen(book: Mapping[str, Any], *, space_on: bool) -> float | None:
    if not space_on:
        return None
    hold = _win(book, "all", windows_key="holdout_windows")
    if not hold:
        return 0.0
    s_h = _num(hold.get("sharpe"))
    if s_h is None or s_h <= 0.0:
        return 0.0
    s_t = _num(_win(book, "all").get("sharpe"))
    if s_t is None or s_t <= 0.0:
        return 100.0
    return 100.0 * min(1.0, s_h / max(s_t, EPS_SHARPE))


def _total(
    s_def_v: float,
    s_str_v: float,
    s_res_v: float,
    s_gen_v: float | None,
    cfg: Mapping[str, Any] | None = None,
) -> float:
    c = _cfg(cfg)
    w_def = float(c["w_def"])
    w_str = float(c["w_str"])
    w_res = float(c["w_res"])
    w_gen = float(c["w_gen"])
    core = w_def * s_def_v + w_str * s_str_v + w_res * s_res_v
    if s_gen_v is None:
        den = w_def + w_str + w_res
        if den <= 0.0:
            return 0.0
        return core / den
    return core + w_gen * s_gen_v


def score_cell(
    book: Mapping[str, Any] | None,
    *,
    space_on: bool,
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    src: Mapping[str, Any] = book if isinstance(book, Mapping) else {}
    used = fill_score(cfg)
    def_v = s_def(src, space_on=space_on, cfg=used)
    str_v = s_str(src, used)
    res_v = s_res(src, used)
    gen_v = s_gen(src, space_on=space_on)
    return {
        "s_def": _round4(def_v),
        "s_str": _round4(str_v),
        "s_res": _round4(res_v),
        "s_gen": _round4(gen_v),
        "total": _round4(_total(def_v, str_v, res_v, gen_v, used)),
        "scored": _book_scored(src),
    }


def score_for_json(score: Mapping[str, Any]) -> dict[str, Any]:
    gen = score.get("s_gen")
    return {
        "s_def": _round4(_num(score.get("s_def")) or 0.0),
        "s_str": _round4(_num(score.get("s_str")) or 0.0),
        "s_res": _round4(_num(score.get("s_res")) or 0.0),
        "s_gen": None if gen is None else _round4(_num(gen) or 0.0),
        "total": _round4(_num(score.get("total")) or 0.0),
        "scored": bool(score.get("scored")),
    }
