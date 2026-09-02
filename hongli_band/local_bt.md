# 本地回测说明

用 **KlineDump 日线 CSV** 回放 **真实拼接的 HlBand 脚本**（`qmt_common` + `hlband` 片段），不经过国金编辑器回测。买卖规则、均线、复权键仍以 [`model.md`](./model.md) 与 [`scripts/qmt/hlband/config.py`](./scripts/qmt/hlband/config.py) 为准。

本页说明：行情从哪来、产物写到哪、界面三种模式、复权多选、选股择优。策略买卖点本身不在这里重复。

## 适用场景

- 批量扫票、按自然年切段、对照 SMA/EMA 或多种复权。
- 已有 `tools/csv/`，不想每次开终端编辑器。
- 从已跑完的 `report/<type>/` 打分，生成 `BOOK_STOCKS` 草稿（**不会自动改 config**）。
- **walk-forward 组合分析**：用过去 N 年组合 KPI 选 Top K，滚动评估持有表现（见下文「数据分析」）。

不要用本地回测代替：三图共享账本、尾盘限价/开盘兜底、券商 T+1 `can_use`。那些只在终端实盘/编辑器路径上完整。

## 和终端回测差在哪

| | 国金编辑器回测 | 本地 CSV 回放 |
| :--- | :--- | :--- |
| 策略代码 | 终端里已 deploy 的 GBK | 每次从片段 **现场拼接**（与 `_deploy_qmt_gbk.py` 同一 `MODULE_ORDER`） |
| 行情 | 终端主图 / `get_market_data_ex` | `tools/csv/<复权>/` 的 `*_1d_*.csv` |
| 成交记账 | 终端操作明细 | `local_bt_*_操作明细.csv`（FIFO，格式对齐终端导出） |
| 账户 | 回测账户 | 每只标的独立走 `TRADE_BUDGET`（默认 10 万），**不是**三图 `BOOK_FILE` |
| 周线 | 原生 `1w`（丢掉未收盘周） | 同目录 `{code}_1w_*.csv`；没有则日线合成并丢掉未收盘周 |
| 成交价 | 与脚本一致：信号日 **收盘价**；隔夜残留次日开盘 | 相同（Mock 按日 K 推进 `handlebar`） |

走区间前的历史 K 线仍在 CSV 里，用于均线/周线暖机。起点太靠前、周线不足约 60 根时，日志会打 `WARN weekly bars at start < 60`。

## 开始之前

1. Python 能 `import pandas`；界面还需要 Streamlit / Plotly：

   ```bash
   pip install -r hongli_band/scripts/local_bt/requirements.txt
   ```

2. 仓库里有日线 CSV。默认根目录：`tools/csv/`。每种复权一个子目录：

   | 目录名 | 含义 |
   | :--- | :--- |
   | `none` | 不复权 |
   | `front` | 前复权（价差） |
   | `back` | 后复权（价差） |
   | `front_ratio` | 等比前复权（默认） |
   | `back_ratio` | 等比后复权 |

   文件名形如 `600350_SH_1d_20180102_20260827.csv`。有周线时同目录再放 `*_1w_*.csv`。

3. 没有 CSV 时，在国金里跑 **KlineDump / 行情导出**（改完片段须先 deploy）：

   ```bash
   python tools/scripts/qmt/_deploy_qmt_gbk.py
   ```

   导出名单、起始日、复权种类见 [`tools/scripts/qmt/kldump/config.py`](../tools/scripts/qmt/kldump/config.py)（`DUMP_STOCKS`、`HIST_START`、`DIVIDEND_TYPES`、`OUT_DIR`）。`FOLLOW_CHART_RANGE=False` 时从 `HIST_START` 起导，给周线暖机留长度。

## 启动界面

在仓库根目录：

```bash
python hongli_band/local_bt_ui.py
```

等价于 `streamlit run hongli_band/scripts/local_bt/app.py`。浏览器打开后，顶栏选模式。

成功标志：能列出 `csv/<type>/` 里的标的，或「仅分析」能看到已有操作明细。

界面表格统一 **中文表头**；凡含标的代码的列，列名用「代码」，并在旁紧跟「名称」（来自 `STOCK_META`，未知则显示裸代码）。磁盘 CSV schema 不变。

## 目录约定

读和写按 **复权类型** 分目录，不要把五种 CSV 揉进同一层。

```
tools/csv/<type>/          ← 行情（KlineDump）
hongli_band/report/<type>/ ← 本地回测 log / 操作明细 / 批量汇总
hongli_band/report/local_bt_stock_select.csv  ← 选股总表（写在 report 根，不进某个 <type>）
hongli_band/回测记录/      ← 旧终端导出；「仅分析」会一并列出
```

侧栏「行情根目录」默认是 `tools/csv`。勾选的每种复权：读 `csv/<type>/`，写 `report/<type>/`。路径名已经是类型时不会再拼一层。

旧的扁平 `report/*.csv`（没有 `<type>` 子目录）仍能被选股扫描；一旦出现 `none`/`front`/… 子目录，就只扫这些子目录。

## 界面三种模式

### 跑本地回测

侧栏 **复权类型可多选**（中文标签）。默认勾选等比前复权。至少一种，否则开始按钮禁用。每种勾选独立跑一遍，互不覆盖目录。

**单标的**

- 下拉列表是所选复权目录里标的的 **并集**。
- 同一套起止日期；开跑后对每种复权找该票 `*_1d_*.csv`，缺文件则跳过并提示。
- 勾选「SMA/EMA 对照」时，每种复权再各跑 SMA 与 EMA。
- 上传 CSV 只写入 **第一种** 勾选复权。
- 跑完后若成功 ≥2 种复权：先出 KPI 对照表与权益曲线叠加，再用 tab 切换查看该复权的 K 线 / 成交（K 线价格口径不同，不叠加）。勾了均线对照时，对照表与权益叠加用各复权的 EMA，tab 内仍是 SMA/EMA 对照。

**批量（按标的汇总）**

- 标的勾选也是并集；某类型没有该票则该类型跳过。
- 「按自然年分段」：每年独立账户、年初空仓；暖机仍用该年之前的历史 K 线。选股要用的分年对照走这条。
- 进度按「复权 × 任务」。任务量大约是 **标的 × 年 × 均线 × 复权数**。
- 汇总 CSV 写在各自 `report/<type>/`（`local_bt_batch_summary.csv`；对照时还有 `local_bt_ma_compare.csv` 等），不把五种揉进一份。
- 结果区可按复权筛选。选「全部」时汇总表带复权列，按年汇总按 **年 × 复权** 拆开；明细下拉为 `标的 · 复权`（分年再加年）。点开某标的同年若有多种复权，同样给出对照表、权益叠加和 tab 切换。

未勾选均线对照时，价格均线仍走 `BOOK_STOCKS[code].ma_type`，缺省全局 `MA_TYPE`（当前默认 EMA）。

### 仅分析已有明细

扫描侧栏勾选的 `report/<type>/` **并集**，外加 `hongli_band/回测记录`。用来看已有成交表、权益、K 线，不再开跑。

### 选股方案

扫描 **`report/` 下已经存在的全部复权子目录**，不受本次侧栏勾选限制。侧栏先选 **起始年 / 结束年**，再调硬过滤（最少轮次、成交年、盈利年、单笔盈利占比、波动分位、Top N）。改年只重打分，不重新扫描。

流程：

1. 每个复权目录内，在**选定年**上做 SMA/EMA 择优（成对年份总盈亏；接近再比胜率；再平落 EMA）。
2. 再在「窗口内仍有分年 KPI」的复权之间，取 **year 键交集**，比总盈亏；与最高者 `|Δ|≤1` 元视为接近，再比胜率；仍平优先 `front_ratio`。
3. 用胜出复权的窗口内分年 KPI 打分；股性（年化波动、贴 MA20）读 **该窗口建议复权** 的 `csv/<type>/`。
4. 过线后按得分取 Top N。页面给出 `BOOK_STOCKS` 草稿：有建议均线才出行动；有建议复权则带上 `"dividend_type"`。

默认硬过滤、侧栏控件范围与打分权重写在 `hongli_band/scripts/local_bt/select_config.py`，侧栏可改。成交年 / 盈利年 / 每年轮次按选定窗口计。

打分权重（过线之后百分位加权）也在该文件。**不要把得分当分真实夏普**；全池 Top N 有多重选择偏差。

覆盖提示里「缺对照」时：先多选复权跑「批量 + 按自然年分段」；建议均线还要同时勾 SMA/EMA 对照。

产物：`hongli_band/report/local_bt_stock_select.csv`。刷新缓存按钮会清扫描缓存。

### 数据分析（walk-forward + 组合回放）

顶栏 **第四模式**。与「选股方案」共用硬过滤/权重控件，但打分与持有走 **组合 BOOK 回放**（全池共享 `BOOK_LOT_MAX` 槽位），而不是读单票分年明细直接相加。

先填 **参数表单**，点「开始分析」后才跑（改控件不会即时重算）。侧栏「刷新缓存」会清扫描缓存，**不会**删除已生成的组合回放文件。

表单顶部可选 **分析类型**：

| 类型 | 做什么 |
| :--- | :--- |
| **Walk-forward** | 过去 N 年打分 → Top K → 持有期组合回放（下文默认描述） |
| **固定标的** | 跳过打分；用 `config.BOOK_STOCKS`（表单可改，不写回）对起止年做 **一段连续** 组合回放 |

#### 固定标的回放

- 默认载入 [`hlband/config.py`](./scripts/qmt/hlband/config.py) 的 `BOOK_STOCKS`（含 `ma_type` / `dividend_type`）；可在表单 `data_editor` 增删改；「从 config 重载」恢复。
- 区间：数据起始/结束年 → `YYYY0101`–`YYYY1231` 连续回放（复利在区间内滚动，不按年重置钱包）。
- 仓位：与 Walk-forward 相同（资金帽 / `BOOK_LOT_MAX` / 分档）；默认开复利；可强制重跑。
- 产物：`report/<type>/local_bt_book_fixed_{start}_{end}_k{hash8}_*`；总表 `report/local_bt_fixed_book.csv`。
- CLI：

```bash
python hongli_band/scripts/local_bt/select_analysis.py \
  --mode fixed --data-start 2024 --data-end 2025 --force-rerun
```

#### 适用场景

- 验证「过去 N 年打分 → 下一年持有 Top K」是否稳健，而不是只看单段全样本。
- 需要 **组合级** KPI（抢槽、分档预算）来打分，而不是各票独立 10 万相加。
- 已有 `report/<type>/` 分年单票明细（用于 ma/div 建议、可选 `single` 回退），以及 `tools/csv/` 日线。

不适合替代：终端三图共享 `BOOK_FILE` 账本、尾盘限价/开盘兜底。本地组合回放是近似模拟。

#### 起止年 = 数据年，不是评估年

表单里的 **数据起始年 / 数据结束年** 表示可用于打分/KPI 的自然年区间；系统据此 **自动推出首评年** 与 **评估持有年**。

规则（实现见 `select_analysis.data_and_eval_years`）：

1. `data_years` = 扫描到的自然年 ∩ `[数据起始, 数据结束]`
2. `eval_years` = `data_years` 里，前面已有 ≥ `lookback_n` 个 **同属 data_years** 的年份
3. 打分窗口 = 每个评估年 **之前** 的最近 `lookback_n` 个 **data_years**（不含评估年本身）

**示例**（数据 2020–2026，回看 2，换仓 1，Top 3）：

| 角色 | 年份 | 说明 |
| :--- | :--- | :--- |
| 数据年（仅打分） | 2020、2021 | 不出现在 CSV 持有行 |
| 首评 / 首次持有 | **2022** | 用 2020–2021 组合 KPI 选 Top3 → 2022 组合持有回放 |
| 滚动持有 | 2023 | 用 2021–2022 选 Top3 → 2023 回放 |
| … | 2024–2026 | 窗口随评估年前移 |

提交表单后界面会提示：`数据 2020–2026 · 回看 2 后首评 2022 · 评估至 2026`。

注意：打分窗口 **只从 data_years 取 prior**，不会用到 data 区间外的扫描年（例如 data 从 2020 起时，即使用户磁盘上有 2019 分年明细，2022 的窗口仍是 2020–2021，而非 2019–2020）。

#### 三阶段流程

```
Phase A  打分预计算（组合）
  对每个需要的自然年 Y：全打分池 run_book_backtest(202Y0101–202Y1231)
  → 操作明细按「代码」列归因 → portfolio_kpi[stock][Y]

Phase B  walk-forward 选股（每个换仓段）
  段首 select_year = 该段第一年
  window = select_year 前 lookback_n 个 data_years
  score_universe(kpi_source=portfolio|single, score_years=window) → Top K

Phase C  持有期回放（组合）
  段内每个评估年 Hy：仅 Top K 篮子 run_book_backtest(Hy)
  → portfolio_pnl、naive_pnl（对照）
```

**Phase A — 打分预计算**

- 对象：**打分池**（默认扫描到的全部 BOOK 候选，见 `score_pool`）。
- 每年 **1 次** 全池组合回放（30 只票共享 3 个槽位，与策略 `BOOK_LOT_MAX` 一致）。
- 产物缓存：`report/<type>/local_bt_book_score_{YYYY}_u{hash8}_操作明细.csv`  
  `hash8` 由打分池内各票 `ma_type` / `dividend_type` 决定；池或复权类型变了会换 hash。
- 空明细文件 **不会** 当作有效缓存（会自动重跑）。

**Phase B — walk-forward 选股**

- `rebalance_years=1`：每年换仓；`=2`：每 2 个评估年共用同一篮子（段首重新选股）。
- `score_mode=portfolio`（默认）：用 Phase A 的 **组合归因 KPI** 在 window 内聚合后硬过滤 + 百分位加权。
- `score_mode=single`：回退为读单票分年明细 KPI（与「选股方案」同源），**不**再跑组合预计算。
- 硬过滤、权重与「选股方案」相同；`portfolio` 模式下会自动 **放宽** `min_n_buy`（组合归因轮次少于单票独立回测）并关闭「单笔盈利占比」过滤。

**Phase C — 持有期回放**

- 仅对 Phase B 选出的 Top K 再跑组合回放（小池，竞争弱于 Phase A 全池）。
- 产物：`report/<type>/local_bt_book_hold_{YYYY}_p{段号}_k{hash8}_操作明细.csv`
- `naive_pnl`：Top K 在对应自然年的 **单票分年明细** `sum_pnl` 之和（对照列，不是组合回放结果）。

#### 界面参数说明

| 分组 | 参数 | 含义 |
| :--- | :--- | :--- |
| 数据区间 | 数据起始/结束年 | 见上文；默认扫描到的最早/最晚年 |
| Walk-forward | 打分回看年数 `lookback_n` | 段首向前取几个自然年做 KPI 窗口 |
| | 换仓周期 `rebalance_years` | 几个评估年共用一篮子 |
| | 每段持仓只数 `top_k` | Top K，上限 9 |
| | 打分 KPI | `portfolio` 组合回放 / `single` 单票 KPI |
| | 打分池 | `scanned` 全池 / `passed_prefilter` 宽松预过滤后再全池回放 |
| | 强制重跑回放 | 忽略已有 book_score / book_hold 缓存 |
| | 打分并行进程 | Phase A 按年并行；0=顺序 |
| 硬过滤 | 同选股方案 | 最少轮次、成交年、盈利年、波动分位等 |
| 组合仓位 | 组合资金帽 | 对应 `TRADE_BUDGET` |
| | BOOK_LOT_MAX | 同时持仓槽位数 |
| | 大仓档 / 加仓档 | `LOT_OPEN_FRAC` / `LOT_ADD_FRAC` |
| 高级 | 打分权重 | pnl / 胜率 / 稳定性 / 盈亏比 / 质量 |

常量默认值见 `hongli_band/scripts/local_bt/select_config.py` 的 `ANALYSIS_*`、`DEFAULT_FILTERS`、`WEIGHTS`；组合仓位默认回落 `hlband/config.py`。

#### 产物与结果字段

**总表**（固定路径）：`hongli_band/report/local_bt_select_analysis.csv`

| 列 | 含义 |
| :--- | :--- |
| `year` | 评估持有年 |
| `period_i` | 换仓段序号 |
| `select_year` | 该段段首（选股年） |
| `is_rebalance` | 是否段首换仓年 |
| `picks` | 该段 Top K（顿号分隔） |
| `pick_details` | Top K 明细列表：`stock` / `ma_type` / `dividend_type`（界面「查看标的」弹窗；CSV 中为 JSON 字符串） |
| `portfolio_pnl` | 该年 Top K **组合回放** 盈亏 |
| `naive_pnl` | 该年 Top K **单票明细相加**（对照） |
| `status` | `ok` / `无推荐` / `窗口不足` / `回放失败:…` |
| `params_json` | 当次分析完整参数快照 |

界面另展示：有效评估年数、组合合计盈亏、年均盈亏、盈利年占比、换仓段汇总、累计组合盈亏曲线。

**缓存明细**（在默认复权 `report/front_ratio/`，随 `DEFAULT_DIVIDEND_TYPE`）：

- 打分：`local_bt_book_score_{YYYY}_u{hash8}_*`
- 持有：`local_bt_book_hold_{YYYY}_p{段}_k{hash8}_*`

#### CLI

```bash
python hongli_band/scripts/local_bt/select_analysis.py \
  --report-dir hongli_band/report \
  --csv-dir tools/csv \
  --data-start 2020 --data-end 2026 \
  --lookback-n 2 \
  --rebalance-years 1 \
  --top-k 3 \
  --score-mode portfolio \
  --score-pool scanned \
  --force-rerun \
  --workers 0
```

| 参数 | 说明 |
| :--- | :--- |
| `--data-start` / `--data-end` | 数据/KPI 自然年（含端点） |
| `--eval-start` / `--eval-end` | 同上别名（兼容旧用法） |
| `--lookback-n` | 打分回看年数，默认 2 |
| `--rebalance-years` | 换仓周期，默认 1 |
| `--top-k` | Top K，默认 3 |
| `--score-mode` | `portfolio` / `single` |
| `--score-pool` | `scanned` / `passed_prefilter` |
| `--force-rerun` | 强制重跑所有组合回放 |
| `--workers` | Phase A 并行进程数 |
| `--out` | 总表路径，默认 `report/local_bt_select_analysis.csv` |

#### 前置依赖

1. **`tools/csv/<type>/`**：组合回放现场读日线，不读旧明细。
2. **`report/<type>/` 单票分年明细**（批量 + 按自然年分段）：用于 `scan_reports` 定标的清单、ma/div 建议、`single` 回退、`naive_pnl` 对照。  
   **不是**组合盈亏的数据源（合并旧明细会失真，故持有期单独回放）。
3. 修改过组合回放相关代码（`book_backtest.py`、`run.py` 的 OHLCV 路由、`hlband/universe.py` 等）后，应对相关年份勾选 **强制重跑回放**，避免命中修复前的缓存。

#### 与「选股方案 / 批量回测」的区别

| | 选股方案 | 数据分析 | 批量回测 |
| :--- | :--- | :--- | :--- |
| 目的 | 静态窗口出 BOOK 草稿 | 滚动样本外评估 Top K 组合 | 单票或多票独立 KPI |
| 打分 KPI | 单票分年明细 | 默认 **组合归因** | 单票明细 |
| 持有/盈亏 | 无 | Top K 组合回放 | 每票独立预算 |
| 起止年 | 选定打分窗口 | **数据年** → 自动推评估年 | 用户指定 walk 区间 |
| 产物 | `local_bt_stock_select.csv` | `local_bt_select_analysis.csv` | 各票分年明细 |

#### 复利回测（local_bt）

默认 **开启**（数据分析表单「复利回测」；侧栏「复利回测」用于单票/批量）。**仅 local_bt**，QMT 编辑器回测仍固定 `TRADE_BUDGET`。

| 项 | 说明 |
| :--- | :--- |
| 口径 | `cap = CASH_RATIO × (现金 + 池内持仓 cost)`；买卖更新现金 |
| 定仓 | patch `_trade_budget_cap` → 动态 cap × 50%/30%/剩余档 |
| 明细列 | `买入权重(%)` / `当前权重(%)` 填 cap 占比；追加 `可部署资金` / `组合权益` |
| walk-forward 持有 | **跨年传递**期末权益作下年初始现金；`portfolio_pnl = wallet_end - wallet_start` |
| 打分预计算 Phase A | 仍每年独立 `TRADE_BUDGET`（不改 KPI 排序） |
| 缓存 | 改逻辑或开关后须 **强制重跑** |

关闭复利：数据分析取消勾选，或 CLI `--no-compound`。

#### 近似与局限

- **打分池（大池）vs 持有池（Top K）**：Phase A 全池抢槽，Phase C 仅 K 只，竞争强度不同；组合 KPI 反映的是「在全池里的表现」，不是持有池里的表现。
- **回测跨票分档**：local_bt 已 patch `_chart_next_frac`，按 universe hot 汇总全池已占 50%/30%/剩余档；与实盘仍可能有 cost 市值等细微差。
- **ma / div 建议**：仍来自单票 SMA/EMA、复权对照（`scan_reports`），不是组合回放现场推导。
- **非实盘账本**：无 `BOOK_FILE` 跨日打卡、无实盘均分冻结窗口的完整语义。
- **得分非 Sharpe**：百分位加权排名，存在多重检验偏差；勿把 `portfolio_pnl` 直接外推为实盘预期。

#### 常见问题

| 现象 | 可能原因 | 处理 |
| :--- | :--- | :--- |
| 某年 `status=无推荐` | 打分窗口内组合 KPI 不过硬过滤；或 Phase A 该年无成交归因 | 看界面 notes / 降 `min_n_buy`；勾 **强制重跑**；试 `score_mode=single` 对照 |
| 2024+ 突然全无推荐 | 窗口内含 **空组合 KPI 年**（如 2023 缓存为空） | 强制重跑；确认 `local_bt_book_score_{Y}_*` 明细非空 |
| 首评年比预期早/晚 | 混淆了 **数据年** 与 **评估年**；或 data 区间外还有扫描年 | 以表单提示的首评年为准；数据区间应覆盖足够回看年 |
| 多年 picks 完全相同 | 窗口内 KPI 排序稳定；或曾出现 OHLCV 串票导致 KPI 失真 | 强制重跑修复后的缓存；缩短/加长 data 区间观察 |
| 很慢 | Phase A 每年全池回放 × 数据年数 | 减小 data 区间；`workers`>0；利用 score 缓存（勿误删有效文件） |

单测：`python -m unittest test_select_analysis test_book_backtest`（在 `hongli_band/scripts/local_bt/` 下）。

## 无界面命令行

仓库根目录。`--csv-dir` / `--out` 是 **根目录**，每种复权再拼 `<type>`。

单标的 / 批量回测：

```bash
python hongli_band/scripts/local_bt/run.py --csv-dir tools/csv --start 20210101 --end 20251231 --split year --compare-ma --dividend-type front,front_ratio
```

`--dividend-type` 逗号分隔；未给默认 `front_ratio`。`--split year` 按自然年；`--compare-ma` 各跑 SMA/EMA。`--workers 0` 为自动进程数。多种复权一次进同一个进程池；同一标的 CSV 的年分段 / SMA·EMA 对照在同一 worker 内顺序跑、复用已加载的行情。

选股（同样扫兄弟复权目录）：

```bash
python hongli_band/scripts/local_bt/stock_select.py --report-dir hongli_band/report --csv-dir tools/csv
python hongli_band/scripts/local_bt/stock_select.py --report-dir hongli_band/report --csv-dir tools/csv --year-start 2024 --year-end 2025
```

默认写出 `hongli_band/report/local_bt_stock_select.csv`。`--year-start` / `--year-end` 含端点；不传则用扫描到的全部自然年。建议均线、建议复权与硬过滤都在该窗口内重算。`--min-n-buy-year` 为每年最少轮次（0 不启用）。

walk-forward 组合分析（数据年 → 自动推首评年）：

```bash
python hongli_band/scripts/local_bt/select_analysis.py \
  --report-dir hongli_band/report \
  --csv-dir tools/csv \
  --data-start 2020 --data-end 2026 \
  --lookback-n 2 --rebalance-years 1 --top-k 3 \
  --score-mode portfolio --force-rerun
```

详见上文「数据分析」一节；`--eval-start` / `--eval-end` 为 `--data-start` / `--data-end` 别名。

单测（在 `hongli_band/scripts/local_bt/` 下）：

```bash
python -m unittest test_market_csv test_select_config test_select_analysis test_book_backtest
```

## 常见误区

- **侧栏没勾的复权，选股就看不到。** 选股扫磁盘上已有的 `report/<type>/`，与本次勾选无关。没跑过的类型不会凭空出现。
- **本地回测等于三图实盘。** 每次只回放一只标的、独立预算，没有共享 `BOOK_FILE` 的 50%/30%/剩余分档抢槽。
- **改了 `hlband/*.py` 却去改终端 GBK。** 本地回测每次拼接片段；终端模型仍须 `python hongli_band/scripts/qmt/_deploy_qmt_gbk.py`。
- **选股 snippet 会写入 config。** 只展示草稿，要改跟踪池须自己编辑 `BOOK_STOCKS` 再 deploy。
- **QMT 图表「复权方式」决定本地 CSV。** 本地用的是 KlineDump 写出的子目录；图表复权只影响看图。
- **扁平旧 `report/` 与分目录混用。** 出现类型子目录后，选股不再读根目录散落的明细。
- **数据分析的起止年当评估年。** 应填 **数据年**；首评年 = 数据起始 + 回看年数（在 data 区间内自动计算）。
- **分析后不勾强制重跑却换了回放逻辑。** 空明细会自动重跑，但旧的有效缓存仍可能命中；改代码后务必强制重跑相关年份。
- **把 `naive_pnl` 当组合成绩。** 它是单票明细相加对照；组合结果看 `portfolio_pnl`。

## 相关文档

- 策略逻辑与实盘验收：[`model.md`](./model.md)
- 终端回测 log → 图与 Markdown：仓库 skill `qmt-backtest-report`（`python hongli_band/gen_report.py`）
- 代码入口：[`scripts/local_bt/app.py`](./scripts/local_bt/app.py)、[`run.py`](./scripts/local_bt/run.py)、[`stock_select.py`](./scripts/local_bt/stock_select.py)、[`select_analysis.py`](./scripts/local_bt/select_analysis.py)、[`book_backtest.py`](./scripts/local_bt/book_backtest.py)
