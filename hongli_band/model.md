# 红利板块波段策略：周线定方向，日线找买卖点

**主题目录**：`hongli_band/`｜**版本**：v1.25｜**形态**：单仓骨架 / 分笔多仓｜**运行**：国金 QMT 终端模型（见 §5）  
**参数默认值**：`hongli_band/scripts/qmt/hlband/config.py`。实盘在「模型交易 → 新建/编辑策略交易」面板覆盖（`hlband/panel.xml`）；编辑器回测无注入时用 config。阶梯止盈 `TRAIL_TIERS`、均线周期、路径仍只在 config。

---

## 核心逻辑

红利资产慢牛爬坡、震荡抗跌。脚本做 **周线估值/斜率过滤 + 日线缩量低吸 + 动态锁利卖出**。  
行情一律 **前复权**（`dividend_type=front_ratio`）。主图 **日线**；实盘信号在收盘确认窗评估 → **次日开盘窗**（`PENDING_EXEC_START`～`PENDING_EXEC_END`，默认 09:30–09:45）按开盘价成交；错过则保留到下一交易日开盘窗，**收盘确认窗不成交**。若收盘窗未跑到，开盘对上一根已收盘日兜底评估（`confirmed_eval_day < 上一完整交易日`）。  
实盘报单成功后**保留**信号 pending / 止盈元数据，**仅成交回调**后清除；废单/撤单后下一开盘窗自动重试。

**加仓**（`SCALE_ENABLE`）：已有仓且任一笔持仓期最大浮盈 `>= SCALE_ARM`（`0.03`，与阶梯止盈起步档对齐）时，再出现合格缩量回踩则加第二笔预算，最多同时 `SCALE_MAX=2` 笔。账户要能再拿出一笔预算。**移动止盈不让路加仓**（与 15 分钟均线策略不同）。  
**多仓**（`SCALE_LOTS`，默认开）：记账在共用模块 `scripts/qmt_common/single/lots.py`。每笔自己的成本、峰值、持仓日数、时间成本豁免；`stop_loss` / `trail_stop` / `time_force` **按笔**出。`weekly_bear` 仍一次出清剩余各笔。第一笔可以先止盈，第二笔继续拿。  
关 `SCALE_LOTS` 则均价合并、整仓出。

---

## 一、周线过滤

1. `(MA5_W - MA30_W) / MA30_W >= W_BIAS_HARD`（当前 `0.08`）→ 禁开（`w_bias_skip`）。
2. **低位斜率**：当周线乖离 `< W_BIAS_LOW`（当前 `0.02`）时，要求 **MA30 连续 `W_MA30_SLOPE_WEEKS` 周向上**（当前 `2`），否则禁开（`w_slope_skip`）；执行日也会取消 pending。
3. 周线空头（收盘破 30 周，或 DIF/DEA 零轴下死叉）：**当日即禁开**（`weekly_bear`）；持仓强制清仓须 **连续 `W_BEAR_CONFIRM_DAYS` 根日 K（信号日）仍空**（当前 `3`）才挂 `pending_exit`；执行日若仍空头则取消买入 pending。

说明：开仓不强制要求 `weekly_bull`；多头条件仅用于日志，禁开靠乖离/斜率/空头。

---

## 二、买入

### 买点 缩量回踩强支撑（`pullback_vol`）

- 收盘靠近 `MA20` 或 `MA60`（容差 `MA_TOUCH_TOL`，当前 ±2.5%）
- 成交量 `< MAVOL10 × VOL_PULLBACK_RATIO`（当前 `0.9`）

空仓时开第一笔；已持仓且满足加仓条件（见核心逻辑）时挂 `pending_entry add=True`，次日开盘再买一笔预算。加仓仍受下方全局拦截；周线空头 / 乖离 / 斜率 / 无量阴跌会取消加仓 pending。

### 全局拦截（任一则当日不开 / 可取消 pending）

| 条件 | 日志码 |
| :--- | :--- |
| 周线空头 | `weekly_bear` |
| 当日涨幅 ≥ `CHASE_MAX_PCT`（当前 `0.05`） | `chase_skip` |
| 收盘 < MA20 且量 < MAVOL20 × `VOL_DRY_RATIO`（当前 `0.60`） | `vol_dry_skip` |
| 周线高位乖离 / 低位斜率不达标 | `w_bias_skip` / `w_slope_skip` |

---

## 三、卖出

| 卖点 | 条件 | 日志码 |
| :--- | :--- | :--- |
| ① 阶梯移动止盈 | 按**该笔**峰值浮盈选档（见下表）；回撤超容忍或跌破利润底线 | `trail_stop` |
| ② 智能时间 | **该笔**持仓 **> `TIME_FORCE_BARS`**（当前 30）日：破日线 MA60 → 强制平仓；仍站上 MA60 → **豁免一次**并再观察 **`TIME_FORCE_GRACE_BARS`**（当前 5）日，期满强制平仓 | `time_force` |
| 兜底 | 收盘 ≤ **该笔**成本 × (1 − `STOP_LOSS`)（当前 `0.08`）/ 周线转空且连续 `W_BEAR_CONFIRM_DAYS` 日 | `stop_loss` / `weekly_bear` |

阶梯档位 `TRAIL_TIERS`（峰值浮盈 = `(hold_peak − cost) / cost`）：

| 档 | 峰值浮盈 | 回撤容忍 | 利润底线 |
| :--- | :--- | :--- | :--- |
| 起步保护 | [3%, 6%) | 1.5% | — |
| 落袋为安 | [6%, 10%) | 3% | 至少带走 3% |
| 放鹰吃肉 | ≥ 10% | 4% | — |

优先级（挂 pending 主因）：`weekly_bear` > `stop_loss` > `trail_stop` > `time_force`。  
`SCALE_LOTS` 开启时，除 `weekly_bear` 一次出清外，其余卖点只平触发的那几笔（日志 `lots=[id]`）。  
买卖委托失败/T+1 skip 时**保留**对应 pending（及持仓元数据）；实盘报单成功亦保留至成交，废单后开盘窗可重试。当日新买的笔 T+1 不可卖，不清仓状态。

---

## 四、执行对照表

| 步骤 | 维度 | 公式（当前配置） |
| :--- | :--- | :--- |
| 周线过滤 | MA5/MA30 | `(wMA5-wMA30)/wMA30 < 0.08` 才可开 |
| 低位斜率 | MA30 | 乖离 < 2% 时须连续 2 周向上 |
| 日线低吸 | 位置+10日量 | 近 MA20/60 且 `vol < MAVOL10×0.9` |
| 无量阴跌 | MA20+20日量 | 收盘 < MA20 且 `vol < MAVOL20×0.60` → 禁开 |
| 动态防御 | 阶梯峰值回撤 | 3%/6%/10% 档 → 回撤 1.5%/3%/4%（6% 档另有 3% 底线） |
| 智能时间 | MA60 缓冲 | `>30` 日：破 MA60 强平；站上则 +5 日豁免后强平 |
| 硬止损 | 成本 | `close ≤ cost×0.92` |

---

## 五、QMT 运行

**部署**：`python hongli_band/scripts/qmt/_deploy_qmt_gbk.py` → `HlBand.py` / `红利波段.py`，以及 `formulaLayout/HlBand.xml` / `红利波段.xml`  
**报告**：`python hongli_band/gen_report.py` → `report/`  
**片段**：`hongli_band/scripts/qmt/hlband/`（只改片段 / `panel.xml` 后 re-deploy，勿手改终端 GBK 或 `formulaLayout`）

实盘改参：模型交易里打开本策略实例，改「基础 / 周线 / 买入 / 卖出」后确定再运行。策略交易注入了单笔预算时**不再**读 `TRADE_BUDGET_BY_STOCK`（每个实例自己填预算）。编辑器回测仍用 config 与按标的覆盖。

| 配置 | 当前值 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `False` | 真下单；联调可改 `True` 只打日志 |
| `TRADE_BUDGET` | `25000` | 默认单笔预算；编辑器回测可被 `TRADE_BUDGET_BY_STOCK` 覆盖；策略交易以面板为准 |
| `CASH_RATIO` | `0.8` | 实盘可用现金占用比例 |
| `W_BIAS_HARD` | `0.08` | 周线高位乖离禁开 |
| `W_BIAS_LOW` | `0.02` | 低位区阈值（配合斜率） |
| `W_MA30_SLOPE_WEEKS` | `2` | 低位区 MA30 连续向上周数 |
| `W_BEAR_CONFIRM_DAYS` | `3` | 周线空头清仓须连续信号日数 |
| `MA_TOUCH_TOL` | `0.025` | 回踩均线容差 |
| `VOL_PULLBACK_N/RATIO` | `10` / `0.9` | 买点量能 |
| `VOL_DRY_N/RATIO` | `20` / `0.60` | 无量阴跌禁开 |
| `TRAIL_TIERS` | 见 §3 | 阶梯移动止盈（档3 回撤 4%） |
| `TIME_FORCE_BARS` | `30` | 时间成本起始持仓日 |
| `TIME_FORCE_GRACE_BARS` | `5` | 站上 MA60 时豁免观察日 |
| `SCALE_ENABLE` | `True` | 盈利后再出现缩量回踩加第二笔 |
| `SCALE_LOTS` | `True` | 分笔独立止盈止损；关则均价合并整仓出 |
| `SCALE_MAX` / `SCALE_ARM` | `2` / `0.03` | 最多 2 笔；浮盈 3% 后才允许加仓（仅 config） |
| `STOP_LOSS` | `0.08` | 硬止损（相对该笔成本） |
| `CHASE_MAX_PCT` | `0.05` | 追高禁开 |
| `LIVE_CLOSE_CONFIRM` | `True` | 收盘确认 + 开盘兜底 |
| `PENDING_EXEC_START/END` | `093000` / `094500` | 信号 pending 仅开盘窗按开盘价成交 |
| `STATE_FILE` | `D:\tradingStrategy\hlband_{stock}.json` | 实盘状态；按主图标的分文件 |
| `LOG_DIR` | `D:\tradingStrategy\logs` | 实盘结构化日志根目录 |

日志确认 `HlBand v1.25 init` 且 `scale= True`、`scale_lots= True`（`dMA=20/60`，`DRY_RUN=` 与面板或 config 一致）后再挂实盘。策略交易下应另有 `panel applied ...` 行。验收：回测先见 `diag: ok`；买卖闭合、无孤儿仓。加仓成交附近有 `lots now n=2`；只出一笔时应看到 `SELL ... lots=[1]` 且另一笔仍持有。
