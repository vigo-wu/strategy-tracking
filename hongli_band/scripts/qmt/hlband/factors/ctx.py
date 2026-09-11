# === hlband/factors/ctx.py ===
def _cross_down(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev >= b_prev) and (a_now < b_now)


def _cross_up(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev <= b_prev) and (a_now > b_now)


def _eval_weekly(closes_w):
    """返回 (bull, bear, detail)。
    多头(仅日志): MA5>MA13 且 DIF>0 且红柱 且生命线未明显走平。
    空头: 收盘破 MA34（W_MA_LIFE）或 DIF/DEA 零轴下死叉。"""
    detail = {
        "ma5": None,
        "ma10": None,
        "ma30": None,
        "dif": None,
        "dea": None,
        "hist": None,
        "close": None,
    }
    ma5 = _price_ma(closes_w, W_MA_FAST)
    ma10 = _price_ma(closes_w, 13)
    ma30 = _price_ma(closes_w, W_MA_LIFE)
    macd = _calc_macd(closes_w)
    if ma5 is None or ma10 is None or ma30 is None or macd is None:
        return False, False, detail
    dif, dea, hist = macd
    i = len(closes_w) - 1
    if i < 1:
        return False, False, detail
    c = float(closes_w[i])
    m5 = _last_valid(ma5, i)
    m10 = _last_valid(ma10, i)
    m30 = _last_valid(ma30, i)
    m30_prev = _last_valid(ma30, i - 1)
    d0 = _last_valid(dif, i)
    e0 = _last_valid(dea, i)
    h0 = _last_valid(hist, i)
    h1 = _last_valid(hist, i - 1)
    d1 = _last_valid(dif, i - 1)
    e1 = _last_valid(dea, i - 1)
    d2 = _last_valid(dif, i - 2) if i >= 2 else None
    e2 = _last_valid(dea, i - 2) if i >= 2 else None
    golden_now = _cross_up(d1, e1, d0, e0)
    golden_prev = _cross_up(d2, e2, d1, e1) if i >= 2 else False
    slope_weeks = int(globals().get("W_MA30_SLOPE_WEEKS", 2) or 2)
    slope_up_n = False
    if slope_weeks > 0 and i >= slope_weeks:
        slope_up_n = True
        for k in range(slope_weeks):
            a = _last_valid(ma30, i - k)
            b = _last_valid(ma30, i - k - 1)
            if a is None or b is None or not (a > b):
                slope_up_n = False
                break
    detail.update(
        {
            "ma5": m5,
            "ma10": m10,
            "ma30": m30,
            "ma30_prev": m30_prev,
            "ma30_slope_up2": slope_up_n,
            "dif": d0,
            "dea": e0,
            "dif_prev": d1,
            "dea_prev": e1,
            "hist": h0,
            "hist_prev": h1,
            "macd_golden_now": golden_now,
            "macd_golden_prev": golden_prev,
            "close": c,
        }
    )
    if None in (m5, m10, m30, d0, e0, h0):
        return False, False, detail

    ma30_ok = (m30_prev is None) or (m30 >= m30_prev * 0.998)
    bull = (m5 > m10) and (d0 > 0) and (h0 > 0) and ma30_ok
    death_below = _cross_down(d1, e1, d0, e0) and (d0 < 0) and (e0 < 0)
    bear = (c < m30) or death_below
    return bull, bear, detail


def _vol_pullback_confirm_need():
    """最少 1：当天缩量即可；勿用 `x or 2`（0 会被当成缺省翻成 2）。"""
    raw = globals().get("VOL_PULLBACK_CONFIRM_DAYS", 2)
    try:
        n = int(2 if raw is None else raw)
    except Exception:
        n = 2
    return max(1, n)


def _build_market_features(closes, volumes, highs=None, lows=None):
    try:
        mid_n = int(D_MA_MID or 0)
    except (TypeError, ValueError):
        mid_n = 0
    try:
        slow_n = int(D_MA_SLOW or 0)
    except (TypeError, ValueError):
        slow_n = 0
    ma20 = _price_ma(closes, mid_n) if mid_n > 0 and closes is not None else None
    ma60 = _price_ma(closes, slow_n) if slow_n > 0 and closes is not None else None
    vol10 = _sma(volumes, VOL_PULLBACK_N) if volumes is not None else None
    vol20 = _sma(volumes, VOL_DRY_N) if volumes is not None else None
    i = (len(closes) - 1) if closes is not None else -1
    price = float(closes[i]) if closes is not None and i >= 0 else None
    m20 = _last_valid(ma20, i) if ma20 is not None and i >= 0 else None
    m60 = _last_valid(ma60, i) if ma60 is not None and i >= 0 else None
    v10 = _last_valid(vol10, i) if vol10 is not None and i >= 0 else None
    v20 = _last_valid(vol20, i) if vol20 is not None and i >= 0 else None
    return {
        "closes": closes,
        "volumes": volumes,
        "highs": highs,
        "lows": lows,
        "mid_n": mid_n,
        "slow_n": slow_n,
        "ma20": ma20,
        "ma60": ma60,
        "vol10": vol10,
        "vol20": vol20,
        "i": i,
        "price": price,
        "m20": m20,
        "m60": m60,
        "v10": v10,
        "v20": v20,
        "vol_need": _vol_pullback_confirm_need(),
    }


def _lot_state_from(lot):
    if not isinstance(lot, dict):
        lot = {}
    cost = float(lot.get("price") or 0)
    peak = lot.get("hold_peak")
    try:
        bars = int(lot.get("hold_bars") or 0)
    except Exception:
        bars = 0
    return {
        "lot": lot,
        "cost": cost,
        "hold_peak": peak,
        "hold_bars": bars,
        "time_force_trend_skip": bool(lot.get("time_force_trend_skip")),
        "hold_max_ret": lot.get("hold_max_ret"),
    }


def _build_factor_ctx(
    closes,
    volumes,
    highs=None,
    lows=None,
    w_detail=None,
    weekly_bear=False,
    weekly_bull=False,
    lot=None,
    market=None,
):
    if market is None:
        market = _build_market_features(closes, volumes, highs, lows)
    else:
        market = dict(market)
    market["w_detail"] = w_detail or {}
    market["highs"] = highs if highs is not None else market.get("highs")
    market["lows"] = lows if lows is not None else market.get("lows")
    market["closes_w"] = market.get("closes_w")
    st = _lot_state_from(lot)
    st["w_bear_streak"] = int(getattr(A, "_w_bear_streak", 0) or 0)
    return {
        "market": market,
        "state": st,
        "clock": {
            "weekly_bear": bool(weekly_bear),
            "weekly_bull": bool(weekly_bull),
        },
        "_tf_hook": None,
    }


def _ctx_with_lot(ctx, lot):
    out = {
        "market": ctx.get("market") or {},
        "clock": ctx.get("clock") or {},
        "state": _lot_state_from(lot),
        "_tf_hook": None,
    }
    out["state"]["w_bear_streak"] = int(
        (ctx.get("state") or {}).get("w_bear_streak")
        or getattr(A, "_w_bear_streak", 0)
        or 0
    )
    return out
