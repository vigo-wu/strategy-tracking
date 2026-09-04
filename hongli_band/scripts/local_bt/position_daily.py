# coding: utf-8
"""从成交轮次推导日度仓位占用（槽位 / 成本敞口 / 按票持仓天数）。

口径:
- 持仓区间半开: [buy_open_day, sell_exec_day)
- 日轴: pd.bdate_range（工作日近似，不依赖行情 CSV）
- 资金占用率: Σ(持仓 cost) / budget
- 槽位: 当日重叠 lot 数（每笔 trade 一行；同票加仓分别计）
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from market_csv import compact_day


def _ymd_to_ts(day: str) -> pd.Timestamp | None:
    d = compact_day(day)
    if len(d) != 8:
        return None
    try:
        return pd.Timestamp("%s-%s-%s" % (d[:4], d[4:6], d[6:8]))
    except ValueError:
        return None


def _trade_interval(t: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp, str, float] | None:
    buy = _ymd_to_ts(str(t.get("buy_open_day") or ""))
    sell = _ymd_to_ts(str(t.get("sell_exec_day") or ""))
    if buy is None or sell is None or sell <= buy:
        return None
    stock = str(t.get("stock") or "").strip() or "?"
    try:
        cost = float(t.get("cost") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    if cost <= 0:
        try:
            cost = float(t.get("buy_price") or 0.0) * float(t.get("shares") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
    return buy, sell, stock, float(cost)


def _lot_windows(trades: list[dict] | None) -> list[tuple[pd.Timestamp, pd.Timestamp, str, float]]:
    out: list[tuple[pd.Timestamp, pd.Timestamp, str, float]] = []
    for t in trades or []:
        iv = _trade_interval(t)
        if iv is not None:
            out.append(iv)
    return out


def build_daily_position_frame(
    trades: list[dict] | None,
    budget: float = 100000.0,
) -> pd.DataFrame:
    """日度 slots / cost / exposure_pct + 各票 cost 列 cost_<stock>。"""
    lots = _lot_windows(trades)
    bud = float(budget) if float(budget) > 0 else 1.0
    empty_cols = ["date", "slots", "cost", "exposure_pct"]
    if not lots:
        return pd.DataFrame(columns=empty_cols)

    start = min(b for b, _, _, _ in lots)
    end = max(s for _, s, _, _ in lots)
    # 半开上界：最后一天为 max(sell)-1 个工作日；bdate_range 含端点，用 end-1day
    last = end - pd.Timedelta(days=1)
    if last < start:
        return pd.DataFrame(columns=empty_cols)
    days = pd.bdate_range(start, last)
    if len(days) == 0:
        return pd.DataFrame(columns=empty_cols)

    stocks = sorted({st for _, _, st, _ in lots})
    stock_cols = ["cost_%s" % s for s in stocks]
    rows: list[dict[str, Any]] = []
    for d in days:
        slots = 0
        total_cost = 0.0
        by_stock = {s: 0.0 for s in stocks}
        for buy, sell, stock, cost in lots:
            if buy <= d < sell:
                slots += 1
                total_cost += cost
                by_stock[stock] = by_stock.get(stock, 0.0) + cost
        row: dict[str, Any] = {
            "date": d,
            "slots": int(slots),
            "cost": float(total_cost),
            "exposure_pct": float(total_cost / bud * 100.0),
        }
        for s in stocks:
            row["cost_%s" % s] = float(by_stock.get(s, 0.0))
        rows.append(row)
    return pd.DataFrame(rows, columns=empty_cols + stock_cols)


def slice_daily(
    daily: pd.DataFrame | None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """按日期窗切片；start/end 为空则不截对应端。含端点。"""
    if daily is None or daily.empty or "date" not in daily.columns:
        return pd.DataFrame(columns=["date", "slots", "cost", "exposure_pct"])
    out = daily.copy()
    out["date"] = pd.to_datetime(out["date"])
    s = _coerce_bound(start)
    e = _coerce_bound(end)
    if s is not None:
        out = out[out["date"] >= s]
    if e is not None:
        out = out[out["date"] <= e]
    return out.reset_index(drop=True)


def _coerce_bound(raw: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, pd.Timestamp):
        return raw.normalize()
    d = compact_day(str(raw))
    if len(d) == 8:
        return pd.Timestamp("%s-%s-%s" % (d[:4], d[4:6], d[6:8]))
    try:
        return pd.Timestamp(str(raw)).normalize()
    except (TypeError, ValueError):
        return None


def stock_hold_days(
    trades: list[dict] | None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """按标的持仓交易日数（同日多 lot 去重）。列: stock, days, days_pct。"""
    daily = build_daily_position_frame(trades, budget=1.0)
    daily = slice_daily(daily, start, end)
    if daily.empty:
        return pd.DataFrame(columns=["stock", "days", "days_pct"])
    cost_cols = [c for c in daily.columns if c.startswith("cost_") and c != "cost"]
    if not cost_cols:
        return pd.DataFrame(columns=["stock", "days", "days_pct"])
    n_days = max(len(daily), 1)
    rows = []
    for col in cost_cols:
        stock = col[len("cost_") :]
        days = int((daily[col].fillna(0.0) > 0).sum())
        rows.append(
            {
                "stock": stock,
                "days": days,
                "days_pct": round(days / n_days * 100.0, 2),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["days", "stock"], ascending=[False, True]).reset_index(drop=True)


def slot_day_hist(
    daily: pd.DataFrame | None,
    book_lot_max: int = 3,
) -> pd.DataFrame:
    """槽位占用直方。列: slots, days。覆盖 0..book_lot_max（超出并入 max）。"""
    n = max(int(book_lot_max), 0)
    counts = {i: 0 for i in range(n + 1)}
    if daily is not None and not daily.empty and "slots" in daily.columns:
        for v in daily["slots"].tolist():
            try:
                s = int(v)
            except (TypeError, ValueError):
                s = 0
            if s < 0:
                s = 0
            if s > n:
                s = n
            counts[s] = counts.get(s, 0) + 1
    return pd.DataFrame({"slots": list(range(n + 1)), "days": [counts[i] for i in range(n + 1)]})


def position_kpis(
    daily: pd.DataFrame | None,
    book_lot_max: int = 3,
) -> dict[str, Any]:
    """avg_slots / full_slot_day_pct / avg_exposure / max_empty_streak。"""
    n = max(int(book_lot_max), 1)
    empty = {
        "avg_slots": 0.0,
        "full_slot_day_pct": 0.0,
        "avg_exposure": 0.0,
        "max_empty_streak": 0,
        "n_days": 0,
    }
    if daily is None or daily.empty:
        return empty
    slots = daily["slots"].astype(int) if "slots" in daily.columns else pd.Series(dtype=int)
    expo = daily["exposure_pct"] if "exposure_pct" in daily.columns else pd.Series(dtype=float)
    n_days = int(len(daily))
    avg_slots = float(slots.mean()) if n_days else 0.0
    full_pct = float((slots >= n).sum() / n_days * 100.0) if n_days else 0.0
    avg_expo = float(expo.mean()) if n_days else 0.0
    streak = 0
    max_empty = 0
    for v in slots.tolist():
        if int(v) == 0:
            streak += 1
            if streak > max_empty:
                max_empty = streak
        else:
            streak = 0
    return {
        "avg_slots": round(avg_slots, 3),
        "full_slot_day_pct": round(full_pct, 2),
        "avg_exposure": round(avg_expo, 2),
        "max_empty_streak": int(max_empty),
        "n_days": n_days,
    }


def cost_stock_columns(daily: pd.DataFrame | None) -> list[str]:
    if daily is None or daily.empty:
        return []
    return [c for c in daily.columns if c.startswith("cost_") and c != "cost"]


def stock_from_cost_col(col: str) -> str:
    return col[len("cost_") :] if col.startswith("cost_") else col
