---
name: qmt-hlband-extend
description: >-
  在 hongli_band 增减技术指标或登记/启用/卸下/除名因子：指标走 indicators/ + ctx + _MODULE_HEAD；
  因子登记走 catalog.LEAVES + lib/<id>.py，启用走四槽 AST。Use when the user mentions
  加因子、删因子、登记、启用、卸下、除名、加减指标、新指标、catalog、LEAVES、
  _factor_eval_、indicators/、MODULE_HEAD、结构窗，或要把一条规则做成 HlBand 因子。
---

# HlBand 增减指标 / 因子

只改 `hongli_band`。先对照词表分类，再走对应清单。改完 **deploy + 单测**；参数契约变了再走 docs-sync。

现网说明：[factors/NAV.md](../../../hongli_band/scripts/qmt/hlband/factors/NAV.md)、[lib/NAV.md](../../../hongli_band/scripts/qmt/hlband/factors/lib/NAV.md)、[indicators/NAV.md](../../../hongli_band/scripts/qmt/hlband/indicators/NAV.md)。  
登记表字段：[reference-catalog.md](reference-catalog.md)。  
分层契约：[架构.md](../../../hongli_band/docs/架构重构/架构.md) §2。  
参数契约同步：`.cursor/rules/hlband-docs-sync.mdc`。  
拼接 / 禁止手改终端文件：`qmt-common-modules`。

## 词表

| 词 | 是 | 不是 |
| :--- | :--- | :--- |
| **因子** | 中性原子 `_factor_eval_<id> → (bool, detail)`；`lib/<id>.py` | 买卖立场；仓位门槛；指标 |
| **登记** | `catalog.LEAVES` 一行 + 对应 `lib` 文件 | 默认盘已经在用 |
| **叶子** | 四槽 AST 里的因子 id 字符串；reasons 用这个 id | 指标；「在 LEAVES 里」本身 |
| **启用 / 卸下** | AST 引用或去掉该 id | 登记 / 除名 |
| **除名** | 删 `LEAVES` 行 + 删 `lib/<id>.py` | 只从 AST 拿掉（现网 `stop_loss` 就是登记保留、AST 不引用） |
| **指标** | 序列→序列（或纯工具） | 叶子、因子 |
| **分层契约** | 谁可读 STATE / 现金 / pending；指标不吃 `RECIPE` | NAV 目录 |
| **参数契约** | 阈值/窗真源、overrides 形态、读窗/读阈值 API、买卖语义 | 任意文档改动 |

`LEAVES` 是**可作 AST 叶子的因子登记表**，不是「正在使用的叶子列表」。`group` 只是网格侧栏分组，不是槽立场；同一因子可进多槽。

## 不要用错

| 需求 | 走哪个 |
| :--- | :--- |
| 正交化 / 中性化残差因子 | `skill-factor-orthogonalize` |
| 批量把 OHLCV alpha 做成 QuantSkills | `skill-quant-factor-skill-factory` |
| 网格扫参（不改登记、不改 AST） | `qmt-local-bt-grid` |
| 新开一整套终端策略 | `qmt-common-modules` |

片段禁止互 `import`。不要手改 `qmt_terminal_*.py`、`registry` 手写表、`MODULE_ORDER` 的 **lib 段**、`grid_spec` 因子白名单。仓位门槛（`SCALE_ARM` / `scale_once` / 满槽 / 资金）**不进** `LEAVES` / `lib/` / `indicators/`。

---

## A. 登记因子（已有指标够用）

```
进度:
- [ ] 1. catalog.LEAVES 加 id（label / group / params）
- [ ] 2. factors/lib/<id>.py 写 _factor_eval_<id>
- [ ] 3. 默认盘要引用：走 B 启用
- [ ] 4. 单测 + deploy compile
- [ ] 5. 现网说明（lib/NAV 清单；启用了再改 Recipe分类 四槽）
```

1. **`LEAVES`**：无阈值因子（如 `weekly_bear`）`params` 留空，**不要**写出空 `{}` 进 `factor_params`。网格轴序用 `params[].axis`。`default` 类型要稳（`2` 不要写成 `2.0`；tiers 用 list）。字段见 [reference-catalog.md](reference-catalog.md)。
2. **`lib/<id>.py`**：阈值只读 `_factor_param(ctx, id, key)`；窗只读 `_structure_windows()`。不写死数字。不读现金 / 账本 / pending，不调用 `passorder`。文件名 = id。中文名写 `LEAVES.label`（买卖不同用 `label_buy`），不要改成交 reason 码。
3. **不要改**：`registry.py`、`_deploy_qmt_gbk.py` 的 lib 段、`grid_spec` 的 `ENTRY_KEYS` 等（从表推）。
4. 因子读不到的列 → 先走 **C. 加指标**，再在 `ctx.py` 装进 `ctx.market`。
5. 只登记、不启用（仿 `stop_loss`）仍要改 `lib/NAV.md` 清单；**不必**当成分层契约变更。

---

## B. 启用 / 卸下（只改 AST）

```
进度:
- [ ] 1. 确认 id 已在 LEAVES（否则先 A）
- [ ] 2. config.RECIPE 四槽引用或去掉该 id
- [ ] 3. 单测 + deploy；同步 Recipe分类 / factors/NAV 四槽草图
```

格子不能改 AST。卸下 ≠ 除名：AST 去掉后求值不再命中，登记仍在。Python 列表里注释掉的字符串不会进 AST。

---

## C. 加 / 删指标

```
加:
- [ ] 1. indicators/<名>.py 只吃序列（窗由调用方传入）
- [ ] 2. _MODULE_HEAD 插入（有依赖放后面）
- [ ] 3. 因子要用：ctx.py 写入 ctx.market
- [ ] 4. 窗可调：RECIPE.structure + _structure_windows + 暖机 + STRUCTURE_KEYS
- [ ] 5. 单测 + deploy + indicators/NAV.md

删:
- [ ] 1. 确认无 ctx / 因子再调用
- [ ] 2. 从 _MODULE_HEAD 去掉；删文件
- [ ] 3. 若曾进 structure：config + _structure_windows + 暖机 + STRUCTURE_KEYS
```

`_calc_*` **必传窗**，不读 `RECIPE`。仿 `atr.py` / `macd.py`。不要新建根上 `indicators.py`。`macd` 必须在 `ema` 之后。lib 段仍由表生成，不要手插 `factors/lib/`。纯工具不成因子 id。

可调窗才进 `RECIPE.structure`。覆盖形态仍是 `overrides.structure`（参数契约）。

---

## D. 除名因子

```
进度:
- [ ] 1. 先 B 卸下（AST 不再引用）
- [ ] 2. 删 LEAVES 行 + 删 factors/lib/<id>.py
- [ ] 3. 清 ctx / strategy 专线（streak、预计算、label 特例）
- [ ] 4. 清单测与现网说明清单
- [ ] 5. deploy（孤儿 lib 会 SystemExit）
```

未从 `LEAVES` 删除却删了文件 → deploy 报 missing。未删文件却删了表 → 孤儿报错。  
`weekly_bear` / `time_force` 在 `strategy.py` / `ctx.py` 有专线，不能只删 lib。

---

## 验证（每次必做）

```bash
python hongli_band/scripts/local_bt/test_catalog.py
python hongli_band/scripts/qmt/_deploy_qmt_gbk.py
```

登记/除名再跑相关 `test_factor_expr` / 该因子单测。不要手改预览或终端 GBK。

**参数契约**变了（阈值/窗真源、`overrides` 形态、`_factor_param` / `_structure_windows` 签名、买卖语义）→ 同一回合同步现网 md，数字与 `catalog` / `config` 字面量一致。不改 `.cursor/plans/`、`docs/归档/`、`report/grid/`。

默认**不升** `STRATEGY_VER`，除非用户要求或语义已变。加阈值会改 `recipe=` 哈希，探针按现网重算，不要对历史档案旧哈希。

网格：因子轴跟 `LEAVES` 走；overrides 仍是 `overrides.factor_params` / `overrides.structure`。用户没点名则**不跑网格**。
