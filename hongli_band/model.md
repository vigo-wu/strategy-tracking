# 红利板块波段策略：周线定方向，日线找买卖点

**主题目录**：`hongli_band/`｜**版本**：v1.5｜**运行**：国金 QMT 终端模型（见 §5）

---

## 核心逻辑

红利资产慢牛爬坡、震荡抗跌。脚本做 **周线估值过滤 + 日线缩量低吸 + 动态锁利卖出**。  
行情一律 **前复权**（`dividend_type=front_ratio`）。主图 **日线**；信号收盘确认 → **次日开盘**执行（日线回测无法精确 14:50，实盘可在决策窗尾段触发）。

---

## 一、周线过滤

`(MA5_W - MA30_W) / MA30_W >= W_BIAS_HARD`（默认 8%）→ 禁开（`w_bias_skip`）。  
周线空头（破 30 周或零轴下死叉）→ 持仓强制清仓（兜底）。

---

## 二、买入

### 买点① 缩量回踩强支撑
- 收盘靠近 `MA20` 或 `MA60`（容差 `MA_TOUCH_TOL`）
- 成交量 `< MAVOL10 × VOL_PULLBACK_RATIO`（默认 0.9）

### 买点② 趋势线之上的 KDJ 超卖
- 前日 `J < 0`，当日 `J` 拐头向上且收阳
- **收盘必须 ≥ MA20**
- **拦截**：收盘 < MA20 且量 < MAVOL20 × 0.7 → `vol_dry_skip`（无量阴跌不言底，全局禁开；执行日也会取消 pending）

另：当日涨幅 ≥ `CHASE_MAX_PCT` → `chase_skip`。

---

## 三、卖出

| 卖点 | 条件 | 日志码 |
| :--- | :--- | :--- |
| ① 短线乖离 | `BIAS5 >= 6%` | `bias5` |
| ② 移动止盈 | 曾浮盈 ≥ 3% 且自峰值回撤 > 1.5% | `trail_stop` |
| ③ 时间成本 | 持仓 ≥ 15 个交易日且盈亏 ∈ [-1%, +1%] | `time_flat` |
| 兜底 | 成本 -8% / 周线转空 | `stop_loss` / `weekly_bear` |

（v1.5 已移除 MACD 死叉/背离、放量滞涨作为主卖点。）

---

## 四、执行对照表

| 步骤 | 维度 | 公式 |
| :--- | :--- | :--- |
| 周线过滤 | MA5/MA30 | `(wMA5-wMA30)/wMA30 < 0.08` 才可开 |
| 日线低吸① | 位置+10日量 | 近 MA20/60 且 `vol < MAVOL10×0.9` |
| 日线低吸② | KDJ+MA20 | J 超卖拐头且 `close≥MA20` |
| 日线高抛 | BIAS5 | `(C-MA5)/MA5 ≥ 6%` |
| 动态防御 | 峰值回撤 | 浮盈≥3% 且回撤>1.5% |
| 时间止损 | 持仓天数 | ≥15 日且 |ret|≤1% |

---

## 五、QMT 运行

**部署**：`python hongli_band/scripts/qmt/_deploy_qmt_gbk.py` → `HlBand.py` / `红利波段.py`  
**报告**：`python hongli_band/gen_report.py` → `report/`

| 配置 | 默认 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `True` | 默认不真实下单 |
| `W_BIAS_HARD` | `0.08` | 周线乖离禁开 |
| `VOL_PULLBACK_N/RATIO` | `10` / `0.9` | 买①量能 |
| `VOL_DRY_N/RATIO` | `20` / `0.7` | 无量阴跌禁开 |
| `TRAIL_*` | `0.03` / `0.015` | 移动止盈 |
| `TIME_FLAT_*` | `15` / `0.01` | 时间成本止损 |
| `STATE_FILE` | `...\hlband_qmt_state.json` | 实盘状态 |

日志确认 `HlBand v1.5 init` 后再改 `DRY_RUN=False`。只改 `hlband/*.py` 后 re-deploy，勿手改终端 GBK。
