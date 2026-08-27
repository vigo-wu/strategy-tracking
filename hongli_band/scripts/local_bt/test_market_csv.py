# coding: utf-8
"""周线：丢掉未收盘周，对齐 QMT 回测原生 1w。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
import sys

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from market_csv import (
    DailyBar,
    MarketStore,
    aggregate_weekly,
    compact_day,
    find_weekly_csv,
    peek_daily_csv_meta,
    week_monday,
)


def _bar(day: str, close: float, high: float | None = None, low: float | None = None) -> DailyBar:
    dt = datetime.strptime(day, "%Y%m%d").replace(hour=0, minute=0, second=0)
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


def _wbar(day: str, close: float) -> DailyBar:
    b = _bar(day, close)
    return DailyBar(
        day=b.day,
        dt=b.dt,
        open=b.open,
        high=b.high,
        low=b.low,
        close=b.close,
        volume=b.volume,
        stock=b.stock,
        period="1w",
    )


class WeeklyFormingTests(unittest.TestCase):
    def test_week_monday(self):
        self.assertEqual(week_monday("20260107"), "20260105")
        self.assertEqual(week_monday("20260105"), "20260105")

    def test_midweek_last_bar_is_previous_week(self):
        dailies = [
            _bar("20251229", 9.0, high=9.5, low=8.5),
            _bar("20251230", 9.5),
            _bar("20251231", 9.2),
            _bar("20260105", 10.0, high=11.0, low=9.0),
            _bar("20260106", 11.0, high=12.0, low=10.0),
            _bar("20260107", 12.5, high=13.0, low=11.0),
        ]
        wed = [b for b in dailies if b.day <= "20260107"]
        weeks = aggregate_weekly(wed)
        self.assertTrue(weeks)
        last = weeks[-1]
        self.assertEqual(last.close, 9.2)
        self.assertEqual(last.day, "20251231")
        forming = aggregate_weekly(wed, drop_forming=False)
        self.assertEqual(forming[-1].close, 12.5)
        self.assertEqual(forming[-1].day, "20260107")

    def test_friday_still_excludes_current_week(self):
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
        weeks = aggregate_weekly(dailies)
        self.assertEqual(weeks[-1].close, 9.2)
        self.assertEqual(weeks[-1].day, "20251231")

    def test_next_monday_includes_last_complete_week(self):
        dailies = [
            _bar("20251229", 9.0),
            _bar("20251230", 9.5),
            _bar("20251231", 9.2),
            _bar("20260105", 10.0),
            _bar("20260106", 11.0),
            _bar("20260107", 12.5),
            _bar("20260108", 13.0),
            _bar("20260109", 14.0),
            _bar("20260112", 15.0),
        ]
        weeks = aggregate_weekly(dailies)
        self.assertEqual(weeks[-1].close, 14.0)
        self.assertEqual(weeks[-1].day, "20260109")

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
        self.assertGreaterEqual(len(frame), 1)
        self.assertEqual(float(frame["close"][-1]), 9.2)
        last_dt = frame.index[-1]
        self.assertEqual(last_dt.strftime("%Y%m%d"), "20251231")
        self.assertEqual(last_dt.hour, 0)

    def test_native_weekly_drops_forming_week(self):
        dailies = [_bar("20260107", 12.5)]
        weekly = [_wbar("20260102", 9.2), _wbar("20260107", 12.5)]
        store = MarketStore(dailies, "600350.SH", weekly=weekly)
        frame = store.frame("1w", "20260107", count=8, fields=["close"])
        self.assertEqual(len(frame), 1)
        self.assertEqual(float(frame["close"][-1]), 9.2)

    def test_find_weekly_csv_prefers_code_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            daily = root / "600350_SH_1d_20220104_20260826.csv"
            weekly = root / "600350_SH_1w_20180105_20260821.csv"
            daily.write_text("x", encoding="utf-8")
            weekly.write_text("x", encoding="utf-8")
            found = find_weekly_csv(daily, "600350.SH")
            self.assertEqual(found, weekly)

    def test_compact_day(self):
        self.assertEqual(compact_day("2026-01-07 15:00:00"), "20260107")
        self.assertEqual(compact_day("20260107"), "20260107")


class IndexedSliceTests(unittest.TestCase):
    def test_daily_bisect_matches_linear(self):
        from market_csv import slice_bars

        days = [
            "20200102",
            "20200103",
            "20200106",
            "20200107",
            "20200108",
            "20200109",
            "20200110",
            "20200113",
            "20200114",
            "20200115",
        ]
        bars = [_bar(d, float(i + 1)) for i, d in enumerate(days)]
        store = MarketStore(bars, "600350.SH")
        for end, count, start in (
            ("20200115", None, ""),
            ("20200110", 3, ""),
            ("20200115", 5, "20200107"),
            ("20200103", 10, ""),
            ("20190101", 5, ""),
        ):
            old = slice_bars(bars, end, count=count, start_day=start)
            new = store.slice_daily(end, start_day=start, count=count)
            self.assertEqual([b.day for b in new], [b.day for b in old], (end, count, start))
            frame = store.frame("1d", end, count, fields=["close"], start_time=start)
            self.assertEqual(len(frame), len(old))
            if old:
                self.assertEqual(float(frame["close"][-1]), float(old[-1].close))

    def test_weekly_precompute_matches_aggregate(self):
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
        weeks = aggregate_weekly([b for b in dailies if b.day <= "20260107"], drop_forming=True, end_day="20260107")
        frame = store.frame("1w", "20260107", count=8, fields=["close"])
        self.assertEqual(len(frame), len(weeks))
        self.assertEqual(float(frame["close"][-1]), float(weeks[-1].close))


class QuietLogTests(unittest.TestCase):
    def test_drop_status_keep_trades(self):
        from run import _drop_quiet_line

        self.assertTrue(_drop_quiet_line("HlBand 20260701 0000 n1d=180 n1w=120 close=1.37"))
        self.assertTrue(_drop_quiet_line("HlBand w_bear streak=3/2 day=20260703"))
        self.assertFalse(_drop_quiet_line("HlBand BUY filled {'shares': 100}"))
        self.assertFalse(_drop_quiet_line("HlBand SELL by signal=stop"))
        self.assertFalse(_drop_quiet_line("HlBand pending_entry set signal=pullback_vol"))
        self.assertFalse(_drop_quiet_line("HlBand diag: d1_ok source=get_market_data_ex"))


class WorkerCountTests(unittest.TestCase):
    def test_resolve_workers(self):
        from run import resolve_workers

        self.assertEqual(resolve_workers(0, 1), 1)
        self.assertEqual(resolve_workers(1, 4), 1)
        self.assertEqual(resolve_workers(8, 3), 3)
        auto = resolve_workers(0, 16)
        self.assertGreaterEqual(auto, 1)
        self.assertLessEqual(auto, 8)


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


class PeekDailyMetaTests(unittest.TestCase):
    _HEADER = "stock,period,datetime,open,high,low,close,volume,amount"

    def _write_daily(
        self,
        path: Path,
        stock: str,
        days: list[str],
        *,
        encoding: str = "utf-8",
        bom: bool = False,
    ) -> None:
        lines = [self._HEADER]
        for d in days:
            lines.append("%s,1d,%s,1,1,1,1,100,100" % (stock, d))
        text = "\n".join(lines) + "\n"
        data = text.encode(encoding)
        if bom:
            data = b"\xef\xbb\xbf" + data
        path.write_bytes(data)

    def test_peek_first_last_and_count(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "AAA_SH_1d_20200101_20200103.csv"
            self._write_daily(path, "600000.SH", ["20200102", "20200103"])
            meta = peek_daily_csv_meta(path)
            self.assertEqual(meta["stock"], "600000.SH")
            self.assertEqual(meta["start"], "20200102")
            self.assertEqual(meta["end"], "20200103")
            self.assertEqual(meta["n"], 2)
            self.assertEqual(Path(meta["path"]), path.resolve())

    def test_peek_utf8_sig(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "600001_SH_1d_20210104_20210105.csv"
            self._write_daily(path, "600001.SH", ["20210104", "20210105"], bom=True)
            meta = peek_daily_csv_meta(path)
            self.assertEqual(meta["stock"], "600001.SH")
            self.assertEqual(meta["start"], "20210104")
            self.assertEqual(meta["end"], "20210105")
            self.assertEqual(meta["n"], 2)

    def test_peek_large_file_uses_tail(self):
        days: list[str] = []
        d = datetime.strptime("20180102", "%Y%m%d")
        while len(days) < 400:
            if d.weekday() < 5:
                days.append(d.strftime("%Y%m%d"))
            d += timedelta(days=1)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ("600000_SH_1d_%s_%s.csv" % (days[0], days[-1]))
            self._write_daily(path, "600000.SH", days)
            self.assertGreater(path.stat().st_size, 8192)
            meta = peek_daily_csv_meta(path)
            self.assertEqual(meta["stock"], "600000.SH")
            self.assertEqual(meta["start"], days[0])
            self.assertEqual(meta["end"], days[-1])
            self.assertEqual(meta["n"], len(days))


class DailyByStockTests(unittest.TestCase):
    def test_group_keeps_latest_end(self):
        from analyze import daily_csvs_by_stock, union_date_range

        header = "stock,period,datetime,open,high,low,close,volume,amount"

        def write_daily(path: Path, stock: str, days: list[str]) -> None:
            lines = [header]
            for d in days:
                lines.append(
                    "%s,1d,%s,1,1,1,1,100,100" % (stock, d)
                )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_daily(root / "AAA_SH_1d_20200101_20210101.csv", "600000.SH", ["20200102", "20210101"])
            write_daily(root / "AAA_SH_1d_20200101_20230101.csv", "600000.SH", ["20200102", "20220101", "20230101"])
            write_daily(root / "BBB_SH_1d_20210101_20220101.csv", "600001.SH", ["20210104", "20220101"])
            grouped = daily_csvs_by_stock(root)
            stocks = [m["stock"] for m in grouped]
            self.assertEqual(stocks, ["600000.SH", "600001.SH"])
            a = grouped[0]
            self.assertEqual(a["end"], "20230101")
            self.assertEqual(a["n"], 3)
            u0, u1 = union_date_range(grouped)
            self.assertEqual(u0, "20200102")
            self.assertEqual(u1, "20230101")


class BatchRunTests(unittest.TestCase):
    def test_missing_csv_does_not_stop_batch(self):
        from analyze import summarize_batch_row
        from run import run_batch

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            missing_a = root / "a.csv"
            missing_b = root / "b.csv"
            rows = run_batch([missing_a, missing_b], start="20200101", end="20201231")
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(not r["ok"] for r in rows))
            self.assertTrue(all(r["error"] for r in rows))
            summarized = [summarize_batch_row(r) for r in rows]
            self.assertEqual(summarized[0]["status"], "失败")

    def test_empty_walk_is_row_error(self):
        from run import run_batch

        header = "stock,period,datetime,open,high,low,close,volume,amount"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "600000_SH_1d_20200102_20200103.csv"
            path.write_text(
                header
                + "\n600000.SH,1d,20200102,1,1,1,1,100,100\n"
                + "600000.SH,1d,20200103,1,1,1,1,100,100\n",
                encoding="utf-8",
            )
            rows = run_batch([path], start="20220101", end="20220131")
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["ok"])
            self.assertIn("无行情交集", rows[0]["error"])
            self.assertEqual(rows[0]["stock"], "600000.SH")


if __name__ == "__main__":
    unittest.main()
