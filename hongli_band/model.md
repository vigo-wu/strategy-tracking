# 红利板块波段策略：周线定方向，日线找买卖点

**主题目录**：`hongli_band/`｜**版本**：v1.44｜**形态**：单仓骨架 / 分笔多仓｜**运行**：国金 QMT 终端模型（见 §5）  
**参数默认值**：`hongli_band/scripts/qmt/hlband/config.py`（文档以该文件为准）。实盘在「模型交易 → 新建/编辑策略交易」面板只覆盖开关 / 预算袖子 / 硬风控（`hlband/panel.xml`）；编辑器回测无注入时用 config。买点窗口、时间成本、加仓细节、`SCALE_LOTS`、`BOOK_N`、阶梯止盈 `TRAIL_TIERS`、均线周期、路径仍只在 config。

---

## 核心逻辑

红利资产慢牛爬坡、震荡抗跌。脚本做 **周线估值/斜率过滤 + 日线缩量低吸 + 动态锁利卖出**。  
行情一律 **前复权**（`dividend_type=front_ratio`）。主图 **日线**；实盘信号在收盘确认窗评估（默认 14:56 起），**尾盘成交窗**（`PENDING_EXEC_START`～`PENDING_EXEC_END`，默认 14:56:00–14:57:00）在连续竞价最后一分钟按 **卖一价限价**买入、买一价限价卖出（`prType=11`）。**14:57 起已是收盘集合竞价，本窗不再报单。** 错过则保留到下一交易日 **开盘兜底窗**（`OPEN_EXEC_START`～`OPEN_EXEC_END`，默认 09:30–09:45）按开盘价补成交（连续竞价走市价）。若收盘窗未跑到，开盘对上一根已收盘日兜底评估（`confirmed_eval_day < 上一完整交易日`），同日开盘窗可成交。回测与尾盘主路径对齐：信号日按**收盘价**成交；T+1 隔夜残留按下一日开盘价。  
实盘报单成功后**保留**信号 pending / 止盈元数据，**仅成交回调**后清除；废单/撤单后下一尾盘或开盘窗自动重试。  
**加仓成交后当日不再评新卖点**（`skip_sell_eval_day`，实盘同一根日 K 的后续 tick 也跳过）；已挂的 `pending_exit` 仍可成交。T+1 导致整仓/多笔只卖掉一部分时，若 `pending_exit.lot_ids` 还有剩余笔则**保留** pending，不因部分成交清掉。

**加仓**（`SCALE_ENABLE`）：已有仓且同时满足门槛：任一笔峰值浮盈 `>= SCALE_ARM`（`0.03`）、该笔持仓日 `>= SCALE_ARM_BARS`（`8`）、周线 MACD 柱 `>= SCALE_W_HIST_MIN`（`-0.01`）。第二笔触发为下列**任一**：① 合格缩量回踩（`pullback_vol`，回踩加仓）；② 日线收盘确认突破前期平台（`plat_break`，破平台推仓）；③ 近两周周线 MACD 黄金交叉且柱放大（`w_macd_golden`）。最多 `SCALE_MAX=2` **同时持有**。`SCALE_ONCE_PER_ROUND`（默认开）：**同一轮持仓只加一次**——加仓成交后锁定，第一笔止盈后空仓前不再用另一种信号再加；整轮空仓后下一轮可再加。执行日若已触发卖点则**取消加仓、让路出场**。开仓与加仓共用当天共享账本均分额度（§仓位）；账户或单标的顶满则 `buy_cap` / `scale_cap`。回踩加仓仍受 `chase_skip`；破平台/金叉不受（突破日允许较大涨幅）。**移动止盈不让路加仓信号评估**（与 15 分钟均线策略不同），但执行日卖点优先。  
**多仓**（`SCALE_LOTS`，默认开）：记账在共用模块 `scripts/qmt_common/single/lots.py`。每笔自己的成本、峰值、持仓日数、时间成本豁免；`stop_loss` / `trail_stop` / `time_force` **按笔**出。`weekly_bear` 仍一次出清剩余各笔。第一笔可以先止盈，第二笔继续拿（本轮已加过则不再加第三笔）。券商可卖是合计 `can_use`，与 `lots=[id]` 可能对不齐；卖出时打 `SELL lot-can_use`，若目标笔当日新开且可卖来自旧仓则打 `WARN`。  
关 `SCALE_LOTS` 则均价合并、整仓出。

---

## 一、周线过滤

周线均线为斐波那契 **MA5 / MA13 / MA34（生命线 `W_MA_LIFE`）/ MA55（取数暖机）**。文档与日志里的 `w_ma30` 字段实际是生命线 MA34。

1. `(MA5_W - MA34_W) / MA34_W >= W_BIAS_HARD`（当前 `0.08`）→ 禁开（`w_bias_skip`）。
2. **低位斜率**：当周线乖离 `< W_BIAS_LOW`（当前 `0.02`）时，要求 **MA34 连续 `W_MA30_SLOPE_WEEKS` 周向上**（当前 `2`；常量名历史兼容，比较对象是生命线），否则禁开（`w_slope_skip`）；执行日也会取消 pending。
3. 周线空头（收盘破 34 周，或 DIF/DEA 零轴下死叉）：**当日即禁开**（`weekly_bear`）；持仓强制清仓须 **连续 `W_BEAR_CONFIRM_DAYS` 根日 K（信号日）仍空**（当前 `2`）才挂 `pending_exit`；执行日若仍空头则取消买入 pending。

说明：开仓不强制要求 `weekly_bull`；多头（MA5>MA13 且 DIF>0 且红柱且生命线未明显走平）仅用于日志，禁开靠乖离/斜率/空头。

---

## 二、买入

### 买点 缩量回踩强支撑（`pullback_vol`）

- 收盘靠近 `MA20` 或 `MA60`（容差 `MA_TOUCH_TOL`，当前 ±2.5%）
- 成交量 `< MAVOL10 × VOL_PULLBACK_RATIO`（当前 `0.9`）

空仓时开第一笔（`pullback_vol`）。已持仓且门槛+触发都满足、且本轮尚未加过仓时挂 `pending_entry add=True`，尾盘按**当天买单均分**后的金额成交（错过则次日开盘补）。加仓仍受下方全局拦截（破平台/金叉不受 `chase_skip`）；另有 `scale_once` / `scale_bars` / `scale_w_hist` / `scale_sell_block` / `scale_cap`。周线空头 / 乖离 / 斜率 / 无量阴跌会取消加仓 pending。

### 加仓触发（持仓中，回踩或破平台任一）

| 触发 | 条件 | 日志码 |
| :--- | :--- | :--- |
| 缩量回踩 | 与第一笔相同：近 MA20/60 且缩量；受 `chase_skip` | `pullback_vol` |
| 日线破平台 | 回看 `SCALE_PLAT_LOOKBACK` 日（当前 20，不含当日）高低点振幅 `(高-低)/低 <= SCALE_PLAT_MAX_RANGE`（当前 10%）；收盘站上该窗口最高价（可加 `SCALE_PLAT_BREAK_BUF`）；昨收仍在平台内 | `plat_break` |
| 周线 MACD 金叉放大 | 本周 DIF 上穿 DEA 且红柱比上周增长；或上周已金叉、本周红柱达到上周柱绝对值 × `SCALE_W_HIST_EXPAND_RATIO`（当前 1.2） | `w_macd_golden` |

### 全局拦截（任一则当日不开 / 可取消 pending）

| 条件 | 日志码 |
| :--- | :--- |
| 周线空头 | `weekly_bear` |
| 当日涨幅 ≥ `CHASE_MAX_PCT`（当前 `0.05`） | `chase_skip` |
| 收盘 < MA20 且量 < MAVOL20 × `VOL_DRY_RATIO`（当前 `0.60`） | `vol_dry_skip` |
| 周线高位乖离 / 低位斜率不达标 | `w_bias_skip` / `w_slope_skip` |
| 账户或单标的额度已满 | `buy_cap` / `scale_cap` |

`chase_skip` 拦第一笔和回踩加仓；破平台 / 周线金叉加仓不受 5% 涨幅禁开。其余拦截对加仓同样生效。

---

## 仓位：共享账本均分 + 单标的 50% 硬顶

跟踪池以 config `BOOK_STOCKS` 为准（默认 600350 / 601398 / 601939 / 513530）。N = 名单长度。四图各评各的票，但**当天所有买单先写入同一份账本**，冻结后再均分可部署资金。不要用「谁先报谁先填满 50%」。

账户可以混持其它股票。`k` / `book_mv` **只统计白名单**。策略净值：

`E_s = 账户总资产 − 其它股票市值`（约等于现金 + 池内市值）。`CASH_RATIO` 与 `MAX_NAME_FRAC` 都相对 `E_s`，不是整户。本策略盈亏进现金后 `E_s` 自动变大；用现金买了其它股票则 `E_s` 变小。不留 `CASH_KEEP`。

账本路径 `BOOK_FILE`（默认 `D:\tradingStrategy\hlband_book.json`），**不是**按标的分的 `STATE_FILE`。无买点也要打卡，否则分不清「没信号」还是「那张图没起来」。

| 时间 | 做什么 |
| :--- | :--- |
| 14:56:00–14:56:30（`BOOK_FREEZE_CLOSE`） | 每图打卡：买 / 加仓 / 卖 / 无信号 |
| 打卡数达到 N，或到冻结点 | 账本冻结；迟到的图本窗不参与均分 |
| 14:56:30–14:57:00 | 按均分结果、卖一价限价下单（14:57 起不报） |
| 次日 09:30–09:32（`BOOK_FREEZE_OPEN`） | 隔夜残留同样打卡冻结，再开盘成交 |

卖出不走均分，仍可在成交窗立即报。持股查询失败时先用本地账本：共享文件里上次成功的持仓快照 + 各图 `STATE_FILE` + 本图内存仓（日志 `src=local`）。若这些都没有，才 `book_fail` 本窗不买、保留 pending，不当空仓去打满。

实盘（`EQUAL_SPLIT=True`）冻结后：

1. 用券商快照：`E_s`、现金、白名单各股市值、其它股票市值；账本里的整只卖出先虚拟减仓
2. `k_after` = 白名单现持股只数 + 本窗新开只数；`empty = max(0, N - k_after)`；`reserve = empty × MIN_LOT`
3. 可分池子 `pool = min(CASH_RATIO×E_s − book_mv − reserve, 现金)`
4. 当天每只有买单的标的均分 `pool`；谁先碰到 `MAX_NAME_FRAC×E_s`（默认 50%）就把剩余再分给还没碰到的（水位法）
5. 向下到 100 股。单只已到 50% 则 `buy_cap` / `scale_cap`

`SCALE_MAX` 仍为 2。回测无全账户账本，仍用 `TRADE_BUDGET`。信号仍走单仓 + `SCALE_LOTS`。

日志含：`E=` `N=` `k=` `k_other=` `reserve=` `lot=` `book_mv=` `other_mv=` `name_mv=` `n_buy=` `split=` `why=` `src=`（`split` 均分 / `wait` 未冻结 / `book_fail` 无本地账本；`src=broker|local`）。

`STATE_FILE` 仍带 `{stock}`，禁止多实例共写同一状态 JSON。

20 万袖子、`MIN_LOT=2万` 时 **N ≤ 9**。空账户、只有新开、另留没信号的空仓预留：

| 当天新开只数 | 预留 | 可分池子 | 每只（均分，且 ≤10 万） |
| ---: | ---: | ---: | :--- |
| 1 | 6 万 | 13 万 | **10 万**（50% 顶） |
| 2 | 4 万 | 15 万 | **7.5 万** |
| 3 | 2 万 | 17 万 | **约 5.67 万** |
| 4 | 0 | 19 万 | **4.75 万** |

更怕集中可把面板 `MAX_NAME_FRAC` 改成 `0.40`。

### 增减跟踪标的

所有实例的 `BOOK_STOCKS` / `CASH_RATIO` / `MIN_LOT` / `MAX_NAME_FRAC` **必须一致**。N 以名单只数为准（`budget._cfg_book_n` 忽略面板/config 里的 `BOOK_N` 除非名单为空）。不要用持股只数反推 N。不为 N 变化做再平衡。

| 动作 | 顺序 | 原因 |
| :--- | :--- | :--- |
| **增加**（4 → 5） | 先改 `BOOK_STOCKS` 并四图 re-deploy，再挂新图 | 空仓预留立刻多 1×`MIN_LOT`；被删出名单但仍持有的票算其它股票，市值从 `E_s` 里减掉 |
| **减少**（4 → 3） | 先停并**清空**被删标的，再从名单去掉并改 `BOOK_N` | 未平就删名单，该市值变成其它股票、`E_s` 变小 |

---

## 三、卖出

| 卖点 | 条件 | 日志码 |
| :--- | :--- | :--- |
| ① 阶梯移动止盈 | 按**该笔**峰值浮盈选档（见下表）；回撤超容忍或跌破利润底线 | `trail_stop` |
| ② 智能时间 | **该笔**持仓 **> `TIME_FORCE_BARS`**（当前 = 日线 MA60/2 = 30）日：破日线 MA60 → 强制平仓；仍站上 MA60 且峰值浮盈 **< `TIME_FORCE_MIN_RET`**（当前 3%，对齐阶梯止盈起步档）→ **豁免一次**并再观察 **`TIME_FORCE_GRACE_BARS`**（当前 5）日，期满强制平仓；峰值已达门槛 → **不按日历强平**，交给移动止盈 / 破 MA60 / 周线转空 | `time_force` |
| 兜底 | 收盘 ≤ **该笔**成本 × (1 − `STOP_LOSS`)（当前 `0.08`）/ 周线转空且连续 `W_BEAR_CONFIRM_DAYS` 日 | `stop_loss` / `weekly_bear` |

阶梯档位 `TRAIL_TIERS`（峰值浮盈 = `(hold_peak − cost) / cost`）：

| 档 | 峰值浮盈 | 回撤容忍 | 利润底线 |
| :--- | :--- | :--- | :--- |
| 起步保护 | [3%, 6%) | 1.5% | — |
| 落袋为安 | [6%, 10%) | 3% | 至少带走 3% |
| 放鹰吃肉 | ≥ 10% | 4% | — |

优先级（挂 pending 主因）：`weekly_bear` > `stop_loss` > `trail_stop` > `time_force`。  
`SCALE_LOTS` 开启时，除 `weekly_bear` 一次出清外，其余卖点只平触发的那几笔（日志 `lots=[id]`）。  
买卖委托失败/T+1 skip 时**保留**对应 pending（及持仓元数据）；实盘报单成功亦保留至成交，废单后尾盘或次日开盘窗可重试。当日新买的笔 T+1 不可卖，不清仓状态。  
加仓成交后当日状态行可见 `skip_add_bar`，不应再出现新的 `pending_exit set`。T+1 部分成交且目标笔仍在应看到 `pending_exit keep after partial fill`。卖出前有 `SELL lot-can_use`；`risk=True` 时说明目标笔当日新开、可卖可能来自旧仓。

---

## 四、执行对照表

| 步骤 | 维度 | 公式（当前配置） |
| :--- | :--- | :--- |
| 周线过滤 | MA5/MA34 | `(wMA5-wMA34)/wMA34 < 0.08` 才可开 |
| 低位斜率 | MA34 | 乖离 < 2% 时须连续 2 周向上 |
| 日线低吸 | 位置+10日量 | 近 MA20/60 且 `vol < MAVOL10×0.9`（仅第一笔） |
| 顺势加仓 | 回踩 / 日线平台 / 周线 MACD | 再缩量回踩，或收盘站上 20 日平台高，或近两周金叉且柱放大 |
| 无量阴跌 | MA20+20日量 | 收盘 < MA20 且 `vol < MAVOL20×0.60` → 禁开 |
| 填满仓位 | 跟踪池均分 | 当天买单均分 `pool`；单只 ≤50%E；顶满 `buy_cap`/`scale_cap` |
| 动态防御 | 阶梯峰值回撤 | 3%/6%/10% 档 → 回撤 1.5%/3%/4%（6% 档另有 3% 底线） |
| 智能时间 | MA60 地板 | `>MA60/2` 日：破 MA60 强平；站上且峰值<3% 则 +5 日豁免后强平；峰值≥3% 不按日历强平 |
| 硬止损 | 成本 | `close ≤ cost×0.92` |

---

## 五、QMT 运行

**部署**：`python hongli_band/scripts/qmt/_deploy_qmt_gbk.py` → `HlBand.py` / `红利波段.py`，以及 `formulaLayout/HlBand.xml` / `红利波段.xml`  
**报告**：`python hongli_band/gen_report.py` → `report/`  
**片段**：`hongli_band/scripts/qmt/hlband/`（只改片段 / `panel.xml` 后 re-deploy，勿手改终端 GBK 或 `formulaLayout`）

实盘改参：模型交易里打开本策略实例，改「模拟下单 / 预算袖子 / 高位禁开 / 追高 / 硬止损 / 加仓开关」后确定再运行。可部署比例、空仓最小金额、单标的上限须**所有实例填相同值**。跟踪池只数以 `BOOK_STOCKS` 长度为准，不要在面板改 N。增减标的改 `BOOK_STOCKS` 后 re-deploy。`TRADE_BUDGET` 仅回测回落；策略交易注入了该值时**不再**读 `TRADE_BUDGET_BY_STOCK`。编辑器回测仍用 config 与按标的覆盖。

| 配置 | 当前值 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `False` | **默认真下单**；联调可改 `True` 或面板勾选「模拟下单」 |
| `TRADE_BUDGET` | `50000` | 回测单笔回落；实盘填满不锁此值；可被 `TRADE_BUDGET_BY_STOCK` 覆盖 |
| `BOOK_STOCKS` | 四只默认名单 | 跟踪池白名单（仅 config）；k / 市值只统计这些 |
| `BOOK_N` | `4` | 仅 config 回落；有 `BOOK_STOCKS` 时 N=名单只数（面板不上屏） |
| `DYNAMIC_BUDGET` | `True` | 实盘动态仓位；回测仍用 `TRADE_BUDGET`（仅 config） |
| `EQUAL_SPLIT` | `True` | 当天多只买单写入 `BOOK_FILE`，冻结后均分（仅 config） |
| `BOOK_FILE` | `D:\tradingStrategy\hlband_book.json` | 四图共享信号账本；不是 STATE |
| `BOOK_FREEZE_CLOSE/OPEN` | `145630` / `093200` | 打卡截止；到点或打卡满 N 即冻结（14:57 竞价前） |
| `CASH_RATIO` | `0.95` | 可部署比例（相对 E_s=总资产−其它市值） |
| `MIN_LOT` | `20000` | 每只空仓预留的最小进场金额（元） |
| `MAX_NAME_FRAC` | `0.50` | 单标的市值上限占 E_s；更怕集中可改 `0.40` |
| `W_MA_FAST/MID/LIFE/SLOW` | `5/13/34/55` | 周线均线；生命线=34（仅 config） |
| `W_BIAS_HARD` | `0.08` | 周线高位乖离禁开（相对 MA34） |
| `W_BIAS_LOW` | `0.02` | 低位区阈值（配合斜率；仅 config） |
| `W_MA30_SLOPE_WEEKS` | `2` | 低位区生命线 MA34 连续向上周数（仅 config） |
| `W_BEAR_CONFIRM_DAYS` | `2` | 周线空头清仓须连续信号日数（仅 config） |
| `MA_TOUCH_TOL` | `0.025` | 回踩均线容差（仅 config） |
| `VOL_PULLBACK_N/RATIO` | `10` / `0.9` | 买点量能（仅 config） |
| `VOL_DRY_N/RATIO` | `20` / `0.60` | 无量阴跌禁开（仅 config） |
| `TRAIL_TIERS` | 见 §3 | 阶梯移动止盈（档3 回撤 4%） |
| `TIME_FORCE_BARS` | `D_MA_SLOW//2`（30） | 时间成本起始持仓日（半段慢均线，不是最长持仓；仅 config） |
| `TIME_FORCE_GRACE_BARS` | `5` | 未武装止盈且站上 MA60 时豁免观察日（仅 config） |
| `TIME_FORCE_MIN_RET` | `0.03` | 峰值浮盈达此值则不按日历强平（对齐阶梯起步档；仅 config） |
| `SCALE_ENABLE` | `True` | 盈利后满足持仓日/周线柱，再缩量回踩或破平台或周线 MACD 金叉放大则加第二笔 |
| `SCALE_LOTS` | `True` | 分笔独立止盈止损；关则均价合并整仓出（仅 config，实盘勿改） |
| `SCALE_ONCE_PER_ROUND` | `True` | 同一轮持仓只加一次；平掉第一笔后空仓前不再加（仅 config） |
| `SCALE_MAX` / `SCALE_ARM` | `2` / `0.03` | 同时最多 2 笔；峰值浮盈 3% 后才允许加仓（仅 config） |
| `SCALE_ARM_BARS` | `8` | 第一笔持仓满 8 日才加仓（仅 config） |
| `SCALE_W_HIST_MIN` | `-0.01` | 周线 MACD 柱低于此值不加仓（仅 config） |
| `SCALE_PLAT_LOOKBACK` | `20` | 日线平台回看日（不含当日；仅 config） |
| `SCALE_PLAT_MAX_RANGE` | `0.10` | 平台振幅上限 10%；更宽则不算平台（仅 config） |
| `SCALE_W_HIST_EXPAND_RATIO` | `1.2` | 上周金叉时本周红柱须放大至 1.2 倍（仅 config） |
| `STOP_LOSS` | `0.08` | 硬止损（相对该笔成本） |
| `CHASE_MAX_PCT` | `0.05` | 追高禁开 |
| `LIVE_CLOSE_CONFIRM` | `True` | 收盘确认 + 开盘兜底 |
| `SIGNAL_CONFIRM_START/END` | `145600` / `160000` | 用当日近似完整 K 确认信号；与尾盘成交窗重叠 |
| `PENDING_EXEC_START/END` | `145600` / `145700` | 14:56 连续竞价尾盘限价：买挂卖一、卖挂买一；14:57 起不报 |
| `OPEN_EXEC_START/END` | `093000` / `094500` | 错过尾盘时次日开盘按开盘价补成交 |
| `STATE_FILE` | `D:\tradingStrategy\hlband_{stock}.json` | 实盘状态；按主图标的分文件 |
| `LOG_DIR` | `D:\tradingStrategy\logs` | 实盘结构化日志根目录 |

日志确认 `HlBand v1.44 init` 且 `BOOK_N= 4` 与 `book_stocks= 513530.SH,600350.SH,601398.SH,601939.SH`（逗号名单）一致、`cash_ratio= 0.95`、`min_lot= 20000`、`max_name_frac= 0.5`、`dynamic_budget= True`、`equal_split= True`、`book_freeze= 145630/093200`、`close_exec= 145600-145700`、`open_exec= 093000-094500`、`scale= True`、`scale_lots= True`、`scale_once= True`、`scale_arm_bars= 8`、`scale_plat= 20/0.10`、`scale_w_expand= 1.2`、`time_force_min_ret= 0.03`、`wMA= 5/13/34`（`dMA=20/60`，`DRY_RUN=False` 与面板或 config 一致）后再挂实盘。策略交易下应另有 `panel applied ...` 行。四图须都能写 `BOOK_FILE`；无信号也要打卡。实盘买入应看到 `fill ... k_other= other_mv= n_buy= split= why=split`（持股查询失败备用为 `src=local`）；未冻结为 `why=wait`。顶满应看到 `buy_cap` / `scale_cap`。验收：回测先见 `diag: ok`；买卖日志为 `@close=`（同日）或残留 `@open=`；买卖闭合、无孤儿仓。第一笔仍为 `pullback_vol`；加仓应为 `pullback_vol` / `plat_break` / `w_macd_golden`（状态行 `scale= True`），成交附近有 `lots now n=2` 与 `skip sell eval after add fill`。加仓当日状态行 `sellR` 应含 `skip_add_bar`，且不应新挂卖点。本轮已加过仓后再出第一笔时，不应再出现 `BUY add`（可见 `scale_once` 或 `pending_entry cancel scale_once`）。执行日已触发卖点时应看到 `pending_entry cancel scale_sell_block` 且不出现 `BUY add`。只出一笔时应看到 `SELL ... lots=[1]` 且另一笔仍持有。卖出前应有 `SELL lot-can_use`；若 `BUY add` 后同日仍出现 `SELL lots=[2]`，看 `risk=True` 的 WARN（券商成交未必是第二笔）。T+1 部分成交应看到 `pending_exit keep after partial fill`。趋势仓满 30 日且峰值≥3%、仍站上 MA60 时应看到 `time_force skip trend`，之后由 `trail_stop` / `weekly_bear` / 破 MA60 出场；磨人仓仍应看到 `time_force grace`。
