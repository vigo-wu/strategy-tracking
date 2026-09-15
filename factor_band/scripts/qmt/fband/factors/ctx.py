# === fband/factors/ctx.py ===
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


def _structure_deep_copy(src):
    """递归深拷贝 structure / 嵌套 dict。"""
    if not isinstance(src, dict):
        return src
    out = {}
    for k, v in src.items():
        out[str(k)] = _structure_deep_copy(v) if isinstance(v, dict) else v
    return out


def _structure_deep_merge(dst, incoming):
    """递归按键合并；两边都是 dict 则下钻，否则覆盖。"""
    if not isinstance(incoming, dict):
        return dst
    if not isinstance(dst, dict):
        return _structure_deep_copy(incoming)
    for k, v in incoming.items():
        key = str(k)
        if isinstance(v, dict):
            cur = dst.get(key)
            if not isinstance(cur, dict):
                dst[key] = {}
                cur = dst[key]
            _structure_deep_merge(cur, v)
        else:
            dst[key] = v
    return dst


_STRUCTURE_DELETED_ROOTS = frozenset({"d_ma", "w_ma"})
_STRUCTURE_MA_ROOTS = frozenset({"ema", "sma"})


def _structure_ma_period_block(alg_block, period, defaults):
    """从 ema/sma 段取一周期窗；缺键用 defaults（三元组 mid/slow/trend）。"""
    block = (alg_block or {}).get(period) or {}
    if block and not isinstance(block, dict):
        raise ValueError("RECIPE.structure 周期段须为 dict：%s" % period)
    mid_d, slow_d, trend_d = defaults
    return {
        "mid": _structure_int(block, "mid", mid_d),
        "slow": _structure_int(block, "slow", slow_d),
        "trend": _structure_int(block, "trend", trend_d),
    }


def _structure_reject_deleted(rec):
    for bad in _STRUCTURE_DELETED_ROOTS:
        if bad in (rec or {}):
            raise ValueError(
                "已删除的 structure 段 %s：请写 structure.ema|sma.<period>.<window>"
                % bad
            )


def _structure_validate_ma_periods(alg_block, alg_name):
    """周期键须 ∈ _VALID_PERIODS。"""
    if not isinstance(alg_block, dict):
        return
    valid = globals().get("_VALID_PERIODS") or ()
    valid_set = frozenset(valid)
    for period in alg_block.keys():
        p = str(period)
        if valid_set and p not in valid_set:
            raise ValueError(
                "RECIPE.structure.%s 周期键须 ∈ _VALID_PERIODS，收到 %s" % (alg_name, p)
            )


def _structure_windows():
    """只读 RECIPE.structure。缺键用数字字面量。物化 ema/sma × 1d/1w。"""
    rec = (globals().get("RECIPE") or {}).get("structure") or {}
    _structure_reject_deleted(rec)
    ema = rec.get("ema") or {}
    sma = rec.get("sma") or {}
    if ema and not isinstance(ema, dict):
        raise ValueError("RECIPE.structure.ema 须为 dict")
    if sma and not isinstance(sma, dict):
        raise ValueError("RECIPE.structure.sma 须为 dict")
    _structure_validate_ma_periods(ema, "ema")
    _structure_validate_ma_periods(sma, "sma")
    macd = rec.get("macd") or {}
    atr = rec.get("atr") or {}
    keltner = rec.get("keltner") or {}
    return {
        "ema": {
            "1d": _structure_ma_period_block(ema, "1d", (20, 60, 120)),
            "1w": _structure_ma_period_block(ema, "1w", (5, 13, 34)),
        },
        "sma": {
            "1d": _structure_ma_period_block(sma, "1d", (0, 0, 0)),
            "1w": _structure_ma_period_block(sma, "1w", (0, 0, 0)),
        },
        "macd": {
            "fast": _structure_int(macd, "fast", 12),
            "slow": _structure_int(macd, "slow", 26),
            "signal": _structure_int(macd, "signal", 9),
        },
        "atr": {
            "n": _structure_int(atr, "n", 14),
        },
        "keltner": {
            "ema_n": _structure_int(keltner, "ema_n", 20),
            "atr_n": _structure_int(keltner, "atr_n", 20),
        },
    }


def _structure_apply_global(params):
    """只合进 RECIPE.structure，递归按算法→周期→窗合并。"""
    if not isinstance(params, dict):
        return
    _structure_reject_deleted(params)
    for alg in _STRUCTURE_MA_ROOTS:
        block = params.get(alg)
        if block is not None:
            _structure_validate_ma_periods(block if isinstance(block, dict) else {}, alg)
    rec = globals().get("RECIPE")
    if not isinstance(rec, dict):
        return
    st = rec.get("structure")
    if not isinstance(st, dict):
        rec["structure"] = {}
        st = rec["structure"]
    _structure_deep_merge(st, params)


def _structure_ma_need_n(period, window):
    """暖机：同周期同窗取 ema/sma 的 max（仅 >0）。"""
    win = _structure_windows()
    best = 0
    for alg in ("ema", "sma"):
        try:
            n = int((win.get(alg) or {}).get(period, {}).get(window) or 0)
        except (TypeError, ValueError, AttributeError):
            n = 0
        if n > best:
            best = n
    return best


_MARKET_TAGS = frozenset(
    {
        "d_ma_mid",
        "d_ma_slow",
        "d_ma_trend",
        "vol_pb",
        "vol_kc",
        "atr",
        "keltner",
        "weekly",
    }
)

_LEAF_MARKET_NEED = {
    "pullback_vol": frozenset({"d_ma_mid", "d_ma_slow", "vol_pb"}),
    "keltner_vol": frozenset({"keltner", "vol_kc"}),
    "above_ema": frozenset({"d_ma_trend"}),
    "scale_arm": frozenset({"weekly"}),
    "stop_loss": frozenset(),
    "atr_stop": frozenset({"atr"}),
    "trail_stop": frozenset(),
    "atr_trail_stop": frozenset({"atr"}),
    "time_force": frozenset({"d_ma_slow"}),
}


def _market_need(recipe=None):
    """启用叶子对应的 ctx / 暖机标签。未知 AST id → 全标签。"""
    walk = globals().get("_recipe_compute_leaves")
    if not callable(walk):
        return set(_MARKET_TAGS)
    out = set()
    for fid in walk(recipe):
        tags = _LEAF_MARKET_NEED.get(str(fid))
        if tags is None:
            return set(_MARKET_TAGS)
        out |= set(tags)
    return out


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
    w_ema = win["ema"]["1w"]
    mc = win["macd"]
    ma5 = _ema(closes_w, w_ema["mid"])
    ma10 = _ema(closes_w, w_ema["slow"])
    ma30 = _ema(closes_w, w_ema["trend"])
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
    detail.update(
        {
            "ma5": m5,
            "ma10": m10,
            "ma30": m30,
            "ma30_prev": m30_prev,
            "dif": d0,
            "dea": e0,
            "dif_prev": d1,
            "dea_prev": e1,
            "hist": h0,
            "hist_prev": h1,
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


def _factor_daily_features(closes, volumes, need=None):
    detail = {
        "ma20": None,
        "ma60": None,
        "ma_trend": None,
        "vol10": None,
        "vol20": None,
        "vol_need": 1,
        "vol_streak": 0,
        "mid_n": 0,
        "slow_n": 0,
        "trend_n": 0,
        "i": -1,
        "price": None,
        "vol": None,
        "v10": None,
        "v20": None,
    }
    if closes is None:
        return False, detail
    if need is None:
        need = _market_need()
    d_ema = _structure_windows()["ema"]["1d"]
    try:
        mid_n = int(d_ema.get("mid") or 0)
    except (TypeError, ValueError):
        mid_n = 0
    try:
        slow_n = int(d_ema.get("slow") or 0)
    except (TypeError, ValueError):
        slow_n = 0
    try:
        trend_n = int(d_ema.get("trend") or 0)
    except (TypeError, ValueError):
        trend_n = 0
    detail["mid_n"] = mid_n
    detail["slow_n"] = slow_n
    detail["trend_n"] = trend_n
    ma20 = (
        _ema(closes, mid_n)
        if ("d_ma_mid" in need and mid_n > 0)
        else None
    )
    ma60 = (
        _ema(closes, slow_n)
        if ("d_ma_slow" in need and slow_n > 0)
        else None
    )
    ma_trend = (
        _ema(closes, trend_n)
        if ("d_ma_trend" in need and trend_n > 0)
        else None
    )
    vol10 = None
    vol20 = None
    if volumes is not None:
        if "vol_pb" in need:
            raw_vn = _factor_param(None, "pullback_vol", "vol_n")
            try:
                vol_n = int(10 if raw_vn is None else raw_vn)
            except (TypeError, ValueError):
                vol_n = 10
            vol10 = _sma(volumes, vol_n) if vol_n > 0 else None
    i = len(closes) - 1
    vol_need = _vol_pullback_confirm_need() if "vol_pb" in need else 1
    detail["vol_need"] = vol_need
    detail["i"] = i
    if i < 0:
        return False, detail
    price = float(closes[i])
    vol = float(volumes[i]) if volumes is not None else None
    m20 = _last_valid(ma20, i) if ma20 is not None else None
    m60 = _last_valid(ma60, i) if ma60 is not None else None
    m_trend = _last_valid(ma_trend, i) if ma_trend is not None else None
    v10 = _last_valid(vol10, i) if vol10 is not None else None
    v20 = None
    detail.update(
        {
            "ma20": m20,
            "ma60": m60,
            "ma_trend": m_trend,
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
    return i >= 2, detail


def _build_factor_ctx(
    closes=None,
    volumes=None,
    highs=None,
    lows=None,
    w_detail=None,
    price=None,
    state=None,
    clock=None,
    need=None,
):
    if need is None:
        need = _market_need()
    ready, daily = _factor_daily_features(closes, volumes, need=need)
    if price is None:
        price = daily.get("price")
    try:
        atr_n = int(_structure_windows()["atr"]["n"] or 0)
    except (TypeError, ValueError, KeyError):
        atr_n = 0
    atr_arr = (
        _calc_atr(highs, lows, closes, atr_n)
        if ("atr" in need and atr_n > 0)
        else None
    )
    atr = _last_valid(atr_arr) if atr_arr is not None else None
    try:
        kc_win = _structure_windows()["keltner"]
        kc_ema_n = int(kc_win["ema_n"] or 0)
        kc_atr_n = int(kc_win["atr_n"] or 0)
    except (TypeError, ValueError, KeyError):
        kc_ema_n = 0
        kc_atr_n = 0
    want_kc = "keltner" in need
    kc_mid_arr = (
        _ema(closes, kc_ema_n)
        if want_kc and kc_ema_n > 0 and closes is not None
        else None
    )
    kc_atr_arr = (
        _calc_atr(highs, lows, closes, kc_atr_n)
        if want_kc and kc_atr_n > 0
        else None
    )
    kc_mid = _last_valid(kc_mid_arr) if kc_mid_arr is not None else None
    kc_atr = _last_valid(kc_atr_arr) if kc_atr_arr is not None else None
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
        "ma_trend": daily.get("ma_trend"),
        "vol10": daily.get("vol10"),
        "vol20": daily.get("vol20"),
        "mid_n": daily.get("mid_n"),
        "slow_n": daily.get("slow_n"),
        "trend_n": daily.get("trend_n"),
        "i": daily.get("i"),
        "vol": daily.get("vol"),
        "v10": daily.get("v10"),
        "v20": daily.get("v20"),
        "vol_need": daily.get("vol_need"),
        "atr": atr,
        "atr_n": atr_n,
        "kc_mid": kc_mid,
        "kc_atr": kc_atr,
        "kc_ema_n": kc_ema_n,
        "kc_atr_n": kc_atr_n,
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
