# coding: utf-8
"""实盘评估过门：硬门 / 软门 / 整次 aggregate 裁决。"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Mapping, Sequence

EPS = 1e-6

HARD_KEYS = ("calmar", "max_dd", "oos_sharpe", "profit_factor")
SOFT_KEYS = ("win_rate", "n_trades")


def _as_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return bool(raw)
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return bool(default)


def _as_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _as_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def default_gate() -> dict[str, Any]:
    return {
        "hard": {
            "calmar": {"enabled": True, "min": 1.2},
            "max_dd": {"enabled": True, "floor": -0.12},
            "oos_sharpe": {"enabled": True, "min": 0.7},
            "profit_factor": {"enabled": True, "min": 1.4},
        },
        "soft": {
            "win_rate": {"enabled": True, "veto": False, "min": 42.0},
            "n_trades": {
                "enabled": True,
                "veto": False,
                "min": 1,
                "max": None,
                "per_stock_year_min": 0.5,
            },
        },
        "aggregate": {
            "pass_rate_min": 0.70,
            "median_calmar_min": 1.2,
            "tail_max_dd_floor": -0.15,
        },
    }


def _fill_hard(src: Mapping[str, Any] | None) -> dict[str, Any]:
    base = default_gate()["hard"]
    raw = src if isinstance(src, Mapping) else {}
    # allow flat {calmar: ...} at gate root
    if "hard" in raw and isinstance(raw.get("hard"), Mapping):
        raw = raw["hard"]  # type: ignore[assignment]
    out: dict[str, Any] = {}
    for key in HARD_KEYS:
        rule = dict(base[key])
        rs = raw.get(key)
        if isinstance(rs, Mapping):
            rule["enabled"] = _as_bool(rs.get("enabled"), rule["enabled"])
            if key == "max_dd":
                if "floor" in rs:
                    rule["floor"] = _as_float(rs.get("floor"), rule["floor"])
                elif "pct" in rs:
                    rule["floor"] = -abs(_as_float(rs.get("pct"), 12.0)) / 100.0
            else:
                rule["min"] = _as_float(rs.get("min"), rule["min"])
        out[key] = rule
    return out


def _fill_soft(src: Mapping[str, Any] | None) -> dict[str, Any]:
    base = default_gate()["soft"]
    raw = src if isinstance(src, Mapping) else {}
    if "soft" in raw and isinstance(raw.get("soft"), Mapping):
        raw = raw["soft"]  # type: ignore[assignment]
    out: dict[str, Any] = {}
    for key in SOFT_KEYS:
        rule = dict(base[key])
        rs = raw.get(key)
        if isinstance(rs, Mapping):
            rule["enabled"] = _as_bool(rs.get("enabled"), rule["enabled"])
            rule["veto"] = _as_bool(rs.get("veto"), rule.get("veto", False))
            if key == "win_rate":
                rule["min"] = _as_float(rs.get("min"), rule["min"])
            else:
                rule["min"] = _as_int(rs.get("min"), rule["min"])
                if "max" in rs:
                    mv = rs.get("max")
                    rule["max"] = None if mv is None or str(mv).strip() == "" else _as_int(mv, 0)
                if "per_stock_year_min" in rs:
                    rule["per_stock_year_min"] = _as_float(
                        rs.get("per_stock_year_min"), rule.get("per_stock_year_min", 0.0)
                    )
        out[key] = rule
    return out


def _fill_aggregate(src: Mapping[str, Any] | None) -> dict[str, Any]:
    base = default_gate()["aggregate"]
    raw = src if isinstance(src, Mapping) else {}
    if "aggregate" in raw and isinstance(raw.get("aggregate"), Mapping):
        raw = raw["aggregate"]  # type: ignore[assignment]
    out = dict(base)
    if "pass_rate_min" in raw:
        out["pass_rate_min"] = _as_float(raw.get("pass_rate_min"), out["pass_rate_min"])
    if "median_calmar_min" in raw:
        out["median_calmar_min"] = _as_float(raw.get("median_calmar_min"), out["median_calmar_min"])
    if "tail_max_dd_floor" in raw:
        out["tail_max_dd_floor"] = _as_float(raw.get("tail_max_dd_floor"), out["tail_max_dd_floor"])
    elif "tail_max_dd_pct" in raw:
        out["tail_max_dd_floor"] = -abs(_as_float(raw.get("tail_max_dd_pct"), 15.0)) / 100.0
    return out


def fill_gate(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    src = raw if isinstance(raw, Mapping) else {}
    if "gate" in src and isinstance(src.get("gate"), Mapping) and "hard" not in src and "calmar" not in src:
        src = src["gate"]  # type: ignore[assignment]
    # nested hard/soft or flat hard keys at root
    hard_src = src.get("hard") if isinstance(src.get("hard"), Mapping) else src
    soft_src = src.get("soft") if isinstance(src.get("soft"), Mapping) else src
    agg_src = src.get("aggregate") if isinstance(src.get("aggregate"), Mapping) else src
    return {
        "hard": _fill_hard(hard_src if isinstance(hard_src, Mapping) else None),
        "soft": _fill_soft(soft_src if isinstance(soft_src, Mapping) else None),
        "aggregate": _fill_aggregate(agg_src if isinstance(agg_src, Mapping) else None),
    }


def validate_gate(gate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    filled = fill_gate(gate)
    h = filled["hard"]
    if h["calmar"]["min"] < 0:
        raise ValueError("gate.hard.calmar.min 不能为负")
    if h["max_dd"]["floor"] > 0:
        raise ValueError("gate.hard.max_dd.floor 应为 ≤0")
    if h["oos_sharpe"]["min"] < 0:
        raise ValueError("gate.hard.oos_sharpe.min 不能为负")
    if h["profit_factor"]["min"] < 0:
        raise ValueError("gate.hard.profit_factor.min 不能为负")
    s = filled["soft"]
    if s["win_rate"]["min"] < 0 or s["win_rate"]["min"] > 100:
        raise ValueError("gate.soft.win_rate.min 应在 0–100")
    if s["n_trades"]["min"] < 0:
        raise ValueError("gate.soft.n_trades.min 不能为负")
    mx = s["n_trades"].get("max")
    if mx is not None and int(mx) < int(s["n_trades"]["min"]):
        raise ValueError("gate.soft.n_trades.max 须 ≥ min")
    a = filled["aggregate"]
    if not (0.0 <= float(a["pass_rate_min"]) <= 1.0):
        raise ValueError("gate.aggregate.pass_rate_min 应在 0–1")
    if float(a["tail_max_dd_floor"]) > 0:
        raise ValueError("gate.aggregate.tail_max_dd_floor 应为 ≤0")
    return filled


def gate_for_json(gate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return deepcopy(fill_gate(gate))


def _miss(tag: str, name: str) -> str:
    return "%s缺%s" % (tag, name)


def eval_hard(kpi: Mapping[str, Any] | None, hard: Mapping[str, Any], *, prefix: str = "") -> list[str]:
    w = kpi if isinstance(kpi, Mapping) else {}
    fails: list[str] = []
    tag = prefix or ""

    if hard["calmar"].get("enabled"):
        v = w.get("calmar")
        if v is None:
            fails.append(_miss(tag, "卡玛"))
        elif float(v) + EPS < float(hard["calmar"]["min"]):
            fails.append("%s卡玛未达线" % tag)

    if hard["max_dd"].get("enabled"):
        v = w.get("max_dd")
        if v is None:
            fails.append(_miss(tag, "回撤"))
        elif float(v) < float(hard["max_dd"]["floor"]) - EPS:
            fails.append("%s回撤超限" % tag)

    if hard["oos_sharpe"].get("enabled"):
        v = w.get("oos_sharpe")
        if v is None:
            v = w.get("sharpe")
        if v is None:
            fails.append(_miss(tag, "夏普"))
        elif float(v) + EPS < float(hard["oos_sharpe"]["min"]):
            fails.append("%s夏普未达线" % tag)

    if hard["profit_factor"].get("enabled"):
        v = w.get("profit_factor")
        if v is None:
            fails.append(_miss(tag, "盈亏比"))
        elif float(v) + EPS < float(hard["profit_factor"]["min"]):
            fails.append("%s盈亏比未达线" % tag)
    return fails


def eval_soft(
    kpi: Mapping[str, Any] | None,
    soft: Mapping[str, Any],
    *,
    basket_size: int = 1,
    n_years: int = 1,
    prefix: str = "",
) -> tuple[list[str], list[str]]:
    """返回 (fails_if_veto, warns)。"""
    w = kpi if isinstance(kpi, Mapping) else {}
    fails: list[str] = []
    warns: list[str] = []
    tag = prefix or ""

    def _push(rule: Mapping[str, Any], msg: str) -> None:
        if rule.get("veto"):
            fails.append(msg)
        else:
            warns.append(msg)

    wr = soft.get("win_rate") or {}
    if wr.get("enabled"):
        v = w.get("win_rate")
        if v is None:
            _push(wr, _miss(tag, "胜率"))
        elif float(v) + EPS < float(wr["min"]):
            _push(wr, "%s胜率未达线" % tag)

    nt = soft.get("n_trades") or {}
    if nt.get("enabled"):
        n = w.get("n_trades")
        if n is None:
            _push(nt, _miss(tag, "笔数"))
        else:
            n_i = int(n)
            floor = int(nt.get("min") or 0)
            psy = float(nt.get("per_stock_year_min") or 0.0)
            if psy > 0 and basket_size > 0 and n_years > 0:
                floor = max(floor, int(math.ceil(psy * basket_size * n_years - EPS)))
            if n_i < floor:
                _push(nt, "%s笔数不足" % tag)
            mx = nt.get("max")
            if mx is not None and n_i > int(mx):
                _push(nt, "%s笔数过多" % tag)
    return fails, warns


def eval_basket(
    kpi: Mapping[str, Any] | None,
    gate: Mapping[str, Any] | None,
    *,
    basket_size: int = 1,
    n_years: int = 1,
    prefix: str = "验收窗",
) -> dict[str, Any]:
    g = validate_gate(gate)
    hard_fails = eval_hard(kpi, g["hard"], prefix=prefix)
    soft_fails, warns = eval_soft(
        kpi, g["soft"], basket_size=basket_size, n_years=n_years, prefix=prefix
    )
    fails = hard_fails + soft_fails
    return {
        "pass": not fails,
        "fails": fails or None,
        "warns": warns or None,
        "fail": "；".join(fails) if fails else None,
        "warn": "；".join(warns) if warns else None,
    }


def _median(vals: Sequence[float]) -> float | None:
    xs = sorted(float(x) for x in vals)
    if not xs:
        return None
    mid = len(xs) // 2
    if len(xs) % 2:
        return xs[mid]
    return 0.5 * (xs[mid - 1] + xs[mid])


def _percentile(vals: Sequence[float], p: float) -> float | None:
    xs = sorted(float(x) for x in vals)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    p = min(max(float(p), 0.0), 1.0)
    idx = p * (len(xs) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(xs) - 1)
    frac = idx - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def eval_run(
    baskets: Sequence[Mapping[str, Any]],
    gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """baskets: 每项含 pass + deploy KPI（calmar/max_dd/...）。"""
    g = validate_gate(gate)
    agg = g["aggregate"]
    rows = list(baskets or [])
    n = len(rows)
    n_pass = sum(1 for r in rows if r.get("pass"))
    pass_rate = (float(n_pass) / float(n)) if n else 0.0
    calmars = [float(r["calmar"]) for r in rows if r.get("calmar") is not None]
    dds = [float(r["max_dd"]) for r in rows if r.get("max_dd") is not None]
    med_calmar = _median(calmars)
    p10_dd = _percentile(dds, 0.10)

    reasons: list[str] = []
    ok_rate = pass_rate + EPS >= float(agg["pass_rate_min"])
    if not ok_rate:
        reasons.append(
            "通过率 %.0f%% < %.0f%%" % (100.0 * pass_rate, 100.0 * float(agg["pass_rate_min"]))
        )
    ok_calmar = med_calmar is not None and med_calmar + EPS >= float(agg["median_calmar_min"])
    if med_calmar is None:
        reasons.append("缺中位卡玛")
    elif not ok_calmar:
        reasons.append("中位卡玛未达线")
    ok_tail = p10_dd is not None and p10_dd + EPS >= float(agg["tail_max_dd_floor"])
    if p10_dd is None:
        reasons.append("缺尾部回撤")
    elif not ok_tail:
        reasons.append("尾部回撤超限")

    go = bool(n > 0 and ok_rate and ok_calmar and ok_tail)
    return {
        "verdict": "GO" if go else "NO-GO",
        "go": go,
        "n_baskets": n,
        "n_pass": n_pass,
        "pass_rate": round(pass_rate, 4),
        "median_calmar": None if med_calmar is None else round(med_calmar, 4),
        "p10_max_dd": None if p10_dd is None else round(p10_dd, 6),
        "reasons": reasons or None,
        "reason": "；".join(reasons) if reasons else ("通过" if go else "未通过"),
        "gate": gate_for_json(g),
    }
