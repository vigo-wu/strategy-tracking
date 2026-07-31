# coding: utf-8
"""TrendPB Basket v1.0 - 趋势回调(国金终端 / 中证央企红利50池).

主图: 建议挂 000825.SH 日线. 池子=中证中央企业红利成分股(~50).
部署: python scripts/qmt/_deploy_qmt_gbk_basket.py -> TrendPBBasket.py (GBK).
单标的版见 qmt_terminal_trend_pb.py; 请编辑本仓库 UTF-8 源, 勿直接开 QMT 目录 GBK 文件.

下单约定 (对齐 qmt-model-script / pitfalls 7.1):
  - DRY_RUN: 只打印, 模拟 T+1, 不 passorder
  - 回测: passorder + 即时落状态; 可卖=bt_held-bt_locked; skip 不清仓
  - 实盘: passorder 后 pending, 成交后才改仓; 可卖=m_nCanUseVolume
  - 按标的分状态(book); 同时持仓上限 MAX_HOLDINGS
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

# 单笔买入预算（元）
TRADE_BUDGET = 10000.0
# 同时持仓上限（只）；满仓后不再开新仓，已有仓位照常卖
MAX_HOLDINGS = 10

# 股票池: 中证中央企业红利 000825.SH (~50)；主图请挂 000825.SH（勿用 .SZ）
POOL_INDEX = "000825.SH"
POOL_INDEX_ALIASES = ("000825.SH", "000825.SZ")
POOL_SECTOR_NAMES = ("中证中央企业红利", "央企红利", "中证央企红利")
# 取池失败时的兜底列表(可手填); 空则用 init 缓存
POOL_FALLBACK = []
# set_universe 报「无效股票代码」的剔除（退市/重组等）
POOL_EXCLUDE = ("600705.SH",)
# 回测成分股刷新: "bar"=每根K(慢) / "month"=按月 / "once"=全程用首次池
POOL_REFRESH = "month"
# 回测进度日志间隔(根K); 0=关闭
BT_PROGRESS_EVERY = 40

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
STATE_FILE = r"D:\service\GJQMT\python\trend_pb_basket_qmt_state.json"

STRATEGY_NAME = "TrendPBBasket"
STRATEGY_VER = "v1.0-basket"
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)


class _S(object):
    pass



A = _S()


def _empty_book_item():
    return {
        "position": None,
        "acted": set(),
        "pending": None,
        "pending_entry": None,
        "bt_held": 0,
        "bt_locked": 0,
        "bt_lock_day": "",
        "bt_opened_at": "",
        "bt_swing_low": 0.0,
        "bt_half_taken": False,
        "bt_initial_shares": 0,
    }


def _ensure_book():
    if not isinstance(getattr(A, "book", None), dict):
        A.book = {}


def _book_get(stock):
    _ensure_book()
    stock = str(stock or "")
    if stock not in A.book:
        A.book[stock] = _empty_book_item()
    return A.book[stock]


def _bind(stock):
    """把 A 工作区切换到指定标的(复用单标的买卖逻辑)."""
    stock = str(stock or "")
    b = _book_get(stock)
    A.stock = stock
    A.position = b.get("position")
    acted = b.get("acted")
    A.acted = acted if isinstance(acted, set) else set(acted or [])
    A.pending = b.get("pending")
    A.pending_entry = b.get("pending_entry")
    A.bt_held = int(b.get("bt_held", 0) or 0)
    A.bt_locked = int(b.get("bt_locked", 0) or 0)
    A.bt_lock_day = str(b.get("bt_lock_day", "") or "")
    A.bt_opened_at = str(b.get("bt_opened_at", "") or "")
    A.bt_swing_low = float(b.get("bt_swing_low", 0) or 0)
    A.bt_half_taken = bool(b.get("bt_half_taken", False))
    A.bt_initial_shares = int(b.get("bt_initial_shares", 0) or 0)


def _unbind():
    stock = str(getattr(A, "stock", "") or "")
    if not stock:
        return
    b = _book_get(stock)
    b["position"] = A.position
    b["acted"] = set(getattr(A, "acted", set()) or set())
    b["pending"] = getattr(A, "pending", None)
    b["pending_entry"] = getattr(A, "pending_entry", None)
    b["bt_held"] = int(getattr(A, "bt_held", 0) or 0)
    b["bt_locked"] = int(getattr(A, "bt_locked", 0) or 0)
    b["bt_lock_day"] = str(getattr(A, "bt_lock_day", "") or "")
    b["bt_opened_at"] = str(getattr(A, "bt_opened_at", "") or "")
    b["bt_swing_low"] = float(getattr(A, "bt_swing_low", 0) or 0)
    b["bt_half_taken"] = bool(getattr(A, "bt_half_taken", False))
    b["bt_initial_shares"] = int(getattr(A, "bt_initial_shares", 0) or 0)


def _count_holdings():
    _ensure_book()
    n = 0
    bt = getattr(A, "is_backtest", False)
    for code, b in A.book.items():
        pos = b.get("position")
        if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100:
            n += 1
            continue
        if bt and int(b.get("bt_held", 0) or 0) >= 100:
            n += 1
    return n


def _holding_codes():
    _ensure_book()
    out = []
    bt = getattr(A, "is_backtest", False)
    for code, b in A.book.items():
        pos = b.get("position")
        if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100:
            out.append(code)
        elif bt and int(b.get("bt_held", 0) or 0) >= 100:
            out.append(code)
    return out


def _normalize_code(code):
    code = str(code or "").strip().upper()
    if not code:
        return ""
    if "." in code:
        return code
    if code.startswith(("5", "6", "9")):
        return code + ".SH"
    return code + ".SZ"


def _pool_normalize_list(codes):
    exclude = set(_normalize_code(x) for x in (POOL_EXCLUDE or ()))
    out = []
    seen = set()
    for c in codes or []:
        cc = _normalize_code(c)
        if not cc or cc in seen or cc in exclude:
            continue
        if cc.startswith("000825."):
            continue
        seen.add(cc)
        out.append(cc)
    return out


def _try_get_sector(C, index_code, tag=None):
    fn = getattr(C, "get_sector", None)
    if not callable(fn):
        fn = globals().get("get_sector")
    if not callable(fn):
        return []
    raw = None
    try:
        if tag is not None:
            raw = fn(index_code, tag)
        else:
            raw = fn(index_code)
    except TypeError:
        try:
            raw = fn(index_code)
        except Exception as e:
            _diag_once("pool_get_sector", index_code, e)
            return []
    except Exception as e:
        _diag_once("pool_get_sector", index_code, e)
        return []
    return list(raw) if raw else []


def _try_get_sector_by_name(C, name, tag=None):
    fn = getattr(C, "get_stock_list_in_sector", None)
    if not callable(fn):
        fn = globals().get("get_stock_list_in_sector")
    if not callable(fn):
        return []
    raw = None
    try:
        if tag is not None:
            try:
                raw = fn(name, tag)
            except TypeError:
                raw = fn(name)
        else:
            raw = fn(name)
    except Exception as e:
        _diag_once("pool_sector_" + str(name), e)
        return []
    return list(raw) if raw else []


def _resolve_pool(C):
    """取中证央企红利成分股.

    回测优先按 timetag 取历史成分; 若终端无历史成分数据(常见返回空),
    则回退到最新成分 / init 缓存, 避免 handlebar 整池为空.
    """
    tag = None
    try:
        tag = C.get_bar_timetag(C.barpos)
    except Exception:
        tag = None

    codes = []
    src = ""
    index_codes = []
    for x in (POOL_INDEX,) + tuple(POOL_INDEX_ALIASES or ()):
        if x and x not in index_codes:
            index_codes.append(x)

    # 1) 回测: 先试历史成分
    if getattr(A, "is_backtest", False) and tag is not None:
        for idx in index_codes:
            codes = _try_get_sector(C, idx, tag=tag)
            if codes:
                src = "get_sector/hist:" + idx
                break
        if not codes:
            for name in POOL_SECTOR_NAMES:
                codes = _try_get_sector_by_name(C, name, tag=tag)
                if codes:
                    src = "sector/hist:" + name
                    break

    # 2) 最新成分（实盘 / 历史空时回退）
    if not codes:
        for idx in index_codes:
            codes = _try_get_sector(C, idx, tag=None)
            if codes:
                src = "get_sector:" + idx
                break
    if not codes:
        for name in POOL_SECTOR_NAMES:
            codes = _try_get_sector_by_name(C, name, tag=None)
            if codes:
                src = "sector:" + name
                break

    # 3) init 缓存 / 手填兜底
    if not codes:
        cached = getattr(A, "pool_cache", None) or []
        if cached:
            codes = list(cached)
            src = "cache"
    if not codes and POOL_FALLBACK:
        codes = list(POOL_FALLBACK)
        src = "fallback"

    out = _pool_normalize_list(codes)
    if out:
        A.pool_cache = list(out)
        _diag_once("pool_src", src or "ok", "n=", len(out))
        return out

    chart = str(getattr(A, "chart_stock", "") or "")
    if chart and not chart.startswith("000825."):
        _diag_once("pool_src", "chart_only", chart)
        return [chart]

    _diag_once(
        "pool_empty",
        "get_sector 空; 主图请用 000825.SH; 或填 POOL_FALLBACK",
    )
    return list(getattr(A, "pool_cache", None) or [])


def _pool_for_handle(C):
    """按 POOL_REFRESH 降低回测每根 K 调 get_sector 的开销."""
    mode = str(POOL_REFRESH or "month").strip().lower()
    cached = list(getattr(A, "pool_cache", None) or [])
    if mode == "once" and cached:
        return cached
    if mode == "month":
        ym = _bar_datetime(C).strftime("%Y%m")
        if getattr(A, "pool_ym", "") == ym and cached:
            return cached
        pool = _resolve_pool(C)
        if pool:
            A.pool_ym = ym
            A.pool_cache = list(pool)
        return pool if pool else cached
    # bar: 每根都解析
    pool = _resolve_pool(C)
    return pool if pool else cached



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


def _pos_from_raw(pos):
    if not isinstance(pos, dict):
        return None
    if int(pos.get("shares", 0) or 0) < 100:
        return None
    return {
        "shares": int(pos["shares"]),
        "price": float(pos.get("price", 0) or 0),
        "cost": float(pos.get("cost", 0) or 0),
        "opened_at": str(pos.get("opened_at", "") or ""),
        "swing_low": float(pos.get("swing_low", 0) or 0),
        "half_taken": bool(pos.get("half_taken", False)),
        "initial_shares": int(pos.get("initial_shares", pos.get("shares", 0)) or 0),
    }


def _load_state():
    _ensure_book()
    A.book = {}
    A.acted_day = ""
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
    A.acted_day = str(raw.get("acted_day", "") or "")
    books = raw.get("books")
    if isinstance(books, dict):
        for code, item in books.items():
            code = _normalize_code(code)
            if not code or not isinstance(item, dict):
                continue
            b = _empty_book_item()
            b["position"] = _pos_from_raw(item.get("position"))
            acted = item.get("acted") or []
            b["acted"] = set(acted) if isinstance(acted, list) else set()
            pe = item.get("pending_entry")
            b["pending_entry"] = pe if isinstance(pe, dict) else None
            pend = item.get("pending")
            b["pending"] = pend if isinstance(pend, dict) else None
            A.book[code] = b
    else:
        code = _normalize_code(raw.get("stock") or getattr(A, "chart_stock", ""))
        if code:
            b = _empty_book_item()
            b["position"] = _pos_from_raw(raw.get("position"))
            acted = raw.get("acted") or []
            b["acted"] = set(acted) if isinstance(acted, list) else set()
            pe = raw.get("pending_entry")
            b["pending_entry"] = pe if isinstance(pe, dict) else None
            A.book[code] = b
    print("%s state loaded holdings=" % STRATEGY_NAME, _count_holdings(), "codes=", list(A.book.keys()))


def _save_state():
    # 回测也要 unbind，否则 book 不同步，MAX_HOLDINGS 会数错
    try:
        _unbind()
    except Exception:
        pass
    if getattr(A, "is_backtest", False):
        return
    path = _state_path()
    if not path:
        return
    _ensure_book()
    books = {}
    for code, b in A.book.items():
        books[code] = {
            "position": b.get("position"),
            "acted": list(b.get("acted") or []),
            "pending": b.get("pending"),
            "pending_entry": b.get("pending_entry"),
        }
    data = {
        "version": STRATEGY_VER,
        "pool_index": POOL_INDEX,
        "acted_day": getattr(A, "acted_day", ""),
        "books": books,
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
        _ensure_book()
        for b in A.book.values():
            b["acted"] = set()
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
    out[n - 1] = float(c[:n].mean())
    alpha = 2.0 / (float(n) + 1.0)
    prev = out[n - 1]
    for i in range(n, len(c)):
        prev = alpha * c[i] + (1.0 - alpha) * prev
        out[i] = prev
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
    avg_gain = float(gains[:n].mean())
    avg_loss = float(losses[:n].mean())
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
    """滚动布林; cumsum O(L), 避免每窗 np.mean/std(回测 50 池会卡死)."""
    n = int(n if n is not None else BOLL_N)
    k = float(k if k is not None else BOLL_K)
    c = np.asarray(closes, dtype=float)
    length = len(c)
    if length < n:
        return None, None, None
    mid = np.full(length, np.nan, dtype=float)
    up = np.full(length, np.nan, dtype=float)
    cs = np.cumsum(c)
    cs2 = np.cumsum(c * c)
    sum1 = cs[n - 1 :] - np.concatenate(([0.0], cs[: length - n]))
    sum2 = cs2[n - 1 :] - np.concatenate(([0.0], cs2[: length - n]))
    mean = sum1 / float(n)
    var = sum2 / float(n) - mean * mean
    var = np.maximum(var, 0.0)
    std = np.sqrt(var)
    mid[n - 1 :] = mean
    up[n - 1 :] = mean + k * std
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

def _get_ohlcv_batch(C, stocks, count=None):
    """批量取 OHLCV, 返回 {stock: (o,h,l,c,v)}."""
    period = getattr(A, "period", "1d")
    if count is None:
        count = int(OHLC_COUNT) if OHLC_COUNT else 180
    end = _bar_end_str(C)
    need = max(int(EMA_SLOW), int(BOLL_N), int(RSI_N)) + int(EMA_SLOPE_LOOKBACK) + 5
    stocks = [str(s) for s in (stocks or []) if s]
    out = {}
    if not stocks:
        return out

    md = None
    try:
        md = C.get_market_data_ex(
            fields=["open", "high", "low", "close", "volume"],
            stock_code=stocks,
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
                ["open", "high", "low", "close", "volume"],
                stocks,
                period=period,
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
        except Exception as e:
            _diag_once("batch_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("batch_ex_fail", e)
        md = None

    for stock in stocks:
        open_ = high = low = close = volume = None
        if md is not None:
            open_ = _series_from_ex(md, stock, "open")
            high = _series_from_ex(md, stock, "high")
            low = _series_from_ex(md, stock, "low")
            close = _series_from_ex(md, stock, "close")
            volume = _series_from_ex(md, stock, "volume")
        if not close or len(close) < need:
            one = _get_ohlcv(C, stock, count=count)
            if one is not None:
                out[stock] = one
            else:
                _diag_once("ohlcv_short_" + stock, "n=", 0 if not close else len(close))
            continue
        n = min(len(open_ or []), len(high or []), len(low or []), len(close), len(volume or close))
        if n < need:
            _diag_once("ohlcv_short_" + stock, "n=", n)
            continue
        if not getattr(A, "_diag_ok", False):
            A._diag_ok = True
            print("%s diag: ok batch n_stocks=" % STRATEGY_NAME, len(stocks), "sample=", stock, "bars=", n)
        out[stock] = (open_[-n:], high[-n:], low[-n:], close[-n:], (volume or [0] * n)[-n:])
    return out


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
        print("%s buy skip: pending active" % STRATEGY_NAME, A.stock)
        return False
    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        print("%s buy skip: already holding" % STRATEGY_NAME, A.stock)
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False
    if _count_holdings() >= int(MAX_HOLDINGS):
        print("%s buy skip: max holdings" % STRATEGY_NAME, MAX_HOLDINGS, A.stock)
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


def _process_all_pendings(C, now):
    """实盘: 处理所有标的 pending."""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return False
    _ensure_book()
    busy = False
    codes = [c for c, b in list(A.book.items()) if isinstance(b.get("pending"), dict)]
    for code in codes:
        _bind(code)
        try:
            if _process_pending(C, now):
                busy = True
        finally:
            _unbind()
    return busy


def _handle_one(C, stock, ohlcv, now, bar_dt, day, live_phase, bt):
    """单标的信号与下单."""
    _bind(stock)
    try:
        if bt:
            _bt_roll_t1(day)
            _bt_recover_position(now=now)

        opens, highs, lows, closes, volumes = ohlcv
        ema20 = _ema(closes, EMA_FAST)
        ema60 = _ema(closes, EMA_SLOW)
        rsi = _rsi_wilder(closes, RSI_N)
        _mid, boll_up, _ = _bollinger(closes, BOLL_N, BOLL_K)
        if ema20 is None or ema60 is None or rsi is None:
            return

        price = float(closes[-1])
        open_px = float(opens[-1])
        if bt:
            _bt_recover_position(now=now, last=price)

        buy, detail = _eval_buy(opens, highs, lows, closes, volumes, ema20, ema60, rsi)
        sell_reason, sell_vol, mark_half = _eval_sell(
            opens, highs, lows, closes, rsi, boll_up, now
        )
        holding = _has_position() or (bt and _bt_held_vol() >= 100)
        swing = _swing_low_at(lows)

        e20 = float(ema20[-1]) if ema20[-1] == ema20[-1] else None
        e60 = float(ema60[-1]) if ema60[-1] == ema60[-1] else None
        r0 = float(rsi[-1]) if rsi[-1] == rsi[-1] else None
        bu = float(boll_up[-1]) if boll_up is not None and boll_up[-1] == boll_up[-1] else None

        interesting = buy or bool(sell_reason) or holding
        if interesting:
            print(
                "%s" % STRATEGY_NAME,
                stock,
                day,
                _bar_hhmm(bar_dt),
                "n=%d close=%.4f ema20=%s ema60=%s rsi=%s boll_up=%s buy=%s sell=%s hold=%s "
                "trend=%s near20=%s alert=%s div=%s cross=%s pat=%s yang=%s "
                "bt_held=%s avail=%s holdings=%s/%s"
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
                    _bt_held_vol() if bt else "-",
                    _bt_available_vol() if bt else "-",
                    _count_holdings(),
                    MAX_HOLDINGS,
                ),
            )

        if sell_reason and holding:
            _order_sell(C, sell_reason, price, now, want_vol=sell_vol, mark_half=mark_half)
            return

        mode = str(ENTRY_MODE or "close").strip().lower()
        pe = getattr(A, "pending_entry", None)
        if (
            (not holding)
            and isinstance(pe, dict)
            and ("BUY" not in getattr(A, "acted", set()))
            and (bt or live_phase == "open" or mode == "next_open")
        ):
            sig_day = str(pe.get("signal_day", "") or "")
            if bt:
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
                print("%s pending_entry set" % STRATEGY_NAME, stock, A.pending_entry)
                return
            _order_buy(C, price, now, swing_low=swing)
    finally:
        _unbind()


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    day = now.strftime("%Y%m%d")
    live_phase = "close"

    if not bt:
        _process_all_pendings(C, now)
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

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    pool = _pool_for_handle(C)
    for code in _holding_codes():
        if code not in pool:
            pool.append(code)

    if not pool:
        _live_heartbeat("empty_pool")
        return

    # 回测勿每根 set_universe(很慢); init 已设过
    if (not bt) or (not getattr(A, "_universe_set", False)):
        try:
            C.set_universe(pool)
            A._universe_set = True
        except Exception:
            pass

    batch = _get_ohlcv_batch(C, pool)
    if not batch:
        _live_heartbeat("ohlcv_none")
        return

    if not getattr(A, "ready_logged", False):
        A.ready_logged = True
        print(
            "%s ready" % STRATEGY_NAME,
            day,
            "pool=",
            len(pool),
            "md=",
            len(batch),
            "holdings=",
            _count_holdings(),
            "/",
            MAX_HOLDINGS,
            "budget=",
            TRADE_BUDGET,
            "refresh=",
            POOL_REFRESH,
        )

    if bt:
        every = int(BT_PROGRESS_EVERY or 0)
        try:
            bp = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            bp = 0
        if every > 0 and bp > 0 and (bp % every == 0):
            print(
                "%s progress" % STRATEGY_NAME,
                "barpos=",
                bp,
                day,
                "hold=",
                _count_holdings(),
                "/",
                MAX_HOLDINGS,
                "md=",
                len(batch),
            )

    sell_first = [c for c in pool if c in set(_holding_codes())]
    buy_cands = [c for c in pool if c not in set(sell_first)]

    for stock in sell_first:
        ohlcv = batch.get(stock)
        if ohlcv is None:
            continue
        _handle_one(C, stock, ohlcv, now, bar_dt, day, live_phase, bt)

    if _count_holdings() < int(MAX_HOLDINGS):
        for stock in buy_cands:
            if _count_holdings() >= int(MAX_HOLDINGS):
                break
            ohlcv = batch.get(stock)
            if ohlcv is None:
                continue
            _handle_one(C, stock, ohlcv, now, bar_dt, day, live_phase, bt)


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
    A.chart_stock = str(getattr(C, "stockcode", "") or "") + "." + str(getattr(C, "market", "") or "")
    A.stock = A.chart_stock
    A.period = _resolve_period(C)
    _ensure_book()

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
    A._diag_ok = False

    chart = str(A.chart_stock or "")
    if chart.startswith("000825.SZ"):
        print(
            "%s warn: 主图是 000825.SZ, 指数应为 000825.SH; 池子仍按 POOL_INDEX 取"
            % STRATEGY_NAME
        )

    try:
        fn = globals().get("download_sector_data")
        if callable(fn):
            fn()
            print("%s download_sector_data ok" % STRATEGY_NAME)
    except Exception as e:
        print("%s download_sector_data skip" % STRATEGY_NAME, e)

    pool = _resolve_pool(C)
    if pool:
        A.pool_cache = list(pool)
        A.pool_ym = _bar_datetime(C).strftime("%Y%m")
    do_dl = DOWNLOAD_HIST_BACKTEST if A.is_backtest else DOWNLOAD_HIST_LIVE
    if do_dl and not getattr(A, "_dl_done", False):
        dl_list = [POOL_INDEX] + list(pool)
        for s in dl_list:
            try:
                _download_hist(s, A.period)
            except Exception as e:
                print("%s download_hist abort-safe" % STRATEGY_NAME, s, e)
        A._dl_done = True
    elif do_dl:
        print("%s skip download_history (already done)" % STRATEGY_NAME)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, A.period, "pool=", len(pool))

    if A.is_backtest:
        barpos = 0
        try:
            barpos = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            barpos = 0
        fresh = (not getattr(A, "_bt_alive", False)) or (barpos <= 0)
        if fresh:
            A.book = {}
            A.acted_day = ""
            A._bt_alive = True
            A.ready_logged = False
            A._universe_set = False
            # 保留 pool_cache / _dl_done，供加速
            print("%s backtest session start barpos=" % STRATEGY_NAME, barpos)
        else:
            print(
                "%s backtest re-init preserve barpos=" % STRATEGY_NAME,
                barpos,
                "holdings=",
                _count_holdings(),
            )
    else:
        _load_state()
        A.ready_logged = False

    try:
        C.set_universe(pool if pool else ([A.chart_stock] if A.chart_stock else []))
        A._universe_set = True
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)
        A._universe_set = False

    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        "chart=",
        A.chart_stock,
        "pool=",
        len(pool),
        "max_hold=",
        MAX_HOLDINGS,
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
        "index=",
        POOL_INDEX,
        "entry=",
        ENTRY_MODE,
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
