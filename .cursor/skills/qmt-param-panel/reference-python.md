# 面板值如何进策略

QMT 在 **模型交易实例启动** 时，按 XML `bind` 注入同名变量。

- 在 `init` / `handlebar` / 自定义函数里可直接当名字用。
- **模块顶格看不到**（`config.py` 里写 `panel_dry_run` 会 `NameError`）。
- 策略编辑器「运行 / 回测」通常**不注入**；必须回落到 `config.py` 常量。

`account`、`accountType` 由对话框注入。未声明时用对话框所选账号；源码一旦赋值 `account = "..."` 会盖掉对话框。

## config：默认值 + 对照表

```python
DRY_RUN = True
TRADE_BUDGET = 25000.0
CASH_RATIO = 0.8
CHASE_MAX_PCT = 0.05

# bind, 模块常量名, 转换：bool / int / float / str
PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_chase_pct", "CHASE_MAX_PCT", "float"),
)
```

XML 每个 `bind` 必须出现在这张表；表里每一项必须在 XML 里。校验脚本查这个。

## runtime：init 里覆盖

放在 `init` **最前面**（`set_account` 之前也可以，但覆盖完再打 init 日志，才能看见面板值）。

```python
def _as_bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y", "是")


def _apply_panel():
    """从调用帧取 bind；无注入则保持 config。须由 init() 直接调用。"""
    import sys
    fr = sys._getframe(1)
    names = {}
    names.update(fr.f_globals)
    names.update(fr.f_locals)
    g = globals()
    for bind, const, kind in PANEL_BINDS:
        if bind not in names:
            continue
        val = names[bind]
        cur = g[const]
        if kind == "bool":
            g[const] = _as_bool(val)
        elif kind == "int":
            g[const] = int(float(val))
        elif kind == "float":
            g[const] = float(val)
        else:
            g[const] = str(val)
        if g[const] != cur:
            print(_strategy_tag(), "panel", const, cur, "->", g[const])


def init(C):
    _apply_panel()
    # ... 其余 init：账号兜底仍用 ACCOUNT_ID，若已注入 account 则优先 account
```

账号兜底（已有策略同款，勿新建 `account =`）：

```python
acct = ACCOUNT_ID
try:
    acct = str(account).strip() or acct
except NameError:
    pass
A.acct = acct
C.set_account(acct)
```

## 不要做

| 错误 | 原因 |
| :--- | :--- |
| `config.py` 顶格 `DRY_RUN = panel_dry_run` | 顶格无注入 |
| bind 与常量同名且不再 `_apply_panel` | 注入范围不确定，handlebar 可能仍读旧常量 |
| 只改 XML 不改 `PANEL_BINDS` | 界面有值，代码不覆盖 |
| 在嵌套函数里裸写 `panel_*` 却不 `_apply_panel` | 覆盖未写回模块全局，其它片段读不到 |
