# coding: utf-8
"""将 hongli/*.py + scripts/qmt_common 拼成国金 QMT 模型交易用的单个 GBK 文件。

编辑 hongli/ 或 qmt_common/ 后运行本脚本。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HONGLI = HERE / "hongli"
PREVIEW = HERE / "qmt_terminal_hongli_t.py"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from qmt_common._deploy_lib import (  # noqa: E402
    build_bundle,
    deploy_gbk,
    write_preview,
)

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
CFG = Path(r"D:\service\GJQMT") / "config" / "indexUserConfig.xml"
TARGETS = [
    QMT_DIR / "HLCL.py",
    QMT_DIR / "红利T_v25.py",
    QMT_DIR / "HLT策略.py",
]

# common:* -> scripts/qmt_common/；其余相对 hongli/
MODULE_ORDER = [
    "_header.py",
    "config.py",
    "common:ctx.py",
    "common:time_util.py",
    "common:period.py",
    "state_io.py",
    "common:backtest.py",
    "state.py",
    "bt_recover.py",
    "indicators.py",
    "common:market_util.py",
    "market.py",
    "common:mode.py",
    "common:broker_base.py",
    "broker.py",
    "common:orders_pending.py",
    "orders.py",
    "runtime.py",
    "strategy.py",
    "_main_guard.py",
]

_SIMPLE = re.compile(
    r'name="HLCL" type="2" simpleRun="([01])"',
    re.M,
)


def _warn_simplerun() -> None:
    if not CFG.is_file():
        return
    raw = CFG.read_text(encoding="utf-8", errors="surrogateescape")
    m = _SIMPLE.search(raw)
    if not m:
        print("WARN: HLCL catalog not found in", CFG)
        return
    if m.group(1) == "0":
        print("OK: HLCL simpleRun=0 (model trade uses PythonFormula)")
        return
    print(
        "WARN: HLCL simpleRun=1 -> table Start uses doRun and exits instantly.\n"
        "  1) Fully EXIT QMT\n"
        "  2) python 红利T策略/scripts/qmt/_fix_hlcl_simplerun.py\n"
        "  3) Restart QMT; do NOT enable independent/simple run on HLCL"
    )


def main() -> None:
    text = build_bundle(MODULE_ORDER, HONGLI)
    write_preview(text, PREVIEW)
    deploy_gbk(text, TARGETS, compile_name="qmt_terminal_hongli_t.py")
    _warn_simplerun()
    print("OK: 打开国金 QMT -> 模型交易 -> 加载 HLCL / 红利T_v25 / HLT策略")
    print("主图: 561580.SH | PERIOD=follow | 部署后请重新编译")
    print("编辑 hongli/*.py 与 scripts/qmt_common/；改完务必重新运行本部署脚本")


if __name__ == "__main__":
    main()
