# coding: utf-8
"""Recipe AST 求值；当天空头 vs 确认清仓两套 weekly_bear。"""
from __future__ import annotations

import unittest

from run import _exec_bundle


class FactorExprTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def _hit(self, expr, ctx):
        return self.ns["_recipe_hit"](expr, ctx)

    def test_and_or_not(self) -> None:
        ns = self.ns

        def fake_eval(fid, ctx):
            return bool(ctx.get(fid)), {}

        orig = ns["_factor_eval"]
        ns["_factor_eval"] = fake_eval
        try:
            ok, rs = self._hit(["and", "a", "b"], {"a": True, "b": True})
            self.assertTrue(ok)
            self.assertEqual(rs, ["a", "b"])
            ok, _ = self._hit(["and", "a", "b"], {"a": True, "b": False})
            self.assertFalse(ok)
            ok, rs = self._hit(["or", "a", "b"], {"a": False, "b": True})
            self.assertTrue(ok)
            self.assertEqual(rs, ["b"])
            ok, rs = self._hit(["not", "a"], {"a": False})
            self.assertTrue(ok)
            self.assertEqual(rs, [])
            ok, _ = self._hit(False, {})
            self.assertFalse(ok)
        finally:
            ns["_factor_eval"] = orig

    def test_weekly_bear_same_day_vs_confirm(self) -> None:
        ns = self.ns
        detail = {
            "close": 8.0,
            "ma30": 10.0,
            "dif": 0.1,
            "dea": 0.2,
            "dif_prev": 0.2,
            "dea_prev": 0.1,
        }
        ctx = {
            "market": {"w_detail": detail},
            "state": {"w_bear_streak": 1, "w_bear_confirmed": False},
        }
        self.assertTrue(ns["_factor_hit"]("weekly_bear", ctx))
        self.assertFalse(ns["_factor_hit"]("weekly_bear_confirm", ctx))
        ctx["state"]["w_bear_streak"] = 2
        ctx["state"].pop("w_bear_confirmed")
        self.assertTrue(ns["_factor_hit"]("weekly_bear_confirm", ctx))
        ctx_flat = {
            "market": {
                "w_detail": {
                    "close": 12.0,
                    "ma30": 10.0,
                    "dif": 0.2,
                    "dea": 0.1,
                    "dif_prev": 0.1,
                    "dea_prev": 0.05,
                }
            },
            "state": {"w_bear_streak": 2},
        }
        self.assertFalse(ns["_factor_hit"]("weekly_bear", ctx_flat))


class DefaultRecipeShapeTests(unittest.TestCase):
    def test_asymmetric_scale_in(self) -> None:
        from run import _exec_bundle

        ns = _exec_bundle()
        recipe = ns["RECIPE"]
        self.assertEqual(recipe["scale_out"], False)
        entry = recipe["entry"]
        self.assertEqual(entry[0], "and")
        self.assertIn(["not", "chase"], entry)
        scale = recipe["scale_in"]
        self.assertEqual(scale[0], "and")
        self.assertNotIn(["not", "chase"], scale[1:5])
        or_node = scale[-1]
        self.assertEqual(or_node[0], "or")
        self.assertEqual(or_node[1], ["and", "pullback_vol", ["not", "chase"]])
        self.assertIn("plat_break", or_node)
        self.assertIn("w_macd_golden", or_node)
        self.assertEqual(
            recipe["exit"],
            [
                "weekly_bear_confirm",
                "stop_loss",
                "atr_stop",
                "trail_stop",
                "time_force",
            ],
        )
        fp = recipe["factor_params"]
        self.assertAlmostEqual(fp["chase"]["max_pct"], 0.05)
        self.assertAlmostEqual(fp["stop_loss"]["pct"], 0.08)
        self.assertAlmostEqual(fp["atr_stop"]["k"], 2)
        self.assertEqual(fp["time_force"]["bars"], 30)
        self.assertEqual(fp["pullback_vol"]["vol_n"], 10)
        self.assertEqual(recipe["structure"]["atr"]["n"], 14)


def _chase_ctx(chg):
    prev = 10.0
    price = prev * (1.0 + float(chg))
    return {
        "market": {
            "daily_ready": True,
            "closes": [prev, price],
            "i": 1,
            "close": price,
        },
        "state": {},
        "clock": {},
    }


class FactorParamsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def _fp(self, fid, key):
        return self.ns["RECIPE"]["factor_params"][fid][key]

    def _set_fp(self, fid, key, val):
        self.ns["RECIPE"]["factor_params"][fid][key] = val

    def test_default_chase_threshold(self) -> None:
        ns = self.ns
        self.assertAlmostEqual(self._fp("chase", "max_pct"), 0.05)
        self.assertFalse(ns["_factor_hit"]("chase", _chase_ctx(0.049)))
        self.assertTrue(ns["_factor_hit"]("chase", _chase_ctx(0.05)))

    def test_table_only_no_global_alias(self) -> None:
        ns = self.ns
        orig = self._fp("chase", "max_pct")
        try:
            self._set_fp("chase", "max_pct", 0.03)
            self.assertNotIn("CHASE_MAX_PCT", ns)
            self.assertTrue(ns["_factor_hit"]("chase", _chase_ctx(0.04)))
        finally:
            self._set_fp("chase", "max_pct", orig)

    def test_apply_nested_merge(self) -> None:
        ns = self.ns
        orig = self._fp("chase", "max_pct")
        try:
            ns["_factor_params_apply_global"]({"chase": {"max_pct": 0.03}})
            self.assertAlmostEqual(self._fp("chase", "max_pct"), 0.03)
            self.assertTrue(ns["_factor_hit"]("chase", _chase_ctx(0.04)))
        finally:
            ns["_factor_params_apply_global"]({"chase": {"max_pct": orig}})

    def test_time_force_bars_off(self) -> None:
        ns = self.ns
        orig = self._fp("time_force", "bars")
        try:
            self._set_fp("time_force", "bars", 0)
            closes = [10.0] * 80
            lot = {"id": 1, "price": 100.0, "hold_peak": 102.0, "hold_bars": 99}
            ctx = {
                "market": {"close": 9.5, "closes": closes},
                "state": {"lot": lot},
            }
            self.assertFalse(ns["_factor_hit"]("time_force", ctx))
        finally:
            self._set_fp("time_force", "bars", orig)

    def test_weekly_bear_confirm_days_one(self) -> None:
        ns = self.ns
        orig = self._fp("weekly_bear_confirm", "days")
        ctx = {"market": {}, "state": {"w_bear_streak": 1}}
        try:
            self._set_fp("weekly_bear_confirm", "days", 1)
            self.assertTrue(ns["_factor_hit"]("weekly_bear_confirm", ctx))
            self._set_fp("weekly_bear_confirm", "days", 0)
            self.assertEqual(ns["_w_bear_confirm_need"](), 1)
            self.assertTrue(ns["_factor_hit"]("weekly_bear_confirm", ctx))
        finally:
            self._set_fp("weekly_bear_confirm", "days", orig)

    def test_pullback_vol_n_rebuilds_sma(self) -> None:
        ns = self.ns
        orig = self._fp("pullback_vol", "vol_n")
        closes = [10.0] * 30
        volumes = [float(i + 1) for i in range(30)]
        try:
            self._set_fp("pullback_vol", "vol_n", 5)
            _ready5, d5 = ns["_factor_daily_features"](closes, volumes)
            self._set_fp("pullback_vol", "vol_n", 10)
            _ready10, d10 = ns["_factor_daily_features"](closes, volumes)
            self.assertNotEqual(d5.get("v10"), d10.get("v10"))
        finally:
            self._set_fp("pullback_vol", "vol_n", orig)


if __name__ == "__main__":
    unittest.main()
