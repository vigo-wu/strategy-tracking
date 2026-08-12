#coding:gbk
# 由 _deploy_qmt_gbk.py 自动生成；请勿手改。请编辑策略片段与 scripts/qmt_common/ 后重新部署。
import datetime
import json
import os
import traceback

import numpy as np


# === pbs/config.py ===
# ===================== 用户配置 =====================
DRY_RUN = False

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

TRADE_BUDGET = 10000.0
CASH_RATIO = 0.8
LOT_SIZE = 10  # 可转债：10 张 = 一手

# ---- 价格锚点（发行价=100，见 model.md / docs）----
ISSUE_PRICE = 100.0
HALT_BASE_PRICE = 130.0       # 30% 临停基准（人工开盘参考）
CAGE_RATIO = 1.1              # 状态日志笼子参考
REOPEN_CAP_PRICE = 143.0      # 130 * 1.1；状态日志参考
LIMIT_UP_PRICE = 157.30       # 首日涨幅 57.3% / 收盘申报价
LIMIT_DOWN_PRICE = 56.70
PRICE_DECIMALS = 3

# ---- 模式开关（仅买入）----
# 开盘/隔夜 130 由人工委托；本策略只跑尾盘 Mode B
ENABLE_MODE_B = True

# ---- 时窗（HHmmss）----
# 14:57 起直接以涨停顶格申报，失败则持续重试直至申报成功
CLOSE_BUY_START = "145700"
CLOSE_BUY_END = "145955"
# None = 用 LIMIT_UP_PRICE
CLOSE_BUY_PRICE = None

# pending：收盘申报意图不短超时自动撤
PENDING_TIMEOUT_EXEMPT_INTENTS = (
    "SZ_CLOSE",
    "SH_CLOSE",
)
PENDING_TIMEOUT_EXEMPT_LOG_SEC = 300
PENDING_TIMEOUT_SEC = 90
PENDING_ORPHAN_SEC = 15
CANCEL_RETRY_SEC = 1.0
# passorder 后以柜台见单为委托成功；长期未见单则间隔命中 + 二次查委托后强清重挂
PENDING_SHADOW_CLEAR_SEC = 3.0
PENDING_SHADOW_CLEAR_HITS = 3
PENDING_SHADOW_CLEAR_HIT_GAP_MS = 1000.0
PENDING_SHADOW_REORDER_COOLDOWN_MS = 2000.0
PENDING_SHADOW_CLEAR_INTENTS = (
    "SZ_CLOSE",
    "SH_CLOSE",
)
# pending_check 日志节流（显式配置才生效；查单仍 50ms）
PENDING_CHECK_LOG_SEC = 5.0

# ---- 上市首日门闩 ----
# 实盘务必填写 LISTING_DATE_MAP，否则首日门闩可能 fail-closed
LISTING_DAY_ONLY = True
LISTING_DAY_FAIL_OPEN = False
LISTING_DATE_MAP = {
    "110103.SH": "20260813",
}

# ---- 行情与运行 ----
# 实盘/回测统一：主图挂「分笔/tick」
PERIOD = "tick"
OHLC_COUNT = 300
LIVE_ONLY_LAST_BAR = False
LIVE_HEARTBEAT_SEC = 60
HIST_MAX_LOOKBACK_DAYS = 5
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True
TICK_ALLOW_1M_FALLBACK = False

# ---- 实盘定时器（收盘申报准点；回测无效）----
# True=init 注册 run_time；与分笔 handlebar 双驱动，busy 防重入
ENABLE_LIVE_TIMER = True
LIVE_TIMER_MS = 50                  # 收盘重试；建议 50–100
TIMER_QUICK_TRADE = 2               # 定时器内 passorder 立即报单
TICK_QUICK_TRADE = 1                # 分笔 handlebar 内报单
# 日志墙钟节流（定时器 50ms 下禁用 barpos%N 抽样）
# 14:57 前默认静默（无状态行/心跳/skip 刷屏）；收盘窗内才按下列间隔打日志
LOG_STATUS_SEC = 10.0               # 收盘窗内：状态行 / bars.jsonl
LOG_WAIT_SEC = 5.0                  # 收盘窗内：申报重试 / buy_skip / passorder_fail 节流

STATE_FILE = r"D:\tradingStrategy\pbs_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "PbsRush"
STRATEGY_VER = "v1.18"

DRY_RUN_FILL_IMMEDIATE = False
DRY_RUN_FILL_ON_LIMIT = True
DRY_RUN_VIRTUAL_CASH = True
DRY_RUN_VIRTUAL_CASH_AMT = 100000.0
DRY_RUN_SAVE_STATE = False
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "tick",
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
    "tick": 500,
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
    "tick": "20240101",
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
        "fenbi": "tick",
        "tickline": "tick",
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
    if p == "tick":
        return True
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

# === pbs/state_extra.py ===
def _state_extra_load(raw):
    A.buy_done_day = str(raw.get("buy_done_day", "") or "")
    A.entry_mode = str(raw.get("entry_mode", "") or "")


def _state_extra_save(data):
    data["buy_done_day"] = str(getattr(A, "buy_done_day", "") or "")
    data["entry_mode"] = str(getattr(A, "entry_mode", "") or "")

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
    lot = int(globals().get("LOT_SIZE") or 100)
    if lot <= 0:
        lot = 100
    if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= lot:
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
    # 历史 DRY 虚拟单不得带入实盘
    if isinstance(A.pending, dict) and A.pending.get("dry_keep"):
        print(_strategy_tag(), "state drop dry_keep pending")
        _event_log("state_drop_dry_pending", remark=A.pending.get("remark"))
        A.pending = None
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
    # DRY_RUN 且策略显式关闭落盘时跳过（cbauct: DRY_RUN_SAVE_STATE=False）
    if DRY_RUN and (not bool(globals().get("DRY_RUN_SAVE_STATE", True))):
        return
    path = _state_path()
    if not path:
        return
    pend = getattr(A, "pending", None)
    if isinstance(pend, dict) and pend.get("dry_keep"):
        pend = None
    data = {
        "stock": getattr(A, "stock", ""),
        "version": str(globals().get("STRATEGY_VER") or ""),
        "position": getattr(A, "position", None),
        "acted_day": getattr(A, "acted_day", ""),
        "acted": sorted(list(getattr(A, "acted", set()) or [])),
        "pending": pend,
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

# === pbs/indicators.py ===
def _bar_hhmmss(dt):
    if dt is None:
        return "000000"
    return dt.strftime("%H%M%S")


def _bar_tag(dt):
    if dt is None:
        return ""
    return dt.strftime("%Y%m%d%H%M%S")


def _cb_code_num():
    stock = str(getattr(A, "stock", "") or "")
    code = stock.split(".")[0] if stock else ""
    try:
        return int(code)
    except Exception:
        return 0


def _is_sz_cb():
    stock = str(getattr(A, "stock", "") or "").upper()
    if stock.endswith(".SZ"):
        return True
    n = _cb_code_num()
    return 120000 <= n <= 129999


def _is_sh_cb():
    stock = str(getattr(A, "stock", "") or "").upper()
    if stock.endswith(".SH"):
        return True
    n = _cb_code_num()
    return 110000 <= n <= 119999


def _market_tag():
    if _is_sz_cb():
        return "SZ"
    if _is_sh_cb():
        return "SH"
    return "UNK"


def _px_round(price):
    dec = int(globals().get("PRICE_DECIMALS") or 3)
    try:
        return round(float(price), dec)
    except Exception:
        return 0.0


def _reopen_cap():
    cfg = globals().get("REOPEN_CAP_PRICE")
    if cfg is not None:
        try:
            v = float(cfg)
            if v > 0:
                return _px_round(v)
        except Exception:
            pass
    base = float(globals().get("HALT_BASE_PRICE") or 130.0)
    ratio = float(globals().get("CAGE_RATIO") or 1.1)
    return _px_round(base * ratio)


def _limit_up():
    return _px_round(globals().get("LIMIT_UP_PRICE") or 157.30)


def _cage_cap_from_last(last_px):
    """深市：最近成交价 * CAGE_RATIO，封顶全日涨停。"""
    try:
        last = float(last_px)
    except Exception:
        last = 0.0
    if last <= 0:
        return _reopen_cap()
    ratio = float(globals().get("CAGE_RATIO") or 1.1)
    return _px_round(min(last * ratio, _limit_up()))


def _tick_quote(C):
    """实盘全推：返回 (last, ask1, bid1)；回测禁用 tick。"""
    if getattr(A, "is_backtest", False):
        return 0.0, 0.0, 0.0
    stock = str(getattr(A, "stock", "") or "")
    try:
        fn = getattr(C, "get_full_tick", None)
        if not callable(fn):
            return 0.0, 0.0, 0.0
        ticks = fn([stock])
        if not (isinstance(ticks, dict) and stock in ticks):
            return 0.0, 0.0, 0.0
        t = ticks[stock]

        def _get(obj, *keys):
            for k in keys:
                if isinstance(obj, dict) and obj.get(k) is not None:
                    try:
                        v = float(obj[k])
                        if v > 0:
                            return v
                    except Exception:
                        pass
                if hasattr(obj, k):
                    try:
                        v = float(getattr(obj, k))
                        if v > 0:
                            return v
                    except Exception:
                        pass
            return 0.0

        last = _get(t, "lastPrice", "price", "last", "match")
        ask1 = _get(t, "askPrice1", "ask1", "offerPrice1")
        if ask1 <= 0:
            # 部分终端 askPrice 为列表
            ap = None
            if isinstance(t, dict):
                ap = t.get("askPrice") or t.get("askPrices")
            else:
                ap = getattr(t, "askPrice", None) or getattr(t, "askPrices", None)
            if isinstance(ap, (list, tuple)) and len(ap) > 0:
                try:
                    ask1 = float(ap[0])
                except Exception:
                    ask1 = 0.0
        bid1 = _get(t, "bidPrice1", "bid1", "buyPrice1")
        if bid1 <= 0:
            bp = None
            if isinstance(t, dict):
                bp = t.get("bidPrice") or t.get("bidPrices")
            else:
                bp = getattr(t, "bidPrice", None) or getattr(t, "bidPrices", None)
            if isinstance(bp, (list, tuple)) and len(bp) > 0:
                try:
                    bid1 = float(bp[0])
                except Exception:
                    bid1 = 0.0
        return _px_round(last), _px_round(ask1), _px_round(bid1)
    except Exception as e:
        _diag_once("tick_fail", e)
        return 0.0, 0.0, 0.0


def _tick_last(C, fallback=None):
    last, _a, _b = _tick_quote(C)
    if last > 0:
        return last
    try:
        if fallback is not None and float(fallback) > 0:
            return _px_round(fallback)
    except Exception:
        pass
    return 0.0


def _cage_cap(C, last_px):
    """有效买入上限（不强制抬到 143，避免低于笼子时废单）。

    深市：最近价 * CAGE_RATIO，封顶全日涨停。
    沪市：优先卖一 * CAGE_RATIO；无盘口回退最近价 * CAGE_RATIO。
    无有效基准时回退 REOPEN_CAP 参考价。
    """
    mkt = _market_tag()
    limit_up = _limit_up()
    ratio = float(globals().get("CAGE_RATIO") or 1.1)

    if mkt == "SH" and (not getattr(A, "is_backtest", False)):
        last, ask1, _bid1 = _tick_quote(C)
        base = ask1 if ask1 > 0 else (last if last > 0 else float(last_px or 0))
        if base > 0:
            return _px_round(min(base * ratio, limit_up))

    try:
        last = float(last_px or 0)
    except Exception:
        last = 0.0
    if last > 0:
        return _px_round(min(last * ratio, limit_up))
    return _reopen_cap()


def _listing_day_uncached(C, day):
    stock = str(getattr(A, "stock", "") or "")
    mp = globals().get("LISTING_DATE_MAP") or {}
    if stock in mp:
        return str(mp.get(stock) or "") == str(day), "map"

    def _from_close(close):
        if close is None:
            return None, "daily_none"
        try:
            n = len(close)
        except Exception:
            return None, "daily_bad"
        if n <= 0:
            return None, "daily_empty"
        if n >= 2:
            return False, "daily_ge2"
        return True, "daily_eq1"

    def _index_yyyymmdd(ix):
        s = str(ix).strip()
        digits = "".join([c for c in s if c.isdigit()])
        if len(digits) >= 8:
            return digits[:8]
        try:
            if hasattr(ix, "strftime"):
                return ix.strftime("%Y%m%d")
        except Exception:
            pass
        return ""

    def _minute_has_today():
        day8 = str(day)[:8]
        start = day8 + "091500"
        end = day8 + "150000"
        md = None
        try:
            md = C.get_market_data_ex(
                fields=["close"],
                stock_code=[stock],
                period="1m",
                start_time=start,
                end_time=end,
                count=300,
                dividend_type="none",
                fill_data=False,
                subscribe=False,
            )
        except TypeError:
            try:
                md = C.get_market_data_ex(
                    ["close"],
                    [stock],
                    period="1m",
                    start_time=start,
                    end_time=end,
                    count=300,
                    dividend_type="none",
                )
            except Exception as e:
                _diag_once("listing_minute_fail", e)
                return False
        except Exception as e:
            _diag_once("listing_minute_fail", e)
            return False
        close = _series_from_ex(md, stock, "close")
        if close is None or len(close) <= 0:
            return False
        try:
            df = None
            if isinstance(md, dict) and stock in md:
                df = md[stock]
            if df is not None and hasattr(df, "index"):
                days = set()
                for ix in list(df.index)[:300]:
                    d8 = _index_yyyymmdd(ix)
                    if d8:
                        days.add(d8)
                if days and (day8 not in days or any(d != day8 for d in days)):
                    return False
        except Exception as e:
            _diag_once("listing_minute_index", e)
        return True

    try:
        md = C.get_market_data_ex(
            fields=["close"],
            stock_code=[stock],
            period="1d",
            end_time=str(day),
            count=5,
            dividend_type="none",
            fill_data=False,
            subscribe=False,
        )
        ok, reason = _from_close(_series_from_ex(md, stock, "close"))
    except TypeError:
        try:
            md = C.get_market_data_ex(
                ["close"],
                [stock],
                period="1d",
                start_time="",
                end_time=str(day),
                count=5,
                dividend_type="none",
            )
            ok, reason = _from_close(_series_from_ex(md, stock, "close"))
        except Exception as e:
            _diag_once("listing_day_fail", e)
            ok, reason = None, "query_fail"
    except Exception as e:
        _diag_once("listing_day_fail", e)
        ok, reason = None, "query_fail"

    if ok is None and reason in ("daily_none", "daily_empty"):
        if _minute_has_today():
            return True, "minute_today_fallback"
    return ok, reason


def _is_listing_day(C, day):
    if not bool(globals().get("LISTING_DAY_ONLY", True)):
        return True
    stock = str(getattr(A, "stock", "") or "")
    cache_key = "%s|%s" % (stock, day)
    cache = getattr(A, "_listing_day_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        A._listing_day_cache = cache
    if cache_key in cache:
        return bool(cache[cache_key])

    ok, reason = _listing_day_uncached(C, day)
    if ok is None:
        fail_open = bool(globals().get("LISTING_DAY_FAIL_OPEN", False))
        ok = fail_open
        print(
            "%s listing_day unknown -> %s" % (STRATEGY_NAME, "ALLOW" if ok else "DENY"),
            reason,
            stock,
            day,
        )
        _event_log(
            "listing_day_unknown",
            stock=stock,
            day=day,
            allow=ok,
            reason=reason,
        )
    else:
        _event_log("listing_day", stock=stock, day=day, ok=ok, reason=reason)
    cache[cache_key] = bool(ok)
    A._listing_day_cache = cache
    return bool(ok)

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

# === pbs/market.py ===
def _synth_ohlcv_from_px(px, open_px=None, high_px=None, low_px=None, vol=0.0):
    """用最新价合成单根 OHLCV，供 tick 主图决策。"""
    px = float(px or 0)
    if px <= 0:
        return None
    o = float(open_px or 0)
    h = float(high_px or 0)
    l = float(low_px or 0)
    if o <= 0:
        o = px
    if h <= 0:
        h = max(o, px)
    if l <= 0:
        l = min(o, px) if o > 0 else px
    return [o], [h], [l], [px], [float(vol or 0)]


def _tick_field_series(md, stock, field):
    """解析 period=tick 的 get_market_data_ex 结果为 float 列表。"""
    if md is None:
        return None
    # 常见：{stock: DataFrame/ndarray/list[dict]}
    if isinstance(md, dict) and stock in md:
        obj = md[stock]
        if hasattr(obj, "columns") and field in getattr(obj, "columns", []):
            return _series_from_ex(md, stock, field)
        if isinstance(obj, dict) and field in obj:
            try:
                return [float(x) for x in list(obj[field]) if x is not None]
            except Exception:
                pass
        # list/tuple of dict-like ticks
        try:
            rows = list(obj)
            out = []
            for row in rows:
                v = None
                if isinstance(row, dict):
                    v = row.get(field)
                elif hasattr(row, field):
                    v = getattr(row, field)
                elif hasattr(row, "__getitem__"):
                    try:
                        v = row[field]
                    except Exception:
                        v = None
                if v is None:
                    continue
                try:
                    fv = float(v)
                    if fv == fv and fv > 0:
                        out.append(fv)
                except Exception:
                    continue
            if out:
                return out
        except Exception:
            pass
    # 也试标准 K 线字段解析（部分终端 tick 仍给 DataFrame）
    return _series_from_ex(md, stock, field)


def _get_ohlcv_tick(C, stock):
    """分笔主图：实盘优先全推；回测/实盘均用 tick 序列；可选回退 1m。"""
    count = int(globals().get("OHLC_COUNT") or 200)
    end = _bar_end_str(C)
    bt = getattr(A, "is_backtest", False)

    # 1) 实盘全推（回测禁用，避免串入实盘脏价）
    if not bt:
        last, _a, _b = _tick_quote(C)
        open_px = high_px = low_px = 0.0
        try:
            fn = getattr(C, "get_full_tick", None)
            if callable(fn):
                ticks = fn([stock])
                t = ticks.get(stock) if isinstance(ticks, dict) else None
                if t is not None:
                    def _g(*keys):
                        for k in keys:
                            if isinstance(t, dict) and t.get(k) is not None:
                                try:
                                    v = float(t[k])
                                    if v > 0:
                                        return v
                                except Exception:
                                    pass
                            if hasattr(t, k):
                                try:
                                    v = float(getattr(t, k))
                                    if v > 0:
                                        return v
                                except Exception:
                                    pass
                        return 0.0

                    if last <= 0:
                        last = _g("lastPrice", "price", "last", "match")
                    open_px = _g("open", "openPrice")
                    high_px = _g("high", "highPrice")
                    low_px = _g("low", "lowPrice")
        except Exception as e:
            _diag_once("tick_full_fail", e)
        syn = _synth_ohlcv_from_px(last, open_px, high_px, low_px)
        if syn is not None:
            _diag_once("md_ok", "source=", "full_tick", "period=", "tick", "last=", round(last, 4))
            return syn

    # 2) get_market_data_ex(period=tick) — 回测主路径
    md = None
    source = None
    fields = ["lastPrice", "open", "high", "low", "volume"]
    try:
        md = C.get_market_data_ex(
            fields=fields,
            stock_code=[stock],
            period="tick",
            end_time=end,
            count=count,
            dividend_type="none",
            fill_data=False,
            subscribe=False,
        )
        source = "get_market_data_ex/tick"
    except TypeError:
        try:
            md = C.get_market_data_ex(
                fields,
                [stock],
                period="tick",
                start_time="",
                end_time=end,
                count=count,
                dividend_type="none",
            )
            source = "get_market_data_ex/tick/pos"
        except Exception as e:
            _diag_once("md_tick_fail", e)
            md = None
    except Exception as e:
        _diag_once("md_tick_fail", e)
        md = None

    lasts = _tick_field_series(md, stock, "lastPrice")
    if not lasts:
        lasts = _tick_field_series(md, stock, "close")
    opens = _tick_field_series(md, stock, "open")
    highs = _tick_field_series(md, stock, "high")
    lows = _tick_field_series(md, stock, "low")
    vols = _tick_field_series(md, stock, "volume")
    if lasts and len(lasts) >= 1:
        n = len(lasts)
        if not opens or len(opens) != n:
            opens = list(lasts)
        if not highs or len(highs) != n:
            highs = list(lasts)
        if not lows or len(lows) != n:
            lows = list(lasts)
        if not vols or len(vols) != n:
            vols = [0.0] * n
        _diag_once(
            "md_ok",
            "source=",
            source,
            "period=",
            "tick",
            "n=",
            n,
            "last=",
            round(float(lasts[-1]), 4),
            "bt=",
            bt,
        )
        return opens, highs, lows, lasts, vols

    # 3) 可选回退 1m（默认关闭，保持回测/实盘一致）
    if bool(globals().get("TICK_ALLOW_1M_FALLBACK", False)):
        _diag_once("md_tick_fallback_1m", "stock=", stock)
        saved = getattr(A, "period", "tick")
        try:
            A.period = "1m"
            return _get_ohlcv_bars(C, stock, period="1m")
        finally:
            A.period = saved

    _diag_once("md_tick_empty", "stock=", stock, "end=", end, "bt=", bt)
    return None


def _get_ohlcv_bars(C, stock, period=None):
    """拉 K 线 OHLCV。"""
    period = period or getattr(A, "period", "1m")
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


def _get_ohlcv(C, stock):
    """拉主图周期行情；tick 走分笔路径，其余走 K 线。"""
    period = getattr(A, "period", "1m")
    if str(period) == "tick":
        return _get_ohlcv_tick(C, stock)
    return _get_ohlcv_bars(C, stock, period=period)

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
        if DRY_RUN and bool(globals().get("DRY_RUN_VIRTUAL_CASH", True)):
            return float(
                globals().get("DRY_RUN_VIRTUAL_CASH_AMT")
                or globals().get("TRADE_BUDGET")
                or 10**9
            )
        return None
    if not accs:
        print(_strategy_tag(), "account not login", A.acct)
        _event_log("account_not_login", acct=A.acct)
        if DRY_RUN and bool(globals().get("DRY_RUN_VIRTUAL_CASH", True)):
            amt = float(
                globals().get("DRY_RUN_VIRTUAL_CASH_AMT")
                or globals().get("TRADE_BUDGET")
                or 10**9
            )
            print(_strategy_tag(), "DRY virtual cash=", amt)
            _event_log("dry_virtual_cash", amt=amt)
            return amt
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
def _deal_fill_ex(remark, stock):
    """汇总匹配 remark+标的 的成交 -> (量, 均价, query_ok)。

    query_ok=False：接口失败；绝不能当成「无成交」去清影子 pending。
    """
    vol = 0
    notional = 0.0
    try:
        deals = get_trade_detail_data(A.acct, A.acct_type, "deal")
    except Exception as e:
        print(_strategy_tag(), "deal query fail", e)
        _event_log("deal_query_fail", error=str(e))
        return 0, 0.0, False
    if deals is None:
        _event_log("deal_query_fail", error="deals_none")
        return 0, 0.0, False
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
    return vol, avg, True


def _deal_fill(remark, stock):
    """汇总匹配 remark+标的 的成交 -> (量, 均价)。兼容旧调用。"""
    vol, avg, _ok = _deal_fill_ex(remark, stock)
    return vol, avg


def _shadow_reorder_block_arm():
    """影子强清后短冷却，避免同轮/紧接重挂双开。"""
    try:
        ms = float(globals().get("PENDING_SHADOW_REORDER_COOLDOWN_MS") or 2000.0)
    except Exception:
        ms = 2000.0
    if ms <= 0:
        A._shadow_reorder_block_until_ms = 0.0
        return
    now_ms = 0.0
    try:
        now_ms = datetime.datetime.now().timestamp() * 1000.0
    except Exception:
        now_ms = 0.0
    A._shadow_reorder_block_until_ms = now_ms + ms
    _event_log(
        "shadow_reorder_block",
        cooldown_ms=ms,
        until_ms=float(A._shadow_reorder_block_until_ms or 0),
    )


def _shadow_reorder_blocked(now=None):
    until = float(getattr(A, "_shadow_reorder_block_until_ms", 0) or 0)
    if until <= 0:
        return False
    now_ms = 0.0
    try:
        if now is not None and hasattr(now, "timestamp"):
            now_ms = now.timestamp() * 1000.0
        else:
            now_ms = datetime.datetime.now().timestamp() * 1000.0
    except Exception:
        now_ms = 0.0
    return now_ms < until


def _find_order_ex(remark, stock):
    """查找委托 -> (order_or_None, query_ok)。

    query_ok=False：接口失败，绝不能当成「已撤/不存在」去清 pending（防双挂）。
    """
    try:
        orders = get_trade_detail_data(A.acct, A.acct_type, "order")
    except Exception as e:
        print(_strategy_tag(), "order query fail", e)
        _event_log("order_query_fail", error=str(e))
        return None, False
    if orders is None:
        _event_log("order_query_fail", error="orders_none")
        return None, False
    hit = None
    for od in orders:
        if str(getattr(od, "m_strRemark", "") or "") != remark:
            continue
        code = getattr(od, "m_strInstrumentID", "") + "." + getattr(od, "m_strExchangeID", "")
        if code != stock:
            continue
        hit = od
    return hit, True


def _find_order(remark, stock):
    od, _ok = _find_order_ex(remark, stock)
    return od


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
    if str(reason or "") == "shadow_never_seen":
        _shadow_reorder_block_arm()


def _pending_check_should_log(
    intent, status, traded, cancel_req, order_seen, order_qok, age, force=False
):
    """pending_check 日志节流：状态变化、强制、或达到间隔才打。

    PENDING_CHECK_LOG_SEC：未配置或 <=0 = 每次都打（opt-in 节流）；>0 才节流。
    """
    if force:
        try:
            now_ms = datetime.datetime.now().timestamp() * 1000.0
        except Exception:
            now_ms = 0.0
        A._pending_check_log_ms = now_ms
        return True

    raw = globals().get("PENDING_CHECK_LOG_SEC", None)
    if raw is None:
        return True
    try:
        log_sec = float(raw)
    except Exception:
        return True
    if log_sec <= 0:
        return True

    fp = "%s|%s|%s|%s|%s|%s" % (
        str(intent or ""),
        str(status),
        str(int(traded or 0)),
        "1" if cancel_req else "0",
        "1" if order_seen else "0",
        "1" if order_qok else "0",
    )
    last_fp = str(getattr(A, "_pending_check_fp", "") or "")
    changed = fp != last_fp
    now_ms = 0.0
    try:
        now_ms = datetime.datetime.now().timestamp() * 1000.0
    except Exception:
        now_ms = 0.0
    last_ms = float(getattr(A, "_pending_check_log_ms", 0) or 0)
    due = (last_ms <= 0) or ((now_ms - last_ms) >= log_sec * 1000.0)
    if (not changed) and (not due):
        return False
    A._pending_check_fp = fp
    A._pending_check_log_ms = now_ms
    return True


def _shadow_clear_intent_ok(intent):
    """必须显式配置 PENDING_SHADOW_CLEAR_INTENTS；未配/空元组 = 不启用强清。"""
    allow = globals().get("PENDING_SHADOW_CLEAR_INTENTS", None)
    if allow is None:
        return False
    try:
        s = set(str(x) for x in allow)
    except Exception:
        return False
    if not s:
        return False
    return str(intent) in s


def _new_remark(tag, side, vol):
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return "%s %s %s %s x%d %s" % (_strategy_tag(), side, tag, A.stock, int(vol), ts)


def _process_pending(C, now):
    """实盘: 处理 pending；超时先撤；仅终态清空。仍阻塞则返回 True。"""
    pend = getattr(A, "pending", None)
    if not pend:
        return False
    if getattr(A, "is_backtest", False):
        A.pending = None
        return False
    if DRY_RUN:
        # dry_keep：保留虚拟挂单，供策略测撤补/升级；否则沿用旧行为立刻清空
        if bool(pend.get("dry_keep")):
            if bool(pend.get("cancel_requested")):
                _clear_pending("dry_cancel")
                return False
            return True
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

    deal_vol, deal_avg, deal_qok = _deal_fill_ex(remark, stock)
    od, order_qok = _find_order_ex(remark, stock)
    status = int(getattr(od, "m_nOrderStatus", -1) or -1) if od is not None else -1
    traded = max(deal_vol, _order_traded_vol(od))
    px = deal_avg if deal_avg > 0 else float(pend.get("price_hint", 0) or 0)
    cancel_req = bool(pend.get("cancel_requested"))
    if od is not None and not pend.get("order_seen"):
        pend["order_seen"] = True
        pend["shadow_miss_hits"] = 0
        A.pending = pend
        try:
            _save_state()
        except Exception:
            pass
        # 委托成功确认：柜台查询已见到本 remark 委托（不以成交为准）
        print(
            _strategy_tag(),
            "order acked intent=%s status=%s age=%.1fs remark=%s"
            % (intent, status, age, remark),
        )
        _event_log(
            "order_acked",
            intent=intent,
            status=status,
            age_sec=round(age, 3),
            remark=remark,
            side=side,
            vol=target,
            price=float(pend.get("price_hint") or 0),
        )

    order_seen = bool(pend.get("order_seen"))

    shadow_sec = 0.0
    try:
        shadow_sec = float(globals().get("PENDING_SHADOW_CLEAR_SEC") or 0)
    except Exception:
        shadow_sec = 0.0
    shadow_intent = _shadow_clear_intent_ok(intent)
    # 影子=委托未见 + 成交查询成功且量为0（成交查询失败则不清，防漏记后双开）
    shadow_candidate = (
        shadow_sec > 0
        and shadow_intent
        and (not cancel_req)
        and (not order_seen)
        and order_qok
        and (od is None)
        and deal_qok
        and int(deal_vol or 0) <= 0
        and age >= shadow_sec
    )
    # 影子候选窗口内强制打 pending_check，保留未见单取证（通常仅数次命中）
    force_pending_log = bool(shadow_candidate)

    if _pending_check_should_log(
        intent,
        status,
        traded,
        cancel_req,
        order_seen,
        order_qok,
        age,
        force=force_pending_log,
    ):
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
            "qok=",
            order_qok,
            "seen=",
            order_seen,
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
            order_qok=order_qok,
            order_seen=order_seen,
            shadow_candidate=bool(shadow_candidate),
        )

    filled = globals().get("_ORDER_FILLED") or (56, 8)
    dead = globals().get("_ORDER_DEAD") or (54, 57, 53, 5, 6, 9)
    # 股票默认 100；可转债等可在策略 config 设 LOT_SIZE=10
    lot = int(globals().get("LOT_SIZE") or 100)
    if lot <= 0:
        lot = 100
    done_fill = traded >= target and target >= lot
    status_filled = status in filled
    status_dead = status in dead

    if done_fill or (status_filled and traded >= lot):
        use_vol = traded if traded >= lot else deal_vol
        if side == "buy":
            _pending_on_buy_fill(pend, use_vol, px)
        else:
            _pending_on_sell_fill(pend, now, use_vol, px)
        _clear_pending("filled")
        return False

    if status_dead:
        if traded > 0:
            if side == "buy":
                _pending_on_buy_fill(pend, traded, px)
            else:
                _pending_on_sell_fill(pend, now, traded, px)
            _clear_pending("dead-partial")
        else:
            _clear_pending("rejected/cancelled")
        return False

    # 委托已离簿但成交查询显示有量：先记账，禁止当影子重挂
    if (
        (not cancel_req)
        and (not order_seen)
        and order_qok
        and (od is None)
        and deal_qok
        and int(deal_vol or 0) > 0
    ):
        use_vol = int(deal_vol)
        print(
            _strategy_tag(),
            "deal without open order -> fill intent=%s vol=%s"
            % (intent, use_vol),
        )
        _event_log(
            "deal_without_order",
            intent=intent,
            vol=use_vol,
            price=px,
            remark=remark,
            age_sec=round(age, 3),
        )
        if side == "buy":
            _pending_on_buy_fill(pend, use_vol, px)
        else:
            _pending_on_sell_fill(pend, now, use_vol, px)
        _clear_pending("deal_without_order")
        return False

    # 未见单影子 pending：委托未见 + 成交查询成功且为0；命中间隔 + 二次确认
    # PENDING_SHADOW_CLEAR_INTENTS 必须显式配置
    if shadow_sec > 0 and shadow_intent:
        if shadow_candidate:
            try:
                need_hits = int(globals().get("PENDING_SHADOW_CLEAR_HITS") or 3)
            except Exception:
                need_hits = 3
            if need_hits < 1:
                need_hits = 1
            try:
                hit_gap_ms = float(globals().get("PENDING_SHADOW_CLEAR_HIT_GAP_MS") or 1000)
            except Exception:
                hit_gap_ms = 1000.0
            if hit_gap_ms < 0:
                hit_gap_ms = 0.0
            now_ms = 0.0
            try:
                now_ms = datetime.datetime.now().timestamp() * 1000.0
            except Exception:
                now_ms = 0.0
            last_hit_ms = float(pend.get("shadow_miss_hit_ms") or 0)
            can_hit = (last_hit_ms <= 0) or ((now_ms - last_hit_ms) >= hit_gap_ms)
            if can_hit:
                hits = int(pend.get("shadow_miss_hits") or 0) + 1
                pend["shadow_miss_hits"] = hits
                pend["shadow_miss_hit_ms"] = now_ms
                A.pending = pend
                try:
                    _save_state()
                except Exception:
                    pass
            else:
                hits = int(pend.get("shadow_miss_hits") or 0)
            if can_hit and hits >= need_hits:
                od2, qok2 = _find_order_ex(remark, stock)
                deal2, avg2, deal_qok2 = _deal_fill_ex(remark, stock)
                confirm_ok = (
                    bool(qok2)
                    and (od2 is None)
                    and bool(deal_qok2)
                    and int(deal2 or 0) <= 0
                )
                _event_log(
                    "pending_shadow_confirm",
                    intent=intent,
                    age_sec=round(age, 3),
                    shadow_sec=shadow_sec,
                    hits=hits,
                    need_hits=need_hits,
                    hit_gap_ms=hit_gap_ms,
                    order_qok=bool(order_qok),
                    order_seen=bool(order_seen),
                    deal_qok=bool(deal_qok),
                    deal=int(deal_vol or 0),
                    confirm_ok=confirm_ok,
                    confirm_qok=bool(qok2),
                    confirm_od=(od2 is not None),
                    confirm_deal_qok=bool(deal_qok2),
                    confirm_deal=int(deal2 or 0),
                    remark=remark,
                )
                if confirm_ok:
                    print(
                        _strategy_tag(),
                        "pending shadow clear: never acked intent=%s age=%.1fs hits=%d"
                        % (intent, age, hits),
                    )
                    _event_log(
                        "pending_shadow_clear",
                        intent=intent,
                        age_sec=round(age, 3),
                        shadow_sec=shadow_sec,
                        hits=hits,
                        need_hits=need_hits,
                        order_qok=True,
                        order_seen=False,
                        deal_qok=True,
                        deal=0,
                        status=status,
                        remark=remark,
                    )
                    _clear_pending("shadow_never_seen")
                    return False
                if od2 is not None:
                    pend["order_seen"] = True
                    print(
                        _strategy_tag(),
                        "order acked (shadow confirm) intent=%s remark=%s"
                        % (intent, remark),
                    )
                    _event_log(
                        "order_acked",
                        intent=intent,
                        status=int(getattr(od2, "m_nOrderStatus", -1) or -1),
                        age_sec=round(age, 3),
                        remark=remark,
                        side=side,
                        via="shadow_confirm",
                    )
                elif deal_qok2 and int(deal2 or 0) > 0:
                    use_vol = int(deal2)
                    fill_px = avg2 if avg2 > 0 else px
                    if side == "buy":
                        _pending_on_buy_fill(pend, use_vol, fill_px)
                    else:
                        _pending_on_sell_fill(pend, now, use_vol, fill_px)
                    _clear_pending("deal_without_order_confirm")
                    return False
                pend["shadow_miss_hits"] = 0
                pend["shadow_miss_hit_ms"] = 0
                A.pending = pend
                try:
                    _save_state()
                except Exception:
                    pass
                if (not confirm_ok) and (od2 is None):
                    print(
                        _strategy_tag(),
                        "pending shadow confirm fail; keep pending intent=%s"
                        % intent,
                    )
        else:
            if int(pend.get("shadow_miss_hits") or 0) > 0:
                pend["shadow_miss_hits"] = 0
                pend["shadow_miss_hit_ms"] = 0
                A.pending = pend
                try:
                    _save_state()
                except Exception:
                    pass

    timeout = float(globals().get("PENDING_TIMEOUT_SEC") or 180)
    orphan = float(globals().get("PENDING_ORPHAN_SEC") or 60)
    retry_sec = float(globals().get("CANCEL_RETRY_SEC") or 1.0)

    # 主动撤单中：周期重试；仅「曾经见过委托 + 查询成功 + 委托已消失」才可清 pending
    if cancel_req:
        cancel_at = _parse_opened_at(pend.get("cancel_at"))
        cancel_age = 0.0
        if cancel_at is not None and now is not None:
            cancel_age = (now - cancel_at).total_seconds()
        if not order_qok:
            print(_strategy_tag(), "cancel wait: order query fail, keep pending")
            _event_log(
                "cancel_wait_query_fail",
                remark=remark,
                intent=intent,
                cancel_age_sec=int(cancel_age),
            )
            return True
        if od is not None:
            last_retry = _parse_opened_at(pend.get("cancel_retry_at"))
            retry_age = 1e9
            if last_retry is not None and now is not None:
                retry_age = (now - last_retry).total_seconds()
            if last_retry is None or retry_age >= retry_sec:
                ok = _try_cancel_order(od, C)
                pend["cancel_retry_at"] = (now or datetime.datetime.now()).strftime(
                    "%Y%m%d%H%M%S"
                )
                A.pending = pend
                _save_state()
                if not ok:
                    print(
                        _strategy_tag(),
                        "cancel retry fail; order still open age=%.0fs" % cancel_age,
                    )
                    _event_log(
                        "cancel_retry_fail",
                        remark=remark,
                        intent=intent,
                        cancel_age_sec=int(cancel_age),
                    )
            return True
        # 查询成功且委托列表中已无此单
        if pend.get("order_seen") and cancel_age >= orphan:
            if traded > 0:
                if side == "buy":
                    _pending_on_buy_fill(pend, traded, px)
                else:
                    _pending_on_sell_fill(pend, now, traded, px)
                _clear_pending("cancel_gone_partial")
            else:
                print(
                    _strategy_tag(),
                    "pending clear after cancel: order seen then gone",
                )
                _event_log(
                    "pending_cancel_confirmed",
                    remark=remark,
                    intent=intent,
                    cancel_age_sec=int(cancel_age),
                )
                _clear_pending("cancel_confirmed_gone")
            return False
        if cancel_age >= orphan and (not pend.get("order_seen")):
            # 从未见到委托：拒绝 orphan 清，避免旧单仍在时双挂
            print(
                _strategy_tag(),
                "orphan blocked: order never seen, keep pending age=%.0fs"
                % cancel_age,
            )
            _event_log(
                "pending_orphan_blocked",
                remark=remark,
                intent=intent,
                cancel_age_sec=int(cancel_age),
                reason="order_never_seen",
            )
        return True

    if age >= timeout:
        exempt = globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()
        try:
            exempt_set = set(str(x) for x in exempt)
        except Exception:
            exempt_set = set()
        if intent in exempt_set or bool(pend.get("no_timeout")):
            # 长生命周期挂单（如深市临停埋单/沪市首单）禁止超时撤
            log_sec = float(globals().get("PENDING_TIMEOUT_EXEMPT_LOG_SEC") or 300)
            last_log = _parse_opened_at(pend.get("timeout_exempt_log_at"))
            need_log = last_log is None
            if (not need_log) and now is not None and last_log is not None:
                need_log = (now - last_log).total_seconds() >= log_sec
            if need_log:
                print(
                    _strategy_tag(),
                    "pending timeout exempt intent=",
                    intent,
                    "age=%.0fs" % age,
                )
                _event_log(
                    "pending_timeout_exempt",
                    remark=remark,
                    intent=intent,
                    age_sec=int(age),
                )
                pend["timeout_exempt_log_at"] = (
                    now or datetime.datetime.now()
                ).strftime("%Y%m%d%H%M%S")
                A.pending = pend
                try:
                    _save_state()
                except Exception:
                    pass
            return True
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

    return True

# === qmt_common/single/orders.py ===
# 作用: 单仓买卖委托与成交落地
# 主要符号: _order_buy, _order_sell, _apply_buy_fill, _apply_sell_fill
# 钩子实现: _pending_on_buy_fill / _pending_on_sell_fill
# 预算: TRADE_BUDGET；可选 TRADE_BUDGET_BY_STOCK[A.stock]；可选 CASH_RATIO
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

# === pbs/strategy.py ===
# model.md — 仅买入抢筹：开盘/隔夜人工；策略只跑 Mode B 尾盘沪深分流


def _has_position():
    pos = getattr(A, "position", None)
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) > 0


def _cb_lot(price, budget):
    lot = int(globals().get("LOT_SIZE") or 10)
    if price is None or price <= 0 or budget <= 0 or lot <= 0:
        return 0
    return int(float(budget) // (float(price) * lot)) * lot


def _remaining_buy_budget(cash):
    cap = _buy_budget(cash)
    try:
        cap = float(cap or 0)
    except Exception:
        cap = 0.0
    pos = getattr(A, "position", None)
    if not isinstance(pos, dict):
        return max(0.0, cap)
    sh = int(pos.get("shares", 0) or 0)
    if sh <= 0:
        return max(0.0, cap)
    spent = float(pos.get("cost", 0) or 0)
    if spent <= 0:
        spent = sh * float(pos.get("price", 0) or 0)
    return max(0.0, cap - spent)


def _intent_entry_mode(intent):
    if intent in ("SZ_CLOSE", "SH_CLOSE"):
        return "B"
    return ""


def _entry_mode_of(pos=None):
    pos = pos if pos is not None else getattr(A, "position", None)
    if isinstance(pos, dict):
        m = str(pos.get("entry_mode", "") or "")
        if m:
            return m
        return _intent_entry_mode(str(pos.get("intent", "") or ""))
    return str(getattr(A, "entry_mode", "") or "")


def _apply_cb_buy_fill(vol, price, opened_at, **extra):
    lot = int(globals().get("LOT_SIZE") or 10)
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol <= 0:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    prev = getattr(A, "position", None)
    prev_sh = int(prev.get("shares", 0) or 0) if isinstance(prev, dict) else 0
    prev_cost = float(prev.get("cost", 0) or 0) if isinstance(prev, dict) else 0.0
    new_sh = prev_sh + vol
    new_cost = prev_cost + round(vol * price, 2)
    avg = (new_cost / float(new_sh)) if new_sh > 0 else price
    intent = str(extra.get("intent") or "")
    entry_mode = str(extra.get("entry_mode") or "") or _intent_entry_mode(intent)
    pos = {
        "shares": new_sh,
        "price": avg,
        "cost": round(new_cost, 2),
        "opened_at": ot if prev_sh <= 0 else str((prev or {}).get("opened_at") or ot),
    }
    for k, v in extra.items():
        if v is not None:
            pos[k] = v
    if entry_mode:
        pos["entry_mode"] = entry_mode
        A.entry_mode = entry_mode
    A.position = pos
    if not hasattr(A, "acted") or A.acted is None:
        A.acted = set()
    A.acted.add("BUY")
    if getattr(A, "is_backtest", False):
        A.bt_opened_at = pos["opened_at"]
    buy_day = str(pos["opened_at"])[:8] if len(str(pos["opened_at"])) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    if getattr(A, "is_backtest", False):
        A.bt_locked = 0
    if buy_day:
        A.buy_done_day = buy_day
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position, "add_vol=", vol, "lot=", lot)
    _event_log(
        "buy_filled",
        position=A.position,
        vol=vol,
        price=price,
        opened_at=ot,
        entry_mode=entry_mode,
    )


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_cb_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _order_buy_limit(C, price, now, budget=None, intent="BUY", entry_mode=None):
    lot = int(globals().get("LOT_SIZE") or 10)
    price = _px_round(price)
    if price <= 0:
        return False
    wait_sec = float(globals().get("LOG_WAIT_SEC") or 5.0)
    if _shadow_reorder_blocked(now):
        if _log_due("shadow_reorder_block", now, wait_sec):
            print(_strategy_tag(), "buy skip: shadow reorder cooldown")
            _event_log("buy_skip", reason="shadow_reorder_cooldown")
        return False
    if getattr(A, "pending", None):
        if _log_due("buy_skip_pending", now, wait_sec):
            print(_strategy_tag(), "buy skip: pending active")
            _event_log("buy_skip", reason="pending_active")
        return False
    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() > 0):
        if _log_due("buy_skip_holding", now, wait_sec):
            print(_strategy_tag(), "buy skip: already holding")
            _event_log("buy_skip", reason="already_holding")
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False

    if budget is None:
        cash = _available_cash()
        budget = _remaining_buy_budget(cash)
    vol = _cb_lot(price, budget)
    if vol < lot:
        if _log_due("buy_skip_lot", now, wait_sec):
            print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
            _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _cb_lot(price, min(budget, float(cash)))
        if vol < lot:
            if _log_due("buy_skip_cash", now, wait_sec):
                print(_strategy_tag(), "buy skip cash", cash)
                _event_log("buy_skip", reason="cash", cash=cash, price=price)
            return False

    if not entry_mode:
        entry_mode = _intent_entry_mode(intent)
    extra_pos = {"intent": intent}
    if entry_mode:
        extra_pos["entry_mode"] = entry_mode

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark(intent, "BUY", vol)
    # 重试路径下报单前日志节流；申报成功日志不节流
    if _log_due("buy_order_try", now, wait_sec):
        print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price, intent)
    exempt = set(str(x) for x in (globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()))
    no_timeout = str(intent) in exempt
    if DRY_RUN:
        if bool(globals().get("DRY_RUN_FILL_IMMEDIATE", False)):
            _apply_cb_buy_fill(vol, price, ot, **extra_pos)
            return True
        A.pending = {
            "remark": msg,
            "side": "buy",
            "intent": intent,
            "vol": int(vol),
            "stock": A.stock,
            "price_hint": float(price),
            "opened_at": ot,
            "submitted_at": ot,
            "cancel_requested": False,
            "no_timeout": no_timeout,
            "dry_keep": True,
            "extra_pos": extra_pos,
        }
        A.sh_last_order_px = float(price)
        _save_state()
        print(_strategy_tag(), "DRY pending", vol, "@", price, intent)
        _event_log(
            "buy_submitted",
            vol=vol,
            price=price,
            remark=msg,
            intent=intent,
            dry_run=True,
            entry_mode=entry_mode,
        )
        if bool(globals().get("DRY_RUN_FILL_ON_LIMIT", True)) and price + 1e-9 >= _limit_up():
            _apply_cb_buy_fill(vol, price, ot, **extra_pos)
            A.pending = None
            _save_state()
            print(_strategy_tag(), "DRY fill on limit", price)
        return True
    try:
        passorder(
            A.buy_code,
            1101,
            A.acct,
            A.stock,
            11,
            float(price),
            vol,
            _strategy_tag(),
            int(getattr(A, "passorder_quick", 1) or 1),
            msg,
            C,
        )
    except Exception as e:
        if _log_due("passorder_fail", now, wait_sec):
            print(_strategy_tag(), "passorder BUY limit fail", e)
            _event_log("passorder_fail", side="buy", error=str(e), vol=vol, price=price)
        return False
    if getattr(A, "is_backtest", False):
        _apply_cb_buy_fill(vol, price, ot, **extra_pos)
        return True
    A.pending = {
        "remark": msg,
        "side": "buy",
        "intent": intent,
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "opened_at": ot,
        "submitted_at": ot,
        "cancel_requested": False,
        "no_timeout": no_timeout,
        "extra_pos": extra_pos,
    }
    A.sh_last_order_px = float(price)
    _save_state()
    print(_strategy_tag(), "BUY submitted limit", vol, "@", price, msg, intent)
    _event_log(
        "buy_submitted",
        vol=vol,
        price=price,
        remark=msg,
        intent=intent,
        dry_run=False,
        entry_mode=entry_mode,
    )
    return True


def _request_pending_cancel(C, now, reason):
    pend = getattr(A, "pending", None)
    if not isinstance(pend, dict):
        return False
    if pend.get("cancel_requested"):
        return True
    if DRY_RUN and bool(pend.get("dry_keep")):
        print(_strategy_tag(), "DRY cancel", reason, "px=", pend.get("price_hint"))
        _event_log("chase_cancel", reason=reason, price=pend.get("price_hint"), dry=True)
        A.pending = None
        _save_state()
        return True
    remark = str(pend.get("remark", "") or "")
    stock = str(pend.get("stock", A.stock) or A.stock)
    od, qok = _find_order_ex(remark, stock)
    if not qok:
        print(_strategy_tag(), "chase cancel defer: order query fail", reason)
        _event_log("chase_cancel_defer", reason=reason, error="order_query_fail")
        return False
    if od is None:
        print(_strategy_tag(), "chase cancel defer: order not visible yet", reason)
        _event_log("chase_cancel_defer", reason=reason, error="order_not_visible")
        return False
    pend["order_seen"] = True
    _try_cancel_order(od, C)
    pend["cancel_requested"] = True
    pend["cancel_at"] = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    pend["cancel_reason"] = str(reason or "")
    A.pending = pend
    _save_state()
    print(_strategy_tag(), "chase cancel requested", reason, "px=", pend.get("price_hint"))
    _event_log("chase_cancel", reason=reason, price=pend.get("price_hint"), remark=remark)
    return True


def _reconcile_with_broker():
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return
    if _available_cash() is None:
        print(_strategy_tag(), "reconcile skip: not login")
        return
    stock = str(getattr(A, "stock", "") or "")
    try:
        positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    except Exception as e:
        print(_strategy_tag(), "reconcile position query fail", e)
        return
    if positions is None:
        return
    vol = 0
    cost = 0.0
    found = False
    for p in positions:
        if _pos_code(p) != stock:
            continue
        found = True
        vol = int(getattr(p, "m_nVolume", 0) or 0)
        for attr in ("m_dOpenPrice", "m_dCostPrice", "m_dAvgPrice"):
            v = getattr(p, attr, None)
            if v is not None:
                try:
                    cost = float(v)
                    if cost > 0:
                        break
                except Exception:
                    pass
        break
    if found and vol > 0:
        cur = int((getattr(A, "position", None) or {}).get("shares", 0) or 0)
        if cur != vol or (not _has_position()):
            ot = ""
            entry_mode = str(getattr(A, "entry_mode", "") or "")
            if isinstance(getattr(A, "position", None), dict):
                ot = str(A.position.get("opened_at", "") or "")
                if not entry_mode:
                    entry_mode = str(A.position.get("entry_mode", "") or "")
            if not ot:
                ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            A.position = {
                "shares": vol,
                "price": float(cost) if cost > 0 else float(
                    (getattr(A, "position", None) or {}).get("price", 0) or 0
                ),
                "cost": round(vol * float(cost), 2) if cost > 0 else 0.0,
                "opened_at": ot,
                "reconciled": True,
            }
            if entry_mode:
                A.position["entry_mode"] = entry_mode
                A.entry_mode = entry_mode
            if not hasattr(A, "acted") or A.acted is None:
                A.acted = set()
            A.acted.add("BUY")
            A.buy_done_day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
            _save_state()
            print(_strategy_tag(), "reconcile sync from broker vol=", vol, "cost=", cost)
        return
    if (not found or vol <= 0) and _has_position():
        print(_strategy_tag(), "reconcile clear shadow (broker flat) was=", A.position)
        A.position = None
        A.entry_mode = ""
        if hasattr(A, "acted") and isinstance(A.acted, set):
            A.acted.discard("BUY")
        A.buy_done_day = ""
        _save_state()


def _in_window(now_s, start, end):
    return str(start) <= str(now_s) <= str(end)


def _now_ms(now):
    if now is None:
        now = datetime.datetime.now()
    try:
        return now.timestamp() * 1000.0
    except Exception:
        return 0.0


def _log_due(key, now=None, sec=None):
    """墙钟节流：到期返回 True 并打戳。定时器高频下代替 C.barpos % N。"""
    if sec is None:
        sec = globals().get("LOG_STATUS_SEC")
    try:
        sec = float(sec if sec is not None else 10.0)
    except Exception:
        sec = 10.0
    if sec <= 0:
        return True
    store = getattr(A, "_log_at_ms", None)
    if not isinstance(store, dict):
        store = {}
        A._log_at_ms = store
    k = str(key or "")
    now_ms = _now_ms(now)
    last = float(store.get(k, 0) or 0)
    if last > 0 and (now_ms - last) < sec * 1000.0:
        return False
    store[k] = now_ms
    return True


def _close_buy_price():
    cfg = globals().get("CLOSE_BUY_PRICE")
    if cfg is not None:
        try:
            v = float(cfg)
            if v > 0:
                return _px_round(v)
        except Exception:
            pass
    return _limit_up()


def _handle_mode_b_close(C, now, now_s, day):
    """尾盘：14:57 起顶格申报；以柜台见单为委托成功，成交非目标。"""
    if not bool(globals().get("ENABLE_MODE_B", True)):
        return
    start = str(globals().get("CLOSE_BUY_START") or "145700")
    end = str(globals().get("CLOSE_BUY_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if _has_position():
        return
    if ("BUY" in getattr(A, "acted", set())) and (not getattr(A, "pending", None)):
        return

    pend = getattr(A, "pending", None)
    if isinstance(pend, dict):
        # 已报出：等柜台 ack（order_seen）/ 废单 / 影子强清；顶格常不成交属正常
        return

    px = _close_buy_price()
    if px <= 0:
        return
    mkt = _market_tag()
    intent = "SZ_CLOSE" if mkt == "SZ" else "SH_CLOSE"
    wait_sec = float(globals().get("LOG_WAIT_SEC") or 5.0)
    # 仍按 50ms 重试；日志约 LOG_WAIT_SEC 一条，避免刷屏
    if _log_due("close_buy_try", now, wait_sec):
        print("%s %s buy @%.3f now=%s (limit-up until submit ok)" % (STRATEGY_NAME, intent, px, now_s))
        _event_log("close_buy_try", intent=intent, price=px, now_s=now_s, mkt=mkt)
    if _order_buy_limit(C, px, now, intent=intent, entry_mode="B"):
        print("%s %s submitted @%.3f now=%s (wait order ack)" % (STRATEGY_NAME, intent, px, now_s))
        _event_log("close_buy_submitted", intent=intent, price=px, now_s=now_s)
        return
    if _log_due("close_buy_retry", now, wait_sec):
        print("%s %s submit fail -> retry @%.3f" % (STRATEGY_NAME, intent, px))
        _event_log("close_buy_retry", intent=intent, price=px, now_s=now_s)


def _in_critical_live_window(now_s):
    """收盘申报时窗：即使非末 bar 也要跑。"""
    return _in_window(
        now_s,
        str(globals().get("CLOSE_BUY_START") or "145700"),
        str(globals().get("CLOSE_BUY_END") or "145955"),
    )


def _before_close_window(now_s):
    """14:57 前：策略空转，尽量不打日志。"""
    start = str(globals().get("CLOSE_BUY_START") or "145700")
    return str(now_s) < start


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)
    in_close = _in_critical_live_window(now_s)
    before_close = _before_close_window(now_s)

    if not bt:
        if getattr(A, "pending", None):
            _process_pending(C, now)
        # tick 主图：每笔都决策；非 tick 仍可用末 bar / critical 窗
        only_last = bool(globals().get("LIVE_ONLY_LAST_BAR", False))
        if str(getattr(A, "period", "")) == "tick":
            only_last = False
        if only_last and (not in_close):
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        # 收盘窗外不打心跳，避免全日刷屏
        if in_close:
            _live_heartbeat("live")
    else:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        if in_close:
            _live_heartbeat("no_cash_or_login")
        return

    holding = _has_position() or (bt and _bt_held_vol() > 0)
    mkt = _market_tag()

    # 已持仓：抢筹目标达成，不再交易
    if holding:
        return

    if ("BUY" in getattr(A, "acted", set())) and (not getattr(A, "pending", None)):
        return

    # 14:57 前静默等待（init 日志仍保留；买卖关键事件仍会打）
    if before_close:
        return

    listing = _is_listing_day(C, day)
    if not listing:
        if in_close and _log_due("skip_not_listing", now, globals().get("LOG_STATUS_SEC")):
            print("%s skip: not listing day" % STRATEGY_NAME, day, A.stock)
            _event_log("skip_not_listing_day", day=day, stock=A.stock)
        return

    # 行情仅用于状态行；收盘顶格申报不依赖 OHLCV
    last_px = 0.0
    open_px = 0.0
    n_bars = 0
    ohlcv = None
    if in_close:
        ohlcv = _get_ohlcv(C, A.stock)
    if ohlcv is not None:
        opens, highs, lows, closes, vols = ohlcv
        n_bars = len(closes)
        open_px = float(opens[-1]) if opens else 0.0
        bar_last = float(closes[-1]) if closes else 0.0
        last_px = _tick_last(C, fallback=bar_last)
        if last_px <= 0:
            last_px = _px_round(bar_last)
        if bt:
            try:
                bar_high = float(highs[-1])
            except Exception:
                bar_high = last_px
            if bar_high > last_px:
                last_px = _px_round(bar_high)
            _bt_recover_position(now=now, last=last_px)

    # 仅收盘窗内打状态行 / bars.jsonl
    if in_close:
        do_status = (not getattr(A, "ready_logged", False)) or _log_due(
            "status", now, globals().get("LOG_STATUS_SEC")
        )
        if do_status:
            A.ready_logged = True
            print(
                "%s" % STRATEGY_NAME,
                day,
                now_s,
                "mkt=%s n=%d last=%.3f open=%.3f hold=%s mode=%s "
                "buy_done=%s pending=%s close_px=%.3f"
                % (
                    mkt,
                    n_bars,
                    last_px,
                    open_px,
                    holding,
                    _entry_mode_of(),
                    getattr(A, "buy_done_day", ""),
                    bool(getattr(A, "pending", None)),
                    _close_buy_price(),
                ),
            )
            _bar_log(
                day=day,
                hhmmss=now_s,
                n=n_bars,
                last=round(last_px, 6),
                open=round(open_px, 6),
                hold=holding,
                mkt=mkt,
                buy_done=str(getattr(A, "buy_done_day", "") or ""),
                tag=tag,
                pending=bool(getattr(A, "pending", None)),
            )

    if mkt in ("SZ", "SH"):
        _handle_mode_b_close(C, now, now_s, day)
    elif in_close:
        if _log_due("unknown_market", now, globals().get("LOG_STATUS_SEC")):
            print("%s unknown market stock=%s" % (STRATEGY_NAME, A.stock))
            _event_log("unknown_market", stock=A.stock)

# === pbs/runtime.py ===
def init(C):
    A.busy = False
    A._hb_at = None
    A.drive = ""
    A.passorder_quick = 1
    try:
        _init_impl(C)
    except Exception as e:
        print("%s init error" % STRATEGY_NAME, e)
        _event_log("init_error", error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass


def _ensure_day_flags():
    defaults = {
        "buy_done_day": "",
        "entry_mode": "",
    }
    for k, v in defaults.items():
        if not hasattr(A, k):
            setattr(A, k, v)
    if not isinstance(getattr(A, "_log_at_ms", None), dict):
        A._log_at_ms = {}


def _start_live_timer(C):
    """实盘注册 run_time：收盘申报准点驱动；回测无效。"""
    if getattr(A, "is_backtest", False):
        return False
    if not bool(globals().get("ENABLE_LIVE_TIMER", True)):
        print("%s live timer disabled" % STRATEGY_NAME)
        return False
    ms = int(globals().get("LIVE_TIMER_MS") or 100)
    if ms < 50:
        ms = 50
    period = "%dnMilliSecond" % ms
    start = "2020-01-01 09:00:00"
    mkt = "SH" if _market_tag() == "SH" else "SZ"
    try:
        try:
            C.run_time("_pbs_pulse", period, start, mkt)
        except TypeError:
            C.run_time("_pbs_pulse", period, start)
        print(
            "%s live timer ON" % STRATEGY_NAME,
            period,
            "quickTrade=",
            int(globals().get("TIMER_QUICK_TRADE") or 2),
            "mkt=",
            mkt,
        )
        _event_log(
            "live_timer_on",
            period=period,
            ms=ms,
            quick_trade=int(globals().get("TIMER_QUICK_TRADE") or 2),
            market=mkt,
        )
        A.live_timer_on = True
        return True
    except Exception as e:
        print("%s live timer FAIL" % STRATEGY_NAME, e)
        _event_log("live_timer_fail", error=str(e), period=period)
        A.live_timer_on = False
        return False


def _run_handle(C, drive):
    """分笔/定时器共用入口；busy 防重入。"""
    try:
        _refresh_mode(C)
        if getattr(A, "busy", False):
            return
        A.busy = True
        A.drive = str(drive or "")
        if drive == "timer":
            A.passorder_quick = int(globals().get("TIMER_QUICK_TRADE") or 2)
        else:
            A.passorder_quick = int(globals().get("TICK_QUICK_TRADE") or 1)
        _handle(C)
    except Exception as e:
        print("%s %s error" % (STRATEGY_NAME, drive or "handle"), e)
        _event_log("handle_error", drive=str(drive or ""), error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        A.busy = False
        A.drive = ""
        A.passorder_quick = 1


def _pbs_pulse(C):
    """run_time 回调：墙钟驱动（收盘申报重试）。"""
    if getattr(A, "is_backtest", False):
        return
    _run_handle(C, "timer")


def _init_impl(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C, default="tick")
    chart_p = _norm_period(getattr(C, "period", None))
    if chart_p == "tick":
        A.period = "tick"
    if str(A.period) == "tick":
        if bool(globals().get("LIVE_ONLY_LAST_BAR", False)):
            print("%s tick period: prefer LIVE_ONLY_LAST_BAR=False" % STRATEGY_NAME)
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
    A.drive = ""
    A.passorder_quick = 1
    A.live_timer_on = False
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
        print("%s skip download_history" % STRATEGY_NAME, A.period)

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
            A.entry_mode = ""
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
            _ensure_day_flags()
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
        _ensure_day_flags()
        try:
            _reconcile_with_broker()
        except Exception as e:
            print("%s reconcile fail" % STRATEGY_NAME, e)
            _event_log("reconcile_fail", error=str(e))

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)

    timer_on = False
    if not A.is_backtest:
        timer_on = bool(_start_live_timer(C))

    mkt = _market_tag()
    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        A.stock,
        "mkt=",
        mkt,
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
        "modeB=",
        bool(globals().get("ENABLE_MODE_B", True)),
        "buy_only=1",
        "timer=",
        timer_on,
        "timer_ms=",
        int(globals().get("LIVE_TIMER_MS") or 0),
        "close=",
        "%s-%s" % (CLOSE_BUY_START, CLOSE_BUY_END),
        "close_px=",
        _close_buy_price(),
        "limit_up=",
        _limit_up(),
        "listing_only=",
        bool(globals().get("LISTING_DAY_ONLY", True)),
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        budget=TRADE_BUDGET,
        mkt=mkt,
        mode_b=bool(globals().get("ENABLE_MODE_B", True)),
        buy_only=True,
        timer=timer_on,
        timer_ms=int(globals().get("LIVE_TIMER_MS") or 0),
        close_start=str(globals().get("CLOSE_BUY_START") or ""),
        close_end=str(globals().get("CLOSE_BUY_END") or ""),
        close_px=_close_buy_price(),
        limit_up=_limit_up(),
        listing_day_only=bool(globals().get("LISTING_DAY_ONLY", True)),
        log_dir=str(globals().get("LOG_DIR") or ""),
    )


def handlebar(C):
    """分笔驱动：有行情时补跑；与定时器共用 _handle。"""
    _run_handle(C, "tick")
