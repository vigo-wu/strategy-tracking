# coding: utf-8
"""将 fband/*.py + scripts/qmt_common 拼成国金 QMT 模型 GBK 文件。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FBAND = HERE / "fband"
PREVIEW = HERE / "qmt_terminal_fband.py"
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts"))

from _fband_ns import load_fband_ns  # noqa: E402

from qmt_common._deploy_lib import (  # noqa: E402
    build_bundle,
    deploy_formula_layout,
    deploy_gbk,
    write_preview,
)

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
TARGETS = [
    QMT_DIR / "FactorBand.py",
]

_MODULE_HEAD = [
    "config.py",
    "factors/catalog.py",
    "common:ctx.py",
    "common:live_log.py",
    "common:time_util.py",
    "common:period.py",
    "state_extra.py",
    "common:single/state_io.py",
    "common:backtest.py",
    "common:single/state_pos.py",
    "common:single/lots.py",
    "common:single/ex_rights.py",
    "common:single/bt_recover.py",
    "indicators/util.py",
    "indicators/sma.py",
    "indicators/ema.py",
    "indicators/macd.py",
    "indicators/atr.py",
    "indicators/price_ma.py",
    "common:market_util.py",
    "common:pit_front.py",
    "market.py",
    "factors/ctx.py",
]
_MODULE_TAIL = [
    "factors/registry.py",
    "factors/expr.py",
    "factors/slots.py",
    "factors/intent.py",
    "common:mode.py",
    "common:broker_base.py",
    "common:single/broker.py",
    "common:orders_pending.py",
    "common:single/orders.py",
    "budget.py",
    "strategy.py",
    "universe.py",
    "runtime.py",
]


def _fband_ns():
    return load_fband_ns()


def _leaf_lib_paths(leaves):
    return ["factors/lib/%s.py" % fid for fid in leaves]


def _check_leaf_files(leaves):
    lib = FBAND / "factors" / "lib"
    on_disk = {p.stem for p in lib.glob("*.py")}
    want = set(leaves)
    missing = sorted(want - on_disk)
    extra = sorted(on_disk - want)
    if missing or extra:
        raise SystemExit(
            "LEAVES 与 lib/ 不一致 missing=%s extra=%s" % (missing, extra)
        )


def build_module_order():
    leaves = _fband_ns()["LEAVES"]
    _check_leaf_files(leaves)
    return list(_MODULE_HEAD) + _leaf_lib_paths(leaves) + list(_MODULE_TAIL)


MODULE_ORDER = build_module_order()


def main() -> None:
    text = build_bundle(MODULE_ORDER, FBAND)
    write_preview(text, PREVIEW)
    deploy_gbk(text, TARGETS, compile_name="qmt_terminal_fband.py")
    deploy_formula_layout(
        FBAND / "panel.xml",
        QMT_DIR,
        stems=[p.stem for p in TARGETS],
    )
    print("OK: 打开国金 QMT -> 模型交易 -> 新建策略交易 -> FactorBand")
    print("主图仅常驻（建议池外日线指数）；扫池=run_time 2s 历史start；交易池=BOOK_STOCKS")
    print("勿勾独立运行/简易运行；上线前停掉旧多图实例，只留一个 FactorBand")
    print("编辑 fband/*.py 与 panel.xml；策略交易改参，编辑器回测仍用 config.py")


if __name__ == "__main__":
    main()
