# === vwapbias/indicators.py ===
def _lower_shadow_ratio(o, h, l, c):
    rng = float(h) - float(l)
    if rng <= 1e-12:
        return 0.0
    return (min(float(o), float(c)) - float(l)) / rng


def _impulse_ok(opens, closes, idx_list, n, last_drop, sum_drop=0.0):
    """信号根之前 n 根：多数阴、或窗口回撤、或末根阴跌，满足其一即可。"""
    n = int(n)
    if n <= 0 or len(idx_list) < n + 1:
        return False
    prior = idx_list[-(n + 1) : -1]
    o0 = float(opens[prior[0]])
    cl = float(closes[prior[-1]])
    if o0 <= 0:
        return False
    peak = o0
    yin = 0
    for j in prior:
        oj = float(opens[j])
        cj = float(closes[j])
        if oj > peak:
            peak = oj
        if cj > peak:
            peak = cj
        if cj < oj:
            yin += 1
    sum_ok = peak > 0 and (peak - cl) / peak >= float(sum_drop)
    ol = float(opens[prior[-1]])
    last_ok = ol > 0 and (ol - cl) / ol >= float(last_drop)
    yin_ok = yin >= max(1, n - 1)
    return sum_ok or last_ok or yin_ok


def _reversal_ok(o, h, l, c, shadow_ratio, prev_close=None):
    if float(c) > float(o):
        return True
    if prev_close is not None and float(c) >= float(prev_close):
        return True
    return _lower_shadow_ratio(o, h, l, c) > float(shadow_ratio)


def _fade_vol_ok(volumes, i_now, i_prev, gap):
    if i_prev is None or i_now is None:
        return False
    v0 = float(volumes[i_prev] or 0)
    v1 = float(volumes[i_now] or 0)
    if v0 <= 0:
        return False
    return v1 <= v0 * float(gap)


def _cum_vwap(amounts, volumes, highs, lows, closes, idx_list):
    """当日已收盘 1m 累加 VWAP。优先 amount，否则 typical*volume。"""
    amt = 0.0
    vol = 0.0
    used_amt = 0
    used_typ = 0
    for j in idx_list:
        v = float(volumes[j] or 0)
        if v <= 0:
            continue
        a = 0.0
        if amounts is not None and j < len(amounts):
            try:
                a = float(amounts[j] or 0)
            except Exception:
                a = 0.0
        if a > 0:
            amt += a
            used_amt += 1
        else:
            typ = (float(highs[j]) + float(lows[j]) + float(closes[j])) / 3.0
            amt += typ * v
            used_typ += 1
        vol += v
    if vol <= 0 or amt <= 0:
        return None, "none"
    raw = amt / vol
    typ_amt = 0.0
    typ_vol = 0.0
    for j in idx_list:
        v = float(volumes[j] or 0)
        if v <= 0:
            continue
        typ = (float(highs[j]) + float(lows[j]) + float(closes[j])) / 3.0
        if typ > 0:
            typ_amt += typ * v
            typ_vol += v
    src = "amount"
    if used_amt == 0:
        src = "typical"
    elif used_typ > 0:
        src = "mixed"
    if typ_vol > 0 and typ_amt > 0:
        typical_vwap = typ_amt / typ_vol
        if typical_vwap > 0:
            ratio = raw / typical_vwap
            # 转债 volume 常为手(1手=10张), amount 为元 -> VWAP 约 10 倍现价
            if 7.5 <= ratio <= 12.5:
                return raw / 10.0, "amount_lot10"
            if ratio > 2.0 or ratio < 0.5:
                return typical_vwap, "typical"
    return raw, src


def _bias_of(price, vwap):
    if vwap is None or vwap <= 0 or price is None:
        return None
    return (float(price) - float(vwap)) / float(vwap)
