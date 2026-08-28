# 本地回测说明

用 **KlineDump 日线 CSV** 回放 **真实拼接的 HlBand 脚本**（`qmt_common` + `hlband` 片段），不经过国金编辑器回测。买卖规则、均线、复权键仍以 [`model.md`](./model.md) 与 [`scripts/qmt/hlband/config.py`](./scripts/qmt/hlband/config.py) 为准。

本页说明：行情从哪来、产物写到哪、界面三种模式、复权多选、选股择优。策略买卖点本身不在这里重复。

## 适用场景

- 批量扫票、按自然年切段、对照 SMA/EMA 或多种复权。
- 已有 `tools/csv/`，不想每次开终端编辑器。
- 从已跑完的 `report/<type>/` 打分，生成 `BOOK_STOCKS` 草稿（**不会自动改 config**）。

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

默认硬过滤（可在侧栏改）：跨年轮次 ≥ 6、每年最少轮次默认不启用（0；>0 时窗口内每一年含缺文件/未走完年都要达标）、成交年 ≥ 2、盈利年 ≥ 2 或盈利年占比 ≥ 50%、单笔盈利占毛利 ≤ 70%、剔除波动最高 10%、推荐池 6 只。成交年 / 盈利年 / 每年轮次按选定窗口计。

打分权重（过线之后）：年等权盈亏 30%、胜率 20%、稳定性 20%、利润因子 15%、卖出质量 15%。**不要把得分当分真实夏普**；全池 Top N 有多重选择偏差。

覆盖提示里「缺对照」时：先多选复权跑「批量 + 按自然年分段」；建议均线还要同时勾 SMA/EMA 对照。

产物：`hongli_band/report/local_bt_stock_select.csv`。刷新缓存按钮会清扫描缓存。

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

单测（在 `hongli_band/scripts/local_bt/` 下）：

```bash
python -m unittest test_market_csv
```

## 常见误区

- **侧栏没勾的复权，选股就看不到。** 选股扫磁盘上已有的 `report/<type>/`，与本次勾选无关。没跑过的类型不会凭空出现。
- **本地回测等于三图实盘。** 每次只回放一只标的、独立预算，没有共享 `BOOK_FILE` 的 50%/30%/剩余分档抢槽。
- **改了 `hlband/*.py` 却去改终端 GBK。** 本地回测每次拼接片段；终端模型仍须 `python hongli_band/scripts/qmt/_deploy_qmt_gbk.py`。
- **选股 snippet 会写入 config。** 只展示草稿，要改跟踪池须自己编辑 `BOOK_STOCKS` 再 deploy。
- **QMT 图表「复权方式」决定本地 CSV。** 本地用的是 KlineDump 写出的子目录；图表复权只影响看图。
- **扁平旧 `report/` 与分目录混用。** 出现类型子目录后，选股不再读根目录散落的明细。

## 相关文档

- 策略逻辑与实盘验收：[`model.md`](./model.md)
- 终端回测 log → 图与 Markdown：仓库 skill `qmt-backtest-report`（`python hongli_band/gen_report.py`）
- 代码入口：[`scripts/local_bt/app.py`](./scripts/local_bt/app.py)、[`run.py`](./scripts/local_bt/run.py)、[`stock_select.py`](./scripts/local_bt/stock_select.py)
