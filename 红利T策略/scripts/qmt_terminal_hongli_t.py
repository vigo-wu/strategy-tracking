#coding:gbk
"""
HongliT v2.16 for Guojin QMT terminal (model trade).

Main chart: 561580.SH; PERIOD below or "follow" chart period.
UI: select stock + account, run in LIVE (not simulate) to send orders.

Rules:
  R-A   zero float + lower band + J<=0     -> buy Float A (50000)
  R-B   has A + lower + J<=0 + drop>=2.5%  -> buy Float B (25000) else skip
  R-Sell upper + J>=100                    -> sell ALL float A/B
  No R1

Risk profile (any PERIOD when USE_RISK_RULES=True):
  - ENABLE_FLOAT_B=False      -> skip R-B (A-only)
  - EXIT_AFTER                -> defer R-Sell/MaxHold until HHMMSS; ""=off; intraday only
  - STOP_LOSS_IGNORE_EXIT_AFTER -> StopLoss may fire before EXIT_AFTER
  - MAX_HOLD_DAYS             -> soft max-hold (loss-only) calendar days; 0=off
  - MAX_HOLD_HARD_DAYS        -> hard force clear even if profit; 0=off
  - COOLDOWN_BARS / LOSS      -> after sell; bars * PERIOD duration -> wall-clock until
  - NO_ENTRY_AFTER            -> no new R-A at/after HHMMSS; ""=off; intraday only
  - STOP_LOSS                 -> soft stop vs avg float cost; 0=off
  - REQUIRE_ABOVE_DAILY_MA    -> open only if daily close > MA(DAILY_MA_N)
  - DAILY_MA_N                -> any MA length (e.g. 10/20/60)

Live order safety (v2.16):
  - Update float state only after deal fill (pending); DRY_RUN instant; backtest passorder+instant
  - init reconciles JSON float vs broker (skips if pending); BASE_SHARES never adopted/sold
  - pending timeout -> cancel first; clear only after order terminal (no double order)
  - cooldown stored as wall-clock datetime (survives model restart)
  - T+1 live: sell vol = min(float, m_nCanUseVolume); can_use<100 -> skip, keep float

Backtest safety (v2.16):
  - Mid-run init must NOT wipe float (was causing orphan double R-A)
  - Shadow bt_held tracks passorder fills; R-A blocked if held; sell clears held
  - T+1: bt_locked = same-day buys; sell only available; never clear if QMT would skip
  - Do not load/save STATE_FILE during backtest (memory only)

IMPORTANT:
  - Keep this file encoding=GBK, first line #coding:gbk
  - This script only trades float A/B; set BASE_SHARES if account also holds base
  - DRY_RUN=True prints only; set False to passorder
  - Download matching period history in QMT data manager before backtest
"""
import datetime
import json
import os

import numpy as np

# ===================== user config =====================
DRY_RUN = False

# Fallback when not started from model-trade UI (no account/accountType inject)
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
COOLDOWN_BARS = 16          # after profitable sell; converted to wall time via PERIOD
COOLDOWN_BARS_LOSS = 28     # after losing sell
NO_ENTRY_AFTER = "143000"   # no new R-A at/after HHMMSS; ""=off; intraday only
STOP_LOSS = 0.03            # soft stop vs avg float cost; 0=off
PENDING_TIMEOUT_SEC = 180   # live: request cancel after N seconds if not filled
PENDING_ORPHAN_SEC = 60     # after cancel request, if order never appears, clear pending

# Shares reserved as base position (never adopted / never sold by this strategy)
BASE_SHARES = 0

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
# wall-clock minutes per bar (for cooldown bars -> datetime)
_PERIOD_BAR_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "1d": 24 * 60,
    "1w": 7 * 24 * 60,
    "1mon": 30 * 24 * 60,
    "1q": 90 * 24 * 60,
    "1hy": 180 * 24 * 60,
    "1y": 365 * 24 * 60,
}
# QMT order status (cover common 50-series and compact enums)
_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)  # cancelled / rejected / partial-cancel terminal


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
    A.cooldown_until = ""
    A.pending = None
    if not os.path.isfile(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r") as f:
            raw = json.load(f)
        A.float_a = raw.get("float_a")
        A.float_b = raw.get("float_b")
        A.acted_day = raw.get("acted_day", "") or ""
        acted = raw.get("acted") or []
        if isinstance(acted, list):
            A.acted = set([str(x) for x in acted])
        A.cooldown_until = str(raw.get("cooldown_until", "") or "")
        pend = raw.get("pending")
        A.pending = pend if isinstance(pend, dict) else None
        # drop legacy barpos cooldown (unsafe across restarts)
        print(
            "HongliT load state",
            STATE_FILE,
            A.float_a,
            A.float_b,
            "cd_until=",
            A.cooldown_until or "-",
            "pending=",
            bool(A.pending),
        )
    except Exception as e:
        print("HongliT load state fail", e)


def _save_state():
    # backtest: memory-only; avoid clobbering live JSON / re-init desync
    if getattr(A, "is_backtest", False):
        return
    payload = {
        "float_a": A.float_a,
        "float_b": A.float_b,
        "acted_day": A.acted_day,
        "acted": sorted(list(getattr(A, "acted", set()) or [])),
        "cooldown_until": getattr(A, "cooldown_until", "") or "",
        "pending": getattr(A, "pending", None),
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
    except Exception as e:
        print("HongliT save state fail", e)


def _bt_held_vol():
    return max(0, int(getattr(A, "bt_held", 0) or 0))


def _bt_locked_vol():
    return max(0, int(getattr(A, "bt_locked", 0) or 0))


def _bt_available_vol():
    """Backtest T+1: shares not bought today (QMT can-sell / ke mai)."""
    return max(0, _bt_held_vol() - _bt_locked_vol())


def _bt_roll_t1(day):
    """New calendar day unlocks prior buys for selling."""
    if not getattr(A, "is_backtest", False):
        return
    day = str(day or "")
    if not day:
        return
    if str(getattr(A, "bt_lock_day", "") or "") == day:
        return
    if _bt_locked_vol() > 0:
        print("HongliT bt T+1 unlock day=", day, "was_locked=", _bt_locked_vol())
    A.bt_locked = 0
    A.bt_lock_day = day


def _bt_held_add(vol, buy_day=None):
    if not getattr(A, "is_backtest", False):
        return
    vol = max(0, int(vol))
    A.bt_held = _bt_held_vol() + vol
    if buy_day:
        _bt_roll_t1(str(buy_day)[:8])
        A.bt_locked = _bt_locked_vol() + vol


def _bt_held_set(vol):
    if not getattr(A, "is_backtest", False):
        return
    A.bt_held = max(0, int(vol))
    if A.bt_held < 100:
        A.bt_opened_at = ""
        A.bt_locked = 0
    else:
        A.bt_locked = min(_bt_locked_vol(), A.bt_held)


def _bt_recover_float(now=None, last=None):
    """If shadow held exists but float legs empty, re-adopt so exits still fire."""
    if not getattr(A, "is_backtest", False):
        return False
    held = _bt_held_vol()
    if held < 100:
        return False
    if _sell_float_vol() >= 100:
        return False
    px = float(last) if last and last > 0 else 0.0
    ot = str(getattr(A, "bt_opened_at", "") or "").strip()
    if not ot:
        ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    A.float_a = {
        "shares": held,
        "price": px,
        "cost": round(held * px, 2) if px > 0 else 0.0,
        "opened_at": ot,
    }
    A.float_b = None
    print("HongliT bt recover float from held", A.float_a)
    return True


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


def _cooldown_timedelta(bars):
    p = getattr(A, "period", "1d") or "1d"
    mins = int(_PERIOD_BAR_MINUTES.get(p, 24 * 60))
    return datetime.timedelta(minutes=max(0, int(bars)) * mins)


def _set_cooldown(now, is_loss=False):
    if not _use_risk_rules():
        return
    bars = int(COOLDOWN_BARS_LOSS) if is_loss else int(COOLDOWN_BARS)
    if bars <= 0:
        return
    if now is None:
        now = datetime.datetime.now()
    until = now + _cooldown_timedelta(bars)
    A.cooldown_until = until.strftime("%Y%m%d%H%M%S")
    print(
        "HongliT cooldown until",
        A.cooldown_until,
        "bars=",
        bars,
        "period=",
        getattr(A, "period", "?"),
        "loss=",
        bool(is_loss),
    )


def _in_cooldown(now):
    if not _use_risk_rules():
        return False
    if int(COOLDOWN_BARS) <= 0 and int(COOLDOWN_BARS_LOSS) <= 0:
        return False
    until_s = str(getattr(A, "cooldown_until", "") or "").strip()
    if not until_s:
        return False
    until = _parse_opened_at(until_s)
    if until is None:
        return False
    if now is None:
        now = datetime.datetime.now()
    return now < until


def _sell_float_vol():
    vol = 0
    if _has_leg(getattr(A, "float_a", None)):
        vol += int(A.float_a["shares"])
    if _has_leg(getattr(A, "float_b", None)):
        vol += int(A.float_b["shares"])
    return vol


def _clear_float_after_sell(now, remark, last=None):
    is_loss = False
    if last is not None:
        is_loss = _float_ret(last) < 0
    A.float_a = None
    A.float_b = None
    _bt_held_set(0)
    A.acted.add("SELL")
    _set_cooldown(now, is_loss=is_loss)
    _save_state()
    print("HongliT", remark, "done, float cleared loss=", bool(is_loss))


def _shrink_float_to_vol(target_vol):
    """Reduce float A/B so total shares <= target_vol (drop B first)."""
    target_vol = int(target_vol)
    if target_vol < 100:
        A.float_a = None
        A.float_b = None
        return
    a = int(A.float_a["shares"]) if _has_leg(A.float_a) else 0
    b = int(A.float_b["shares"]) if _has_leg(A.float_b) else 0
    total = a + b
    if total <= target_vol:
        return
    drop = total - target_vol
    if b > 0:
        take = min(b, drop)
        b -= take
        drop -= take
        if b < 100:
            A.float_b = None
        else:
            A.float_b["shares"] = b
            A.float_b["cost"] = round(b * float(A.float_b.get("price", 0) or 0), 2)
    if drop > 0 and a > 0:
        a = max(0, a - drop)
        if a < 100:
            A.float_a = None
        else:
            A.float_a["shares"] = a
            A.float_a["cost"] = round(a * float(A.float_a.get("price", 0) or 0), 2)

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


def _pos_code(p):
    return p.m_strInstrumentID + "." + p.m_strExchangeID


def _broker_position(stock):
    """Return (total_vol, can_use, avg_cost) for stock; (0,0,0) if none."""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return 0, 0, 0.0
    positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    if not positions:
        return 0, 0, 0.0
    for p in positions:
        if _pos_code(p) != stock:
            continue
        vol = int(getattr(p, "m_nVolume", 0) or 0)
        can = int(getattr(p, "m_nCanUseVolume", 0) or 0)
        cost = 0.0
        for attr in ("m_dOpenPrice", "m_dCostPrice", "m_dAvgPrice"):
            v = getattr(p, attr, None)
            if v is not None:
                try:
                    cost = float(v)
                    if cost > 0:
                        break
                except Exception:
                    pass
        return vol, can, cost
    return 0, 0, 0.0


def _can_use_vol(stock):
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return 10**9
    _vol, can, _cost = _broker_position(stock)
    return int(can)


def _base_shares():
    return max(0, int(BASE_SHARES or 0))


def _floatable_broker_vol(broker_vol):
    """Shares above BASE_SHARES that this strategy may manage."""
    return max(0, int(broker_vol) - _base_shares())


def _adopt_share_cap(price):
    """Max shares to adopt on reconcile: float budgets only (not entire account)."""
    budget = float(FLOAT_A_BUDGET)
    if _enable_float_b():
        budget += float(FLOAT_B_BUDGET)
    if price and price > 0:
        return _lot(price, budget)
    # unknown price: cap by budget at ~1 yuan worst-case lot step
    return int(budget // 100) * 100


def _max_sell_vol():
    """Sell at most strategy float, never touch BASE_SHARES. Always T+1-capped."""
    want = _sell_float_vol()
    if getattr(A, "is_backtest", False):
        # include shadow held; cap by T+1 available (matches QMT can-sell)
        want = max(want, _bt_held_vol())
        avail = _bt_available_vol()
        return max(0, min(want, avail))
    if want < 100:
        return 0
    if DRY_RUN:
        # Dry-run still respects calendar T+1 so logs match live constraints.
        return _dry_t1_sellable(want)
    broker_vol, can, _cost = _broker_position(A.stock)
    floatable = _floatable_broker_vol(broker_vol)
    # Live hard rule: never exceed m_nCanUseVolume (same-day buys = 0 can_use).
    return max(0, min(want, int(can), floatable))


def _dry_t1_sellable(want):
    """DRY_RUN T+1: block same-calendar-day exit when no broker can_use feed."""
    want = int(want)
    if want < 100:
        return 0
    now = datetime.datetime.now()
    day = now.strftime("%Y%m%d")
    locked = 0
    for leg in (getattr(A, "float_a", None), getattr(A, "float_b", None)):
        if not _has_leg(leg):
            continue
        ot = _parse_opened_at(leg.get("opened_at"))
        if ot is not None and ot.strftime("%Y%m%d") == day:
            locked += int(leg.get("shares", 0) or 0)
    return max(0, want - locked)


def _reconcile_float_with_broker():
    """Align JSON float vs broker floatable shares. Skip if pending. Never touch BASE_SHARES."""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return
    if getattr(A, "pending", None):
        print("HongliT reconcile skip: pending active")
        return
    broker_vol, _can, broker_cost = _broker_position(A.stock)
    floatable = _floatable_broker_vol(broker_vol)
    state_vol = _sell_float_vol()
    changed = False
    if floatable < 100:
        if state_vol > 0:
            print(
                "HongliT reconcile: no floatable (broker=%s base=%s), clear float was %s"
                % (broker_vol, _base_shares(), state_vol)
            )
            A.float_a = None
            A.float_b = None
            changed = True
    elif state_vol <= 0:
        px = float(broker_cost) if broker_cost and broker_cost > 0 else 0.0
        cap = _adopt_share_cap(px if px > 0 else None)
        sh = int(min(floatable, cap) // 100) * 100
        if sh < 100:
            print(
                "HongliT reconcile: broker has shares but adopt cap <100 (floatable=%s cap=%s); leave unmanaged"
                % (floatable, cap)
            )
        else:
            A.float_a = {
                "shares": sh,
                "price": px,
                "cost": round(sh * px, 2) if px > 0 else 0.0,
                "opened_at": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
                "adopted": True,
            }
            A.float_b = None
            changed = True
            print(
                "HongliT reconcile: adopt floatable as float_a",
                A.float_a,
                "broker=",
                broker_vol,
                "base=",
                _base_shares(),
            )
    elif state_vol > floatable:
        print(
            "HongliT reconcile: shrink float",
            state_vol,
            "->",
            floatable,
            "(broker=%s base=%s)" % (broker_vol, _base_shares()),
        )
        _shrink_float_to_vol(floatable)
        changed = True
    if changed:
        _save_state()


def _deal_fill(remark, stock):
    """Sum deals matching remark+stock -> (vol, avg_price)."""
    vol = 0
    notional = 0.0
    try:
        deals = get_trade_detail_data(A.acct, A.acct_type, "deal")
    except Exception as e:
        print("HongliT deal query fail", e)
        return 0, 0.0
    if not deals:
        return 0, 0.0
    for d in deals:
        if str(getattr(d, "m_strRemark", "") or "") != remark:
            continue
        code = getattr(d, "m_strInstrumentID", "") + "." + getattr(d, "m_strExchangeID", "")
        if code != stock:
            continue
        v = int(getattr(d, "m_nVolume", 0) or 0)
        px = float(getattr(d, "m_dPrice", 0) or 0)
        if v > 0:
            vol += v
            notional += v * px
    avg = (notional / float(vol)) if vol > 0 else 0.0
    return vol, avg


def _find_order(remark, stock):
    try:
        orders = get_trade_detail_data(A.acct, A.acct_type, "order")
    except Exception as e:
        print("HongliT order query fail", e)
        return None
    if not orders:
        return None
    hit = None
    for od in orders:
        if str(getattr(od, "m_strRemark", "") or "") != remark:
            continue
        code = getattr(od, "m_strInstrumentID", "") + "." + getattr(od, "m_strExchangeID", "")
        if code != stock:
            continue
        hit = od
    return hit


def _order_traded_vol(od):
    if od is None:
        return 0
    for attr in ("m_nVolumeTraded", "m_nDealVolume", "m_nTradedVolume"):
        v = getattr(od, attr, None)
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
    return 0


def _order_sys_id(od):
    if od is None:
        return None
    for attr in ("m_strOrderSysID", "m_strOrderID", "m_nOrderID", "m_nRef"):
        v = getattr(od, attr, None)
        if v is None or v == "" or v == 0:
            continue
        return v
    return None


def _try_cancel_order(od, C):
    """Best-effort cancel via QMT builtins (API name varies by build)."""
    oid = _order_sys_id(od)
    if oid is None:
        print("HongliT cancel skip: no order id")
        return False
    # prefer cancel(sysId, account, accountType, ContextInfo)
    for fn_name in ("cancel", "cancel_order", "cancelorder"):
        fn = globals().get(fn_name)
        if not callable(fn):
            continue
        try:
            fn(oid, A.acct, A.acct_type, C)
            print("HongliT cancel via", fn_name, oid)
            return True
        except TypeError:
            try:
                fn(oid, A.acct, A.acct_type)
                print("HongliT cancel via", fn_name, "(3arg)", oid)
                return True
            except Exception as e:
                print("HongliT", fn_name, "fail", e)
        except Exception as e:
            print("HongliT", fn_name, "fail", e)
    print("HongliT cancel unavailable; keep waiting for terminal status, oid=", oid)
    return False


def _apply_buy_fill(intent, vol, price, opened_at):
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < 100:
        return
    leg = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
    }
    if intent == "RA":
        leg["opened_at"] = opened_at or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        A.float_a = leg
        A.acted.add("RA")
        if getattr(A, "is_backtest", False):
            A.bt_opened_at = leg["opened_at"]
        print("HongliT R-A filled", A.float_a)
    elif intent == "RB":
        A.float_b = leg
        A.acted.add("RB")
        print("HongliT R-B filled", A.float_b)
    buy_day = None
    if opened_at:
        buy_day = str(opened_at).strip()[:8]
    elif getattr(A, "is_backtest", False) and intent == "RA" and A.float_a:
        buy_day = str(A.float_a.get("opened_at", "") or "")[:8]
    _bt_held_add(vol, buy_day=buy_day if buy_day and len(buy_day) == 8 else None)
    _save_state()


def _apply_sell_fill(now, intent, last_hint, filled_vol):
    """Clear or shrink float after sell fill."""
    want = _sell_float_vol()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    filled_vol = int(filled_vol)
    tag = intent or "SELL"
    if filled_vol >= max(100, int(want * 0.95)) or filled_vol >= want:
        _clear_float_after_sell(now, tag, last=last_hint)
        return
    if filled_vol >= 100:
        remain = max(0, want - filled_vol)
        print("HongliT partial sell fill", filled_vol, "remain~", remain)
        _shrink_float_to_vol(remain)
        _bt_held_set(remain)
        if remain < 100:
            _clear_float_after_sell(now, tag + "/partial", last=last_hint)
        else:
            A.acted.add("SELL")
            _save_state()


def _clear_pending(reason=""):
    if getattr(A, "pending", None):
        print("HongliT pending clear", reason, A.pending.get("remark"))
    A.pending = None
    _save_state()


def _process_pending(C, now):
    """Live: resolve pending; timeout cancels first; clear only on terminal. Return True if blocking."""
    pend = getattr(A, "pending", None)
    if not pend:
        return False
    if getattr(A, "is_backtest", False) or DRY_RUN:
        A.pending = None
        return False

    remark = str(pend.get("remark", "") or "")
    stock = str(pend.get("stock", A.stock) or A.stock)
    side = str(pend.get("side", "") or "")
    intent = str(pend.get("intent", "") or "")
    target = int(pend.get("vol", 0) or 0)
    submitted = _parse_opened_at(pend.get("submitted_at"))
    age = 0.0
    if submitted is not None and now is not None:
        age = (now - submitted).total_seconds()

    deal_vol, deal_avg = _deal_fill(remark, stock)
    od = _find_order(remark, stock)
    status = int(getattr(od, "m_nOrderStatus", -1) or -1) if od is not None else -1
    traded = max(deal_vol, _order_traded_vol(od))
    px = deal_avg if deal_avg > 0 else float(pend.get("price_hint", 0) or 0)
    cancel_req = bool(pend.get("cancel_requested"))

    print(
        "HongliT pending check",
        intent,
        "deal=",
        deal_vol,
        "traded=",
        traded,
        "status=",
        status,
        "age=%.0fs" % age,
        "cancel_req=",
        cancel_req,
    )

    done_fill = traded >= target and target >= 100
    status_filled = status in _ORDER_FILLED
    status_dead = status in _ORDER_DEAD

    if done_fill or (status_filled and traded >= 100):
        use_vol = traded if traded >= 100 else deal_vol
        if side == "buy":
            _apply_buy_fill(intent, use_vol, px, pend.get("opened_at"))
        else:
            _apply_sell_fill(now, intent, pend.get("last_hint"), use_vol)
        _clear_pending("filled")
        return False

    if status_dead:
        if traded >= 100:
            if side == "buy":
                _apply_buy_fill(intent, traded, px, pend.get("opened_at"))
            else:
                _apply_sell_fill(now, intent, pend.get("last_hint"), traded)
            _clear_pending("dead-partial")
        else:
            _clear_pending("rejected/cancelled")
        return False

    # timeout: request cancel, keep blocking until terminal (prevents double order)
    if age >= float(PENDING_TIMEOUT_SEC):
        if not cancel_req:
            if od is not None:
                _try_cancel_order(od, C)
            else:
                print("HongliT pending timeout, order not visible yet; wait for cancel/orphan")
            pend["cancel_requested"] = True
            pend["cancel_at"] = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
            A.pending = pend
            _save_state()
            return True
        # cancel already requested
        cancel_at = _parse_opened_at(pend.get("cancel_at"))
        cancel_age = 0.0
        if cancel_at is not None and now is not None:
            cancel_age = (now - cancel_at).total_seconds()
        if od is None and cancel_age >= float(PENDING_ORPHAN_SEC):
            # never saw the order - likely submit failed; safe to unlock
            print("HongliT pending orphan clear (no order after cancel wait)")
            _clear_pending("orphan")
            return False
        # still live or settling - do NOT clear, do NOT retry
        return True

    return True


def _new_remark(tag, side, vol):
    # unique remark so deal/order matching does not hit stale rows
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return "HongliT %s %s %s x%d %s" % (side, tag, A.stock, int(vol), ts)


def _order_buy(C, vol, remark_tag, intent, price_hint, opened_at, now):
    """Submit buy. DRY_RUN instant; backtest passorder+instant; live pending until fill."""
    # backtest guard: never open another leg while shadow held remains
    if getattr(A, "is_backtest", False) and intent == "RA" and _bt_held_vol() >= 100:
        print("HongliT R-A skip bt_held=", _bt_held_vol())
        return False
    msg = _new_remark(remark_tag, "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        _apply_buy_fill(intent, vol, price_hint, opened_at)
        return True
    try:
        passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v216", 1, msg, C)
    except Exception as e:
        print("HongliT passorder BUY fail", e)
        return False
    # Backtest: still passorder so QMT shows trade log; apply state immediately
    if getattr(A, "is_backtest", False):
        _apply_buy_fill(intent, vol, price_hint, opened_at)
        return True
    A.pending = {
        "remark": msg,
        "side": "buy",
        "intent": intent,
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price_hint),
        "opened_at": opened_at,
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
    }
    _save_state()
    return True


def _order_sell(C, vol, remark_tag, intent, last_hint, now):
    """Submit sell. DRY_RUN instant; backtest passorder+instant; live pending until fill.

    T+1 (backtest + live): never passorder more than sellable; never clear float on skip.
    Live sellable = m_nCanUseVolume; backtest sellable = bt_held - bt_locked.
    """
    want = int(vol)
    if getattr(A, "is_backtest", False):
        if now is not None:
            _bt_roll_t1(now.strftime("%Y%m%d"))
        want = max(want, _bt_held_vol(), _sell_float_vol())
        avail = _bt_available_vol()
        vol = min(want, avail)
        if vol < 100:
            print(
                "HongliT sell skip T+1 avail=",
                avail,
                "held=",
                _bt_held_vol(),
                "locked=",
                _bt_locked_vol(),
                "want=",
                want,
                "tag=",
                remark_tag,
            )
            return False
    else:
        # live / DRY_RUN: always cap by _max_sell_vol (can_use or dry calendar T+1)
        avail = _max_sell_vol()
        vol = min(want, avail)
        if vol < 100:
            if DRY_RUN:
                print(
                    "HongliT [DRY] sell skip T+1 want=",
                    want,
                    "sellable=",
                    avail,
                    "tag=",
                    remark_tag,
                )
            else:
                broker_vol, can, _cost = _broker_position(A.stock)
                print(
                    "HongliT sell skip T+1/live can_use=",
                    can,
                    "broker=",
                    broker_vol,
                    "float=",
                    _sell_float_vol(),
                    "want=",
                    want,
                    "tag=",
                    remark_tag,
                )
            return False
    msg = _new_remark(remark_tag, "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        # only clear what we "sold" under dry T+1 cap
        if vol >= _sell_float_vol():
            _clear_float_after_sell(now, intent or remark_tag, last=last_hint)
        else:
            remain = max(0, _sell_float_vol() - vol)
            _shrink_float_to_vol(remain)
            if remain < 100:
                _clear_float_after_sell(now, (intent or remark_tag) + "/partial", last=last_hint)
            else:
                _save_state()
        return True
    try:
        passorder(A.sell_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v216", 1, msg, C)
    except Exception as e:
        print("HongliT passorder SELL fail", e)
        return False
    # Backtest: apply only the volume we could sell (T+1-aware); never clear on 0-fill
    if getattr(A, "is_backtest", False):
        held_before = _bt_held_vol()
        if vol >= held_before:
            _clear_float_after_sell(now, intent or remark_tag, last=last_hint)
        else:
            remain = held_before - vol
            print(
                "HongliT T+1 partial sell",
                vol,
                "remain=",
                remain,
                "locked=",
                _bt_locked_vol(),
            )
            _shrink_float_to_vol(remain)
            _bt_held_set(remain)
            if remain < 100:
                _clear_float_after_sell(now, (intent or remark_tag) + "/partial", last=last_hint)
            else:
                _save_state()
        return True
    # Live: pending until broker fill; do NOT clear float here (T+1 skip must not wipe state)
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": intent or remark_tag,
        "vol": int(vol),
        "stock": A.stock,
        "last_hint": last_hint,
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
    }
    _save_state()
    return True


def init(C):
    # stock from chart; account from model-trade UI if present, else config
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
    A.busy = False
    A.is_backtest = _is_backtest(C)
    _download_hist(A.stock, A.period)
    if bool(REQUIRE_ABOVE_DAILY_MA):
        _download_hist(A.stock, "1d")

    if A.is_backtest:
        # QMT may re-call init mid-run; wiping float then orphans passorder fills.
        # Fresh start: first bt session OR barpos near 0 (new replay).
        barpos = 0
        try:
            barpos = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            barpos = 0
        fresh = (not getattr(A, "_bt_alive", False)) or (barpos <= 0)
        if fresh:
            A.float_a = None
            A.float_b = None
            A.acted_day = ""
            A.acted = set()
            A.cooldown_until = ""
            A.pending = None
            A.bt_held = 0
            A.bt_locked = 0
            A.bt_lock_day = ""
            A.bt_opened_at = ""
            A._bt_alive = True
            A.ready_logged = False
            print("HongliT backtest session start barpos=", barpos)
        else:
            if not hasattr(A, "bt_held"):
                A.bt_held = _sell_float_vol()
            if not hasattr(A, "acted") or A.acted is None:
                A.acted = set()
            if not hasattr(A, "cooldown_until"):
                A.cooldown_until = ""
            if not hasattr(A, "pending"):
                A.pending = None
            _bt_recover_float()
            print(
                "HongliT backtest re-init preserve barpos=",
                barpos,
                "float_a=",
                A.float_a,
                "bt_held=",
                _bt_held_vol(),
            )
    else:
        _load_state()
        A.ready_logged = True
        if not hasattr(A, "cooldown_until"):
            A.cooldown_until = ""
        if not hasattr(A, "pending"):
            A.pending = None
        try:
            _reconcile_float_with_broker()
        except Exception as e:
            print("HongliT reconcile fail", e)

    C.set_universe([A.stock])
    print(
        "HongliT v2.16 init",
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
        "baseShares=",
        _base_shares(),
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
        "cdUntil=",
        getattr(A, "cooldown_until", "") or "-",
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
        "bt_held=",
        _bt_held_vol() if A.is_backtest else "-",
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
        # resolve pending fills even outside daily decision window
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                return
        # daily+: near-close window; intraday: every last bar in session
        if (not intraday) and (now_s < DECISION_START or now_s > DECISION_END):
            return
    # backtest: each bar ~= decision at bar close
    if bt:
        _bt_roll_t1(day)
        _bt_recover_float(now=now)

    _reset_day(day)

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
    if bt:
        _bt_recover_float(now=now, last=last)
    buy_cond = (last <= lower * LOWER_TOL) and (j <= 0)
    sell_cond = (last >= upper * UPPER_TOL) and (j >= 100)
    has_a = _has_leg(A.float_a)
    has_b = _has_leg(A.float_b)
    zero_float = (not has_a) and (not has_b)
    # shadow held blocks new R-A even if float legs were wiped mid-run
    if bt and _bt_held_vol() >= 100:
        zero_float = False
    drop_vs_a = None
    if has_a:
        ap = float(A.float_a["price"])
        if ap > 0:
            drop_vs_a = (ap - last) / ap

    interesting = buy_cond or sell_cond or has_a or has_b or (bt and _bt_held_vol() >= 100)
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 20 == 0):
        A.ready_logged = True
        print(
            "HongliT",
            getattr(A, "period", "?"),
            day,
            now_s,
            "n=%d close=%.4f lower=%.4f upper=%.4f J=%.2f buy=%s sell=%s A=%s B=%s dropA=%s bt_held=%s avail=%s"
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
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
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
        and (not getattr(A, "pending", None))
    ):
        sell_vol = _sell_float_vol()
        print(
            "HongliT StopLoss trigger ret=%.2f%% <= -%.2f%% now=%s exitGate=%s"
            % (fret * 100.0, float(STOP_LOSS) * 100.0, now_s, exit_ok)
        )
        _order_sell(C, sell_vol, "StopLoss", "StopLoss", last, now)
        return

    # R-Sell first: clear float only
    if sell_cond and (has_a or has_b) and ("SELL" not in A.acted) and (not getattr(A, "pending", None)):
        if not exit_ok:
            print("R-Sell defer until", EXIT_AFTER, "now=", now_s)
            return
        else:
            sell_vol = _sell_float_vol()
            _order_sell(C, sell_vol, "RSell", "R-Sell", last, now)
            return

    # Soft max-hold (loss-only) + hard max-hold leak guard
    if (
        _use_risk_rules()
        and (has_a or has_b)
        and ("SELL" not in A.acted)
        and (not getattr(A, "pending", None))
    ):
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
                _order_sell(C, sell_vol, tag, tag, last, now)
                return

    # R-A
    if (
        buy_cond
        and zero_float
        and ("RA" not in A.acted)
        and (not getattr(A, "pending", None))
    ):
        if not _entry_time_ok(now_s):
            print("R-A skip after", NO_ENTRY_AFTER, "now=", now_s)
            return
        if _in_cooldown(now):
            print(
                "R-A skip cooldown now=",
                now.strftime("%Y%m%d%H%M%S"),
                "until=",
                getattr(A, "cooldown_until", None),
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
            return
        opened_at = now.strftime("%Y%m%d%H%M%S")
        _order_buy(C, vol, "RA", "RA", last, opened_at, now)
        return

    # R-B (disabled when USE_RISK_RULES and ENABLE_FLOAT_B=False)
    if (
        _enable_float_b()
        and buy_cond
        and has_a
        and (not has_b)
        and ("RB" not in A.acted)
        and (not getattr(A, "pending", None))
    ):
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
            return
        _order_buy(C, vol, "RB", "RB", last, None, now)
        return

    if (not buy_cond) and (not sell_cond) and interesting:
        extra = ""
        if _use_risk_rules() and (has_a or has_b):
            extra = " holdDays=%.2f ret=%.2f%%" % (hold_d, fret * 100.0)
        print("HongliT hold float" + extra)


