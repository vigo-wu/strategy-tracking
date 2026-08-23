#coding:gbk
# 由 _deploy_qmt_gbk.py 自动生成；请勿手改。请编辑策略片段与 scripts/qmt_common/ 后重新部署。
import datetime
import json
import os
import traceback

import numpy as np


# === vwapbias/config.py ===
# 分时 VWAP 乖离、日内 T+0。首测标的: 113699.SH 金25转债（沪市、10 张整数倍）。
# 形态: 单仓骨架 + SCALE_LOTS 同标的分笔。主图必须 1 分钟，不要挂正股 603979.SH，
# 也不要挂同发行人旧券 113615.SH。规则真源: strategy/model.md（当前 v0.9）。
# 终端改参走 panel.xml / PANEL_BINDS；改本文件后必须跑 _deploy_qmt_gbk.py。

# ===================== 开关与账户 =====================
# True=只打日志不下单。回测/实盘真下单前在面板取消「模拟下单」，或改这里。
DRY_RUN = True

# 编辑器/回测兜底账号；实盘以对话框 account / accountType 为准，勿把账号放上面板。
ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# ===================== 资金 =====================
# 单日预算上限（元）。两档各按 LOT_W* 再按 VOL_STEP 取整。建议 5 万~20 万，
# 不超过近 5 日日均额的 1%。价格约 194 时，10 张约 1940 元。
TRADE_BUDGET = 50000.0
# 按标的覆盖预算（key 须与 A.stock 一致，如 113699.SH）；空则用上面默认值。
TRADE_BUDGET_BY_STOCK = {}
# 可用现金占用比例，预留下单缓冲，避免打满失败。
CASH_RATIO = 0.8

# ===================== 转债数量与 T+0 =====================
# 沪市转债申报 10 张（1000 元面值）整数倍。common._lot / 可卖取整读此值，不要当 100 股。
VOL_STEP = 10
# 可转债当日买入可卖。必须 True，否则回测会按股票 T+1 锁仓。
ALLOW_T0 = True

# ===================== 标的拦截 =====================
# 主图须与此一致，否则 univ_skip=wrong_symbol。
EXPECT_STOCK = "113699.SH"
# 禁止交易（挂错主图时直接 skip）。113615=金诚转债；113069=博23已摘牌。
FORBID_STOCKS = ("113615.SH", "113069.SH")

# ===================== 周期与取数 =====================
# 主图周期。只在已收盘 1 分钟 K 上决策（回测用当前根，实盘用上一根）。
PERIOD = "1m"
# 向 ContextInfo 要的 1 分钟根数。本机 pandas/get_market_data_ex 损坏时走 ori，
# ori 往往只给最近约 240 根，靠 barpos 窗口对齐，不必把此值当成实际可用长度。
OHLC_COUNT = 800
# 日线根数：ADV_MIN 近 N 日均额、昨收等。
DAILY_OHLC_COUNT = 12
# 实盘只在 is_last_bar() 决策，避免未收盘 K 上反复下单。回测忽略。
LIVE_ONLY_LAST_BAR = True

# ===================== 交易时段（HHMMSS 字符串） =====================
# 回测用 K 线时间；实盘用墙钟。沪市转债连续匹配到 15:00（无深市 14:57 收盘集合）。
DECISION_START = "093000"      # 决策窗开始
DECISION_END = "150000"        # 决策窗结束
OPEN_SKIP_AM_END = "093500"    # 09:30~09:35 只更新指标，不交易（开盘噪声）
OPEN_SKIP_PM_START = "130000"  # 13:00~13:05 同样暖机
OPEN_SKIP_PM_END = "130500"
LUNCH_START = "113000"         # 午休，phase=lunch
LUNCH_END = "130000"
NO_NEW_ENTRY = "144000"        # 14:40 起只卖不买（sell_only）
FLAT_START = "145000"          # 14:50 起 eod_flatten 强平；未平视为策略失败

# ===================== 买入: 负乖离分档 =====================
# BIAS = (收盘 - 当日VWAP) / VWAP，小数。-0.018 = 低于均价 1.8%。
# 阈值按上市以来 60 分钟 + 近月 5 分钟分位校准（公开源无完整 1 分钟历史），
# 约 10% / 3% 交易日触及 L1/L2。脚本: strategy/scripts/calibrate_113699_bias.py
BIAS_L1 = -0.018               # 开仓档，日志 buy_l1
BIAS_L2 = -0.025               # 须已持 L1，且止跌 + 现价>=持仓均价，日志 buy_l2
BIAS_L3 = -0.035               # 更深一档，默认关
ENABLE_L3 = False
# 各档占用 TRADE_BUDGET 的比例，再按 VOL_STEP 取整。L3 关时 W3 不用。
LOT_W1 = 0.30
LOT_W2 = 0.30
LOT_W3 = 0.40

# ===================== 买入: 急跌 + 止跌形态 =====================
# 看信号根之前的 DOWN_BARS 根已收盘 1 分钟，满足其一即 impulse_ok:
#   至少 1 根阴；或窗口最高到末收回撤 >= IMPULSE_SUM；或末根 (开-收)/开 >= LAST_DROP。
DOWN_BARS = 2                  # 观察窗长度（不含当前信号根）
LAST_DROP = 0.002              # 0.2%，窗口末根阴跌
IMPULSE_SUM = 0.005            # 0.5%，窗口回撤
# 当前根 reversal_ok: 收红，或收盘>=上一根收盘，或下影占比 > 此值。
# 空仓且 BIAS<=L2 时允许跳过止跌开 L1；加 L2 必须止跌，且禁止现价低于均价加仓。
SHADOW_RATIO = 0.25

# ===================== 卖出（优先级见 strategy.py） =====================
# eod_flatten > stop_loss > trail_stop > take_profit > fade_sell > vwap_reversion
#
# fade_sell: BIAS >= BIAS_FADE；若尚未到 BIAS_FADE+0.004，还要求量比 <= VOL_GAP。
# 持仓后 1 分钟很少到 +1.5%，故用 5 分钟 p90 的 +0.8%。样本里常为 0 次。
BIAS_FADE = 0.008
VOL_GAP = 0.75
# vwap_reversion: BIAS >= 此值且该笔已盈利则平盈利笔。0 = 回到均价即可。
# 不再用 0~+0.2% 窄带（1 分钟容易一根跳过）。
REVERSION_BIAS = 0.00
# 仅作文档/备份上限；当前代码卖出不读此值。fade 量能确认的分界用 BIAS_FADE+0.004。
REVERSION_BIAS_HI = 0.012
# take_profit: 相对该笔成本 +1.0% 只平达标的 lot。未走到移动止盈启动带的日子靠它离场。
TAKE_PROFIT = 0.010
# trail_stop: 合并均价浮盈达到 ARM 后，自峰值回撤 GIVE 则全平。
# 用来接「先冲到 +1.4% 再单边砸到止损」的路径。ARM=0 关闭。
TRAIL_ARM = 0.012              # 1.2% 启动
TRAIL_GIVE = 0.005             # 0.5% 回撤
# stop_loss: 相对合并均价 -3.0% 清可卖仓，并当日 risk_skip 不再开。
# 不要收到 2%: 有的日子先深跌再回归（如 01-29），2% 会误杀。
STOP_LOSS = 0.030

# ===================== 流动性 / 涨跌停（univ_skip） =====================
# 近 ADV_DAYS 日均成交额低于此值（元）则当日不新开。该券近期通常 2 亿以上。
ADV_MIN = 5e7
ADV_DAYS = 5
# 实盘一档价差/中间价超过此值停开。0.003 = 0.30%。回测不查盘口。
SPREAD_MAX = 0.003
# 转债上市后涨跌幅约 +/-20%。相对昨收绝对涨跌达到 LIMIT_NEAR 则视为接近涨跌停，不新开。
LIMIT_PCT = 0.20
LIMIT_NEAR = 0.18

# ===================== 分笔 =====================
# True: L1/L2 分笔记账，止盈/回归可按 lot 平；止损仍按合并均价。
# 不要为此去接双浮仓 orders.py。SCALE_MAX=2 对应 L1+L2（L3 关闭时）。
SCALE_LOTS = True
SCALE_MAX = 2

# ===================== 终端参数面板 =====================
# bind 名 -> 本文件常量 -> 类型。注入发生在 runtime.init 的 _apply_panel()。
# 禁止上屏: account、STATE_FILE、LOG_DIR、STRATEGY_VER、_ORDER_*。
PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_bias_l1", "BIAS_L1", "float"),
    ("panel_bias_l2", "BIAS_L2", "float"),
    ("panel_bias_fade", "BIAS_FADE", "float"),
    ("panel_take_profit", "TAKE_PROFIT", "float"),
    ("panel_trail_arm", "TRAIL_ARM", "float"),
    ("panel_trail_give", "TRAIL_GIVE", "float"),
    ("panel_stop_loss", "STOP_LOSS", "float"),
    ("panel_adv_min", "ADV_MIN", "float"),
    ("panel_spread_max", "SPREAD_MAX", "float"),
    ("panel_scale_lots", "SCALE_LOTS", "bool"),
)

# ===================== 日志 / 历史 / 挂单超时 =====================
# 实盘心跳最短间隔（秒）。回测不走墙钟心跳。
LIVE_HEARTBEAT_SEC = 60
# download_history_data 最多回看日历日。上市日 2025-10-27，回测起点不要更早。
HIST_MAX_LOOKBACK_DAYS = 400
DOWNLOAD_HIST_LIVE = False     # 实盘一般不在 init 拉长历史
DOWNLOAD_HIST_BACKTEST = True  # 回测 init 拉 1m/1d，保证暖机
# 委托超时（秒）。PENDING_ORPHAN: 成交回报丢失后的孤儿仓处理窗口。
PENDING_TIMEOUT_SEC = 60
PENDING_ORPHAN_SEC = 60

# 状态文件必须绝对路径。{stock} 展开为 113699_SH，多实例不可共用同一 JSON。
STATE_FILE = r"D:\tradingStrategy\vwapbias_{stock}.json"
# 实盘事件日志目录。回测默认不写盘（LOG_IN_BACKTEST=False），看终端 log.txt。
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

# 日志前缀与版本。init 行形如: VwapBias v0.9 init ...
STRATEGY_NAME = "VwapBias"
STRATEGY_VER = "v0.9"

# 券商委托状态码: 已成 / 已死（撤废拒等）。勿改除非柜台码表变了。
_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

# 终端允许的周期名；download 起点按周期覆盖（该债 2025-10-27 上市）。
_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
_PERIOD_HIST_START = {
    "1m": "20251027",
    "1d": "20251027",
}

# === qmt_common/ctx.py ===
# 作用: 全局运行时对象与手数工具
# 主要符号: A, _S, _vol_step, _lot
# 前置: 策略 config（可选 STRATEGY_NAME, VOL_STEP）
# VOL_STEP: 下单数量步长。股票/ETF 默认 100 股；沪市转债设 10（10 张=1000 元面值）
class _S(object):
    pass


A = _S()


def _vol_step():
    try:
        s = int(globals().get("VOL_STEP") or 100)
    except Exception:
        s = 100
    if s <= 0:
        s = 100
    return s


def _lot(price, budget):
    step = _vol_step()
    if price is None or price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * step)) * step


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

# === vwapbias/state_extra.py ===
def _state_extra_load(raw):
    A.acted_closed = str(raw.get("acted_closed", "") or "")
    A.risk_skip_day = str(raw.get("risk_skip_day", "") or "")
    A.scale_out_lock = bool(raw.get("scale_out_lock", False))
    pk = raw.get("hold_peak_ret", None)
    try:
        A.hold_peak_ret = float(pk) if pk is not None and pk != "" else None
    except Exception:
        A.hold_peak_ret = None


def _state_extra_save(data):
    data["acted_closed"] = str(getattr(A, "acted_closed", "") or "")
    data["risk_skip_day"] = str(getattr(A, "risk_skip_day", "") or "")
    data["scale_out_lock"] = bool(getattr(A, "scale_out_lock", False))
    pk = getattr(A, "hold_peak_ret", None)
    data["hold_peak_ret"] = None if pk is None else float(pk)

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
    A.lots = []
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
    if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= _vol_step():
        A.position = dict(pos)
        A.position["shares"] = int(pos["shares"])
        A.position["price"] = float(pos.get("price", 0) or 0)
        A.position["cost"] = float(pos.get("cost", 0) or 0)
        A.position["opened_at"] = str(pos.get("opened_at", "") or "")
    lots = raw.get("lots")
    cleaned = []
    if isinstance(lots, list):
        for lot in lots:
            if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= _vol_step():
                cleaned.append(dict(lot))
    A.lots = cleaned
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
        "lots": list(getattr(A, "lots", None) or []) if isinstance(getattr(A, "lots", None), list) else [],
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
    if A.bt_held < _vol_step():
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
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= _vol_step()


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
    A.lots = []
    A.acted.add("SELL")
    if getattr(A, "is_backtest", False):
        A.bt_held = 0
        A.bt_locked = 0
        A.bt_opened_at = ""
    _save_state()

# === qmt_common/single/lots.py ===
# 作用: 同一标的多笔独立仓（SCALE_LOTS）；A.position 仍是合计，供经纪/T+1
# 主要符号: _lots_enabled, _ensure_lots, _pos_lots, _lots_on_buy_fill,
#           _lots_on_sell_fill, _order_sell(lot_ids=)
# 默认关：未设 SCALE_LOTS 时一票一仓，行为与无本片段时相同
# 策略可在 lot 字典上挂 hold_peak 等字段；本模块原样保留
def _lots_enabled():
    return bool(globals().get("SCALE_LOTS", False))


def _scale_lots():
    """兼容旧策略名；与 _lots_enabled 相同。"""
    return _lots_enabled()


def _lot_from_agg():
    pos = getattr(A, "position", None) or {}
    px = float(pos.get("price", 0) or 0)
    peak = getattr(A, "hold_peak", None)
    cp = getattr(A, "hold_close_peak", None)
    if peak is None:
        peak = px
    if cp is None:
        cp = px
    return {
        "id": 1,
        "shares": int(pos.get("shares", 0) or 0),
        "price": px,
        "opened_at": str(pos.get("opened_at", "") or ""),
        "hold_peak": peak,
        "hold_close_peak": cp,
        "hold_max_ret": float(getattr(A, "hold_max_ret", 0) or 0),
        "hold_bars": int(getattr(A, "hold_bars", 0) or 0),
        "hold_count_bar": str(getattr(A, "_hold_count_bar", "") or ""),
    }


def _ensure_lots():
    lots = getattr(A, "lots", None)
    cleaned = []
    if isinstance(lots, list):
        for lot in lots:
            if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= _vol_step():
                cleaned.append(lot)
    if cleaned:
        A.lots = cleaned
        return cleaned
    if _has_position():
        A.lots = [_lot_from_agg()]
        return A.lots
    A.lots = []
    return A.lots


def _next_lot_id():
    mx = 0
    for lot in getattr(A, "lots", None) or []:
        try:
            mx = max(mx, int(lot.get("id") or 0))
        except Exception:
            pass
    return mx + 1


def _new_lot(shares, price, opened_at=""):
    px = float(price) if price else 0.0
    ot = str(opened_at or "")
    if not ot:
        pos = getattr(A, "position", None)
        if isinstance(pos, dict):
            ot = str(pos.get("opened_at") or "")
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return {
        "id": _next_lot_id(),
        "shares": int(shares),
        "price": px,
        "opened_at": ot,
        "hold_peak": px,
        "hold_close_peak": px,
        "hold_max_ret": 0.0,
        "hold_bars": 0,
        "hold_count_bar": "",
    }


def _sync_position_from_lots():
    lots = []
    for lot in getattr(A, "lots", None) or []:
        if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= _vol_step():
            lots.append(lot)
    A.lots = lots
    if not lots:
        A.position = None
        return
    total = 0
    cost_sum = 0.0
    ot = ""
    for lot in lots:
        sh = int(lot.get("shares") or 0)
        px = float(lot.get("price") or 0)
        total += sh
        cost_sum += sh * px
        if not ot:
            ot = str(lot.get("opened_at") or "")
    avg = (cost_sum / float(total)) if total else 0.0
    A.position = {
        "shares": int(total),
        "price": float(avg),
        "cost": round(total * avg, 2),
        "opened_at": ot,
        "lots": len(lots),
    }
    if getattr(A, "is_backtest", False):
        held = _bt_held_vol()
        if held < _vol_step() and total >= _vol_step():
            print(_strategy_tag(), "restore bt_held from lots", total)
            A.bt_held = total
        elif held != total:
            print(
                _strategy_tag(),
                "lots vs bt_held mismatch lots=",
                total,
                "held=",
                held,
            )


def _mirror_hold_from_lots():
    lots = getattr(A, "lots", None) or []
    if not lots:
        A.hold_peak = None
        A.hold_close_peak = None
        A.hold_max_ret = 0.0
        A.hold_bars = 0
        A._hold_count_bar = ""
        return
    lot = lots[0]
    A.hold_peak = lot.get("hold_peak")
    A.hold_close_peak = lot.get("hold_close_peak")
    A.hold_max_ret = float(lot.get("hold_max_ret") or 0)
    A.hold_bars = int(lot.get("hold_bars") or 0)
    A._hold_count_bar = str(lot.get("hold_count_bar") or "")


def _bump_lot_bars(lot, bar_tag):
    if str(lot.get("hold_count_bar") or "") == str(bar_tag):
        return False
    lot["hold_bars"] = int(lot.get("hold_bars") or 0) + 1
    lot["hold_count_bar"] = str(bar_tag)
    return True


def _update_lot_peaks(lot, high_px, close_px):
    hi = float(high_px)
    cl = float(close_px)
    cost = float(lot.get("price") or 0)
    changed = False
    peak = lot.get("hold_peak")
    if peak is None:
        base = cost if cost > 0 else hi
        lot["hold_peak"] = max(base, hi)
        changed = True
    elif hi > float(peak):
        lot["hold_peak"] = hi
        changed = True
    cp = lot.get("hold_close_peak")
    if cp is None:
        lot["hold_close_peak"] = cl
        changed = True
    elif cl > float(cp):
        lot["hold_close_peak"] = cl
        changed = True
    if cost > 0:
        mx = max((cl - cost) / cost, (hi - cost) / cost)
        prev = lot.get("hold_max_ret")
        try:
            prev_f = float(prev) if prev is not None else None
        except Exception:
            prev_f = None
        if prev_f is None or mx > prev_f:
            lot["hold_max_ret"] = mx
            changed = True
    return changed


def _pos_lots():
    if _lots_enabled():
        return len(_ensure_lots())
    pos = getattr(A, "position", None)
    if not isinstance(pos, dict):
        return 0
    try:
        return max(1, int(pos.get("lots", 1) or 1))
    except Exception:
        return 1


def _lots_want_vol(lot_ids):
    if not lot_ids:
        return None
    try:
        idset = set(int(x) for x in lot_ids)
    except Exception:
        return None
    total = 0
    for lot in getattr(A, "lots", None) or []:
        try:
            if int(lot.get("id") or 0) in idset:
                total += int(lot.get("shares") or 0)
        except Exception:
            pass
    if total < _vol_step():
        return None
    return int(total)


def _exit_is_partial(lot_ids):
    if (not _lots_enabled()) or (not lot_ids):
        return False
    try:
        idset = set(int(x) for x in lot_ids)
    except Exception:
        return False
    for lot in _ensure_lots():
        try:
            if int(lot.get("id") or 0) not in idset:
                return True
        except Exception:
            pass
    return False


def _lots_on_buy_fill(px, add=False, vol=None, opened_at=""):
    if not _lots_enabled():
        return
    if vol is None:
        total = _pos_shares()
        if getattr(A, "is_backtest", False):
            total = max(total, _bt_held_vol())
        have = 0
        if add:
            for lot in getattr(A, "lots", None) or []:
                try:
                    have += int(lot.get("shares") or 0)
                except Exception:
                    pass
        vol = total if not add else (total - have)
    vol = int(vol or 0)
    if not add:
        A.lots = []
    elif not (getattr(A, "lots", None) or []):
        A.lots = [_lot_from_agg()]
        _sync_position_from_lots()
        _mirror_hold_from_lots()
        return
    if vol < _vol_step():
        if add and not (getattr(A, "lots", None) or []):
            A.lots = [_lot_from_agg()]
        _sync_position_from_lots()
        _mirror_hold_from_lots()
        return
    A.lots.append(_new_lot(vol, px, opened_at))
    _sync_position_from_lots()
    _mirror_hold_from_lots()
    print(_strategy_tag(), "lots now n=%s" % len(A.lots), A.lots)
    _event_log("lots_update", action="buy", add=add, lots=A.lots)


def _lots_on_sell_fill(lot_ids, filled_vol):
    if not _lots_enabled():
        return
    lots = list(getattr(A, "lots", None) or [])
    if not lots:
        return
    remain_fill = int(filled_vol or 0)
    idset = None
    if lot_ids:
        try:
            idset = set(int(x) for x in lot_ids)
        except Exception:
            idset = None
    new_lots = []
    for lot in lots:
        try:
            lid = int(lot.get("id") or 0)
        except Exception:
            lid = 0
        if idset is not None and lid not in idset:
            new_lots.append(lot)
            continue
        if remain_fill < _vol_step():
            new_lots.append(lot)
            continue
        sh = int(lot.get("shares") or 0)
        if sh <= remain_fill:
            remain_fill -= sh
        else:
            lot = dict(lot)
            lot["shares"] = sh - remain_fill
            remain_fill = 0
            new_lots.append(lot)
    A.lots = new_lots
    _sync_position_from_lots()
    _mirror_hold_from_lots()
    print(_strategy_tag(), "lots now n=%s" % len(A.lots), A.lots)
    _event_log("lots_update", action="sell", lot_ids=lot_ids, lots=A.lots)


def _heartbeat_extra():
    lots = getattr(A, "lots", None) or []
    if not lots:
        return ""
    bits = []
    for lot in lots:
        try:
            bits.append(
                "L%s:%s@%.4f"
                % (lot.get("id"), lot.get("shares"), float(lot.get("price") or 0))
            )
        except Exception:
            pass
    return "lots=" + ",".join(bits)

# === qmt_common/single/bt_recover.py ===
# 作用: 单仓回测影子仓恢复为 A.position
def _bt_recover_position(now=None, last=None):
    if not getattr(A, "is_backtest", False):
        return False
    held = _bt_held_vol()
    if held < _vol_step():
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
    fn = globals().get("_ensure_lots")
    if callable(fn) and bool(globals().get("SCALE_LOTS")):
        fn()
    return True

# === vwapbias/indicators.py ===
def _lower_shadow_ratio(o, h, l, c):
    rng = float(h) - float(l)
    if rng <= 1e-12:
        return 0.0
    return (min(float(o), float(c)) - float(l)) / rng


def _impulse_ok(opens, closes, idx_list, n, last_drop, sum_drop=0.0):
    """信号根之前 n 根：多数阴、或窗口回撤、或末根阴跌，满足其一即可。"""
    n = int(n)
    if n <= 0 or len(idx_list) < n + 1:
        return False
    prior = idx_list[-(n + 1) : -1]
    o0 = float(opens[prior[0]])
    cl = float(closes[prior[-1]])
    if o0 <= 0:
        return False
    peak = o0
    yin = 0
    for j in prior:
        oj = float(opens[j])
        cj = float(closes[j])
        if oj > peak:
            peak = oj
        if cj > peak:
            peak = cj
        if cj < oj:
            yin += 1
    sum_ok = peak > 0 and (peak - cl) / peak >= float(sum_drop)
    ol = float(opens[prior[-1]])
    last_ok = ol > 0 and (ol - cl) / ol >= float(last_drop)
    yin_ok = yin >= max(1, n - 1)
    return sum_ok or last_ok or yin_ok


def _reversal_ok(o, h, l, c, shadow_ratio, prev_close=None):
    if float(c) > float(o):
        return True
    if prev_close is not None and float(c) >= float(prev_close):
        return True
    return _lower_shadow_ratio(o, h, l, c) > float(shadow_ratio)


def _fade_vol_ok(volumes, i_now, i_prev, gap):
    if i_prev is None or i_now is None:
        return False
    v0 = float(volumes[i_prev] or 0)
    v1 = float(volumes[i_now] or 0)
    if v0 <= 0:
        return False
    return v1 <= v0 * float(gap)


def _cum_vwap(amounts, volumes, highs, lows, closes, idx_list):
    """当日已收盘 1m 累加 VWAP。优先 amount，否则 typical*volume。"""
    amt = 0.0
    vol = 0.0
    used_amt = 0
    used_typ = 0
    for j in idx_list:
        v = float(volumes[j] or 0)
        if v <= 0:
            continue
        a = 0.0
        if amounts is not None and j < len(amounts):
            try:
                a = float(amounts[j] or 0)
            except Exception:
                a = 0.0
        if a > 0:
            amt += a
            used_amt += 1
        else:
            typ = (float(highs[j]) + float(lows[j]) + float(closes[j])) / 3.0
            amt += typ * v
            used_typ += 1
        vol += v
    if vol <= 0 or amt <= 0:
        return None, "none"
    raw = amt / vol
    typ_amt = 0.0
    typ_vol = 0.0
    for j in idx_list:
        v = float(volumes[j] or 0)
        if v <= 0:
            continue
        typ = (float(highs[j]) + float(lows[j]) + float(closes[j])) / 3.0
        if typ > 0:
            typ_amt += typ * v
            typ_vol += v
    src = "amount"
    if used_amt == 0:
        src = "typical"
    elif used_typ > 0:
        src = "mixed"
    if typ_vol > 0 and typ_amt > 0:
        typical_vwap = typ_amt / typ_vol
        if typical_vwap > 0:
            ratio = raw / typical_vwap
            # 转债 volume 常为手(1手=10张), amount 为元 -> VWAP 约 10 倍现价
            if 7.5 <= ratio <= 12.5:
                return raw / 10.0, "amount_lot10"
            if ratio > 2.0 or ratio < 0.5:
                return typical_vwap, "typical"
    return raw, src


def _bias_of(price, vwap):
    if vwap is None or vwap <= 0 or price is None:
        return None
    return (float(price) - float(vwap)) / float(vwap)

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

# === vwapbias/market.py ===
# 1 分钟主图优先用 ContextInfo 序列（C.close 等）。
# 本机 QMT pandas 损坏时 get_market_data_ex 会报 _TSObject/iNaT，
# 且 get_market_data(count=800) 会把 1m 回测拖死，故 1m 不再走那条回退。
def _pandas_broken_msg(exc):
    s = str(exc or "")
    return ("__reduce_cython__" in s) or ("iNaT" in s) or ("C extension" in s)


def _mark_pandas_broken(exc):
    A._md_pandas_broken = True
    _diag_once("md_pandas_broken", exc)


def _as_float_list(obj, n=None):
    if obj is None:
        return None
    vals = None
    try:
        if hasattr(obj, "values") and not isinstance(obj, (list, tuple, dict)):
            vals = list(np.asarray(obj.values, dtype=float).reshape(-1))
    except Exception:
        vals = None
    if vals is None:
        try:
            vals = list(np.asarray(obj, dtype=float).reshape(-1))
        except Exception:
            vals = None
    if vals is None:
        try:
            if hasattr(obj, "tolist"):
                vals = [float(x) for x in obj.tolist()]
            else:
                vals = [float(x) for x in list(obj)]
        except Exception:
            return None
    if n is not None:
        if n <= 0:
            return []
        vals = vals[: int(n)]
    out = []
    for fv in vals:
        try:
            if fv != fv:
                out.append(0.0)
            else:
                out.append(float(fv))
        except Exception:
            out.append(0.0)
    return out


def _index_n(obj, n):
    if obj is None or n <= 0:
        return None
    out = []
    for i in range(int(n)):
        v = None
        try:
            v = obj[i]
        except Exception:
            try:
                v = obj.iloc[i]
            except Exception:
                return None
        try:
            fv = float(v)
            if fv != fv:
                fv = 0.0
            out.append(fv)
        except Exception:
            out.append(0.0)
    return out


def _ctx_field(C, names, n=None):
    if isinstance(names, str):
        names = (names,)
    try:
        bp_n = int(getattr(C, "barpos", 0) or 0) + 1
    except Exception:
        bp_n = 1
    if n is None:
        n = bp_n
    for name in names:
        obj = getattr(C, name, None)
        if obj is None:
            continue
        if callable(obj):
            got = None
            for args in ((), (n,), (bp_n,), (int(n - 1),)):
                try:
                    got = obj(*args)
                    break
                except Exception:
                    continue
            if got is None:
                continue
            obj = got
        vals = _as_float_list(obj, n)
        if vals and not (len(vals) == 1 and n > 1):
            return vals
        vals = _index_n(obj, n)
        if vals and not (len(vals) == 1 and n > 1):
            return vals
        try:
            fv = float(obj)
            if n <= 1:
                return [fv]
        except Exception:
            pass
    return None


def _diag_ctx_once(C):
    hits = []
    try:
        for n in dir(C):
            ln = str(n).lower()
            if (
                ("close" in ln)
                or ("history" in ln)
                or ("market" in ln)
                or (n in ("open", "high", "low", "volume", "amount", "barpos", "period"))
            ):
                hits.append(str(n))
            if len(hits) >= 30:
                break
    except Exception as e:
        hits.append("dir_fail")
        hits.append(str(e)[:80])
    close = getattr(C, "close", None)
    _diag_once(
        "chart_probe",
        "barpos=",
        getattr(C, "barpos", None),
        "period=",
        getattr(C, "period", None),
        "close_type=",
        type(close),
        "hits=",
        ",".join(hits),
    )


def _from_hist_dict(raw, stock, field):
    if raw is None:
        return None
    vals = _series_from_ex(raw, stock, field)
    if vals:
        return vals
    if not isinstance(raw, dict):
        return _as_float_list(raw)
    keys = [stock, field]
    if "." in str(stock):
        code, mkt = str(stock).split(".", 1)
        keys.extend([code, str(mkt) + str(code), str(code) + "." + str(mkt)])
    for k in keys:
        if k in raw:
            vals = _as_float_list(raw[k])
            if vals:
                return vals
    if len(raw) == 1:
        return _as_float_list(list(raw.values())[0])
    return None


def _call_history(C, count, period, field):
    fn = getattr(C, "get_history_data", None)
    if not callable(fn):
        fn = globals().get("get_history_data")
    if not callable(fn):
        return None
    count = max(1, int(count))
    period = str(period or "1m")
    last = None
    names = (field,)
    if field == "open":
        names = ("open", "Open", "openPrice", "openprice")
    elif field == "high":
        names = ("high", "High", "highPrice", "highprice")
    elif field == "low":
        names = ("low", "Low", "lowPrice", "lowprice")
    elif field == "volume":
        names = ("volume", "vol", "Volume")
    elif field == "amount":
        names = ("amount", "Amount", "money", "turnover")
    for fname in names:
        for args in (
            (count, period, fname, ""),
            (count, period, fname, "none"),
            (count, period, fname),
            (count, period, fname, "front_ratio"),
        ):
            try:
                raw = fn(*args)
            except TypeError as e:
                last = e
                continue
            except Exception as e:
                last = e
                break
            vals = _from_hist_dict(raw, str(getattr(A, "stock", "") or ""), fname)
            if vals:
                return vals
    if last is not None:
        _diag_once("hist_fail", field, period, last)
    return None


def _history_ohlcv_1m(C, bp):
    """get_history_data 返回 list，不经过 pandas。模型交易无 C.close 时用。"""
    n = max(1, int(bp) + 1)
    count = min(n, 240)
    periods = []
    for p in (getattr(A, "period", None), getattr(C, "period", None), "1m", "1min"):
        s = str(p or "").strip()
        if s and s not in periods:
            periods.append(s)
    closes = None
    used = None
    for period in periods:
        for ctry in (count, max(int(count), 8)):
            closes = _call_history(C, ctry, period, "close")
            if closes:
                used = period
                count = int(ctry)
                break
        if closes:
            break
    if not closes:
        return None
    if len(closes) > n:
        closes = closes[-n:]
    k = len(closes)
    opens = _call_history(C, count, used, "open")
    highs = _call_history(C, count, used, "high")
    lows = _call_history(C, count, used, "low")
    volumes = _call_history(C, count, used, "volume") or [0.0] * k
    amounts = _call_history(C, count, used, "amount") or [0.0] * k
    if not opens:
        _diag_once("hist_open_missing", "period=", used)
        opens = list(closes)
    if not highs:
        _diag_once("hist_high_missing", "period=", used)
        highs = list(closes)
    if not lows:
        _diag_once("hist_low_missing", "period=", used)
        lows = list(closes)
    if len(opens) > k:
        opens = opens[-k:]
    if len(highs) > k:
        highs = highs[-k:]
    if len(lows) > k:
        lows = lows[-k:]
    if len(volumes) > k:
        volumes = volumes[-k:]
    if len(amounts) > k:
        amounts = amounts[-k:]
    if len(opens) < k:
        opens = list(closes)
    if len(highs) < k:
        highs = list(closes)
    if len(lows) < k:
        lows = list(closes)
    if len(volumes) < k:
        volumes = [0.0] * k
    if len(amounts) < k:
        amounts = [0.0] * k
    eq = 0
    for i in range(k):
        try:
            if abs(float(opens[i]) - float(closes[i])) < 1e-8:
                eq += 1
        except Exception:
            pass
    _diag_once("ohlc_cmp", "open_eq_close=", eq, "/", k, "src=hist")
    times = []
    miss = 0
    look = k
    idx0 = max(0, int(bp) + 1 - k)
    for j in range(k):
        ts = _timetag_str(C, idx0 + j)
        if not ts:
            miss += 1
        times.append(ts)
    if miss > look // 2:
        times = _synth_1m_times(look, _bar_datetime(C))
        _diag_once("m1_time_synth", "n=", look, "src=hist")
    if len(times) != look:
        return None
    _diag_once("hist_ok", "period=", used, "n=", k)
    return opens, highs, lows, closes, volumes, amounts, times


def _times_for_window(C, bp, n):
    """最近 n 根对应主图下标 [bp-n+1, bp]，不要用 0..n-1（那是上市日）。"""
    n = max(1, int(n))
    bp = int(bp)
    idx0 = max(0, bp + 1 - n)
    times = []
    miss = 0
    for j in range(n):
        ts = _timetag_str(C, idx0 + j)
        if not ts:
            miss += 1
        times.append(ts)
    if miss > n // 2:
        times = _synth_1m_times(n, _bar_datetime(C))
        _diag_once("m1_time_synth", "n=", n, "bp=", bp)
    return times


def _align_ohlcv_times(C, bp, opens, highs, lows, closes, volumes, amounts, times):
    """ori/history 只返回最近若干根时，时间戳必须对齐当前 barpos，而不是图表从头。"""
    if not closes:
        return None
    look = min(len(closes), 240)
    if not opens or len(opens) < look:
        opens = list(closes)
    if not highs or len(highs) < look:
        highs = list(closes)
    if not lows or len(lows) < look:
        lows = list(closes)
    if not volumes or len(volumes) < look:
        volumes = [0.0] * look
    if not amounts or len(amounts) < look:
        amounts = [0.0] * look
    opens = opens[-look:]
    highs = highs[-look:]
    lows = lows[-look:]
    closes = closes[-look:]
    volumes = volumes[-look:]
    amounts = amounts[-look:]
    times_use = None
    if times and len(times) >= look:
        times_use = [_norm_bar_time(x) for x in times[-look:]]
        if not any(times_use):
            times_use = None
    bar_day = ""
    try:
        bar_day = _bar_datetime(C).strftime("%Y%m%d")
    except Exception:
        bar_day = ""
    last = (times_use[-1] if times_use else "") or ""
    if (not times_use) or (bar_day and last[:8] != bar_day):
        times_use = _times_for_window(C, bp, look)
        last = (times_use[-1] if times_use else "") or ""
        if bar_day and last[:8] != bar_day:
            times_use = _synth_1m_times(look, _bar_datetime(C))
            _diag_once("m1_time_synth", "n=", look, "bp=", bp, "force_day=", bar_day)
    if (not times_use) or len(times_use) != look:
        return None
    return opens, highs, lows, closes, volumes, amounts, times_use


def _ori_fetch_md(C, bp, count):
    fn = getattr(C, "get_market_data_ex_ori", None)
    if not callable(fn):
        return None
    stock = str(getattr(A, "stock", "") or "")
    end = _bar_datetime(C).strftime("%Y%m%d%H%M%S")
    fields = ["open", "high", "low", "close", "volume", "amount"]
    try:
        return fn(
            fields,
            [stock],
            period="1m",
            end_time=end,
            count=int(count),
            subscribe=False,
        )
    except TypeError:
        try:
            return fn(fields, [stock], "1m", "", end, int(count), "none")
        except Exception as e:
            _diag_once("ori_fail", e)
            return None
    except Exception as e:
        _diag_once("ori_fail", e)
        return None


def _pack_from_ori_md(C, bp, md):
    stock = str(getattr(A, "stock", "") or "")
    close = _series_from_ex(md, stock, "close") or _from_hist_dict(md, stock, "close")
    if not close:
        return None
    open_ = _series_from_ex(md, stock, "open") or _from_hist_dict(md, stock, "open")
    high = _series_from_ex(md, stock, "high") or _from_hist_dict(md, stock, "high")
    low = _series_from_ex(md, stock, "low") or _from_hist_dict(md, stock, "low")
    volume = _series_from_ex(md, stock, "volume") or _from_hist_dict(md, stock, "volume")
    amount = _series_from_ex(md, stock, "amount") or _from_hist_dict(md, stock, "amount")
    times = _times_from_ex(md, stock)
    return _align_ohlcv_times(C, bp, open_, high, low, close, volume, amount, times)


def _concat_1m_pack(prev, extra, max_n=240):
    if prev is None:
        return extra
    if extra is None:
        return prev
    out = []
    for a, b in zip(prev, extra):
        merged = list(a) + list(b)
        if len(merged) > max_n:
            merged = merged[-max_n:]
        out.append(merged)
    return tuple(out)


def _ori_ohlcv_1m(C, bp):
    """get_market_data_ex_ori 走 numpy，避开 pandas DataFrame。"""
    bp = int(bp)
    prev_bp = int(getattr(A, "_ori_tail_bp", -9))
    prev = getattr(A, "_ori_tail_pack", None)
    if prev is not None and prev_bp >= 0 and bp == prev_bp + 1:
        md_one = _ori_fetch_md(C, bp, 1)
        one = _pack_from_ori_md(C, bp, md_one) if md_one is not None else None
        if one is not None:
            if prev[6] and one[6] and prev[6][-1] == one[6][-1]:
                pack = prev
            else:
                pack = _concat_1m_pack(prev, one, 240)
            A._ori_tail_bp = bp
            A._ori_tail_pack = pack
            return pack
    n = max(1, bp + 1)
    count = min(n, 240)
    md = _ori_fetch_md(C, bp, count)
    if md is None:
        return None
    pack = _pack_from_ori_md(C, bp, md)
    if pack is None:
        return None
    A._ori_tail_bp = bp
    A._ori_tail_pack = pack
    _diag_once(
        "ori_ok",
        "n=",
        len(pack[3]),
        "end=",
        _bar_datetime(C).strftime("%Y%m%d%H%M%S"),
        "t0=",
        pack[6][0] if pack[6] else "",
        "t1=",
        pack[6][-1] if pack[6] else "",
    )
    return pack


def _timetag_str(C, i):
    try:
        tag = C.get_bar_timetag(i)
        if "timetag_to_datetime" in globals():
            s = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
            return str(s)
        if tag > 10**12:
            return datetime.datetime.fromtimestamp(tag / 1000.0).strftime("%Y%m%d%H%M%S")
        return datetime.datetime.fromtimestamp(tag).strftime("%Y%m%d%H%M%S")
    except Exception:
        return ""


def _chart_ohlcv_1m(C):
    """主图 1 分钟 OHLCV，切到当前 barpos（含）。"""
    try:
        bp = int(getattr(C, "barpos", 0) or 0)
    except Exception:
        bp = 0
    if bp < 0:
        return None
    if int(getattr(A, "_chart_bp", -2)) == bp:
        cached = getattr(A, "_chart_pack", None)
        if cached is not None:
            return cached
    nwant = bp + 1
    pack = None
    closes = None
    if nwant <= 400:
        closes = _ctx_field(C, ("close", "get_close", "get_close_price"), nwant)
    if closes:
        n = min(len(closes), nwant)
        if n > 0:
            opens = _ctx_field(C, ("open", "get_open"), nwant)
            highs = _ctx_field(C, ("high", "get_high"), nwant)
            lows = _ctx_field(C, ("low", "get_low"), nwant)
            volumes = _ctx_field(C, ("volume", "vol", "get_volume"), nwant)
            amounts = _ctx_field(C, ("amount", "money", "turnover", "get_amount"), nwant)
            if not opens or len(opens) < n:
                opens = list(closes)
            if not highs or len(highs) < n:
                highs = list(closes)
            if not lows or len(lows) < n:
                lows = list(closes)
            if not volumes or len(volumes) < n:
                volumes = [0.0] * n
            if not amounts or len(amounts) < n:
                amounts = [0.0] * n
            opens = opens[:n]
            highs = highs[:n]
            lows = lows[:n]
            closes = closes[:n]
            volumes = volumes[:n]
            amounts = amounts[:n]
            look = min(n, 300)
            start = n - look
            times = []
            miss = 0
            for i in range(start, n):
                ts = _timetag_str(C, i)
                if not ts:
                    miss += 1
                times.append(ts)
            if miss > look // 2:
                times = _synth_1m_times(look, _bar_datetime(C))
                _diag_once("m1_time_synth", "n=", look)
            if len(times) == look:
                pack = (
                    opens[start:],
                    highs[start:],
                    lows[start:],
                    closes[start:],
                    volumes[start:],
                    amounts[start:],
                    times,
                )
                A._ohlcv_src = "chart"
    if pack is None:
        _diag_ctx_once(C)
        pack = _ori_ohlcv_1m(C, bp)
        if pack is not None:
            A._ohlcv_src = "ori"
    if pack is None:
        pack = _history_ohlcv_1m(C, bp)
        if pack is not None:
            A._ohlcv_src = "history"
    A._chart_bp = bp
    A._chart_pack = pack
    return pack


def _norm_bar_time(x):
    """行情时间 -> yyyymmddHHMMSS。"""
    if x is None:
        return ""
    try:
        if hasattr(x, "strftime"):
            return x.strftime("%Y%m%d%H%M%S")
    except Exception:
        pass
    try:
        if isinstance(x, (int, float)) or (hasattr(x, "item") and not isinstance(x, str)):
            iv = int(x)
            if iv > 10**12:
                return datetime.datetime.fromtimestamp(iv / 1000.0).strftime("%Y%m%d%H%M%S")
            s = str(iv)
            if len(s) >= 14:
                return s[:14]
            if len(s) == 12:
                return s + "00"
            if len(s) == 8:
                return s + "000000"
    except Exception:
        pass
    s = str(x).strip()
    digits = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        elif digits and ch in "- T:./":
            continue
        elif digits:
            break
    d = "".join(digits)
    if len(d) >= 14:
        return d[:14]
    if len(d) >= 8:
        return (d + "000000")[:14]
    return ""


def _times_from_ex(md, stock):
    if md is None:
        return None
    df = None
    if isinstance(md, dict) and stock in md:
        df = md[stock]
    elif isinstance(md, dict):
        for v in md.values():
            df = v
            break
    if df is None:
        return None
    raw = None
    if isinstance(df, dict):
        for col in ("stime", "time", "datetime", "date"):
            if col in df:
                try:
                    raw = list(df[col])
                    break
                except Exception:
                    raw = None
    if (not raw) and hasattr(df, "dtype") and getattr(df.dtype, "names", None):
        names = df.dtype.names
        for col in ("stime", "time", "datetime", "date"):
            if col in names:
                try:
                    raw = list(df[col])
                    break
                except Exception:
                    raw = None
    if (not raw) and hasattr(df, "index"):
        try:
            raw = list(df.index)
        except Exception:
            raw = None
    if (not raw) and hasattr(df, "columns"):
        cols = getattr(df, "columns", [])
        for col in ("time", "stime", "datetime", "date"):
            try:
                if col in cols:
                    raw = list(df[col])
                    break
            except Exception:
                continue
    if not raw:
        return None
    out = [_norm_bar_time(x) for x in raw]
    if not any(out):
        return None
    return out


def _synth_1m_times(n, end_dt):
    times = []
    t = end_dt.replace(second=0, microsecond=0)
    guard = 0
    while len(times) < n and guard < n * 20 + 50:
        guard += 1
        hhmm = t.strftime("%H%M")
        if ("0930" <= hhmm <= "1130") or ("1300" <= hhmm <= "1500"):
            times.append(t.strftime("%Y%m%d%H%M%S"))
        t -= datetime.timedelta(minutes=1)
    times.reverse()
    return times


def _fetch_md(C, stock, period, fields, end, count, diag_key):
    """日线等跨周期取数。1m 不要走这里。pandas 损坏后本会话不再重试。"""
    if getattr(A, "_md_pandas_broken", False):
        return None, None
    md = None
    source = None
    flist = list(fields)
    try:
        md = C.get_market_data_ex(
            flist,
            [stock],
            period=period,
            end_time=end,
            count=int(count),
            dividend_type="front_ratio",
            subscribe=False,
        )
        source = "get_market_data_ex"
    except TypeError:
        try:
            md = C.get_market_data_ex(
                flist,
                [stock],
                period=period,
                start_time="",
                end_time=end,
                count=int(count),
                dividend_type="front_ratio",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            if _pandas_broken_msg(e):
                _mark_pandas_broken(e)
            else:
                _diag_once(diag_key + "_ex_fail", e)
            md = None
    except Exception as e:
        if _pandas_broken_msg(e):
            _mark_pandas_broken(e)
        else:
            _diag_once(diag_key + "_ex_fail", e)
        md = None
    return md, source


def _get_ohlcv_1m(C, stock):
    """已对齐的 1 分钟 OHLCV + amount + 时间戳。"""
    end = _bar_datetime(C).strftime("%Y%m%d%H%M%S")
    pack = _chart_ohlcv_1m(C)
    if pack is not None:
        open_, high, low, close, volume, amount, times = pack
        n = len(close)
        need = int(globals().get("DOWN_BARS") or 3) + 2
        if n >= need:
            _diag_once(
                "ok",
                "source=",
                str(getattr(A, "_ohlcv_src", "chart") or "chart"),
                "period=1m n=",
                n,
                "end=",
                end,
                "t0=",
                times[0] if times else "",
                "t1=",
                times[-1] if times else "",
                "last=",
                round(float(close[-1]), 4),
                "stock=",
                stock,
            )
            return pack
        _diag_once("chart_short", "n=", n, "need=", need)
        return None
    _diag_once("chart_miss", "end=", end, "stock=", stock)
    return None


def _today_indices(times, day):
    out = []
    for i, ts in enumerate(times or []):
        if not ts or len(ts) < 12:
            continue
        if ts[:8] != day:
            continue
        hhmm = ts[8:12]
        if ("0930" <= hhmm <= "1130") or ("1300" <= hhmm <= "1500"):
            out.append(i)
    return out


def _get_daily_adv(C, stock, today):
    """近 ADV_DAYS 个已收盘日的日均成交额。"""
    cache_day = str(getattr(A, "_adv_cache_day", "") or "")
    if cache_day == today:
        return getattr(A, "_adv_cache_val", None)
    val = None
    if getattr(A, "is_backtest", False) or getattr(A, "_md_pandas_broken", False):
        A._adv_cache_day = today
        A._adv_cache_val = None
        return None
    end = today
    count = int(globals().get("DAILY_OHLC_COUNT") or 12)
    md, _src = _fetch_md(C, stock, "1d", ["amount", "close"], end, count, "d1")
    amounts = _series_from_ex(md, stock, "amount") if md is not None else None
    times = _times_from_ex(md, stock) if md is not None else None
    if amounts:
        days = int(globals().get("ADV_DAYS") or 5)
        picked = []
        n = len(amounts)
        for i in range(n):
            d = ""
            if times and i < len(times) and times[i]:
                d = times[i][:8]
            a = float(amounts[i] or 0)
            if a <= 0:
                continue
            if d and d >= today:
                continue
            picked.append(a)
        if picked:
            use = picked[-days:]
            if use:
                val = sum(use) / float(len(use))
    A._adv_cache_day = today
    A._adv_cache_val = val
    return val


def _prev_close_from_times(closes, times, today):
    if not closes or not times:
        return None
    n = min(len(closes), len(times))
    for i in range(n - 1, -1, -1):
        ts = times[i] or ""
        if len(ts) < 8:
            continue
        if ts[:8] >= today:
            continue
        px = float(closes[i] or 0)
        if px > 0:
            return px
    return None


def _get_prev_close(C, stock, today):
    cache_day = str(getattr(A, "_preclose_day", "") or "")
    if cache_day == today and getattr(A, "_preclose_val", None) is not None:
        return A._preclose_val
    found = None
    pack = _chart_ohlcv_1m(C)
    if pack is not None:
        _o, _h, _l, closes, _v, _a, times = pack
        found = _prev_close_from_times(closes, times, today)
    if found is None and (not getattr(A, "is_backtest", False)) and (not getattr(A, "_md_pandas_broken", False)):
        end = today
        md, _src = _fetch_md(C, stock, "1d", ["close"], end, 8, "d1c")
        closes = _series_from_ex(md, stock, "close") if md is not None else None
        times = _times_from_ex(md, stock) if md is not None else None
        if closes:
            n = len(closes)
            for i in range(n - 1, -1, -1):
                d = ""
                if times and i < len(times) and times[i]:
                    d = times[i][:8]
                if d and d >= today:
                    continue
                px = float(closes[i] or 0)
                if px > 0:
                    found = px
                    break
            if found is None and n >= 2 and float(closes[-2] or 0) > 0:
                found = float(closes[-2])
    A._preclose_day = today
    A._preclose_val = found
    return found


def _parse_tick(raw, stock):
    if raw is None:
        return None
    if isinstance(raw, dict):
        if stock in raw and isinstance(raw[stock], dict):
            return raw[stock]
        if "lastPrice" in raw or "lastClose" in raw or "bid" in raw:
            return raw
        keys = list(raw.keys())
        if len(keys) == 1 and isinstance(raw[keys[0]], dict):
            return raw[keys[0]]
    return None


def _get_tick(C, stock):
    fn = getattr(C, "get_full_tick", None)
    if not callable(fn):
        fn = globals().get("get_full_tick")
    if not callable(fn):
        return None
    try:
        raw = fn([stock])
    except Exception as e:
        _diag_once("tick_fail", e)
        return None
    return _parse_tick(raw, stock)


def _tick_num(tick, *names):
    if not tick:
        return None
    for name in names:
        if name not in tick:
            continue
        try:
            v = float(tick.get(name) or 0)
        except Exception:
            continue
        if v > 0:
            return v
    return None


def _tick_vwap(tick):
    amt = _tick_num(tick, "amount")
    vol = _tick_num(tick, "volume")
    if amt is None or vol is None or vol <= 0:
        return None
    return amt / vol


def _tick_spread(tick):
    bid = _tick_num(tick, "bid", "bidPrice", "bid1", "bidPrice1")
    ask = _tick_num(tick, "ask", "askPrice", "ask1", "askPrice1")
    if bid is None or ask is None or ask <= bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid

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
    if want < _vol_step():
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
    if want < _vol_step():
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
    step = _vol_step()
    done_fill = traded >= target and target >= step
    status_filled = status in filled
    status_dead = status in dead

    if done_fill or (status_filled and traded >= step):
        use_vol = traded if traded >= step else deal_vol
        if side == "buy":
            _pending_on_buy_fill(pend, use_vol, px)
        else:
            _pending_on_sell_fill(pend, now, use_vol, px)
        _clear_pending("filled")
        return False

    if status_dead:
        if traded >= _vol_step():
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
# add=True: 已有仓上加仓；SCALE_LOTS 时记独立笔，否则均价合并（默认仍一票一仓）
def _try_lots_buy(px, add, vol, opened_at):
    if not bool(globals().get("SCALE_LOTS")):
        return
    fn = globals().get("_lots_on_buy_fill")
    if callable(fn):
        fn(px, add=add, vol=vol, opened_at=opened_at)


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
    if vol < _vol_step():
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
        _try_lots_buy(price, True, vol, ot)
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
    _try_lots_buy(price, False, vol, ot)
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position)
    _event_log("buy_filled", position=A.position, vol=vol, price=price, opened_at=ot)


def _apply_sell_fill(now, reason, last_hint, filled_vol, mark_half=False, lot_ids=None):
    """卖出成交后清空或缩减持仓. 仅按实际成交量改状态.
    SCALE_LOTS + lot_ids: 按笔减仓，不因 95% 误清剩余笔。"""
    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    filled_vol = int(filled_vol)
    if filled_vol < _vol_step():
        return
    partial_lots = False
    if bool(globals().get("SCALE_LOTS")) and lot_ids:
        fn = globals().get("_exit_is_partial")
        if callable(fn):
            partial_lots = bool(fn(lot_ids))
    if (not partial_lots) and (
        filled_vol >= max(_vol_step(), int(want * 0.95)) or filled_vol >= want
    ):
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
        lot_ids=lot_ids,
    )
    _bt_held_set(remain)
    lots_fn = globals().get("_lots_on_sell_fill")
    if bool(globals().get("SCALE_LOTS")) and callable(lots_fn):
        lots_fn(lot_ids, filled_vol)
    elif A.position:
        A.position["shares"] = remain
    if remain < _vol_step() or not _has_position():
        _clear_after_sell(now, str(reason) + "/partial", last=last_hint)
    else:
        if mark_half:
            A.acted.add("HALF")
        acted = getattr(A, "acted", None)
        if isinstance(acted, set):
            acted.discard("SELL")
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
    lot_ids = pend.get("lot_ids")
    _apply_sell_fill(now, intent, last_hint, vol, mark_half=mark_half, lot_ids=lot_ids)


def _order_buy(C, price, now, budget=None, add=False, **extra_pos):
    """提交买入. DRY 即时; 回测 passorder+即时; 实盘 pending 至成交.
    add=True 允许在已有仓上加仓；SCALE_LOTS 时每笔独立，否则均价合并。默认仍一票一仓。"""
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    holding_now = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= _vol_step()
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
    if vol < _vol_step():
        print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
        _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _lot(price, cash)
        if vol < _vol_step():
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


def _order_sell(C, reason, price, now, want_vol=None, mark_half=False, lot_ids=None):
    """提交卖出. T+1: 下单量不超过可卖; skip 绝不清仓.
    lot_ids: SCALE_LOTS 时指定要平的笔；部分笔自动 mark_half。"""
    if getattr(A, "pending", None):
        print(_strategy_tag(), "sell skip: pending active")
        _event_log("sell_skip", reason="pending_active", sell_reason=reason)
        return False
    if not _has_position() and not (getattr(A, "is_backtest", False) and _bt_held_vol() >= _vol_step()):
        return False
    if lot_ids:
        fn = globals().get("_exit_is_partial")
        if callable(fn) and fn(lot_ids):
            mark_half = True
        if want_vol is None:
            wv = globals().get("_lots_want_vol")
            if callable(wv):
                want_vol = wv(lot_ids)
    if (not mark_half) and ("SELL" in getattr(A, "acted", set())):
        return False

    want = int(want_vol) if want_vol is not None else _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol()) if want_vol is None else want
    if want < _vol_step():
        return False

    avail = _max_sell_vol(now)
    vol = int(min(want, avail) // _vol_step()) * _vol_step()
    if vol < _vol_step():
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
        _apply_sell_fill(now, reason, price, vol, mark_half=mark_half, lot_ids=lot_ids)
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
        _apply_sell_fill(now, reason, price, vol, mark_half=mark_half, lot_ids=lot_ids)
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
        "lot_ids": list(lot_ids) if lot_ids else None,
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

# === vwapbias/strategy.py ===
def _t6(x):
    s = str(x or "").strip().replace(":", "")
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return "000000"
    return digits.zfill(6)[-6:]


def _bar_hhmmss(dt):
    if dt is None:
        return "000000"
    return dt.strftime("%H%M%S")


def _session_phase(t6):
    t = _t6(t6)
    start = _t6(globals().get("DECISION_START") or "093000")
    end = _t6(globals().get("DECISION_END") or "150000")
    lunch_a = _t6(globals().get("LUNCH_START") or "113000")
    lunch_b = _t6(globals().get("LUNCH_END") or "130000")
    warm_am = _t6(globals().get("OPEN_SKIP_AM_END") or "093500")
    warm_pm_a = _t6(globals().get("OPEN_SKIP_PM_START") or "130000")
    warm_pm_b = _t6(globals().get("OPEN_SKIP_PM_END") or "130500")
    no_new = _t6(globals().get("NO_NEW_ENTRY") or "144000")
    flat = _t6(globals().get("FLAT_START") or "145000")
    if t < start or t > end:
        return "closed"
    if lunch_a <= t < lunch_b:
        return "lunch"
    if (start <= t < warm_am) or (warm_pm_a <= t < warm_pm_b):
        return "warmup"
    if flat <= t <= end:
        return "flatten"
    if no_new <= t < flat:
        return "sell_only"
    return "trade"


def _max_lots():
    mx = int(globals().get("SCALE_MAX") or 2)
    if bool(globals().get("ENABLE_L3")):
        return max(mx, 3)
    return max(1, min(mx, 2))


def _lot_budget(weight):
    cap = _trade_budget_cap()
    return float(cap) * float(weight)


def _reset_acted_bar(tag):
    if str(getattr(A, "acted_closed", "") or "") == str(tag):
        return
    A.acted_closed = str(tag)
    A.acted = set()


def _profit_lot_ids(price):
    ids = []
    lots = _ensure_lots() if _lots_enabled() else []
    if not lots:
        return ids
    px = float(price)
    for lot in lots:
        try:
            cost = float(lot.get("price") or 0)
            lid = int(lot.get("id") or 0)
        except Exception:
            continue
        if lid and cost > 0 and px >= cost:
            ids.append(lid)
    return ids


def _tp_lot_ids(price, tp):
    ids = []
    tp = float(tp or 0)
    if tp <= 0:
        return ids
    lots = _ensure_lots() if _lots_enabled() else []
    if not lots:
        return ids
    px = float(price)
    for lot in lots:
        try:
            cost = float(lot.get("price") or 0)
            lid = int(lot.get("id") or 0)
        except Exception:
            continue
        if lid and cost > 0 and (px - cost) / cost >= tp:
            ids.append(lid)
    return ids


def _univ_skip_reason(stock, day, px, tick, C):
    expect = str(globals().get("EXPECT_STOCK") or "").strip().upper()
    if expect and str(stock).upper() != expect:
        return "wrong_symbol"
    for bad in (globals().get("FORBID_STOCKS") or ()):
        if str(stock).upper() == str(bad).upper():
            return "forbid_stock"
    adv_min = float(globals().get("ADV_MIN") or 0)
    if adv_min > 0:
        adv = _get_daily_adv(C, stock, day)
        if adv is None:
            if not getattr(A, "is_backtest", False):
                return "adv_unknown"
        elif adv < adv_min:
            return "adv"
    spread_max = float(globals().get("SPREAD_MAX") or 0)
    if (not getattr(A, "is_backtest", False)) and spread_max > 0:
        sp = _tick_spread(tick)
        if sp is not None and sp > spread_max:
            return "spread"
    near = float(globals().get("LIMIT_NEAR") or 0)
    if near > 0 and px and px > 0:
        pre = _tick_num(tick, "lastClose")
        if pre is None:
            pre = _get_prev_close(C, stock, day)
        if pre and pre > 0:
            ret = abs(float(px) / float(pre) - 1.0)
            if ret >= near:
                return "limit"
    return None


def _try_sell(C, reason, price, now, lot_ids=None):
    ok = _order_sell(C, reason, price, now, lot_ids=lot_ids)
    if ok:
        print(_strategy_tag(), reason, "px=", round(float(price), 4))
        _event_log("sell_signal", sell_reason=reason, price=price, lot_ids=lot_ids)
    return ok


def _try_buy(C, tag, price, now, weight, add):
    budget = _lot_budget(weight)
    ok = _order_buy(C, price, now, budget=budget, add=add)
    if ok:
        A.hold_peak_ret = None
        print(_strategy_tag(), tag, "px=", round(float(price), 4), "budget=", round(budget, 2))
        _event_log("buy_signal", tag=tag, price=price, budget=budget, add=add)
    return ok


def _mark_after_sell():
    A.hold_peak_ret = None
    holding = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= _vol_step()
    )
    if holding:
        A.scale_out_lock = True
    else:
        A.scale_out_lock = False


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        if now_s < _t6(DECISION_START) or now_s > _t6(DECISION_END):
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

    if bt:
        nprog = int(getattr(A, "_bt_prog", 0) or 0) + 1
        A._bt_prog = nprog
        if nprog <= 5 or nprog % 120 == 0:
            print(
                _strategy_tag(),
                "progress n=",
                nprog,
                "barpos=",
                getattr(C, "barpos", None),
                "day=",
                day,
                "now=",
                now.strftime("%Y%m%d%H%M%S"),
            )

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    pack = _get_ohlcv_1m(C, A.stock)
    if pack is None:
        _live_heartbeat("ohlcv_1m_none")
        return
    opens, highs, lows, closes, volumes, amounts, times = pack
    today_idx = _today_indices(times, day)
    if not today_idx:
        _diag_once(
            "no_today_1m",
            "day=",
            day,
            "n=",
            len(times or []),
            "t0=",
            times[0] if times else "",
            "t1=",
            times[-1] if times else "",
            "barpos=",
            getattr(C, "barpos", None),
        )
        nprog = int(getattr(A, "_bt_prog", 0) or 0)
        if (not bt) or nprog <= 5:
            print(
                _strategy_tag(),
                "no_today_1m",
                "day=",
                day,
                "t0=",
                times[0] if times else "",
                "t1=",
                times[-1] if times else "",
            )
        return

    if bt:
        closed_i = today_idx[-1]
    else:
        if len(today_idx) < 2:
            _live_heartbeat("no_closed_1m")
            return
        closed_i = today_idx[-2]

    closed_tag = times[closed_i] if closed_i < len(times) else now.strftime("%Y%m%d%H%M%S")
    if str(getattr(A, "acted_closed", "") or "") == str(closed_tag):
        if not bt:
            _live_heartbeat("acted_bar")
        return
    _reset_acted_bar(closed_tag)

    sig_s = closed_tag[8:14] if len(closed_tag) >= 14 else now_s
    session_s = now_s if not bt else sig_s
    phase = _session_phase(session_s)

    day_closed = [j for j in today_idx if j <= closed_i]
    vwap, vwap_src = _cum_vwap(amounts, volumes, highs, lows, closes, day_closed)
    px = float(closes[closed_i])
    bias = _bias_of(px, vwap)

    tick = None if bt else _get_tick(C, A.stock)
    live_px = _tick_num(tick, "lastPrice") if tick else None
    if live_px is None:
        live_px = px
    stop_px = live_px if not bt else px
    tick_vw = _tick_vwap(tick) if tick else None

    holding = _has_position() or (bt and _bt_held_vol() >= _vol_step())
    if holding and (not _has_position()):
        _bt_recover_position(now=now, last=px)

    if vwap is None or bias is None:
        print(_strategy_tag(), "vwap not ready", "src=", vwap_src, "bar=", closed_tag)
        _event_log("vwap_skip", vwap_src=vwap_src, bar=closed_tag)
        A.acted_closed = closed_tag
        _save_state()
        return

    if not getattr(A, "ready_logged", False):
        A.ready_logged = True
        print(
            _strategy_tag(),
            "ready",
            A.stock,
            "VOL_STEP=",
            _vol_step(),
            "ALLOW_T0=",
            ALLOW_T0,
            "SCALE_LOTS=",
            SCALE_LOTS,
        )

    noisy = (
        bt
        or holding
        or (abs(float(bias)) >= abs(float(BIAS_L1)))
        or phase in ("flatten", "sell_only", "warmup")
        or str(getattr(A, "_printed_day", "") or "") != day
    )
    if noisy:
        A._printed_day = day
        print(
            _strategy_tag(),
            "bar",
            closed_tag,
            "phase=",
            phase,
            "close=",
            round(px, 4),
            "vwap=",
            round(float(vwap), 4),
            "vwap_src=",
            vwap_src,
            "bias=",
            round(float(bias) * 100.0, 3),
            "tick_vwap=",
            None if tick_vw is None else round(float(tick_vw), 4),
            "lots=",
            _pos_lots(),
            "held=",
            _pos_shares(),
        )
    _bar_log(
        bar=closed_tag,
        phase=phase,
        close=px,
        vwap=vwap,
        vwap_src=vwap_src,
        bias=bias,
        lots=_pos_lots(),
        held=_pos_shares(),
    )

    if phase in ("closed", "lunch", "warmup"):
        A.acted_closed = closed_tag
        _save_state()
        if phase == "warmup" and not bt:
            _live_heartbeat("open_skip")
        return

    did = False
    if holding:
        cost = _pos_cost_price()
        if phase == "flatten":
            did = _try_sell(C, "eod_flatten", stop_px, now)
            if did:
                _mark_after_sell()
        elif cost > 0 and (stop_px - cost) / cost <= -float(STOP_LOSS):
            did = _try_sell(C, "stop_loss", stop_px, now)
            if did:
                A.risk_skip_day = day
                _mark_after_sell()
                _save_state()
        elif phase in ("trade", "sell_only"):
            ret_now = (float(stop_px) - cost) / cost if cost > 0 else 0.0
            peak = getattr(A, "hold_peak_ret", None)
            try:
                peak = float(peak) if peak is not None else None
            except Exception:
                peak = None
            if peak is None or ret_now > peak:
                A.hold_peak_ret = ret_now
                peak = ret_now
            arm = float(globals().get("TRAIL_ARM") or 0)
            give = float(globals().get("TRAIL_GIVE") or 0)
            if (not did) and arm > 0 and give > 0 and peak >= arm and ret_now <= (peak - give):
                did = _try_sell(C, "trail_stop", stop_px, now)
                if did:
                    _mark_after_sell()
            tp = float(globals().get("TAKE_PROFIT") or 0)
            if (not did) and tp > 0:
                if _lots_enabled():
                    lids = _tp_lot_ids(px, tp)
                    if lids:
                        did = _try_sell(C, "take_profit", px, now, lot_ids=lids)
                        if did:
                            _mark_after_sell()
                elif cost > 0 and (px - cost) / cost >= tp:
                    did = _try_sell(C, "take_profit", px, now)
                    if did:
                        _mark_after_sell()
            fade_ok = bias >= float(BIAS_FADE) and len(day_closed) >= 2
            if fade_ok and bias < float(BIAS_FADE) + 0.004:
                fade_ok = _fade_vol_ok(
                    volumes, day_closed[-1], day_closed[-2], float(VOL_GAP)
                )
            if (not did) and fade_ok:
                did = _try_sell(C, "fade_sell", px, now)
                if did:
                    _mark_after_sell()
            if (not did) and bias >= float(REVERSION_BIAS):
                if _lots_enabled():
                    lids = _profit_lot_ids(px)
                    if lids:
                        did = _try_sell(C, "vwap_reversion", px, now, lot_ids=lids)
                        if did:
                            _mark_after_sell()
                else:
                    if cost <= 0 or px >= cost:
                        did = _try_sell(C, "vwap_reversion", px, now)
                        if did:
                            _mark_after_sell()

    holding = _has_position() or (bt and _bt_held_vol() >= _vol_step())
    if not holding:
        A.scale_out_lock = False
        A.hold_peak_ret = None
    can_buy = phase == "trade"
    if can_buy and str(getattr(A, "risk_skip_day", "") or "") == day:
        can_buy = False
        _diag_once("risk_skip_" + day, day)
        _event_log("buy_skip", reason="risk_skip", day=day)
    if can_buy and bool(getattr(A, "scale_out_lock", False)) and holding:
        can_buy = False
        _diag_once("scale_out_" + day, day)
        _event_log("buy_skip", reason="scale_out_lock", day=day)
    if can_buy and "SELL" in getattr(A, "acted", set()):
        can_buy = False
    if can_buy and getattr(A, "pending", None):
        can_buy = False

    if can_buy:
        live_check_px = live_px
        why = _univ_skip_reason(A.stock, day, live_check_px, tick, C)
        if why:
            _diag_once("univ_" + str(why) + "_" + day, why)
            _event_log("univ_skip", reason=why, price=live_check_px)
        else:
            nlot = _pos_lots() if holding else 0
            mx = _max_lots()
            if nlot >= mx:
                _event_log("buy_skip", reason="lot_skip", n=nlot, max_lots=mx)
            else:
                bias_l1 = float(BIAS_L1)
                bias_l2 = float(BIAS_L2)
                bias_l3 = float(BIAS_L3)
                impulse = _impulse_ok(
                    opens,
                    closes,
                    day_closed,
                    int(DOWN_BARS),
                    float(LAST_DROP),
                    float(IMPULSE_SUM),
                )
                prev_c = None
                if len(day_closed) >= 2:
                    prev_c = closes[day_closed[-2]]
                reversal = _reversal_ok(
                    opens[closed_i],
                    highs[closed_i],
                    lows[closed_i],
                    closes[closed_i],
                    float(SHADOW_RATIO),
                    prev_c,
                )
                deep_open = nlot == 0 and bias <= float(BIAS_L2)
                if (not impulse) or ((not reversal) and (not deep_open)):
                    _diag_once(
                        "skip_sig_" + day,
                        "impulse=",
                        impulse,
                        "reversal=",
                        reversal,
                        "bias=",
                        round(float(bias) * 100.0, 3),
                    )
                    if bias <= float(BIAS_L1):
                        _diag_once(
                            "skip_l1_" + day,
                            "impulse=",
                            impulse,
                            "reversal=",
                            reversal,
                            "deep=",
                            deep_open,
                            "bias=",
                            round(float(bias) * 100.0, 3),
                        )
                else:
                    want_l3 = (
                        bool(ENABLE_L3)
                        and nlot >= 2
                        and bias <= bias_l3
                    )
                    want_l2 = nlot >= 1 and bias <= bias_l2
                    if want_l2:
                        c0 = _pos_cost_price()
                        if c0 > 0 and px < c0:
                            want_l2 = False
                            _diag_once("l2_uw_" + day, round(float(px), 4), round(float(c0), 4))
                            _event_log(
                                "buy_skip",
                                reason="l2_underwater",
                                price=px,
                                cost=c0,
                                day=day,
                            )
                    want_l1 = nlot == 0 and bias <= bias_l1
                    if want_l3:
                        did = _try_buy(C, "buy_l3", px, now, float(LOT_W3), True)
                    elif want_l2:
                        did = _try_buy(C, "buy_l2", px, now, float(LOT_W2), True)
                    elif want_l1:
                        did = _try_buy(C, "buy_l1", px, now, float(LOT_W1), False)

    A.acted_closed = closed_tag
    _save_state()

# === vwapbias/runtime.py ===
def _as_bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y", "是")


def _apply_panel():
    """策略交易注入 bind -> 写回 config 全局。须由 init() 直接调用。"""
    g = globals()
    names = dict(g)
    try:
        fr = sys._getframe(1)
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


def _reset_runtime_fields():
    A.position = None
    A.acted_day = ""
    A.acted = set()
    A.pending = None
    A.lots = []
    A.acted_closed = ""
    A.risk_skip_day = ""
    A.bt_held = 0
    A.bt_locked = 0
    A.bt_lock_day = ""
    A.bt_opened_at = ""
    A.ready_logged = False
    A._adv_cache_day = ""
    A._adv_cache_val = None
    A._preclose_day = ""
    A._preclose_val = None
    A._md_pandas_broken = False
    A._chart_bp = -2
    A._chart_pack = None
    A._ori_tail_bp = -9
    A._ori_tail_pack = None
    A._bt_prog = 0


def _ensure_runtime_fields():
    if not hasattr(A, "acted") or A.acted is None:
        A.acted = set()
    if not hasattr(A, "pending"):
        A.pending = None
    if not hasattr(A, "lots") or A.lots is None:
        A.lots = []
    if not hasattr(A, "acted_closed"):
        A.acted_closed = ""
    if not hasattr(A, "risk_skip_day"):
        A.risk_skip_day = ""
    if not hasattr(A, "bt_held"):
        A.bt_held = _pos_shares()
    if not hasattr(A, "ready_logged"):
        A.ready_logged = False
    if not hasattr(A, "_md_pandas_broken"):
        A._md_pandas_broken = False
    if not hasattr(A, "_chart_bp"):
        A._chart_bp = -2
    if not hasattr(A, "_chart_pack"):
        A._chart_pack = None
    if not hasattr(A, "_ori_tail_bp"):
        A._ori_tail_bp = -9
    if not hasattr(A, "_ori_tail_pack"):
        A._ori_tail_pack = None
    if not hasattr(A, "_bt_prog"):
        A._bt_prog = 0


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
            _download_hist(A.stock, "1m")
            _download_hist(A.stock, "1d")
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, "1m+1d")

    if A.is_backtest:
        barpos = 0
        try:
            barpos = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            barpos = 0
        fresh = (not getattr(A, "_bt_alive", False)) or (barpos <= 0)
        if fresh:
            _reset_runtime_fields()
            A._bt_alive = True
            print("%s backtest session start barpos=" % STRATEGY_NAME, barpos)
        else:
            _ensure_runtime_fields()
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
        _ensure_runtime_fields()
        A.ready_logged = False

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)

    if str(A.period) != "1m":
        print(_strategy_tag(), "warn chart period=", A.period, "signals still use 1m")

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
        _trade_budget_cap(),
        "VOL_STEP=",
        VOL_STEP,
        "ALLOW_T0=",
        ALLOW_T0,
        "SCALE_LOTS=",
        SCALE_LOTS,
        "BIAS_L1=",
        BIAS_L1,
        "BIAS_L2=",
        BIAS_L2,
        "BIAS_FADE=",
        BIAS_FADE,
        "TAKE_PROFIT=",
        TAKE_PROFIT,
        "TRAIL_ARM=",
        TRAIL_ARM,
        "TRAIL_GIVE=",
        TRAIL_GIVE,
        "LAST_DROP=",
        LAST_DROP,
        "IMPULSE_SUM=",
        IMPULSE_SUM,
        "DOWN_BARS=",
        DOWN_BARS,
        "STOP=",
        STOP_LOSS,
        "expect=",
        EXPECT_STOCK,
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        budget=_trade_budget_cap(),
        vol_step=VOL_STEP,
        allow_t0=ALLOW_T0,
        scale_lots=SCALE_LOTS,
        bias_l1=BIAS_L1,
        bias_l2=BIAS_L2,
        bias_fade=BIAS_FADE,
        take_profit=TAKE_PROFIT,
        trail_arm=TRAIL_ARM,
        trail_give=TRAIL_GIVE,
        stop_loss=STOP_LOSS,
        expect=EXPECT_STOCK,
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
