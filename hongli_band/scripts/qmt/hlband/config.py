# === hlband/config.py ===
# ===================== 用户配置 =====================
# True=只打日志不下单；回测/实盘真下单前务必确认
DRY_RUN = False

ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# 跟踪池仓位（实盘）。全池最多 BOOK_LOT_MAX 笔（开仓+加仓合计）。
# 第 1 笔开仓：大仓空则 LOT_OPEN_FRAC×cap。第 2 笔：LOT_ADD_FRAC×cap（加仓或其它标的开仓）。
# 第 3 笔：金额吃剩余可部署资金；book_frac 仍记空档（0.50 / 0.30 / 剩余档）。
# 同标的一轮只加一次；加过仓后该只须全平才能再开。卖掉大仓由其他空仓标的开仓补回。
# cap = CASH_RATIO * E_s；E_s = 总资产 - 非白名单股票市值。
# k / book_mv 只统计 BOOK_STOCKS。N = 字典长度。实盘单实例监视全池并写账本；回测用 TRADE_BUDGET。
# 形态：code → 配置字典。ma_type（EMA|SMA）；dividend_type 见下方复权注释。
# 简写兼容：value 写成 "SMA" 视为 {"ma_type": "SMA"}；旧纯字符串 tuple 仍认作白名单。
BOOK_STOCKS = {
"600938.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
"603259.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
"601615.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
"603659.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
"002001.SZ": {"ma_type": "EMA", "dividend_type": "front_ratio"},
"600350.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
"601857.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
}

# 单实例共享信号账本（不是 STATE_FILE；禁止按标的分文件）
BOOK_FILE = r"D:\HlBandV6\hlband_book.json"
# 账本冻结截止：确认窗内打卡，到点（或打卡满 N）冻结；须在收盘集合竞价前完成分档下单
BOOK_FREEZE_CLOSE = "145640"
BOOK_FREEZE_OPEN = "093030"
# 可部署比例（相对 E_s = 总资产-其它股票市值）；其余留作 T+1 / 废单重试
CASH_RATIO = 0.90
# 全池同时最多几笔（开仓+加仓）。第 4 笔不下。
BOOK_LOT_MAX = 3
# 开仓：大仓空档用 50%；大仓已在且不是最后一槽则新开走 30%。
LOT_OPEN_FRAC = 0.50
# 第二笔（加仓或其它标的开仓）30%。全池最后一槽不锁此值，改吃剩余资金（约 20% cap）。
# 大仓空且只剩 1 个槽时不加仓，留给开仓补大仓（该笔会吃剩余，约等于 50%）。
LOT_ADD_FRAC = 0.30
# 回测无全账户账本时的单笔回落（元）
TRADE_BUDGET = 100000.0
# 按标的覆盖预算（key 须与 A.stock 一致）；仅回测生效
TRADE_BUDGET_BY_STOCK = {}

# ---- 周线过滤（跨周期；主图仍是日线）----
# 价格均线缺省：EMA 或 SMA（大小写不敏感）。BOOK_STOCKS[code].ma_type 优先；
# 缺省/非法回落本常量。只作用于周/日价格均线；成交量均量始终 SMA；MACD 仍用 EMA。
MA_TYPE = "EMA"
# 周线均线：快/中/生命线/慢线（斐波那契 5/13/34/55）；算法见标的 ma_type / MA_TYPE
#   MA5 vs MA13 + MACD → 多头判定（仅日志；开仓不强制 weekly_bull）
#   MA34 → 生命线（收盘跌破即周线空，强制清仓）；乖离/斜率过滤也用它
#   MA55 → 数据暖机长度参考（market 取数 need）
W_MA_FAST = 5
W_MA_MID = 13
W_MA_LIFE = 34
W_MA_SLOW = 55
# 周线 MACD 参数（DIF/DEA/柱）；多头要求 DIF>0 且柱>0；死叉且双线在零轴下 → 空
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
# 高位禁开：周线乖离 (MA5-MA34)/MA34 >= 此值 → 不做新开（追高风险）
# 例 0.08 = MA5 相对生命线 MA34 高 8% 以上禁开
W_BIAS_HARD = 0.08
# 低位斜率过滤：乖离 < 此值视为「低位区」；此时若 MA34 未连续向上则禁开
# 例 0.02 = 乖离不足 2% 时要求生命线已拐头向上
W_BIAS_LOW = 0.02
# 低位区判定「连续向上」的周数：需 life[t]>life[t-1]>life[t-2]（即 2 周斜率）
# 常量名 W_MA30_SLOPE_WEEKS 为历史兼容；比较对象是 W_MA_LIFE（34）
W_MA30_SLOPE_WEEKS = 2

# ---- 日线买卖 ----
# 日线均线（算法见标的 ma_type / MA_TYPE）：MA20→回踩/站上/无量阴跌；MA60→回踩支撑 + 时间成本线
D_MA_MID = 20
D_MA_SLOW = 60

# 买点 pullback_vol：缩量回踩强支撑
#   价格贴近 MA20 或 MA60（|价-均线|/均线 <= 容差）且当日量 < N 日均量 * 比例
MA_TOUCH_TOL = 0.025          # 0.025 = 距均线 ±2.5% 内算「回踩到位」
VOL_PULLBACK_N = 10           # 缩量比较的均量窗口（日，始终 SMA）
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
# 卖② time_force：智能时间成本（防长期磨人，不砍还在趋势里的仓）
#   BARS = 日线慢均线一半：满此日后才把 MA60 当出场地板，不是最长持仓
#   BARS<=0：关闭整条 time_force（不是 MIN_RET=0）
#   收盘破日线 MA60 → 立即强制平仓
#   仍站上 MA60 且峰值浮盈 < MIN_RET → 豁免一次，再观察 GRACE_BARS 日，期满强平（回收死钱）
#   仍站上 MA60 且峰值 >= MIN_RET → 不按日历强平，交给 trail / 破 MA60 / 周线空
#   MIN_RET 对齐阶梯止盈起步档；0 = 关闭让路（回到期满强平）
TIME_FORCE_BARS = D_MA_SLOW // 2
TIME_FORCE_GRACE_BARS = 5
TIME_FORCE_MIN_RET = 0.03

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

# 盈利后加仓（回踩加仓 + 破平台推仓，任一即可）：
#   门槛：峰值浮盈 >= SCALE_ARM，且该笔已持仓 >= SCALE_ARM_BARS 日
#   触发（任一）：缩量回踩 / 日线收盘突破前期平台 / 近两周周线 MACD 金叉且柱放大
#   回踩加仓仍受 chase_skip；破平台/金叉不受（突破日允许较大涨幅）
#   执行日若已触发卖点则取消加仓、让路出场
# SCALE_ONCE_PER_ROUND：同一轮只加一次。加过仓后该只须全平才能再开，不能把剩余仓当新开
# SCALE_W_HIST_MIN：周线 MACD 柱低于此值不加（过滤深空头里的冲高）；None 关闭
# SCALE_LOTS=True：每笔独立成本/峰值/止盈；False：均价合并后整仓出
# weekly_bear 仍一次出清剩余各笔；trail_stop / time_force / stop_loss 按笔
SCALE_ENABLE = True
SCALE_MAX = 2
SCALE_ONCE_PER_ROUND = True
SCALE_ARM = 0.03
SCALE_ARM_BARS = 8
SCALE_W_HIST_MIN = -0.01
SCALE_LOTS = True
# 日线平台：回看 N 日（不含当日）高低点；振幅 <= 此值视为平台；收盘站上高点且昨收仍在平台内
SCALE_PLAT_LOOKBACK = 20
SCALE_PLAT_MAX_RANGE = 0.10          # 0.10 = 平台振幅不超过 10%
SCALE_PLAT_BREAK_BUF = 0.0           # 收盘超过平台高点的缓冲；0=收盘严格站上
# 周线 MACD：本周或上周 DIF 上穿 DEA；上周金叉则本周红柱须比上周放大此倍数
SCALE_W_HIST_EXPAND_RATIO = 1.2

# 策略交易面板 bind → 模块常量。编辑器/回测无注入时用上面默认值。
# 只上屏：开关 / 可部署比例 / 硬风控。买点窗口、时间成本、加仓细节、SCALE_LOTS、
# TRAIL_TIERS、均线周期、BOOK_STOCKS 子配置（ma_type / dividend_type）、
# MA_TYPE、路径、账号仍只在 config（N 以 BOOK_STOCKS 长度为准）。
PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_w_bias_hard", "W_BIAS_HARD", "float"),
    ("panel_chase_pct", "CHASE_MAX_PCT", "float"),
    ("panel_stop_loss", "STOP_LOSS", "float"),
    ("panel_scale", "SCALE_ENABLE", "bool"),
)

# ---- 行情与运行 ----
# 主图周期；周线另拉 1w 跨周期
PERIOD = "1d"
# 日/周 K 拉取根数（须覆盖最慢均线 + 指标暖机）
OHLC_COUNT = 180
WEEKLY_OHLC_COUNT = 120

# 实盘只在最新一根 bar 决策；回测逐 bar 扫
LIVE_ONLY_LAST_BAR = True
# 实盘：SIGNAL_CONFIRM_* 用当日近似完整日/周 K 确认信号并挂起；
# PENDING_EXEC_* 尾盘窗按现价/收盘价成交（避免隔夜跳空）；确认可早于成交。
# 错过尾盘则保留到下一交易日 OPEN_EXEC_* 开盘窗按开盘价成交。
# 若收盘窗未跑到，开盘对「上一根已收盘日」兜底评估并挂起（同日开盘窗可成交）。
# 判定：confirmed_eval_day < 上一完整交易日 且今日尚未 fallback
# 周线：bt/confirm/开盘一律丢掉未收盘周（对齐 QMT 回测 0000 原生 1w；周五仍看上周）
# 日线开盘仍去未收盘日 K
LIVE_CLOSE_CONFIRM = True
# 实盘决策时窗（HHmmss）：盘中处理券商 pending / 心跳；信号成交见 PENDING_EXEC_* / OPEN_EXEC_*
DECISION_START = "093000"
DECISION_END = "150000"
# 信号 pending 主成交窗：连续竞价尾盘限价（买挂卖一 / 卖挂买一）。
# 截止后进入收盘集合竞价，本窗不再报单；错过则次日开盘窗补。
# 建议：FREEZE≈本窗起点，且起点晚于 SIGNAL_CONFIRM_START（先打卡再成交）。
PENDING_EXEC_START = "145640"
PENDING_EXEC_END = "145700"
# 隔夜残留 / 开盘兜底：错过尾盘时次日开盘窗按开盘价补成交
OPEN_EXEC_START = "093000"
OPEN_EXEC_END = "094500"
# 收盘确认信号时窗（与尾盘成交窗重叠；盘后仍可确认，成交则等到次日开盘窗）
SIGNAL_CONFIRM_START = "145630"
SIGNAL_CONFIRM_END = "150000"
# 实盘心跳/状态行间隔（秒）；空仓与持仓无新信号沿时均按此节流
LIVE_HEARTBEAT_SEC = 300
# 实盘取数：window=确认窗/开盘兜底才拉日+周，盘中只 pending；always=决策窗内每次当确认窗
LIVE_OHLCV_POLICY = "window"

# 行情复权（传给 get_market_data_ex 的 dividend_type）
# 优先 BOOK_STOCKS[code].dividend_type；缺键/非法回落本常量。不上屏。
#   follow       跟随主图 / 公式「基本信息 → 复权方式」
#   none         不复权
#   front        前复权（价差）
#   back         后复权（价差）
#   front_ratio  等比前复权（池外/未写字段的缺省）
#   back_ratio   等比后复权
DIVIDEND_TYPE = "front_ratio"

# download_history_data 最长回溯（自然日）；回测暖机用
HIST_MAX_LOOKBACK_DAYS = 800
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True

# pending 委托超时/孤儿清理（秒）
PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60

# QMT 模型无 __file__；状态绝对路径（含 {stock}，宇宙循环按票分文件）
#   513530.SH → ...\hlband_513530_SH.json
STATE_FILE = r"D:\HlBandV6\hlband_{stock}.json"
# 实盘结构化日志根目录；落盘为 LOG_DIR/<stock_tag>/{tag}_events.jsonl 等
# 空字符串关闭落盘（仍保留终端 print）
LOG_DIR = r"D:\HlBandV6\logs"
# True=回测也写日志（默认关，避免回测刷爆磁盘）
LOG_IN_BACKTEST = False

STRATEGY_NAME = "HlBandV6"
STRATEGY_VER = "v1.63"
# =======================================================

# 券商委托终态：成交 / 废单死单（勿改除非对接环境不同）
_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
