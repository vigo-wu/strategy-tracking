# coding: utf-8
"""将 ma_dual/*.py + scripts/qmt_common 拼成国金 QMT 模型 GBK 文件。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MA = HERE / "ma_dual"
PREVIEW = HERE / "qmt_terminal_ma_dual.py"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from qmt_common._deploy_lib import build_bundle, deploy_gbk, write_preview  # noqa: E402

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
TARGETS = [
    QMT_DIR / "MaDual.py",
    QMT_DIR / "均线双周期.py",
]

MODULE_ORDER = [
    "config.py",
    "common:ctx.py",
    "common:time_util.py",
    "common:period.py",
    "state_extra.py",
    "common:single/state_io.py",
    "common:backtest.py",
    "common:single/state_pos.py",
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
    text = build_bundle(MODULE_ORDER, MA)
    write_preview(text, PREVIEW)
    deploy_gbk(text, TARGETS, compile_name="qmt_terminal_ma_dual.py")
    print("OK: 打开国金 QMT -> 模型交易 -> 加载 MaDual")
    print("主图: 目标股票 | 周期=1小时 | 部署后请重新编译")


if __name__ == "__main__":
    main()
