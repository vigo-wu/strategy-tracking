# coding: utf-8
"""网格 summarize：book 选参、调参/验收年切分。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SKILL = REPO / ".cursor" / "skills" / "qmt-local-bt-grid" / "scripts"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from summarize import pick_recommend, stats_from_trades  # noqa: E402
from equity_yearly import (  # noqa: E402
    _sharpe_daily,
    build_daily_equity,
    sharpe_from_returns,
    simple_returns,
    year_equity_path,
)


def _cell(cid, kind, is_pnl, oos_pnl, overrides=None, **book_extra):
    book = {"is_pnl": is_pnl, "oos_pnl": oos_pnl, "n_logs_ok": 1}
    book.update(book_extra)
    return {
        "id": cid,
        "label": cid,
        "kind": kind,
        "overrides": overrides if overrides is not None else ({"STOP_LOSS": 0.06} if cid != "base" else {}),
        "samples": {
            "book": book,
        },
    }


class GridSummarizeTest(unittest.TestCase):
    def test_pick_recommend_book_only_gate(self) -> None:
        cells = [
            _cell("base", "base", 1000.0, 500.0, overrides={}),
            _cell("bad_sign", "tighten", -100.0, 800.0),
            _cell("worse_oos", "loosen", 2000.0, 400.0),
            _cell("good", "other", 1500.0, 900.0),
        ]
        rec = pick_recommend(cells)
        self.assertEqual(rec["id"], "good")
        self.assertIn("验收期", rec["reason"])
        self.assertNotIn("IS", rec["reason"])
        self.assertNotIn("OOS", rec["reason"])
        by_id = {n["id"]: n for n in rec["candidates"]}
        self.assertIn("调参期", by_id["bad_sign"]["fail"])
        self.assertIn("验收期", by_id["worse_oos"]["fail"])
        self.assertIsNone(by_id["good"]["fail"])

    def test_pick_recommend_corner_collapse_keeps_base(self) -> None:
        cells = [
            _cell(
                "base",
                "base",
                1000.0,
                500.0,
                overrides={},
                corner_oos_pnl=200.0,
                holdout_has_coverage=True,
                holdout_n_logs=2,
            ),
            _cell(
                "good_time",
                "tighten",
                1500.0,
                900.0,
                corner_oos_pnl=50.0,
                holdout_has_coverage=True,
                holdout_n_logs=2,
            ),
        ]
        rec = pick_recommend(cells)
        self.assertEqual(rec["id"], "base")
        by_id = {n["id"]: n for n in rec["candidates"]}
        self.assertIn("盲测", by_id["good_time"]["fail"])

    def test_pick_recommend_holdout_no_coverage(self) -> None:
        cells = [
            _cell(
                "base",
                "base",
                100.0,
                50.0,
                overrides={},
                corner_oos_pnl=0.0,
                holdout_has_coverage=False,
                holdout_n_logs=0,
            ),
            _cell(
                "sl06",
                "tighten",
                200.0,
                80.0,
                corner_oos_pnl=0.0,
                holdout_has_coverage=False,
                holdout_n_logs=0,
            ),
        ]
        rec = pick_recommend(cells)
        self.assertEqual(rec["id"], "base")
        by_id = {n["id"]: n for n in rec["candidates"]}
        self.assertIn("无覆盖", by_id["sl06"]["fail"])

    def test_stats_tune_excludes_holdout_pnl(self) -> None:
        trades = [
            {"pnl": 100.0, "sell_exec_day": "20180615", "sell_signal": "trail_stop", "stock": "A.SH"},
            {"pnl": 999.0, "sell_exec_day": "20180615", "sell_signal": "trail_stop", "stock": "B.SH"},
            {"pnl": -20.0, "sell_exec_day": "20240615", "sell_signal": "time_force", "stock": "A.SH"},
            {"pnl": -500.0, "sell_exec_day": "20240615", "sell_signal": "time_force", "stock": "B.SH"},
        ]
        st = stats_from_trades(
            trades,
            {2018: 2, 2024: 2},
            tune_years={2018},
            check_years={2024},
            tune_stocks=["A.SH"],
            holdout_stocks=["B.SH"],
        )
        self.assertEqual(st["sum_pnl"], 80.0)
        self.assertEqual(st["is_pnl"], 100.0)
        self.assertEqual(st["oos_pnl"], -20.0)
        self.assertEqual(st["corner_oos_pnl"], -500.0)
        self.assertTrue(st["holdout_has_coverage"])
        self.assertIn("holdout_windows", st)
        self.assertEqual(st["holdout_windows"]["tune"]["n_open"], 1)
        self.assertEqual(st["holdout_windows"]["check"]["n_open"], 1)
        self.assertIsNotNone(st["windows"]["tune"]["n_open"])

    def test_pick_recommend_ignores_winner_sample(self) -> None:
        cells = [
            {
                "id": "base",
                "label": "base",
                "kind": "base",
                "overrides": {},
                "samples": {
                    "winner": {"is_pnl": 9999.0, "oos_pnl": 9999.0, "n_logs_ok": 4},
                    "book": {"is_pnl": 100.0, "oos_pnl": 50.0, "n_logs_ok": 1},
                },
            },
            {
                "id": "sl06",
                "label": "sl06",
                "kind": "tighten",
                "overrides": {"STOP_LOSS": 0.06},
                "samples": {
                    "winner": {"is_pnl": 1.0, "oos_pnl": 1.0, "n_logs_ok": 4},
                    "book": {"is_pnl": 200.0, "oos_pnl": 80.0, "n_logs_ok": 1},
                },
            },
        ]
        rec = pick_recommend(cells)
        self.assertEqual(rec["id"], "sl06")

    def test_stats_from_trades_uses_year_sets(self) -> None:
        trades = [
            {"pnl": 100.0, "sell_exec_day": "20180615", "sell_signal": "trail_stop"},
            {"pnl": 50.0, "sell_exec_day": "20210615", "sell_signal": "stop_loss"},
            {"pnl": -20.0, "sell_exec_day": "20240615", "sell_signal": "time_force"},
        ]
        st = stats_from_trades(
            trades,
            {2018: 1, 2021: 1, 2024: 1},
            tune_years={2018, 2019, 2020},
            check_years={2023, 2024},
        )
        self.assertEqual(st["is_pnl"], 100.0)
        self.assertEqual(st["oos_pnl"], -20.0)
        self.assertEqual(st["sum_pnl"], 130.0)

    def test_windows_cross_year_sell_stays_on_job_year(self) -> None:
        trades = [
            {
                "year": "2018",
                "buy_open_day": "20181203",
                "sell_exec_day": "20190115",
                "pnl": 500.0,
                "sell_signal": "trail_stop",
            }
        ]
        st = stats_from_trades(
            trades,
            {2018: 1},
            tune_years={2018},
            check_years={2019},
            run_years={2018, 2019},
            per_budget=100000.0,
        )
        self.assertEqual(st["windows"]["tune"]["n_open"], 1)
        self.assertEqual(st["windows"]["check"]["n_open"], 0)
        self.assertEqual(st["windows"]["all"]["n_open"], 1)
        self.assertEqual(st["is_pnl"], 0.0)
        self.assertEqual(st["oos_pnl"], 500.0)

    def test_windows_empty_check_sharpe_none(self) -> None:
        trades = [
            {
                "year": "2018",
                "buy_open_day": "20180115",
                "sell_exec_day": "20180215",
                "pnl": 100.0,
                "sell_signal": "trail_stop",
            }
        ]
        st = stats_from_trades(
            trades,
            {2018: 1},
            tune_years={2018},
            check_years={2023, 2024},
            run_years={2018, 2023, 2024},
            per_budget=100000.0,
        )
        chk = st["windows"]["check"]
        self.assertIsNone(chk["sharpe"])
        self.assertEqual(chk["n_open"], 0)
        self.assertIsNone(chk["avg_ann_pct"])
        self.assertIsNone(chk["avg_year_pnl"])
        self.assertEqual(st["windows"]["tune"]["n_open"], 1)

    def test_windows_sharpe_concat_returns_not_stitched_equity(self) -> None:
        t18 = {
            "year": "2018",
            "buy_open_day": "20180102",
            "sell_exec_day": "20180629",
            "pnl": 20000.0,
            "sell_signal": "trail_stop",
        }
        t19 = {
            "year": "2019",
            "buy_open_day": "20190102",
            "sell_exec_day": "20190628",
            "pnl": -15000.0,
            "sell_signal": "stop_loss",
        }
        st = stats_from_trades(
            [t18, t19],
            {2018: 1, 2019: 1},
            tune_years={2018},
            check_years={2019},
            run_years={2018, 2019},
            per_budget=100000.0,
        )
        p18 = year_equity_path(build_daily_equity([t18], 100000.0), 2018, 100000.0)
        p19 = year_equity_path(build_daily_equity([t19], 100000.0), 2019, 100000.0)
        stitched = _sharpe_daily(pd.concat([p18, p19], ignore_index=True))
        concat_rets = list(simple_returns(p18)) + list(simple_returns(p19))
        concat_sharpe = sharpe_from_returns(concat_rets)
        self.assertIsNotNone(concat_sharpe)
        self.assertNotEqual(concat_sharpe, stitched)
        self.assertEqual(st["windows"]["all"]["sharpe"], concat_sharpe)
        self.assertEqual(st["windows"]["tune"]["n_open"], 1)
        self.assertEqual(st["windows"]["check"]["n_open"], 1)
        self.assertAlmostEqual(st["windows"]["all"]["avg_year_pnl"], (20000.0 - 15000.0) / 2.0, places=2)
        self.assertAlmostEqual(st["windows"]["tune"]["avg_ann_pct"], 20.0, places=2)
        self.assertAlmostEqual(st["windows"]["check"]["avg_ann_pct"], -15.0, places=2)


if __name__ == "__main__":
    unittest.main()
