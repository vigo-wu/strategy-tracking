# === band35/config.py ===
# ===================== 用户配置 =====================
DRY_RUN = True

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 单笔买入预算（元）；全仓卖出
TRADE_BUDGET = 50000.0

# KDJ(9,3,3) 与日线均线
KDJ_N = 9
KDJ_M1 = 3
KDJ_M2 = 3
DAILY_MA_N = 10
DAILY_MA_COUNT = 40

# 买入阈值 (15M 版)
BUY_K_MAX = 20.0
BUY_D_MAX = 20.0
BUY_TIME_START = "1430"  # 含: 14:30 <= t
BUY_TIME_END = "1500"    # 不含: t < 15:00

# 卖出阈值
SELL_K_MIN = 85.0
STOP_LOSS = 0.04              # 成本 * (1 - 0.04)
TAKE_PROFIT = 0.12            # 成本 * (1 + 0.12)
DAILY_BREAK_RATIO = 0.99      # 15M 收盘 < MA10 * 0.99
MAX_HOLD_DAYS = 4             # 当前交易日 - 买入日 >= 4

# 固定 15m；也可 "follow" 跟随主图
PERIOD = "15m"
# 15m 约 16 根/日；480 ≈ 30 个交易日，保证 KDJ 暖机
OHLC_COUNT = 480

# 实盘: 仅最新 K 决策
LIVE_ONLY_LAST_BAR = True
DECISION_START = "093000"
DECISION_END = "150000"
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 360
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__；状态绝对路径
STATE_FILE = r"D:\service\GJQMT\python\band35_qmt_state.json"

STRATEGY_NAME = "Band35"
STRATEGY_VER = "v1.3"
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
