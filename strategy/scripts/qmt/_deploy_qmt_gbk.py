# coding: utf-8
"""将 ma15/*.py + scripts/qmt_common 拼成国金 QMT 模型 GBK 文件。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRAT = HERE / "ma15"
PREVIEW = HERE / "qmt_terminal_ma15.py"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from qmt_common._deploy_lib import (  # noqa: E402
    build_bundle,
    deploy_formula_layout,
    deploy_gbk,
    write_preview,
)

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
TARGETS = [
    QMT_DIR / "Ma15.py",
    QMT_DIR / "均线回踩.py",
]

MODULE_ORDER = [
    "config.py",
    "common:ctx.py",
    "common:live_log.py",
    "common:time_util.py",
    "common:period.py",
    "state_extra.py",
    "common:single/state_io.py",
    "common:backtest.py",
    "common:single/state_pos.py",
    "common:single/lots.py",
    "common:single/bt_recover.py",
    "indicators.py",
    "common:market_util.py",
    "market.py",
    "common:mode.py",
    "common:broker_base.py",
    "common:single/broker.py",
    "common:orders_pending.py",
    "common:single/orders.py",
    "strategy.py",
    "runtime.py",
]


def main() -> None:
    text = build_bundle(MODULE_ORDER, STRAT)
    write_preview(text, PREVIEW)
    deploy_gbk(text, TARGETS, compile_name="qmt_terminal_ma15.py")
    deploy_formula_layout(
        STRAT / "panel.xml",
        QMT_DIR,
        stems=[p.stem for p in TARGETS],
    )
    print("OK: 打开国金 QMT -> 模型交易 -> 新建策略交易 -> Ma15 / 均线回踩")
    print("主图: 513530.SH | 周期=15分钟 | 前复权")
    print("编辑 ma15/*.py 与 panel.xml；策略交易改参，编辑器回测仍用 config.py")


if __name__ == "__main__":
    main()
