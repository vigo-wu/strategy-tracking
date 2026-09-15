# Recipe 分类与布尔式

配套：[架构.md](架构.md)（分层契约）、[factors/NAV.md](../../scripts/qmt/fband/factors/NAV.md)（现行默认配置四个槽位的唯一可信数据源）。

叶子文件：`hlband/factors/lib/<id>.py`，一 id 一文件；登记表是 `factors/catalog.py` 的 `LEAVES`。引擎在 `factors/` 根目录（`ctx` / `registry` / `expr` / `slots`）。清单见下 §7。

策略四个槽位各自持有一棵布尔表达式（Recipe）。因子无立场，只作为叶子被引用。

---

## 1. 四个槽位与典型形态

买入 `entry`、加仓 `scale_in`、卖出 `exit`、减仓 `scale_out` 四个槽位各自持有一棵条件抽象语法树。

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

现行默认配置的叶子是**复合原子**（见 §7），不要把 `keltner_vol` 拆进表达式。`pullback_vol` 仍登记，默认 AST 不引用。

入场（对齐现行默认配置）：

```json
["and",
  "above_ema",
  "keltner_vol"]
```

加仓（现行默认 `scale_in=false`；启用示例，`scale_arm` 在表达式末）：

```json
["and",
  "above_ema",
  "keltner_vol",
  "scale_arm"]
```

细原子示例（第二期才用，现行默认配置不用）：

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
- 新写法：整棵入场式里写 `["not","leaf"]` 等

因子仍是中性的；立场由所在槽的表达式赋予。

---

## 4. 仓位层 vs Recipe

下列**不要**写进布尔式，留在仓位管理：

- `book_lot_cap` / 现金不足 / `scale_once`
- T+1 可卖、当日加仓后跳过评卖
- 减仓比例、开仓/加仓 `frac`

Recipe 只回答「意图是否触发」；能不能成交、下多少，由仓位管理 + 委托层决定。

---

## 5. 现状编码（默认 Recipe 草图）

```text
entry:
  above_ema & keltner_vol

scale_in:
  false
  # scale_arm 仍登记；启用后由 _recipe_compute_leaves 特例拉入
  # scale_once / 满槽在仓位层

exit:
  atr_stop | atr_trail_stop
  # or 短路；主因 = 第一个命中叶子 id
  # stop_loss / trail_stop / time_force 叶子仍在，默认 AST 不引用

scale_out:
  false   # 现行默认配置无独立减仓槽
```

---

## 6. 因子 ctx（行情 + 状态）

`eval(ctx)` 不只读取 OHLCV。组装见 [架构.md](架构.md) §2.4。

| 因子 | 主要读的 state |
| :--- | :--- |
| `pullback_vol` / `keltner_vol` / `above_ema` | 可几乎只靠 market |
| `scale_arm` | `lots` / `hold_max_ret` / `hold_bars`、`w_detail.hist` |
| `stop_loss` / `atr_stop` / `trail_stop` / `atr_trail_stop` | `cost`、`hold_peak`（或 lot 同名字段）；`atr_stop` / `atr_trail_stop` 另读 `market.atr` |
| `time_force` | `hold_bars`、`hold_max_ret`、`time_force_trend_skip` |

`eval` 只读；`trend_skip` 的写回不放在 `eval` 内。

---

## 7. 第一期复合原子（现行默认配置叶子）

引擎可支持细原子，但现行默认配置的叶子 **只登记** `catalog.LEAVES`（下表）。每个 id 对应 `hlband/factors/lib/<id>.py`。默认 exit AST 引用其中一部分（见 §5）。作者改 `LEAVES` 的 `default`；运行时阈值读 `RECIPE.factor_params`（catalog 整表写入，`_factor_param`），**没有** `STOP_LOSS` 这类模块全局别名。均线/MACD/ATR/肯特纳窗读 `RECIPE.structure`（`_structure_windows`），`<=0` 关条。

| id | 现逻辑 | 阈值（`factor_params`） |
| :--- | :--- | :--- |
| `pullback_vol` | 贴中/慢均线 + 连续缩量 | `pullback_vol.tol` / `vol_n` / `ratio` / `confirm_days`（默认 AST 不引用） |
| `keltner_vol` | 收盘在肯特纳通道内 + 连续缩量 | `keltner_vol.k` / `ratio` / `vol_n` / `confirm_days`；窗是 `structure.keltner.*` |
| `above_ema` | 收盘 > 日线趋势 EMA | 无叶子阈值；窗是 `structure.ema.1d.trend`（`<=0` 关闸门） |
| `scale_arm` | 峰值浮盈 + 该笔持仓日 + 周柱下限 | `scale_arm.arm` / `bars` / `hist_min`；`arm<=0` 回落 `0.03`；`bars<=0` 不查持仓日；`hist_min` 为 `None` 关闭周柱 |
| `stop_loss` | 收盘相对成本 | `stop_loss.pct` |
| `atr_stop` | 收盘 <= 成本 − k×ATR | `atr_stop.k`；窗是 `structure.atr.n` |
| `atr_trail_stop` | 峰值相对成本 > k1×ATR 武装；收盘<=成本或峰值回撤>=k2×ATR | `atr_trail_stop.k1` / `k2`；`k1<=0` 整条关；`k2<=0` 只保本 |
| `trail_stop` | 档位回撤 / 利润底 | `trail_stop.tiers`（默认 exit 不引用） |
| `time_force` | 持仓日 + 慢线地板 + 武装让路 | `time_force.bars` / `time_force.arm`；`arm<=0` 关让路 |

仓位门槛（`scale_once` / 满槽）**不进** Factor Lib，也不进 `factor_params`。`SCALE_ARM` / `SCALE_ARM_BARS` / `SCALE_W_HIST_MIN` 已删，顶层写入即报错；改 `scale_arm.arm` / `bars` / `hist_min`。

同一 id 可进多槽；阈值按 id 共享。不做每槽别名。

---

## 8. 参数组

作者改 `factors/catalog.py` 的 `LEAVES`；运行时读 `RECIPE.factor_params`（catalog 用 defaults 整表写入，不要给 `above_ema` 写空 `{}`）。四个槽位的条件抽象语法树 / `structure` 仍手写在 `config.RECIPE`。叶子只读表，不读同名全局。没有 `STOP_LOSS` / `D_MA_MID` 别名。

加普通因子：`LEAVES` + `lib/<id>.py` + 必要时改四个槽位的条件抽象语法树。不要手改 `registry` / `MODULE_ORDER` / `grid_spec` 白名单。公式仍留在 `lib/`，不做成配置字符串。

| 住哪 | 例子 | 说明 |
| :--- | :--- | :--- |
| `RECIPE` 四个槽位 AST | `entry` / `scale_in` / `exit` / `scale_out` | 无数字；默认盘启用写这里 |
| `catalog.LEAVES` → `RECIPE.factor_params` | `stop_loss.pct`、`atr_stop.k`、`atr_trail_stop.k1` / `k2`、`time_force.arm`、`trail_stop.tiers`、`scale_arm.arm` / `bars` / `hist_min`、`keltner_vol.*` | 作者改 `LEAVES`；运行时 `_factor_param` |
| `RECIPE.structure` | 见下表 | 均线/MACD/ATR/肯特纳 **窗**；`_structure_windows` |
| 仓位 / 资金全局 | `SCALE_ENABLE`、`CASH_RATIO`、`TRADE_BUDGET` | 不上表、不上因子面板 |

`RECIPE.structure` 现行读窗物化（`_structure_windows()`；`<=0` 关该条均线/ATR/肯特纳；MACD 三窗都应 >0）。价格均线按算法 × `_VALID_PERIODS` 周期键（`1d`/`1w`/…）× `mid`/`slow`/`trend`。config 字面量可精简（现行只写 `ema.1d.trend=120` + `keltner`）；缺键由读窗填字面量。

| 段 | 键 | 现行默认 | 用途 |
| :--- | :--- | :--- | :--- |
| `ema.1d` | `mid` / `slow` / `trend` | 20 / 60 / 120 | 日线回踩；慢线还是 time_force 地板；`trend` 是 `above_ema`（`<=0` 关闸门） |
| `ema.1w` | `mid` / `slow` / `trend` | 5 / 13 / 34 | 周线快/中/生命线（原 `w_ma.fast/mid/life`）；`slow` 仅日志 `weekly_bull` |
| `sma.1d` / `sma.1w` | `mid` / `slow` / `trend` | 全 0 | 价格 SMA 窗；现行盘无调用点；`<=0` 关条 |
| `macd` | `fast` / `slow` / `signal` | 12 / 26 / 9 | 周线 DIF/DEA/柱 |
| `atr` | `n` | 14 | 日线威尔德 ATR；`<=0` 关 `atr_stop` / `atr_trail_stop` |
| `keltner` | `ema_n` / `atr_n` | 20 / 20 | 肯特纳中轨 EMA / 带宽 ATR（与 `atr.n` 独立）；`<=0` 关 |

读取指标周期窗：调用方先 `_structure_windows()`，再把 `n` 传给 `_ema` / `_sma` / `_calc_macd`（三窗必传）/ `_calc_atr` / `_calc_keltner`（`ema_n` / `atr_n` / `k` 必传；`k` 不上 `structure`）。`_ema` 读 `ema.*`，`_sma` 读 `sma.*`。网格覆盖 `_structure_apply_global`，**递归**按算法→周期→窗合并。QMT 暖机（`market._ohlcv_need_*`）同周期对 `ema`/`sma` 窗取 max（`>0`）。旧 `d_ma`/`w_ma` 段写入即报错。量均窗仍在 `factor_params`（`pullback_vol.vol_n` / `keltner_vol.vol_n`）。

网格：因子轴元数据（分组 / 短名 / percent / kind）来自 `LEAVES`，侧栏只含买入 `entry`、加仓 `scale_in`、卖出 `exit`、减仓 `scale_out` 四个槽位已启用叶子的阈值（现行默认配置的 `stop_loss` 登记保留、不上轴）。轴 id 仍是点路径（`stop_loss.pct` / `atr_stop.k` / `atr_trail_stop.k1` / `k2` / `time_force.arm` / `scale_arm.arm` / `scale_arm.bars` / `scale_arm.hist_min` / `ema.1d.mid` / `ema.1d.trend` / `atr.n` / `keltner.ema_n` / `keltner.atr_n` / `keltner_vol.k`）；短 id 如 `e1dm15` / `e1dt` / `ask` / `atk1` / `atk2` / `tfa` / `sa` / `sab` / `swh` / `atr` / `kem` / `kat` / `kvk`。`sma.*` 不上轴。`atr_stop.k` / `atr_trail_stop.k1` / `k2` 是浮点倍数轴（`LEAVES` 默认 `2.0`，可扫 `1.5`），**不是**百分比轴。格子 `overrides` 形态不变，必须写成：

```text
{"factor_params": {"stop_loss": {"pct": 0.06}}}
{"factor_params": {"atr_stop": {"k": 1.5}}}
{"factor_params": {"atr_trail_stop": {"k1": 2.0, "k2": 1.5}}}
{"factor_params": {"time_force": {"arm": 0.03}}}
{"factor_params": {"scale_arm": {"arm": 0.03, "bars": 8, "hist_min": -0.01}}}
{"structure": {"ema": {"1d": {"mid": 15}}}}
{"structure": {"ema": {"1d": {"trend": 120}}}}
{"structure": {"atr": {"n": 14}}}
{"structure": {"keltner": {"ema_n": 20, "atr_n": 20}}}
```

顶层旧键（`STOP_LOSS` / `D_MA_MID` / `SCALE_ARM`）或顶层点路径（`stop_loss.pct` / `d_ma.mid` / `ema.1d.mid`）都直接报错；袋内旧段 `d_ma`/`w_ma` 亦报错。面板只上模拟下单 / 资金 / 加仓开关，因子阈值和指标周期窗不上屏。

`recipe=` 指纹：表达式 + 折进表的 `factor_params` + `structure`。apply 之后再算，`overrides` 袋为空。默认哈希会随 payload 增 `structure` 而变；参数指纹预检用 `expected_fingerprint` 重算，不要对历史 `report/grid/` 档案里的旧哈希。两份拷贝：`factors/slots.py` 与 `local_bt/grid_spec.py`。

仓位不做 sizing 分栏，也不做全因子 `2^n` 开关。优先扫命名数值轴，见 `qmt-local-bt-grid`。
