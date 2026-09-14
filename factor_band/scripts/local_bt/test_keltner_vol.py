# coding: utf-8
"""keltner_vol：通道内 + 连续缩量。"""
from __future__ import annotations

import unittest

from run import _exec_bundle


def _vol_ctx(price, kc_mid=10.0, kc_atr=1.0):
    n = 15
    volumes = [1000.0] * (n - 2) + [100.0, 100.0]
    return {
        "market": {
            "daily_ready": True,
            "close": price,
            "kc_mid": kc_mid,
            "kc_atr": kc_atr,
            "volumes": volumes,
            "i": n - 1,
        },
        "state": {},
        "clock": {},
    }


class KeltnerVolFactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def _hit(self, ctx):
        return self.ns["_factor_hit"]("keltner_vol", ctx)

    def test_hits_inside_with_shrink(self) -> None:
        self.assertTrue(self._hit(_vol_ctx(10.0)))
        self.assertTrue(self._hit(_vol_ctx(8.0)))
        self.assertTrue(self._hit(_vol_ctx(12.0)))

    def test_misses_outside_upper(self) -> None:
        self.assertFalse(self._hit(_vol_ctx(12.01)))

    def test_k_nonpositive_off(self) -> None:
        orig = self.ns["RECIPE"]["factor_params"]["keltner_vol"]["k"]
        try:
            self.ns["RECIPE"]["factor_params"]["keltner_vol"]["k"] = 0
            self.assertFalse(self._hit(_vol_ctx(10.0)))
            self.ns["RECIPE"]["factor_params"]["keltner_vol"]["k"] = -1
            self.assertFalse(self._hit(_vol_ctx(10.0)))
        finally:
            self.ns["RECIPE"]["factor_params"]["keltner_vol"]["k"] = orig


if __name__ == "__main__":
    unittest.main()
