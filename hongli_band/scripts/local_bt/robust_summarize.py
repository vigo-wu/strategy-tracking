# coding: utf-8
"""实盘评估汇总：窗内组合 KPI + 硬软门 + GO/NO-GO。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from analyze import load_detail_raw, sibling_log_path
from equity_yearly import build_daily_equity, sharpe_from_returns
from grid_spec import year_range_set
from market_csv import compact_day
from robust_gate import eval_basket, eval_run, gate_for_json, validate_gate
from robust_spec import fill_year_windows, load_spec


def _year_of_day(day: str) -> int | None:
    d = compact_day(str(day or ""))
    if len(d) >= 4 and d[:4].isdigit():
        return int(d[:4])
    return None


def trades_from_detail(detail_path: Path) -> list[dict[str, Any]]:
    """操作明细 → [{sell_exec_day, pnl, ...}] 仅卖出。"""
    if not detail_path.is_file():
        return []
    try:
        df = load_detail_raw(detail_path)
    except Exception:
        return []
    if df is None or df.empty:
        return []
    side_col = None
    for name in ("操作类型", "买卖方向", "方向"):
        if name in df.columns:
            side_col = name
            break
    time_col = "操作时间" if "操作时间" in df.columns else None
    pnl_col = "盈利" if "盈利" in df.columns else None
    eq_col = "组合权益" if "组合权益" in df.columns else None
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        side = str(row.get(side_col) or "") if side_col else ""
        if "卖" not in side and "SELL" not in side.upper():
            continue
        when = str(row.get(time_col) or "") if time_col else ""
        day = compact_day(when[:10] if when else "")
        if len(day) != 8:
            day = compact_day(when)
        try:
            pnl = float(row.get(pnl_col) or 0.0) if pnl_col else 0.0
        except (TypeError, ValueError):
            pnl = 0.0
        eq = None
        if eq_col is not None:
            try:
                eq = float(row.get(eq_col))
            except (TypeError, ValueError):
                eq = None
        out.append({"sell_exec_day": day, "pnl": pnl, "equity": eq})
    return out


def _empty_window() -> dict[str, Any]:
    return {
        "n_trades": 0,
        "win_rate": None,
        "profit_factor": None,
        "max_dd": None,
        "oos_sharpe": None,
        "sharpe": None,
        "calmar": None,
        "avg_ann_pct": None,
        "sum_pnl": None,
    }


def _calmar(avg_ann_pct: float | None, max_dd: float | None) -> float | None:
    if avg_ann_pct is None or max_dd is None:
        return None
    try:
        ann = float(avg_ann_pct) / 100.0
        dd = float(max_dd)
    except (TypeError, ValueError):
        return None
    if dd >= -1e-12:
        return None
    return round(ann / abs(dd), 6)


def _max_dd_from_equity(eq: pd.Series) -> float | None:
    if eq is None or len(eq) == 0:
        return None
    peak = eq.cummax()
    dd = (eq - peak) / peak.replace(0, pd.NA)
    try:
        v = float(dd.min())
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    return round(v, 6)


def window_kpi_from_trades(
    trades: Sequence[Mapping[str, Any]],
    years: set[int],
    *,
    budget: float = 100000.0,
) -> dict[str, Any]:
    """胜率/盈亏比/笔数：窗内平仓；回撤/夏普/卡玛：窗内权益路径。"""
    out = _empty_window()
    if not years:
        return out
    win_trades = []
    for t in trades:
        y = _year_of_day(str(t.get("sell_exec_day") or ""))
        if y is not None and int(y) in years:
            win_trades.append(t)
    n = len(win_trades)
    out["n_trades"] = n
    if n:
        pnls = [float(t.get("pnl") or 0.0) for t in win_trades]
        wins = sum(1 for p in pnls if p > 0)
        gp = sum(p for p in pnls if p > 0)
        gl = abs(sum(p for p in pnls if p < 0))
        out["win_rate"] = round(100.0 * wins / n, 2)
        if gl > 1e-12:
            out["profit_factor"] = round(gp / gl, 3)
        elif gp > 0:
            out["profit_factor"] = 99.0
        out["sum_pnl"] = round(sum(pnls), 2)

    # equity path: full trades for continuity, then slice window dates
    eq_df = build_daily_equity(list(trades), budget=float(budget))
    if eq_df is None or eq_df.empty:
        out["calmar"] = _calmar(out.get("avg_ann_pct"), out.get("max_dd"))
        return out
    mask = eq_df["date"].map(lambda d: int(pd.Timestamp(d).year) in years)
    sub = eq_df.loc[mask].copy()
    if sub.empty:
        return out
    out["max_dd"] = _max_dd_from_equity(sub["equity"])
    rets = sub["equity"].pct_change().dropna()
    sh = sharpe_from_returns(rets.tolist()) if len(rets) else None
    out["oos_sharpe"] = sh
    out["sharpe"] = sh
    # 年化：窗内首尾权益简单收益 / 年数
    eq0 = float(sub["equity"].iloc[0])
    eq1 = float(sub["equity"].iloc[-1])
    n_y = max(len(years), 1)
    if eq0 > 1e-12:
        total_ret = (eq1 / eq0) - 1.0
        # 几何年化近似
        try:
            ann = (1.0 + total_ret) ** (1.0 / float(n_y)) - 1.0
            out["avg_ann_pct"] = round(100.0 * ann, 4)
        except Exception:
            out["avg_ann_pct"] = round(100.0 * total_ret / float(n_y), 4)
    out["calmar"] = _calmar(out.get("avg_ann_pct"), out.get("max_dd"))
    return out


def summarize_basket_dir(
    basket_dir: Path,
    windows: Mapping[str, int],
    gate: Mapping[str, Any],
    *,
    basket_size: int,
    budget: float = 100000.0,
) -> dict[str, Any]:
    detail = None
    for p in sorted(basket_dir.glob("*_操作明细.csv")):
        detail = p
        break
    if detail is None:
        # alternate naming
        for p in sorted(basket_dir.glob("*.csv")):
            if "操作明细" in p.name:
                detail = p
                break
    trades = trades_from_detail(detail) if detail else []
    win = fill_year_windows(windows)
    blocks = {
        "tune": window_kpi_from_trades(
            trades, year_range_set(win["tune_start"], win["tune_end"]), budget=budget
        ),
        "check": window_kpi_from_trades(
            trades, year_range_set(win["check_start"], win["check_end"]), budget=budget
        ),
        "deploy": window_kpi_from_trades(
            trades, year_range_set(win["deploy_start"], win["deploy_end"]), budget=budget
        ),
    }
    n_years = len(year_range_set(win["deploy_start"], win["deploy_end"])) or 1
    judged = eval_basket(
        blocks["deploy"],
        gate,
        basket_size=basket_size,
        n_years=n_years,
        prefix="盲测",
    )
    return {
        "basket_dir": str(basket_dir),
        "detail": str(detail) if detail else None,
        "windows": blocks,
        "pass": judged["pass"],
        "fails": judged["fails"],
        "warns": judged["warns"],
        "fail": judged["fail"],
        "warn": judged["warn"],
        "calmar": blocks["deploy"].get("calmar"),
        "max_dd": blocks["deploy"].get("max_dd"),
        "oos_sharpe": blocks["deploy"].get("oos_sharpe"),
        "profit_factor": blocks["deploy"].get("profit_factor"),
        "win_rate": blocks["deploy"].get("win_rate"),
        "n_trades": blocks["deploy"].get("n_trades"),
    }


def summarize_run(
    root: str | Path,
    *,
    gate: Mapping[str, Any] | None = None,
    spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root_p = Path(root)
    if spec is None:
        for name in ("freeze.json", "spec.json"):
            p = root_p / name
            if p.is_file():
                try:
                    spec = json.loads(p.read_text(encoding="utf-8"))
                    break
                except Exception:
                    continue
    if not isinstance(spec, Mapping):
        raise ValueError("缺少 spec/freeze")
    # may already be loaded
    try:
        loaded = load_spec(spec) if "deploy_start" in spec or "gate" in spec else dict(spec)
    except Exception:
        loaded = dict(spec)
    g = validate_gate(gate if gate is not None else loaded.get("gate"))
    win = fill_year_windows(loaded)
    basket_size = int(loaded.get("basket_size") or 10)
    budget = 100000.0
    ov = loaded.get("overrides") if isinstance(loaded.get("overrides"), Mapping) else {}
    if "TRADE_BUDGET" in ov:
        try:
            budget = float(ov["TRADE_BUDGET"])
        except (TypeError, ValueError):
            pass

    baskets_meta = []
    freeze = root_p / "freeze.json"
    if freeze.is_file():
        try:
            fr = json.loads(freeze.read_text(encoding="utf-8"))
            baskets_meta = list((fr or {}).get("baskets") or [])
        except Exception:
            baskets_meta = []

    rows: list[dict[str, Any]] = []
    for child in sorted(root_p.iterdir()):
        if not child.is_dir() or not child.name.startswith("basket_"):
            continue
        row = summarize_basket_dir(child, win, g, basket_size=basket_size, budget=budget)
        row["id"] = child.name
        # attach stocks from freeze
        for bm in baskets_meta:
            if isinstance(bm, Mapping) and str(bm.get("id") or "") == child.name:
                row["stocks"] = bm.get("stocks")
                break
        rows.append(row)

    verdict = eval_run(rows, g)
    fail_counter: Counter[str] = Counter()
    warn_counter: Counter[str] = Counter()
    for r in rows:
        for msg in r.get("fails") or []:
            fail_counter[str(msg)] += 1
        for msg in r.get("warns") or []:
            warn_counter[str(msg)] += 1

    out = {
        "run_id": loaded.get("run_id"),
        "root": str(root_p),
        "windows": win,
        "gate": gate_for_json(g),
        "overrides_meta": loaded.get("_overrides_meta"),
        "verdict": verdict,
        "baskets": rows,
        "fail_counts": dict(fail_counter.most_common()),
        "warn_counts": dict(warn_counter.most_common()),
        "mean_jaccard": None,
    }
    if freeze.is_file():
        try:
            fr = json.loads(freeze.read_text(encoding="utf-8"))
            out["mean_jaccard"] = fr.get("mean_jaccard")
        except Exception:
            pass

    summary_path = root_p / "summary.json"
    summary_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    out["summary_path"] = str(summary_path)
    return out
