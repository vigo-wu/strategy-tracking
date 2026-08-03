# === hwr/config.py ===
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


