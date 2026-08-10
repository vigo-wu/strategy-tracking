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

# ---- 上市首日价格锚点（model.md）----
# 临停基准价 / 模式A 早盘顶格买价（触及 30% 停牌）
HALT_BASE_PRICE = 130.0
MORNING_BUY_PRICE = 130.0
# 价格笼子比例（有效申报上限 = 基准/最新价 * CAGE_RATIO）
CAGE_RATIO = 1.1
# 复牌首段顶格 = 130 * 1.1（严禁深市临停期硬编码 157.30）
REOPEN_CAP_PRICE = 143.0
# 全天最高限价 / 模式A 复牌卖出价
LIMIT_UP_PRICE = 157.30
# 可转债价格小数位
PRICE_DECIMALS = 3
# 沪市追单：新上限至少高出旧挂单价这么多才撤补
CHASE_MIN_STEP = 0.01

# ---- 模式开关（model.md：A 日内动量 / B 尾盘隔夜 / 次日出局）----
ENABLE_MODE_A = True   # 09:25 前 130 抢筹 → 14:57 后封板卖 157.30
ENABLE_MODE_B = True   # 早盘失败则尾盘 143→157.30 备用买入
ENABLE_DAY2_EXIT = True

# ---- 时窗（HHmmss；实盘墙钟，回测用 K 线时间）----
# 模式A 深市：隔夜委托优先；上市日前夜清算后 + 首日 09:25 前均可挂 130
SZ_AM_EVE_START = "203000"
SZ_AM_EVE_END = "223000"
SZ_AM_BUY_START = "000000"
SZ_AM_BUY_END = "092459"
# 模式A 沪市：临停托管不接受申报，卡点 09:24:59.850–09:24:59.950（毫秒）
SH_AM_BUY_MS_START = 850
SH_AM_BUY_MS_END = 950
# 回测 1m 分辨率：用秒级窗近似卡点（实盘仍走毫秒窗）
SH_AM_BUY_START = "092459"
SH_AM_BUY_END = "092459"
# VERIFY_AUCTION_ANY_DAY：开盘竞价放宽窗（1m/联调够得着；首日实盘仍用上方卡点）
SH_AM_BUY_START_VERIFY = "091500"
SH_AM_BUY_END_VERIFY = "092459"
# 未成交早盘单：过此时点后撤掉，腾出 Mode B
AM_CANCEL_AFTER = "092500"

# 模式A 复牌卖出（两市 14:57 起；深市不可撤时段慎挂）
SELL_START = "145700"
SELL_END = "145955"

# 模式B 深市：临停期内均可埋 143（须在 14:55 前完成）
SZ_PREPLACE_START = "130000"
SZ_PREPLACE_END = "145459"
# 模式B 深市：封板后撤 143→挂 157.30
SZ_CLOSE_BUY_START = "145700"
SZ_CLOSE_BUY_END = "145950"
SZ_ESCALATE_ALERT_SEC = 2.0
# 模式B 沪市：14:57 起连续竞价阶梯追单
SH_CHASE_START = "145700"
SH_CHASE_END = "145955"
# 沪市追单节流（毫秒）；model 建议 50–100ms
SH_CHASE_INTERVAL_MS = 50
SH_CHASE_MODE = "cancel_replace"

# 次日（模式B 隔夜仓）出局
D2_AUCTION_START = "091500"
D2_AUCTION_END = "092459"
# 集合竞价高开达到该比例则锁利卖出（相对成本价）
D2_GAP_UP_MIN = 0.05
D2_TRAIL_START = "093000"
D2_TRAIL_END = "093500"
# 自次日开盘后最高点回撤超过该比例 → 市价清仓
D2_TRAIL_DRAWDOWN = 0.015
# 次日开盘相对成本低开超过该比例 → 09:30 止损（无正股映射时用转债自身）
D2_GAP_DOWN_STOP = -0.02
# 可选正股映射：{"123276.SZ": "000001.SZ"}；有则优先看正股开盘
UNDERLYING_MAP = {}

CANCEL_RETRY_SEC = 1.0
PENDING_ORPHAN_SEC = 15
# 排队/追单意图禁止按短超时自动撤
PENDING_TIMEOUT_EXEMPT_INTENTS = (
    "SZ_AM",
    "SH_AM",
    "SZ_PREPLACE",
    "SH_OPEN",
    "SH_CHASE",
    "SZ_SELL",
    "SH_SELL",
    "SH_SELL_CHASE",
)
PENDING_TIMEOUT_EXEMPT_LOG_SEC = 300

# ---- 上市首日门闩 ----
# True=仅上市首日跑买卖；非首日只心跳
LISTING_DAY_ONLY = True
# True=任意交易日验竞价流程（开盘 ModeA + 尾盘 ModeB）；非首日无真实微观结构，只验时窗/下单
# DRY 下开盘 130 会模拟成交以便串起 ModeA 卖出；实盘务必 False
VERIFY_AUCTION_ANY_DAY = False
# 兼容旧名：等同 VERIFY_AUCTION_ANY_DAY（联调）
FORCE_RUN = False
# 日K推断失败时：False=禁止下单(fail-closed)；True=放行(fail-open)
LISTING_DAY_FAIL_OPEN = False
# 可选显式上市日 YYYYMMDD；有则优先于日K推断
LISTING_DATE_MAP = {
    # "123276.SZ": "20260810",
    "118073.SH": "20260812",
}

# 发行规模仅作日志参考（本策略买入不依赖规模）
ISSUE_SIZE_YI = 0.0
SMALL_SIZE_YI = 5.0
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

# ---- 行情与运行 ----
PERIOD = "1m"
OHLC_COUNT = 120
LIVE_ONLY_LAST_BAR = True
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 30
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

# 尾盘窗口短：超时缩短；orphan 仅在「见过委托后消失」时生效（见上方 PENDING_ORPHAN_SEC）
PENDING_TIMEOUT_SEC = 90

STATE_FILE = r"D:\tradingStrategy\cbauct_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "CbAuct"
STRATEGY_VER = "v3.1"

# DRY_RUN：False=虚拟挂单可测阶梯/升级；True=下单即成交（旧行为）
DRY_RUN_FILL_IMMEDIATE = False
# DRY_RUN 且非立即成交时：挂到涨停价则模拟成交
DRY_RUN_FILL_ON_LIMIT = True
# DRY_RUN 未登录时使用虚拟资金（便于无柜台联调）
DRY_RUN_VIRTUAL_CASH = True
DRY_RUN_VIRTUAL_CASH_AMT = 100000.0
# DRY_RUN 默认不写 STATE，避免污染实盘
DRY_RUN_SAVE_STATE = False
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
    A.am_buy_day = str(raw.get("am_buy_day", "") or "")
    A.sz_preplace_day = str(raw.get("sz_preplace_day", "") or "")
    A.sz_close_buy_day = str(raw.get("sz_close_buy_day", "") or "")
    A.sz_escalate_day = str(raw.get("sz_escalate_day", "") or "")
    A.sz_escalate_alert_ms = float(raw.get("sz_escalate_alert_ms", 0) or 0)
    A.sz_sell_day = str(raw.get("sz_sell_day", "") or "")
    A.sh_chase_day = str(raw.get("sh_chase_day", "") or "")
    A.sh_last_order_px = float(raw.get("sh_last_order_px", 0) or 0)
    A.sh_chase_at_ms = float(raw.get("sh_chase_at_ms", 0) or 0)
    A.sh_sell_day = str(raw.get("sh_sell_day", "") or "")
    A.d2_auction_day = str(raw.get("d2_auction_day", "") or "")
    A.d2_stop_day = str(raw.get("d2_stop_day", "") or "")
    A.d2_trail_day = str(raw.get("d2_trail_day", "") or "")
    A.d2_day_high = float(raw.get("d2_day_high", 0) or 0)
    A.d2_open_px = float(raw.get("d2_open_px", 0) or 0)
    A.entry_mode = str(raw.get("entry_mode", "") or "")


def _state_extra_save(data):
    data["buy_done_day"] = str(getattr(A, "buy_done_day", "") or "")
    data["am_buy_day"] = str(getattr(A, "am_buy_day", "") or "")
    data["sz_preplace_day"] = str(getattr(A, "sz_preplace_day", "") or "")
    data["sz_close_buy_day"] = str(getattr(A, "sz_close_buy_day", "") or "")
    data["sz_escalate_day"] = str(getattr(A, "sz_escalate_day", "") or "")
    data["sz_escalate_alert_ms"] = float(getattr(A, "sz_escalate_alert_ms", 0) or 0)
    data["sz_sell_day"] = str(getattr(A, "sz_sell_day", "") or "")
    data["sh_chase_day"] = str(getattr(A, "sh_chase_day", "") or "")
    data["sh_last_order_px"] = float(getattr(A, "sh_last_order_px", 0) or 0)
    data["sh_chase_at_ms"] = float(getattr(A, "sh_chase_at_ms", 0) or 0)
    data["sh_sell_day"] = str(getattr(A, "sh_sell_day", "") or "")
    data["d2_auction_day"] = str(getattr(A, "d2_auction_day", "") or "")
    data["d2_stop_day"] = str(getattr(A, "d2_stop_day", "") or "")
    data["d2_trail_day"] = str(getattr(A, "d2_trail_day", "") or "")
    data["d2_day_high"] = float(getattr(A, "d2_day_high", 0) or 0)
    data["d2_open_px"] = float(getattr(A, "d2_open_px", 0) or 0)
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
    """发行规模（亿元）；未知返回 None。仅日志参考。"""
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


def _cb_code_num():
    stock = str(getattr(A, "stock", "") or "")
    code = stock.split(".")[0] if stock else ""
    try:
        return int(code)
    except Exception:
        return 0


def _is_sz_cb():
    """深市新债：12 / 123 开头（含 127/128 等 12x）。"""
    stock = str(getattr(A, "stock", "") or "").upper()
    if stock.endswith(".SZ"):
        return True
    n = _cb_code_num()
    return 120000 <= n <= 129999


def _is_sh_cb():
    """沪市新债：11 开头。"""
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
    """临停基准 * 笼子；默认 143.00。"""
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


def _cage_cap(last_px):
    """有效申报上限 = min(last * CAGE_RATIO, 全天涨停)。"""
    try:
        last = float(last_px)
    except Exception:
        last = 0.0
    if last <= 0:
        return _reopen_cap()
    ratio = float(globals().get("CAGE_RATIO") or 1.1)
    return _px_round(min(last * ratio, _limit_up()))


def _tick_last(C, fallback=None):
    """优先全推 tick 最新价；失败回退 K 线收盘。"""
    stock = str(getattr(A, "stock", "") or "")
    try:
        fn = getattr(C, "get_full_tick", None)
        if callable(fn):
            ticks = fn([stock])
            if isinstance(ticks, dict) and stock in ticks:
                t = ticks[stock]
                # 勿用 lastClose（昨收/面值），会算错笼子
                for k in ("lastPrice", "price", "last", "match"):
                    if isinstance(t, dict) and t.get(k) is not None:
                        px = float(t[k])
                        if px > 0:
                            return _px_round(px)
                    if hasattr(t, k):
                        px = float(getattr(t, k))
                        if px > 0:
                            return _px_round(px)
    except Exception as e:
        _diag_once("tick_fail", e)
    try:
        if fallback is not None and float(fallback) > 0:
            return _px_round(fallback)
    except Exception:
        pass
    return 0.0


def _listing_day_uncached(C, day):
    """无缓存推断是否上市首日。空日K时若今日分钟线有行情则放行。"""
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
        """日K空洞时：仅当 1m 有数据且时间戳均属 day 才放行。"""
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
        # 尽量校验 index 日期；拿不到 index 则依赖 start/end 窗口
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

    # 日K >=2 根 => 已非首日；fill_data=False 避免空洞填充假K
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

    # 仅日K空洞兜底；query_fail/daily_bad 不兜底，避免老债误放行
    if ok is None and reason in ("daily_none", "daily_empty"):
        if _minute_has_today():
            return True, "minute_today_fallback"
    return ok, reason


def _verify_any_day():
    """联调：跳过上市首日门闩，开盘+尾盘竞价流程均可在任意交易日验证。"""
    if bool(globals().get("VERIFY_AUCTION_ANY_DAY", False)):
        return True
    if bool(globals().get("FORCE_RUN", False)):
        return True
    if not bool(globals().get("LISTING_DAY_ONLY", True)):
        return True
    return False


def _is_listing_day(C, day):
    """上市首日门闩（按 day+stock 缓存）。

    VERIFY_AUCTION_ANY_DAY / FORCE_RUN / LISTING_DAY_ONLY=False 均可放行任意交易日。
    推断失败看 LISTING_DAY_FAIL_OPEN。
    """
    if _verify_any_day():
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

    deal_vol, deal_avg = _deal_fill(remark, stock)
    od, order_qok = _find_order_ex(remark, stock)
    status = int(getattr(od, "m_nOrderStatus", -1) or -1) if od is not None else -1
    traded = max(deal_vol, _order_traded_vol(od))
    px = deal_avg if deal_avg > 0 else float(pend.get("price_hint", 0) or 0)
    cancel_req = bool(pend.get("cancel_requested"))
    if od is not None and not pend.get("order_seen"):
        pend["order_seen"] = True
        A.pending = pend
        try:
            _save_state()
        except Exception:
            pass

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
        bool(pend.get("order_seen")),
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
        order_seen=bool(pend.get("order_seen")),
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

# === cbauct/strategy.py ===
# model.md v3.0:
#   Mode A: 早盘 130 抢筹 → 14:57 后封板卖 157.30（T+0）
#   Mode B: 早盘失败 → 深市 143 埋单/升级顶格；沪市 143 阶梯追至 157.30
#   Day2: 高开锁利 / 1.5% 移动止盈 / 低开止损


def _has_position():
    """可转债：任意张数>0 即视为有仓（防部分成交影子丢失后重复满仓）。"""
    pos = getattr(A, "position", None)
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) > 0


def _cb_lot(price, budget):
    lot = int(globals().get("LOT_SIZE") or 10)
    if price is None or price <= 0 or budget <= 0 or lot <= 0:
        return 0
    return int(float(budget) // (float(price) * lot)) * lot


def _remaining_buy_budget(cash):
    """预算扣减已持仓成本，防止部分成交后再按满额重挂。"""
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


def _entry_mode_of(pos=None):
    pos = pos if pos is not None else getattr(A, "position", None)
    if isinstance(pos, dict):
        m = str(pos.get("entry_mode", "") or "")
        if m:
            return m
        intent = str(pos.get("intent", "") or "")
        if intent in ("SZ_AM", "SH_AM"):
            return "A"
        if intent in ("SZ_PREPLACE", "SZ_CLOSE", "SH_OPEN", "SH_CHASE"):
            return "B"
    m = str(getattr(A, "entry_mode", "") or "")
    return m


def _is_mode_a_pos():
    return _entry_mode_of() == "A"


def _is_mode_b_pos():
    return _entry_mode_of() == "B"


def _pos_opened_day():
    pos = getattr(A, "position", None)
    if not isinstance(pos, dict):
        return ""
    ot = str(pos.get("opened_at", "") or "")
    return ot[:8] if len(ot) >= 8 else ""


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
    entry_mode = str(extra.get("entry_mode") or "")
    if not entry_mode:
        if intent in ("SZ_AM", "SH_AM"):
            entry_mode = "A"
        elif intent in ("SZ_PREPLACE", "SZ_CLOSE", "SH_OPEN", "SH_CHASE"):
            entry_mode = "B"
    pos = {
        "shares": new_sh,
        "price": avg,
        "cost": round(new_cost, 2),
        "opened_at": ot
        if prev_sh <= 0
        else str((prev or {}).get("opened_at") or ot),
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
    # 可转债 T+0：回测不锁仓
    if getattr(A, "is_backtest", False):
        A.bt_locked = 0
    day = buy_day or ""
    if day:
        A.buy_done_day = day
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position, "add_vol=", vol, "lot=", lot)
    _event_log(
        "buy_filled",
        position=A.position,
        vol=vol,
        price=price,
        opened_at=ot,
        add_vol=vol,
        entry_mode=entry_mode,
    )


def _apply_cb_sell_fill(now, reason, last_hint, filled_vol, mark_half=False):
    lot = int(globals().get("LOT_SIZE") or 10)
    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    filled_vol = int(filled_vol)
    if filled_vol < lot:
        return
    if filled_vol >= max(lot, int(want * 0.95)) or filled_vol >= want:
        _clear_after_sell(now, reason, last=last_hint)
        A.entry_mode = ""
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
    if remain < lot:
        _clear_after_sell(now, str(reason) + "/partial", last=last_hint)
        A.entry_mode = ""
    else:
        if mark_half:
            A.acted.add("HALF")
        _save_state()


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_cb_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _pending_on_sell_fill(pend, now, vol, px):
    intent = str(pend.get("intent", "") or "")
    last_hint = pend.get("last_hint")
    if last_hint is None:
        last_hint = px
    mark_half = bool(pend.get("mark_half"))
    _apply_cb_sell_fill(now, intent, last_hint, vol, mark_half=mark_half)


def _max_sell_vol(now=None):
    """可转债 T+0：当日买入亦可卖（回测/DRY 不套用股票 T+1）。"""
    want = _pos_shares()
    lot = int(globals().get("LOT_SIZE") or 10)
    if getattr(A, "is_backtest", False):
        held = max(want, _bt_held_vol())
        return max(0, held)
    if want < lot:
        return 0
    if DRY_RUN:
        return want
    broker_vol, can, _cost = _broker_position(A.stock)
    return max(0, min(want, int(can), int(broker_vol)))


def _order_buy_limit(C, price, now, budget=None, intent="BUY", entry_mode=None):
    """限价买入 prType=11。"""
    lot = int(globals().get("LOT_SIZE") or 10)
    price = _px_round(price)
    if price <= 0:
        return False
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    if _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() > 0
    ):
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
        print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
        _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _cb_lot(price, min(budget, float(cash)))
        if vol < lot:
            print(_strategy_tag(), "buy skip cash", cash)
            _event_log("buy_skip", reason="cash", cash=cash, price=price)
            return False

    if not entry_mode:
        if intent in ("SZ_AM", "SH_AM"):
            entry_mode = "A"
        elif intent in ("SZ_PREPLACE", "SZ_CLOSE", "SH_OPEN", "SH_CHASE"):
            entry_mode = "B"
    extra_pos = {"intent": intent}
    if entry_mode:
        extra_pos["entry_mode"] = entry_mode

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark(intent, "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price, intent)
    exempt = set(str(x) for x in (globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()))
    no_timeout = str(intent) in exempt
    if DRY_RUN:
        # VERIFY 开盘竞价：130 不会触达 DRY_RUN_FILL_ON_LIMIT，须模拟抢筹成交才能验 ModeA 卖出
        fill_now = bool(globals().get("DRY_RUN_FILL_IMMEDIATE", False))
        if (not fill_now) and intent in ("SZ_AM", "SH_AM") and _verify_any_day():
            fill_now = True
        if fill_now:
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
        A.buy_done_day = ot[:8]
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
            dry_keep=True,
            entry_mode=entry_mode,
        )
        if (
            bool(globals().get("DRY_RUN_FILL_ON_LIMIT", True))
            and price + 1e-9 >= _limit_up()
        ):
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
            1,
            msg,
            C,
        )
    except Exception as e:
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
    A.buy_done_day = ot[:8]
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


def _order_sell_limit(C, reason, price, now, want_vol=None):
    """限价卖出 prType=11；可转债 T+0 + LOT_SIZE。"""
    lot = int(globals().get("LOT_SIZE") or 10)
    price = _px_round(price)
    if price <= 0:
        return False
    if getattr(A, "pending", None):
        print(_strategy_tag(), "sell skip: pending active")
        _event_log("sell_skip", reason="pending_active", sell_reason=reason)
        return False
    if not _has_position() and not (
        getattr(A, "is_backtest", False) and _bt_held_vol() > 0
    ):
        return False
    if "SELL" in getattr(A, "acted", set()):
        return False

    want = int(want_vol) if want_vol is not None else _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol()) if want_vol is None else want
    if want < lot:
        return False

    avail = _max_sell_vol(now)
    vol = int(min(want, avail) // lot) * lot
    if vol < lot:
        print(
            _strategy_tag(),
            "sell skip avail",
            reason,
            "avail=",
            avail,
            "want=",
            want,
        )
        _event_log(
            "sell_skip",
            reason="avail",
            sell_reason=reason,
            avail=avail,
            want=want,
        )
        return False

    msg = _new_remark(reason or "SELL", "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price, reason)
    exempt = set(str(x) for x in (globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()))
    no_timeout = str(reason) in exempt
    if DRY_RUN:
        if bool(globals().get("DRY_RUN_FILL_IMMEDIATE", False)):
            _apply_cb_sell_fill(now, reason, price, vol)
            return True
        A.pending = {
            "remark": msg,
            "side": "sell",
            "intent": reason or "SELL",
            "vol": int(vol),
            "stock": A.stock,
            "price_hint": float(price),
            "last_hint": float(price),
            "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
            "cancel_requested": False,
            "no_timeout": no_timeout,
            "dry_keep": True,
            "mark_half": False,
        }
        A.sh_last_order_px = float(price)
        _save_state()
        print(_strategy_tag(), "DRY sell pending", vol, "@", price, reason)
        _event_log(
            "sell_submitted",
            vol=vol,
            price=price,
            sell_reason=reason,
            dry_run=True,
            dry_keep=True,
        )
        if (
            bool(globals().get("DRY_RUN_FILL_ON_LIMIT", True))
            and price + 1e-9 >= _limit_up()
        ):
            # 卖出挂顶格：DRY 下视为对手盘吃掉
            _apply_cb_sell_fill(now, reason, price, vol)
            A.pending = None
            _save_state()
            print(_strategy_tag(), "DRY sell fill on limit", price)
        return True
    try:
        passorder(
            A.sell_code,
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
        print(_strategy_tag(), "passorder SELL limit fail", e)
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
        _apply_cb_sell_fill(now, reason, price, vol)
        return True
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": reason or "SELL",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "last_hint": float(price),
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
        "no_timeout": no_timeout,
        "mark_half": False,
    }
    A.sh_last_order_px = float(price)
    _save_state()
    print(_strategy_tag(), "SELL submitted limit", vol, "@", price, reason, msg)
    _event_log(
        "sell_submitted",
        vol=vol,
        price=price,
        sell_reason=reason,
        remark=msg,
        dry_run=False,
    )
    return True


def _order_sell_mkt(C, reason, now, want_vol=None):
    """市价/对手方卖出（次日止盈止损）；prType=14。"""
    lot = int(globals().get("LOT_SIZE") or 10)
    if getattr(A, "pending", None):
        print(_strategy_tag(), "sell skip: pending active")
        _event_log("sell_skip", reason="pending_active", sell_reason=reason)
        return False
    if not _has_position() and not (
        getattr(A, "is_backtest", False) and _bt_held_vol() > 0
    ):
        return False
    if "SELL" in getattr(A, "acted", set()):
        return False

    want = int(want_vol) if want_vol is not None else _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol()) if want_vol is None else want
    if want < lot:
        return False
    avail = _max_sell_vol(now)
    vol = int(min(want, avail) // lot) * lot
    if vol < lot:
        print(_strategy_tag(), "sell skip avail", reason, "avail=", avail)
        _event_log("sell_skip", reason="avail", sell_reason=reason, avail=avail)
        return False

    msg = _new_remark(reason or "SELL", "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@mkt", reason)
    if DRY_RUN:
        _apply_cb_sell_fill(now, reason, 0.0, vol)
        return True
    try:
        passorder(
            A.sell_code,
            1101,
            A.acct,
            A.stock,
            14,
            -1,
            vol,
            _strategy_tag(),
            1,
            msg,
            C,
        )
    except Exception as e:
        print(_strategy_tag(), "passorder SELL mkt fail", e)
        _event_log("passorder_fail", side="sell", error=str(e), vol=vol, sell_reason=reason)
        return False
    if getattr(A, "is_backtest", False):
        _apply_cb_sell_fill(now, reason, 0.0, vol)
        return True
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": reason or "SELL",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": 0.0,
        "last_hint": 0.0,
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
        "mark_half": False,
    }
    _save_state()
    print(_strategy_tag(), "SELL submitted mkt", vol, reason, msg)
    _event_log("sell_submitted", vol=vol, sell_reason=reason, remark=msg, dry_run=False)
    return True


def _request_pending_cancel(C, now, reason):
    """主动撤当前 pending；未见委托时不打 cancel_requested，避免永久卡住。"""
    pend = getattr(A, "pending", None)
    if not isinstance(pend, dict):
        return False
    if pend.get("cancel_requested"):
        return True
    if DRY_RUN and bool(pend.get("dry_keep")):
        print(_strategy_tag(), "DRY cancel", reason, "px=", pend.get("price_hint"))
        _event_log(
            "chase_cancel",
            reason=reason,
            price=pend.get("price_hint"),
            remark=pend.get("remark"),
            dry=True,
        )
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
    _event_log(
        "chase_cancel",
        reason=reason,
        price=pend.get("price_hint"),
        remark=remark,
        order_seen=True,
    )
    return True


def _reconcile_with_broker():
    """实盘启动/暖机切活：用券商持仓校正影子仓，防状态丢失后重复买。"""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return
    if _available_cash() is None:
        print(_strategy_tag(), "reconcile skip: not login")
        _event_log("reconcile_skip", reason="not_login")
        return
    lot = int(globals().get("LOT_SIZE") or 10)
    stock = str(getattr(A, "stock", "") or "")
    try:
        positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    except Exception as e:
        print(_strategy_tag(), "reconcile position query fail", e)
        _event_log("reconcile_fail", error=str(e))
        return
    if positions is None:
        _event_log("reconcile_fail", error="positions_none")
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
            day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
            A.buy_done_day = day
            _save_state()
            print(_strategy_tag(), "reconcile sync from broker vol=", vol, "cost=", cost)
            _event_log("reconcile_sync", vol=vol, cost=cost)
        return
    if (not found or vol <= 0) and _has_position():
        print(
            _strategy_tag(),
            "reconcile clear shadow (broker flat) was=",
            A.position,
        )
        _event_log("reconcile_clear", was=A.position, broker_vol=vol, found=found)
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


def _now_ms_of_second(now):
    """当前秒内毫秒 0–999。"""
    if now is None:
        now = datetime.datetime.now()
    try:
        return int(now.microsecond // 1000)
    except Exception:
        return 0


def _listing_date_str(stock=None):
    stock = str(stock or getattr(A, "stock", "") or "")
    mp = globals().get("LISTING_DATE_MAP") or {}
    if stock in mp:
        return str(mp.get(stock) or "")
    return ""


def _is_eve_before_listing(C, now, day):
    """上市日前夜：LISTING_DATE_MAP 命中明日，或日K推断明日为首日。

    VERIFY 模式不把「每天晚上」当成前夜（否则任意日晚间乱挂 130）；
    仅当显式 LISTING_DATE_MAP 指向明日时仍允许验隔夜委托。
    """
    if now is None:
        return False
    try:
        tomorrow = (now + datetime.timedelta(days=1)).strftime("%Y%m%d")
    except Exception:
        return False
    mapped = _listing_date_str()
    if mapped:
        return mapped == tomorrow
    if _verify_any_day():
        return False
    try:
        return bool(_is_listing_day(C, tomorrow))
    except Exception:
        return False


def _morning_buy_price():
    cfg = globals().get("MORNING_BUY_PRICE")
    if cfg is not None:
        try:
            v = float(cfg)
            if v > 0:
                return _px_round(v)
        except Exception:
            pass
    return _px_round(globals().get("HALT_BASE_PRICE") or 130.0)


def _try_morning_buy(C, now, now_s, day):
    """模式A：深市隔夜/早盘挂 130；沪市卡点挂 130。

    VERIFY_AUCTION_ANY_DAY：任意交易日可走开盘竞价窗（沪市放宽至集合竞价时段、跳过毫秒卡点）。
    """
    if not bool(globals().get("ENABLE_MODE_A", True)):
        return False
    if _has_position() or getattr(A, "pending", None):
        return False
    if str(getattr(A, "am_buy_day", "") or "") == day:
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False

    mkt = _market_tag()
    px = _morning_buy_price()
    bt = getattr(A, "is_backtest", False)
    verify = _verify_any_day()

    if mkt == "SZ":
        eve_s = str(globals().get("SZ_AM_EVE_START") or "203000")
        eve_e = str(globals().get("SZ_AM_EVE_END") or "223000")
        am_s = str(globals().get("SZ_AM_BUY_START") or "000000")
        am_e = str(globals().get("SZ_AM_BUY_END") or "092459")
        ok = False
        if _in_window(now_s, am_s, am_e) and _is_listing_day(C, day):
            ok = True
        elif _in_window(now_s, eve_s, eve_e) and _is_eve_before_listing(C, now, day):
            ok = True
        if not ok:
            return False
        print(
            "%s SZ_AM buy @%.3f window listing/eve now=%s verify=%s"
            % (STRATEGY_NAME, px, now_s, verify)
        )
        _event_log("sz_am_buy", price=px, now_s=now_s, verify=verify)
        if _order_buy_limit(C, px, now, intent="SZ_AM", entry_mode="A"):
            A.am_buy_day = day
            A.buy_done_day = day
            _save_state()
            return True
        return False

    if mkt == "SH":
        if not _is_listing_day(C, day):
            return False
        if verify:
            am_s = str(globals().get("SH_AM_BUY_START_VERIFY") or "091500")
            am_e = str(globals().get("SH_AM_BUY_END_VERIFY") or "092459")
        else:
            am_s = str(globals().get("SH_AM_BUY_START") or "092459")
            am_e = str(globals().get("SH_AM_BUY_END") or "092459")
        if not _in_window(now_s, am_s, am_e):
            return False
        # 首日实盘毫秒卡点；回测 / VERIFY 联调跳过（1m 分辨率够不着 100ms）
        if (not bt) and (not verify):
            ms0 = int(globals().get("SH_AM_BUY_MS_START") or 850)
            ms1 = int(globals().get("SH_AM_BUY_MS_END") or 950)
            ms = _now_ms_of_second(now)
            if ms < ms0 or ms > ms1:
                return False
        print(
            "%s SH_AM buy @%.3f card-point now=%s ms=%s verify=%s"
            % (STRATEGY_NAME, px, now_s, _now_ms_of_second(now), verify)
        )
        _event_log(
            "sh_am_buy",
            price=px,
            now_s=now_s,
            ms=_now_ms_of_second(now),
            verify=verify,
        )
        if _order_buy_limit(C, px, now, intent="SH_AM", entry_mode="A"):
            A.am_buy_day = day
            A.buy_done_day = day
            _save_state()
            return True
        return False

    return False


def _cleanup_am_pending(C, now, now_s):
    """早盘未成：过 09:25 后撤单，腾出 Mode B。"""
    after = str(globals().get("AM_CANCEL_AFTER") or "092500")
    if str(now_s) < after:
        return False
    pend = getattr(A, "pending", None)
    if not isinstance(pend, dict):
        return False
    intent = str(pend.get("intent", "") or "")
    if intent not in ("SZ_AM", "SH_AM"):
        return False
    if pend.get("cancel_requested"):
        return True
    print("%s AM cancel unfilled intent=%s" % (STRATEGY_NAME, intent))
    _event_log("am_cancel", intent=intent, now_s=now_s)
    return _request_pending_cancel(C, now, "am_unfilled")


def _handle_sz_sell(C, now, now_s, day, last_px):
    """模式A 深市：封板后以 157.30 卖出。"""
    if not bool(globals().get("ENABLE_MODE_A", True)):
        return
    start = str(globals().get("SELL_START") or "145700")
    end = str(globals().get("SELL_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if str(getattr(A, "sz_sell_day", "") or "") == day:
        return
    if not _has_position() or not _is_mode_a_pos():
        return
    limit_up = _limit_up()
    # VERIFY：非首日盘面不会封板，跳过 last>=157.30 门闩，只验卖出通道
    if (not _verify_any_day()) and last_px + 1e-9 < limit_up:
        if C.barpos % 5 == 0:
            print(
                "%s SZ_SELL wait limit_up last=%.3f need=%.3f"
                % (STRATEGY_NAME, last_px, limit_up)
            )
        return
    print(
        "%s SZ_SELL @%.3f last=%.3f verify=%s"
        % (STRATEGY_NAME, limit_up, last_px, _verify_any_day())
    )
    _event_log("sz_sell", price=limit_up, last=last_px, verify=_verify_any_day())
    if _order_sell_limit(C, "SZ_SELL", limit_up, now):
        A.sz_sell_day = day
        _save_state()


def _handle_sh_sell_chase(C, now, now_s, day, last_px):
    """模式A 沪市：从笼子上限阶梯追卖至 157.30。"""
    if not bool(globals().get("ENABLE_MODE_A", True)):
        return
    start = str(globals().get("SELL_START") or "145700")
    end = str(globals().get("SELL_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if not _has_position() or not _is_mode_a_pos():
        return

    reopen = _reopen_cap()
    limit_up = _limit_up()
    target = _cage_cap(last_px if last_px > 0 else reopen)
    if target < reopen:
        target = reopen
    interval = float(globals().get("SH_CHASE_INTERVAL_MS") or 50)
    min_step = float(globals().get("CHASE_MIN_STEP") or 0.01)
    now_ms = _now_ms(now)
    pend = getattr(A, "pending", None)

    if isinstance(pend, dict):
        last_ms = float(getattr(A, "sh_chase_at_ms", 0) or 0)
        if last_ms > 0 and (now_ms - last_ms) < interval:
            if not pend.get("cancel_requested"):
                return
        side = str(pend.get("side", "") or "")
        if side != "sell":
            return
        old_px = float(pend.get("price_hint") or 0)
        if old_px + 1e-9 >= limit_up:
            return
        if target > old_px + min_step:
            if not pend.get("cancel_requested"):
                A.sh_chase_at_ms = now_ms
                print(
                    "%s SH_SELL_CHASE cancel->%.3f old=%.3f last=%.3f"
                    % (STRATEGY_NAME, target, old_px, last_px)
                )
                _event_log(
                    "sh_sell_chase",
                    target=target,
                    old=old_px,
                    last=last_px,
                )
                _request_pending_cancel(C, now, "sell_cage_up")
                if getattr(A, "pending", None):
                    return
            else:
                return
        else:
            return

    if "SELL" in getattr(A, "acted", set()):
        return
    if str(getattr(A, "sh_sell_day", "") or "") == day and not getattr(A, "pending", None):
        # 已挂过且无 pending：可能已成交或废单；有仓则允许继续追
        pass

    A.sh_chase_at_ms = now_ms
    intent = "SH_SELL" if target + 1e-9 >= limit_up else "SH_SELL_CHASE"
    print(
        "%s %s @%.3f last=%.3f"
        % (STRATEGY_NAME, intent, target, last_px)
    )
    _event_log("sh_sell", intent=intent, price=target, last=last_px)
    if _order_sell_limit(C, intent, target, now):
        A.sh_sell_day = day
        A.sh_last_order_px = float(target)
        _save_state()


def _handle_sz_mode_b(C, now, now_s, day, last_px):
    """深市 Mode B：临停埋 143 → 封板后撤未成单再挂 157.30。"""
    if not bool(globals().get("ENABLE_MODE_B", True)):
        return
    reopen = _reopen_cap()
    limit_up = _limit_up()
    pre_s = str(globals().get("SZ_PREPLACE_START") or "130000")
    pre_e = str(globals().get("SZ_PREPLACE_END") or "145459")
    close_s = str(globals().get("SZ_CLOSE_BUY_START") or "145700")
    close_e = str(globals().get("SZ_CLOSE_BUY_END") or "145950")
    alert_sec = float(globals().get("SZ_ESCALATE_ALERT_SEC") or 2.0)

    if _in_window(now_s, pre_s, pre_e):
        if str(getattr(A, "sz_preplace_day", "") or "") == day:
            return
        if _has_position() or getattr(A, "pending", None):
            return
        print(
            "%s SZ_PREPLACE buy @%.3f window=%s-%s (禁挂涨停顶格)"
            % (STRATEGY_NAME, reopen, pre_s, pre_e)
        )
        _event_log("sz_preplace", price=reopen, window="%s-%s" % (pre_s, pre_e))
        if _order_buy_limit(C, reopen, now, intent="SZ_PREPLACE", entry_mode="B"):
            A.sz_preplace_day = day
            A.buy_done_day = day
            _save_state()
        return

    if not _in_window(now_s, close_s, close_e):
        return
    if str(getattr(A, "sz_close_buy_day", "") or "") == day:
        return
    if _has_position():
        return
    if last_px + 1e-9 < limit_up:
        if C.barpos % 5 == 0:
            print(
                "%s SZ_CLOSE wait limit_up last=%.3f need=%.3f"
                % (STRATEGY_NAME, last_px, limit_up)
            )
        return

    pend = getattr(A, "pending", None)
    if isinstance(pend, dict):
        intent = str(pend.get("intent", "") or "")
        old_px = float(pend.get("price_hint") or 0)
        if not pend.get("cancel_requested"):
            A.sz_escalate_day = day
            print(
                "%s SZ_ESCALATE cancel old=%.3f intent=%s -> then @%.3f"
                % (STRATEGY_NAME, old_px, intent, limit_up)
            )
            _event_log(
                "sz_escalate_cancel",
                old=old_px,
                intent=intent,
                target=limit_up,
                last=last_px,
            )
            _request_pending_cancel(C, now, "sz_escalate_to_limit")
            A.sz_escalate_alert_ms = _now_ms(now)
            _save_state()
            if getattr(A, "pending", None):
                return
            pend = None
        else:
            now_ms = _now_ms(now)
            last_alert = float(getattr(A, "sz_escalate_alert_ms", 0) or 0)
            if last_alert <= 0 or (now_ms - last_alert) >= alert_sec * 1000.0:
                A.sz_escalate_alert_ms = now_ms
                print(
                    "%s SZ_ESCALATE ALERT: 143未撤掉无法挂157.30 pending=%s "
                    "px=%.3f - 若已进收盘竞价请人工处理"
                    % (STRATEGY_NAME, intent, old_px)
                )
                _event_log(
                    "sz_escalate_alert",
                    intent=intent,
                    price=old_px,
                    last=last_px,
                    cancel_requested=True,
                )
                _save_state()
            return

    if isinstance(pend, dict):
        return

    print(
        "%s SZ_CLOSE buy @%.3f last=%.3f window=%s-%s"
        % (STRATEGY_NAME, limit_up, last_px, close_s, close_e)
    )
    _event_log(
        "sz_close_buy",
        price=limit_up,
        last=last_px,
        window="%s-%s" % (close_s, close_e),
        escalated=str(getattr(A, "sz_escalate_day", "") or "") == day,
    )
    if _order_buy_limit(C, limit_up, now, intent="SZ_CLOSE", entry_mode="B"):
        A.sz_close_buy_day = day
        A.buy_done_day = day
        _save_state()


def _handle_sh_mode_b(C, now, now_s, day, last_px):
    """沪市 Mode B：143 起阶梯追至 157.30。"""
    if not bool(globals().get("ENABLE_MODE_B", True)):
        return
    start = str(globals().get("SH_CHASE_START") or "145700")
    end = str(globals().get("SH_CHASE_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if _has_position():
        return

    reopen = _reopen_cap()
    limit_up = _limit_up()
    target = _cage_cap(last_px if last_px > 0 else reopen)
    if target < reopen:
        target = reopen
    interval = float(globals().get("SH_CHASE_INTERVAL_MS") or 50)
    min_step = float(globals().get("CHASE_MIN_STEP") or 0.01)
    now_ms = _now_ms(now)
    pend = getattr(A, "pending", None)
    if isinstance(pend, dict):
        last_ms = float(getattr(A, "sh_chase_at_ms", 0) or 0)
        if last_ms > 0 and (now_ms - last_ms) < interval:
            if pend.get("cancel_requested"):
                pass
            else:
                return

    if isinstance(pend, dict):
        old_px = float(pend.get("price_hint") or 0)
        if old_px + 1e-9 >= limit_up:
            return
        if target > old_px + min_step:
            if not pend.get("cancel_requested"):
                A.sh_chase_at_ms = now_ms
                print(
                    "%s SH_CHASE cancel->%.3f old=%.3f last=%.3f"
                    % (STRATEGY_NAME, target, old_px, last_px)
                )
                _event_log("sh_chase", target=target, old=old_px, last=last_px)
                _request_pending_cancel(C, now, "cage_up")
                if getattr(A, "pending", None):
                    return
            else:
                if C.barpos % 3 == 0:
                    print(
                        "%s SH_CHASE wait cancel old=%.3f target=%.3f"
                        % (STRATEGY_NAME, old_px, target)
                    )
                return
        else:
            return

    if "BUY" in getattr(A, "acted", set()):
        return
    A.sh_chase_at_ms = now_ms
    intent = "SH_OPEN" if str(getattr(A, "sh_chase_day", "") or "") != day else "SH_CHASE"
    print(
        "%s %s buy @%.3f last=%.3f cage=%.3f"
        % (STRATEGY_NAME, intent, target, last_px, target)
    )
    _event_log("sh_buy", intent=intent, price=target, last=last_px)
    if _order_buy_limit(C, target, now, intent=intent, entry_mode="B"):
        A.sh_chase_day = day
        A.sh_last_order_px = float(target)
        A.buy_done_day = day
        _save_state()


def _underlying_open_gap(C, day, cb_open, cost):
    """正股开盘涨跌幅；无映射则用转债相对成本。"""
    stock = str(getattr(A, "stock", "") or "")
    mp = globals().get("UNDERLYING_MAP") or {}
    und = str(mp.get(stock) or "").strip()
    if und:
        try:
            md = C.get_market_data_ex(
                fields=["open", "close"],
                stock_code=[und],
                period="1d",
                end_time=str(day),
                count=3,
                dividend_type="none",
                fill_data=False,
                subscribe=False,
            )
            opens = _series_from_ex(md, und, "open")
            closes = _series_from_ex(md, und, "close")
            if opens is not None and closes is not None and len(opens) >= 1:
                o = float(opens[-1])
                prev = float(closes[-2]) if len(closes) >= 2 else float(closes[-1])
                if prev > 0 and o > 0:
                    return (o / prev) - 1.0, "underlying"
        except Exception as e:
            _diag_once("underlying_gap_fail", e)
    if cost and cost > 0 and cb_open and cb_open > 0:
        return (float(cb_open) / float(cost)) - 1.0, "cb_vs_cost"
    return None, "none"


def _handle_day2_exit(C, now, now_s, day, last_px, open_px):
    """模式B 隔夜仓：次日高开锁利 / 移动止盈 / 低开止损。"""
    if not bool(globals().get("ENABLE_DAY2_EXIT", True)):
        return
    if not _has_position():
        return
    # Mode A 若首日未卖掉，次日也按同一退出规则处理
    opened = _pos_opened_day()
    if opened and opened >= day:
        return

    cost = float((getattr(A, "position", None) or {}).get("price", 0) or 0)
    if cost <= 0:
        cost = float(last_px or 0)

    # 记录次日开盘参考价
    if float(getattr(A, "d2_open_px", 0) or 0) <= 0 and open_px and open_px > 0:
        A.d2_open_px = float(open_px)
        _save_state()
    d2_open = float(getattr(A, "d2_open_px", 0) or 0) or float(open_px or 0)

    # 1) 集合竞价高开锁利
    auc_s = str(globals().get("D2_AUCTION_START") or "091500")
    auc_e = str(globals().get("D2_AUCTION_END") or "092459")
    gap_up = float(globals().get("D2_GAP_UP_MIN") or 0.05)
    if (
        _in_window(now_s, auc_s, auc_e)
        and str(getattr(A, "d2_auction_day", "") or "") != day
    ):
        ref = d2_open if d2_open > 0 else last_px
        if cost > 0 and ref > 0 and (ref / cost - 1.0) >= gap_up:
            print(
                "%s D2_AUCTION sell gap=%.2f%% ref=%.3f cost=%.3f"
                % (STRATEGY_NAME, (ref / cost - 1.0) * 100.0, ref, cost)
            )
            _event_log("d2_auction_sell", ref=ref, cost=cost, gap=ref / cost - 1.0)
            if _order_sell_limit(C, "D2_AUCTION", _px_round(ref), now) or _order_sell_mkt(
                C, "D2_AUCTION", now
            ):
                A.d2_auction_day = day
                _save_state()
            return

    # 2) 09:30 低开止损（正股或转债自身）
    trail_s = str(globals().get("D2_TRAIL_START") or "093000")
    gap_dn = float(globals().get("D2_GAP_DOWN_STOP") or -0.02)
    if (
        str(now_s) >= trail_s
        and str(getattr(A, "d2_stop_day", "") or "") != day
        and str(now_s) <= str(globals().get("D2_TRAIL_END") or "093500")
    ):
        gap, src = _underlying_open_gap(C, day, d2_open or open_px, cost)
        if gap is not None and gap <= gap_dn:
            print(
                "%s D2_STOP sell gap=%.2f%% src=%s"
                % (STRATEGY_NAME, gap * 100.0, src)
            )
            _event_log("d2_stop_sell", gap=gap, src=src)
            if _order_sell_mkt(C, "D2_STOP", now):
                A.d2_stop_day = day
                _save_state()
            return

    # 3) 开盘后移动止盈：自最高点回撤
    trail_e = str(globals().get("D2_TRAIL_END") or "093500")
    dd = float(globals().get("D2_TRAIL_DRAWDOWN") or 0.015)
    if _in_window(now_s, trail_s, trail_e):
        hi = float(getattr(A, "d2_day_high", 0) or 0)
        if last_px > hi:
            A.d2_day_high = float(last_px)
            hi = float(last_px)
            _save_state()
        if (
            hi > 0
            and last_px > 0
            and (hi - last_px) / hi >= dd
            and str(getattr(A, "d2_trail_day", "") or "") != day
        ):
            print(
                "%s D2_TRAIL sell hi=%.3f last=%.3f dd=%.2f%%"
                % (STRATEGY_NAME, hi, last_px, ((hi - last_px) / hi) * 100.0)
            )
            _event_log("d2_trail_sell", high=hi, last=last_px, dd=(hi - last_px) / hi)
            if _order_sell_mkt(C, "D2_TRAIL", now):
                A.d2_trail_day = day
                _save_state()


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
                pass
            else:
                pass
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
    bar_last = float(closes[-1])
    open_px = float(opens[-1])
    last_px = _tick_last(C, fallback=bar_last)
    if last_px <= 0:
        last_px = _px_round(bar_last)

    if bt:
        _bt_recover_position(now=now, last=last_px)

    holding = _has_position() or (bt and _bt_held_vol() > 0)
    mkt = _market_tag()
    size_yi = _issue_size_yi()

    interesting = holding or getattr(A, "pending", None) or (
        str(getattr(A, "buy_done_day", "") or "") == day
    )
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 30 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            now_s,
            "mkt=%s n=%d last=%.3f open=%.3f hold=%s mode=%s size=%s "
            "buy_done=%s pending=%s cage=%.3f"
            % (
                mkt,
                len(closes),
                last_px,
                open_px,
                holding,
                _entry_mode_of(),
                size_yi,
                getattr(A, "buy_done_day", ""),
                bool(getattr(A, "pending", None)),
                _cage_cap(last_px),
            ),
        )
        _bar_log(
            day=day,
            hhmmss=now_s,
            n=len(closes),
            last=round(last_px, 6),
            open=round(open_px, 6),
            hold=holding,
            mkt=mkt,
            size_yi=size_yi,
            buy_done=str(getattr(A, "buy_done_day", "") or ""),
            tag=tag,
        )

    # ---- 持仓：Mode A 复牌卖 / Mode B 次日出局 ----
    if holding:
        if "SELL" in getattr(A, "acted", set()) and (not getattr(A, "pending", None)):
            return
        opened = _pos_opened_day()
        if opened and opened < day:
            _handle_day2_exit(C, now, now_s, day, last_px, open_px)
            return
        if _is_listing_day(C, day) or _verify_any_day():
            if mkt == "SZ":
                _handle_sz_sell(C, now, now_s, day, last_px)
            elif mkt == "SH":
                _handle_sh_sell_chase(C, now, now_s, day, last_px)
        return

    if ("BUY" in getattr(A, "acted", set())) and (not getattr(A, "pending", None)):
        return

    listing = _is_listing_day(C, day)
    eve = _is_eve_before_listing(C, now, day)
    if (not listing) and (not eve):
        if C.barpos % 60 == 0:
            print("%s skip: not listing day" % STRATEGY_NAME, day, A.stock)
            _event_log("skip_not_listing_day", day=day, stock=A.stock)
        return

    # ---- Mode A 早盘 ----
    if _try_morning_buy(C, now, now_s, day):
        return

    # 早盘未成：撤单腾出 Mode B
    if _cleanup_am_pending(C, now, now_s):
        if getattr(A, "pending", None):
            return

    if not listing:
        return

    if mkt == "SZ":
        _handle_sz_mode_b(C, now, now_s, day, last_px)
    elif mkt == "SH":
        _handle_sh_mode_b(C, now, now_s, day, last_px)
    else:
        if C.barpos % 60 == 0:
            print("%s unknown market stock=%s" % (STRATEGY_NAME, A.stock))
            _event_log("unknown_market", stock=A.stock)

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


def _ensure_day_flags():
    if not hasattr(A, "buy_done_day"):
        A.buy_done_day = ""
    if not hasattr(A, "am_buy_day"):
        A.am_buy_day = ""
    if not hasattr(A, "sz_preplace_day"):
        A.sz_preplace_day = ""
    if not hasattr(A, "sz_close_buy_day"):
        A.sz_close_buy_day = ""
    if not hasattr(A, "sz_escalate_day"):
        A.sz_escalate_day = ""
    if not hasattr(A, "sz_escalate_alert_ms"):
        A.sz_escalate_alert_ms = 0.0
    if not hasattr(A, "sz_sell_day"):
        A.sz_sell_day = ""
    if not hasattr(A, "sh_chase_day"):
        A.sh_chase_day = ""
    if not hasattr(A, "sh_last_order_px"):
        A.sh_last_order_px = 0.0
    if not hasattr(A, "sh_chase_at_ms"):
        A.sh_chase_at_ms = 0.0
    if not hasattr(A, "sh_sell_day"):
        A.sh_sell_day = ""
    if not hasattr(A, "d2_auction_day"):
        A.d2_auction_day = ""
    if not hasattr(A, "d2_stop_day"):
        A.d2_stop_day = ""
    if not hasattr(A, "d2_trail_day"):
        A.d2_trail_day = ""
    if not hasattr(A, "d2_day_high"):
        A.d2_day_high = 0.0
    if not hasattr(A, "d2_open_px"):
        A.d2_open_px = 0.0
    if not hasattr(A, "entry_mode"):
        A.entry_mode = ""


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
            A.am_buy_day = ""
            A.sz_preplace_day = ""
            A.sz_close_buy_day = ""
            A.sz_escalate_day = ""
            A.sz_escalate_alert_ms = 0.0
            A.sz_sell_day = ""
            A.sh_chase_day = ""
            A.sh_last_order_px = 0.0
            A.sh_chase_at_ms = 0.0
            A.sh_sell_day = ""
            A.d2_auction_day = ""
            A.d2_stop_day = ""
            A.d2_trail_day = ""
            A.d2_day_high = 0.0
            A.d2_open_px = 0.0
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

    size_yi = _issue_size_yi()
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
        "modeA=",
        bool(globals().get("ENABLE_MODE_A", True)),
        "modeB=",
        bool(globals().get("ENABLE_MODE_B", True)),
        "day2=",
        bool(globals().get("ENABLE_DAY2_EXIT", True)),
        "am_px=",
        _morning_buy_price(),
        "reopen_cap=",
        _reopen_cap(),
        "limit_up=",
        _limit_up(),
        "size_yi=",
        size_yi,
        "sz_pre=",
        "%s-%s" % (SZ_PREPLACE_START, SZ_PREPLACE_END),
        "sz_close=",
        "%s-%s" % (SZ_CLOSE_BUY_START, SZ_CLOSE_BUY_END),
        "sh_chase=",
        "%s-%s" % (SH_CHASE_START, SH_CHASE_END),
        "chase_ms=",
        SH_CHASE_INTERVAL_MS,
        "any_day=",
        bool(globals().get("VERIFY_AUCTION_ANY_DAY", False))
        or bool(globals().get("FORCE_RUN", False))
        or (not bool(globals().get("LISTING_DAY_ONLY", True))),
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
        size_yi=size_yi,
        mode_a=bool(globals().get("ENABLE_MODE_A", True)),
        mode_b=bool(globals().get("ENABLE_MODE_B", True)),
        day2=bool(globals().get("ENABLE_DAY2_EXIT", True)),
        reopen_cap=_reopen_cap(),
        limit_up=_limit_up(),
        verify_any_day=bool(globals().get("VERIFY_AUCTION_ANY_DAY", False)),
        force_run=bool(globals().get("FORCE_RUN", False)),
        listing_day_only=bool(globals().get("LISTING_DAY_ONLY", True)),
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
