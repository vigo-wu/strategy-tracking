# coding: utf-8
"""robust_gate / robust_spec / sample / summarize 纯逻辑单测。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    fill_sampling,
    fingerprints_match,
    load_spec,
    resolve_overrides,
    resolve_overrides_from_summary,
    sampling_fingerprint,
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
                    {
                        "id": "sl06",
                        "kind": "tighten",
                        "overrides": {"factor_params": {"stop_loss": {"pct": 0.06}}},
                    },
                ],
            }
            path = root / "summary.json"
            path.write_text(json.dumps(summary), encoding="utf-8")
            got = resolve_overrides_from_summary(path)
            self.assertEqual(got["id"], "sl06")
            self.assertEqual(got["overrides"]["factor_params"]["stop_loss"]["pct"], 0.06)
            base = resolve_overrides_from_summary(path, recommend_id="base")
            self.assertEqual(base["id"], "base")
            self.assertEqual(base["overrides"], {})
            self.assertEqual(base["reason"], "手动指定格子")
            via = resolve_overrides(
                {"overrides_from": str(path), "overrides_cell_id": "base"}
            )
            self.assertEqual(via["id"], "base")
            with self.assertRaises(Exception) as ctx:
                resolve_overrides_from_summary(path, recommend_id="nope")
            self.assertIn("无格子 id", str(ctx.exception))

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
                "overrides": {"factor_params": {"stop_loss": {"pct": 0.1}}},
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
        self.assertEqual(spec["overrides"]["factor_params"]["stop_loss"]["pct"], 0.1)
        self.assertEqual(spec["deploy_start"], 2024)

    def test_load_spec_rejects_old_stop_loss(self) -> None:
        with self.assertRaises(RobustSpecError) as ctx:
            load_spec(
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
        self.assertIn("STOP_LOSS", str(ctx.exception))

    def test_load_spec_rejects_flat_stop_loss_pct(self) -> None:
        with self.assertRaises(RobustSpecError) as ctx:
            load_spec(
                {
                    "run_id": "t1",
                    "overrides": {"stop_loss.pct": 0.1},
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
        self.assertIn("stop_loss.pct", str(ctx.exception))

    def test_load_spec_rejects_old_dma_mid(self) -> None:
        with self.assertRaises(RobustSpecError) as ctx:
            load_spec(
                {
                    "run_id": "t1",
                    "overrides": {"D_MA_MID": 15},
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
        self.assertIn("D_MA_MID", str(ctx.exception))

    def test_load_spec_rejects_flat_dma_mid(self) -> None:
        with self.assertRaises(RobustSpecError) as ctx:
            load_spec(
                {
                    "run_id": "t1",
                    "overrides": {"d_ma.mid": 15},
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
        self.assertIn("d_ma.mid", str(ctx.exception))


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

    def test_full_span_passed_to_eligible(self) -> None:
        spec = {
            "year_start": 2018,
            "year_end": 2026,
            "n_baskets": 2,
            "basket_size": 2,
            "seed": 1,
            "full_span": True,
        }
        pool = ["000001.SZ", "000002.SZ", "600000.SH"]
        with patch("robust_sample.list_eligible_stocks", return_value=pool) as mocked:
            out = sample_baskets_for_spec(spec, reshuffle=True)
        self.assertTrue(out["full_span"])
        kwargs = mocked.call_args.kwargs
        self.assertTrue(kwargs.get("full_span"))
        self.assertEqual(kwargs.get("year_start"), 2018)
        self.assertEqual(kwargs.get("year_end"), 2026)

    def test_fingerprint_mismatch_redraws(self) -> None:
        pool = ["000001.SZ", "000002.SZ", "600000.SH", "600519.SH"]
        spec = {
            "year_start": 2018,
            "year_end": 2026,
            "n_baskets": 2,
            "basket_size": 2,
            "seed": 1,
            "full_span": False,
        }
        first = sample_baskets_for_spec(spec, reshuffle=True, eligible=pool)
        freeze = {
            "baskets": first["baskets"],
            "sampling_fingerprint": first["sampling_fingerprint"],
            **first["sampling_fingerprint"],
        }
        reused = sample_baskets_for_spec(spec, reshuffle=False, freeze=freeze, eligible=pool)
        self.assertEqual([b["stocks"] for b in reused["baskets"]], [b["stocks"] for b in first["baskets"]])
        changed = dict(spec)
        changed["seed"] = 99
        redrawn = sample_baskets_for_spec(changed, reshuffle=False, freeze=freeze, eligible=pool)
        self.assertNotEqual(
            [b["stocks"] for b in redrawn["baskets"]],
            [b["stocks"] for b in first["baskets"]],
        )

    def test_fill_sampling_full_span(self) -> None:
        self.assertFalse(fill_sampling({})["full_span"])
        self.assertTrue(fill_sampling({"full_span": True})["full_span"])
        fp = sampling_fingerprint(
            {
                "year_start": 2018,
                "year_end": 2026,
                "n_baskets": 3,
                "basket_size": 2,
                "seed": 7,
                "full_span": True,
            }
        )
        self.assertTrue(fp["full_span"])
        self.assertFalse(fingerprints_match(fp, {**fp, "full_span": False}))


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


class TestRobustRunHelpers(unittest.TestCase):
    def test_resolve_pool_workers_via_robust(self) -> None:
        from robust_run import resolve_pool_workers

        self.assertEqual(resolve_pool_workers(1, 40), 1)
        self.assertGreaterEqual(resolve_pool_workers(0, 40), 2)
        self.assertEqual(resolve_pool_workers(8, 3), 3)

    def test_progress_denom_is_n_probe_excluded(self) -> None:
        from grid_run import WalkProgress
        from robust_run import apply_walk_progress, robust_progress_caption

        state = WalkProgress(4)
        state.probe_done = 1
        state.probe_total = 1
        state.finish("a")
        state.bar("b", 50, 100)
        prog = apply_walk_progress({"batches": [{"status": "running"}]}, state)
        self.assertEqual(prog["batch_walk_total"], 4)
        self.assertAlmostEqual(float(prog["batch_walk_done"]), 1.5)
        self.assertEqual(prog["batch_cell_done"], 1)
        cap = robust_progress_caption(prog)
        self.assertIn("walk 1.5/4", cap)
        self.assertIn("已完成", cap)
        self.assertNotIn("格", cap)

    def test_worker_argv_has_workers(self) -> None:
        from robust_run import robust_worker_argv

        cmd = robust_worker_argv(spec_path="x.json", workers=3, reshuffle=True)
        self.assertIn("--workers", cmd)
        self.assertIn("3", cmd)
        self.assertIn("--reshuffle", cmd)
        self.assertTrue(any(str(x).endswith("robust_run.py") for x in cmd))

    def test_stop_does_not_call_dirty(self) -> None:
        from robust_run import stop_robust_worker

        with patch("robust_run.terminate_process_tree") as term:
            with patch("robust_run.wait_until_dead", return_value=True):
                with patch("robust_run.pid_exists", return_value=False):
                    with patch("grid_progress.stop_worker_and_dirty") as dirty:
                        out = stop_robust_worker(9, timeout=0.01)
        self.assertTrue(out["ok"])
        term.assert_called_once_with(9)
        dirty.assert_not_called()

    def test_ui_actions_do_not_run_inline(self) -> None:
        from robust_ui import _begin_pause_request, _begin_resume_request, _begin_run_request

        ss: dict = {}
        _begin_run_request(ss, reshuffle=False)
        self.assertEqual(ss["robust_action"], "run")
        _begin_run_request(ss, reshuffle=True)
        self.assertEqual(ss["robust_action"], "reshuffle")
        _begin_pause_request(ss)
        self.assertEqual(ss["robust_action"], "pause")
        _begin_resume_request(ss)
        self.assertEqual(ss["robust_action"], "resume")


if __name__ == "__main__":
    unittest.main()
