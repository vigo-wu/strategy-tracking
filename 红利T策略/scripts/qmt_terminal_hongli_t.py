#coding:gbk
"""
HongliT v2.12 for Guojin QMT terminal (model trade).

Main chart: 561580.SH; PERIOD below or "follow" chart period.
UI: select stock + account, run in LIVE (not simulate) to send orders.

Rules:
  R-A   zero float + lower band + J<=0     -> buy Float A (50000)
  R-B   has A + lower + J<=0 + drop>=2.5%  -> buy Float B (25000) else skip
  R-Sell upper + J>=100                    -> sell ALL float A/B
  No R1

Risk profile (any PERIOD when USE_RISK_RULES=True):
  - ENABLE_FLOAT_B=False      -> skip R-B (A-only)
  - EXIT_AFTER                -> defer R-Sell/MaxHold until HHMMSS (intraday only; StopLoss may bypass)
  - STOP_LOSS_IGNORE_EXIT_AFTER -> StopLoss may fire before EXIT_AFTER
  - MAX_HOLD_DAYS             -> soft max-hold (loss-only) calendar days; 0=off
  - MAX_HOLD_HARD_DAYS        -> hard force clear even if profit; 0=off
  - COOLDOWN_BARS / LOSS      -> asymmetric cooldown after sell (in barpos units)
  - NO_ENTRY_AFTER            -> no new R-A at/after HHMMSS (intraday only); ""=off
  - STOP_LOSS                 -> soft stop vs avg float cost; 0=off
  - REQUIRE_ABOVE_DAILY_MA    -> open only if daily close > MA(DAILY_MA_N)
  - DAILY_MA_N                -> any MA length (e.g. 10/20/60)

IMPORTANT:
  - Keep this file encoding=GBK, first line #coding:gbk
  - This script only trades float A/B (no base position)
  - DRY_RUN=True prints only; set False to passorder
  - Download matching period history in QMT data manager before backtest
"""
import datetime
import json
import os

import numpy as np

# ===================== user config =====================
DRY_RUN = False

# Fallback when not started from "模型交易" (no account/accountType inject)
ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

FLOAT_A_BUDGET = 50000.0
FLOAT_B_BUDGET = 25000.0
SPACE_STEP = 0.025

BOLL_N = 20
BOLL_K = 2.0
KDJ_N = 9
LOWER_TOL = 1.002
UPPER_TOL = 0.998

# K-line period for indicators / decisions.
# "follow" = C.period from main chart; or set explicitly:
#   1m / 3m / 5m / 15m / 30m / 1h / 1d / 1w / 1mon / 1q / 1hy / 1y
PERIOD = "follow"
# 0 = auto count by period; else fixed bar count for OHLC fetch
OHLC_COUNT = 0

# ---- risk profile (any PERIOD) ----
# Master switch: False = classic R-A/B/Sell only (no maxhold/cooldown/time gates/stop).
USE_RISK_RULES = True
ENABLE_FLOAT_B = False      # False = close R-B (A-only); ignored if USE_RISK_RULES=False (B on)
EXIT_AFTER = "100000"       # defer R-Sell/MaxHold until HHMMSS; ""=off; intraday only
STOP_LOSS_IGNORE_EXIT_AFTER = True  # StopLoss may fire before EXIT_AFTER (gap guard)
MAX_HOLD_DAYS = 4           # soft: force clear if hold>=N AND float loss; 0=off
MAX_HOLD_ONLY_LOSS = True
MAX_HOLD_HARD_DAYS = 8      # always force clear at N days (leak guard); 0=off
COOLDOWN_BARS = 16          # after profitable sell (barpos units; tune per PERIOD)
COOLDOWN_BARS_LOSS = 28     # after losing sell
NO_ENTRY_AFTER = "143000"   # no new R-A at/after HHMMSS; ""=off; intraday only
STOP_LOSS = 0.03            # soft stop vs avg float cost; 0=off

# Daily trend filter (applies to R-A / R-B on any period)
REQUIRE_ABOVE_DAILY_MA = True   # only open when daily close > MA(DAILY_MA_N)
DAILY_MA_N = 20                 # MA period: any int >=2 (10/20/60/...)
DAILY_MA_COUNT = 60             # fetch bars; auto raised to >= DAILY_MA_N+5

# Live decision window (only for daily+ periods; intraday uses every bar in session)
DECISION_START = "143000"
DECISION_END = "145700"

# QMT model runtime has no __file__; use fixed path under terminal python/
STATE_FILE = r"D:\service\GJQMT\python\hongli_t_qmt_state.json"
# =======================================================

_VALID_PERIODS = (
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "1d",
    "1w",
    "1mon",
    "1q",
    "1hy",
    "1y",
)
_PERIOD_COUNT = {
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
_PERIOD_HIST_START = {
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


class _S(object):
    pass


A = _S()


def _lot(price, budget):
    if price is None or price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * 100)) * 100


def _norm_period(p):
    if p is None:
        return None
    s = str(p).strip().lower()
    if s in ("", "follow", "none"):
        return None
    # common aliases from chart UI
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
    if s in _VALID_PERIODS:
        return s
    return None


def _resolve_period(C):
    """PERIOD config, else C.period, else 1d."""
    cfg = _norm_period(PERIOD)
    if cfg:
        return cfg
    chart = _norm_period(getattr(C, "period", None))
    if chart:
        return chart
    return "1d"


def _is_intraday(period):
    p = period or "1d"
    if p == "1mon":
        return False
    return p.endswith("m") or p == "1h"


def _ohlc_count(period):
    if OHLC_COUNT and int(OHLC_COUNT) > 0:
        return int(OHLC_COUNT)
    return int(_PERIOD_COUNT.get(period, 120))


def _hist_start(period):
    return _PERIOD_HIST_START.get(period, "20220101")


def _bar_end_str(C):
    """end_time for get_market_data*: yyyymmdd or yyyymmddHHMMSS."""
    dt = _bar_datetime(C)
    if _is_intraday(getattr(A, "period", "1d")):
        return dt.strftime("%Y%m%d%H%M%S")
    return dt.strftime("%Y%m%d")


def _load_state():
    A.float_a = None
    A.float_b = None
    A.acted_day = ""
    A.acted = set()
    A.cooldown_until_bar = -1
    if not os.path.isfile(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r") as f:
            raw = json.load(f)
        A.float_a = raw.get("float_a")
        A.float_b = raw.get("float_b")
        A.acted_day = raw.get("acted_day", "") or ""
        A.cooldown_until_bar = int(raw.get("cooldown_until_bar", -1) or -1)
        print("HongliT load state", STATE_FILE, A.float_a, A.float_b, "cd_bar=", A.cooldown_until_bar)
    except Exception as e:
        print("HongliT load state fail", e)


def _save_state():
    payload = {
        "float_a": A.float_a,
        "float_b": A.float_b,
        "acted_day": A.acted_day,
        "cooldown_until_bar": getattr(A, "cooldown_until_bar", -1),
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
    except Exception as e:
        print("HongliT save state fail", e)


def _reset_day(day):
    if A.acted_day != day:
        A.acted_day = day
        A.acted = set()
        _save_state()


def _has_leg(leg):
    return leg is not None and int(leg.get("shares", 0)) >= 100


def _use_risk_rules():
    """Risk profile (maxhold/cooldown/stop/time gates/float-B switch). Any PERIOD."""
    return bool(USE_RISK_RULES)


def _enable_float_b():
    if _use_risk_rules():
        return bool(ENABLE_FLOAT_B)
    return True


def _parse_opened_at(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt, n in (("%Y%m%d%H%M%S", 14), ("%Y-%m-%d %H:%M:%S", 19), ("%Y%m%d", 8)):
        try:
            return datetime.datetime.strptime(s[:n], fmt)
        except Exception:
            continue
    return None


def _hold_days(opened_at, now):
    ot = opened_at if isinstance(opened_at, datetime.datetime) else _parse_opened_at(opened_at)
    if ot is None or now is None:
        return 0.0
    return max(0.0, (now - ot).total_seconds() / 86400.0)


def _float_avg_cost():
    """Share-weighted avg entry of float A/B; 0 if empty."""
    cost = 0.0
    sh = 0
    for leg in (getattr(A, "float_a", None), getattr(A, "float_b", None)):
        if not _has_leg(leg):
            continue
        s = int(leg.get("shares", 0))
        px = float(leg.get("price", 0) or 0)
        if s >= 100 and px > 0:
            cost += s * px
            sh += s
    if sh <= 0:
        return 0.0
    return cost / float(sh)


def _float_ret(last):
    avg = _float_avg_cost()
    if avg <= 0 or last is None or last <= 0:
        return 0.0
    return (float(last) - avg) / avg


def _exit_time_ok(now_s):
    """Defer R-Sell/MaxHold until EXIT_AFTER (intraday only; StopLoss may bypass)."""
    if not _use_risk_rules():
        return True
    if not getattr(A, "intraday", False):
        return True
    gate = str(EXIT_AFTER or "").strip()
    if not gate:
        return True
    return str(now_s) >= gate


def _entry_time_ok(now_s):
    """Block new R-A at/after NO_ENTRY_AFTER (intraday only)."""
    if not _use_risk_rules():
        return True
    if not getattr(A, "intraday", False):
        return True
    gate = str(NO_ENTRY_AFTER or "").strip()
    if not gate:
        return True
    return str(now_s) < gate


def _set_cooldown(C, is_loss=False):
    if not _use_risk_rules():
        return
    bars = int(COOLDOWN_BARS_LOSS) if is_loss else int(COOLDOWN_BARS)
    if bars <= 0:
        return
    until = int(getattr(C, "barpos", 0)) + bars
    A.cooldown_until_bar = until
    print("HongliT cooldown until barpos=", until, "bars=", bars, "loss=", bool(is_loss))


def _in_cooldown(C):
    if not _use_risk_rules():
        return False
    # either win/loss cooldown may be active; until_bar is absolute
    if int(COOLDOWN_BARS) <= 0 and int(COOLDOWN_BARS_LOSS) <= 0:
        return False
    until = int(getattr(A, "cooldown_until_bar", -1) or -1)
    if until < 0:
        return False
    return int(getattr(C, "barpos", 0)) < until


def _sell_float_vol():
    vol = 0
    if _has_leg(getattr(A, "float_a", None)):
        vol += int(A.float_a["shares"])
    if _has_leg(getattr(A, "float_b", None)):
        vol += int(A.float_b["shares"])
    return vol


def _clear_float_after_sell(C, remark, last=None):
    is_loss = False
    if last is not None:
        is_loss = _float_ret(last) < 0
    A.float_a = None
    A.float_b = None
    A.acted.add("SELL")
    _set_cooldown(C, is_loss=is_loss)
    _save_state()
    print("HongliT", remark, "done, float cleared loss=", bool(is_loss))


def _calc_indicators(high, low, close):
    """Return (lower, upper, j, last_close) or None."""
    n = len(close)
    need = max(BOLL_N, KDJ_N) + 2
    if n < need:
        return None
    c = np.asarray(close, dtype=float)
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    # reject padded / flat window (history not ready)
    if np.std(c[-BOLL_N:]) < 1e-8:
        return None
    mid = np.mean(c[-BOLL_N:])
    std = np.std(c[-BOLL_N:])
    lower = mid - BOLL_K * std
    upper = mid + BOLL_K * std

    # KDJ same as run_screener: RSV ewm(com=2)
    rsv = np.zeros(n, dtype=float)
    for i in range(n):
        i0 = max(0, i - KDJ_N + 1)
        hn = np.max(h[i0 : i + 1])
        ln = np.min(l[i0 : i + 1])
        if hn <= ln:
            rsv[i] = 0.0
        else:
            rsv[i] = (c[i] - ln) / (hn - ln) * 100.0
    k = np.zeros(n, dtype=float)
    d = np.zeros(n, dtype=float)
    alpha = 1.0 / 3.0  # ewm com=2 -> alpha=1/(com+1)
    k[0] = rsv[0]
    d[0] = k[0]
    for i in range(1, n):
        k[i] = (1 - alpha) * k[i - 1] + alpha * rsv[i]
        d[i] = (1 - alpha) * d[i - 1] + alpha * k[i]
    j = 3.0 * k[-1] - 2.0 * d[-1]
    return lower, upper, float(j), float(c[-1])


def _bar_end_yyyymmdd(C):
    dt = _bar_datetime(C)
    return dt.strftime("%Y%m%d")


def _diag_once(key, *msg):
    if not hasattr(A, "_diag"):
        A._diag = set()
    if key in A._diag:
        return
    A._diag.add(key)
    print("HongliT diag:", key, " ".join([str(x) for x in msg]))


def _series_from_ex(md, stock, field):
    """Parse get_market_data_ex / get_market_data result into float list."""
    if md is None:
        return None
    obj = None
    # shape1: {code: DataFrame(columns=fields)}
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
    # shape2: {field: DataFrame(columns=codes)} / Series
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
            if fv != fv:  # nan
                continue
            out.append(float(fv))
        except Exception:
            continue
    return out


def _download_hist(stock, period):
    """Supplement local history for the configured period (QMT builtin name varies)."""
    start = _hist_start(period)
    for fn_name in ("download_history_data", "down_history_data"):
        fn = globals().get(fn_name)
        if callable(fn):
            try:
                fn(stock, period, start, "")
                print("HongliT downloaded history via", fn_name, period, "from", start)
                return
            except Exception as e:
                print(fn_name, "fail", e)


def _fetch_closes(C, stock, period, count, end):
    """Fetch close list for an explicit period (used by daily MA filter)."""
    md = None
    try:
        md = C.get_market_data_ex(
            fields=["close"],
            stock_code=[stock],
            period=period,
            end_time=end,
            count=count,
            dividend_type="front_ratio",
            fill_data=True,
            subscribe=False,
        )
    except TypeError:
        try:
            md = C.get_market_data_ex(
                ["close"],
                [stock],
                period=period,
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
        except Exception as e:
            _diag_once("daily_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("daily_ex_fail", e)
        md = None
    closes = _series_from_ex(md, stock, "close") if md is not None else None
    if closes and len(closes) >= 2:
        return closes
    try:
        md2 = C.get_market_data(
            ["close"],
            stock_code=[stock],
            period=period,
            end_time=end,
            count=count,
            dividend_type="front_ratio",
        )
        closes = _series_from_ex(md2, stock, "close")
        if closes and len(closes) >= 2:
            return closes
    except Exception as e:
        _diag_once("daily_gmd_fail", e)
    try:
        c_map = C.get_history_data(count, period, "close", dividend_type="front_ratio")
        if c_map and stock in c_map:
            return [float(x) for x in c_map[stock] if x == x]
    except Exception as e:
        _diag_once("daily_hist_fail", e)
    return None


def _daily_ma_ok(C, stock, closes_hint=None):
    """True if latest daily close > MA(DAILY_MA_N). Cached per hour + MA length."""
    if not bool(REQUIRE_ABOVE_DAILY_MA):
        return True, None, None
    n = int(DAILY_MA_N)
    if n <= 1:
        return True, None, None
    day = _bar_datetime(C).strftime("%Y%m%d")
    # refresh a few times per day on intraday so today's running close updates
    bucket = "%s|ma%d" % (_bar_datetime(C).strftime("%Y%m%d%H"), n)
    cache = getattr(A, "_daily_ma_cache", None)
    if isinstance(cache, dict) and cache.get("bucket") == bucket and cache.get("ok") is not None:
        return bool(cache.get("above")), cache.get("last"), cache.get("ma")

    closes = None
    # if strategy period is already daily, reuse hint series
    if closes_hint is not None and getattr(A, "period", "") == "1d":
        closes = list(closes_hint)
    if not closes:
        end = day  # daily API wants yyyymmdd
        closes = _fetch_closes(C, stock, "1d", max(int(DAILY_MA_COUNT), n + 5), end)
    if not closes or len(closes) < n:
        _diag_once("daily_ma_short", "bars=", 0 if not closes else len(closes), "need=", n)
        # fail-closed: do not open without trend confirmation
        A._daily_ma_cache = {"bucket": bucket, "above": False, "ok": False, "last": None, "ma": None}
        return False, None, None

    last = float(closes[-1])
    ma = float(np.mean(closes[-n:]))
    above = last > ma
    A._daily_ma_cache = {
        "bucket": bucket,
        "above": above,
        "ok": True,
        "last": last,
        "ma": ma,
    }
    _diag_once(
        "daily_ma_ok",
        "last=",
        round(last, 4),
        "ma%d=" % n,
        round(ma, 4),
        "above=",
        above,
    )
    return above, last, ma


def _get_ohlc(C, stock, count=None):
    """Fetch OHLC for A.period; try get_market_data_ex then fallbacks."""
    period = getattr(A, "period", "1d")
    if count is None:
        count = _ohlc_count(period)
    end = _bar_end_str(C)
    need = max(BOLL_N, KDJ_N) + 2
    md = None
    source = None
    high = None
    low = None

    # 1) get_market_data_ex
    try:
        md = C.get_market_data_ex(
            fields=["high", "low", "close"],
            stock_code=[stock],
            period=period,
            end_time=end,
            count=count,
            dividend_type="front_ratio",
            fill_data=True,
            subscribe=False,
        )
        source = "get_market_data_ex"
    except TypeError:
        try:
            md = C.get_market_data_ex(
                ["high", "low", "close"],
                [stock],
                period=period,
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once("ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("ex_fail", e)
        md = None

    close = _series_from_ex(md, stock, "close") if md is not None else None

    # 2) get_market_data
    if not close or len(close) < need:
        try:
            md2 = C.get_market_data(
                ["high", "low", "close"],
                stock_code=[stock],
                period=period,
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data"
            close = _series_from_ex(md2, stock, "close")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
            md = md2
        except Exception as e:
            _diag_once("gmd_fail", e)

    # 3) get_history_data (legacy, still works on some builds)
    if not close or len(close) < need:
        try:
            c_map = C.get_history_data(count, period, "close", dividend_type="front_ratio")
            h_map = C.get_history_data(count, period, "high", dividend_type="front_ratio")
            l_map = C.get_history_data(count, period, "low", dividend_type="front_ratio")
            if c_map and stock in c_map:
                close = [float(x) for x in c_map[stock] if x == x]
                high = [float(x) for x in h_map[stock]] if h_map and stock in h_map else list(close)
                low = [float(x) for x in l_map[stock]] if l_map and stock in l_map else list(close)
                source = "get_history_data"
                md = {"close": close}
        except Exception as e:
            _diag_once("hist_fail", e)

    if not close:
        _diag_once(
            "empty",
            "period=",
            period,
            "end=",
            end,
            "barpos=",
            getattr(C, "barpos", None),
            "md_type=",
            type(md),
            "md_keys=",
            list(md.keys())[:8] if isinstance(md, dict) else None,
        )
        return None

    if md is not None and source != "get_history_data":
        high = _series_from_ex(md, stock, "high")
        low = _series_from_ex(md, stock, "low")
    if not high or len(high) != len(close):
        high = list(close)
    if not low or len(low) != len(close):
        low = list(close)

    if len(close) < need:
        _diag_once(
            "short",
            "period=",
            period,
            "n=",
            len(close),
            "need=",
            need,
            "source=",
            source,
            "end=",
            end,
        )
        return None

    _diag_once(
        "ok",
        "period=",
        period,
        "source=",
        source,
        "n=",
        len(close),
        "end=",
        end,
        "last=",
        close[-1],
        "std20=",
        round(float(np.std(close[-BOLL_N:])), 6),
    )
    return high, low, close


def _is_backtest(C):
    return bool(getattr(C, "do_back_test", False))


def _bar_datetime(C):
    """Bar time in backtest; wall clock in live."""
    try:
        tag = C.get_bar_timetag(C.barpos)
        # timetag_to_datetime is QMT builtin when available
        if "timetag_to_datetime" in globals():
            s = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
            return datetime.datetime.strptime(str(s), "%Y%m%d%H%M%S")
        # fallback: ms timestamp
        if tag > 10**12:
            return datetime.datetime.fromtimestamp(tag / 1000.0)
        return datetime.datetime.fromtimestamp(tag)
    except Exception:
        return datetime.datetime.now()


def _available_cash():
    if getattr(A, "is_backtest", False):
        return 10**9
    accs = get_trade_detail_data(A.acct, A.acct_type, "account")
    if not accs:
        print("account not login", A.acct)
        return None
    return float(accs[0].m_dAvailable)


def _can_use_vol(stock):
    if getattr(A, "is_backtest", False) or DRY_RUN:
        # backtest/dry: trust strategy state shares
        return 10**9
    positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    for p in positions:
        code = p.m_strInstrumentID + "." + p.m_strExchangeID
        if code == stock:
            return int(p.m_nCanUseVolume or 0)
    return 0


def _order_buy(C, vol, remark):
    msg = "HongliT BUY %s %s x%d" % (remark, A.stock, vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        return True
    passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v25", 1, msg, C)
    A.waiting_list.append(msg)
    return True


def _order_sell(C, vol, remark):
    can = _can_use_vol(A.stock)
    vol = min(int(vol), can)
    if vol < 100:
        print("sell skip, can_use=", can, "want=", vol)
        return False
    msg = "HongliT SELL %s %s x%d" % (remark, A.stock, vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        return True
    passorder(A.sell_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v25", 1, msg, C)
    A.waiting_list.append(msg)
    return True


def init(C):
    # stock from chart; account from 模型交易 UI if present, else config
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C)
    A.intraday = _is_intraday(A.period)
    if "account" in globals() and account:
        A.acct = str(account)
    elif hasattr(C, "accountid") and C.accountid:
        A.acct = str(C.accountid)
    else:
        A.acct = ACCOUNT_ID

    if "accountType" in globals() and accountType:
        A.acct_type = str(accountType)
    else:
        A.acct_type = ACCOUNT_TYPE

    try:
        C.set_account(A.acct)
    except Exception:
        pass

    A.buy_code = 23 if A.acct_type == "STOCK" else 33
    A.sell_code = 24 if A.acct_type == "STOCK" else 34
    A.waiting_list = []
    A.busy = False
    A.is_backtest = _is_backtest(C)
    _download_hist(A.stock, A.period)
    if bool(REQUIRE_ABOVE_DAILY_MA):
        _download_hist(A.stock, "1d")
    _load_state()
    # backtest: start with clean float state so replay is consistent
    if A.is_backtest:
        A.float_a = None
        A.float_b = None
        A.acted_day = ""
        A.acted = set()
        A.cooldown_until_bar = -1
        A.ready_logged = False
    else:
        A.ready_logged = True
    if not hasattr(A, "cooldown_until_bar"):
        A.cooldown_until_bar = -1
    C.set_universe([A.stock])
    print(
        "HongliT v2.12 init",
        A.stock,
        A.acct,
        A.acct_type,
        "PERIOD=",
        A.period,
        "cfg=",
        PERIOD,
        "chart=",
        getattr(C, "period", None),
        "riskRules=",
        _use_risk_rules(),
        "B=",
        _enable_float_b(),
        "exitAfter=",
        (EXIT_AFTER if getattr(A, "intraday", False) else "-") if _use_risk_rules() else "-",
        "stopIgnoreExit=",
        STOP_LOSS_IGNORE_EXIT_AFTER if _use_risk_rules() else False,
        "maxHoldDays=",
        MAX_HOLD_DAYS if _use_risk_rules() else 0,
        "maxHoldHard=",
        MAX_HOLD_HARD_DAYS if _use_risk_rules() else 0,
        "cdWin/Loss=",
        ("%s/%s" % (COOLDOWN_BARS, COOLDOWN_BARS_LOSS)) if _use_risk_rules() else "-",
        "noEntryAfter=",
        (NO_ENTRY_AFTER if getattr(A, "intraday", False) else "-") if _use_risk_rules() else "-",
        "stopLoss=",
        STOP_LOSS if _use_risk_rules() else 0,
        "dailyMA=",
        ("on/MA%d" % int(DAILY_MA_N)) if REQUIRE_ABOVE_DAILY_MA else "off",
        "DRY_RUN=",
        DRY_RUN,
        "BACKTEST=",
        A.is_backtest,
        "STATE=",
        STATE_FILE,
    )


def handlebar(C):
    # live: only latest bar; backtest: every bar (skip inside if OHLC not ready)
    if (not getattr(A, "is_backtest", False)) and (not C.is_last_bar()):
        return
    if A.busy:
        return
    A.busy = True
    try:
        if getattr(A, "is_backtest", False) and (C.barpos % 100 == 0):
            print("HongliT progress barpos=", C.barpos, "time=", _bar_end_yyyymmdd(C))
        _handle(C)
    except Exception as e:
        print("HongliT handlebar error", e)
    finally:
        A.busy = False


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    now = _bar_datetime(C) if bt else datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    day = now.strftime("%Y%m%d")
    intraday = getattr(A, "intraday", False)

    if not bt:
        # live: session hours
        if now_s < "093000" or now_s > "150000":
            return
        # daily+: near-close window; intraday: every last bar in session
        if (not intraday) and (now_s < DECISION_START or now_s > DECISION_END):
            return
    # backtest: each bar ~= decision at bar close

    _reset_day(day)

    if (not bt) and A.waiting_list:
        found = []
        orders = get_trade_detail_data(A.acct, A.acct_type, "order")
        for od in orders:
            if od.m_strRemark in A.waiting_list:
                found.append(od.m_strRemark)
        A.waiting_list = [x for x in A.waiting_list if x not in found]
        if A.waiting_list:
            print("waiting orders", A.waiting_list)
            return

    cash = _available_cash()
    if cash is None:
        return

    ohlc = _get_ohlc(C, A.stock)
    if ohlc is None:
        return
    high, low, close = ohlc
    ind = _calc_indicators(high, low, close)
    if ind is None:
        return
    lower, upper, j, last = ind
    buy_cond = (last <= lower * LOWER_TOL) and (j <= 0)
    sell_cond = (last >= upper * UPPER_TOL) and (j >= 100)
    has_a = _has_leg(A.float_a)
    has_b = _has_leg(A.float_b)
    zero_float = (not has_a) and (not has_b)
    drop_vs_a = None
    if has_a:
        ap = float(A.float_a["price"])
        if ap > 0:
            drop_vs_a = (ap - last) / ap

    interesting = buy_cond or sell_cond or has_a or has_b
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 20 == 0):
        A.ready_logged = True
        print(
            "HongliT",
            getattr(A, "period", "?"),
            day,
            now_s,
            "n=%d close=%.4f lower=%.4f upper=%.4f J=%.2f buy=%s sell=%s A=%s B=%s dropA=%s"
            % (
                len(close),
                last,
                lower,
                upper,
                j,
                buy_cond,
                sell_cond,
                has_a,
                has_b,
                None if drop_vs_a is None else round(drop_vs_a * 100, 2),
            ),
        )

    # ensure opened_at exists for live-restored legs (avoid instant MaxHold)
    if has_a and not A.float_a.get("opened_at"):
        A.float_a["opened_at"] = now.strftime("%Y%m%d%H%M%S")
        _save_state()

    hold_d = 0.0
    if has_a:
        hold_d = _hold_days(A.float_a.get("opened_at"), now)
    fret = _float_ret(last) if (has_a or has_b) else 0.0
    exit_ok = _exit_time_ok(now_s)

    # Soft stop (before R-Sell). May ignore EXIT_AFTER to catch open gaps.
    stop_time_ok = exit_ok or bool(STOP_LOSS_IGNORE_EXIT_AFTER)
    if (
        _use_risk_rules()
        and float(STOP_LOSS) > 0
        and (has_a or has_b)
        and fret <= -float(STOP_LOSS)
        and stop_time_ok
        and ("SELL" not in A.acted)
    ):
        sell_vol = _sell_float_vol()
        print(
            "HongliT StopLoss trigger ret=%.2f%% <= -%.2f%% now=%s exitGate=%s"
            % (fret * 100.0, float(STOP_LOSS) * 100.0, now_s, exit_ok)
        )
        if _order_sell(C, sell_vol, "StopLoss"):
            _clear_float_after_sell(C, "StopLoss", last=last)
        return

    # R-Sell first: clear float only
    if sell_cond and (has_a or has_b) and ("SELL" not in A.acted):
        if not exit_ok:
            print("R-Sell defer until", EXIT_AFTER, "now=", now_s)
            return
        else:
            sell_vol = _sell_float_vol()
            if _order_sell(C, sell_vol, "RSell"):
                _clear_float_after_sell(C, "R-Sell", last=last)
            return

    # Soft max-hold (loss-only) + hard max-hold leak guard
    if _use_risk_rules() and (has_a or has_b) and ("SELL" not in A.acted):
        hard_n = int(MAX_HOLD_HARD_DAYS)
        soft_n = int(MAX_HOLD_DAYS)
        hard_hit = hard_n > 0 and hold_d >= float(hard_n)
        soft_hit = soft_n > 0 and hold_d >= float(soft_n)
        if soft_hit and (not hard_hit) and bool(MAX_HOLD_ONLY_LOSS) and fret >= 0:
            soft_hit = False  # float profit: wait for R-Sell
        if hard_hit or soft_hit:
            if not exit_ok:
                print(
                    "MaxHold defer until",
                    EXIT_AFTER,
                    "now=",
                    now_s,
                    "hold=%.2f" % hold_d,
                    "ret=%.2f%%" % (fret * 100.0),
                    "hard=" + str(hard_hit),
                )
            else:
                tag = "MaxHoldHard" if hard_hit else "MaxHold"
                sell_vol = _sell_float_vol()
                print(
                    "HongliT %s trigger hold_days=%.2f soft=%s hard=%s ret=%.2f%%"
                    % (tag, hold_d, soft_n, hard_n, fret * 100.0)
                )
                if _order_sell(C, sell_vol, tag):
                    _clear_float_after_sell(C, tag, last=last)
                return

    # R-A
    if buy_cond and zero_float and ("RA" not in A.acted):
        if not _entry_time_ok(now_s):
            print("R-A skip after", NO_ENTRY_AFTER, "now=", now_s)
            return
        if _in_cooldown(C):
            print(
                "R-A skip cooldown barpos=",
                getattr(C, "barpos", None),
                "until=",
                getattr(A, "cooldown_until_bar", None),
            )
            return
        above_ma, d_last, d_ma = _daily_ma_ok(C, A.stock, closes_hint=close)
        if not above_ma:
            print(
                "R-A skip daily MA%d last=%s ma=%s"
                % (
                    int(DAILY_MA_N),
                    None if d_last is None else round(d_last, 4),
                    None if d_ma is None else round(d_ma, 4),
                )
            )
            return
        budget = min(FLOAT_A_BUDGET, cash)
        vol = _lot(last, budget)
        if vol < 100:
            print("R-A skip cash/lot")
            A.acted.add("RA")
            _save_state()
            return
        if _order_buy(C, vol, "RA"):
            A.float_a = {
                "shares": vol,
                "price": float(last),
                "cost": round(vol * last, 2),
                "opened_at": now.strftime("%Y%m%d%H%M%S"),
            }
            A.acted.add("RA")
            _save_state()
            print("HongliT R-A opened", A.float_a)
        return

    # R-B (disabled when USE_RISK_RULES and ENABLE_FLOAT_B=False)
    if _enable_float_b() and buy_cond and has_a and (not has_b) and ("RB" not in A.acted):
        above_ma, d_last, d_ma = _daily_ma_ok(C, A.stock, closes_hint=close)
        if not above_ma:
            print(
                "R-B skip daily MA%d last=%s ma=%s"
                % (
                    int(DAILY_MA_N),
                    None if d_last is None else round(d_last, 4),
                    None if d_ma is None else round(d_ma, 4),
                )
            )
            return
        ap = float(A.float_a["price"])
        need = ap * (1.0 - SPACE_STEP)
        if last > need + 1e-9:
            print("R-B skip space close=%.4f need<=%.4f" % (last, need))
            return
        budget = min(FLOAT_B_BUDGET, cash)
        vol = _lot(last, budget)
        if vol < 100:
            print("R-B skip cash/lot")
            A.acted.add("RB")
            _save_state()
            return
        if _order_buy(C, vol, "RB"):
            A.float_b = {"shares": vol, "price": float(last), "cost": round(vol * last, 2)}
            A.acted.add("RB")
            _save_state()
            print("HongliT R-B opened", A.float_b)
        return

    if (not buy_cond) and (not sell_cond) and interesting:
        extra = ""
        if _use_risk_rules() and (has_a or has_b):
            extra = " holdDays=%.2f ret=%.2f%%" % (hold_d, fret * 100.0)
        print("HongliT hold float" + extra)


