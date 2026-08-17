#coding:gbk
# 由 _deploy_qmt_gbk.py 自动生成；请勿手改。请编辑策略片段与 scripts/qmt_common/ 后重新部署。
import datetime
import json
import os
import traceback

import numpy as np


# === ma15/config.py ===
# True=只打日志不下单；回测/实盘真下单前务必确认
DRY_RUN = False

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 只交易此代码（主图须为 513530.SH）
TRADE_CODE = "513530"

# ETF T+0：回测不锁当日买入；实盘可卖以券商为准
ALLOW_T0 = True

TRADE_BUDGET = 50000.0
TRADE_BUDGET_BY_STOCK = {}
CASH_RATIO = 0.8

# ---- 15m / 1h 均线 ----
MA_FAST = 20
MA_SLOW = 60
H_MA_FAST = 20
H_MA_SLOW = 60
VOL_MA_N = 20

# 触线 / 未有效跌破（0.4%：ETF 1 跳约 0.001，0.2% 经常够不着）
MA_TOUCH_TOL = 0.004
MA_BREAK_TOL = 0.002

# 缩量：只比 20 均量（不再 AND 前波上涨量，否则多头里经常 vol_skip）
VOL_PULLBACK_RATIO = 0.85
VOL_UP_LOOKBACK = 8
VOL_UP_RATIO = 0.70

# 锤子：下影相对实体、实体占振幅上限
HAMMER_LOWER_MULT = 1.5
HAMMER_BODY_MAX = 0.50

# 大盘 15m 放量杀跌
INDEX_CODE = "000001.SH"
INDEX_DUMP_RET = -0.004
INDEX_DUMP_VOL = 1.5

# 卖出
STOP_MA_PCT = 0.008
STOP_MA_AFTER_HHMM = "1015"  # 早盘第一根不按隔夜缺口打 MA 止损
STOP_LOSS = 0.02
STALL_BARS = 16              # 约 1 个交易日；6 根=1.5h 会把回踩本身当成衰竭
STALL_BAND = 0.005
STALL_MA_FLAT = 0.002
STALL_ABORT_RET = 0.005      # 持仓期曾有 >=0.5% 浮盈则不再用 stall 砍
TREND_BREAK_ABORT_RET = 0.001  # 曾有 >=0.1% 浮盈则不用 trend_break（避免砍 7/16 这类回撤后再止盈）
TREND_BREAK_MIN_RET = -0.004   # 当前浮亏至少 0.4%，避免 4/17 那种 -0.06% 噪声
# 硬止盈：浮盈达标且离开 MA20。默认开（v1.0 关掉会少赚）
TAKE_PROFIT_HARD = True
TAKE_PROFIT = 0.015          # 回吐启动阈值（收盘最高浮盈）
TAKE_LEAVE = 0.008           # 仅 TAKE_PROFIT_HARD=True 时用
GIVEBACK = 0.008             # 启动后相对收盘最高回吐；硬止盈打开时作辅层
GIVEBACK_TIGHT = 0.008       # 最高浮盈达到 GIVEBACK_TIGHT_AFTER 后收紧
GIVEBACK_TIGHT_AFTER = 0.04

# 盈利后加仓：浮盈达到 SCALE_ARM 后，下一笔回踩信号加第二笔（仍 1*TRADE_BUDGET）
# 等加仓期间硬止盈让路（趋势仍在且未超过 SCALE_GIVEUP_BARS）；账户需能再拿出一笔预算
# 加仓成交后重置收盘最高：不继承第一笔峰值，否则均价下降会立刻触发整仓 giveback
SCALE_ENABLE = True
SCALE_MAX = 2
SCALE_ARM = 0.015
SCALE_GIVEUP_BARS = 80
SCALE_RESET_PEAK = True

# 允许开仓的 15m 结束时刻 HHmm。
# 不含 1400/1415：次根 1415/1430 成交，T+0 来不及当日止损，隔夜缺口（v0.3 的 1430 同因）
ENTRY_HHMM_ALLOW = (
    "1000", "1015", "1030", "1045", "1100", "1115", "1130",
    "1315", "1330", "1345",
)
# 这些结束时刻的 15m 不开新买（已挂 pending 也作废）
ENTRY_FILL_BAN = ("1415", "1430", "1445", "1500")

PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_allow_t0", "ALLOW_T0", "bool"),
    ("panel_ma_touch", "MA_TOUCH_TOL", "float"),
    ("panel_ma_break", "MA_BREAK_TOL", "float"),
    ("panel_vol_ratio", "VOL_PULLBACK_RATIO", "float"),
    ("panel_stop_ma", "STOP_MA_PCT", "float"),
    ("panel_stop_loss", "STOP_LOSS", "float"),
    ("panel_hard_tp", "TAKE_PROFIT_HARD", "bool"),
    ("panel_take_profit", "TAKE_PROFIT", "float"),
    ("panel_giveback", "GIVEBACK", "float"),
    ("panel_stall_bars", "STALL_BARS", "int"),
    ("panel_stall_abort", "STALL_ABORT_RET", "float"),
    ("panel_scale", "SCALE_ENABLE", "bool"),
)

PERIOD = "15m"
OHLC_COUNT = 400
HOUR_OHLC_COUNT = 240
INDEX_OHLC_COUNT = 120

LIVE_ONLY_LAST_BAR = True
DECISION_START = "093000"
DECISION_END = "150000"
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 400
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

STATE_FILE = r"D:\tradingStrategy\ma15_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "Ma15"
STRATEGY_VER = "v1.3"

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

# === ma15/state_extra.py ===
def _state_extra_load(raw):
    pe = raw.get("pending_entry")
    A.pending_entry = pe if isinstance(pe, dict) else None
    px = raw.get("pending_exit")
    A.pending_exit = px if isinstance(px, dict) else None
    peak = raw.get("hold_peak")
    try:
        A.hold_peak = float(peak) if peak is not None else None
    except Exception:
        A.hold_peak = None
    cp = raw.get("hold_close_peak")
    try:
        A.hold_close_peak = float(cp) if cp is not None else None
    except Exception:
        A.hold_close_peak = None
    try:
        A.hold_bars = int(raw.get("hold_bars", 0) or 0)
    except Exception:
        A.hold_bars = 0
    A._hold_count_bar = str(raw.get("hold_count_bar", "") or "")
    try:
        A.hold_max_ret = float(raw.get("hold_max_ret", 0) or 0)
    except Exception:
        A.hold_max_ret = 0.0
    A._eval_bar_tag = str(raw.get("eval_bar_tag", "") or "")
    A.stall_cool_day = str(raw.get("stall_cool_day", "") or "")


def _state_extra_save(data):
    data["pending_entry"] = getattr(A, "pending_entry", None)
    data["pending_exit"] = getattr(A, "pending_exit", None)
    peak = getattr(A, "hold_peak", None)
    data["hold_peak"] = None if peak is None else float(peak)
    cp = getattr(A, "hold_close_peak", None)
    data["hold_close_peak"] = None if cp is None else float(cp)
    data["hold_bars"] = int(getattr(A, "hold_bars", 0) or 0)
    data["hold_count_bar"] = str(getattr(A, "_hold_count_bar", "") or "")
    data["hold_max_ret"] = float(getattr(A, "hold_max_ret", 0) or 0)
    data["eval_bar_tag"] = str(getattr(A, "_eval_bar_tag", "") or "")
    data["stall_cool_day"] = str(getattr(A, "stall_cool_day", "") or "")

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
# 主要符号: _bt_held_*, _bt_locked_*, _bt_roll_t1, _allow_t0
# 说明: 仓位恢复（_bt_recover_*）由策略侧实现
# 策略可设 ALLOW_T0=True（ETF 等当日可卖）；默认 False 保持 T+1
def _allow_t0():
    return bool(globals().get("ALLOW_T0", False))


def _bt_held_vol():
    return max(0, int(getattr(A, "bt_held", 0) or 0))


def _bt_locked_vol():
    return max(0, int(getattr(A, "bt_locked", 0) or 0))


def _bt_available_vol():
    """回测可卖：T+1 为 held-locked；ALLOW_T0 时为 held。"""
    if _allow_t0():
        return _bt_held_vol()
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
    if _allow_t0():
        return
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

# === ma15/indicators.py ===
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


def _last_valid(arr, i=-1):
    if arr is None:
        return None
    v = arr[i]
    if v != v:
        return None
    return float(v)


def _is_hammer(o, h, l, c):
    rng = float(h) - float(l)
    if rng <= 0:
        return False
    body = abs(float(c) - float(o))
    lower = min(float(o), float(c)) - float(l)
    lower_mult = float(globals().get("HAMMER_LOWER_MULT") or 1.5)
    body_max = float(globals().get("HAMMER_BODY_MAX") or 0.50)
    if lower < lower_mult * body:
        return False
    if body / rng > body_max:
        return False
    if float(c) < float(o):
        return False
    return float(c) >= (float(h) + float(l)) / 2.0


def _is_bounce(o, h, l, c):
    """弱于锤子：收阳、有下影、收在区间上半（回踩确认，不要求 2 倍下影）。"""
    rng = float(h) - float(l)
    if rng <= 0:
        return False
    if float(c) < float(o):
        return False
    body = abs(float(c) - float(o))
    lower = min(float(o), float(c)) - float(l)
    if lower < max(body, rng * 0.20):
        return False
    if body / rng > 0.70:
        return False
    return float(c) >= (float(h) + float(l)) / 2.0


def _is_engulf(o0, c0, o1, c1, v0, v1):
    if float(c0) >= float(o0):
        return False
    if float(c1) <= float(o1):
        return False
    if float(c1) < float(o0):
        return False
    if float(o1) > float(c0):
        return False
    return float(v1) > float(v0)

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

# === ma15/market.py ===
def _get_ohlcv_period(C, stock, period, count, need, diag_key, end=None):
    if end is None:
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


def _get_ohlcv_15m(C, stock, end=None):
    need = max(int(MA_SLOW), int(VOL_MA_N), int(VOL_UP_LOOKBACK)) + 10
    return _get_ohlcv_period(
        C, stock, getattr(A, "period", "15m"), int(OHLC_COUNT), need, "m15", end=end
    )


def _get_ohlcv_1h(C, stock, end=None):
    need = int(H_MA_SLOW) + 10
    return _get_ohlcv_period(
        C, stock, "1h", int(HOUR_OHLC_COUNT), need, "h1", end=end
    )


def _get_ohlcv_index_15m(C, end=None):
    code = str(globals().get("INDEX_CODE") or "000001.SH")
    need = int(VOL_MA_N) + 5
    return _get_ohlcv_period(
        C, code, "15m", int(INDEX_OHLC_COUNT), need, "idx15", end=end
    )

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
    """DRY_RUN 可卖: 默认禁止同日历日卖出当日买入仓; ALLOW_T0 则放行。"""
    want = int(want)
    if want < 100:
        return 0
    if not _has_position():
        return 0
    if _allow_t0():
        return want
    ot = _parse_opened_at(A.position.get("opened_at"))
    if ot is not None and now is not None and ot.date() == now.date():
        return 0
    return want


def _max_sell_vol(now=None):
    """最多可卖股数; 默认 T+1, ALLOW_T0 时回测/DRY 不锁当日仓. skip 时调用方绝不清仓."""
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
# 预算: TRADE_BUDGET；可选 TRADE_BUDGET_BY_STOCK[A.stock]；可选 CASH_RATIO
# add=True: 已有仓上加仓并均价（默认 False，一票一仓）
def _trade_budget_cap():
    """单笔预算上限：优先 TRADE_BUDGET_BY_STOCK[A.stock]，否则 TRADE_BUDGET。"""
    stock = str(getattr(A, "stock", "") or "").strip()
    by_stock = globals().get("TRADE_BUDGET_BY_STOCK") or {}
    if stock and isinstance(by_stock, dict) and stock in by_stock:
        try:
            return float(by_stock[stock] or 0)
        except Exception:
            pass
    return float(globals().get("TRADE_BUDGET") or 0)


def _buy_budget(cash):
    budget = _trade_budget_cap()
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
    add = bool(extra.pop("add", False))
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    if add and _has_position():
        old_s = _pos_shares()
        old_px = _pos_cost_price()
        new_s = old_s + vol
        new_px = (old_s * old_px + vol * price) / float(new_s)
        pos = dict(A.position)
        pos["shares"] = int(new_s)
        pos["price"] = float(new_px)
        pos["cost"] = round(new_s * new_px, 2)
        pos["lots"] = int(pos.get("lots", 1) or 1) + 1
        A.position = pos
        A.acted.add("BUY")
        buy_day = ot[:8] if len(ot) >= 8 else None
        _bt_held_add(vol, buy_day=buy_day)
        _save_state()
        print(
            _strategy_tag(),
            "BUY add filled",
            {
                "add_shares": vol,
                "price": price,
                "lots": pos["lots"],
                "total": new_s,
                "avg": new_px,
            },
        )
        _event_log(
            "buy_add_filled",
            add_shares=vol,
            price=price,
            lots=pos["lots"],
            total=new_s,
            avg=new_px,
        )
        return
    pos = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
        "lots": 1,
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


def _order_buy(C, price, now, budget=None, add=False, **extra_pos):
    """提交买入. DRY 即时; 回测 passorder+即时; 实盘 pending 至成交.
    add=True 允许在已有仓上加仓（均价合并）；默认仍一票一仓。"""
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    holding_now = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= 100
    )
    if holding_now and not add:
        print(_strategy_tag(), "buy skip: already holding")
        _event_log("buy_skip", reason="already_holding")
        return False
    if add and not holding_now:
        add = False
    if (not add) and ("BUY" in getattr(A, "acted", set())):
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

    extra_pos = dict(extra_pos or {})
    if add:
        extra_pos["add"] = True
    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark("BUY", "ADD" if add else "BUY", vol)
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

# === ma15/strategy.py ===
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


def _stock_allowed():
    code = str(globals().get("TRADE_CODE") or "").strip()
    if not code:
        return True
    stock = str(getattr(A, "stock", "") or "")
    return stock.startswith(code)


def _in_entry_window(hhmm):
    allow = globals().get("ENTRY_HHMM_ALLOW") or ()
    return str(hhmm) in set([str(x) for x in allow])


def _entry_fill_banned(hhmm):
    ban = globals().get("ENTRY_FILL_BAN") or ()
    return str(hhmm) in set([str(x) for x in ban])


def _prev_15m_dt(dt):
    if dt is None:
        return None
    h = int(dt.hour)
    m = int(dt.minute)
    if h == 13 and m == 15:
        return dt.replace(hour=11, minute=30, second=0, microsecond=0)
    if h == 9 and m == 45:
        prev = dt - datetime.timedelta(days=1)
        return prev.replace(hour=15, minute=0, second=0, microsecond=0)
    return dt - datetime.timedelta(minutes=15)


def _drop_live_forming(C, now, bar_dt):
    if getattr(A, "is_backtest", False):
        return False
    try:
        if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
            return False
    except Exception:
        pass
    if now is None or bar_dt is None:
        return True
    return now < bar_dt


def _slice_ohlcv(opens, highs, lows, closes, vols):
    if closes is None or len(closes) < 2:
        return None
    return opens[:-1], highs[:-1], lows[:-1], closes[:-1], vols[:-1]


def _h1_ok(closes_h):
    ma_f = _sma(closes_h, H_MA_FAST)
    ma_s = _sma(closes_h, H_MA_SLOW)
    if ma_f is None or ma_s is None:
        return False, {}
    i = len(closes_h) - 1
    if i < 1:
        return False, {}
    f0 = _last_valid(ma_f, i)
    s0 = _last_valid(ma_s, i)
    f1 = _last_valid(ma_f, i - 1)
    detail = {"h_ma20": f0, "h_ma60": s0}
    if None in (f0, s0, f1):
        return False, detail
    ok = (f0 > s0) and (f0 >= f1)
    return ok, detail


def _trend_ok(closes):
    ma_f = _sma(closes, MA_FAST)
    ma_s = _sma(closes, MA_SLOW)
    if ma_f is None or ma_s is None:
        return False, None, None, {}
    i = len(closes) - 1
    if i < 1:
        return False, None, None, {}
    f0 = _last_valid(ma_f, i)
    s0 = _last_valid(ma_s, i)
    s1 = _last_valid(ma_s, i - 1)
    c0 = float(closes[i])
    detail = {"ma20": f0, "ma60": s0}
    if None in (f0, s0, s1):
        return False, ma_f, ma_s, detail
    ok = (f0 > s0) and (s0 >= s1) and (c0 > s0)
    return ok, ma_f, ma_s, detail


def _index_dump(opens, closes, vols):
    if not closes or len(closes) < int(VOL_MA_N):
        return True, "index_na_skip", {}
    i = len(closes) - 1
    o0 = float(opens[i])
    c0 = float(closes[i])
    v0 = float(vols[i])
    vm = _sma(vols, VOL_MA_N)
    vma = _last_valid(vm, i) if vm is not None else None
    detail = {"idx_ret": None if o0 <= 0 else (c0 - o0) / o0, "idx_vol": v0, "idx_mavol": vma}
    if o0 <= 0 or vma is None or vma <= 0:
        return True, "index_na_skip", detail
    ret = (c0 - o0) / o0
    dump = (ret <= float(INDEX_DUMP_RET)) and (v0 >= vma * float(INDEX_DUMP_VOL))
    if dump:
        return True, "index_dump_skip", detail
    return False, "", detail


def _vol_ok(closes, vols):
    i = len(closes) - 1
    v0 = float(vols[i])
    vm = _sma(vols, VOL_MA_N)
    vma = _last_valid(vm, i) if vm is not None else None
    if vma is None or vma <= 0:
        return False, {}
    if v0 >= vma * float(VOL_PULLBACK_RATIO):
        return False, {"mavol": vma, "vol": v0}
    return True, {"mavol": vma, "vol": v0}


def _eval_buy(opens, highs, lows, closes, vols, hhmm, h1_ok, idx_block, idx_why):
    reasons = []
    trend, ma20_arr, _ma60_arr, t_detail = _trend_ok(closes)
    detail = dict(t_detail)
    detail["trend_ok"] = trend
    if idx_block:
        return False, [idx_why or "index_na_skip"], detail
    if not h1_ok:
        return False, ["h1_skip"], detail
    if not trend:
        return False, ["trend_skip"], detail
    if not _in_entry_window(hhmm):
        return False, ["time_skip"], detail
    vok, v_detail = _vol_ok(closes, vols)
    detail.update(v_detail)
    if not vok:
        return False, ["vol_skip"], detail
    i = len(closes) - 1
    if i < 1:
        return False, ["short"], detail
    ma20 = _last_valid(ma20_arr, i)
    if ma20 is None or ma20 <= 0:
        return False, ["ma_na"], detail
    low = float(lows[i])
    close = float(closes[i])
    if low > ma20 * (1.0 + float(MA_TOUCH_TOL)):
        return False, ["touch_skip"], detail
    if close < ma20 * (1.0 - float(MA_BREAK_TOL)):
        return False, ["break_skip"], detail
    hammer = _is_hammer(opens[i], highs[i], lows[i], closes[i])
    bounce = _is_bounce(opens[i], highs[i], lows[i], closes[i])
    engulf = _is_engulf(
        opens[i - 1], closes[i - 1], opens[i], closes[i], vols[i - 1], vols[i]
    )
    if hammer:
        reasons.append("hammer")
    elif bounce:
        reasons.append("bounce")
    if engulf:
        reasons.append("engulf")
    if not reasons:
        return False, ["pattern_skip"], detail
    return True, reasons, detail


def _stall_hit(closes, ma20_arr, hold_bars, hold_max_ret):
    abort = float(globals().get("STALL_ABORT_RET") or 0)
    try:
        mx = float(hold_max_ret) if hold_max_ret is not None else 0.0
    except Exception:
        mx = 0.0
    if abort > 0 and mx >= abort:
        return False
    need = int(STALL_BARS)
    if hold_bars is None or int(hold_bars) < need:
        return False
    i = len(closes) - 1
    if i < need:
        return False
    ma_now = _last_valid(ma20_arr, i)
    ma_old = _last_valid(ma20_arr, i - need)
    if ma_now is None or ma_old is None or ma_now <= 0:
        return False
    band = float(STALL_BAND)
    for k in range(need):
        px = float(closes[i - k])
        ma = _last_valid(ma20_arr, i - k)
        if ma is None or ma <= 0:
            return False
        if abs(px - ma) / ma > band:
            return False
    flat = abs(ma_now - ma_old) / ma_now <= float(STALL_MA_FLAT)
    return flat


def _eval_sell(price, cost, close_peak, closes, ma20_arr, hold_bars, hhmm, hold_max_ret, trend_ok):
    reasons = []
    ma20 = _last_valid(ma20_arr, -1) if ma20_arr is not None else None
    stop_after = str(globals().get("STOP_MA_AFTER_HHMM") or "1015")
    if (
        ma20 is not None
        and ma20 > 0
        and str(hhmm) >= stop_after
        and price < ma20 * (1.0 - float(STOP_MA_PCT))
    ):
        reasons.append("stop_ma")
        return True, reasons
    if cost > 0 and price <= cost * (1.0 - float(STOP_LOSS)):
        reasons.append("stop_loss")
        return True, reasons
    try:
        mx = float(hold_max_ret) if hold_max_ret is not None else 0.0
    except Exception:
        mx = 0.0
    abort_tb = float(globals().get("TREND_BREAK_ABORT_RET") or 0.001)
    min_red = float(globals().get("TREND_BREAK_MIN_RET") or -0.004)
    cur_ret = (price - cost) / cost if cost > 0 else 0.0
    if (
        (not trend_ok)
        and cost > 0
        and cur_ret <= min_red
        and mx < abort_tb
        and str(hhmm) >= stop_after
    ):
        reasons.append("trend_break")
        return True, reasons
    if cost > 0:
        ret = (price - cost) / cost
        hard_tp = bool(globals().get("TAKE_PROFIT_HARD"))
        leave_ok = (ma20 is not None and ma20 > 0 and price >= ma20 * (1.0 + float(TAKE_LEAVE)))
        if hard_tp and ret >= float(TAKE_PROFIT) and leave_ok:
            wait_scale = False
            if bool(globals().get("SCALE_ENABLE")) and trend_ok:
                max_lots = int(globals().get("SCALE_MAX") or 1)
                giveup = int(globals().get("SCALE_GIVEUP_BARS") or 0)
                lots = 1
                pos = getattr(A, "position", None)
                if isinstance(pos, dict):
                    try:
                        lots = max(1, int(pos.get("lots", 1) or 1))
                    except Exception:
                        lots = 1
                arm = float(globals().get("SCALE_ARM") or TAKE_PROFIT)
                bars = int(hold_bars or 0)
                if lots < max_lots and mx >= arm and (giveup <= 0 or bars < giveup):
                    wait_scale = True
            if not wait_scale:
                reasons.append("take_profit")
                return True, reasons
    if close_peak is not None and cost > 0:
        pk = float(close_peak)
        peak_ret = (pk - float(cost)) / float(cost) if pk > 0 else 0.0
        arm = float(TAKE_PROFIT)
        if peak_ret >= arm and pk > 0:
            gb = float(GIVEBACK)
            tight_after = float(globals().get("GIVEBACK_TIGHT_AFTER") or 0)
            tight = float(globals().get("GIVEBACK_TIGHT") or 0)
            if tight_after > 0 and tight > 0 and peak_ret >= tight_after:
                gb = tight
            if (pk - price) / pk >= gb:
                reasons.append("giveback")
                return True, reasons
    if _stall_hit(closes, ma20_arr, hold_bars, hold_max_ret):
        reasons.append("stall")
        return True, reasons
    return False, reasons


def _clear_hold_meta():
    A.hold_peak = None
    A.hold_close_peak = None
    A.hold_max_ret = 0.0
    A.hold_bars = 0
    A._hold_count_bar = ""


def _bump_hold_bars(bar_tag):
    if getattr(A, "_hold_count_bar", "") == bar_tag:
        return
    A.hold_bars = int(getattr(A, "hold_bars", 0) or 0) + 1
    A._hold_count_bar = bar_tag


def _update_peaks(high_px, close_px, cost):
    hi = float(high_px)
    cl = float(close_px)
    changed = False
    peak = getattr(A, "hold_peak", None)
    if peak is None:
        base = float(cost) if cost and cost > 0 else hi
        A.hold_peak = max(base, hi)
        changed = True
    elif hi > float(peak):
        A.hold_peak = hi
        changed = True
    cp = getattr(A, "hold_close_peak", None)
    if cp is None:
        A.hold_close_peak = cl
        changed = True
    elif cl > float(cp):
        A.hold_close_peak = cl
        changed = True
    if cost and float(cost) > 0:
        r_cl = (cl - float(cost)) / float(cost)
        r_hi = (hi - float(cost)) / float(cost)
        mx = max(r_cl, r_hi)
        prev = getattr(A, "hold_max_ret", None)
        try:
            prev_f = float(prev) if prev is not None else None
        except Exception:
            prev_f = None
        if prev_f is None or mx > prev_f:
            A.hold_max_ret = mx
            changed = True
    return changed


def _pos_lots():
    pos = getattr(A, "position", None)
    if not isinstance(pos, dict):
        return 0
    try:
        return max(1, int(pos.get("lots", 1) or 1))
    except Exception:
        return 1


def _scale_ready():
    if not bool(globals().get("SCALE_ENABLE")):
        return False
    holding_now = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= 100
    )
    if not holding_now:
        return False
    if _pos_lots() >= int(globals().get("SCALE_MAX") or 1):
        return False
    try:
        mx = float(getattr(A, "hold_max_ret", 0) or 0)
    except Exception:
        mx = 0.0
    arm = float(globals().get("SCALE_ARM") or 0)
    if arm <= 0:
        arm = float(TAKE_PROFIT)
    return mx >= arm


def _pending_ready(pend, day, exec_tag):
    if not isinstance(pend, dict):
        return False
    sig_tag = str(pend.get("signal_tag", "") or "")
    if sig_tag and exec_tag:
        return sig_tag < exec_tag
    sig_day = str(pend.get("signal_day", "") or "")
    return bool(sig_day) and sig_day < day


def _reset_peaks_after_scale(px):
    """加仓后回吐从新高起算，不把第一笔收盘最高带到更低均价上。"""
    if not bool(globals().get("SCALE_RESET_PEAK", True)):
        return
    try:
        pxf = float(px) if px else 0.0
    except Exception:
        pxf = 0.0
    if pxf <= 0:
        return
    A.hold_peak = pxf
    A.hold_close_peak = pxf
    cost = _pos_cost_price()
    try:
        cost_f = float(cost) if cost else 0.0
    except Exception:
        cost_f = 0.0
    prev = float(getattr(A, "hold_max_ret", 0) or 0)
    if cost_f > 0:
        A.hold_max_ret = max(prev, (pxf - cost_f) / cost_f)
    print(
        "%s scale peak reset px=%.4f avg=%.4f max_ret=%.2f%%"
        % (STRATEGY_NAME, pxf, cost_f, float(A.hold_max_ret) * 100.0)
    )
    _event_log("scale_peak_reset", px=pxf, avg=cost_f, max_ret=A.hold_max_ret)


def _after_signal_buy_filled(px, day, add=False):
    A.pending_entry = None
    A.pending_exit = None
    if add:
        _reset_peaks_after_scale(px)
        _save_state()
        return
    try:
        A.hold_peak = float(px) if px else None
    except Exception:
        A.hold_peak = None
    A.hold_close_peak = A.hold_peak
    A.hold_max_ret = 0.0
    A.hold_bars = 0
    A._hold_count_bar = ""
    _save_state()


def _after_signal_sell_filled():
    A.pending_exit = None
    A.pending_entry = None
    _clear_hold_meta()
    acted = getattr(A, "acted", None)
    if isinstance(acted, set):
        acted.discard("BUY")
        acted.discard("SELL")
    _save_state()


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)
    ot = str(pend.get("opened_at") or pend.get("submitted_at") or "")
    day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
    _after_signal_buy_filled(px, day, add=bool(extra.get("add")))


def _pending_on_sell_fill(pend, now, vol, px):
    intent = str(pend.get("intent", "") or "")
    last_hint = pend.get("last_hint")
    if last_hint is None:
        last_hint = px
    mark_half = bool(pend.get("mark_half"))
    _apply_sell_fill(now, intent, last_hint, vol, mark_half=mark_half)
    if not _has_position() and not (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= 100
    ):
        _after_signal_sell_filled()
    else:
        A.pending_exit = None
        _save_state()


def _on_signal_order_ok(side, px=None, day=None, add=False):
    live_waiting = (not getattr(A, "is_backtest", False)) and (
        not DRY_RUN
    ) and isinstance(getattr(A, "pending", None), dict)
    if live_waiting:
        print("%s %s submitted keep signal pending until fill" % (STRATEGY_NAME, side))
        _event_log("signal_pending_keep_until_fill", side=side)
        _save_state()
        return
    if side == "buy":
        _after_signal_buy_filled(px, day, add=add)
    else:
        _after_signal_sell_filled()


_SELL_LABELS = {
    "stop_ma": "MA20硬止损",
    "stop_loss": "成本止损",
    "trend_break": "15m趋势破坏",
    "stall": "贴线动能衰竭",
    "take_profit": "浮盈止盈",
    "giveback": "收盘最高回吐",
}
_BUY_LABELS = {
    "hammer": "长脚十字/假阴护盘",
    "bounce": "回踩收阳",
    "engulf": "放量反包",
    "time_skip": "时段过滤",
    "vol_skip": "缩量未达标",
    "h1_skip": "小时趋势未向上",
    "trend_skip": "15m非多头排列",
    "index_dump_skip": "大盘放量杀跌",
    "index_na_skip": "指数数据缺失",
    "touch_skip": "未触及MA20",
    "break_skip": "收盘有效跌破MA20",
    "pattern_skip": "无锤子/回踩阳/反包",
    "entry_expire": "买入pending隔日作废",
    "entry_late_skip": "尾盘不买",
}


def _reason_label(code, kind="sell"):
    code = str(code or "")
    table = _SELL_LABELS if kind == "sell" else _BUY_LABELS
    return table.get(code, code)


def _format_reasons(codes, kind="sell"):
    codes = [str(x) for x in (codes or []) if x]
    if not codes:
        return "-"
    return ",".join(["%s(%s)" % (c, _reason_label(c, kind)) for c in codes])


def _mark_eval(tag):
    A._eval_bar_tag = str(tag or "")
    _save_state()


def _should_log_bar(C, now, force):
    if force:
        return True
    if getattr(A, "is_backtest", False):
        try:
            return int(getattr(C, "barpos", 0) or 0) % 16 == 0
        except Exception:
            return True
    sec = int(globals().get("LIVE_HEARTBEAT_SEC") or 60)
    last = getattr(A, "_bar_status_at", None)
    if last is not None and now is not None and sec > 0:
        try:
            if (now - last).total_seconds() < float(sec):
                return False
        except Exception:
            pass
    return True


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)

    if not _stock_allowed():
        _diag_once("stock_skip", "want=", TRADE_CODE, "got=", getattr(A, "stock", ""))
        return

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
        _live_heartbeat("session")
    else:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    ohlcv = _get_ohlcv_15m(C, A.stock)
    if ohlcv is None:
        _live_heartbeat("ohlcv_15m_none")
        return
    opens, highs, lows, closes, vols = ohlcv
    exec_open = float(opens[-1])
    exec_tag = tag
    drop = _drop_live_forming(C, now, bar_dt)
    if drop:
        sliced = _slice_ohlcv(opens, highs, lows, closes, vols)
        if sliced is None:
            _live_heartbeat("ohlcv_forming_short")
            return
        opens, highs, lows, closes, vols = sliced
        complete_dt = _prev_15m_dt(bar_dt)
    else:
        complete_dt = bar_dt
    complete_tag = _bar_tag(complete_dt)
    sig_hhmm = _bar_hhmm(complete_dt)
    sig_day = complete_dt.strftime("%Y%m%d") if complete_dt else day
    end_sig = complete_dt.strftime("%Y%m%d%H%M%S") if complete_dt else None

    if len(closes) < max(int(MA_SLOW), 80):
        _diag_once("m15_short", "n=", len(closes))
        return

    ohlcv_h = _get_ohlcv_1h(C, A.stock, end=end_sig)
    if ohlcv_h is None:
        _live_heartbeat("ohlcv_1h_none")
        return
    _oh, _hh, _lh, closes_h, _vh = ohlcv_h
    if drop and closes_h is not None and len(closes_h) >= 2:
        closes_h = list(closes_h[:-1])
    if closes_h is None or len(closes_h) < int(H_MA_SLOW) + 2:
        _diag_once("h1_short", "n=", 0 if not closes_h else len(closes_h))
        return

    idx = _get_ohlcv_index_15m(C, end=end_sig)
    idx_block = False
    idx_why = ""
    idx_detail = {}
    if idx is None:
        idx_block = True
        idx_why = "index_na_skip"
    else:
        io, _ih, _il, ic, iv = idx
        if drop and ic is not None and len(ic) >= 2:
            io, ic, iv = io[:-1], ic[:-1], iv[:-1]
        idx_block, idx_why, idx_detail = _index_dump(io, ic, iv)

    price = float(closes[-1])
    high_px = float(highs[-1])
    if bt:
        _bt_recover_position(now=now, last=price)

    h1_ok, h_detail = _h1_ok(closes_h)
    buy_ok, buy_reasons, b_detail = _eval_buy(
        opens, highs, lows, closes, vols, sig_hhmm, h1_ok, idx_block, idx_why
    )
    ma20_arr = _sma(closes, MA_FAST)

    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    cost = _pos_cost_price()
    if not holding:
        if (
            getattr(A, "hold_peak", None) is not None
            or getattr(A, "hold_close_peak", None) is not None
            or int(getattr(A, "hold_bars", 0) or 0)
            or float(getattr(A, "hold_max_ret", 0) or 0)
        ):
            _clear_hold_meta()
    else:
        _bump_hold_bars(complete_tag)
        if _update_peaks(high_px, price, cost):
            _save_state()

    sell_ok, sell_reasons = False, []
    if holding:
        sell_ok, sell_reasons = _eval_sell(
            price,
            cost,
            getattr(A, "hold_close_peak", None),
            closes,
            ma20_arr,
            getattr(A, "hold_bars", 0),
            sig_hhmm,
            getattr(A, "hold_max_ret", 0),
            bool(b_detail.get("trend_ok")),
        )

    skip_codes = (
        "time_skip",
        "vol_skip",
        "h1_skip",
        "trend_skip",
        "index_dump_skip",
        "index_na_skip",
        "touch_skip",
        "break_skip",
        "pattern_skip",
        "ma_na",
        "short",
    )
    real_buys = [r for r in buy_reasons if r not in skip_codes]
    buy_sig = bool(real_buys)

    pe_now = bool(getattr(A, "pending_entry", None))
    px_now = bool(getattr(A, "pending_exit", None))
    ret_pct = None
    if holding and cost > 0:
        ret_pct = (price - cost) / cost
    if _should_log_bar(C, now, bool(buy_sig or sell_ok)):
        if not bt:
            A._bar_status_at = now
        print(
            "%s" % STRATEGY_NAME,
            day,
            sig_hhmm,
            "n15=%d n1h=%d close=%.4f drop=%s "
            "h1=%s buy=%s buyR=%s sell=%s sellR=%s hold=%s ret=%s pe=%s px=%s"
            % (
                len(closes),
                len(closes_h),
                price,
                drop,
                h1_ok,
                buy_sig,
                ",".join(buy_reasons) if buy_reasons else "-",
                sell_ok,
                ",".join(sell_reasons) if sell_reasons else "-",
                holding,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                pe_now,
                px_now,
            ),
        )
        _bar_log(
            day=day,
            hhmm=sig_hhmm,
            n15=len(closes),
            n1h=len(closes_h),
            close=round(price, 6),
            drop=drop,
            h1=h1_ok,
            buy=buy_sig,
            buyR=",".join(buy_reasons) if buy_reasons else "-",
            sell=sell_ok,
            sellR=",".join(sell_reasons) if sell_reasons else "-",
            hold=holding,
            ret=None if ret_pct is None else round(ret_pct * 100.0, 4),
            pe=pe_now,
            px=px_now,
            idx=idx_why or "-",
            ma20=None if b_detail.get("ma20") is None else round(b_detail["ma20"], 4),
            h_ma20=None if h_detail.get("h_ma20") is None else round(h_detail["h_ma20"], 4),
        )

    pe_entry = getattr(A, "pending_entry", None)
    if isinstance(pe_entry, dict):
        sig_d = str(pe_entry.get("signal_day", "") or "")
        if sig_d and sig_d < day:
            A.pending_entry = None
            _save_state()
            print("%s pending_entry cancel entry_expire signal_day=%s" % (STRATEGY_NAME, sig_d))
            _event_log("pending_entry_cancel", reason="entry_expire", signal_day=sig_d)
            pe_entry = None

    pe_exit = getattr(A, "pending_exit", None)
    if holding and isinstance(pe_exit, dict) and _pending_ready(pe_exit, day, exec_tag):
        reason = str(pe_exit.get("reason", "SELL") or "SELL")
        reasons = pe_exit.get("reasons") or [reason]
        print(
            "%s SELL by signal=%s label=%s all=%s signal_day=%s signal_tag=%s @open=%.4f"
            % (
                STRATEGY_NAME,
                reason,
                _reason_label(reason, "sell"),
                _format_reasons(reasons, "sell"),
                pe_exit.get("signal_day"),
                pe_exit.get("signal_tag"),
                exec_open,
            )
        )
        _event_log(
            "sell_by_signal",
            signal=reason,
            signal_tag=pe_exit.get("signal_tag"),
            open=exec_open,
        )
        ok = _order_sell(C, reason, exec_open, now)
        if ok:
            _on_signal_order_ok("sell")
        else:
            print("%s pending_exit keep after sell fail/skip signal=%s" % (STRATEGY_NAME, reason))
            _event_log("pending_exit_keep_after_fail", sell_reason=reason)
        return

    pe_entry = getattr(A, "pending_entry", None)
    exec_hhmm = _bar_hhmm(bar_dt)
    pe_is_add = isinstance(pe_entry, dict) and bool(pe_entry.get("add"))
    if (
        ((not holding) or pe_is_add)
        and isinstance(pe_entry, dict)
        and _pending_ready(pe_entry, day, exec_tag)
        and _entry_fill_banned(exec_hhmm)
    ):
        A.pending_entry = None
        _save_state()
        print(
            "%s pending_entry cancel entry_late_skip hhmm=%s signal_day=%s"
            % (STRATEGY_NAME, exec_hhmm, pe_entry.get("signal_day"))
        )
        _event_log(
            "pending_entry_cancel",
            reason="entry_late_skip",
            hhmm=exec_hhmm,
            signal_day=pe_entry.get("signal_day"),
        )
        return

    pe_entry = getattr(A, "pending_entry", None)
    pe_is_add = isinstance(pe_entry, dict) and bool(pe_entry.get("add"))
    if (
        ((not holding) or pe_is_add)
        and isinstance(pe_entry, dict)
        and _pending_ready(pe_entry, day, exec_tag)
    ):
        if pe_is_add and not holding:
            A.pending_entry = None
            _save_state()
            print("%s pending_entry cancel add_no_pos" % STRATEGY_NAME)
            _event_log("pending_entry_cancel", reason="add_no_pos")
            return
        reasons = pe_entry.get("reasons") or []
        primary = reasons[0] if reasons else "entry"
        kind = "add" if pe_is_add else "buy"
        print(
            "%s %s by signal=%s label=%s all=%s signal_day=%s signal_tag=%s @open=%.4f"
            % (
                STRATEGY_NAME,
                "BUY add" if pe_is_add else "BUY",
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(reasons, "buy"),
                pe_entry.get("signal_day"),
                pe_entry.get("signal_tag"),
                exec_open,
            )
        )
        _event_log(
            "buy_by_signal" if not pe_is_add else "buy_add_by_signal",
            signal=primary,
            signal_tag=pe_entry.get("signal_tag"),
            open=exec_open,
            add=pe_is_add,
        )
        budget = _buy_budget(cash)
        ok = _order_buy(C, exec_open, now, budget, add=pe_is_add)
        if ok:
            _on_signal_order_ok("buy", px=exec_open, day=day, add=pe_is_add)
        else:
            print(
                "%s pending_entry keep after %s fail/skip signal=%s"
                % (STRATEGY_NAME, kind, primary)
            )
            _event_log("pending_entry_keep_after_fail", signal=primary, add=pe_is_add)
        return

    if str(getattr(A, "_eval_bar_tag", "") or "") == complete_tag:
        return

    if holding:
        if sell_ok:
            if isinstance(getattr(A, "pending_exit", None), dict):
                _mark_eval(complete_tag)
                return
            reason = sell_reasons[0] if sell_reasons else "SELL"
            A.pending_exit = {
                "reason": reason,
                "signal_day": sig_day,
                "signal_tag": complete_tag,
                "close": price,
                "reasons": list(sell_reasons),
            }
            A.pending_entry = None
            _mark_eval(complete_tag)
            print(
                "%s pending_exit set signal=%s label=%s all=%s tag=%s close=%.4f"
                % (
                    STRATEGY_NAME,
                    reason,
                    _reason_label(reason, "sell"),
                    _format_reasons(sell_reasons, "sell"),
                    complete_tag,
                    price,
                )
            )
            _event_log(
                "pending_exit_set",
                signal=reason,
                signal_tag=complete_tag,
                close=price,
            )
        elif buy_sig and _scale_ready():
            if isinstance(getattr(A, "pending_entry", None), dict):
                _mark_eval(complete_tag)
                return
            A.pending_entry = {
                "signal_day": sig_day,
                "signal_tag": complete_tag,
                "close": price,
                "reasons": list(real_buys),
                "add": True,
            }
            A.pending_exit = None
            _mark_eval(complete_tag)
            primary = real_buys[0] if real_buys else "entry"
            print(
                "%s pending_entry set add signal=%s label=%s all=%s tag=%s close=%.4f lots=%s"
                % (
                    STRATEGY_NAME,
                    primary,
                    _reason_label(primary, "buy"),
                    _format_reasons(real_buys, "buy"),
                    complete_tag,
                    price,
                    _pos_lots(),
                )
            )
            _event_log(
                "pending_entry_set",
                signal=primary,
                signal_tag=complete_tag,
                close=price,
                add=True,
            )
        else:
            _mark_eval(complete_tag)
        return

    if buy_sig:
        if isinstance(getattr(A, "pending_entry", None), dict):
            _mark_eval(complete_tag)
            return
        A.pending_entry = {
            "signal_day": sig_day,
            "signal_tag": complete_tag,
            "close": price,
            "reasons": list(real_buys),
        }
        A.pending_exit = None
        _mark_eval(complete_tag)
        primary = real_buys[0] if real_buys else "entry"
        print(
            "%s pending_entry set signal=%s label=%s all=%s tag=%s close=%.4f"
            % (
                STRATEGY_NAME,
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(real_buys, "buy"),
                complete_tag,
                price,
            )
        )
        _event_log(
            "pending_entry_set",
            signal=primary,
            signal_tag=complete_tag,
            close=price,
        )
    else:
        _mark_eval(complete_tag)

# === ma15/runtime.py ===
def _as_bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y", "是")


def _apply_panel():
    """策略交易注入 bind → 写回 config 全局。须由 init() 直接调用。"""
    g = globals()
    names = dict(g)
    try:
        fr = __import__("sys")._getframe(1)
        for _ in range(3):
            if fr is None:
                break
            names.update(fr.f_globals)
            names.update(fr.f_locals)
            fr = fr.f_back
    except Exception:
        pass
    applied = []
    for bind, const, kind in (g.get("PANEL_BINDS") or ()):
        if bind not in names:
            continue
        val = names[bind]
        cur = g.get(const)
        if kind == "bool":
            new = _as_bool(val)
        elif kind == "int":
            new = int(float(val))
        elif kind == "float":
            new = float(val)
        else:
            new = str(val)
        g[const] = new
        applied.append(const)
        if new != cur:
            print(_strategy_tag(), "panel", const, cur, "->", new)
        if const == "TRADE_BUDGET":
            g["TRADE_BUDGET_BY_STOCK"] = {}
    if applied:
        g["_PANEL_APPLIED"] = set(applied)
        print(_strategy_tag(), "panel applied", ",".join(applied))


def init(C):
    A.busy = False
    A._hb_at = None
    try:
        _apply_panel()
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
    A.period = _resolve_period(C, default="15m")
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
    idx = str(globals().get("INDEX_CODE") or "000001.SH")
    if do_dl:
        try:
            _download_hist(A.stock, A.period)
            _download_hist(A.stock, "1h")
            _download_hist(idx, "15m")
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, A.period, "+1h +index")

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
            A.hold_peak = None
            A.hold_close_peak = None
            A.hold_max_ret = 0.0
            A.hold_bars = 0
            A._hold_count_bar = ""
            A._eval_bar_tag = ""
            A.stall_cool_day = ""
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
            if not hasattr(A, "pending_entry"):
                A.pending_entry = None
            if not hasattr(A, "pending_exit"):
                A.pending_exit = None
            if not hasattr(A, "hold_peak"):
                A.hold_peak = None
            if not hasattr(A, "hold_close_peak"):
                A.hold_close_peak = None
            if not hasattr(A, "hold_max_ret"):
                A.hold_max_ret = 0.0
            if not hasattr(A, "hold_bars"):
                A.hold_bars = 0
            if not hasattr(A, "_hold_count_bar"):
                A._hold_count_bar = ""
            if not hasattr(A, "_eval_bar_tag"):
                A._eval_bar_tag = ""
            if not hasattr(A, "stall_cool_day"):
                A.stall_cool_day = ""
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
        if not hasattr(A, "hold_peak"):
            A.hold_peak = None
        if not hasattr(A, "hold_close_peak"):
            A.hold_close_peak = None
        if not hasattr(A, "hold_max_ret"):
            A.hold_max_ret = 0.0
        if not hasattr(A, "hold_bars"):
            A.hold_bars = 0
        if not hasattr(A, "_hold_count_bar"):
            A._hold_count_bar = ""
        if not hasattr(A, "_eval_bar_tag"):
            A._eval_bar_tag = ""
        if not hasattr(A, "stall_cool_day"):
            A.stall_cool_day = ""

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
        "ALLOW_T0=",
        ALLOW_T0,
        "budget=",
        _trade_budget_cap(),
        "dMA=",
        "%d/%d" % (MA_FAST, MA_SLOW),
        "hMA=",
        "%d/%d" % (H_MA_FAST, H_MA_SLOW),
        "stop_ma=",
        STOP_MA_PCT,
        "hard_tp=",
        TAKE_PROFIT_HARD,
        "take=",
        TAKE_PROFIT,
        "giveback=",
        GIVEBACK,
        "scale=",
        SCALE_ENABLE,
        "scale_reset_peak=",
        SCALE_RESET_PEAK,
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        allow_t0=ALLOW_T0,
        budget=_trade_budget_cap(),
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
