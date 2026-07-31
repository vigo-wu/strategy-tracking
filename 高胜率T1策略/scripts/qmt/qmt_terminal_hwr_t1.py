# coding: utf-8
"""HwrT1 v1.1 - 高胜率 T+1 尾盘潜伏(国金 QMT 终端模型 / 1分钟版).

主图周期: 1分钟. 信号见主题 model.md.
v1.1: 放量拉升过滤 + 真实VWAP; 动态分时追踪出场; 14:30保底.
部署: python scripts/qmt/_deploy_qmt_gbk.py -> 写入 QMT python/HwrT1.py (GBK).
注意: 请编辑本仓库 UTF-8 源文件; 勿在 IDE 中直接打开 QMT 目录下的 HwrT1.py(其为 GBK, 会显示乱码).

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
DRY_RUN = True

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 回测定额；实盘预算 = min(TRADE_BUDGET, 可用资金 * CASH_RATIO)
TRADE_BUDGET = 50000.0
CASH_RATIO = 0.15

# 买入过滤（近 LOOKBACK 根 1m）
LOOKBACK_N = 240
NEAR_HIGH_RATIO = 0.996  # close >= max(high) * 0.996
MOM_BARS = 10
MOM_MIN_RET = 0.005  # 近 10 分钟涨幅 > 0.5%
VOL_RATIO_MIN = 1.3  # 近 10 分钟均量 > 更早均量 * 1.3
BUY_MIN_BARS = 60

STOP_LOSS = 0.015  # 硬止损 -1.5%
TARGET_PROFIT = 0.04  # 硬止盈 +4%
TRAIL_ARM_RET = 0.005  # 盈利 > 0.5% 后启用 VWAP 追踪
TRAIL_START_HHMM = "0935"  # 次日 >=09:35 开始动态追踪
FORCE_EXIT_HHMM = "1430"  # 次日 >=14:30 保底清仓

# 买入窗（含两端）：14:48 - 14:55
BUY_TIME_START = "1448"
BUY_TIME_END = "1455"

PERIOD = "1m"
# 1m 约 240 根/日；暖机 + 缓冲
OHLC_COUNT = 480

LIVE_ONLY_LAST_BAR = True
# 实盘决策：开盘起覆盖止盈止损 / 追踪 / 买入窗 / 尾盘保底
DECISION_START = "093000"
DECISION_END = "150000"
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 60
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__；状态绝对路径
STATE_FILE = r"D:\service\GJQMT\python\hwr_t1_qmt_state.json"

STRATEGY_NAME = "HwrT1"
STRATEGY_VER = "v1.1"
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
    cfg = str(PERIOD or "1m").strip().lower()
    if cfg == "follow":
        p = str(getattr(C, "period", "1m") or "1m").strip().lower()
        return p if p in _VALID_PERIODS else "1m"
    return cfg if cfg in _VALID_PERIODS else "1m"


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
    period = getattr(A, "period", "1m")
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
        }
    A.acted_day = str(raw.get("acted_day", "") or "")
    acted = raw.get("acted") or []
    A.acted = set(acted) if isinstance(acted, list) else set()
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
    }
    print("%s bt recover position" % STRATEGY_NAME, A.position)
    return True


# -------------------- 指标 --------------------
def _vwap(closes, volumes):
    """成交量加权均价；量全 0 时退回收盘均价."""
    c = np.asarray(closes, dtype=float)
    v = np.asarray(volumes, dtype=float)
    if len(c) == 0 or len(v) != len(c):
        return None
    vsum = float(np.sum(v))
    if vsum <= 1e-12:
        return float(np.mean(c))
    return float(np.sum(c * v) / vsum)


def _approx_session_bars(hhmm):
    """按 A 股连续竞价估算当日已走分钟数（用于截取今日 VWAP）。"""
    try:
        t = int(str(hhmm)[:4])
    except Exception:
        return 60
    h, m = t // 100, t % 100
    mins = h * 60 + m
    am0, am1 = 9 * 60 + 30, 11 * 60 + 30
    pm0, pm1 = 13 * 60, 15 * 60
    if mins < am0:
        return 1
    if mins <= am1:
        return max(1, mins - am0 + 1)
    if mins < pm0:
        return 120
    if mins <= pm1:
        return 120 + max(1, mins - pm0 + 1)
    return 240


def _today_slice(closes, volumes, hhmm):
    n = min(len(closes), max(1, int(_approx_session_bars(hhmm))))
    return closes[-n:], volumes[-n:]


def _buy_filters(closes, highs, volumes):
    """返回 (ok, vwap, day_high, mom10, vol_ratio) 或失败时 ok=False."""
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs, dtype=float)
    v = np.asarray(volumes, dtype=float)
    n = len(c)
    if n < int(BUY_MIN_BARS) or len(h) != n or len(v) != n:
        return False, None, None, None, None
    mom_n = int(MOM_BARS)
    if n <= mom_n or c[-(mom_n + 1)] <= 0:
        return False, None, None, None, None

    vwap = _vwap(c[-int(LOOKBACK_N) :], v[-int(LOOKBACK_N) :])
    day_high = float(np.max(h[-int(LOOKBACK_N) :]))
    price = float(c[-1])
    mom10 = (price - float(c[-mom_n])) / float(c[-mom_n])
    vol_ma = float(np.mean(v[-mom_n:]))
    base = v[:-mom_n]
    if len(base) < mom_n:
        return False, vwap, day_high, mom10, None
    vol_base = float(np.mean(base[-int(LOOKBACK_N) :])) if len(base) > 0 else 0.0
    if vol_base <= 1e-12:
        vol_ratio = 0.0
    else:
        vol_ratio = vol_ma / vol_base

    ok = (
        vwap is not None
        and price > float(vwap)
        and day_high > 0
        and price >= day_high * float(NEAR_HIGH_RATIO)
        and mom10 > float(MOM_MIN_RET)
        and vol_ratio > float(VOL_RATIO_MIN)
    )
    return ok, vwap, day_high, mom10, vol_ratio


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
    period = getattr(A, "period", "1m")
    if count is None:
        count = int(OHLC_COUNT) if OHLC_COUNT else 480
    end = _bar_end_str(C)
    need = max(int(BUY_MIN_BARS), int(MOM_BARS) * 2 + 5)
    md = None
    source = None
    high = low = close = volume = None
    fields = ["high", "low", "close", "volume"]

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
            _diag_once("ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("ex_fail", e)
        md = None

    if md is not None:
        close = _series_from_ex(md, stock, "close")
        high = _series_from_ex(md, stock, "high")
        low = _series_from_ex(md, stock, "low")
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
            close = _series_from_ex(md2, stock, "close")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
            volume = _series_from_ex(md2, stock, "volume")
        except Exception as e:
            _diag_once("gmd_fail", e)

    if not close or len(close) < need:
        _diag_once("empty", "period=", period, "end=", end, "n=", 0 if not close else len(close))
        return None

    if not high or len(high) != len(close):
        high = list(close)
    if not low or len(low) != len(close):
        low = list(close)
    if not volume or len(volume) != len(close):
        volume = [1.0] * len(close)

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
    return high, low, close, volume


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
    """实盘: min(定额, 资金*比例); 回测: TRADE_BUDGET."""
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


def _apply_buy_fill(vol, price, opened_at):
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < 100:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    A.position = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
    }
    A.acted.add("BUY")
    if getattr(A, "is_backtest", False):
        A.bt_opened_at = ot
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
    if getattr(A, "is_backtest", False):
        A.bt_held = 0
        A.bt_locked = 0
        A.bt_opened_at = ""
    _save_state()


def _clear_pending(reason=""):
    if getattr(A, "pending", None):
        print("%s pending clear" % STRATEGY_NAME, reason, A.pending.get("remark"))
    A.pending = None
    _save_state()


def _order_buy(C, price, now, budget):
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
    print(("[DRY] " if DRY_RUN else "") + msg, "@", price)
    if DRY_RUN:
        _apply_buy_fill(vol, price, ot)
        return True
    try:
        passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, STRATEGY_NAME, 1, msg, C)
    except Exception as e:
        print("%s passorder BUY fail" % STRATEGY_NAME, e)
        return False
    if getattr(A, "is_backtest", False):
        _apply_buy_fill(vol, price, ot)
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
        "cancel_requested": False,
    }
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
            _apply_buy_fill(use_vol, px, pend.get("opened_at") or pend.get("submitted_at"))
        else:
            _apply_sell_fill(now, intent, pend.get("last_hint") or px, use_vol)
        _clear_pending("filled")
        return False

    if status_dead:
        if traded >= 100:
            if side == "buy":
                _apply_buy_fill(traded, px, pend.get("opened_at") or pend.get("submitted_at"))
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


def _in_buy_time_window(dt):
    """14:48 <= t <= 14:55（含两端）。"""
    t = _bar_hhmm(dt)
    return (t >= str(BUY_TIME_START)) and (t <= str(BUY_TIME_END))


def _is_next_day_hold(now):
    """持仓且当前日 > 买入日。"""
    if not (_has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100)):
        return False
    ed = _entry_date()
    if ed is None:
        ot = getattr(A, "bt_opened_at", "") if getattr(A, "is_backtest", False) else ""
        ed_dt = _parse_opened_at(ot)
        if ed_dt is None:
            return False
        ed = ed_dt.date()
    if now is None:
        return False
    return now.date() > ed


def _eval_signals(price, buy_ok, today_vwap, bar_dt, now):
    """返回 (buy, sell_reason)。"""
    buy = bool(buy_ok) and _in_buy_time_window(bar_dt)

    sell_reason = None
    if not _is_next_day_hold(now):
        return buy, sell_reason

    t = _bar_hhmm(bar_dt if getattr(A, "is_backtest", False) else now)
    cost = _pos_cost_price()
    if cost <= 0 or price is None:
        if t >= str(FORCE_EXIT_HHMM):
            sell_reason = "t1_force_1430"
        return buy, sell_reason

    ret = (float(price) - cost) / cost

    # 1) 硬止损 -1.5%
    if ret <= -float(STOP_LOSS):
        return buy, "stop_loss"

    # 2) >=09:35 动态追踪 / 硬止盈
    if t >= str(TRAIL_START_HHMM):
        if ret >= float(TARGET_PROFIT):
            return buy, "take_profit"
        if (
            today_vwap is not None
            and ret > float(TRAIL_ARM_RET)
            and float(price) < float(today_vwap)
        ):
            return buy, "trail_vwap"

    # 3) >=14:30 保底清仓
    if t >= str(FORCE_EXIT_HHMM):
        return buy, "t1_force_1430"

    return buy, sell_reason


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

    ohlcv = _get_ohlcv(C, A.stock)
    if ohlcv is None:
        _live_heartbeat("ohlcv_none")
        return
    high, low, close, volume = ohlcv
    price = float(close[-1])
    if bt:
        _bt_recover_position(now=now, last=price)

    buy_ok, vwap, day_high, mom10, vol_ratio = _buy_filters(close, high, volume)
    tc, tv = _today_slice(close, volume, hhmm)
    today_vwap = _vwap(tc, tv)

    buy, sell_reason = _eval_signals(price, buy_ok, today_vwap, bar_dt, now)
    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    ret_pct = None
    cost = _pos_cost_price()
    if holding and cost > 0:
        ret_pct = (price - cost) / cost

    interesting = buy or bool(sell_reason) or holding
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 60 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            hhmm,
            "n=%d close=%.4f vwap=%s hi=%s mom10=%s volR=%s tVwap=%s buy=%s sell=%s hold=%s ret=%s bt_held=%s avail=%s"
            % (
                len(close),
                price,
                None if vwap is None else round(float(vwap), 4),
                None if day_high is None else round(float(day_high), 4),
                None if mom10 is None else ("%.2f%%" % (mom10 * 100.0)),
                None if vol_ratio is None else round(float(vol_ratio), 2),
                None if today_vwap is None else round(float(today_vwap), 4),
                buy,
                sell_reason,
                holding,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
            ),
        )

    # 先卖后买
    if sell_reason and holding:
        _order_sell(C, sell_reason, price, now)
        return
    if buy and (not holding) and ("BUY" not in getattr(A, "acted", set())):
        budget = _buy_budget(cash)
        _order_buy(C, price, now, budget)


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
            A.bt_held = 0
            A.bt_locked = 0
            A.bt_lock_day = ""
            A.bt_opened_at = ""
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
        "cash_ratio=",
        CASH_RATIO,
        "buyWin=",
        "%s-%s" % (BUY_TIME_START, BUY_TIME_END),
        "mom10>",
        MOM_MIN_RET,
        "volR>",
        VOL_RATIO_MIN,
        "nearHi=",
        NEAR_HIGH_RATIO,
        "trail@",
        TRAIL_START_HHMM,
        "force@",
        FORCE_EXIT_HHMM,
        "stop=",
        STOP_LOSS,
        "tp=",
        TARGET_PROFIT,
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
