# === vwapbias/market.py ===
# 1 分钟主图优先用 ContextInfo 序列（C.close 等）。
# 本机 QMT pandas 损坏时 get_market_data_ex 会报 _TSObject/iNaT，
# 且 get_market_data(count=800) 会把 1m 回测拖死，故 1m 不再走那条回退。
def _pandas_broken_msg(exc):
    s = str(exc or "")
    return ("__reduce_cython__" in s) or ("iNaT" in s) or ("C extension" in s)


def _mark_pandas_broken(exc):
    A._md_pandas_broken = True
    _diag_once("md_pandas_broken", exc)


def _as_float_list(obj, n=None):
    if obj is None:
        return None
    vals = None
    try:
        if hasattr(obj, "values") and not isinstance(obj, (list, tuple, dict)):
            vals = list(np.asarray(obj.values, dtype=float).reshape(-1))
    except Exception:
        vals = None
    if vals is None:
        try:
            vals = list(np.asarray(obj, dtype=float).reshape(-1))
        except Exception:
            vals = None
    if vals is None:
        try:
            if hasattr(obj, "tolist"):
                vals = [float(x) for x in obj.tolist()]
            else:
                vals = [float(x) for x in list(obj)]
        except Exception:
            return None
    if n is not None:
        if n <= 0:
            return []
        vals = vals[: int(n)]
    out = []
    for fv in vals:
        try:
            if fv != fv:
                out.append(0.0)
            else:
                out.append(float(fv))
        except Exception:
            out.append(0.0)
    return out


def _index_n(obj, n):
    if obj is None or n <= 0:
        return None
    out = []
    for i in range(int(n)):
        v = None
        try:
            v = obj[i]
        except Exception:
            try:
                v = obj.iloc[i]
            except Exception:
                return None
        try:
            fv = float(v)
            if fv != fv:
                fv = 0.0
            out.append(fv)
        except Exception:
            out.append(0.0)
    return out


def _ctx_field(C, names, n=None):
    if isinstance(names, str):
        names = (names,)
    try:
        bp_n = int(getattr(C, "barpos", 0) or 0) + 1
    except Exception:
        bp_n = 1
    if n is None:
        n = bp_n
    for name in names:
        obj = getattr(C, name, None)
        if obj is None:
            continue
        if callable(obj):
            got = None
            for args in ((), (n,), (bp_n,), (int(n - 1),)):
                try:
                    got = obj(*args)
                    break
                except Exception:
                    continue
            if got is None:
                continue
            obj = got
        vals = _as_float_list(obj, n)
        if vals and not (len(vals) == 1 and n > 1):
            return vals
        vals = _index_n(obj, n)
        if vals and not (len(vals) == 1 and n > 1):
            return vals
        try:
            fv = float(obj)
            if n <= 1:
                return [fv]
        except Exception:
            pass
    return None


def _diag_ctx_once(C):
    hits = []
    try:
        for n in dir(C):
            ln = str(n).lower()
            if (
                ("close" in ln)
                or ("history" in ln)
                or ("market" in ln)
                or (n in ("open", "high", "low", "volume", "amount", "barpos", "period"))
            ):
                hits.append(str(n))
            if len(hits) >= 30:
                break
    except Exception as e:
        hits.append("dir_fail")
        hits.append(str(e)[:80])
    close = getattr(C, "close", None)
    _diag_once(
        "chart_probe",
        "barpos=",
        getattr(C, "barpos", None),
        "period=",
        getattr(C, "period", None),
        "close_type=",
        type(close),
        "hits=",
        ",".join(hits),
    )


def _from_hist_dict(raw, stock, field):
    if raw is None:
        return None
    vals = _series_from_ex(raw, stock, field)
    if vals:
        return vals
    if not isinstance(raw, dict):
        return _as_float_list(raw)
    keys = [stock, field]
    if "." in str(stock):
        code, mkt = str(stock).split(".", 1)
        keys.extend([code, str(mkt) + str(code), str(code) + "." + str(mkt)])
    for k in keys:
        if k in raw:
            vals = _as_float_list(raw[k])
            if vals:
                return vals
    if len(raw) == 1:
        return _as_float_list(list(raw.values())[0])
    return None


def _call_history(C, count, period, field):
    fn = getattr(C, "get_history_data", None)
    if not callable(fn):
        fn = globals().get("get_history_data")
    if not callable(fn):
        return None
    count = max(1, int(count))
    period = str(period or "1m")
    last = None
    names = (field,)
    if field == "open":
        names = ("open", "Open", "openPrice", "openprice")
    elif field == "high":
        names = ("high", "High", "highPrice", "highprice")
    elif field == "low":
        names = ("low", "Low", "lowPrice", "lowprice")
    elif field == "volume":
        names = ("volume", "vol", "Volume")
    elif field == "amount":
        names = ("amount", "Amount", "money", "turnover")
    for fname in names:
        for args in (
            (count, period, fname, ""),
            (count, period, fname, "none"),
            (count, period, fname),
            (count, period, fname, "front_ratio"),
        ):
            try:
                raw = fn(*args)
            except TypeError as e:
                last = e
                continue
            except Exception as e:
                last = e
                break
            vals = _from_hist_dict(raw, str(getattr(A, "stock", "") or ""), fname)
            if vals:
                return vals
    if last is not None:
        _diag_once("hist_fail", field, period, last)
    return None


def _history_ohlcv_1m(C, bp):
    """get_history_data 返回 list，不经过 pandas。模型交易无 C.close 时用。"""
    n = max(1, int(bp) + 1)
    count = min(n, 240)
    periods = []
    for p in (getattr(A, "period", None), getattr(C, "period", None), "1m", "1min"):
        s = str(p or "").strip()
        if s and s not in periods:
            periods.append(s)
    closes = None
    used = None
    for period in periods:
        for ctry in (count, max(int(count), 8)):
            closes = _call_history(C, ctry, period, "close")
            if closes:
                used = period
                count = int(ctry)
                break
        if closes:
            break
    if not closes:
        return None
    if len(closes) > n:
        closes = closes[-n:]
    k = len(closes)
    opens = _call_history(C, count, used, "open")
    highs = _call_history(C, count, used, "high")
    lows = _call_history(C, count, used, "low")
    volumes = _call_history(C, count, used, "volume") or [0.0] * k
    amounts = _call_history(C, count, used, "amount") or [0.0] * k
    if not opens:
        _diag_once("hist_open_missing", "period=", used)
        opens = list(closes)
    if not highs:
        _diag_once("hist_high_missing", "period=", used)
        highs = list(closes)
    if not lows:
        _diag_once("hist_low_missing", "period=", used)
        lows = list(closes)
    if len(opens) > k:
        opens = opens[-k:]
    if len(highs) > k:
        highs = highs[-k:]
    if len(lows) > k:
        lows = lows[-k:]
    if len(volumes) > k:
        volumes = volumes[-k:]
    if len(amounts) > k:
        amounts = amounts[-k:]
    if len(opens) < k:
        opens = list(closes)
    if len(highs) < k:
        highs = list(closes)
    if len(lows) < k:
        lows = list(closes)
    if len(volumes) < k:
        volumes = [0.0] * k
    if len(amounts) < k:
        amounts = [0.0] * k
    eq = 0
    for i in range(k):
        try:
            if abs(float(opens[i]) - float(closes[i])) < 1e-8:
                eq += 1
        except Exception:
            pass
    _diag_once("ohlc_cmp", "open_eq_close=", eq, "/", k, "src=hist")
    times = []
    miss = 0
    look = k
    idx0 = max(0, int(bp) + 1 - k)
    for j in range(k):
        ts = _timetag_str(C, idx0 + j)
        if not ts:
            miss += 1
        times.append(ts)
    if miss > look // 2:
        times = _synth_1m_times(look, _bar_datetime(C))
        _diag_once("m1_time_synth", "n=", look, "src=hist")
    if len(times) != look:
        return None
    _diag_once("hist_ok", "period=", used, "n=", k)
    return opens, highs, lows, closes, volumes, amounts, times


def _times_for_window(C, bp, n):
    """最近 n 根对应主图下标 [bp-n+1, bp]，不要用 0..n-1（那是上市日）。"""
    n = max(1, int(n))
    bp = int(bp)
    idx0 = max(0, bp + 1 - n)
    times = []
    miss = 0
    for j in range(n):
        ts = _timetag_str(C, idx0 + j)
        if not ts:
            miss += 1
        times.append(ts)
    if miss > n // 2:
        times = _synth_1m_times(n, _bar_datetime(C))
        _diag_once("m1_time_synth", "n=", n, "bp=", bp)
    return times


def _align_ohlcv_times(C, bp, opens, highs, lows, closes, volumes, amounts, times):
    """ori/history 只返回最近若干根时，时间戳必须对齐当前 barpos，而不是图表从头。"""
    if not closes:
        return None
    look = min(len(closes), 240)
    if not opens or len(opens) < look:
        opens = list(closes)
    if not highs or len(highs) < look:
        highs = list(closes)
    if not lows or len(lows) < look:
        lows = list(closes)
    if not volumes or len(volumes) < look:
        volumes = [0.0] * look
    if not amounts or len(amounts) < look:
        amounts = [0.0] * look
    opens = opens[-look:]
    highs = highs[-look:]
    lows = lows[-look:]
    closes = closes[-look:]
    volumes = volumes[-look:]
    amounts = amounts[-look:]
    times_use = None
    if times and len(times) >= look:
        times_use = [_norm_bar_time(x) for x in times[-look:]]
        if not any(times_use):
            times_use = None
    bar_day = ""
    try:
        bar_day = _bar_datetime(C).strftime("%Y%m%d")
    except Exception:
        bar_day = ""
    last = (times_use[-1] if times_use else "") or ""
    if (not times_use) or (bar_day and last[:8] != bar_day):
        times_use = _times_for_window(C, bp, look)
        last = (times_use[-1] if times_use else "") or ""
        if bar_day and last[:8] != bar_day:
            times_use = _synth_1m_times(look, _bar_datetime(C))
            _diag_once("m1_time_synth", "n=", look, "bp=", bp, "force_day=", bar_day)
    if (not times_use) or len(times_use) != look:
        return None
    return opens, highs, lows, closes, volumes, amounts, times_use


def _ori_fetch_md(C, bp, count):
    fn = getattr(C, "get_market_data_ex_ori", None)
    if not callable(fn):
        return None
    stock = str(getattr(A, "stock", "") or "")
    end = _bar_datetime(C).strftime("%Y%m%d%H%M%S")
    fields = ["open", "high", "low", "close", "volume", "amount"]
    try:
        return fn(
            fields,
            [stock],
            period="1m",
            end_time=end,
            count=int(count),
            subscribe=False,
        )
    except TypeError:
        try:
            return fn(fields, [stock], "1m", "", end, int(count), "none")
        except Exception as e:
            _diag_once("ori_fail", e)
            return None
    except Exception as e:
        _diag_once("ori_fail", e)
        return None


def _pack_from_ori_md(C, bp, md):
    stock = str(getattr(A, "stock", "") or "")
    close = _series_from_ex(md, stock, "close") or _from_hist_dict(md, stock, "close")
    if not close:
        return None
    open_ = _series_from_ex(md, stock, "open") or _from_hist_dict(md, stock, "open")
    high = _series_from_ex(md, stock, "high") or _from_hist_dict(md, stock, "high")
    low = _series_from_ex(md, stock, "low") or _from_hist_dict(md, stock, "low")
    volume = _series_from_ex(md, stock, "volume") or _from_hist_dict(md, stock, "volume")
    amount = _series_from_ex(md, stock, "amount") or _from_hist_dict(md, stock, "amount")
    times = _times_from_ex(md, stock)
    return _align_ohlcv_times(C, bp, open_, high, low, close, volume, amount, times)


def _concat_1m_pack(prev, extra, max_n=240):
    if prev is None:
        return extra
    if extra is None:
        return prev
    out = []
    for a, b in zip(prev, extra):
        merged = list(a) + list(b)
        if len(merged) > max_n:
            merged = merged[-max_n:]
        out.append(merged)
    return tuple(out)


def _ori_ohlcv_1m(C, bp):
    """get_market_data_ex_ori 走 numpy，避开 pandas DataFrame。"""
    bp = int(bp)
    prev_bp = int(getattr(A, "_ori_tail_bp", -9))
    prev = getattr(A, "_ori_tail_pack", None)
    if prev is not None and prev_bp >= 0 and bp == prev_bp + 1:
        md_one = _ori_fetch_md(C, bp, 1)
        one = _pack_from_ori_md(C, bp, md_one) if md_one is not None else None
        if one is not None:
            if prev[6] and one[6] and prev[6][-1] == one[6][-1]:
                pack = prev
            else:
                pack = _concat_1m_pack(prev, one, 240)
            A._ori_tail_bp = bp
            A._ori_tail_pack = pack
            return pack
    n = max(1, bp + 1)
    count = min(n, 240)
    md = _ori_fetch_md(C, bp, count)
    if md is None:
        return None
    pack = _pack_from_ori_md(C, bp, md)
    if pack is None:
        return None
    A._ori_tail_bp = bp
    A._ori_tail_pack = pack
    _diag_once(
        "ori_ok",
        "n=",
        len(pack[3]),
        "end=",
        _bar_datetime(C).strftime("%Y%m%d%H%M%S"),
        "t0=",
        pack[6][0] if pack[6] else "",
        "t1=",
        pack[6][-1] if pack[6] else "",
    )
    return pack


def _timetag_str(C, i):
    try:
        tag = C.get_bar_timetag(i)
        if "timetag_to_datetime" in globals():
            s = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
            return str(s)
        if tag > 10**12:
            return datetime.datetime.fromtimestamp(tag / 1000.0).strftime("%Y%m%d%H%M%S")
        return datetime.datetime.fromtimestamp(tag).strftime("%Y%m%d%H%M%S")
    except Exception:
        return ""


def _chart_ohlcv_1m(C):
    """主图 1 分钟 OHLCV，切到当前 barpos（含）。"""
    try:
        bp = int(getattr(C, "barpos", 0) or 0)
    except Exception:
        bp = 0
    if bp < 0:
        return None
    if int(getattr(A, "_chart_bp", -2)) == bp:
        cached = getattr(A, "_chart_pack", None)
        if cached is not None:
            return cached
    nwant = bp + 1
    pack = None
    closes = None
    if nwant <= 400:
        closes = _ctx_field(C, ("close", "get_close", "get_close_price"), nwant)
    if closes:
        n = min(len(closes), nwant)
        if n > 0:
            opens = _ctx_field(C, ("open", "get_open"), nwant)
            highs = _ctx_field(C, ("high", "get_high"), nwant)
            lows = _ctx_field(C, ("low", "get_low"), nwant)
            volumes = _ctx_field(C, ("volume", "vol", "get_volume"), nwant)
            amounts = _ctx_field(C, ("amount", "money", "turnover", "get_amount"), nwant)
            if not opens or len(opens) < n:
                opens = list(closes)
            if not highs or len(highs) < n:
                highs = list(closes)
            if not lows or len(lows) < n:
                lows = list(closes)
            if not volumes or len(volumes) < n:
                volumes = [0.0] * n
            if not amounts or len(amounts) < n:
                amounts = [0.0] * n
            opens = opens[:n]
            highs = highs[:n]
            lows = lows[:n]
            closes = closes[:n]
            volumes = volumes[:n]
            amounts = amounts[:n]
            look = min(n, 300)
            start = n - look
            times = []
            miss = 0
            for i in range(start, n):
                ts = _timetag_str(C, i)
                if not ts:
                    miss += 1
                times.append(ts)
            if miss > look // 2:
                times = _synth_1m_times(look, _bar_datetime(C))
                _diag_once("m1_time_synth", "n=", look)
            if len(times) == look:
                pack = (
                    opens[start:],
                    highs[start:],
                    lows[start:],
                    closes[start:],
                    volumes[start:],
                    amounts[start:],
                    times,
                )
                A._ohlcv_src = "chart"
    if pack is None:
        _diag_ctx_once(C)
        pack = _ori_ohlcv_1m(C, bp)
        if pack is not None:
            A._ohlcv_src = "ori"
    if pack is None:
        pack = _history_ohlcv_1m(C, bp)
        if pack is not None:
            A._ohlcv_src = "history"
    A._chart_bp = bp
    A._chart_pack = pack
    return pack


def _norm_bar_time(x):
    """行情时间 -> yyyymmddHHMMSS。"""
    if x is None:
        return ""
    try:
        if hasattr(x, "strftime"):
            return x.strftime("%Y%m%d%H%M%S")
    except Exception:
        pass
    try:
        if isinstance(x, (int, float)) or (hasattr(x, "item") and not isinstance(x, str)):
            iv = int(x)
            if iv > 10**12:
                return datetime.datetime.fromtimestamp(iv / 1000.0).strftime("%Y%m%d%H%M%S")
            s = str(iv)
            if len(s) >= 14:
                return s[:14]
            if len(s) == 12:
                return s + "00"
            if len(s) == 8:
                return s + "000000"
    except Exception:
        pass
    s = str(x).strip()
    digits = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        elif digits and ch in "- T:./":
            continue
        elif digits:
            break
    d = "".join(digits)
    if len(d) >= 14:
        return d[:14]
    if len(d) >= 8:
        return (d + "000000")[:14]
    return ""


def _times_from_ex(md, stock):
    if md is None:
        return None
    df = None
    if isinstance(md, dict) and stock in md:
        df = md[stock]
    elif isinstance(md, dict):
        for v in md.values():
            df = v
            break
    if df is None:
        return None
    raw = None
    if isinstance(df, dict):
        for col in ("stime", "time", "datetime", "date"):
            if col in df:
                try:
                    raw = list(df[col])
                    break
                except Exception:
                    raw = None
    if (not raw) and hasattr(df, "dtype") and getattr(df.dtype, "names", None):
        names = df.dtype.names
        for col in ("stime", "time", "datetime", "date"):
            if col in names:
                try:
                    raw = list(df[col])
                    break
                except Exception:
                    raw = None
    if (not raw) and hasattr(df, "index"):
        try:
            raw = list(df.index)
        except Exception:
            raw = None
    if (not raw) and hasattr(df, "columns"):
        cols = getattr(df, "columns", [])
        for col in ("time", "stime", "datetime", "date"):
            try:
                if col in cols:
                    raw = list(df[col])
                    break
            except Exception:
                continue
    if not raw:
        return None
    out = [_norm_bar_time(x) for x in raw]
    if not any(out):
        return None
    return out


def _synth_1m_times(n, end_dt):
    times = []
    t = end_dt.replace(second=0, microsecond=0)
    guard = 0
    while len(times) < n and guard < n * 20 + 50:
        guard += 1
        hhmm = t.strftime("%H%M")
        if ("0930" <= hhmm <= "1130") or ("1300" <= hhmm <= "1500"):
            times.append(t.strftime("%Y%m%d%H%M%S"))
        t -= datetime.timedelta(minutes=1)
    times.reverse()
    return times


def _fetch_md(C, stock, period, fields, end, count, diag_key):
    """日线等跨周期取数。1m 不要走这里。pandas 损坏后本会话不再重试。"""
    if getattr(A, "_md_pandas_broken", False):
        return None, None
    md = None
    source = None
    flist = list(fields)
    try:
        md = C.get_market_data_ex(
            flist,
            [stock],
            period=period,
            end_time=end,
            count=int(count),
            dividend_type="front_ratio",
            subscribe=False,
        )
        source = "get_market_data_ex"
    except TypeError:
        try:
            md = C.get_market_data_ex(
                flist,
                [stock],
                period=period,
                start_time="",
                end_time=end,
                count=int(count),
                dividend_type="front_ratio",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            if _pandas_broken_msg(e):
                _mark_pandas_broken(e)
            else:
                _diag_once(diag_key + "_ex_fail", e)
            md = None
    except Exception as e:
        if _pandas_broken_msg(e):
            _mark_pandas_broken(e)
        else:
            _diag_once(diag_key + "_ex_fail", e)
        md = None
    return md, source


def _get_ohlcv_1m(C, stock):
    """已对齐的 1 分钟 OHLCV + amount + 时间戳。"""
    end = _bar_datetime(C).strftime("%Y%m%d%H%M%S")
    pack = _chart_ohlcv_1m(C)
    if pack is not None:
        open_, high, low, close, volume, amount, times = pack
        n = len(close)
        need = int(globals().get("DOWN_BARS") or 3) + 2
        if n >= need:
            _diag_once(
                "ok",
                "source=",
                str(getattr(A, "_ohlcv_src", "chart") or "chart"),
                "period=1m n=",
                n,
                "end=",
                end,
                "t0=",
                times[0] if times else "",
                "t1=",
                times[-1] if times else "",
                "last=",
                round(float(close[-1]), 4),
                "stock=",
                stock,
            )
            return pack
        _diag_once("chart_short", "n=", n, "need=", need)
        return None
    _diag_once("chart_miss", "end=", end, "stock=", stock)
    return None


def _today_indices(times, day):
    out = []
    for i, ts in enumerate(times or []):
        if not ts or len(ts) < 12:
            continue
        if ts[:8] != day:
            continue
        hhmm = ts[8:12]
        if ("0930" <= hhmm <= "1130") or ("1300" <= hhmm <= "1500"):
            out.append(i)
    return out


def _get_daily_adv(C, stock, today):
    """近 ADV_DAYS 个已收盘日的日均成交额。"""
    cache_day = str(getattr(A, "_adv_cache_day", "") or "")
    if cache_day == today:
        return getattr(A, "_adv_cache_val", None)
    val = None
    if getattr(A, "is_backtest", False) or getattr(A, "_md_pandas_broken", False):
        A._adv_cache_day = today
        A._adv_cache_val = None
        return None
    end = today
    count = int(globals().get("DAILY_OHLC_COUNT") or 12)
    md, _src = _fetch_md(C, stock, "1d", ["amount", "close"], end, count, "d1")
    amounts = _series_from_ex(md, stock, "amount") if md is not None else None
    times = _times_from_ex(md, stock) if md is not None else None
    if amounts:
        days = int(globals().get("ADV_DAYS") or 5)
        picked = []
        n = len(amounts)
        for i in range(n):
            d = ""
            if times and i < len(times) and times[i]:
                d = times[i][:8]
            a = float(amounts[i] or 0)
            if a <= 0:
                continue
            if d and d >= today:
                continue
            picked.append(a)
        if picked:
            use = picked[-days:]
            if use:
                val = sum(use) / float(len(use))
    A._adv_cache_day = today
    A._adv_cache_val = val
    return val


def _prev_close_from_times(closes, times, today):
    if not closes or not times:
        return None
    n = min(len(closes), len(times))
    for i in range(n - 1, -1, -1):
        ts = times[i] or ""
        if len(ts) < 8:
            continue
        if ts[:8] >= today:
            continue
        px = float(closes[i] or 0)
        if px > 0:
            return px
    return None


def _get_prev_close(C, stock, today):
    cache_day = str(getattr(A, "_preclose_day", "") or "")
    if cache_day == today and getattr(A, "_preclose_val", None) is not None:
        return A._preclose_val
    found = None
    pack = _chart_ohlcv_1m(C)
    if pack is not None:
        _o, _h, _l, closes, _v, _a, times = pack
        found = _prev_close_from_times(closes, times, today)
    if found is None and (not getattr(A, "is_backtest", False)) and (not getattr(A, "_md_pandas_broken", False)):
        end = today
        md, _src = _fetch_md(C, stock, "1d", ["close"], end, 8, "d1c")
        closes = _series_from_ex(md, stock, "close") if md is not None else None
        times = _times_from_ex(md, stock) if md is not None else None
        if closes:
            n = len(closes)
            for i in range(n - 1, -1, -1):
                d = ""
                if times and i < len(times) and times[i]:
                    d = times[i][:8]
                if d and d >= today:
                    continue
                px = float(closes[i] or 0)
                if px > 0:
                    found = px
                    break
            if found is None and n >= 2 and float(closes[-2] or 0) > 0:
                found = float(closes[-2])
    A._preclose_day = today
    A._preclose_val = found
    return found


def _parse_tick(raw, stock):
    if raw is None:
        return None
    if isinstance(raw, dict):
        if stock in raw and isinstance(raw[stock], dict):
            return raw[stock]
        if "lastPrice" in raw or "lastClose" in raw or "bid" in raw:
            return raw
        keys = list(raw.keys())
        if len(keys) == 1 and isinstance(raw[keys[0]], dict):
            return raw[keys[0]]
    return None


def _get_tick(C, stock):
    fn = getattr(C, "get_full_tick", None)
    if not callable(fn):
        fn = globals().get("get_full_tick")
    if not callable(fn):
        return None
    try:
        raw = fn([stock])
    except Exception as e:
        _diag_once("tick_fail", e)
        return None
    return _parse_tick(raw, stock)


def _tick_num(tick, *names):
    if not tick:
        return None
    for name in names:
        if name not in tick:
            continue
        try:
            v = float(tick.get(name) or 0)
        except Exception:
            continue
        if v > 0:
            return v
    return None


def _tick_vwap(tick):
    amt = _tick_num(tick, "amount")
    vol = _tick_num(tick, "volume")
    if amt is None or vol is None or vol <= 0:
        return None
    return amt / vol


def _tick_spread(tick):
    bid = _tick_num(tick, "bid", "bidPrice", "bid1", "bidPrice1")
    ask = _tick_num(tick, "ask", "askPrice", "ask1", "askPrice1")
    if bid is None or ask is None or ask <= bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid
