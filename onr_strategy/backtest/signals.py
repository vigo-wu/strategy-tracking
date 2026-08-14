# coding: utf-8
"""基础池 + 14:45 因子。决策只用 <= t_decision 的分钟线。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from onr_strategy.backtest.config import OnrConfig
from onr_strategy.backtest.data import (
    MarketStore,
    compact_row,
    daily_history,
    daily_row,
    last_at_or_before,
    limit_up_price,
    slice_hhmm,
    trading_age,
)


@dataclass
class FactorSnapshot:
    symbol: str
    px_decision: Optional[float] = None
    px_tail_start: Optional[float] = None
    day_high: Optional[float] = None
    ret: Optional[float] = None
    shadow: Optional[float] = None
    momentum: Optional[float] = None
    pullback: Optional[float] = None
    vol_ratio: Optional[float] = None
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma5_slope: Optional[float] = None
    ma10_slope: Optional[float] = None
    large_buy: Optional[float] = None
    industry_ret: Optional[float] = None
    industry_rank_q: Optional[float] = None
    reasons: Tuple[str, ...] = ()
    passed: bool = False


def universe_ok(store: MarketStore, symbol: str, day: date, cfg: OnrConfig) -> Tuple[bool, str]:
    meta = store.meta(symbol)
    if cfg.exclude_bj:
        from onr_strategy.backtest.data import is_bj

        if is_bj(symbol):
            return False, "bj"
    if meta.is_st or (meta.name and ("ST" in meta.name.upper() or "退" in meta.name)):
        return False, "st"
    days = store.trading_days()
    age = trading_age(days, meta.list_date, day)
    if age is not None and age < cfg.ipo_trading_days:
        return False, "ipo"
    row = daily_row(store, symbol, day)
    if row is None:
        return False, "no_daily"
    if int(row.get("suspended") or 0):
        return False, "halt"
    hist = daily_history(store, symbol, day)
    if len(hist) < cfg.adv_days:
        return False, "adv_hist"
    adv = float(hist.tail(cfg.adv_days)["amount"].mean())
    if adv <= cfg.adv_min_amount:
        return False, "adv"
    cap = float(row.get("float_mkt_cap") or 0)
    if cap < cfg.float_cap_min or cap > cfg.float_cap_max:
        return False, "cap"
    return True, ""


def _ma(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return float(sum(values) / len(values))


def _completed_closes(hist: pd.DataFrame) -> List[float]:
    return [float(x) for x in hist["close"].tolist()]


def compute_mas(hist: pd.DataFrame, px: float) -> Dict[str, Optional[float]]:
    closes = _completed_closes(hist)
    out = {
        "ma5": None,
        "ma10": None,
        "ma20": None,
        "ma5_slope": None,
        "ma10_slope": None,
    }
    if len(closes) < 19:
        return out
    out["ma5"] = _ma(closes[-4:] + [px])
    out["ma10"] = _ma(closes[-9:] + [px])
    out["ma20"] = _ma(closes[-19:] + [px])
    ma5_y = _ma(closes[-5:])
    ma10_y = _ma(closes[-10:])
    if out["ma5"] is not None and ma5_y is not None:
        out["ma5_slope"] = out["ma5"] - ma5_y
    if out["ma10"] is not None and ma10_y is not None:
        out["ma10_slope"] = out["ma10"] - ma10_y
    return out


def tail_pullback(tail: pd.DataFrame) -> Optional[float]:
    if tail is None or tail.empty:
        return None
    peak = None
    worst = 0.0
    for close in tail["close"].astype(float):
        peak = close if peak is None else max(peak, close)
        if peak > 0:
            worst = max(worst, (peak - close) / peak)
    return worst


def vol_ratio(mins: pd.DataFrame, cfg: OnrConfig) -> Optional[float]:
    body = slice_hhmm(mins, cfg.t_open, cfg.t_tail_start, end_inclusive=False)
    tail = slice_hhmm(mins, cfg.t_tail_start, cfg.t_decision, end_inclusive=True)
    if body.empty or tail.empty:
        return None
    b = float(body["volume"].mean())
    t = float(tail["volume"].mean())
    if b <= 0:
        return None
    return t / b


def index_dumped(store: MarketStore, day: date, cfg: OnrConfig) -> Tuple[bool, str]:
    """True = 尾盘放量下跌，当日禁开。缺数据按 index_missing_policy。"""
    if not cfg.use_index_filter:
        return False, "off"
    missing = 0
    for code in cfg.index_codes:
        raw = store.index_minutes(code, day)
        if raw is None or raw.empty:
            missing += 1
            continue
        cutoff = slice_hhmm(raw, cfg.t_open, cfg.t_decision, end_inclusive=True)
        p0 = last_at_or_before(cutoff, cfg.t_tail_start)
        p1 = last_at_or_before(cutoff, cfg.t_decision)
        if p0 is None or p1 is None or p0 <= 0:
            missing += 1
            continue
        ret = p1 / p0 - 1.0
        vr = vol_ratio(cutoff, cfg)
        if ret < cfg.index_dump_ret and vr is not None and vr >= cfg.index_dump_vol_ratio:
            return True, code
    if missing == len(cfg.index_codes):
        if cfg.index_missing_policy == "block":
            return True, "index_missing"
        return False, "index_missing_pass"
    return False, ""


def industry_quantile(
    store: MarketStore,
    sw2: str,
    day: date,
    cfg: OnrConfig,
) -> Optional[float]:
    keys = store.industry_keys(day)
    if not keys or not sw2:
        return None
    rets = []
    mine = None
    for k in keys:
        r = store.industry_ret_1445(k, day)
        if r is None:
            continue
        rets.append((k, r))
        if k == sw2:
            mine = r
    if mine is None or not rets:
        return None
    rets.sort(key=lambda x: x[1], reverse=True)
    rank = next(i for i, (k, _) in enumerate(rets) if k == sw2)
    n = len(rets)
    return (rank + 1) / n


def _num(row: dict, key: str) -> Optional[float]:
    if row is None or key not in row:
        return None
    val = row[key]
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def snapshot_from_compact(
    store: MarketStore,
    symbol: str,
    day: date,
    cfg: OnrConfig,
    row: dict,
    cutoff: int,
) -> FactorSnapshot:
    snap = FactorSnapshot(symbol=symbol)
    daily = daily_row(store, symbol, day)
    if daily is None:
        snap.reasons = ("no_daily",)
        return snap
    pre = float(daily["pre_close"]) if pd.notna(daily.get("pre_close")) else None
    if cutoff <= cfg.t_decision:
        px = _num(row, "px_1445")
        day_high = _num(row, "high_1445")
        pullback = _num(row, "pullback_1445")
    else:
        px = _num(row, "px_1450")
        day_high = _num(row, "high_1450")
        pullback = _num(row, "pullback_1445")
    p_tail = _num(row, "px_1430")
    snap.px_decision = px
    snap.px_tail_start = p_tail
    snap.day_high = day_high
    if px is None or px <= 0 or pre is None or pre <= 0:
        snap.reasons = ("px",)
        return snap
    snap.ret = px / pre - 1.0
    if day_high is not None:
        snap.shadow = (day_high - px) / px
    if p_tail is not None and p_tail > 0:
        snap.momentum = px / p_tail - 1.0
    snap.pullback = pullback
    snap.vol_ratio = _num(row, "vol_ratio")
    hist = daily_history(store, symbol, day)
    mas = compute_mas(hist, px)
    snap.ma5, snap.ma10, snap.ma20 = mas["ma5"], mas["ma10"], mas["ma20"]
    snap.ma5_slope, snap.ma10_slope = mas["ma5_slope"], mas["ma10_slope"]
    snap.large_buy = store.large_buy_ratio(symbol, day)
    meta = store.meta(symbol)
    snap.industry_ret = store.industry_ret_1445(meta.sw2, day) if meta.sw2 else None
    snap.industry_rank_q = industry_quantile(store, meta.sw2, day, cfg)
    return snap


def snapshot_at(
    store: MarketStore,
    symbol: str,
    day: date,
    cfg: OnrConfig,
    *,
    cutoff: Optional[int] = None,
) -> FactorSnapshot:
    t_cut = cfg.t_decision if cutoff is None else cutoff
    packed = compact_row(store, symbol, day)
    if packed:
        return snapshot_from_compact(store, symbol, day, cfg, packed, t_cut)
    snap = FactorSnapshot(symbol=symbol)
    row = daily_row(store, symbol, day)
    if row is None:
        snap.reasons = ("no_daily",)
        return snap
    pre = float(row["pre_close"]) if pd.notna(row.get("pre_close")) else None
    raw = store.minutes(symbol, day)
    if raw is None or raw.empty:
        snap.reasons = ("no_minute",)
        return snap
    mins = slice_hhmm(raw, cfg.t_open, t_cut, end_inclusive=True)
    if mins.empty:
        snap.reasons = ("no_minute",)
        return snap
    px = last_at_or_before(mins, t_cut)
    p_tail = last_at_or_before(mins, cfg.t_tail_start)
    day_high = float(mins["high"].max())
    snap.px_decision = px
    snap.px_tail_start = p_tail
    snap.day_high = day_high
    if px is None or px <= 0 or pre is None or pre <= 0:
        snap.reasons = ("px",)
        return snap
    snap.ret = px / pre - 1.0
    snap.shadow = (day_high - px) / px
    if p_tail is not None and p_tail > 0:
        snap.momentum = px / p_tail - 1.0
    tail = slice_hhmm(mins, cfg.t_tail_start, t_cut, end_inclusive=True)
    snap.pullback = tail_pullback(tail)
    snap.vol_ratio = vol_ratio(mins, cfg)
    hist = daily_history(store, symbol, day)
    mas = compute_mas(hist, px)
    snap.ma5, snap.ma10, snap.ma20 = mas["ma5"], mas["ma10"], mas["ma20"]
    snap.ma5_slope, snap.ma10_slope = mas["ma5_slope"], mas["ma10_slope"]
    snap.large_buy = store.large_buy_ratio(symbol, day)
    meta = store.meta(symbol)
    snap.industry_ret = store.industry_ret_1445(meta.sw2, day) if meta.sw2 else None
    snap.industry_rank_q = industry_quantile(store, meta.sw2, day, cfg)
    return snap


def evaluate_snapshot(snap: FactorSnapshot, cfg: OnrConfig, *, at_recheck: bool = False) -> FactorSnapshot:
    reasons: List[str] = []
    if snap.px_decision is None:
        reasons.append("px")
        snap.reasons = tuple(reasons)
        snap.passed = False
        return snap
    if cfg.use_ret_window:
        if snap.ret is None or snap.ret < cfg.ret_min:
            reasons.append("ret_low")
        elif snap.ret > cfg.ret_max:
            reasons.append("ret_high")
    if cfg.use_shadow:
        if snap.shadow is None or snap.shadow >= cfg.shadow_max:
            reasons.append("shadow")
    if at_recheck:
        snap.reasons = tuple(reasons)
        snap.passed = not reasons
        return snap
    if cfg.use_ma:
        ok_stack = (
            snap.ma5 is not None
            and snap.ma10 is not None
            and snap.ma20 is not None
            and snap.px_decision >= snap.ma5 > snap.ma10 > snap.ma20
            and snap.ma5_slope is not None
            and snap.ma10_slope is not None
            and snap.ma5_slope > 0
            and snap.ma10_slope > 0
        )
        if not ok_stack:
            reasons.append("ma")
    if cfg.use_momentum:
        if snap.momentum is None or snap.momentum <= cfg.momentum_min:
            reasons.append("mom")
    if cfg.use_pullback:
        if snap.pullback is None or snap.pullback >= cfg.pullback_max:
            reasons.append("pullback")
    if cfg.use_vol_ratio:
        if snap.vol_ratio is None or snap.vol_ratio < cfg.vol_ratio_min:
            reasons.append("vol_ratio")
    if cfg.use_large_order:
        if snap.large_buy is None:
            reasons.append("large_order_no_data")
        elif snap.large_buy <= cfg.large_buy_min:
            reasons.append("large_order")
    if cfg.use_industry:
        if snap.industry_rank_q is None:
            reasons.append("industry_no_data")
        elif snap.industry_rank_q > cfg.industry_top_q:
            reasons.append("industry")
    snap.reasons = tuple(reasons)
    snap.passed = not reasons
    return snap


def score_symbol(store: MarketStore, symbol: str, day: date, cfg: OnrConfig) -> FactorSnapshot:
    ok, why = universe_ok(store, symbol, day, cfg)
    if not ok:
        snap = FactorSnapshot(symbol=symbol, reasons=(why,))
        return snap
    snap = snapshot_at(store, symbol, day, cfg, cutoff=cfg.t_decision)
    snap = evaluate_snapshot(snap, cfg, at_recheck=False)
    if snap.passed and cfg.use_recheck_1450:
        later = snapshot_at(store, symbol, day, cfg, cutoff=cfg.t_recheck)
        later = evaluate_snapshot(later, cfg, at_recheck=True)
        if not later.passed:
            snap.passed = False
            snap.reasons = snap.reasons + tuple("recheck_" + r for r in later.reasons)
            snap.px_decision = later.px_decision
            snap.ret = later.ret
            snap.shadow = later.shadow
    return snap


def select_names(
    store: MarketStore,
    day: date,
    cfg: OnrConfig,
    *,
    exclude: Sequence[str] = (),
) -> Tuple[List[FactorSnapshot], str]:
    dumped, dump_why = index_dumped(store, day, cfg)
    if dumped:
        return [], "index_dump:%s" % dump_why
    held = set(exclude)
    passed: List[FactorSnapshot] = []
    for symbol in store.symbols():
        if symbol in held:
            continue
        snap = score_symbol(store, symbol, day, cfg)
        if snap.passed:
            passed.append(snap)
    passed.sort(
        key=lambda s: (
            -(s.momentum if s.momentum is not None else -1e9),
            float(daily_row(store, s.symbol, day)["float_mkt_cap"]),
        )
    )
    return passed[: cfg.max_names], dump_why


def cannot_buy_limit_up(store: MarketStore, symbol: str, day: date) -> bool:
    row = daily_row(store, symbol, day)
    if row is None:
        return True
    meta = store.meta(symbol)
    pre = float(row["pre_close"])
    up = limit_up_price(pre, symbol, meta.is_st)
    close = float(row["close"])
    return close >= up - 1e-6
