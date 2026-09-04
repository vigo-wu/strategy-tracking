# coding: utf-8
"""qmt_common/pit_front 单测（含价差/等比双路径与静态 CSV 金标）。"""
from __future__ import annotations

import csv
import datetime
import json
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO = Path(__file__).resolve().parents[3]
PIT_PATH = REPO / "scripts" / "qmt_common" / "pit_front.py"
CSV_ROOT = REPO / "tools" / "csv"


def _ms(day: str) -> int:
    dt = datetime.datetime.strptime(day, "%Y%m%d")
    utc = dt - datetime.timedelta(hours=8)
    return int(utc.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)


def _load():
    A = SimpleNamespace(is_backtest=True, _pit_ohlc_cache={})
    ns = {"datetime": datetime, "A": A}
    src = PIT_PATH.read_text(encoding="utf-8")
    exec(compile(src, str(PIT_PATH), "exec"), ns, ns)
    ns["A"] = A
    return ns


def _load_closes(path: Path):
    days, closes = [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = row.get("datetime") or row.get("date") or ""
            d = "".join(ch for ch in str(raw) if ch.isdigit())[:8]
            if len(d) < 8:
                continue
            days.append(d)
            closes.append(float(row["close"]))
    return days, closes


class PitFrontTests(unittest.TestCase):
    def test_parse_and_jump(self):
        ns = _load()
        fac = {_ms("20240601"): [0.0, 0.3, 0.0, 0.0, 0.0, 0, 1.3]}
        ev = ns["pit_parse_events"](fac)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0][0], "20240601")
        days = ["20240101", "20240601", "20240602"]
        closes = [13.0, 10.0, 10.1]
        _o, _h, _l, c0 = ns["pit_adjust_ohlc"](
            days, closes, closes, closes, closes, ev, "20240531"
        )
        self.assertAlmostEqual(c0[0], 13.0, places=6)
        _o, _h, _l, c1 = ns["pit_adjust_ohlc"](
            days, closes, closes, closes, closes, ev, "20240601"
        )
        self.assertAlmostEqual(c1[0], 13.0 / 1.3, places=6)
        self.assertAlmostEqual(c1[1], 10.0, places=6)

    def test_empty_events_identity(self):
        ns = _load()
        days = ["20240101", "20240102"]
        closes = [1.0, 2.0]
        _o, _h, _l, c = ns["pit_adjust_ohlc"](
            days, closes, closes, closes, closes, [], "20240102"
        )
        self.assertEqual(c, closes)

    def test_multi_dr_product(self):
        ns = _load()
        fac = {
            _ms("20240301"): [0.0, 0.0, 0.0, 0.0, 0.0, 0, 1.1],
            _ms("20240601"): [0.0, 0.0, 0.0, 0.0, 0.0, 0, 1.2],
        }
        ev = ns["pit_parse_events"](fac)
        days = ["20240101"]
        closes = [12.0]
        _o, _h, _l, c = ns["pit_adjust_ohlc"](
            days, closes, closes, closes, closes, ev, "20240601"
        )
        self.assertAlmostEqual(c[0], 12.0 / (1.1 * 1.2), places=6)

    def test_should_apply(self):
        ns = _load()
        A = ns["A"]
        A.is_backtest = True
        self.assertTrue(ns["pit_should_apply"]("front_ratio"))
        self.assertTrue(ns["pit_should_apply"]("front"))
        self.assertFalse(ns["pit_should_apply"]("none"))
        self.assertEqual(ns["pit_mode_from_div"]("front"), "diff")
        self.assertEqual(ns["pit_mode_from_div"]("front_ratio"), "ratio")
        A.is_backtest = False
        self.assertFalse(ns["pit_should_apply"]("front_ratio"))

    def test_cached_incremental(self):
        ns = _load()
        fac = {_ms("20240601"): [0.0, 0.0, 0.0, 0.0, 0.0, 0, 1.5]}
        ev = ns["pit_parse_events"](fac)
        days = ["20240101", "20240602"]
        closes = [15.0, 10.0]
        a1 = ns["pit_adjust_ohlc_cached"](
            "600000.SH", days, closes, closes, closes, closes, ev, "20240501"
        )
        self.assertAlmostEqual(a1[3][0], 15.0, places=6)
        a2 = ns["pit_adjust_ohlc_cached"](
            "600000.SH", days, closes, closes, closes, closes, ev, "20240601"
        )
        self.assertAlmostEqual(a2[3][0], 15.0 / 1.5, places=6)

    def test_diff_cash_jump(self):
        ns = _load()
        fac = {_ms("20240601"): [0.5, 0.0, 0.0, 0.0, 0.0, 0, 1.05]}
        full = ns["pit_parse_full_events"](fac)
        days = ["20240101", "20240601"]
        closes = [10.0, 9.5]
        _o, _h, _l, c0 = ns["pit_adjust_ohlc"](
            days, closes, closes, closes, closes, full, "20240531", mode="diff"
        )
        self.assertAlmostEqual(c0[0], 10.0, places=6)
        _o, _h, _l, c1 = ns["pit_adjust_ohlc"](
            days, closes, closes, closes, closes, full, "20240601", mode="diff"
        )
        self.assertAlmostEqual(c1[0], 9.5, places=6)
        self.assertAlmostEqual(c1[1], 9.5, places=6)

    def test_diff_bonus_step(self):
        ns = _load()
        # 现金后再送股：合成自洽
        fac = {
            _ms("20240301"): [0.2, 0.0, 0.0, 0.0, 0.0, 0, 1.02],
            _ms("20240601"): [0.0, 0.3, 0.0, 0.0, 0.0, 0, 1.3],
        }
        full = ns["pit_parse_full_events"](fac)
        p = ns["pit_cum_diff"](full, "20240101", "20240601", 13.0)
        # (13 - 0.2) / 1.3
        self.assertAlmostEqual(p, (13.0 - 0.2) / 1.3, places=6)

    def test_mode_isolation(self):
        ns = _load()
        fac = {_ms("20240601"): [0.3, 0.0, 0.0, 0.0, 0.0, 0, 1.05]}
        full = ns["pit_parse_full_events"](fac)
        ratio = ns["pit_parse_events"](fac)
        days = ["20240101", "20240602"]
        closes = [10.5, 10.0]
        _o, _h, _l, c_r = ns["pit_adjust_ohlc"](
            days, closes, closes, closes, closes, ratio, "20240602", mode="ratio"
        )
        _o, _h, _l, c_d = ns["pit_adjust_ohlc"](
            days, closes, closes, closes, closes, full, "20240602", mode="diff"
        )
        self.assertAlmostEqual(c_r[0], 10.5 / 1.05, places=6)
        self.assertAlmostEqual(c_d[0], 10.5 - 0.3, places=6)
        self.assertNotAlmostEqual(c_r[0], c_d[0], places=4)
        self.assertAlmostEqual(c_r[1], 10.0, places=6)
        self.assertAlmostEqual(c_d[1], 10.0, places=6)

    def test_gold_csv_final_asof(self):
        """终态 asof：PIT(none) 对齐静态 front / front_ratio。"""
        if not (CSV_ROOT / "none").is_dir():
            self.skipTest("no tools/csv")
        ns = _load()
        for code in ("600350_SH", "601939_SH"):
            fac_path = CSV_ROOT / "divid_factors" / ("%s.json" % code)
            none_path = list((CSV_ROOT / "none").glob("%s_1d_*.csv" % code))
            front_path = list((CSV_ROOT / "front").glob("%s_1d_*.csv" % code))
            ratio_path = list((CSV_ROOT / "front_ratio").glob("%s_1d_*.csv" % code))
            if not (fac_path.is_file() and none_path and front_path and ratio_path):
                self.skipTest("missing csv/factors for %s" % code)
            fac = json.loads(fac_path.read_text(encoding="utf-8"))
            full = ns["pit_parse_full_events"](fac)
            ratio_ev = ns["pit_parse_events"](fac)
            nd, nc = _load_closes(none_path[0])
            fd, fc = _load_closes(front_path[0])
            rd, rc = _load_closes(ratio_path[0])
            asof = nd[-1]
            _o, _h, _l, pit_d = ns["pit_adjust_ohlc"](
                nd, nc, nc, nc, nc, full, asof, mode="diff"
            )
            _o, _h, _l, pit_r = ns["pit_adjust_ohlc"](
                nd, nc, nc, nc, nc, ratio_ev, asof, mode="ratio"
            )
            fmap = dict(zip(fd, fc))
            rmap = dict(zip(rd, rc))
            for d, p in zip(nd, pit_d):
                if d in fmap and fmap[d] > 0:
                    self.assertAlmostEqual(
                        p, fmap[d], places=9, msg="%s diff %s" % (code, d)
                    )
            for d, p in zip(nd, pit_r):
                if d in rmap and rmap[d] > 0:
                    self.assertAlmostEqual(
                        p, rmap[d], places=9, msg="%s ratio %s" % (code, d)
                    )


if __name__ == "__main__":
    unittest.main()
