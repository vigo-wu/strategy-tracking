# coding: utf-8
"""Recipe 布尔式：and/or/not、缺叶子、not→现网 skip 码。"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HLBAND = HERE.parent / "qmt" / "hlband"


def _load_expr_ns():
    ns: dict = {}
    for rel in (
        "factors/registry.py",
        "factors/expr.py",
    ):
        path = HLBAND / rel
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), ns, ns)

    def _true(_ctx):
        return True, {}

    def _false(_ctx):
        return False, {}

    ns["_register_factor"]("chase", _false, "chase_skip", "gate")
    ns["_register_factor"]("vol_dry", _true, "vol_dry_skip", "gate")
    ns["_register_factor"]("pullback_vol", _true, "pullback_vol")
    return ns


class FactorExprTest(unittest.TestCase):
    def test_and_or_not(self) -> None:
        ns = _load_expr_ns()
        hit = ns["_hit"]
        ctx = {}
        ok, reasons, _d = hit(
            ["and", ["not", "chase"], "pullback_vol"],
            ctx,
        )
        self.assertTrue(ok)
        self.assertEqual(reasons, ["pullback_vol"])
        ok, reasons, _d = hit(["or", "chase", "pullback_vol"], ctx)
        self.assertTrue(ok)
        self.assertEqual(reasons, ["pullback_vol"])
        ok, reasons, _d = hit(["not", "vol_dry"], ctx)
        self.assertFalse(ok)
        self.assertEqual(reasons, ["vol_dry_skip"])

    def test_unknown_leaf(self) -> None:
        ns = _load_expr_ns()
        with self.assertRaises(ValueError) as ctx:
            ns["_hit"]("no_such_factor", {})
        self.assertIn("unknown factor", str(ctx.exception))

    def test_recipe_off(self) -> None:
        ns = _load_expr_ns()
        self.assertTrue(ns["_recipe_off"]([]))
        self.assertTrue(ns["_recipe_off"](False))
        self.assertFalse(ns["_recipe_off"]("pullback_vol"))
        ok, reasons, _d = ns["_hit"]([], {})
        self.assertFalse(ok)
        self.assertEqual(reasons, [])

    def test_gate_kind_skip_codes(self) -> None:
        ns = _load_expr_ns()
        gates = ns["_factor_gate_reasons"]()
        self.assertIn("chase_skip", gates)
        self.assertIn("vol_dry_skip", gates)
        self.assertNotIn("pullback_vol", gates)

    def test_entry_slot_real_filters_gate_skip(self) -> None:
        ns = _load_expr_ns()
        slots = (HLBAND / "factors" / "slots.py").read_text(encoding="utf-8")
        exec(compile(slots, str(HLBAND / "factors" / "slots.py"), "exec"), ns, ns)
        ns["RECIPE_ENTRY"] = ["not", "vol_dry"]
        hit, reasons, real, _d = ns["_eval_entry_slot"]({})
        self.assertFalse(hit)
        self.assertEqual(reasons, ["vol_dry_skip"])
        self.assertEqual(real, [])

    def test_scale_in_no_hardcoded_leaves(self) -> None:
        ns = _load_expr_ns()
        slots = (HLBAND / "factors" / "slots.py").read_text(encoding="utf-8")
        exec(compile(slots, str(HLBAND / "factors" / "slots.py"), "exec"), ns, ns)
        ns["RECIPE_SCALE_IN"] = []
        hit, push = ns["_eval_scale_in_slot"]({})
        self.assertFalse(hit)
        self.assertEqual(push, [])

    def test_pending_gate_vol_dry_cancels(self) -> None:
        ns = _load_expr_ns()
        slots = (HLBAND / "factors" / "slots.py").read_text(encoding="utf-8")
        exec(compile(slots, str(HLBAND / "factors" / "slots.py"), "exec"), ns, ns)
        ns["RECIPE_ENTRY"] = ["and", ["not", "vol_dry"], "pullback_vol"]
        ok, reasons = ns["_pending_gate_hit"]({}, False)
        self.assertFalse(ok)
        self.assertEqual(reasons, ["vol_dry_skip"])

    def test_pending_scale_in_chase_does_not_cancel(self) -> None:
        ns = _load_expr_ns()
        slots = (HLBAND / "factors" / "slots.py").read_text(encoding="utf-8")
        exec(compile(slots, str(HLBAND / "factors" / "slots.py"), "exec"), ns, ns)

        def _true(_ctx):
            return True, {}

        def _false(_ctx):
            return False, {}

        ns["_register_factor"]("chase", _true, "chase_skip", "gate")
        ns["_register_factor"]("vol_dry", _false, "vol_dry_skip", "gate")
        ns["RECIPE_SCALE_IN"] = [
            "and",
            ["not", "vol_dry"],
            ["or", "pullback_vol", "plat_break"],
        ]
        ok, reasons = ns["_pending_gate_hit"]({}, True)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_pending_signal_leaf_off_does_not_cancel(self) -> None:
        ns = _load_expr_ns()
        slots = (HLBAND / "factors" / "slots.py").read_text(encoding="utf-8")
        exec(compile(slots, str(HLBAND / "factors" / "slots.py"), "exec"), ns, ns)

        def _false(_ctx):
            return False, {}

        ns["_register_factor"]("vol_dry", _false, "vol_dry_skip", "gate")
        ns["_register_factor"]("pullback_vol", _false, "pullback_vol")
        ns["RECIPE_ENTRY"] = ["and", ["not", "vol_dry"], "pullback_vol"]
        ok, reasons = ns["_pending_gate_hit"]({}, False)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_deploy_globs_lib_not_slot_files(self) -> None:
        deploy = HLBAND.parent / "_deploy_qmt_gbk.py"
        spec = importlib.util.spec_from_file_location("hlband_deploy_libtest", deploy)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        order = list(mod.MODULE_ORDER)
        lib_dir = HLBAND / "factors" / "lib"
        names = sorted(
            p.name for p in lib_dir.glob("*.py") if p.is_file() and not p.name.startswith("_")
        )
        self.assertTrue(names)
        for n in names:
            self.assertIn("factors/lib/%s" % n, order)
        self.assertNotIn("factors/entry.py", order)
        self.assertNotIn("factors/scale.py", order)
        self.assertNotIn("factors/exit.py", order)


if __name__ == "__main__":
    unittest.main()
