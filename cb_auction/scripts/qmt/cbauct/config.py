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

# ---- 竞价价格（上市首日规则）----
# 开盘竞价买入顶格价
OPEN_BUY_PRICE = 130.0
# 首日涨停顶格价（≤5亿收盘挂卖参考）
LIMIT_UP_PRICE = 157.30
# 小盘分界：发行规模（亿元）<= 此值 → 收盘提示/回测模拟挂 157.30
SMALL_SIZE_YI = 5.0

# 发行规模（亿元）：优先 ISSUE_SIZE_MAP[A.stock]，否则用默认
ISSUE_SIZE_YI = 0.0
# 2026 样本规模（可继续追加）；键=代码.市场
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

# ---- 时窗（HHmmss，实盘用墙钟；回测用 K 线时间）----
# 开盘竞价：9:15 起挂 130；默认挂到 9:24:59
BUY_START = "091500"
BUY_END = "092500"
# 收盘竞价提示窗（仅日志 / 回测模拟卖，实盘不自动卖）
SELL_HINT_START = "145700"
SELL_HINT_END = "150000"

# 实盘：卖出一律手动；本策略只打印建议挂单价
# 回测：True=在提示窗按定稿价模拟卖出（可转债 T+0）；实盘忽略此开关
BACKTEST_SIM_SELL = True

# ---- 行情与运行 ----
PERIOD = "1m"
OHLC_COUNT = 120
LIVE_ONLY_LAST_BAR = True
LIVE_HEARTBEAT_SEC = 60

HIST_MAX_LOOKBACK_DAYS = 30
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

PENDING_TIMEOUT_SEC = 300
PENDING_ORPHAN_SEC = 60

STATE_FILE = r"D:\tradingStrategy\cbauct_{stock}.json"
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

STRATEGY_NAME = "CbAuct"
STRATEGY_VER = "v1.0"
# =======================================================

_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
