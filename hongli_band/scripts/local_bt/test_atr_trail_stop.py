# coding: utf-8
"""atr_trail_stop：k1 武装保本，k2 峰值回撤。"""
from __future__ import annotations

import unittest

from run import _exec_bundle


def _ctx(price, cost=10.0, peak=12.1, atr=1.0, atr_n=14):
    return {
        "market": {"close": price, "atr": atr, "atr_n": atr_n},
        "state": {"lot": {"price": cost, "hold_peak": peak}},
        "clock": {},
    }


class AtrTrailStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def _hit(self, ctx):
        return self.ns["_factor_hit"]("atr_trail_stop", ctx)

    def test_not_armed(self) -> None:
        self.assertFalse(self._hit(_ctx(9.0, peak=11.9)))

    def test_armed_breakeven(self) -> None:
        self.assertTrue(self._hit(_ctx(10.0, peak=12.1)))
        self.assertTrue(self._hit(_ctx(9.99, peak=12.1)))
        self.assertFalse(self._hit(_ctx(10.2, peak=12.1)))

    def test_armed_giveback(self) -> None:
        self.assertTrue(self._hit(_ctx(10.1, peak=12.1)))
        self.assertFalse(self._hit(_ctx(10.11, peak=12.1)))

    def test_k1_off(self) -> None:
        orig = self.ns["RECIPE"]["factor_params"]["atr_trail_stop"]["k1"]
        try:
            self.ns["RECIPE"]["factor_params"]["atr_trail_stop"]["k1"] = 0
            self.assertFalse(self._hit(_ctx(9.0, peak=20.0)))
        finally:
            self.ns["RECIPE"]["factor_params"]["atr_trail_stop"]["k1"] = orig

    def test_k2_off_only_breakeven(self) -> None:
        orig = self.ns["RECIPE"]["factor_params"]["atr_trail_stop"]["k2"]
        try:
            self.ns["RECIPE"]["factor_params"]["atr_trail_stop"]["k2"] = 0
            self.assertFalse(self._hit(_ctx(10.1, peak=12.1)))
            self.assertTrue(self._hit(_ctx(10.0, peak=12.1)))
        finally:
            self.ns["RECIPE"]["factor_params"]["atr_trail_stop"]["k2"] = orig


if __name__ == "__main__":
    unittest.main()
