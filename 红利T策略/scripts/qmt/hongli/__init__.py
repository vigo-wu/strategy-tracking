# HongliT 国金 QMT 终端模型片段目录。
#
# 快速导航: NAV.md（按改什么找哪里 / 拼接顺序 / 调用链）
# 编辑本目录后执行: python scripts/qmt/_deploy_qmt_gbk.py
# 运行时勿跨模块 import — 部署时拼成单个 GBK 文件。
#
# 常用入口:
#   config.py    — DRY_RUN / 预算 / 风控开关
#   strategy.py  — R-A / R-B / R-Sell 决策
#   runtime.py   — init / handlebar
#   orders.py    — pending / 下单
#   market.py    — OHLC / 日线 MA
