# 红利板块波段策略：周线定方向，日线找买卖点

**主题目录**：`hongli_band/`｜**版本**：v1.8｜**运行**：国金 QMT 终端模型（见 §5）

---

## 核心逻辑

红利资产慢牛爬坡、震荡抗跌。脚本做 **周线估值/斜率过滤 + 日线缩量低吸 + 动态锁利卖出**。  
行情一律 **前复权**（`dividend_type=front_ratio`）。主图 **日线**；信号收盘确认 → **次日开盘**执行（日线回测无法精确 14:50，实盘可在决策窗尾段触发）。

---

## 一、周线过滤

1. `(MA5_W - MA30_W) / MA30_W >= W_BIAS_HARD`（默认 8%）→ 禁开（`w_bias_skip`）。
2. **低位斜率**：当周线乖离 `< W_BIAS_LOW`（默认 2%）时，要求 **MA30 连续 2 周向上**，否则禁开（`w_slope_skip`）；执行日也会取消 pending。
3. 周线空头（收盘破 30 周，或 DIF/DEA 零轴下死叉）→ 持仓强制清仓（`weekly_bear`）；执行日若仍空头则取消买入 pending。

---

## 二、买入

### 买点 缩量回踩强支撑（`pullback_vol`）

- 收盘靠近 `MA20` 或 `MA60`（容差 `MA_TOUCH_TOL`，默认 ±2.5%）
- 成交量 `< MAVOL10 × VOL_PULLBACK_RATIO`（默认 0.9）

### 全局拦截（任一则当日不开 / 可取消 pending）

| 条件 | 日志码 |
| :--- | :--- |
| 当日涨幅 ≥ `CHASE_MAX_PCT`（默认 5%） | `chase_skip` |
| 收盘 < MA20 且量 < MAVOL20 × `VOL_DRY_RATIO`（默认 0.7） | `vol_dry_skip` |
| 周线高位乖离 / 低位斜率不达标 | `w_bias_skip` / `w_slope_skip` |

---

## 三、卖出

| 卖点 | 条件 | 日志码 |
| :--- | :--- | :--- |
| ① 移动止盈 | 曾浮盈 ≥ `TRAIL_ACTIVATE`（3%）且自峰值回撤 > `TRAIL_GIVEBACK`（1.5%） | `trail_stop` |
| ② 智能时间 | 持仓 **> 30** 日：破日线 MA60 → 强制平仓；仍站上 MA60 → **豁免一次**并再观察 **5** 日，期满强制平仓 | `time_force` |
| 兜底 | 收盘 ≤ 成本 × (1 − `STOP_LOSS`)（默认 −8%）/ 周线转空 | `stop_loss` / `weekly_bear` |

优先级（挂 pending 主因）：`weekly_bear` > `stop_loss` > `trail_stop` > `time_force`。

---

## 四、执行对照表

| 步骤 | 维度 | 公式 |
| :--- | :--- | :--- |
| 周线过滤 | MA5/MA30 | `(wMA5-wMA30)/wMA30 < 0.08` 才可开 |
| 低位斜率 | MA30 | 乖离 < 2% 时须连续 2 周向上 |
| 日线低吸 | 位置+10日量 | 近 MA20/60 且 `vol < MAVOL10×0.9` |
| 动态防御 | 峰值回撤 | 浮盈≥3% 且回撤>1.5% |
| 智能时间 | MA60 缓冲 | `>30` 日：破 MA60 强平；站上则 +5 日豁免后强平 |
| 硬止损 | 成本 | `close ≤ cost×0.92` |

---

## 五、QMT 运行

**部署**：`python hongli_band/scripts/qmt/_deploy_qmt_gbk.py` → `HlBand.py` / `红利波段.py`  
**报告**：`python hongli_band/gen_report.py` → `report/`  
**片段**：`hongli_band/scripts/qmt/hlband/`（只改片段后 re-deploy，勿手改终端 GBK）

| 配置 | 默认 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `True` | 默认不真实下单（联调可临时 False） |
| `W_BIAS_HARD` | `0.08` | 周线高位乖离禁开 |
| `W_BIAS_LOW` | `0.02` | 低位区阈值（配合斜率） |
| `MA_TOUCH_TOL` | `0.025` | 回踩均线容差 |
| `VOL_PULLBACK_N/RATIO` | `10` / `0.9` | 买点量能 |
| `VOL_DRY_N/RATIO` | `20` / `0.7` | 无量阴跌禁开 |
| `TRAIL_*` | `0.03` / `0.015` | 移动止盈 |
| `TIME_FORCE_BARS` | `30` | 时间成本起始持仓日 |
| `TIME_FORCE_GRACE_BARS` | `5` | 站上 MA60 时豁免观察日 |
| `STOP_LOSS` | `0.08` | 硬止损（相对成本） |
| `CHASE_MAX_PCT` | `0.05` | 追高禁开 |
| `STATE_FILE` | `...\hlband_qmt_state.json` | 实盘状态 |

日志确认 `HlBand v1.8 init`（`dMA=20/60`）后再改 `DRY_RUN=False`。
