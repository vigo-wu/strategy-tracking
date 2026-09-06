# coding: utf-8
"""滚动选股过门：泄漏、空窗、复利关闭、同向门、picks.json。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from select_config import (
    fill_select_windows,
    first_hold_year,
    named_filter_cells,
    resolve_named_filters,
    scaled_min_n_buy,
    score_years_before_hold,
)
from select_qualify import listing_year_from_meta, qualify_stocks
from select_wf import (
    assert_no_leak,
    build_period_baskets,
    contribution_warnings,
    csv_meta_map,
    judge_select_gate,
    run_select_gate,
    select_progress_units,
)
from select_overfit import select_overfit_report
from stock_select import empty_year_kpi, score_universe


def _kpi(n_buy: int, pnl: float) -> dict:
    k = empty_year_kpi()
    k["n_buy"] = n_buy
    k["sum_pnl"] = pnl
    k["gross_profit"] = max(pnl, 0.0)
    k["gross_loss"] = abs(min(pnl, 0.0))
    k["win_rate"] = 60.0
    k["profit_factor"] = 2.0
    return k


def _stock_rec(*years: str) -> dict:
    rec = {
        "stock": "600000.SH",
        "years": {y: _kpi(3, 100.0) for y in years},
        "style": {"vol_ann": 0.2, "touch_ma20": 0.1, "n_close": 200},
        "ma_type_suggest": "EMA",
        "div_type_suggest": "front_ratio",
    }
    return rec


class SelectQualifyTests(unittest.TestCase):
    def test_listing_year_from_meta(self) -> None:
        self.assertEqual(listing_year_from_meta({"start": "20180105"}), 2018)
        self.assertIsNone(listing_year_from_meta({}))

    def test_amount_quantile_uses_score_window_only(self) -> None:
        stocks = ["AAA.SH", "BBB.SH", "CCC.SH"]
        metas = {
            "AAA.SH": {"start": "20150101", "path": ""},
            "BBB.SH": {"start": "20150101", "path": ""},
            "CCC.SH": {"start": "20150101", "path": ""},
        }
        # 全样本 CCC 很大，但打分窗里很小，应被分位剔除
        q = qualify_stocks(
            stocks,
            select_year=2021,
            score_years=("2018", "2019", "2020"),
            csv_meta_by_stock=metas,
            amount_drop_bottom=0.34,
            amount_by_stock={"AAA.SH": 100.0, "BBB.SH": 90.0, "CCC.SH": 1.0},
        )
        self.assertNotIn("CCC.SH", q["eligible"])
        self.assertIn("AAA.SH", q["eligible"])

    def test_listing_too_new(self) -> None:
        q = qualify_stocks(
            ["NEW.SH"],
            select_year=2021,
            score_years=("2018", "2019", "2020"),
            csv_meta_by_stock={"NEW.SH": {"start": "20200101"}},
            amount_by_stock={"NEW.SH": 99.0},
        )
        self.assertEqual(q["n_eligible"], 0)
        self.assertEqual(q["n_no_listing"], 0)
        self.assertIn("上市未满", q["reasons"]["NEW.SH"])

    def test_no_listing_counts(self) -> None:
        q = qualify_stocks(
            ["X.SH"],
            select_year=2021,
            score_years=("2018", "2019", "2020"),
            csv_meta_by_stock={},
        )
        self.assertEqual(q["n_no_listing"], 1)
        self.assertEqual(q["n_eligible"], 0)

    def test_csv_meta_map_reads_typed_subdir(self) -> None:
        header = "stock,period,datetime,open,high,low,close,volume,amount"
        with tempfile.TemporaryDirectory() as td:
            none = Path(td) / "none"
            none.mkdir()
            (none / "600000_SH_1d_20180101_20180103.csv").write_text(
                header + "\n600000.SH,1d,2018-01-02,1,1,1,1,100,100\n",
                encoding="utf-8",
            )
            meta = csv_meta_map(td)
            self.assertIn("600000.SH", meta)
            self.assertTrue(str(meta["600000.SH"].get("start") or "").startswith("2018"))
            self.assertEqual(csv_meta_map(Path(td) / "missing"), {})


class SelectWfWindowTests(unittest.TestCase):
    def test_first_hold_and_empty_score_window(self) -> None:
        win = fill_select_windows({"year_start": 2018, "lookback": 3})
        self.assertEqual(first_hold_year(win), 2021)
        self.assertEqual(score_years_before_hold(2018, win), ())
        self.assertIn("空", assert_no_leak((), ("2018",)))

    def test_leak_overlap(self) -> None:
        msg = assert_no_leak(("2018", "2019"), ("2019", "2020"))
        self.assertIn("相交", msg)

    def test_strict_score_years_no_fallback(self) -> None:
        scanned = {"stocks": {"600000.SH": _stock_rec("2018")}, "book": {}}
        scored = score_universe(scanned, score_years=(), strict_score_years=True)
        self.assertTrue(scored.get("empty_score_years"))
        self.assertEqual(scored.get("score_years"), ())

    def test_scaled_min_n_buy_named(self) -> None:
        self.assertEqual(scaled_min_n_buy(3, 2), 6)
        flt = resolve_named_filters({"scale_min_n_buy": True}, 3)
        self.assertEqual(flt["min_n_buy"], 6)
        self.assertLessEqual(len(named_filter_cells()), 8)
        self.assertEqual(named_filter_cells()[0]["id"], "base")
        self.assertEqual(select_progress_units(6), 19)
        self.assertEqual(select_progress_units(3, with_meta=False), 9)

    def test_build_leak_when_no_prior_kpi_years(self) -> None:
        scanned = {"stocks": {"600000.SH": _stock_rec("2024")}, "book": {}}
        built = build_period_baskets(
            scanned,
            win=fill_select_windows({}),
            csv_meta_by_stock={"600000.SH": {"start": "20150101"}},
            amount_by_stock={"600000.SH": 1e9},
        )
        self.assertTrue(built["leak"])


class SelectGateTests(unittest.TestCase):
    def test_keep_current_if_check_not_better(self) -> None:
        j = judge_select_gate(
            leak="",
            wf_by_year={"2021": 50.0, "2022": 10.0, "2023": 5.0},
            book_by_year={"2021": 10.0, "2022": 8.0, "2023": 40.0},
            train_years=("2021",),
            precheck_years=("2022",),
            check_years=("2023",),
            wf_fail=[],
            book_fail=[],
        )
        self.assertEqual(j["verdict"], "KEEP_CURRENT")

    def test_fail_on_leak(self) -> None:
        j = judge_select_gate(
            leak="打分年与持有年相交: 2019",
            wf_by_year={},
            book_by_year={},
            train_years=("2021",),
            precheck_years=("2022",),
            check_years=("2023",),
            wf_fail=[],
            book_fail=[],
        )
        self.assertEqual(j["verdict"], "FAIL")

    def test_same_sign_keep(self) -> None:
        j = judge_select_gate(
            leak="",
            wf_by_year={"2021": 1.0, "2022": 10.0, "2023": 80.0},
            book_by_year={"2021": 50.0, "2022": 8.0, "2023": 10.0},
            train_years=("2021",),
            precheck_years=("2022",),
            check_years=("2023",),
            wf_fail=[],
            book_fail=[],
        )
        self.assertEqual(j["verdict"], "KEEP_CURRENT")
        self.assertIn("不同向", j["reason"])

    def test_pass_and_picks_json_not_book_stocks(self) -> None:
        years = ("2018", "2019", "2020", "2021", "2022", "2023")
        scanned = {"stocks": {"600000.SH": _stock_rec(*years)}, "book": {}}
        calls: list[dict] = []

        def runner(**kwargs):
            calls.append(kwargs)
            self.assertFalse(kwargs.get("compound_backtest"))
            baskets = kwargs.get("period_baskets") or {}
            rows = []
            for y in kwargs.get("eval_years") or ():
                b = baskets.get(str(y)) or {}
                wf = "600000.SH" in b
                pnl = 80.0 if wf else 10.0
                rows.append({"year": y, "status": "ok", "portfolio_pnl": pnl})
            return {"year_rows": rows, "summary": {}, "period_rows": []}

        with tempfile.TemporaryDirectory() as td:
            out = run_select_gate(
                scanned,
                spec={"year_start": 2018, "year_end": 2023, "check_start": 2023, "check_end": 2023},
                book={"601857.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"}},
                report_dir=td,
                csv_root=td,
                wf_runner=runner,
                csv_meta_by_stock={"600000.SH": {"start": "20150101"}},
                amount_by_stock={"600000.SH": 1e9},
                write_files=True,
                with_overfit=False,
            )
            self.assertEqual(out["gate"]["verdict"], "PASS")
            self.assertFalse(out["compound_backtest"])
            picks_path = Path(td) / "picks.json"
            data = json.loads(picks_path.read_text(encoding="utf-8"))
            self.assertNotIn("BOOK_STOCKS", data)
            self.assertTrue(any(str(k).isdigit() for k in data))
            self.assertTrue(out.get("next_basket"))

    def test_gate_progress_prefixes_paths_and_years(self) -> None:
        years = ("2018", "2019", "2020", "2021", "2022", "2023")
        scanned = {"stocks": {"600000.SH": _stock_rec(*years)}, "book": {}}
        events: list[dict] = []

        def runner(**kwargs):
            cb = kwargs.get("on_progress")
            eval_years = tuple(kwargs.get("eval_years") or ())
            y = str(eval_years[-1] if eval_years else "2023")
            if cb:
                cb(
                    {
                        "phase": "hold",
                        "done": 1,
                        "total": 1,
                        "year": y,
                        "label": "持有回放 1/1 · %s · 正在回测…" % y,
                    }
                )
            baskets = kwargs.get("period_baskets") or {}
            rows = []
            for yy in eval_years:
                wf = "600000.SH" in (baskets.get(str(yy)) or {})
                pnl = 80.0 if wf else 10.0
                rows.append({"year": yy, "status": "ok", "portfolio_pnl": pnl})
            return {"year_rows": rows, "summary": {}, "period_rows": []}

        out = run_select_gate(
            scanned,
            spec={"year_start": 2018, "year_end": 2023, "check_start": 2023, "check_end": 2023},
            book={"601857.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"}},
            report_dir=".",
            csv_root=".",
            wf_runner=runner,
            csv_meta_by_stock={"600000.SH": {"start": "20150101"}},
            amount_by_stock={"600000.SH": 1e9},
            write_files=False,
            with_overfit=False,
            on_progress=lambda ev: events.append(dict(ev or {})),
        )
        labels = [str(e.get("label") or "") for e in events]
        blob = "\n".join(labels)
        self.assertIn("按年打分", blob)
        self.assertIn("自动篮", blob)
        self.assertIn("现行池", blob)
        self.assertIn("总进度", blob)
        self.assertTrue(any("2021" in x or "2022" in x or "2023" in x for x in labels))
        dones = [int(e.get("done") or 0) for e in events]
        totals = [int(e.get("total") or 0) for e in events]
        self.assertTrue(events)
        self.assertEqual(dones, sorted(dones))
        self.assertEqual(len(set(totals)), 1)
        self.assertEqual(totals[0], select_progress_units(3, with_meta=False))
        self.assertEqual(out["gate"]["verdict"], "PASS")

    def test_keep_current_does_not_write_picks_json(self) -> None:
        years = ("2018", "2019", "2020", "2021", "2022", "2023")
        scanned = {"stocks": {"600000.SH": _stock_rec(*years)}, "book": {}}

        def runner(**kwargs):
            baskets = kwargs.get("period_baskets") or {}
            rows = []
            for y in kwargs.get("eval_years") or ():
                wf = "600000.SH" in (baskets.get(str(y)) or {})
                # 验收年现行池更好 → KEEP_CURRENT
                if str(y) >= "2023":
                    pnl = 10.0 if wf else 80.0
                else:
                    pnl = 80.0 if wf else 10.0
                rows.append({"year": y, "status": "ok", "portfolio_pnl": pnl})
            return {"year_rows": rows, "summary": {}, "period_rows": []}

        with tempfile.TemporaryDirectory() as td:
            stale = Path(td) / "picks.json"
            stale.write_text('{"2023": {"999999.SH": {}}}', encoding="utf-8")
            out = run_select_gate(
                scanned,
                spec={"year_start": 2018, "year_end": 2023, "check_start": 2023, "check_end": 2023},
                book={"601857.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"}},
                report_dir=td,
                csv_root=td,
                wf_runner=runner,
                csv_meta_by_stock={"600000.SH": {"start": "20150101"}},
                amount_by_stock={"600000.SH": 1e9},
                write_files=True,
                with_overfit=False,
            )
            self.assertEqual(out["gate"]["verdict"], "KEEP_CURRENT")
            self.assertFalse(out.get("picks"))
            self.assertFalse(stale.is_file())
            self.assertTrue((Path(td) / "select_gate.json").is_file())

    def test_empty_meta_fails_qualify(self) -> None:
        years = ("2018", "2019", "2020", "2021", "2022", "2023")
        scanned = {"stocks": {"600000.SH": _stock_rec(*years)}, "book": {}}
        called = []

        def runner(**kwargs):
            called.append(1)
            return {"year_rows": [], "summary": {}, "period_rows": []}

        out = run_select_gate(
            scanned,
            spec={"year_start": 2018, "year_end": 2023, "check_start": 2023, "check_end": 2023},
            book={"601857.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"}},
            report_dir=".",
            csv_root=".",
            wf_runner=runner,
            csv_meta_by_stock={},
            amount_by_stock={"600000.SH": 1e9},
            write_files=False,
            with_overfit=False,
        )
        self.assertEqual(out["gate"]["verdict"], "FAIL")
        self.assertIn("资格", out["gate"]["reason"])
        self.assertFalse(called)

    def test_contribution_warns_when_one_stock_dominates(self) -> None:
        notes = contribution_warnings(
            {
                "year_rows": [
                    {
                        "year": "2023",
                        "status": "ok",
                        "portfolio_pnl": 100.0,
                        "per_stock": {"AAA.SH": {"sum_pnl": 90.0}, "BBB.SH": {"sum_pnl": 10.0}},
                    }
                ]
            },
            ("2023",),
            baskets={"2023": {"AAA.SH": {}, "BBB.SH": {}}},
        )
        self.assertTrue(any("AAA.SH" in n and "90%" in n for n in notes))
        quiet = contribution_warnings(
            {
                "year_rows": [
                    {
                        "year": "2023",
                        "per_stock": {"AAA.SH": {"sum_pnl": 55.0}, "BBB.SH": {"sum_pnl": 45.0}},
                    }
                ]
            },
            ("2023",),
            baskets={"2023": {"AAA.SH": {}, "BBB.SH": {}}},
        )
        self.assertFalse(quiet)

    def test_overfit_skips_without_daily_equity(self) -> None:
        rep = select_overfit_report(
            {"_wf_raw": {"year_rows": [{"year": "2023", "status": "ok", "portfolio_pnl": 1}]}, "n_passed_max": 10, "n_filter_cells": 1}
        )
        self.assertEqual(rep.get("status"), "skip")


if __name__ == "__main__":
    unittest.main()
