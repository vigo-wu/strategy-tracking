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
