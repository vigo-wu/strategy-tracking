# coding: utf-8
"""grid_score 合成 KPI 钉公式。"""
from __future__ import annotations

import unittest

from grid_score import (
    W_DEF,
    W_GEN,
    W_NO_GEN,
    W_RES,
    W_STR,
    _s_dd,
    _s_decay,
    _s_factor,
    _s_shield,
    _s_trades,
    fill_score,
    s_gen,
    score_cell,
    validate_score,
)


def _book(
    *,
    all_w: dict | None = None,
    tune: dict | None = None,
    check: dict | None = None,
    hold_all: dict | None = None,
    hold_check: dict | None = None,
) -> dict:
    windows = {
        "all": dict(all_w or {}),
        "tune": dict(tune or {}),
        "check": dict(check or {}),
    }
    out: dict = {"windows": windows}
    if hold_all is not None or hold_check is not None:
        out["holdout_windows"] = {
            "all": dict(hold_all or {}),
            "tune": {},
            "check": dict(hold_check or {}),
        }
    return out


class GridScoreTests(unittest.TestCase):
    def test_dd_cap_35pct(self) -> None:
        self.assertAlmostEqual(_s_dd(_book(all_w={"max_dd": -0.35})), 0.0)
        self.assertAlmostEqual(_s_dd(_book(all_w={"max_dd": -0.175})), 50.0)
        self.assertAlmostEqual(_s_dd(_book(all_w={"max_dd": 0.0})), 100.0)
        self.assertAlmostEqual(_s_dd(_book(tune={"max_dd": -0.40}, check={"max_dd": -0.10})), 0.0)

    def test_dd_ignores_holdout(self) -> None:
        book = _book(all_w={"max_dd": -0.10}, hold_all={"max_dd": -0.40})
        self.assertAlmostEqual(_s_dd(book), 100.0 * (1.0 - 0.10 / 0.35))

    def test_shield_floor_and_holdout_node(self) -> None:
        both_pos = _book(tune={"avg_year_pnl": 1.0}, check={"avg_year_pnl": 2.0})
        self.assertAlmostEqual(_s_shield(both_pos, space_on=False), 30.0)
        one_neg = _book(tune={"avg_year_pnl": -1.0}, check={"avg_year_pnl": 2.0})
        self.assertAlmostEqual(_s_shield(one_neg, space_on=False), 15.0)
        two_neg = _book(tune={"avg_year_pnl": -1.0}, check={"avg_year_pnl": 0.0})
        self.assertAlmostEqual(_s_shield(two_neg, space_on=False), 0.0)
        three = _book(
            tune={"avg_year_pnl": -1.0},
            check={"avg_year_pnl": -1.0},
            hold_check={"avg_year_pnl": -1.0},
        )
        self.assertAlmostEqual(_s_shield(three, space_on=True), 0.0)

    def test_trades_piecewise(self) -> None:
        self.assertAlmostEqual(_s_trades({"n_trades": 29}), 0.0)
        self.assertAlmostEqual(_s_trades({"n_trades": 30}), 20.0)
        self.assertAlmostEqual(_s_trades({"n_trades": 55}), 30.0)
        self.assertAlmostEqual(_s_trades({"n_trades": 80}), 40.0)
        self.assertAlmostEqual(_s_trades({"n_trades": 90}), 40.0)

    def test_pf_cap_5(self) -> None:
        capped = _s_factor({"win_rate": 8.0, "profit_factor": 99.0})
        expected = min(100.0, (0.08 * 5.0) / 0.5 * 100.0) * 0.60
        self.assertAlmostEqual(capped, expected)
        self.assertLess(capped, 60.0)

    def test_ann_decay_piecewise(self) -> None:
        self.assertAlmostEqual(
            _s_decay(_book(tune={"avg_ann_pct": 2.0}, check={"avg_ann_pct": 2.0})),
            50.0,
        )
        self.assertAlmostEqual(
            _s_decay(_book(tune={"avg_ann_pct": 2.0}, check={"avg_ann_pct": 1.0})),
            25.0,
        )
        self.assertAlmostEqual(
            _s_decay(_book(tune={"avg_ann_pct": 2.0}, check={"avg_ann_pct": 0.0})),
            0.0,
        )
        self.assertAlmostEqual(
            _s_decay(_book(tune={"avg_ann_pct": -0.5}, check={"avg_ann_pct": 3.0})),
            0.0,
        )
        self.assertAlmostEqual(
            _s_decay(_book(tune={"avg_ann_pct": 1.0}, check={"avg_ann_pct": 1.5})),
            50.0,
        )

    def test_spatial_linear_and_missing(self) -> None:
        eq = _book(all_w={"sharpe": 0.4}, hold_all={"sharpe": 0.4})
        self.assertAlmostEqual(s_gen(eq, space_on=True), 100.0)
        half = _book(all_w={"sharpe": 0.4}, hold_all={"sharpe": 0.2})
        self.assertAlmostEqual(s_gen(half, space_on=True), 50.0)
        dead = _book(all_w={"sharpe": 0.4}, hold_all={"sharpe": -0.1})
        self.assertAlmostEqual(s_gen(dead, space_on=True), 0.0)
        missing = _book(all_w={"sharpe": 0.4})
        self.assertAlmostEqual(s_gen(missing, space_on=True), 0.0)
        self.assertIsNone(s_gen(eq, space_on=False))

    def test_no_holdout_redistributes(self) -> None:
        book = _book(
            all_w={"max_dd": 0.0, "sharpe": 0.5},
            tune={
                "max_dd": 0.0,
                "avg_year_pnl": 1.0,
                "sharpe": 0.5,
                "avg_ann_pct": 2.0,
            },
            check={
                "max_dd": 0.0,
                "avg_year_pnl": 1.0,
                "sharpe": 0.5,
                "avg_ann_pct": 2.0,
                "win_rate": 50.0,
                "profit_factor": 1.0,
                "n_trades": 80,
            },
        )
        sc = score_cell(book, space_on=False)
        self.assertTrue(sc["scored"])
        self.assertIsNone(sc["s_gen"])
        core = W_DEF * sc["s_def"] + W_STR * sc["s_str"] + W_RES * sc["s_res"]
        self.assertAlmostEqual(sc["total"], core / W_NO_GEN, places=4)

    def test_space_on_missing_holdout_zero_gen(self) -> None:
        book = _book(
            all_w={"max_dd": 0.0, "sharpe": 0.4},
            tune={"max_dd": 0.0, "avg_year_pnl": 1.0, "sharpe": 0.2, "avg_ann_pct": 1.0},
            check={
                "max_dd": 0.0,
                "avg_year_pnl": 1.0,
                "sharpe": 0.2,
                "avg_ann_pct": 1.0,
                "win_rate": 35.0,
                "profit_factor": 1.1,
                "n_trades": 90,
            },
        )
        sc = score_cell(book, space_on=True)
        self.assertEqual(sc["s_gen"], 0.0)
        core = W_DEF * sc["s_def"] + W_STR * sc["s_str"] + W_RES * sc["s_res"]
        self.assertAlmostEqual(sc["total"], core + W_GEN * 0.0, places=4)

    def test_empty_not_scored(self) -> None:
        sc = score_cell({}, space_on=False)
        self.assertFalse(sc["scored"])
        self.assertIsNone(sc["s_gen"])

    def test_pick_recommend_ranks_total(self) -> None:
        from summarize import pick_recommend

        low = _book(
            all_w={"max_dd": -0.34, "sharpe": 0.1},
            tune={"max_dd": -0.34, "avg_year_pnl": -1.0, "sharpe": 0.01, "avg_ann_pct": -0.5},
            check={
                "max_dd": -0.10,
                "avg_year_pnl": 1.0,
                "sharpe": 0.1,
                "avg_ann_pct": 1.0,
                "win_rate": 30.0,
                "profit_factor": 1.0,
                "n_trades": 20,
            },
        )
        high = _book(
            all_w={"max_dd": 0.0, "sharpe": 0.4},
            tune={"max_dd": 0.0, "avg_year_pnl": 10.0, "sharpe": 0.4, "avg_ann_pct": 3.0},
            check={
                "max_dd": 0.0,
                "avg_year_pnl": 10.0,
                "sharpe": 0.4,
                "avg_ann_pct": 3.0,
                "win_rate": 40.0,
                "profit_factor": 1.5,
                "n_trades": 90,
            },
        )
        cells = [
            {
                "id": "low",
                "label": "low",
                "kind": "other",
                "n_diffs": 0,
                "overrides": {},
                "samples": {"book": low},
            },
            {
                "id": "high",
                "label": "high",
                "kind": "tighten",
                "n_diffs": 2,
                "overrides": {},
                "samples": {"book": high},
            },
        ]
        rec = pick_recommend(cells)
        self.assertEqual(rec["id"], "high")
        self.assertIsNotNone(rec["total"])
        self.assertGreater(float(rec["total"]), 0.0)
        by_id = {n["id"]: n for n in rec["candidates"]}
        self.assertGreater(float(by_id["high"]["total"]), float(by_id["low"]["total"]))
        self.assertIn("四维综合分", rec["reason"])
        self.assertNotIn("gate", rec)

    def test_fill_score_normalizes_same_ratio(self) -> None:
        a = fill_score({"w_def": 30, "w_str": 25, "w_res": 25, "w_gen": 20})
        b = fill_score({"w_def": 60, "w_str": 50, "w_res": 50, "w_gen": 40})
        keys = ("w_def", "w_str", "w_res", "w_gen")
        for k in keys:
            self.assertAlmostEqual(a[k], b[k])
        self.assertAlmostEqual(sum(a[k] for k in keys), 1.0)
        self.assertAlmostEqual(a["dd_cap"], 0.35)
        pct = fill_score({"dd_cap": 35})
        self.assertAlmostEqual(pct["dd_cap"], 0.35)

    def test_validate_score_rejects_bad_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            validate_score({"w_def": 0, "w_str": 0, "w_res": 0, "w_gen": 0})
        with self.assertRaises(ValueError):
            validate_score({"w_def": -1, "w_str": 1, "w_res": 1, "w_gen": 1})
        with self.assertRaises(ValueError):
            validate_score({"dd_cap": 0})
        with self.assertRaises(ValueError):
            validate_score({"n_trades_floor": 80, "n_trades_full": 30})
        with self.assertRaises(ValueError):
            validate_score({"n_trades_floor": 80, "n_trades_full": 80})

    def test_score_cell_dd_cap_changes_s_def(self) -> None:
        book = _book(all_w={"max_dd": -0.20}, tune={"max_dd": -0.20}, check={"max_dd": -0.20})
        wide = score_cell(book, space_on=False, cfg={"dd_cap": 0.35})
        tight = score_cell(book, space_on=False, cfg={"dd_cap": 0.20})
        self.assertGreater(float(wide["s_def"]), float(tight["s_def"]))
        self.assertAlmostEqual(float(tight["s_def"]), 0.0)


if __name__ == "__main__":
    unittest.main()
