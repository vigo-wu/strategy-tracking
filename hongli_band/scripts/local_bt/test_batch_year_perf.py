# coding: utf-8
"""批量单票合计分年绩效：range 连续账户 vs 按年分段独立空仓。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batch_year_perf import (
    batch_naive_year_perf,
    collect_batch_detail_trades,
    parse_detail_trades,
)


HEADER = (
    "代码,名称,品种类型,行业,多空,操作时间,操作类型,操作价格,当前价格,盈利,"
    "买入权重(%),当前权重(%),数量,交易费用,市值,业务类型"
)


def _t(buy, sell, pnl, stock="600000.SH"):
    return {
        "stock": stock,
        "buy_open_day": buy,
        "sell_exec_day": sell,
        "pnl": pnl,
        "cost": 10000.0,
        "shares": 100,
        "buy_price": 100.0,
    }


def _row(**kwargs):
    base = {
        "ok": True,
        "detail": "dummy.csv",
        "budget": 100000.0,
        "dividend_type": "front",
        "sum_pnl": 0.0,
        "stock": "600000.SH",
    }
    base.update(kwargs)
    return base


def _write_detail(path: Path, body_lines: list[str]) -> Path:
    path.write_text("\n".join([HEADER] + body_lines) + "\n", encoding="gbk")
    return path


class BatchNaiveYearPerfTests(unittest.TestCase):
    def test_range_two_stocks_same_year_uses_n_ok_budget(self):
        rows = [
            _row(stock="000001.SZ", sum_pnl=1000.0),
            _row(stock="000002.SZ", detail="dummy2.csv", sum_pnl=2000.0),
        ]
        packed = [
            {**rows[0], "trades": [_t("20180105", "20180110", 1000.0, "000001.SZ")]},
            {**rows[1], "trades": [_t("20180115", "20180119", 2000.0, "000002.SZ")]},
        ]
        out = batch_naive_year_perf(rows, split="range", packed=packed)
        self.assertTrue(out["ok"])
        self.assertEqual(out["budget"], 200000.0)
        self.assertEqual(out["n_ok"], 2)
        self.assertEqual(out["n_buy"], 2)
        self.assertEqual(out["sum_pnl"], 3000.0)
        row = out["table"].iloc[0]
        self.assertEqual(str(row["year"]), "2018")
        self.assertEqual(row["year_pnl"], 3000.0)
        self.assertEqual(row["start_equity"], 200000.0)
        self.assertAlmostEqual(float(row["year_ret_pct"]), 1.5)

    def test_year_split_next_year_starts_fresh(self):
        rows = [
            _row(year="2017", sum_pnl=1000.0, detail="y2017.csv"),
            _row(year="2018", sum_pnl=500.0, detail="y2018.csv"),
        ]
        packed = [
            {**rows[0], "trades": [_t("20170105", "20170110", 1000.0)]},
            {**rows[1], "trades": [_t("20180105", "20180110", 500.0)]},
        ]
        out = batch_naive_year_perf(rows, split="year", packed=packed)
        self.assertTrue(out["ok"])
        by = {str(r["year"]): r for _, r in out["table"].iterrows()}
        self.assertEqual(by["2017"]["start_equity"], 100000.0)
        self.assertEqual(by["2017"]["end_equity"], 101000.0)
        self.assertEqual(by["2018"]["start_equity"], 100000.0)
        self.assertNotEqual(by["2018"]["start_equity"], by["2017"]["end_equity"])
        self.assertEqual(out["budget_by_year"]["2017"], 100000.0)
        self.assertEqual(out["budget_by_year"]["2018"], 100000.0)

    def test_range_two_years_chain_start_equals_prior_end(self):
        rows = [
            _row(stock="A", sum_pnl=1000.0, detail="a.csv"),
            _row(stock="B", sum_pnl=-400.0, detail="b.csv"),
        ]
        packed = [
            {**rows[0], "trades": [_t("20170105", "20170110", 1000.0, "A")]},
            {**rows[1], "trades": [_t("20180105", "20180110", -400.0, "B")]},
        ]
        out = batch_naive_year_perf(rows, split="range", packed=packed)
        self.assertEqual(out["budget"], 200000.0)
        by = {str(r["year"]): r for _, r in out["table"].iterrows()}
        self.assertEqual(by["2017"]["start_equity"], 200000.0)
        self.assertEqual(by["2017"]["end_equity"], 201000.0)
        self.assertEqual(by["2018"]["start_equity"], by["2017"]["end_equity"])

    def test_mixed_div_refuses(self):
        rows = [
            _row(dividend_type="front"),
            _row(detail="b.csv", dividend_type="front_ratio"),
        ]
        out = batch_naive_year_perf(rows, split="range")
        self.assertFalse(out["ok"])
        self.assertIn("复权", out["reason"])

    def test_mixed_ma_requires_selector(self):
        rows = [
            _row(ma_type="SMA"),
            _row(detail="b.csv", ma_type="EMA"),
        ]
        out = batch_naive_year_perf(rows, split="range")
        self.assertFalse(out["ok"])
        self.assertIn("SMA", out["reason"])
        packed = [
            {**rows[0], "trades": [_t("20180105", "20180110", 100.0)]},
            {**rows[1], "trades": [_t("20180115", "20180119", 900.0)]},
        ]
        picked = batch_naive_year_perf(rows, split="range", ma_type="EMA", packed=packed)
        self.assertTrue(picked["ok"])
        self.assertEqual(picked["n_ok"], 1)
        self.assertEqual(picked["sum_pnl"], 900.0)

    def test_collect_parses_detail_and_cache(self):
        lines = [
            "600000,浦发,股票,银行,多,2018-01-10 15:00:00,买入,10,10,0,0,0,100,0,1000,普通",
            "600000,浦发,股票,银行,多,2018-01-15 15:00:00,卖出,11,11,1000,0,0,100,0,1100,普通",
        ]
        with tempfile.TemporaryDirectory() as td:
            p = _write_detail(Path(td) / "local_bt_600000_操作明细.csv", lines)
            cache: dict = {}
            rows = [_row(detail=str(p), stock="600000.SH", sum_pnl=1000.0)]
            packed = collect_batch_detail_trades(rows, cache=cache)
            self.assertEqual(len(packed), 1)
            trades = packed[0]["trades"]
            self.assertEqual(len(trades), 1)
            self.assertAlmostEqual(float(trades[0]["pnl"]), 1000.0, places=2)
            self.assertEqual(len(cache), 1)
            again = parse_detail_trades(p, cache=cache)
            self.assertEqual(len(again), 1)
            self.assertAlmostEqual(float(again[0]["pnl"]), 1000.0, places=2)


if __name__ == "__main__":
    unittest.main()
