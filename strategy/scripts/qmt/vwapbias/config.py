# === vwapbias/config.py ===
# 分时 VWAP 乖离、日内 T+0。首测标的: 113699.SH 金25转债（沪市、10 张整数倍）。
# 形态: 单仓骨架 + SCALE_LOTS 同标的分笔。主图必须 1 分钟，不要挂正股 603979.SH，
# 也不要挂同发行人旧券 113615.SH。规则真源: strategy/model.md（当前 v0.9）。
# 终端改参走 panel.xml / PANEL_BINDS；改本文件后必须跑 _deploy_qmt_gbk.py。

# ===================== 开关与账户 =====================
# True=只打日志不下单。回测/实盘真下单前在面板取消「模拟下单」，或改这里。
DRY_RUN = True

# 编辑器/回测兜底账号；实盘以对话框 account / accountType 为准，勿把账号放上面板。
ACCOUNT_ID = "39953913"
ACCOUNT_TYPE = "STOCK"  # STOCK / CREDIT

# ===================== 资金 =====================
# 单日预算上限（元）。两档各按 LOT_W* 再按 VOL_STEP 取整。建议 5 万~20 万，
# 不超过近 5 日日均额的 1%。价格约 194 时，10 张约 1940 元。
TRADE_BUDGET = 50000.0
# 按标的覆盖预算（key 须与 A.stock 一致，如 113699.SH）；空则用上面默认值。
TRADE_BUDGET_BY_STOCK = {}
# 可用现金占用比例，预留下单缓冲，避免打满失败。
CASH_RATIO = 0.8

# ===================== 转债数量与 T+0 =====================
# 沪市转债申报 10 张（1000 元面值）整数倍。common._lot / 可卖取整读此值，不要当 100 股。
VOL_STEP = 10
# 可转债当日买入可卖。必须 True，否则回测会按股票 T+1 锁仓。
ALLOW_T0 = True

# ===================== 标的拦截 =====================
# 主图须与此一致，否则 univ_skip=wrong_symbol。
EXPECT_STOCK = "113699.SH"
# 禁止交易（挂错主图时直接 skip）。113615=金诚转债；113069=博23已摘牌。
FORBID_STOCKS = ("113615.SH", "113069.SH")

# ===================== 周期与取数 =====================
# 主图周期。只在已收盘 1 分钟 K 上决策（回测用当前根，实盘用上一根）。
PERIOD = "1m"
# 向 ContextInfo 要的 1 分钟根数。本机 pandas/get_market_data_ex 损坏时走 ori，
# ori 往往只给最近约 240 根，靠 barpos 窗口对齐，不必把此值当成实际可用长度。
OHLC_COUNT = 800
# 日线根数：ADV_MIN 近 N 日均额、昨收等。
DAILY_OHLC_COUNT = 12
# 实盘只在 is_last_bar() 决策，避免未收盘 K 上反复下单。回测忽略。
LIVE_ONLY_LAST_BAR = True

# ===================== 交易时段（HHMMSS 字符串） =====================
# 回测用 K 线时间；实盘用墙钟。沪市转债连续匹配到 15:00（无深市 14:57 收盘集合）。
DECISION_START = "093000"      # 决策窗开始
DECISION_END = "150000"        # 决策窗结束
OPEN_SKIP_AM_END = "093500"    # 09:30~09:35 只更新指标，不交易（开盘噪声）
OPEN_SKIP_PM_START = "130000"  # 13:00~13:05 同样暖机
OPEN_SKIP_PM_END = "130500"
LUNCH_START = "113000"         # 午休，phase=lunch
LUNCH_END = "130000"
NO_NEW_ENTRY = "144000"        # 14:40 起只卖不买（sell_only）
FLAT_START = "145000"          # 14:50 起 eod_flatten 强平；未平视为策略失败

# ===================== 买入: 负乖离分档 =====================
# BIAS = (收盘 - 当日VWAP) / VWAP，小数。-0.018 = 低于均价 1.8%。
# 阈值按上市以来 60 分钟 + 近月 5 分钟分位校准（公开源无完整 1 分钟历史），
# 约 10% / 3% 交易日触及 L1/L2。脚本: strategy/scripts/calibrate_113699_bias.py
BIAS_L1 = -0.015               # 开仓档，日志 buy_l1
BIAS_L2 = -0.025               # 须已持 L1，且止跌 + 现价>=持仓均价，日志 buy_l2
BIAS_L3 = -0.035               # 更深一档，默认关
ENABLE_L3 = False
# 各档占用 TRADE_BUDGET 的比例，再按 VOL_STEP 取整。L3 关时 W3 不用。
LOT_W1 = 0.30
LOT_W2 = 0.30
LOT_W3 = 0.40

# ===================== 买入: 急跌 + 止跌形态 =====================
# 看信号根之前的 DOWN_BARS 根已收盘 1 分钟，满足其一即 impulse_ok:
#   至少 1 根阴；或窗口最高到末收回撤 >= IMPULSE_SUM；或末根 (开-收)/开 >= LAST_DROP。
DOWN_BARS = 2                  # 观察窗长度（不含当前信号根）
LAST_DROP = 0.002              # 0.2%，窗口末根阴跌
IMPULSE_SUM = 0.005            # 0.5%，窗口回撤
# 当前根 reversal_ok: 收红，或收盘>=上一根收盘，或下影占比 > 此值。
# 空仓且 BIAS<=L2 时允许跳过止跌开 L1；加 L2 必须止跌，且禁止现价低于均价加仓。
SHADOW_RATIO = 0.25

# ===================== 卖出（优先级见 strategy.py） =====================
# eod_flatten > stop_loss > trail_stop > take_profit > fade_sell > vwap_reversion
#
# fade_sell: BIAS >= BIAS_FADE；若尚未到 BIAS_FADE+0.004，还要求量比 <= VOL_GAP。
# 持仓后 1 分钟很少到 +1.5%，故用 5 分钟 p90 的 +0.8%。样本里常为 0 次。
BIAS_FADE = 0.008
VOL_GAP = 0.75
# vwap_reversion: BIAS >= 此值且该笔已盈利则平盈利笔。0 = 回到均价即可。
# 不再用 0~+0.2% 窄带（1 分钟容易一根跳过）。
REVERSION_BIAS = 0.00
# 仅作文档/备份上限；当前代码卖出不读此值。fade 量能确认的分界用 BIAS_FADE+0.004。
REVERSION_BIAS_HI = 0.012
# take_profit: 相对该笔成本 +1.0% 只平达标的 lot。未走到移动止盈启动带的日子靠它离场。
TAKE_PROFIT = 0.010
# trail_stop: 合并均价浮盈达到 ARM 后，自峰值回撤 GIVE 则全平。
# 用来接「先冲到 +1.4% 再单边砸到止损」的路径。ARM=0 关闭。
TRAIL_ARM = 0.012              # 1.2% 启动
TRAIL_GIVE = 0.005             # 0.5% 回撤
# stop_loss: 相对合并均价 -3.0% 清可卖仓，并当日 risk_skip 不再开。
# 不要收到 2%: 有的日子先深跌再回归（如 01-29），2% 会误杀。
STOP_LOSS = 0.030

# ===================== 流动性 / 涨跌停（univ_skip） =====================
# 近 ADV_DAYS 日均成交额低于此值（元）则当日不新开。该券近期通常 2 亿以上。
ADV_MIN = 5e7
ADV_DAYS = 5
# 实盘一档价差/中间价超过此值停开。0.003 = 0.30%。回测不查盘口。
SPREAD_MAX = 0.003
# 转债上市后涨跌幅约 +/-20%。相对昨收绝对涨跌达到 LIMIT_NEAR 则视为接近涨跌停，不新开。
LIMIT_PCT = 0.20
LIMIT_NEAR = 0.18

# ===================== 分笔 =====================
# True: L1/L2 分笔记账，止盈/回归可按 lot 平；止损仍按合并均价。
# 不要为此去接双浮仓 orders.py。SCALE_MAX=2 对应 L1+L2（L3 关闭时）。
SCALE_LOTS = True
SCALE_MAX = 2

# ===================== 终端参数面板 =====================
# bind 名 -> 本文件常量 -> 类型。注入发生在 runtime.init 的 _apply_panel()。
# 禁止上屏: account、STATE_FILE、LOG_DIR、STRATEGY_VER、_ORDER_*。
PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_bias_l1", "BIAS_L1", "float"),
    ("panel_bias_l2", "BIAS_L2", "float"),
    ("panel_bias_fade", "BIAS_FADE", "float"),
    ("panel_take_profit", "TAKE_PROFIT", "float"),
    ("panel_trail_arm", "TRAIL_ARM", "float"),
    ("panel_trail_give", "TRAIL_GIVE", "float"),
    ("panel_stop_loss", "STOP_LOSS", "float"),
    ("panel_adv_min", "ADV_MIN", "float"),
    ("panel_spread_max", "SPREAD_MAX", "float"),
    ("panel_scale_lots", "SCALE_LOTS", "bool"),
)

# ===================== 日志 / 历史 / 挂单超时 =====================
# 实盘心跳最短间隔（秒）。回测不走墙钟心跳。
LIVE_HEARTBEAT_SEC = 60
# download_history_data 最多回看日历日。上市日 2025-10-27，回测起点不要更早。
HIST_MAX_LOOKBACK_DAYS = 400
DOWNLOAD_HIST_LIVE = False     # 实盘一般不在 init 拉长历史
DOWNLOAD_HIST_BACKTEST = True  # 回测 init 拉 1m/1d，保证暖机
# 委托超时（秒）。PENDING_ORPHAN: 成交回报丢失后的孤儿仓处理窗口。
PENDING_TIMEOUT_SEC = 60
PENDING_ORPHAN_SEC = 60

# 状态文件必须绝对路径。{stock} 展开为 113699_SH，多实例不可共用同一 JSON。
STATE_FILE = r"D:\tradingStrategy\vwapbias_{stock}.json"
# 实盘事件日志目录。回测默认不写盘（LOG_IN_BACKTEST=False），看终端 log.txt。
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False

# 日志前缀与版本。init 行形如: VwapBias v0.9 init ...
STRATEGY_NAME = "VwapBias"
STRATEGY_VER = "v0.9"

# 券商委托状态码: 已成 / 已死（撤废拒等）。勿改除非柜台码表变了。
_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)

# 终端允许的周期名；download 起点按周期覆盖（该债 2025-10-27 上市）。
_VALID_PERIODS = (
    "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y",
)
_PERIOD_HIST_START = {
    "1m": "20251027",
    "1d": "20251027",
}
