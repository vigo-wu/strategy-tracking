# coding: utf-8
"""可复现的合成行情：覆盖基础池剔除、14:45 通过、前视陷阱。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

import pandas as pd

from onr_strategy.backtest.data import MemoryStore, StockMeta, add_hhmm


def session_stamps(day: date) -> List[datetime]:
    out: List[datetime] = []
    t = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=30)
    end_am = t.replace(hour=11, minute=29)
    while t <= end_am:
        out.append(t)
        t += timedelta(minutes=1)
    t = datetime.combine(day, datetime.min.time()).replace(hour=13, minute=0)
    end_pm = t.replace(hour=14, minute=59)
    while t <= end_pm:
        out.append(t)
        t += timedelta(minutes=1)
    return out


def _weekdays(n: int, start: date) -> List[date]:
    days = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _minute_frame(
    symbol: str,
    day: date,
    *,
    pre_close: float,
    p_open: float,
    p_1430: float,
    p_1445: float,
    p_close: float,
    body_vol: float = 1000.0,
    tail_vol: float = 1000.0,
    after_vol: float = 1000.0,
    after_px: float | None = None,
) -> pd.DataFrame:
    stamps = session_stamps(day)
    rows = []
    after = after_px if after_px is not None else p_close
    for ts in stamps:
        hh = ts.hour * 100 + ts.minute
        if hh <= 1430:
            frac = _frac(hh, 930, 1430)
            px = p_open + (p_1430 - p_open) * frac
            vol = body_vol
        elif hh <= 1445:
            frac = _frac(hh, 1430, 1445)
            px = p_1430 + (p_1445 - p_1430) * frac
            vol = tail_vol
        else:
            frac = _frac(hh, 1445, 1459)
            px = p_1445 + (after - p_1445) * frac
            vol = after_vol
        rows.append(
            {
                "symbol": symbol,
                "datetime": ts,
                "open": px,
                "high": px * 1.001,
                "low": px * 0.999,
                "close": px,
                "volume": vol,
                "amount": px * vol,
            }
        )
    df = pd.DataFrame(rows)
    # 日最高用 14:45 前的 high，避免把决策后冲高写进上影（前视）。
    # 合成数据里 14:45 后 after_px 可以很高，但因子层会截断。
    return add_hhmm(df)


def _frac(hh: int, a: int, b: int) -> float:
    if b == a:
        return 1.0
    return max(0.0, min(1.0, (hh - a) / float(b - a)))


def _daily_frame(symbol: str, days: List[date], closes: List[float], caps: List[float]) -> pd.DataFrame:
    rows = []
    for i, day in enumerate(days):
        close = closes[i]
        pre = closes[i - 1] if i else close
        o = pre * 1.002
        h = max(o, close) * 1.01
        l = min(o, close) * 0.99
        rows.append(
            {
                "symbol": symbol,
                "date": day,
                "open": o,
                "high": h,
                "low": l,
                "close": close,
                "volume": 2_000_000,
                "amount": 2.0e8,
                "pre_close": pre,
                "float_mkt_cap": caps[i],
                "suspended": 0,
            }
        )
    return pd.DataFrame(rows)


def build_demo_store(*, n_days: int = 28, start: date = date(2024, 1, 2)) -> MemoryStore:
    """AAA/FFF 在倒数第 2 个交易日发出可交易信号；GGG 只在 14:45 后变强。"""
    days = _weekdays(n_days, start)
    signal = days[-2]
    metas = {
        "AAA.SZ": StockMeta("AAA.SZ", "优品", date(2020, 1, 2), False, "sw_a", "SZ"),
        "FFF.SZ": StockMeta("FFF.SZ", "次优", date(2020, 1, 2), False, "sw_a", "SZ"),
        "BBB.SZ": StockMeta("BBB.SZ", "无动量", date(2020, 1, 2), False, "sw_a", "SZ"),
        "GGG.SZ": StockMeta("GGG.SZ", "前视陷阱", date(2020, 1, 2), False, "sw_a", "SZ"),
        "CCC.SZ": StockMeta("CCC.SZ", "ST风险", date(2020, 1, 2), True, "sw_a", "SZ"),
        "DDD.BJ": StockMeta("DDD.BJ", "北交", date(2020, 1, 2), False, "sw_a", "BJ"),
        "EEE.SZ": StockMeta("EEE.SZ", "次新", days[-5], False, "sw_a", "SZ"),
    }
    daily_map: Dict[str, pd.DataFrame] = {}
    minute_map: Dict[Tuple[str, date], pd.DataFrame] = {}
    cap_aaa = [40e8] * n_days
    cap_fff = [80e8] * n_days
    cap_rest = [50e8] * n_days

    def trend_closes(start_px: float, last_close: float) -> List[float]:
        out = []
        for i in range(n_days):
            if i < n_days - 2:
                out.append(start_px + 0.04 * i)
            elif i == n_days - 2:
                out.append(last_close)
            else:
                out.append(last_close * 1.02)
        return out

    profiles = {
        "AAA.SZ": (9.0, 10.50, cap_aaa, 10.32, 10.42, 2000.0, 10.80),
        "FFF.SZ": (9.0, 10.48, cap_fff, 10.35, 10.44, 1800.0, 10.55),
        "BBB.SZ": (9.0, 10.40, cap_rest, 10.39, 10.40, 1800.0, 10.40),
        "GGG.SZ": (9.0, 10.55, cap_rest, 10.18, 10.20, 2500.0, 10.70),
        "CCC.SZ": (9.0, 10.50, cap_rest, 10.32, 10.42, 2000.0, 10.50),
        "DDD.BJ": (9.0, 10.50, cap_rest, 10.32, 10.42, 2000.0, 10.50),
        "EEE.SZ": (9.0, 10.50, cap_rest, 10.32, 10.42, 2000.0, 10.50),
    }
    for sym, (start_px, sig_close, caps, p1430, p1445, tail_vol, after_px) in profiles.items():
        closes = trend_closes(start_px, sig_close)
        daily_map[sym] = _daily_frame(sym, days, closes, caps)
        for i, day in enumerate(days):
            pre = closes[i - 1] if i else closes[i]
            if day == signal:
                p_open = pre * 1.01
                mf = _minute_frame(
                    sym,
                    day,
                    pre_close=pre,
                    p_open=p_open,
                    p_1430=p1430,
                    p_1445=p1445,
                    p_close=sig_close,
                    body_vol=800.0,
                    tail_vol=tail_vol,
                    after_vol=3000.0 if sym == "GGG.SZ" else 900.0,
                    after_px=after_px,
                )
                # 上影用 14:45 前 high；把信号日日线 high 对齐到截断高点，避免日线干扰（引擎买价用 close）。
            else:
                px = closes[i]
                mf = _minute_frame(
                    sym,
                    day,
                    pre_close=pre,
                    p_open=px * 0.999,
                    p_1430=px,
                    p_1445=px,
                    p_close=px,
                    body_vol=1000.0,
                    tail_vol=1000.0,
                    after_vol=1000.0,
                    after_px=px,
                )
            minute_map[(sym, day)] = mf
        # T+1 出场日：AAA 高开后回落，方便 rules 卖出
        t1 = days[-1]
        if sym == "AAA.SZ":
            pre = sig_close
            minute_map[(sym, t1)] = _exit_minutes(sym, t1, pre, open_px=pre * 1.02, dump_after=6)
        elif sym == "FFF.SZ":
            pre = sig_close
            minute_map[(sym, t1)] = _exit_minutes(sym, t1, pre, open_px=pre * 1.001, dump_after=20)

    index_map: Dict[Tuple[str, date], pd.DataFrame] = {}
    for code in ("000001.SH", "399006.SZ"):
        for day in days:
            index_map[(code, day)] = _minute_frame(
                code,
                day,
                pre_close=3000.0,
                p_open=3000.0,
                p_1430=3002.0,
                p_1445=3003.0,
                p_close=3004.0,
                body_vol=1e6,
                tail_vol=1.1e6,
                after_vol=1e6,
                after_px=3004.0,
            )
    return MemoryStore(
        metas=metas,
        daily_map=daily_map,
        minute_map=minute_map,
        index_minute_map=index_map,
        days=days,
    )


def _exit_minutes(symbol: str, day: date, pre: float, *, open_px: float, dump_after: int) -> pd.DataFrame:
    stamps = session_stamps(day)
    rows = []
    px = open_px
    for i, ts in enumerate(stamps):
        if i >= dump_after:
            px = max(pre * 0.995, px * 0.997)
        else:
            px = px * 1.0005
        vol = 1000.0
        rows.append(
            {
                "symbol": symbol,
                "datetime": ts,
                "open": px,
                "high": px * 1.002,
                "low": px * 0.998,
                "close": px,
                "volume": vol,
                "amount": px * vol,
            }
        )
    return add_hhmm(pd.DataFrame(rows))
