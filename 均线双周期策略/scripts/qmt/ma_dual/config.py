# === ma_dual/config.py ===
# ===================== 用户配置 =====================
DRY_RUN = True

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

TRADE_BUDGET = 50000.0
CASH_RATIO = 0.15

# 日线方向
D_MA_FAST = 20
D_MA_SLOW = 60

# 1小时买点
H_MA_FAST = 5
H_MA_MID = 10
H_MA_SLOW = 120
MA120_TOL = 0.02  # 收盘不低于 MA120 下方 2%

# 卖出
STOP_LOSS = 0.03  # 相对成本 -3%
USE_SWING_STOP = True
SWING_N = 20  # 近期波段低点窗口(1h)

# 主图 1小时
PERIOD = "1h"
# 1h 约 4 根/日; MA120 + 缓冲
OHLC_COUNT = 200
DAILY_OHLC_COUNT = 120

LIVE_ONLY_LAST_BAR = True
DECISION_START = "093000"
DECISION_END = "150000"
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 500
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__; 状态绝对路径
STATE_FILE = r"D:\service\GJQMT\python\ma_dual_qmt_state.json"

STRATEGY_NAME = "MaDual"
STRATEGY_VER = "v1.0"
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)


