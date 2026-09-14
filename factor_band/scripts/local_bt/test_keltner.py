# coding: utf-8
"""肯特纳通道：中轨 EMA，上下轨 = mid ± k×威尔德 ATR。"""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from run import _exec_bundle

HERE = Path(__file__).resolve().parent
HLBAND = HERE.parent / "qmt" / "fband"
EMA_PATH = HLBAND / "indicators" / "ema.py"
ATR_PATH = HLBAND / "indicators" / "atr.py"
KC_PATH = HLBAND / "indicators" / "keltner.py"


def _load_kc_ns():
    ns = {"np": np}
    for path in (EMA_PATH, ATR_PATH, KC_PATH):
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), ns, ns)
    return ns


class KeltnerCalcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ns = _load_kc_ns()

    def test_bands_are_mid_plus_minus_k_atr(self) -> None:
        highs = [10.0, 12.0, 11.0, 13.0]
        lows = [9.0, 10.0, 10.0, 11.0]
        closes = [9.5, 11.0, 10.5, 12.0]
        k = 2.0
        mid = self.ns["_ema"](closes, 3)
        atr = self.ns["_calc_atr"](highs, lows, closes, 3)
        bands = self.ns["_calc_keltner"](highs, lows, closes, 3, 3, k)
        self.assertIsNotNone(bands)
        got_mid, upper, lower = bands
        self.assertEqual(len(got_mid), len(mid))
        for i in range(len(mid)):
            if mid[i] != mid[i] or atr[i] != atr[i]:
                self.assertTrue(got_mid[i] != got_mid[i])
                self.assertTrue(upper[i] != upper[i])
                self.assertTrue(lower[i] != lower[i])
                continue
            self.assertAlmostEqual(float(got_mid[i]), float(mid[i]))
            self.assertAlmostEqual(float(upper[i]), float(mid[i] + k * atr[i]))
            self.assertAlmostEqual(float(lower[i]), float(mid[i] - k * atr[i]))

    def test_nonpositive_or_short_is_none(self) -> None:
        highs = [10.0, 12.0]
        lows = [9.0, 10.0]
        closes = [9.5, 11.0]
        calc = self.ns["_calc_keltner"]
        self.assertIsNone(calc(highs, lows, closes, 0, 3, 2.0))
        self.assertIsNone(calc(highs, lows, closes, 3, 0, 2.0))
        self.assertIsNone(calc(highs, lows, closes, 3, 3, 0))
        self.assertIsNone(calc(highs, lows, closes, 3, 3, -1))
        self.assertIsNone(calc(highs, lows, closes, 3, 3, 2.0))
        self.assertIsNone(calc(None, lows, closes, 2, 2, 2.0))


class KeltnerStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def test_structure_defaults(self) -> None:
        st = self.ns["RECIPE"]["structure"]["keltner"]
        self.assertEqual(st["ema_n"], 20)
        self.assertEqual(st["atr_n"], 20)
        win = self.ns["_structure_windows"]()["keltner"]
        self.assertEqual(win["ema_n"], 20)
        self.assertEqual(win["atr_n"], 20)

    def test_ctx_market_has_keltner_mid(self) -> None:
        n = 30
        closes = [10.0 + 0.1 * i for i in range(n)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        volumes = [1000.0] * n
        ctx = self.ns["_build_factor_ctx"](
            closes=closes, volumes=volumes, highs=highs, lows=lows, price=closes[-1]
        )
        market = ctx["market"]
        self.assertEqual(market["kc_ema_n"], 20)
        self.assertEqual(market["kc_atr_n"], 20)
        self.assertIsNotNone(market["kc_mid"])
        self.assertIsNotNone(market["kc_atr"])


if __name__ == "__main__":
    unittest.main()
