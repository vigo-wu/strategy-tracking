# === kldump/dump.py ===
# 作用: 按主图标的/周期拉 K 线并写成 CSV
import csv


def _digits_only(s):
    out = []
    for ch in str(s or ""):
        if ch.isdigit():
            out.append(ch)
    return "".join(out)


def _year_ok(s):
    d = _digits_only(s)
    if len(d) < 8:
        return False
    try:
        y = int(d[:4])
    except Exception:
        return False
    return 1990 <= y <= 2100


def _apply_hist_start(start=""):
    hs = _digits_only(start)[:8]
    if not hs:
        hs = str(globals().get("HIST_START") or "").strip()
    if not hs:
        return
    mapping = {}
    for p in (globals().get("_VALID_PERIODS") or ()):
        mapping[p] = hs
    globals()["_PERIOD_HIST_START"] = mapping


def _coerce_qmt_time(val):
    """C.start / C.end / timetag -> yyyymmdd 或 yyyymmddHHMMSS。"""
    t = _coerce_qmt_time_raw(val)
    if t and _year_ok(t):
        return t
    return ""


def _coerce_qmt_time_raw(val):
    if val is None or val == "" or val is False:
        return ""
    try:
        if hasattr(val, "strftime"):
            hour = int(getattr(val, "hour", 0) or 0)
            minute = int(getattr(val, "minute", 0) or 0)
            second = int(getattr(val, "second", 0) or 0)
            if hour == 0 and minute == 0 and second == 0:
                return val.strftime("%Y%m%d")
            return val.strftime("%Y%m%d%H%M%S")
    except Exception:
        pass
    n = None
    try:
        if isinstance(val, bool):
            return ""
        if isinstance(val, (int, float)):
            n = int(val)
        else:
            s = str(val).strip()
            if (not s) or s in ("0", "-1", "None"):
                return ""
            d = _digits_only(s)
            if d:
                n = int(d)
    except Exception:
        n = None
    if n is None or n <= 0:
        return ""
    d = str(n)
    if len(d) == 8 and (d.startswith("19") or d.startswith("20")):
        return d
    if len(d) >= 14 and (d.startswith("19") or d.startswith("20")):
        return d[:14]
    if 10 ** 12 <= n < 10 ** 14 and not (d.startswith("19") or d.startswith("20")):
        try:
            return datetime.datetime.fromtimestamp(n / 1000.0).strftime("%Y%m%d%H%M%S")
        except Exception:
            pass
    if 10 ** 9 <= n < 10 ** 12:
        try:
            return datetime.datetime.fromtimestamp(float(n)).strftime("%Y%m%d%H%M%S")
        except Exception:
            pass
    if len(d) >= 8 and (d.startswith("19") or d.startswith("20")):
        return d[:8]
    return ""


def _fmt_query_time(s, period, is_end):
    d = _digits_only(s)
    if not d:
        return ""
    if _is_intraday(period):
        if len(d) >= 14:
            return d[:14]
        if is_end:
            return d[:8] + "150000"
        return d[:8] + "000000"
    return d[:8]


def _cmp_key(s, n, is_end=False):
    d = _digits_only(s)
    if not d:
        return ""
    if is_end and len(d) <= 8:
        d = d[:8] + "235959"
    elif len(d) < n:
        d = d + ("0" * (n - len(d)))
    return d[:n]


def _row_in_range(tstr, start, end, period):
    n = 12 if _is_intraday(period) else 8
    k = _cmp_key(tstr, n)
    if not k:
        return True
    s = _cmp_key(start, n)
    e = _cmp_key(end, n, True)
    if s and k < s:
        return False
    if e and k > e:
        return False
    return True


def _bar_time_str(C, barpos=None):
    try:
        if barpos is None:
            barpos = int(getattr(C, "barpos", 0) or 0)
        tag = C.get_bar_timetag(barpos)
        t = _coerce_qmt_time(tag)
        if t:
            return t
        if "timetag_to_datetime" in globals():
            s = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
            t = _digits_only(s)
            if t and _year_ok(t):
                return t
    except Exception:
        pass
    return ""


def _first_attr(obj, names):
    for name in names:
        try:
            if hasattr(obj, name):
                val = getattr(obj, name)
                t = _coerce_qmt_time(val)
                if t:
                    return t, name, val
        except Exception:
            continue
    return "", "", None


def _resolve_dump_range(C):
    """优先主图回测区间 C.start / C.end；init 里不要用 bar0（timetag 常为 0）。"""
    follow = bool(globals().get("FOLLOW_CHART_RANGE", True))
    start, start_src, start_raw = ("", "", None)
    end, end_src, end_raw = ("", "", None)
    if follow:
        start, start_src, start_raw = _first_attr(
            C, ("start", "start_time", "startdate", "startDate")
        )
        end, end_src, end_raw = _first_attr(
            C, ("end", "end_time", "enddate", "endDate")
        )
    print(
        _strategy_tag(),
        "C.start=",
        getattr(C, "start", None),
        "C.end=",
        getattr(C, "end", None),
        "->",
        start,
        end,
        "src=",
        start_src,
        end_src,
    )
    return start, end, start_src, end_src


def _resolve_period_dump(C):
    p = _resolve_period(C, default="")
    if p:
        return p
    raw = getattr(C, "period", None)
    if raw:
        print(_strategy_tag(), "period fallback raw=", raw)
        return str(raw).strip()
    return "1d"


def _stock_tag(stock):
    return str(stock).replace(".", "_")


def _compact_day(s):
    digits = []
    for ch in str(s):
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    if len(digits) >= 8:
        return "".join(digits[:8])
    return ""


def _fmt_bar_time(x):
    if x is None:
        return ""
    try:
        if hasattr(x, "strftime"):
            hour = 0
            minute = 0
            second = 0
            try:
                hour = int(getattr(x, "hour", 0) or 0)
                minute = int(getattr(x, "minute", 0) or 0)
                second = int(getattr(x, "second", 0) or 0)
            except Exception:
                pass
            if hour == 0 and minute == 0 and second == 0:
                return x.strftime("%Y-%m-%d")
            return x.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    try:
        if type(x).__name__ == "datetime64":
            s = str(x)
            s = s.replace("T", " ").split(".")[0]
            return s
    except Exception:
        pass
    s = str(x).strip()
    digits = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
    d = "".join(digits)
    if len(d) >= 14:
        return "%s-%s-%s %s:%s:%s" % (d[0:4], d[4:6], d[6:8], d[8:10], d[10:12], d[12:14])
    if len(d) >= 8:
        return "%s-%s-%s" % (d[0:4], d[4:6], d[6:8])
    return s


def _ex_frame(md, stock):
    if md is None:
        return None
    if isinstance(md, dict) and stock in md:
        return md[stock]
    if hasattr(md, "columns") and not isinstance(md, dict):
        return md
    if isinstance(md, dict):
        for key in ("close", "open"):
            if key in md:
                return md[key]
        for v in md.values():
            return v
    return None


def _times_from_ex(md, stock):
    df = _ex_frame(md, stock)
    if df is None:
        return None
    raw = None
    if hasattr(df, "index"):
        try:
            raw = list(df.index)
        except Exception:
            raw = None
    if (not raw) and hasattr(df, "columns"):
        for col in ("time", "date", "datetime", "stime"):
            try:
                cols = getattr(df, "columns", [])
                if col in cols:
                    raw = list(df[col])
                    break
            except Exception:
                continue
    if not raw:
        return None
    return [_fmt_bar_time(x) for x in raw]


def _col_keep(md, stock, field):
    """与 _series_from_ex 相同来源，但保留空位以便与时间对齐。"""
    obj = None
    if md is None:
        return None
    if isinstance(md, dict) and stock in md:
        df = md[stock]
        if hasattr(df, "columns") and field in getattr(df, "columns", []):
            obj = df[field]
        elif isinstance(df, dict) and field in df:
            obj = df[field]
        elif hasattr(df, "__getitem__"):
            try:
                obj = df[field]
            except Exception:
                pass
    if obj is None and isinstance(md, dict) and field in md:
        df = md[field]
        if hasattr(df, "columns"):
            cols = list(df.columns)
            if stock in cols:
                obj = df[stock]
            elif len(cols) == 1:
                obj = df[cols[0]]
            else:
                obj = df
        elif isinstance(df, dict) and stock in df:
            obj = df[stock]
        else:
            obj = df
    if obj is None and hasattr(md, "columns") and field in getattr(md, "columns", []):
        obj = md[field]
    if obj is None:
        return None
    try:
        vals = list(np.asarray(obj).reshape(-1))
    except Exception:
        try:
            vals = list(obj)
        except Exception:
            return None
    out = []
    for fv in vals:
        try:
            x = float(fv)
            if x != x:
                out.append("")
            else:
                out.append(x)
        except Exception:
            out.append("")
    return out


def _fetch_md(C, stock, period):
    fields = ["open", "high", "low", "close", "volume", "amount"]
    start_raw = str(getattr(A, "dump_start", "") or "")
    end_raw = str(getattr(A, "dump_end", "") or "")
    start = _fmt_query_time(start_raw, period, False)
    end = _fmt_query_time(end_raw, period, True)
    has_range = bool(start and end)
    if has_range:
        count = -1
    else:
        count = int(globals().get("BAR_COUNT") or 5000)
        if not start:
            start = _fmt_query_time(str(globals().get("HIST_START") or ""), period, False)
        if not end:
            end = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            if not _is_intraday(period):
                end = end[:8]
    div = str(globals().get("DIVIDEND_TYPE") or "front_ratio")
    md = None
    source = None
    try:
        md = C.get_market_data_ex(
            fields=fields,
            stock_code=[stock],
            period=period,
            start_time=start,
            end_time=end,
            count=int(count),
            dividend_type=div,
            fill_data=True,
            subscribe=False,
        )
        source = "get_market_data_ex"
    except TypeError:
        try:
            md = C.get_market_data_ex(
                fields,
                [stock],
                period=period,
                start_time=start,
                end_time=end,
                count=int(count),
                dividend_type=div,
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once("ex_fail_" + str(period), e)
            md = None
    except Exception as e:
        _diag_once("ex_fail_" + str(period), e)
        md = None
    if md is None:
        try:
            md = C.get_market_data(
                fields,
                stock_code=[stock],
                period=period,
                start_time=start,
                end_time=end,
                count=int(count),
                dividend_type=div,
            )
            source = "get_market_data"
        except Exception as e:
            _diag_once("gmd_fail_" + str(period), e)
            md = None
    return md, source, start, end


def _align_cols(times, open_, high, low, close, volume, amount):
    n = 0
    for seq in (close, open_, high, low, volume, amount, times):
        if seq:
            n = max(n, len(seq))
    if n <= 0:
        return None

    def pad(seq):
        if not seq:
            return [""] * n
        if len(seq) >= n:
            return list(seq)[:n]
        return list(seq) + [""] * (n - len(seq))

    return (
        pad(times),
        pad(open_),
        pad(high),
        pad(low),
        pad(close),
        pad(volume),
        pad(amount),
    )


def _write_csv(path, rows):
    parent = os.path.dirname(path)
    if parent and (not os.path.isdir(parent)):
        os.makedirs(parent)
    f = open(path, "w", encoding="utf-8-sig", newline="")
    try:
        w = csv.writer(f)
        w.writerow(
            ["stock", "period", "datetime", "open", "high", "low", "close", "volume", "amount"]
        )
        w.writerows(rows)
    finally:
        f.close()


def _dump_period(C, stock, period):
    md, source, q_start, q_end = _fetch_md(C, stock, period)
    if md is None:
        print(_strategy_tag(), "dump empty period=", period, "source=", source)
        return None
    times = _times_from_ex(md, stock)
    open_ = _col_keep(md, stock, "open")
    high = _col_keep(md, stock, "high")
    low = _col_keep(md, stock, "low")
    close = _col_keep(md, stock, "close")
    volume = _col_keep(md, stock, "volume")
    amount = _col_keep(md, stock, "amount")
    aligned = _align_cols(times, open_, high, low, close, volume, amount)
    if aligned is None:
        print(_strategy_tag(), "dump empty period=", period, "source=", source)
        return None
    times, open_, high, low, close, volume, amount = aligned
    clip_start = str(getattr(A, "dump_start", "") or q_start or "")
    clip_end = str(getattr(A, "dump_end", "") or q_end or "")
    n = len(close)
    rows = []
    i = 0
    while i < n:
        if clip_start or clip_end:
            if not _row_in_range(times[i], clip_start, clip_end, period):
                i += 1
                continue
        rows.append(
            [
                stock,
                period,
                times[i],
                open_[i],
                high[i],
                low[i],
                close[i],
                volume[i],
                amount[i],
            ]
        )
        i += 1
    if not rows:
        print(
            _strategy_tag(),
            "dump empty after clip period=",
            period,
            "query=",
            q_start,
            q_end,
        )
        return None
    first_day = _compact_day(rows[0][2])
    last_day = _compact_day(rows[-1][2])
    if not first_day:
        first_day = _digits_only(clip_start)[:8] or "start"
    if not last_day:
        last_day = _digits_only(clip_end)[:8] or datetime.datetime.now().strftime("%Y%m%d")
    fname = "%s_%s_%s_%s.csv" % (_stock_tag(stock), period, first_day, last_day)
    out_dir = str(globals().get("OUT_DIR") or "")
    path = os.path.join(out_dir, fname)
    _write_csv(path, rows)
    print(
        _strategy_tag(),
        "dumped n=",
        len(rows),
        "period=",
        period,
        "range=",
        q_start,
        q_end,
        "source=",
        source,
        "path=",
        path,
    )
    return path


def _infer_dump_market(code6):
    if not code6:
        return ""
    first = str(code6)[0]
    if first in ("6", "9", "5"):
        return "SH"
    if first in ("0", "1", "2", "3"):
        return "SZ"
    if first in ("4", "8"):
        return "BJ"
    return ""


def _norm_dump_stock(raw):
    s = str(raw or "").strip().upper().replace(" ", "")
    if not s:
        return ""
    if "." in s:
        parts = s.split(".")
        if len(parts) != 2:
            return ""
        digits = _digits_only(parts[0])
        mkt = str(parts[1] or "").strip()
        if len(digits) != 6:
            return ""
        if mkt not in ("SH", "SZ", "BJ"):
            return ""
        return digits + "." + mkt
    digits = _digits_only(s)
    if len(digits) == 6 and s == digits:
        mkt = _infer_dump_market(digits)
        if not mkt:
            return ""
        return digits + "." + mkt
    return ""


def _iter_dump_stock_raw():
    raw = globals().get("DUMP_STOCKS")
    if raw is None or raw is False:
        return []
    if isinstance(raw, dict):
        return list(raw.keys())
    if isinstance(raw, (str, bytes)):
        s = str(raw or "").strip()
        if not s:
            return []
        parts = []
        for chunk in s.replace(",", " ").split():
            if chunk:
                parts.append(chunk)
        return parts
    try:
        seq = list(raw)
    except Exception:
        return []
    out = []
    for x in seq:
        if isinstance(x, (list, tuple)) and len(x) >= 1:
            out.append(x[0])
        else:
            out.append(x)
    return out


def _resolve_dump_stocks():
    stocks = []
    seen = set()
    for x in _iter_dump_stock_raw():
        code = _norm_dump_stock(x)
        if not code:
            if str(x or "").strip():
                print(_strategy_tag(), "dump skip bad stock=", x)
            continue
        key = code.upper()
        if key in seen:
            continue
        seen.add(key)
        stocks.append(code)
    if stocks:
        return stocks
    chart = str(getattr(A, "stock", "") or "").strip()
    if chart:
        return [chart]
    return []


def _dump_periods(C):
    stocks = _resolve_dump_stocks()
    periods = [A.period]
    for p in (globals().get("EXTRA_PERIODS") or ()):
        n = _norm_period(p)
        if n and n not in periods:
            periods.append(n)
    print(_strategy_tag(), "batch stocks=", stocks, "periods=", periods)
    do_dl = bool(globals().get("DOWNLOAD_HIST", True))
    for stock in stocks:
        for period in periods:
            if do_dl:
                try:
                    _download_hist(stock, period)
                except Exception as e:
                    print(_strategy_tag(), "download_hist abort-safe", stock, period, e)
            try:
                _dump_period(C, stock, period)
            except Exception as e:
                print(_strategy_tag(), "dump abort-safe", stock, period, e)
    A._dumped = True


def _dump_init(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period_dump(C)
    A._diag = set()
    A.is_backtest = bool(getattr(C, "do_back_test", False))
    A._dumped = False
    A.need_last_bar = False
    start, end, start_src, end_src = _resolve_dump_range(C)
    A.dump_start = start
    A.dump_end = end
    _apply_hist_start(start)
    dump_stocks = _resolve_dump_stocks()
    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        A.stock,
        "PERIOD=",
        A.period,
        "BACKTEST=",
        A.is_backtest,
        "range=",
        start,
        end,
        "DUMP_STOCKS=",
        dump_stocks,
        "OUT_DIR=",
        globals().get("OUT_DIR") or "",
    )
    if start and end:
        _dump_periods(C)
        return
    # 回测：C.start/C.end 常为空；用主图正在走的第一根/最后一根 K
    A.need_last_bar = True
    A.dump_start = start or ""
    A.dump_end = end or ""
    print(_strategy_tag(), "wait chart bars for range")


def _find_chart_end(C):
    """从当前 barpos 向后倍增搜索主图最后一根有效 K。"""
    try:
        bp = int(getattr(C, "barpos", 0) or 0)
    except Exception:
        bp = 0
    last_t = _bar_time_str(C, bp)
    last_i = bp
    if not last_t:
        return "", bp
    step = 1
    guard = 0
    while step < 5000000 and guard < 32:
        guard += 1
        nxt = last_i + step
        t = _bar_time_str(C, nxt)
        if not t:
            break
        last_t = t
        last_i = nxt
        step *= 2
    lo = last_i
    hi = last_i + step
    while lo + 1 < hi and guard < 80:
        guard += 1
        mid = int((lo + hi) / 2)
        t = _bar_time_str(C, mid)
        if t:
            lo = mid
            last_t = t
        else:
            hi = mid
    return last_t, lo


def _is_chart_last_bar(C):
    try:
        if hasattr(C, "is_last_bar") and C.is_last_bar():
            return True
    except Exception:
        pass
    try:
        bp = int(getattr(C, "barpos", 0) or 0)
        t0 = C.get_bar_timetag(bp)
        t1 = C.get_bar_timetag(bp + 1)
        n0 = int(t0) if t0 is not None else 0
        n1 = int(t1) if t1 is not None else 0
        if n0 > 0 and n1 <= 0:
            return True
        if n0 > 0 and n1 > 0 and n1 <= n0:
            return True
    except Exception:
        pass
    return False


def _dump_track_bars(C):
    if getattr(A, "_dumped", False):
        return
    if not getattr(A, "need_last_bar", False):
        return
    t = _bar_time_str(C)
    if t and (not getattr(A, "dump_start", "")):
        A.dump_start = t
        _apply_hist_start(t)
        end_t, end_i = _find_chart_end(C)
        print(
            _strategy_tag(),
            "first bar start=",
            t,
            "barpos=",
            getattr(C, "barpos", None),
            "search_end=",
            end_t,
            "end_barpos=",
            end_i,
        )
        if end_t and end_i > int(getattr(C, "barpos", 0) or 0):
            A.dump_end = end_t
            _dump_periods(C)
            return
        print(_strategy_tag(), "chart end search stayed on current bar, wait last")
    if t:
        A.dump_end = t
    if not _is_chart_last_bar(C):
        return
    if not getattr(A, "dump_start", ""):
        A.dump_start = t or str(globals().get("HIST_START") or "")
    if not getattr(A, "dump_end", ""):
        A.dump_end = t or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    print(_strategy_tag(), "last bar start=", A.dump_start, "end=", A.dump_end)
    _dump_periods(C)


def _dump_on_stop(C):
    if getattr(A, "_dumped", False):
        return
    t = _bar_time_str(C)
    if t and (not getattr(A, "dump_start", "")):
        A.dump_start = t
    if t:
        A.dump_end = t
    if not getattr(A, "dump_start", "") or not getattr(A, "dump_end", ""):
        print(_strategy_tag(), "stop skip, range incomplete", A.dump_start, A.dump_end)
        return
    print(_strategy_tag(), "stop dump start=", A.dump_start, "end=", A.dump_end)
    _dump_periods(C)
