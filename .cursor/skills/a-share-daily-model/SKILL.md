---
name: a-share-daily-model
description: >-
  管理 chinaAModel / strategy-tracking 内 A 股日度选股模型：建档、续日、选股、
  list.md 名单回测（含总资金/定额仓位）、策略变更（origin→model）、交易明细入报告。
  Use when the user mentions chinaAModel、日度选股、观察池、跑公式、历史回测、
  list回测、定额仓位、策略变更、origin、周日双周期、大蓝筹防御、科技成长波段反转、
  红利资产, or 建档.
---

# A 股日度选股模型工作流

对齐「一主题一目录」，周期为**每个交易日**。  
模板与约定见 [reference-layout.md](reference-layout.md)、[reference-templates.md](reference-templates.md)、[reference-backtest.md](reference-backtest.md)。

## 仓库布局（多模型）

```
strategy-tracking/   # 或 chinaAModel/
  README.md                 # 模型索引
  list.md                   # 可选：共享股票名单（可复制到主题目录）
  requirements.txt
  data/daily/               # 共享日线缓存
  <主题名>/
    model.md                # 现行手册（含变更记录）
    origin.md               # 可选：优化草案 / 变更来源
    list.md                 # 可选：主题股票池
    log/  portfolio/  output/  scripts/
  .cursor/skills/a-share-daily-model/
```

示例主题：`科技成长波段反转`、`大蓝筹防御型波段策略`、`红利资产·绝对防御低回撤波段策略`、`A股周日双周期趋势波段交易策略系统`。

---

## 路径选择

| 用户意图 | 路径 |
| :--- | :--- |
| 新增一个日度选股模型 | **A. 建档** |
| 某主题续写今日日志 / 更新观察池 | **B. 续日** |
| 自动跑选股公式 | **C. 选股** |
| 跑历史回测（宽池或 list 名单） | **D. 回测** |
| 按 origin / 口述落地策略变更 | **E. 策略变更** |
| 只改手册阈值 | 直接改 `<主题>/model.md` |

---

## A. 建档（新主题）

```
建档进度:
- [ ] 1. 定主题目录名（中文业务名）
- [ ] 2. 写 model.md（因子 + 公式 + 出场 R 规则 + 仓位；可先有草稿）
- [ ] 3. 建 log/_template.md、log/README.md、portfolio/active.md
- [ ] 4. 写首期 log/YYYY-MM-DD.md（空池待命亦可）
- [ ] 5. 在 model.md 追加「日度滚动工作流」节
- [ ] 6. 按需改造 scripts/run_screener.py、run_backtest.py（支持 --universe list）
- [ ] 7. 根 README 索引表加一行
- [ ] 8. （可选）复制仓库根 list.md → 主题 list.md
```

`THEME_ROOT = scripts 的上一级`；`REPO_ROOT = THEME_ROOT.parent`；日线缓存必须写 `REPO_ROOT/data/daily/`。

---

## B. 续日（先跟踪后选股）

```
续日进度:
- [ ] 1. 读 <主题>/model.md 出场规则 + portfolio/active.md + 上一日日志
- [ ] 2. 【跟踪】按该主题现行 R 规则复核 → 剔除行移出 active.md
- [ ] 3. 【选股】跑 C 或手工公式 → 硬条件全过入库
- [ ] 4. 环境/催化剂核对（未核不得标「可建仓」；缺数标「待核」）
- [ ] 5. 写 log/YYYY-MM-DD.md；更新 log/README 索引
- [ ] 6. （可选）同步 model.md 滚动摘要
```

**强制顺序**：先剔除，后选股。  
**状态**：`候选` / `持仓` / `减仓半仓`；已剔除禁止留在 `active.md`。

默认剔除编码（**以该主题 `model.md` 为准**，可改名不可留僵尸规则）：

| 码 | 典型含义（示例，非强制） |
| :--- | :--- |
| R1 | 硬止损 |
| R2 | 阶段止盈 / 减仓半仓 |
| R3 | 趋势线破位清仓 |
| R4 | 时间清仓（若主题仍使用） |
| R5 | 候选失效 |

行动用词：`观望` / `建仓` / `持有` / `减仓50%` / `剔除` / `时间清仓`。禁止编造行情。

---

## C. 选股（自动跑公式）

```bash
cd <主题目录>
python scripts/run_screener.py
```

- 逻辑必须对齐该主题现行 `model.md`（含优化版规则）
- 结果：`output/screener_YYYY-MM-DD.json|.csv`
- 命中写入 `portfolio/active.md`（默认 `候选`），记入当日日志
- 0 命中也要写日志；共享缓存 `data/daily/`

---

## D. 回测

```bash
cd <主题目录>
python scripts/run_backtest.py --universe list          # 默认优先名单
python scripts/run_backtest.py --universe mainboard     # 宽池
python scripts/run_backtest.py --list path/to/list.md   # 指定名单
```

### 必须做到

1. **股票池**：`list` 解析主题（或指定）`list.md` 表格 `| 序号 | 股票代码 | 股票名称 |`；无名单再回退宽池  
2. **资金模型**（用户指定时）：写入 `model.md` 与脚本常量；常见默认见下  
3. **产物**：
   - `output/backtest_report_*.md`（list 池文件名含 `list_`）
   - `output/backtest_trades_*.csv`
   - `output/backtest_summary_*.json`
   - 若有跳过：`backtest_skipped_*.csv`
4. **报告正文必须含**：
   - 摘要（胜率、均/中位数、出场分布、资金与期末权益）
   - 假设（过滤、R 规则、是否计税费）
   - **信号交易明细表**（按入场日；含股数/成本/盈亏元若启用定额）
   - 零信号标的、分票 Top/Bottom（若适用）
   - 跳过信号表（满仓/现金不足等）
5. **关键数字**写入当日 `log/YYYY-MM-DD.md` 与 `log/README` 索引摘要  

细节与定额配资算法见 [reference-backtest.md](reference-backtest.md)。

### 常见资金约定（周日双周期等）

| 参数 | 默认 |
| :--- | :--- |
| 总盘 | 200_000 |
| 每信号定额 | 50_000（整手向下取整） |
| 最大同时持仓 | 4（= 总盘/定额） |
| 满仓/现金不足 | **跳过**该信号并记入 skipped |

---

## E. 策略变更（origin / 口述 → 现行手册）

用户提供 `origin.md`、附件优化版或口述规则时：

```
策略变更进度:
- [ ] 1. 对照 origin（或口述）与现行 model.md，列出差异表
- [ ] 2. 更新 model.md：写入「变更记录」表 + 重写相关章节（筛选/入场/出场/公式）
- [ ] 3. 同步 scripts/run_screener.py、run_backtest.py（阈值与 R 逻辑）
- [ ] 4. 同步 log/_template.md、log/README.md、portfolio/active.md（R 释义与仓位口径）
- [ ] 5. 保留 origin.md 作为变更来源；勿删历史回测文件除非用户要求
- [ ] 6. 若用户要验证：按 D 用 list.md 重跑回测，更新报告与当日日志
- [ ] 7. 在 model.md「最近一日摘要」注明版本与回测结果要点
```

**变更记录表示例**（放在 `model.md` 文首附近）：

| 日期 | 来源 | 摘要 |
| :--- | :--- | :--- |
| YYYY-MM-DD | origin.md | R1/R2/R3 与标的门槛变更要点… |

R 规则以**变更后的 model.md** 为唯一真源；脚本不得残留旧出场逻辑。

---

## 完成标准

| 路径 | 完成标准 |
| :--- | :--- |
| **建档** | 三件套 + model 滚动节 + 根 README 已登记 |
| **续日** | 先剔后选；索引已更新；active 无应删未删 |
| **选股** | output 有 screener 产物；日志有命中/零命中记录 |
| **回测** | report/trades/summary 齐全；报告含交易明细；关键数字入日志 |
| **策略变更** | model 变更记录 + 脚本/模板已对齐；可选 list 回测已刷新 |

## 附加资源

- [reference-layout.md](reference-layout.md) — 目录与脚本路径  
- [reference-templates.md](reference-templates.md) — log / portfolio 骨架  
- [reference-backtest.md](reference-backtest.md) — list 回测、定额仓位、报告章节  
