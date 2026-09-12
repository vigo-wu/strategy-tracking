# coding: utf-8
"""grid_run：GridError、8 格以上通过、dry_run 组 job。"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from queue import Empty, Full
from typing import Any
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from grid_run import (  # noqa: E402
    GridError,
    WALK_PROGRESS_QUEUE_MAX,
    WalkProgress,
    _drain_walk_queue,
    _queue_put,
    _run_walks_in_pool,
    assemble_jobs,
    book_jobs,
    book_stock_entries,
    expected_fingerprint,
    grid_book_overrides,
    init_walk_pool,
    job_payload,
    load_book_lock,
    load_config_defaults,
    load_spec,
    parse_fingerprint,
    prune_stale_cell_dirs,
    reset_cell_sample_dirs,
    resolve_pool_workers,
    run_cell,
    run_one_book_walk,
    run_sweep,
    run_walk_job,
    validate_spec,
)
from grid_spec import build_cells  # noqa: E402
from run import run_init_probe  # noqa: E402


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

    def test_validate_warns_over_eight_but_continues(self) -> None:
        spec = {
            "cells": [
                {"id": "c%s" % i, "kind": "other", "overrides": {}}
                for i in range(9)
            ]
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cells = validate_spec(spec)
        self.assertEqual(len(cells), 9)
        self.assertIn("仍继续跑", buf.getvalue())
        self.assertNotIn("确认后再跑", buf.getvalue())

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
        self.assertAlmostEqual(float(defaults["STOP_LOSS"]), 0.10)
        self.assertEqual(int(defaults["D_MA_MID"]), 0)
        self.assertAlmostEqual(float(defaults["MA_TOUCH_TOL"]), 0.015)
        self.assertEqual(int(defaults["TIME_FORCE_BARS"]), 0)
        self.assertAlmostEqual(float(defaults["TRAIL_TIERS"][0][0]), 0.04)

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


class GridInitProbeTest(unittest.TestCase):
    def test_run_init_probe_applies_stop_loss(self) -> None:
        text = run_init_probe({"STOP_LOSS": 0.06})
        got = parse_fingerprint(text)
        self.assertTrue(got["has_stop"])
        self.assertTrue(got["has_tfb"])
        self.assertAlmostEqual(float(got["stop"]), 0.06)
        defaults = load_config_defaults()
        expected = expected_fingerprint(defaults, {"STOP_LOSS": 0.06})
        self.assertAlmostEqual(float(got["stop"]), expected["stop"])
        self.assertEqual(got["time_force_bars"], expected["time_force_bars"])

    def test_run_cell_probe_then_all_walks(self) -> None:
        defaults = {
            "STOP_LOSS": 0.08,
            "TIME_FORCE_BARS": 30,
            "TRAIL_TIERS": (
                (0.03, 0.06, 0.015, None),
                (0.06, 0.10, 0.03, 0.03),
                (0.10, None, 0.04, None),
            ),
            "TRADE_BUDGET": 100000.0,
        }
        cell = {
            "id": "sl06",
            "label": "止损 6%",
            "kind": "tighten",
            "overrides": {"STOP_LOSS": 0.06},
        }
        jobs = [
            _walk(basket="tune", stocks=["AAA111.SH"]),
            _walk(basket="holdout", stocks=["BBB222.SZ"]),
        ]
        probe_text = (
            "HlBand v1 init stop= 0.06 trail_arm= 0.03 "
            "time_force_bars= 30 time_force_min_ret= 0.03"
        )
        ok_row = {"ok": True, "basket_id": "tune", "log_path": "x", "error": ""}
        labels: list[tuple[int, int, str]] = []

        def on_progress(_cid: str, done: int, tot: int, label: str, **_kw: Any) -> None:
            labels.append((done, tot, label))

        with tempfile.TemporaryDirectory() as td:
            cell_dir = Path(td) / "report" / "grid" / "s" / "sl06"
            with patch("grid_run.run_init_probe", return_value=probe_text) as probe:
                with patch("grid_run.run_one_book_walk", return_value=ok_row) as walk:
                    run_cell(cell, jobs, cell_dir, defaults, workers=1, on_progress=on_progress)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(walk.call_count, 2)
            self.assertTrue((cell_dir / "cell_meta.json").is_file())
            self.assertEqual(labels[0], (0, 2, "探针 init"))
            self.assertEqual(labels[1], (0, 2, "回放 tune"))
            self.assertIn((1, 2, "tune"), labels)
            self.assertEqual(labels[-2], (1, 2, "回放 holdout"))
            self.assertEqual(labels[-1], (2, 2, "holdout"))

    def test_run_cell_bar_progress_updates_label(self) -> None:
        defaults = {
            "STOP_LOSS": 0.08,
            "TIME_FORCE_BARS": 30,
            "TRAIL_TIERS": ((0.03, 0.06, 0.015, None),),
            "TRADE_BUDGET": 100000.0,
        }
        cell = {
            "id": "sl06",
            "label": "止损 6%",
            "kind": "tighten",
            "overrides": {"STOP_LOSS": 0.06},
        }
        jobs = [_walk(basket="tune")]
        probe_text = (
            "HlBand v1 init stop= 0.06 trail_arm= 0.03 "
            "time_force_bars= 30 time_force_min_ret= 0.03"
        )
        events: list[tuple[int, int, str, int, int]] = []

        def on_progress(
            _cid: str, done: int, tot: int, label: str, **extra: Any
        ) -> None:
            events.append(
                (
                    done,
                    tot,
                    label,
                    int(extra.get("walk_done") or 0),
                    int(extra.get("walk_total") or 0),
                )
            )

        def fake_walk(payload, on_bar_progress=None):
            if on_bar_progress:
                on_bar_progress(12, 100, "20190506")
            return {
                "ok": True,
                "basket_id": payload.get("basket_id"),
                "log_path": "x",
                "error": "",
            }

        with tempfile.TemporaryDirectory() as td:
            cell_dir = Path(td) / "report" / "grid" / "s" / "sl06"
            with patch("grid_run.run_init_probe", return_value=probe_text):
                with patch("grid_run.run_one_book_walk", side_effect=fake_walk):
                    run_cell(cell, jobs, cell_dir, defaults, workers=1, on_progress=on_progress)
        self.assertTrue(
            any(
                ev[2] == "回放 tune · 2019 12/100" and ev[3] == 12 and ev[4] == 100
                for ev in events
            )
        )

    def test_run_cell_probe_fail_skips_walks(self) -> None:
        defaults = {
            "STOP_LOSS": 0.08,
            "TIME_FORCE_BARS": 30,
            "TRAIL_TIERS": ((0.03, 0.06, 0.015, None),),
            "TRADE_BUDGET": 100000.0,
        }
        cell = {
            "id": "sl06",
            "label": "止损 6%",
            "kind": "tighten",
            "overrides": {"STOP_LOSS": 0.06},
        }
        jobs = [_walk()]
        with tempfile.TemporaryDirectory() as td:
            cell_dir = Path(td) / "report" / "grid" / "s" / "sl06"
            with patch("grid_run.run_init_probe", side_effect=RuntimeError("boom")):
                with patch("grid_run.run_one_book_walk") as walk:
                    with self.assertRaises(GridError) as ctx:
                        run_cell(cell, jobs, cell_dir, defaults, workers=1)
            self.assertIn("探针失败", str(ctx.exception))
            walk.assert_not_called()


class _ListQ:
    def __init__(self, items):
        self._items = list(items)

    def get_nowait(self):
        if not self._items:
            raise Empty
        return self._items.pop(0)


class WalkProgressTest(unittest.TestCase):
    def test_frac_completed_plus_two_inflight(self) -> None:
        st = WalkProgress(8)
        st.finish("a")
        st.finish("b")
        st.finish("c")
        st.bar("x", 50, 100)
        st.bar("y", 1, 2)
        self.assertAlmostEqual(st.frac(), 0.5)
        self.assertEqual(st.completed, 3)
        self.assertEqual(st.n_running, 2)

    def test_finish_pops_inflight_before_increment(self) -> None:
        st = WalkProgress(2)
        st.bar("j", 100, 100)
        self.assertAlmostEqual(st.frac(), 0.5)
        st.finish("j")
        self.assertEqual(st.completed, 1)
        self.assertNotIn("j", st.inflight)
        self.assertAlmostEqual(st.frac(), 0.5)
        st.finish("j")
        self.assertEqual(st.completed, 1)

    def test_late_bar_after_pop_ignored(self) -> None:
        st = WalkProgress(2)
        st.finish("j")
        before = st.frac()
        st.bar("j", 100, 100)
        st.start("j")
        self.assertAlmostEqual(st.frac(), before)
        self.assertNotIn("j", st.inflight)

    def test_drain_bar_then_finish_leaves_inflight(self) -> None:
        st = WalkProgress(8)
        jk = "c1|book|tune"
        q = _ListQ([("bar", "c1", jk, 50, 100, "回放 tune")])
        cid, got_jk, lab = _drain_walk_queue(q, st)
        self.assertEqual(cid, "c1")
        self.assertEqual(got_jk, jk)
        self.assertIn("tune", lab)
        extra = st.extras(phase="walk", job_key=jk)
        self.assertAlmostEqual(extra["inflight_frac"], 0.5)
        self.assertEqual(extra["n_running"], 1)
        self.assertEqual(extra["n_walks"], 8)
        st.finish(jk)
        self.assertEqual(st.completed, 1)
        self.assertNotIn(jk, st.inflight)
        extra2 = st.extras(phase="walk", job_key=jk)
        self.assertEqual(extra2["inflight_frac"], 0.0)
        self.assertEqual(extra2["completed"], 1)


_POOL_DEFAULTS = {
    "STOP_LOSS": 0.08,
    "TIME_FORCE_BARS": 30,
    "TRAIL_TIERS": ((0.03, 0.06, 0.015, None),),
    "TRADE_BUDGET": 100000.0,
}
_POOL_PROBE = (
    "HlBand v1 init stop= 0.08 trail_arm= 0.03 "
    "time_force_bars= 30 time_force_min_ret= 0.03"
)


class _FakeFuture:
    def __init__(self, row=None, exc=None):
        self._row = row
        self._exc = exc
        self.cancelled = False

    def result(self, timeout=None):
        if self._exc:
            raise self._exc
        return self._row

    def cancel(self):
        self.cancelled = True
        return True


class _FakePool:
    last = None

    def __init__(self, max_workers=1, mp_context=None, initializer=None, initargs=()):
        self.max_workers = max_workers
        self.initializer = initializer
        self.initargs = initargs
        self.submitted: list = []
        self.fail_cell = None
        self.raise_on = -1
        _FakePool.last = self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, payload):
        idx = len(self.submitted)
        if "progress_queue" in payload:
            raise AssertionError("payload must not contain progress_queue")
        if self.raise_on == idx:
            fut = _FakeFuture(exc=RuntimeError("broken"))
        elif self.fail_cell and payload.get("cell_id") == self.fail_cell:
            fut = _FakeFuture(
                row={
                    "ok": False,
                    "error": "boom",
                    "cell_id": payload.get("cell_id"),
                    "basket_id": payload.get("basket_id"),
                }
            )
        else:
            fut = _FakeFuture(
                row={
                    "ok": True,
                    "cell_id": payload.get("cell_id"),
                    "basket_id": payload.get("basket_id"),
                }
            )
        self.submitted.append((fn, payload, fut))
        return fut


def _fake_wait(fs, timeout=None, return_when=None):
    pending = set(fs)
    if not pending:
        return set(), set()
    pool = _FakePool.last
    if pool is not None:
        for _fn, _payload, fut in pool.submitted:
            if fut in pending:
                return {fut}, pending - {fut}
    one = next(iter(pending))
    return {one}, pending - {one}


class _FakeSummarize:
    def __init__(self):
        self.called = False

    def summarize_sweep(self, dest, gate=None, cell_ids=None):
        self.called = True
        return {
            "summary_path": str(Path(dest) / "summary.json"),
            "recommend": {"id": "base", "reason": "ok"},
        }


def _n_cell_spec(n: int, sweep: str = "pool_unit") -> dict:
    cells = []
    for i in range(n):
        cid = "base" if i == 0 else "c%s" % i
        cells.append(
            {
                "id": cid,
                "label": cid,
                "kind": "base" if i == 0 else "other",
                "overrides": {},
                "is_current": i == 0,
            }
        )
    return {
        "theme": "hongli_band",
        "sweep": sweep,
        "compare_div": "front_ratio",
        "cells": cells,
    }


class GridWalkPoolTest(unittest.TestCase):
    def test_resolve_pool_workers_auto_and_cli_24(self) -> None:
        with patch("grid_run.os.cpu_count", return_value=4):
            self.assertEqual(resolve_pool_workers(0, 9), 4)
            self.assertEqual(resolve_pool_workers(1, 9), 1)
            self.assertEqual(resolve_pool_workers(24, 32), 24)
        with patch("grid_run.os.cpu_count", return_value=32):
            self.assertEqual(resolve_pool_workers(0, 9), 9)
        self.assertEqual(resolve_pool_workers(0, 1), 1)

    def test_workers_1_serial_run_cell(self) -> None:
        spec = _n_cell_spec(4, "serial_unit")
        book = [_walk(start="20200101", end="20201231")]
        with tempfile.TemporaryDirectory() as td:
            sweep_dir = Path(td) / "report" / "grid" / "serial_unit"
            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run.run_cell") as rc:
                        with patch("grid_run._load_summarize", return_value=_FakeSummarize()):
                            with patch("grid_run.ProcessPoolExecutor") as pool_cls:
                                run_sweep(spec, workers=1, sweep_dir=sweep_dir)
            self.assertEqual(rc.call_count, 4)
            for call in rc.call_args_list:
                args = call.args
                kwargs = call.kwargs
                w = kwargs.get("workers", args[4] if len(args) > 4 else None)
                self.assertEqual(w, 1)
            pool_cls.assert_not_called()

    def test_workers_4_flat_pool_eight_walks(self) -> None:
        spec = _n_cell_spec(4, "flat_unit")
        jobs = [
            _walk(basket="tune", stocks=["AAA111.SH"]),
            _walk(basket="holdout", stocks=["BBB222.SZ"]),
        ]
        _FakePool.last = None
        fake_sum = _FakeSummarize()
        with tempfile.TemporaryDirectory() as td:
            sweep_dir = Path(td) / "report" / "grid" / "flat_unit"
            with patch("grid_run.assemble_jobs", return_value=(jobs, jobs)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run.run_init_probe", return_value=_POOL_PROBE):
                        with patch("grid_run._load_summarize", return_value=fake_sum):
                            with patch("grid_run.ProcessPoolExecutor", _FakePool):
                                with patch("grid_run.wait", _fake_wait):
                                    run_sweep(spec, workers=4, sweep_dir=sweep_dir)
        pool = _FakePool.last
        self.assertIsNotNone(pool)
        self.assertEqual(pool.max_workers, 4)
        self.assertEqual(len(pool.submitted), 8)
        self.assertEqual(pool.submitted[0][0], run_walk_job)
        for _fn, payload, _fut in pool.submitted:
            self.assertNotIn("progress_queue", payload)
            self.assertIn("cell_id", payload)
            self.assertTrue(payload.get("out_dir"))
        self.assertTrue(fake_sum.called)

    def test_pool_drain_bar_then_future_complete(self) -> None:
        payloads = [
            {"cell_id": "c1", "sample": "book", "basket_id": "tune", "out_dir": "x"},
            {"cell_id": "c1", "sample": "book", "basket_id": "holdout", "out_dir": "y"},
        ]
        state = WalkProgress(2)
        jk_hold = "c1|book|holdout"
        events: list[dict[str, Any]] = []

        def on_progress(_cid: str, _done: int, _tot: int, _label: str, **extra: Any) -> None:
            events.append(dict(extra))

        def fake_drain(_q, st: WalkProgress):
            st.bar(jk_hold, 40, 80)
            return ("c1", jk_hold, "回放 holdout · 2019 40/80")

        _FakePool.last = None
        with patch("grid_run.ProcessPoolExecutor", _FakePool):
            with patch("grid_run.wait", _fake_wait):
                with patch("grid_run._drain_walk_queue", fake_drain):
                    got = _run_walks_in_pool(
                        payloads, 2, 2, state, on_progress=on_progress
                    )
        self.assertEqual(got, {"c1"})
        self.assertTrue(
            any(abs(float(e.get("inflight_frac") or 0) - 0.5) < 1e-9 for e in events)
        )
        self.assertTrue(all(e.get("n_walks") == 2 for e in events))
        self.assertEqual(state.completed, 2)
        self.assertNotIn(jk_hold, state.inflight)
        last = events[-1]
        self.assertEqual(last.get("completed"), 2)
        self.assertEqual(float(last.get("inflight_frac") or 0), 0.0)

    def test_walk_ok_false_cancels_and_skips_summarize(self) -> None:
        spec = _n_cell_spec(4, "fail_unit")
        jobs = [
            _walk(basket="tune"),
            _walk(basket="holdout"),
        ]
        fake_sum = _FakeSummarize()

        def _pool(*a, **k):
            p = _FakePool(*a, **k)
            p.fail_cell = "c1"
            return p

        with tempfile.TemporaryDirectory() as td:
            sweep_dir = Path(td) / "report" / "grid" / "fail_unit"
            with patch("grid_run.assemble_jobs", return_value=(jobs, jobs)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run.run_init_probe", return_value=_POOL_PROBE):
                        with patch("grid_run._load_summarize", return_value=fake_sum):
                            with patch("grid_run.ProcessPoolExecutor", _pool):
                                with patch("grid_run.wait", _fake_wait):
                                    with patch("grid_run.run_cell") as rc:
                                        with self.assertRaises(GridError) as ctx:
                                            run_sweep(spec, workers=4, sweep_dir=sweep_dir)
        self.assertIn("walk 失败", str(ctx.exception))
        self.assertFalse(fake_sum.called)
        rc.assert_not_called()
        cancelled = [fut for _fn, _p, fut in _FakePool.last.submitted if fut.cancelled]
        self.assertGreaterEqual(len(cancelled), 1)

    def test_pool_runtimeerror_fallback_skips_done_cells(self) -> None:
        spec = _n_cell_spec(2, "fb_unit")
        jobs = [
            _walk(basket="tune"),
            _walk(basket="holdout"),
        ]

        def _pool(*a, **k):
            p = _FakePool(*a, **k)
            p.raise_on = 2
            return p

        fake_sum = _FakeSummarize()
        with tempfile.TemporaryDirectory() as td:
            sweep_dir = Path(td) / "report" / "grid" / "fb_unit"
            with patch("grid_run.assemble_jobs", return_value=(jobs, jobs)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run.run_init_probe", return_value=_POOL_PROBE):
                        with patch("grid_run._load_summarize", return_value=fake_sum):
                            with patch("grid_run.ProcessPoolExecutor", _pool):
                                with patch("grid_run.wait", _fake_wait):
                                    with patch("grid_run.run_cell") as rc:
                                        run_sweep(spec, workers=4, sweep_dir=sweep_dir)
        self.assertTrue(fake_sum.called)
        ids = [call.args[0]["id"] for call in rc.call_args_list]
        self.assertEqual(ids, ["c1"])

    def test_queue_inherited_spawn_from_thread(self) -> None:
        import threading

        from concurrent.futures import ProcessPoolExecutor
        from multiprocessing import get_context

        from grid_run import HERE

        err: list[BaseException] = []
        out: list[dict] = []

        def _in_thread() -> None:
            try:
                ctx = get_context("spawn")
                q = ctx.Queue()
                with ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=ctx,
                    initializer=init_walk_pool,
                    initargs=(str(HERE), q),
                ) as ex:
                    fut = ex.submit(run_walk_job, {"cell_id": "x"})
                    out.append(fut.result(timeout=60))
            except BaseException as e:
                err.append(e)

        t = threading.Thread(target=_in_thread, daemon=False)
        t.start()
        t.join(timeout=90)
        self.assertFalse(t.is_alive())
        self.assertEqual(err, [], msg=str(err))
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].get("ok"))
        self.assertIn("无 job", str(out[0].get("error") or ""))
        self.assertNotIn("Queue objects should only be shared", str(out[0]))


class QueuePutAndCacheClearTest(unittest.TestCase):
    def test_walk_progress_queue_max_is_256(self) -> None:
        self.assertEqual(WALK_PROGRESS_QUEUE_MAX, 256)

    def test_queue_put_full_is_dropped(self) -> None:
        import grid_run as gr

        q = MagicMock()
        q.put_nowait.side_effect = Full
        q.put = MagicMock(side_effect=AssertionError("must not block put"))
        prev = gr._WALK_PROGRESS_Q
        gr._WALK_PROGRESS_Q = q
        try:
            _queue_put("bar", "c1", "c1|book|tune", 1, 10, "lab")
        finally:
            gr._WALK_PROGRESS_Q = prev
        q.put_nowait.assert_called_once()
        q.put.assert_not_called()

    def test_run_walks_pool_creates_bounded_queue(self) -> None:
        payloads = [
            {"cell_id": "c1", "sample": "book", "basket_id": "tune", "out_dir": "x"},
        ]
        state = WalkProgress(1)
        recorded: list[int] = []

        class _Ctx:
            def Queue(self, maxsize=0):
                recorded.append(int(maxsize))
                return _ListQ([])

        with patch("grid_run.get_context", return_value=_Ctx()):
            with patch("grid_run.ProcessPoolExecutor", _FakePool):
                with patch("grid_run.wait", _fake_wait):
                    _run_walks_in_pool(payloads, 1, 1, state)
        self.assertEqual(recorded, [WALK_PROGRESS_QUEUE_MAX])

    def test_run_one_book_walk_clears_cache_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "basket_id": "tune",
                "out_dir": td,
                "log_name": "t.txt",
                "book_stocks": {"600000.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"}},
                "start": "20200101",
                "end": "20200131",
                "sample": "book",
            }
            with patch(
                "grid_run.run_book_backtest",
                return_value=(Path(td) / "t.txt", {"n_bars": 1}),
            ):
                with patch("grid_run.clear_market_store_cache") as clear:
                    with patch("grid_run.trades_csv_path", return_value=str(Path(td) / "t.csv")):
                        row = run_one_book_walk(payload)
            self.assertTrue(row.get("ok"))
            clear.assert_called_once()

    def test_run_one_book_walk_clears_cache_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "basket_id": "tune",
                "out_dir": td,
                "log_name": "t.txt",
                "book_stocks": {},
                "start": "20200101",
                "end": "20200131",
                "sample": "book",
            }
            with patch("grid_run.run_book_backtest", side_effect=RuntimeError("boom")):
                with patch("grid_run.clear_market_store_cache") as clear:
                    row = run_one_book_walk(payload)
            self.assertFalse(row.get("ok"))
            self.assertIn("boom", str(row.get("error") or ""))
            clear.assert_called_once()


if __name__ == "__main__":
    unittest.main()
