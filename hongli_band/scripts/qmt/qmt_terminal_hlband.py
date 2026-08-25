#coding:gbk
# 由 _deploy_qmt_gbk.py 自动生成；请勿手改。请编辑策略片段与 scripts/qmt_common/ 后重新部署。
import datetime
import json
import os
import traceback

import numpy as np


# === hlband/config.py ===
# ===================== 用户配置 =====================
# True=只打日志不下单；回测/实盘真下单前务必确认
DRY_RUN = False

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 跟踪池仓位（实盘）。空仓不锁 1/N，只锁 MIN_LOT。当天多只买单先写入共享账本，冻结后均分可部署资金。
# 单只硬顶 MAX_NAME_FRAC * E_s（默认 50%）。E_s = 账户总资产 - 非白名单股票市值（约等于现金+池内市值）。
# k / book_mv 只统计 BOOK_STOCKS；其它持股不占名额、不进 50% 分母。N = 字典长度。
# 约束：N * MIN_LOT <= CASH_RATIO * E_s。增减标的改本表后四图 re-deploy。
# 形态：code → 配置字典。可写 ma_type / ma_lock。
#   MA_STICK_ADAPT=True（默认）：按近半年「趋势粘性」自动选 EMA/SMA；
#     ma_lock=True 时强制用 ma_type，不跑自适应。
#   MA_STICK_ADAPT=False：行为同旧版，BOOK_STOCKS[code].ma_type 优先，否则 MA_TYPE。
# 简写兼容：value 写成 "SMA" 视为 {"ma_type": "SMA"}；旧纯字符串 tuple 仍认作白名单。
BOOK_STOCKS = {
    "600350.SH": {},
    "601398.SH": {},
    "601939.SH": {},
    "513530.SH": {},
}
BOOK_N = 4
DYNAMIC_BUDGET = True
EQUAL_SPLIT = True
# 四图共享信号账本（不是 STATE_FILE；禁止按标的分文件）
BOOK_FILE = r"D:\tradingStrategy\hlband_book.json"
# 确认打卡截止：14:56 打卡，14:56:30 冻结，须在 14:57 集合竞价前完成均分下单
BOOK_FREEZE_CLOSE = "145630"
BOOK_FREEZE_OPEN = "093200"
# 可部署比例（相对 E_s = 总资产-其它股票市值）；其余留作 T+1 / 废单重试
CASH_RATIO = 0.90
# 每只空仓预留的最小进场金额（元）；不足 100 股则实际成交仍按 100 股市值
MIN_LOT = 20000.0
# 单标的市值上限占 E_s 的比例
MAX_NAME_FRAC = 0.50
# 回测无全账户账本时的单笔回落（元）；DYNAMIC_BUDGET=False 时也用此上限
TRADE_BUDGET = 50000.0
# 按标的覆盖预算（key 须与 A.stock 一致，如 513530.SH）；仅回测/关闭动态预算时生效
TRADE_BUDGET_BY_STOCK = {}

# ---- 周线过滤（跨周期；主图仍是日线）----
# 价格均线缺省：EMA 或 SMA（大小写不敏感）。解析顺序见 _ma_kind：
#   粘性自适应（默认开）→ ma_lock 强制 → BOOK_STOCKS.ma_type → 本常量。
# 只作用于周/日价格均线；成交量均量始终 SMA；MACD 仍用 EMA。
MA_TYPE = "EMA"
# 方案二「趋势粘性」：近半年收盘相对基准均线（固定 SMA）的偏离标准差。
#   std 小 = 高粘性/贴线爬坡 → EMA；std 大 = 低粘性/深砸脉冲 → SMA。
#   持仓中不切换线型，避免 time_force / 回踩基准中途跳变。
MA_STICK_ADAPT = True
STICK_LOOKBACK = 120          # 约半年交易日
STICK_MA_N = 20               # 偏离基准均线周期（始终 SMA，避免与待选线型循环依赖）
STICK_STD_THR = 0.025         # 偏离标准差阈值；<= 此值用 EMA，> 用 SMA（可按日志 stick_std 调）
# 周线均线：快/中/生命线/慢线（斐波那契 5/13/34/55）；算法见 _ma_kind
#   MA5 vs MA13 + MACD → 多头判定（仅日志；开仓不强制 weekly_bull）
#   MA34 → 生命线（收盘跌破即周线空，强制清仓）；乖离/斜率过滤也用它
#   MA55 → 数据暖机长度参考（market 取数 need）
W_MA_FAST = 5
W_MA_MID = 13
W_MA_LIFE = 34
W_MA_SLOW = 55
# 周线 MACD 参数（DIF/DEA/柱）；多头要求 DIF>0 且柱>0；死叉且双线在零轴下 → 空
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
# 高位禁开：周线乖离 (MA5-MA34)/MA34 >= 此值 → 不做新开（追高风险）
# 例 0.08 = MA5 相对生命线 MA34 高 8% 以上禁开
W_BIAS_HARD = 0.08
# 低位斜率过滤：乖离 < 此值视为「低位区」；此时若 MA34 未连续向上则禁开
# 例 0.02 = 乖离不足 2% 时要求生命线已拐头向上
W_BIAS_LOW = 0.02
# 低位区判定「连续向上」的周数：需 life[t]>life[t-1]>life[t-2]（即 2 周斜率）
# 常量名 W_MA30_SLOPE_WEEKS 为历史兼容；比较对象是 W_MA_LIFE（34）
W_MA30_SLOPE_WEEKS = 2

# ---- 日线买卖 ----
# 日线均线（算法见标的 ma_type / MA_TYPE）：MA20→回踩/站上/无量阴跌；MA60→回踩支撑 + 时间成本线
D_MA_MID = 20
D_MA_SLOW = 60

# 买点 pullback_vol：缩量回踩强支撑
#   价格贴近 MA20 或 MA60（|价-均线|/均线 <= 容差）且当日量 < N 日均量 * 比例
MA_TOUCH_TOL = 0.025          # 0.025 = 距均线 ±2.5% 内算「回踩到位」
VOL_PULLBACK_N = 10           # 缩量比较的均量窗口（日，始终 SMA）
VOL_PULLBACK_RATIO = 0.9      # 量 < 均量*0.9 视为缩量

# 全局禁开 vol_dry_skip（无量阴跌不言底）：
#   收盘跌破 MA20 且量 < N 日均量 * 比例 → 当天任何买点失效
VOL_DRY_N = 20
VOL_DRY_RATIO = 0.60          # 量 < 20 日均量的 60% 视为无量阴跌

# 卖① trail_stop：阶梯式移动止盈
#   按历史最高浮盈 (peak-cost)/cost 选档；触发条件：
#     自峰值回撤 > giveback，或（若设了 profit_floor）当前浮盈 < 底线
#   元组：(peak_lo, peak_hi, giveback, profit_floor)
#     peak_hi=None 无上限；profit_floor=None 不设硬底线
#   档1 起步保护 [3%,6%)：回撤>1.5%（同旧版，防破本）
#   档2 落袋为安 [6%,10%)：回撤>3% 或 利润跌破 3%
#   档3 放鹰吃肉 >=10%：回撤>4%（利润垫扛日线洗盘）
TRAIL_TIERS = (
    (0.03, 0.06, 0.015, None),
    (0.06, 0.10, 0.03, 0.03),
    (0.10, None, 0.04, None),
)
# 卖② time_force：智能时间成本（防长期磨人，不砍还在趋势里的仓）
#   BARS = 日线慢均线一半：满此日后才把 MA60 当出场地板，不是最长持仓
#   收盘破日线 MA60 → 立即强制平仓
#   仍站上 MA60 且峰值浮盈 < MIN_RET → 豁免一次，再观察 GRACE_BARS 日，期满强平（回收死钱）
#   仍站上 MA60 且峰值 >= MIN_RET → 不按日历强平，交给 trail / 破 MA60 / 周线空
#   MIN_RET 对齐阶梯止盈起步档；0 = 关闭让路（回到期满强平）
TIME_FORCE_BARS = D_MA_SLOW // 2
TIME_FORCE_GRACE_BARS = 5
TIME_FORCE_MIN_RET = 0.03

# 兜底风控（优先级高）
# chase_skip：当日涨幅 (收-昨收)/昨收 >= 此值 → 禁开（防追高）
CHASE_MAX_PCT = 0.05
# stop_loss：收盘价 <= 成本 * (1 - 此值) → 硬止损清仓
STOP_LOSS = 0.08
# weekly_bear 强制清仓：连续 N 个信号日（日 K）仍为空头才挂 pending_exit
#   N<=0 或 1：当天空头即挂（与改前一致）；N=2：连续两日仍空才挂
#   禁开 / 撤买入 pending 仍按「当日」空头即时生效，不要求满 N 日
W_BEAR_CONFIRM_DAYS = 2

# （另有 weekly_bear：周线空头判定见 _eval_weekly；清仓见上）

# 盈利后加仓（回踩加仓 + 破平台推仓，任一即可）：
#   门槛：峰值浮盈 >= SCALE_ARM，且该笔已持仓 >= SCALE_ARM_BARS 日
#   触发（任一）：缩量回踩 / 日线收盘突破前期平台 / 近两周周线 MACD 金叉且柱放大
#   回踩加仓仍受 chase_skip；破平台/金叉不受（突破日允许较大涨幅）
#   执行日若已触发卖点则取消加仓、让路出场
# SCALE_ONCE_PER_ROUND：同一轮持仓只加一次。第一笔止盈后，空仓前不再用另一种信号再加
# SCALE_W_HIST_MIN：周线 MACD 柱低于此值不加（过滤深空头里的冲高）；None 关闭
# SCALE_LOTS=True：每笔独立成本/峰值/止盈；False：均价合并后整仓出
# weekly_bear 仍一次出清剩余各笔；trail_stop / time_force / stop_loss 按笔
SCALE_ENABLE = True
SCALE_MAX = 2
SCALE_ONCE_PER_ROUND = True
SCALE_ARM = 0.03
SCALE_ARM_BARS = 8
SCALE_W_HIST_MIN = -0.01
SCALE_LOTS = True
# 日线平台：回看 N 日（不含当日）高低点；振幅 <= 此值视为平台；收盘站上高点且昨收仍在平台内
SCALE_PLAT_LOOKBACK = 20
SCALE_PLAT_MAX_RANGE = 0.10          # 0.10 = 平台振幅不超过 10%
SCALE_PLAT_BREAK_BUF = 0.0           # 收盘超过平台高点的缓冲；0=收盘严格站上
# 周线 MACD：本周或上周 DIF 上穿 DEA；上周金叉则本周红柱须比上周放大此倍数
SCALE_W_HIST_EXPAND_RATIO = 1.2

# 策略交易面板 bind → 模块常量。编辑器/回测无注入时用上面默认值。
# 只上屏：开关 / 预算袖子 / 硬风控。买点窗口、时间成本、加仓细节、SCALE_LOTS、
# BOOK_N、TRAIL_TIERS、均线周期、粘性自适应、BOOK_STOCKS、MA_TYPE、路径、账号仍只在 config（N 以 BOOK_STOCKS 长度为准）。
PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_min_lot", "MIN_LOT", "float"),
    ("panel_max_name_frac", "MAX_NAME_FRAC", "float"),
    ("panel_w_bias_hard", "W_BIAS_HARD", "float"),
    ("panel_chase_pct", "CHASE_MAX_PCT", "float"),
    ("panel_stop_loss", "STOP_LOSS", "float"),
    ("panel_scale", "SCALE_ENABLE", "bool"),
)

# ---- 行情与运行 ----
# 主图周期；周线另拉 1w 跨周期
PERIOD = "1d"
# 日/周 K 拉取根数（须覆盖最慢均线 + 指标暖机）
OHLC_COUNT = 180
WEEKLY_OHLC_COUNT = 120

# 实盘只在最新一根 bar 决策；回测逐 bar 扫
LIVE_ONLY_LAST_BAR = True
# 实盘：SIGNAL_CONFIRM_* 用当日近似完整日/周 K 确认信号并挂起；
# PENDING_EXEC_* 尾盘窗按现价/收盘价成交（避免隔夜跳空）；确认可早于成交。
# 错过尾盘则保留到下一交易日 OPEN_EXEC_* 开盘窗按开盘价成交。
# 若收盘窗未跑到，开盘对「上一根已收盘日」兜底评估并挂起（同日开盘窗可成交）。
# 判定：confirmed_eval_day < 上一完整交易日 且今日尚未 fallback
# 周线：bt/confirm/开盘 exec·兜底一律含本周未收盘根；日线开盘仍去未收盘日 K
LIVE_CLOSE_CONFIRM = True
# 实盘决策时窗（HHmmss）：盘中处理券商 pending / 心跳；信号成交见 PENDING_EXEC_* / OPEN_EXEC_*
DECISION_START = "093000"
DECISION_END = "150000"
# 信号 pending 主成交窗：连续竞价尾盘，14:57 起已是收盘集合竞价，不再报单。
# 14:56:00 起限价挂卖一（买）/买一（卖）；14:57:00 前结束。错过则次日开盘窗补。
PENDING_EXEC_START = "145600"
PENDING_EXEC_END = "145700"
# 隔夜残留 / 开盘兜底：错过尾盘时次日开盘窗按开盘价补成交
OPEN_EXEC_START = "093000"
OPEN_EXEC_END = "094500"
# 收盘确认信号时窗（与尾盘成交窗重叠；盘后仍可确认，成交则等到次日开盘窗）
SIGNAL_CONFIRM_START = "145600"
SIGNAL_CONFIRM_END = "160000"
# 实盘心跳/状态行间隔（秒）；空仓与持仓无新信号沿时均按此节流
LIVE_HEARTBEAT_SEC = 300

# download_history_data 最长回溯（自然日）；回测暖机用
HIST_MAX_LOOKBACK_DAYS = 800
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

# pending 委托超时/孤儿清理（秒）
PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__；状态绝对路径（含 {stock}，多实例不同主图互不覆盖）
#   513530.SH → ...\hlband_513530_SH.json
STATE_FILE = r"D:\tradingStrategy\hlband_{stock}.json"
# 实盘结构化日志根目录；落盘为 LOG_DIR/<stock_tag>/{tag}_events.jsonl 等
# 空字符串关闭落盘（仍保留终端 print）
LOG_DIR = r"D:\tradingStrategy\logs"
# True=回测也写日志（默认关，避免回测刷爆磁盘）
LOG_IN_BACKTEST = False

STRATEGY_NAME = "HlBand"
STRATEGY_VER = "v1.48"
# =======================================================

# 券商委托终态：成交 / 废单死单（勿改除非对接环境不同）
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

# === hlband/state_extra.py ===
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
    try:
        A.hold_bars = int(raw.get("hold_bars", 0) or 0)
    except Exception:
        A.hold_bars = 0
    A._hold_count_day = str(raw.get("hold_count_day", "") or "")
    gu = raw.get("time_force_grace_until")
    try:
        A.time_force_grace_until = None if gu is None else int(gu)
    except Exception:
        A.time_force_grace_until = None
    A.time_force_trend_skip = bool(raw.get("time_force_trend_skip"))
    A._confirmed_eval_day = str(raw.get("confirmed_eval_day", "") or "")
    A._fallback_done_day = str(raw.get("fallback_done_day", "") or "")
    try:
        A._w_bear_streak = int(raw.get("w_bear_streak", 0) or 0)
    except Exception:
        A._w_bear_streak = 0
    A._w_bear_last_day = str(raw.get("w_bear_last_day", "") or "")
    A.round_scaled = bool(raw.get("round_scaled"))
    A._skip_sell_eval_day = str(raw.get("skip_sell_eval_day", "") or "")
    A._last_add_day = str(raw.get("last_add_day", "") or "")
    A._last_add_signal = str(raw.get("last_add_signal", "") or "")
    mk = str(raw.get("ma_kind", "") or "").strip().upper()
    A.ma_kind = mk if mk in ("SMA", "EMA") else ""
    try:
        ss = raw.get("stick_std")
        A.stick_std = None if ss is None else float(ss)
    except Exception:
        A.stick_std = None
    A.stick_day = str(raw.get("stick_day", "") or "")
    A.stick_src = str(raw.get("stick_src", "") or "")


def _state_extra_save(data):
    data["pending_entry"] = getattr(A, "pending_entry", None)
    data["pending_exit"] = getattr(A, "pending_exit", None)
    peak = getattr(A, "hold_peak", None)
    data["hold_peak"] = None if peak is None else float(peak)
    data["hold_bars"] = int(getattr(A, "hold_bars", 0) or 0)
    data["hold_count_day"] = str(getattr(A, "_hold_count_day", "") or "")
    gu = getattr(A, "time_force_grace_until", None)
    data["time_force_grace_until"] = None if gu is None else int(gu)
    data["time_force_trend_skip"] = bool(getattr(A, "time_force_trend_skip", False))
    data["confirmed_eval_day"] = str(getattr(A, "_confirmed_eval_day", "") or "")
    data["fallback_done_day"] = str(getattr(A, "_fallback_done_day", "") or "")
    data["w_bear_streak"] = int(getattr(A, "_w_bear_streak", 0) or 0)
    data["w_bear_last_day"] = str(getattr(A, "_w_bear_last_day", "") or "")
    data["round_scaled"] = bool(getattr(A, "round_scaled", False))
    data["skip_sell_eval_day"] = str(getattr(A, "_skip_sell_eval_day", "") or "")
    data["last_add_day"] = str(getattr(A, "_last_add_day", "") or "")
    data["last_add_signal"] = str(getattr(A, "_last_add_signal", "") or "")
    mk = str(getattr(A, "ma_kind", "") or "").strip().upper()
    data["ma_kind"] = mk if mk in ("SMA", "EMA") else ""
    ss = getattr(A, "stick_std", None)
    try:
        data["stick_std"] = None if ss is None else float(ss)
    except Exception:
        data["stick_std"] = None
    data["stick_day"] = str(getattr(A, "stick_day", "") or "")
    data["stick_src"] = str(getattr(A, "stick_src", "") or "")

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
    if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100:
        A.position = dict(pos)
        A.position["shares"] = int(pos["shares"])
        A.position["price"] = float(pos.get("price", 0) or 0)
        A.position["cost"] = float(pos.get("cost", 0) or 0)
        A.position["opened_at"] = str(pos.get("opened_at", "") or "")
    lots = raw.get("lots")
    cleaned = []
    if isinstance(lots, list):
        for lot in lots:
            if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= 100:
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
            if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= 100:
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
        if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= 100:
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
        if held < 100 and total >= 100:
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
    if total < 100:
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
    if vol < 100:
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
        if remain_fill < 100:
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
    fn = globals().get("_ensure_lots")
    if callable(fn) and bool(globals().get("SCALE_LOTS")):
        fn()
    return True

# === hlband/indicators.py ===
def _sma(closes, n):
    """简单均线；成交量均量固定走此函数。"""
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


def _ema(closes, n):
    c = np.asarray(closes, dtype=float)
    n = int(n)
    if n <= 0 or len(c) < n:
        return None
    out = np.full(len(c), np.nan, dtype=float)
    alpha = 2.0 / (n + 1.0)
    out[n - 1] = float(np.mean(c[:n]))
    for i in range(n, len(c)):
        out[i] = alpha * c[i] + (1.0 - alpha) * out[i - 1]
    return out


def _book_entry_for(stock=None):
    """BOOK_STOCKS 中当前标的的配置 dict；无则 None。"""
    stock = str(stock or getattr(A, "stock", "") or "").strip().upper()
    book = globals().get("BOOK_STOCKS")
    if not stock or not isinstance(book, dict):
        return None
    if stock in book:
        entry = book.get(stock)
    else:
        entry = None
        for k, v in book.items():
            if str(k or "").strip().upper() == stock:
                entry = v
                break
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, (str, bytes)):
        return {"ma_type": entry}
    return None


def _norm_ma_kind(raw, fallback="EMA"):
    kind = str(raw or "").strip().upper()
    if kind in ("SMA", "EMA"):
        return kind
    return str(fallback or "EMA").strip().upper() or "EMA"


def _stick_std(closes, lookback=None, ma_n=None):
    """近 lookback 日收盘相对 SMA(ma_n) 的偏离标准差；样本不足返回 None。"""
    lookback = int(lookback if lookback is not None else globals().get("STICK_LOOKBACK", 120) or 120)
    ma_n = int(ma_n if ma_n is not None else globals().get("STICK_MA_N", 20) or 20)
    if lookback < 20 or ma_n < 2:
        return None
    c = np.asarray(closes, dtype=float)
    if len(c) < ma_n + lookback:
        return None
    ma = _sma(c, ma_n)
    if ma is None:
        return None
    tail_c = c[-lookback:]
    tail_m = ma[-lookback:]
    dev = []
    for i in range(lookback):
        m = float(tail_m[i])
        if m != m or m <= 0:
            continue
        v = float(tail_c[i])
        if v != v:
            continue
        dev.append((v - m) / m)
    if len(dev) < max(20, lookback // 2):
        return None
    return float(np.std(np.asarray(dev, dtype=float), ddof=0))


def _ma_kind_from_stick(stick_std):
    """高粘性(std小)→EMA；低粘性(std大)→SMA。"""
    thr = float(globals().get("STICK_STD_THR", 0.025) or 0.025)
    if stick_std is None:
        return None
    return "EMA" if float(stick_std) <= thr else "SMA"


def _ma_lock_kind():
    """BOOK_STOCKS 强制锁线：ma_lock=True 且 ma_type 合法时返回线型，否则 None。"""
    entry = _book_entry_for()
    if not isinstance(entry, dict):
        return None
    if not bool(entry.get("ma_lock")):
        return None
    raw = entry.get("ma_type")
    kind = _norm_ma_kind(raw, "")
    if kind in ("SMA", "EMA"):
        return kind
    return None


def _ma_kind_static():
    """关自适应时：BOOK_STOCKS.ma_type → MA_TYPE；非法回落 EMA。"""
    entry = _book_entry_for()
    raw = None
    if isinstance(entry, dict):
        raw = entry.get("ma_type")
    if raw is None or str(raw or "").strip() == "":
        raw = globals().get("MA_TYPE", "EMA")
    kind = _norm_ma_kind(raw, "EMA")
    if kind in ("SMA", "EMA"):
        return kind
    if not globals().get("_MA_TYPE_BAD"):
        globals()["_MA_TYPE_BAD"] = True
        print("%s ma_type=%s invalid, fallback EMA" % (STRATEGY_NAME, raw))
    return "EMA"


def _holding_now():
    try:
        if callable(globals().get("_has_position")) and _has_position():
            return True
    except Exception:
        pass
    lots = getattr(A, "lots", None) or []
    if lots:
        return True
    try:
        if callable(globals().get("_bt_held_vol")) and int(_bt_held_vol() or 0) >= 100:
            return True
    except Exception:
        pass
    try:
        vol = float(getattr(A, "volume", 0) or 0)
        if vol > 0:
            return True
    except Exception:
        pass
    return False


def _refresh_ma_kind(closes, day=""):
    """按趋势粘性刷新 A.ma_kind。持仓中保持上次线型；失败回落静态配置。
    返回 (kind, stick_std, source)：source=lock|stick|hold|static|fallback。
    """
    locked = _ma_lock_kind()
    if locked:
        A.ma_kind = locked
        A.stick_std = getattr(A, "stick_std", None)
        A.stick_src = "lock"
        return locked, getattr(A, "stick_std", None), "lock"

    adapt = bool(globals().get("MA_STICK_ADAPT", True))
    if not adapt:
        kind = _ma_kind_static()
        A.ma_kind = kind
        A.stick_std = None
        A.stick_src = "static"
        return kind, None, "static"

    prev = str(getattr(A, "ma_kind", "") or "").strip().upper()
    if prev not in ("SMA", "EMA"):
        prev = ""

    if _holding_now() and prev:
        A.stick_src = "hold"
        return prev, getattr(A, "stick_std", None), "hold"

    stick = _stick_std(closes)
    A.stick_std = stick
    kind = _ma_kind_from_stick(stick)
    if kind is None:
        kind = prev or _ma_kind_static()
        A.ma_kind = kind
        A.stick_src = "fallback"
        return kind, stick, "fallback"

    A.ma_kind = kind
    A.stick_day = day
    A.stick_src = "stick"
    if prev and kind != prev:
        print(
            "%s stick ma_type %s -> %s stick_std=%.4f thr=%.4f"
            % (
                STRATEGY_NAME,
                prev,
                kind,
                float(stick),
                float(globals().get("STICK_STD_THR", 0.025) or 0.025),
            )
        )
    return kind, stick, "stick"


def _ma_kind():
    """当前价格均线类型。优先 A.ma_kind（粘性刷新后），否则静态配置。"""
    cur = str(getattr(A, "ma_kind", "") or "").strip().upper()
    if cur in ("SMA", "EMA"):
        return cur
    locked = _ma_lock_kind()
    if locked:
        A.ma_kind = locked
        return locked
    if bool(globals().get("MA_STICK_ADAPT", True)):
        # 尚未 refresh 时先用静态，等 _handle 用日线收盘刷新
        kind = _ma_kind_static()
        A.ma_kind = kind
        return kind
    kind = _ma_kind_static()
    A.ma_kind = kind
    return kind


def _price_ma(closes, n):
    if _ma_kind() == "SMA":
        return _sma(closes, n)
    return _ema(closes, n)


def _calc_macd(closes, fast=None, slow=None, signal=None):
    """返回 (dif, dea, hist) 或 None。hist = dif - dea。"""
    fast = int(fast if fast is not None else MACD_FAST)
    slow = int(slow if slow is not None else MACD_SLOW)
    signal = int(signal if signal is not None else MACD_SIGNAL)
    c = np.asarray(closes, dtype=float)
    if len(c) < slow + signal:
        return None
    ema_f = _ema(c, fast)
    ema_s = _ema(c, slow)
    if ema_f is None or ema_s is None:
        return None
    dif = ema_f - ema_s
    start = slow - 1
    dif_valid = dif[start:]
    if len(dif_valid) < signal:
        return None
    dea_tail = _ema(dif_valid, signal)
    if dea_tail is None:
        return None
    dea = np.full(len(c), np.nan, dtype=float)
    dea[start:] = dea_tail
    hist = dif - dea
    return dif, dea, hist


def _last_valid(arr, i=-1):
    if arr is None:
        return None
    v = arr[i]
    if v != v:
        return None
    return float(v)


def _near_ma(price, ma, tol=None):
    tol = float(tol if tol is not None else MA_TOUCH_TOL)
    if price is None or ma is None or ma <= 0:
        return False
    return abs(float(price) - float(ma)) / float(ma) <= tol


def _plat_window(highs, lows, lookback, end_i=None):
    """不含 end_i 的回看窗口平台高低点；(plat_high, plat_low) 或 None。"""
    if highs is None or lows is None:
        return None
    n = min(len(highs), len(lows))
    lookback = int(lookback)
    if lookback < 2 or n < lookback + 1:
        return None
    i = n - 1 if end_i is None else int(end_i)
    if i < lookback:
        return None
    win_h = [float(x) for x in highs[i - lookback:i]]
    win_l = [float(x) for x in lows[i - lookback:i]]
    if not win_h or not win_l:
        return None
    plat_high = max(win_h)
    plat_low = min(win_l)
    if plat_high <= 0 or plat_low <= 0:
        return None
    return plat_high, plat_low

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

# === hlband/market.py ===
def _norm_bar_day(x):
    """行情时间戳/索引 → yyyymmdd。"""
    if x is None:
        return ""
    try:
        if hasattr(x, "strftime"):
            return x.strftime("%Y%m%d")
    except Exception:
        pass
    s = str(x).strip()
    digits = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    if len(digits) >= 8:
        return "".join(digits[:8])
    return ""


def _days_from_ex(md, stock):
    """从 get_market_data_ex 结果解析交易日列表（与 close 序列对齐时优先 index/time）。"""
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
    if hasattr(df, "index"):
        try:
            raw = list(df.index)
        except Exception:
            raw = None
    if (not raw) and hasattr(df, "columns"):
        for col in ("time", "date", "datetime", "stime"):
            try:
                cols = getattr(df, "columns", [])
                if col in cols:
                    raw = list(df[col])
                    break
            except Exception:
                continue
    if not raw:
        return None
    out = []
    for x in raw:
        d = _norm_bar_day(x)
        if d:
            out.append(d)
    return out if out else None


def _get_daily_bar_days(C, stock, count=8):
    """最近若干根日线交易日（yyyymmdd），失败返回 None。"""
    end = _bar_end_str(C)
    if len(end) >= 8:
        end = end[:8]
    fields = ["close"]
    md = None
    try:
        md = C.get_market_data_ex(
            fields=fields,
            stock_code=[stock],
            period=getattr(A, "period", "1d"),
            end_time=end,
            count=int(count),
            dividend_type="front_ratio",
            fill_data=True,
            subscribe=False,
        )
    except TypeError:
        try:
            md = C.get_market_data_ex(
                fields,
                [stock],
                period=getattr(A, "period", "1d"),
                start_time="",
                end_time=end,
                count=int(count),
                dividend_type="front_ratio",
            )
        except Exception:
            md = None
    except Exception:
        md = None
    days = _days_from_ex(md, stock) if md is not None else None
    return days


def _get_ohlcv_period(C, stock, period, count, need, diag_key):
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


def _get_ohlcv_1d(C, stock):
    plat_n = int(globals().get("SCALE_PLAT_LOOKBACK") or 20)
    need = max(
        int(D_MA_SLOW),
        int(VOL_PULLBACK_N),
        int(VOL_DRY_N),
        plat_n + 2,
    ) + 10
    return _get_ohlcv_period(
        C, stock, getattr(A, "period", "1d"), int(OHLC_COUNT), need, "d1"
    )


def _get_ohlcv_1w(C, stock):
    need = max(int(W_MA_SLOW), int(MACD_SLOW) + int(MACD_SIGNAL)) + 5
    return _get_ohlcv_period(
        C, stock, "1w", int(WEEKLY_OHLC_COUNT), need, "w1"
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
# add=True: 已有仓上加仓；SCALE_LOTS 时记独立笔，否则均价合并（默认仍一票一仓）
# 实盘尾盘成交窗：限价 prType=11，买挂卖一、卖挂买一；不开涨跌停、不按收盘集合竞价价吃单。
# 开盘窗仍用 14/-1 市价。回测路径不变。
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
    if filled_vol < 100:
        return
    partial_lots = False
    if bool(globals().get("SCALE_LOTS")) and lot_ids:
        fn = globals().get("_exit_is_partial")
        if callable(fn):
            partial_lots = bool(fn(lot_ids))
    if (not partial_lots) and (
        filled_vol >= max(100, int(want * 0.95)) or filled_vol >= want
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
    if remain < 100 or not _has_position():
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


def _in_live_close_exec(now):
    """是否处于实盘尾盘成交窗（PENDING_EXEC_*）。"""
    if getattr(A, "is_backtest", False):
        return False
    now_s = (now or datetime.datetime.now()).strftime("%H%M%S")
    fn = globals().get("_in_close_exec_window")
    if callable(fn):
        try:
            return bool(fn(now_s))
        except Exception:
            pass
    start = str(globals().get("PENDING_EXEC_START") or "")
    end = str(globals().get("PENDING_EXEC_END") or "")
    if start and end:
        return start <= now_s < end
    return False


def _round_order_px(stock, px):
    px = float(px or 0)
    if px <= 0:
        return 0.0
    code = str(stock or "").split(".")[0]
    if len(code) == 6 and code[:1] in ("1", "5"):
        return round(px + 1e-12, 3)
    return round(px + 1e-12, 2)


def _tick_field(obj, names):
    if obj is None:
        return 0.0
    for name in names:
        if isinstance(obj, dict):
            raw = obj.get(name)
        else:
            raw = getattr(obj, name, None)
        if raw is None or raw == "":
            continue
        try:
            v = float(raw)
        except Exception:
            continue
        if v > 0:
            return v
    return 0.0


def _seq_first_px(val):
    if val is None or val == "":
        return 0.0
    if isinstance(val, (list, tuple)):
        if not val:
            return 0.0
        try:
            return float(val[0] or 0)
        except Exception:
            return 0.0
    try:
        return float(val)
    except Exception:
        return 0.0


def _get_stock_tick(C, stock):
    ticks = None
    if C is not None:
        for meth in ("get_full_tick", "get_tick"):
            fn = getattr(C, meth, None)
            if not callable(fn):
                continue
            try:
                ticks = fn([stock])
            except Exception:
                ticks = None
            if ticks:
                break
    if ticks is None:
        gfn = globals().get("get_full_tick")
        if callable(gfn):
            try:
                ticks = gfn([stock])
            except Exception:
                ticks = None
    if isinstance(ticks, dict):
        t = ticks.get(stock)
        if t is None:
            t = ticks.get(str(stock).split(".")[0])
        return t
    return ticks


def _level1_px(t, array_names, scalar_names):
    if t is None:
        return 0.0
    for name in array_names:
        if isinstance(t, dict):
            raw = t.get(name)
        else:
            raw = getattr(t, name, None)
        px = _seq_first_px(raw)
        if px > 0:
            return px
    return _tick_field(t, scalar_names)


def _live_opponent_px(C, side, fallback):
    """买=卖一，卖=买一；取不到则回落 last。"""
    t = _get_stock_tick(C, getattr(A, "stock", ""))
    if str(side) == "buy":
        raw = _level1_px(
            t,
            ("askPrice", "askPrices", "ask", "asks"),
            ("askPrice1", "ask1", "AskPrice1", "askPr1", "m_dAskPrice"),
        )
        kind = "ask1"
    else:
        raw = _level1_px(
            t,
            ("bidPrice", "bidPrices", "bid", "bids"),
            ("bidPrice1", "bid1", "BidPrice1", "bidPr1", "m_dBidPrice"),
        )
        kind = "bid1"
    if raw <= 0:
        raw = float(fallback or 0)
        kind = "last"
    px = _round_order_px(getattr(A, "stock", ""), raw)
    return px, kind


def _passorder_live(C, side, vol, last_px, msg, now):
    """实盘报单。尾盘窗限价挂卖一/买一；其余仍市价。"""
    vol = int(vol)
    last_px = float(last_px or 0)
    if _in_live_close_exec(now):
        px, kind = _live_opponent_px(C, side, last_px)
        if px > 0:
            code = A.buy_code if str(side) == "buy" else A.sell_code
            print(
                _strategy_tag(),
                "passorder quote-limit",
                side,
                kind,
                "pr=11",
                "px=",
                px,
                "last=",
                last_px,
                "vol=",
                vol,
            )
            _event_log(
                "passorder_quote_limit",
                side=side,
                kind=kind,
                pr_type=11,
                px=px,
                last=last_px,
                vol=vol,
            )
            passorder(code, 1101, A.acct, A.stock, 11, px, vol, _strategy_tag(), 2, msg, C)
            return px
    code = A.buy_code if str(side) == "buy" else A.sell_code
    passorder(code, 1101, A.acct, A.stock, 14, -1, vol, _strategy_tag(), 1, msg, C)
    return last_px


def _order_buy(C, price, now, budget=None, add=False, **extra_pos):
    """提交买入. DRY 即时; 回测 passorder+即时; 实盘 pending 至成交.
    add=True 允许在已有仓上加仓；SCALE_LOTS 时每笔独立，否则均价合并。默认仍一票一仓。"""
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
    freeze_px = float(price or 0)
    if (not getattr(A, "is_backtest", False)) and (not DRY_RUN) and _in_live_close_exec(now):
        prot, _kind = _live_opponent_px(C, "buy", price)
        if prot > freeze_px:
            freeze_px = prot
    if cash is not None and freeze_px > 0 and cash < freeze_px * vol:
        vol = _lot(freeze_px, cash)
        if vol < 100:
            print(_strategy_tag(), "buy skip cash", cash)
            _event_log("buy_skip", reason="cash", cash=cash, price=price, freeze_px=freeze_px)
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
        _passorder_live(C, "buy", vol, price, msg, now)
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
    if not _has_position() and not (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
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
        _apply_sell_fill(now, reason, price, vol, mark_half=mark_half, lot_ids=lot_ids)
        return True
    try:
        _passorder_live(C, "sell", vol, price, msg, now)
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

# === hlband/budget.py ===
# 覆盖 common:single/orders._buy_budget。实盘共享账本均分；回测仍用 TRADE_BUDGET。
# 勿改 scripts/qmt_common/single/orders.py。
def _dynamic_budget_on():
    if getattr(A, "is_backtest", False):
        return False
    return bool(globals().get("DYNAMIC_BUDGET", True))


def _equal_split_on():
    return _dynamic_budget_on() and bool(globals().get("EQUAL_SPLIT", True))


def _norm_code(code):
    return str(code or "").strip().upper()


def _book_entry_normalize(val):
    """把 BOOK_STOCKS 的 value 规范成 dict。str → {ma_type: str}；其它非 dict → {}。"""
    if isinstance(val, dict):
        return dict(val)
    if isinstance(val, (str, bytes)):
        s = str(val or "").strip()
        if s:
            return {"ma_type": s}
        return {}
    return {}


def _book_stock_map():
    """解析 BOOK_STOCKS → {norm_code: cfg_dict}。兼容 dict / 旧纯字符串序列。"""
    out = {}
    raw = globals().get("BOOK_STOCKS")
    if raw is None:
        return out
    if isinstance(raw, dict):
        for k, v in raw.items():
            code = _norm_code(k)
            if not code:
                continue
            out[code] = _book_entry_normalize(v)
        return out
    try:
        seq = list(raw)
    except Exception:
        return out
    for x in seq:
        if isinstance(x, (list, tuple)) and len(x) >= 1:
            code = _norm_code(x[0])
            cfg = _book_entry_normalize(x[1] if len(x) >= 2 else {})
        else:
            code = _norm_code(x)
            cfg = {}
        if code:
            out[code] = cfg
    return out


def _book_stock_set():
    return set(_book_stock_map().keys())


def _book_cfg(stock):
    """当前标的在 BOOK_STOCKS 中的子配置；不在池则 {}。"""
    ncode = _norm_code(stock)
    if not ncode:
        return {}
    return dict(_book_stock_map().get(ncode) or {})


def _code_in_book(code):
    ncode = _norm_code(code)
    if not ncode:
        return False
    mine = _norm_code(getattr(A, "stock", ""))
    if mine and ncode == mine:
        return True
    s = _book_stock_set()
    if not s:
        return True
    return ncode in s


def _cfg_book_n():
    n_list = len(_book_stock_set())
    try:
        n_cfg = int(globals().get("BOOK_N") or 0)
    except Exception:
        n_cfg = 0
    if n_list > 0:
        if n_cfg and n_cfg != n_list:
            _diag_once("book_n_mismatch", "BOOK_N=%s BOOK_STOCKS=%s" % (n_cfg, n_list))
        return n_list
    return max(1, n_cfg or 4)


def _cfg_min_lot():
    try:
        v = float(globals().get("MIN_LOT") or 0)
    except Exception:
        v = 0.0
    return max(0.0, v)


def _cfg_max_name_frac():
    try:
        v = float(globals().get("MAX_NAME_FRAC") or 0.50)
    except Exception:
        v = 0.50
    if v <= 0:
        v = 0.50
    if v > 1.0:
        v = 1.0
    return v


def _cfg_cash_ratio():
    try:
        v = float(globals().get("CASH_RATIO") or 0.95)
    except Exception:
        v = 0.95
    if v <= 0:
        return 0.95
    if v > 1.0:
        return 1.0
    return v


def _buy_budget_fixed(cash):
    """回测 / 关闭 DYNAMIC_BUDGET：沿用单笔 TRADE_BUDGET。"""
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


def _pos_row_mv(p, vol):
    mv = 0.0
    raw_mv = getattr(p, "m_dMarketValue", None)
    if raw_mv is not None:
        try:
            mv = float(raw_mv)
        except Exception:
            mv = 0.0
    if mv <= 0:
        last = getattr(p, "m_dLastPrice", None)
        if last is None:
            last = getattr(p, "m_dOpenPrice", None)
        try:
            if last is not None and float(last) > 0:
                mv = float(last) * float(vol)
        except Exception:
            mv = 0.0
    return float(mv or 0)


def _query_broker_book():
    """白名单持股只数与市值；同时给出其它股票市值。失败则回落本地账本。"""
    stock = _norm_code(getattr(A, "stock", ""))
    out = {
        "ok": False,
        "k": 0,
        "k_other": 0,
        "book_mv": 0.0,
        "other_mv": 0.0,
        "name_mv": 0.0,
        "name_vol": 0,
        "held": {},
        "src": "",
    }
    if getattr(A, "is_backtest", False):
        return out
    try:
        positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    except Exception as e:
        print(_strategy_tag(), "book query fail, try local", e)
        _event_log("book_query_fail", error=str(e))
        return _query_local_book(stock)
    if positions is None:
        return _query_local_book(stock)
    k = 0
    k_other = 0
    book_mv = 0.0
    other_mv = 0.0
    name_mv = 0.0
    name_vol = 0
    held = {}
    for p in positions:
        try:
            vol = int(getattr(p, "m_nVolume", 0) or 0)
        except Exception:
            vol = 0
        if vol < 100:
            continue
        code = _norm_code(_pos_code(p))
        mv = _pos_row_mv(p, vol)
        if _code_in_book(code):
            k += 1
            book_mv += mv
            held[code] = mv
            if code == _norm_code(stock):
                name_mv = mv
                name_vol = vol
        else:
            k_other += 1
            other_mv += mv
    out["ok"] = True
    out["k"] = int(k)
    out["k_other"] = int(k_other)
    out["book_mv"] = float(book_mv)
    out["other_mv"] = float(other_mv)
    out["name_mv"] = float(name_mv)
    out["name_vol"] = int(name_vol)
    out["held"] = held
    out["src"] = "broker"
    _broker_cache_save(held, k, book_mv, other_mv, k_other)
    return out


def _broker_cache_save(held, k, book_mv, other_mv=0.0, k_other=0):
    data = _book_load()
    if not isinstance(data, dict):
        data = {}
    data["broker"] = {
        "ts": datetime.datetime.now().strftime("%Y%m%d %H%M%S"),
        "held": dict(held or {}),
        "k": int(k or 0),
        "k_other": int(k_other or 0),
        "book_mv": float(book_mv or 0),
        "other_mv": float(other_mv or 0),
    }
    _book_save(data)


def _held_from_state_raw(raw):
    """一份 STATE JSON -> (stock, mv, vol)。"""
    if not isinstance(raw, dict):
        return "", 0.0, 0
    stock = str(raw.get("stock") or "")
    stock = _norm_code(stock)
    pos = raw.get("position")
    vol = 0
    px = 0.0
    if isinstance(pos, dict):
        try:
            vol = int(pos.get("shares") or 0)
        except Exception:
            vol = 0
        try:
            px = float(pos.get("price") or 0)
        except Exception:
            px = 0.0
    if vol < 100:
        vol = 0
        lots = raw.get("lots")
        if isinstance(lots, list):
            for lot in lots:
                if not isinstance(lot, dict):
                    continue
                try:
                    sh = int(lot.get("shares") or 0)
                except Exception:
                    sh = 0
                if sh < 100:
                    continue
                vol += sh
                try:
                    px = float(lot.get("price") or px or 0)
                except Exception:
                    pass
    if vol < 100 or px <= 0:
        return stock, 0.0, 0
    return stock, float(vol) * float(px), int(vol)


def _state_glob_held():
    """读各图 STATE_FILE，得到 {stock: mv}。"""
    held = {}
    base = str(globals().get("STATE_FILE") or "").strip()
    if not base or "{stock}" not in base:
        return held
    folder = os.path.dirname(base)
    fname = os.path.basename(base)
    mid = fname.find("{stock}")
    if mid < 0:
        return held
    pre = fname[:mid]
    post = fname[mid + len("{stock}"):]
    book_name = os.path.basename(_book_path() or "")
    try:
        names = os.listdir(folder) if folder else []
    except Exception:
        return held
    for fn in names:
        if book_name and fn == book_name:
            continue
        if not (fn.startswith(pre) and fn.endswith(post)):
            continue
        path = os.path.join(folder, fn) if folder else fn
        try:
            raw = json.loads(open(path, "r").read())
        except Exception:
            continue
        stock, mv, _vol = _held_from_state_raw(raw)
        if stock and mv > 1e-6:
            held[stock] = mv
    return held


def _query_local_book(stock):
    """持仓查询失败：上次券商快照 + 各图 STATE + 本图内存仓。"""
    out = {
        "ok": False,
        "k": 0,
        "k_other": 0,
        "book_mv": 0.0,
        "other_mv": 0.0,
        "name_mv": 0.0,
        "name_vol": 0,
        "held": {},
        "src": "local",
    }
    data = _book_load()
    cache = data.get("broker") if isinstance(data.get("broker"), dict) else None
    held = {}
    if cache and isinstance(cache.get("held"), dict):
        for code, mv in cache.get("held").items():
            try:
                v = float(mv or 0)
            except Exception:
                v = 0.0
            if v > 1e-6 and _code_in_book(code):
                held[_norm_code(code)] = v
    other_mv = 0.0
    k_other = 0
    if cache:
        try:
            other_mv = float(cache.get("other_mv") or 0)
        except Exception:
            other_mv = 0.0
        try:
            k_other = int(cache.get("k_other") or 0)
        except Exception:
            k_other = 0
    for code, mv in _state_glob_held().items():
        if _code_in_book(code):
            held[_norm_code(code)] = mv
    name_vol = 0
    if _has_position():
        sh = _pos_shares()
        px = _pos_cost_price()
        if sh >= 100 and px > 0:
            held[_norm_code(stock)] = float(sh) * float(px)
            name_vol = int(sh)
    if (not held) and (cache is None):
        print(_strategy_tag(), "book local empty, skip buy")
        _event_log("book_local_empty")
        return out
    book_mv = 0.0
    k = 0
    for mv in held.values():
        book_mv += float(mv or 0)
        k += 1
    name_mv = float(held.get(_norm_code(stock)) or 0)
    out["ok"] = True
    out["k"] = int(k)
    out["k_other"] = int(k_other)
    out["book_mv"] = float(book_mv)
    out["other_mv"] = float(other_mv)
    out["name_mv"] = name_mv
    out["name_vol"] = int(name_vol)
    out["held"] = held
    print(
        "%s book fallback local k=%s k_other=%s book_mv=%.0f other_mv=%.0f name_mv=%.0f cache=%s"
        % (STRATEGY_NAME, k, k_other, book_mv, other_mv, name_mv, bool(cache))
    )
    _event_log(
        "book_fallback_local",
        k=k,
        k_other=k_other,
        book_mv=book_mv,
        other_mv=other_mv,
        name_mv=name_mv,
        names=list(held.keys()),
        has_cache=bool(cache),
    )
    return out


def _account_equity(cash, book_mv, other_mv=0.0):
    """E_s = 总资产 - 其它股票市值；失败则现金 + 池内市值。"""
    if getattr(A, "is_backtest", False):
        return None
    try:
        accs = get_trade_detail_data(A.acct, A.acct_type, "account")
        if accs:
            raw = getattr(accs[0], "m_dTotalAsset", None)
            if raw is not None and float(raw) > 0:
                es = float(raw) - float(other_mv or 0)
                if es > 0:
                    return es
    except Exception as e:
        print(_strategy_tag(), "equity query fail", e)
        _event_log("equity_query_fail", error=str(e))
    try:
        c = float(cash or 0)
    except Exception:
        c = 0.0
    return c + float(book_mv or 0)


def _empty_fill_snap():
    return {
        "E": 0.0,
        "N": _cfg_book_n(),
        "k": 0,
        "k_after": 0,
        "k_other": 0,
        "empty": 0,
        "reserve": 0.0,
        "lot": 0.0,
        "book_mv": 0.0,
        "other_mv": 0.0,
        "name_mv": 0.0,
        "cap": 0.0,
        "acct_room": 0.0,
        "name_room": 0.0,
        "opening": False,
        "cash": 0.0,
        "why": "",
        "n_buy": 0,
        "split": 0.0,
        "src": "",
    }


def _name_limit(equity, cap, n, min_lot, name_frac):
    lim = min(name_frac * float(equity), cap - (n - 1) * min_lot)
    if lim < 0:
        return 0.0
    return float(lim)


def _water_fill(rooms, pool):
    """rooms: {stock: max_yuan}. 均分 pool，触顶后把剩余再分给未触顶的。"""
    lots = {}
    for s in rooms:
        lots[s] = 0.0
    try:
        remaining = float(pool)
    except Exception:
        remaining = 0.0
    if remaining <= 0:
        return lots
    active = [s for s in rooms if float(rooms.get(s) or 0) > 1e-6]
    guard = 0
    while active and remaining > 1e-6 and guard < 16:
        guard += 1
        share = remaining / float(len(active))
        nxt = []
        progressed = False
        for s in active:
            room = float(rooms.get(s) or 0) - lots[s]
            if room <= 1e-6:
                continue
            if share + 1e-9 >= room:
                lots[s] += room
                remaining -= room
                progressed = True
            else:
                lots[s] += share
                remaining -= share
                nxt.append(s)
                progressed = True
        if not nxt:
            break
        if len(nxt) == len(active) and share > 0:
            break
        if not progressed:
            break
        active = nxt
    return lots


def _book_path():
    return str(globals().get("BOOK_FILE") or "").strip()


def _book_window_id(now_s):
    s = str(now_s or "")
    open_s = _cfg_hhmmss("OPEN_EXEC_START", "093000")
    open_e = _cfg_hhmmss("OPEN_EXEC_END", "094500")
    conf_s = _cfg_hhmmss("SIGNAL_CONFIRM_START", "145600")
    close_e = _cfg_hhmmss("PENDING_EXEC_END", "145700")
    if open_s <= s < open_e:
        return "open"
    if conf_s <= s <= close_e:
        return "close"
    return ""


def _book_freeze_s(window):
    if window == "open":
        return str(globals().get("BOOK_FREEZE_OPEN") or "093200")
    return str(globals().get("BOOK_FREEZE_CLOSE") or "145630")


def _book_load():
    path = _book_path()
    if not path:
        return {}
    try:
        raw = open(path, "r").read()
    except Exception:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _book_save(data):
    path = _book_path()
    if not path:
        return False
    text = json.dumps(data, ensure_ascii=False)
    tmp = path + ".tmp." + str(os.getpid())
    try:
        fh = open(tmp, "w")
        fh.write(text)
        fh.close()
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(_strategy_tag(), "book save fail", e)
        _event_log("book_save_fail", error=str(e))
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


def _book_checkin(day, window, now_s, buy=False, add=False, sell=False, sell_all=False):
    """本图写入共享账本一条打卡。"""
    if not _equal_split_on():
        return
    if not window:
        return
    stock = _norm_code(getattr(A, "stock", ""))
    if not stock:
        return
    data = _book_load()
    broker_keep = data.get("broker") if isinstance(data.get("broker"), dict) else None
    if str(data.get("day") or "") != str(day) or str(data.get("window") or "") != str(window):
        data = {"day": str(day), "window": str(window), "names": {}}
        if broker_keep:
            data["broker"] = broker_keep
    names = data.get("names")
    if not isinstance(names, dict):
        names = {}
        data["names"] = names
    names[stock] = {
        "checkin": True,
        "buy": bool(buy),
        "add": bool(add),
        "sell": bool(sell),
        "sell_all": bool(sell_all),
        "hhmmss": str(now_s or ""),
    }
    _book_save(data)


def _sync_signal_book(day, now_s, buy_sig, scale_sig, holding, sell_ok, force_empty):
    if not _equal_split_on():
        return
    window = _book_window_id(now_s)
    if not window:
        return
    pe = getattr(A, "pending_entry", None)
    px = getattr(A, "pending_exit", None)
    sell = bool(isinstance(px, dict) or sell_ok or force_empty)
    buy = bool(isinstance(pe, dict)) or bool(buy_sig) or (bool(scale_sig) and bool(holding))
    add = False
    if isinstance(pe, dict) and pe.get("add"):
        add = True
    elif scale_sig and holding:
        add = True
    if sell:
        buy = False
        add = False
    sell_all = False
    if isinstance(px, dict):
        reasons = px.get("reasons") or []
        if (not px.get("lot_ids")) or ("weekly_bear" in reasons):
            sell_all = True
    _book_checkin(
        day,
        window,
        now_s,
        buy=buy,
        add=add,
        sell=sell,
        sell_all=sell_all,
    )


def _book_is_frozen(now_s, data=None):
    if not _equal_split_on():
        return True
    window = _book_window_id(now_s)
    if not window:
        return False
    if data is None:
        data = _book_load()
    if str(data.get("window") or "") != window:
        data = {}
    names = data.get("names") if isinstance(data.get("names"), dict) else {}
    n_ok = 0
    for stock, rec in names.items():
        if not _code_in_book(stock):
            continue
        if isinstance(rec, dict) and rec.get("checkin"):
            n_ok += 1
    if n_ok >= _cfg_book_n():
        return True
    return str(now_s or "") >= _book_freeze_s(window)


def _book_buy_intents(data, now_s):
    """冻结后纳入均分的买单。超时打卡不计入。"""
    window = str(data.get("window") or "")
    names = data.get("names") if isinstance(data.get("names"), dict) else {}
    n_ok = 0
    for stock, rec in names.items():
        if not _code_in_book(stock):
            continue
        if isinstance(rec, dict) and rec.get("checkin"):
            n_ok += 1
    frozen_by_n = n_ok >= _cfg_book_n()
    freeze_s = _book_freeze_s(window)
    frozen_by_time = str(now_s or "") >= freeze_s
    cutoff = "999999" if frozen_by_n else freeze_s
    intents = []
    sells = []
    for stock, rec in names.items():
        if not isinstance(rec, dict) or (not rec.get("checkin")):
            continue
        hh = str(rec.get("hhmmss") or "")
        if hh > cutoff:
            continue
        if rec.get("sell"):
            sells.append((str(stock), bool(rec.get("sell_all"))))
        if rec.get("buy") and (not rec.get("sell")):
            intents.append({"stock": str(stock), "add": bool(rec.get("add"))})
    return intents, sells


def _allocate_equal(cash, now_s):
    """返回 (lots_by_stock, snap_base)。无券商且无本地账本时 why=book_fail。"""
    snap = _empty_fill_snap()
    broker = _query_broker_book()
    if not broker.get("ok"):
        snap["why"] = "book_fail"
        return {}, snap
    held = {}
    for code, mv in (broker.get("held") or {}).items():
        try:
            v = float(mv or 0)
        except Exception:
            v = 0.0
        if v > 1e-6:
            held[_norm_code(code)] = v
    data = _book_load()
    intents, sells = _book_buy_intents(data, now_s)
    intents = [{"stock": _norm_code(it.get("stock")), "add": bool(it.get("add"))} for it in intents if _code_in_book(it.get("stock"))]
    sells = [(_norm_code(st), sa) for st, sa in sells if _code_in_book(st)]
    cash_v = 0.0
    try:
        cash_v = float(cash) if cash is not None else 0.0
    except Exception:
        cash_v = 0.0
    for stock, sell_all in sells:
        if not sell_all:
            continue
        mv = float(held.pop(stock, 0) or 0)
        cash_v += mv
    book_mv = 0.0
    for mv in held.values():
        book_mv += float(mv or 0)
    k = len([1 for mv in held.values() if float(mv or 0) > 1e-6])
    n_new = 0
    for it in intents:
        st = it.get("stock")
        if float(held.get(st) or 0) <= 1e-6:
            n_new += 1
    n = _cfg_book_n()
    min_lot = _cfg_min_lot()
    k_after = k + n_new
    empty = max(0, n - k_after)
    reserve = empty * min_lot
    other_mv = float(broker.get("other_mv") or 0)
    equity = _account_equity(cash, float(broker.get("book_mv") or 0), other_mv)
    if sells:
        equity = cash_v + book_mv
    stock = _norm_code(getattr(A, "stock", ""))
    name_mv = float(held.get(stock) or 0)
    snap.update(
        {
            "N": n,
            "k": k,
            "k_after": k_after,
            "k_other": int(broker.get("k_other") or 0),
            "empty": empty,
            "reserve": reserve,
            "book_mv": book_mv,
            "other_mv": other_mv,
            "name_mv": name_mv,
            "cash": cash_v,
            "n_buy": len(intents),
            "opening": name_mv <= 1e-6,
        }
    )
    if equity is None or equity <= 0:
        snap["why"] = "no_E"
        return {}, snap
    ratio = _cfg_cash_ratio()
    name_frac = _cfg_max_name_frac()
    cap = ratio * float(equity)
    pool = cap - book_mv - reserve
    pool = min(pool, cash_v)
    if pool < 0:
        pool = 0.0
    name_lim = _name_limit(equity, cap, n, min_lot, name_frac)
    rooms = {}
    for it in intents:
        st = it.get("stock")
        mv = float(held.get(st) or 0)
        room = name_lim - mv
        if room < 0:
            room = 0.0
        rooms[st] = room
    lots = _water_fill(rooms, pool)
    my_lot = float(lots.get(stock) or 0)
    my_room = float(rooms.get(stock) or 0)
    n_buy = len(intents) if intents else 1
    snap.update(
        {
            "E": float(equity),
            "cap": cap,
            "acct_room": pool,
            "name_room": my_room,
            "lot": my_lot,
            "split": (pool / float(n_buy)) if n_buy else 0.0,
            "why": "split",
            "src": str(broker.get("src") or "broker"),
        }
    )
    return lots, snap


def _fill_budget_snapshot(cash, opening=None):
    snap = _empty_fill_snap()
    if not _dynamic_budget_on():
        snap["lot"] = float(_buy_budget_fixed(cash) or 0)
        snap["why"] = "fixed"
        return snap
    now = datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    if _equal_split_on():
        if not _book_is_frozen(now_s):
            snap["why"] = "wait"
            return snap
        _lots, snap = _allocate_equal(cash, now_s)
        if opening is not None:
            snap["opening"] = bool(opening)
        return snap
    book = _query_broker_book()
    if not book.get("ok"):
        snap["why"] = "book_fail"
        return snap
    book_mv = float(book.get("book_mv") or 0)
    other_mv = float(book.get("other_mv") or 0)
    name_mv = float(book.get("name_mv") or 0)
    name_vol = int(book.get("name_vol") or 0)
    k = int(book.get("k") or 0)
    name_on_book = name_vol >= 100
    if opening is None:
        opening = (not name_on_book) and (not _has_position())
    opening = bool(opening)
    if opening and (not name_on_book):
        k_after = k + 1
    else:
        k_after = k
    n = _cfg_book_n()
    min_lot = _cfg_min_lot()
    empty = max(0, n - k_after)
    reserve = empty * min_lot
    equity = _account_equity(cash, book_mv, other_mv)
    try:
        cash_v = float(cash) if cash is not None else 0.0
    except Exception:
        cash_v = 0.0
    snap.update(
        {
            "N": n,
            "k": k,
            "k_after": k_after,
            "k_other": int(book.get("k_other") or 0),
            "empty": empty,
            "reserve": reserve,
            "book_mv": book_mv,
            "other_mv": other_mv,
            "name_mv": name_mv,
            "opening": opening,
            "cash": cash_v,
        }
    )
    if equity is None or equity <= 0:
        snap["why"] = "no_E"
        return snap
    ratio = _cfg_cash_ratio()
    name_frac = _cfg_max_name_frac()
    cap = ratio * float(equity)
    name_lim = _name_limit(equity, cap, n, min_lot, name_frac)
    name_room = name_lim - name_mv
    acct_room = cap - book_mv - reserve
    lot = min(acct_room, name_room, cash_v)
    if lot < 0:
        lot = 0.0
    snap.update(
        {
            "E": float(equity),
            "cap": cap,
            "acct_room": acct_room,
            "name_room": name_room,
            "lot": lot,
            "why": "fill",
            "src": str(book.get("src") or "broker"),
        }
    )
    return snap


def _log_fill_budget(snap, tag=""):
    snap = snap or {}
    print(
        "%s fill%s E=%.0f N=%s k=%s k_other=%s reserve=%.0f lot=%.0f book_mv=%.0f other_mv=%.0f name_mv=%.0f "
        "n_buy=%s split=%.0f why=%s src=%s"
        % (
            STRATEGY_NAME,
            (" " + str(tag)) if tag else "",
            float(snap.get("E") or 0),
            snap.get("N"),
            snap.get("k"),
            snap.get("k_other"),
            float(snap.get("reserve") or 0),
            float(snap.get("lot") or 0),
            float(snap.get("book_mv") or 0),
            float(snap.get("other_mv") or 0),
            float(snap.get("name_mv") or 0),
            snap.get("n_buy"),
            float(snap.get("split") or 0),
            snap.get("why") or "-",
            snap.get("src") or "-",
        )
    )
    _event_log(
        "fill_budget",
        tag=str(tag or ""),
        E=snap.get("E"),
        N=snap.get("N"),
        k=snap.get("k"),
        k_after=snap.get("k_after"),
        k_other=snap.get("k_other"),
        reserve=snap.get("reserve"),
        lot=snap.get("lot"),
        book_mv=snap.get("book_mv"),
        other_mv=snap.get("other_mv"),
        name_mv=snap.get("name_mv"),
        empty=snap.get("empty"),
        opening=snap.get("opening"),
        why=snap.get("why"),
        n_buy=snap.get("n_buy"),
        src=snap.get("src"),
    )


def _fill_room_ok(price=None, opening=None):
    """额度是否够买至少 100 股。why=buy_cap / scale_cap / wait / book_fail。"""
    cash = _available_cash()
    snap = _fill_budget_snapshot(cash, opening=opening)
    why0 = str(snap.get("why") or "")
    if why0 in ("wait", "book_fail", "no_E"):
        return False, why0, snap
    lot = float(snap.get("lot") or 0)
    is_open = bool(opening) if opening is not None else bool(snap.get("opening"))
    why = "buy_cap" if is_open else "scale_cap"
    if lot <= 0:
        return False, why, snap
    if price is not None:
        try:
            px = float(price)
        except Exception:
            px = 0.0
        if px > 0 and _lot(px, lot) < 100:
            return False, why, snap
    return True, "", snap


def _buy_budget(cash):
    """覆盖 common：实盘均分/填满；回测回落 TRADE_BUDGET。"""
    if not _dynamic_budget_on():
        return _buy_budget_fixed(cash)
    snap = _fill_budget_snapshot(cash)
    if str(snap.get("why") or "") in ("wait", "book_fail", "no_E"):
        return 0.0
    lot = float(snap.get("lot") or 0)
    return lot if lot > 0 else 0.0


def _heartbeat_extra():
    parts = []
    lots = getattr(A, "lots", None) or []
    if lots:
        bits = []
        for lot in lots:
            try:
                bits.append(
                    "L%s:%s@%.4f"
                    % (lot.get("id"), lot.get("shares"), float(lot.get("price") or 0))
                )
            except Exception:
                pass
        if bits:
            parts.append("lots=" + ",".join(bits))
    if _dynamic_budget_on():
        try:
            cash = _available_cash()
            snap = _fill_budget_snapshot(cash)
            parts.append(
                "E=%.0f N=%s k=%s k_other=%s reserve=%.0f lot=%.0f book_mv=%.0f other_mv=%.0f name_mv=%.0f "
                "n_buy=%s why=%s src=%s"
                % (
                    float(snap.get("E") or 0),
                    snap.get("N"),
                    snap.get("k"),
                    snap.get("k_other"),
                    float(snap.get("reserve") or 0),
                    float(snap.get("lot") or 0),
                    float(snap.get("book_mv") or 0),
                    float(snap.get("other_mv") or 0),
                    float(snap.get("name_mv") or 0),
                    snap.get("n_buy"),
                    snap.get("why") or "-",
                    snap.get("src") or "-",
                )
            )
        except Exception:
            pass
    return " ".join(parts)

# === hlband/strategy.py ===
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


def _cross_down(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev >= b_prev) and (a_now < b_now)


def _cross_up(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev <= b_prev) and (a_now > b_now)


def _eval_weekly(closes_w):
    """返回 (bull, bear, detail)。
    多头(仅日志): MA5>MA13 且 DIF>0 且红柱 且生命线未明显走平。
    空头: 收盘破 MA34（W_MA_LIFE）或 DIF/DEA 零轴下死叉。"""
    detail = {
        "ma5": None,
        "ma10": None,
        "ma30": None,
        "dif": None,
        "dea": None,
        "hist": None,
        "close": None,
    }
    ma5 = _price_ma(closes_w, W_MA_FAST)
    ma10 = _price_ma(closes_w, W_MA_MID)
    ma30 = _price_ma(closes_w, W_MA_LIFE)
    macd = _calc_macd(closes_w)
    if ma5 is None or ma10 is None or ma30 is None or macd is None:
        return False, False, detail
    dif, dea, hist = macd
    i = len(closes_w) - 1
    if i < 1:
        return False, False, detail
    c = float(closes_w[i])
    m5 = _last_valid(ma5, i)
    m10 = _last_valid(ma10, i)
    m30 = _last_valid(ma30, i)
    m30_prev = _last_valid(ma30, i - 1)
    d0 = _last_valid(dif, i)
    e0 = _last_valid(dea, i)
    h0 = _last_valid(hist, i)
    h1 = _last_valid(hist, i - 1)
    d1 = _last_valid(dif, i - 1)
    e1 = _last_valid(dea, i - 1)
    d2 = _last_valid(dif, i - 2) if i >= 2 else None
    e2 = _last_valid(dea, i - 2) if i >= 2 else None
    golden_now = _cross_up(d1, e1, d0, e0)
    golden_prev = _cross_up(d2, e2, d1, e1) if i >= 2 else False
    slope_weeks = int(globals().get("W_MA30_SLOPE_WEEKS", 2) or 2)
    slope_up_n = False
    if slope_weeks > 0 and i >= slope_weeks:
        slope_up_n = True
        for k in range(slope_weeks):
            a = _last_valid(ma30, i - k)
            b = _last_valid(ma30, i - k - 1)
            if a is None or b is None or not (a > b):
                slope_up_n = False
                break
    detail.update(
        {
            "ma5": m5,
            "ma10": m10,
            "ma30": m30,
            "ma30_prev": m30_prev,
            "ma30_slope_up2": slope_up_n,
            "dif": d0,
            "dea": e0,
            "dif_prev": d1,
            "dea_prev": e1,
            "hist": h0,
            "hist_prev": h1,
            "macd_golden_now": golden_now,
            "macd_golden_prev": golden_prev,
            "close": c,
        }
    )
    if None in (m5, m10, m30, d0, e0, h0):
        return False, False, detail

    ma30_ok = (m30_prev is None) or (m30 >= m30_prev * 0.998)
    bull = (m5 > m10) and (d0 > 0) and (h0 > 0) and ma30_ok
    death_below = _cross_down(d1, e1, d0, e0) and (d0 < 0) and (e0 < 0)
    bear = (c < m30) or death_below
    return bull, bear, detail


def _w_bear_confirm_need():
    """最少 1：当天空头即可挂清仓；勿用 `x or 2`（0 会被当成缺省翻成 2）。"""
    raw = globals().get("W_BEAR_CONFIRM_DAYS", 2)
    try:
        n = int(2 if raw is None else raw)
    except Exception:
        n = 2
    return max(1, n)


def _update_w_bear_streak(weekly_bear, sig_day, track):
    """
    连续 N 个信号日仍周线空头才确认清仓。
    track=False（实盘盘中 exec）不改计数，避免半成品 K 抖动。
    返回 (force_empty, streak)。
    """
    need = _w_bear_confirm_need()
    sig_day = str(sig_day or "")
    streak = int(getattr(A, "_w_bear_streak", 0) or 0)
    last = str(getattr(A, "_w_bear_last_day", "") or "")
    if not track:
        return bool(weekly_bear) and streak >= need, streak
    if not sig_day:
        return False, streak

    prev_streak = streak
    prev_last = last
    changed = False

    if sig_day == last:
        # 同一信号日：confirm 窗内可能先空后翻多（或相反），须跟最终电平
        if weekly_bear:
            if streak <= 0:
                streak = 1
                changed = True
        else:
            if streak > 0:
                streak = 0
                changed = True
    elif weekly_bear:
        if streak > 0 and last and sig_day > last:
            streak = streak + 1
        else:
            streak = 1
        changed = True
    else:
        streak = 0
        changed = True

    A._w_bear_streak = int(streak)
    A._w_bear_last_day = sig_day
    if changed or (sig_day != prev_last):
        if not getattr(A, "is_backtest", False):
            _save_state()
        if weekly_bear and (streak != prev_streak or sig_day != prev_last):
            print(
                "%s w_bear streak=%d/%d day=%s"
                % (STRATEGY_NAME, streak, need, sig_day)
            )
            _event_log(
                "w_bear_streak",
                streak=streak,
                need=need,
                signal_day=sig_day,
            )
        elif (not weekly_bear) and prev_streak:
            print(
                "%s w_bear streak reset day=%s (was %d)"
                % (STRATEGY_NAME, sig_day, prev_streak)
            )
            _event_log(
                "w_bear_streak_reset",
                signal_day=sig_day,
                was=prev_streak,
            )
    return streak >= need, streak


def _eval_daily_buy(closes, volumes):
    """买点：缩量回踩 MA20/MA60。"""
    reasons = []
    ma20 = _price_ma(closes, D_MA_MID)
    ma60 = _price_ma(closes, D_MA_SLOW)
    vol10 = _sma(volumes, VOL_PULLBACK_N)
    vol20 = _sma(volumes, VOL_DRY_N)
    if ma20 is None or ma60 is None or vol10 is None or vol20 is None:
        return False, reasons, {}
    i = len(closes) - 1
    if i < 2:
        return False, reasons, {}
    price = float(closes[i])
    vol = float(volumes[i])
    m20 = _last_valid(ma20, i)
    m60 = _last_valid(ma60, i)
    v10 = _last_valid(vol10, i)
    v20 = _last_valid(vol20, i)
    detail = {
        "ma20": m20,
        "ma60": m60,
        "vol10": v10,
        "vol20": v20,
    }

    prev = float(closes[i - 1]) if closes[i - 1] else 0.0
    if prev > 0 and (price - prev) / prev >= float(CHASE_MAX_PCT):
        return False, ["chase_skip"], detail

    # 无量阴跌不言底：跌破 MA20 且量 < 20 日均量 * VOL_DRY_RATIO → 全局禁开
    dry_below = (
        m20 is not None
        and price < m20
        and v20 is not None
        and v20 > 0
        and vol < v20 * float(VOL_DRY_RATIO)
    )
    if dry_below:
        return False, ["vol_dry_skip"], detail

    # 缩量回踩 MA20/MA60 + 量 < 10 日均量 * 0.9
    near = _near_ma(price, m20) or _near_ma(price, m60)
    shrink = v10 is not None and v10 > 0 and vol < v10 * float(VOL_PULLBACK_RATIO)
    if near and shrink:
        reasons.append("pullback_vol")

    return bool(reasons), reasons, detail


def _weekly_bias_guard(w_detail):
    """周线 (MA5-MA34)/MA34 >= W_BIAS_HARD → 禁开。"""
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, None
    bias = (float(m5) - float(m30)) / float(m30)
    return bias >= float(W_BIAS_HARD), bias


def _weekly_low_slope_guard(w_detail):
    """低位 (MA5-MA34)/MA34 < W_BIAS_LOW 且生命线 MA34 未连续向上 → 禁开。"""
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, None
    bias = (float(m5) - float(m30)) / float(m30)
    if bias >= float(W_BIAS_LOW):
        return False, bias
    slope_ok = bool(w_detail.get("ma30_slope_up2"))
    return (not slope_ok), bias


def _update_hold_peak(high_px, cost):
    """持仓期跟踪最高价（移动止盈用）。"""
    hi = float(high_px)
    peak = getattr(A, "hold_peak", None)
    if peak is None:
        base = float(cost) if cost and cost > 0 else hi
        A.hold_peak = max(base, hi)
        changed = True
    elif hi > float(peak):
        A.hold_peak = hi
        changed = True
    else:
        changed = False
    if cost and float(cost) > 0:
        mx = (float(A.hold_peak) - float(cost)) / float(cost)
        prev = float(getattr(A, "hold_max_ret", 0) or 0)
        if mx > prev:
            A.hold_max_ret = mx
            changed = True
    return changed


def _trail_tier_params(max_profit):
    """按峰值浮盈选档，返回 (giveback, profit_floor)；未达起步档则 (None, None)。"""
    mp = float(max_profit)
    for lo, hi, giveback, floor in TRAIL_TIERS:
        if mp < float(lo):
            continue
        if hi is not None and mp >= float(hi):
            continue
        fl = None if floor is None else float(floor)
        return float(giveback), fl
    return None, None


def _trail_stop_hit(price, cost, peak=None):
    """阶梯移动止盈：峰值浮盈落档后，回撤超容忍 或 跌破利润底线。"""
    if cost is None or cost <= 0:
        return False
    if peak is None:
        peak = getattr(A, "hold_peak", None)
    if peak is None or peak <= 0:
        return False
    max_profit = (float(peak) - float(cost)) / float(cost)
    giveback_lim, profit_floor = _trail_tier_params(max_profit)
    if giveback_lim is None:
        return False
    giveback = (float(peak) - float(price)) / float(peak)
    if giveback > giveback_lim:
        return True
    if profit_floor is not None:
        cur_profit = (float(price) - float(cost)) / float(cost)
        if cur_profit < profit_floor:
            return True
    return False


def _time_force_min_ret():
    try:
        return float(globals().get("TIME_FORCE_MIN_RET") or 0)
    except Exception:
        return 0.0


def _time_force_peak_ret(lot):
    if lot is None:
        mx = float(getattr(A, "hold_max_ret", 0) or 0)
        peak = getattr(A, "hold_peak", None)
        cost = _pos_cost_price()
    else:
        try:
            mx = float(lot.get("hold_max_ret") or 0)
        except Exception:
            mx = 0.0
        peak = lot.get("hold_peak")
        cost = float(lot.get("price") or 0)
    if peak and cost and float(cost) > 0:
        mx = max(mx, (float(peak) - float(cost)) / float(cost))
    return mx


def _time_force_already_skip(lot):
    if lot is None:
        return bool(getattr(A, "time_force_trend_skip", False))
    return bool(lot.get("time_force_trend_skip"))


def _time_force_mark_skip(lot, peak_ret, hold_bars, m60):
    if lot is None:
        A.time_force_trend_skip = True
        lid = None
    else:
        lot["time_force_trend_skip"] = True
        lid = lot.get("id")
    print(
        "%s time_force skip trend peak=%.2f%% ma60=%.4f hold=%s lot=%s"
        % (STRATEGY_NAME, float(peak_ret) * 100.0, m60, hold_bars, lid)
    )
    _event_log(
        "time_force_skip_trend",
        peak_ret=peak_ret,
        ma60=m60,
        hold_bars=hold_bars,
        lot_id=lid,
    )
    _save_state()


def _time_force_hit(price, closes, hold_bars, lot=None):
    """智能时间成本：持仓 > TIME_FORCE_BARS 后，破日线 MA60 强制平仓。
    仍站上 MA60 时：峰值已达 TIME_FORCE_MIN_RET（阶梯止盈起步档）则不按日历强平；
    从未武装的死钱仓豁免 GRACE 日后强平。"""
    if hold_bars is None or int(hold_bars) <= int(TIME_FORCE_BARS):
        return False
    ma60_arr = _price_ma(closes, D_MA_SLOW)
    if ma60_arr is None:
        return False
    i = len(closes) - 1
    ma60 = _last_valid(ma60_arr, i)
    if ma60 is None or price is None:
        return False
    px = float(price)
    m60 = float(ma60)

    if px < m60:
        return True

    min_ret = _time_force_min_ret()
    peak_ret = _time_force_peak_ret(lot)
    already = _time_force_already_skip(lot)
    if min_ret > 0 and (already or peak_ret >= min_ret):
        if not already:
            _time_force_mark_skip(lot, peak_ret, hold_bars, m60)
        return False

    if lot is None:
        grace_until = getattr(A, "time_force_grace_until", None)
    else:
        grace_until = lot.get("time_force_grace_until")
    if grace_until is None:
        until = int(hold_bars) + int(TIME_FORCE_GRACE_BARS)
        if lot is None:
            A.time_force_grace_until = until
        else:
            lot["time_force_grace_until"] = until
        print(
            "%s time_force grace ma60=%.4f hold=%s until_bars=%s lot=%s"
            % (STRATEGY_NAME, m60, hold_bars, until, None if lot is None else lot.get("id"))
        )
        _event_log(
            "time_force_grace",
            ma60=m60,
            hold_bars=hold_bars,
            until_bars=until,
            lot_id=None if lot is None else lot.get("id"),
        )
        _save_state()
        return False
    return int(hold_bars) > int(grace_until)


def _lot_from_agg():
    pos = getattr(A, "position", None) or {}
    px = float(pos.get("price", 0) or 0)
    peak = getattr(A, "hold_peak", None)
    if peak is None:
        peak = px
    cost = px if px > 0 else 0.0
    mx = 0.0
    if cost > 0 and peak is not None:
        mx = (float(peak) - cost) / cost
    return {
        "id": 1,
        "shares": int(pos.get("shares", 0) or 0),
        "price": px,
        "opened_at": str(pos.get("opened_at", "") or ""),
        "hold_peak": peak,
        "hold_close_peak": peak,
        "hold_max_ret": mx,
        "hold_bars": int(getattr(A, "hold_bars", 0) or 0),
        "hold_count_bar": str(getattr(A, "_hold_count_day", "") or ""),
        "time_force_grace_until": getattr(A, "time_force_grace_until", None),
        "time_force_trend_skip": bool(getattr(A, "time_force_trend_skip", False)),
    }


def _mirror_hold_from_lots():
    lots = getattr(A, "lots", None) or []
    if not lots:
        A.hold_peak = None
        A.hold_close_peak = None
        A.hold_max_ret = 0.0
        A.hold_bars = 0
        A._hold_count_bar = ""
        A._hold_count_day = ""
        A.time_force_grace_until = None
        A.time_force_trend_skip = False
        return
    lot = lots[0]
    A.hold_peak = lot.get("hold_peak")
    A.hold_close_peak = lot.get("hold_close_peak")
    A.hold_max_ret = float(lot.get("hold_max_ret") or 0)
    A.hold_bars = int(lot.get("hold_bars") or 0)
    tag = str(lot.get("hold_count_bar") or "")
    A._hold_count_bar = tag
    A._hold_count_day = tag
    A.time_force_grace_until = lot.get("time_force_grace_until")
    A.time_force_trend_skip = bool(lot.get("time_force_trend_skip"))


def _infer_round_scaled():
    """旧状态无 round_scaled 时：剩余笔 id>1 或同时 >=2 笔，视为本轮已加过仓。"""
    if _lots_enabled():
        mx = 0
        n = 0
        for lot in getattr(A, "lots", None) or []:
            if not isinstance(lot, dict):
                continue
            try:
                sh = int(lot.get("shares") or 0)
            except Exception:
                sh = 0
            if sh < 100:
                continue
            n += 1
            try:
                mx = max(mx, int(lot.get("id") or 0))
            except Exception:
                pass
        return n >= 2 or mx > 1
    pos = getattr(A, "position", None) or {}
    try:
        return int(pos.get("lots", 1) or 1) >= 2
    except Exception:
        return False


def _round_scaled_now():
    if bool(getattr(A, "round_scaled", False)):
        return True
    if not _infer_round_scaled():
        return False
    A.round_scaled = True
    try:
        _save_state()
    except Exception:
        pass
    return True


def _scale_peak_ret():
    mx = 0.0
    armed_bars = 0
    arm = float(globals().get("SCALE_ARM") or 0)
    if arm <= 0:
        arm = 0.03
    if _lots_enabled():
        for lot in _ensure_lots():
            try:
                ret = float(lot.get("hold_max_ret") or 0)
            except Exception:
                ret = 0.0
            bars = int(lot.get("hold_bars") or 0)
            if ret > mx:
                mx = ret
            if ret >= arm and bars > armed_bars:
                armed_bars = bars
        if mx <= 0:
            peak = getattr(A, "hold_peak", None)
            cost = _pos_cost_price()
            if peak and cost > 0:
                mx = (float(peak) - float(cost)) / float(cost)
            armed_bars = int(getattr(A, "hold_bars", 0) or 0)
        return mx, armed_bars
    peak = getattr(A, "hold_peak", None)
    cost = _pos_cost_price()
    if peak and cost > 0:
        mx = (float(peak) - float(cost)) / float(cost)
    armed_bars = int(getattr(A, "hold_bars", 0) or 0)
    return mx, armed_bars


def _scale_gate(w_detail=None, price=None):
    """加仓门槛：(ok, why)。why 仅失败时有值。"""
    if not bool(globals().get("SCALE_ENABLE")):
        return False, "scale_off"
    holding_now = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= 100
    )
    if not holding_now:
        return False, "scale_no_pos"
    if bool(globals().get("SCALE_ONCE_PER_ROUND", True)) and _round_scaled_now():
        return False, "scale_once"
    if _pos_lots() >= int(globals().get("SCALE_MAX") or 1):
        return False, "scale_max"
    arm = float(globals().get("SCALE_ARM") or 0)
    if arm <= 0:
        arm = 0.03
    mx, armed_bars = _scale_peak_ret()
    if mx < arm:
        return False, "scale_arm"
    need_bars = int(globals().get("SCALE_ARM_BARS") or 0)
    if need_bars > 0 and armed_bars < need_bars:
        return False, "scale_bars"
    hist_min = globals().get("SCALE_W_HIST_MIN")
    if hist_min is not None and w_detail is not None:
        h = w_detail.get("hist")
        if h is not None and float(h) < float(hist_min):
            return False, "scale_w_hist"
    return True, ""


def _scale_ready(w_detail=None):
    ok, _why = _scale_gate(w_detail)
    return ok


def _daily_plat_break(closes, highs, lows):
    """日线收盘确认突破前期平台：回看窗口振幅够窄，今日收盘站上窗口最高价，昨收仍在平台内。"""
    lookback = int(globals().get("SCALE_PLAT_LOOKBACK") or 20)
    max_range = float(globals().get("SCALE_PLAT_MAX_RANGE") or 0.10)
    buf = float(globals().get("SCALE_PLAT_BREAK_BUF") or 0.0)
    if lookback < 5 or max_range <= 0:
        return False
    if closes is None or highs is None or lows is None:
        return False
    n = len(closes)
    if n < lookback + 1 or len(highs) != n or len(lows) != n:
        return False
    if n < 2:
        return False
    plat = _plat_window(highs, lows, lookback)
    if plat is None:
        return False
    plat_high, plat_low = plat
    rng = (float(plat_high) - float(plat_low)) / float(plat_low)
    if rng > max_range:
        return False
    hurdle = float(plat_high) * (1.0 + buf)
    px = float(closes[-1])
    prev = float(closes[-2])
    if px <= hurdle:
        return False
    if prev > hurdle:
        return False
    return True


def _weekly_macd_golden_expand(w_detail):
    """近两周周线 MACD 金叉，且当前红柱比上周放大。"""
    if not w_detail:
        return False
    h0 = w_detail.get("hist")
    h1 = w_detail.get("hist_prev")
    if h0 is None or h1 is None:
        return False
    hist = float(h0)
    hist_prev = float(h1)
    if hist <= 0 or hist <= hist_prev:
        return False
    golden_now = bool(w_detail.get("macd_golden_now"))
    golden_prev = bool(w_detail.get("macd_golden_prev"))
    if not (golden_now or golden_prev):
        return False
    if golden_now and (not golden_prev):
        return True
    ratio = float(globals().get("SCALE_W_HIST_EXPAND_RATIO") or 1.0)
    if ratio <= 1.0:
        return True
    base = abs(hist_prev) if abs(hist_prev) > 1e-12 else hist
    return hist >= base * ratio


def _eval_scale_push(closes, highs, lows, w_detail, pullback=False):
    """加仓触发：缩量回踩 或 日线破平台 或 周线 MACD 金叉柱放大。"""
    reasons = []
    if pullback:
        reasons.append("pullback_vol")
    if _daily_plat_break(closes, highs, lows):
        reasons.append("plat_break")
    if _weekly_macd_golden_expand(w_detail):
        reasons.append("w_macd_golden")
    return bool(reasons), reasons


def _eval_lot_sell(price, closes, lot):
    reasons = []
    cost = float(lot.get("price") or 0)
    if cost > 0 and price <= cost * (1.0 - float(STOP_LOSS)):
        reasons.append("stop_loss")
        return True, reasons
    if _trail_stop_hit(price, cost, peak=lot.get("hold_peak")):
        reasons.append("trail_stop")
        return True, reasons
    if _time_force_hit(price, closes, lot.get("hold_bars", 0), lot=lot):
        reasons.append("time_force")
        return True, reasons
    return False, reasons


def _collect_lot_exits(price, closes, force_empty):
    lots = _ensure_lots()
    if not lots:
        return False, [], [], 0
    if force_empty:
        lot_ids = [int(l.get("id") or 0) for l in lots]
        shares = sum(int(l.get("shares") or 0) for l in lots)
        return True, ["weekly_bear"], lot_ids, shares
    exits = []
    for lot in lots:
        ok, reasons = _eval_lot_sell(price, closes, lot)
        if ok:
            exits.append((lot, reasons))
    if not exits:
        return False, [], [], 0
    lot_ids = [int(item[0].get("id") or 0) for item in exits]
    shares = sum(int(item[0].get("shares") or 0) for item in exits)
    reasons = []
    for _lot, rs in exits:
        for r in rs:
            if r not in reasons:
                reasons.append(r)
    return True, reasons, lot_ids, shares


def _clear_hold_meta():
    A.hold_peak = None
    A.hold_bars = 0
    A._hold_count_day = ""
    A.time_force_grace_until = None
    A.time_force_trend_skip = False
    A.round_scaled = False


def _bump_hold_bars(day):
    """每个交易日持仓计 1 根。"""
    if getattr(A, "_hold_count_day", "") == day:
        return
    A.hold_bars = int(getattr(A, "hold_bars", 0) or 0) + 1
    A._hold_count_day = day


def _drop_forming_bar(seq):
    """去掉正在形成的最新一根（实盘未收盘 K）。"""
    if seq is None:
        return None
    if len(seq) < 2:
        return list(seq) if seq else seq
    return list(seq[:-1])


def _live_close_confirm_on():
    return (not getattr(A, "is_backtest", False)) and bool(
        globals().get("LIVE_CLOSE_CONFIRM", True)
    )


def _calendar_prev_weekday(yyyymmdd):
    """自然日回退到上一工作日（跳过周末；节假日以行情轴为准）。"""
    try:
        d = datetime.datetime.strptime(str(yyyymmdd), "%Y%m%d")
    except Exception:
        return str(yyyymmdd)
    d -= datetime.timedelta(days=1)
    while int(d.weekday()) >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y%m%d")


def _last_closed_bar_day(C, today):
    """上一根已收盘日线交易日；优先行情时间轴，否则跳过周末的自然日。"""
    today = str(today)
    days = None
    try:
        days = _get_daily_bar_days(C, A.stock, count=8)
    except Exception:
        days = None
    if days:
        last = str(days[-1])
        if last >= today and len(days) >= 2:
            return str(days[-2])
        if last and last < today:
            return last
    return _calendar_prev_weekday(today)


def _live_signal_day(C, today):
    """开盘兜底/盘中校验用的信号日：上一根已收盘交易日（保证 signal_day < 今日可成交）。"""
    return _last_closed_bar_day(C, today)


def _mark_confirmed_eval(day):
    """收盘确认完成（当日完整 K）。"""
    A._confirmed_eval_day = str(day)
    _save_state()


def _mark_fallback_done(day):
    """开盘兜底评估完成；不写 confirmed，以免挡住今日收盘确认。"""
    A._fallback_done_day = str(day)
    _save_state()


def _mark_signal_eval_done(day, is_confirm):
    if is_confirm:
        _mark_confirmed_eval(day)
    else:
        _mark_fallback_done(day)


def _pending_ready(pend, day, bar_tag, mode):
    if not isinstance(pend, dict):
        return False
    sig_tag = str(pend.get("signal_tag", "") or "")
    sig_day = str(pend.get("signal_day", "") or "")
    if mode == "day":
        # 同日尾盘可成交；隔夜残留次日可成交。实际报单还受 _can_exec_signal_pending 约束。
        return bool(sig_day) and sig_day <= day
    if sig_tag and bar_tag:
        return sig_tag < bar_tag
    if sig_day and sig_day <= day:
        return True
    return False


def _cfg_hhmmss(key, default):
    return str(globals().get(key, default) or default)


def _in_hhmmss_window(now_s, start, end, inclusive_end=False):
    s = str(now_s)
    if inclusive_end:
        return start <= s <= end
    return start <= s < end


def _in_close_exec_window(now_s):
    start = _cfg_hhmmss("PENDING_EXEC_START", "145600")
    end = _cfg_hhmmss("PENDING_EXEC_END", "145700")
    return _in_hhmmss_window(now_s, start, end, inclusive_end=False)


def _in_open_exec_window(now_s):
    start = _cfg_hhmmss("OPEN_EXEC_START", "093000")
    end = _cfg_hhmmss("OPEN_EXEC_END", "094500")
    return _in_hhmmss_window(now_s, start, end, inclusive_end=False)


def _can_exec_signal_pending(pend, day, now_s):
    """回测随时；实盘当日信号仅尾盘，隔夜残留开盘窗（尾盘也可补）。"""
    if getattr(A, "is_backtest", False):
        return True
    if not _live_close_confirm_on():
        return True
    if not isinstance(pend, dict):
        return False
    sig_day = str(pend.get("signal_day", "") or "")
    if _in_close_exec_window(now_s):
        return True
    if _in_open_exec_window(now_s) and sig_day and sig_day < str(day):
        return True
    return False


def _signal_exec_px(pend, day, now_s, open_px, last_px):
    """尾盘/回测同日用收盘现价；隔夜残留用开盘价。"""
    sig_day = str((pend or {}).get("signal_day", "") or "")
    if getattr(A, "is_backtest", False):
        if sig_day and sig_day < str(day):
            return float(open_px), "open"
        return float(last_px), "close"
    if _in_close_exec_window(now_s):
        return float(last_px), "close"
    return float(open_px), "open"


def _log_pending_defer_once(kind, day, now_s, signal_day):
    """成交窗外 defer 每个交易日每种 pending 只打一次日志，避免盘中刷屏。"""
    kind = str(kind or "")
    day = str(day or "")
    attr = "_defer_log_%s_day" % kind
    if str(getattr(A, attr, "") or "") == day:
        return
    setattr(A, attr, day)
    print(
        "%s pending_%s defer outside exec window now=%s signal_day=%s"
        % (STRATEGY_NAME, kind, now_s, signal_day)
    )
    _event_log(
        "pending_%s_defer" % kind,
        now=now_s,
        signal_day=signal_day,
        close_exec_end=_cfg_hhmmss("PENDING_EXEC_END", "145700"),
        open_exec_end=_cfg_hhmmss("OPEN_EXEC_END", "094500"),
    )


def _should_emit_bar_status(C, now, force, status_idle):
    """
    状态行是否输出。
    force（信号上升沿）立刻打；回测 idle 逐 bar、非 idle 每 20 根；
    实盘无新沿时一律按 LIVE_HEARTBEAT_SEC 节流（空仓/持仓/挂起相同）。
    """
    if not getattr(A, "ready_logged", False):
        return True
    if force:
        return True
    if getattr(A, "is_backtest", False):
        if status_idle:
            return True
        try:
            return int(getattr(C, "barpos", 0) or 0) % 20 == 0
        except Exception:
            return False
    sec = int(globals().get("LIVE_HEARTBEAT_SEC") or 60)
    if sec <= 0:
        return True
    last = getattr(A, "_bar_status_at", None)
    if last is not None and now is not None:
        try:
            if (now - last).total_seconds() < float(sec):
                return False
        except Exception:
            pass
    return True


def _bar_signal_rising_edge(buy_sig, sell_ok, force_empty):
    """
    相对上一 tick 的买卖/强平上升沿。
    电平一直为真时不再强制打状态行（避免收盘确认窗刷屏）。
    """
    cur = (bool(buy_sig), bool(sell_ok), bool(force_empty))
    prev = getattr(A, "_bar_sig_prev", None)
    A._bar_sig_prev = cur
    if prev is None:
        return bool(cur[0] or cur[1] or cur[2])
    return (
        (cur[0] and not prev[0])
        or (cur[1] and not prev[1])
        or (cur[2] and not prev[2])
    )


def _lot_open_day(lot):
    ot = str((lot or {}).get("opened_at") or "")
    return ot[:8] if len(ot) >= 8 else ""


def _pending_exit_unfilled_ids():
    """pending_exit.lot_ids 中仍持有的笔；无 lot_ids 视为整仓出清残留。"""
    pe = getattr(A, "pending_exit", None)
    if not isinstance(pe, dict):
        return []
    lots = getattr(A, "lots", None) or []
    raw_ids = pe.get("lot_ids")
    idset = None
    if raw_ids:
        try:
            idset = set(int(x) for x in raw_ids)
        except Exception:
            idset = None
    remain = []
    for lot in lots:
        if not isinstance(lot, dict):
            continue
        try:
            sh = int(lot.get("shares") or 0)
            lid = int(lot.get("id") or 0)
        except Exception:
            continue
        if sh < 100 or lid <= 0:
            continue
        if idset is None or lid in idset:
            remain.append(lid)
    return remain


def _refresh_pending_exit_remain(remain_ids):
    pe = getattr(A, "pending_exit", None)
    if not isinstance(pe, dict):
        return
    remain_ids = [int(x) for x in (remain_ids or []) if x]
    pe["lot_ids"] = list(remain_ids)
    shares = 0
    idset = set(remain_ids)
    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        try:
            if int(lot.get("id") or 0) in idset:
                shares += int(lot.get("shares") or 0)
        except Exception:
            continue
    pe["shares"] = int(shares)
    A.pending_exit = pe


def _log_skip_sell_eval_day(day):
    day = str(day or "")
    if str(getattr(A, "_skip_sell_eval_logged", "") or "") == day:
        return
    A._skip_sell_eval_logged = day
    print(
        "%s skip sell eval after add fill day=%s last_add=%s"
        % (STRATEGY_NAME, day, getattr(A, "_last_add_signal", "") or "-")
    )
    _event_log(
        "skip_sell_eval_day",
        day=day,
        last_add=getattr(A, "_last_add_signal", "") or "",
        last_add_day=getattr(A, "_last_add_day", "") or "",
    )


def _log_sell_lot_can_use(now, day, lot_ids, want_vol, reason):
    """核对按笔卖出 vs 券商合计 can_use：当日新仓可能实际卖掉旧仓。"""
    avail = None
    try:
        avail = _max_sell_vol(now)
    except Exception:
        avail = None
    idset = None
    if lot_ids:
        try:
            idset = set(int(x) for x in lot_ids)
        except Exception:
            idset = None
    target = []
    others = []
    same_day_target = []
    older_other = []
    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        try:
            lid = int(lot.get("id") or 0)
            sh = int(lot.get("shares") or 0)
        except Exception:
            continue
        if sh < 100 or lid <= 0:
            continue
        open_day = _lot_open_day(lot)
        brief = {
            "id": lid,
            "shares": sh,
            "opened_at": str(lot.get("opened_at") or ""),
            "open_day": open_day,
            "hold_bars": lot.get("hold_bars"),
        }
        is_tgt = idset is None or lid in idset
        if is_tgt:
            target.append(brief)
            if open_day and open_day == str(day):
                same_day_target.append(lid)
        else:
            others.append(brief)
            if open_day and open_day < str(day):
                older_other.append(lid)
    last_add_day = str(getattr(A, "_last_add_day", "") or "")
    last_add = str(getattr(A, "_last_add_signal", "") or "")
    risk = bool(same_day_target) and (avail is None or int(avail) >= 100) and (
        bool(older_other) or bool(others)
    )
    print(
        "%s SELL lot-can_use reason=%s lots=%s want=%s avail=%s "
        "same_day_lots=%s other=%s last_add=%s@%s risk=%s"
        % (
            STRATEGY_NAME,
            reason,
            lot_ids if lot_ids is not None else "-",
            want_vol,
            avail,
            same_day_target or "-",
            [x.get("id") for x in others] or "-",
            last_add or "-",
            last_add_day or "-",
            risk,
        )
    )
    _event_log(
        "sell_lot_can_use",
        reason=reason,
        lot_ids=lot_ids,
        want=want_vol,
        avail=avail,
        target=target,
        other=others,
        same_day_lots=same_day_target,
        last_add=last_add,
        last_add_day=last_add_day,
        risk=risk,
    )
    if risk:
        print(
            "%s WARN SELL lots=%s opened today; broker can_use may fill older lots, "
            "not necessarily lots=%s (plat_break add same-day trail is the typical case)"
            % (STRATEGY_NAME, same_day_target, lot_ids)
        )
        _event_log(
            "sell_lot_can_use_risk",
            lot_ids=lot_ids,
            same_day_lots=same_day_target,
            avail=avail,
            last_add=last_add,
            last_add_day=last_add_day,
        )


def _after_signal_buy_filled(px, day, add=False):
    """买入成交后初始化持仓元数据并清信号 pending。"""
    pe = getattr(A, "pending_entry", None)
    add_reasons = []
    if isinstance(pe, dict):
        add_reasons = [str(x) for x in (pe.get("reasons") or []) if x]
    A.pending_entry = None
    A.pending_exit = None
    A.round_scaled = True if add else False
    if add:
        d = str(day or "")
        A._skip_sell_eval_day = d
        A._last_add_day = d
        A._last_add_signal = ",".join(add_reasons) if add_reasons else "add"
        print(
            "%s skip sell eval after add fill day=%s signal=%s"
            % (STRATEGY_NAME, d, A._last_add_signal)
        )
        _event_log(
            "skip_sell_eval_after_add",
            day=d,
            signal=A._last_add_signal,
        )
    if _lots_enabled():
        lots = getattr(A, "lots", None) or []
        if lots and day:
            lots[-1]["hold_count_bar"] = str(day)
            if not add:
                lots[-1]["hold_bars"] = 0
        _mirror_hold_from_lots()
        _save_state()
        return
    if not add:
        try:
            A.hold_peak = float(px) if px else None
        except Exception:
            A.hold_peak = None
        A.hold_bars = 0
        A._hold_count_day = str(day or "")
        A.time_force_grace_until = None
        A.time_force_trend_skip = False
    _save_state()


def _after_signal_sell_filled():
    """卖出成交（或已空仓）后清信号 pending 与持仓元数据。"""
    A.pending_exit = None
    A.pending_entry = None
    A.lots = []
    _clear_hold_meta()
    _save_state()


def _finish_sell_fill():
    if _lots_enabled() and getattr(A, "lots", None):
        remain = _pending_exit_unfilled_ids()
        if remain:
            _refresh_pending_exit_remain(remain)
            acted = getattr(A, "acted", None)
            if isinstance(acted, set):
                acted.discard("SELL")
            pe = getattr(A, "pending_exit", None) or {}
            print(
                "%s pending_exit keep after partial fill lots=%s shares=%s"
                % (STRATEGY_NAME, remain, pe.get("shares"))
            )
            _event_log(
                "pending_exit_keep_partial",
                lot_ids=remain,
                shares=pe.get("shares"),
            )
            _save_state()
            return
        A.pending_exit = None
        acted = getattr(A, "acted", None)
        if isinstance(acted, set):
            acted.discard("SELL")
        _save_state()
        return
    _after_signal_sell_filled()


def _pending_on_buy_fill(pend, vol, px):
    """覆盖 common：成交后再清 pending_entry / 写 hold_meta（废单则保留信号 pending）。"""
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)
    ot = str(pend.get("opened_at") or pend.get("submitted_at") or "")
    day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
    _after_signal_buy_filled(px, day, add=bool(extra.get("add")))


def _pending_on_sell_fill(pend, now, vol, px):
    """覆盖 common：成交后再清 pending_exit；部分成交仍持仓则保留 hold_meta。"""
    intent = str(pend.get("intent", "") or "")
    last_hint = pend.get("last_hint")
    if last_hint is None:
        last_hint = px
    mark_half = bool(pend.get("mark_half"))
    lot_ids = pend.get("lot_ids")
    if not lot_ids:
        pe = getattr(A, "pending_exit", None)
        if isinstance(pe, dict):
            lot_ids = pe.get("lot_ids")
    _apply_sell_fill(now, intent, last_hint, vol, mark_half=mark_half, lot_ids=lot_ids)
    _finish_sell_fill()


def _on_signal_order_ok(side, px=None, day=None, add=False):
    """下单返回 True：实盘等成交回调；回测/DRY 立即清信号 pending 并写 hold_meta。"""
    live_waiting = (not getattr(A, "is_backtest", False)) and (
        not DRY_RUN
    ) and isinstance(getattr(A, "pending", None), dict)
    if live_waiting:
        print(
            "%s %s submitted keep signal pending until fill"
            % (STRATEGY_NAME, side)
        )
        _event_log("signal_pending_keep_until_fill", side=side)
        _save_state()
        return
    if side == "buy":
        _after_signal_buy_filled(px, day, add=add)
        return
    _finish_sell_fill()


_SELL_LABELS = {
    "trail_stop": "卖点1-移动止盈回撤",
    "time_force": "卖点2-时间成本智能平仓",
    "weekly_bear": "周线转空强制清仓",
    "stop_loss": "硬止损",
    "skip_add_bar": "加仓成交后当日不评卖",
}
_BUY_LABELS = {
    "pullback_vol": "买点1-缩量回踩强支撑",
    "plat_break": "加仓-日线突破前期平台",
    "w_macd_golden": "加仓-周线MACD金叉柱放大",
    "chase_skip": "追高过滤跳过",
    "w_bias_skip": "周线高位乖离禁开",
    "w_slope_skip": "低位周线MA34未连升禁开",
    "vol_dry_skip": "无量阴跌禁开",
    "weekly_bear": "周线空头禁开",
    "scale_once": "本轮已加仓",
    "buy_cap": "账户或单标的额度已满跳过开仓",
    "scale_cap": "账户或单标的额度已满跳过加仓",
    "wait": "等待共享账本冻结",
    "book_fail": "持股查询失败且无本地账本不下单",
}


def _reason_label(code, kind="sell"):
    code = str(code or "")
    table = _SELL_LABELS if kind == "sell" else _BUY_LABELS
    return table.get(code, code)


def _format_reasons(codes, kind="sell"):
    codes = [str(x) for x in (codes or []) if x]
    if not codes:
        return "-"
    parts = ["%s(%s)" % (c, _reason_label(c, kind)) for c in codes]
    return ",".join(parts)


def _try_exec_pending_exit(C, now, now_s, day, tag, open_px, last_px, holding):
    """成交就绪的 pending_exit。True=调用方应 return。"""
    if not holding:
        return False
    pe_exit = getattr(A, "pending_exit", None)
    if not isinstance(pe_exit, dict):
        return False
    if not _pending_ready(pe_exit, day, tag, "day"):
        return False
    if not _can_exec_signal_pending(pe_exit, day, now_s):
        _log_pending_defer_once("exit", day, now_s, pe_exit.get("signal_day"))
        return False
    px, px_kind = _signal_exec_px(pe_exit, day, now_s, open_px, last_px)
    reason = str(pe_exit.get("reason", "SELL") or "SELL")
    reasons = pe_exit.get("reasons") or [reason]
    print(
        "%s SELL by signal=%s label=%s all=%s lots=%s shares=%s signal_day=%s @%s=%.4f"
        % (
            STRATEGY_NAME,
            reason,
            _reason_label(reason, "sell"),
            _format_reasons(reasons, "sell"),
            pe_exit.get("lot_ids") or "-",
            pe_exit.get("shares") if pe_exit.get("shares") is not None else _pos_shares(),
            pe_exit.get("signal_day"),
            px_kind,
            px,
        )
    )
    _event_log(
        "sell_by_signal",
        signal=reason,
        label=_reason_label(reason, "sell"),
        all_reasons=_format_reasons(reasons, "sell"),
        signal_day=pe_exit.get("signal_day"),
        px=px,
        px_kind=px_kind,
        lot_ids=pe_exit.get("lot_ids"),
        shares=pe_exit.get("shares"),
    )
    lot_ids = pe_exit.get("lot_ids")
    want_vol = pe_exit.get("shares")
    _log_sell_lot_can_use(now, day, lot_ids, want_vol, reason)
    ok = _order_sell(
        C,
        reason,
        px,
        now,
        want_vol=None if want_vol is None else int(want_vol),
        lot_ids=lot_ids,
    )
    if ok:
        _on_signal_order_ok("sell")
    else:
        print(
            "%s pending_exit keep after sell fail/skip signal=%s"
            % (STRATEGY_NAME, reason)
        )
        _event_log(
            "pending_exit_keep_after_fail",
            sell_reason=reason,
            signal_day=pe_exit.get("signal_day"),
        )
    return True


def _try_exec_pending_entry(
    C,
    now,
    now_s,
    day,
    tag,
    open_px,
    last_px,
    holding,
    cash,
    weekly_bear,
    w_bias_block,
    w_slope_block,
    vol_dry_block,
    w_detail,
    force_empty,
    sell_ok,
    stop_hit,
    trail_hit,
    time_force_hit,
):
    """成交就绪的 pending_entry。'done'=return；'force_eval'=让路卖点；None=继续。"""
    pe_entry = getattr(A, "pending_entry", None)
    pe_is_add = isinstance(pe_entry, dict) and bool(pe_entry.get("add"))
    if not (
        ((not holding) or pe_is_add)
        and isinstance(pe_entry, dict)
        and (pe_is_add or ("BUY" not in getattr(A, "acted", set())))
        and _pending_ready(pe_entry, day, tag, "day")
    ):
        return None
    if pe_is_add and not holding:
        A.pending_entry = None
        _save_state()
        print("%s pending_entry cancel add_no_pos" % STRATEGY_NAME)
        _event_log("pending_entry_cancel", reason="add_no_pos")
        return "done"
    sell_block = bool(
        pe_is_add
        and (force_empty or sell_ok or stop_hit or trail_hit or time_force_hit)
    )
    scale_ok, scale_why = _scale_gate(w_detail, price=last_px) if pe_is_add else (True, "")
    if sell_block or (pe_is_add and (not scale_ok)):
        why = "scale_sell_block" if sell_block else scale_why
        A.pending_entry = None
        _save_state()
        print("%s pending_entry cancel %s" % (STRATEGY_NAME, why))
        _event_log(
            "pending_entry_cancel",
            reason=why,
            signal_day=pe_entry.get("signal_day"),
        )
        if sell_block:
            return "force_eval"
        return "done"
    if weekly_bear or w_bias_block or w_slope_block or vol_dry_block:
        A.pending_entry = None
        _save_state()
        if weekly_bear:
            why = "weekly_bear"
        elif w_bias_block:
            why = "w_bias_skip"
        elif w_slope_block:
            why = "w_slope_skip"
        else:
            why = "vol_dry_skip"
        print("%s pending_entry cancel %s" % (STRATEGY_NAME, why))
        _event_log(
            "pending_entry_cancel",
            reason=why,
            signal_day=pe_entry.get("signal_day"),
        )
        return "done"
    if not _can_exec_signal_pending(pe_entry, day, now_s):
        _log_pending_defer_once("entry", day, now_s, pe_entry.get("signal_day"))
        return None
    if _equal_split_on() and (not _book_is_frozen(now_s)):
        _log_pending_defer_once("book", day, now_s, pe_entry.get("signal_day"))
        return None
    px, px_kind = _signal_exec_px(pe_entry, day, now_s, open_px, last_px)
    reasons = pe_entry.get("reasons") or []
    primary = reasons[0] if reasons else "entry"
    kind = "add" if pe_is_add else "buy"
    cap_ok, cap_why, snap = _fill_room_ok(px, opening=not pe_is_add)
    if _dynamic_budget_on():
        _log_fill_budget(snap, kind)
    if cap_why in ("wait", "book_fail", "no_E"):
        _log_pending_defer_once(cap_why or "wait", day, now_s, pe_entry.get("signal_day"))
        return None
    if not cap_ok:
        A.pending_entry = None
        _save_state()
        why = cap_why or ("scale_cap" if pe_is_add else "buy_cap")
        print("%s pending_entry cancel %s" % (STRATEGY_NAME, why))
        _event_log(
            "pending_entry_cancel",
            reason=why,
            signal_day=pe_entry.get("signal_day"),
            E=snap.get("E"),
            N=snap.get("N"),
            k=snap.get("k"),
            reserve=snap.get("reserve"),
            lot=snap.get("lot"),
            book_mv=snap.get("book_mv"),
            other_mv=snap.get("other_mv"),
            name_mv=snap.get("name_mv"),
            n_buy=snap.get("n_buy"),
            why=snap.get("why"),
        )
        return "done"
    print(
        "%s %s by signal=%s label=%s all=%s signal_day=%s @%s=%.4f"
        % (
            STRATEGY_NAME,
            "BUY add" if pe_is_add else "BUY",
            primary,
            _reason_label(primary, "buy"),
            _format_reasons(reasons, "buy"),
            pe_entry.get("signal_day"),
            px_kind,
            px,
        )
    )
    _event_log(
        "buy_by_signal" if not pe_is_add else "buy_add_by_signal",
        signal=primary,
        label=_reason_label(primary, "buy"),
        all_reasons=_format_reasons(reasons, "buy"),
        signal_day=pe_entry.get("signal_day"),
        px=px,
        px_kind=px_kind,
        add=pe_is_add,
    )
    budget = float(snap.get("lot") or 0)
    ok = _order_buy(C, px, now, budget, add=pe_is_add)
    if ok:
        _on_signal_order_ok("buy", px=px, day=day, add=pe_is_add)
    else:
        print(
            "%s pending_entry keep after %s fail/skip signal=%s"
            % (STRATEGY_NAME, kind, primary)
        )
        _event_log(
            "pending_entry_keep_after_fail",
            signal=primary,
            signal_day=pe_entry.get("signal_day"),
            add=pe_is_add,
        )
    return "done"


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)
    hhmm = _bar_hhmm(bar_dt if bt else now)
    live_cc = _live_close_confirm_on()
    conf_start = str(globals().get("SIGNAL_CONFIRM_START", "145600") or "145600")
    conf_end = str(globals().get("SIGNAL_CONFIRM_END", "160000") or "160000")
    in_exec = (not bt) and (DECISION_START <= now_s < conf_start)
    in_confirm = (not bt) and (conf_start <= now_s <= conf_end)
    # 收盘确认：用当日完整 K；开盘：日 K 去未收盘根，周 K 含未收盘根
    prev_d = False
    prev_w = False
    phase = "bt" if bt else "live"

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        if live_cc:
            if (not in_exec) and (not in_confirm):
                _live_heartbeat("outside_session")
                return
            phase = "confirm" if in_confirm else "exec"
        else:
            if now_s < DECISION_START or now_s > DECISION_END:
                _live_heartbeat("outside_session")
                return
            phase = "session"
        if LIVE_ONLY_LAST_BAR:
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        _live_heartbeat(phase)
    else:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    ohlcv_d = _get_ohlcv_1d(C, A.stock)
    if ohlcv_d is None:
        _live_heartbeat("ohlcv_1d_none")
        return
    opens_d, highs_d, lows_d, closes_d, vols_d = ohlcv_d

    ohlcv_w = _get_ohlcv_1w(C, A.stock)
    if ohlcv_w is None:
        _live_heartbeat("ohlcv_1w_none")
        return
    _ow, _hw, _lw, closes_w, _vw = ohlcv_w

    open_px = float(opens_d[-1])
    # v1.10 误把开盘兜底写成 confirmed=今日，会挡收盘确认；盘中执行时段自动清掉
    if (
        live_cc
        and phase == "exec"
        and str(getattr(A, "_confirmed_eval_day", "") or "") == day
    ):
        print(
            "%s clear mis-marked confirmed_eval_day=%s (was open fallback)"
            % (STRATEGY_NAME, day)
        )
        _event_log("clear_mis_confirmed_eval_day", day=day)
        A._confirmed_eval_day = ""
        _save_state()
    # 开盘兜底：上一根已收盘日尚未确认、今日尚未兜底、无挂起
    prev_closed_day = _last_closed_bar_day(C, day) if live_cc else day
    confirmed_day = str(getattr(A, "_confirmed_eval_day", "") or "")
    need_fallback = (
        live_cc
        and phase == "exec"
        and confirmed_day < str(prev_closed_day)
        and str(getattr(A, "_fallback_done_day", "") or "") != day
        and (not isinstance(getattr(A, "pending_entry", None), dict))
        and (not isinstance(getattr(A, "pending_exit", None), dict))
    )
    if live_cc and phase == "confirm":
        highs_s, lows_s, closes_s, vols_s = highs_d, lows_d, closes_d, vols_d
        closes_ws = closes_w
        sig_day_daily = day
        sig_day_weekly = day
    elif need_fallback or (live_cc and phase == "exec"):
        # 开盘兜底 / 盘中执行：日 K 去掉未收盘根，避免未完成日线误触 vol_dry 等；
        # 周 K 含本周未收盘根，与 confirm/回测一致（新周首日即可 weekly_bear 撤买入 pending）
        # 日信号日=上一完整交易日；周线 streak/清仓信号日=今日（与含未收盘周根对齐）
        prev_d = True
        prev_w = False
        highs_s = _drop_forming_bar(highs_d)
        lows_s = _drop_forming_bar(lows_d)
        closes_s = _drop_forming_bar(closes_d)
        vols_s = _drop_forming_bar(vols_d)
        closes_ws = closes_w
        if closes_s is None or len(closes_s) < 3 or closes_ws is None or len(closes_ws) < 3:
            _live_heartbeat("ohlcv_confirm_short")
            return
        sig_day_daily = prev_closed_day
        sig_day_weekly = day
    else:
        # 回测：信号评估用完整序列
        highs_s, lows_s, closes_s, vols_s = highs_d, lows_d, closes_d, vols_d
        closes_ws = closes_w
        sig_day_daily = day
        sig_day_weekly = day

    price = float(closes_s[-1])
    high_px = float(highs_s[-1])
    if bt:
        _bt_recover_position(now=now, last=float(closes_d[-1]))

    _refresh_ma_kind(closes_s, day=sig_day_daily)

    weekly_bull, weekly_bear, w_detail = _eval_weekly(closes_ws)
    # 清仓二次确认只在 bt / confirm / 开盘兜底累计；盘中 exec 不改 streak
    track_bear = (not live_cc) or (phase == "confirm") or bool(need_fallback)
    force_empty, w_bear_n = _update_w_bear_streak(
        weekly_bear, sig_day_weekly, track=track_bear
    )
    w_bias_block, w_bias = _weekly_bias_guard(w_detail)
    w_slope_block, _w_bias_low = _weekly_low_slope_guard(w_detail)
    buy_ok, buy_reasons, b_detail = _eval_daily_buy(closes_s, vols_s)
    if weekly_bear:
        buy_ok = False
        buy_reasons = ["weekly_bear"] + [
            r for r in buy_reasons if r not in ("weekly_bear",)
        ]
    elif w_bias_block:
        buy_ok = False
        buy_reasons = ["w_bias_skip"] + [
            r for r in buy_reasons if r not in ("w_bias_skip",)
        ]
    elif w_slope_block:
        buy_ok = False
        buy_reasons = ["w_slope_skip"] + [
            r for r in buy_reasons if r not in ("w_slope_skip",)
        ]
    sell_ok = False
    sell_reasons = []

    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    cost = _pos_cost_price()
    exit_ids = []
    exit_shares = 0
    if _lots_enabled():
        if not holding:
            if getattr(A, "lots", None):
                A.lots = []
            if (
                getattr(A, "hold_peak", None) is not None
                or int(getattr(A, "hold_bars", 0) or 0)
                or getattr(A, "time_force_grace_until", None) is not None
                or bool(getattr(A, "time_force_trend_skip", False))
                or bool(getattr(A, "round_scaled", False))
            ):
                _clear_hold_meta()
        else:
            _ensure_lots()
            changed = False
            for lot in A.lots:
                if _bump_lot_bars(lot, day):
                    changed = True
                if _update_lot_peaks(lot, high_px, price):
                    changed = True
            _mirror_hold_from_lots()
            if changed:
                _save_state()
    elif not holding:
        if (
            getattr(A, "hold_peak", None) is not None
            or int(getattr(A, "hold_bars", 0) or 0)
            or getattr(A, "time_force_grace_until", None) is not None
            or bool(getattr(A, "time_force_trend_skip", False))
            or bool(getattr(A, "round_scaled", False))
        ):
            _clear_hold_meta()
    else:
        _bump_hold_bars(day)
        if _update_hold_peak(high_px, cost):
            _save_state()

    stop_hit = False
    trail_hit = False
    time_force_hit = False
    skip_sell_eval = str(getattr(A, "_skip_sell_eval_day", "") or "") == str(day)
    force_empty_act = False if skip_sell_eval else bool(force_empty)
    if skip_sell_eval and holding:
        _log_skip_sell_eval_day(day)
        sell_ok = False
        sell_reasons = ["skip_add_bar"]
        exit_ids = []
        exit_shares = 0
    elif holding and _lots_enabled():
        sell_ok, sell_reasons, exit_ids, exit_shares = _collect_lot_exits(
            price, closes_s, force_empty
        )
        stop_hit = "stop_loss" in sell_reasons
        trail_hit = "trail_stop" in sell_reasons
        time_force_hit = "time_force" in sell_reasons
    else:
        if holding and cost > 0 and price <= cost * (1.0 - float(STOP_LOSS)):
            stop_hit = True
            sell_reasons = list(sell_reasons) + ["stop_loss"]
            sell_ok = True

        if holding and (not stop_hit) and _trail_stop_hit(price, cost):
            trail_hit = True
            sell_reasons = list(sell_reasons) + ["trail_stop"]
            sell_ok = True

        grace_before = getattr(A, "time_force_grace_until", None)
        skip_before = bool(getattr(A, "time_force_trend_skip", False))
        if holding and (not stop_hit) and (not trail_hit) and _time_force_hit(
            price, closes_s, getattr(A, "hold_bars", 0)
        ):
            time_force_hit = True
            sell_reasons = list(sell_reasons) + ["time_force"]
            sell_ok = True
        elif (
            holding
            and (
                (grace_before is None and getattr(A, "time_force_grace_until", None) is not None)
                or ((not skip_before) and bool(getattr(A, "time_force_trend_skip", False)))
            )
        ):
            _save_state()

    ret_pct = None
    if holding and cost > 0:
        ret_pct = (price - cost) / cost

    skip_codes = (
        "chase_skip",
        "w_bias_skip",
        "w_slope_skip",
        "vol_dry_skip",
        "weekly_bear",
    )
    real_buys = [r for r in buy_reasons if r not in skip_codes]
    buy_sig = bool(
        (not weekly_bear)
        and (not w_bias_block)
        and (not w_slope_block)
        and buy_ok
        and real_buys
    )
    vol_dry_block = "vol_dry_skip" in buy_reasons
    scale_push_ok, scale_push_reasons = _eval_scale_push(
        closes_s,
        highs_s,
        lows_s,
        w_detail,
        pullback=("pullback_vol" in real_buys),
    )
    scale_ok, scale_why = _scale_gate(w_detail, price=price)
    scale_sig = bool(
        scale_ok
        and scale_push_ok
        and (not weekly_bear)
        and (not w_bias_block)
        and (not w_slope_block)
        and (not vol_dry_block)
    )

    if not bt:
        _sync_signal_book(
            day,
            now_s,
            buy_sig,
            scale_sig,
            holding,
            sell_ok,
            force_empty_act,
        )

    pe_now = bool(getattr(A, "pending_entry", None))
    px_now = bool(getattr(A, "pending_exit", None))
    # 信号上升沿强制打；实盘其余按 LIVE_HEARTBEAT_SEC；回测 idle 用 status_idle
    force_bar_log = _bar_signal_rising_edge(buy_sig or scale_sig, sell_ok, force_empty)
    status_idle = (bool(holding) or pe_now or px_now) and (not force_bar_log)
    if _should_emit_bar_status(C, now, force_bar_log, status_idle):
        A.ready_logged = True
        if not getattr(A, "is_backtest", False):
            A._bar_status_at = now
        print(
            "%s" % STRATEGY_NAME,
            day,
            hhmm,
            "n1d=%d n1w=%d close=%.4f sig_d=%s sig_w=%s phase=%s prev_d=%s prev_w=%s "
            "w_bull=%s w_bear=%s w_bn=%s/%s w_ma5=%s w_ma30=%s w_hist=%s "
            "buy=%s buyR=%s scale=%s scaleR=%s sell=%s sellR=%s "
            "hold=%s nlot=%s ret=%s pe=%s px=%s bt_held=%s avail=%s "
            "ma=%s stick=%s src=%s"
            % (
                len(closes_s),
                len(closes_ws),
                price,
                sig_day_daily,
                sig_day_weekly,
                phase,
                prev_d,
                prev_w,
                weekly_bull,
                weekly_bear,
                w_bear_n,
                _w_bear_confirm_need(),
                None if w_detail.get("ma5") is None else round(w_detail["ma5"], 4),
                None if w_detail.get("ma30") is None else round(w_detail["ma30"], 4),
                None if w_detail.get("hist") is None else round(w_detail["hist"], 4),
                buy_sig,
                ",".join(buy_reasons) if buy_reasons else "-",
                scale_sig,
                (
                    ",".join(scale_push_reasons)
                    if scale_push_reasons
                    else (scale_why or "-")
                ),
                sell_ok or force_empty_act,
                ",".join((["weekly_bear"] if force_empty else []) + sell_reasons) or "-",
                holding,
                _pos_lots() if holding else 0,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                pe_now,
                px_now,
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
                _ma_kind(),
                (
                    "-"
                    if getattr(A, "stick_std", None) is None
                    else ("%.4f" % float(A.stick_std))
                ),
                str(getattr(A, "stick_src", "") or "-"),
            ),
        )
        _bar_log(
            day=day,
            hhmm=hhmm,
            n1d=len(closes_s),
            n1w=len(closes_ws),
            close=round(price, 6),
            sig_d=sig_day_daily,
            sig_w=sig_day_weekly,
            phase=phase,
            prev_d=prev_d,
            prev_w=prev_w,
            w_bull=weekly_bull,
            w_bear=weekly_bear,
            w_bn=w_bear_n,
            w_bn_need=_w_bear_confirm_need(),
            w_ma5=None if w_detail.get("ma5") is None else round(w_detail["ma5"], 4),
            w_ma30=None if w_detail.get("ma30") is None else round(w_detail["ma30"], 4),
            w_hist=None if w_detail.get("hist") is None else round(w_detail["hist"], 4),
            buy=buy_sig,
            buyR=",".join(buy_reasons) if buy_reasons else "-",
            scale=scale_sig,
            scaleR=(
                ",".join(scale_push_reasons)
                if scale_push_reasons
                else (scale_why or "-")
            ),
            sell=bool(sell_ok or force_empty_act),
            sellR=",".join((["weekly_bear"] if force_empty else []) + sell_reasons) or "-",
            hold=holding,
            nlot=_pos_lots() if holding else 0,
            ret=None if ret_pct is None else round(ret_pct * 100.0, 4),
            pe=pe_now,
            px=px_now,
            ma=_ma_kind(),
            stick_std=(
                None
                if getattr(A, "stick_std", None) is None
                else round(float(A.stick_std), 6)
            ),
            stick_src=str(getattr(A, "stick_src", "") or ""),
        )

    # ---- 先执行挂起的卖/买（尾盘按收盘价；隔夜残留开盘按开盘价）----
    if _try_exec_pending_exit(C, now, now_s, day, tag, open_px, price, holding):
        return
    force_eval = False
    entry_act = _try_exec_pending_entry(
        C,
        now,
        now_s,
        day,
        tag,
        open_px,
        price,
        holding,
        cash,
        weekly_bear,
        w_bias_block,
        w_slope_block,
        vol_dry_block,
        w_detail,
        force_empty,
        sell_ok,
        stop_hit,
        trail_hit,
        time_force_hit,
    )
    if entry_act == "done":
        return
    if entry_act == "force_eval":
        force_eval = True

    # ---- 新信号：回测当根；实盘仅收盘确认或开盘兜底 ----
    allow_new = True
    is_confirm = live_cc and phase == "confirm"
    if live_cc:
        if is_confirm:
            if getattr(A, "_confirmed_eval_day", "") == day:
                allow_new = False
        elif need_fallback:
            allow_new = True
        else:
            allow_new = False
    if not allow_new and not force_eval:
        return

    if holding:
        cur_ex = getattr(A, "pending_exit", None)
        if force_empty_act or sell_ok or stop_hit or trail_hit or time_force_hit:
            if isinstance(cur_ex, dict):
                if live_cc:
                    _mark_signal_eval_done(day, is_confirm)
                return
            if force_empty_act:
                reason = "weekly_bear"
            elif stop_hit:
                reason = "stop_loss"
            elif trail_hit:
                reason = "trail_stop"
            elif time_force_hit:
                reason = "time_force"
            else:
                reason = sell_reasons[0] if sell_reasons else "SELL"
            reasons = (["weekly_bear"] if force_empty_act else []) + list(sell_reasons)
            seen = set()
            uniq = []
            for r in reasons:
                if r not in seen and r != "skip_add_bar":
                    seen.add(r)
                    uniq.append(r)
            # 周线清仓用 sig_w；日线卖点用 sig_d
            exit_sig_day = (
                sig_day_weekly
                if (force_empty_act or reason == "weekly_bear")
                else sig_day_daily
            )
            A.pending_exit = {
                "mode": "day",
                "reason": reason,
                "signal_day": exit_sig_day,
                "signal_tag": tag,
                "close": price,
                "reasons": uniq,
            }
            if _lots_enabled() and exit_ids:
                A.pending_exit["lot_ids"] = list(exit_ids)
                A.pending_exit["shares"] = int(exit_shares)
            A.pending_entry = None
            if live_cc:
                _mark_signal_eval_done(day, is_confirm)
            else:
                _save_state()
            print(
                "%s pending_exit set signal=%s label=%s all=%s lots=%s shares=%s day=%s close=%.4f phase=%s"
                % (
                    STRATEGY_NAME,
                    reason,
                    _reason_label(reason, "sell"),
                    _format_reasons(uniq, "sell"),
                    exit_ids or "-",
                    exit_shares or _pos_shares(),
                    exit_sig_day,
                    price,
                    phase,
                )
            )
            _event_log(
                "pending_exit_set",
                signal=reason,
                label=_reason_label(reason, "sell"),
                all_reasons=_format_reasons(uniq, "sell"),
                signal_day=exit_sig_day,
                close=price,
                phase=phase,
                lot_ids=exit_ids or None,
                shares=exit_shares or None,
            )
            _try_exec_pending_exit(C, now, now_s, day, tag, open_px, price, holding)
        elif scale_sig:
            if isinstance(getattr(A, "pending_entry", None), dict):
                if live_cc:
                    _mark_signal_eval_done(day, is_confirm)
                return
            A.pending_entry = {
                "signal_day": sig_day_daily,
                "signal_tag": tag,
                "close": price,
                "reasons": list(scale_push_reasons),
                "add": True,
            }
            A.pending_exit = None
            if live_cc:
                _mark_signal_eval_done(day, is_confirm)
            else:
                _save_state()
            primary = scale_push_reasons[0] if scale_push_reasons else "entry"
            print(
                "%s pending_entry set add signal=%s label=%s all=%s day=%s close=%.4f lots=%s phase=%s"
                % (
                    STRATEGY_NAME,
                    primary,
                    _reason_label(primary, "buy"),
                    _format_reasons(scale_push_reasons, "buy"),
                    sig_day_daily,
                    price,
                    _pos_lots(),
                    phase,
                )
            )
            _event_log(
                "pending_entry_set",
                signal=primary,
                label=_reason_label(primary, "buy"),
                all_reasons=_format_reasons(scale_push_reasons, "buy"),
                signal_day=sig_day_daily,
                close=price,
                phase=phase,
                add=True,
            )
            _try_exec_pending_entry(
                C,
                now,
                now_s,
                day,
                tag,
                open_px,
                price,
                holding,
                cash,
                weekly_bear,
                w_bias_block,
                w_slope_block,
                vol_dry_block,
                w_detail,
                force_empty,
                sell_ok,
                stop_hit,
                trail_hit,
                time_force_hit,
            )
        elif live_cc:
            _mark_signal_eval_done(day, is_confirm)
        return

    if buy_sig and ("BUY" not in getattr(A, "acted", set())):
        if isinstance(getattr(A, "pending_entry", None), dict):
            if live_cc:
                _mark_signal_eval_done(day, is_confirm)
            return
        A.pending_entry = {
            "signal_day": sig_day_daily,
            "signal_tag": tag,
            "close": price,
            "reasons": list(real_buys),
        }
        A.pending_exit = None
        if live_cc:
            _mark_signal_eval_done(day, is_confirm)
        else:
            _save_state()
        primary = real_buys[0] if real_buys else "entry"
        print(
            "%s pending_entry set signal=%s label=%s all=%s day=%s close=%.4f phase=%s"
            % (
                STRATEGY_NAME,
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(real_buys, "buy"),
                sig_day_daily,
                price,
                phase,
            )
        )
        _event_log(
            "pending_entry_set",
            signal=primary,
            label=_reason_label(primary, "buy"),
            all_reasons=_format_reasons(real_buys, "buy"),
            signal_day=sig_day_daily,
            close=price,
            phase=phase,
        )
        _try_exec_pending_entry(
            C,
            now,
            now_s,
            day,
            tag,
            open_px,
            price,
            holding,
            cash,
            weekly_bear,
            w_bias_block,
            w_slope_block,
            vol_dry_block,
            w_detail,
            force_empty,
            sell_ok,
            stop_hit,
            trail_hit,
            time_force_hit,
        )
    elif live_cc:
        _mark_signal_eval_done(day, is_confirm)

# === hlband/runtime.py ===
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


def _init_impl(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C, default="1d")
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
            _download_hist(A.stock, "1w")
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, A.period, "+1w")

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
            A.hold_bars = 0
            A._hold_count_day = ""
            A.time_force_grace_until = None
            A.time_force_trend_skip = False
            A.lots = []
            A.round_scaled = False
            A._confirmed_eval_day = ""
            A._fallback_done_day = ""
            A._w_bear_streak = 0
            A._w_bear_last_day = ""
            A._skip_sell_eval_day = ""
            A._last_add_day = ""
            A._last_add_signal = ""
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
            if not hasattr(A, "hold_bars"):
                A.hold_bars = 0
            if not hasattr(A, "_hold_count_day"):
                A._hold_count_day = ""
            if not hasattr(A, "time_force_grace_until"):
                A.time_force_grace_until = None
            if not hasattr(A, "time_force_trend_skip"):
                A.time_force_trend_skip = False
            if not hasattr(A, "lots") or A.lots is None:
                A.lots = []
            if not hasattr(A, "round_scaled"):
                A.round_scaled = False
            if not hasattr(A, "_confirmed_eval_day"):
                A._confirmed_eval_day = ""
            if not hasattr(A, "_fallback_done_day"):
                A._fallback_done_day = ""
            if not hasattr(A, "_w_bear_streak"):
                A._w_bear_streak = 0
            if not hasattr(A, "_w_bear_last_day"):
                A._w_bear_last_day = ""
            if not hasattr(A, "_skip_sell_eval_day"):
                A._skip_sell_eval_day = ""
            if not hasattr(A, "_last_add_day"):
                A._last_add_day = ""
            if not hasattr(A, "_last_add_signal"):
                A._last_add_signal = ""
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
        if not hasattr(A, "hold_bars"):
            A.hold_bars = 0
        if not hasattr(A, "_hold_count_day"):
            A._hold_count_day = ""
        if not hasattr(A, "time_force_grace_until"):
            A.time_force_grace_until = None
        if not hasattr(A, "time_force_trend_skip"):
            A.time_force_trend_skip = False
        if not hasattr(A, "lots") or A.lots is None:
            A.lots = []
        if not hasattr(A, "round_scaled"):
            A.round_scaled = False
        if not hasattr(A, "_confirmed_eval_day"):
            A._confirmed_eval_day = ""
        if not hasattr(A, "_fallback_done_day"):
            A._fallback_done_day = ""
        if not hasattr(A, "_w_bear_streak"):
            A._w_bear_streak = 0
        if not hasattr(A, "_w_bear_last_day"):
            A._w_bear_last_day = ""
        if not hasattr(A, "_skip_sell_eval_day"):
            A._skip_sell_eval_day = ""
        if not hasattr(A, "_last_add_day"):
            A._last_add_day = ""
        if not hasattr(A, "_last_add_signal"):
            A._last_add_signal = ""
        if not hasattr(A, "ma_kind"):
            A.ma_kind = ""
        if not hasattr(A, "stick_std"):
            A.stick_std = None
        if not hasattr(A, "stick_day"):
            A.stick_day = ""
        if not hasattr(A, "stick_src"):
            A.stick_src = ""

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
        _trade_budget_cap(),
        "dynamic_budget=",
        DYNAMIC_BUDGET,
        "BOOK_N=",
        _cfg_book_n(),
        "book_stocks=",
        ",".join(sorted(_book_stock_set())) or "-",
        "cash_ratio=",
        CASH_RATIO,
        "min_lot=",
        MIN_LOT,
        "max_name_frac=",
        MAX_NAME_FRAC,
        "equal_split=",
        EQUAL_SPLIT,
        "book_freeze=",
        "%s/%s" % (BOOK_FREEZE_CLOSE, BOOK_FREEZE_OPEN),
        "wMA=",
        "%d/%d/%d" % (W_MA_FAST, W_MA_MID, W_MA_LIFE),
        "dMA=",
        "%d/%d" % (D_MA_MID, D_MA_SLOW),
        "ma_type=",
        _ma_kind(),
        "stick_adapt=",
        bool(globals().get("MA_STICK_ADAPT", True)),
        "stick_thr=",
        float(globals().get("STICK_STD_THR", 0.025) or 0.025),
        "stop=",
        STOP_LOSS,
        "chase<",
        CHASE_MAX_PCT,
        "scale=",
        SCALE_ENABLE,
        "scale_lots=",
        SCALE_LOTS,
        "scale_once=",
        SCALE_ONCE_PER_ROUND,
        "scale_arm=",
        SCALE_ARM,
        "scale_arm_bars=",
        SCALE_ARM_BARS,
        "scale_plat=",
        "%d/%.2f" % (SCALE_PLAT_LOOKBACK, SCALE_PLAT_MAX_RANGE),
        "scale_w_expand=",
        SCALE_W_HIST_EXPAND_RATIO,
        "time_force_bars=",
        TIME_FORCE_BARS,
        "time_force_min_ret=",
        TIME_FORCE_MIN_RET,
        "close_exec=",
        "%s-%s" % (
            globals().get("PENDING_EXEC_START", "145600"),
            globals().get("PENDING_EXEC_END", "145700"),
        ),
        "open_exec=",
        "%s-%s" % (
            globals().get("OPEN_EXEC_START", "093000"),
            globals().get("OPEN_EXEC_END", "094500"),
        ),
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        scale=SCALE_ENABLE,
        scale_lots=SCALE_LOTS,
        scale_once=SCALE_ONCE_PER_ROUND,
        scale_arm=SCALE_ARM,
        scale_arm_bars=SCALE_ARM_BARS,
        scale_w_hist_min=SCALE_W_HIST_MIN,
        scale_plat_lookback=SCALE_PLAT_LOOKBACK,
        scale_plat_max_range=SCALE_PLAT_MAX_RANGE,
        scale_w_hist_expand=SCALE_W_HIST_EXPAND_RATIO,
        time_force_bars=TIME_FORCE_BARS,
        time_force_min_ret=TIME_FORCE_MIN_RET,
        close_exec="%s-%s"
        % (
            globals().get("PENDING_EXEC_START", "145600"),
            globals().get("PENDING_EXEC_END", "145700"),
        ),
        open_exec="%s-%s"
        % (
            globals().get("OPEN_EXEC_START", "093000"),
            globals().get("OPEN_EXEC_END", "094500"),
        ),
        budget=_trade_budget_cap(),
        dynamic_budget=DYNAMIC_BUDGET,
        book_n=_cfg_book_n(),
        book_stocks=len(_book_stock_set()),
        cash_ratio=CASH_RATIO,
        min_lot=MIN_LOT,
        max_name_frac=MAX_NAME_FRAC,
        equal_split=EQUAL_SPLIT,
        ma_type=_ma_kind(),
        stick_adapt=bool(globals().get("MA_STICK_ADAPT", True)),
        stick_thr=float(globals().get("STICK_STD_THR", 0.025) or 0.025),
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
