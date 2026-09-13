# === hlband/factors/ctx.py ===
def _factor_tiers_as_lists(raw):
    """trail_stop.tiers → list of lists，避免指纹把 tuple 打成字符串。"""
    out = []
    for row in raw or ():
        seq = list(row)
        while len(seq) < 4:
            seq.append(None)
        lo, hi, gb, fl = seq[0], seq[1], seq[2], seq[3]
        out.append(
            [
                float(lo),
                None if hi is None else float(hi),
                float(gb),
                None if fl is None else float(fl),
            ]
        )
    return out


def _factor_param(ctx, fid, key, default=None):
    """ctx.params > RECIPE.factor_params。缺键用调用方 default（数字字面量）。"""
    extra = ((ctx or {}).get("params") or {}).get(fid) or {}
    if key in extra:
        return extra[key]
    rec = (globals().get("RECIPE") or {}).get("factor_params") or {}
    block = rec.get(fid) or {}
    if key in block:
        return block[key]
    return default


def _factor_params_apply_global(params):
    """只合进 RECIPE.factor_params，按 id 再按 key 合并。"""
    if not isinstance(params, dict):
        return
    rec = globals().get("RECIPE")
    if not isinstance(rec, dict):
        return
    fp = rec.get("factor_params")
    if not isinstance(fp, dict):
        rec["factor_params"] = {}
        fp = rec["factor_params"]
    for fid, incoming in params.items():
        if not isinstance(incoming, dict):
            continue
        cur = fp.get(fid)
        if not isinstance(cur, dict):
            fp[fid] = {}
            cur = fp[fid]
        cur.update(incoming)
        if fid == "trail_stop" and "tiers" in cur:
            cur["tiers"] = _factor_tiers_as_lists(cur.get("tiers"))


def _structure_int(block, key, default):
    raw = (block or {}).get(key)
    try:
        return int(default if raw is None else raw)
    except (TypeError, ValueError):
        return int(default)


def _structure_windows():
    """只读 RECIPE.structure。缺键用数字字面量。"""
    rec = (globals().get("RECIPE") or {}).get("structure") or {}
    d_ma = rec.get("d_ma") or {}
    w_ma = rec.get("w_ma") or {}
    macd = rec.get("macd") or {}
    atr = rec.get("atr") or {}
    return {
        "d_ma": {
            "mid": _structure_int(d_ma, "mid", 20),
            "slow": _structure_int(d_ma, "slow", 60),
        },
        "w_ma": {
            "fast": _structure_int(w_ma, "fast", 5),
            "mid": _structure_int(w_ma, "mid", 13),
            "life": _structure_int(w_ma, "life", 34),
        },
        "macd": {
            "fast": _structure_int(macd, "fast", 12),
            "slow": _structure_int(macd, "slow", 26),
            "signal": _structure_int(macd, "signal", 9),
        },
        "atr": {
            "n": _structure_int(atr, "n", 14),
        },
    }


def _structure_apply_global(params):
    """只合进 RECIPE.structure，按段再按 key 合并。"""
    if not isinstance(params, dict):
        return
    rec = globals().get("RECIPE")
    if not isinstance(rec, dict):
        return
    st = rec.get("structure")
    if not isinstance(st, dict):
        rec["structure"] = {}
        st = rec["structure"]
    for fid, incoming in params.items():
        if not isinstance(incoming, dict):
            continue
        cur = st.get(fid)
        if not isinstance(cur, dict):
            st[fid] = {}
            cur = st[fid]
        cur.update(incoming)


def _vol_pullback_confirm_need():
    """最少 1：当天缩量即可；勿用 `x or 2`（0 会被当成缺省翻成 2）。"""
    raw = _factor_param(None, "pullback_vol", "confirm_days")
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
    win = _structure_windows()
    w_ma = win["w_ma"]
    mc = win["macd"]
    ma5 = _price_ma(closes_w, w_ma["fast"])
    ma10 = _price_ma(closes_w, w_ma["mid"])
    ma30 = _price_ma(closes_w, w_ma["life"])
    macd = _calc_macd(closes_w, mc["fast"], mc["slow"], mc["signal"])
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
    raw_slope = _factor_param(None, "w_slope", "slope_weeks")
    try:
        slope_weeks = int(raw_slope if raw_slope is not None else 2)
    except (TypeError, ValueError):
        slope_weeks = 2
    if not slope_weeks:
        slope_weeks = 2
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
    d_ma = _structure_windows()["d_ma"]
    try:
        mid_n = int(d_ma.get("mid") or 0)
    except (TypeError, ValueError):
        mid_n = 0
    try:
        slow_n = int(d_ma.get("slow") or 0)
    except (TypeError, ValueError):
        slow_n = 0
    detail["mid_n"] = mid_n
    detail["slow_n"] = slow_n
    ma20 = _price_ma(closes, mid_n) if mid_n > 0 else None
    ma60 = _price_ma(closes, slow_n) if slow_n > 0 else None
    raw_vn = _factor_param(None, "pullback_vol", "vol_n")
    raw_dn = _factor_param(None, "vol_dry", "n")
    try:
        vol_n = int(10 if raw_vn is None else raw_vn)
    except (TypeError, ValueError):
        vol_n = 10
    try:
        dry_n = int(20 if raw_dn is None else raw_dn)
    except (TypeError, ValueError):
        dry_n = 20
    vol10 = _sma(volumes, vol_n)
    vol20 = _sma(volumes, dry_n)
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
    try:
        atr_n = int(_structure_windows()["atr"]["n"] or 0)
    except (TypeError, ValueError, KeyError):
        atr_n = 0
    atr_arr = _calc_atr(highs, lows, closes, atr_n) if atr_n > 0 else None
    atr = _last_valid(atr_arr) if atr_arr is not None else None
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
        "atr": atr,
        "atr_n": atr_n,
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
