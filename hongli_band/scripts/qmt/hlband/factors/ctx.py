# === hlband/factors/ctx.py ===
def _vol_pullback_confirm_need():
    """最少 1：当天缩量即可；勿用 `x or 2`（0 会被当成缺省翻成 2）。"""
    raw = globals().get("VOL_PULLBACK_CONFIRM_DAYS", 2)
    try:
        n = int(2 if raw is None else raw)
    except Exception:
        n = 2
    return max(1, n)


def _weekly_market_features(closes_w):
    """周线 MA/MACD 进 ctx.market；不判多空。"""
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
        return detail
    dif, dea, hist = macd
    i = len(closes_w) - 1
    if i < 1:
        return detail
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
    return detail


def _weekly_bull_from_detail(detail):
    """仅日志；不成因子。"""
    if not detail:
        return False
    m5 = detail.get("ma5")
    m10 = detail.get("ma10")
    m30 = detail.get("ma30")
    m30_prev = detail.get("ma30_prev")
    d0 = detail.get("dif")
    h0 = detail.get("hist")
    if None in (m5, m10, m30, d0, h0):
        return False
    ma30_ok = (m30_prev is None) or (m30 >= m30_prev * 0.998)
    return (m5 > m10) and (d0 > 0) and (h0 > 0) and ma30_ok


def _factor_daily_features(closes, volumes):
    detail = {
        "ma20": None,
        "ma60": None,
        "vol10": None,
        "vol20": None,
        "vol_need": 1,
        "vol_streak": 0,
        "mid_n": 0,
        "slow_n": 0,
        "i": -1,
        "price": None,
        "vol": None,
        "v10": None,
        "v20": None,
    }
    if closes is None or volumes is None:
        return False, detail
    try:
        mid_n = int(D_MA_MID or 0)
    except (TypeError, ValueError):
        mid_n = 0
    try:
        slow_n = int(D_MA_SLOW or 0)
    except (TypeError, ValueError):
        slow_n = 0
    detail["mid_n"] = mid_n
    detail["slow_n"] = slow_n
    ma20 = _price_ma(closes, mid_n) if mid_n > 0 else None
    ma60 = _price_ma(closes, slow_n) if slow_n > 0 else None
    vol10 = _sma(volumes, VOL_PULLBACK_N)
    vol20 = _sma(volumes, VOL_DRY_N)
    if vol10 is None or vol20 is None:
        return False, detail
    i = len(closes) - 1
    vol_need = _vol_pullback_confirm_need()
    detail["vol_need"] = vol_need
    detail["i"] = i
    if i < max(2, vol_need):
        return False, detail
    price = float(closes[i])
    vol = float(volumes[i])
    m20 = _last_valid(ma20, i) if ma20 is not None else None
    m60 = _last_valid(ma60, i) if ma60 is not None else None
    v10 = _last_valid(vol10, i)
    v20 = _last_valid(vol20, i)
    detail.update(
        {
            "ma20": m20,
            "ma60": m60,
            "vol10": vol10,
            "vol20": vol20,
            "price": price,
            "vol": vol,
            "v10": v10,
            "v20": v20,
            "closes": closes,
            "volumes": volumes,
        }
    )
    return True, detail


def _build_factor_ctx(
    closes=None,
    volumes=None,
    highs=None,
    lows=None,
    w_detail=None,
    price=None,
    state=None,
    clock=None,
):
    ready, daily = _factor_daily_features(closes, volumes)
    if price is None:
        price = daily.get("price")
    market = {
        "close": price,
        "closes": closes,
        "volumes": volumes,
        "highs": highs,
        "lows": lows,
        "w_detail": w_detail or {},
        "daily_ready": ready,
        "daily_detail": daily,
        "ma20": daily.get("ma20"),
        "ma60": daily.get("ma60"),
        "vol10": daily.get("vol10"),
        "vol20": daily.get("vol20"),
        "mid_n": daily.get("mid_n"),
        "slow_n": daily.get("slow_n"),
        "i": daily.get("i"),
        "vol": daily.get("vol"),
        "v10": daily.get("v10"),
        "v20": daily.get("v20"),
        "vol_need": daily.get("vol_need"),
    }
    return {
        "market": market,
        "state": dict(state or {}),
        "clock": dict(clock or {}),
    }


def _factor_ctx_bind_state(ctx, **fields):
    st = dict((ctx or {}).get("state") or {})
    st.update(fields)
    out = dict(ctx or {})
    out["state"] = st
    return out
