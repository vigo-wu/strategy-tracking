# coding: utf-8
"""将 pbs/*.py + scripts/qmt_common 拼成国金 QMT 模型 GBK 文件。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRAT = HERE / "pbs"
PREVIEW = HERE / "qmt_terminal_pbs.py"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from qmt_common._deploy_lib import build_bundle, deploy_gbk, write_preview  # noqa: E402

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
TARGETS = [
    QMT_DIR / "PbsRush.py",
    QMT_DIR / "转债首日抢筹.py",
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
    deploy_gbk(text, TARGETS, compile_name="qmt_terminal_pbs.py")
    print("OK: 打开国金 QMT -> 模型交易 -> 加载 PbsRush / 转债首日抢筹")
    print("主图/回测: 分笔(tick); 实盘另开 run_time 定时器+分笔双驱动")
    print("v1.7 timer+tick; ModeA130 / 深市预挂撤升级 / 沪市阶梯追")
    print("默认 DRY_RUN=True; ENABLE_LIVE_TIMER=True; LIVE_TIMER_MS=100")


if __name__ == "__main__":
    main()
