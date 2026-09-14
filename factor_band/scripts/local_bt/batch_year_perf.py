# coding: utf-8
"""批量结果：单票独立账户盈亏按年相加（数据分析「单票合计」口径）。

不跑组合回放。整段区间用一条连续权益；按年分段每年独立空仓。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from equity_yearly import year_performance_table
from market_csv import compact_day

GRID_SAMPLE_NAMES = ("book", "sma", "ema")
GRID_DETAIL_NAME_RE = re.compile(
    r"^local_bt_(\d{6})_(SZ|SH)_(\d{4})_(SMA|EMA)_操作明细\.csv$",
    re.IGNORECASE,
)


def _row_year(row: dict[str, Any]) -> str:
    y = str(row.get("year") or "").strip()
    if y:
        return y[:4] if len(y) >= 4 else y
    walk = compact_day(str(row.get("walk_start") or ""))
    return walk[:4] if len(walk) >= 4 else ""


def _per_budget(rows: list[dict[str, Any]]) -> float:
    for r in rows:
        try:
            b = float(r.get("budget") or 0)
        except (TypeError, ValueError):
            b = 0.0
        if b > 0:
            return b
    return 100000.0


def _detail_mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        return 0


def parse_detail_trades(path: str | Path, cache: dict | None = None) -> list[dict[str, Any]]:
    """parse_terminal_rounds + 规范化；按 (路径, mtime) 缓存。"""
    p = Path(path)
    if not p.is_file():
        return []
    key = (str(p.resolve()), _detail_mtime(p))
    if cache is not None and key in cache:
        return list(cache[key])
    from analyze import _normalize_trades, report_mod  # noqa: WPS433

    rounds = report_mod().parse_terminal_rounds(p, quiet=True)
    trades = _normalize_trades(rounds)
    if cache is not None:
        stale = [k for k in cache if k[0] == key[0] and k != key]
        for k in stale:
            cache.pop(k, None)
        cache[key] = list(trades)
    return trades


def _sum_trade_pnl(trades: list[dict[str, Any]]) -> float:
    total = 0.0
    for t in trades:
        try:
            total += float(t.get("pnl") or 0)
        except (TypeError, ValueError):
            continue
    return total


def collect_batch_detail_trades(
    rows: list[dict[str, Any]],
    cache: dict | None = None,
) -> list[dict[str, Any]]:
    """成功且有明细的行 → {row 字段 + trades}。缺文件跳过。"""
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not r.get("ok"):
            continue
        detail = str(r.get("detail") or "").strip()
        if not detail:
            continue
        p = Path(detail)
        if not p.is_file():
            continue
        packed = dict(r)
        packed["trades"] = parse_detail_trades(p, cache=cache)
        if "sum_pnl" not in r:
            packed["sum_pnl"] = _sum_trade_pnl(packed["trades"])
        out.append(packed)
    return out


def _iter_grid_sample_details(cell_dir: str | Path, sample: str) -> list[Path]:
    root = Path(cell_dir) / str(sample)
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*_操作明细.csv") if p.is_file())


def list_grid_samples_with_details(cell_dir: str | Path) -> list[str]:
    """该格目录下实际有操作明细的 sample 名，顺序 book / sma / ema。"""
    root = Path(cell_dir)
    return [name for name in GRID_SAMPLE_NAMES if _iter_grid_sample_details(root, name)]


def _div_from_detail_path(path: Path) -> str:
    from analyze import normalize_dividend_type  # noqa: WPS433

    for part in reversed(path.parts[:-1]):
        d = normalize_dividend_type(part)
        if d:
            return d
    return str(path.parent.name or "")


def rows_from_grid_sample_dir(
    cell_dir: str | Path,
    sample: str,
    *,
    fallback_budget: float = 100000.0,
) -> list[dict[str, Any]]:
    """扫一格下一个 sample：ok / year / detail / stock / ma_type / dividend_type / budget。"""
    from analyze import parse_budget_from_log, sibling_log_path  # noqa: WPS433

    try:
        fb = float(fallback_budget)
    except (TypeError, ValueError):
        fb = 100000.0
    if fb <= 0:
        fb = 100000.0
    rows: list[dict[str, Any]] = []
    for path in _iter_grid_sample_details(cell_dir, sample):
        m = GRID_DETAIL_NAME_RE.match(path.name)
        if not m:
            continue
        code, ex, year, ma = m.group(1), m.group(2).upper(), m.group(3), m.group(4).upper()
        log = sibling_log_path(path)
        budget = parse_budget_from_log(log, default=fb) if log else fb
        rows.append(
            {
                "ok": True,
                "year": year,
                "detail": str(path),
                "stock": "%s.%s" % (code, ex),
                "ma_type": ma,
                "dividend_type": _div_from_detail_path(path),
                "budget": float(budget),
            }
        )
    return rows


def _is_holdout_path(path: Path) -> bool:
    return "holdout" in [str(p).lower() for p in path.parts] or path.name.lower().startswith(
        "holdout_"
    )


def portfolio_year_perf_from_grid_sample(
    cell_dir: str | Path,
    sample: str,
    *,
    fallback_budget: float = 100000.0,
    cache: dict | None = None,
) -> dict[str, Any]:
    """组合 walk 明细 → 连续账户分年绩效（非多票独立账户加总）。"""
    from analyze import parse_budget_from_log, sibling_log_path  # noqa: WPS433

    empty = {
        "ok": False,
        "reason": "该格无操作明细",
        "table": pd.DataFrame(),
        "trades": [],
        "trades_by_year": {},
        "budget": 0.0,
        "budget_by_year": {},
        "n_ok": 0,
        "n_buy": 0,
        "sum_pnl": 0.0,
        "pos_ratio": None,
        "split": "range",
    }
    try:
        fb = float(fallback_budget)
    except (TypeError, ValueError):
        fb = 100000.0
    if fb <= 0:
        fb = 100000.0
    details = [
        p for p in _iter_grid_sample_details(cell_dir, sample) if not _is_holdout_path(p)
    ]
    if not details:
        return empty
    trades: list[dict[str, Any]] = []
    budget = fb
    for path in details:
        trades.extend(parse_detail_trades(path, cache=cache))
        log = sibling_log_path(path)
        if log:
            budget = parse_budget_from_log(log, default=budget)
    if not trades:
        empty["reason"] = "无成交轮次，无法按年汇总。"
        empty["n_ok"] = len(details)
        empty["budget"] = float(budget)
        return empty
    tbl = year_performance_table(trades, float(budget))
    by_year: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        day = compact_day(str(t.get("sell_exec_day") or t.get("buy_open_day") or ""))
        y = day[:4] if len(day) >= 4 else "?"
        by_year.setdefault(y, []).append(t)
    n_buy = len(trades)
    sum_pnl = _sum_trade_pnl(trades)
    return {
        "ok": True,
        "reason": "",
        "table": tbl if tbl is not None else pd.DataFrame(),
        "trades": trades,
        "trades_by_year": by_year,
        "budget": float(budget),
        "budget_by_year": {
            str(y): float(budget) for y in (tbl["year"].astype(str).tolist() if tbl is not None and not tbl.empty else [])
        },
        "n_ok": 1,
        "n_buy": n_buy,
        "sum_pnl": round(sum_pnl, 2),
        "pos_ratio": (1.0 if sum_pnl > 0 else 0.0) if n_buy else None,
        "split": "range",
    }


def _filter_perf_rows(
    rows: list[dict[str, Any]],
    *,
    ma_type: str = "",
    allow_mixed_ma: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """复权必须唯一；出现 SMA+EMA 时必须指定 ma_type。失败 reason 非空。"""
    from analyze import normalize_ma_type, unique_dividend_types  # noqa: WPS433

    ok_rows = [r for r in (rows or []) if r.get("ok")]
    divs = unique_dividend_types(ok_rows)
    if len(divs) >= 2:
        return [], "请先选一种复权"
    want_ma = normalize_ma_type(ma_type)
    found_ma: list[str] = []
    for r in ok_rows:
        m = normalize_ma_type(r.get("ma_type"))
        if m and m not in found_ma:
            found_ma.append(m)
    if len(found_ma) >= 2 and not want_ma and not allow_mixed_ma:
        return [], "请先选 SMA 或 EMA"
    filtered = []
    for r in ok_rows:
        if want_ma:
            got = normalize_ma_type(r.get("ma_type"))
            if got and got != want_ma:
                continue
        if not str(r.get("detail") or "").strip():
            continue
        filtered.append(r)
    if not filtered:
        return [], "没有成功明细"
    return filtered, ""


def _concat_trades(packed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for item in packed:
        trades.extend(list(item.get("trades") or []))
    return trades


def _pos_task_ratio(rows: list[dict[str, Any]]) -> float | None:
    n = 0
    pos = 0
    for r in rows:
        n += 1
        try:
            pnl = float(r.get("sum_pnl") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        if pnl > 0:
            pos += 1
    if n <= 0:
        return None
    return float(pos) / float(n)


def batch_naive_year_perf(
    rows: list[dict[str, Any]],
    *,
    split: str = "range",
    ma_type: str = "",
    cache: dict | None = None,
    packed: list[dict[str, Any]] | None = None,
    allow_mixed_ma: bool = False,
) -> dict[str, Any]:
    """单票合计分年绩效。

    返回 ok / reason / table / trades / trades_by_year / budget / budget_by_year /
    n_ok / n_buy / sum_pnl / pos_ratio / split。
    packed 仅供单测注入已解析轮次，跳过读盘。
    """
    empty = {
        "ok": False,
        "reason": "",
        "table": pd.DataFrame(),
        "trades": [],
        "trades_by_year": {},
        "budget": 0.0,
        "budget_by_year": {},
        "n_ok": 0,
        "n_buy": 0,
        "sum_pnl": 0.0,
        "pos_ratio": None,
        "split": str(split or "range"),
    }
    filtered, reason = _filter_perf_rows(
        rows, ma_type=ma_type, allow_mixed_ma=allow_mixed_ma
    )
    if reason:
        empty["reason"] = reason
        return empty
    if packed is None:
        packed = collect_batch_detail_trades(filtered, cache=cache)
    else:
        want = {str(r.get("detail") or "") for r in filtered}
        packed = [p for p in packed if str(p.get("detail") or "") in want]
    if not packed:
        empty["reason"] = "没有成功明细"
        return empty
    n_ok = len(packed)
    per = _per_budget(packed)
    split_s = "year" if str(split or "") == "year" else "range"
    pos_ratio = _pos_task_ratio(packed)

    if split_s == "year":
        by_year: dict[str, list[dict[str, Any]]] = {}
        for item in packed:
            y = _row_year(item) or "?"
            by_year.setdefault(y, []).append(item)
        frames: list[pd.DataFrame] = []
        trades_by_year: dict[str, list[dict[str, Any]]] = {}
        budget_by_year: dict[str, float] = {}
        all_trades: list[dict[str, Any]] = []
        for y in sorted(by_year):
            group = by_year[y]
            trades_y = _concat_trades(group)
            bud_y = float(len(group)) * per
            tbl = year_performance_table(trades_y, bud_y)
            if tbl is not None and not tbl.empty:
                match = tbl.loc[tbl["year"].astype(str) == str(y)]
                if match.empty:
                    match = tbl
                frames.append(match)
            trades_by_year[y] = trades_y
            budget_by_year[y] = bud_y
            all_trades.extend(trades_y)
        table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return {
            "ok": True,
            "reason": "",
            "table": table,
            "trades": all_trades,
            "trades_by_year": trades_by_year,
            "budget": per * n_ok,
            "budget_by_year": budget_by_year,
            "n_ok": n_ok,
            "n_buy": len(all_trades),
            "sum_pnl": _sum_trade_pnl(all_trades),
            "pos_ratio": pos_ratio,
            "split": split_s,
        }

    trades = _concat_trades(packed)
    budget = float(n_ok) * per
    table = year_performance_table(trades, budget)
    trades_by_year = {}
    for t in trades:
        sell = compact_day(str(t.get("sell_exec_day") or t.get("sell_signal_day") or ""))
        y = sell[:4] if len(sell) >= 4 else ""
        if not y:
            buy = compact_day(str(t.get("buy_open_day") or ""))
            y = buy[:4] if len(buy) >= 4 else "?"
        trades_by_year.setdefault(y, []).append(t)
    budget_by_year = {y: budget for y in trades_by_year}
    return {
        "ok": True,
        "reason": "",
        "table": table,
        "trades": trades,
        "trades_by_year": trades_by_year,
        "budget": budget,
        "budget_by_year": budget_by_year,
        "n_ok": n_ok,
        "n_buy": len(trades),
        "sum_pnl": _sum_trade_pnl(trades),
        "pos_ratio": pos_ratio,
        "split": split_s,
    }
