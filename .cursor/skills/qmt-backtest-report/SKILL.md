---
name: qmt-backtest-report
description: >-
  从 QMT 终端回测 log 自动生成分析报告：解析成交、成交表 CSV、权益曲线、
  持仓着色 K 线、Markdown 报告。Use when the user mentions 回测报告、分析报告、
  解析 log、成交表、权益曲线、K线图、报告自动化，或 hongli_band/log.txt /
  回测分析报告、plot_trades_kline、report 目录.
---

# QMT 回测报告自动化

将主题目录下的 `log.txt` +（优先）`report/QMT终端操作明细.csv` 一键变成：成交表、权益曲线、持仓着色 K 线、Markdown 报告。  
**产物一律写到 `<主题>/report/`**（日志仍读 `<主题>/log.txt`）。

## 何时使用

- 用户说：生成/更新回测分析报告、解析 log、画权益曲线/K 线
- 主题下已有 `log.txt`（如 `hongli_band/log.txt`）
- 联调结束后需要沉淀数字结论

联调踩坑仍走 [qmt-model-script](../qmt-model-script/SKILL.md)；本 skill **只读日志与画图，不改策略片段、不 deploy**。

## 一键命令（优先执行脚本）

在仓库根目录：

```bash
python .cursor/skills/qmt-backtest-report/scripts/generate_report.py --theme hongli_band
```

先将国金终端导出的 **`QMT终端操作明细.csv`** 放到 `<主题>/report/`（盈亏真源）；无此文件则回退 log 自记账价并告警。

常用参数：

| 参数 | 含义 |
| :--- | :--- |
| `--theme <dir>` | 主题目录；读 `<dir>/log.txt`，写出到 **`<dir>/report/`** |
| `--log <path>` | 显式指定日志 |
| `--out-dir <path>` | 覆盖输出目录（默认 `<主题>/report`） |
| `--terminal-csv <path>` | 显式指定终端操作明细；默认在 `report/` 自动查找 |
| `--no-terminal` | 强制仅用 log 自记账价 |
| `--tag HlBand` | 日志前缀（默认取末次 `xxx vN.N init`） |
| `--ver v1.2` | 锁定版本会话 |
| `--no-kline` | 跳过行情拉取（仅成交表+权益+MD） |

依赖：`pandas`、`matplotlib`、`akshare`（K 线；失败则回退新浪）。

## 产物（写入 `<主题>/report/`）

| 文件 | 内容 |
| :--- | :--- |
| `回测分析报告.md` | 结论摘要 + 成交表 + 绩效 + 图链接 |
| `<tag>_trades.csv` | 成交明细 |
| `<tag>_report_stats.json` | 结构化统计 |
| `<tag>_equity.png` | 权益曲线（预算 + 已实现盈亏累计） |
| `<tag>_trades_kline.png` | K 线：**红=持仓(买→卖)**，**绿=空仓**，▲买 ▼卖 |

人工深度解读可另存同目录（如 `r1.md`），脚本不覆盖非自动生成文件名。

## Agent 工作流

```
进度:
- [ ] 1. 确认主题目录与 log.txt 存在
- [ ] 2. 运行 generate_report.py --theme <主题>（产物进 report/）
- [ ] 3. 核对控制台：trades 数、sum_pnl、wrote 路径含 /report/
- [ ] 4. 如用户要解读：读 report/回测分析报告.md，必要时另写 report/r*.md
```

**默认**：脚本已生成完整 MD；仅当用户要求更深度文字解读时，再追加人工笔记，**不要**手工重算成交表。

## 解析规则（硬约束）

1. **只取末次** `{tag} vX.Y init` 之后的会话（同文件可能混有 KeyboardInterrupt / 旧策略噪声）。
2. 成交配对：`BUY by signal` + `BUY filled` ↔ `SELL by signal` + `SELL done`；卖出执行日取 `SELL by signal` 前一条 bar 日。
3. 盈亏粗算：`(sell_price - buy_price) * shares`，不拆佣金。终端 CSV 有「盈利」列时以该列为准；**组合多标的明细按「代码」各自 FIFO**，禁止跨票配对（否则收益%会假阴/假阳）。一笔卖出吃掉多笔买入时**按买入 lot 拆轮次**（保留各笔买入日/买价，盈利按股数分摊）。
4. 权益：`equity = budget + cum_pnl`（按平仓日阶梯）。
5. K 线着色按持仓区间，**不是**涨跌红绿。

日志字段细节见 [reference-log-patterns.md](reference-log-patterns.md)。

## 主题薄封装

```bash
python hongli_band/gen_report.py
```

改策略后：先覆盖 `log.txt`，再跑本脚本。

## 禁止

- 用手改数字填报告代替跑脚本
- 把其它策略/中断栈算进成交（未切片 session）
- 为画图去改 `qmt_terminal_*.py` 或 GBK 产物
- 把自动产物写到主题根目录（必须进 `report/`）
