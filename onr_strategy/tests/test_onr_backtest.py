# coding: utf-8
from __future__ import annotations

import unittest
from datetime import date

from onr_strategy.backtest.config import OnrConfig
from onr_strategy.backtest.data import last_at_or_before, slice_hhmm
from onr_strategy.backtest.engine import run_backtest, summarize
from onr_strategy.backtest.signals import score_symbol, select_names, snapshot_at, universe_ok
from onr_strategy.backtest.synthetic import build_demo_store
from onr_strategy.backtest.trade import Position, walk_rules_exit


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.store = build_demo_store()
        self.cfg = OnrConfig()
        self.day = self.store.trading_days()[-2]

    def test_rejects_st_bj_ipo(self):
        self.assertEqual(universe_ok(self.store, "CCC.SZ", self.day, self.cfg)[1], "st")
        self.assertEqual(universe_ok(self.store, "DDD.BJ", self.day, self.cfg)[1], "bj")
        self.assertEqual(universe_ok(self.store, "EEE.SZ", self.day, self.cfg)[1], "ipo")
        self.assertTrue(universe_ok(self.store, "AAA.SZ", self.day, self.cfg)[0])


class LookaheadTests(unittest.TestCase):
    def setUp(self):
        self.store = build_demo_store()
        self.cfg = OnrConfig(use_recheck_1450=False)
        self.day = self.store.trading_days()[-2]

    def test_cutoff_excludes_after_1445(self):
        raw = self.store.minutes("GGG.SZ", self.day)
        cut = slice_hhmm(raw, 930, 1445)
        self.assertTrue((cut["hhmm"] <= 1445).all())
        self.assertGreater(float(raw.loc[raw["hhmm"] > 1445, "close"].max()), float(cut["close"].max()))

    def test_ggg_fails_at_1445_would_pass_later(self):
        snap = snapshot_at(self.store, "GGG.SZ", self.day, self.cfg, cutoff=1445)
        self.assertIsNotNone(snap.ret)
        self.assertLess(snap.ret, 0.03)
        later = last_at_or_before(self.store.minutes("GGG.SZ", self.day), 1455)
        pre = float(self.store.daily("GGG.SZ").loc[lambda d: d["date"] == self.day].iloc[0]["pre_close"])
        self.assertGreater(later / pre - 1.0, 0.03)

    def test_ggg_not_selected(self):
        names, _ = select_names(self.store, self.day, self.cfg)
        syms = [s.symbol for s in names]
        self.assertNotIn("GGG.SZ", syms)
        self.assertIn("AAA.SZ", syms)


class FactorTests(unittest.TestCase):
    def setUp(self):
        self.store = build_demo_store()
        self.cfg = OnrConfig()
        self.day = self.store.trading_days()[-2]

    def test_aaa_passes_bbb_fails_momentum(self):
        aaa = score_symbol(self.store, "AAA.SZ", self.day, self.cfg)
        bbb = score_symbol(self.store, "BBB.SZ", self.day, self.cfg)
        self.assertTrue(aaa.passed, aaa.reasons)
        self.assertFalse(bbb.passed)
        self.assertIn("mom", bbb.reasons)

    def test_large_order_missing_data_fails_when_enabled(self):
        cfg = OnrConfig(use_large_order=True)
        snap = score_symbol(self.store, "AAA.SZ", self.day, cfg)
        self.assertFalse(snap.passed)
        self.assertIn("large_order_no_data", snap.reasons)

    def test_rank_momentum_then_smaller_cap(self):
        names, _ = select_names(self.store, self.day, OnrConfig())
        syms = [s.symbol for s in names]
        self.assertGreaterEqual(len(syms), 1)
        self.assertEqual(syms[0], "AAA.SZ")


class ExitTests(unittest.TestCase):
    def test_low_open_hits_stop(self):
        store = build_demo_store()
        day = store.trading_days()[-1]
        pos = Position("AAA.SZ", 100, cost=10.50, buy_close=10.50, buy_date=store.trading_days()[-2], px_1445=10.42)
        mins = store.minutes("AAA.SZ", day).copy()
        mins.loc[:, "low"] = 10.0
        mins.loc[:, "open"] = 10.40
        mins.loc[:, "close"] = 10.30
        store.minute_map[("AAA.SZ", day)] = mins
        fill = walk_rules_exit(pos, store, day, OnrConfig())
        self.assertIsNotNone(fill)
        self.assertEqual(fill.reason, "stop")
        self.assertAlmostEqual(fill.price, 10.50 * 0.98, places=4)


class EngineTests(unittest.TestCase):
    def test_demo_t1_and_buy_at_close(self):
        store = build_demo_store()
        cfg = OnrConfig(exit_mode="open", use_recheck_1450=False)
        out = run_backtest(store, cfg, with_baseline=True)
        st = out["strategy"]
        self.assertTrue(st.trades, "expected demo trades")
        for t in st.trades:
            self.assertGreater(t.sell_date, t.buy_date)
            self.assertEqual(t.buy_hhmm, 1500)
            if t.px_1445 > 0:
                self.assertNotAlmostEqual(t.buy_px, t.px_1445, places=4)
        self.assertLessEqual(max(d.n_hold for d in st.days), 3)
        bought = {t.symbol for t in st.trades}
        self.assertIn("AAA.SZ", bought)
        self.assertNotIn("GGG.SZ", bought)
        self.assertNotIn("CCC.SZ", bought)
        stats = summarize(st)
        self.assertGreater(stats["n_trades"], 0)
        self.assertIn("baseline", out)

    def test_ablation_disable_momentum_picks_bbb(self):
        store = build_demo_store()
        day = store.trading_days()[-2]
        cfg = OnrConfig(use_momentum=False, use_recheck_1450=False)
        names, _ = select_names(store, day, cfg)
        self.assertIn("BBB.SZ", [s.symbol for s in names])


class CompactDumpTests(unittest.TestCase):
    def test_compact_matches_minute_snapshot(self):
        from onr_strategy.backtest.compact import compact_from_minutes, sparse_minutes

        store = build_demo_store()
        day = store.trading_days()[-2]
        cfg = OnrConfig(use_recheck_1450=False)
        mins = store.minutes("AAA.SZ", day)
        pack = compact_from_minutes(mins, cfg)
        from_min = snapshot_at(store, "AAA.SZ", day, cfg, cutoff=1445)
        self.assertAlmostEqual(pack["px_1445"], from_min.px_decision, places=5)
        self.assertAlmostEqual(pack["vol_ratio"], from_min.vol_ratio, places=5)
        sparse = sparse_minutes(mins)
        self.assertTrue((sparse["hhmm"] <= 1450).all())
        self.assertFalse(((sparse["hhmm"] > 1000) & (sparse["hhmm"] < 1430)).any())

    def test_compact_store_without_body_minutes(self):
        from onr_strategy.backtest.compact import compact_from_minutes

        store = build_demo_store()
        day = store.trading_days()[-2]
        cfg = OnrConfig(use_recheck_1450=False)
        pack = compact_from_minutes(store.minutes("AAA.SZ", day), cfg)
        store.compact_map[("AAA.SZ", day)] = pack
        store.minute_map[("AAA.SZ", day)] = store.minutes("AAA.SZ", day).iloc[0:0]
        snap = score_symbol(store, "AAA.SZ", day, cfg)
        self.assertTrue(snap.passed, snap.reasons)

    def test_ashare_and_times(self):
        from onr_strategy.backtest.dump_xtdata import is_ashare, parse_times

        self.assertTrue(is_ashare("600000.SH"))
        self.assertTrue(is_ashare("000001.SZ"))
        self.assertTrue(is_ashare("300001.SZ"))
        self.assertFalse(is_ashare("000001.SH"))
        self.assertFalse(is_ashare("510300.SH"))
        self.assertFalse(is_ashare("830001.BJ"))
        ts = parse_times(["20240102144500", "20240102145000"])
        self.assertEqual(ts[0].hour, 14)
        self.assertEqual(ts[0].minute, 45)


if __name__ == "__main__":
    unittest.main()
