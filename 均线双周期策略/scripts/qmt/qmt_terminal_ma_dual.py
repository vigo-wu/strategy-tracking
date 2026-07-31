# coding: utf-8
"""MaDual v1.0 - 均线双周期共振(国金 QMT 终端模型 / 1小时版).

主图周期: 1小时. 信号见主题 model.md.
日线 MA20/MA60 定方向; 1小时 MA5 金叉 MA10 找买点; 卖出=日线破MA20或1h硬止损.
部署: python scripts/qmt/_deploy_qmt_gbk.py -> 写入 QMT python/MaDual.py (GBK).
注意: 请编辑本仓库 UTF-8 源文件; 勿在 IDE 中直接打开 QMT 目录下的 MaDual.py(其为 GBK, 会显示乱码).

下单约定 (对齐 qmt-model-script / pitfalls 7.1):
  - DRY_RUN: 只打印, 模拟 T+1, 不 passorder
  - 回测: passorder + 即时落状态; 可卖=bt_held-bt_locked; skip 不清仓
  - 实盘: passorder 后 pending, 成交后才改仓; 可卖=m_nCanUseVolume
  - 买入/卖出均在信号确认后的下一根开盘执行 (pending_entry / pending_exit)
"""
import datetime
import json
import os
import traceback

import numpy as np

# ===================== 用户配置 =====================
DRY_RUN = True

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

TRADE_BUDGET = 50000.0
CASH_RATIO = 0.15

# 日线方向
D_MA_FAST = 20
D_MA_SLOW = 60

# 1小时买点
H_MA_FAST = 5
H_MA_MID = 10
H_MA_SLOW = 120
MA120_TOL = 0.02  # 收盘不低于 MA120 下方 2%

# 卖出
STOP_LOSS = 0.03  # 相对成本 -3%
USE_SWING_STOP = True
SWING_N = 20  # 近期波段低点窗口(1h)

# 主图 1小时
PERIOD = "1h"
# 1h 约 4 根/日; MA120 + 缓冲
OHLC_COUNT = 200
DAILY_OHLC_COUNT = 120

LIVE_ONLY_LAST_BAR = True
DECISION_START = "093000"
DECISION_END = "150000"
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 500
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__; 状态绝对路径
STATE_FILE = r"D:\service\GJQMT\python\ma_dual_qmt_state.json"

STRATEGY_NAME = "MaDual"
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
    cfg = str(PERIOD or "1h").strip().lower()
    if cfg == "follow":
        p = str(getattr(C, "period", "1h") or "1h").strip().lower()
        return p if p in _VALID_PERIODS else "1h"
    return cfg if cfg in _VALID_PERIODS else "1h"


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
    period = getattr(A, "period", "1h")
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
    A.pending_exit = None
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
        }
    A.acted_day = str(raw.get("acted_day", "") or "")
    acted = raw.get("acted") or []
    A.acted = set(acted) if isinstance(acted, list) else set()
    pe = raw.get("pending_entry")
    A.pending_entry = pe if isinstance(pe, dict) else None
    px = raw.get("pending_exit")
    A.pending_exit = px if isinstance(px, dict) else None
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
        "pending_exit": getattr(A, "pending_exit", None),
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


def _entry_date():
    if not _has_position():
        return None
    ot = _parse_opened_at(A.position.get("opened_at"))
    if ot is None:
        return None
    return ot.date()


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
    }
    print("%s bt recover position" % STRATEGY_NAME, A.position)
    return True


# -------------------- 指标 --------------------
def _sma(closes, n):
    c = np.asarray(closes, dtype=float)
    n = int(n)
    if n <= 0 or len(c) < n:
        return None
    out = np.full(len(c), np.nan, dtype=float)
    cs = np.cumsum(c)
    out[n - 1] = cs[n - 1] / float(n)
    if len(c) > n:
        out[n:] = (cs[n:] - cs[:-n]) / float(n)
    return out


def _swing_low(lows, n=None):
    n = int(n if n is not None else SWING_N)
    if lows is None or len(lows) < 2:
        return 0.0
    window = lows[-n:] if len(lows) >= n else lows
    return float(np.min(np.asarray(window, dtype=float)))


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


def _get_ohlcv_period(C, stock, period, count, need, diag_key):
    end = _bar_end_str(C)
    # 日线 end 用日期即可
    if period in ("1d", "1w", "1mon", "1q", "1hy", "1y"):
        end = end[:8] if len(end) >= 8 else end
    md = None
    source = None
    open_ = high = low = close = volume = None
    fields = ["open", "high", "low", "close", "volume"]

    try:
        md = C.get_market_data_ex(
            fields=fields,
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
                fields,
                [stock],
                period=period,
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once(diag_key + "_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once(diag_key + "_ex_fail", e)
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
                fields,
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
            _diag_once(diag_key + "_gmd_fail", e)

    if not close or len(close) < need:
        _diag_once(
            diag_key + "_empty",
            "period=",
            period,
            "end=",
            end,
            "n=",
            0 if not close else len(close),
        )
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
        _diag_once(diag_key + "_flat", "n=", len(close), "source=", source)
        return None

    _diag_once(
        diag_key + "_ok",
        "source=",
        source,
        "period=",
        period,
        "n=",
        len(close),
        "end=",
        end,
        "last=",
        round(float(close[-1]), 4),
    )
    return open_, high, low, close, volume


def _get_ohlcv_1h(C, stock):
    need = max(int(H_MA_SLOW), int(SWING_N)) + 5
    return _get_ohlcv_period(
        C, stock, getattr(A, "period", "1h"), int(OHLC_COUNT), need, "h1"
    )


def _get_ohlcv_1d(C, stock):
    need = int(D_MA_SLOW) + 5
    return _get_ohlcv_period(
        C, stock, "1d", int(DAILY_OHLC_COUNT), need, "d1"
    )


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


def _buy_budget(cash):
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return float(TRADE_BUDGET)
    if cash is None or cash <= 0:
        return float(TRADE_BUDGET)
    by_ratio = float(cash) * float(CASH_RATIO)
    return min(float(TRADE_BUDGET), by_ratio) if TRADE_BUDGET > 0 else by_ratio


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
    }
    A.acted.add("BUY")
    A.pending_entry = None
    if getattr(A, "is_backtest", False):
        A.bt_opened_at = ot
        A.bt_swing_low = sl
    buy_day = ot[:8] if len(ot) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    _save_state()
    print("%s BUY filled" % STRATEGY_NAME, A.position)


def _apply_sell_fill(now, reason, last_hint, filled_vol):
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
    print("%s partial sell fill" % STRATEGY_NAME, filled_vol, "remain~", remain)
    if A.position:
        A.position["shares"] = remain
    _bt_held_set(remain)
    if remain < 100:
        _clear_after_sell(now, str(reason) + "/partial", last=last_hint)
    else:
        _save_state()


def _clear_after_sell(now, reason, last=None):
    print("%s SELL done" % STRATEGY_NAME, reason, "last=", last, "cleared", A.position)
    A.position = None
    A.acted.add("SELL")
    A.pending_exit = None
    A.pending_entry = None
    if getattr(A, "is_backtest", False):
        A.bt_held = 0
        A.bt_locked = 0
        A.bt_opened_at = ""
        A.bt_swing_low = 0.0
    _save_state()


def _clear_pending(reason=""):
    if getattr(A, "pending", None):
        print("%s pending clear" % STRATEGY_NAME, reason, A.pending.get("remark"))
    A.pending = None
    _save_state()


def _order_buy(C, price, now, budget, swing_low=0.0):
    if getattr(A, "pending", None):
        print("%s buy skip: pending active" % STRATEGY_NAME)
        return False
    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        print("%s buy skip: already holding" % STRATEGY_NAME)
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False
    vol = _lot(price, budget)
    if vol < 100:
        print("%s buy skip lot" % STRATEGY_NAME, "price=", price, "budget=", budget)
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
    A.pending_entry = None
    _save_state()
    print("%s BUY submitted" % STRATEGY_NAME, vol, msg)
    return True


def _order_sell(C, reason, price, now):
    if getattr(A, "pending", None):
        print("%s sell skip: pending active" % STRATEGY_NAME)
        return False
    if not _has_position() and not (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        return False
    if "SELL" in getattr(A, "acted", set()):
        return False

    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    if want < 100:
        return False

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
        _apply_sell_fill(now, reason, price, vol)
        return True
    try:
        passorder(A.sell_code, 1101, A.acct, A.stock, 14, -1, vol, STRATEGY_NAME, 1, msg, C)
    except Exception as e:
        print("%s passorder SELL fail" % STRATEGY_NAME, e)
        return False
    if getattr(A, "is_backtest", False):
        _apply_sell_fill(now, reason, price, vol)
        return True
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": reason or "SELL",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "last_hint": price,
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
    }
    A.pending_exit = None
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
            _apply_sell_fill(now, intent, pend.get("last_hint") or px, use_vol)
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
                _apply_sell_fill(now, intent, pend.get("last_hint") or px, traded)
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


def _bar_tag(dt):
    if dt is None:
        return ""
    return dt.strftime("%Y%m%d%H%M%S")


def _eval_daily(closes_d):
    """返回 (daily_ok, daily_break, ma20, ma60, close)."""
    ma20 = _sma(closes_d, D_MA_FAST)
    ma60 = _sma(closes_d, D_MA_SLOW)
    if ma20 is None or ma60 is None:
        return False, False, None, None, None
    i = len(closes_d) - 1
    c = float(closes_d[i])
    m20 = float(ma20[i]) if ma20[i] == ma20[i] else None
    m60 = float(ma60[i]) if ma60[i] == ma60[i] else None
    if m20 is None or m60 is None:
        return False, False, None, None, c
    daily_ok = (c > m20) and (m20 > m60)
    daily_break = c < m20
    return daily_ok, daily_break, m20, m60, c


def _eval_hourly_buy(closes_h, ma5, ma10, ma120):
    """金叉 + MA120 支撑. 返回 (buy_signal, detail)."""
    detail = {"support": False, "golden": False, "ma5": None, "ma10": None, "ma120": None}
    if closes_h is None or ma5 is None or ma10 is None or ma120 is None:
        return False, detail
    if len(closes_h) < 2:
        return False, detail
    i = len(closes_h) - 1
    c = float(closes_h[i])
    f0 = float(ma5[i]) if ma5[i] == ma5[i] else None
    f1 = float(ma5[i - 1]) if ma5[i - 1] == ma5[i - 1] else None
    m0 = float(ma10[i]) if ma10[i] == ma10[i] else None
    m1 = float(ma10[i - 1]) if ma10[i - 1] == ma10[i - 1] else None
    s0 = float(ma120[i]) if ma120[i] == ma120[i] else None
    detail["ma5"] = f0
    detail["ma10"] = m0
    detail["ma120"] = s0
    if f0 is None or f1 is None or m0 is None or m1 is None or s0 is None:
        return False, detail
    detail["support"] = c >= s0 * (1.0 - float(MA120_TOL))
    detail["golden"] = (f1 <= m1) and (f0 > m0)
    return bool(detail["support"] and detail["golden"]), detail


def _eval_hourly_stop(price, cost, lows_h):
    """返回 (stop, reason)."""
    if cost is None or cost <= 0 or price is None:
        return False, None
    ret = (float(price) - float(cost)) / float(cost)
    if ret <= -float(STOP_LOSS):
        return True, "stop_1h"
    if USE_SWING_STOP:
        # 入场前低点存于 position.swing_low; 若无则用近期低点
        sl = 0.0
        if _has_position():
            sl = float(A.position.get("swing_low", 0) or 0)
        if sl <= 0:
            sl = _swing_low(lows_h)
        if sl > 0 and float(price) < sl:
            return True, "stop_swing"
    return False, None


def _pending_ready(pend, day, bar_tag, mode):
    """mode: hour | day. 信号 bar 之后的下一根才执行."""
    if not isinstance(pend, dict):
        return False
    sig_tag = str(pend.get("signal_tag", "") or "")
    sig_day = str(pend.get("signal_day", "") or "")
    if mode == "day":
        return bool(sig_day) and sig_day < day
    # hour: 信号 tag 严格早于当前 bar
    if sig_tag and bar_tag:
        return sig_tag < bar_tag
    if sig_day and sig_day < day:
        return True
    return False


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
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)
    hhmm = _bar_hhmm(bar_dt if bt else now)

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        if now_s < DECISION_START or now_s > DECISION_END:
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

    ohlcv_h = _get_ohlcv_1h(C, A.stock)
    if ohlcv_h is None:
        _live_heartbeat("ohlcv_1h_none")
        return
    opens_h, highs_h, lows_h, closes_h, _vols_h = ohlcv_h

    ohlcv_d = _get_ohlcv_1d(C, A.stock)
    if ohlcv_d is None:
        _live_heartbeat("ohlcv_1d_none")
        return
    _od, _hd, _ld, closes_d, _vd = ohlcv_d

    ma5 = _sma(closes_h, H_MA_FAST)
    ma10 = _sma(closes_h, H_MA_MID)
    ma120 = _sma(closes_h, H_MA_SLOW)
    if ma5 is None or ma10 is None or ma120 is None:
        _live_heartbeat("ind_none")
        return

    price = float(closes_h[-1])
    open_px = float(opens_h[-1])
    if bt:
        _bt_recover_position(now=now, last=price)

    daily_ok, daily_break, d_ma20, d_ma60, d_close = _eval_daily(closes_d)
    buy_sig, h_detail = _eval_hourly_buy(closes_h, ma5, ma10, ma120)

    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    cost = _pos_cost_price()
    stop_hit, stop_reason = (False, None)
    if holding:
        stop_hit, stop_reason = _eval_hourly_stop(price, cost, lows_h)

    ret_pct = None
    if holding and cost > 0:
        ret_pct = (price - cost) / cost

    interesting = buy_sig or daily_break or stop_hit or holding or bool(
        getattr(A, "pending_entry", None) or getattr(A, "pending_exit", None)
    )
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 20 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            hhmm,
            "n1h=%d n1d=%d close=%.4f open=%.4f "
            "d_ok=%s d_brk=%s d_ma20=%s d_ma60=%s "
            "ma5=%s ma10=%s ma120=%s support=%s golden=%s "
            "buy=%s stop=%s hold=%s ret=%s "
            "pe=%s px=%s bt_held=%s avail=%s"
            % (
                len(closes_h),
                len(closes_d),
                price,
                open_px,
                daily_ok,
                daily_break,
                None if d_ma20 is None else round(d_ma20, 4),
                None if d_ma60 is None else round(d_ma60, 4),
                None if h_detail.get("ma5") is None else round(h_detail["ma5"], 4),
                None if h_detail.get("ma10") is None else round(h_detail["ma10"], 4),
                None if h_detail.get("ma120") is None else round(h_detail["ma120"], 4),
                h_detail.get("support"),
                h_detail.get("golden"),
                buy_sig,
                stop_reason,
                holding,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                bool(getattr(A, "pending_entry", None)),
                bool(getattr(A, "pending_exit", None)),
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
            ),
        )

    # ---- 先执行挂起的卖/买（本根开盘）----
    pe_exit = getattr(A, "pending_exit", None)
    if holding and isinstance(pe_exit, dict):
        mode = str(pe_exit.get("mode", "hour") or "hour")
        if _pending_ready(pe_exit, day, tag, mode):
            reason = str(pe_exit.get("reason", "SELL") or "SELL")
            _order_sell(C, reason, open_px, now)
            return

    pe_entry = getattr(A, "pending_entry", None)
    if (
        (not holding)
        and isinstance(pe_entry, dict)
        and ("BUY" not in getattr(A, "acted", set()))
        and _pending_ready(pe_entry, day, tag, "hour")
    ):
        budget = _buy_budget(cash)
        sl = float(pe_entry.get("swing_low", 0) or 0)
        _order_buy(C, open_px, now, budget, swing_low=sl)
        return

    # ---- 评估新信号（收盘确认 → 挂到下一根；已有挂起不刷新 tag，避免推迟执行）----
    if holding:
        cur_ex = getattr(A, "pending_exit", None)
        if daily_break:
            if not isinstance(cur_ex, dict):
                A.pending_exit = {
                    "mode": "day",
                    "reason": "daily_break",
                    "signal_day": day,
                    "signal_tag": tag,
                    "close": price,
                    "d_close": d_close,
                }
                _save_state()
                print("%s pending_exit set" % STRATEGY_NAME, A.pending_exit)
            elif str(cur_ex.get("mode")) != "day":
                # 小时止损挂起升级为日线破位（保留更早 signal_day 以便尽快次日开盘）
                A.pending_exit = {
                    "mode": "day",
                    "reason": "daily_break",
                    "signal_day": str(cur_ex.get("signal_day") or day),
                    "signal_tag": str(cur_ex.get("signal_tag") or tag),
                    "close": price,
                    "d_close": d_close,
                }
                _save_state()
                print("%s pending_exit upgrade daily_break" % STRATEGY_NAME, A.pending_exit)
            return
        if stop_hit and stop_reason:
            if isinstance(cur_ex, dict):
                return
            A.pending_exit = {
                "mode": "hour",
                "reason": stop_reason,
                "signal_day": day,
                "signal_tag": tag,
                "close": price,
            }
            _save_state()
            print("%s pending_exit set" % STRATEGY_NAME, A.pending_exit)
            return
        return

    # 无仓: 双周期共振买点
    if buy_sig and daily_ok and ("BUY" not in getattr(A, "acted", set())):
        if isinstance(getattr(A, "pending_entry", None), dict):
            return
        sl = _swing_low(lows_h[:-1] if len(lows_h) > 1 else lows_h)
        A.pending_entry = {
            "signal_day": day,
            "signal_tag": tag,
            "swing_low": sl,
            "close": price,
        }
        A.pending_exit = None
        _save_state()
        print("%s pending_entry set" % STRATEGY_NAME, A.pending_entry)


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
            _download_hist(A.stock, "1d")
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, A.period, "+1d")

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
            A.pending_exit = None
            A.bt_held = 0
            A.bt_locked = 0
            A.bt_lock_day = ""
            A.bt_opened_at = ""
            A.bt_swing_low = 0.0
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
            if not hasattr(A, "pending_exit"):
                A.pending_exit = None
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
        if not hasattr(A, "pending_exit"):
            A.pending_exit = None

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
        "dMA=",
        "%d/%d" % (D_MA_FAST, D_MA_SLOW),
        "hMA=",
        "%d/%d/%d" % (H_MA_FAST, H_MA_MID, H_MA_SLOW),
        "ma120_tol=",
        MA120_TOL,
        "stop=",
        STOP_LOSS,
        "swing=",
        USE_SWING_STOP,
        SWING_N,
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
