# === hlband/config.py ===
# ===================== 用户配置 =====================
DRY_RUN = True

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

TRADE_BUDGET = 50000.0
CASH_RATIO = 0.15

# ---- 周线过滤 ----
W_MA_FAST = 5
W_MA_MID = 10
W_MA_LIFE = 30
W_MA_SLOW = 60
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
# 周线 (MA5-MA30)/MA30 >= 此值禁开
W_BIAS_HARD = 0.08

# ---- 日线买卖 ----
D_MA_FAST = 5
D_MA_MID = 20
D_MA_SLOW = 60
KDJ_N = 9
KDJ_M1 = 3
KDJ_M2 = 3

# 买①：回踩 MA20/MA60 容差；量 < 10 日均量 * 0.9
MA_TOUCH_TOL = 0.025
VOL_PULLBACK_N = 10
VOL_PULLBACK_RATIO = 0.9
# 买② 反面：跌破 MA20 且量 < 20 日均量 * 0.7 → 禁开
VOL_DRY_N = 20
VOL_DRY_RATIO = 0.70

# 卖① BIAS5(%)；卖② 移动止盈；卖③ 时间成本
BIAS5_SELL = 6.0
TRAIL_ACTIVATE = 0.03
TRAIL_GIVEBACK = 0.015
TIME_FLAT_BARS = 15
TIME_FLAT_BAND = 0.01

# 兜底：追高过滤、硬止损、周线空头强平
CHASE_MAX_PCT = 0.05
STOP_LOSS = 0.08

# 主图日线；周线跨周期拉取
PERIOD = "1d"
OHLC_COUNT = 180
WEEKLY_OHLC_COUNT = 120

LIVE_ONLY_LAST_BAR = True
DECISION_START = "093000"
DECISION_END = "150000"
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 800
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__；状态绝对路径
STATE_FILE = r"D:\service\GJQMT\python\hlband_qmt_state.json"

STRATEGY_NAME = "HlBand"
STRATEGY_VER = "v1.5"
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
