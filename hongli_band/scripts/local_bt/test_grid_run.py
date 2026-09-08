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
    GridError,
    assemble_jobs,
    book_jobs,
    book_stock_entries,
    expected_fingerprint,
    grid_book_overrides,
    job_payload,
    load_book_lock,
    load_config_defaults,
    load_spec,
    parse_fingerprint,
    prune_stale_cell_dirs,
    reset_cell_sample_dirs,
    run_sweep,
    validate_spec,
)
from grid_spec import build_cells  # noqa: E402


def _walk(
    *,
    sample: str = "book",
    basket: str = "book",
    stocks: list[str] | None = None,
    start: str = "20180101",
    end: str = "20261231",
    ma: str = "EMA",
) -> dict:
    codes = stocks or ["600350.SH"]
    book = {s: {"ma_type": ma, "dividend_type": "front_ratio"} for s in codes}
    return {
        "sample": sample,
        "basket": basket,
        "book_stocks": book,
        "start": start,
        "end": end,
        "div": "front_ratio",
        "ma": ma,
        "n_stocks": len(book),
        "stocks": sorted(book.keys()),
    }


def _nine_cell_spec() -> dict:
    defaults = {
        "STOP_LOSS": 0.08,
        "TIME_FORCE_BARS": 30,
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
        book = [_walk(start="20200101", end="20201231")]
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
            self.assertEqual(freeze["book"][0]["basket"], "book")
            self.assertNotIn("year", freeze["book"][0])
            self.assertEqual(freeze["book"][0]["start"], "20200101")


    def test_assemble_jobs_book_and_sma_ema(self) -> None:
        spec = {"compare_div": "front_ratio", "cells": [{"id": "base", "overrides": {}}]}
        fake_book = [_walk()]
        with patch("grid_run.book_jobs", return_value=fake_book):
            book, jobs = assemble_jobs(spec)
            self.assertEqual(len(jobs), 1)
            self.assertEqual(book, fake_book)
            _, many = assemble_jobs(spec, include_sma_ema=True)
        self.assertEqual(len(many), 3)
        self.assertEqual({j["sample"] for j in many}, {"book", "sma", "ema"})
        sma = next(j for j in many if j["sample"] == "sma")
        self.assertEqual(sma["book_stocks"]["600350.SH"]["ma_type"], "SMA")
        self.assertEqual(sma["basket"], "book")

    def test_assemble_jobs_space_sma_ema_max_six(self) -> None:
        spec = {"compare_div": "front_ratio", "cells": [{"id": "base", "overrides": {}}]}
        fake = [
            _walk(basket="tune", stocks=["AAA111.SH"]),
            _walk(basket="holdout", stocks=["BBB222.SZ"]),
        ]
        with patch("grid_run.book_jobs", return_value=fake):
            _, many = assemble_jobs(spec, include_sma_ema=True)
        self.assertEqual(len(many), 6)
        self.assertEqual(
            {(j["sample"], j["basket"]) for j in many},
            {
                ("book", "tune"),
                ("book", "holdout"),
                ("sma", "tune"),
                ("sma", "holdout"),
                ("ema", "tune"),
                ("ema", "holdout"),
            },
        )

    def test_book_jobs_one_walk_not_stock_year(self) -> None:
        csv_p = Path("fake.csv")
        spec = {"year_start": 2022, "year_end": 2023}
        with patch("grid_run.load_book_lock", return_value=[("600938.SH", "EMA", "front_ratio")]):
            with patch("grid_run.csv_for", return_value=csv_p):
                with patch("grid_run._csv_span", return_value=("20220421", "20260904")):
                    jobs = book_jobs(spec)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["start"], "20220101")
        self.assertEqual(jobs[0]["end"], "20231231")
        self.assertEqual(jobs[0]["basket"], "book")
        self.assertNotIn("year", jobs[0])
        self.assertEqual(jobs[0]["stocks"], ["600938.SH"])

    def test_book_jobs_skips_stocks_without_overlap(self) -> None:
        csv_p = Path("fake.csv")
        with patch("grid_run.load_book_lock", return_value=[("600938.SH", "EMA", "front_ratio")]):
            with patch("grid_run.csv_for", return_value=csv_p):
                with patch("grid_run._csv_span", return_value=("20100101", "20101231")):
                    with self.assertRaises(GridError) as ctx:
                        book_jobs({"year_start": 2018, "year_end": 2026})
        self.assertIn("无可用 CSV", str(ctx.exception))

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
        book = [_walk(stocks=["AAA111.SH"], start="20200101", end="20211231")]
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
        self.assertEqual(len(jobs), 2)
        self.assertEqual([j["basket"] for j in jobs], ["tune", "holdout"])
        self.assertEqual(jobs[0]["stocks"], ["600001.SH"])
        self.assertEqual(jobs[1]["stocks"], ["600002.SH"])
        self.assertTrue(all("year" not in j for j in jobs))
        self.assertEqual(jobs[0]["start"], "20220101")
        self.assertEqual(jobs[0]["end"], "20221231")

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

    def test_reset_cell_sample_dirs_drops_legacy_logs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cell = Path(td) / "base"
            book = cell / "book" / "front_ratio"
            book.mkdir(parents=True)
            leftover = book / "local_bt_600000_SH_2018_EMA.txt"
            leftover.write_text("old\n", encoding="utf-8")
            (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            reset_cell_sample_dirs(cell)
            self.assertFalse(leftover.exists())
            self.assertFalse((cell / "book").exists())
            self.assertTrue((cell / "cell_meta.json").is_file())

    def test_dry_run_does_not_prune_stale_cells(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "dry_prune",
            "compare_div": "front_ratio",
            "cells": [
                {"id": "base", "label": "现行", "kind": "base", "overrides": {}},
            ],
        }
        book = [_walk(start="20200101", end="20201231")]
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

    def test_parse_fingerprint_trail_tiers_distinguishes_giveback(self) -> None:
        current = [
            [0.03, 0.06, 0.015, None],
            [0.06, 0.10, 0.03, 0.03],
            [0.10, None, 0.04, None],
        ]
        other = [
            [0.03, 0.06, 0.02, None],
            [0.06, 0.10, 0.03, 0.03],
            [0.10, None, 0.04, None],
        ]
        compact_cur = json.dumps(current, separators=(",", ":"))
        compact_other = json.dumps(other, separators=(",", ":"))
        text = (
            "HlBand v1 init stop= 0.08 trail_arm= 0.03 trail_tiers= %s "
            "time_force_bars= 30 time_force_min_ret= 0.03"
            % compact_cur
        )
        got = parse_fingerprint(text)
        self.assertTrue(got["has_trail_tiers"])
        self.assertAlmostEqual(got["trail_arm"], 0.03)
        self.assertAlmostEqual(got["trail_tiers"][0][2], 0.015)
        expected = expected_fingerprint(
            {
                "STOP_LOSS": 0.08,
                "TIME_FORCE_BARS": 30,
                "TRAIL_TIERS": current,
            },
            {"TRAIL_TIERS": current},
        )
        self.assertEqual(expected["trail_tiers"][0][2], 0.015)
        self.assertNotEqual(compact_cur, compact_other)
        other_text = text.replace(compact_cur, compact_other)
        other_got = parse_fingerprint(other_text)
        self.assertAlmostEqual(other_got["trail_arm"], 0.03)
        self.assertAlmostEqual(other_got["trail_tiers"][0][2], 0.02)
        self.assertNotEqual(got["trail_tiers"][0][2], other_got["trail_tiers"][0][2])

    def test_grid_book_overrides_wallet_follows_trade_budget(self) -> None:
        ov = grid_book_overrides({"STOP_LOSS": 0.06, "TRADE_BUDGET": 200000})
        self.assertTrue(ov["compound_backtest"])
        self.assertEqual(ov["TRADE_BUDGET"], 200000.0)
        self.assertEqual(ov["wallet_cash"], 200000.0)
        ov2 = grid_book_overrides({}, {"TRADE_BUDGET": 150000.0})
        self.assertEqual(ov2["wallet_cash"], 150000.0)

    def test_job_payload_splits_tune_holdout_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cell = Path(td) / "report" / "grid" / "s" / "base"
            job = _walk(basket="tune", stocks=["600001.SH"], start="20220101", end="20221231")
            payload = job_payload(job, cell, {"STOP_LOSS": 0.06, "TRADE_BUDGET": 100000})
            out = Path(payload["out_dir"])
            self.assertIn("tune", out.parts)
            self.assertTrue(payload["log_name"].startswith("tune_"))
            self.assertIn("local_bt_book_fixed", payload["log_name"])
            self.assertTrue(payload["overrides"]["compound_backtest"])
            hold = _walk(basket="holdout", stocks=["600002.SH"], start="20220101", end="20221231")
            p2 = job_payload(hold, cell, {})
            self.assertIn("holdout", Path(p2["out_dir"]).parts)
            self.assertTrue(p2["log_name"].startswith("holdout_"))
            self.assertNotEqual(payload["out_dir"], p2["out_dir"])

    def test_book_stock_entries_accepts_set(self) -> None:
        codes = {"600938.SH", "601615.SH"}
        got = {str(k).upper() for k, _v in book_stock_entries(codes)}
        self.assertEqual(got, codes)
        frozen = book_stock_entries(frozenset(codes))
        self.assertEqual({str(k).upper() for k, _v in frozen}, codes)
        items = book_stock_entries({"600938.SH": {"ma_type": "SMA"}})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0][0], "600938.SH")
        self.assertEqual(items[0][1].get("ma_type"), "SMA")
        listed = book_stock_entries(["600350.SH", "601857.SH"])
        self.assertEqual([str(k) for k, _v in listed], ["600350.SH", "601857.SH"])
        self.assertEqual(book_stock_entries(None), [])
        self.assertEqual(book_stock_entries("600938.SH"), [])

    def test_load_book_lock_real_config_set(self) -> None:
        locks = load_book_lock()
        codes = {row[0] for row in locks}
        self.assertIn("600938.SH", codes)
        self.assertGreaterEqual(len(locks), 1)
        for _stock, ma, div in locks:
            self.assertEqual(ma, "EMA")
            self.assertEqual(div, "front_ratio")

    def test_load_book_lock_empty_set_raises(self) -> None:
        class EmptyBook:
            BOOK_STOCKS = set()
            MA_TYPE = "EMA"
            DIVIDEND_TYPE = "front_ratio"

        with patch("grid_run._load_hlband_config", return_value=EmptyBook):
            with self.assertRaises(GridError) as ctx:
                load_book_lock()
        self.assertIn("没有有效标的", str(ctx.exception))

    def test_load_spec_rejects_min_ret(self) -> None:
        spec = {
            "cells": [
                {"id": "tfm0", "kind": "other", "overrides": {"TIME_FORCE_MIN_RET": 0.0}},
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaises(GridError) as ctx:
                load_spec(path)
        self.assertIn("TIME_FORCE_MIN_RET", str(ctx.exception))
        with self.assertRaises(GridError):
            validate_spec(spec)


if __name__ == "__main__":
    unittest.main()
