# FactorBand：中长线 / 波段，因子库组合四个槽位

**主题目录**：`factor_band/`｜**版本**：v1.70｜**形态**：单仓骨架 / 分笔多仓｜**运行**：国金 QMT 终端模型（见 §5）；本地 CSV 回放（见 §6）  
**参数默认值**：`factor_band/scripts/qmt/fband/config.py`（文档以该文件为准）。因子数字的唯一可信数据源（Single Source of Truth）是 `RECIPE.factor_params`；均线/MACD/ATR 窗的唯一可信数据源是 `RECIPE.structure`。交易终端实盘环境在「模型交易 → 新建/编辑策略交易」面板只覆盖开关 / 资金基数 / 固定金额 / 可部署比例 / 加仓开关（`fband/panel.xml`）；编辑器回测无注入时用 config。买入 `entry`、加仓 `scale_in`、卖出 `exit`、减仓 `scale_out` 四个槽位的条件抽象语法树、买点窗口、时间成本、加仓细节、`SCALE_LOTS`、阶梯止盈 `trail_stop.tiers`、`RECIPE.structure` 指标周期窗、`BOOK_STOCKS` 子配置 / `MA_TYPE`、路径仍只在 config（因子阈值和指标周期窗不上屏）。

分层契约见 [`docs/架构重构/架构.md`](./docs/架构重构/架构.md)；叶子与四个槽位草图见 [`docs/架构重构/Recipe分类.md`](./docs/架构重构/Recipe分类.md)。跟踪池、部署文件名与历史目录名不约束标的风格。

---

## 核心逻辑

FactorBand 是 **中长线 / 波段** 交易框架：日线主图找点、周线作跨周期过滤，持仓按笔记账，全池分档。标的以 `BOOK_STOCKS` 为准，不限定板块或分红风格。

信号不写死在过程式分支。叶子登记在因子库（`factors/catalog.py` 的 `LEAVES` + `factors/lib/<id>.py`），每个因子只回答条件是否成立，**不带开仓/平仓立场**。立场由四个槽位的条件抽象语法树赋予（`config.RECIPE`）。同一叶子可进多槽（例如 `pullback_vol` 可同时作开仓与加仓）。改四个槽位的引用、`and` / `or` / `not` 即换组合；格子只覆盖 `overrides.factor_params` / `overrides.structure`，不能改 AST。仓位门槛（`SCALE_ARM` / `scale_once` / 满槽 / 资金）不进因子库。登记 ≠ 已启用：`stop_loss` / `trail_stop` 仍在 `LEAVES`，现行默认配置的 `exit` 不引用。

同一根 K 四个槽位都求值，仓位仲裁优先级写死：`flat > reduce > add > open`。现行默认配置 `scale_out=false`（减仓未启用）。`weekly_bull` 只进日志，不是因子、不进四个槽位。

现行默认配置的组合（可改，不是框架定义）：

```text
entry:     ¬chase ∧ ¬vol_dry ∧ ¬w_bias ∧ ¬w_slope ∧ ¬weekly_bear ∧ pullback_vol
scale_in:  ¬vol_dry ∧ ¬w_bias ∧ ¬w_slope ∧ ¬weekly_bear
           ∧ ((pullback_vol ∧ ¬chase) ∨ plat_break ∨ w_macd_golden)
exit:      weekly_bear_confirm ∨ atr_stop ∨ atr_trail_stop ∨ time_force
           # stop_loss / trail_stop 已登记，默认 AST 不引用
scale_out: false
```

行情复权优先 `BOOK_STOCKS[code].dividend_type`，缺键回落全局 `DIVIDEND_TYPE`（`front_ratio`）。现行默认配置的 `BOOK_STOCKS` 是代码集合，未写 per-stock 覆盖，池内全部 `front_ratio`。公式「基本信息 → 复权方式」只影响看图，不叠加。改复权会改变均线与买卖点。**回测**时 `front`/`front_ratio` 自动改为：请求 `none` + `get_divid_factors` 做**时点前复权（PIT）**——`front_ratio` 用 `Πdr`，`front` 用价差事件序；日线/周线各自按 bar 标签日。实盘仍走 QMT `front*`。旧静态 CSV / 早期同结果 PIT 报告不可直接比。

主图 **日线**。实盘信号在收盘确认窗评估（`SIGNAL_CONFIRM_START`～`SIGNAL_CONFIRM_END`，默认 14:56:30–15:00:00），**尾盘成交窗**（`PENDING_EXEC_START`～`PENDING_EXEC_END`，默认 14:56:40–14:57:00）在连续竞价按 **卖一价限价**买入、买一价限价卖出（`prType=11`）。**14:57 起已是收盘集合竞价，本窗不再报单。** 错过则保留到下一交易日 **开盘兜底窗**（`OPEN_EXEC_START`～`OPEN_EXEC_END`，默认 09:30–09:45）按开盘价补成交（连续竞价走市价）。若收盘窗未跑到，开盘对上一根已收盘日兜底评估（`confirmed_eval_day < 上一完整交易日`），同日开盘窗可成交。回测与尾盘主路径对齐：信号日按**收盘价**成交；T+1 隔夜残留按下一日开盘价。  
实盘报单成功后**保留**信号 pending / 止盈元数据，**仅成交回调**后清除；废单/撤单后下一尾盘或开盘窗自动重试。  
**加仓成交后当日不再评新卖点**（`skip_sell_eval_day`，实盘同一根日 K 的后续 tick 也跳过）；已挂的 `pending_exit` 仍可成交。T+1 导致整仓/多笔只卖掉一部分时，若 `pending_exit.lot_ids` 还有剩余笔则**保留** pending，不因部分成交清掉。

**加仓**（`SCALE_ENABLE`）分两层：AST 回答「加仓叶子是否命中」；`_scale_gate` 回答「这一轮允不允许加」。门槛：任一笔峰值浮盈 `>= SCALE_ARM`（`0.03`，独立于 `trail_stop` 档1）、该笔持仓日 `>= SCALE_ARM_BARS`（`8`）、周线 MACD 柱 `>= SCALE_W_HIST_MIN`（`-0.01`）。现行默认配置的 `scale_in` 触发为下列**任一**：① 合格缩量回踩（`pullback_vol`，且受 `chase`）；② 日线收盘确认突破前期平台（`plat_break`）；③ 近两周周线 MACD 黄金交叉且柱放大（`w_macd_golden`）。破平台/金叉不受 `chase`。`SCALE_ONCE_PER_ROUND`（默认开）：**同一轮只加一次**——加仓成交后锁定，该只只要还剩任何一笔就不能再买；两笔都平掉后才能再开下一轮。金额：第二笔 30% cap；若该笔已是全池第三槽则吃剩余可部署资金。执行日若已触发卖点则**取消加仓、让路出场**（`scale_sell_block`）。全池最多 3 笔（`BOOK_LOT_MAX`），前两笔 50%/30%、第三笔吃剩余（约 20% cap）；满则 `book_lot_cap`。  
**多仓**（`SCALE_LOTS`，默认开）：记账在共用模块 `scripts/qmt_common/single/lots.py`。每笔自己的成本、峰值、持仓日数、时间成本豁免；`atr_stop` / `atr_trail_stop` / `time_force`（以及未进默认 exit 的 `stop_loss` / `trail_stop`）**按笔**出。`weekly_bear_confirm` 仍一次出清剩余各笔。第一笔可以先止盈，第二笔继续拿（本轮已加过则不再加第三笔）。券商可卖是合计 `can_use`，与 `lots=[id]` 可能对不齐；卖出时打 `SELL lot-can_use`，若目标笔当日新开且可卖来自旧仓则打 `WARN`。  
关 `SCALE_LOTS` 则均价合并、整仓出。

---

## 一、因子库与四个槽位

叶子登记在 `LEAVES`；默认盘启用哪些、如何 `and` / `or` / `not`，写在 `config.RECIPE` 四个槽位。均线/MACD/ATR 窗只读 `RECIPE.structure`（通过 `_structure_windows()` 读取）。阈值运行时读 `RECIPE.factor_params`（catalog 用 defaults 整表写入）。

周线均线为斐波那契 **MA5 / MA13 / MA34**（`RECIPE.structure.w_ma` 的 `fast` / `mid` / `life`，当前 5 / 13 / 34；`mid` 只给日志多头 `weekly_bull`）。周线取数 need 另钳原 MA55 暖机地板。价格均线**算法**优先取 `BOOK_STOCKS[code].ma_type`，缺省回落全局 `MA_TYPE`（`EMA` 或 `SMA`，默认 EMA）；成交量均量始终 SMA。文档与日志里的 `w_ma30` 字段实际是生命线 MA34。实盘与回测都只用**上一根已收盘周 K**（丢掉今天所在自然周，周五尾盘也看上周），对齐 QMT 回测 0000 原生 `1w`。

现行默认配置里，周线叶子是跨周期过滤（禁开 / 清仓），不是开仓前提：

| 叶子 | 槽 | 条件 | 现行默认 |
| :--- | :--- | :--- | :--- |
| `w_bias` | `entry` / `scale_in` 的 `not` | `(MA5_W − MA34_W) / MA34_W >= w_bias.hard` → 禁开 | `0.08` |
| `w_slope` | 同上 | 乖离 `< w_slope.low` 时，MA34 未连续 `slope_weeks` 周向上 → 禁开；执行日也会取消 pending | `0.02` / `2` |
| `weekly_bear` | 同上 | 收盘破 34 周，或 DIF/DEA 零轴下死叉：**当日即禁开**；执行日若仍空头则取消买入 pending | 无叶子阈值 |
| `weekly_bear_confirm` | `exit` | 连续 `days` 根日 K（信号日）仍空才挂 `pending_exit` | `2` |

开仓不要求 `weekly_bull`。多头（MA5>MA13 且 DIF>0 且红柱且生命线未明显走平）仅用于日志。

---

## 二、买入 / 加仓（现行默认配置）

下表与条件是现行默认 `entry` / `scale_in`，不是框架唯一形态。

### 开仓（`entry`）

空仓且 `entry` 命中：缩量回踩（`pullback_vol`），且不被 `chase` / `vol_dry` / `w_bias` / `w_slope` / `weekly_bear` 挡住。未命中时 reasons 为第一个挡住的叶子。

`pullback_vol`：

- 收盘靠近日线中线或慢线（`d_ma.mid` / `d_ma.slow`，当前 MA20 / MA60；容差 `pullback_vol.tol`，当前 ±2.5%；算法见标的 `ma_type` / `MA_TYPE`）。对应窗 `<=0` 则该条贴线关掉
- **连续** `pullback_vol.confirm_days` 日（当前 `2`）成交量 `<` 该日 `MAVOL{vol_n} × pullback_vol.ratio`（当前 `vol_n=10`、`ratio=0.9`）；贴均线只看当天

### 加仓（`scale_in` + `_scale_gate`）

已持仓、门槛通过、且本轮尚未加过仓时挂 `pending_entry add=True`，尾盘按**分档金额**成交（第二笔 30% cap；全池最后一槽吃剩余；错过则次日开盘补）。执行日 `scale_in` 顶层 `not` 叶子任一为真则撤买（`_scale_in_gate_hit`）。另有 `scale_once` / `scale_bars` / `scale_w_hist` / `scale_sell_block` / `scale_cap` / `book_lot_cap`。

| 触发 | 条件 | 日志码 |
| :--- | :--- | :--- |
| 缩量回踩 | 与开仓相同：近 MA20/60 且连续 N 日缩量；受 `chase` | `pullback_vol` |
| 日线破平台 | 回看 `plat_break.lookback` 日（当前 20，不含当日）高低点振幅 `(高-低)/低 <= plat_break.max_range`（当前 10%）；收盘严格站上该窗口最高价 × `(1+break_buf)`（当前 `break_buf=0`）；昨收仍在平台内 | `plat_break` |
| 周线 MACD 金叉放大 | 本周 DIF 上穿 DEA 且红柱比上周增长；或上周已金叉、本周红柱达到上周柱绝对值 × `w_macd_golden.hist_expand`（当前 1.2） | `w_macd_golden` |

`chase`：当日涨幅 ≥ `chase.max_pct`（当前 `0.05`）。拦开仓和回踩加仓；破平台 / 周线金叉不受。  
`vol_dry`：收盘 < MA20 且量 < MAVOL20 × `vol_dry.ratio`（当前 `0.60`）。对开仓和加仓都生效。  
额度已满 / 全池满 3 笔在仓位层：`buy_cap` / `scale_cap` / `book_lot_cap`（不进 AST）。

---

## 仓位：全池三笔分档（50% / 30% / 剩余资金）

跟踪池以 config `BOOK_STOCKS` 为准。N = 集合/字典长度。**一个** FactorBand 实例用 `run_time` 扫全池，**当天买单写入同一份账本**，冻结后按空档赋额。全池最多 `BOOK_LOT_MAX=3` 笔（开仓+加仓合计）。已从池中移除但仍持仓的票，其市值算其它股票，从 `E_s` 扣掉（仅 `BUDGET_BASE=equity`）；须先停掉旧多图实例，勿再并行打卡。

`BUDGET_BASE=equity`（默认）：`E_s = 账户总资产 − 其它股票市值`，`cap = CASH_RATIO×E_s`（20 万账户、0.90 → 约 18 万）。  
`BUDGET_BASE=fixed`：基数=`TRADE_BUDGET`，`cap = CASH_RATIO×TRADE_BUDGET`（10 万、0.90 → 9 万；空池三笔约 4.5 万 / 2.7 万 / 1.8 万）。其它股票市值不进基数。从较大 E_s 切到更小固定金额**不强制卖**，只停买。`k` / `book_mv` 只统计白名单。

| 槽位 | 占 cap | 谁来填 |
| :--- | :--- | :--- |
| 第 1 笔（大仓） | 50% ≈ 9 万 | **只开仓**（空池第一笔，或大仓卖掉后**另一只空仓**开仓） |
| 第 2 笔 | 30% ≈ 5.4 万 | 加仓，或大仓已在时别的标的新开 |
| 第 3 笔 | **剩余**（约 20% cap；`cap − 已占用`，并受现金、单只 room 限制） | 开仓或加仓；吸收前两笔 100 股取整未打满的余额 |

同标的一轮：开仓 1 笔 + 加仓最多 1 笔。加过仓后该只只要还剩任何仓就不再买（`scale_once`）；两笔都平掉才能再开。卖掉该只大仓、还留着 30% 时，大仓由**其他空仓标的**开仓补回（此时只剩 1 槽，该开仓吃剩余，约等于 50%），不是同一只再开。大仓空且只剩 1 个槽时不加仓，留给开仓。

账本路径 `BOOK_FILE`（默认 `D:\HlBandV7\hlband_book.json`），**不是**按标的分的 `STATE_FILE`。无买点也要打卡。

| 时间 | 做什么 |
| :--- | :--- |
| 14:56:30–14:56:40（`SIGNAL_CONFIRM` 起，至 `BOOK_FREEZE_CLOSE`=`PENDING_EXEC_START`） | 单实例 eval 轮全池打卡：买 / 加仓 / 卖 / 无信号 |
| 打卡数达到 N，或到冻结点 | 账本冻结；取数失败未打卡的票本窗不参与分档 |
| 14:56:40–14:57:00（`PENDING_EXEC`） | 按空档结果、卖一价限价下单（14:57 起不报） |
| 次日 09:30:00–09:30:30（`BOOK_FREEZE_OPEN`） | 隔夜残留打卡缓冲，到点冻结后再开盘成交 |

卖出不走分档，仍可在成交窗立即报。持股查询失败时先用本地账本（日志 `src=local`）。成交时 lot 写入 `book_frac`（空档标签 0.50 / 0.30 / 剩余档，第三笔金额可大于该档、标签不变；旧账本 0.25 收到 0.30）。卖掉哪一档下一笔就补哪一档。

实盘冻结后：

1. 券商快照：`E_s`、现金、白名单各股市值；整只卖出先虚拟减仓
2. 按各笔 `book_frac` 认占用槽；空档优先 50% 再 30% 再剩余档
3. **大仓空时开仓优先于加仓**；前两笔按 50%/30% 赋额；**全池最后一槽金额吃 `remain_free`**（标签仍是该空档的 0.50 / 0.30 / 剩余档）
4. 向下到 100 股。满 3 笔 `book_lot_cap`；加仓被大仓空档拦住则 `scale_cap`

回测无全账户账本：本图 `frac × TRADE_BUDGET`（10 万袖子 → 开仓 5 万或加仓 3 万；最后一槽按剩余比例）。第一笔按 50% 档，不会打满 cap。编辑器回测 / local_bt 非复利**不乘** `CASH_RATIO`；实盘固定金额会乘，同一组 10 万 / 0.90 回测第一笔 5 万、实盘约 4.5 万。

日志含：`frac=` `n_held=` `vacant=` `lot=` `why=`（`split` 分档成功 / `book_lot_cap` / `scale_cap` / `wait` / `book_fail`）。

`STATE_FILE` 仍带 `{stock}`，宇宙循环按票分文件，禁止再开多个 FactorBand 实例共写账本。

| 场景 | 开仓 | 加仓 |
| :--- | :--- | :--- |
| 空池 | 该只 50% | — |
| 该只已开未加 | 其他空仓 30%（若已是第三槽则吃剩余） | 该只 30%（仅一次；若已是第三槽则吃剩余） |
| 该只已加过仍有仓 | 其他空仓（大仓空则 50% / 最后一槽吃剩余） | 该只不下 |
| 卖掉 50% 还留 30% | 其他空仓开仓吃剩余（约补回大仓）；该只不下 | 该只不下 |
| 该只全平 | 可重新开仓 | — |
| 全池已 3 笔 | `book_lot_cap` | `book_lot_cap` |

### 增减跟踪标的

增减标的改 config `BOOK_STOCKS` 后 re-deploy，并**重启这一个**实例。N 以名单只数为准。不要用持股只数反推 N。不为 N 变化做再平衡。

| 动作 | 顺序 | 原因 |
| :--- | :--- | :--- |
| **增加**（3 → 4） | 改 `BOOK_STOCKS` → deploy → 重启这一实例 | 被删出名单但仍持有的票算其它股票，市值从 `E_s` 里减掉 |
| **减少**（3 → 2） | 先**清空**被删标的，再从名单去掉后 deploy 重启 | 未平就删名单，该市值变成其它股票、`E_s` 变小 |

---

## 三、卖出（现行默认配置）

下表是现行默认 `exit`。默认 AST **不含** `stop_loss` / `trail_stop`（叶子与 `factor_params` 仍在，网格可扫）。

| 卖点 | 条件 | 日志码 |
| :--- | :--- | :--- |
| ① ATR 止损 | 收盘 ≤ **该笔**成本 − `atr_stop.k`×ATR（当前 `k=2.0`、`atr.n=14`）；`atr.n<=0` 或 `k<=0` 关 | `atr_stop` |
| ② ATR 移动止盈 | **该笔**峰值相对成本 > `atr_trail_stop.k1`×ATR 武装（当前 `k1=2.0`）：收盘 ≤ 成本（保本）或峰值回撤 ≥ `k2`×ATR（当前 `k2=2.0`）；`k1<=0` 整条关；`k2<=0` 只保本 | `atr_trail_stop` |
| ③ 智能时间 | **该笔**持仓 **> `time_force.bars`**（当前 30）日：破日线 MA60 → 强制平仓；仍站上 MA60 且峰值浮盈 **< `time_force.arm`**（当前 3%）→ **立即强制平仓**；峰值已达门槛 → **不按日历强平**，交给 ATR 移动止盈 / 破 MA60 / 周线转空。`arm<=0` 关让路；`d_ma.slow<=0` 慢线地板不存在则整条不触发 | `time_force` |
| 兜底 | 周线转空且连续 `weekly_bear_confirm.days` 日 | `weekly_bear_confirm` |

优先级（挂 pending 主因，`exit` 的 or 短路）：`weekly_bear_confirm` > `atr_stop` > `atr_trail_stop` > `time_force`。

阶梯档位 `trail_stop.tiers`（峰值浮盈 = `(hold_peak − cost) / cost`）仅在把该叶子写进 `exit` 后才生效：

| 档 | 峰值浮盈 | 回撤容忍 | 利润底线 |
| :--- | :--- | :--- | :--- |
| 起步保护 | [3%, 6%) | 1.5% | — |
| 落袋为安 | [6%, 10%) | 3% | 至少带走 3% |
| 放鹰吃肉 | ≥ 10% | 4% | — |

持仓过除权除息：卖点评估前按 `get_divid_factors` 的 `dr` 缩放该票 `cost`/`hold_peak`（送转同步股数）；**配股默认按未认购**（股数不含配股部分），实盘用券商量延后判定认购后再加权成本；除权日当日开仓不缩放。回测若行情是**静态** `front`/`front_ratio`/`back`/`back_ratio`/`follow`（未走 PIT）则跳过；**PIT 激活**（回测 front*→none+因子）时与实盘一样缩放。本地回测操作明细同步写「送转」行，成交轮次按缩放后成本/股数计收益%。  
`SCALE_LOTS` 开启时，除 `weekly_bear_confirm` 一次出清外，其余卖点只平触发的那几笔（日志 `lots=[id]`）。  
买卖委托失败/T+1 skip 时**保留**对应 pending（及持仓元数据）；实盘报单成功亦保留至成交，废单后尾盘或次日开盘窗可重试。当日新买的笔 T+1 不可卖，不清仓状态。  
加仓成交后当日状态行可见 `skip_add_bar`，不应再出现新的 `pending_exit set`。T+1 部分成交且目标笔仍在应看到 `pending_exit keep after partial fill`。卖出前有 `SELL lot-can_use`；`risk=True` 时说明目标笔当日新开、可卖可能来自旧仓。

---

## 四、执行对照表

下表是现行默认组合，不是框架唯一形态。

| 步骤 | 维度 | 公式（当前配置） |
| :--- | :--- | :--- |
| 周线高位乖离 | MA5/MA34 | `(wMA5-wMA34)/wMA34 < 0.08` 才可开 |
| 低位斜率 | MA34 | 乖离 < 2% 时须连续 2 周向上 |
| 缩量回踩 | 位置+连续缩量 | 近 MA20/60 且连续 2 日 `vol < 当日MAVOL10×0.9` |
| 加仓 | 回踩 / 日线平台 / 周线 MACD | 再缩量回踩（受 chase），或收盘站上 20 日平台高，或近两周金叉且柱放大 |
| 无量阴跌 | MA20+20日量 | 收盘 < MA20 且 `vol < MAVOL20×0.60` → 禁开 |
| 填满仓位 | 全池最多 3 笔 50/30/剩余 | 前两笔 50%/30%；第三笔吃剩余可部署资金；满 3 笔 `book_lot_cap` |
| ATR 止损 | 成本 − k×ATR | `close ≤ cost − 2×ATR14`（威尔德；`atr.n<=0` 或 `k<=0` 关） |
| ATR 移动止盈 | 峰值相对成本 | 峰值相对成本 > 2×ATR 武装；收盘≤成本或回撤≥2×ATR（`k1`/`k2`；`k1<=0` 关；`k2<=0` 只保本） |
| 智能时间 | MA60 地板 | `> time_force.bars` 日：破 MA60 强平；站上且峰值 < `time_force.arm`（3%）立即强平；峰值≥arm 不按日历强平 |

---

## 五、QMT 运行

**部署**：`python factor_band/scripts/qmt/_deploy_qmt_gbk.py` → `FactorBand.py`，以及 `formulaLayout/FactorBand.xml`（产物文件名；不约束跟踪池风格）  
**报告**：`python factor_band/gen_report.py` → `report/`  
**片段**：`factor_band/scripts/qmt/fband/`（只改片段 / `panel.xml` 后 re-deploy，勿手改终端 GBK 或 `formulaLayout`）

实盘改参：模型交易里打开**这一个**策略实例，改「模拟下单 / 资金基数 / 固定金额 / 可部署比例 / 加仓开关」后确定再运行。跟踪池只数以 `BOOK_STOCKS` 长度为准，不要在面板改 N。增减标的改 `BOOK_STOCKS` 后 deploy 并重启这一实例。`TRADE_BUDGET` 在 `BUDGET_BASE=fixed` 时是实盘基数；`equity` 时实盘忽略此栏。编辑器回测仍用 config（一图一票，主图挂池内那只）。

实盘：**主图只当时钟**（建议挂不在 `BOOK_STOCKS` 的日线指数）；扫池只走 `run_time`（`1nSecond`，起始空串立即启动）。勿勾独立运行/简易运行。确认窗/开盘兜底才拉全量 K，盘中只处理 pending。账本同一轮先 eval 打卡再 exec 买入。上线前必须停掉旧多图实例。定时下单 `quickTrade=2`。

| 配置 | 当前值 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `False` | **默认真下单**；联调可改 `True` 或面板勾选「模拟下单」。C1–C11 通过前请保持模拟 |
| `LIVE_OHLCV_POLICY` | `"window"` | `window`=按时段分流；`always`=决策窗内每次当确认窗拉 K |
| `DIVIDEND_TYPE` | `"front_ratio"` | 池外/未写 `dividend_type` 时的复权缺省（仅 config）；池内未写字段回落此值 |
| `TRADE_BUDGET` | `100000` | 固定金额；实盘 `BUDGET_BASE=fixed` 时作基数；编辑器回测袖子 |
| `BUDGET_BASE` | `"equity"` | `equity`=总资产减其它市值；`fixed`=上面固定金额。面板下拉「总资产减其它 / 固定金额」 |
| `BOOK_STOCKS` | 见 config | 单实例监视名单；N=集合/字典长度；未写 `ma_type`/`dividend_type` 回落全局 |
| `BOOK_FILE` | `D:\HlBandV7\hlband_book.json` | 单实例信号账本；不是 STATE |
| `BOOK_FREEZE_CLOSE/OPEN` | `PENDING_EXEC_START` / `093030` | 收盘冻结=尾盘成交窗起点；开盘冻结保留 30s 打卡缓冲 |
| `CASH_RATIO` | `0.90` | 可部署比例（相对所选基数） |
| `BOOK_LOT_MAX` | `3` | 全池同时最多 3 笔（仅 config） |
| `LOT_OPEN_FRAC` | `0.50` | 开仓：大仓空则 50%；大仓已在且非最后一槽则 30%（仅 config） |
| `LOT_ADD_FRAC` | `0.30` | 第二笔 30%；全池最后一槽不锁此值，改吃剩余约 20% cap（仅 config） |
| `MA_TYPE` | `"EMA"` | 价格均线**算法**缺省：`EMA`/`SMA`；`BOOK_STOCKS[code].ma_type` 优先（仅 config；不是窗。量均始终 SMA，MACD 仍 EMA） |
| `d_ma.mid` / `d_ma.slow` | `20` / `60` | 日线中/慢均线（`RECIPE.structure`）；`<=0` 关该条（关中线同时关无量阴跌禁开；关慢线则 time_force 破线地板关掉） |
| `w_ma.fast` / `w_ma.mid` / `w_ma.life` | `5` / `13` / `34` | 周线快/中/生命线（`RECIPE.structure`）；`mid` 仅日志多头 |
| `macd.fast` / `macd.slow` / `macd.signal` | `12` / `26` / `9` | 周线 MACD 三窗（`RECIPE.structure`） |
| `atr.n` | `14` | 日线威尔德 ATR 窗（`RECIPE.structure`）；`<=0` 关 `atr_stop` / `atr_trail_stop` |
| `w_bias.hard` | `0.08` | 周线高位乖离禁开（相对 MA34；`RECIPE.factor_params`） |
| `w_slope.low` | `0.02` | 低位区阈值（配合斜率；`factor_params`） |
| `w_slope.slope_weeks` | `2` | 低位区生命线 MA34 连续向上周数（`factor_params`） |
| `weekly_bear_confirm.days` | `2` | 周线空头清仓须连续信号日数（`factor_params`） |
| `pullback_vol.tol` | `0.025` | 回踩均线容差（`factor_params`） |
| `pullback_vol.vol_n` / `ratio` | `10` / `0.9` | 买点均量窗口与缩量比例（`factor_params`） |
| `pullback_vol.confirm_days` | `2` | 缩量连续确认日；`<=0`/`1`=当天即可（`factor_params`） |
| `vol_dry.n` / `ratio` | `20` / `0.60` | 无量阴跌禁开（`factor_params`） |
| `trail_stop.tiers` | 见 §3 | 阶梯移动止盈（叶子仍在；默认 exit 不引用；`factor_params`） |
| `time_force.bars` | `30` | 时间成本起始持仓日；`<=0` 关整条（`factor_params`） |
| `time_force.arm` | `0.03` | 时间成本让路：峰值浮盈门槛；`<=0` 关让路（站上慢线也日历强平） |
| `SCALE_ENABLE` | `True` | 盈利后满足持仓日/周线柱，再缩量回踩或破平台或周线 MACD 金叉放大则加第二笔 |
| `SCALE_LOTS` | `True` | 分笔独立止盈止损；关则均价合并整仓出（仅 config，实盘勿改） |
| `SCALE_ONCE_PER_ROUND` | `True` | 同一轮只加一次；加过仓后该只须全平才能再开（仅 config） |
| `SCALE_ARM` | `0.03` | 峰值浮盈门槛（独立于 `trail_stop` 档1；仅 config） |
| `SCALE_ARM_BARS` | `8` | 第一笔持仓满 8 日才加仓（仅 config） |
| `SCALE_W_HIST_MIN` | `-0.01` | 周线 MACD 柱低于此值不加仓（仅 config） |
| `plat_break.lookback` | `20` | 日线平台回看日（不含当日；`factor_params`） |
| `plat_break.max_range` | `0.10` | 平台振幅上限 10%；更宽则不算平台（`factor_params`） |
| `plat_break.break_buf` | `0.0` | 突破缓冲：收盘须站上平台高 × `(1+buf)`（`factor_params`） |
| `w_macd_golden.hist_expand` | `1.2` | 上周金叉时本周红柱须放大至 1.2 倍（`factor_params`） |
| `stop_loss.pct` | `0.08` | 硬止损（相对该笔成本；`factor_params`；默认 exit 不引用） |
| `atr_stop.k` | `2.0` | ATR 止损倍数：收盘 ≤ 成本 − k×ATR（`factor_params`，浮点，可扫 `1.5`）；`<=0` 关 |
| `atr_trail_stop.k1` | `2.0` | ATR 移动武装：峰值相对成本 > k1×ATR（`factor_params`，浮点）；`<=0` 整条关 |
| `atr_trail_stop.k2` | `2.0` | ATR 移动回撤：已武装且峰值回撤 ≥ k2×ATR（`factor_params`，浮点）；`<=0` 只保本 |
| `chase.max_pct` | `0.05` | 追高禁开（`factor_params`） |
| `LIVE_CLOSE_CONFIRM` | `True` | 收盘确认 + 开盘兜底 |
| `SIGNAL_CONFIRM_START/END` | `145630` / `150000` | 用当日近似完整 K 确认信号；须早于尾盘成交 |
| `PENDING_EXEC_START/END` | `145640` / `145700` | 14:56:40 连续竞价尾盘限价：买挂卖一、卖挂买一；14:57 起不报 |
| `OPEN_EXEC_START/END` | `093000` / `094500` | 错过尾盘时次日开盘按开盘价补成交 |
| `STATE_FILE` | `D:\HlBandV7\hlband_{stock}.json` | 实盘状态；宇宙循环按票分文件 |
| `LOG_DIR` | `D:\HlBandV7\logs` | 实盘结构化日志根目录 |

日志确认 `HlBandV7 v1.70 init` 且 `UNIVERSE n=` 与 `book_stocks=` 一致、`chart=` 不在池内（建议指数）、`drive=timer`、`ohlcv_policy= window`、`DIVIDEND= per-stock`、`budget_base= equity`（或 `fixed`）、`cash_ratio= 0.9`、`BOOK_N=` 与名单只数一致后再挂实盘。策略交易下应另有 `panel applied ...` 与 `run_time _universe_on_timer` 行。只开**一个**实例写 `BOOK_FILE`；无信号也要打卡。切 live 后 `state loaded path=` 应为 `hlband_600350_SH.json` 等池内票，**不应**出现时钟指数后缀。10:00 心跳 `work=pending drive=timer`，无全池 `n1d=`；14:56 后每只 `phase=confirm`；15:00 后仍应有定时心跳直到确认结束。实盘买入应看到 `fill ... frac= n_held= vacant= lot= why=split base=`（持股查询失败备用为 `src=local`）；未冻结为 `why=wait`。空池第一笔 `frac=0.50`（equity 且 20 万账户约 9 万；fixed 且 10 万约 4.5 万），第二笔 `frac=0.30`，第三笔 `frac` 仍是空档 0.50/0.30/0.20、`lot` 接近 `cap - book_mv`。满 3 笔 `book_lot_cap`。本轮已加过仓后再出买点应 `scale_once`，无第 3 笔。验收：回测先见 `diag: ok`（主图挂池内一只）；买卖日志为 `@close=`（同日）或残留 `@open=`；买卖闭合、无孤儿仓。第一笔仍为 `pullback_vol`；加仓应为 `pullback_vol` / `plat_break` / `w_macd_golden`（状态行 `scale= True`），成交附近有 `lots now n=2`、`book_frac` 与 `skip sell eval after add fill`。加仓当日状态行 `sellR` 应含 `skip_add_bar`，且不应新挂卖点。本轮已加过仓后再出第一笔时，不应再出现 `BUY add`（可见 `scale_once` 或 `pending_entry cancel scale_once`）。执行日已触发卖点时应看到 `pending_entry cancel scale_sell_block` 且不出现 `BUY add`。只出一笔时应看到 `SELL ... lots=[1]` 且另一笔仍持有。卖出前应有 `SELL lot-can_use`；若 `BUY add` 后同日仍出现 `SELL lots=[2]`，看 `risk=True` 的 WARN（券商成交未必是第二笔）。T+1 部分成交应看到 `pending_exit keep after partial fill`。趋势仓满 30 日且峰值≥`time_force.arm`（3%）、仍站上 EMA60 时应看到 `time_force skip trend`，之后由 `atr_trail_stop` / `weekly_bear` / 破 EMA60 出场；磨人仓满 30 日即使仍站上 EMA60 也应看到 `time_force`（不再有 `time_force grace`）。

### 上线后确认事项（C1–C12）

代码审查无法关闭；**部署后按条打勾**。未通过不要把「模拟下单」关掉。每条记：日期、日志依据、通过/失败。

| 项 | 要点 | 否则 |
| :--- | :--- | :--- |
| C1 P0 非主图下单 | 模拟盘、主图池外指数，池内一只 `passorder` 品种 ≠ 主图，柜台/委托列表出现该代码 | 本方案不能实盘，退回一图一票 |
| C2 P0 `run_time` 真跑 | 策略交易切 live（不要只用编辑器运行）。10:00 `drive=timer`；15:05 仍有心跳；handlebar 不扫池 | 查独立运行、函数名、起始是否写成了 09:30。不恢复 tick 扫池 |
| C3 主图 | `chart=` 不在 `book_stocks=`；暖机无指数买卖点 | 改挂指数；不要改回 tick 驱动 |
| C4 旧多图已停 | 模型交易只留一个 FactorBand | 双打卡双下单 |
| C5 STATE 路径 | `hlband_<池内代码>_SH.json`，无指数后缀文件 | 停机，禁止按时钟 load |
| C6 取数分流 | 10:00 `work=pending` 无全池 `n1d=`；14:56 `phase=confirm`；15:00 后仍有心跳 | 查 `LIVE_OHLCV_POLICY` / 降级条件 |
| C7 尾盘分档 | 打卡齐 N 后 `why=split`，不是前几只一直 `wait` | 两轮 exec 未跑或 exec 重写了打卡 |
| C8 开盘/15:00 后 | `@open=` 兜底；15:05 仍有定时心跳 | C2 没跑或兜底条件不对 |
| C9 非主图行情/持仓 | 池内票 `diag: ok`；`_broker_position` 与柜台一致 | universe 未订阅或查询写死主图 |
| C10 复权 | 每只 `DIVIDEND=` 仍是 `BOOK_STOCKS` 的值，不是时钟 `follow` | 给每只补 `dividend_type` |
| C11 编辑器回测 | 主图挂池内一只，与改前同样 `diag: ok`、买卖闭合 | 三分支把回测误判成暖机 skip |
| C12 真下单 | C1–C11 通过且用户明确同意后才关模拟下单 | 未确认非主图报单就真下单 |

---

## 六、本地 CSV 回放

不经过国金编辑器，用 KlineDump 日线回放同一套拼接脚本。行情在 `tools/csv/<复权>/`，产物在 `factor_band/report/<复权>/`。**`front`/`front_ratio` 任务读 `csv/none` + `csv/divid_factors/*.json` 做时点前复权（PIT）**（`mode=diff` / `mode=ratio`），报告目录名仍为逻辑复权；日志指纹含 `pit=1 mode=…`。缺 none CSV 或因子 JSON 会硬失败——须先跑 KlineDump（`DUMP_STOCKS` 覆盖要测的票，`DIVIDEND_TYPES` 含 `none`，`DUMP_DIVID_FACTORS=True`）。启动：`python factor_band/local_bt_ui.py`。

目录、复权多选、按年批量、选股择优见 **[`local_bt.md`](./local_bt.md)**。买卖规则仍以本文 §1–§4 与 `config.py` 为准。现行默认四个槽位见 §核心逻辑；改 `RECIPE` 后以 config 为准。
