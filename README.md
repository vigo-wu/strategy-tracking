# strategy-tracking · QMT 策略仓库

本仓库只保留 **QMT（国金终端模型 / xtquant）** 相关内容：策略说明、可部署脚本、Agent Skill。

| 主题 | 手册 | QMT 脚本 |
| :--- | :--- | :--- |
| 红利T · 561580 日线做T（v2.5 · 底仓20万/A5万/B2.5万） | [`红利T策略/model.md`](./红利T策略/model.md) | [`红利T策略/scripts/qmt/`](./红利T策略/scripts/qmt/) |
| 波段3-5天 · 15M KDJ（v1.3） | [`波段3-5天策略/model.md`](./波段3-5天策略/model.md) | [`波段3-5天策略/scripts/qmt/`](./波段3-5天策略/scripts/qmt/) |
| 趋势回调 · 日线 EMA60/20 + RSI + 布林（v1.0） | [`趋势回调策略/model.md`](./趋势回调策略/model.md) | [`趋势回调策略/scripts/qmt/`](./趋势回调策略/scripts/qmt/) |
| 高胜率T1 · 1M 尾盘潜伏 / VWAP追踪（v1.1） | [`高胜率T1策略/model.md`](./高胜率T1策略/model.md) | [`高胜率T1策略/scripts/qmt/`](./高胜率T1策略/scripts/qmt/) |
| 均线双周期 · 日线方向 + 1h 金叉（v1.0） | [`均线双周期策略/model.md`](./均线双周期策略/model.md) | [`均线双周期策略/scripts/qmt/`](./均线双周期策略/scripts/qmt/) |

**共用基础设施**（P0/P1）：[`scripts/qmt_common/`](./scripts/qmt_common/)（下单 pending、经纪查询、T+1、模式切换、行情工具等）。导航见 [`scripts/qmt_common/NAV.md`](./scripts/qmt_common/NAV.md)。

**Skills / 约束**

| 用途 | 路径 |
| :--- | :--- |
| 新建/改策略（模块拼接，必遵） | [`.cursor/skills/qmt-common-modules/`](./.cursor/skills/qmt-common-modules/) |
| 转写 / 对齐 / 排障 | [`.cursor/skills/qmt-model-script/`](./.cursor/skills/qmt-model-script/) |
| XtQuant API 索引 | [`.cursor/skills/qmt-helper/`](./.cursor/skills/qmt-helper/) |
| 编辑 `scripts/qmt/**` 时自动约束 | [`.cursor/rules/qmt-common-modules.mdc`](./.cursor/rules/qmt-common-modules.mdc) |

## 国金终端部署

```bash
# 任一主题（会拼接 qmt_common + 策略片段 → GBK 写入终端 python\）
python 红利T策略/scripts/qmt/_deploy_qmt_gbk.py
python 波段3-5天策略/scripts/qmt/_deploy_qmt_gbk.py
python 高胜率T1策略/scripts/qmt/_deploy_qmt_gbk.py
python 均线双周期策略/scripts/qmt/_deploy_qmt_gbk.py
```

红利 T 操作步骤见 [`红利T策略/model.md`](./红利T策略/model.md) §6.5；模块导航见 [`hongli/NAV.md`](./红利T策略/scripts/qmt/hongli/NAV.md)。

默认各策略 `DRY_RUN=True`；回测见 `diag: ok` 后再改 `False` 实盘。

## Agent 用法

对 Agent 说「按 qmt-model-script 转写 / 对齐 / 排障」或「查 QMT API（qmt-helper）」。
