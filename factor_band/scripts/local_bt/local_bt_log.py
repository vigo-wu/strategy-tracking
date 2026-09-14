# coding: utf-8
"""解析 local_bt 回测 log / 旁路操作明细为成交轮次。网格 summarize 用，不依赖 MAE。"""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

IS_YEARS = {2018, 2019, 2020, 2021, 2022}
OOS_YEARS = {2023, 2024, 2025, 2026}
BUDGET = 100000.0

RE_BANNER = re.compile(
    r"local_bt\s+(\S+)\s+csv=\s+(\S+)\s+walk=\s+(\d+)\s+(\d+).*?\bma_type=\s+(\S+)",
    re.S,
)
RE_BUY_FILL = re.compile(r"BUY(?: add)? filled (\{.*\})")
RE_SELL_SIG = re.compile(r"SELL by signal=(\w+)\b.*?signal_day=(\d+)")
RE_SELL_DONE = re.compile(
    r"SELL done (\S+)\s+last=\s*([0-9.eE+-]+)\s+cleared (\{.*\})"
)
RE_BUDGET = re.compile(r"budget=\s*([0-9.]+)")


def parse_trade_budget(path: str | Path | None, default: float = BUDGET) -> float:
    """从 local_bt log 读 TRADE_BUDGET；读不到则用 default。"""
    fallback = float(default)
    if not path:
        return fallback
    p = Path(path)
    if not p.is_file():
        return fallback
    text = p.read_text(encoding="utf-8", errors="replace")
    m = RE_BUDGET.search(text)
    if not m:
        return fallback
    try:
        val = float(m.group(1))
    except ValueError:
        return fallback
    return val if val > 0 else fallback


def parse_banner(text: str) -> dict[str, str]:
    first = text.splitlines()[0] if text else ""
    m = RE_BANNER.search(first)
    if not m:
        return {}
    return {
        "stock": m.group(1).strip().upper(),
        "csv": m.group(2).strip(),
        "walk_start": m.group(3)[:8],
        "walk_end": m.group(4)[:8],
        "ma_type": m.group(5).strip().upper(),
    }


def _parse_pos(raw: str) -> dict[str, Any]:
    try:
        obj = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _trades_from_log_text(text: str) -> list[dict[str, Any]]:
    fills: dict[str, dict[str, Any]] = {}
    for m in RE_BUY_FILL.finditer(text):
        pos = _parse_pos(m.group(1))
        opened = str(pos.get("opened_at") or "")
        if not opened:
            continue
        fills[opened] = {
            "pos": m.start(),
            "shares": int(pos.get("shares") or 0),
            "price": float(pos.get("price") or 0),
            "opened_at": opened,
        }
    sigs: list[tuple[int, str, str]] = []
    for m in RE_SELL_SIG.finditer(text):
        sigs.append((m.start(), m.group(1), str(m.group(2))[:8]))
    trades: list[dict[str, Any]] = []
    for m in RE_SELL_DONE.finditer(text):
        pos = _parse_pos(m.group(3))
        opened = str(pos.get("opened_at") or "")
        buy = fills.get(opened)
        if not buy:
            continue
        sm = None
        for sp, ss, sd in reversed(sigs):
            if sp < m.start():
                sm = (ss, sd)
                break
        buy_px = float(buy["price"])
        sell_px = float(m.group(2))
        shares = int(buy["shares"] or pos.get("shares") or 0)
        buy_day = str(opened)[:8]
        sell_day = (sm[1] if sm else "") or buy_day
        signal = str(m.group(1) or (sm[0] if sm else "") or "-")
        trades.append(
            {
                "buy_open_day": buy_day,
                "sell_exec_day": sell_day,
                "buy_price": buy_px,
                "sell_price": sell_px,
                "shares": shares,
                "pnl": (sell_px - buy_px) * shares,
                "sell_signal": signal,
            }
        )
    return trades


def parse_local_bt_log(path: Path) -> tuple[dict[str, str], list[dict[str, Any]]]:
    log = Path(path)
    text = log.read_text(encoding="utf-8", errors="replace")
    banner = parse_banner(text)
    detail = log.with_name(log.stem + "_操作明细.csv")
    if detail.is_file():
        from analyze import analyze_detail

        result = analyze_detail(detail, log_path=log, hold_metrics=False)
        return banner, list(result.get("trades") or [])
    return banner, _trades_from_log_text(text)


def _year_of(day: str) -> int | None:
    d = str(day or "")
    if len(d) >= 4 and d[:4].isdigit():
        return int(d[:4])
    return None


def _max_dd(pnls_by_day: list[tuple[str, float]], n_accounts: int) -> float | None:
    if n_accounts <= 0 or not pnls_by_day:
        return None
    grouped: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for day, pnl in pnls_by_day:
        y = _year_of(day)
        if y is None:
            continue
        grouped[y].append((day, pnl))
    worst: float | None = None
    start = float(n_accounts) * BUDGET
    for y in sorted(grouped):
        rows = sorted(grouped[y], key=lambda x: x[0])
        eq = start
        peak = start
        dd = 0.0
        for _d, pnl in rows:
            eq += float(pnl)
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = min(dd, (eq - peak) / peak)
        if worst is None or dd < worst:
            worst = dd
    return worst
