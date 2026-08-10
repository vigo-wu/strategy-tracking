# === cbauct/config.py ===
# ===================== 用户配置 =====================
# True=只打日志不下单；实盘前确认账号与主图后再改 False
DRY_RUN = True

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 单笔买入资金上限（元）；可转债一手=10张，建议 >= 20000
TRADE_BUDGET = 50000.0
CASH_RATIO = 0.8
# 可转债最小交易单位（张）
LOT_SIZE = 10

# ---- 上市首日价格锚点（model.md）----
# 临停基准价 / 模式A 早盘顶格买价（触及 30% 停牌）
HALT_BASE_PRICE = 130.0
MORNING_BUY_PRICE = 130.0
# 价格笼子比例（有效申报上限 = 基准/最新价 * CAGE_RATIO）
CAGE_RATIO = 1.1
# 复牌首段顶格 = 130 * 1.1（严禁深市临停期硬编码 157.30）
REOPEN_CAP_PRICE = 143.0
# 全天最高限价 / 模式A 复牌卖出价
LIMIT_UP_PRICE = 157.30
# 可转债价格小数位
PRICE_DECIMALS = 3
# 沪市追单：新上限至少高出旧挂单价这么多才撤补
CHASE_MIN_STEP = 0.01

# ---- 模式开关（model.md：A 日内动量 / B 尾盘隔夜 / 次日出局）----
ENABLE_MODE_A = True   # 09:25 前 130 抢筹 → 14:57 后封板卖 157.30
ENABLE_MODE_B = True   # 早盘失败则尾盘 143→157.30 备用买入
ENABLE_DAY2_EXIT = True

# ---- 时窗（HHmmss；实盘墙钟，回测用 K 线时间）----
# 模式A 深市：隔夜委托优先；上市日前夜清算后 + 首日 09:25 前均可挂 130
SZ_AM_EVE_START = "203000"
SZ_AM_EVE_END = "223000"
SZ_AM_BUY_START = "000000"
SZ_AM_BUY_END = "092459"
# 模式A 沪市：临停托管不接受申报，卡点 09:24:59.850–09:24:59.950（毫秒）
SH_AM_BUY_MS_START = 850
SH_AM_BUY_MS_END = 950
# 回测 1m 分辨率：用秒级窗近似卡点（实盘仍走毫秒窗）
SH_AM_BUY_START = "092459"
SH_AM_BUY_END = "092459"
# VERIFY_AUCTION_ANY_DAY：开盘竞价放宽窗（1m/联调够得着；首日实盘仍用上方卡点）
SH_AM_BUY_START_VERIFY = "091500"
SH_AM_BUY_END_VERIFY = "092459"
# 未成交早盘单：过此时点后撤掉，腾出 Mode B
AM_CANCEL_AFTER = "092500"

# 模式A 复牌卖出（两市 14:57 起；深市不可撤时段慎挂）
SELL_START = "145700"
SELL_END = "145955"

# 模式B 深市：临停期内均可埋 143（须在 14:55 前完成）
SZ_PREPLACE_START = "130000"
SZ_PREPLACE_END = "145459"
# 模式B 深市：封板后撤 143→挂 157.30
SZ_CLOSE_BUY_START = "145700"
SZ_CLOSE_BUY_END = "145950"
SZ_ESCALATE_ALERT_SEC = 2.0
# 模式B 沪市：14:57 起连续竞价阶梯追单
SH_CHASE_START = "145700"
SH_CHASE_END = "145955"
# 沪市追单节流（毫秒）；model 建议 50–100ms
SH_CHASE_INTERVAL_MS = 50
SH_CHASE_MODE = "cancel_replace"

# 次日（模式B 隔夜仓）出局
D2_AUCTION_START = "091500"
D2_AUCTION_END = "092459"
# 集合竞价高开达到该比例则锁利卖出（相对成本价）
D2_GAP_UP_MIN = 0.05
D2_TRAIL_START = "093000"
D2_TRAIL_END = "093500"
# 自次日开盘后最高点回撤超过该比例 → 市价清仓
D2_TRAIL_DRAWDOWN = 0.015
# 次日开盘相对成本低开超过该比例 → 09:30 止损（无正股映射时用转债自身）
D2_GAP_DOWN_STOP = -0.02
# 可选正股映射：{"123276.SZ": "000001.SZ"}；有则优先看正股开盘
UNDERLYING_MAP = {}

CANCEL_RETRY_SEC = 1.0
PENDING_ORPHAN_SEC = 15
# 排队/追单意图禁止按短超时自动撤
PENDING_TIMEOUT_EXEMPT_INTENTS = (
    "SZ_AM",
    "SH_AM",
    "SZ_PREPLACE",
    "SH_OPEN",
    "SH_CHASE",
    "SZ_SELL",
    "SH_SELL",
    "SH_SELL_CHASE",
)
PENDING_TIMEOUT_EXEMPT_LOG_SEC = 300

# ---- 上市首日门闩 ----
# True=仅上市首日跑买卖；非首日只心跳
LISTING_DAY_ONLY = True
# True=任意交易日验竞价流程（开盘 ModeA + 尾盘 ModeB）；非首日无真实微观结构，只验时窗/下单
# DRY 下开盘 130 会模拟成交以便串起 ModeA 卖出；实盘务必 False
VERIFY_AUCTION_ANY_DAY = False
# 兼容旧名：等同 VERIFY_AUCTION_ANY_DAY（联调）
FORCE_RUN = False
# 日K推断失败时：False=禁止下单(fail-closed)；True=放行(fail-open)
LISTING_DAY_FAIL_OPEN = False
# 可选显式上市日 YYYYMMDD；有则优先于日K推断
LISTING_DATE_MAP = {
    # "123276.SZ": "20260810",
    "118073.SH": "20260812",
}

# 发行规模仅作日志参考（本策略买入不依赖规模）
ISSUE_SIZE_YI = 0.0
SMALL_SIZE_YI = 5.0
ISSUE_SIZE_MAP = {
    "118063.SH": 16.72,
    "111024.SH": 5.80,
    "123264.SZ": 8.00,
    "118064.SH": 6.95,
    "123265.SZ": 4.50,
    "127112.SZ": 17.34,
    "110100.SH": 10.00,
    "118065.SH": 19.01,
    "113700.SH": 8.01,
    "118066.SH": 5.76,
    "113701.SH": 4.00,
    "127113.SZ": 7.59,
    "123266.SZ": 3.75,
    "118067.SH": 3.25,
    "123268.SZ": 4.69,
    "113702.SH": 15.00,
    "123269.SZ": 9.80,
    "123267.SZ": 7.50,
    "123270.SZ": 4.05,
    "123271.SZ": 5.22,
    "118068.SH": 9.08,
    "123272.SZ": 10.39,
    "123273.SZ": 2.90,
    "113704.SH": 21.79,
    "113703.SH": 13.01,
    "118069.SH": 2.67,
    "113705.SH": 18.00,
    "113706.SH": 9.70,
    "118070.SH": 15.87,
    "123274.SZ": 6.30,
    "127114.SZ": 33.00,
    "110101.SH": 35.00,
    "118072.SH": 9.30,
    "118071.SH": 7.49,
    "111025.SH": 25.00,
    "123275.SZ": 5.90,
    "113707.SH": 14.91,
    "123276.SZ": 3.00,
    "110102.SH": 11.85,
    "113708.SH": 80.00,
}

# ---- 行情与运行 ----
PERIOD = "1m"
OHLC_COUNT = 120
LIVE_ONLY_LAST_BAR = True
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 30
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

# 尾盘窗口短：超时缩短；orphan 仅在「见过委托后消失」时生效（见上方 PENDING_ORPHAN_SEC）
PENDING_TIMEOUT_SEC = 90

STATE_FILE = r"D:\tradingStrategy\cbauct_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "CbAuct"
STRATEGY_VER = "v3.2"

# DRY_RUN：False=虚拟挂单可测阶梯/升级；True=下单即成交（旧行为）
DRY_RUN_FILL_IMMEDIATE = False
# DRY_RUN 且非立即成交时：挂到涨停价则模拟成交
DRY_RUN_FILL_ON_LIMIT = True
# DRY_RUN 未登录时使用虚拟资金（便于无柜台联调）
DRY_RUN_VIRTUAL_CASH = True
DRY_RUN_VIRTUAL_CASH_AMT = 100000.0
# DRY_RUN 默认不写 STATE，避免污染实盘
DRY_RUN_SAVE_STATE = False
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
