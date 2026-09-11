# coding: utf-8
"""减仓 Intent：RECIPE_SCALE_OUT 空则不减；两笔时只平指定笔。"""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
HLBAND = HERE.parent / "qmt" / "hlband"
INTENT_PATH = HLBAND / "factors" / "intent.py"


def _load_intent(lots, scale_out_lot="last"):
    A = SimpleNamespace(lots=lots)
    ns = {
        "A": A,
        "SCALE_OUT_LOT": scale_out_lot,
        "RECIPE_EXIT_WEEKLY_BEAR": True,
    }
    src = INTENT_PATH.read_text(encoding="utf-8")
    exec(compile(src, str(INTENT_PATH), "exec"), ns, ns)
    ns["A"] = A
    return ns


def _lot(lid, shares=1000):
    return {"id": lid, "shares": shares, "price": 10.0}


class ScaleOutIntentTest(unittest.TestCase):
    def test_empty_recipe_no_reduce(self) -> None:
        ns = _load_intent([_lot(1), _lot(2)])
        intent = ns["_resolve_intent"](
            True, False, False, False, [], [], 0, False, [], False, [], True, False, []
        )
        self.assertIsNone(intent.get("target"))

    def test_two_lots_picks_last(self) -> None:
        ns = _load_intent([_lot(1), _lot(2)], scale_out_lot="last")
        intent = ns["_resolve_intent"](
            True,
            False,
            False,
            False,
            [],
            [],
            0,
            True,
            ["scale_out"],
            False,
            [],
            True,
            False,
            [],
        )
        self.assertEqual(intent.get("target"), "reduce")
        self.assertFalse(intent.get("sell_all"))
        self.assertEqual(intent.get("lot_ids"), [2])
        self.assertEqual(intent.get("shares"), 1000)

    def test_one_lot_no_reduce(self) -> None:
        ns = _load_intent([_lot(1)])
        intent = ns["_resolve_intent"](
            True, False, False, False, [], [], 0, True, ["scale_out"], False, [], True, False, []
        )
        self.assertIsNone(intent.get("target"))

    def test_exit_beats_scale_out(self) -> None:
        ns = _load_intent([_lot(1), _lot(2)])
        intent = ns["_resolve_intent"](
            True,
            False,
            False,
            True,
            ["stop_loss"],
            [1],
            1000,
            True,
            ["scale_out"],
            False,
            [],
            True,
            False,
            [],
        )
        self.assertEqual(intent.get("target"), "flat")
        self.assertEqual(intent.get("reason"), "stop_loss")

    def test_skip_sell_allows_add(self) -> None:
        ns = _load_intent([_lot(1), _lot(2)])
        intent = ns["_resolve_intent"](
            True,
            False,
            True,
            True,
            ["stop_loss"],
            [1],
            1000,
            True,
            ["scale_out"],
            True,
            ["plat_break"],
            True,
            False,
            [],
        )
        self.assertEqual(intent.get("target"), "add")
        self.assertTrue(intent.get("add"))


if __name__ == "__main__":
    unittest.main()
