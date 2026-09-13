# Recipe 分类与布尔式

配套：[架构.md](架构.md)（分层契约）、[factors/NAV.md](../../scripts/qmt/hlband/factors/NAV.md)（现网四槽真源）。

叶子文件：`hlband/factors/lib/<id>.py`，一 id 一文件；引擎在 `factors/` 根目录（`ctx` / `registry` / `expr` / `slots`）。清单见下 §7。

策略四个结构槽各自持有一棵布尔表达式（Recipe）。因子无立场，只作为叶子被引用。

---

## 1. 四槽与典型形态

| 槽 | 键名（建议） | 典型形态 | 语义 |
| :--- | :--- | :--- | :--- |
| 入场 | `entry` | `A \| B \| (C & D)` | 是否开仓 |
| 出场 | `exit` | `A & (B \| C)` | 是否清仓 / 清指定笔 |
| 加仓 | `scale_in` | `A \| B \| (C & D)` | 是否加仓 |
| 减仓 | `scale_out` | `A & (B \| C)` | 是否减仓（非清零） |

形态是示例，不是引擎硬约束。入场也可能写成「闸门 AND 信号」；出场也可能是多条有序式。

---

## 2. AST 约定

叶子 = 因子 id（字符串）。  
节点 = `and` / `or` / `not`。

现网默认叶子是**复合原子**（见 §7），不要把 `pullback_vol` 拆进表达式。

入场（对齐现网）：

```json
["and",
  ["not", "chase"], ["not", "vol_dry"],
  ["not", "w_bias"], ["not", "w_slope"],
  ["not", "weekly_bear"],
  "pullback_vol"]
```

加仓信号（门槛在仓位层）：

```json
["and",
  ["not", "vol_dry"], ["not", "w_bias"],
  ["not", "w_slope"], ["not", "weekly_bear"],
  ["or",
    ["and", "pullback_vol", ["not", "chase"]],
    "plat_break", "w_macd_golden"]]
```

细原子示例（第二期才用，现网不用）：

```json
["and", "near_ma", "vol_shrink"]
```

求值：

```text
hit(atom)        = FACTORS[id].eval(ctx)   # ctx = market + state + clock
hit(["and", …])  = all(hit(x))
hit(["or", …])   = any(hit(x))
hit(["not", x])  = not hit(x)
```

槽输出：`hit` + 命中叶子 `reasons`（用于日志与归因）。

---

## 3. 与「闸门 / 信号」的关系

不必单独维护 gate 层。

- 旧写法：先跑一堆 skip，再跑买点
- 新写法：整棵入场式里写 `["not","chase"]`、`["not","vol_dry"]` 等

因子仍是中性的（如 `chase` = 当日追高为真）；立场由所在槽的表达式赋予。

---

## 4. 仓位层 vs Recipe

下列**不要**写进布尔式，留在仓位管理：

- `book_lot_cap` / 现金不足 / `scale_once`
- T+1 可卖、当日加仓后跳过评卖
- 减仓比例、开仓/加仓 `frac`

Recipe 只回答「意图是否触发」；能不能成交、下多少，由仓位管理 + 委托层决定。

---

## 5. 现状编码（默认 Recipe 草图）

迁移第一期应用表达式**对齐**现逻辑，而不是先改语义：

```text
entry:
  ¬chase & ¬vol_dry & ¬w_bias & ¬w_slope & ¬weekly_bear & pullback_vol

scale_in:
  （仓位门槛 SCALE_ARM / scale_once / 满槽在仓位层）
  ¬vol_dry & ¬w_bias & ¬w_slope & ¬weekly_bear
  & ((pullback_vol & ¬chase) | plat_break | w_macd_golden)
  # 破平台 / 金叉不受 chase；回踩加仓受

exit:
  有序列表（不是单棵 and/or）：
    1) weekly_bear_confirm   # 对外 reason 仍打 weekly_bear
    2) stop_loss
    3) atr_stop
    4) trail_stop
    5) time_force

scale_out:
  false   # 现网无独立减仓槽
```

---

## 6. 因子 ctx（行情 + 状态）

`eval(ctx)` 不只吃 OHLCV。组装见 [架构.md](架构.md) §2.4。

| 因子 | 主要读的 state |
| :--- | :--- |
| `chase` / `vol_dry` / `w_bias` / `w_slope` / `pullback_vol` / `plat_break` / `w_macd_golden` | 可几乎只靠 market |
| `stop_loss` / `atr_stop` / `trail_stop` | `cost`、`hold_peak`（或 lot 同名字段）；`atr_stop` 另读 `market.atr` |
| `time_force` | `hold_bars`、`hold_max_ret`、`time_force_trend_skip` |
| `weekly_bear`（当天空头，禁开/撤买） | 主要靠 `w_detail` |
| `weekly_bear_confirm`（确认清仓） | `w_bear_streak`、`w_bear_last_day` |

`eval` 只读；streak / `trend_skip` 的写回不放在 `eval` 内。

---

## 7. 第一期复合原子（现网叶子）

引擎可支持细原子，但默认 Recipe **只引用**下表。每个 id 对应 `hlband/factors/lib/<id>.py`。阈值读 `RECIPE.factor_params`（`_factor_param`），**没有** `STOP_LOSS` / `CHASE_MAX_PCT` 这类模块全局别名。均线/MACD/ATR 窗读 `RECIPE.structure`（`_structure_windows`），`<=0` 关条。

| id | 现逻辑 | 阈值（`factor_params`） |
| :--- | :--- | :--- |
| `pullback_vol` | 贴中/慢均线 + 连续缩量 | `pullback_vol.tol` / `vol_n` / `ratio` / `confirm_days` |
| `chase` | 当日涨幅过大 | `chase.max_pct` |
| `vol_dry` | 跌破中线且无量 | `vol_dry.ratio` / `n` |
| `w_bias` | 周线高位乖离 | `w_bias.hard` |
| `w_slope` | 低位生命线未连升 | `w_slope.low` / `slope_weeks` |
| `weekly_bear` | **当天空头**（破生命线 / 零轴下死叉） | 无叶子阈值；周期在 `RECIPE.structure` |
| `weekly_bear_confirm` | **确认清仓**：streak ≥ N | `weekly_bear_confirm.days` |
| `plat_break` | 平台突破 | `plat_break.lookback` / `max_range` / `break_buf` |
| `w_macd_golden` | 周金叉且柱放大 | `w_macd_golden.hist_expand` |
| `stop_loss` | 收盘相对成本 | `stop_loss.pct` |
| `atr_stop` | 收盘 <= 成本 − k×ATR | `atr_stop.k`；窗是 `structure.atr.n` |
| `trail_stop` | 档位回撤 / 利润底 | `trail_stop.tiers` |
| `time_force` | 持仓日 + 慢线地板 + 武装让路 | `time_force.bars` |

仓位门槛（`SCALE_ARM` / `scale_once` / 满槽）**不进** Factor Lib，也不进 `factor_params`。

同一 id 可进多槽；阈值按 id 共享。不做每槽别名。

---

## 8. 参数组

数字真源是 `config.RECIPE` 里两张表的字面量。叶子只读表，不读同名全局。没有 `STOP_LOSS` / `D_MA_MID` 别名。

| 住哪 | 例子 | 说明 |
| :--- | :--- | :--- |
| `RECIPE` 四槽 AST | `entry` / `scale_in` / `exit` / `scale_out` | 无数字 |
| `RECIPE.factor_params` | `stop_loss.pct`、`atr_stop.k`、`chase.max_pct`、`trail_stop.tiers` | 因子阈值；`_factor_param` |
| `RECIPE.structure` | 见下表 | 均线/MACD/ATR **窗**；`_structure_windows` |
| 算法（不是窗） | `MA_TYPE`、`BOOK_STOCKS[].ma_type` | SMA/EMA；不上 `structure` |
| 仓位 / 资金全局 | `SCALE_ARM`、`CASH_RATIO`、`TRADE_BUDGET` | 不上表、不上因子面板 |

`RECIPE.structure` 现网字面量（`<=0` 关该条均线/ATR；MACD 三窗都应 >0）：

| 段 | 键 | 现网 | 用途 |
| :--- | :--- | :--- | :--- |
| `d_ma` | `mid` / `slow` | 20 / 60 | 日线回踩/无量阴跌；慢线还是 time_force 地板 |
| `w_ma` | `fast` / `mid` / `life` | 5 / 13 / 34 | 周线快/中/生命线；`mid` 仅日志 `weekly_bull` |
| `macd` | `fast` / `slow` / `signal` | 12 / 26 / 9 | 周线 DIF/DEA/柱 |
| `atr` | `n` | 14 | 日线威尔德 ATR；`<=0` 关 `atr_stop` |

读窗：调用方先 `_structure_windows()`，再把 `n` 传给 `_price_ma` / `_calc_macd`（三窗必传）/ `_calc_atr`。缺键用上表数字字面量。网格覆盖 `_structure_apply_global`，按段再按 key 合并。QMT 暖机（`market._ohlcv_need_*`）走 `_structure_windows()`；local_bt `run.py` 读裸表，缺键当 0——现网字面量齐全时两者一致。

网格：轴 id 是点路径（`stop_loss.pct` / `atr_stop.k` / `d_ma.mid` / `atr.n`）；短 id 如 `dmm15` / `ask` / `atr`。格子 `overrides` 必须写成：

```text
{"factor_params": {"stop_loss": {"pct": 0.06}}}
{"factor_params": {"atr_stop": {"k": 2}}}
{"structure": {"d_ma": {"mid": 15}}}
{"structure": {"atr": {"n": 14}}}
```

顶层旧键（`STOP_LOSS` / `D_MA_MID`）或顶层点路径（`stop_loss.pct` / `d_ma.mid`）都直接报错。面板只上模拟下单 / 资金 / 加仓开关，因子阈值和结构窗不上屏。

`recipe=` 指纹：表达式 + 折进表的 `factor_params` + `structure`。apply 之后再算，`overrides` 袋为空。默认哈希会随 payload 增 `structure` 而变；探针用 `expected_fingerprint` 重算，不要对历史 `report/grid/` 档案里的旧哈希。两份拷贝：`factors/slots.py` 与 `local_bt/grid_spec.py`。

仓位不做 sizing 分栏，也不做全因子 `2^n` 开关。优先扫命名数值轴，见 `qmt-local-bt-grid`。
