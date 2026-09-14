# 架构重构

目标分层的唯一可信数据源：

- [架构.md](./架构.md) — 各层契约、指标目录、因子库目录（`lib/<id>.py`）、与现行默认配置对照、落地顺序
- [策略架构.drawio](./策略架构.drawio) — 总图（用 diagrams.net 打开）

配套：

- [Recipe分类.md](Recipe分类.md) — 买入 `entry`、加仓 `scale_in`、卖出 `exit`、减仓 `scale_out` 四个槽位的布尔式 / AST
- 落地目录导航（改代码先看这里）：
  - [indicators/NAV.md](../../scripts/qmt/hlband/indicators/NAV.md)
  - [factors/NAV.md](../../scripts/qmt/hlband/factors/NAV.md)
  - [factors/lib/NAV.md](../../scripts/qmt/hlband/factors/lib/NAV.md)
