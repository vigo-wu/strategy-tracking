# coding: utf-8
"""将 kldump/*.py + scripts/qmt_common 拼成国金 QMT 模型 GBK 文件。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRAT = HERE / "kldump"
PREVIEW = HERE / "qmt_terminal_kldump.py"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from qmt_common._deploy_lib import (  # noqa: E402
    build_bundle,
    deploy_gbk,
    write_preview,
)

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
TARGETS = [
    QMT_DIR / "KlineDump.py",
    QMT_DIR / "行情导出.py",
]

MODULE_ORDER = [
    "config.py",
    "common:ctx.py",
    "common:period.py",
    "common:market_util.py",
    "dump.py",
    "runtime.py",
]


def main() -> None:
    text = build_bundle(MODULE_ORDER, STRAT)
    write_preview(text, PREVIEW)
    deploy_gbk(text, TARGETS, compile_name="qmt_terminal_kldump.py")
    print("OK: 打开国金 QMT -> 模型交易 -> 新建策略交易 -> KlineDump / 行情导出")
    print("主图=要导出的标的 | 周期=要导出的K线周期 | 勿勾独立/简易运行")
    print("回测区间可很短；条数由 BAR_COUNT / HIST_START 决定")
    print("编辑 kldump/*.py 后重新本脚本部署，终端再编译")


if __name__ == "__main__":
    main()
