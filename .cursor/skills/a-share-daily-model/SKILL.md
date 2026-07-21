---
name: a-share-daily-model
description: >-
  管理 chinaAModel 仓库内 A 股日度选股模型：新建主题目录、每日选股与观察池跟踪剔除、
  运行通达信等价自动选股、历史回测。Use when the user mentions chinaAModel、日度选股、
  观察池、跑公式、历史回测、新增选股模型、大蓝筹防御, or 科技成长波段反转.
---

# A 股日度选股模型工作流

对齐 `stock_analysis_model_tracking` 的「一主题一目录」，周期为**每个交易日**。  
模板与目录约定见 [reference-layout.md](reference-layout.md)、[reference-templates.md](reference-templates.md)。

## 仓库布局（多模型）

```
chinaAModel/
  README.md                 # 模型索引
  requirements.txt
  data/daily/               # 共享日线缓存（各主题复用）
  <主题名>/                 # 例：科技成长波段反转
    model.md
    log/
    portfolio/active.md
    output/
    scripts/                # run_screener.py / run_backtest.py（按主题定制）
  .cursor/skills/a-share-daily-model/
```

---

## 路径选择

| 用户意图 | 路径 |
| :--- | :--- |
| 新增一个日度选股模型 | **A. 建档** |
| 某主题续写今日日志 / 更新观察池 | **B. 续日** |
| 自动跑选股公式 | **C. 选股** |
| 跑历史回测 | **D. 回测** |
| 只改手册阈值 | 直接改 `<主题>/model.md` |

---

## A. 建档（新主题）

```
建档进度:
- [ ] 1. 定主题目录名（中文业务名，如 科技成长波段反转）
- [ ] 2. 写 model.md（因子 + 公式 + 出场 R 规则 + 催化剂）
- [ ] 3. 建 log/_template.md、log/README.md、portfolio/active.md
- [ ] 4. 写首期 log/YYYY-MM-DD.md
- [ ] 5. 在 model.md 追加「日度滚动工作流」节
- [ ] 6. 按需复制/改造 scripts/run_screener.py、run_backtest.py
- [ ] 7. 根 README 索引表加一行
```

`THEME_ROOT = scripts 的上一级`；`REPO_ROOT = THEME_ROOT.parent`；日线缓存必须写 `REPO_ROOT/data/daily/`。

---

## B. 续日（先跟踪后选股）

```
续日进度:
- [ ] 1. 读 <主题>/model.md 出场规则 + portfolio/active.md + 上一日日志
- [ ] 2. 【跟踪】R1–R5 复核 → 剔除行移出 active.md
- [ ] 3. 【选股】跑 C 或手工公式 → 四维全过入库
- [ ] 4. 催化剂双向核对（未核不得标「可建仓」）
- [ ] 5. 写 log/YYYY-MM-DD.md；更新 log/README 索引
- [ ] 6. （可选）同步 model.md 滚动摘要
```

**强制顺序**：先剔除，后选股。  
**状态**：`候选` / `持仓` / `减仓半仓`；已剔除禁止留在 `active.md`。

默认剔除编码（以该主题 `model.md` 为准，可改名不可留僵尸规则）：

| 码 | 典型含义 |
| :--- | :--- |
| R1 | 硬止损（破起爆开盘/防守价） |
| R2 | 止盈减仓 |
| R3 | 趋势保护线破位（如 MA10） |
| R4 | 时间清仓 |
| R5 | 候选失效 |

行动用词：`观望` / `建仓` / `持有` / `减仓50%` / `剔除` / `时间清仓`。缺数标 `待核`，禁止编造行情。

---

## C. 选股（自动跑公式）

在主题目录：

```bash
python scripts/run_screener.py
```

- 读该主题公式逻辑；结果写入 `<主题>/output/screener_YYYY-MM-DD.json|.csv`
- 命中票写入 `portfolio/active.md`（默认 `候选`），并记入当日日志「新信号」表
- 0 命中也要写日志（预筛数、技术面通过数、失败原因摘要）
- 数据：baostock 历史 + 快照补当日 K；共享缓存 `data/daily/`

当前科技成长主题限制：仅 `300/688`；无 CONCEPT 扩展；市值 50–500 亿（腾讯字段）。

---

## D. 回测

```bash
python scripts/run_backtest.py
```

- 输出：`output/backtest_report_*.md`、`backtest_trades_*.csv`、`backtest_summary_*.json`
- 报告须含：胜率、均收益、中位数、出场分布、主要假设（是否过滤市值/催化）
- 首次会拉取并缓存日线，耗时长；已有 `data/daily/*.csv` 则增量跳过

---

## 完成标准

**建档**：主题目录三件套 + model.md 滚动节 + 根 README 已登记  
**续日**：先剔后选；索引已更新；active 无应删未删  
**选股/回测**：output 有产物；关键数字写入当日日志或回测报告  

## 附加资源

- [reference-layout.md](reference-layout.md) — 目录与脚本路径约定  
- [reference-templates.md](reference-templates.md) — log / portfolio 模板骨架  
