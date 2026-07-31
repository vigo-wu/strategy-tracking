# coding: utf-8
"""TrendPB v1.0 - 趋势回调策略(国金 QMT 终端模型 / 日线版).

主图周期: 日线. 信号见主题 model.md.
部署: python scripts/qmt/_deploy_qmt_gbk.py -> 写入 QMT python/TrendPB.py (GBK).
注意: 请编辑本仓库 UTF-8 源文件; 勿在 IDE 中直接打开 QMT 目录下的 TrendPB.py(其为 GBK, 会显示乱码).

下单约定 (对齐 qmt-model-script / pitfalls 7.1):
  - DRY_RUN: 只打印, 模拟 T+1, 不 passorder
  - 回测: passorder + 即时落状态; 可卖=bt_held-bt_locked; skip 不清仓
  - 实盘: passorder 后 pending, 成交后才改仓; 可卖=m_nCanUseVolume
"""
import datetime
import json
import os
import traceback

import numpy as np

# ===================== 用户配置 =====================
DRY_RUN = False

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 单笔买入预算（元）
TRADE_BUDGET = 50000.0

# 均线 / RSI / 布林
EMA_FAST = 20
EMA_SLOW = 60
EMA_SLOPE_LOOKBACK = 3
EMA20_TOL = 0.01
RSI_N = 14
RSI_ALERT = 35.0
RSI_DIVERGE_FLOOR = 30.0
RSI_OVERBUY = 70.0
BOLL_N = 20
BOLL_K = 2.0
SWING_N = 8
STOP_BELOW = 0.01
ALERT_LOOKBACK = 8
DIVERGE_LOOKBACK = 20
VOLUME_SHRINK_REQUIRED = False
VOLUME_SHRINK_BARS = 5
STALL_YANG_MAX = 0.008  # 滞涨阳线：涨幅上限

# close=信号日尾盘按收盘; next_open=次日开盘
ENTRY_MODE = "close"

# 主图日线；也可 "follow"
PERIOD = "1d"
# 暖机: EMA60 + RSI + 布林，取足够日线
OHLC_COUNT = 180

# 实盘: 仅最新 K；尾盘决策窗（对应收盘前约5分钟）
LIVE_ONLY_LAST_BAR = True
DECISION_START = "145500"
DECISION_END = "150000"
# next_open 模式次日开盘窗
OPEN_DECISION_START = "093000"
OPEN_DECISION_END = "093500"
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 500
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__；状态绝对路径
STATE_FILE = r"D:\service\GJQMT\python\trend_pb_qmt_state.json"

STRATEGY_NAME = "TrendPB"
STRATEGY_VER = "v1.0"
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)


class _S(object):
    pass


A = _S()


def _lot(price, budget):
    if price is None or price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * 100)) * 100


def _diag_once(key, *parts):
    seen = getattr(A, "_diag_seen", None)
    if seen is None:
        A._diag_seen = set()
        seen = A._diag_seen
    if key in seen:
        return
    seen.add(key)
    msg = " ".join(str(p) for p in parts)
    print("%s diag: %s %s" % (STRATEGY_NAME, key, msg))


def _is_backtest(C):
    return bool(getattr(C, "do_back_test", False))


def _resolve_period(C):
    cfg = str(PERIOD or "1d").strip().lower()
    if cfg == "follow":
        p = str(getattr(C, "period", "1d") or "1d").strip().lower()
        return p if p in _VALID_PERIODS else "1d"
    return cfg if cfg in _VALID_PERIODS else "1d"


def _bar_datetime(C):
    try:
        tag = C.get_bar_timetag(C.barpos)
        if tag is None:
            return datetime.datetime.now()
        s = str(int(tag)) if isinstance(tag, (int, float)) else str(tag)
        if len(s) >= 14:
            return datetime.datetime.strptime(s[:14], "%Y%m%d%H%M%S")
        if len(s) >= 8:
            return datetime.datetime.strptime(s[:8], "%Y%m%d")
    except Exception:
        pass
    try:
        fn = globals().get("timetag_to_datetime")
        if callable(fn):
            tag = C.get_bar_timetag(C.barpos)
            s = fn(tag, "%Y%m%d%H%M%S")
            if s:
                return datetime.datetime.strptime(str(s)[:14], "%Y%m%d%H%M%S")
    except Exception:
        pass
    return datetime.datetime.now()


def _bar_end_str(C):
    dt = _bar_datetime(C)
    period = getattr(A, "period", "1d")
    if period in ("1d", "1w", "1mon", "1q", "1hy", "1y"):
        return dt.strftime("%Y%m%d")
    return dt.strftime("%Y%m%d%H%M%S")


def _parse_opened_at(s):
    s = str(s or "").strip()
    if not s:
        return None
    if len(s) >= 14:
        try:
            return datetime.datetime.strptime(s[:14], "%Y%m%d%H%M%S")
        except Exception:
            pass
    if len(s) >= 8:
        try:
            return datetime.datetime.strptime(s[:8], "%Y%m%d")
        except Exception:
            pass
    return None


# -------------------- 状态 IO --------------------
def _state_path():
    return STATE_FILE


def _load_state():
    A.position = None
    A.acted_day = ""
    A.acted = set()
    A.pending = None
    A.pending_entry = None
    path = _state_path()
    if not path or not os.path.isfile(path):
        print("%s state: empty (no file)" % STRATEGY_NAME)
        return
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except Exception as e:
        print("%s state load fail" % STRATEGY_NAME, e)
        return
    if not isinstance(raw, dict):
        return
    if str(raw.get("stock", "")) and str(raw.get("stock")) != str(A.stock):
        print("%s state stock mismatch, ignore" % STRATEGY_NAME, raw.get("stock"), A.stock)
        return
    pos = raw.get("position")
    if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100:
        A.position = {
            "shares": int(pos["shares"]),
            "price": float(pos.get("price", 0) or 0),
            "cost": float(pos.get("cost", 0) or 0),
            "opened_at": str(pos.get("opened_at", "") or ""),
            "swing_low": float(pos.get("swing_low", 0) or 0),
            "half_taken": bool(pos.get("half_taken", False)),
            "initial_shares": int(pos.get("initial_shares", pos.get("shares", 0)) or 0),
        }
    A.acted_day = str(raw.get("acted_day", "") or "")
    acted = raw.get("acted") or []
    A.acted = set(acted) if isinstance(acted, list) else set()
    pe = raw.get("pending_entry")
    A.pending_entry = pe if isinstance(pe, dict) else None
    print("%s state loaded" % STRATEGY_NAME, A.position)


def _save_state():
    if getattr(A, "is_backtest", False):
        return
    path = _state_path()
    if not path:
        return
    data = {
        "stock": A.stock,
        "version": STRATEGY_VER,
        "position": A.position,
        "acted_day": getattr(A, "acted_day", ""),
        "acted": list(getattr(A, "acted", set()) or []),
        "pending": getattr(A, "pending", None),
        "pending_entry": getattr(A, "pending_entry", None),
    }
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("%s state save fail" % STRATEGY_NAME, e)


def _reset_day(day):
    if getattr(A, "acted_day", "") != day:
        A.acted_day = day
        A.acted = set()


def _has_position():
    pos = getattr(A, "position", None)
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100


def _pos_shares():
    if not _has_position():
        return 0
    return int(A.position.get("shares", 0) or 0)


def _pos_cost_price():
    if not _has_position():
        return 0.0
    return float(A.position.get("price", 0) or 0)


# -------------------- 回测 T+1 --------------------
def _bt_held_vol():
    return max(0, int(getattr(A, "bt_held", 0) or 0))


def _bt_locked_vol():
    return max(0, int(getattr(A, "bt_locked", 0) or 0))


def _bt_available_vol():
    return max(0, _bt_held_vol() - _bt_locked_vol())


def _bt_roll_t1(day):
    if not getattr(A, "is_backtest", False):
        return
    day = str(day or "")
    if not day:
        return
    if str(getattr(A, "bt_lock_day", "") or "") == day:
        return
    if _bt_locked_vol() > 0:
        print("%s bt T+1 unlock day=" % STRATEGY_NAME, day, "was_locked=", _bt_locked_vol())
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


def _bt_recover_position(now=None, last=None):
    if not getattr(A, "is_backtest", False):
        return False
    held = _bt_held_vol()
    if held < 100:
        return False
    if _has_position():
        return False
    px = float(last) if last and last > 0 else 0.0
    ot = str(getattr(A, "bt_opened_at", "") or "").strip()
    if not ot:
        ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    A.position = {
        "shares": held,
        "price": px,
        "cost": round(held * px, 2) if px > 0 else 0.0,
        "opened_at": ot,
        "swing_low": float(getattr(A, "bt_swing_low", 0) or 0),
        "half_taken": bool(getattr(A, "bt_half_taken", False)),
        "initial_shares": int(getattr(A, "bt_initial_shares", held) or held),
    }
    print("%s bt recover position" % STRATEGY_NAME, A.position)
    return True


# -------------------- 指标 --------------------
def _ema(closes, n):
    c = np.asarray(closes, dtype=float)
    if len(c) < n:
        return None
    out = np.empty(len(c), dtype=float)
    out[:] = np.nan
    out[n - 1] = float(np.mean(c[:n]))
    alpha = 2.0 / (float(n) + 1.0)
    for i in range(n, len(c)):
        out[i] = alpha * c[i] + (1.0 - alpha) * out[i - 1]
    return out


def _rsi_wilder(closes, n=None):
    n = int(n if n is not None else RSI_N)
    c = np.asarray(closes, dtype=float)
    length = len(c)
    if length < n + 2:
        return None
    delta = np.diff(c)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    rsi = np.empty(length, dtype=float)
    rsi[:] = np.nan
    avg_gain = float(np.mean(gains[:n]))
    avg_loss = float(np.mean(losses[:n]))
    if avg_loss <= 1e-12:
        rsi[n] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[n] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(n, len(delta)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / float(n)
        avg_loss = (avg_loss * (n - 1) + losses[i]) / float(n)
        if avg_loss <= 1e-12:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def _bollinger(closes, n=None, k=None):
    n = int(n if n is not None else BOLL_N)
    k = float(k if k is not None else BOLL_K)
    c = np.asarray(closes, dtype=float)
    if len(c) < n:
        return None, None, None
    mid = np.empty(len(c), dtype=float)
    up = np.empty(len(c), dtype=float)
    mid[:] = np.nan
    up[:] = np.nan
    for i in range(n - 1, len(c)):
        window = c[i - n + 1 : i + 1]
        m = float(np.mean(window))
        s = float(np.std(window, ddof=0))
        mid[i] = m
        up[i] = m + k * s
    return mid, up, None


def _is_yang(o, c):
    return float(c) > float(o)


def _is_yin(o, c):
    return float(c) < float(o)


def _candle_parts(o, h, l, c):
    o, h, l, c = float(o), float(h), float(l), float(c)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    full = max(h - l, 1e-12)
    return body, upper, lower, full


def _is_bullish_engulfing(o, h, l, c, po, ph, pl, pc):
    if not (_is_yin(po, pc) and _is_yang(o, c)):
        return False
    return float(o) <= float(pc) and float(c) >= float(po)


def _is_hammer(o, h, l, c):
    body, upper, lower, full = _candle_parts(o, h, l, c)
    if body <= 1e-12:
        body = full * 0.01
    if lower < 2.0 * body:
        return False
    if upper > body:
        return False
    # 实体偏上
    return min(o, c) > (float(l) + float(h)) / 2.0


def _is_high_wave(o, h, l, c):
    body, upper, lower, full = _candle_parts(o, h, l, c)
    if full <= 1e-12:
        return False
    if body / full > 0.25:
        return False
    if upper < 0.3 * full or lower < 0.3 * full:
        return False
    return True


def _bullish_pattern(opens, highs, lows, closes, i=-1):
    if len(closes) < 2:
        return False, ""
    i = i if i >= 0 else len(closes) - 1
    if i < 1:
        return False, ""
    o, h, l, c = opens[i], highs[i], lows[i], closes[i]
    po, ph, pl, pc = opens[i - 1], highs[i - 1], lows[i - 1], closes[i - 1]
    if _is_bullish_engulfing(o, h, l, c, po, ph, pl, pc):
        return True, "engulf"
    if _is_hammer(o, h, l, c):
        return True, "hammer"
    if _is_high_wave(o, h, l, c):
        return True, "high_wave"
    return False, ""


def _near_ema20(close, ema20, high, low, tol=None):
    tol = float(tol if tol is not None else EMA20_TOL)
    if ema20 is None or ema20 <= 0:
        return False
    e = float(ema20)
    # 收盘逼近或当日触及
    if abs(float(close) / e - 1.0) <= tol:
        return True
    lo = float(low) * (1.0 - tol)
    hi = float(high) * (1.0 + tol)
    return lo <= e <= hi


def _volume_shrinking(volumes, bars=None):
    bars = int(bars if bars is not None else VOLUME_SHRINK_BARS)
    if volumes is None or len(volumes) < bars + 1:
        return False
    recent = [float(x) for x in volumes[-bars:]]
    # 近 bars 根均量 < 再往前 bars 根均量
    prev = [float(x) for x in volumes[-(2 * bars) : -bars]] if len(volumes) >= 2 * bars else None
    if not prev:
        # 退化: 近段单调不增占比高
        drops = sum(1 for i in range(1, len(recent)) if recent[i] <= recent[i - 1] * 1.05)
        return drops >= max(1, bars - 2)
    return float(np.mean(recent)) < float(np.mean(prev))


def _rsi_alert_recent(rsi, lookback=None, thr=None):
    lookback = int(lookback if lookback is not None else ALERT_LOOKBACK)
    thr = float(thr if thr is not None else RSI_ALERT)
    if rsi is None or len(rsi) < 2:
        return False
    window = rsi[-lookback:]
    vals = [float(x) for x in window if x == x]
    if not vals:
        return False
    return min(vals) <= thr


def _bullish_rsi_divergence(closes, rsi, lookback=None):
    """价格创近端新低，RSI 未同步新低且位于背离关注区附近。"""
    lookback = int(lookback if lookback is not None else DIVERGE_LOOKBACK)
    if closes is None or rsi is None or len(closes) < lookback + 2:
        return False
    c = np.asarray(closes[-lookback:], dtype=float)
    r = np.asarray(rsi[-lookback:], dtype=float)
    if np.any(np.isnan(r)):
        # 忽略 NaN：用有效段
        mask = ~np.isnan(r)
        if int(np.sum(mask)) < 6:
            return False
        c = c[mask]
        r = r[mask]
    cur_i = len(c) - 1
    # 近端最低价位置
    low_i = int(np.argmin(c))
    if low_i == cur_i:
        # 当前即新低：找此前另一低点
        if cur_i < 3:
            return False
        prev_seg = c[: cur_i - 1]
        if len(prev_seg) < 2:
            return False
        prev_i = int(np.argmin(prev_seg))
    else:
        prev_i = low_i
        # 要求当前接近新低
        if float(c[cur_i]) > float(np.min(c)) * 1.01:
            return False
        # 找更早的低点作对比
        if prev_i < 2:
            return False
        earlier = c[: prev_i - 1]
        if len(earlier) < 1:
            return False
        prev_i = int(np.argmin(earlier))
        low_i = int(np.argmin(c))
    # 价格更低或近新低，RSI 更高
    price_ll = float(c[low_i]) <= float(c[prev_i]) * 1.002
    rsi_hl = float(r[low_i]) > float(r[prev_i]) + 0.5
    rsi_near = float(r[low_i]) <= float(RSI_ALERT) + 5.0 or float(r[low_i]) <= float(RSI_DIVERGE_FLOOR) + 8.0
    return price_ll and rsi_hl and rsi_near


def _is_stall_yang(o, h, l, c):
    if not _is_yang(o, c):
        return False
    o, h, l, c = float(o), float(h), float(l), float(c)
    body, upper, lower, full = _candle_parts(o, h, l, c)
    chg = (c - o) / o if o > 0 else 0.0
    if chg <= float(STALL_YANG_MAX):
        return True
    if body > 1e-12 and upper >= body:
        return True
    return False


# -------------------- 行情 --------------------
def _series_from_ex(md, stock, field):
    if md is None:
        return None
    try:
        if isinstance(md, dict) and stock in md:
            df = md[stock]
            if hasattr(df, "columns") and field in getattr(df, "columns", []):
                return [float(x) for x in list(df[field]) if x == x]
            if hasattr(df, field):
                return [float(x) for x in list(getattr(df, field)) if x == x]
        if isinstance(md, dict) and field in md:
            df = md[field]
            if hasattr(df, "columns") and stock in getattr(df, "columns", []):
                return [float(x) for x in list(df[stock]) if x == x]
            if hasattr(df, "__iter__"):
                return [float(x) for x in list(df) if x == x]
    except Exception as e:
        _diag_once("parse_" + field, e)
    return None


def _download_hist(stock, period):
    start = (
        datetime.datetime.now() - datetime.timedelta(days=int(HIST_MAX_LOOKBACK_DAYS))
    ).strftime("%Y%m%d")
    try:
        download_history_data(stock, period, start, "")
        print("%s download_history" % STRATEGY_NAME, stock, period, "from", start)
    except NameError:
        try:
            down_history_data(stock, period, start, "")
        except Exception as e:
            print("%s download fail" % STRATEGY_NAME, e)
    except Exception as e:
        print("%s download fail" % STRATEGY_NAME, e)


def _get_ohlcv(C, stock, count=None):
    period = getattr(A, "period", "1d")
    if count is None:
        count = int(OHLC_COUNT) if OHLC_COUNT else 180
    end = _bar_end_str(C)
    need = max(int(EMA_SLOW), int(BOLL_N), int(RSI_N)) + int(EMA_SLOPE_LOOKBACK) + 5
    md = None
    source = None
    open_ = high = low = close = volume = None

    try:
        md = C.get_market_data_ex(
            fields=["open", "high", "low", "close", "volume"],
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
                ["open", "high", "low", "close", "volume"],
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

    if md is not None:
        open_ = _series_from_ex(md, stock, "open")
        high = _series_from_ex(md, stock, "high")
        low = _series_from_ex(md, stock, "low")
        close = _series_from_ex(md, stock, "close")
        volume = _series_from_ex(md, stock, "volume")

    if not close or len(close) < need:
        try:
            md2 = C.get_market_data(
                ["open", "high", "low", "close", "volume"],
                stock_code=[stock],
                period=period,
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data"
            open_ = _series_from_ex(md2, stock, "open")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
            close = _series_from_ex(md2, stock, "close")
            volume = _series_from_ex(md2, stock, "volume")
        except Exception as e:
            _diag_once("gmd_fail", e)

    if not close or len(close) < need:
        _diag_once("empty", "period=", period, "end=", end, "n=", 0 if not close else len(close))
        return None

    n = len(close)
    if not open_ or len(open_) != n:
        open_ = list(close)
    if not high or len(high) != n:
        high = list(close)
    if not low or len(low) != n:
        low = list(close)
    if not volume or len(volume) != n:
        volume = [0.0] * n

    if np.std(np.asarray(close[-min(20, len(close)) :], dtype=float)) < 1e-8:
        _diag_once("flat", "n=", len(close), "source=", source)
        return None

    _diag_once(
        "ok",
        "source=",
        source,
        "n=",
        len(close),
        "end=",
        end,
        "last=",
        round(float(close[-1]), 4),
    )
    return open_, high, low, close, volume


# -------------------- 经纪 / 下单 --------------------
def _available_cash():
    if getattr(A, "is_backtest", False):
        return 10 ** 9
    try:
        accs = get_trade_detail_data(A.acct, A.acct_type, "account")
        if not accs:
            print("%s account not login" % STRATEGY_NAME, A.acct)
            return None
        return float(accs[0].m_dAvailable)
    except Exception as e:
        _diag_once("cash_fail", e)
        return None


def _pos_code(p):
    return str(getattr(p, "m_strInstrumentID", "") or "") + "." + str(
        getattr(p, "m_strExchangeID", "") or ""
    )


def _broker_position(stock):
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return 0, 0, 0.0
    try:
        positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    except Exception as e:
        print("%s position query fail" % STRATEGY_NAME, e)
        return 0, 0, 0.0
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


def _dry_t1_sellable(want, now):
    want = int(want)
    if want < 100:
        return 0
    if not _has_position():
        return 0
    ot = _parse_opened_at(A.position.get("opened_at"))
    if ot is not None and now is not None and ot.date() == now.date():
        return 0
    return want


def _max_sell_vol(now=None):
    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        if now is not None:
            _bt_roll_t1(now.strftime("%Y%m%d"))
        want = max(want, _bt_held_vol())
        return max(0, min(want, _bt_available_vol()))
    if want < 100:
        return 0
    if DRY_RUN:
        return _dry_t1_sellable(want, now or datetime.datetime.now())
    broker_vol, can, _cost = _broker_position(A.stock)
    return max(0, min(want, int(can), int(broker_vol)))


def _new_remark(tag, side, vol):
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return "%s %s %s %s x%d %s" % (STRATEGY_NAME, side, tag, A.stock, int(vol), ts)


def _apply_buy_fill(vol, price, opened_at, swing_low=0.0):
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < 100:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    sl = float(swing_low or 0.0)
    A.position = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
        "swing_low": sl,
        "half_taken": False,
        "initial_shares": vol,
    }
    A.acted.add("BUY")
    A.pending_entry = None
    if getattr(A, "is_backtest", False):
        A.bt_opened_at = ot
        A.bt_swing_low = sl
        A.bt_half_taken = False
        A.bt_initial_shares = vol
    buy_day = ot[:8] if len(ot) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    _save_state()
    print("%s BUY filled" % STRATEGY_NAME, A.position)


def _apply_sell_fill(now, reason, last_hint, filled_vol, mark_half=False):
    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    filled_vol = int(filled_vol)
    if filled_vol < 100:
        return
    if filled_vol >= max(100, int(want * 0.95)) or filled_vol >= want:
        _clear_after_sell(now, reason, last=last_hint)
        return
    remain = max(0, want - filled_vol)
    print("%s partial sell fill" % STRATEGY_NAME, filled_vol, "remain~", remain, reason)
    if A.position:
        A.position["shares"] = remain
        if mark_half or str(reason).startswith("boll_half"):
            A.position["half_taken"] = True
            if getattr(A, "is_backtest", False):
                A.bt_half_taken = True
    _bt_held_set(remain)
    if remain < 100:
        _clear_after_sell(now, str(reason) + "/partial", last=last_hint)
    else:
        A.acted.add("HALF")
        _save_state()


def _clear_after_sell(now, reason, last=None):
    print("%s SELL done" % STRATEGY_NAME, reason, "last=", last, "cleared", A.position)
    A.position = None
    A.acted.add("SELL")
    if getattr(A, "is_backtest", False):
        A.bt_held = 0
        A.bt_locked = 0
        A.bt_opened_at = ""
        A.bt_swing_low = 0.0
        A.bt_half_taken = False
        A.bt_initial_shares = 0
    _save_state()


def _clear_pending(reason=""):
    if getattr(A, "pending", None):
        print("%s pending clear" % STRATEGY_NAME, reason, A.pending.get("remark"))
    A.pending = None
    _save_state()


def _order_buy(C, price, now, swing_low=0.0):
    if getattr(A, "pending", None):
        print("%s buy skip: pending active" % STRATEGY_NAME)
        return False
    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        print("%s buy skip: already holding" % STRATEGY_NAME)
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False
    vol = _lot(price, TRADE_BUDGET)
    if vol < 100:
        print("%s buy skip lot" % STRATEGY_NAME, "price=", price, "budget=", TRADE_BUDGET)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _lot(price, cash)
        if vol < 100:
            print("%s buy skip cash" % STRATEGY_NAME, cash)
            return False

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark("BUY", "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@", price, "swing_low=", swing_low)
    if DRY_RUN:
        _apply_buy_fill(vol, price, ot, swing_low=swing_low)
        return True
    try:
        passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, STRATEGY_NAME, 1, msg, C)
    except Exception as e:
        print("%s passorder BUY fail" % STRATEGY_NAME, e)
        return False
    if getattr(A, "is_backtest", False):
        _apply_buy_fill(vol, price, ot, swing_low=swing_low)
        return True
    A.pending = {
        "remark": msg,
        "side": "buy",
        "intent": "BUY",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "opened_at": ot,
        "submitted_at": ot,
        "swing_low": float(swing_low or 0),
        "cancel_requested": False,
    }
    _save_state()
    print("%s BUY submitted" % STRATEGY_NAME, vol, msg)
    return True


def _order_sell(C, reason, price, now, want_vol=None, mark_half=False):
    if getattr(A, "pending", None):
        print("%s sell skip: pending active" % STRATEGY_NAME)
        return False
    if not _has_position() and not (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        return False
    if "SELL" in getattr(A, "acted", set()):
        return False
    if mark_half and "HALF" in getattr(A, "acted", set()):
        return False

    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    if want < 100:
        return False
    if want_vol is not None:
        want = min(want, int(want_vol))

    avail = _max_sell_vol(now)
    vol = int(min(want, avail) // 100) * 100
    if vol < 100:
        if getattr(A, "is_backtest", False):
            print(
                "%s sell skip T+1" % STRATEGY_NAME,
                reason,
                "avail=",
                avail,
                "held=",
                _bt_held_vol(),
                "locked=",
                _bt_locked_vol(),
                "want=",
                want,
            )
        elif DRY_RUN:
            print(
                "%s [DRY] sell skip T+1" % STRATEGY_NAME,
                reason,
                "want=",
                want,
                "sellable=",
                avail,
            )
        else:
            broker_vol, can, _cost = _broker_position(A.stock)
            print(
                "%s sell skip T+1/live" % STRATEGY_NAME,
                reason,
                "can_use=",
                can,
                "broker=",
                broker_vol,
                "want=",
                want,
            )
        return False

    msg = _new_remark(reason or "SELL", "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@", price)
    if DRY_RUN:
        _apply_sell_fill(now, reason, price, vol, mark_half=mark_half)
        return True
    try:
        passorder(A.sell_code, 1101, A.acct, A.stock, 14, -1, vol, STRATEGY_NAME, 1, msg, C)
    except Exception as e:
        print("%s passorder SELL fail" % STRATEGY_NAME, e)
        return False
    if getattr(A, "is_backtest", False):
        _apply_sell_fill(now, reason, price, vol, mark_half=mark_half)
        return True
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": reason or "SELL",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "last_hint": price,
        "mark_half": bool(mark_half),
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
    }
    _save_state()
    print("%s SELL submitted" % STRATEGY_NAME, vol, reason, msg)
    return True


def _deal_fill(remark, stock):
    vol = 0
    notional = 0.0
    try:
        deals = get_trade_detail_data(A.acct, A.acct_type, "deal")
    except Exception as e:
        print("%s deal query fail" % STRATEGY_NAME, e)
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
        print("%s order query fail" % STRATEGY_NAME, e)
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
    oid = _order_sys_id(od)
    if oid is None:
        print("%s cancel skip: no order id" % STRATEGY_NAME)
        return False
    for fn_name in ("cancel", "cancel_order", "cancelorder"):
        fn = globals().get(fn_name)
        if not callable(fn):
            continue
        try:
            fn(oid, A.acct, A.acct_type, C)
            print("%s cancel via" % STRATEGY_NAME, fn_name, oid)
            return True
        except TypeError:
            try:
                fn(oid, A.acct, A.acct_type)
                print("%s cancel via" % STRATEGY_NAME, fn_name, "(3arg)", oid)
                return True
            except Exception as e:
                print("%s" % STRATEGY_NAME, fn_name, "fail", e)
        except Exception as e:
            print("%s" % STRATEGY_NAME, fn_name, "fail", e)
    print("%s cancel unavailable; keep waiting, oid=" % STRATEGY_NAME, oid)
    return False


def _process_pending(C, now):
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
        "%s pending check" % STRATEGY_NAME,
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
            _apply_buy_fill(
                use_vol,
                px,
                pend.get("opened_at") or pend.get("submitted_at"),
                swing_low=float(pend.get("swing_low", 0) or 0),
            )
        else:
            _apply_sell_fill(
                now,
                intent,
                pend.get("last_hint") or px,
                use_vol,
                mark_half=bool(pend.get("mark_half")),
            )
        _clear_pending("filled")
        return False

    if status_dead:
        if traded >= 100:
            if side == "buy":
                _apply_buy_fill(
                    traded,
                    px,
                    pend.get("opened_at") or pend.get("submitted_at"),
                    swing_low=float(pend.get("swing_low", 0) or 0),
                )
            else:
                _apply_sell_fill(
                    now,
                    intent,
                    pend.get("last_hint") or px,
                    traded,
                    mark_half=bool(pend.get("mark_half")),
                )
            _clear_pending("dead-partial")
        else:
            _clear_pending("rejected/cancelled")
        return False

    if age >= float(PENDING_TIMEOUT_SEC):
        if not cancel_req:
            if od is not None:
                _try_cancel_order(od, C)
            else:
                print("%s pending timeout, order not visible yet" % STRATEGY_NAME)
            pend["cancel_requested"] = True
            pend["cancel_at"] = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
            A.pending = pend
            _save_state()
            return True
        cancel_at = _parse_opened_at(pend.get("cancel_at"))
        cancel_age = 0.0
        if cancel_at is not None and now is not None:
            cancel_age = (now - cancel_at).total_seconds()
        if od is None and cancel_age >= float(PENDING_ORPHAN_SEC):
            print("%s pending orphan clear (no order after cancel wait)" % STRATEGY_NAME)
            _clear_pending("orphan")
            return False
        return True

    return True


# -------------------- 信号 --------------------
def _bar_hhmm(dt):
    if dt is None:
        return "0000"
    return dt.strftime("%H%M")


def _bar_hhmmss(dt):
    if dt is None:
        return "000000"
    return dt.strftime("%H%M%S")


def _in_live_decision_window(now):
    t = _bar_hhmmss(now)
    mode = str(ENTRY_MODE or "close").strip().lower()
    if mode == "next_open":
        # 开盘窗处理 pending_entry；尾盘窗打标
        if OPEN_DECISION_START <= t <= OPEN_DECISION_END:
            return True, "open"
        if DECISION_START <= t <= DECISION_END:
            return True, "close"
        return False, ""
    return (DECISION_START <= t <= DECISION_END), "close"


def _eval_buy(opens, highs, lows, closes, volumes, ema20, ema60, rsi):
    """返回 (buy, detail_dict)。"""
    detail = {
        "trend": False,
        "near20": False,
        "vol_ok": False,
        "rsi_alert": False,
        "diverge": False,
        "rsi_cross": False,
        "pattern": "",
        "yang": False,
    }
    if closes is None or ema20 is None or ema60 is None or rsi is None:
        return False, detail
    if len(closes) < max(EMA_SLOW, BOLL_N) + EMA_SLOPE_LOOKBACK + 2:
        return False, detail

    i = len(closes) - 1
    lb = int(EMA_SLOPE_LOOKBACK)
    e20 = float(ema20[i]) if ema20[i] == ema20[i] else None
    e60 = float(ema60[i]) if ema60[i] == ema60[i] else None
    e60_prev = float(ema60[i - lb]) if ema60[i - lb] == ema60[i - lb] else None
    if e20 is None or e60 is None or e60_prev is None:
        return False, detail

    price = float(closes[i])
    detail["trend"] = (price > e60) and (e60 > e60_prev)
    detail["near20"] = _near_ema20(price, e20, highs[i], lows[i])
    detail["vol_ok"] = _volume_shrinking(volumes)
    detail["rsi_alert"] = _rsi_alert_recent(rsi)
    detail["diverge"] = _bullish_rsi_divergence(closes, rsi)
    r0 = float(rsi[i]) if rsi[i] == rsi[i] else None
    r1 = float(rsi[i - 1]) if rsi[i - 1] == rsi[i - 1] else None
    detail["rsi_cross"] = (
        r0 is not None
        and r1 is not None
        and r1 <= float(RSI_ALERT)
        and r0 > float(RSI_ALERT)
    )
    ok_pat, pat = _bullish_pattern(opens, highs, lows, closes, i)
    detail["pattern"] = pat if ok_pat else ""
    detail["yang"] = _is_yang(opens[i], closes[i])

    vol_pass = detail["vol_ok"] if VOLUME_SHRINK_REQUIRED else True
    alert_pass = detail["rsi_alert"] or detail["diverge"]
    buy = (
        detail["trend"]
        and detail["near20"]
        and vol_pass
        and alert_pass
        and detail["rsi_cross"]
        and bool(detail["pattern"])
        and detail["yang"]
    )
    return buy, detail


def _eval_sell(opens, highs, lows, closes, rsi, boll_up, now):
    """返回 (reason, want_vol_or_None, mark_half)。want_vol=None 表示全仓。"""
    if not (_has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100)):
        return None, None, False
    i = len(closes) - 1
    price = float(closes[i])
    pos = A.position or {}
    swing = float(pos.get("swing_low", 0) or getattr(A, "bt_swing_low", 0) or 0)
    half_taken = bool(pos.get("half_taken", False) or getattr(A, "bt_half_taken", False))

    # 1) 止损
    if swing > 0 and price <= swing * (1.0 - float(STOP_BELOW)):
        return "stop_swing", None, False

    # 2) 布林上轨减仓 50%
    bu = float(boll_up[i]) if boll_up is not None and boll_up[i] == boll_up[i] else None
    if (not half_taken) and bu is not None and price >= bu:
        shares = _pos_shares()
        if getattr(A, "is_backtest", False):
            shares = max(shares, _bt_held_vol())
        half = int((shares // 2) // 100) * 100
        if half >= 100 and shares - half >= 100:
            return "boll_half", half, True
        # 不足分拆则直接全清
        return "boll_all", None, False

    # 3) RSI 超买 + 滞涨阳 / 首阴 → 清仓剩余
    r0 = float(rsi[i]) if rsi is not None and rsi[i] == rsi[i] else None
    if r0 is not None and r0 >= float(RSI_OVERBUY):
        if _is_stall_yang(opens[i], highs[i], lows[i], closes[i]) or _is_yin(opens[i], closes[i]):
            return "rsi_exit", None, False

    return None, None, False


def _swing_low_at(lows, n=None):
    n = int(n if n is not None else SWING_N)
    if lows is None or len(lows) < 2:
        return 0.0
    window = lows[-n:] if len(lows) >= n else lows
    return float(np.min(np.asarray(window, dtype=float)))


# -------------------- 主逻辑 --------------------
def _live_heartbeat(tag):
    if getattr(A, "is_backtest", False):
        return
    sec = int(LIVE_HEARTBEAT_SEC or 0)
    if sec <= 0:
        return
    now = datetime.datetime.now()
    last = getattr(A, "_hb_at", None)
    if last is not None and (now - last).total_seconds() < sec:
        return
    A._hb_at = now
    print("%s heartbeat" % STRATEGY_NAME, tag, now.strftime("%H%M%S"))


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    day = now.strftime("%Y%m%d")
    live_phase = "close"

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        in_win, live_phase = _in_live_decision_window(now)
        if not in_win:
            _live_heartbeat("outside_session")
            return
        if LIVE_ONLY_LAST_BAR:
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        _live_heartbeat("in_session")
    else:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    ohlcv = _get_ohlcv(C, A.stock)
    if ohlcv is None:
        _live_heartbeat("ohlcv_none")
        return
    opens, highs, lows, closes, volumes = ohlcv

    ema20 = _ema(closes, EMA_FAST)
    ema60 = _ema(closes, EMA_SLOW)
    rsi = _rsi_wilder(closes, RSI_N)
    _mid, boll_up, _ = _bollinger(closes, BOLL_N, BOLL_K)
    if ema20 is None or ema60 is None or rsi is None:
        _live_heartbeat("ind_none")
        return

    price = float(closes[-1])
    open_px = float(opens[-1])
    if bt:
        _bt_recover_position(now=now, last=price)

    buy, detail = _eval_buy(opens, highs, lows, closes, volumes, ema20, ema60, rsi)
    sell_reason, sell_vol, mark_half = _eval_sell(opens, highs, lows, closes, rsi, boll_up, now)
    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    swing = _swing_low_at(lows)

    e20 = float(ema20[-1]) if ema20[-1] == ema20[-1] else None
    e60 = float(ema60[-1]) if ema60[-1] == ema60[-1] else None
    r0 = float(rsi[-1]) if rsi[-1] == rsi[-1] else None
    bu = float(boll_up[-1]) if boll_up is not None and boll_up[-1] == boll_up[-1] else None

    interesting = buy or bool(sell_reason) or holding
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 5 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            _bar_hhmm(bar_dt),
            "n=%d close=%.4f ema20=%s ema60=%s rsi=%s boll_up=%s buy=%s sell=%s hold=%s "
            "trend=%s near20=%s alert=%s div=%s cross=%s pat=%s yang=%s vol_ok=%s "
            "bt_held=%s avail=%s half=%s"
            % (
                len(closes),
                price,
                None if e20 is None else round(e20, 4),
                None if e60 is None else round(e60, 4),
                None if r0 is None else round(r0, 2),
                None if bu is None else round(bu, 4),
                buy,
                sell_reason,
                holding,
                detail.get("trend"),
                detail.get("near20"),
                detail.get("rsi_alert"),
                detail.get("diverge"),
                detail.get("rsi_cross"),
                detail.get("pattern") or "-",
                detail.get("yang"),
                detail.get("vol_ok"),
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
                (A.position or {}).get("half_taken") if holding else "-",
            ),
        )

    # 先卖后买
    if sell_reason and holding:
        _order_sell(C, sell_reason, price, now, want_vol=sell_vol, mark_half=mark_half)
        return

    mode = str(ENTRY_MODE or "close").strip().lower()

    # next_open: 执行挂起的入场
    pe = getattr(A, "pending_entry", None)
    if (
        (not holding)
        and isinstance(pe, dict)
        and ("BUY" not in getattr(A, "acted", set()))
        and (bt or live_phase == "open" or mode == "next_open")
    ):
        sig_day = str(pe.get("signal_day", "") or "")
        if bt:
            # 回测日线: 信号日的下一根 K 用开盘价买入
            if sig_day and sig_day < day:
                _order_buy(C, open_px, now, swing_low=float(pe.get("swing_low", 0) or 0))
                return
        else:
            if live_phase == "open" and sig_day and sig_day < day:
                _order_buy(C, open_px, now, swing_low=float(pe.get("swing_low", 0) or 0))
                return

    if buy and (not holding) and ("BUY" not in getattr(A, "acted", set())):
        if mode == "next_open":
            A.pending_entry = {
                "signal_day": day,
                "swing_low": swing,
                "close": price,
            }
            _save_state()
            print("%s pending_entry set" % STRATEGY_NAME, A.pending_entry)
            if bt:
                # 回测当日不买，等下一根
                return
            return
        _order_buy(C, price, now, swing_low=swing)


def init(C):
    A.busy = False
    A._hb_at = None
    try:
        _init_impl(C)
    except Exception as e:
        print("%s init error" % STRATEGY_NAME, e)
        try:
            traceback.print_exc()
        except Exception:
            pass


def _init_impl(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C)
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
    A.do_back_test_raw = _is_backtest(C)
    A.is_backtest = A.do_back_test_raw
    A._diag_seen = set()

    do_dl = DOWNLOAD_HIST_BACKTEST if A.is_backtest else DOWNLOAD_HIST_LIVE
    if do_dl:
        try:
            _download_hist(A.stock, A.period)
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, A.period)

    if A.is_backtest:
        barpos = 0
        try:
            barpos = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            barpos = 0
        fresh = (not getattr(A, "_bt_alive", False)) or (barpos <= 0)
        if fresh:
            A.position = None
            A.acted_day = ""
            A.acted = set()
            A.pending = None
            A.pending_entry = None
            A.bt_held = 0
            A.bt_locked = 0
            A.bt_lock_day = ""
            A.bt_opened_at = ""
            A.bt_swing_low = 0.0
            A.bt_half_taken = False
            A.bt_initial_shares = 0
            A._bt_alive = True
            A.ready_logged = False
            print("%s backtest session start barpos=" % STRATEGY_NAME, barpos)
        else:
            if not hasattr(A, "bt_held"):
                A.bt_held = _pos_shares()
            if not hasattr(A, "acted") or A.acted is None:
                A.acted = set()
            if not hasattr(A, "pending"):
                A.pending = None
            if not hasattr(A, "pending_entry"):
                A.pending_entry = None
            _bt_recover_position()
            print(
                "%s backtest re-init preserve barpos=" % STRATEGY_NAME,
                barpos,
                "pos=",
                A.position,
                "bt_held=",
                _bt_held_vol(),
            )
    else:
        _load_state()
        A.ready_logged = False
        if not hasattr(A, "pending"):
            A.pending = None
        if not hasattr(A, "pending_entry"):
            A.pending_entry = None

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)

    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        A.stock,
        A.acct,
        A.acct_type,
        "PERIOD=",
        A.period,
        "BACKTEST=",
        A.is_backtest,
        "DRY_RUN=",
        DRY_RUN,
        "budget=",
        TRADE_BUDGET,
        "EMA=",
        (EMA_FAST, EMA_SLOW),
        "RSI_N=",
        RSI_N,
        "alert=",
        RSI_ALERT,
        "overbuy=",
        RSI_OVERBUY,
        "boll=",
        (BOLL_N, BOLL_K),
        "entry=",
        ENTRY_MODE,
        "stop_below=",
        STOP_BELOW,
    )


def handlebar(C):
    try:
        A.is_backtest = _is_backtest(C)
        if getattr(A, "busy", False):
            return
        A.busy = True
        _handle(C)
    except Exception as e:
        print("%s handlebar error" % STRATEGY_NAME, e)
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        A.busy = False
