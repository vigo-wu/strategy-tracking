# coding: utf-8
import unittest

from compound_wallet import CompoundWallet, parse_wallet_from_log
from trades_csv import TradeLedger, HEADER


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


if __name__ == "__main__":
    unittest.main()
