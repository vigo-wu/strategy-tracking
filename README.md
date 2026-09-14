# strategy-tracking · QMT 策略仓库

本仓库只保留 **QMT（国金终端模型 / xtquant）** 相关内容：策略说明、可部署脚本、Agent Skill。

| 主题 | 手册 | QMT 脚本 |
| :--- | :--- | :--- |
| FactorBand · 中长线 / 波段（因子库组合） | [`factor_band/model.md`](./factor_band/model.md) · [`factor_band/local_bt.md`](./factor_band/local_bt.md) | [`factor_band/scripts/qmt/`](./factor_band/scripts/qmt/) |

**共用基础设施**（P0/P1）：[`scripts/qmt_common/`](./scripts/qmt_common/)（下单 pending、经纪查询、T+1、模式切换、行情工具等）。导航见 [`scripts/qmt_common/NAV.md`](./scripts/qmt_common/NAV.md)。

**Skills / 约束**

| 用途 | 路径 |
| :--- | :--- |
| 新建/改策略（模块拼接，必遵） | [`.cursor/skills/qmt-common-modules/`](./.cursor/skills/qmt-common-modules/) |
| 转写 / 对齐 / 排障 | [`.cursor/skills/qmt-model-script/`](./.cursor/skills/qmt-model-script/) |
| XtQuant API 索引 | [`.cursor/skills/qmt-helper/`](./.cursor/skills/qmt-helper/) |
| 回测报告 | [`.cursor/skills/qmt-backtest-report/`](./.cursor/skills/qmt-backtest-report/) |
| 编辑 `scripts/qmt/**` 时自动约束 | [`.cursor/rules/qmt-common-modules.mdc`](./.cursor/rules/qmt-common-modules.mdc) |

## 国金终端部署

```bash
# 拼接 qmt_common + 策略片段 → GBK 写入终端 python\
python factor_band/scripts/qmt/_deploy_qmt_gbk.py
```

操作步骤见 [`factor_band/model.md`](./factor_band/model.md) §5。本地 CSV 回放见 [`factor_band/local_bt.md`](./factor_band/local_bt.md)（§6）。

默认 `DRY_RUN=True`；回测见 `diag: ok` 后再改 `False` 实盘。

## Agent 用法

对 Agent 说「按 qmt-model-script 转写 / 对齐 / 排障」或「查 QMT API（qmt-helper）」。
