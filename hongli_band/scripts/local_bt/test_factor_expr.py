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
        ns["W_BEAR_CONFIRM_DAYS"] = 2
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
            ["weekly_bear_confirm", "stop_loss", "trail_stop", "time_force"],
        )


if __name__ == "__main__":
    unittest.main()
