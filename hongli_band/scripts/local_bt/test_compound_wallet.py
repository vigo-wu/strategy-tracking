# coding: utf-8
import unittest

from compound_wallet import CompoundWallet, make_ledger_wallet, parse_wallet_from_log
from trades_csv import TradeLedger, HEADER, wrap_fill_hooks


class CompoundWalletTests(unittest.TestCase):
    def test_deploy_cap_grows_after_sell_profit(self):
        w = CompoundWallet(100000.0, cash_ratio=0.9)
        ns = {"A": type("A", (), {"stock": "600350.SH", "position": None})()}
        cap0 = w.deploy_cap(ns)
        w.on_buy(1000, 10.0)
        ns["A"].position = {"shares": 1000, "price": 10.0, "cost": 10000.0}
        w.on_sell(1000, 12.0)
        ns["A"].position = None
        cap1 = w.deploy_cap(ns)
        self.assertAlmostEqual(cap0, 90000.0)
        self.assertGreater(cap1, cap0)

    def test_deploy_cap_fixed_base_does_not_grow_after_sell_profit(self):
        w = CompoundWallet(
            100000.0,
            cash_ratio=0.9,
            budget_base="fixed",
            fixed_amount=100000.0,
        )
        ns = {
            "A": type("A", (), {"stock": "600350.SH", "position": None})(),
            "TRADE_BUDGET": 100000.0,
            "BUDGET_BASE": "fixed",
        }
        cap0 = w.deploy_cap(ns)
        w.on_buy(1000, 10.0)
        ns["A"].position = {"shares": 1000, "price": 10.0, "cost": 10000.0}
        w.on_sell(1000, 12.0)
        ns["A"].position = None
        cap1 = w.deploy_cap(ns)
        self.assertAlmostEqual(cap0, 90000.0)
        self.assertAlmostEqual(cap1, 90000.0)

    def test_norm_budget_base_accepts_panel_chinese(self):
        from compound_wallet import _norm_budget_base, make_wallet

        self.assertEqual(_norm_budget_base("固定金额"), "fixed")
        self.assertEqual(_norm_budget_base("总资产减其它"), "equity")
        ns = {"CASH_RATIO": 0.9, "TRADE_BUDGET": 200000.0, "BUDGET_BASE": "固定金额"}
        w = make_wallet(ns, {"compound_backtest": True}, 100000.0)
        self.assertIsNotNone(w)
        self.assertEqual(w.budget_base, "fixed")
        self.assertAlmostEqual(w.deploy_cap(ns), 180000.0)

    def test_ledger_writes_cap_columns(self):
        lg = TradeLedger("600350.SH")
        snap = {"deploy_cap": 90000.0, "equity": 100000.0}
        snap_after = {"deploy_cap": 81000.0, "equity": 90000.0}
        lg.on_buy(1000, 10.0, "20240102", snap=snap, snap_after=snap_after, stock_mv=10000.0)
        self.assertEqual(len(lg.rows), 1)
        row = lg.rows[0]
        self.assertEqual(len(row), len(HEADER))
        self.assertIn("%", row[10])
        self.assertNotEqual(row[10], "0.00%")
        self.assertEqual(row[16], "90000.00")
        self.assertEqual(row[17], "90000.00")

    def test_parse_wallet_from_log(self):
        text = "local_bt_book n=3 compound=1 wallet_start=100000.00\nwallet_end=105000.50\n"
        parsed = parse_wallet_from_log(text)
        self.assertAlmostEqual(float(parsed["wallet_cash_start"] or 0), 100000.0)
        self.assertAlmostEqual(float(parsed["wallet_cash_end"] or 0), 105000.50)

    def test_make_ledger_wallet_without_compound(self):
        ns = {"CASH_RATIO": 0.9}
        w, on = make_ledger_wallet(ns, None, 100000.0)
        self.assertFalse(on)
        self.assertAlmostEqual(w.cash, 100000.0)

    def test_wrap_fill_hooks_fixed_cap_writes_columns(self):
        w = CompoundWallet(100000.0, cash_ratio=0.9)

        class Acc:
            stock = "600350.SH"
            position = None

        a = Acc()

        def _buy(vol, price, opened_at, **extra):
            a.position = {"shares": int(vol), "price": float(price), "cost": float(vol) * float(price)}

        def _sell(now, reason, last_hint, filled_vol, mark_half=False, lot_ids=None):
            a.position = None

        ns = {
            "A": a,
            "_apply_buy_fill": _buy,
            "_apply_sell_fill": _sell,
            "_trade_budget_cap": lambda: 90000.0,
            "_per_stock_map": lambda: {},
        }
        lg = TradeLedger("600350.SH")
        wrap_fill_hooks(ns, lg, w, dynamic_cap=False)
        ns["_apply_buy_fill"](1000, 10.0, "20240102")
        self.assertEqual(lg.rows[0][16], "90000.00")
        self.assertEqual(lg.rows[0][17], "100000.00")

    def test_on_ex_rights_scales_lots_and_writes_bonus_row(self):
        w = CompoundWallet(100000.0, cash_ratio=0.9, enabled=True)
        cash0 = w.cash
        lg = TradeLedger("000963.SZ")
        lg.on_buy(500, 93.58, "20170519")
        lg.on_ex_rights("20170524", 2.029398, 2.0)
        self.assertEqual(len(lg.rows), 2)
        self.assertEqual(lg.rows[1][6], "送转")
        self.assertEqual(lg.rows[1][12], "500")
        self.assertEqual(int(lg._lots[0]["shares"]), 1000)
        self.assertAlmostEqual(float(lg._lots[0]["price"]), 93.58 / 2.029398, places=4)
        w.on_buy(500, 93.58)
        # 送转不碰现金
        self.assertAlmostEqual(w.cash, cash0 - 500 * 93.58)
        lg.on_sell(1000, 44.81, "20170606")
        pnl = float(lg.rows[-1][9])
        self.assertGreater(pnl, -4000)


    def test_wrap_fill_hooks_registers_ex_rights(self):
        class Acc:
            stock = "000963.SZ"
            position = None

        a = Acc()

        def _buy(vol, price, opened_at, **extra):
            a.position = {
                "shares": int(vol),
                "price": float(price),
                "cost": float(vol) * float(price),
            }

        def _sell(now, reason, last_hint, filled_vol, mark_half=False, lot_ids=None):
            a.position = None

        ns = {
            "A": a,
            "_apply_buy_fill": _buy,
            "_apply_sell_fill": _sell,
            "_per_stock_map": lambda: {},
        }
        lg = TradeLedger("000963.SZ")
        wrap_fill_hooks(ns, lg, None, dynamic_cap=False)
        ns["_apply_buy_fill"](500, 93.58, "20170519")
        ns["_on_ex_rights_ledger"]("20170524", 2.0, 2.0)
        self.assertEqual(lg.rows[1][6], "送转")
        ns["_apply_sell_fill"]("20170606", "weekly_bear", 44.81, 1000)
        self.assertEqual(lg.rows[-1][12], "1000")


if __name__ == "__main__":
    unittest.main()
