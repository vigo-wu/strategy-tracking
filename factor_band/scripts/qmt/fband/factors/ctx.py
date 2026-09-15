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


_STRUCTURE_DELETED_ROOTS = frozenset({"d_ma", "w_ma", "macd"})
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
    atr = rec.get("atr") or {}
    keltner = rec.get("keltner") or {}
    return {
        "ema": {
            "1d": _structure_ma_period_block(ema, "1d", (20, 60, 120)),
            "1w": _structure_ma_period_block(ema, "1w", (5, 0, 34)),
        },
        "sma": {
            "1d": _structure_ma_period_block(sma, "1d", (0, 0, 0)),
            "1w": _structure_ma_period_block(sma, "1w", (0, 0, 0)),
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
        "vol_kc",
        "atr",
        "keltner",
        "weekly",
    }
)


_LEAVES_NEED_OK = False


def _leaf_need_tags(fid, leaf=None):
    """LEAVES[id].need → frozenset。缺键 / 非法标签报错。"""
    if leaf is None:
        leaf = ((globals().get("LEAVES") or {}).get(str(fid)) or None)
    if not isinstance(leaf, dict) or "need" not in leaf:
        raise ValueError("LEAVES.%s 缺 need" % fid)
    raw = leaf.get("need")
    if raw is None:
        raise ValueError("LEAVES.%s.need 不能为 None" % fid)
    tags = frozenset(str(t) for t in raw)
    bad = tags - _MARKET_TAGS
    if bad:
        raise ValueError(
            "LEAVES.%s.need 非法标签 %s" % (fid, ",".join(sorted(bad)))
        )
    return tags


def _validate_leaves_need():
    """组表时扫全表 need。"""
    global _LEAVES_NEED_OK
    if _LEAVES_NEED_OK:
        return
    leaves = globals().get("LEAVES") or {}
    for fid, leaf in leaves.items():
        _leaf_need_tags(fid, leaf)
    _LEAVES_NEED_OK = True


def _market_need(recipe=None):
    """启用叶子对应的 ctx / 暖机标签。未知 AST id → 全标签。"""
    _validate_leaves_need()
    walk = globals().get("_recipe_compute_leaves")
    if not callable(walk):
        return set(_MARKET_TAGS)
    leaves = globals().get("LEAVES") or {}
    out = set()
    for fid in walk(recipe):
        key = str(fid)
        if key not in leaves:
            return set(_MARKET_TAGS)
        out |= set(_leaf_need_tags(key, leaves.get(key)))
    return out


def _weekly_market_features(closes_w):
    """周线 MA 进 ctx.market；不判多空。"""
    detail = {
        "w_mid": None,
        "w_trend": None,
        "close": None,
    }
    win = _structure_windows()
    w_ema = win["ema"]["1w"]
    mid_arr = _ema(closes_w, w_ema["mid"])
    trend_arr = _ema(closes_w, w_ema["trend"])
    if mid_arr is None or trend_arr is None:
        return detail
    i = len(closes_w) - 1
    if i < 1:
        return detail
    c = float(closes_w[i])
    m_mid = _last_valid(mid_arr, i)
    m_trend = _last_valid(trend_arr, i)
    m_trend_prev = _last_valid(trend_arr, i - 1)
    detail.update(
        {
            "w_mid": m_mid,
            "w_trend": m_trend,
            "w_trend_prev": m_trend_prev,
            "close": c,
        }
    )
    return detail


def _factor_daily_features(closes, volumes, need=None):
    detail = {
        "d_mid": None,
        "d_slow": None,
        "d_trend": None,
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
    mid_arr = (
        _ema(closes, mid_n)
        if ("d_ma_mid" in need and mid_n > 0)
        else None
    )
    slow_arr = (
        _ema(closes, slow_n)
        if ("d_ma_slow" in need and slow_n > 0)
        else None
    )
    trend_arr = (
        _ema(closes, trend_n)
        if ("d_ma_trend" in need and trend_n > 0)
        else None
    )
    vol10 = None
    vol20 = None
    i = len(closes) - 1
    detail["vol_need"] = 1
    detail["i"] = i
    if i < 0:
        return False, detail
    price = float(closes[i])
    vol = float(volumes[i]) if volumes is not None else None
    m_mid = _last_valid(mid_arr, i) if mid_arr is not None else None
    m_slow = _last_valid(slow_arr, i) if slow_arr is not None else None
    m_trend = _last_valid(trend_arr, i) if trend_arr is not None else None
    v10 = _last_valid(vol10, i) if vol10 is not None else None
    v20 = None
    detail.update(
        {
            "d_mid": m_mid,
            "d_slow": m_slow,
            "d_trend": m_trend,
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
        "d_mid": daily.get("d_mid"),
        "d_slow": daily.get("d_slow"),
        "d_trend": daily.get("d_trend"),
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
