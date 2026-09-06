# coding: utf-8
"""从成交轮次推导日度权益与按年绩效。

口径:
- 权益 = budget + 已实现 cum_pnl（按 sell_exec_day 台阶，工作日向前填充）
- 年盈亏归因按卖出年；开仓次数按 buy_open_day 年
- 年化盈亏% = (期末 − 期初) / 期初 × 100（简单年收益）
- 夏普 = mean(日收益) / std(日收益) × √252
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
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


def _trade_pnl(t: dict[str, Any]) -> float:
    try:
        return float(t.get("pnl") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_daily_equity(
    trades: list[dict] | None,
    budget: float = 100000.0,
) -> pd.DataFrame:
    """日度权益阶梯。列: date, equity, cum_pnl。"""
    cols = ["date", "equity", "cum_pnl"]
    bud = float(budget)
    sells: list[tuple[pd.Timestamp, float]] = []
    buys: list[pd.Timestamp] = []
    for t in trades or []:
        sell = _ymd_to_ts(str(t.get("sell_exec_day") or t.get("sell_signal_day") or ""))
        buy = _ymd_to_ts(str(t.get("buy_open_day") or ""))
        if buy is not None:
            buys.append(buy)
        if sell is None:
            continue
        sells.append((sell, _trade_pnl(t)))
    if not sells and not buys:
        return pd.DataFrame(columns=cols)

    start = min(([s for s, _ in sells] + buys))
    end = max([s for s, _ in sells] + buys) if sells else max(buys)
    if sells:
        end = max(end, max(s for s, _ in sells))
    days = pd.bdate_range(start, end)
    if len(days) == 0:
        return pd.DataFrame(columns=cols)

    pnl_by_day: dict[pd.Timestamp, float] = {}
    for sell, pnl in sells:
        key = sell.normalize()
        pnl_by_day[key] = pnl_by_day.get(key, 0.0) + pnl

    cum = 0.0
    rows: list[dict[str, Any]] = []
    for d in days:
        dn = pd.Timestamp(d).normalize()
        cum += float(pnl_by_day.get(dn, 0.0))
        rows.append({"date": dn, "equity": bud + cum, "cum_pnl": cum})
    return pd.DataFrame(rows, columns=cols)


def _max_dd_pct(eq: pd.Series) -> float | None:
    vals = pd.to_numeric(eq, errors="coerce").dropna()
    if vals.empty:
        return None
    peak = vals.cummax()
    base = peak.replace(0, np.nan)
    dd = (vals - peak) / base
    val = float(dd.min()) if len(dd) else None
    if val is None or not np.isfinite(val):
        return None
    return round(val * 100.0, 4)


def simple_returns(eq: pd.Series) -> pd.Series:
    """权益序列 → 简单日收益（丢掉首个 NaN / 非有限值）。"""
    vals = pd.to_numeric(eq, errors="coerce").dropna()
    if vals.empty:
        return pd.Series(dtype=float)
    prev = vals.shift(1)
    rets = (vals - prev) / prev.replace(0, np.nan)
    return rets.replace([np.inf, -np.inf], np.nan).dropna()


def sharpe_from_returns(rets: pd.Series | list | np.ndarray) -> float | None:
    """mean/std × √252。不足 2 个收益或标准差为 0 则 None。"""
    s = pd.to_numeric(pd.Series(rets), errors="coerce").dropna()
    if len(s) < 2:
        return None
    std = float(s.std(ddof=1))
    if std <= 1e-12 or not np.isfinite(std):
        return None
    mean = float(s.mean())
    if not np.isfinite(mean):
        return None
    return round(mean / std * math.sqrt(252.0), 4)


def _sharpe_daily(eq: pd.Series) -> float | None:
    vals = pd.to_numeric(eq, errors="coerce").dropna()
    if len(vals) < 3:
        return None
    return sharpe_from_returns(simple_returns(vals))


def year_equity_path(
    daily: pd.DataFrame | None,
    year: str | int,
    budget: float = 100000.0,
) -> pd.Series:
    """含期初点的该年权益路径（与 year_performance_table 夏普同一条）。"""
    bud = float(budget)
    if daily is None or daily.empty:
        return pd.Series([bud], dtype=float)
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    y_int = int(year)
    year_slice = df.loc[df["date"].dt.year == y_int]
    prior = df.loc[df["date"].dt.year < y_int]
    start_eq = float(prior["equity"].iloc[-1]) if not prior.empty else bud
    if year_slice.empty:
        return pd.Series([start_eq], dtype=float)
    return pd.concat(
        [pd.Series([start_eq], dtype=float), year_slice["equity"].reset_index(drop=True)],
        ignore_index=True,
    )


def _years_touched(trades: list[dict] | None) -> list[str]:
    years: set[str] = set()
    for t in trades or []:
        for key in ("sell_exec_day", "sell_signal_day", "buy_open_day"):
            ts = _ymd_to_ts(str(t.get(key) or ""))
            if ts is not None:
                years.add(str(ts.year))
    return sorted(years)


def year_performance_table(
    trades: list[dict] | None,
    budget: float = 100000.0,
) -> pd.DataFrame:
    """按年绩效。列: year, start_equity, end_equity, year_pnl, year_ret_pct, max_dd_pct, n_open, sharpe。"""
    cols = [
        "year",
        "start_equity",
        "end_equity",
        "year_pnl",
        "year_ret_pct",
        "max_dd_pct",
        "n_open",
        "sharpe",
    ]
    daily = build_daily_equity(trades, budget)
    years = _years_touched(trades)
    if not years:
        return pd.DataFrame(columns=cols)

    bud = float(budget)
    open_count: dict[str, int] = {y: 0 for y in years}
    for t in trades or []:
        buy = _ymd_to_ts(str(t.get("buy_open_day") or ""))
        if buy is not None:
            y = str(buy.year)
            open_count[y] = open_count.get(y, 0) + 1

    if daily.empty:
        # 仅有开仓、尚无卖出：仍可出开仓年行，权益停在 budget
        rows = []
        for y in years:
            rows.append(
                {
                    "year": y,
                    "start_equity": bud,
                    "end_equity": bud,
                    "year_pnl": 0.0,
                    "year_ret_pct": 0.0,
                    "max_dd_pct": 0.0,
                    "n_open": int(open_count.get(y, 0)),
                    "sharpe": None,
                }
            )
        return pd.DataFrame(rows, columns=cols)

    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    rows = []
    for y in years:
        path = year_equity_path(daily, y, bud)
        start_eq = float(path.iloc[0])
        end_eq = float(path.iloc[-1])
        year_pnl = end_eq - start_eq
        if abs(start_eq) < 1e-12:
            ret_pct = None
        else:
            ret_pct = round(year_pnl / start_eq * 100.0, 4)
        rows.append(
            {
                "year": y,
                "start_equity": round(start_eq, 2),
                "end_equity": round(end_eq, 2),
                "year_pnl": round(year_pnl, 2),
                "year_ret_pct": ret_pct,
                "max_dd_pct": _max_dd_pct(path),
                "n_open": int(open_count.get(y, 0)),
                "sharpe": _sharpe_daily(path),
            }
        )
    return pd.DataFrame(rows, columns=cols)


def daily_equity_for_year(
    daily_eq: pd.DataFrame | None,
    year: str | int,
    *,
    start_equity: float | None = None,
) -> pd.DataFrame:
    """弹窗用：该年日度权益，前置一期初点（date=None）。"""
    cols = ["date", "equity", "cum_pnl"]
    if daily_eq is None or daily_eq.empty:
        return pd.DataFrame(columns=cols)
    y_int = int(year)
    df = daily_eq.copy()
    df["date"] = pd.to_datetime(df["date"])
    year_slice = df.loc[df["date"].dt.year == y_int].copy()
    prior = df.loc[df["date"].dt.year < y_int]
    bud = float(df["equity"].iloc[0]) - float(df["cum_pnl"].iloc[0])
    if start_equity is not None:
        start_eq = float(start_equity)
    elif not prior.empty:
        start_eq = float(prior["equity"].iloc[-1])
    else:
        start_eq = bud
    start_cum = start_eq - bud
    head = pd.DataFrame([{"date": None, "equity": start_eq, "cum_pnl": start_cum}])
    if year_slice.empty:
        return head
    return pd.concat([head, year_slice[cols]], ignore_index=True)


YEAR_PERF_DISPLAY_COLUMNS = (
    "年份",
    "年化盈亏%",
    "当年盈亏",
    "最大回撤%",
    "开仓次数",
    "夏普",
    "期初权益",
    "期末权益",
)


def year_perf_display_df(tbl: pd.DataFrame | None) -> pd.DataFrame:
    """分年绩效表中文列，与数据分析/批量结果一致。"""
    if tbl is None or getattr(tbl, "empty", True):
        return pd.DataFrame(columns=list(YEAR_PERF_DISPLAY_COLUMNS))
    return pd.DataFrame(
        {
            "年份": tbl["year"].astype(str),
            "年化盈亏%": tbl["year_ret_pct"],
            "当年盈亏": tbl["year_pnl"],
            "最大回撤%": tbl["max_dd_pct"],
            "开仓次数": tbl["n_open"],
            "夏普": tbl["sharpe"],
            "期初权益": tbl["start_equity"],
            "期末权益": tbl["end_equity"],
        }
    )
