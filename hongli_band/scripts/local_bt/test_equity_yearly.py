# coding: utf-8
import unittest

from equity_yearly import (
    build_daily_equity,
    daily_equity_for_year,
    year_performance_table,
)


def _t(buy, sell, pnl, stock="600000.SH"):
    return {
        "stock": stock,
        "buy_open_day": buy,
        "sell_exec_day": sell,
        "pnl": pnl,
        "cost": 10000.0,
        "shares": 100,
        "buy_price": 100.0,
    }


class EquityYearlyTests(unittest.TestCase):
    def test_two_years_chain(self):
        trades = [
            _t("20230105", "20230110", 1000.0),
            _t("20240201", "20240205", -400.0),
        ]
        budget = 100000.0
        tbl = year_performance_table(trades, budget)
        by = {str(r["year"]): r for _, r in tbl.iterrows()}
        self.assertEqual(by["2023"]["start_equity"], 100000.0)
        self.assertEqual(by["2023"]["end_equity"], 101000.0)
        self.assertEqual(by["2023"]["year_pnl"], 1000.0)
        self.assertAlmostEqual(by["2023"]["year_ret_pct"], 1.0)
        self.assertEqual(by["2024"]["start_equity"], 101000.0)
        self.assertEqual(by["2024"]["end_equity"], 100600.0)
        self.assertEqual(by["2024"]["year_pnl"], -400.0)
        self.assertAlmostEqual(by["2024"]["year_ret_pct"], round(-400.0 / 101000.0 * 100.0, 4))

    def test_intrayear_dd_and_steps(self):
        trades = [
            _t("20240102", "20240105", 2000.0),
            _t("20240108", "20240110", -3000.0),
        ]
        daily = build_daily_equity(trades, 100000.0)
        self.assertFalse(daily.empty)
        # after first sell equity 102000; after second 99000
        last = float(daily["equity"].iloc[-1])
        self.assertEqual(last, 99000.0)
        tbl = year_performance_table(trades, 100000.0)
        row = tbl.iloc[0]
        self.assertEqual(row["year_pnl"], -1000.0)
        self.assertIsNotNone(row["max_dd_pct"])
        self.assertLess(float(row["max_dd_pct"]), 0.0)

    def test_open_year_differs_from_sell_year(self):
        trades = [_t("20231228", "20240105", 500.0)]
        tbl = year_performance_table(trades, 100000.0)
        by = {str(r["year"]): r for _, r in tbl.iterrows()}
        self.assertEqual(int(by["2023"]["n_open"]), 1)
        self.assertEqual(int(by["2024"]["n_open"]), 0)
        self.assertEqual(by["2024"]["year_pnl"], 500.0)
        self.assertEqual(by["2023"]["year_pnl"], 0.0)

    def test_empty_trades(self):
        tbl = year_performance_table([], 100000.0)
        self.assertTrue(tbl.empty)
        daily = build_daily_equity([], 100000.0)
        self.assertTrue(daily.empty)

    def test_flat_year_sharpe_none(self):
        # buy in year but sell only creates flat stretch before sell with no daily ret variance after only one jump
        trades = [_t("20240102", "20240103", 0.0)]
        tbl = year_performance_table(trades, 100000.0)
        # equity constant 100000 entire path after 0 pnl → sharpe None
        self.assertTrue(tbl.iloc[0]["sharpe"] is None or tbl.iloc[0]["sharpe"] != tbl.iloc[0]["sharpe"])

    def test_daily_equity_for_year_head(self):
        trades = [
            _t("20230105", "20230110", 1000.0),
            _t("20240201", "20240205", 200.0),
        ]
        daily = build_daily_equity(trades, 100000.0)
        y24 = daily_equity_for_year(daily, "2024", start_equity=101000.0)
        self.assertTrue(y24.iloc[0]["date"] is None or (y24["date"].isna().iloc[0]))
        self.assertEqual(float(y24.iloc[0]["equity"]), 101000.0)
        self.assertEqual(float(y24.iloc[-1]["equity"]), 101200.0)


if __name__ == "__main__":
    unittest.main()
