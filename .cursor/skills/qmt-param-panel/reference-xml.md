# 参数面板 XML

路径约定：仓库 `<简名>/panel.xml` → 部署 `QMT/python/formulaLayout/<入口stem>.xml`。

编码：UTF-8（文件头 `<?xml version="1.0" encoding="utf-8"?>`）。显示名用中文；`bind` 只用 ASCII 标识符。

对照本机可运行文件：`QMT/python/formulaLayout/网格策略.xml`（单 `control` + 单 `variable` + 全部 `item`）。

## 骨架（必须单组）

终端**只读第一个** `<control>` / `<variable>`。多个 control **不会**出现增强网格那种分栏，后面的组直接丢弃。

```xml
<?xml version="1.0" encoding="utf-8"?>
<TCStageLayout>
    <control note="控件">
        <variable note="控件">
            <item bind="panel_dry_run" name="模拟下单" note="勾选则只打日志不下单"
                  value="True" type="checkBox"/>
            <item bind="panel_budget" name="单笔预算" note="元；实际整手"
                  value="25000" type="intput"/>
            <item bind="panel_chase_pct" name="买入 追高禁开" note="0.05=5%"
                  value="0.05" type="intput"/>
        </variable>
    </control>
</TCStageLayout>
```

完整可改稿见 [templates/panel.xml](templates/panel.xml)，对照表见 [templates/config_snippet.py](templates/config_snippet.py)。

分组只能写在 `name` 前缀里（如 `周线 高位乖离禁开`）。增强网格 V2 的三列是内置策略界面，不是这份 XML。

## item 属性

| 属性 | 必填 | 含义 |
| :--- | :--- | :--- |
| `bind` | 是 | 注入到 Python 的变量名；唯一；ASCII 标识符 |
| `name` | 是 | 界面标签 |
| `value` | 是 | 默认值（字符串进 XML；Python 侧按类型转） |
| `type` | 是 | 控件，见下表 |
| `note` | 建议 | 悬停说明 |
| `list` | combo | 逗号分隔选项 |
| `comboType` | combo 选价时 | 内置网格用 `price`；普通下拉可省略 |

## type

| type | 控件 | 说明 |
| :--- | :--- | :--- |
| `intput` | 输入框 | 终端内置 XML 的实际拼写（不是 `input`） |
| `checkBox` | 勾选 | `value` 为 `True` / `False` |
| `combo` | 下拉 | 必须带 `list="a,b,c"`，`value` 为其中一项 |

`type="input"` 偶发能显示，与内置文件不一致；本仓库一律写 `intput`。

```xml
<item bind="panel_gap_unit" name="网格间距单位" note="元或百分比"
      value="元" type="combo" list="元,百分比"/>
```

## 命名

- `bind` 前缀 `panel_`，避免和 `DRY_RUN` 等模块常量抢名。
- 常量仍用原名：`panel_dry_run` → `DRY_RUN`。
- 不要 `bind="account"` / `accountType`。

## 不要上屏

`STATE_FILE`、`LOG_DIR`、`ACCOUNT_ID`（用对话框账号）、`STRATEGY_NAME` / `STRATEGY_VER`、`_ORDER_FILLED` / `_ORDER_DEAD`、`HIST_MAX_LOOKBACK_DAYS`、`DOWNLOAD_HIST_*`、路径类配置。

## 内置策略 XML

`网格策略.xml` 等可打开对照。不要改它们当本仓库源；本仓库策略只维护自己的 `panel.xml`。
