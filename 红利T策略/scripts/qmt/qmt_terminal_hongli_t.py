#coding:gbk
# 由 _deploy_qmt_gbk.py 自动生成；请勿手改。请编辑策略片段与 scripts/qmt_common/ 后重新部署。
import datetime
import json
import os
import traceback

import numpy as np


# === hongli/_header.py ===
# 作用: 策略总览注释（规则/风控/实盘与回测约定），无可执行代码
# 主要符号: 仅注释
# 拼接序: 1/16 | 上一部: - | 下一部: config.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
#
# HongliT v2.19 — 国金 QMT 终端模型交易。
#
# 主图标的: 561580.SH；PERIOD 见 config，或 "follow" 跟随主图周期。
# 界面: 选标的 + 账号，用实盘模式（非模拟）才会真正下单。
#
# 规则:
#   R-A   零浮仓 + 下轨 + J<=0     -> 买 Float A（FLOAT_A_BUDGET）
#   R-B   已有 A + 下轨 + J<=0 + 跌幅>=2.5%  -> 买 Float B（FLOAT_B_BUDGET），否则跳过
#   R-Sell 上轨 + J>=100                    -> 清全部浮仓 A/B
#   无 R1
#
# 风控档（USE_RISK_RULES=True 时任意 PERIOD 生效）:
#   - ENABLE_FLOAT_B=False      -> 关闭 R-B（仅 A）
#   - EXIT_AFTER                -> 延后 R-Sell/MaxHold 至 HHMMSS；""=关；仅日内
#   - STOP_LOSS_IGNORE_EXIT_AFTER -> 止损可早于 EXIT_AFTER 触发
#   - MAX_HOLD_DAYS             -> 软最长持仓（仅亏损）日历日；0=关
#   - MAX_HOLD_HARD_DAYS        -> 硬性到期强平（含盈利）；0=关
#   - COOLDOWN_BARS / LOSS      -> 卖出后冷却；根数 * PERIOD 时长 -> 墙钟截止
#   - NO_ENTRY_AFTER            -> 该时刻起禁止新开 R-A；""=关；仅日内
#   - STOP_LOSS                 -> 相对浮仓均价软止损；0=关
#   - REQUIRE_ABOVE_DAILY_MA    -> 仅当日线收盘 > MA(DAILY_MA_N) 时开仓
#   - DAILY_MA_N                -> 均线周期（如 10/20/60）
#
# 实盘委托安全 (v2.19):
#   - 浮仓状态仅成交后更新（pending）；DRY_RUN 即时；回测 passorder+即时
#   - init 用券商持仓对齐 JSON 浮仓（有 pending 则跳过）；BASE_SHARES 永不吸纳/卖出
#   - pending 超时先撤单；仅终态后清空（防双单）
#   - 15:00 后仍处理 pending（晚成交/撤单）
#   - 卖出部分成交保留当日剩余可卖（不标记 acted SELL）
#   - 冷却存墙钟时间（模型重启仍有效）
#   - 实盘 T+1: 卖量 = min(浮仓, m_nCanUseVolume)；可卖<100 则跳过并保留浮仓
#   - init 全包 try/except；历史下载起点钳制（VIP 最早日期）
#   - 实盘心跳 LIVE_HEARTBEAT_SEC，避免 UI 静默被当成已停
#   - 每根 handlebar 刷新 is_backtest；国金暖机->实盘追赶检测
#
# 回测安全 (v2.19):
#   - 运行中途 init 不得清空浮仓（曾导致孤儿双开 R-A）
#   - 影子 bt_held 跟踪 passorder 成交；有持仓则拦 R-A；卖出清空 held
#   - T+1: bt_locked = 当日买入（R-A/R-B）；仅可卖部分可卖；QMT 会跳过时绝不清仓
#   - 回测不读写 STATE_FILE（仅内存）
#
# 注意:
#   - 部署产物编码=GBK，首行 #coding:gbk
#   - 本策略只交易浮仓 A/B；账户另有底仓时设 BASE_SHARES
#   - DRY_RUN=True 只打印；False 才 passorder
#   - 回测前在 QMT 数据管理下载对应周期历史
#   - 模型交易: 期望 BACKTEST=False 且常驻；部署后需重新编译

# === hongli/config.py ===
# 作用: 用户可调参数与周期/委托常量
# 主要符号: DRY_RUN, FLOAT_*_BUDGET, USE_RISK_RULES, STATE_FILE, _ORDER_*
# 拼接序: 2/16 | 上一部: _header.py | 下一部: ctx.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
# ===================== 用户配置 =====================
DRY_RUN = True

STRATEGY_NAME = "HongliT"
STRATEGY_VER = "v2.5"

# 未从模型交易界面启动时的兜底（无 account/accountType 注入）
ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

FLOAT_A_BUDGET = 500.0
FLOAT_B_BUDGET = 500.0
SPACE_STEP = 0.025

BOLL_N = 20
BOLL_K = 2.0
KDJ_N = 9
LOWER_TOL = 1.002
UPPER_TOL = 0.998

# K 线周期（指标 / 决策）。
# "follow" = 跟随主图 C.period；或显式指定:
#   1m / 3m / 5m / 15m / 30m / 1h / 1d / 1w / 1mon / 1q / 1hy / 1y
PERIOD = "follow"
# 0 = 按周期自动根数；否则固定 OHLC 拉取根数
OHLC_COUNT = 0

# ---- 风控档（任意 PERIOD）----
# 总开关: False = 仅经典 R-A/B/Sell（无最长持仓/冷却/时段门/止损）。
USE_RISK_RULES = True
ENABLE_FLOAT_B = False      # False = 关闭 R-B（仅 A）；USE_RISK_RULES=False 时忽略（B 开启）
EXIT_AFTER = "100000"       # 延后 R-Sell/MaxHold 至 HHMMSS；""=关；仅日内
STOP_LOSS_IGNORE_EXIT_AFTER = True  # 止损可早于 EXIT_AFTER（防跳空）
MAX_HOLD_DAYS = 4           # 软: 持仓>=N 且浮仓亏损则强平；0=关
MAX_HOLD_ONLY_LOSS = True
MAX_HOLD_HARD_DAYS = 8      # 硬: 满 N 日一律强平（防漏单）；0=关
COOLDOWN_BARS = 16          # 盈利卖出后冷却；按 PERIOD 换成墙钟
COOLDOWN_BARS_LOSS = 28     # 亏损卖出后冷却
NO_ENTRY_AFTER = "143000"   # 该时刻起禁新开 R-A；""=关；仅日内
STOP_LOSS = 0.03            # 相对浮仓均价软止损；0=关
PENDING_TIMEOUT_SEC = 180   # 实盘: 未成交满 N 秒则请求撤单
PENDING_ORPHAN_SEC = 60     # 撤单请求后若始终无委托，清空 pending

# 预留底仓股数（本策略不吸纳、不卖出）
BASE_SHARES = 0

# 日线趋势过滤（任意周期的 R-A / R-B）
REQUIRE_ABOVE_DAILY_MA = True   # 仅当日线收盘 > MA(DAILY_MA_N) 时开仓
DAILY_MA_N = 20                 # 均线周期: 任意整数 >=2（10/20/60/...）
DAILY_MA_COUNT = 60             # 拉取根数；自动抬到 >= DAILY_MA_N+5

# 实盘决策窗（仅日线及以上；日内则交易时段每根都决策）
DECISION_START = "143000"
DECISION_END = "145700"

# 实盘心跳: 最新 K 上最多每 N 秒打印一次（0=关）
LIVE_HEARTBEAT_SEC = 60
# 钳制 download_history_data 起点，避免 VIP 最早日期导致模型中止
HIST_MAX_LOOKBACK_DAYS = 360
# 实盘: 默认不远程补历史（本地缓存 + get_market_data_ex）
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

# QMT 模型运行时无 __file__；使用终端 python/ 下固定路径
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
# 每根 K 对应墙钟分钟数（冷却根数 -> 时间）
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
# QMT 委托状态（覆盖常见 50 段与精简枚举）
_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)  # 已撤 / 废单 / 部撤终态

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

# === hongli/state_io.py ===
# 作用: 实盘浮仓状态 JSON 读写（回测不落盘）
# 主要符号: _load_state, _save_state
# 拼接序: 5/16 | 上一部: period.py | 下一部: backtest.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
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
        # 丢弃旧版按 barpos 的冷却（重启不安全）
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
    # 回测: 仅内存；避免覆盖实盘 JSON / 再 init 不同步
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

# === hongli/state.py ===
# 作用: 浮仓腿、风控门闩、冷却、缩仓
# 主要符号: _has_leg, _exit/_entry_time_ok, _set/_in_cooldown, _clear_float_*
# 拼接序: 7/16 | 上一部: backtest.py | 下一部: indicators.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _reset_day(day):
    if A.acted_day != day:
        A.acted_day = day
        A.acted = set()
        _save_state()


def _has_leg(leg):
    return leg is not None and int(leg.get("shares", 0)) >= 100


def _use_risk_rules():
    """风控档（最长持仓/冷却/止损/时段门/Float-B 开关）。任意 PERIOD。"""
    return bool(USE_RISK_RULES)


def _enable_float_b():
    if _use_risk_rules():
        return bool(ENABLE_FLOAT_B)
    return True


def _hold_days(opened_at, now):
    ot = opened_at if isinstance(opened_at, datetime.datetime) else _parse_opened_at(opened_at)
    if ot is None or now is None:
        return 0.0
    return max(0.0, (now - ot).total_seconds() / 86400.0)


def _float_avg_cost():
    """浮仓 A/B 按股数加权均价；空则 0。"""
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
    """延后 R-Sell/MaxHold 至 EXIT_AFTER（仅日内；止损可绕过）。"""
    if not _use_risk_rules():
        return True
    if not getattr(A, "intraday", False):
        return True
    gate = str(EXIT_AFTER or "").strip()
    if not gate:
        return True
    return str(now_s) >= gate


def _entry_time_ok(now_s):
    """NO_ENTRY_AFTER 及之后禁止新开 R-A（仅日内）。"""
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
    """缩减浮仓 A/B 使总股数 <= target_vol（先减 B）。"""
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

# === hongli/bt_recover.py ===
# 作用: 红利T 回测影子仓恢复为浮仓腿
# 前置: common/backtest + state(_sell_float_vol)
def _bt_recover_float(now=None, last=None):
    """影子持仓仍在但浮仓腿为空时，重新吸纳以便退出信号仍能触发。"""
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
    print(_strategy_tag(), "bt recover float from held", A.float_a)
    return True

# === hongli/indicators.py ===
# 作用: 布林带 + KDJ(J)，与 model.md 对齐
# 主要符号: _calc_indicators
# 拼接序: 8/16 | 上一部: state.py | 下一部: market_util.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _calc_indicators(high, low, close):
    """返回 (下轨, 上轨, J, 最新收盘) 或 None。"""
    n = len(close)
    need = max(BOLL_N, KDJ_N) + 2
    if n < need:
        return None
    c = np.asarray(close, dtype=float)
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    # 拒绝填充/平坦窗口（历史未就绪）
    if np.std(c[-BOLL_N:]) < 1e-8:
        return None
    mid = np.mean(c[-BOLL_N:])
    std = np.std(c[-BOLL_N:])
    lower = mid - BOLL_K * std
    upper = mid + BOLL_K * std

    # KDJ 与 model.md 一致: RSV ewm(com=2)
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

# === hongli/market.py ===
# 作用: 拉取 OHLC/收盘价与日线均线过滤
# 主要符号: _fetch_closes, _daily_ma_ok, _get_ohlc
# 拼接序: 10/16 | 上一部: market_util.py | 下一部: mode.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _fetch_closes(C, stock, period, count, end):
    """按指定周期拉取收盘价序列（供日线均线过滤）。"""
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
    """最新日线收盘 > MA(DAILY_MA_N) 则为 True。按小时+均线周期缓存。"""
    if not bool(REQUIRE_ABOVE_DAILY_MA):
        return True, None, None
    n = int(DAILY_MA_N)
    if n <= 1:
        return True, None, None
    day = _bar_datetime(C).strftime("%Y%m%d")
    # 日内策略一天刷新数次，使今日滚动收盘价更新
    bucket = "%s|ma%d" % (_bar_datetime(C).strftime("%Y%m%d%H"), n)
    cache = getattr(A, "_daily_ma_cache", None)
    if isinstance(cache, dict) and cache.get("bucket") == bucket and cache.get("ok") is not None:
        return bool(cache.get("above")), cache.get("last"), cache.get("ma")

    closes = None
    # 策略周期已是日线时，复用传入序列
    if closes_hint is not None and getattr(A, "period", "") == "1d":
        closes = list(closes_hint)
    if not closes:
        end = day  # 日线 API 要 yyyymmdd
        closes = _fetch_closes(C, stock, "1d", max(int(DAILY_MA_COUNT), n + 5), end)
    if not closes or len(closes) < n:
        _diag_once("daily_ma_short", "bars=", 0 if not closes else len(closes), "need=", n)
        # 失败关闭: 无趋势确认则不开仓
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
    """按 A.period 拉取 OHLC；先 get_market_data_ex，再回退。"""
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

    # 3) get_history_data（旧接口，部分版本仍可用）
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
    A.ready_logged = False
    A._hb_at = None
    try:
        _load_state()
    except Exception as e:
        print(_strategy_tag(), "live switch load_state fail", e)
    if not hasattr(A, "pending"):
        A.pending = None
    recon = globals().get("_reconcile_with_broker")
    if callable(recon):
        try:
            recon()
        except Exception as e:
            print(_strategy_tag(), "live switch reconcile fail", e)


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

# === hongli/broker.py ===
# 作用: 红利T 底仓隔离 / 可卖上限 / 浮仓对账
# 前置: common/broker_base；主要符号: _max_sell_vol, _reconcile_with_broker
def _base_shares():
    return max(0, int(globals().get("BASE_SHARES") or 0))


def _floatable_broker_vol(broker_vol):
    """超出 BASE_SHARES、可由本策略管理的股数。"""
    return max(0, int(broker_vol) - _base_shares())


def _adopt_share_cap(price):
    """对账吸纳上限: 仅按浮仓预算（非整户持仓）。"""
    budget = float(FLOAT_A_BUDGET)
    if _enable_float_b():
        budget += float(FLOAT_B_BUDGET)
    if price and price > 0:
        return _lot(price, budget)
    return int(budget // 100) * 100


def _max_sell_vol():
    """最多卖策略浮仓，永不碰 BASE_SHARES。始终受 T+1 约束。"""
    want = _sell_float_vol()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
        avail = _bt_available_vol()
        return max(0, min(want, avail))
    if want < 100:
        return 0
    if DRY_RUN:
        return _dry_t1_sellable(want)
    broker_vol, can, _cost = _broker_position(A.stock)
    floatable = _floatable_broker_vol(broker_vol)
    return max(0, min(want, int(can), floatable))


def _dry_t1_sellable(want):
    """DRY_RUN 的 T+1: 无券商可卖数据时，禁止同日历日卖出。"""
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
    """对齐 JSON 浮仓与券商可管理股数。有 pending 则跳过。永不碰 BASE_SHARES。"""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return
    if getattr(A, "pending", None):
        print(_strategy_tag(), "reconcile skip: pending active")
        return
    broker_vol, _can, broker_cost = _broker_position(A.stock)
    floatable = _floatable_broker_vol(broker_vol)
    state_vol = _sell_float_vol()
    changed = False
    if floatable < 100:
        if state_vol > 0:
            print(
                _strategy_tag(),
                "reconcile: no floatable (broker=%s base=%s), clear float was %s"
                % (broker_vol, _base_shares(), state_vol),
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
                _strategy_tag(),
                "reconcile: broker has shares but adopt cap <100 (floatable=%s cap=%s); leave unmanaged"
                % (floatable, cap),
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
                _strategy_tag(),
                "reconcile: adopt floatable as float_a",
                A.float_a,
                "broker=",
                broker_vol,
                "base=",
                _base_shares(),
            )
    elif state_vol > floatable:
        print(
            _strategy_tag(),
            "reconcile: shrink float",
            state_vol,
            "->",
            floatable,
            "(broker=%s base=%s)" % (broker_vol, _base_shares()),
        )
        _shrink_float_to_vol(floatable)
        changed = True
    if changed:
        _save_state()


def _reconcile_with_broker():
    """mode 暖机切实盘钩子。"""
    _reconcile_float_with_broker()


def _heartbeat_extra():
    return "A=%s B=%s pending=%s" % (
        _has_leg(getattr(A, "float_a", None)),
        _has_leg(getattr(A, "float_b", None)),
        bool(getattr(A, "pending", None)),
    )

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
        return False
    for fn_name in ("cancel", "cancel_order", "cancelorder"):
        fn = globals().get(fn_name)
        if not callable(fn):
            continue
        try:
            fn(oid, A.acct, A.acct_type, C)
            print(_strategy_tag(), "cancel via", fn_name, oid)
            return True
        except TypeError:
            try:
                fn(oid, A.acct, A.acct_type)
                print(_strategy_tag(), "cancel via", fn_name, "(3arg)", oid)
                return True
            except Exception as e:
                print(_strategy_tag(), fn_name, "fail", e)
        except Exception as e:
            print(_strategy_tag(), fn_name, "fail", e)
    print(_strategy_tag(), "cancel unavailable; keep waiting, oid=", oid)
    return False


def _clear_pending(reason=""):
    if getattr(A, "pending", None):
        print(_strategy_tag(), "pending clear", reason, A.pending.get("remark"))
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
            _clear_pending("orphan")
            return False
        return True

    return True

# === hongli/orders.py ===
# 作用: 红利T 双浮仓腿买卖与成交落地
# 前置: common/orders_pending；实现 _pending_on_* 钩子
def _apply_buy_fill(intent, vol, price, opened_at):
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < 100:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    leg = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
    }
    if intent == "RA":
        A.float_a = leg
        A.acted.add("RA")
        if getattr(A, "is_backtest", False):
            A.bt_opened_at = ot
        print(_strategy_tag(), "R-A filled", A.float_a)
    elif intent == "RB":
        A.float_b = leg
        A.acted.add("RB")
        print(_strategy_tag(), "R-B filled", A.float_b)
    buy_day = ot[:8] if len(ot) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    _save_state()


def _apply_sell_fill(now, intent, last_hint, filled_vol):
    """卖出成交后清空或缩减浮仓。"""
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
        print(_strategy_tag(), "partial sell fill", filled_vol, "remain~", remain)
        _shrink_float_to_vol(remain)
        _bt_held_set(remain)
        if remain < 100:
            _clear_float_after_sell(now, tag + "/partial", last=last_hint)
        else:
            _save_state()


def _pending_on_buy_fill(pend, vol, px):
    _apply_buy_fill(pend.get("intent"), vol, px, pend.get("opened_at"))


def _pending_on_sell_fill(pend, now, vol, px):
    _apply_sell_fill(now, pend.get("intent"), pend.get("last_hint"), vol)


def _order_buy(C, vol, remark_tag, intent, price_hint, opened_at, now):
    """提交买入。DRY_RUN 即时；回测 passorder+即时；实盘 pending 至成交。"""
    if getattr(A, "is_backtest", False) and intent == "RA" and _bt_held_vol() >= 100:
        print(_strategy_tag(), "R-A skip bt_held=", _bt_held_vol())
        return False
    msg = _new_remark(remark_tag, "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        _apply_buy_fill(intent, vol, price_hint, opened_at)
        return True
    try:
        passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v219", 1, msg, C)
    except Exception as e:
        print(_strategy_tag(), "passorder BUY fail", e)
        return False
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
    """提交卖出。DRY_RUN 即时；回测 passorder+即时；实盘 pending 至成交。

    T+1（回测+实盘）: 下单量不超过可卖；跳过时绝不清浮仓。
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
                _strategy_tag(),
                "sell skip T+1 avail=",
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
        avail = _max_sell_vol()
        vol = min(want, avail)
        if vol < 100:
            if DRY_RUN:
                print(
                    _strategy_tag(),
                    "[DRY] sell skip T+1 want=",
                    want,
                    "sellable=",
                    avail,
                    "tag=",
                    remark_tag,
                )
            else:
                broker_vol, can, _cost = _broker_position(A.stock)
                print(
                    _strategy_tag(),
                    "sell skip T+1/live can_use=",
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
        passorder(A.sell_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v219", 1, msg, C)
    except Exception as e:
        print(_strategy_tag(), "passorder SELL fail", e)
        return False
    if getattr(A, "is_backtest", False):
        held_before = _bt_held_vol()
        if vol >= held_before:
            _clear_float_after_sell(now, intent or remark_tag, last=last_hint)
        else:
            remain = held_before - vol
            print(
                _strategy_tag(),
                "T+1 partial sell",
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

# === hongli/runtime.py ===
# 作用: QMT 入口：init / handlebar
# 主要符号: init, handlebar, _init_impl
# 拼接序: 14/16 | 上一部: orders.py | 下一部: strategy.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def init(C):
    # 尽早设 busy，避免 init 半截时 handlebar 因 A.busy 崩溃
    A.busy = False
    A._hb_at = None
    try:
        _init_impl(C)
    except Exception as e:
        print("HongliT init error", e)
        try:
            traceback.print_exc()
        except Exception:
            pass


def _init_impl(C):
    # 标的来自主图；账号优先模型交易界面，否则用配置
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
    A._mode_last_bp = -1
    A._mode_same_bp_hits = 0
    A.do_back_test_raw = _is_backtest(C)
    A.is_backtest = A.do_back_test_raw

    do_dl = DOWNLOAD_HIST_BACKTEST if A.is_backtest else DOWNLOAD_HIST_LIVE
    if do_dl:
        try:
            _download_hist(A.stock, A.period)
            if bool(REQUIRE_ABOVE_DAILY_MA):
                _download_hist(A.stock, "1d")
        except Exception as e:
            print("HongliT download_hist abort-safe", e)
    else:
        print(
            "HongliT skip download_history (live); use local cache PERIOD=",
            A.period,
        )

    if A.is_backtest:
        # QMT 可能中途再调 init；若清空浮仓会导致 passorder 成交变孤儿。
        # 全新开始: 首次回测会话 或 barpos 接近 0（新回放）。
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
        # False -> 实盘首根决策 K 必打印 close=/J=
        A.ready_logged = False
        if not hasattr(A, "cooldown_until"):
            A.cooldown_until = ""
        if not hasattr(A, "pending"):
            A.pending = None
        try:
            _reconcile_float_with_broker()
        except Exception as e:
            print("HongliT reconcile fail", e)

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("HongliT set_universe fail", e)

    print(
        "HongliT v2.19 init",
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
        "rawBT=",
        getattr(A, "do_back_test_raw", A.is_backtest),
        "bt_held=",
        _bt_held_vol() if A.is_backtest else "-",
        "hbSec=",
        LIVE_HEARTBEAT_SEC,
        "dlLive=",
        DOWNLOAD_HIST_LIVE,
        "STATE=",
        STATE_FILE,
    )


def handlebar(C):
    # 实盘: 仅最新 K；回测: 每根（OHLC 未就绪则内部跳过）
    try:
        # 须在 is_last_bar 门控前刷新（国金暖机 -> 实盘）
        is_bt = _refresh_mode(C)
        if (not is_bt) and (not C.is_last_bar()):
            return
        if getattr(A, "busy", False):
            return
        A.busy = True
        try:
            if is_bt and (C.barpos % 100 == 0):
                print("HongliT progress barpos=", C.barpos, "time=", _bar_end_yyyymmdd(C))
            _handle(C)
        except Exception as e:
            print("HongliT handlebar error", e)
            try:
                traceback.print_exc()
            except Exception:
                pass
        finally:
            A.busy = False
    except Exception as e:
        print("HongliT handlebar outer error", e)
        try:
            A.busy = False
        except Exception:
            pass

# === hongli/strategy.py ===
# 作用: 交易决策：止损/R-Sell/MaxHold/R-A/R-B
# 主要符号: _handle
# 拼接序: 15/16 | 上一部: runtime.py | 下一部: _main_guard.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _handle(C):
    bt = getattr(A, "is_backtest", False)
    now = _bar_datetime(C) if bt else datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    day = now.strftime("%Y%m%d")
    intraday = getattr(A, "intraday", False)

    if not bt:
        # 先处理 pending（含 15:00 后成交/撤单）
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        # 实盘: 交易时段外不做新决策
        if now_s < "093000" or now_s > "150000":
            _live_heartbeat("outside_session")
            return
        # 日线+: 临近收盘窗；日内: 时段内每根最新 K
        if (not intraday) and (now_s < DECISION_START or now_s > DECISION_END):
            _live_heartbeat("wait_decision_window")
            return
        _live_heartbeat("in_session")
    # 回测: 每根约等于该 K 收盘决策
    if bt:
        _bt_roll_t1(day)
        _bt_recover_float(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    ohlc = _get_ohlc(C, A.stock)
    if ohlc is None:
        _live_heartbeat("ohlc_none")
        return
    high, low, close = ohlc
    ind = _calc_indicators(high, low, close)
    if ind is None:
        _live_heartbeat("ind_none")
        return
    lower, upper, j, last = ind
    if bt:
        _bt_recover_float(now=now, last=last)
    buy_cond = (last <= lower * LOWER_TOL) and (j <= 0)
    sell_cond = (last >= upper * UPPER_TOL) and (j >= 100)
    has_a = _has_leg(A.float_a)
    has_b = _has_leg(A.float_b)
    zero_float = (not has_a) and (not has_b)
    # 影子持仓拦住新 R-A（即使中途浮仓腿被清空）
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

    # 实盘恢复的腿补 opened_at（避免立刻触发 MaxHold）
    if has_a and not A.float_a.get("opened_at"):
        A.float_a["opened_at"] = now.strftime("%Y%m%d%H%M%S")
        _save_state()

    hold_d = 0.0
    if has_a:
        hold_d = _hold_days(A.float_a.get("opened_at"), now)
    fret = _float_ret(last) if (has_a or has_b) else 0.0
    exit_ok = _exit_time_ok(now_s)

    # 软止损（先于 R-Sell）。可忽略 EXIT_AFTER 以抓住开盘跳空。
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

    # 先做 R-Sell: 只清浮仓
    if sell_cond and (has_a or has_b) and ("SELL" not in A.acted) and (not getattr(A, "pending", None)):
        if not exit_ok:
            print("R-Sell defer until", EXIT_AFTER, "now=", now_s)
            return
        else:
            sell_vol = _sell_float_vol()
            _order_sell(C, sell_vol, "RSell", "R-Sell", last, now)
            return

    # 软最长持仓（仅亏损）+ 硬最长持仓防漏
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
            soft_hit = False  # 浮仓盈利: 等 R-Sell
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

    # R-B（USE_RISK_RULES 且 ENABLE_FLOAT_B=False 时关闭）
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
        opened_at = now.strftime("%Y%m%d%H%M%S")
        _order_buy(C, vol, "RB", "RB", last, opened_at, now)
        return

    if (not buy_cond) and (not sell_cond) and interesting:
        extra = ""
        if _use_risk_rules() and (has_a or has_b):
            extra = " holdDays=%.2f ret=%.2f%%" % (hold_d, fret * 100.0)
        print("HongliT hold float" + extra)

# === hongli/_main_guard.py ===
# 作用: 拦截 simpleRun/doRun 独立启动（应走模型交易）
# 主要符号: __main__
# 拼接序: 16/16 | 上一部: strategy.py | 下一部: -
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
# 国金模型交易须按 PythonFormula 加载（init/handlebar）。
# 若经 doRun `python -u HLCL.py ...`（simpleRun=1）启动会立刻退出，
# 策略日志只见开始/结束 — 并非常驻监控。
if __name__ == "__main__":

    print(
        "HongliT ERROR: standalone doRun (simpleRun=1). "
        "EXIT QMT fully -> python scripts/qmt/_fix_hlcl_simplerun.py -> "
        "reopen QMT -> compile HLCL -> model trade Start. "
        "Expect HongliT init, not this line."
    )
    sys.exit(2)
