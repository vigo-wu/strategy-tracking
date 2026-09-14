# coding: utf-8
"""above_ema：收盘 > EMA(ema.1d.trend)；trend<=0 关闸门。"""
from __future__ import annotations

import unittest

from run import _exec_bundle


def _ctx(price, ma_trend=10.0):
    return {
        "market": {
            "daily_ready": True,
            "close": price,
            "ma_trend": ma_trend,
        },
        "state": {},
        "clock": {},
    }


class AboveEmaFactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def _hit(self, ctx):
        return self.ns["_factor_hit"]("above_ema", ctx)

    def test_hits_above_ma(self) -> None:
        self.assertTrue(self._hit(_ctx(10.01)))
        self.assertFalse(self._hit(_ctx(10.0)))
        self.assertFalse(self._hit(_ctx(9.99)))

    def test_trend_nonpositive_off(self) -> None:
        st = self.ns["RECIPE"]["structure"]
        ema = st.setdefault("ema", {}).setdefault("1d", {})
        orig = ema.get("trend", 120)
        try:
            ema["trend"] = 0
            self.assertTrue(self._hit(_ctx(9.0)))
        finally:
            ema["trend"] = orig


if __name__ == "__main__":
    unittest.main()
