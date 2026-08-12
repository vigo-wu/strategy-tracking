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
HALT_BASE_PRICE = 130.0       # 开盘集合上限 / 30% 临停基准
MORNING_BUY_PRICE = 130.0
CAGE_RATIO = 1.1              # 有效申报上沿比例
REOPEN_CAP_PRICE = 143.0      # 130 * 1.1；临停复牌首档参考
LIMIT_UP_PRICE = 157.30       # 首日涨幅 57.3%
LIMIT_DOWN_PRICE = 56.70
PRICE_DECIMALS = 3
CHASE_MIN_STEP = 0.01         # 沪市撤补最小价差

# ---- 模式开关（仅买入）----
ENABLE_MODE_A = True          # 早盘 130 抢筹
ENABLE_MODE_B = True          # 早盘失败 → 尾盘抢筹

# ---- 时窗（HHmmss）----
# 深市 Mode A：前夜清算窗 + 首日开盘前
SZ_AM_EVE_START = "193000"
SZ_AM_EVE_END = "203000"
SZ_AM_BUY_START = "000000"
SZ_AM_BUY_END = "092459"
# 沪市 Mode A：抢时间优先 → 09:15 起尽早挂 130
SH_AM_BUY_START = "091500"
SH_AM_BUY_END = "092459"
AM_CANCEL_AFTER = "092501"    # 开盘集合结束后再撤未成早盘单
# 早盘撤单请求后超过该秒数仍未清 pending → 强清影子，放行 Mode B
AM_CANCEL_STUCK_SEC = 30.0

# 深市 Mode B：
#   临停预挂 143（09:30 起，吃上午时间优先）→ 14:55-14:56 必须撤掉
#   14:57 后：等复牌 last 就绪再按笼子顶挂；到点强制挂一笔
SZ_PREPLACE_START = "093000"
SZ_PREPLACE_END = "145459"
SZ_ESCALATE_CANCEL_START = "145500"
SZ_ESCALATE_CANCEL_END = "145659"
SZ_CLOSE_BUY_START = "145701"
SZ_CLOSE_BUY_END = "145950"
# last >= 该价视为复牌已刷新（默认=REOPEN_CAP，笼子已能顶到 157.30）
SZ_CLOSE_READY_LAST = 143.0
# 仍未就绪则强制按当前笼子挂（保底抢筹）
SZ_CLOSE_FORCE_AT = "145745"
SZ_ESCALATE_ALERT_SEC = 2.0

# 沪市 Mode B / 追单（连续匹配可撤）
SH_CHASE_START = "145700"
SH_CHASE_END = "145955"
SH_CHASE_INTERVAL_MS = 50

# pending：排队/追单/收盘集合意图不短超时自动撤
PENDING_TIMEOUT_EXEMPT_INTENTS = (
    "SZ_AM",
    "SH_AM",
    "SZ_PREPLACE",
    "SZ_CLOSE",
    "SH_OPEN",
    "SH_CHASE",
)
PENDING_TIMEOUT_EXEMPT_LOG_SEC = 300
PENDING_TIMEOUT_SEC = 90
PENDING_ORPHAN_SEC = 15
CANCEL_RETRY_SEC = 1.0

# ---- 上市首日门闩 ----
# 实盘务必填写 LISTING_DATE_MAP，否则深市隔夜单/首日门闩可能 fail-closed
LISTING_DAY_ONLY = True
LISTING_DAY_FAIL_OPEN = False
LISTING_DATE_MAP = {
    "118073.SH": "20260812",
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

# ---- 实盘定时器（竞价/临停准点；回测无效）----
# True=init 注册 run_time；与分笔 handlebar 双驱动，busy 防重入
ENABLE_LIVE_TIMER = True
LIVE_TIMER_MS = 50                  # 09:15 抢先；建议 50–100
TIMER_QUICK_TRADE = 2               # 定时器内 passorder 立即报单
TICK_QUICK_TRADE = 1                # 分笔 handlebar 内报单
# 日志墙钟节流（定时器 50ms 下禁用 barpos%N 抽样）
LOG_STATUS_SEC = 10.0               # 状态行 / bars.jsonl / 非上市日 skip
LOG_WAIT_SEC = 5.0                  # 撤单等待 / 收盘就绪等待等

STATE_FILE = r"D:\tradingStrategy\pbs_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "PbsRush"
STRATEGY_VER = "v1.10"

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
