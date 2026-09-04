# === qmt_common/pit_front.py ===
# 作用: 回测时点前复权（PIT）— none 价 + divid factors
# 主要符号: pit_parse_events, pit_parse_full_events, pit_adjust_ohlc, pit_adjust_ohlc_cached
# front_ratio: P_adj(t;T) = P_raw(t) / Π{dr | t < e.day <= T}
# front: 事件序 P <- (P - interest + allot*px) / (1+bonus+gift+allot)
# volume 不调整
def pit_day_from_key(key):
    """除权 dict key → YYYYMMDD（东八区）。"""
    norm = globals().get("_norm_bar_day")
    try:
        ms = int(float(key))
    except Exception:
        if callable(norm):
            return str(norm(key) or "")
        s = str(key or "").strip()
        return s[:8] if len(s) >= 8 and s[:8].isdigit() else ""
    if ms > 10**12:
        sec = ms / 1000.0
    elif ms > 10**9:
        sec = float(ms)
    else:
        if callable(norm):
            return str(norm(key) or "")
        return ""
    try:
        dt = datetime.datetime.utcfromtimestamp(sec) + datetime.timedelta(hours=8)
        return dt.strftime("%Y%m%d")
    except Exception:
        return ""


def pit_mode_from_div(logical_div):
    """logical_div → ratio|diff|""。"""
    d = str(logical_div or "").strip().lower()
    if d == "front_ratio":
        return "ratio"
    if d == "front":
        return "diff"
    return ""


def pit_parse_full_events(factors_dict):
    """factors → [(day, interest, bonus, gift, allot, allot_px, dr), ...] 升序。"""
    out = []
    if not isinstance(factors_dict, dict):
        return out
    for key, row in factors_dict.items():
        day = pit_day_from_key(key)
        if not day:
            continue
        interest = bonus = gift = allot = allot_px = 0.0
        dr = 0.0
        if isinstance(row, (list, tuple)) and len(row) >= 7:
            try:
                interest = float(row[0] or 0)
                bonus = float(row[1] or 0)
                gift = float(row[2] or 0)
                allot = float(row[3] or 0)
                allot_px = float(row[4] or 0)
                dr = float(row[6] or 0)
            except Exception:
                continue
        elif isinstance(row, (int, float)):
            try:
                dr = float(row)
            except Exception:
                continue
        else:
            continue
        # 无有效调整则跳过
        if (
            (dr is None or dr <= 1.0)
            and interest == 0.0
            and bonus == 0.0
            and gift == 0.0
            and allot == 0.0
        ):
            continue
        out.append((day, interest, bonus, gift, allot, allot_px, dr))
    out.sort(key=lambda x: x[0])
    return out


def pit_parse_events(factors_dict):
    """factors dict → [(day, dr), ...] 升序；仅 dr>1（等比路径 / 旧单测）。"""
    out = []
    for day, _i, _b, _g, _a, _ap, dr in pit_parse_full_events(factors_dict):
        try:
            d = float(dr)
        except Exception:
            continue
        if d > 1.0:
            out.append((day, d))
    return out


def pit_cum_dr(events, bar_day, asof_day):
    """Π dr for events with bar_day < e.day <= asof_day；无则 1.0。

    events 可为 [(day, dr), ...] 或 full 元组（取末位 dr）。
    """
    bd = str(bar_day or "")
    ad = str(asof_day or "")
    if not bd or not ad or bd > ad:
        return 1.0
    prod = 1.0
    for item in events or ():
        if not item:
            continue
        day = item[0]
        dr = item[1] if len(item) == 2 else item[6]
        if day <= bd:
            continue
        if day > ad:
            break
        try:
            d = float(dr)
        except Exception:
            continue
        if d > 1.0:
            prod *= d
    return prod if prod > 0 else 1.0


def pit_apply_diff_one(price, interest, bonus, gift, allot, allot_px):
    """单事件价差一步。"""
    try:
        p = float(price)
    except Exception:
        return price
    try:
        interest = float(interest or 0)
        bonus = float(bonus or 0)
        gift = float(gift or 0)
        allot = float(allot or 0)
        allot_px = float(allot_px or 0)
    except Exception:
        return p
    mul = 1.0 + bonus + gift + allot
    if mul <= 0:
        mul = 1.0
    return (p - interest + allot * allot_px) / mul


def pit_cum_diff(full_events, bar_day, asof_day, price):
    """对 price 按 (bar, asof] 内事件升序做价差逐步调整。"""
    bd = str(bar_day or "")
    ad = str(asof_day or "")
    if not bd or not ad or bd > ad:
        return price
    p = price
    for item in full_events or ():
        if not item or len(item) < 7:
            continue
        day, interest, bonus, gift, allot, allot_px, _dr = item[:7]
        if day <= bd:
            continue
        if day > ad:
            break
        p = pit_apply_diff_one(p, interest, bonus, gift, allot, allot_px)
    return p


def _pit_norm_mode(mode):
    m = str(mode or "ratio").strip().lower()
    if m in ("diff", "price", "front"):
        return "diff"
    return "ratio"


def pit_adjust_ohlc(days, opens, highs, lows, closes, events, asof_day, mode="ratio"):
    """按 asof_day 调整 OHLC；mode=ratio|diff。volume 调用方自理。"""
    asof = str(asof_day or "")
    n = len(days) if days is not None else 0
    if n <= 0:
        return opens, highs, lows, closes
    mode = _pit_norm_mode(mode)
    ev = events or ()
    o2, h2, l2, c2 = [], [], [], []
    for i in range(n):
        d = str(days[i] or "")

        def _one(seq):
            if seq is None or i >= len(seq):
                return None
            try:
                raw = float(seq[i])
            except Exception:
                return seq[i]
            if mode == "diff":
                return pit_cum_diff(ev, d, asof, raw)
            mul = pit_cum_dr(ev, d, asof)
            inv = (1.0 / mul) if mul > 0 else 1.0
            return raw * inv

        o2.append(_one(opens))
        h2.append(_one(highs))
        l2.append(_one(lows))
        c2.append(_one(closes))
    return o2, h2, l2, c2


def pit_cache_map():
    cache = getattr(A, "_pit_ohlc_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        A._pit_ohlc_cache = cache
    return cache


def pit_adjust_ohlc_cached(
    stock, days, opens, highs, lows, closes, events, asof_day, mode="ratio"
):
    """带 (stock, asof, mode) 缓存；ratio 可 asof 增量 / 新 dr；diff 全量。"""
    stock = str(stock or "")
    asof = str(asof_day or "")
    mode = _pit_norm_mode(mode)
    cache = pit_cache_map()
    key = (stock, asof, mode)
    hit = cache.get(key)
    if hit is not None:
        return hit
    days = list(days or [])
    ev = list(events or ())
    if mode == "ratio":
        prev_asof = None
        for ck, _val in list(cache.items()):
            if not (isinstance(ck, tuple) and len(ck) >= 3):
                continue
            st, a, m = ck[0], ck[1], ck[2]
            if st != stock or m != "ratio":
                continue
            if a < asof and (prev_asof is None or a > prev_asof):
                prev_asof = a
        if prev_asof is not None:
            prev = cache.get((stock, prev_asof, "ratio"))
            if prev is not None:
                po, ph, pl, pc = prev
                new_prod = 1.0
                for item in ev:
                    if not item:
                        continue
                    day = item[0]
                    dr = item[1] if len(item) == 2 else item[6]
                    if day <= prev_asof:
                        continue
                    if day > asof:
                        break
                    try:
                        d = float(dr)
                    except Exception:
                        continue
                    if d > 1.0:
                        new_prod *= d
                if new_prod > 1.0 + 1e-15:
                    inv = 1.0 / new_prod
                    o2 = [float(x) * inv for x in po]
                    h2 = [float(x) * inv for x in ph]
                    l2 = [float(x) * inv for x in pl]
                    c2 = [float(x) * inv for x in pc]
                    if len(o2) == len(days):
                        cache[key] = (o2, h2, l2, c2)
                        return cache[key]
    o2, h2, l2, c2 = pit_adjust_ohlc(
        days, opens, highs, lows, closes, ev, asof, mode=mode
    )
    cache[key] = (o2, h2, l2, c2)
    return cache[key]


def pit_should_apply(logical_div):
    """回测且逻辑复权为 front/front_ratio 时启用 PIT。"""
    if not getattr(A, "is_backtest", False):
        return False
    d = str(logical_div or "").strip().lower()
    return d in ("front", "front_ratio")
