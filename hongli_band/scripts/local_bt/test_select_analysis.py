# coding: utf-8
import unittest

from book_backtest import book_stocks_hash, normalize_book_stocks
from select_analysis import (
    collect_score_years,
    data_and_eval_years,
    iter_rebalance_periods,
    score_years_for_period,
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


if __name__ == "__main__":
    unittest.main()
