# Recipe 分类与布尔式

配套：[架构.md](./架构.md)（当前实现）、[架构优化.md](./架构优化.md)、[草图.png](./草图.png)。

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
["or", "pullback_vol", "plat_break", "w_macd_golden"]
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

已挂出的 `pending_entry` **只复评**该槽里的 `["not", leaf]`（开仓=`RECIPE_ENTRY`，加仓=`RECIPE_SCALE_IN`），不要求信号叶子次日仍为真。不要对整棵式 `_hit` 来撤单。详见 [架构.md](./架构.md)「pending：粘性委托」。

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
  （仓位门槛 SCALE_ARM / once / 满槽 在仓位层）
  ¬weekly_bear & ¬w_bias & ¬w_slope & ¬vol_dry
  & (pullback_vol | plat_break | w_macd_golden)
  # chase 不挡 plat_break / 金叉

exit:
  暂可用有序列表模拟：
    1) stop_loss
    2) trail_stop
    3) time_force
    另: weekly_bear 确认 → 全平
  或后续收成单棵/多棵布尔式 + 稳定 reason 排序

scale_out:
  []   # 现网默认关闭；非空且 >=2 笔时按 SCALE_OUT_LOT 平 1 笔
```

---

## 6. 因子 ctx（行情 + 状态）

`eval(ctx)` 不只吃 OHLCV。组装见 [架构优化.md](./架构优化.md) §3.6。

| 因子 | 主要读的 state |
| :--- | :--- |
| `chase` / `vol_dry` / `w_bias` / `w_slope` / `pullback_vol` / `plat_break` / `w_macd_golden` | 可几乎只靠 market |
| `stop_loss` / `trail_stop` | `cost`、`hold_peak`（或 lot 同名字段） |
| `time_force` | `hold_bars`、`hold_max_ret`、`time_force_trend_skip` |
| `weekly_bear`（确认清仓） | `w_bear_streak`、`w_bear_last_day` |

`eval` 只读；streak / `trend_skip` 的写回不放在 `eval` 内。

---

## 7. 第一期复合原子（现网叶子）

引擎可支持细原子，但默认 Recipe **只引用**下表。内部已复合的条件仍由该因子自己的参数（含 `D_MA_*<=0` 关条）处理。

| id | 现逻辑 | 内部已复合 |
| :--- | :--- | :--- |
| `pullback_vol` | 贴 MA20/60 + 连续缩量 | 近中线或近慢线，且量确认 |
| `chase` | 当日涨幅 ≥ `CHASE_MAX_PCT` | — |
| `vol_dry` | 跌破中线且无量 | 价 + 量 |
| `w_bias` | 周线乖离过高 | — |
| `w_slope` | 低位生命线未连升 | 乖离区 + 斜率 |
| `weekly_bear` | 周空（破生命线 / 零轴下死叉） | 确认日数：读 state 计数 |
| `plat_break` | 平台突破 | 振幅 + 收盘站上 |
| `w_macd_golden` | 周金叉且柱放大 | 交叉 + 柱比 |
| `stop_loss` | 收盘相对成本 | 需 state.cost |
| `trail_stop` | 档位回撤 / 利润底 | 整表 `TRAIL_TIERS` + peak |
| `time_force` | 持仓日 + MA60 + 武装让路 | 多条件 + state |

仓位门槛（`SCALE_ARM` / `scale_once` / 满槽）**不进** Factor Lib。

同一 id 可进多槽；参数默认共享。某槽要不同阈值再用别名覆写。

---

## 8. 参数组

一份参数组 = 四槽表达式 + `factor_params` + `structure` + `sizing`。  
网格优先扫「命名表达式变体」，再扫已启用因子的数值；避免全因子开关笛卡尔积。
组合轴 = 命名格子改 `RECIPE_*`（JSON）；`RECIPE_SCALE_OUT=[]` 关闭减仓。

**已落地**（引擎 + 默认 Recipe 对齐 + 网格 overrides + 减仓槽默认关）：见 [架构.md](./架构.md)。`hlband/factors/lib/` 一原子一文件，四槽只引用 id；`_resolve_intent`、`expr` dtype、`recipe=` 探针。
