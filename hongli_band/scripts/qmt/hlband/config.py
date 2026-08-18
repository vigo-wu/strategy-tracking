# === hlband/config.py ===
# ===================== 用户配置 =====================
# True=只打日志不下单；回测/实盘真下单前务必确认
DRY_RUN = False

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 单笔下单资金上限（元）；实际股数 = floor(预算/开盘价/100)*100
# 未在 TRADE_BUDGET_BY_STOCK 中单独配置的标的用此默认值
TRADE_BUDGET = 25000.0
# 按标的覆盖预算（key 须与 A.stock 一致，如 513530.SH）
TRADE_BUDGET_BY_STOCK = {}
# 可用现金占用比例（预留下单缓冲，避免满仓打满失败）
CASH_RATIO = 0.8

# ---- 周线过滤（跨周期；主图仍是日线）----
# 周线均线周期：快/中/生命线/慢线
#   MA5 vs MA10 + MACD → 多头/空头判定
#   MA30 → 生命线（收盘跌破即周线空，强制清仓）；乖离/斜率过滤也用它
#   MA60 → 数据暖机长度参考（market 取数 need）
W_MA_FAST = 5
W_MA_MID = 13
W_MA_LIFE = 34
W_MA_SLOW = 55
# 周线 MACD 参数（DIF/DEA/柱）；多头要求 DIF>0 且柱>0；死叉且双线在零轴下 → 空
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
# 高位禁开：周线乖离 (MA5-MA30)/MA30 >= 此值 → 不做新开（追高风险）
# 例 0.08 = MA5 相对 MA30 高 8% 以上禁开
W_BIAS_HARD = 0.08
# 低位斜率过滤：乖离 < 此值视为「低位区」；此时若 MA30 未连续向上则禁开
# 例 0.02 = 乖离不足 2% 时要求生命线已拐头向上
W_BIAS_LOW = 0.02
# 低位区判定「连续向上」的周数：需 ma30[t]>ma30[t-1]>ma30[t-2]（即 2 周斜率）
W_MA30_SLOPE_WEEKS = 2

# ---- 日线买卖 ----
# 日线均线：MA20→回踩/站上/无量阴跌；MA60→回踩支撑 + 时间成本线
D_MA_MID = 20
D_MA_SLOW = 60

# 买点 pullback_vol：缩量回踩强支撑
#   价格贴近 MA20 或 MA60（|价-均线|/均线 <= 容差）且当日量 < N 日均量 * 比例
MA_TOUCH_TOL = 0.025          # 0.025 = 距均线 ±2.5% 内算「回踩到位」
VOL_PULLBACK_N = 10           # 缩量比较的均量窗口（日）
VOL_PULLBACK_RATIO = 0.9      # 量 < 均量*0.9 视为缩量

# 全局禁开 vol_dry_skip（无量阴跌不言底）：
#   收盘跌破 MA20 且量 < N 日均量 * 比例 → 当天任何买点失效
VOL_DRY_N = 20
VOL_DRY_RATIO = 0.60          # 量 < 20 日均量的 60% 视为无量阴跌

# 卖① trail_stop：阶梯式移动止盈
#   按历史最高浮盈 (peak-cost)/cost 选档；触发条件：
#     自峰值回撤 > giveback，或（若设了 profit_floor）当前浮盈 < 底线
#   元组：(peak_lo, peak_hi, giveback, profit_floor)
#     peak_hi=None 无上限；profit_floor=None 不设硬底线
#   档1 起步保护 [3%,6%)：回撤>1.5%（同旧版，防破本）
#   档2 落袋为安 [6%,10%)：回撤>3% 或 利润跌破 3%
#   档3 放鹰吃肉 >=10%：回撤>4%（利润垫扛日线洗盘）
TRAIL_TIERS = (
    (0.03, 0.06, 0.015, None),
    (0.06, 0.10, 0.03, 0.03),
    (0.10, None, 0.04, None),
)
# 卖② time_force：智能时间成本（防长期磨人）
#   持仓 bar 数 > BARS 后：收盘破日线 MA60 → 立即强制平仓；
#   仍站上 MA60 → 豁免一次，再观察 GRACE_BARS 日，期满仍强制平仓
TIME_FORCE_BARS = 30
TIME_FORCE_GRACE_BARS = 5

# 兜底风控（优先级高）
# chase_skip：当日涨幅 (收-昨收)/昨收 >= 此值 → 禁开（防追高）
CHASE_MAX_PCT = 0.05
# stop_loss：收盘价 <= 成本 * (1 - 此值) → 硬止损清仓
STOP_LOSS = 0.08
# weekly_bear 强制清仓：连续 N 个信号日（日 K）仍为空头才挂 pending_exit
#   N<=0 或 1：当天空头即挂（与改前一致）；N=2：连续两日仍空才挂
#   禁开 / 撤买入 pending 仍按「当日」空头即时生效，不要求满 N 日
W_BEAR_CONFIRM_DAYS = 2

# （另有 weekly_bear：周线空头判定见 _eval_weekly；清仓见上）

# 盈利后加仓：峰值浮盈 >= SCALE_ARM，且该笔已持仓 >= SCALE_ARM_BARS 日，
# 再出现缩量回踩才加第二笔。执行日若已触发卖点则取消加仓、让路出场。
# SCALE_W_HIST_MIN：周线 MACD 柱低于此值不加（过滤深空头里的 3% 冲高）；None 关闭
# SCALE_LOTS=True：每笔独立成本/峰值/止盈；False：均价合并后整仓出
# weekly_bear 仍一次出清剩余各笔；trail_stop / time_force / stop_loss 按笔
SCALE_ENABLE = True
SCALE_MAX = 2
SCALE_ARM = 0.03
SCALE_ARM_BARS = 8
SCALE_W_HIST_MIN = -0.01
SCALE_LOTS = True

# 策略交易面板 bind → 模块常量。编辑器/回测无注入时用上面默认值。
# TRAIL_TIERS、均线周期、路径、账号不在面板。
PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_w_bias_hard", "W_BIAS_HARD", "float"),
    ("panel_w_bias_low", "W_BIAS_LOW", "float"),
    ("panel_w_slope_weeks", "W_MA30_SLOPE_WEEKS", "int"),
    ("panel_w_bear_days", "W_BEAR_CONFIRM_DAYS", "int"),
    ("panel_ma_touch_tol", "MA_TOUCH_TOL", "float"),
    ("panel_vol_pb_n", "VOL_PULLBACK_N", "int"),
    ("panel_vol_pb_ratio", "VOL_PULLBACK_RATIO", "float"),
    ("panel_vol_dry_n", "VOL_DRY_N", "int"),
    ("panel_vol_dry_ratio", "VOL_DRY_RATIO", "float"),
    ("panel_chase_pct", "CHASE_MAX_PCT", "float"),
    ("panel_stop_loss", "STOP_LOSS", "float"),
    ("panel_time_force_bars", "TIME_FORCE_BARS", "int"),
    ("panel_time_force_grace", "TIME_FORCE_GRACE_BARS", "int"),
    ("panel_scale", "SCALE_ENABLE", "bool"),
    ("panel_scale_lots", "SCALE_LOTS", "bool"),
    ("panel_scale_arm_bars", "SCALE_ARM_BARS", "int"),
)

# ---- 行情与运行 ----
# 主图周期；周线另拉 1w 跨周期
PERIOD = "1d"
# 日/周 K 拉取根数（须覆盖最慢均线 + 指标暖机）
OHLC_COUNT = 180
WEEKLY_OHLC_COUNT = 120

# 实盘只在最新一根 bar 决策；回测逐 bar 扫
LIVE_ONLY_LAST_BAR = True
# 实盘：盘中(DECISION_*)只执行 pending；收盘后(SIGNAL_CONFIRM_*)用当日完整日/周 K 确认信号并挂起 → 次日开盘成交
# 若收盘窗口未跑到，次日开盘对「上一根已收盘日」兜底评估并挂起（同日可成交）
# 判定：confirmed_eval_day < 上一完整交易日 且今日尚未 fallback
# 周线：bt/confirm/开盘 exec·兜底一律含本周未收盘根；日线开盘仍去未收盘日 K
LIVE_CLOSE_CONFIRM = True
# 实盘决策时窗（HHmmss）：盘中处理券商 pending / 心跳；信号成交见 PENDING_EXEC_*
DECISION_START = "093000"
DECISION_END = "150000"
# 信号 pending（pending_entry/exit）仅在开盘附近成交；错过则保留到下一交易日开盘窗
# 须覆盖「开盘兜底挂起 → 同窗内下一根成交」；收盘确认窗绝不按开盘价成交
PENDING_EXEC_START = "093000"
PENDING_EXEC_END = "094500"
# 收盘确认信号时窗（须与 DECISION 衔接；含尾盘近似收盘 + 盘后）
# 日线盘后常无新 tick，故从 14:55 起用当日 K 确认；16:00 前仍可确认
SIGNAL_CONFIRM_START = "145500"
SIGNAL_CONFIRM_END = "160000"
# 实盘心跳日志间隔（秒）；持仓无事件时的状态行也按此节流
LIVE_HEARTBEAT_SEC = 60

# download_history_data 最长回溯（自然日）；回测暖机用
HIST_MAX_LOOKBACK_DAYS = 800
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

# pending 委托超时/孤儿清理（秒）
PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__；状态绝对路径（含 {stock}，多实例不同主图互不覆盖）
#   513530.SH → ...\hlband_513530_SH.json
STATE_FILE = r"D:\tradingStrategy\hlband_{stock}.json"
# 实盘结构化日志根目录；落盘为 LOG_DIR/<stock_tag>/{tag}_events.jsonl 等
# 空字符串关闭落盘（仍保留终端 print）
LOG_DIR = r"D:\tradingStrategy\logs"
# True=回测也写日志（默认关，避免回测刷爆磁盘）
LOG_IN_BACKTEST = False

STRATEGY_NAME = "HlBand"
STRATEGY_VER = "v1.26"
# =======================================================

# 券商委托终态：成交 / 废单死单（勿改除非对接环境不同）
_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
