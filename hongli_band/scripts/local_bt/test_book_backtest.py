# coding: utf-8
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from market_csv import DailyBar, MarketStore
from trades_csv import CombinedTradeLedger, TradeLedger


def _bars(n=120, stock="600350.SH", start="20200102"):
    d = datetime.strptime(start, "%Y%m%d")
    bars = []
    while len(bars) < n:
        if d.weekday() < 5:
            px = 10.0 + 0.02 * len(bars)
            day = d.strftime("%Y%m%d")
            bars.append(
                DailyBar(
                    day=day,
                    dt=d,
                    open=px,
                    high=px + 0.1,
                    low=px - 0.1,
                    close=px,
                    volume=1e6,
                    stock=stock,
                )
            )
        d += timedelta(days=1)
    return bars


class BookBacktestUnitTests(unittest.TestCase):
    def test_combined_ledger_two_stocks(self):
        rows = []

        def getter():
            return cur["s"]

        cur = {"s": "600350.SH"}
        lg = CombinedTradeLedger(getter)
        lg.on_buy(1000, 10.0, "20200110150000")
        cur["s"] = "601939.SH"
        lg.on_buy(2000, 20.0, "20200111150000")
        cur["s"] = "600350.SH"
        lg.on_sell(1000, 10.5, "20200120150000")
        self.assertEqual(len(lg.rows), 3)
        codes = {r[0] for r in lg.rows}
        self.assertIn("600350", codes)
        self.assertIn("601939", codes)

    def test_norm_detail_stock(self):
        from book_backtest import _norm_detail_stock

        self.assertEqual(_norm_detail_stock("301"), "000301.SZ")
        self.assertEqual(_norm_detail_stock("600350"), "600350.SH")
        from book_backtest import attribute_portfolio_kpi

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "empty.csv"
            lg = TradeLedger("600350.SH")
            lg.write(p)
            self.assertEqual(attribute_portfolio_kpi(p), {})


if __name__ == "__main__":
    unittest.main()
