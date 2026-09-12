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
# cap = CASH_RATIO * 基数。BUDGET_BASE=equity：基数=E_s=总资产-非白名单股票市值；
# BUDGET_BASE=fixed：基数=TRADE_BUDGET（不读其它市值）。
# k / book_mv 只统计 BOOK_STOCKS。N = 集合/字典长度。实盘单实例监视全池并写账本；回测用 TRADE_BUDGET。
# 形态：code 集合，或 code → 配置字典。ma_type（EMA|SMA）；dividend_type 见下方复权注释。
# 简写兼容：value 写成 "SMA" 视为 {"ma_type": "SMA"}；旧纯字符串 tuple 仍认作白名单。
BOOK_STOCKS = {
    "600938.SH",
    "603259.SH",
    "601615.SH",
    "603659.SH",
    "002001.SZ",
    "600350.SH",
    "601857.SH",
}

# 单实例共享信号账本（不是 STATE_FILE；禁止按标的分文件）
BOOK_FILE = r"D:\HlBandV7\hlband_book.json"
# 资金基数：equity=总资产减其它股票市值；fixed=下面 TRADE_BUDGET。面板下拉会写成中文，代码归一成这两值。
BUDGET_BASE = "equity"
# 可部署比例（相对所选基数）；其余留作 T+1 / 废单重试
CASH_RATIO = 0.90
# 全池同时最多几笔（开仓+加仓）。第 4 笔不下。
BOOK_LOT_MAX = 3
# 开仓：大仓空档用 50%；大仓已在且不是最后一槽则新开走 30%。
LOT_OPEN_FRAC = 0.50
# 第二笔（加仓或其它标的开仓）30%。全池最后一槽不锁此值，改吃剩余资金（约 20% cap）。
# 大仓空且只剩 1 个槽时不加仓，留给开仓补大仓（该笔会吃剩余，约等于 50%）。
LOT_ADD_FRAC = 0.30
# 固定金额（元）：实盘 BUDGET_BASE=fixed 时的基数；编辑器回测袖子也用此值（回测不乘 CASH_RATIO）
TRADE_BUDGET = 100000.0

# ---- 周线过滤（跨周期；主图仍是日线）----
# 价格均线缺省：EMA 或 SMA（大小写不敏感）。BOOK_STOCKS[code].ma_type 优先；
# 缺省/非法回落本常量。只作用于周/日价格均线；成交量均量始终 SMA；MACD 仍用 EMA。
MA_TYPE = "EMA"
# 周线均线：快/生命线（斐波那契 5/34）；算法见标的 ma_type / MA_TYPE
#   MA5 vs MA13 + MACD → 多头判定（仅日志，中线周期写死 13；开仓不强制 weekly_bull）
#   MA34 → 生命线（收盘跌破即周线空，强制清仓）；乖离/斜率过滤也用它
# 周线取数 need 另钳原 MA55 暖机地板（见 market._ohlcv_need_1w）
W_MA_FAST = 5
W_MA_LIFE = 34
# 周线 MACD 参数（DIF/DEA/柱）；多头要求 DIF>0 且柱>0；死叉且双线在零轴下 → 空
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ---- 日线买卖（均线周期是 structure，阈值在 RECIPE.factor_params）----
# 日线均线（算法见标的 ma_type / MA_TYPE）：中线→回踩/无量阴跌；慢线→回踩支撑 + 时间成本地板
#   <=0 关闭该条（与 time_force.bars 相同约定）
#   关中线：回踩只看慢线（若开着）；vol_dry 关掉
#   关慢线：回踩只看中线；time_force 破慢线地板关掉（bars 仍独立）
#   两条都关：无 pullback_vol 新开；加仓仍可走 plat_break / w_macd_golden
D_MA_MID = 20
D_MA_SLOW = 60

# 盈利后加仓门槛（仓位层，不进 factor_params）：
#   峰值浮盈 >= SCALE_ARM，且该笔已持仓 >= SCALE_ARM_BARS 日
#   回踩加仓仍受 chase；破平台/金叉不受
#   执行日若已触发卖点则取消加仓
# SCALE_ONCE_PER_ROUND：同一轮只加一次
# SCALE_W_HIST_MIN：周线 MACD 柱低于此值不加；None 关闭
# SCALE_LOTS=True：每笔独立成本/峰值/止盈
SCALE_ENABLE = True
SCALE_ONCE_PER_ROUND = True
SCALE_ARM = 0.03
SCALE_ARM_BARS = 8
SCALE_W_HIST_MIN = -0.01
SCALE_LOTS = True

# 默认 Recipe：四槽布尔式。数字真源是 factor_params 字面量。
# D_MA_* / W_MA_* / MACD_* 是 structure。SCALE_ARM 等仓位门槛不进表。
# scale_out 恒 false：减仓未启用。
RECIPE = {
    "entry": [
        "and",
        ["not", "chase"],
        ["not", "vol_dry"],
        ["not", "w_bias"],
        ["not", "w_slope"],
        ["not", "weekly_bear"],
        "pullback_vol",
    ],
    "scale_in": [
        "and",
        ["not", "vol_dry"],
        ["not", "w_bias"],
        ["not", "w_slope"],
        ["not", "weekly_bear"],
        [
            "or",
            ["and", "pullback_vol", ["not", "chase"]],
            "plat_break",
            "w_macd_golden",
        ],
    ],
    "exit": [
        "weekly_bear_confirm",
        "stop_loss",
        "trail_stop",
        "time_force",
    ],
    "scale_out": False,
    "factor_params": {
        # chase：当日涨幅 >= max_pct 禁开
        "chase": {"max_pct": 0.05},
        # vol_dry：收盘破中线且量 < n 日均量 * ratio
        "vol_dry": {"ratio": 0.60, "n": 20},
        # pullback_vol：贴均线 tol + 连续 confirm_days 日量 < vol_n 日均量 * ratio
        "pullback_vol": {
            "tol": 0.025,
            "vol_n": 10,
            "ratio": 0.9,
            "confirm_days": 2,
        },
        # w_bias：周线 (MA5-MA34)/MA34 >= hard 禁开
        "w_bias": {"hard": 0.08},
        # w_slope：乖离 < low 且生命线未连续 slope_weeks 周向上则禁开
        "w_slope": {"low": 0.02, "slope_weeks": 2},
        # weekly_bear_confirm：连续 days 个信号日仍空才清仓；<=0/1=当天
        "weekly_bear_confirm": {"days": 2},
        # plat_break：回看 lookback 日振幅 <= max_range 且收盘破高
        "plat_break": {
            "lookback": 20,
            "max_range": 0.10,
            "break_buf": 0.0,
        },
        # w_macd_golden：上周金叉则本周红柱须放大 hist_expand 倍
        "w_macd_golden": {"hist_expand": 1.2},
        # stop_loss：收盘 <= 成本 * (1 - pct)
        "stop_loss": {"pct": 0.08},
        # trail_stop：档 (peak_lo, peak_hi, giveback, profit_floor)；档1 peak_lo 给 time_force 让路
        "trail_stop": {
            "tiers": [
                [0.03, 0.06, 0.015, None],
                [0.06, 0.10, 0.03, 0.03],
                [0.10, None, 0.04, None],
            ]
        },
        # time_force：持仓 > bars 后评估；<=0 关整条
        "time_force": {"bars": 30},
    },
}

# 策略交易面板 bind → 模块常量。因子阈值不上屏（改 RECIPE.factor_params）。
# 只上屏：开关 / 资金基数 / 固定金额 / 可部署比例 / 加仓开关。
PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget_base", "BUDGET_BASE", "str"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
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
# 信号 pending 主成交窗：连续竞价尾盘限价（买挂卖一 / 卖挂买一）。
# 截止后进入收盘集合竞价，本窗不再报单；错过则次日开盘窗补。
PENDING_EXEC_START = "145640"
PENDING_EXEC_END = "145700"
# 隔夜残留 / 开盘兜底：错过尾盘时次日开盘窗按开盘价补成交
OPEN_EXEC_START = "093000"
OPEN_EXEC_END = "094500"
# 收盘确认信号时窗（与尾盘成交窗重叠；盘后仍可确认，成交则等到次日开盘窗）
# 确认须早于尾盘成交（先打卡再成交）
SIGNAL_CONFIRM_START = "145630"
SIGNAL_CONFIRM_END = "150000"
# 账本冻结：收盘跟尾盘成交窗起点（勿单独改）；开盘保留打卡缓冲（可改）
BOOK_FREEZE_CLOSE = PENDING_EXEC_START
BOOK_FREEZE_OPEN = "093030"
# 实盘决策时窗（HHmmss）：盘中处理券商 pending / 心跳；信号成交见 PENDING_EXEC_* / OPEN_EXEC_*
# START 是「策略醒着」，不要绑 OPEN_EXEC_START（推迟补单窗不应睡过 09:30 pending）
DECISION_START = "093000"
DECISION_END = SIGNAL_CONFIRM_END
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
STATE_FILE = r"D:\HlBandV7\hlband_{stock}.json"
# 实盘结构化日志根目录；落盘为 LOG_DIR/<stock_tag>/{tag}_events.jsonl 等
# 空字符串关闭落盘（仍保留终端 print）
LOG_DIR = r"D:\HlBandV7\logs"
# True=回测也写日志（默认关，避免回测刷爆磁盘）
LOG_IN_BACKTEST = False

STRATEGY_NAME = "HlBandV7"
STRATEGY_VER = "v1.68"
# =======================================================

# 券商委托终态：成交 / 废单死单（勿改除非对接环境不同）
_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
