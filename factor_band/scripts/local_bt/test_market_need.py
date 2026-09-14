# coding: utf-8
"""RECIPE 闸 ctx 预计算 / 暖机。"""
from __future__ import annotations

import unittest

from run import _exec_bundle


class MarketNeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def test_default_need_tags(self) -> None:
        ns = self.ns
        self.assertEqual(
            ns["_market_need"](),
            {"d_ma_trend", "keltner", "atr", "vol_kc"},
        )
        self.assertNotIn("weekly", ns["_market_need"]())
        self.assertEqual(ns["_ohlcv_need_1w"](), 0)

    def test_weekly_bear_in_entry_adds_weekly(self) -> None:
        ns = self.ns
        rec = dict(ns["RECIPE"])
        rec["entry"] = ["and", "above_ema", "weekly_bear"]
        rec["scale_in"] = False
        rec["exit"] = False
        rec["scale_out"] = False
        self.assertIn("weekly", ns["_market_need"](rec))
        self.assertIn("weekly_bear", ns["_recipe_compute_leaves"](rec))
        self.assertNotIn("weekly_bear_confirm", ns["_recipe_compute_leaves"](rec))

    def test_weekly_bear_confirm_implies_weekly_bear(self) -> None:
        ns = self.ns
        rec = dict(ns["RECIPE"])
        rec["entry"] = False
        rec["scale_in"] = False
        rec["exit"] = ["or", "weekly_bear_confirm"]
        rec["scale_out"] = False
        leaves = ns["_recipe_compute_leaves"](rec)
        self.assertIn("weekly_bear_confirm", leaves)
        self.assertIn("weekly_bear", leaves)
        self.assertIn("weekly", ns["_market_need"](rec))

    def test_ohlcv_need_1d_ignores_plat_keeps_kc_vol(self) -> None:
        ns = self.ns
        need_d = ns["_ohlcv_need_1d"]()
        self.assertGreaterEqual(need_d, 120 + 10)
        plat_n = int(ns["RECIPE"]["factor_params"]["plat_break"]["lookback"] or 20)
        with_plat = plat_n + 2 + 10
        self.assertGreaterEqual(need_d, with_plat)
        orig_lookback = ns["RECIPE"]["factor_params"]["plat_break"]["lookback"]
        try:
            ns["RECIPE"]["factor_params"]["plat_break"]["lookback"] = 500
            self.assertEqual(ns["_ohlcv_need_1d"](), need_d)
        finally:
            ns["RECIPE"]["factor_params"]["plat_break"]["lookback"] = orig_lookback
        kvn = int(ns["RECIPE"]["factor_params"]["keltner_vol"]["vol_n"] or 10)
        kvc = max(1, int(ns["RECIPE"]["factor_params"]["keltner_vol"]["confirm_days"] or 2))
        self.assertGreaterEqual(need_d, kvn + max(0, kvc - 1) + 10)

    def test_default_ctx_skips_unused_series(self) -> None:
        ns = self.ns
        n = 180
        closes = [10.0 + 0.01 * i for i in range(n)]
        volumes = [1000.0] * n
        highs = [c + 0.2 for c in closes]
        lows = [c - 0.2 for c in closes]
        ctx = ns["_build_factor_ctx"](
            closes=closes,
            volumes=volumes,
            highs=highs,
            lows=lows,
            w_detail={},
            price=closes[-1],
        )
        market = ctx["market"]
        self.assertTrue(market["daily_ready"])
        self.assertIsNotNone(market["ma_trend"])
        self.assertIsNotNone(market["kc_mid"])
        self.assertIsNotNone(market["atr"])
        self.assertIsNone(market["ma20"])
        self.assertIsNone(market["vol10"])
        self.assertEqual(market["w_detail"], {})

    def test_unknown_leaf_fail_open(self) -> None:
        ns = self.ns
        rec = dict(ns["RECIPE"])
        rec["entry"] = "not_a_real_leaf"
        rec["scale_in"] = False
        rec["exit"] = False
        rec["scale_out"] = False
        self.assertEqual(ns["_market_need"](rec), set(ns["_MARKET_TAGS"]))


if __name__ == "__main__":
    unittest.main()
