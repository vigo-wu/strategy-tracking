# coding: utf-8
"""grid_run：GridError、8 格以上通过、dry_run 组 job。"""
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

from grid_run import (  # noqa: E402
    assemble_jobs,
    book_jobs,
    load_config_defaults,
    prune_stale_cell_dirs,
    run_sweep,
    validate_spec,
)
from grid_spec import build_cells  # noqa: E402


def _nine_cell_spec() -> dict:
    defaults = {
        "STOP_LOSS": 0.08,
        "TIME_FORCE_BARS": 30,
        "TIME_FORCE_MIN_RET": 0.03,
        "TRAIL_TIERS": ((0.03, 0.06, 0.015, None), (0.06, 0.10, 0.03, 0.03), (0.10, None, 0.04, None)),
    }
    cells = build_cells({"STOP_LOSS": [0.05, 0.06, 0.07, 0.09, 0.10, 0.11, 0.12, 0.13]}, defaults)
    return {"theme": "hongli_band", "sweep": "nine_cells", "compare_div": "front_ratio", "cells": cells}


class GridRunApiTest(unittest.TestCase):
    def test_validate_nine_cells_ok(self) -> None:
        spec = _nine_cell_spec()
        self.assertGreaterEqual(len(spec["cells"]), 8)
        cells = validate_spec(spec)
        self.assertEqual(len(cells), len(spec["cells"]))
        self.assertEqual(len(cells), 8)

    def test_missing_base_ok(self) -> None:
        spec = {
            "cells": [
                {"id": "sl06", "kind": "tighten", "overrides": {"STOP_LOSS": 0.06}},
            ]
        }
        cells = validate_spec(spec)
        self.assertEqual(cells[0]["id"], "sl06")
        self.assertFalse(cells[0]["is_current"])

    def test_dry_run_job_counts(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "dry_unit",
            "compare_div": "front_ratio",
            "cells": [
                {"id": "base", "label": "现行", "kind": "base", "overrides": {}},
                {"id": "sl06", "label": "止损 6%", "kind": "tighten", "overrides": {"STOP_LOSS": 0.06}},
            ],
        }
        book = [
            {
                "sample": "book",
                "stock": "600350.SH",
                "year": "2020",
                "ma": "EMA",
                "div": "front_ratio",
                "csv": Path("x.csv"),
                "start": "20200101",
                "end": "20201231",
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            sweep_dir = Path(td) / "report" / "grid" / "dry_unit"
            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                info = run_sweep(spec, dry_run=True, sweep_dir=sweep_dir)
            self.assertTrue(info["dry_run"])
            self.assertEqual(info["n_cells"], 2)
            self.assertEqual(info["n_jobs"], 1)
            self.assertEqual(info["n_book"], 1)
            self.assertNotIn("n_winner", info)
            self.assertTrue((sweep_dir / "spec.json").is_file())
            freeze = json.loads((sweep_dir / "freeze.json").read_text(encoding="utf-8"))
            self.assertEqual(freeze["n_book"], 1)
            self.assertNotIn("winner", freeze)
            self.assertEqual(freeze["year_start"], 2018)
            self.assertEqual(freeze["tune_end"], 2022)


    def test_assemble_jobs_book_and_sma_ema(self) -> None:
        spec = {"compare_div": "front_ratio", "cells": [{"id": "base", "overrides": {}}]}
        fake_book = [
            {
                "sample": "book",
                "stock": "A",
                "year": "2020",
                "ma": "EMA",
                "div": "front_ratio",
                "csv": Path("a.csv"),
                "start": "20200101",
                "end": "20201231",
            }
        ]
        with patch("grid_run.book_jobs", return_value=fake_book):
            book, jobs = assemble_jobs(spec)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(book, fake_book)
            _, many = assemble_jobs(spec, include_sma_ema=True)
        self.assertEqual(len(many), 3)
        self.assertEqual({j["sample"] for j in many}, {"book", "sma", "ema"})

    def test_book_jobs_respects_spec_years(self) -> None:
        csv_p = Path("fake.csv")
        spec = {"year_start": 2022, "year_end": 2023}
        with patch("grid_run.load_book_lock", return_value=[("600938.SH", "EMA", "front_ratio")]):
            with patch("grid_run.csv_for", return_value=csv_p):
                with patch("grid_run._csv_span", return_value=("20220421", "20260904")):
                    jobs = book_jobs(spec)
        years = {j["year"] for j in jobs}
        self.assertEqual(years, {"2022", "2023"})
        self.assertTrue(all(j["sample"] == "book" for j in jobs))

    def test_book_jobs_skips_years_without_bars(self) -> None:
        csv_p = Path("fake.csv")
        with patch("grid_run.load_book_lock", return_value=[("600938.SH", "EMA", "front_ratio")]):
            with patch("grid_run.csv_for", return_value=csv_p):
                with patch("grid_run._csv_span", return_value=("20220421", "20260904")):
                    jobs = book_jobs()
        years = {j["year"] for j in jobs}
        self.assertNotIn("2018", years)
        self.assertNotIn("2021", years)
        self.assertIn("2022", years)
        self.assertTrue(all(j["stock"] == "600938.SH" for j in jobs))

    def test_dry_run_random_from_csv_freeze_lists(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "space_unit",
            "compare_div": "front_ratio",
            "year_start": 2020,
            "year_end": 2021,
            "tune_start": 2020,
            "tune_end": 2020,
            "check_start": 2021,
            "check_end": 2021,
            "asset_split": {
                "mode": "random_from_csv",
                "n_tune": 2,
                "n_holdout": 1,
                "seed": 3,
                "ma_type": "EMA",
                "dividend_type": "front_ratio",
            },
            "cells": [
                {"id": "base", "label": "现行", "kind": "base", "overrides": {}},
            ],
        }
        pool = ["AAA111.SH", "BBB222.SZ", "CCC333.SH", "DDD444.SZ"]
        book = [
            {
                "sample": "book",
                "stock": "AAA111.SH",
                "year": "2020",
                "ma": "EMA",
                "div": "front_ratio",
                "csv": Path("x.csv"),
                "start": "20200101",
                "end": "20201231",
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            sweep_dir = Path(td) / "report" / "grid" / "space_unit"
            with patch("grid_run.draw_asset_split") as draw:
                drawn = {
                    "mode": "random_from_csv",
                    "n_tune": 2,
                    "n_holdout": 1,
                    "seed": 3,
                    "tune_stocks": ["AAA111.SH", "BBB222.SZ"],
                    "holdout_stocks": ["CCC333.SH"],
                    "eligible_n": 4,
                    "universe_dir": "tools/csv/none",
                    "ma_type": "EMA",
                    "dividend_type": "front_ratio",
                    "exclude": [],
                }
                draw.return_value = drawn
                with patch("grid_run.assemble_jobs", return_value=(book, book)):
                    info = run_sweep(spec, dry_run=True, sweep_dir=sweep_dir, reshuffle=True)
            freeze = json.loads((sweep_dir / "freeze.json").read_text(encoding="utf-8"))
            self.assertEqual(freeze["tune_stocks"], ["AAA111.SH", "BBB222.SZ"])
            self.assertEqual(freeze["holdout_stocks"], ["CCC333.SH"])
            self.assertEqual(info["asset_split"]["mode"], "random_from_csv")
            spec_saved = json.loads((sweep_dir / "spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec_saved["asset_split"]["tune_stocks"], freeze["tune_stocks"])

    def test_book_jobs_uses_asset_split_locks(self) -> None:
        csv_p = Path("fake.csv")
        spec = {
            "year_start": 2022,
            "year_end": 2022,
            "asset_split": {
                "mode": "random_from_csv",
                "tune_stocks": ["600001.SH"],
                "holdout_stocks": ["600002.SH"],
                "ma_type": "EMA",
                "dividend_type": "front_ratio",
                "n_tune": 1,
                "n_holdout": 1,
                "seed": 1,
            },
        }
        with patch("grid_run.csv_for", return_value=csv_p):
            with patch("grid_run._csv_span", return_value=("20220101", "20221231")):
                jobs = book_jobs(spec)
        stocks = {j["stock"] for j in jobs}
        self.assertEqual(stocks, {"600001.SH", "600002.SH"})

    def test_prune_stale_cell_dirs_keeps_current_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "sweep"
            dest.mkdir(parents=True)
            (dest / "spec.json").write_text("{}", encoding="utf-8")
            for cid in ("base", "vpn15", "vpn13"):
                cell = dest / cid
                cell.mkdir()
                (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            removed = prune_stale_cell_dirs(dest, ["base", "vpn15"])
            self.assertEqual(set(removed), {"vpn13"})
            self.assertTrue((dest / "base").is_dir())
            self.assertTrue((dest / "vpn15").is_dir())
            self.assertFalse((dest / "vpn13").exists())
            self.assertTrue((dest / "spec.json").is_file())

    def test_dry_run_does_not_prune_stale_cells(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "dry_prune",
            "compare_div": "front_ratio",
            "cells": [
                {"id": "base", "label": "现行", "kind": "base", "overrides": {}},
            ],
        }
        book = [
            {
                "sample": "book",
                "stock": "600350.SH",
                "year": "2020",
                "ma": "EMA",
                "div": "front_ratio",
                "csv": Path("x.csv"),
                "start": "20200101",
                "end": "20201231",
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            sweep_dir = Path(td) / "report" / "grid" / "dry_prune"
            sweep_dir.mkdir(parents=True)
            leftover = sweep_dir / "vpn13"
            leftover.mkdir()
            (leftover / "cell_meta.json").write_text("{}", encoding="utf-8")
            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                run_sweep(spec, dry_run=True, sweep_dir=sweep_dir)
            self.assertTrue(leftover.is_dir())

    def test_load_config_defaults_covers_catalog(self) -> None:
        defaults = load_config_defaults()
        self.assertIn("STOP_LOSS", defaults)
        self.assertIn("TRAIL_TIERS", defaults)
        self.assertIn("CHASE_MAX_PCT", defaults)
        self.assertIn("W_BIAS_HARD", defaults)
        self.assertIn("MA_TOUCH_TOL", defaults)
        self.assertIn("VOL_PULLBACK_CONFIRM_DAYS", defaults)
        self.assertEqual(int(defaults["VOL_PULLBACK_CONFIRM_DAYS"]), 2)
        self.assertNotIn("STATE_FILE", defaults)
        self.assertAlmostEqual(float(defaults["CHASE_MAX_PCT"]), 0.05)
        self.assertAlmostEqual(float(defaults["STOP_LOSS"]), 0.08)


if __name__ == "__main__":
    unittest.main()
