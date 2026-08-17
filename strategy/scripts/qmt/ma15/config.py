# === ma15/config.py ===
# True=只打日志不下单；回测/实盘真下单前务必确认
DRY_RUN = False

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 只交易此代码（主图须为 513530.SH）
TRADE_CODE = "513530"

# ETF T+0：回测不锁当日买入；实盘可卖以券商为准
ALLOW_T0 = True

TRADE_BUDGET = 50000.0
TRADE_BUDGET_BY_STOCK = {}
CASH_RATIO = 0.8

# ---- 15m / 1h 均线 ----
MA_FAST = 20
MA_SLOW = 60
H_MA_FAST = 20
H_MA_SLOW = 60
VOL_MA_N = 20

# 触线 / 未有效跌破（0.4%：ETF 1 跳约 0.001，0.2% 经常够不着）
MA_TOUCH_TOL = 0.004
MA_BREAK_TOL = 0.002

# 缩量：只比 20 均量（不再 AND 前波上涨量，否则多头里经常 vol_skip）
VOL_PULLBACK_RATIO = 0.85
VOL_UP_LOOKBACK = 8
VOL_UP_RATIO = 0.70

# 锤子：下影相对实体、实体占振幅上限
HAMMER_LOWER_MULT = 1.5
HAMMER_BODY_MAX = 0.50

# 大盘 15m 放量杀跌
INDEX_CODE = "000001.SH"
INDEX_DUMP_RET = -0.004
INDEX_DUMP_VOL = 1.5

# 卖出
STOP_MA_PCT = 0.008
STOP_MA_AFTER_HHMM = "1015"  # 早盘第一根不按隔夜缺口打 MA 止损
STOP_LOSS = 0.02
STALL_BARS = 16              # 约 1 个交易日；6 根=1.5h 会把回踩本身当成衰竭
STALL_BAND = 0.005
STALL_MA_FLAT = 0.002
STALL_ABORT_RET = 0.005      # 持仓期曾有 >=0.5% 浮盈则不再用 stall 砍
TREND_BREAK_ABORT_RET = 0.001  # 曾有 >=0.1% 浮盈则不用 trend_break（避免砍 7/16 这类回撤后再止盈）
TREND_BREAK_MIN_RET = -0.004   # 当前浮亏至少 0.4%，避免 4/17 那种 -0.06% 噪声
# 硬止盈：浮盈达标且离开 MA20。默认开（v1.0 关掉会少赚）
TAKE_PROFIT_HARD = True
TAKE_PROFIT = 0.015          # 回吐启动阈值（收盘最高浮盈）
TAKE_LEAVE = 0.008           # 仅 TAKE_PROFIT_HARD=True 时用
GIVEBACK = 0.008             # 启动后相对收盘最高回吐；硬止盈打开时作辅层
GIVEBACK_TIGHT = 0.008       # 最高浮盈达到 GIVEBACK_TIGHT_AFTER 后收紧
GIVEBACK_TIGHT_AFTER = 0.04

# 盈利后加仓：浮盈达到 SCALE_ARM 后，下一笔回踩信号加第二笔（仍 1*TRADE_BUDGET）
# 等加仓期间硬止盈让路（趋势仍在且未超过 SCALE_GIVEUP_BARS）；账户需能再拿出一笔预算
# SCALE_LOTS=True：每笔独立成本/峰值/止盈（多仓）；False：均价合并后整仓出（v1.2）
# SCALE_RESET_PEAK 仅合并模式有效；多仓不继承、不重置
SCALE_ENABLE = True
SCALE_MAX = 2
SCALE_ARM = 0.015
SCALE_GIVEUP_BARS = 80
SCALE_LOTS = True
SCALE_RESET_PEAK = True

# 允许开仓的 15m 结束时刻 HHmm。
# 不含 1400/1415：次根 1415/1430 成交，T+0 来不及当日止损，隔夜缺口（v0.3 的 1430 同因）
ENTRY_HHMM_ALLOW = (
    "1000", "1015", "1030", "1045", "1100", "1115", "1130",
    "1315", "1330", "1345",
)
# 这些结束时刻的 15m 不开新买（已挂 pending 也作废）
ENTRY_FILL_BAN = ("1415", "1430", "1445", "1500")

PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_allow_t0", "ALLOW_T0", "bool"),
    ("panel_ma_touch", "MA_TOUCH_TOL", "float"),
    ("panel_ma_break", "MA_BREAK_TOL", "float"),
    ("panel_vol_ratio", "VOL_PULLBACK_RATIO", "float"),
    ("panel_stop_ma", "STOP_MA_PCT", "float"),
    ("panel_stop_loss", "STOP_LOSS", "float"),
    ("panel_hard_tp", "TAKE_PROFIT_HARD", "bool"),
    ("panel_take_profit", "TAKE_PROFIT", "float"),
    ("panel_giveback", "GIVEBACK", "float"),
    ("panel_stall_bars", "STALL_BARS", "int"),
    ("panel_stall_abort", "STALL_ABORT_RET", "float"),
    ("panel_scale", "SCALE_ENABLE", "bool"),
    ("panel_scale_lots", "SCALE_LOTS", "bool"),
)

PERIOD = "15m"
OHLC_COUNT = 400
HOUR_OHLC_COUNT = 240
INDEX_OHLC_COUNT = 120

LIVE_ONLY_LAST_BAR = True
DECISION_START = "093000"
DECISION_END = "150000"
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 400
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

STATE_FILE = r"D:\tradingStrategy\ma15_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "Ma15"
STRATEGY_VER = "v1.4"

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
