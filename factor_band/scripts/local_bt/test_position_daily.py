# coding: utf-8
import unittest

import pandas as pd

from position_daily import (
    apply_current_equity,
    build_daily_position_frame,
    position_kpis,
    slice_daily,
    slot_day_hist,
    stock_hold_days,
)
from equity_yearly import build_daily_equity


def _t(stock, buy, sell, cost=10000.0, shares=100, buy_price=100.0):
    return {
        "stock": stock,
        "buy_open_day": buy,
        "sell_exec_day": sell,
        "cost": cost,
        "shares": shares,
        "buy_price": buy_price,
    }


class PositionDailyTests(unittest.TestCase):
    def test_single_lot_slots_and_half_open(self):
        # Mon 2024-01-02 .. Fri 2024-01-05 hold; sell Mon 2024-01-08 → 卖出日不含
        trades = [_t("600000.SH", "20240102", "20240108", cost=20000.0)]
        daily = build_daily_position_frame(trades, budget=100000.0)
        self.assertFalse(daily.empty)
        days = [pd.Timestamp(d).strftime("%Y%m%d") for d in daily["date"]]
        self.assertIn("20240102", days)
        self.assertIn("20240105", days)
        self.assertNotIn("20240108", days)
        self.assertTrue((daily["slots"] == 1).all())
        self.assertTrue((daily["cost"] == 20000.0).all())
        self.assertAlmostEqual(float(daily["exposure_pct"].iloc[0]), 20.0)

    def test_two_lots_same_stock_overlap_slots(self):
        trades = [
            _t("600000.SH", "20240102", "20240110", cost=10000.0),
            _t("600000.SH", "20240103", "20240110", cost=5000.0),
        ]
        daily = build_daily_position_frame(trades, budget=100000.0)
        by = {pd.Timestamp(r["date"]).strftime("%Y%m%d"): int(r["slots"]) for _, r in daily.iterrows()}
        self.assertEqual(by["20240102"], 1)
        self.assertEqual(by["20240103"], 2)
        self.assertAlmostEqual(
            float(daily.loc[daily["date"] == pd.Timestamp("2024-01-03"), "cost"].iloc[0]),
            15000.0,
        )

    def test_stock_hold_days_dedupe(self):
        trades = [
            _t("600000.SH", "20240102", "20240105", cost=10000.0),
            _t("600000.SH", "20240103", "20240105", cost=5000.0),
            _t("601988.SH", "20240102", "20240104", cost=8000.0),
        ]
        hold = stock_hold_days(trades)
        by = {r["stock"]: int(r["days"]) for _, r in hold.iterrows()}
        # 600000: 20240102,03,04 (3 bdays); 601988: 20240102,03 (2)
        self.assertEqual(by["600000.SH"], 3)
        self.assertEqual(by["601988.SH"], 2)

    def test_slice_and_hist(self):
        trades = [
            _t("600000.SH", "20240102", "20240110", cost=10000.0),
            _t("601988.SH", "20240102", "20240104", cost=10000.0),
        ]
        daily = build_daily_position_frame(trades, budget=100000.0)
        mid = slice_daily(daily, "20240103", "20240105")
        self.assertEqual(len(mid), 3)  # 3,4,5
        # 1/3 slots=2 (Jan3), then 1 after 601988 exits on Jan4 exclusive → Jan4,5 slots=1
        hist = slot_day_hist(mid, book_lot_max=3)
        hist_map = {int(r["slots"]): int(r["days"]) for _, r in hist.iterrows()}
        self.assertEqual(hist_map[2], 1)
        self.assertEqual(hist_map[1], 2)
        self.assertEqual(hist_map[0], 0)
        hold = stock_hold_days(trades, "20240103", "20240105")
        by = {r["stock"]: int(r["days"]) for _, r in hold.iterrows()}
        self.assertEqual(by["600000.SH"], 3)
        self.assertEqual(by["601988.SH"], 1)  # only Jan3 in window with hold

    def test_kpis_empty_streak(self):
        trades = [_t("600000.SH", "20240103", "20240105", cost=10000.0)]
        # range starts Jan2 empty, Jan3-4 held, ...
        daily = build_daily_position_frame(
            [
                _t("600000.SH", "20240102", "20240103", cost=10000.0),
                _t("600000.SH", "20240108", "20240110", cost=10000.0),
            ],
            budget=50000.0,
        )
        # Jan2 held; Jan3-5 empty (bdays); Jan8-9 held
        kpi = position_kpis(daily, book_lot_max=3)
        self.assertGreaterEqual(kpi["max_empty_streak"], 2)
        self.assertAlmostEqual(kpi["avg_exposure"], float(daily["exposure_pct"].mean()), places=2)
        self.assertEqual(kpi["n_days"], len(daily))

    def test_empty_trades(self):
        daily = build_daily_position_frame([], budget=100000.0)
        self.assertTrue(daily.empty)
        self.assertEqual(list(stock_hold_days([]).columns), ["stock", "days", "days_pct"])
        hist = slot_day_hist(daily, book_lot_max=3)
        self.assertEqual(hist["days"].sum(), 0)
        kpi = position_kpis(daily, book_lot_max=3)
        self.assertEqual(kpi["n_days"], 0)

    def test_exposure_vs_current_equity(self):
        # 先平一笔赚 50k → 权益 150k；再开 30k 仓，相对当前权益=20%
        trades = [
            _t("600000.SH", "20240102", "20240105", cost=50000.0),
            {
                "stock": "600000.SH",
                "buy_open_day": "20240102",
                "sell_exec_day": "20240105",
                "cost": 50000.0,
                "shares": 500,
                "buy_price": 100.0,
                "pnl": 50000.0,
            },
            _t("601988.SH", "20240108", "20240112", cost=30000.0),
        ]
        # fix first trade pnl
        trades[0] = {
            "stock": "600000.SH",
            "buy_open_day": "20240102",
            "sell_exec_day": "20240105",
            "cost": 50000.0,
            "shares": 500,
            "buy_price": 100.0,
            "pnl": 50000.0,
        }
        trades = [trades[0], trades[2]]
        budget = 100000.0
        daily = build_daily_position_frame(trades, budget=budget)
        eq = build_daily_equity(trades, budget=budget)
        daily = apply_current_equity(daily, eq, budget)
        # after sell 20240105, equity=150000; hold 601988 from 20240108
        row = daily.loc[daily["date"] == pd.Timestamp("2024-01-08")].iloc[0]
        self.assertAlmostEqual(float(row["exposure_base"]), 150000.0, places=2)
        self.assertAlmostEqual(float(row["exposure_pct"]), 20.0, places=2)
        # before first sell, base stays budget
        row0 = daily.loc[daily["date"] == pd.Timestamp("2024-01-02")].iloc[0]
        self.assertAlmostEqual(float(row0["exposure_base"]), 100000.0, places=2)
        self.assertAlmostEqual(float(row0["exposure_pct"]), 50.0, places=2)


if __name__ == "__main__":
    unittest.main()
