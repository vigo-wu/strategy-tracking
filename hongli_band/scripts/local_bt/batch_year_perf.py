# coding: utf-8
"""批量结果：单票独立账户盈亏按年相加（数据分析「单票合计」口径）。

不跑组合回放。整段区间用一条连续权益；按年分段每年独立空仓。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from equity_yearly import year_performance_table
from market_csv import compact_day


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
        out.append(packed)
    return out


def _filter_perf_rows(
    rows: list[dict[str, Any]],
    *,
    ma_type: str = "",
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
    if len(found_ma) >= 2 and not want_ma:
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


def _sum_trade_pnl(trades: list[dict[str, Any]]) -> float:
    total = 0.0
    for t in trades:
        try:
            total += float(t.get("pnl") or 0)
        except (TypeError, ValueError):
            continue
    return total


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
    filtered, reason = _filter_perf_rows(rows, ma_type=ma_type)
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
