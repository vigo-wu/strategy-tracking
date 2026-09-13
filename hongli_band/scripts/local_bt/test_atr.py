# coding: utf-8
"""威尔德 ATR 与 atr_stop：close <= cost - k*ATR。"""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from run import _exec_bundle

HERE = Path(__file__).resolve().parent
HLBAND = HERE.parent / "qmt" / "hlband"
ATR_PATH = HLBAND / "indicators" / "atr.py"
EMA_PATH = HLBAND / "indicators" / "ema.py"


def _load_atr_ns():
    ns = {"np": np}
    for path in (EMA_PATH, ATR_PATH):
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), ns, ns)
    return ns


class WilderAtrTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = _load_atr_ns()

    def test_hand_tr_and_wilder(self) -> None:
        highs = [10.0, 12.0, 11.0, 13.0]
        lows = [9.0, 10.0, 10.0, 11.0]
        closes = [9.5, 11.0, 10.5, 12.0]
        tr = self.ns["_true_range"](highs, lows, closes)
        self.assertIsNotNone(tr)
        self.assertAlmostEqual(float(tr[0]), 1.0)
        self.assertAlmostEqual(float(tr[1]), 2.5)
        self.assertAlmostEqual(float(tr[2]), 1.0)
        self.assertAlmostEqual(float(tr[3]), 2.5)
        atr = self.ns["_calc_atr"](highs, lows, closes, 3)
        self.assertIsNotNone(atr)
        self.assertTrue(atr[0] != atr[0])
        self.assertTrue(atr[1] != atr[1])
        self.assertAlmostEqual(float(atr[2]), 1.5)
        self.assertAlmostEqual(float(atr[3]), 5.5 / 3.0)

    def test_not_same_as_ema(self) -> None:
        highs = [10.0, 12.0, 11.0, 13.0]
        lows = [9.0, 10.0, 10.0, 11.0]
        closes = [9.5, 11.0, 10.5, 12.0]
        tr = self.ns["_true_range"](highs, lows, closes)
        atr = self.ns["_calc_atr"](highs, lows, closes, 3)
        ema = self.ns["_ema"](tr, 3)
        self.assertAlmostEqual(float(atr[2]), float(ema[2]))
        self.assertNotAlmostEqual(float(atr[3]), float(ema[3]))

    def test_n_nonpositive_or_short_is_none(self) -> None:
        highs = [10.0, 12.0]
        lows = [9.0, 10.0]
        closes = [9.5, 11.0]
        self.assertIsNone(self.ns["_calc_atr"](highs, lows, closes, 0))
        self.assertIsNone(self.ns["_calc_atr"](highs, lows, closes, -1))
        self.assertIsNone(self.ns["_calc_atr"](highs, lows, closes, 3))
        self.assertIsNone(self.ns["_calc_atr"](None, lows, closes, 2))


def _atr_ctx(price, cost=10.0, atr=1.0, atr_n=14, k=None):
    ctx = {
        "market": {"close": price, "atr": atr, "atr_n": atr_n},
        "state": {"lot": {"price": cost}},
        "clock": {},
    }
    return ctx, k


class AtrStopFactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def _hit(self, ctx):
        return self.ns["_factor_hit"]("atr_stop", ctx)

    def test_hits_at_cost_minus_k_atr(self) -> None:
        ctx, _ = _atr_ctx(8.0)
        self.assertTrue(self._hit(ctx))
        ctx, _ = _atr_ctx(7.99)
        self.assertTrue(self._hit(ctx))
        ctx, _ = _atr_ctx(8.01)
        self.assertFalse(self._hit(ctx))

    def test_n_or_k_nonpositive_off(self) -> None:
        ctx, _ = _atr_ctx(8.0, atr_n=0)
        self.assertFalse(self._hit(ctx))
        orig = self.ns["RECIPE"]["factor_params"]["atr_stop"]["k"]
        try:
            self.ns["RECIPE"]["factor_params"]["atr_stop"]["k"] = 0
            ctx, _ = _atr_ctx(8.0)
            self.assertFalse(self._hit(ctx))
            self.ns["RECIPE"]["factor_params"]["atr_stop"]["k"] = -1
            self.assertFalse(self._hit(ctx))
        finally:
            self.ns["RECIPE"]["factor_params"]["atr_stop"]["k"] = orig


if __name__ == "__main__":
    unittest.main()
