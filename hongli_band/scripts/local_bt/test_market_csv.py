# coding: utf-8
"""周线合成：周中最后一根收盘 = 当日收盘。"""
from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from market_csv import DailyBar, MarketStore, aggregate_weekly, compact_day, week_monday


def _bar(day: str, close: float, high: float | None = None, low: float | None = None) -> DailyBar:
    dt = datetime.strptime(day, "%Y%m%d").replace(hour=15, minute=0, second=0)
    px = float(close)
    hi = float(high if high is not None else px)
    lo = float(low if low is not None else px)
    return DailyBar(
        day=day,
        dt=dt,
        open=px,
        high=hi,
        low=lo,
        close=px,
        volume=100.0,
        stock="600350.SH",
    )


class WeeklyFormingTests(unittest.TestCase):
    def test_week_monday(self):
        self.assertEqual(week_monday("20260107"), "20260105")
        self.assertEqual(week_monday("20260105"), "20260105")

    def test_midweek_close_is_today_not_friday(self):
        dailies = [
            _bar("20260105", 10.0, high=11.0, low=9.0),
            _bar("20260106", 11.0, high=12.0, low=10.0),
            _bar("20260107", 12.5, high=13.0, low=11.0),
            _bar("20260108", 13.0),
            _bar("20260109", 14.0),
        ]
        wed = [b for b in dailies if b.day <= "20260107"]
        weeks = aggregate_weekly(wed)
        self.assertTrue(weeks)
        last = weeks[-1]
        self.assertEqual(last.close, 12.5)
        self.assertEqual(last.day, "20260107")
        self.assertEqual(last.open, 10.0)
        self.assertEqual(last.high, 13.0)
        self.assertEqual(last.low, 9.0)
        self.assertNotEqual(last.close, 14.0)

    def test_store_weekly_slice_on_wednesday(self):
        dailies = [
            _bar("20251229", 9.0),
            _bar("20251230", 9.5),
            _bar("20251231", 9.2),
            _bar("20260105", 10.0),
            _bar("20260106", 11.0),
            _bar("20260107", 12.5),
            _bar("20260108", 13.0),
            _bar("20260109", 14.0),
        ]
        store = MarketStore(dailies, "600350.SH")
        frame = store.frame("1w", "20260107", count=8, fields=["open", "high", "low", "close", "volume"])
        self.assertGreaterEqual(len(frame), 2)
        self.assertEqual(float(frame["close"][-1]), 12.5)
        last_dt = frame.index[-1]
        self.assertEqual(last_dt.strftime("%Y%m%d"), "20260107")

    def test_compact_day(self):
        self.assertEqual(compact_day("2026-01-07 15:00:00"), "20260107")
        self.assertEqual(compact_day("20260107"), "20260107")


class TradeLedgerTests(unittest.TestCase):
    def test_fifo_sell_pnl_and_qmt_header(self):
        from trades_csv import HEADER, TradeLedger

        book = TradeLedger("600350.SH")
        book.on_buy(10000, 4.17, "20230105150000")
        book.on_buy(9900, 4.38, "20230302150000")
        book.on_sell(19900, 4.47, "20230307150000")
        self.assertEqual(len(book.rows), 3)
        self.assertEqual(book.rows[0][6], "买入")
        self.assertEqual(book.rows[0][9], "0.00")
        self.assertEqual(book.rows[2][6], "卖出")
        self.assertEqual(book.rows[2][12], "19900")
        # (4.47-4.17)*10000 + (4.47-4.38)*9900 = 3000 + 891 = 3891
        self.assertEqual(book.rows[2][9], "3891.00")
        self.assertEqual(len(book.rows[0]), len(HEADER))

    def test_etf_decimals_and_write_gbk(self):
        import tempfile
        from pathlib import Path
        from trades_csv import HEADER, TradeLedger

        book = TradeLedger("513530.SH")
        book.on_buy(50200, 0.957, "20230707150000")
        book.on_sell(50200, 0.995, "20230801150000")
        self.assertEqual(book.rows[0][2], "ETF")
        self.assertEqual(book.rows[0][7], "0.957")
        pnl = (0.995 - 0.957) * 50200
        self.assertEqual(book.rows[1][9], "%.3f" % pnl)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "t.csv"
            book.write(path)
            text = path.read_text(encoding="gbk")
            self.assertTrue(text.startswith(",".join(HEADER)))
            self.assertIn("港股通红利ETF华泰柏瑞", text)


if __name__ == "__main__":
    unittest.main()
