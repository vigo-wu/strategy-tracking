# coding: utf-8
"""Intent 仲裁：flat > reduce > add > open；减仓槽默认不产生 reduce。"""
from __future__ import annotations

import unittest

from run import _exec_bundle, run_init_probe
from grid_run import parse_fingerprint, expected_fingerprint, load_config_defaults
from grid_spec import recipe_fingerprint


class IntentArbitrateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ns = _exec_bundle()

    def test_flat_beats_add(self) -> None:
        fn = self.ns["_arbitrate_intent"]
        got = fn(
            entry={"hit": True, "reasons": ["pullback_vol"]},
            scale_in={"hit": True, "reasons": ["plat_break"]},
            exit_slot={"hit": True, "reasons": ["stop_loss"]},
            scale_out={"hit": False},
            scale_gate_ok=True,
            holding=True,
            lot_ids=[1],
            shares=1000,
        )
        self.assertEqual(got["target"], "flat")
        self.assertEqual(got["side"], "sell")
        self.assertEqual(got["reasons"], ["stop_loss"])

    def test_reduce_beats_add_but_default_scale_out_false(self) -> None:
        fn = self.ns["_arbitrate_intent"]
        forced = fn(
            entry={"hit": False},
            scale_in={"hit": True, "reasons": ["plat_break"]},
            exit_slot={"hit": False},
            scale_out={"hit": True, "reasons": ["fake"]},
            scale_gate_ok=True,
            holding=True,
        )
        self.assertEqual(forced["target"], "reduce")
        slots = self.ns["_eval_recipe_slots"](
            {"market": {"daily_ready": False, "w_detail": {}}, "state": {}, "clock": {}}
        )
        self.assertFalse(slots["scale_out"]["hit"])
        self.assertIn("reduce", ("open", "add", "flat", "reduce"))

    def test_add_then_open(self) -> None:
        fn = self.ns["_arbitrate_intent"]
        add = fn(
            entry={"hit": True, "reasons": ["pullback_vol"]},
            scale_in={"hit": True, "reasons": ["plat_break"]},
            exit_slot={"hit": False},
            scale_out={"hit": False},
            scale_gate_ok=True,
            holding=True,
        )
        self.assertEqual(add["target"], "add")
        opened = fn(
            entry={"hit": True, "reasons": ["pullback_vol"]},
            scale_in={"hit": True, "reasons": ["plat_break"]},
            exit_slot={"hit": False},
            scale_out={"hit": False},
            scale_gate_ok=True,
            holding=False,
        )
        self.assertEqual(opened["target"], "open")
        blocked = fn(
            entry={"hit": True, "reasons": ["pullback_vol"]},
            scale_in={"hit": True, "reasons": ["plat_break"]},
            exit_slot={"hit": False},
            scale_out={"hit": False},
            scale_gate_ok=False,
            holding=True,
        )
        self.assertIsNone(blocked["target"])


class RecipeFingerprintTests(unittest.TestCase):
    def test_probe_prints_recipe_and_override_changes_hash(self) -> None:
        defaults = load_config_defaults()
        text0 = run_init_probe({})
        got0 = parse_fingerprint(text0)
        self.assertTrue(got0["has_recipe"])
        exp0 = expected_fingerprint(defaults, {})
        self.assertEqual(got0["recipe"], exp0["recipe"])
        ov = {"factor_params": {"chase": {"max_pct": 0.03}}}
        text1 = run_init_probe(ov)
        got1 = parse_fingerprint(text1)
        self.assertTrue(got1["has_recipe"])
        self.assertNotEqual(got0["recipe"], got1["recipe"])
        self.assertEqual(
            got1["recipe"],
            recipe_fingerprint(overrides=ov),
        )


if __name__ == "__main__":
    unittest.main()
