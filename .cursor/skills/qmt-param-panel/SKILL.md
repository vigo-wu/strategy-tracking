---
name: qmt-param-panel
description: >-
  为国金 QMT「模型交易 / 新建策略交易」做参数面板：仓库 panel.xml、
  formulaLayout 部署、bind 注入、config 回落。Use when the user mentions
  参数面板、参数配置、新建策略交易、编辑策略交易、formulaLayout、
  TCStageLayout、bind、加载参数、增强网格界面，或要把 config.py 阈值
  暴露到终端对话框。
---

# QMT 参数面板（策略交易）

终端「新建策略交易」里那张表**不是** Python `input()`，也**不是** `ContextInfo.get_param()`。  
布局来自 `formulaLayout/<入口名>.xml`；取值在 `init`/`handlebar` 里以 **bind 同名变量**注入。

本仓库默认仍用 `config.py` 常量。只有用户要「终端改参、不改代码」时才加面板。  
基础设施（拼接、T+1、deploy GBK）仍走 [qmt-common-modules](../qmt-common-modules/SKILL.md)。

XML 字段与控件：[reference-xml.md](reference-xml.md)  
注入与覆盖：[reference-python.md](reference-python.md)

---

## 硬性约束（违反即错）

1. **源在仓库**：`<主题>/scripts/qmt/<简名>/panel.xml`。禁止手改 `QMT\python\formulaLayout\`。
2. **文件名 = 入口 stem**：deploy 到 `HlBand.py` 就必须有 `formulaLayout/HlBand.xml`。多 TARGET 就拷多份同内容、不同文件名。
3. **`bind` 是 Python 标识符**（ASCII，如 `panel_dry_run`）。`name` 才是中文显示名。`bind` 全局唯一。
4. **禁止多个 `<control>`**：全部 `item` 放进同一个 `<variable>`。终端只渲染第一组。
5. **禁止**在 `config.py` 顶格读面板变量（注入在函数内才可见）。
6. **禁止**声明/覆盖 `account`、`accountType`（对话框账号）。`ACCOUNT_ID` 仅作编辑器/回测兜底。
7. **禁止**把 `STATE_FILE`、`LOG_DIR`、`_ORDER_*`、`STRATEGY_VER` 放上面板。
8. 编辑器右侧「参数设置」（最多 20 个、带最小/最大/步长）只用于回测遍历，**不做**实盘 UI。
9. 改 XML 或 `PANEL_BINDS` 后必须：校验 → 改 `_deploy_qmt_gbk.py` 调 `deploy_formula_layout` → 跑 deploy。
10. 策略编辑器点「运行」**不会**加载 XML。要在 **模型交易 → 新建/编辑策略交易** 里开实例；没有表就点「加载参数」。

---

## 路径选择

| 意图 | 动作 |
| :--- | :--- |
| 给已有策略加终端改参 | **A. 新建面板** |
| 改阈值/文案/默认值/分组 | **B. 改面板**（XML + `PANEL_BINDS` + config 默认值对齐） |
| 面板有、对话框没有 | **C. 排障** |
| 只要改逻辑、不暴露 UI | 只改 `config.py`，不动 XML |
| 内置「增强网格 V2」 | 只读 `formulaLayout` 作参考；**不要**当本仓库策略改 |

---

## A. 新建面板

```
进度:
- [ ] 1. 列暴露项：用户可调阈值 / 预算 / DRY_RUN；对照「禁止上屏」清单
- [ ] 2. 在 config.py 写 PANEL_BINDS（bind → 常量名 → 类型），默认值仍是原常量；可从 templates/config_snippet.py 改
- [ ] 3. 复制 templates/panel.xml 为 <简名>/panel.xml；bind/name/value 与 BINDS 一致
- [ ] 4. runtime.init 开头调 _apply_panel()（见 reference-python）
- [ ] 5. _deploy_qmt_gbk.py 在 deploy_gbk 后调 deploy_formula_layout
- [ ] 6. python .../validate_panel.py <panel.xml> --config <config.py>
- [ ] 7. python .../_deploy_qmt_gbk.py
- [ ] 8. 模型交易新建实例：能看到分组；改一值运行，日志打印覆盖后的值
```

`deploy_formula_layout` 在 `scripts/qmt_common/_deploy_lib.py`。范本调用：

```python
from qmt_common._deploy_lib import build_bundle, deploy_gbk, deploy_formula_layout, write_preview

def main() -> None:
    text = build_bundle(MODULE_ORDER, STRAT)
    write_preview(text, PREVIEW)
    deploy_gbk(text, TARGETS, compile_name=PREVIEW.name)
    deploy_formula_layout(
        STRAT / "panel.xml",
        QMT_DIR,  # .../python
        stems=[p.stem for p in TARGETS],
    )
```

---

## B. 改面板

| 改什么 | 动哪里 |
| :--- | :--- |
| 显示名、提示、默认值、下拉选项 | `panel.xml` 的 `name` / `note` / `value` / `list` |
| 新增/删除一项 | XML `item` **和** `PANEL_BINDS` **和** `_apply_panel` 映射（后两者应同一份表） |
| 分组列（基础/买入/…） | **不要**多个 `<control>`（终端只读第一组）。全部 `item` 放进同一个 `<variable>`，用 `name` 前缀区分 |
| config 默认（无面板时） | 只改常量；XML `value` 改成相同字面量 |
| 控件类型 | `type` + 必要时 `list`；布尔用 `checkBox` |

改完跑 A 的步骤 6–8。**不要**只改 QMT 安装目录里的 XML。

---

## C. 排障

| 症状 | 处理 |
| :--- | :--- |
| 对话框无策略参数表 | XML 文件名 ≠ `python\<入口>.py` 的 stem；或没放进 `python\formulaLayout\`；点「加载参数」 |
| 只显示第一组几个参数 | 写了多个 `<control>`；终端只读第一个。合并成单组，见 reference-xml |
| 有表但代码仍是 config 旧值 | bind 与 `PANEL_BINDS` 不一致；`_apply_panel` 未在 `init` 最先调用；在编辑器里点了运行而非策略交易 |
| `account is not defined` / 账号不是对话框里那个 | 源码声明了 `account`；删掉，兜底只用 `ACCOUNT_ID` |
| 顶格 `NameError: panel_*` | 面板变量不能写在模块级 |
| 复选框怎么改都不生效 | `type` 必须是 `checkBox`（驼峰）；`_as_bool` 见 reference-python |
| 输入框不出现 | 用 `intput`（终端拼写），不要用 `input` |

---

## 校验

```text
python .cursor/skills/qmt-param-panel/scripts/validate_panel.py <主题>/scripts/qmt/<简名>/panel.xml --config <主题>/scripts/qmt/<简名>/config.py
```

无 `--config` 时只查 XML 结构与 `bind` 唯一性。

---

## 完成标准

- [ ] `panel.xml` 在策略片段目录，不在 QMT 安装树里当源
- [ ] 每个 TARGET stem 都有对应 `formulaLayout/<stem>.xml`
- [ ] `PANEL_BINDS` 的 bind 与 XML 一一对应；禁止上屏的项未出现
- [ ] `init` 能在无注入时回落 config；策略交易下日志能看到面板值
- [ ] 未声明 `account` / `accountType`
