# coding: utf-8
"""scale_arm：峰值浮盈 + 持仓日 + 周柱下限。"""
from __future__ import annotations

import unittest

from run import _exec_bundle


def _ctx(peak=0.04, bars=10, hist=0.0, lots=None):
    if lots is None:
        lots = [{"hold_max_ret": peak, "hold_bars": bars}]
    return {
        "market": {"w_detail": {"hist": hist}, "close": 10.0},
        "state": {"lots": lots},
        "clock": {},
    }


class ScaleArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def _hit(self, ctx):
        return self.ns["_factor_hit"]("scale_arm", ctx)

    def _eval(self, ctx):
        return self.ns["_factor_eval_scale_arm"](ctx)

    def test_defaults_in_table(self) -> None:
        fp = self.ns["RECIPE"]["factor_params"]["scale_arm"]
        self.assertAlmostEqual(fp["arm"], 0.03)
        self.assertEqual(fp["bars"], 8)
        self.assertAlmostEqual(fp["hist_min"], -0.01)
        self.assertNotIn("SCALE_ARM", self.ns)
        self.assertNotIn("SCALE_ARM_BARS", self.ns)
        self.assertNotIn("SCALE_W_HIST_MIN", self.ns)

    def test_peak_below_arm(self) -> None:
        self.assertFalse(self._hit(_ctx(peak=0.02, bars=10, hist=0.0)))

    def test_bars_short(self) -> None:
        self.assertFalse(self._hit(_ctx(peak=0.04, bars=7, hist=0.0)))

    def test_hist_below_min(self) -> None:
        self.assertFalse(self._hit(_ctx(peak=0.04, bars=10, hist=-0.02)))

    def test_all_pass(self) -> None:
        self.assertTrue(self._hit(_ctx(peak=0.03, bars=8, hist=-0.01)))

    def test_armed_lot_not_max_ret(self) -> None:
        lots = [
            {"hold_max_ret": 0.10, "hold_bars": 3},
            {"hold_max_ret": 0.04, "hold_bars": 10},
        ]
        self.assertTrue(self._hit(_ctx(lots=lots, hist=0.0)))
        lots_fail = [
            {"hold_max_ret": 0.10, "hold_bars": 3},
            {"hold_max_ret": 0.02, "hold_bars": 20},
        ]
        self.assertFalse(self._hit(_ctx(lots=lots_fail, hist=0.0)))

    def test_hist_min_none_skips(self) -> None:
        orig = self.ns["RECIPE"]["factor_params"]["scale_arm"]["hist_min"]
        try:
            self.ns["RECIPE"]["factor_params"]["scale_arm"]["hist_min"] = None
            self.assertTrue(self._hit(_ctx(peak=0.04, bars=10, hist=-9.0)))
        finally:
            self.ns["RECIPE"]["factor_params"]["scale_arm"]["hist_min"] = orig

    def test_bars_le0_skips(self) -> None:
        orig = self.ns["RECIPE"]["factor_params"]["scale_arm"]["bars"]
        try:
            self.ns["RECIPE"]["factor_params"]["scale_arm"]["bars"] = 0
            self.assertTrue(self._hit(_ctx(peak=0.04, bars=1, hist=0.0)))
        finally:
            self.ns["RECIPE"]["factor_params"]["scale_arm"]["bars"] = orig

    def test_scale_in_ast_includes_id(self) -> None:
        tree = self.ns["RECIPE"]["scale_in"]
        self.assertEqual(tree[0], "and")
        self.assertEqual(tree[-1], "scale_arm")


if __name__ == "__main__":
    unittest.main()
