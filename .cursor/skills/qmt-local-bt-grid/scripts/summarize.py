# coding: utf-8
"""解析 local_bt 网格各格 log → 合计 / 调参期 / 验收期 / 稳健推荐 JSON。

用法（仓库根目录）::

  python .cursor/skills/qmt-local-bt-grid/scripts/summarize.py --sweep-dir hongli_band/report/grid/stop_loss_confirm
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
LOCAL_BT = REPO / "hongli_band" / "scripts" / "local_bt"

if str(LOCAL_BT) not in sys.path:
    sys.path.insert(0, str(LOCAL_BT))

from local_bt_log import (  # noqa: E402
    BUDGET,
    _max_dd,
    _year_of,
    parse_local_bt_log,
    parse_trade_budget,
)
from equity_yearly import (  # noqa: E402
    build_daily_equity,
    sharpe_from_returns,
    simple_returns,
    year_equity_path,
    year_performance_table,
)
from grid_spec import (  # noqa: E402
    YEAR_WINDOW_KEYS,
    fill_year_windows,
    year_range_set,
)

SAMPLES = ("book", "sma", "ema")
RE_LOG = re.compile(
    r"^local_bt_(\d{6})_(SZ|SH)_(\d{4})_(SMA|EMA)\.txt$",
    re.I,
)
EPS_PNL = 1.0


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(x) for x in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _job_year(t: dict[str, Any]) -> int | None:
    raw = str(t.get("year") or "").strip()
    if len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return _year_of(
        str(t.get("sell_exec_day") or t.get("buy_open_day") or "")
    )


def _empty_window() -> dict[str, Any]:
    return {
        "sharpe": None,
        "n_open": 0,
        "avg_ann_pct": None,
        "avg_year_pnl": None,
    }


def _agg_window(year_rows: list[dict[str, Any]], years: set[int]) -> dict[str, Any]:
    rows = [r for r in year_rows if int(r["year"]) in years]
    if not rows:
        return _empty_window()
    n_open = sum(int(r.get("n_open") or 0) for r in rows)
    anns = [
        float(r["year_ret_pct"])
        for r in rows
        if r.get("year_ret_pct") is not None
    ]
    pnls = [
        float(r["year_pnl"])
        for r in rows
        if r.get("year_pnl") is not None
    ]
    rets: list[float] = []
    for r in rows:
        rets.extend(float(x) for x in (r.get("returns") or []))
    return {
        "sharpe": sharpe_from_returns(rets) if rets else None,
        "n_open": n_open,
        "avg_ann_pct": round(sum(anns) / len(anns), 4) if anns else None,
        "avg_year_pnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
    }


def _job_year_rows(
    trades: list[dict[str, Any]],
    n_accounts_by_year: dict[int, int],
    per_budget: float,
) -> list[dict[str, Any]]:
    """每年独立空仓；只保留任务年那一行（跨年卖出不另开邻年行）。"""
    by_job: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        y = _job_year(t)
        if y is not None:
            by_job[y].append(t)
    years = set(n_accounts_by_year) | set(by_job)
    rows: list[dict[str, Any]] = []
    bud_one = float(per_budget)
    for y in sorted(years):
        trades_y = by_job.get(y) or []
        n_acc = int(n_accounts_by_year.get(y) or 0)
        if n_acc <= 0:
            n_acc = 1 if trades_y else 0
        if n_acc <= 0:
            continue
        bud_y = float(n_acc) * bud_one
        tbl = year_performance_table(trades_y, bud_y)
        if tbl is None or tbl.empty:
            continue
        match = tbl.loc[tbl["year"].astype(str) == str(y)]
        if match.empty:
            continue
        rec = match.iloc[0]
        daily = build_daily_equity(trades_y, bud_y)
        path = year_equity_path(daily, y, bud_y)
        rets = simple_returns(path)
        rows.append(
            {
                "year": int(y),
                "n_open": int(rec["n_open"] or 0),
                "year_ret_pct": None
                if rec["year_ret_pct"] is None or rec["year_ret_pct"] != rec["year_ret_pct"]
                else float(rec["year_ret_pct"]),
                "year_pnl": float(rec["year_pnl"]),
                "returns": [float(x) for x in rets.tolist()],
            }
        )
    return rows


def stats_from_trades(
    trades: list[dict[str, Any]],
    n_accounts_by_year: dict[int, int],
    *,
    tune_years: set[int] | None = None,
    check_years: set[int] | None = None,
    run_years: set[int] | None = None,
    per_budget: float | None = None,
) -> dict[str, Any]:
    pnls = [float(t["pnl"]) for t in trades]
    n = len(pnls)
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    pf = (gp / gl) if gl > 1e-12 else (99.0 if gp > 0 else None)
    wins = sum(1 for p in pnls if p > 0)
    by_year: dict[int, float] = defaultdict(float)
    by_sig: dict[str, int] = defaultdict(int)
    day_pnls: list[tuple[str, float]] = []
    for t in trades:
        sig = str(t.get("sell_signal") or "-")
        by_sig[sig] += 1
        day = str(t.get("sell_exec_day") or t.get("year") or "")
        y = _year_of(day)
        pnl = float(t["pnl"])
        if y is not None:
            by_year[y] += pnl
        day_pnls.append((day, pnl))
    win = fill_year_windows(None)
    tune = set(tune_years) if tune_years is not None else year_range_set(
        win["tune_start"], win["tune_end"]
    )
    check = set(check_years) if check_years is not None else year_range_set(
        win["check_start"], win["check_end"]
    )
    run = set(run_years) if run_years is not None else year_range_set(
        win["year_start"], win["year_end"]
    )
    is_pnl = sum(by_year[y] for y in by_year if y in tune)
    oos_pnl = sum(by_year[y] for y in by_year if y in check)
    n_acc = max(n_accounts_by_year.values()) if n_accounts_by_year else 0
    budget = float(BUDGET if per_budget is None else per_budget)
    year_rows = _job_year_rows(trades, n_accounts_by_year, budget)
    return {
        "n_trades": n,
        "sum_pnl": round(sum(pnls), 2),
        "win_rate": round(100.0 * wins / n, 2) if n else None,
        "profit_factor": None if pf is None else round(float(pf), 3),
        "is_pnl": round(is_pnl, 2),
        "oos_pnl": round(oos_pnl, 2),
        "max_dd": _max_dd(day_pnls, n_acc),
        "sell": dict(by_sig),
        "n_trail": int(by_sig.get("trail_stop", 0)),
        "n_stop": int(by_sig.get("stop_loss", 0)),
        "n_weekly": int(by_sig.get("weekly_bear", 0)),
        "n_time": int(by_sig.get("time_force", 0)),
        "by_year": {str(y): round(by_year[y], 2) for y in sorted(by_year)},
        "n_accounts_by_year": {str(y): int(n_accounts_by_year[y]) for y in sorted(n_accounts_by_year)},
        "per_budget": budget,
        "windows": {
            "all": _agg_window(year_rows, run),
            "tune": _agg_window(year_rows, tune),
            "check": _agg_window(year_rows, check),
        },
    }


def _empty_stats() -> dict[str, Any]:
    return stats_from_trades([], {})


def _delta_stats(cell: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    keys = ("sum_pnl", "is_pnl", "oos_pnl", "profit_factor", "win_rate", "max_dd")
    out: dict[str, Any] = {}
    for k in keys:
        a = cell.get(k)
        b = base.get(k)
        if a is None or b is None:
            out[k] = None
        else:
            out[k] = round(float(a) - float(b), 4 if k in ("profit_factor", "win_rate", "max_dd") else 2)
    return out


def parse_logs(log_paths: list[Path]) -> tuple[list[dict[str, Any]], dict[int, int], int, int, float]:
    trades: list[dict[str, Any]] = []
    n_accounts: dict[int, int] = defaultdict(int)
    n_ok = 0
    n_fail = 0
    seen_acc: set[tuple[int, str]] = set()
    per_budget: float | None = None
    for path in log_paths:
        try:
            _banner, raw = parse_local_bt_log(path)
        except Exception:
            n_fail += 1
            continue
        n_ok += 1
        bud = parse_trade_budget(path, default=0.0)
        if per_budget is None and bud > 0:
            per_budget = bud
        m = RE_LOG.match(path.name)
        stock = ""
        year = ""
        ma = ""
        if m:
            stock = "%s.%s" % (m.group(1), m.group(2).upper())
            year = m.group(3)
            ma = m.group(4).upper()
        y_acc = int(year) if year.isdigit() else None
        if y_acc is not None:
            key = (y_acc, stock or path.name)
            if key not in seen_acc:
                seen_acc.add(key)
                n_accounts[y_acc] += 1
        for t in raw:
            row = dict(t)
            row["stock"] = stock
            row["year"] = year
            row["ma"] = ma
            trades.append(row)
    return trades, dict(n_accounts), n_ok, n_fail, float(per_budget or BUDGET)


def _list_logs(sample_dir: Path) -> list[Path]:
    if not sample_dir.is_dir():
        return []
    return sorted(p for p in sample_dir.rglob("local_bt_*.txt") if p.is_file())


def _load_cell_meta(cell_dir: Path) -> dict[str, Any]:
    meta_p = cell_dir / "cell_meta.json"
    if meta_p.is_file():
        return json.loads(meta_p.read_text(encoding="utf-8"))
    return {"id": cell_dir.name, "label": cell_dir.name, "kind": "other", "overrides": {}}


def summarize_cell(
    cell_dir: Path,
    *,
    tune_years: set[int] | None = None,
    check_years: set[int] | None = None,
    run_years: set[int] | None = None,
) -> dict[str, Any]:
    meta = _load_cell_meta(cell_dir)
    samples: dict[str, Any] = {}
    for name in SAMPLES:
        logs = _list_logs(cell_dir / name)
        trades, n_acc, n_ok, n_fail, per_budget = parse_logs(logs)
        st = stats_from_trades(
            trades,
            n_acc,
            tune_years=tune_years,
            check_years=check_years,
            run_years=run_years,
            per_budget=per_budget,
        )
        st["n_logs_ok"] = n_ok
        st["n_logs_fail"] = n_fail
        samples[name] = st
    return {
        "id": str(meta.get("id") or cell_dir.name),
        "label": str(meta.get("label") or cell_dir.name),
        "kind": str(meta.get("kind") or "other"),
        "overrides": meta.get("overrides") or {},
        "samples": samples,
    }


def _sign(val: float | None, eps: float = EPS_PNL) -> int:
    if val is None:
        return 0
    x = float(val)
    if abs(x) < eps:
        return 0
    return 1 if x > 0 else -1


def _n_override_keys(overrides: Any) -> int:
    if not isinstance(overrides, dict):
        return 0
    return len(overrides)


def pick_recommend(cells: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {c["id"]: c for c in cells}
    base = by_id.get("base")
    if base is None:
        return {"id": None, "reason": "缺少 base 格，无法选参"}

    def sample(cell: dict[str, Any], name: str) -> dict[str, Any]:
        return (cell.get("samples") or {}).get(name) or {}

    bb = sample(base, "book")
    passers: list[tuple[dict[str, Any], float, int]] = []
    notes: list[dict[str, Any]] = []

    for cell in cells:
        if cell["id"] == "base":
            continue
        b = sample(cell, "book")
        d_oos = float(b.get("oos_pnl") or 0) - float(bb.get("oos_pnl") or 0)
        d_is = float(b.get("is_pnl") or 0) - float(bb.get("is_pnl") or 0)
        fail = ""
        if _sign(d_oos) * _sign(d_is) < 0:
            fail = "调参期与验收期不同向"
        elif d_oos <= 0:
            fail = "验收期未优于现行"
        row = {
            "id": cell["id"],
            "kind": cell.get("kind"),
            "d_oos": round(d_oos, 2),
            "d_is": round(d_is, 2),
            "fail": fail or None,
        }
        notes.append(row)
        if not fail:
            passers.append((cell, d_oos, _n_override_keys(cell.get("overrides"))))

    by_kind: dict[str, Any] = {}
    for kind in ("tighten", "loosen", "off", "other"):
        opts = [n for n in notes if n.get("kind") == kind]
        if not opts:
            continue
        best = max(opts, key=lambda x: x["d_oos"])
        by_kind[kind] = best

    if not passers:
        return {
            "id": "base",
            "label": base.get("label") or "base",
            "kind": "base",
            "reason": "验收期未优于现行或与调参期不同向，维持现行",
            "candidates": notes,
            "by_kind": by_kind,
        }

    best_oos = max(p[1] for p in passers)
    pad = max(500.0, 0.2 * abs(best_oos))
    close = [p for p in passers if p[1] >= best_oos - pad]
    close.sort(key=lambda p: (p[2], -p[1]))
    picked = close[0][0]
    return {
        "id": picked["id"],
        "label": picked.get("label") or picked["id"],
        "kind": picked.get("kind"),
        "reason": "以验收期为主且与调参期同向；接近则少改结构",
        "candidates": notes,
        "by_kind": by_kind,
    }


def attach_deltas(cells: list[dict[str, Any]]) -> None:
    by_id = {c["id"]: c for c in cells}
    base = by_id.get("base")
    if base is None:
        return
    for cell in cells:
        deltas: dict[str, Any] = {}
        for name in SAMPLES:
            deltas[name] = _delta_stats(
                (cell.get("samples") or {}).get(name) or {},
                (base.get("samples") or {}).get(name) or {},
            )
        cell["delta_vs_base"] = deltas


def _load_sweep_windows(root: Path) -> dict[str, int]:
    for name in ("spec.json", "freeze.json"):
        path = root / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return fill_year_windows(data)
    return fill_year_windows(None)


def summarize_sweep(sweep_dir: str | Path) -> dict[str, Any]:
    root = Path(sweep_dir)
    if not root.is_dir():
        raise FileNotFoundError("sweep dir not found: %s" % root)
    win = _load_sweep_windows(root)
    tune = year_range_set(win["tune_start"], win["tune_end"])
    check = year_range_set(win["check_start"], win["check_end"])
    run = year_range_set(win["year_start"], win["year_end"])
    cells: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "cell_meta.json").is_file() and not any(
            (child / s).is_dir() for s in SAMPLES
        ):
            continue
        cells.append(
            summarize_cell(
                child, tune_years=tune, check_years=check, run_years=run
            )
        )
    attach_deltas(cells)
    rec = pick_recommend(cells)
    spec = {}
    spec_p = root / "spec.json"
    if spec_p.is_file():
        try:
            spec = json.loads(spec_p.read_text(encoding="utf-8"))
        except Exception:
            spec = {}
    out = {
        "sweep": str(spec.get("sweep") or root.name),
        "sweep_dir": str(root),
        "n_cells": len(cells),
        "cells": cells,
        "recommend": rec,
        "note": "MAE 反事实不得写入推荐；默认不改 config / 不 deploy",
    }
    for key in YEAR_WINDOW_KEYS:
        out[key] = int(win[key])
    out_p = root / "summary.json"
    out_p.write_text(
        json.dumps(_json_ready(out), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    out["summary_path"] = str(out_p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="local_bt 网格 summarize")
    ap.add_argument("--sweep-dir", required=True, help="report/grid/<sweep> 目录")
    args = ap.parse_args()
    out = summarize_sweep(args.sweep_dir)
    rec = out.get("recommend") or {}
    print("wrote", out.get("summary_path"))
    print("recommend", rec.get("id"), rec.get("reason"))


if __name__ == "__main__":
    main()
