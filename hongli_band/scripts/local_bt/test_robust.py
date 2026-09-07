# coding: utf-8
"""robust_gate / robust_spec / sample / summarize 纯逻辑单测。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from robust_gate import (  # noqa: E402
    default_gate,
    eval_basket,
    eval_run,
    fill_gate,
    validate_gate,
)
from robust_sample import draw_baskets, mean_pairwise_jaccard, sample_baskets_for_spec  # noqa: E402
from robust_spec import (  # noqa: E402
    RobustSpecError,
    load_spec,
    resolve_overrides,
    resolve_overrides_from_summary,
    validate_year_windows,
)
from robust_summarize import window_kpi_from_trades  # noqa: E402


class TestRobustGate(unittest.TestCase):
    def test_hard_fail_soft_warn(self) -> None:
        g = default_gate()
        g["soft"]["win_rate"]["veto"] = False
        kpi = {
            "calmar": 2.0,
            "max_dd": -0.05,
            "oos_sharpe": 1.0,
            "profit_factor": 2.0,
            "win_rate": 30.0,
            "n_trades": 20,
        }
        row = eval_basket(kpi, g, basket_size=10, n_years=3)
        self.assertTrue(row["pass"])
        self.assertTrue(row["warn"])

    def test_hard_calmar_fail(self) -> None:
        g = default_gate()
        g["soft"]["win_rate"]["veto"] = False
        g["soft"]["n_trades"]["veto"] = False
        kpi = {
            "calmar": 0.5,
            "max_dd": -0.05,
            "oos_sharpe": 1.0,
            "profit_factor": 2.0,
            "win_rate": 50.0,
            "n_trades": 20,
        }
        row = eval_basket(kpi, g)
        self.assertFalse(row["pass"])
        self.assertIn("卡玛", str(row["fail"]))

    def test_soft_veto(self) -> None:
        g = default_gate()
        g["soft"]["win_rate"]["veto"] = True
        kpi = {
            "calmar": 2.0,
            "max_dd": -0.05,
            "oos_sharpe": 1.0,
            "profit_factor": 2.0,
            "win_rate": 10.0,
            "n_trades": 20,
        }
        row = eval_basket(kpi, g)
        self.assertFalse(row["pass"])

    def test_eval_run_go(self) -> None:
        g = default_gate()
        g["aggregate"]["pass_rate_min"] = 0.5
        g["aggregate"]["median_calmar_min"] = 1.0
        g["aggregate"]["tail_max_dd_floor"] = -0.20
        rows = [
            {"pass": True, "calmar": 1.5, "max_dd": -0.08},
            {"pass": True, "calmar": 1.4, "max_dd": -0.09},
            {"pass": False, "calmar": 0.8, "max_dd": -0.11},
        ]
        out = eval_run(rows, g)
        self.assertEqual(out["verdict"], "GO")

    def test_eval_run_nogo_rate(self) -> None:
        g = default_gate()
        g["aggregate"]["pass_rate_min"] = 0.9
        rows = [
            {"pass": True, "calmar": 2.0, "max_dd": -0.05},
            {"pass": False, "calmar": 2.0, "max_dd": -0.05},
        ]
        out = eval_run(rows, g)
        self.assertEqual(out["verdict"], "NO-GO")


class TestRobustSpec(unittest.TestCase):
    def test_deploy_must_after_check(self) -> None:
        with self.assertRaises(RobustSpecError):
            validate_year_windows(
                {
                    "year_start": 2018,
                    "year_end": 2026,
                    "tune_start": 2018,
                    "tune_end": 2021,
                    "check_start": 2022,
                    "check_end": 2024,
                    "deploy_start": 2024,
                    "deploy_end": 2026,
                }
            )

    def test_overrides_from_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = {
                "recommend": {"id": "sl06", "kind": "tighten", "reason": "ok"},
                "cells": [
                    {"id": "base", "kind": "base", "overrides": {}},
                    {"id": "sl06", "kind": "tighten", "overrides": {"STOP_LOSS": 0.06}},
                ],
            }
            path = root / "summary.json"
            path.write_text(json.dumps(summary), encoding="utf-8")
            got = resolve_overrides_from_summary(path)
            self.assertEqual(got["id"], "sl06")
            self.assertEqual(got["overrides"]["STOP_LOSS"], 0.06)

    def test_base_empty_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = {
                "recommend": {"id": "base", "kind": "base", "reason": "维持现行"},
                "cells": [{"id": "base", "kind": "base", "overrides": {}}],
            }
            path = root / "summary.json"
            path.write_text(json.dumps(summary), encoding="utf-8")
            got = resolve_overrides({"overrides_from": str(path)})
            self.assertEqual(got["id"], "base")
            self.assertEqual(got["overrides"], {})

    def test_empty_means_config(self) -> None:
        got = resolve_overrides({})
        self.assertEqual(got["id"], "config")
        self.assertEqual(got["overrides"], {})

    def test_freeze_reload_empty_overrides(self) -> None:
        got = resolve_overrides(
            {
                "overrides": {},
                "_overrides_meta": {"id": "base", "kind": "base", "label": "base"},
            }
        )
        self.assertEqual(got["id"], "base")
        self.assertEqual(got["overrides"], {})

    def test_load_spec_manual_overrides(self) -> None:
        spec = load_spec(
            {
                "run_id": "t1",
                "overrides": {"STOP_LOSS": 0.1},
                "year_start": 2018,
                "year_end": 2026,
                "tune_start": 2018,
                "tune_end": 2021,
                "check_start": 2022,
                "check_end": 2023,
                "deploy_start": 2024,
                "deploy_end": 2026,
                "n_baskets": 2,
                "basket_size": 3,
            }
        )
        self.assertEqual(spec["overrides"]["STOP_LOSS"], 0.1)
        self.assertEqual(spec["deploy_start"], 2024)


class TestRobustSample(unittest.TestCase):
    def test_draw_reproducible(self) -> None:
        pool = ["000001.SZ", "000002.SZ", "600000.SH", "600519.SH", "000858.SZ"]
        a = draw_baskets(pool, n_baskets=3, basket_size=2, seed=7)
        b = draw_baskets(pool, n_baskets=3, basket_size=2, seed=7)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 3)
        self.assertEqual(len(a[0]), 2)

    def test_jaccard(self) -> None:
        v = mean_pairwise_jaccard([["A", "B"], ["A", "C"], ["B", "C"]])
        self.assertIsNotNone(v)
        self.assertGreater(float(v), 0.0)


class TestWindowKpi(unittest.TestCase):
    def test_trade_window_filter(self) -> None:
        trades = [
            {"sell_exec_day": "20220115", "pnl": 100.0},
            {"sell_exec_day": "20240115", "pnl": -50.0},
            {"sell_exec_day": "20240601", "pnl": 80.0},
        ]
        kpi = window_kpi_from_trades(trades, {2024}, budget=100000.0)
        self.assertEqual(kpi["n_trades"], 2)
        self.assertAlmostEqual(float(kpi["win_rate"]), 50.0)
        self.assertIsNotNone(kpi["max_dd"])
        self.assertIsNotNone(kpi["calmar"])


if __name__ == "__main__":
    unittest.main()
