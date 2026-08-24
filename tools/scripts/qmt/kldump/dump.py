# === kldump/dump.py ===
# 作用: 按主图标的/周期拉 K 线并写成 CSV
import csv


def _apply_hist_start():
    hs = str(globals().get("HIST_START") or "").strip()
    if not hs:
        return
    mapping = {}
    for p in (globals().get("_VALID_PERIODS") or ()):
        mapping[p] = hs
    globals()["_PERIOD_HIST_START"] = mapping


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


def _fetch_md(C, stock, period, count):
    fields = ["open", "high", "low", "close", "volume", "amount"]
    start = str(globals().get("HIST_START") or "")
    end = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
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
    return md, source


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
    count = int(globals().get("BAR_COUNT") or 5000)
    md, source = _fetch_md(C, stock, period, count)
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
    n = len(close)
    rows = []
    i = 0
    while i < n:
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
    first_day = _compact_day(times[0]) if times else ""
    last_day = _compact_day(times[-1]) if times else ""
    if not first_day:
        first_day = str(globals().get("HIST_START") or "start")
    if not last_day:
        last_day = datetime.datetime.now().strftime("%Y%m%d")
    fname = "%s_%s_%s_%s.csv" % (_stock_tag(stock), period, first_day, last_day)
    out_dir = str(globals().get("OUT_DIR") or "")
    path = os.path.join(out_dir, fname)
    _write_csv(path, rows)
    print(
        _strategy_tag(),
        "dumped n=",
        n,
        "period=",
        period,
        "source=",
        source,
        "path=",
        path,
    )
    return path


def _dump_init(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period_dump(C)
    A._diag = set()
    A.is_backtest = bool(getattr(C, "do_back_test", False))
    _apply_hist_start()
    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        A.stock,
        "PERIOD=",
        A.period,
        "BACKTEST=",
        A.is_backtest,
        "BAR_COUNT=",
        int(globals().get("BAR_COUNT") or 0),
        "OUT_DIR=",
        globals().get("OUT_DIR") or "",
    )
    periods = [A.period]
    for p in (globals().get("EXTRA_PERIODS") or ()):
        n = _norm_period(p)
        if n and n not in periods:
            periods.append(n)
    do_dl = bool(globals().get("DOWNLOAD_HIST", True))
    for period in periods:
        if do_dl:
            try:
                _download_hist(A.stock, period)
            except Exception as e:
                print(_strategy_tag(), "download_hist abort-safe", period, e)
        _dump_period(C, A.stock, period)
