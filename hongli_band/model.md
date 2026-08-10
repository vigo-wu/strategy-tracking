# 红利板块波段策略：周线定方向，日线找买卖点

**主题目录**：`hongli_band/`｜**版本**：v1.20｜**运行**：国金 QMT 终端模型（见 §5）  
**参数真源**：`hongli_band/scripts/qmt/hlband/config.py`（本文数值与之对齐；改参只改 config 后 re-deploy）

---

## 核心逻辑

红利资产慢牛爬坡、震荡抗跌。脚本做 **周线估值/斜率过滤 + 日线缩量低吸 + 动态锁利卖出**。  
行情一律 **前复权**（`dividend_type=front_ratio`）。主图 **日线**；实盘信号在收盘确认窗评估 → **次日开盘窗**（`PENDING_EXEC_START`～`PENDING_EXEC_END`，默认 09:30–09:45）按开盘价成交；错过则保留到下一交易日开盘窗，**收盘确认窗不成交**。若收盘窗未跑到，开盘对上一根已收盘日兜底评估（`confirmed_eval_day < 上一完整交易日`）。  
实盘报单成功后**保留**信号 pending / 止盈元数据，**仅成交回调**后清除；废单/撤单后下一开盘窗自动重试。

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
| ① 阶梯移动止盈 | 按峰值浮盈选档（见下表）；回撤超容忍或跌破利润底线 | `trail_stop` |
| ② 智能时间 | 持仓 **> `TIME_FORCE_BARS`**（当前 30）日：破日线 MA60 → 强制平仓；仍站上 MA60 → **豁免一次**并再观察 **`TIME_FORCE_GRACE_BARS`**（当前 5）日，期满强制平仓 | `time_force` |
| 兜底 | 收盘 ≤ 成本 × (1 − `STOP_LOSS`)（当前 `0.08`）/ 周线转空且连续 `W_BEAR_CONFIRM_DAYS` 日 | `stop_loss` / `weekly_bear` |

阶梯档位 `TRAIL_TIERS`（峰值浮盈 = `(hold_peak − cost) / cost`）：

| 档 | 峰值浮盈 | 回撤容忍 | 利润底线 |
| :--- | :--- | :--- | :--- |
| 起步保护 | [3%, 6%) | 1.5% | — |
| 落袋为安 | [6%, 10%) | 3% | 至少带走 3% |
| 放鹰吃肉 | ≥ 10% | 4% | — |

优先级（挂 pending 主因）：`weekly_bear` > `stop_loss` > `trail_stop` > `time_force`。  
买卖委托失败/T+1 skip 时**保留**对应 pending（及持仓元数据）；实盘报单成功亦保留至成交，废单后开盘窗可重试。

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

**部署**：`python hongli_band/scripts/qmt/_deploy_qmt_gbk.py` → `HlBand.py` / `红利波段.py`  
**报告**：`python hongli_band/gen_report.py` → `report/`  
**片段**：`hongli_band/scripts/qmt/hlband/`（只改片段后 re-deploy，勿手改终端 GBK）

| 配置 | 当前值 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `False` | 真下单；联调可改 `True` 只打日志 |
| `TRADE_BUDGET` | `25000` | 默认单笔预算；可被 `TRADE_BUDGET_BY_STOCK` 覆盖 |
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
| `STOP_LOSS` | `0.08` | 硬止损（相对成本） |
| `CHASE_MAX_PCT` | `0.05` | 追高禁开 |
| `LIVE_CLOSE_CONFIRM` | `True` | 收盘确认 + 开盘兜底 |
| `PENDING_EXEC_START/END` | `093000` / `094500` | 信号 pending 仅开盘窗按开盘价成交 |
| `STATE_FILE` | `D:\tradingStrategy\hlband_{stock}.json` | 实盘状态；按主图标的分文件 |
| `LOG_DIR` | `D:\tradingStrategy\logs` | 实盘结构化日志根目录 |

日志确认 `HlBand v1.19 init`（`dMA=20/60`，`DRY_RUN=` 与 config 一致）后再挂实盘。
