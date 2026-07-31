# strategy-tracking · QMT 策略仓库

本仓库只保留 **QMT（国金终端模型 / xtquant）** 相关内容：策略说明、可部署脚本、Agent Skill。

| 主题 | 手册 | QMT 脚本 |
| :--- | :--- | :--- |
| 红利T · 561580 日线做T（v2.5 · 底仓20万/A5万/B2.5万） | [`红利T策略/model.md`](./红利T策略/model.md) | [`红利T策略/scripts/qmt/`](./红利T策略/scripts/qmt/) |

**Skills**：[`.cursor/skills/qmt-model-script/`](./.cursor/skills/qmt-model-script/)（策略→脚本 / 联调排障）· [`.cursor/skills/qmt-helper/`](./.cursor/skills/qmt-helper/)（XtQuant API 索引）

## 国金终端部署

```bash
cd 红利T策略
python scripts/qmt/_deploy_qmt_gbk.py
```

会按依赖顺序拼接 `scripts/qmt/hongli/*.py` → GBK 写入终端 `python\`（如 `HLCL.py` / `红利T_v25.py` / `HLT策略.py`）。

操作步骤、参数与 T+1 约定见 [`红利T策略/model.md`](./红利T策略/model.md) §6.5；模块导航见 [`scripts/qmt/hongli/NAV.md`](./红利T策略/scripts/qmt/hongli/NAV.md)。

默认 `DRY_RUN=True`（`hongli/config.py`）；回测见 `diag: ok` 后再改 `False` 实盘。

## Agent 用法

对 Agent 说「按 qmt-model-script 转写 / 对齐 / 排障」或「查 QMT API（qmt-helper）」。
