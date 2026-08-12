# === pbs/config.py ===
# ===================== 用户配置 =====================
DRY_RUN = False

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

TRADE_BUDGET = 10000.0
CASH_RATIO = 0.8
LOT_SIZE = 10  # 可转债：10 张 = 一手

# ---- 价格锚点（发行价=100，见 model.md / docs）----
ISSUE_PRICE = 100.0
HALT_BASE_PRICE = 130.0       # 30% 临停基准（人工开盘参考）
CAGE_RATIO = 1.1              # 状态日志笼子参考
REOPEN_CAP_PRICE = 143.0      # 130 * 1.1；状态日志参考
LIMIT_UP_PRICE = 157.30       # 首日涨幅 57.3% / 收盘申报价
LIMIT_DOWN_PRICE = 56.70
PRICE_DECIMALS = 3

# ---- 模式开关（仅买入）----
# 开盘/隔夜 130 由人工委托；本策略只跑尾盘 Mode B
ENABLE_MODE_B = True

# ---- 时窗（HHmmss）----
# 14:56 预热手数；14:57 起顶格申报（准点 run_time + 50ms 轮询）
CLOSE_PREWARM_START = "145600"
CLOSE_BUY_START = "145700"
CLOSE_BUY_END = "145955"
CLOSE_PREWARM_TIMER = "2020-01-01 14:56:00"
CLOSE_FIRE_TIMER = "2020-01-01 14:57:00"
# None = 用 LIMIT_UP_PRICE
CLOSE_BUY_PRICE = None

# pending：收盘申报意图不短超时自动撤
PENDING_TIMEOUT_EXEMPT_INTENTS = (
    "SZ_CLOSE",
    "SH_CLOSE",
)
PENDING_TIMEOUT_EXEMPT_LOG_SEC = 300
PENDING_TIMEOUT_SEC = 90
PENDING_ORPHAN_SEC = 15
CANCEL_RETRY_SEC = 1.0
# 抢筹：见单前不查成交；影子只看委托；见单后降频轮询
PENDING_ACK_ORDER_ONLY = True
PENDING_SHADOW_ORDER_ONLY = True
PENDING_AFTER_ACK_POLL_SEC = 5.0
# 简化影子：超时未见单 → 查委托确认 → 冷却后重挂
PENDING_SHADOW_CLEAR_SEC = 5.0
PENDING_SHADOW_CLEAR_HITS = 1
PENDING_SHADOW_CLEAR_HIT_GAP_MS = 0.0
PENDING_SHADOW_REORDER_COOLDOWN_MS = 2000.0
PENDING_SHADOW_CLEAR_INTENTS = (
    "SZ_CLOSE",
    "SH_CLOSE",
)
# pending_check 日志节流（显式配置才生效；查单仍按上面节奏）
PENDING_CHECK_LOG_SEC = 5.0

# ---- 上市首日门闩 ----
# 实盘务必填写 LISTING_DATE_MAP，否则首日门闩可能 fail-closed
LISTING_DAY_ONLY = True
LISTING_DAY_FAIL_OPEN = False
LISTING_DATE_MAP = {
    "110103.SH": "20260813",
}

# ---- 行情与运行 ----
# 实盘/回测统一：主图挂「分笔/tick」
PERIOD = "tick"
OHLC_COUNT = 300
LIVE_ONLY_LAST_BAR = False
LIVE_HEARTBEAT_SEC = 60
HIST_MAX_LOOKBACK_DAYS = 5
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True
TICK_ALLOW_1M_FALLBACK = False

# ---- 实盘定时器（收盘申报准点；回测无效）----
# True=init 注册 run_time；与分笔 handlebar 双驱动，busy 防重入
ENABLE_LIVE_TIMER = True
LIVE_TIMER_MS = 50                  # 收盘重试；建议 50–100
TIMER_QUICK_TRADE = 2               # 定时器内 passorder 立即报单
TICK_QUICK_TRADE = 1                # 分笔 handlebar 内报单
# 日志墙钟节流（定时器 50ms 下禁用 barpos%N 抽样）
# 14:57 前默认静默（无状态行/心跳/skip 刷屏）；收盘窗内才按下列间隔打日志
LOG_STATUS_SEC = 10.0               # 收盘窗内：状态行 / bars.jsonl
LOG_WAIT_SEC = 5.0                  # 收盘窗内：申报重试 / buy_skip / passorder_fail 节流

STATE_FILE = r"D:\tradingStrategy\pbs_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "PbsRush"
STRATEGY_VER = "v1.19"

DRY_RUN_FILL_IMMEDIATE = False
DRY_RUN_FILL_ON_LIMIT = True
DRY_RUN_VIRTUAL_CASH = True
DRY_RUN_VIRTUAL_CASH_AMT = 100000.0
DRY_RUN_SAVE_STATE = False
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "tick",
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
