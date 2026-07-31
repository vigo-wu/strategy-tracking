# === hongli/_header.py ===
# 作用: 策略总览注释（规则/风控/实盘与回测约定），无可执行代码
# 主要符号: 仅注释
# 拼接序: 1/16 | 上一部: - | 下一部: config.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
#
# HongliT v2.19 — 国金 QMT 终端模型交易。
#
# 主图标的: 561580.SH；PERIOD 见 config，或 "follow" 跟随主图周期。
# 界面: 选标的 + 账号，用实盘模式（非模拟）才会真正下单。
#
# 规则:
#   R-A   零浮仓 + 下轨 + J<=0     -> 买 Float A（FLOAT_A_BUDGET）
#   R-B   已有 A + 下轨 + J<=0 + 跌幅>=2.5%  -> 买 Float B（FLOAT_B_BUDGET），否则跳过
#   R-Sell 上轨 + J>=100                    -> 清全部浮仓 A/B
#   无 R1
#
# 风控档（USE_RISK_RULES=True 时任意 PERIOD 生效）:
#   - ENABLE_FLOAT_B=False      -> 关闭 R-B（仅 A）
#   - EXIT_AFTER                -> 延后 R-Sell/MaxHold 至 HHMMSS；""=关；仅日内
#   - STOP_LOSS_IGNORE_EXIT_AFTER -> 止损可早于 EXIT_AFTER 触发
#   - MAX_HOLD_DAYS             -> 软最长持仓（仅亏损）日历日；0=关
#   - MAX_HOLD_HARD_DAYS        -> 硬性到期强平（含盈利）；0=关
#   - COOLDOWN_BARS / LOSS      -> 卖出后冷却；根数 * PERIOD 时长 -> 墙钟截止
#   - NO_ENTRY_AFTER            -> 该时刻起禁止新开 R-A；""=关；仅日内
#   - STOP_LOSS                 -> 相对浮仓均价软止损；0=关
#   - REQUIRE_ABOVE_DAILY_MA    -> 仅当日线收盘 > MA(DAILY_MA_N) 时开仓
#   - DAILY_MA_N                -> 均线周期（如 10/20/60）
#
# 实盘委托安全 (v2.19):
#   - 浮仓状态仅成交后更新（pending）；DRY_RUN 即时；回测 passorder+即时
#   - init 用券商持仓对齐 JSON 浮仓（有 pending 则跳过）；BASE_SHARES 永不吸纳/卖出
#   - pending 超时先撤单；仅终态后清空（防双单）
#   - 15:00 后仍处理 pending（晚成交/撤单）
#   - 卖出部分成交保留当日剩余可卖（不标记 acted SELL）
#   - 冷却存墙钟时间（模型重启仍有效）
#   - 实盘 T+1: 卖量 = min(浮仓, m_nCanUseVolume)；可卖<100 则跳过并保留浮仓
#   - init 全包 try/except；历史下载起点钳制（VIP 最早日期）
#   - 实盘心跳 LIVE_HEARTBEAT_SEC，避免 UI 静默被当成已停
#   - 每根 handlebar 刷新 is_backtest；国金暖机->实盘追赶检测
#
# 回测安全 (v2.19):
#   - 运行中途 init 不得清空浮仓（曾导致孤儿双开 R-A）
#   - 影子 bt_held 跟踪 passorder 成交；有持仓则拦 R-A；卖出清空 held
#   - T+1: bt_locked = 当日买入（R-A/R-B）；仅可卖部分可卖；QMT 会跳过时绝不清仓
#   - 回测不读写 STATE_FILE（仅内存）
#
# 注意:
#   - 部署产物编码=GBK，首行 #coding:gbk
#   - 本策略只交易浮仓 A/B；账户另有底仓时设 BASE_SHARES
#   - DRY_RUN=True 只打印；False 才 passorder
#   - 回测前在 QMT 数据管理下载对应周期历史
#   - 模型交易: 期望 BACKTEST=False 且常驻；部署后需重新编译
