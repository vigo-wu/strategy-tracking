# coding: utf-8
"""日循环：先处理 T+1 可卖，再 14:45 选股，收盘价买入。含同池随机基线。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from onr_strategy.backtest.config import OnrConfig
from onr_strategy.backtest.data import MarketStore, daily_row, last_at_or_before, slice_hhmm
from onr_strategy.backtest.signals import cannot_buy_limit_up, select_names, snapshot_at, universe_ok
from onr_strategy.backtest.trade import (
    Position,
    attach_open_legs,
    buy_fill_price,
    buy_notional_cost,
    exit_fill,
    make_trade,
    sell_notional_cost,
    session_open,
    shares_for_budget,
)


@dataclass
class DayLog:
    date: date
    cash: float
    equity: float
    n_hold: int
    n_buy: int
    n_sell: int
    selected: Tuple[str, ...]
    skip: str
    source: str


@dataclass
class BacktestResult:
    source: str
    cfg: OnrConfig
    trades: List[Trade] = field(default_factory=list)
    days: List[DayLog] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def trades_frame(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([t.__dict__ for t in self.trades])

    def days_frame(self) -> pd.DataFrame:
        if not self.days:
            return pd.DataFrame()
        return pd.DataFrame([d.__dict__ for d in self.days])


def _mark_equity(cash: float, holds: Sequence[Position], store: MarketStore, day: date) -> float:
    eq = cash
    for pos in holds:
        row = daily_row(store, pos.symbol, day)
        px = float(row["close"]) if row is not None else pos.cost
        eq += pos.shares * px
    return eq


def _px_1445(store: MarketStore, symbol: str, day: date, cfg: OnrConfig) -> float:
    snap = snapshot_at(store, symbol, day, cfg, cutoff=cfg.t_decision)
    if snap.px_decision is not None:
        return snap.px_decision
    mins = store.minutes(symbol, day)
    cut = slice_hhmm(mins, cfg.t_open, cfg.t_decision)
    px = last_at_or_before(cut, cfg.t_decision) if cut is not None and not cut.empty else None
    return float(px) if px is not None else 0.0


def _open_t1(store: MarketStore, symbol: str, day: date) -> float:
    px = session_open(store, symbol, day)
    if px is not None:
        return px
    row = daily_row(store, symbol, day)
    return float(row["open"]) if row is not None else 0.0


def _try_buy(
    symbol: str,
    store: MarketStore,
    day: date,
    cfg: OnrConfig,
    cash: float,
    equity: float,
) -> Tuple[Optional[Position], float]:
    row = daily_row(store, symbol, day)
    if row is None or cannot_buy_limit_up(store, symbol, day):
        return None, cash
    close = float(row["close"])
    px = buy_fill_price(close, cfg)
    budget = min(equity * cfg.weight_per_name, cash)
    shares = shares_for_budget(budget, px, cfg.lot_size)
    if shares <= 0:
        return None, cash
    notional = shares * px
    fee = buy_notional_cost(notional, cfg)
    if notional + fee > cash + 1e-6:
        shares = shares_for_budget(cash - fee, px, cfg.lot_size)
        if shares <= 0:
            return None, cash
        notional = shares * px
        fee = buy_notional_cost(notional, cfg)
    cash -= notional + fee
    pos = Position(
        symbol=symbol,
        shares=shares,
        cost=px,
        buy_close=close,
        buy_date=day,
        px_1445=_px_1445(store, symbol, day, cfg),
        hold_days=1,
    )
    return pos, cash


def run_once(
    store: MarketStore,
    cfg: OnrConfig,
    *,
    source: str,
    picker,
) -> BacktestResult:
    result = BacktestResult(source=source, cfg=cfg)
    days = store.trading_days()
    if len(days) < cfg.adv_days + 2:
        result.warnings.append("not_enough_days")
        return result
    cash = cfg.init_cash
    holds: List[Position] = []
    for i, day in enumerate(days):
        n_sell = 0
        still: List[Position] = []
        if i > 0:
            leftover: List[Position] = []
            for pos in holds:
                pos.hold_days = (days.index(day) - days.index(pos.buy_date))
                fill = exit_fill(pos, store, day, cfg)
                if fill is None:
                    leftover.append(pos)
                    continue
                cash += pos.shares * fill.price
                cash -= sell_notional_cost(pos.shares * fill.price, cfg)
                tr = make_trade(pos, fill, day, source, cfg)
                attach_open_legs(tr, _open_t1(store, pos.symbol, day))
                result.trades.append(tr)
                n_sell += 1
            still = leftover
        holds = still
        equity = _mark_equity(cash, holds, store, day)
        selected: List[str] = []
        skip = ""
        n_buy = 0
        slots = cfg.max_names - len(holds)
        if slots > 0 and i < len(days) - 1:
            names, skip = picker(store, day, cfg, tuple(p.symbol for p in holds))
            selected = list(names)
            for symbol in selected[:slots]:
                pos, cash = _try_buy(symbol, store, day, cfg, cash, equity)
                if pos is None:
                    continue
                holds.append(pos)
                n_buy += 1
                equity = _mark_equity(cash, holds, store, day)
        result.days.append(
            DayLog(
                date=day,
                cash=cash,
                equity=_mark_equity(cash, holds, store, day),
                n_hold=len(holds),
                n_buy=n_buy,
                n_sell=n_sell,
                selected=tuple(selected),
                skip=skip,
                source=source,
            )
        )
    return result


def strategy_picker(store, day, cfg, exclude):
    snaps, why = select_names(store, day, cfg, exclude=exclude)
    return [s.symbol for s in snaps], why


def baseline_picker(store, day, cfg, exclude, rng):
    pool = []
    for symbol in store.symbols():
        if symbol in exclude:
            continue
        ok, _ = universe_ok(store, symbol, day, cfg)
        if ok and not cannot_buy_limit_up(store, symbol, day):
            pool.append(symbol)
    if not pool:
        return [], "empty_pool"
    rng.shuffle(pool)
    return pool[: cfg.max_names], "baseline"


def run_backtest(
    store: MarketStore,
    cfg: Optional[OnrConfig] = None,
    *,
    with_baseline: bool = True,
) -> Dict[str, BacktestResult]:
    cfg = cfg or OnrConfig()
    out = {"strategy": run_once(store, cfg, source="strategy", picker=strategy_picker)}
    if with_baseline:
        import random

        rng = random.Random(cfg.baseline_seed)

        def picker(store, day, cfg, exclude, _rng=rng):
            return baseline_picker(store, day, cfg, exclude, _rng)

        out["baseline"] = run_once(store, cfg.with_exit("open"), source="baseline", picker=picker)
    return out


def summarize(result: BacktestResult) -> Dict[str, float]:
    trades = result.trades
    empty = {
        "n_trades": 0.0,
        "n_days": float(len(result.days)),
        "empty_days": float(sum(1 for d in result.days if d.n_hold == 0 and d.n_buy == 0)),
        "mean_net": 0.0,
        "mean_overnight": 0.0,
        "mean_morning": 0.0,
        "win_rate": 0.0,
        "max_names": 0.0,
        "final_equity": result.days[-1].equity if result.days else result.cfg.init_cash,
        "total_return": 0.0,
    }
    if result.days:
        empty["total_return"] = result.days[-1].equity / result.cfg.init_cash - 1.0
        empty["max_names"] = float(max(d.n_hold for d in result.days))
    if not trades:
        return empty
    nets = [t.net_ret for t in trades]
    ovs = [t.overnight_ret for t in trades]
    morn = [t.morning_ret for t in trades]
    empty.update(
        {
            "n_trades": float(len(trades)),
            "mean_net": float(sum(nets) / len(nets)),
            "mean_overnight": float(sum(ovs) / len(ovs)),
            "mean_morning": float(sum(morn) / len(morn)),
            "win_rate": float(sum(1 for x in nets if x > 0) / len(nets)),
        }
    )
    return empty


def split_tables(result: BacktestResult) -> Dict[str, pd.DataFrame]:
    tf = result.trades_frame()
    if tf.empty:
        return {"weekday": pd.DataFrame(), "year": pd.DataFrame()}
    wd = tf.groupby("t1_weekday")[["net_ret", "overnight_ret", "morning_ret"]].mean().reset_index()
    yr = tf.groupby("year")[["net_ret", "overnight_ret", "morning_ret"]].mean().reset_index()
    return {"weekday": wd, "year": yr}


def format_summary(label: str, stats: Dict[str, float]) -> str:
    return (
        "%s  trades=%d  mean_net=%.4f  overnight=%.4f  morning=%.4f  "
        "win=%.2f  max_names=%.0f  final=%.0f  ret=%.4f  empty_days=%.0f"
        % (
            label,
            int(stats["n_trades"]),
            stats["mean_net"],
            stats["mean_overnight"],
            stats["mean_morning"],
            stats["win_rate"],
            stats["max_names"],
            stats["final_equity"],
            stats["total_return"],
            stats["empty_days"],
        )
    )
