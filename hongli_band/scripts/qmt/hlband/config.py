# === hlband/config.py ===
# ===================== 用户配置 =====================
DRY_RUN = True

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

TRADE_BUDGET = 50000.0
CASH_RATIO = 0.15

# ---- 周线方向 ----
W_MA_FAST = 5
W_MA_MID = 10
W_MA_LIFE = 30
W_MA_SLOW = 60
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ---- 日线买卖 ----
D_MA_FAST = 5
D_MA_MID = 20
D_MA_SLOW = 60
KDJ_N = 9
KDJ_M1 = 3
KDJ_M2 = 3

# 缩量回踩：价距均线容差、量相对 20 日均量
MA_TOUCH_TOL = 0.025
VOL_SHRINK_RATIO = 0.65
VOL_MA_N = 20

# 卖点：5 日乖离率(%)、放量倍数、新高窗口、上影/十字星
BIAS5_SELL = 6.0
VOL_SPIKE_RATIO = 1.8
HIGH_LOOKBACK = 20
UPPER_SHADOW_RATIO = 0.45
DOJI_BODY_RATIO = 0.12

# 风控：当日涨幅过大不追
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
STRATEGY_VER = "v1.2"
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
