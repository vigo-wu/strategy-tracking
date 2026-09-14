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


class UniverseExecSkipTests(unittest.TestCase):
    def _gate(self, *, bt: bool) -> dict:
        now = datetime(2020, 1, 10, 15, 0, 0)
        return {
            "bt": bt,
            "now": now,
            "now_s": "150000",
            "day": "20200110",
            "tag": "20200110150000",
            "hhmm": "1500",
            "live_cc": False,
            "phase": "bt" if bt else "session",
            "live_work": "",
            "bar_dt": now,
            "prev_closed": "20200109",
        }

    def _run_universe(self, *, bt: bool, pend_code: str):
        from run import _exec_bundle

        ns = _exec_bundle()
        a = ns["A"]
        a.is_backtest = bt
        a.watch = ["600350.SH", "601939.SH"]
        a.chart_stock = "600350.SH"
        a.stock = ""
        a._per_stock = {}
        ns["_save_state"] = lambda: None
        ns["_log_book_checkin_missing"] = lambda *_a, **_k: None
        ns["_ensure_clock_prev_closed"] = lambda *_a, **_k: "20200109"
        ns["_handle_clock_gate"] = lambda _c, from_timer=False: self._gate(bt=bt)
        calls: list[tuple[str, str]] = []

        def _handle_stock(_c, _ctx):
            stock = str(getattr(a, "stock", "") or "")
            upass = str(getattr(a, "_universe_pass", "") or "")
            calls.append((stock, upass))
            if stock == pend_code:
                a.pending_entry = {"signal_day": "20200110"}
                a.pending_exit = None
                a.pending = None
            else:
                a.pending_entry = None
                a.pending_exit = None
                a.pending = None

        ns["_handle_stock"] = _handle_stock
        ns["_handle_universe"](object())
        return calls

    def test_backtest_exec_skips_stock_without_pending(self):
        calls = self._run_universe(bt=True, pend_code="600350.SH")
        evals = [c for c in calls if c[1] == "eval"]
        execs = [c for c in calls if c[1] == "exec"]
        self.assertEqual(
            [c[0] for c in evals],
            ["600350.SH", "601939.SH"],
        )
        self.assertEqual([c[0] for c in execs], ["600350.SH"])

    def test_live_exec_still_runs_all_stocks(self):
        calls = self._run_universe(bt=False, pend_code="600350.SH")
        evals = [c for c in calls if c[1] == "eval"]
        execs = [c for c in calls if c[1] == "exec"]
        self.assertEqual(
            [c[0] for c in evals],
            ["600350.SH", "601939.SH"],
        )
        self.assertEqual(
            [c[0] for c in execs],
            ["600350.SH", "601939.SH"],
        )


class WalkProgressHelperTest(unittest.TestCase):
    def test_year_change_and_step(self) -> None:
        from book_backtest import should_emit_walk_progress, walk_progress_step

        self.assertEqual(walk_progress_step(2000), 50)
        self.assertTrue(should_emit_walk_progress(0, 100, "20180102", "", -1, 10))
        self.assertTrue(should_emit_walk_progress(99, 100, "20200102", "2019", 90, 10))
        self.assertTrue(should_emit_walk_progress(20, 100, "20190102", "2018", 10, 50))
        self.assertFalse(should_emit_walk_progress(15, 100, "20180120", "2018", 10, 50))


if __name__ == "__main__":
    unittest.main()
