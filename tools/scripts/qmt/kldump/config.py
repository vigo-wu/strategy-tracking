# === kldump/config.py ===
# 主图行情导出 CSV。周期跟随当前主图；改完后跑 _deploy_qmt_gbk.py
# QMT 模型无 __file__，OUT_DIR 必须是绝对路径

STRATEGY_NAME = "KlineDump"
STRATEGY_VER = "v1.5"

# 跟随主图；填 1d/15m 等则覆盖 C.period
PERIOD = "follow"

# 非空则按名单批量导出（不自动并入主图）；空=只导主图
# 示例: ("600350.SH", "601398.SH", "601939.SH", "513530.SH")
# 也可用 list / 逗号分隔字符串 / dict 的 key
DUMP_STOCKS = ("600350.SH", "601398.SH", "601939.SH", "513530.SH")

# 导出根目录（绝对路径）
OUT_DIR = r"D:\vigo\strategy-tracking\tools\csv"

# False=按 HIST_START 起导，给本地回测留足周线暖机（QMT 1w 约 120 根）
FOLLOW_CHART_RANGE = False
# 读不到主图区间时的回落（实盘或 C.start 为空）
BAR_COUNT = 5000
HIST_START = "20180101"
HIST_MAX_LOOKBACK_DAYS = 0

# 复权，传给 get_market_data_ex 的 dividend_type。每种写到 OUT_DIR/<type>/
#   none         不复权（PIT 时点前复权原料；local_bt front* 会读 none + divid_factors）
#   front        前复权（价差）
#   back         后复权（价差）
#   front_ratio  等比前复权（最新价贴近市价）
#   back_ratio   等比后复权
# 可改成子集以缩短导出；改完须 re-deploy 再编译。
# PIT 要求 DIVIDEND_TYPES 必须含 none；DUMP_STOCKS 须覆盖要做 PIT 的标的（可与 BOOK 对齐）。
DIVIDEND_TYPES = ("none", "front", "back", "front_ratio", "back_ratio")
DOWNLOAD_HIST = True

# 导出 get_divid_factors → OUT_DIR/divid_factors/{CODE}_{MKT}.json（local_bt PIT 用）
DUMP_DIVID_FACTORS = True

# 额外周期。本地回测优先读同目录 {code}_1w_*.csv，对齐 QMT 原生周线
EXTRA_PERIODS = ("1w",)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
