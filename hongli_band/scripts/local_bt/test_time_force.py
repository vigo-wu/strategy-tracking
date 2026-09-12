# coding: utf-8
"""_time_force_hit：BARS 边界 / 破线 / 让路 / 死钱立即强平（不依赖 QMT 终端）。"""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
HLBAND = HERE.parent / "qmt" / "hlband"
INDICATORS_DIR = HLBAND / "indicators"
TRAIL_PATH = HLBAND / "factors" / "lib" / "trail_stop.py"
TIME_FORCE_PATH = HLBAND / "factors" / "lib" / "time_force.py"
_INDICATOR_FILES = (
    "util.py",
    "sma.py",
    "ema.py",
    "macd.py",
    "price_ma.py",
)

TIERS = (
    (0.03, 0.06, 0.015, None),
    (0.06, 0.10, 0.03, 0.03),
    (0.10, None, 0.04, None),
)


def _load_tf_ns(**overrides):
    A = SimpleNamespace(
        stock="600000.SH",
        hold_max_ret=0.0,
        hold_peak=None,
        time_force_trend_skip=False,
        time_force_grace_until=None,
    )
    logs = []

    ns = {
        "np": np,
        "A": A,
        "STRATEGY_NAME": "HlBand",
        "MA_TYPE": "SMA",
        "BOOK_STOCKS": {},
        "TIME_FORCE_BARS": 30,
        "D_MA_SLOW": 60,
        "TRAIL_TIERS": TIERS,
        "_save_state": lambda: logs.append("save"),
        "_event_log": lambda event, **fields: logs.append((event, fields)),
        "_pos_cost_price": lambda: 100.0,
    }
    ns.update(overrides)
    for name in _INDICATOR_FILES:
        path = INDICATORS_DIR / name
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), ns, ns)
    for path in (TRAIL_PATH, TIME_FORCE_PATH):
        src = path.read_text(encoding="utf-8")
        exec(compile(src, str(path), "exec"), ns, ns)
    ns["_logs"] = logs
    ns["A"] = A
    return ns


def _closes(n=80, px=10.0):
    return [float(px)] * int(n)


def _lot(cost=100.0, peak=102.0, skip=False, grace=None):
    return {
        "id": 1,
        "price": float(cost),
        "hold_peak": float(peak),
        "hold_max_ret": (float(peak) - float(cost)) / float(cost),
        "time_force_trend_skip": bool(skip),
        "time_force_grace_until": grace,
    }


class TimeForceHitTest(unittest.TestCase):
    def test_hold_bars_equal_limit_no_hit(self) -> None:
        ns = _load_tf_ns()
        hit = ns["_time_force_hit"](10.0, _closes(), 30, lot=_lot())
        self.assertFalse(hit)
        self.assertIsNone(ns["A"].time_force_grace_until)

    def test_dead_money_on_ma_hits_immediately(self) -> None:
        ns = _load_tf_ns()
        lot = _lot(cost=100.0, peak=102.0)
        hit = ns["_time_force_hit"](10.0, _closes(), 31, lot=lot)
        self.assertTrue(hit)
        self.assertNotIn("time_force_grace", [x[0] for x in ns["_logs"] if isinstance(x, tuple)])
        self.assertIsNone(lot.get("time_force_grace_until"))
        self.assertIsNone(ns["A"].time_force_grace_until)

    def test_break_ma60_hits_regardless_of_peak(self) -> None:
        ns = _load_tf_ns()
        armed = _lot(cost=100.0, peak=104.0)
        hit = ns["_time_force_hit"](9.5, _closes(), 31, lot=armed)
        self.assertTrue(hit)

    def test_armed_on_ma_skips_calendar(self) -> None:
        ns = _load_tf_ns()
        lot = _lot(cost=100.0, peak=104.0)
        hit = ns["_time_force_hit"](10.0, _closes(), 31, lot=lot)
        self.assertFalse(hit)
        self.assertTrue(lot.get("time_force_trend_skip"))
        events = [x[0] for x in ns["_logs"] if isinstance(x, tuple)]
        self.assertIn("time_force_skip_trend", events)

    def test_already_skip_still_hits_on_ma_break(self) -> None:
        ns = _load_tf_ns()
        lot = _lot(cost=100.0, peak=104.0, skip=True)
        hit = ns["_time_force_hit"](9.5, _closes(), 31, lot=lot)
        self.assertTrue(hit)

    def test_bars_off_or_slow_off(self) -> None:
        ns0 = _load_tf_ns(TIME_FORCE_BARS=0)
        self.assertFalse(ns0["_time_force_hit"](9.5, _closes(), 99, lot=_lot()))
        ns_s = _load_tf_ns(D_MA_SLOW=0)
        self.assertFalse(ns_s["_time_force_hit"](9.5, _closes(), 99, lot=_lot()))


if __name__ == "__main__":
    unittest.main()
