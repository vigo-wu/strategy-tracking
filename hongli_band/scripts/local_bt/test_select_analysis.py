# coding: utf-8
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from book_backtest import book_log_name, book_stocks_hash, normalize_book_stocks
from compound_wallet import compound_enabled
from select_analysis import (
    collect_score_years,
    data_and_eval_years,
    iter_rebalance_periods,
    pick_details_from_basket,
    run_fixed_book,
    score_years_for_period,
    write_analysis_csv,
)
from select_config import (
    book_stocks_to_editor_rows,
    editor_rows_to_book_stocks,
    load_book_stocks_full,
)
from stock_select import empty_year_kpi, score_universe, _overlay_portfolio_kpi


class SelectAnalysisTests(unittest.TestCase):
    def test_iter_rebalance_periods(self):
        ps = iter_rebalance_periods(("2020", "2021", "2022", "2023", "2024"), 2)
        self.assertEqual(len(ps), 3)
        self.assertEqual(ps[0]["hold_years"], ("2020", "2021"))
        self.assertEqual(ps[2]["hold_years"], ("2024",))

    def test_score_years_for_period(self):
        data = ("2020", "2021", "2022", "2023", "2024")
        self.assertEqual(score_years_for_period("2022", 2, data), ("2020", "2021"))
        self.assertEqual(score_years_for_period("2021", 2, data), ())

    def test_data_and_eval_years(self):
        avail = ("2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026")
        data, ev = data_and_eval_years("2020", "2026", 2, avail)
        self.assertEqual(data, ("2020", "2021", "2022", "2023", "2024", "2025", "2026"))
        self.assertEqual(ev, ("2022", "2023", "2024", "2025", "2026"))
        data2, ev2 = data_and_eval_years("2020", "2021", 2, avail)
        self.assertEqual(ev2, ())

    def test_collect_score_years(self):
        ps = iter_rebalance_periods(("2022", "2023", "2024"), 1)
        data = ("2020", "2021", "2022", "2023", "2024")
        years = collect_score_years(ps, 2, data)
        self.assertIn("2020", years)
        self.assertIn("2023", years)

    def test_book_hash_stable(self):
        a = {"600350.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"}}
        b = normalize_book_stocks(a)
        self.assertEqual(book_stocks_hash(a), book_stocks_hash(b))

    def test_compound_enabled_overrides(self):
        self.assertTrue(compound_enabled({"compound_backtest": True}))
        self.assertFalse(compound_enabled({"compound_backtest": False}))
        self.assertFalse(compound_enabled(None))

    def test_load_book_stocks_full_from_temp_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.py"
            cfg.write_text(
                "BOOK_STOCKS = {\n"
                '  "600350.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},\n'
                '  "601988.SH": "SMA",\n'
                "}\n"
                'MA_TYPE = "EMA"\n',
                encoding="utf-8",
            )
            book = load_book_stocks_full(str(cfg))
            self.assertEqual(book["600350.SH"]["ma_type"], "EMA")
            self.assertEqual(book["600350.SH"]["dividend_type"], "front_ratio")
            self.assertEqual(book["601988.SH"]["ma_type"], "SMA")
            rows = book_stocks_to_editor_rows(book)
            back = editor_rows_to_book_stocks(rows)
            self.assertIn("600350.SH", back)

    def test_run_fixed_book_passes_basket_and_compound(self):
        basket = {
            "600350.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
            "601988.SH": {"ma_type": "SMA", "dividend_type": "front"},
        }
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report"
            report.mkdir()
            captured = {}

            def _fake_run(book_stocks, start, end, csv_root, out_dir, **kwargs):
                captured["book"] = dict(book_stocks)
                captured["start"] = start
                captured["end"] = end
                captured["overrides"] = dict(kwargs.get("overrides") or {})
                log_name = kwargs.get("log_name") or "x.txt"
                log_path = Path(out_dir) / log_name
                log_path.write_text(
                    "local_bt_book compound=1 wallet_start=100000.00\nwallet_end=110000.00\n",
                    encoding="utf-8",
                )
                trades = log_path.with_name(log_path.stem + "_操作明细.csv")
                trades.write_text("代码,操作类型,操作价格,数量,盈利\n", encoding="gbk")
                return log_path, {
                    "wallet_cash_start": 100000.0,
                    "wallet_cash_end": 110000.0,
                    "skipped": [],
                }

            with patch("select_analysis.run_book_backtest", side_effect=_fake_run), patch(
                "select_analysis.analyze_book_detail",
                return_value={"sum_pnl": 10000.0, "stats": {"n_buy": 2}},
            ):
                result = run_fixed_book(
                    basket,
                    data_start="2024",
                    data_end="2025",
                    book_params={"trade_budget": 100000.0},
                    csv_root=td,
                    report_dir=report,
                    compound_backtest=True,
                    force_rerun=True,
                )
            self.assertEqual(captured["start"], "20240101")
            self.assertEqual(captured["end"], "20251231")
            self.assertTrue(captured["overrides"].get("compound_backtest"))
            self.assertEqual(set(captured["book"].keys()), set(basket.keys()))
            self.assertEqual(result["mode"], "fixed")
            self.assertAlmostEqual(float(result["summary"]["total_pnl"]), 10000.0)
            self.assertIn(
                "fixed",
                book_log_name(kind="fixed", year="20240101", tag="abc", end="20251231"),
            )

    def test_score_universe_portfolio_kpi(self):
        scanned = {
            "stocks": {
                "600350.SH": {
                    "stock": "600350.SH",
                    "years": {"2020": {"n_buy": 9, "sum_pnl": 9000.0, "win_rate": 80.0}},
                    "by_ma": {},
                    "by_div": {},
                    "style": {},
                },
                "601939.SH": {
                    "stock": "601939.SH",
                    "years": {"2020": {"n_buy": 8, "sum_pnl": 8000.0, "win_rate": 70.0}},
                    "by_ma": {},
                    "by_div": {},
                    "style": {},
                },
            },
            "book": {},
            "portfolio_kpi": {
                "600350.SH": {
                    "2020": {**empty_year_kpi(), "n_buy": 2, "sum_pnl": 2000.0, "win_rate": 50.0},
                },
            },
        }
        resolved = {"600350.SH": {"years": {}, "style": {}}}
        _overlay_portfolio_kpi(resolved, scanned["portfolio_kpi"], ("2020",))
        self.assertEqual(resolved["600350.SH"]["years"]["2020"]["n_buy"], 2)
        scored = score_universe(
            scanned,
            filters={"min_n_buy": 0, "min_years_traded": 1, "min_pos_years": 0, "top_n": 3},
            score_years=("2020",),
            kpi_source="portfolio",
        )
        df = scored["df"]
        row = df[df["stock"] == "600350.SH"].iloc[0]
        self.assertEqual(int(row["n_buy"]), 2)

    def test_pick_details_from_basket(self):
        basket = {
            "601988.SH": {"ma_type": "SMA", "dividend_type": "front"},
            "600350.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
        }
        details = pick_details_from_basket(basket, {"600350.SH": 1.23})
        self.assertEqual(len(details), 2)
        self.assertEqual(details[0]["stock"], "600350.SH")
        self.assertEqual(details[0]["ma_type"], "EMA")
        self.assertEqual(details[0]["dividend_type"], "front_ratio")
        self.assertEqual(details[0]["score"], 1.23)
        self.assertEqual(details[1]["stock"], "601988.SH")
        self.assertNotIn("score", details[1])
        self.assertEqual(pick_details_from_basket(None), [])
        self.assertEqual(pick_details_from_basket({}), [])

    def test_write_analysis_csv_serializes_pick_details(self):
        result = {
            "year_rows": [
                {
                    "year": "2022",
                    "picks": "600350.SH",
                    "pick_details": [
                        {"stock": "600350.SH", "ma_type": "EMA", "dividend_type": "front_ratio"}
                    ],
                    "portfolio_pnl": 100.0,
                    "status": "ok",
                }
            ],
            "params": {"top_k": 3},
        }
        with tempfile.TemporaryDirectory() as td:
            path = write_analysis_csv(result, Path(td) / "out.csv")
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("pick_details", text)
            self.assertIn("600350.SH", text)
            self.assertIn("front_ratio", text)
            # nested list must be JSON string, not Python repr of list-of-dict alone in cell mess
            import json

            import pandas as pd

            df = pd.read_csv(path)
            parsed = json.loads(df.iloc[0]["pick_details"])
            self.assertEqual(parsed[0]["ma_type"], "EMA")


if __name__ == "__main__":
    unittest.main()
