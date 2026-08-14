# 与 templates/panel.xml 对齐的 PANEL_BINDS 示例；复制到策略 config.py 后按需增删。
DRY_RUN = True
TRADE_BUDGET = 25000.0
CASH_RATIO = 0.8
CHASE_MAX_PCT = 0.05
STOP_LOSS = 0.05

PANEL_BINDS = (
    ("panel_dry_run", "DRY_RUN", "bool"),
    ("panel_budget", "TRADE_BUDGET", "float"),
    ("panel_cash_ratio", "CASH_RATIO", "float"),
    ("panel_chase_pct", "CHASE_MAX_PCT", "float"),
    ("panel_stop_loss", "STOP_LOSS", "float"),
)
