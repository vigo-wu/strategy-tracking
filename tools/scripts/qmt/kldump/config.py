# === kldump/config.py ===
# 主图行情导出 CSV。周期跟随当前主图；改完后跑 _deploy_qmt_gbk.py
# QMT 模型无 __file__，OUT_DIR 必须是绝对路径

STRATEGY_NAME = "KlineDump"
STRATEGY_VER = "v1.3"

# 跟随主图；填 1d/15m 等则覆盖 C.period
PERIOD = "follow"

# 导出根目录（绝对路径）
OUT_DIR = r"D:\persion\strategy-tracking\tools\csv"

# False=按 HIST_START 起导，给本地回测留足周线暖机（QMT 1w 约 120 根）
FOLLOW_CHART_RANGE = False
# 读不到主图区间时的回落（实盘或 C.start 为空）
BAR_COUNT = 5000
HIST_START = "20180101"
HIST_MAX_LOOKBACK_DAYS = 0

DIVIDEND_TYPE = "front_ratio"
DOWNLOAD_HIST = True

# 额外周期。本地回测优先读同目录 {code}_1w_*.csv，对齐 QMT 原生周线
EXTRA_PERIODS = ("1w",)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
