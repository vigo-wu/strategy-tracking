---
name: qmt-model-script
description: >-
  将 strategy-tracking 主题策略转为 QMT 可运行脚本：国金终端模型
  （init/handlebar/passorder、GBK，须用 qmt_common 拼接）或外部 xtquant（XtQuantTrader）。
  含编码 0xb9、__file__/account 缺失、回测墙钟、get_market_data_ex、
  暖机陷阱、T+1 假平仓/孤儿双开、回测盈利虚高、实盘 can_use 等联调踩坑。
  Use when the user mentions QMT、MiniQMT、xtquant、国金、模型交易、
  handlebar、passorder、HLT策略、可在qmt终端跑、codec 0xb9、
  account is not defined、get_history_data、back test mode、T+1、
  可卖0股、float cleared、孤儿仓、回测盈利、or 把策略转成 QMT 脚本.
  For new/refactored terminal modules also activate qmt-common-modules.
---

# 策略 → QMT 模型脚本

把主题 `model.md` 落成可运行脚本。**先选形态，勿混用**：

| 形态 | 入口 | 编码 | 文档 |
| :--- | :--- | :--- | :--- |
| **终端模型交易**（国金等） | `init`/`handlebar`/`passorder` | GBK | [reference-pitfalls.md](reference-pitfalls.md) |
| **外部 xtquant** | `XtQuantTrader` | UTF-8 | [reference-xtquant.md](reference-xtquant.md) |

指标与 R 规则以该主题 `model.md` 与 `scripts/qmt/` 实现为真源。  
权威 API：[完整实例](https://dict.thinktrader.net/nativeApi/code_examples.html)、[常见问题](https://dict.thinktrader.net/innerApi/question_answer.html)。

**A 股/ETF 终端脚本必须遵守 T+1**（回测 `bt_locked` + 实盘 `m_nCanUseVolume`）：详见 [reference-pitfalls.md](reference-pitfalls.md) §7.1。

---

## 路径选择

| 用户意图 | 动作 |
| :--- | :--- |
| 国金 QMT「模型交易 / 回测」 | **A. 终端转写** |
| 外部 Python 连 userdata | **A'. xtquant 转写** |
| 终端报错 / 回测无日志 / 盈利异常 | **C. 排障** → [reference-pitfalls.md](reference-pitfalls.md) |
| 策略变更后同步脚本 | **B. 对齐** |
| 部署到 `QMT\python\` | `python <主题>/scripts/qmt/_deploy_qmt_gbk.py`（拼接 `scripts/qmt_common` + 策略片段） |
| 终端「新建策略交易」参数面板 | [qmt-param-panel](../qmt-param-panel/SKILL.md)（`panel.xml` → `formulaLayout`） |

---

## A. 终端转写（推荐国金）

**必须**按 [qmt-common-modules](../qmt-common-modules/SKILL.md) 使用 `scripts/qmt_common` 拼接；禁止新建整文件复制 pending/T+1/经纪层。

```
转写进度:
- [ ] 1. 读 model.md；判定单仓 vs 双浮仓 → 打开 qmt-common-modules
- [ ] 2. 建 <主题>/scripts/qmt/<简名>/ 策略片段 + _deploy_qmt_gbk.py（MODULE_ORDER 含 common:）
- [ ] 3. ACCOUNT_ID 兜底；STATE 绝对路径 + `{stock}`/按标的分文件（禁 __file__、禁多实例共写一文件）；DRY_RUN=True
- [ ] 4. 行情：download_history_data + get_market_data_ex（走 common market_util）；禁 get_history_data
- [ ] 5. handlebar 用 _refresh_mode；回测 K 线时间 / 实盘决策窗
- [ ] 6. T+1：common backtest + broker；skip 不清仓；pending 成交后才改状态
- [ ] 7. deploy 写入终端 python\；model.md 写操作步骤
- [ ] 8. 回测先见 diag: ok，再改 DRY_RUN=False；验收买卖笔数相等、期末空仓
```

硬性约定见 [reference-pitfalls.md](reference-pitfalls.md) §1–8。  
模块布局见 [qmt-common-modules/reference-layout.md](../qmt-common-modules/reference-layout.md)。  
xtquant 骨架见 [reference-template.md](reference-template.md)。

---

## A'. xtquant 转写（外部进程）

```
转写进度:
- [ ] 1. 对照 reference-xtquant
- [ ] 2. 写 scripts/qmt/qmt_<简名>.py（UTF-8）
- [ ] 3. QMT_USERDATA / ACCOUNT_ID；DRY_RUN=True
- [ ] 4. 状态可落盘；model.md 注明「勿当终端模型导入」
- [ ] 5. 卖出用可卖数量（查询持仓可用），勿假设当日可平
```

---

## B. 对齐（策略变更后）

```
对齐进度:
- [ ] 1. model 变更记录 vs 终端/xtquant 脚本阈值与 R 分支
- [ ] 2. 删已废规则；同步 SPACE_STEP / BOLL / KDJ
- [ ] 3. 重新 _deploy_qmt_gbk.py（若用终端版）；核对终端文件含最新版本号
- [ ] 4. 更新 model.md 实盘小节
```

---

## C. 排障（联调必做）

出现以下任一情况，**先读** [reference-pitfalls.md](reference-pitfalls.md) 再改代码：

| 症状 | 节 |
| :--- | :--- |
| `codec can't decode byte 0xb9` | §1 编码 |
| `__file__ is not defined` | §2 |
| `state stock mismatch` / 多实例 pending 丢失 | §2.1 多实例 STATE |
| `account is not defined` | §3 |
| 只有 init / warmup，无 close= | §4 |
| `get_history_data` 过时或上下轨=收盘价 | §5 |
| `sell=True` 但不下单 | §6–7 |
| `可卖0股...跳过` 仍 `float cleared` / 连续双买 / 期末残留 | §7.1 T+1 |
| 修 T+1 后「盈利大幅下降」 | §7.1（多为虚高修正） |
| 部署了仓库但仍像旧结果 | §8（加载错文件 / 未重编译） |
| 点开始秒退 / 不常驻 / 仅开始结束 | §9（simpleRun / doRun） |

```
排障进度:
- [ ] 1. 确认终端版 vs xtquant 版
- [ ] 2. GBK 部署并重新编译；日志版本号匹配
- [ ] 3. 看日志：BACKTEST / DRY_RUN / diag ok|empty|short / sell skip T+1
- [ ] 4. 主图=标的、周期匹配、区间足够长
- [ ] 5. CSV：买卖笔数相等、无双买、期末空仓后再信盈利
- [ ] 6. 修源码 → 部署全部运行入口 → QMT 再编译
```

---

## 完成标准

| 路径 | 完成标准 |
| :--- | :--- |
| **终端转写** | 有 `qmt_terminal_*.py` + deploy；回测能出 `diag: ok` 与信号行；model 有步骤；T+1 验收通过 |
| **xtquant 转写** | 有 `qmt_*.py`；DRY_RUN 默认；model 标明外部运行 |
| **排障** | 对应该节陷阱已消除；用户日志/CSV 可解释 |

## 附加资源

- [qmt-common-modules](../qmt-common-modules/SKILL.md) — **终端策略模块化新建/修改（必遵）**
- [qmt-param-panel](../qmt-param-panel/SKILL.md) — 策略交易参数面板（`panel.xml` / `formulaLayout`）
- [scripts/qmt_common/NAV.md](../../../scripts/qmt_common/NAV.md) — 共用模块清单
- [reference-pitfalls.md](reference-pitfalls.md) — **国金终端联调踩坑（优先读，含 T+1）**
- [reference-xtquant.md](reference-xtquant.md) — 外部 xtquant 要点  
- [reference-template.md](reference-template.md) — xtquant / 历史骨架说明  
- 范本：`波段3-5天策略/scripts/qmt/`（单仓）、`红利T策略/scripts/qmt/hongli/`（双浮仓）
