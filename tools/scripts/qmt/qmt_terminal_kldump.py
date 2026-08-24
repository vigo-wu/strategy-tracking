#coding:gbk
# 由 _deploy_qmt_gbk.py 自动生成；请勿手改。请编辑策略片段与 scripts/qmt_common/ 后重新部署。
import datetime
import json
import os
import traceback

import numpy as np


# === kldump/config.py ===
# 主图行情导出 CSV。周期跟随当前主图；改完后跑 _deploy_qmt_gbk.py
# QMT 模型无 __file__，OUT_DIR 必须是绝对路径

STRATEGY_NAME = "KlineDump"
STRATEGY_VER = "v1.0"

# 跟随主图；填 1d/15m 等则覆盖 C.period
PERIOD = "follow"

# 导出根目录（绝对路径）
OUT_DIR = r"D:\vigo\strategy-tracking\tools\csv"

# 拉取根数；与 HIST_START 一起决定导出区间（不依赖回测走多少根 K）
BAR_COUNT = 5000
HIST_START = "20220101"
HIST_MAX_LOOKBACK_DAYS = 0

DIVIDEND_TYPE = "front_ratio"
DOWNLOAD_HIST = True

# 额外周期（空=只导主图周期）。例: ("1w",)
EXTRA_PERIODS = ()

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)

# === qmt_common/ctx.py ===
# 作用: 全局运行时对象与手数工具
# 主要符号: A, _S, _lot
# 前置: 策略 config（可选 STRATEGY_NAME）
class _S(object):
    pass


A = _S()


def _lot(price, budget):
    if price is None or price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * 100)) * 100


def _strategy_tag():
    return str(globals().get("STRATEGY_NAME") or "QMT")


# 实盘落盘钩子空实现；引入 common:live_log.py 后覆盖
def _event_log(event, **fields):
    pass


def _bar_log(**fields):
    pass


def _heartbeat_persist(text):
    pass


def _live_state_snapshot(data):
    pass

# === qmt_common/period.py ===
# 作用: 周期解析与取数时间/根数
# 主要符号: _resolve_period, _ohlc_count, _bar_end_str, _hist_start
# 前置: config 中 PERIOD / OHLC_COUNT / HIST_MAX_LOOKBACK_DAYS / _VALID_PERIODS
#       可选 _PERIOD_COUNT / _PERIOD_HIST_START；_bar_datetime 由 mode 提供（运行时）
_DEFAULT_PERIOD_COUNT = {
    "1m": 1200,
    "3m": 800,
    "5m": 600,
    "15m": 400,
    "30m": 300,
    "1h": 240,
    "1d": 120,
    "1w": 100,
    "1mon": 80,
    "1q": 60,
    "1hy": 40,
    "1y": 30,
}
_DEFAULT_PERIOD_HIST_START = {
    "1m": "20240101",
    "3m": "20240101",
    "5m": "20230101",
    "15m": "20230101",
    "30m": "20220101",
    "1h": "20220101",
    "1d": "20220101",
    "1w": "20180101",
    "1mon": "20150101",
    "1q": "20100101",
    "1hy": "20050101",
    "1y": "20000101",
}


def _norm_period(p):
    if p is None:
        return None
    s = str(p).strip().lower()
    if s in ("", "follow", "none"):
        return None
    aliases = {
        "day": "1d",
        "daily": "1d",
        "week": "1w",
        "weekly": "1w",
        "month": "1mon",
        "monthly": "1mon",
        "hour": "1h",
        "60m": "1h",
        "min": "1m",
        "minute": "1m",
    }
    s = aliases.get(s, s)
    valid = globals().get("_VALID_PERIODS") or tuple(_DEFAULT_PERIOD_COUNT.keys())
    if s in valid:
        return s
    return None


def _resolve_period(C, default="1d"):
    """优先 PERIOD 配置，否则 C.period，否则 default。"""
    cfg = _norm_period(globals().get("PERIOD"))
    if cfg:
        return cfg
    chart = _norm_period(getattr(C, "period", None))
    if chart:
        return chart
    return default


def _is_intraday(period):
    p = period or "1d"
    if p == "1mon":
        return False
    return p.endswith("m") or p == "1h"


def _ohlc_count(period):
    oc = globals().get("OHLC_COUNT")
    if oc and int(oc) > 0:
        return int(oc)
    counts = globals().get("_PERIOD_COUNT") or _DEFAULT_PERIOD_COUNT
    return int(counts.get(period, 120))


def _hist_start(period):
    """下载最早 yyyymmdd；受 HIST_MAX_LOOKBACK_DAYS 钳制。"""
    starts = globals().get("_PERIOD_HIST_START") or _DEFAULT_PERIOD_HIST_START
    cfg = str(starts.get(period, "20220101") or "20220101")
    days = int(globals().get("HIST_MAX_LOOKBACK_DAYS") or 0)
    if days <= 0:
        return cfg
    floor = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    if cfg < floor:
        return floor
    return cfg


def _bar_end_str(C):
    """get_market_data* 的 end_time：yyyymmdd 或 yyyymmddHHMMSS。"""
    dt = _bar_datetime(C)
    if _is_intraday(getattr(A, "period", "1d")):
        return dt.strftime("%Y%m%d%H%M%S")
    return dt.strftime("%Y%m%d")

# === qmt_common/market_util.py ===
# 作用: 行情辅助：诊断、序列解析、补历史、心跳
# 主要符号: _diag_once, _series_from_ex, _download_hist, _live_heartbeat
# 可选钩子: _heartbeat_extra() -> str
def _bar_end_yyyymmdd(C):
    dt = _bar_datetime(C)
    return dt.strftime("%Y%m%d")


def _diag_once(key, *msg):
    if not hasattr(A, "_diag"):
        A._diag = set()
    if key in A._diag:
        return
    A._diag.add(key)
    print(_strategy_tag(), "diag:", key, " ".join([str(x) for x in msg]))
    _event_log("diag", key=str(key), msg=" ".join([str(x) for x in msg]))


def _series_from_ex(md, stock, field):
    """将 get_market_data_ex / get_market_data 结果解析为 float 列表。"""
    if md is None:
        return None
    obj = None
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
    if obj is None:
        return None
    try:
        vals = list(np.asarray(obj, dtype=float).reshape(-1))
    except Exception:
        try:
            vals = [float(x) for x in list(obj)]
        except Exception:
            return None
    out = []
    for fv in vals:
        try:
            if fv != fv:  # NaN
                continue
            out.append(float(fv))
        except Exception:
            continue
    return out


def _download_hist(stock, period):
    """按配置周期补本地历史（QMT 内置函数名因版本而异）。"""
    start = _hist_start(period)
    for fn_name in ("download_history_data", "down_history_data"):
        fn = globals().get(fn_name)
        if not callable(fn):
            continue
        try:
            fn(stock, period, start, "")
            print(_strategy_tag(), "downloaded history via", fn_name, period, "from", start)
            return
        except Exception as e:
            print(_strategy_tag(), fn_name, "fail", period, "from", start, e)
    print(_strategy_tag(), "download skip/unavailable period=", period, "from=", start)


def _live_heartbeat(reason=""):
    """周期性实盘日志，避免静默提前 return 被当成模型已停。"""
    if getattr(A, "is_backtest", False):
        return
    sec = int(globals().get("LIVE_HEARTBEAT_SEC") or 0)
    if sec <= 0:
        return
    now = datetime.datetime.now()
    last = getattr(A, "_hb_at", None)
    if last is not None and (now - last).total_seconds() < sec:
        return
    A._hb_at = now
    extra = ""
    fn = globals().get("_heartbeat_extra")
    if callable(fn):
        try:
            extra = str(fn() or "")
        except Exception:
            extra = ""
    print(
        _strategy_tag(),
        "live heartbeat",
        now.strftime("%Y-%m-%d %H:%M:%S"),
        "PERIOD=",
        getattr(A, "period", "?"),
        "stock=",
        getattr(A, "stock", "?"),
        extra,
        ("reason=" + str(reason)) if reason else "",
    )
    _heartbeat_persist(
        "%s live heartbeat %s PERIOD= %s stock= %s %s %s"
        % (
            _strategy_tag(),
            now.strftime("%Y-%m-%d %H:%M:%S"),
            getattr(A, "period", "?"),
            getattr(A, "stock", "?"),
            extra,
            ("reason=" + str(reason)) if reason else "",
        )
    )

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

# === kldump/runtime.py ===
def init(C):
    try:
        _dump_init(C)
    except Exception as e:
        print("%s init error" % STRATEGY_NAME, e)
        try:
            traceback.print_exc()
        except Exception:
            pass


def handlebar(C):
    return
