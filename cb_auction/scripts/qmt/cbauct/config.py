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

# ---- 上市首日价格锚点（model.md 终审）----
# 临停基准价（触及 30% 停牌）
HALT_BASE_PRICE = 130.0
# 价格笼子比例（有效申报上限 = 基准/最新价 * CAGE_RATIO）
CAGE_RATIO = 1.1
# 复牌首段顶格 = 130 * 1.1（严禁深市临停期硬编码 157.30）
REOPEN_CAP_PRICE = 143.0
# 全天最高限价
LIMIT_UP_PRICE = 157.30
# 可转债价格小数位
PRICE_DECIMALS = 3
# 沪市追单：新上限至少高出旧挂单价这么多才撤补
CHASE_MIN_STEP = 0.01

# ---- 时窗（HHmmss；实盘墙钟，回测用 K 线时间）----
# 深市：临停期内均可埋 143（须在 14:55 前完成）；窗开太晚易漏单
SZ_PREPLACE_START = "130000"
SZ_PREPLACE_END = "145459"
# 深市：复牌瞬间即可升级（撤143→挂157.30）；勿晚于 14:57:01
SZ_CLOSE_BUY_START = "145700"
SZ_CLOSE_BUY_END = "145950"
# 深市升级撤单告警阈值（秒）：撤不掉则持续告警
SZ_ESCALATE_ALERT_SEC = 2.0
# 沪市：14:57 起连续竞价阶梯追单（可撤可补）
SH_CHASE_START = "145700"
SH_CHASE_END = "145955"
# 沪市追单节流（毫秒）。仅抑制重复撤单评估；撤成后允许立刻重挂
SH_CHASE_INTERVAL_MS = 200
# cancel_replace=撤旧挂新（model 定稿）
SH_CHASE_MODE = "cancel_replace"
# 撤单重试间隔（秒）；common orders_pending 读取
CANCEL_RETRY_SEC = 1.0
# 撤单后「见过委托且已从列表消失」才清 pending 的等待秒数
PENDING_ORPHAN_SEC = 15
# 深市临停埋单 + 沪市追单窗内挂单：禁止按短超时自动撤（否则丢排队）
PENDING_TIMEOUT_EXEMPT_INTENTS = ("SZ_PREPLACE", "SH_OPEN", "SH_CHASE")
# 豁免超时日志最短间隔（秒）
PENDING_TIMEOUT_EXEMPT_LOG_SEC = 300

# ---- 上市首日门闩 ----
# True=仅上市首日跑买卖；非首日只心跳
LISTING_DAY_ONLY = True
# True=忽略首日检测强制运行（联调）
FORCE_RUN = False
# 日K推断失败时：False=禁止下单(fail-closed)；True=放行(fail-open)
LISTING_DAY_FAIL_OPEN = False
# 可选显式上市日 YYYYMMDD；有则优先于日K推断
LISTING_DATE_MAP = {
    # "123276.SZ": "20260810",
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
STRATEGY_VER = "v2.8"

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
