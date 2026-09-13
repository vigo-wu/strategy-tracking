# coding: utf-8
"""LEAVES ↔ lib / factor_params / recipe 指纹 / 轴序。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
QMT = HERE.parent / "qmt"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(QMT) not in sys.path:
    sys.path.insert(0, str(QMT))

from grid_spec import (
    ENTRY_KEYS,
    EXIT_KEYS,
    SCALE_FACTOR_KEYS,
    _load_config_ns,
    catalog_ids,
    infer_kind,
    recipe_fingerprint,
)
from run import _exec_bundle

HLBAND = Path(__file__).resolve().parent.parent / "qmt" / "hlband"
LIB = HLBAND / "factors" / "lib"

_EXPECTED_FP = {
    "chase": {"max_pct": 0.05},
    "vol_dry": {"ratio": 0.60, "n": 20},
    "pullback_vol": {
        "tol": 0.025,
        "vol_n": 10,
        "ratio": 0.9,
        "confirm_days": 2,
    },
    "w_bias": {"hard": 0.08},
    "w_slope": {"low": 0.02, "slope_weeks": 2},
    "weekly_bear_confirm": {"days": 2},
    "plat_break": {
        "lookback": 20,
        "max_range": 0.10,
        "break_buf": 0.0,
    },
    "w_macd_golden": {"hist_expand": 1.2},
    "stop_loss": {"pct": 0.08},
    "atr_stop": {"k": 2},
    "atr_trail_stop": {"k1": 2, "k2": 2},
    "trail_stop": {
        "tiers": [
            [0.03, 0.06, 0.015, None],
            [0.06, 0.10, 0.03, 0.03],
            [0.10, None, 0.04, None],
        ]
    },
    "time_force": {"bars": 30, "arm": 0.03},
}

_EXPECTED_CATALOG_HEAD = (
    "stop_loss.pct",
    "trail_stop.tiers",
    "time_force.bars",
    "weekly_bear_confirm.days",
    "atr_stop.k",
    "atr_trail_stop.k1",
    "atr_trail_stop.k2",
    "time_force.arm",
    "pullback_vol.tol",
    "pullback_vol.ratio",
    "pullback_vol.vol_n",
    "pullback_vol.confirm_days",
    "vol_dry.ratio",
    "vol_dry.n",
    "chase.max_pct",
    "w_bias.hard",
    "w_slope.low",
    "w_slope.slope_weeks",
)


def _expr_ids(expr):
    if expr is False or expr is None or expr is True:
        return set()
    if isinstance(expr, str):
        return {expr}
    if not isinstance(expr, (list, tuple)) or not expr:
        return set()
    op = expr[0]
    if op in ("and", "or", "not"):
        out = set()
        for node in expr[1:]:
            out |= _expr_ids(node)
        return out
    return set()


class CatalogContractTests(unittest.TestCase):
    def test_leaves_match_lib_files(self) -> None:
        ns = _load_config_ns()
        leaves = ns["LEAVES"]
        on_disk = {p.stem for p in LIB.glob("*.py")}
        self.assertEqual(set(leaves), on_disk)

    def test_recipe_ast_ids_in_leaves(self) -> None:
        ns = _load_config_ns()
        rec = ns["RECIPE"]
        used = set()
        for slot in ("entry", "scale_in", "exit", "scale_out"):
            used |= _expr_ids(rec.get(slot))
        self.assertTrue(used <= set(ns["LEAVES"]))

    def test_factor_params_literals(self) -> None:
        ns = _load_config_ns()
        fp = ns["RECIPE"]["factor_params"]
        self.assertNotIn("weekly_bear", fp)
        self.assertEqual(fp, _EXPECTED_FP)

    def test_recipe_fingerprint_unchanged(self) -> None:
        self.assertEqual(recipe_fingerprint({}), "f20c4472")

    def test_catalog_axis_order(self) -> None:
        ids = list(catalog_ids())
        self.assertEqual(tuple(ids[: len(_EXPECTED_CATALOG_HEAD)]), _EXPECTED_CATALOG_HEAD)
        self.assertEqual(
            ENTRY_KEYS,
            (
                "pullback_vol.tol",
                "pullback_vol.ratio",
                "pullback_vol.vol_n",
                "pullback_vol.confirm_days",
                "vol_dry.ratio",
                "vol_dry.n",
                "chase.max_pct",
                "w_bias.hard",
                "w_slope.low",
                "w_slope.slope_weeks",
            ),
        )
        self.assertEqual(
            EXIT_KEYS,
            (
                "stop_loss.pct",
                "trail_stop.tiers",
                "time_force.bars",
                "weekly_bear_confirm.days",
                "atr_stop.k",
                "atr_trail_stop.k1",
                "atr_trail_stop.k2",
                "time_force.arm",
            ),
        )
        self.assertEqual(
            SCALE_FACTOR_KEYS,
            (
                "plat_break.lookback",
                "plat_break.max_range",
                "plat_break.break_buf",
                "w_macd_golden.hist_expand",
            ),
        )

    def test_infer_kind_directions(self) -> None:
        from grid_run import load_config_defaults

        defaults = load_config_defaults()
        self.assertEqual(infer_kind("stop_loss.pct", 0.06, defaults), "tighten")
        self.assertEqual(infer_kind("atr_trail_stop.k1", 0, defaults), "off")
        self.assertEqual(infer_kind("time_force.arm", 0.01, defaults), "loosen")
        self.assertEqual(infer_kind("time_force.bars", 0, defaults), "off")

    def test_module_order_follows_leaves(self) -> None:
        from _deploy_qmt_gbk import MODULE_ORDER, _leaf_lib_paths

        ns = _load_config_ns()
        leaves = ns["LEAVES"]
        self.assertEqual(MODULE_ORDER[0], "config.py")
        self.assertEqual(MODULE_ORDER[1], "factors/catalog.py")
        lib_seg = _leaf_lib_paths(leaves)
        i = MODULE_ORDER.index("factors/ctx.py") + 1
        self.assertEqual(MODULE_ORDER[i : i + len(lib_seg)], lib_seg)
        self.assertEqual(MODULE_ORDER[i + len(lib_seg)], "factors/registry.py")

    def test_load_ns_shared(self) -> None:
        from _deploy_qmt_gbk import _hlband_ns
        from _hlband_ns import load_hlband_ns

        a = load_hlband_ns()["RECIPE"]["factor_params"]
        self.assertEqual(a, _hlband_ns()["RECIPE"]["factor_params"])
        self.assertEqual(a, _load_config_ns()["RECIPE"]["factor_params"])

    def test_registry_missing_eval_raises(self) -> None:
        ns = _exec_bundle()
        del ns["_factor_eval_chase"]
        with self.assertRaises(RuntimeError) as ctx:
            ns["_factor_registry"]()
        self.assertIn("chase", str(ctx.exception))

    def test_bundle_registry_and_labels(self) -> None:
        ns = _exec_bundle()
        leaves = ns["LEAVES"]
        reg = ns["_factor_registry"]()
        self.assertEqual(set(reg), set(leaves))
        self.assertEqual(ns["_reason_label"]("atr_trail_stop", "sell"), "ATR移动止盈")
        self.assertEqual(ns["_reason_label"]("weekly_bear", "buy"), "周线空头禁开")
        self.assertEqual(ns["_reason_label"]("weekly_bear", "sell"), "周线转空强制清仓")
        self.assertEqual(ns["_reason_label"]("skip_add_bar", "sell"), "加仓成交后当日不评卖")


if __name__ == "__main__":
    unittest.main()
