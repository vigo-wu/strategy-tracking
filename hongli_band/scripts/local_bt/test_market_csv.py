# coding: utf-8
"""周线：丢掉未收盘周，对齐 QMT 回测原生 1w。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

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

    def test_ohlcv_matches_frame_daily_and_weekly(self):
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
        frame = store.frame("1d", "20260107", count=3, fields=["open", "high", "low", "close", "volume"])
        tup = store.ohlcv("1d", "20260107", count=3)
        self.assertIsNotNone(tup)
        self.assertEqual(len(tup[3]), len(frame))
        self.assertEqual(float(tup[3][-1]), float(frame["close"][-1]))
        wframe = store.frame("1w", "20260107", count=8, fields=["close"])
        wtup = store.ohlcv("1w", "20260107", count=8)
        self.assertIsNotNone(wtup)
        self.assertEqual(len(wtup[3]), len(wframe))
        self.assertEqual(float(wtup[3][-1]), float(wframe["close"][-1]))
        self.assertEqual(float(wtup[3][-1]), 9.2)


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

    def test_odd_lot_sell_is_recorded(self):
        from trades_csv import TradeLedger

        book = TradeLedger("603659.SH")
        book.on_buy(1800, 51.0, "20230504150000")
        book.on_ex_rights("20230509150000", 1.45, 1.45)
        book.on_sell(2600, 37.3, "20230526150000")
        book.on_sell(10, 37.3, "20230527150000")
        sells = [r for r in book.rows if r[6] == "卖出"]
        self.assertEqual(len(sells), 2)
        self.assertEqual(sells[1][12], "10")
        self.assertEqual(len(book._lots), 0)

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

    def test_peek_skips_leading_zero_close_beyond_head(self):
        zeros: list[str] = []
        d = datetime.strptime("20070104", "%Y%m%d")
        while len(zeros) < 250:
            if d.weekday() < 5:
                zeros.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "000166_SZ_1d_20070104_20150127.csv"
            lines = [self._HEADER]
            for day in zeros:
                lines.append("000166.SZ,1d,%s,0.0,0.0,0.0,0.0,0.0,0.0" % day)
            lines.append("000166.SZ,1d,2015-01-26,11,13,10,12,100,100")
            lines.append("000166.SZ,1d,2015-01-27,11,12,10,11,100,100")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertGreater(path.stat().st_size, 8192)
            meta = peek_daily_csv_meta(path)
            self.assertEqual(meta["stock"], "000166.SZ")
            self.assertEqual(meta["start"], "20150126")
            self.assertEqual(meta["end"], "20150127")
            self.assertEqual(meta["n"], len(zeros) + 2)

    def test_peek_skips_trailing_zeros(self):
        zeros: list[str] = []
        d = datetime.strptime("20070104", "%Y%m%d")
        while len(zeros) < 250:
            if d.weekday() < 5:
                zeros.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "000166_SZ_1d_20070104_20150129.csv"
            lines = [self._HEADER]
            for day in zeros:
                lines.append("000166.SZ,1d,%s,0.0,0.0,0.0,0.0,0.0,0.0" % day)
            lines.append("000166.SZ,1d,2015-01-26,11,13,10,12,100,100")
            lines.append("000166.SZ,1d,2015-01-27,11,12,10,11,100,100")
            lines.append("000166.SZ,1d,2015-01-28,0.0,0.0,0.0,0.0,0.0,0.0")
            lines.append("000166.SZ,1d,2015-01-29,0.0,0.0,0.0,0.0,0.0,0.0")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertGreater(path.stat().st_size, 8192)
            meta = peek_daily_csv_meta(path)
            self.assertEqual(meta["stock"], "000166.SZ")
            self.assertEqual(meta["start"], "20150126")
            self.assertEqual(meta["end"], "20150127")


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


class YearSplitTests(unittest.TestCase):
    def test_iter_year_windows_span_and_clip(self):
        from analyze import iter_year_windows

        self.assertEqual(
            iter_year_windows("20180301", "20200630"),
            [
                ("2018", "20180301", "20181231"),
                ("2019", "20190101", "20191231"),
                ("2020", "20200101", "20200630"),
            ],
        )
        self.assertEqual(
            iter_year_windows("20200301", "20200630"),
            [("2020", "20200301", "20200630")],
        )

    def test_build_year_jobs_skips_no_overlap(self):
        from analyze import build_year_jobs

        metas = [
            {
                "stock": "600000.SH",
                "path": "/tmp/a.csv",
                "start": "20200102",
                "end": "20200103",
            }
        ]
        jobs = build_year_jobs(metas, "20180101", "20201231")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["year"], "2020")
        self.assertEqual(jobs[0]["start"], "20200102")
        self.assertEqual(jobs[0]["end"], "20200103")

    def test_year_weighted_win_rate(self):
        from analyze import summarize_batch_by_year

        rows = [
            {
                "year": "2020",
                "ok": True,
                "n_buy": 1,
                "win_rate": 100.0,
                "avg_ret": 10.0,
                "sum_pnl": 1.0,
                "max_win": 10.0,
                "max_loss": 0.0,
            },
            {
                "year": "2020",
                "ok": True,
                "n_buy": 3,
                "win_rate": 0.0,
                "avg_ret": -2.0,
                "sum_pnl": -1.0,
                "max_win": 0.0,
                "max_loss": -5.0,
            },
        ]
        agg = summarize_batch_by_year(rows)
        self.assertEqual(len(agg), 1)
        self.assertEqual(agg[0]["n_buy"], 4)
        self.assertAlmostEqual(agg[0]["win_rate"], 25.0)
        self.assertAlmostEqual(agg[0]["avg_ret"], 1.0)
        self.assertAlmostEqual(agg[0]["sum_pnl"], 0.0)
        self.assertAlmostEqual(agg[0]["max_win"], 10.0)
        self.assertAlmostEqual(agg[0]["max_loss"], -5.0)

    def test_backtest_one_result_year_in_log_name(self):
        from run import backtest_one_result

        header = "stock,period,datetime,open,high,low,close,volume,amount"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "600000_SH_1d_20200102_20200103.csv"
            path.write_text(
                header
                + "\n600000.SH,1d,20200102,1,1,1,1,100,100\n"
                + "600000.SH,1d,20200103,1,1,1,1,100,100\n",
                encoding="utf-8",
            )
            out = Path(td) / "out"
            row = backtest_one_result(
                path,
                start="20200102",
                end="20200103",
                out_dir=out,
                year="2020",
            )
            self.assertTrue(row.get("ok"), row.get("error"))
            self.assertEqual(row.get("year"), "2020")
            self.assertIn("2020", Path(row["log"]).name)
            self.assertNotIn("SMA", Path(row["log"]).name)
            self.assertNotIn("EMA", Path(row["log"]).name)
            self.assertTrue(Path(row["log"]).is_file())

    def test_backtest_one_result_ma_type_in_log_and_banner(self):
        from run import backtest_one_result

        header = "stock,period,datetime,open,high,low,close,volume,amount"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "600000_SH_1d_20200102_20200103.csv"
            path.write_text(
                header
                + "\n600000.SH,1d,20200102,1,1,1,1,100,100\n"
                + "600000.SH,1d,20200103,1,1,1,1,100,100\n",
                encoding="utf-8",
            )
            out = Path(td) / "out"
            row = backtest_one_result(
                path,
                start="20200102",
                end="20200103",
                out_dir=out,
                year="2020",
                ma_type="SMA",
            )
            self.assertTrue(row.get("ok"), row.get("error"))
            self.assertEqual(row.get("ma_type"), "SMA")
            name = Path(row["log"]).name
            self.assertIn("2020", name)
            self.assertIn("SMA", name)
            text = Path(row["log"]).read_text(encoding="utf-8")
            self.assertIn("ma_type= SMA", text)


class MaCompareTests(unittest.TestCase):
    def test_pick_ma_winner_higher_pnl(self):
        from analyze import pick_ma_winner

        r = pick_ma_winner(
            {"ok": True, "sum_pnl": 10.0, "win_rate": 80.0},
            {"ok": True, "sum_pnl": 20.0, "win_rate": 40.0},
        )
        self.assertEqual(r["winner"], "EMA")
        self.assertEqual(r["label"], "EMA")
        self.assertEqual(r["why"], "compare")
        self.assertAlmostEqual(r["pnl_delta"], 10.0)

    def test_pick_ma_winner_close_uses_win_rate(self):
        from analyze import pick_ma_winner

        r = pick_ma_winner(
            {"ok": True, "sum_pnl": 10.0, "win_rate": 80.0},
            {"ok": True, "sum_pnl": 10.4, "win_rate": 20.0},
        )
        self.assertEqual(r["label"], "接近")
        self.assertEqual(r["why"], "compare_close")
        self.assertEqual(r["winner"], "SMA")

    def test_pick_ma_winner_close_tie_ema(self):
        from analyze import pick_ma_winner

        r = pick_ma_winner(
            {"ok": True, "sum_pnl": 10.0, "win_rate": 50.0},
            {"ok": True, "sum_pnl": 10.0, "win_rate": 50.0},
        )
        self.assertEqual(r["label"], "接近")
        self.assertEqual(r["winner"], "EMA")

    def test_pick_ma_winner_both_fail(self):
        from analyze import pick_ma_winner

        r = pick_ma_winner({"ok": False, "sum_pnl": None}, {"ok": False})
        self.assertEqual(r["winner"], "")
        self.assertEqual(r["label"], "")
        self.assertEqual(r["why"], "")


class DetailReTests(unittest.TestCase):
    def test_parse_year_and_ma(self):
        from stock_select import DETAIL_RE

        m = DETAIL_RE.match("local_bt_600350_SH_2024_SMA_操作明细.csv")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "600350")
        self.assertEqual(m.group(2).upper(), "SH")
        self.assertEqual(m.group(3), "2024")
        self.assertEqual(m.group(4).upper(), "SMA")

    def test_parse_ma_without_year(self):
        from stock_select import DETAIL_RE

        m = DETAIL_RE.match("local_bt_600350_SH_EMA_操作明细.csv")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(3))
        self.assertEqual(m.group(4).upper(), "EMA")

    def test_parse_year_without_ma(self):
        from stock_select import DETAIL_RE

        m = DETAIL_RE.match("local_bt_600350_SH_2024_操作明细.csv")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(3), "2024")
        self.assertIsNone(m.group(4))


class ResolveMaTests(unittest.TestCase):
    def test_compare_winner_not_plain_file(self):
        from stock_select import _resolve_stock_ma

        rec = {
            "by_ma": {
                "SMA": {
                    "years": {"2024": {"sum_pnl": 100.0, "n_buy": 2, "win_rate": 50.0}},
                    "recent": None,
                },
                "EMA": {
                    "years": {"2024": {"sum_pnl": 10.0, "n_buy": 2, "win_rate": 50.0}},
                    "recent": None,
                },
                "": {
                    "years": {"2024": {"sum_pnl": 999.0, "n_buy": 1, "win_rate": 10.0}},
                    "recent": None,
                },
            }
        }
        _resolve_stock_ma(rec)
        self.assertEqual(rec["ma_type_suggest"], "SMA")
        self.assertEqual(rec["ma_type_why"], "compare")
        self.assertEqual(rec["years"]["2024"]["sum_pnl"], 100.0)

    def test_no_compare_empty_suggest(self):
        from stock_select import _resolve_stock_ma

        rec = {
            "by_ma": {
                "": {
                    "years": {"2024": {"sum_pnl": 1.0, "n_buy": 1, "win_rate": 50.0}},
                    "recent": None,
                }
            }
        }
        _resolve_stock_ma(rec)
        self.assertEqual(rec["ma_type_suggest"], "")
        self.assertEqual(rec["ma_type_why"], "no_compare")

    def test_window_flips_ma_winner_without_mutating_buckets(self):
        from stock_select import _resolve_stock_ma

        rec = {
            "by_ma": {
                "SMA": {
                    "years": {
                        "2021": {"sum_pnl": 1000.0, "n_buy": 2, "win_rate": 50.0},
                        "2024": {"sum_pnl": 1.0, "n_buy": 2, "win_rate": 50.0},
                        "2025": {"sum_pnl": 1.0, "n_buy": 2, "win_rate": 50.0},
                    },
                    "recent": None,
                },
                "EMA": {
                    "years": {
                        "2021": {"sum_pnl": 1.0, "n_buy": 2, "win_rate": 50.0},
                        "2024": {"sum_pnl": 100.0, "n_buy": 2, "win_rate": 50.0},
                        "2025": {"sum_pnl": 100.0, "n_buy": 2, "win_rate": 50.0},
                    },
                    "recent": None,
                },
            }
        }
        raw_sma = dict(rec["by_ma"]["SMA"]["years"])
        _resolve_stock_ma(rec)
        self.assertEqual(rec["ma_type_suggest"], "SMA")
        windowed = {"by_ma": rec["by_ma"]}
        _resolve_stock_ma(windowed, years_keep=("2024", "2025"))
        self.assertEqual(windowed["ma_type_suggest"], "EMA")
        self.assertEqual(set(windowed["years"]), {"2024", "2025"})
        self.assertEqual(rec["by_ma"]["SMA"]["years"], raw_sma)
        self.assertIn("2021", rec["by_ma"]["EMA"]["years"])

    def test_score_universe_uses_compare_not_book(self):
        from stock_select import score_universe

        year_kpi = {
            "n_buy": 10,
            "sum_pnl": 100.0,
            "win_rate": 60.0,
            "avg_ret": 1.0,
            "max_win": 2.0,
            "max_loss": -1.0,
            "gross_profit": 120.0,
            "gross_loss": -20.0,
            "profit_factor": 6.0,
            "max_dd": -0.1,
            "avg_hold_days": 5.0,
            "max_win_pnl": 50.0,
            "sell": {"trail_stop": 3},
            "buy": {},
            "skip": {},
            "n_bars": 200,
        }
        scanned = {
            "book": {"600000.SH": "EMA"},
            "score_years": ("2024",),
            "coverage": {"n_stock": 1, "2024": 1},
            "stocks": {
                "600000.SH": {
                    "years": {"2024": year_kpi},
                    "recent": None,
                    "style": {"vol_ann": 0.1, "touch_ma20": 0.9},
                    "error": "",
                    "ma_type_suggest": "SMA",
                    "ma_type_why": "compare",
                    "ma_pnl_sma": 100.0,
                    "ma_pnl_ema": 10.0,
                    "ma_pnl_delta": -90.0,
                }
            },
        }
        scored = score_universe(
            scanned,
            filters={
                "min_n_buy": 0,
                "min_years_traded_ratio": 0.0,
                "min_pos_ratio": 0.0,
                "max_win_pnl_share": 1.0,
                "vol_drop_top": 0.0,
                "top_n": 6,
            },
        )
        row = scored["df"].iloc[0]
        self.assertEqual(row["ma_type_suggest"], "SMA")
        self.assertEqual(row["ma_type_why"], "compare")
        self.assertAlmostEqual(float(row["ma_pnl_delta"]), -90.0)


class TestScoreYears(unittest.TestCase):
    def test_infer_score_years_keeps_incomplete_max_year(self):
        from stock_select import infer_score_years

        stocks = {
            "600000.SH": {"years": {"2024": {}, "2025": {}, "2026": {}}},
            "000001.SZ": {"years": {"2025": {}, "2026": {}}},
        }
        self.assertEqual(infer_score_years(stocks), ("2024", "2025", "2026"))

    def test_infer_score_years_unions_nested_buckets(self):
        from stock_select import infer_score_years

        stocks = {
            "600000.SH": {
                "years": {},
                "by_ma": {},
                "by_div": {
                    "front": {
                        "years": {},
                        "by_ma": {
                            "SMA": {"years": {"2021": {}, "2024": {}}},
                            "EMA": {"years": {"2025": {}}},
                        },
                    }
                },
            }
        }
        self.assertEqual(infer_score_years(stocks), ("2021", "2024", "2025"))

    def test_infer_score_years_empty(self):
        from stock_select import infer_score_years

        self.assertEqual(infer_score_years({}), ())


class ScoreWindowTests(unittest.TestCase):
    def _kpi(self, pnl: float) -> dict:
        return {
            "n_buy": 10,
            "sum_pnl": pnl,
            "win_rate": 60.0,
            "avg_ret": 1.0,
            "max_win": 2.0,
            "max_loss": -1.0,
            "gross_profit": max(pnl, 1.0),
            "gross_loss": -1.0,
            "profit_factor": 6.0,
            "max_dd": -0.1,
            "avg_hold_days": 5.0,
            "max_win_pnl": 1.0,
            "sell": {"trail_stop": 3},
            "buy": {},
            "skip": {},
            "n_bars": 200,
        }

    def _loose(self) -> dict:
        return {
            "min_n_buy": 0,
            "min_years_traded_ratio": 0.0,
            "min_pos_ratio": 0.0,
            "max_win_pnl_share": 1.0,
            "vol_drop_top": 0.0,
            "top_n": 6,
        }

    def test_score_universe_window_flips_ma_and_keeps_cache(self):
        from stock_select import score_universe

        scanned = {
            "book": {},
            "stocks": {
                "600000.SH": {
                    "by_ma": {
                        "SMA": {
                            "years": {
                                "2021": self._kpi(1000.0),
                                "2024": self._kpi(1.0),
                                "2025": self._kpi(1.0),
                            },
                            "recent": None,
                        },
                        "EMA": {
                            "years": {
                                "2021": self._kpi(1.0),
                                "2024": self._kpi(100.0),
                                "2025": self._kpi(100.0),
                            },
                            "recent": None,
                        },
                    },
                    "style": {"vol_ann": 0.1, "touch_ma20": 0.9},
                    "error": "",
                }
            },
        }
        full = score_universe(scanned, filters=self._loose(), score_years=("2021", "2024", "2025"))
        late = score_universe(scanned, filters=self._loose(), score_years=("2024", "2025"))
        self.assertEqual(full["df"].iloc[0]["ma_type_suggest"], "SMA")
        self.assertEqual(late["df"].iloc[0]["ma_type_suggest"], "EMA")
        rec = scanned["stocks"]["600000.SH"]
        self.assertNotIn("ma_type_suggest", rec)
        self.assertIn("2021", rec["by_ma"]["SMA"]["years"])
        self.assertEqual(set(late["score_years"]), {"2024", "2025"})

    def test_score_universe_window_flips_div_and_style(self):
        from stock_select import score_universe

        scanned = {
            "book": {},
            "stocks": {
                "600000.SH": {
                    "by_div": {
                        "front": {
                            "by_ma": {
                                "SMA": {
                                    "years": {
                                        "2023": self._kpi(1000.0),
                                        "2024": self._kpi(10.0),
                                    },
                                    "recent": None,
                                },
                                "EMA": {
                                    "years": {
                                        "2023": self._kpi(1.0),
                                        "2024": self._kpi(1.0),
                                    },
                                    "recent": None,
                                },
                            },
                            "style": {"vol_ann": 0.2, "touch_ma20": 0.5, "n_close": 80},
                        },
                        "front_ratio": {
                            "by_ma": {
                                "SMA": {
                                    "years": {
                                        "2023": self._kpi(10.0),
                                        "2024": self._kpi(100.0),
                                    },
                                    "recent": None,
                                },
                                "EMA": {
                                    "years": {
                                        "2023": self._kpi(1.0),
                                        "2024": self._kpi(1.0),
                                    },
                                    "recent": None,
                                },
                            },
                            "style": {"vol_ann": 0.11, "touch_ma20": 0.8, "n_close": 80},
                        },
                    },
                    "style": {"vol_ann": 0.2, "touch_ma20": 0.5, "n_close": 80},
                    "error": "",
                }
            },
        }
        full = score_universe(scanned, filters=self._loose(), score_years=("2023", "2024"))
        late = score_universe(scanned, filters=self._loose(), score_years=("2024",))
        self.assertEqual(full["df"].iloc[0]["div_type_suggest"], "front")
        self.assertAlmostEqual(float(full["df"].iloc[0]["vol_ann"]), 0.2)
        self.assertEqual(late["df"].iloc[0]["div_type_suggest"], "front_ratio")
        self.assertAlmostEqual(float(late["df"].iloc[0]["vol_ann"]), 0.11)
        self.assertEqual(scanned["stocks"]["600000.SH"]["style"]["vol_ann"], 0.2)

    def test_years_in_range(self):
        from stock_select import years_in_range

        avail = ("2021", "2022", "2023", "2024")
        self.assertEqual(years_in_range(avail, "2023", "2024"), ("2023", "2024"))
        self.assertEqual(years_in_range(avail, "2022", ""), ("2022", "2023", "2024"))


class PerYearBuyFilterTests(unittest.TestCase):
    def _kpi(self, n_buy: int, pnl: float = 10.0) -> dict:
        return {
            "n_buy": n_buy,
            "sum_pnl": pnl,
            "win_rate": 60.0,
            "avg_ret": 1.0,
            "max_win": 2.0,
            "max_loss": -1.0,
            "gross_profit": 20.0,
            "gross_loss": -1.0,
            "profit_factor": 6.0,
            "max_dd": -0.1,
            "avg_hold_days": 5.0,
            "max_win_pnl": 1.0,
            "sell": {"trail_stop": 3},
            "buy": {},
            "skip": {},
            "n_bars": 200,
        }

    def _loose(self, **extra) -> dict:
        flt = {
            "min_n_buy": 0,
            "min_n_buy_per_year": 0,
            "min_years_traded_ratio": 0.0,
            "min_pos_ratio": 0.0,
            "max_win_pnl_share": 1.0,
            "vol_drop_top": 0.0,
            "top_n": 6,
        }
        flt.update(extra)
        return flt

    def _scanned(self, years: dict) -> dict:
        return {
            "book": {},
            "stocks": {
                "600000.SH": {
                    "years": years,
                    "recent": None,
                    "style": {"vol_ann": 0.1, "touch_ma20": 0.9},
                    "error": "",
                    "ma_type_suggest": "SMA",
                    "ma_type_why": "compare",
                }
            },
        }

    def test_thin_year_fails_when_threshold_set(self):
        from stock_select import score_universe

        scanned = self._scanned({"2023": self._kpi(5), "2024": self._kpi(1)})
        fail = score_universe(
            scanned,
            filters=self._loose(min_n_buy_per_year=2),
            score_years=("2023", "2024"),
        )
        row = fail["df"].iloc[0]
        self.assertFalse(bool(row["passed"]))
        self.assertIn("每年轮次不足", str(row["fail_reason"]))
        self.assertEqual(int(row["n_buy_year_min"]), 1)

        ok = score_universe(
            scanned,
            filters=self._loose(min_n_buy_per_year=0),
            score_years=("2023", "2024"),
        )
        self.assertTrue(bool(ok["df"].iloc[0]["passed"]))

    def test_missing_year_counts_as_zero(self):
        from stock_select import score_universe

        scanned = {
            "book": {},
            "stocks": {
                "600000.SH": {
                    "years": {"2023": self._kpi(5)},
                    "recent": None,
                    "style": {"vol_ann": 0.1, "touch_ma20": 0.9},
                    "error": "",
                    "ma_type_suggest": "SMA",
                    "ma_type_why": "compare",
                },
                "000001.SZ": {
                    "years": {"2023": self._kpi(5), "2024": self._kpi(5)},
                    "recent": None,
                    "style": {"vol_ann": 0.1, "touch_ma20": 0.9},
                    "error": "",
                    "ma_type_suggest": "SMA",
                    "ma_type_why": "compare",
                },
            },
        }
        scored = score_universe(
            scanned,
            filters=self._loose(min_n_buy_per_year=2),
            score_years=("2023", "2024"),
        )
        row = scored["df"][scored["df"]["stock"] == "600000.SH"].iloc[0]
        self.assertFalse(bool(row["passed"]))
        self.assertIn("每年轮次不足", str(row["fail_reason"]))
        self.assertEqual(int(row["n_buy_year_min"]), 0)
        peer = scored["df"][scored["df"]["stock"] == "000001.SZ"].iloc[0]
        self.assertTrue(bool(peer["passed"]))

    def test_traded_year_ratio_fails_sparse_coverage(self):
        from stock_select import score_universe

        scanned = self._scanned(
            {
                "2021": self._kpi(5),
                "2022": self._kpi(0),
                "2023": self._kpi(0),
                "2024": self._kpi(0),
            }
        )
        fail = score_universe(
            scanned,
            filters=self._loose(min_years_traded_ratio=0.50),
            score_years=("2021", "2022", "2023", "2024"),
        )
        row = fail["df"].iloc[0]
        self.assertFalse(bool(row["passed"]))
        self.assertIn("成交年占比不足", str(row["fail_reason"]))

        ok = score_universe(
            scanned,
            filters=self._loose(min_years_traded_ratio=0.0),
            score_years=("2021", "2022", "2023", "2024"),
        )
        self.assertTrue(bool(ok["df"].iloc[0]["passed"]))

    def test_pos_ratio_only_fails_few_profit_years(self):
        from stock_select import score_universe

        scanned = self._scanned(
            {
                "2020": self._kpi(5, 10.0),
                "2021": self._kpi(5, 10.0),
                "2022": self._kpi(5, -1.0),
                "2023": self._kpi(5, -1.0),
                "2024": self._kpi(5, -1.0),
            }
        )
        fail = score_universe(
            scanned,
            filters=self._loose(min_pos_ratio=0.50),
            score_years=("2020", "2021", "2022", "2023", "2024"),
        )
        row = fail["df"].iloc[0]
        self.assertFalse(bool(row["passed"]))
        self.assertIn("盈利年不稳定", str(row["fail_reason"]))
        self.assertEqual(int(row["n_years_pos"]), 2)
        self.assertEqual(int(row["n_years_traded"]), 5)


class TypedDirTests(unittest.TestCase):
    def test_resolve_typed_dir_appends(self):
        from analyze import DEFAULT_DIVIDEND_TYPE, resolve_typed_dir

        root = Path("D:/data/csv")
        self.assertEqual(resolve_typed_dir(root, "front"), root / "front")
        self.assertEqual(resolve_typed_dir(root, ""), root / DEFAULT_DIVIDEND_TYPE)

    def test_resolve_typed_dir_no_double_append(self):
        from analyze import resolve_typed_dir

        leaf = Path("D:/data/csv/front")
        self.assertEqual(resolve_typed_dir(leaf, "front"), leaf)

    def test_resolve_typed_dir_invalid_falls_back(self):
        from analyze import DEFAULT_DIVIDEND_TYPE, resolve_typed_dir

        root = Path("D:/data/report")
        self.assertEqual(resolve_typed_dir(root, "nope"), root / DEFAULT_DIVIDEND_TYPE)
        self.assertEqual(resolve_typed_dir(root, "FOLLOW"), root / DEFAULT_DIVIDEND_TYPE)

    def test_resolve_typed_dir_nested_snapshot(self):
        from analyze import resolve_typed_dir

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            older = root / "20070104_20200101" / "front_ratio"
            newer = root / "20070104_20260828" / "front_ratio"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            self.assertEqual(resolve_typed_dir(root, "front_ratio"), newer)

    def test_daily_csv_for_stock_uses_filename_index(self):
        from analyze import daily_csv_for_stock

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            keep = root / "600350_SH_1d_20100101_20200101.csv"
            newer = root / "600350_SH_1d_20100101_20240101.csv"
            keep.write_text("x", encoding="utf-8")
            newer.write_text("y", encoding="utf-8")
            found = daily_csv_for_stock(root, "600350.SH")
            self.assertEqual(found, newer)

    def test_list_detail_csvs_stays_in_typed_dir(self):
        from analyze import list_detail_csvs

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            front = root / "front"
            back = root / "back"
            front.mkdir()
            back.mkdir()
            keep = front / "local_bt_600000_SH_操作明细.csv"
            skip = back / "local_bt_600001_SH_操作明细.csv"
            keep.write_text("x", encoding="utf-8")
            skip.write_text("y", encoding="utf-8")
            found = list_detail_csvs(front, include_hist=False)
            self.assertEqual([p.name for p in found], [keep.name])

    def test_list_detail_csvs_union_of_dirs(self):
        from analyze import list_detail_csvs

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            front = root / "front"
            ratio = root / "front_ratio"
            front.mkdir()
            ratio.mkdir()
            a = front / "local_bt_600000_SH_操作明细.csv"
            b = ratio / "local_bt_600001_SH_操作明细.csv"
            a.write_text("x", encoding="utf-8")
            b.write_text("y", encoding="utf-8")
            found = list_detail_csvs([front, ratio], include_hist=False)
            self.assertEqual(sorted(p.name for p in found), sorted([a.name, b.name]))

    def test_typed_report_dirs_scans_siblings(self):
        from analyze import typed_report_dirs, typed_sibling_dirs

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "front").mkdir()
            (root / "front_ratio").mkdir()
            leaf = root / "front_ratio"
            sibs = typed_report_dirs(leaf)
            self.assertEqual(typed_sibling_dirs(leaf), sibs)
            self.assertEqual([d for d, _p in sibs], ["front", "front_ratio"])


class StockFilterTokensTests(unittest.TestCase):
    def test_comma_space_and_runs(self):
        from analyze import parse_stock_filter_tokens, stock_matches_filter

        self.assertEqual(parse_stock_filter_tokens("600350,600028"), ["600350", "600028"])
        self.assertEqual(parse_stock_filter_tokens("600350  600028"), ["600350", "600028"])
        self.assertEqual(
            parse_stock_filter_tokens("600350,,  , 600028"),
            ["600350", "600028"],
        )
        self.assertEqual(
            parse_stock_filter_tokens("600350.SH，601939"),
            ["600350.SH", "601939"],
        )
        stocks = ["600350.SH", "600028.SH", "601939.SH"]
        toks = parse_stock_filter_tokens("600350,  600028")
        self.assertEqual(
            [s for s in stocks if stock_matches_filter(s, toks)],
            ["600350.SH", "600028.SH"],
        )
        self.assertTrue(stock_matches_filter("600350.SH", []))
        self.assertEqual(parse_stock_filter_tokens(" , , "), [])
        self.assertTrue(stock_matches_filter("600350.SH", ["600350_SH"]))


class MatchDailyForDetailTests(unittest.TestCase):
    def _write_daily(self, folder: Path, stock: str) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        name = "%s_1d_20200102_20200103.csv" % stock.replace(".", "_")
        path = folder / name
        path.write_text(
            "stock,period,datetime,open,high,low,close,volume,amount\n"
            "%s,1d,20200102,1,1,1,1,100,100\n"
            "%s,1d,20200103,1,1,1,1,100,100\n"
            % (stock, stock),
            encoding="utf-8",
        )
        return path

    def test_stock_from_local_bt_filename(self):
        from analyze import stock_from_detail_path

        p = Path("report/front/local_bt_600350_SH_2024_SMA_操作明细.csv")
        self.assertEqual(stock_from_detail_path(p, read_csv=False), "600350.SH")

    def test_div_from_report_folder(self):
        from analyze import dividend_from_detail_path

        p = Path("report/front/local_bt_600350_SH_操作明细.csv")
        self.assertEqual(dividend_from_detail_path(p), "front")
        hist = Path("hongli_band") / "回测记录" / "foo.csv"
        self.assertEqual(dividend_from_detail_path(hist), "")

    def test_front_detail_hits_front_not_ratio(self):
        from analyze import match_daily_csv_for_detail

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            csv_root = root / "csv"
            front_d = self._write_daily(csv_root / "front", "600350.SH")
            ratio_d = self._write_daily(csv_root / "front_ratio", "600350.SH")
            detail = root / "report" / "front" / "local_bt_600350_SH_2024_SMA_操作明细.csv"
            detail.parent.mkdir(parents=True, exist_ok=True)
            detail.write_text("x", encoding="utf-8")
            found = match_daily_csv_for_detail(
                detail,
                csv_root,
                fallback_divs=["front_ratio"],
            )
            self.assertIsNotNone(found)
            self.assertEqual(found.resolve(), front_d.resolve())
            self.assertNotEqual(found.resolve(), ratio_d.resolve())

    def test_hist_uses_fallback_div(self):
        from analyze import match_daily_csv_for_detail

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            csv_root = root / "csv"
            ratio_d = self._write_daily(csv_root / "front_ratio", "600350.SH")
            self._write_daily(csv_root / "front", "600350.SH")
            detail = root / "回测记录" / "local_bt_600350_SH_操作明细.csv"
            detail.parent.mkdir(parents=True, exist_ok=True)
            detail.write_text("x", encoding="utf-8")
            found = match_daily_csv_for_detail(
                detail,
                csv_root,
                fallback_divs=["front_ratio"],
            )
            self.assertIsNotNone(found)
            self.assertEqual(found.resolve(), ratio_d.resolve())

    def test_stock_from_code_column(self):
        from analyze import stock_from_detail_path

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "export.csv"
            p.write_text("代码,名称\n600350,山东高速\n", encoding="utf-8")
            self.assertEqual(stock_from_detail_path(p), "600350")


class ChartMaFrameTests(unittest.TestCase):
    def test_ema_matches_strategy_seed(self):
        import numpy as np
        from analyze import price_ma

        c = np.arange(1.0, 11.0)
        ema = price_ma(c, 3, "EMA")
        self.assertIsNotNone(ema)
        self.assertTrue(np.isnan(ema[0]) and np.isnan(ema[1]))
        self.assertAlmostEqual(float(ema[2]), 2.0)
        self.assertAlmostEqual(float(ema[3]), 3.0)
        self.assertAlmostEqual(float(ema[4]), 4.0)
        sma = price_ma(c, 3, "SMA")
        self.assertAlmostEqual(float(sma[2]), 2.0)
        self.assertAlmostEqual(float(sma[3]), 3.0)

    def test_filename_ma_kind(self):
        from analyze import resolve_chart_ma_kind

        p = Path("local_bt_600350_SH_2024_SMA_操作明细.csv")
        self.assertEqual(resolve_chart_ma_kind(detail_path=p), "SMA")
        self.assertEqual(resolve_chart_ma_kind(ma_kind="EMA", detail_path=p), "EMA")

    def test_daily_and_weekly_ma_columns(self):
        from analyze import ohlc_frame_for_chart

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "600350_SH_1d_20180102_20181231.csv"
            d = datetime(2018, 1, 2)
            rows = ["stock,period,datetime,open,high,low,close,volume,amount"]
            days = []
            while len(days) < 250:
                if d.weekday() < 5:
                    px = 10.0 + 0.01 * len(days)
                    day = d.strftime("%Y%m%d")
                    rows.append(
                        "600350.SH,1d,%s,%.4f,%.4f,%.4f,%.4f,100,100" % (day, px, px, px, px)
                    )
                    days.append(day)
                d += timedelta(days=1)
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            start, end = days[80], days[-1]
            daily = ohlc_frame_for_chart(
                path,
                start=start,
                end=end,
                stock="600350.SH",
                period="1d",
                ma_kind="EMA",
            )
            self.assertIn("MA20", daily.columns)
            self.assertIn("MA60", daily.columns)
            self.assertFalse(pd.isna(daily["MA20"].iloc[0]))
            self.assertFalse(pd.isna(daily["MA60"].iloc[0]))
            weekly = ohlc_frame_for_chart(
                path,
                start=start,
                end=end,
                stock="600350.SH",
                period="1w",
                ma_kind="EMA",
            )
            self.assertIn("MA5", weekly.columns)
            self.assertIn("MA13", weekly.columns)
            self.assertIn("MA34", weekly.columns)
            self.assertGreater(len(weekly), 5)

    def test_weekly_maps_midweek_buy(self):
        from analyze import map_day_to_bar

        idx = pd.to_datetime(["20260102", "20260109"])
        df = pd.DataFrame(
            {"Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0], "Close": [1.0, 2.0]},
            index=idx,
        )
        hit = map_day_to_bar(df, "20260107", "1w")
        self.assertEqual(pd.Timestamp(hit).normalize(), pd.Timestamp("20260109"))
        miss = map_day_to_bar(df, "20251220", "1w")
        self.assertIsNone(miss)


class ParseDividendTypesTests(unittest.TestCase):
    def test_comma_and_space(self):
        from analyze import parse_dividend_types

        self.assertEqual(parse_dividend_types("front,front_ratio"), ["front", "front_ratio"])
        self.assertEqual(parse_dividend_types("front_ratio front"), ["front", "front_ratio"])
        self.assertEqual(parse_dividend_types(["back", "front", "front"]), ["front", "back"])

    def test_empty_defaults(self):
        from analyze import DEFAULT_DIVIDEND_TYPE, parse_dividend_types

        self.assertEqual(parse_dividend_types(""), [DEFAULT_DIVIDEND_TYPE])
        self.assertEqual(parse_dividend_types(None), [DEFAULT_DIVIDEND_TYPE])

    def test_all_invalid_empty(self):
        from analyze import parse_dividend_types

        self.assertEqual(parse_dividend_types("nope,FOLLOW"), [])


class PickDivWinnerTests(unittest.TestCase):
    def test_higher_pnl_wins(self):
        from analyze import pick_div_winner

        r = pick_div_winner(
            {
                "front": {"ok": True, "sum_pnl": 80.0, "win_rate": 40.0},
                "front_ratio": {"ok": True, "sum_pnl": 20.0, "win_rate": 90.0},
            }
        )
        self.assertEqual(r["winner"], "front")
        self.assertEqual(r["why"], "compare")

    def test_close_uses_win_rate(self):
        from analyze import pick_div_winner

        r = pick_div_winner(
            {
                "front": {"ok": True, "sum_pnl": 10.0, "win_rate": 80.0},
                "front_ratio": {"ok": True, "sum_pnl": 10.4, "win_rate": 20.0},
            }
        )
        self.assertEqual(r["why"], "compare_close")
        self.assertEqual(r["winner"], "front")

    def test_tie_prefers_front_ratio(self):
        from analyze import pick_div_winner

        r = pick_div_winner(
            {
                "front": {"ok": True, "sum_pnl": 10.0, "win_rate": 50.0},
                "none": {"ok": True, "sum_pnl": 10.0, "win_rate": 50.0},
                "front_ratio": {"ok": True, "sum_pnl": 10.0, "win_rate": 50.0},
            }
        )
        self.assertEqual(r["why"], "compare_close")
        self.assertEqual(r["winner"], "front_ratio")

    def test_single_div(self):
        from analyze import pick_div_winner

        r = pick_div_winner({"back": {"ok": True, "sum_pnl": 1.0, "win_rate": 10.0}})
        self.assertEqual(r["winner"], "back")
        self.assertEqual(r["why"], "single_div")


class DivCompareViewTests(unittest.TestCase):
    def test_div_compare_dataframe_marks_winner(self):
        from analyze import div_compare_dataframe

        df = div_compare_dataframe(
            {
                "front": {"ok": True, "n_buy": 2, "sum_pnl": 80.0, "win_rate": 40.0, "avg_ret": 1.0},
                "front_ratio": {"ok": True, "n_buy": 3, "sum_pnl": 20.0, "win_rate": 90.0, "avg_ret": 0.5},
            },
            stock="600000.SH",
        )
        self.assertEqual(
            list(df.columns),
            ["代码", "名称", "复权", "轮次", "总盈亏", "胜率", "平均收益%", "更优"],
        )
        self.assertEqual(list(df["复权"]), ["前复权", "等比前复权"])
        self.assertEqual(list(df["更优"]), ["是", ""])

    def test_pair_ma_keeps_dividend_type(self):
        from analyze import pair_ma_batch_rows

        rows = [
            {
                "stock": "600000.SH",
                "year": "2024",
                "dividend_type": "front",
                "ma_type": "SMA",
                "ok": True,
                "n_buy": 1,
                "sum_pnl": 10.0,
                "win_rate": 100.0,
            },
            {
                "stock": "600000.SH",
                "year": "2024",
                "dividend_type": "front",
                "ma_type": "EMA",
                "ok": True,
                "n_buy": 1,
                "sum_pnl": 12.0,
                "win_rate": 100.0,
            },
            {
                "stock": "600000.SH",
                "year": "2024",
                "dividend_type": "front_ratio",
                "ma_type": "SMA",
                "ok": True,
                "n_buy": 1,
                "sum_pnl": 1.0,
                "win_rate": 0.0,
            },
            {
                "stock": "600000.SH",
                "year": "2024",
                "dividend_type": "front_ratio",
                "ma_type": "EMA",
                "ok": True,
                "n_buy": 1,
                "sum_pnl": 2.0,
                "win_rate": 0.0,
            },
        ]
        pairs = pair_ma_batch_rows(rows)
        self.assertEqual(len(pairs), 2)
        self.assertEqual({p["dividend_type"] for p in pairs}, {"front", "front_ratio"})

    def test_ma_compare_dataframe_adds_div_col(self):
        from analyze import ma_compare_dataframe, pair_ma_batch_rows

        rows = [
            {
                "stock": "A",
                "year": "",
                "dividend_type": "front",
                "ma_type": "SMA",
                "ok": True,
                "n_buy": 1,
                "sum_pnl": 1.0,
                "win_rate": 50.0,
            },
            {
                "stock": "A",
                "year": "",
                "dividend_type": "front",
                "ma_type": "EMA",
                "ok": True,
                "n_buy": 1,
                "sum_pnl": 2.0,
                "win_rate": 50.0,
            },
            {
                "stock": "A",
                "year": "",
                "dividend_type": "none",
                "ma_type": "SMA",
                "ok": True,
                "n_buy": 1,
                "sum_pnl": 3.0,
                "win_rate": 50.0,
            },
            {
                "stock": "A",
                "year": "",
                "dividend_type": "none",
                "ma_type": "EMA",
                "ok": True,
                "n_buy": 1,
                "sum_pnl": 4.0,
                "win_rate": 50.0,
            },
        ]
        df = ma_compare_dataframe(pair_ma_batch_rows(rows))
        self.assertIn("复权", df.columns)
        self.assertEqual(sorted(df["复权"].tolist()), ["不复权", "前复权"])

    def test_batch_summary_adds_div_col(self):
        from analyze import batch_summary_dataframe

        df = batch_summary_dataframe(
            [
                {"stock": "A", "ok": True, "status": "成功", "dividend_type": "front", "n_buy": 1, "sum_pnl": 1},
                {"stock": "A", "ok": True, "status": "成功", "dividend_type": "front_ratio", "n_buy": 1, "sum_pnl": 2},
            ]
        )
        self.assertIn("复权", df.columns)
        self.assertEqual(sorted(df["复权"].tolist()), ["前复权", "等比前复权"])

    def test_year_summary_splits_by_div(self):
        from analyze import batch_year_summary_dataframe, summarize_batch_by_year

        rows = [
            {
                "year": "2020",
                "ok": True,
                "dividend_type": "front",
                "n_buy": 1,
                "win_rate": 100.0,
                "avg_ret": 10.0,
                "sum_pnl": 1.0,
            },
            {
                "year": "2020",
                "ok": True,
                "dividend_type": "front_ratio",
                "n_buy": 3,
                "win_rate": 0.0,
                "avg_ret": -2.0,
                "sum_pnl": -1.0,
            },
        ]
        agg = summarize_batch_by_year(rows)
        self.assertEqual(len(agg), 2)
        by_div = {r["dividend_type"]: r for r in agg}
        self.assertEqual(by_div["front"]["n_buy"], 1)
        self.assertAlmostEqual(by_div["front"]["sum_pnl"], 1.0)
        self.assertEqual(by_div["front_ratio"]["n_buy"], 3)
        df = batch_year_summary_dataframe(rows)
        self.assertIn("复权", df.columns)
        self.assertEqual(len(df), 2)


class ResolveDivTests(unittest.TestCase):
    def test_compare_uses_year_intersection(self):
        from stock_select import _resolve_stock_div

        rec = {
            "by_div": {
                "front": {
                    "years": {
                        "2023": {"sum_pnl": 1000.0, "n_buy": 2, "win_rate": 50.0},
                        "2024": {"sum_pnl": 10.0, "n_buy": 2, "win_rate": 50.0},
                    },
                    "recent": None,
                    "ma_type_suggest": "SMA",
                    "ma_type_why": "compare",
                },
                "front_ratio": {
                    "years": {
                        "2024": {"sum_pnl": 100.0, "n_buy": 2, "win_rate": 50.0},
                        "2025": {"sum_pnl": 5.0, "n_buy": 1, "win_rate": 50.0},
                    },
                    "recent": {"sum_pnl": 1.0},
                    "ma_type_suggest": "EMA",
                    "ma_type_why": "compare",
                },
            }
        }
        _resolve_stock_div(rec)
        self.assertEqual(rec["div_type_suggest"], "front_ratio")
        self.assertEqual(rec["div_type_why"], "compare")
        self.assertEqual(rec["ma_type_suggest"], "EMA")
        self.assertIn("2024", rec["years"])
        self.assertIn("2025", rec["years"])
        self.assertNotIn("2023", rec["years"])

    def test_single_div(self):
        from stock_select import _resolve_stock_div

        rec = {
            "by_div": {
                "none": {
                    "years": {"2024": {"sum_pnl": 1.0, "n_buy": 1, "win_rate": 50.0}},
                    "recent": None,
                    "ma_type_suggest": "EMA",
                    "ma_type_why": "single_ma",
                }
            }
        }
        _resolve_stock_div(rec)
        self.assertEqual(rec["div_type_suggest"], "none")
        self.assertEqual(rec["div_type_why"], "single_div")
        self.assertEqual(rec["ma_type_suggest"], "EMA")

    def test_no_years_no_suggest(self):
        from stock_select import _resolve_stock_div

        rec = {"by_div": {"front": {"years": {}, "recent": None}}}
        _resolve_stock_div(rec)
        self.assertEqual(rec["div_type_suggest"], "")
        self.assertEqual(rec["div_type_why"], "no_compare")

    def test_window_flips_div_winner(self):
        from stock_select import _resolve_stock_div

        rec = {
            "by_div": {
                "front": {
                    "years": {
                        "2023": {"sum_pnl": 1000.0, "n_buy": 2, "win_rate": 50.0},
                        "2024": {"sum_pnl": 10.0, "n_buy": 2, "win_rate": 50.0},
                    },
                    "recent": None,
                    "ma_type_suggest": "SMA",
                    "ma_type_why": "compare",
                },
                "front_ratio": {
                    "years": {
                        "2023": {"sum_pnl": 10.0, "n_buy": 2, "win_rate": 50.0},
                        "2024": {"sum_pnl": 100.0, "n_buy": 2, "win_rate": 50.0},
                    },
                    "recent": None,
                    "ma_type_suggest": "EMA",
                    "ma_type_why": "compare",
                },
            }
        }
        _resolve_stock_div(rec)
        self.assertEqual(rec["div_type_suggest"], "front")
        self.assertIn("2023", rec["years"])
        windowed = {"by_div": rec["by_div"]}
        _resolve_stock_div(windowed, years_keep=("2024",))
        self.assertEqual(windowed["div_type_suggest"], "front_ratio")
        self.assertEqual(set(windowed["years"]), {"2024"})
        self.assertIn("2023", rec["by_div"]["front"]["years"])


class FingerprintUnionTests(unittest.TestCase):
    def test_report_fingerprint_unions_siblings(self):
        from stock_select import report_fingerprint

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            front = root / "front"
            ratio = root / "front_ratio"
            front.mkdir()
            ratio.mkdir()
            (front / "local_bt_600000_SH_操作明细.csv").write_text("a", encoding="utf-8")
            (ratio / "local_bt_600001_SH_操作明细.csv").write_text("bb", encoding="utf-8")
            self.assertEqual(report_fingerprint(front), report_fingerprint(root))
            self.assertEqual(report_fingerprint(front)[0], 2)


class BookSnippetTests(unittest.TestCase):
    def test_includes_dividend_type(self):
        from stock_select import format_book_snippet

        df = pd.DataFrame(
            [
                {
                    "stock": "600350.SH",
                    "ma_type_suggest": "EMA",
                    "div_type_suggest": "front",
                }
            ]
        )
        text = format_book_snippet(df)
        self.assertIn('"ma_type": "EMA"', text)
        self.assertIn('"dividend_type": "front"', text)
        self.assertIn("600350.SH", text)

    def test_no_compare_uses_run_default(self):
        from stock_select import format_book_snippet, ma_suggest_label

        df = pd.DataFrame(
            [
                {
                    "stock": "000000.SZ",
                    "ma_type_suggest": "",
                    "div_type_suggest": "",
                }
            ]
        )
        text = format_book_snippet(df)
        self.assertIn("000000.SZ", text)
        self.assertIn('"ma_type": "EMA"', text)
        self.assertIn('"dividend_type": "front_ratio"', text)
        self.assertEqual(ma_suggest_label("000000.SZ", ""), "EMA（默认）")

    def test_keeps_suggested_div_when_ma_missing(self):
        from stock_select import format_book_snippet

        df = pd.DataFrame(
            [
                {
                    "stock": "000000.SZ",
                    "ma_type_suggest": "",
                    "div_type_suggest": "front",
                }
            ]
        )
        text = format_book_snippet(df)
        self.assertIn('"ma_type": "EMA"', text)
        self.assertIn('"dividend_type": "front"', text)


class PayloadGroupTests(unittest.TestCase):
    def test_same_csv_years_and_ma_one_group(self):
        from run import group_payloads_by_csv

        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.csv"
            b = Path(td) / "b.csv"
            a.write_text("x", encoding="utf-8")
            b.write_text("y", encoding="utf-8")
            payloads = [
                {"csv": str(a), "year": "2021", "ma_type": "SMA"},
                {"csv": str(a), "year": "2021", "ma_type": "EMA"},
                {"csv": str(a), "year": "2022", "ma_type": "SMA"},
                {"csv": str(b), "year": "2021", "ma_type": "SMA"},
            ]
            groups = group_payloads_by_csv(payloads)
            self.assertEqual(len(groups), 2)
            self.assertEqual(groups[0], [0, 1, 2])
            self.assertEqual(groups[1], [3])

    def test_typed_dirs_are_different_groups(self):
        from run import group_payloads_by_csv

        with tempfile.TemporaryDirectory() as td:
            front = Path(td) / "front"
            ratio = Path(td) / "front_ratio"
            front.mkdir()
            ratio.mkdir()
            a = front / "600000_SH_1d.csv"
            b = ratio / "600000_SH_1d.csv"
            a.write_text("x", encoding="utf-8")
            b.write_text("y", encoding="utf-8")
            payloads = [{"csv": str(a)}, {"csv": str(b)}]
            groups = group_payloads_by_csv(payloads)
            self.assertEqual(len(groups), 2)


class StoreCacheTests(unittest.TestCase):
    def test_backtest_one_result_loads_csv_once(self):
        from unittest.mock import patch

        from market_csv import load_daily_csv as real_load
        from run import backtest_one_result, clear_market_store_cache

        header = "stock,period,datetime,open,high,low,close,volume,amount"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "600000_SH_1d_20200102_20200103.csv"
            path.write_text(
                header
                + "\n600000.SH,1d,20200102,1,1,1,1,100,100\n"
                + "600000.SH,1d,20200103,1,1,1,1,100,100\n",
                encoding="utf-8",
            )
            clear_market_store_cache()
            with patch("run.load_daily_csv", wraps=real_load) as mocked:
                row = backtest_one_result(
                    path,
                    start="20200102",
                    end="20200103",
                    out_dir=Path(td) / "out",
                    year="2020",
                )
                self.assertTrue(row.get("ok"), row.get("error"))
                self.assertEqual(mocked.call_count, 1)


class FastOhlcvPatchTests(unittest.TestCase):
    def test_patched_ohlcv_matches_period_path(self):
        import numpy as np
        from mock_qmt import MockContext, _as_tag
        from run import _exec_bundle, _patch_fast_ohlcv

        d = datetime(2018, 1, 2)
        bars = []
        while len(bars) < 400:
            if d.weekday() < 5:
                px = 10.0 + 0.01 * len(bars)
                bars.append(_bar(d.strftime("%Y%m%d"), px))
            d += timedelta(days=1)
        store = MarketStore(bars, "600350.SH")
        walk = bars[-30:]
        ctx = MockContext(store, [_as_tag(b.dt) for b in walk], "600350.SH")
        ctx.barpos = len(walk) - 1
        ns = _exec_bundle()
        ns["A"].period = "1d"
        ns["A"].stock = "600350.SH"
        ns["A"].is_backtest = True
        orig_d = ns["_get_ohlcv_1d"](ctx, "600350.SH")
        orig_w = ns["_get_ohlcv_1w"](ctx, "600350.SH")
        self.assertIsNotNone(orig_d)
        self.assertIsNotNone(orig_w)
        _patch_fast_ohlcv(ns)
        ns["A"]._ohlcv_cache = {"sentinel": True}
        fast_d = ns["_get_ohlcv_1d"](ctx, "600350.SH")
        fast_w = ns["_get_ohlcv_1w"](ctx, "600350.SH")
        self.assertEqual(ns["A"]._ohlcv_cache, {"sentinel": True})
        self.assertIsNotNone(fast_d)
        self.assertIsNotNone(fast_w)
        self.assertEqual(len(fast_d[3]), len(orig_d[3]))
        self.assertEqual(len(fast_w[3]), len(orig_w[3]))
        self.assertTrue(np.allclose(np.asarray(fast_d[3], dtype=float), np.asarray(orig_d[3], dtype=float)))
        self.assertTrue(np.allclose(np.asarray(fast_w[3], dtype=float), np.asarray(orig_w[3], dtype=float)))
        self.assertAlmostEqual(float(fast_d[3][-1]), float(orig_d[3][-1]))
        self.assertAlmostEqual(float(fast_w[3][-1]), float(orig_w[3][-1]))


class LocalBtUniverseHandlebarTests(unittest.TestCase):
    def _bars(self, n=400, stock="600000.SH"):
        d = datetime(2018, 1, 2)
        bars = []
        while len(bars) < n:
            if d.weekday() < 5:
                px = 10.0 + 0.01 * len(bars)
                b = _bar(d.strftime("%Y%m%d"), px)
                bars.append(
                    DailyBar(
                        day=b.day,
                        dt=b.dt,
                        open=b.open,
                        high=b.high,
                        low=b.low,
                        close=b.close,
                        volume=b.volume,
                        stock=stock,
                    )
                )
            d += timedelta(days=1)
        return bars

    def test_out_of_book_local_bt_still_calls_handle(self):
        from mock_qmt import MockContext, _as_tag
        from run import _exec_bundle, _patch_fast_ohlcv

        bars = self._bars(stock="600000.SH")
        store = MarketStore(bars, "600000.SH")
        walk = bars[-5:]
        ctx = MockContext(store, [_as_tag(b.dt) for b in walk], "600000.SH")
        ns = _exec_bundle()
        _patch_fast_ohlcv(ns)
        called = []
        orig = ns["_handle"]

        def wrapped(C):
            called.append(1)
            return orig(C)

        ns["_handle"] = wrapped
        ns["init"](ctx)
        self.assertEqual(list(ns["A"].watch), ["600000.SH"])
        ctx.barpos = 0
        ns["handlebar"](ctx)
        self.assertEqual(len(called), 1)
        rec = ns["_per_stock_map"]()
        self.assertIsInstance(rec, dict)

    def test_qmt_warmup_index_skips_handle(self):
        from mock_qmt import MockContext, _as_tag
        from run import _exec_bundle

        bars = self._bars(stock="000001.SH")
        store = MarketStore(bars, "000001.SH")
        walk = bars[-3:]
        ctx = MockContext(store, [_as_tag(b.dt) for b in walk], "000001.SH")
        ctx._local_bt = False
        ns = _exec_bundle()
        ns["_LOCAL_BT"] = False
        called = []
        orig = ns["_handle"]

        def wrapped(C):
            called.append(1)
            return orig(C)

        ns["_handle"] = wrapped
        ns["init"](ctx)
        self.assertIn("600350.SH", list(ns["A"].watch))
        self.assertFalse(ns["_chart_in_watch"]())
        ctx.barpos = 0
        ns["handlebar"](ctx)
        self.assertEqual(len(called), 0)

    def test_qmt_editor_backtest_skips_run_time_and_scans_chart(self):
        from mock_qmt import MockContext, _as_tag
        from run import _exec_bundle

        bars = self._bars(stock="600350.SH")
        store = MarketStore(bars, "600350.SH")
        walk = bars[-5:]
        ctx = MockContext(store, [_as_tag(b.dt) for b in walk], "600350.SH")
        ctx._local_bt = False
        ctx.do_back_test = True
        ns = _exec_bundle()
        ns["_LOCAL_BT"] = False
        called = []
        orig = ns["_handle"]

        def wrapped(C):
            called.append(1)
            return orig(C)

        ns["_handle"] = wrapped
        ns["init"](ctx)
        self.assertEqual(ctx.run_time_calls, [])
        self.assertIn("600350.SH", list(ns["A"].watch))
        self.assertTrue(ns["_chart_in_watch"]())
        ctx.barpos = 0
        ns["handlebar"](ctx)
        self.assertEqual(len(called), 1)

    def test_live_init_registers_run_time_with_historical_start(self):
        from mock_qmt import MockContext, _as_tag
        from run import _exec_bundle

        bars = self._bars(stock="000001.SH")
        store = MarketStore(bars, "000001.SH")
        walk = bars[-3:]
        ctx = MockContext(store, [_as_tag(b.dt) for b in walk], "000001.SH")
        ctx._local_bt = False
        ctx.do_back_test = False
        ns = _exec_bundle()
        ns["_LOCAL_BT"] = False
        ns["init"](ctx)
        self.assertEqual(len(ctx.run_time_calls), 1)
        args = ctx.run_time_calls[0][0]
        self.assertEqual(args[0], "check_market")
        self.assertIn(args[1], ("2nSecond", "2Second"))
        self.assertGreaterEqual(len(args[2]), 19)
        self.assertIn("-", args[2])
        self.assertIn(" ", args[2])
        self.assertTrue(callable(ns.get("check_market")))

    def test_activate_stock_throttles_disk_reload(self):
        from run import _exec_bundle

        ns = _exec_bundle()
        ns["A"].is_backtest = False
        ns["A"].stock = ""
        ns["A"]._per_stock = {}
        ns["_save_state"] = lambda: None
        loads = []

        def fake_load(log=True):
            loads.append((str(ns["A"].stock), log))
            ns["A"].position = None
            ns["A"].lots = []
            ns["A"].pending = None

        ns["_load_state"] = fake_load
        ns["_activate_stock"]("600350.SH")
        ns["_activate_stock"]("601939.SH")
        ns["_activate_stock"]("600350.SH")
        ns["_activate_stock"]("601939.SH")
        self.assertEqual([x[0] for x in loads], ["600350.SH", "601939.SH"])
        self.assertEqual([x[1] for x in loads], [True, True])
        rec = ns["_per_stock_map"]()["600350.SH"]
        rec["_state_loaded_at"] = datetime.now() - timedelta(seconds=120)
        ns["_activate_stock"]("600350.SH")
        self.assertEqual([x[0] for x in loads], ["600350.SH", "601939.SH", "600350.SH"])
        self.assertEqual([x[1] for x in loads], [True, True, False])


class FingerprintAggTests(unittest.TestCase):
    def test_glob_fingerprint_is_triple(self):
        from stock_select import glob_fingerprint

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "600000_SH_1d_a.csv").write_text("x", encoding="utf-8")
            fp = glob_fingerprint(root, "*_1d_*.csv")
            self.assertEqual(len(fp), 3)
            self.assertEqual(fp[0], 1)
            self.assertGreater(fp[2], 0)


class OhlcvPrefetchCacheTests(unittest.TestCase):
    def _bars(self, n=400, stock="600350.SH"):
        d = datetime(2018, 1, 2)
        bars = []
        while len(bars) < n:
            if d.weekday() < 5:
                px = 10.0 + 0.01 * len(bars)
                b = _bar(d.strftime("%Y%m%d"), px)
                bars.append(
                    DailyBar(
                        day=b.day,
                        dt=b.dt,
                        open=b.open,
                        high=b.high,
                        low=b.low,
                        close=b.close,
                        volume=b.volume,
                        stock=stock,
                    )
                )
            d += timedelta(days=1)
        return bars

    def _setup(self):
        from mock_qmt import MockContext, _as_tag
        from run import _exec_bundle

        bars = self._bars()
        store = MarketStore(bars, "600350.SH")
        walk = bars[-30:]
        ctx = MockContext(store, [_as_tag(b.dt) for b in walk], "600350.SH")
        ctx.barpos = len(walk) - 1
        ns = _exec_bundle()
        ns["A"].period = "1d"
        ns["A"].stock = ""
        ns["A"].is_backtest = True
        ns["A"]._diag = set()
        if hasattr(ns["A"], "_ohlcv_cache"):
            delattr(ns["A"], "_ohlcv_cache")
        return ns, ctx

    def _wrap_md(self, ctx, *, lower_keys=False, fail_multi=False):
        from mock_qmt import _parse_md_call

        calls = []
        orig = ctx._md

        def wrapped(*a, **k):
            spec = _parse_md_call(a, k)
            calls.append({"spec": spec, "kwargs": dict(k)})
            if fail_multi and len(spec["stocks"]) > 1:
                raise RuntimeError("batch fail")
            out = orig(*a, **k)
            if lower_keys:
                return {str(kk).lower(): vv for kk, vv in out.items()}
            return out

        ctx._md = wrapped
        return calls

    def test_dividend_type_wraps_for_stock(self):
        from run import _exec_bundle

        ns = _exec_bundle()
        ns["A"].stock = "600350.SH"
        self.assertEqual(ns["_dividend_type"](), ns["_dividend_type_for"]("600350.SH"))
        self.assertEqual(ns["_dividend_type_for"]("600350.SH"), "front_ratio")
        self.assertEqual(ns["_dividend_type_for"]("600028.SH"), "front")
        self.assertEqual(
            ns["_ohlcv_diag_key"]("d1", "600028.SH"),
            "d1_600028_SH",
        )

    def test_prefetch_codes_watch_only_and_open_subset(self):
        from run import _exec_bundle

        ns = _exec_bundle()
        ns["A"].watch = ["600350.SH", "600028.SH"]
        ns["A"].chart_stock = "000300.SH"
        uni = ns["_watch_universe_codes"]()
        self.assertIn("000300.SH", uni)
        stocks = list(ns["A"].watch)
        got = ns["_ohlcv_prefetch_codes"]("signal", stocks, "20260901", "20260831")
        self.assertEqual(got, stocks)
        self.assertNotIn("000300.SH", got)
        self.assertEqual(
            ns["_ohlcv_prefetch_codes"]("pending", stocks, "20260901", "20260831"),
            [],
        )
        ns["A"]._per_stock = {}
        self.assertEqual(
            ns["_ohlcv_prefetch_codes"]("open_exec", stocks, "20260901", "20260831"),
            stocks,
        )
        ns["A"]._per_stock = {
            "600350.SH": {
                "_confirmed_eval_day": "20260831",
                "_has_pend": False,
                "_fallback_done_day": "",
            },
            "600028.SH": {
                "_confirmed_eval_day": "20260831",
                "_has_pend": True,
                "_has_buy_pend": False,
                "_fallback_done_day": "",
            },
        }
        self.assertEqual(
            ns["_ohlcv_prefetch_codes"]("open_exec", stocks, "20260901", "20260831"),
            [],
        )
        ns["A"]._per_stock["600028.SH"]["_has_buy_pend"] = True
        self.assertEqual(
            ns["_ohlcv_prefetch_codes"]("open_exec", stocks, "20260901", "20260831"),
            ["600028.SH"],
        )
        ns["A"]._per_stock["600350.SH"]["_confirmed_eval_day"] = "20260830"
        self.assertEqual(
            ns["_ohlcv_prefetch_codes"]("open_exec", stocks, "20260901", "20260831"),
            ["600350.SH", "600028.SH"],
        )

    def test_multi_code_one_md_cache_matches_single(self):
        import numpy as np

        ns, ctx = self._setup()
        calls = self._wrap_md(ctx, lower_keys=True)
        codes = ["600028.SH", "600188.SH"]
        single_d = ns["_get_ohlcv_1d"](ctx, codes[0])
        single_w = ns["_get_ohlcv_1w"](ctx, codes[0])
        self.assertIsNotNone(single_d)
        self.assertIsNotNone(single_w)
        self.assertFalse(hasattr(ns["A"], "_ohlcv_cache") and ns["A"]._ohlcv_cache)
        ns["A"].stock = ""
        ns["A"]._diag = set()
        calls.clear()
        ns["_prefetch_watch_ohlcv"](ctx, codes)
        batch = [c for c in calls if len(c["spec"]["stocks"]) >= 2]
        self.assertEqual(len(batch), 2)
        self.assertEqual({c["spec"]["period"] for c in batch}, {"1d", "1w"})
        for c in batch:
            self.assertFalse(c["kwargs"].get("subscribe", True))
            self.assertEqual(c["spec"]["stocks"], codes)
        n_after_prefetch = len(calls)
        cached_d = ns["_get_ohlcv_1d"](ctx, codes[0])
        cached_w = ns["_get_ohlcv_1w"](ctx, codes[0])
        self.assertEqual(len(calls), n_after_prefetch)
        self.assertIsNotNone(cached_d)
        self.assertIsNotNone(cached_w)
        self.assertTrue(
            np.allclose(
                np.asarray(cached_d[3], dtype=float),
                np.asarray(single_d[3], dtype=float),
            )
        )
        self.assertTrue(
            np.allclose(
                np.asarray(cached_w[3], dtype=float),
                np.asarray(single_w[3], dtype=float),
            )
        )
        self.assertAlmostEqual(float(cached_d[3][-1]), float(single_d[3][-1]))
        tick = ns["_get_ohlcv_period"](ctx, codes[0], "1d", 2, 1, "d1open_600028_SH")
        self.assertIsNotNone(tick)
        self.assertGreater(len(calls), n_after_prefetch)
        self.assertEqual(int(calls[-1]["spec"]["count"]), 2)

    def test_group_fail_falls_back_per_stock(self):
        ns, ctx = self._setup()
        calls = self._wrap_md(ctx, fail_multi=True)
        codes = ["600028.SH", "600188.SH"]
        ns["_prefetch_watch_ohlcv"](ctx, codes)
        singles = [c for c in calls if len(c["spec"]["stocks"]) == 1]
        self.assertGreaterEqual(len(singles), 4)
        hit_d = ns["_get_ohlcv_1d"](ctx, codes[0])
        self.assertIsNotNone(hit_d)
        n = len(calls)
        ns["_get_ohlcv_1d"](ctx, codes[0])
        self.assertEqual(len(calls), n)


if __name__ == "__main__":
    unittest.main()
