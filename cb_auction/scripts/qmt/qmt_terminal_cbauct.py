#coding:gbk
# 由 _deploy_qmt_gbk.py 自动生成；请勿手改。请编辑策略片段与 scripts/qmt_common/ 后重新部署。
import datetime
import json
import os
import traceback

import numpy as np


# === cbauct/config.py ===
# ===================== 用户配置 =====================
# True=只打日志不下单；实盘前确认账号与主图后再改 False
DRY_RUN = True

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 单笔买入资金上限（元）；可转债一手=10张，建议 >= 20000
TRADE_BUDGET = 50000.0
CASH_RATIO = 0.8
# 可转债最小交易单位（张）
LOT_SIZE = 10

# ---- 竞价价格（上市首日规则）----
# 开盘竞价买入顶格价
OPEN_BUY_PRICE = 130.0
# 首日涨停顶格价（≤5亿收盘挂卖参考）
LIMIT_UP_PRICE = 157.30
# 小盘分界：发行规模（亿元）<= 此值 → 收盘提示/回测模拟挂 157.30
SMALL_SIZE_YI = 5.0

# 发行规模（亿元）：优先 ISSUE_SIZE_MAP[A.stock]，否则用默认
ISSUE_SIZE_YI = 0.0
# 2026 样本规模（可继续追加）；键=代码.市场
ISSUE_SIZE_MAP = {
    "118063.SH": 16.72,
    "111024.SH": 5.80,
    "123264.SZ": 8.00,
    "118064.SH": 6.95,
    "123265.SZ": 4.50,
    "127112.SZ": 17.34,
    "110100.SH": 10.00,
    "118065.SH": 19.01,
    "113700.SH": 8.01,
    "118066.SH": 5.76,
    "113701.SH": 4.00,
    "127113.SZ": 7.59,
    "123266.SZ": 3.75,
    "118067.SH": 3.25,
    "123268.SZ": 4.69,
    "113702.SH": 15.00,
    "123269.SZ": 9.80,
    "123267.SZ": 7.50,
    "123270.SZ": 4.05,
    "123271.SZ": 5.22,
    "118068.SH": 9.08,
    "123272.SZ": 10.39,
    "123273.SZ": 2.90,
    "113704.SH": 21.79,
    "113703.SH": 13.01,
    "118069.SH": 2.67,
    "113705.SH": 18.00,
    "113706.SH": 9.70,
    "118070.SH": 15.87,
    "123274.SZ": 6.30,
    "127114.SZ": 33.00,
    "110101.SH": 35.00,
    "118072.SH": 9.30,
    "118071.SH": 7.49,
    "111025.SH": 25.00,
    "123275.SZ": 5.90,
    "113707.SH": 14.91,
    "123276.SZ": 3.00,
    "110102.SH": 11.85,
    "113708.SH": 80.00,
}

# ---- 时窗（HHmmss，实盘用墙钟；回测用 K 线时间）----
# 开盘竞价：9:15 起挂 130；默认挂到 9:24:59
BUY_START = "091500"
BUY_END = "092500"
# 收盘竞价提示窗（仅日志 / 回测模拟卖，实盘不自动卖）
SELL_HINT_START = "145700"
SELL_HINT_END = "150000"

# 实盘：卖出一律手动；本策略只打印建议挂单价
# 回测：True=在提示窗按定稿价模拟卖出（可转债 T+0）；实盘忽略此开关
BACKTEST_SIM_SELL = True

# ---- 行情与运行 ----
PERIOD = "1m"
OHLC_COUNT = 120
LIVE_ONLY_LAST_BAR = True
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 30
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 300
PENDING_ORPHAN_SEC = 60

STATE_FILE = r"D:\tradingStrategy\cbauct_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "CbAuct"
STRATEGY_VER = "v1.0"
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

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

# === qmt_common/live_log.py ===
# 作用: 实盘结构化日志落盘（events / bars / heartbeat / state 快照）
# 主要符号: _event_log, _bar_log, _heartbeat_persist, _live_state_snapshot
# 前置: LOG_DIR（绝对路径）；可选 LOG_IN_BACKTEST
# 目录: LOG_DIR/<stock_tag>/{tag}_events.jsonl | {tag}_bars.jsonl |
#       {tag}_heartbeat.log | state_snapshots/YYYYMMDD_HHMM.json
# 覆盖 ctx 中的同名空实现
def _live_log_stock_tag():
    stock = str(getattr(A, "stock", "") or "").strip()
    if not stock:
        return ""
    return (
        stock.replace(".", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(" ", "")
    )


def _live_log_enabled():
    base = str(globals().get("LOG_DIR") or "").strip()
    if not base:
        return False
    if getattr(A, "is_backtest", False) and (not bool(globals().get("LOG_IN_BACKTEST"))):
        return False
    return True


def _live_log_root():
    base = str(globals().get("LOG_DIR") or "").strip()
    tag = _live_log_stock_tag() or "_unknown"
    return os.path.join(base, tag)


def _live_log_file_tag():
    raw = _strategy_tag()
    return (
        str(raw or "QMT")
        .replace(".", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(" ", "_")
    )


def _live_log_paths():
    root = _live_log_root()
    ft = _live_log_file_tag()
    return {
        "root": root,
        "events": os.path.join(root, "%s_events.jsonl" % ft),
        "bars": os.path.join(root, "%s_bars.jsonl" % ft),
        "heartbeat": os.path.join(root, "%s_heartbeat.log" % ft),
        "snap_dir": os.path.join(root, "state_snapshots"),
    }


def _live_log_mkdir(path):
    d = os.path.dirname(path)
    if d and (not os.path.isdir(d)):
        os.makedirs(d)


def _live_json_safe(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[str(k)] = _live_json_safe(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_live_json_safe(x) for x in obj]
    if isinstance(obj, set):
        return sorted([_live_json_safe(x) for x in obj])
    try:
        if isinstance(obj, datetime.datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return str(obj)


def _live_append_line(path, line):
    _live_log_mkdir(path)
    with open(path, "a") as f:
        f.write(line)
        if not line.endswith("\n"):
            f.write("\n")


def _live_append_jsonl(path, row):
    line = json.dumps(_live_json_safe(row), ensure_ascii=True)
    _live_append_line(path, line)


def _event_log(event, **fields):
    """一行一事写入 {tag}_events.jsonl；失败静默，不影响交易。"""
    if not _live_log_enabled():
        return
    try:
        now = datetime.datetime.now()
        row = {
            "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
            "tag": _strategy_tag(),
            "ver": str(globals().get("STRATEGY_VER") or ""),
            "stock": getattr(A, "stock", ""),
            "event": str(event or ""),
        }
        for k, v in fields.items():
            if k in row:
                continue
            row[k] = v
        _live_append_jsonl(_live_log_paths()["events"], row)
    except Exception:
        pass


def _bar_log(**fields):
    """决策行抽样写入 {tag}_bars.jsonl。"""
    if not _live_log_enabled():
        return
    try:
        now = datetime.datetime.now()
        row = {
            "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
            "tag": _strategy_tag(),
            "ver": str(globals().get("STRATEGY_VER") or ""),
            "stock": getattr(A, "stock", ""),
        }
        for k, v in fields.items():
            if k in row:
                continue
            row[k] = v
        _live_append_jsonl(_live_log_paths()["bars"], row)
    except Exception:
        pass


def _heartbeat_persist(text):
    """心跳写入 {tag}_heartbeat.log（纯文本）。"""
    if not _live_log_enabled():
        return
    try:
        line = str(text or "").rstrip()
        if not line:
            return
        _live_append_line(_live_log_paths()["heartbeat"], line)
    except Exception:
        pass


def _live_state_snapshot(data):
    """状态快照: state_snapshots/YYYYMMDD_HHMM.json（同分钟覆盖）。"""
    if not _live_log_enabled():
        return
    if not isinstance(data, dict):
        return
    try:
        now = datetime.datetime.now()
        name = now.strftime("%Y%m%d_%H%M") + ".json"
        path = os.path.join(_live_log_paths()["snap_dir"], name)
        _live_log_mkdir(path)
        with open(path, "w") as f:
            json.dump(_live_json_safe(data), f, ensure_ascii=True, indent=2)
    except Exception:
        pass

# === qmt_common/time_util.py ===
# 作用: 时间解析与日历日差
# 主要符号: _parse_opened_at, _hold_calendar_days
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


def _hold_calendar_days(opened_at, now):
    """当前交易日 - 买入交易日（日历日差）。"""
    ot = opened_at if isinstance(opened_at, datetime.datetime) else _parse_opened_at(opened_at)
    if ot is None or now is None:
        return 0
    return max(0, (now.date() - ot.date()).days)

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

# === cbauct/state_extra.py ===
def _state_extra_load(raw):
    A.buy_done_day = str(raw.get("buy_done_day", "") or "")
    A.sell_hint_day = str(raw.get("sell_hint_day", "") or "")
    A.sim_sell_day = str(raw.get("sim_sell_day", "") or "")


def _state_extra_save(data):
    data["buy_done_day"] = str(getattr(A, "buy_done_day", "") or "")
    data["sell_hint_day"] = str(getattr(A, "sell_hint_day", "") or "")
    data["sim_sell_day"] = str(getattr(A, "sim_sell_day", "") or "")

# === qmt_common/single/state_io.py ===
# 作用: 单仓 JSON 状态读写（回测不落盘）
# 主要符号: _load_state, _save_state
# 前置: STATE_FILE, STRATEGY_VER；可选扩展字段由 _state_extra_load/_state_extra_save
# STATE_FILE 为基路径；有 A.stock 时按标的分文件，多模型实例互不覆盖
#   例 ...\hlband_qmt_state.json + 513530.SH → ...\hlband_qmt_state_513530_SH.json
#   或 STATE_FILE 含 {stock} 占位符时直接替换
def _state_stock_tag():
    stock = str(getattr(A, "stock", "") or "").strip()
    if not stock:
        return ""
    return (
        stock.replace(".", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(" ", "")
    )


def _state_path():
    base = str(STATE_FILE or "").strip()
    if not base:
        return base
    tag = _state_stock_tag()
    if not tag:
        return base
    if "{stock}" in base:
        return base.replace("{stock}", tag)
    root, ext = os.path.splitext(base)
    if not ext:
        ext = ".json"
    return root + "_" + tag + ext


def _state_load_path():
    """优先分标的文件；缺失时回退旧版共用 STATE_FILE（由 _load_state 再校验 stock）。"""
    path = _state_path()
    if path and os.path.isfile(path):
        return path
    legacy = str(STATE_FILE or "").strip()
    if legacy and legacy != path and os.path.isfile(legacy):
        return legacy
    return path


def _load_state():
    A.position = None
    A.acted_day = ""
    A.acted = set()
    A.pending = None
    path = _state_load_path()
    if not path or not os.path.isfile(path):
        print(_strategy_tag(), "state: empty (no file)", path or STATE_FILE)
        _event_log("state_empty", path=path or STATE_FILE)
        return
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except Exception as e:
        print(_strategy_tag(), "state load fail", e)
        _event_log("state_load_fail", error=str(e), path=path)
        return
    if not isinstance(raw, dict):
        return
    if str(raw.get("stock", "")) and str(raw.get("stock")) != str(getattr(A, "stock", "")):
        print(_strategy_tag(), "state stock mismatch, ignore", raw.get("stock"), getattr(A, "stock", None))
        _event_log(
            "state_stock_mismatch",
            file_stock=raw.get("stock"),
            runtime_stock=getattr(A, "stock", None),
            path=path,
        )
        return
    pos = raw.get("position")
    if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100:
        A.position = dict(pos)
        A.position["shares"] = int(pos["shares"])
        A.position["price"] = float(pos.get("price", 0) or 0)
        A.position["cost"] = float(pos.get("cost", 0) or 0)
        A.position["opened_at"] = str(pos.get("opened_at", "") or "")
    A.acted_day = str(raw.get("acted_day", "") or "")
    acted = raw.get("acted") or []
    A.acted = set([str(x) for x in acted]) if isinstance(acted, list) else set()
    pend = raw.get("pending")
    A.pending = pend if isinstance(pend, dict) else None
    extra = globals().get("_state_extra_load")
    if callable(extra):
        try:
            extra(raw)
        except Exception as e:
            print(_strategy_tag(), "state extra load fail", e)
            _event_log("state_extra_load_fail", error=str(e))
    print(_strategy_tag(), "state loaded", "path=", path, A.position, "pending=", bool(A.pending))
    _event_log(
        "state_loaded",
        path=path,
        position=A.position,
        pending=bool(A.pending),
        pending_order=bool(getattr(A, "pending", None)),
    )


def _save_state():
    if getattr(A, "is_backtest", False):
        return
    path = _state_path()
    if not path:
        return
    data = {
        "stock": getattr(A, "stock", ""),
        "version": str(globals().get("STRATEGY_VER") or ""),
        "position": getattr(A, "position", None),
        "acted_day": getattr(A, "acted_day", ""),
        "acted": sorted(list(getattr(A, "acted", set()) or [])),
        "pending": getattr(A, "pending", None),
        "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    extra = globals().get("_state_extra_save")
    if callable(extra):
        try:
            extra(data)
        except Exception as e:
            print(_strategy_tag(), "state extra save fail", e)
            _event_log("state_extra_save_fail", error=str(e))
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)
        _live_state_snapshot(data)
    except Exception as e:
        print(_strategy_tag(), "state save fail", path, e)
        _event_log("state_save_fail", error=str(e), path=path)

# === qmt_common/backtest.py ===
# 作用: 回测影子持仓与 T+1 锁定
# 主要符号: _bt_held_*, _bt_locked_*, _bt_roll_t1
# 说明: 仓位恢复（_bt_recover_*）由策略侧实现
def _bt_held_vol():
    return max(0, int(getattr(A, "bt_held", 0) or 0))


def _bt_locked_vol():
    return max(0, int(getattr(A, "bt_locked", 0) or 0))


def _bt_available_vol():
    """回测 T+1: 非当日买入的可卖股数（对应 QMT 可卖）。"""
    return max(0, _bt_held_vol() - _bt_locked_vol())


def _bt_roll_t1(day):
    """新日历日解锁此前买入，变为可卖。"""
    if not getattr(A, "is_backtest", False):
        return
    day = str(day or "")
    if not day:
        return
    if str(getattr(A, "bt_lock_day", "") or "") == day:
        return
    if _bt_locked_vol() > 0:
        print(_strategy_tag(), "bt T+1 unlock day=", day, "was_locked=", _bt_locked_vol())
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

# === qmt_common/single/state_pos.py ===
# 作用: 单仓 A.position 读写辅助
# 主要符号: _has_position, _pos_shares, _pos_cost_price, _reset_day, _clear_after_sell
def _reset_day(day):
    if getattr(A, "acted_day", "") != day:
        A.acted_day = day
        A.acted = set()
        try:
            _save_state()
        except Exception:
            pass


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


def _clear_after_sell(now, reason, last=None):
    cleared = getattr(A, "position", None)
    print(_strategy_tag(), "SELL done", reason, "last=", last, "cleared", cleared)
    _event_log("sell_done", sell_reason=reason, last=last, cleared=cleared)
    A.position = None
    A.acted.add("SELL")
    if getattr(A, "is_backtest", False):
        A.bt_held = 0
        A.bt_locked = 0
        A.bt_opened_at = ""
    _save_state()

# === qmt_common/single/bt_recover.py ===
# 作用: 单仓回测影子仓恢复为 A.position
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
    print(_strategy_tag(), "bt recover position from held", A.position)
    return True

# === cbauct/indicators.py ===
def _bar_hhmmss(dt):
    if dt is None:
        return "000000"
    return dt.strftime("%H%M%S")


def _bar_tag(dt):
    if dt is None:
        return ""
    return dt.strftime("%Y%m%d%H%M%S")


def _issue_size_yi():
    """发行规模（亿元）；未知返回 None。"""
    stock = str(getattr(A, "stock", "") or "")
    mp = globals().get("ISSUE_SIZE_MAP") or {}
    if stock in mp:
        try:
            return float(mp[stock])
        except Exception:
            pass
    try:
        v = float(globals().get("ISSUE_SIZE_YI") or 0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    return None


def _is_small_issue():
    sz = _issue_size_yi()
    if sz is None:
        return False
    return sz <= float(globals().get("SMALL_SIZE_YI") or 5.0)


def _sell_hint_price(last_px):
    """定稿卖价：≤5亿→157.30；否则→可确认收盘价（用最新价近似）。"""
    if _is_small_issue():
        return float(globals().get("LIMIT_UP_PRICE") or 157.30)
    try:
        px = float(last_px)
    except Exception:
        px = 0.0
    if px > 0:
        return round(px, 3)
    return None

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

# === cbauct/market.py ===
def _get_ohlcv(C, stock):
    """拉主图周期 OHLCV；上市首日样本可能很短，need 放宽。"""
    period = getattr(A, "period", "1m")
    count = int(globals().get("OHLC_COUNT") or 120)
    need = 1
    end = _bar_end_str(C)
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
            dividend_type="none",
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
                dividend_type="none",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once("md_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("md_ex_fail", e)
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
                dividend_type="none",
            )
            source = "get_market_data"
            open_ = _series_from_ex(md2, stock, "open")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
            close = _series_from_ex(md2, stock, "close")
            volume = _series_from_ex(md2, stock, "volume")
        except Exception as e:
            _diag_once("md_gmd_fail", e)

    if not close or len(close) < need:
        _diag_once(
            "md_empty",
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

    _diag_once(
        "md_ok",
        "source=",
        source,
        "period=",
        period,
        "n=",
        n,
        "end=",
        end,
        "last=",
        round(float(close[-1]), 4),
    )
    return open_, high, low, close, volume

# === qmt_common/mode.py ===
# 作用: 回测/实盘模式、暖机切换、K 线时间
# 主要符号: _refresh_mode, _is_backtest, _bar_datetime
# 钩子: _load_state；可选 _reconcile_with_broker
def _is_backtest(C):
    return bool(getattr(C, "do_back_test", False))


def _on_mode_switch_to_live(C):
    """暖机结束: 切到实盘语义（STATE / pending / 墙钟）。"""
    print(
        _strategy_tag(),
        "mode switch backtest -> live",
        "raw_do_back_test=",
        getattr(A, "do_back_test_raw", None),
        "barpos=",
        getattr(C, "barpos", None),
    )
    _event_log(
        "mode_switch",
        direction="backtest_to_live",
        raw_do_back_test=getattr(A, "do_back_test_raw", None),
        barpos=getattr(C, "barpos", None),
    )
    A.ready_logged = False
    A._hb_at = None
    try:
        _load_state()
    except Exception as e:
        print(_strategy_tag(), "live switch load_state fail", e)
        _event_log("live_switch_load_state_fail", error=str(e))
    if not hasattr(A, "pending"):
        A.pending = None
    recon = globals().get("_reconcile_with_broker")
    if callable(recon):
        try:
            recon()
        except Exception as e:
            print(_strategy_tag(), "live switch reconcile fail", e)
            _event_log("live_switch_reconcile_fail", error=str(e))


def _refresh_mode(C):
    """每根 K 刷新 A.is_backtest。

    国金模型交易常先以 do_back_test=True 暖机历史，
    再进入同一根最新 K 做实时，而标志可能仍为 True。
    追赶规则: 今日最新 K 上 barpos 不变的第 2 次及以后调用 => 实盘。
    """
    prev = getattr(A, "is_backtest", None)
    raw = bool(getattr(C, "do_back_test", False))
    A.do_back_test_raw = raw
    use_bt = raw
    if raw:
        try:
            if C.is_last_bar():
                bp = int(getattr(C, "barpos", 0) or 0)
                last_bp = int(getattr(A, "_mode_last_bp", -1))
                hits = int(getattr(A, "_mode_same_bp_hits", 0) or 0)
                if bp == last_bp and bp >= 0:
                    hits += 1
                else:
                    hits = 0
                A._mode_last_bp = bp
                A._mode_same_bp_hits = hits
                bar_day = _bar_datetime(C).strftime("%Y%m%d")
                today = datetime.datetime.now().strftime("%Y%m%d")
                if bar_day == today and hits >= 1:
                    use_bt = False
        except Exception:
            pass
    else:
        A._mode_same_bp_hits = 0

    A.is_backtest = use_bt
    if prev is True and (not use_bt):
        _on_mode_switch_to_live(C)
    elif prev is False and use_bt:
        print(_strategy_tag(), "mode switch live -> backtest raw=", raw)
        _event_log("mode_switch", direction="live_to_backtest", raw=raw)
    return use_bt


def _bar_datetime(C):
    """回测用 K 线时间；实盘用墙钟。

    注意: 若调用方已判定实盘，可直接用 datetime.now()；
    本函数在无法解析 timetag 时回退墙钟。
    """
    try:
        tag = C.get_bar_timetag(C.barpos)
        if "timetag_to_datetime" in globals():
            s = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
            return datetime.datetime.strptime(str(s), "%Y%m%d%H%M%S")
        if tag > 10**12:
            return datetime.datetime.fromtimestamp(tag / 1000.0)
        return datetime.datetime.fromtimestamp(tag)
    except Exception:
        return datetime.datetime.now()

# === qmt_common/broker_base.py ===
# 作用: 资金/持仓查询（只读券商账本）
# 主要符号: _available_cash, _broker_position, _can_use_vol
# 说明: _max_sell_vol / 底仓隔离由策略或 single/broker 提供
def _available_cash():
    if getattr(A, "is_backtest", False):
        return 10**9
    try:
        accs = get_trade_detail_data(A.acct, A.acct_type, "account")
    except Exception as e:
        _diag_once("cash_fail", e)
        return None
    if not accs:
        print(_strategy_tag(), "account not login", A.acct)
        _event_log("account_not_login", acct=A.acct)
        return None
    return float(accs[0].m_dAvailable)


def _pos_code(p):
    return str(getattr(p, "m_strInstrumentID", "") or "") + "." + str(
        getattr(p, "m_strExchangeID", "") or ""
    )


def _broker_position(stock):
    """返回标的 (总量, 可卖, 成本价)；无持仓则 (0,0,0)。"""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return 0, 0, 0.0
    try:
        positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    except Exception as e:
        print(_strategy_tag(), "position query fail", e)
        _event_log("position_query_fail", error=str(e), query_stock=stock)
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


def _can_use_vol(stock):
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return 10**9
    _vol, can, _cost = _broker_position(stock)
    return int(can)

# === qmt_common/single/broker.py ===
# 作用: 单仓可卖上限（T+1 / can_use）
# 主要符号: _max_sell_vol, _dry_t1_sellable
def _dry_t1_sellable(want, now):
    """DRY_RUN 的 T+1: 禁止同日历日卖出当日买入仓。"""
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
    """最多可卖股数; 始终受 T+1 约束. skip 时调用方绝不清仓."""
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

# === qmt_common/orders_pending.py ===
# 作用: 委托查询、撤单、pending 生命周期
# 主要符号: _process_pending, _deal_fill, _try_cancel_order, _new_remark
# 钩子(策略必须提供): _pending_on_buy_fill(pend, vol, px)
#                     _pending_on_sell_fill(pend, now, vol, px)
#                     _save_state
def _deal_fill(remark, stock):
    """汇总匹配 remark+标的 的成交 -> (量, 均价)。"""
    vol = 0
    notional = 0.0
    try:
        deals = get_trade_detail_data(A.acct, A.acct_type, "deal")
    except Exception as e:
        print(_strategy_tag(), "deal query fail", e)
        _event_log("deal_query_fail", error=str(e))
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
        print(_strategy_tag(), "order query fail", e)
        _event_log("order_query_fail", error=str(e))
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
    """尽力通过 QMT 内置撤单（API 名因版本而异）。"""
    oid = _order_sys_id(od)
    if oid is None:
        print(_strategy_tag(), "cancel skip: no order id")
        _event_log("cancel_skip", reason="no_order_id")
        return False
    for fn_name in ("cancel", "cancel_order", "cancelorder"):
        fn = globals().get(fn_name)
        if not callable(fn):
            continue
        try:
            fn(oid, A.acct, A.acct_type, C)
            print(_strategy_tag(), "cancel via", fn_name, oid)
            _event_log("cancel", via=fn_name, oid=str(oid))
            return True
        except TypeError:
            try:
                fn(oid, A.acct, A.acct_type)
                print(_strategy_tag(), "cancel via", fn_name, "(3arg)", oid)
                _event_log("cancel", via=fn_name, oid=str(oid), argc=3)
                return True
            except Exception as e:
                print(_strategy_tag(), fn_name, "fail", e)
                _event_log("cancel_fail", via=fn_name, error=str(e), oid=str(oid))
        except Exception as e:
            print(_strategy_tag(), fn_name, "fail", e)
            _event_log("cancel_fail", via=fn_name, error=str(e), oid=str(oid))
    print(_strategy_tag(), "cancel unavailable; keep waiting, oid=", oid)
    _event_log("cancel_unavailable", oid=str(oid))
    return False


def _clear_pending(reason=""):
    pend = getattr(A, "pending", None)
    if pend:
        print(_strategy_tag(), "pending clear", reason, pend.get("remark"))
        _event_log(
            "pending_clear",
            reason=reason,
            remark=pend.get("remark"),
            side=pend.get("side"),
            intent=pend.get("intent"),
            vol=pend.get("vol"),
        )
    A.pending = None
    _save_state()


def _new_remark(tag, side, vol):
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return "%s %s %s %s x%d %s" % (_strategy_tag(), side, tag, A.stock, int(vol), ts)


def _process_pending(C, now):
    """实盘: 处理 pending；超时先撤；仅终态清空。仍阻塞则返回 True。"""
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
        _strategy_tag(),
        "pending check",
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
    _event_log(
        "pending_check",
        intent=intent,
        side=side,
        deal=deal_vol,
        traded=traded,
        status=status,
        age_sec=int(age),
        cancel_req=cancel_req,
        target=target,
        remark=remark,
    )

    filled = globals().get("_ORDER_FILLED") or (56, 8)
    dead = globals().get("_ORDER_DEAD") or (54, 57, 53, 5, 6, 9)
    done_fill = traded >= target and target >= 100
    status_filled = status in filled
    status_dead = status in dead

    if done_fill or (status_filled and traded >= 100):
        use_vol = traded if traded >= 100 else deal_vol
        if side == "buy":
            _pending_on_buy_fill(pend, use_vol, px)
        else:
            _pending_on_sell_fill(pend, now, use_vol, px)
        _clear_pending("filled")
        return False

    if status_dead:
        if traded >= 100:
            if side == "buy":
                _pending_on_buy_fill(pend, traded, px)
            else:
                _pending_on_sell_fill(pend, now, traded, px)
            _clear_pending("dead-partial")
        else:
            _clear_pending("rejected/cancelled")
        return False

    timeout = float(globals().get("PENDING_TIMEOUT_SEC") or 180)
    orphan = float(globals().get("PENDING_ORPHAN_SEC") or 60)
    if age >= timeout:
        if not cancel_req:
            if od is not None:
                _try_cancel_order(od, C)
            else:
                print(_strategy_tag(), "pending timeout, order not visible yet")
                _event_log("pending_timeout", remark=remark, intent=intent, age_sec=int(age))
            pend["cancel_requested"] = True
            pend["cancel_at"] = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
            A.pending = pend
            _save_state()
            return True
        cancel_at = _parse_opened_at(pend.get("cancel_at"))
        cancel_age = 0.0
        if cancel_at is not None and now is not None:
            cancel_age = (now - cancel_at).total_seconds()
        if od is None and cancel_age >= orphan:
            print(_strategy_tag(), "pending orphan clear (no order after cancel wait)")
            _event_log(
                "pending_orphan",
                remark=remark,
                intent=intent,
                cancel_age_sec=int(cancel_age),
            )
            _clear_pending("orphan")
            return False
        return True

    return True

# === qmt_common/single/orders.py ===
# 作用: 单仓买卖委托与成交落地
# 主要符号: _order_buy, _order_sell, _apply_buy_fill, _apply_sell_fill
# 钩子实现: _pending_on_buy_fill / _pending_on_sell_fill
# 预算: TRADE_BUDGET；可选 CASH_RATIO（实盘 min(budget, cash*ratio)）
def _buy_budget(cash):
    budget = float(globals().get("TRADE_BUDGET") or 0)
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return budget if budget > 0 else 0.0
    ratio = float(globals().get("CASH_RATIO") or 0)
    if cash is None or cash <= 0:
        return budget
    if ratio > 0:
        by_ratio = float(cash) * ratio
        return min(budget, by_ratio) if budget > 0 else by_ratio
    return budget


def _apply_buy_fill(vol, price, opened_at, **extra):
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < 100:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    pos = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
    }
    for k, v in extra.items():
        if v is not None:
            pos[k] = v
    A.position = pos
    A.acted.add("BUY")
    if getattr(A, "is_backtest", False):
        A.bt_opened_at = ot
    buy_day = ot[:8] if len(ot) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position)
    _event_log("buy_filled", position=A.position, vol=vol, price=price, opened_at=ot)


def _apply_sell_fill(now, reason, last_hint, filled_vol, mark_half=False):
    """卖出成交后清空或缩减持仓. 仅按实际成交量改状态."""
    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    filled_vol = int(filled_vol)
    if filled_vol < 100:
        return
    if filled_vol >= max(100, int(want * 0.95)) or filled_vol >= want:
        _clear_after_sell(now, reason, last=last_hint)
        if mark_half:
            A.acted.add("HALF")
            _save_state()
        return
    remain = max(0, want - filled_vol)
    print(_strategy_tag(), "partial sell fill", filled_vol, "remain~", remain)
    _event_log(
        "partial_sell_fill",
        reason=reason,
        filled_vol=filled_vol,
        remain=remain,
        last=last_hint,
    )
    if A.position:
        A.position["shares"] = remain
    _bt_held_set(remain)
    if remain < 100:
        _clear_after_sell(now, str(reason) + "/partial", last=last_hint)
    else:
        if mark_half:
            A.acted.add("HALF")
        _save_state()


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _pending_on_sell_fill(pend, now, vol, px):
    intent = str(pend.get("intent", "") or "")
    last_hint = pend.get("last_hint")
    if last_hint is None:
        last_hint = px
    mark_half = bool(pend.get("mark_half"))
    _apply_sell_fill(now, intent, last_hint, vol, mark_half=mark_half)


def _order_buy(C, price, now, budget=None, **extra_pos):
    """提交买入. DRY 即时; 回测 passorder+即时; 实盘 pending 至成交."""
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        print(_strategy_tag(), "buy skip: already holding")
        _event_log("buy_skip", reason="already_holding")
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False

    if budget is None:
        cash = _available_cash()
        budget = _buy_budget(cash)
    vol = _lot(price, budget)
    if vol < 100:
        print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
        _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _lot(price, cash)
        if vol < 100:
            print(_strategy_tag(), "buy skip cash", cash)
            _event_log("buy_skip", reason="cash", cash=cash, price=price)
            return False

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark("BUY", "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@", price)
    if DRY_RUN:
        _apply_buy_fill(vol, price, ot, **extra_pos)
        return True
    try:
        passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, _strategy_tag(), 1, msg, C)
    except Exception as e:
        print(_strategy_tag(), "passorder BUY fail", e)
        _event_log("passorder_fail", side="buy", error=str(e), vol=vol, price=price)
        return False
    if getattr(A, "is_backtest", False):
        _apply_buy_fill(vol, price, ot, **extra_pos)
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
        "extra_pos": extra_pos or {},
    }
    _save_state()
    print(_strategy_tag(), "BUY submitted", vol, msg)
    _event_log("buy_submitted", vol=vol, price=price, remark=msg, dry_run=False)
    return True


def _order_sell(C, reason, price, now, want_vol=None, mark_half=False):
    """提交卖出. T+1: 下单量不超过可卖; skip 绝不清仓."""
    if getattr(A, "pending", None):
        print(_strategy_tag(), "sell skip: pending active")
        _event_log("sell_skip", reason="pending_active", sell_reason=reason)
        return False
    if not _has_position() and not (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        return False
    if (not mark_half) and ("SELL" in getattr(A, "acted", set())):
        return False

    want = int(want_vol) if want_vol is not None else _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol()) if want_vol is None else want
    if want < 100:
        return False

    avail = _max_sell_vol(now)
    vol = int(min(want, avail) // 100) * 100
    if vol < 100:
        if getattr(A, "is_backtest", False):
            print(
                _strategy_tag(),
                "sell skip T+1",
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
            _event_log(
                "sell_skip",
                reason="t1_bt",
                sell_reason=reason,
                avail=avail,
                held=_bt_held_vol(),
                locked=_bt_locked_vol(),
                want=want,
            )
        elif DRY_RUN:
            print(
                _strategy_tag(),
                "[DRY] sell skip T+1",
                reason,
                "want=",
                want,
                "sellable=",
                avail,
            )
            _event_log(
                "sell_skip",
                reason="t1_dry",
                sell_reason=reason,
                want=want,
                sellable=avail,
            )
        else:
            broker_vol, can, _cost = _broker_position(A.stock)
            print(
                _strategy_tag(),
                "sell skip T+1/live",
                reason,
                "can_use=",
                can,
                "broker=",
                broker_vol,
                "want=",
                want,
            )
            _event_log(
                "sell_skip",
                reason="t1_live",
                sell_reason=reason,
                can_use=can,
                broker=broker_vol,
                want=want,
            )
        return False

    msg = _new_remark(reason or "SELL", "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@", price)
    if DRY_RUN:
        _apply_sell_fill(now, reason, price, vol, mark_half=mark_half)
        return True
    try:
        passorder(A.sell_code, 1101, A.acct, A.stock, 14, -1, vol, _strategy_tag(), 1, msg, C)
    except Exception as e:
        print(_strategy_tag(), "passorder SELL fail", e)
        _event_log(
            "passorder_fail",
            side="sell",
            error=str(e),
            vol=vol,
            price=price,
            sell_reason=reason,
        )
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
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
        "mark_half": bool(mark_half),
    }
    _save_state()
    print(_strategy_tag(), "SELL submitted", vol, reason, msg)
    _event_log(
        "sell_submitted",
        vol=vol,
        price=price,
        sell_reason=reason,
        remark=msg,
        dry_run=False,
    )
    return True

# === cbauct/strategy.py ===
# 定稿:
#   开盘竞价: 9:15 全标的 @130 限价买
#   收盘竞价: ≤5亿提示 157.30；>5亿提示可确认收盘价；卖出手动（回测可模拟）


def _has_position():
    """可转债一手=10张；覆盖 common 的 >=100 判定。"""
    pos = getattr(A, "position", None)
    lot = int(globals().get("LOT_SIZE") or 10)
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= lot


def _cb_lot(price, budget):
    lot = int(globals().get("LOT_SIZE") or 10)
    if price is None or price <= 0 or budget <= 0 or lot <= 0:
        return 0
    return int(float(budget) // (float(price) * lot)) * lot


def _apply_cb_buy_fill(vol, price, opened_at, **extra):
    lot = int(globals().get("LOT_SIZE") or 10)
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < lot:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    pos = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
    }
    for k, v in extra.items():
        if v is not None:
            pos[k] = v
    A.position = pos
    A.acted.add("BUY")
    if getattr(A, "is_backtest", False):
        A.bt_opened_at = ot
    buy_day = ot[:8] if len(ot) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    # 可转债 T+0：回测当日即可卖（仅影响 BACKTEST_SIM_SELL）
    if getattr(A, "is_backtest", False):
        A.bt_locked = 0
    day = buy_day or ""
    if day:
        A.buy_done_day = day
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position)
    _event_log("buy_filled", position=A.position, vol=vol, price=price, opened_at=ot)


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_cb_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _order_buy_limit(C, price, now, budget=None):
    """限价买入 prType=11；用于开盘竞价挂 130。"""
    lot = int(globals().get("LOT_SIZE") or 10)
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    if _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= lot
    ):
        print(_strategy_tag(), "buy skip: already holding")
        _event_log("buy_skip", reason="already_holding")
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False

    if budget is None:
        cash = _available_cash()
        budget = _buy_budget(cash)
    vol = _cb_lot(price, budget)
    if vol < lot:
        print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
        _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _cb_lot(price, cash)
        if vol < lot:
            print(_strategy_tag(), "buy skip cash", cash)
            _event_log("buy_skip", reason="cash", cash=cash, price=price)
            return False

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark("BUY", "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price)
    if DRY_RUN:
        _apply_cb_buy_fill(vol, price, ot)
        return True
    try:
        # prType=11 指定价；quickTrade=1 即时报单（集合竞价可挂）
        passorder(
            A.buy_code,
            1101,
            A.acct,
            A.stock,
            11,
            float(price),
            vol,
            _strategy_tag(),
            1,
            msg,
            C,
        )
    except Exception as e:
        print(_strategy_tag(), "passorder BUY limit fail", e)
        _event_log("passorder_fail", side="buy", error=str(e), vol=vol, price=price)
        return False
    if getattr(A, "is_backtest", False):
        _apply_cb_buy_fill(vol, price, ot)
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
        "extra_pos": {},
    }
    A.buy_done_day = ot[:8]
    _save_state()
    print(_strategy_tag(), "BUY submitted limit", vol, "@", price, msg)
    _event_log("buy_submitted", vol=vol, price=price, remark=msg, dry_run=False)
    return True


def _cb_sim_sell(now, reason, price):
    """仅回测：按提示价清空影子仓（T+0）。"""
    if not getattr(A, "is_backtest", False):
        return False
    if not _has_position() and _bt_held_vol() < int(globals().get("LOT_SIZE") or 10):
        return False
    A.bt_locked = 0
    vol = max(_pos_shares(), _bt_held_vol())
    print(
        "[BT-SIM] %s SELL" % _strategy_tag(),
        reason,
        "vol=",
        vol,
        "@",
        price,
    )
    _event_log(
        "bt_sim_sell",
        sell_reason=reason,
        vol=vol,
        price=price,
    )
    _clear_after_sell(now, reason, last=price)
    return True


def _in_window(now_s, start, end):
    return str(start) <= str(now_s) <= str(end)


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        if LIVE_ONLY_LAST_BAR:
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        _live_heartbeat("live")
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
    opens, highs, lows, closes, vols = ohlcv
    last_px = float(closes[-1])
    open_px = float(opens[-1])

    if bt:
        _bt_recover_position(now=now, last=last_px)

    holding = _has_position() or (
        bt and _bt_held_vol() >= int(globals().get("LOT_SIZE") or 10)
    )
    size_yi = _issue_size_yi()
    small = _is_small_issue()
    hint_px = _sell_hint_price(last_px)

    buy_start = str(globals().get("BUY_START") or "091500")
    buy_end = str(globals().get("BUY_END") or "092500")
    hint_start = str(globals().get("SELL_HINT_START") or "145700")
    hint_end = str(globals().get("SELL_HINT_END") or "150000")
    buy_px = float(globals().get("OPEN_BUY_PRICE") or 130.0)

    interesting = holding or getattr(A, "pending", None) or (
        str(getattr(A, "buy_done_day", "") or "") == day
    )
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 30 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            now_s,
            "n=%d last=%.4f open=%.4f hold=%s size=%s small=%s hint=%s "
            "buy_done=%s pending=%s bt_held=%s"
            % (
                len(closes),
                last_px,
                open_px,
                holding,
                size_yi,
                small,
                hint_px,
                getattr(A, "buy_done_day", ""),
                bool(getattr(A, "pending", None)),
                _bt_held_vol() if bt else "-",
            ),
        )
        _bar_log(
            day=day,
            hhmmss=now_s,
            n=len(closes),
            last=round(last_px, 6),
            open=round(open_px, 6),
            hold=holding,
            size_yi=size_yi,
            small=small,
            hint=hint_px,
            buy_done=str(getattr(A, "buy_done_day", "") or ""),
            tag=tag,
        )

    # ---- 开盘竞价限价买 ----
    in_buy = _in_window(now_s, buy_start, buy_end)
    already_bought = str(getattr(A, "buy_done_day", "") or "") == day
    if (
        in_buy
        and (not holding)
        and (not already_bought)
        and ("BUY" not in getattr(A, "acted", set()))
        and (not getattr(A, "pending", None))
    ):
        print(
            "%s OPEN_AUCTION buy @%.2f window=%s-%s size=%s"
            % (STRATEGY_NAME, buy_px, buy_start, buy_end, size_yi)
        )
        _event_log(
            "open_auction_buy",
            price=buy_px,
            size_yi=size_yi,
            window="%s-%s" % (buy_start, buy_end),
        )
        ok = _order_buy_limit(C, buy_px, now)
        if ok:
            A.buy_done_day = day
            _save_state()
        return

    # ---- 收盘：手动卖出提示；回测可选模拟 ----
    in_hint = _in_window(now_s, hint_start, hint_end)
    if in_hint and holding:
        if str(getattr(A, "sell_hint_day", "") or "") != day:
            A.sell_hint_day = day
            _save_state()
            mode = "小盘顶格" if small else "可确认收盘价"
            print(
                "%s MANUAL_SELL hint mode=%s price=%s size=%s亿 last=%.4f "
                "(实盘请手动挂卖，策略不下单)"
                % (STRATEGY_NAME, mode, hint_px, size_yi, last_px)
            )
            _event_log(
                "manual_sell_hint",
                mode=mode,
                price=hint_px,
                size_yi=size_yi,
                last=last_px,
            )

        if (
            bt
            and bool(globals().get("BACKTEST_SIM_SELL", True))
            and str(getattr(A, "sim_sell_day", "") or "") != day
            and hint_px is not None
        ):
            reason = "close_limit_up" if small else "close_confirm"
            if _cb_sim_sell(now, reason, float(hint_px)):
                A.sim_sell_day = day
                _save_state()
            return

# === cbauct/runtime.py ===
def init(C):
    A.busy = False
    A._hb_at = None
    try:
        _init_impl(C)
    except Exception as e:
        print("%s init error" % STRATEGY_NAME, e)
        _event_log("init_error", error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass


def _init_impl(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C, default="1m")
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
    A._diag = set()

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
            A.buy_done_day = ""
            A.sell_hint_day = ""
            A.sim_sell_day = ""
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
            if not hasattr(A, "buy_done_day"):
                A.buy_done_day = ""
            if not hasattr(A, "sell_hint_day"):
                A.sell_hint_day = ""
            if not hasattr(A, "sim_sell_day"):
                A.sim_sell_day = ""
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
        if not hasattr(A, "buy_done_day"):
            A.buy_done_day = ""
        if not hasattr(A, "sell_hint_day"):
            A.sell_hint_day = ""
        if not hasattr(A, "sim_sell_day"):
            A.sim_sell_day = ""

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)

    size_yi = _issue_size_yi()
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
        "lot=",
        LOT_SIZE,
        "open_buy=",
        OPEN_BUY_PRICE,
        "size_yi=",
        size_yi,
        "small=",
        _is_small_issue(),
        "buy_window=",
        "%s-%s" % (BUY_START, BUY_END),
        "sell=MANUAL",
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        budget=TRADE_BUDGET,
        size_yi=size_yi,
        small=_is_small_issue(),
        log_dir=str(globals().get("LOG_DIR") or ""),
    )


def handlebar(C):
    try:
        _refresh_mode(C)
        if getattr(A, "busy", False):
            return
        A.busy = True
        _handle(C)
    except Exception as e:
        print("%s handlebar error" % STRATEGY_NAME, e)
        _event_log("handlebar_error", error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        A.busy = False
