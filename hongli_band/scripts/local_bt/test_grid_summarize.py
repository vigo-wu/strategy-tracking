# coding: utf-8
"""网格 summarize：窗内过门、调参/验收年切分。"""
from __future__ import annotations

import json
import sys
import tempfile
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

from grid_gate import default_gate, fill_gate  # noqa: E402
from summarize import pick_recommend, stats_from_trades, summarize_sweep  # noqa: E402
from equity_yearly import (  # noqa: E402
    _sharpe_daily,
    build_daily_equity,
    sharpe_from_returns,
    simple_returns,
    year_equity_path,
)


def _win(
    *,
    calmar: float | None = 2.0,
    sharpe: float | None = 1.0,
    max_dd: float | None = -0.05,
    n_trades: int = 10,
    win_rate: float | None = 50.0,
    profit_factor: float | None = 2.0,
    avg_ann_pct: float | None = 20.0,
) -> dict:
    return {
        "calmar": calmar,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_ann_pct": avg_ann_pct,
        "n_open": n_trades,
        "avg_year_pnl": 100.0,
    }


def _cell(
    cid,
    kind,
    *,
    check,
    tune=None,
    overrides=None,
    is_pnl=1000.0,
    oos_pnl=500.0,
    holdout_check=None,
    **book_extra,
):
    tune_w = tune if tune is not None else check
    book = {
        "is_pnl": is_pnl,
        "oos_pnl": oos_pnl,
        "n_logs_ok": 1,
        "windows": {"all": check, "tune": tune_w, "check": check},
    }
    if holdout_check is not None:
        book["holdout_windows"] = {
            "all": holdout_check,
            "tune": holdout_check,
            "check": holdout_check,
        }
        book.setdefault("holdout_has_coverage", True)
        book.setdefault("holdout_n_logs", 1)
        book.setdefault("corner_oos_pnl", 100.0)
    book.update(book_extra)
    return {
        "id": cid,
        "label": cid,
        "kind": kind,
        "overrides": overrides
        if overrides is not None
        else ({"STOP_LOSS": 0.06} if cid != "base" else {}),
        "samples": {"book": book},
    }


def _gate_off_absolute(**kwargs):
    g = default_gate()
    for key in ("calmar", "max_dd", "oos_sharpe", "n_trades", "win_rate", "profit_factor"):
        g[key]["enabled"] = False
    g.update(kwargs)
    return fill_gate(g)


class GridSummarizeTest(unittest.TestCase):
    def test_windows_include_trade_kpis_and_calmar(self) -> None:
        trades = [
            {
                "year": "2024",
                "buy_open_day": "20240102",
                "sell_exec_day": "20240628",
                "pnl": 20000.0,
                "sell_signal": "trail_stop",
            },
            {
                "year": "2024",
                "buy_open_day": "20240701",
                "sell_exec_day": "20240901",
                "pnl": -5000.0,
                "sell_signal": "stop_loss",
            },
        ]
        st = stats_from_trades(
            trades,
            {2024: 1},
            tune_years={2018},
            check_years={2024},
            run_years={2018, 2024},
            per_budget=100000.0,
        )
        chk = st["windows"]["check"]
        self.assertEqual(chk["n_trades"], 2)
        self.assertAlmostEqual(chk["win_rate"], 50.0, places=2)
        self.assertGreater(chk["profit_factor"], 1.0)
        self.assertIsNotNone(chk["max_dd"])
        self.assertLess(chk["max_dd"], 0)
        self.assertIsNotNone(chk["calmar"])
        self.assertAlmostEqual(chk["calmar"], (chk["avg_ann_pct"] / 100.0) / abs(chk["max_dd"]), places=5)

    def test_pick_recommend_absolute_and_same_sign(self) -> None:
        base_chk = _win(calmar=1.6, sharpe=0.9)
        base_tune = _win(calmar=1.8)
        cells = [
            _cell("base", "base", check=base_chk, tune=base_tune, overrides={}),
            _cell(
                "bad_sign",
                "tighten",
                check=_win(calmar=2.5, sharpe=1.2),
                tune=_win(calmar=1.0),  # Δ tune 负、Δ check 正 → 不同向
                is_pnl=500.0,
                oos_pnl=900.0,
            ),
            _cell(
                "low_calmar",
                "loosen",
                check=_win(calmar=1.2, sharpe=1.0),  # 绝对未达 1.5
                tune=_win(calmar=2.0),
            ),
            _cell(
                "good",
                "other",
                check=_win(calmar=2.4, sharpe=1.2, max_dd=-0.04, win_rate=55, profit_factor=2.2),
                tune=_win(calmar=2.2),
                is_pnl=1500.0,
                oos_pnl=900.0,
            ),
        ]
        rec = pick_recommend(
            cells,
            gate=fill_gate(
                {
                    "calmar_same_sign": True,
                    "calmar": {"enabled": True, "min": 1.5},
                }
            ),
        )
        self.assertEqual(rec["id"], "good")
        by_id = {n["id"]: n for n in rec["candidates"]}
        self.assertIn("同向", by_id["bad_sign"]["fail"])
        self.assertIn("卡玛", by_id["low_calmar"]["fail"])
        self.assertIsNone(by_id["good"]["fail"])

    def test_pick_disabled_skips_missing(self) -> None:
        gate = _gate_off_absolute(relative_to_base=False, calmar_same_sign=False)
        cells = [
            _cell("base", "base", check=_win(calmar=None, sharpe=None, max_dd=None), overrides={}),
            _cell(
                "sl06",
                "tighten",
                check=_win(calmar=None, sharpe=None, max_dd=None),
                oos_pnl=80.0,
            ),
        ]
        rec = pick_recommend(cells, gate=gate)
        self.assertEqual(rec["id"], "sl06")
        self.assertIsNone(rec["candidates"][0]["fail"])

    def test_pick_threshold_change(self) -> None:
        cells = [
            _cell("base", "base", check=_win(calmar=1.55), tune=_win(calmar=1.55), overrides={}),
            _cell(
                "mid",
                "other",
                check=_win(calmar=1.7, sharpe=1.0),
                tune=_win(calmar=1.8),
            ),
        ]
        ok = pick_recommend(cells)
        self.assertEqual(ok["id"], "mid")
        strict = default_gate()
        strict["calmar"]["enabled"] = True
        strict["calmar"]["min"] = 2.0
        rec = pick_recommend(cells, gate=strict)
        self.assertEqual(rec["id"], "base")
        self.assertIn("卡玛", rec["candidates"][0]["fail"])

    def test_pick_relative_off_allows_worse_than_base(self) -> None:
        cells = [
            _cell(
                "base",
                "base",
                check=_win(calmar=3.0, sharpe=1.5, win_rate=60, profit_factor=3.0),
                tune=_win(calmar=3.0),
                overrides={},
            ),
            _cell(
                "weaker",
                "tighten",
                check=_win(calmar=2.0, sharpe=1.0, win_rate=50, profit_factor=2.0, max_dd=-0.05),
                tune=_win(calmar=2.5),
            ),
        ]
        with_rel = pick_recommend(cells)
        self.assertEqual(with_rel["id"], "base")
        gate = default_gate()
        gate["relative_to_base"] = False
        gate["calmar_same_sign"] = False
        no_rel = pick_recommend(cells, gate=gate)
        self.assertEqual(no_rel["id"], "weaker")

    def test_pick_holdout_no_coverage(self) -> None:
        gate = _gate_off_absolute(relative_to_base=False, calmar_same_sign=False)
        cells = [
            _cell(
                "base",
                "base",
                check=_win(),
                overrides={},
                holdout_has_coverage=False,
                holdout_n_logs=0,
                corner_oos_pnl=0.0,
            ),
            _cell(
                "sl06",
                "tighten",
                check=_win(),
                holdout_has_coverage=False,
                holdout_n_logs=0,
                corner_oos_pnl=0.0,
            ),
        ]
        rec = pick_recommend(cells, gate=gate)
        self.assertEqual(rec["id"], "base")
        self.assertIn("无覆盖", rec["candidates"][0]["fail"])

    def test_pick_holdout_veto_absolute(self) -> None:
        base_h = _win(calmar=2.0, sharpe=1.0)
        cells = [
            _cell(
                "base",
                "base",
                check=_win(calmar=2.0),
                tune=_win(calmar=2.0),
                holdout_check=base_h,
                overrides={},
            ),
            _cell(
                "good_time",
                "tighten",
                check=_win(calmar=2.5, sharpe=1.2),
                tune=_win(calmar=2.2),
                holdout_check=_win(calmar=0.5, sharpe=0.2),  # 盲测卡玛不过
            ),
        ]
        rec = pick_recommend(cells)
        self.assertEqual(rec["id"], "base")
        self.assertIn("盲测", rec["candidates"][0]["fail"])

    def test_pick_rank_by_calmar_delta(self) -> None:
        gate = _gate_off_absolute(relative_to_base=False, calmar_same_sign=False)
        cells = [
            _cell("base", "base", check=_win(calmar=1.0), overrides={}),
            _cell(
                "more_keys",
                "other",
                check=_win(calmar=2.0),
                overrides={"STOP_LOSS": 0.06, "TRAIL_STOP": 0.08},
                oos_pnl=9999.0,
            ),
            _cell(
                "less_keys",
                "other",
                check=_win(calmar=1.95),
                overrides={"STOP_LOSS": 0.06},
                oos_pnl=1.0,
            ),
        ]
        rec = pick_recommend(cells, gate=gate)
        # pad = max(0.05, 0.2) → 两者接近，少改 overrides 胜出
        self.assertEqual(rec["id"], "less_keys")
        self.assertEqual(rec["by_kind"]["other"]["id"], "more_keys")

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
        self.assertEqual(st["holdout_windows"]["tune"]["n_trades"], 1)
        self.assertEqual(st["holdout_windows"]["check"]["n_trades"], 1)

    def test_pick_recommend_ignores_winner_sample(self) -> None:
        gate = _gate_off_absolute(relative_to_base=False, calmar_same_sign=False)
        cells = [
            {
                "id": "base",
                "label": "base",
                "kind": "base",
                "overrides": {},
                "samples": {
                    "winner": {"is_pnl": 9999.0, "oos_pnl": 9999.0, "n_logs_ok": 4},
                    "book": {
                        "is_pnl": 100.0,
                        "oos_pnl": 50.0,
                        "n_logs_ok": 1,
                        "windows": {
                            "check": _win(calmar=1.0),
                            "tune": _win(calmar=1.0),
                            "all": _win(calmar=1.0),
                        },
                    },
                },
            },
            {
                "id": "sl06",
                "label": "sl06",
                "kind": "tighten",
                "overrides": {"STOP_LOSS": 0.06},
                "samples": {
                    "winner": {"is_pnl": 1.0, "oos_pnl": 1.0, "n_logs_ok": 4},
                    "book": {
                        "is_pnl": 200.0,
                        "oos_pnl": 80.0,
                        "n_logs_ok": 1,
                        "windows": {
                            "check": _win(calmar=2.0),
                            "tune": _win(calmar=2.0),
                            "all": _win(calmar=2.0),
                        },
                    },
                },
            },
        ]
        rec = pick_recommend(cells, gate=gate)
        self.assertEqual(rec["id"], "sl06")

    def test_summarize_sweep_gate_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spec.json").write_text(
                json.dumps(
                    {
                        "sweep": "tmp",
                        "gate": default_gate(),
                        "year_start": 2018,
                        "year_end": 2024,
                        "tune_start": 2018,
                        "tune_end": 2020,
                        "check_start": 2023,
                        "check_end": 2024,
                    }
                ),
                encoding="utf-8",
            )
            cell = root / "base"
            cell.mkdir()
            (cell / "cell_meta.json").write_text(
                json.dumps({"id": "base", "label": "base", "kind": "base", "overrides": {}}),
                encoding="utf-8",
            )
            (cell / "book").mkdir()
            gate = _gate_off_absolute(relative_to_base=False, calmar_same_sign=False)
            out = summarize_sweep(root, gate=gate)
            self.assertEqual(out["gate"]["relative_to_base"], False)
            self.assertFalse(out["gate"]["calmar"]["enabled"])
            self.assertEqual(out["recommend"]["id"], "base")

    def _write_cell(self, root: Path, cid: str) -> None:
        cell = root / cid
        cell.mkdir()
        (cell / "cell_meta.json").write_text(
            json.dumps({"id": cid, "label": cid, "kind": "other" if cid != "base" else "base", "overrides": {}}),
            encoding="utf-8",
        )
        (cell / "book").mkdir()

    def test_summarize_sweep_skips_cells_not_in_spec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spec.json").write_text(
                json.dumps(
                    {
                        "sweep": "tmp",
                        "cells": [
                            {"id": "base", "kind": "base", "overrides": {}},
                            {"id": "vpn15", "kind": "other", "overrides": {"VOL_PULLBACK_N": 15}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self._write_cell(root, "base")
            self._write_cell(root, "vpn15")
            self._write_cell(root, "vpn13")
            out = summarize_sweep(root)
            self.assertEqual([c["id"] for c in out["cells"]], ["base", "vpn15"])

    def test_summarize_sweep_cell_ids_override_spec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spec.json").write_text(
                json.dumps(
                    {
                        "sweep": "tmp",
                        "cells": [
                            {"id": "base", "kind": "base", "overrides": {}},
                            {"id": "vpn15", "kind": "other", "overrides": {}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self._write_cell(root, "base")
            self._write_cell(root, "vpn15")
            self._write_cell(root, "vpn15_vpc1")
            out = summarize_sweep(root, cell_ids=["base", "vpn15_vpc1"])
            self.assertEqual([c["id"] for c in out["cells"]], ["base", "vpn15_vpc1"])

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
        self.assertEqual(st["windows"]["tune"]["n_trades"], 1)
        self.assertEqual(st["windows"]["check"]["n_trades"], 0)
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
        self.assertEqual(chk["n_trades"], 0)
        self.assertIsNone(chk["calmar"])
        self.assertIsNone(chk["avg_ann_pct"])

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
