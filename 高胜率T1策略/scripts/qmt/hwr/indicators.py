# === hwr/indicators.py ===
def _vwap(closes, volumes):
    """成交量加权均价；量全 0 时退回收盘均价."""
    c = np.asarray(closes, dtype=float)
    v = np.asarray(volumes, dtype=float)
    if len(c) == 0 or len(v) != len(c):
        return None
    vsum = float(np.sum(v))
    if vsum <= 1e-12:
        return float(np.mean(c))
    return float(np.sum(c * v) / vsum)


def _approx_session_bars(hhmm):
    """按 A 股连续竞价估算当日已走分钟数（用于截取今日 VWAP）。"""
    try:
        t = int(str(hhmm)[:4])
    except Exception:
        return 60
    h, m = t // 100, t % 100
    mins = h * 60 + m
    am0, am1 = 9 * 60 + 30, 11 * 60 + 30
    pm0, pm1 = 13 * 60, 15 * 60
    if mins < am0:
        return 1
    if mins <= am1:
        return max(1, mins - am0 + 1)
    if mins < pm0:
        return 120
    if mins <= pm1:
        return 120 + max(1, mins - pm0 + 1)
    return 240


def _today_slice(closes, volumes, hhmm):
    n = min(len(closes), max(1, int(_approx_session_bars(hhmm))))
    return closes[-n:], volumes[-n:]


def _buy_filters(closes, highs, volumes):
    """返回 (ok, vwap, day_high, mom10, vol_ratio) 或失败时 ok=False."""
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs, dtype=float)
    v = np.asarray(volumes, dtype=float)
    n = len(c)
    if n < int(BUY_MIN_BARS) or len(h) != n or len(v) != n:
        return False, None, None, None, None
    mom_n = int(MOM_BARS)
    if n <= mom_n or c[-(mom_n + 1)] <= 0:
        return False, None, None, None, None

    vwap = _vwap(c[-int(LOOKBACK_N) :], v[-int(LOOKBACK_N) :])
    day_high = float(np.max(h[-int(LOOKBACK_N) :]))
    price = float(c[-1])
    mom10 = (price - float(c[-mom_n])) / float(c[-mom_n])
    vol_ma = float(np.mean(v[-mom_n:]))
    base = v[:-mom_n]
    if len(base) < mom_n:
        return False, vwap, day_high, mom10, None
    vol_base = float(np.mean(base[-int(LOOKBACK_N) :])) if len(base) > 0 else 0.0
    if vol_base <= 1e-12:
        vol_ratio = 0.0
    else:
        vol_ratio = vol_ma / vol_base

    ok = (
        vwap is not None
        and price > float(vwap)
        and day_high > 0
        and price >= day_high * float(NEAR_HIGH_RATIO)
        and mom10 > float(MOM_MIN_RET)
        and vol_ratio > float(VOL_RATIO_MIN)
    )
    return ok, vwap, day_high, mom10, vol_ratio


# -------------------- 行情 --------------------
