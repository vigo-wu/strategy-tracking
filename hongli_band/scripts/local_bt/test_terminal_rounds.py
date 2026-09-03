# coding: utf-8
"""parse_terminal_rounds：组合明细须按代码 FIFO，避免跨票错配假收益%。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analyze import (
    add_stats_from_trades,
    enrich_trades_signals_from_log,
    mark_add_lots,
    parse_fill_signals_from_log,
    report_mod,
)


HEADER = (
    "代码,名称,品种类型,行业,多空,操作时间,操作类型,操作价格,当前价格,盈利,"
    "买入权重(%),当前权重(%),数量,交易费用,市值,业务类型"
)


def _write_detail(path: Path, body_lines: list[str]) -> Path:
    path.write_text("\n".join([HEADER] + body_lines) + "\n", encoding="gbk")
    return path


class ParseTerminalRoundsTests(unittest.TestCase):
    def test_cross_stock_sell_order_does_not_mismatch(self):
        """买 A→买 B→卖 B→卖 A 时，不得把 B 的卖配到 A 的买（曾出现假 -41%）。"""
        lines = [
            "600000,浦发,股票,银行,多,2024-11-20 15:00:00,买入,4.56,4.56,0,0,0,5700,0,25992,普通",
            "601988,中行,股票,银行,多,2024-11-20 15:00:00,买入,8.11,8.11,0,0,0,6200,0,50282,普通",
            "601988,中行,股票,银行,多,2024-12-11 15:00:00,卖出,8.73,8.73,3844,0,0,6200,0,54126,普通",
            "600000,浦发,股票,银行,多,2024-12-11 15:00:00,卖出,4.72,4.72,912,0,0,5700,0,26904,普通",
        ]
        with tempfile.TemporaryDirectory() as td:
            p = _write_detail(Path(td) / "book_操作明细.csv", lines)
            rounds = report_mod().parse_terminal_rounds(p)
        self.assertEqual(len(rounds), 2)
        by_sell = {round(r["sell_price"], 2): r for r in rounds}
        b = by_sell[8.73]
        a = by_sell[4.72]
        self.assertAlmostEqual(b["buy_price"], 8.11, places=4)
        self.assertAlmostEqual(a["buy_price"], 4.56, places=4)
        self.assertGreater(b["ret_pct"], 0)
        self.assertGreater(a["ret_pct"], 0)
        self.assertLess(abs(b["ret_pct"]), 20)
        self.assertLess(abs(a["ret_pct"]), 20)
        self.assertNotAlmostEqual(a["ret_pct"], -41.8, places=0)
        self.assertEqual(b.get("stock"), "601988")
        self.assertEqual(a.get("stock"), "600000")

    def test_multi_lot_sell_keeps_each_buy_day(self):
        """一笔卖出吃掉两笔买入时，拆成两轮，保留各自买入日/买价。"""
        lines = [
            "600350,山东高速,股票,交运,多,2022-09-16 15:00:00,买入,4.51,4.51,0,0,0,13700,0,61807,普通",
            "600350,山东高速,股票,交运,多,2022-10-17 15:00:00,买入,4.68,4.68,0,0,0,7900,0,36972,普通",
            "600350,山东高速,股票,交运,多,2022-10-26 15:00:00,卖出,4.69,4.69,3285.75,0,0,21600,0,101304,普通",
        ]
        with tempfile.TemporaryDirectory() as td:
            p = _write_detail(Path(td) / "multi_操作明细.csv", lines)
            rounds = report_mod().parse_terminal_rounds(p)
        self.assertEqual(len(rounds), 2)
        by_day = {r["buy_open_day"]: r for r in rounds}
        self.assertIn("20220916", by_day)
        self.assertIn("20221017", by_day)
        self.assertEqual(by_day["20220916"]["shares"], 13700)
        self.assertEqual(by_day["20221017"]["shares"], 7900)
        self.assertAlmostEqual(by_day["20220916"]["buy_price"], 4.51, places=4)
        self.assertAlmostEqual(by_day["20221017"]["buy_price"], 4.68, places=4)
        self.assertAlmostEqual(
            by_day["20220916"]["pnl"] + by_day["20221017"]["pnl"], 3285.75, places=2
        )

    def test_single_stock_still_fifo(self):
        lines = [
            "600350,山东高速,股票,交运,多,2024-01-09 15:00:00,买入,3.59,3.59,0,0,0,4100,0,14719,普通",
            "600350,山东高速,股票,交运,多,2024-01-30 15:00:00,卖出,3.80,3.80,861,0,0,4100,0,15580,普通",
        ]
        with tempfile.TemporaryDirectory() as td:
            p = _write_detail(Path(td) / "one_操作明细.csv", lines)
            rounds = report_mod().parse_terminal_rounds(p)
        self.assertEqual(len(rounds), 1)
        self.assertAlmostEqual(rounds[0]["buy_price"], 3.59, places=4)
        self.assertAlmostEqual(rounds[0]["sell_price"], 3.80, places=4)
        self.assertAlmostEqual(rounds[0]["pnl"], 861.0, places=2)

    def test_leading_zero_code_not_stripped(self):
        """002001 被 pandas 读成 int 2001 时，轮次仍应还原为 002001。"""
        lines = [
            "002001,新和成,股票,医药,多,2021-04-21 15:00:00,买入,21.74,21.74,0,0,0,1200,0,26088,普通",
            "002001,新和成,股票,医药,多,2021-04-23 15:00:00,卖出,22.25,22.25,620.33,0,0,1200,0,26700,普通",
        ]
        with tempfile.TemporaryDirectory() as td:
            p = _write_detail(Path(td) / "zhc_操作明细.csv", lines)
            rounds = report_mod().parse_terminal_rounds(p)
            raw = report_mod()._read_csv_auto(p)
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0].get("stock"), "002001")
        self.assertNotEqual(rounds[0].get("stock"), "2001")
        self.assertEqual(str(raw.iloc[0]["代码"]), "002001")
        self.assertEqual(report_mod().normalize_terminal_code(2001), "002001")
        self.assertEqual(report_mod().normalize_terminal_code(2001.0), "002001")
        self.assertEqual(report_mod().normalize_terminal_code("002001.SZ"), "002001")

    def test_enrich_signals_from_log(self):
        log = "\n".join(
            [
                "HlBandV5 BUY by signal=pullback_vol label=买1-回踩 all=pullback_vol(买1-回踩) signal_day=20190221 @close=4.04",
                "HlBandV5 BUY BUY 601939.SH x11100 20260902 @ 4.04",
                "HlBandV5 BUY filled {'shares': 11100, 'price': 4.04, 'cost': 44844.0, 'opened_at': '20190221000000', 'lots': 1}",
                "HlBandV5 SELL by signal=trail_stop label=卖1-移动止盈 all=trail_stop(卖1) signal_day=20190226 @close=4.29",
                "HlBandV5 SELL trail_stop 601939.SH x11100 20260902 @ 4.29",
                "HlBandV5 SELL done trail_stop last= 4.29 cleared {'shares': 11100, 'price': 4.04, 'cost': 44844.0, 'opened_at': '20190221000000', 'lots': 1}",
            ]
        )
        ev = parse_fill_signals_from_log(log)
        self.assertEqual(len(ev), 2)
        with tempfile.TemporaryDirectory() as td:
            lp = Path(td) / "x.txt"
            lp.write_text(log, encoding="utf-8")
            trades = [
                {
                    "i": 1,
                    "stock": "601939",
                    "buy_open_day": "20190221",
                    "sell_exec_day": "20190226",
                    "shares": 11100,
                    "buy_signal": "-",
                    "sell_signal": "-",
                }
            ]
            out = enrich_trades_signals_from_log(trades, lp)
        self.assertEqual(out[0]["buy_signal"], "pullback_vol")
        self.assertEqual(out[0]["sell_signal"], "trail_stop")

    def test_enrich_add_buy_and_exact_before_loose(self):
        """加仓 BUY add filled；同日小仓不得抢走精确股数信号。"""
        log = "\n".join(
            [
                "HlBandV5 BUY by signal=pullback_vol label=买1 all=pullback_vol signal_day=20191201 @close=3.2",
                "HlBandV5 BUY BUY 600350.SH x9400 20260902 @ 3.2",
                "HlBandV5 BUY filled {'shares': 9400, 'price': 3.2, 'cost': 30080.0, 'opened_at': '20191201000000', 'lots': 1}",
                "HlBandV5 BUY add by signal=plat_break label=加仓 all=plat_break signal_day=20191216 @close=3.37",
                "HlBandV5 ADD BUY 600350.SH x6100 20260902 @ 3.37",
                "HlBandV5 BUY add filled {'add_shares': 6100, 'price': 3.37, 'lots': 2, 'total': 15500, 'avg': 3.31}",
                "HlBandV5 SELL by signal=trail_stop label=卖1 all=trail_stop signal_day=20191220 @close=3.5",
                "HlBandV5 SELL trail_stop 600350.SH x6100 20260902 @ 3.5",
                "HlBandV5 SELL trail_stop 600350.SH x9400 20260902 @ 3.5",
            ]
        )
        ev = parse_fill_signals_from_log(log)
        buys = [e for e in ev if e["kind"] == "buy"]
        self.assertEqual(len(buys), 2)
        self.assertFalse(buys[0].get("is_add"))
        self.assertTrue(buys[1].get("is_add"))
        self.assertEqual(buys[1]["signal"], "plat_break")
        self.assertEqual(buys[1]["shares"], 6100)
        self.assertEqual(buys[1]["day"], "20191216")
        with tempfile.TemporaryDirectory() as td:
            lp = Path(td) / "x.txt"
            lp.write_text(log, encoding="utf-8")
            # 同日另一笔小仓排在前面，精确匹配须先保住 9400
            trades = [
                {
                    "i": 1,
                    "stock": "600350",
                    "buy_open_day": "20191201",
                    "sell_exec_day": "20191220",
                    "shares": 3000,
                    "pnl": 100.0,
                    "ret_pct": 3.0,
                    "buy_signal": "-",
                    "sell_signal": "-",
                },
                {
                    "i": 2,
                    "stock": "600350",
                    "buy_open_day": "20191201",
                    "sell_exec_day": "20191220",
                    "shares": 9400,
                    "pnl": 200.0,
                    "ret_pct": 5.0,
                    "buy_signal": "-",
                    "sell_signal": "-",
                },
                {
                    "i": 3,
                    "stock": "600350",
                    "buy_open_day": "20191216",
                    "sell_exec_day": "20191220",
                    "shares": 6100,
                    "pnl": -50.0,
                    "ret_pct": -2.5,
                    "buy_signal": "-",
                    "sell_signal": "-",
                },
            ]
            out = enrich_trades_signals_from_log(trades, lp)
            out = mark_add_lots(out)
        self.assertEqual(out[1]["buy_signal"], "pullback_vol")
        self.assertEqual(out[2]["buy_signal"], "plat_break")
        self.assertEqual(out[2]["sell_signal"], "trail_stop")
        # 同日小仓共享买入信号
        self.assertEqual(out[0]["buy_signal"], "pullback_vol")
        self.assertFalse(out[0].get("is_add"))
        self.assertFalse(out[1].get("is_add"))
        self.assertTrue(out[2].get("is_add"))
        stats = add_stats_from_trades(out)
        self.assertEqual(stats["n_add"], 1)
        self.assertEqual(stats["add_win_n"], 0)
        self.assertEqual(stats["add_win_rate"], 0.0)
        self.assertEqual(stats["add_sum_pnl"], -50.0)
        self.assertEqual(stats["add_avg_ret"], -2.5)
        self.assertEqual(stats["add_max_win"], -2.5)
        self.assertEqual(stats["add_max_loss"], -2.5)

    def test_mark_add_lots_overlap_without_log(self):
        """无 log 时：后买日落在先前持仓区间内 → 加仓。"""
        trades = [
            {
                "i": 1,
                "stock": "600350",
                "buy_open_day": "20220916",
                "sell_exec_day": "20221026",
                "shares": 13700,
                "pnl": 2000.0,
                "ret_pct": 4.0,
            },
            {
                "i": 2,
                "stock": "600350",
                "buy_open_day": "20221017",
                "sell_exec_day": "20221026",
                "shares": 7900,
                "pnl": 1285.0,
                "ret_pct": 1.5,
            },
        ]
        out = mark_add_lots(trades)
        self.assertFalse(out[0].get("is_add"))
        self.assertTrue(out[1].get("is_add"))
        stats = add_stats_from_trades(out)
        self.assertEqual(stats["n_add"], 1)
        self.assertEqual(stats["add_win_rate"], 100.0)
        self.assertEqual(stats["add_sum_pnl"], 1285.0)
        self.assertEqual(stats["add_avg_ret"], 1.5)
        self.assertEqual(stats["add_max_win"], 1.5)
        self.assertEqual(stats["add_max_loss"], 1.5)


if __name__ == "__main__":
    unittest.main()
