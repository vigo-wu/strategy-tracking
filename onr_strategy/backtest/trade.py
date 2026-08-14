# coding: utf-8
"""成本、成交、T+1 出场。买入价 = 收盘 × (1+冲击)，不用 14:45 价。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import pandas as pd

from onr_strategy.backtest.config import OnrConfig
from onr_strategy.backtest.data import (
    MarketStore,
    add_hhmm,
    daily_row,
    last_at_or_before,
    limit_up_price,
    slice_hhmm,
)


@dataclass
class Position:
    symbol: str
    shares: int
    cost: float
    buy_close: float
    buy_date: date
    px_1445: float
    hold_days: int = 1


@dataclass
class Fill:
    time_hhmm: int
    price: float
    reason: str


@dataclass
class Trade:
    symbol: str
    buy_date: date
    sell_date: date
    buy_hhmm: int
    sell_hhmm: int
    shares: int
    buy_px: float
    sell_px: float
    open_t1: float
    px_1445: float
    overnight_ret: float
    morning_ret: float
    gross_ret: float
    net_ret: float
    t1_weekday: int
    year: int
    exit_reason: str
    source: str


def buy_notional_cost(notional: float, cfg: OnrConfig) -> float:
    return notional * cfg.commission


def sell_notional_cost(notional: float, cfg: OnrConfig) -> float:
    return notional * (cfg.commission + cfg.stamp_sell)


def buy_fill_price(close: float, cfg: OnrConfig) -> float:
    return float(close) * (1.0 + cfg.buy_impact)


def round_lot(shares: int, lot: int) -> int:
    return (shares // lot) * lot


def shares_for_budget(budget: float, price: float, lot: int) -> int:
    if price <= 0 or budget <= 0:
        return 0
    return round_lot(int(budget // price), lot)


def _mins(store: MarketStore, symbol: str, day: date) -> pd.DataFrame:
    raw = store.minutes(symbol, day)
    if raw is None or raw.empty:
        return pd.DataFrame()
    return add_hhmm(raw) if "hhmm" not in raw.columns else raw


def session_open(store: MarketStore, symbol: str, day: date) -> Optional[float]:
    row = daily_row(store, symbol, day)
    if row is None:
        return None
    mins = _mins(store, symbol, day)
    if mins.empty:
        return float(row["open"])
    px = last_at_or_before(mins, 930, "open")
    if px is None:
        px = last_at_or_before(mins, 930, "close")
    return px if px is not None else float(row["open"])


def one_word_limit_up(mins: pd.DataFrame, limit_up: float, cfg: OnrConfig) -> bool:
    if mins is None or mins.empty:
        return False
    head = slice_hhmm(mins, cfg.t_open, cfg.t_flat_deadline, end_inclusive=True)
    if head.empty:
        return False
    first_open = float(head.iloc[0]["open"])
    if first_open < limit_up - 1e-6:
        return False
    return float(head["low"].min()) >= limit_up - 1e-6


def bar_sellable(low: float, limit_up: float) -> bool:
    return float(low) < limit_up - 1e-6


def _fill_at_bar(bar: pd.Series, reason: str, *, price: Optional[float] = None) -> Fill:
    px = float(bar["close"] if price is None else price)
    return Fill(time_hhmm=int(bar["hhmm"]), price=px, reason=reason)


def walk_rules_exit(
    pos: Position,
    store: MarketStore,
    day: date,
    cfg: OnrConfig,
) -> Optional[Fill]:
    row = daily_row(store, pos.symbol, day)
    if row is None:
        return None
    meta = store.meta(pos.symbol)
    pre = pos.buy_close
    up = limit_up_price(pre, pos.symbol, meta.is_st)
    mins = _mins(store, pos.symbol, day)
    if mins.empty:
        return None
    open_px = session_open(store, pos.symbol, day)
    if open_px is None:
        return None
    if pos.hold_days >= cfg.max_hold_days:
        last = mins.iloc[-1]
        if bar_sellable(float(last["low"]), up):
            return _fill_at_bar(last, "max_hold")
        return None
    if one_word_limit_up(mins, up, cfg):
        return None
    g = open_px / pre - 1.0
    if g > cfg.high_open:
        bucket = "high"
    elif g < cfg.low_open:
        bucket = "low"
    else:
        bucket = "flat"
    stop = pos.cost * (1.0 - cfg.stop_from_cost)
    closes: List[float] = []
    cum_pv = 0.0
    cum_v = 0.0
    pumped = False
    for _, bar in mins.iterrows():
        hh = int(bar["hhmm"])
        if hh < cfg.t_open:
            continue
        o, h, l, c, v = (float(bar[k]) for k in ("open", "high", "low", "close", "volume"))
        if not bar_sellable(l, up):
            closes.append(c)
            cum_v += v
            cum_pv += c * v
            continue
        if bucket == "low":
            if l <= stop:
                fill_px = o if o <= stop else stop
                return Fill(hh, fill_px, "stop")
            if hh >= cfg.t_low_confirm and c < pre:
                return _fill_at_bar(bar, "low_unrecovered")
            if hh >= cfg.t_force_exit:
                return _fill_at_bar(bar, "low_deadline")
        if bucket == "flat":
            if (not pumped) and h >= open_px * (1.0 + cfg.flat_pump_ret) and c > open_px:
                pumped = True
            if (not pumped) and hh >= cfg.t_flat_deadline:
                return _fill_at_bar(bar, "flat_timeout")
        closes.append(c)
        cum_v += v
        cum_pv += c * v
        ma5 = sum(closes[-5:]) / min(5, len(closes)) if len(closes) >= 5 else None
        vwap = (cum_pv / cum_v) if cum_v > 0 else None
        if bucket == "high" or (bucket == "flat" and pumped):
            if ma5 is not None and c < ma5:
                return _fill_at_bar(bar, "break_ma5")
            if vwap is not None and c < vwap:
                return _fill_at_bar(bar, "break_vwap")
            if hh >= cfg.t_force_exit:
                return _fill_at_bar(bar, "high_deadline")
        if hh >= cfg.t_force_exit:
            return _fill_at_bar(bar, "deadline")
    last = mins.iloc[-1]
    if bar_sellable(float(last["low"]), up):
        return _fill_at_bar(last, "eod")
    return None


def exit_fill(
    pos: Position,
    store: MarketStore,
    day: date,
    cfg: OnrConfig,
) -> Optional[Fill]:
    row = daily_row(store, pos.symbol, day)
    if row is None:
        return None
    meta = store.meta(pos.symbol)
    up = limit_up_price(pos.buy_close, pos.symbol, meta.is_st)
    mins = _mins(store, pos.symbol, day)
    if cfg.exit_mode == "open":
        open_px = session_open(store, pos.symbol, day)
        if open_px is None:
            return None
        if abs(open_px - up) <= 1e-6 and mins is not None and not mins.empty:
            if float(mins["low"].min()) >= up - 1e-6:
                return None
        return Fill(930, float(open_px), "open")
    if cfg.exit_mode == "next_close":
        close = float(row["close"])
        if close >= up - 1e-6 and mins is not None and not mins.empty:
            if float(mins["low"].min()) >= up - 1e-6:
                return None
        return Fill(1500, close, "next_close")
    return walk_rules_exit(pos, store, day, cfg)


def make_trade(pos: Position, fill: Fill, sell_date: date, source: str, cfg: OnrConfig) -> Trade:
    buy_notional = pos.shares * pos.cost
    sell_notional = pos.shares * fill.price
    fees = buy_notional_cost(buy_notional, cfg) + sell_notional_cost(sell_notional, cfg)
    return Trade(
        symbol=pos.symbol,
        buy_date=pos.buy_date,
        sell_date=sell_date,
        buy_hhmm=1500,
        sell_hhmm=fill.time_hhmm,
        shares=pos.shares,
        buy_px=pos.cost,
        sell_px=fill.price,
        open_t1=0.0,
        px_1445=pos.px_1445,
        overnight_ret=0.0,
        morning_ret=0.0,
        gross_ret=fill.price / pos.cost - 1.0,
        net_ret=(sell_notional - buy_notional - fees) / buy_notional,
        t1_weekday=sell_date.weekday(),
        year=sell_date.year,
        exit_reason=fill.reason,
        source=source,
    )


def attach_open_legs(trade: Trade, open_t1: float) -> Trade:
    if trade.buy_px <= 0 or open_t1 <= 0:
        return trade
    trade.open_t1 = open_t1
    trade.overnight_ret = open_t1 / trade.buy_px - 1.0
    trade.morning_ret = trade.sell_px / open_t1 - 1.0
    return trade
