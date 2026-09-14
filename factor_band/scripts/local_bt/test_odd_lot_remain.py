# coding: utf-8
"""送转零股残仓：引擎保留并可卖掉，成交不按 95% 误清。"""
from __future__ import annotations

import datetime
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
LOTS_PATH = REPO / "scripts" / "qmt_common" / "single" / "lots.py"
ORDERS_PATH = REPO / "scripts" / "qmt_common" / "single" / "orders.py"


def _load_lots_ns():
    A = SimpleNamespace(
        position=None,
        lots=[],
        is_backtest=True,
        bt_held=0,
        hold_peak=None,
        hold_close_peak=None,
        hold_max_ret=0.0,
        hold_bars=0,
        _hold_count_bar="",
    )

    def _has_position():
        pos = getattr(A, "position", None)
        return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) > 0

    def _pos_shares():
        if not _has_position():
            return 0
        return int(A.position.get("shares", 0) or 0)

    def _bt_held_vol():
        return int(getattr(A, "bt_held", 0) or 0)

    def _event_log(event, **fields):
        pass

    def _strategy_tag():
        return "[HlBand]"

    ns = {
        "datetime": datetime,
        "A": A,
        "SCALE_LOTS": True,
        "_has_position": _has_position,
        "_pos_shares": _pos_shares,
        "_bt_held_vol": _bt_held_vol,
        "_event_log": _event_log,
        "_strategy_tag": _strategy_tag,
    }
    src = LOTS_PATH.read_text(encoding="utf-8")
    exec(compile(src, str(LOTS_PATH), "exec"), ns, ns)
    ns["A"] = A
    return ns


def _load_orders_ns():
    A = SimpleNamespace(
        position={
            "shares": 2610,
            "price": 34.94,
            "cost": 91193.4,
            "opened_at": "20230504093000",
            "lots": 1,
        },
        lots=[],
        is_backtest=True,
        bt_held=2610,
        bt_locked=0,
        acted=set(),
        pending=None,
        stock="603659.SH",
    )

    def _has_position():
        pos = getattr(A, "position", None)
        return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) > 0

    def _pos_shares():
        if not _has_position():
            return 0
        return int(A.position.get("shares", 0) or 0)

    def _bt_held_vol():
        return int(getattr(A, "bt_held", 0) or 0)

    def _bt_held_set(vol):
        A.bt_held = max(0, int(vol))

    def _clear_after_sell(now, reason, last=None):
        A.position = None
        A.lots = []
        A.acted.add("SELL")
        A.bt_held = 0

    def _save_state():
        pass

    def _event_log(event, **fields):
        pass

    def _strategy_tag():
        return "[HlBand]"

    ns = {
        "datetime": datetime,
        "A": A,
        "DRY_RUN": True,
        "SCALE_LOTS": False,
        "_has_position": _has_position,
        "_pos_shares": _pos_shares,
        "_bt_held_vol": _bt_held_vol,
        "_bt_held_set": _bt_held_set,
        "_bt_held_add": lambda *a, **k: None,
        "_clear_after_sell": _clear_after_sell,
        "_save_state": _save_state,
        "_event_log": _event_log,
        "_strategy_tag": _strategy_tag,
        "_available_cash": lambda: 0,
        "_lot": lambda px, budget: 0,
        "_max_sell_vol": lambda now=None: int(getattr(A, "bt_held", 0) or 0),
        "_allow_t0": lambda: False,
        "_broker_position": lambda stock: (0, 0, 0.0),
        "_new_remark": lambda *a, **k: "SELL",
        "_passorder_live": lambda *a, **k: 0,
        "passorder": lambda *a, **k: None,
    }
    src = ORDERS_PATH.read_text(encoding="utf-8")
    exec(compile(src, str(ORDERS_PATH), "exec"), ns, ns)
    ns["A"] = A
    return ns


class OddLotRemainTests(unittest.TestCase):
    def test_sync_keeps_bonus_odd_lot(self):
        ns = _load_lots_ns()
        A = ns["A"]
        A.lots = [
            {
                "id": 1,
                "shares": 10,
                "price": 34.94,
                "opened_at": "20230504093000",
                "hold_peak": 37.0,
                "hold_close_peak": 37.0,
                "hold_max_ret": 0.0,
                "hold_bars": 3,
                "hold_count_bar": "",
            }
        ]
        A.bt_held = 10
        ns["_sync_position_from_lots"]()
        self.assertIsNotNone(A.position)
        self.assertEqual(int(A.position["shares"]), 10)
        self.assertEqual(len(A.lots), 1)
        self.assertEqual(int(A.lots[0]["shares"]), 10)

    def test_ensure_and_want_vol_odd_only(self):
        ns = _load_lots_ns()
        A = ns["A"]
        A.position = {
            "shares": 10,
            "price": 34.94,
            "cost": 349.4,
            "opened_at": "20230504093000",
        }
        A.lots = [{"id": 2, "shares": 10, "price": 34.94, "opened_at": "20230504093000"}]
        lots = ns["_ensure_lots"]()
        self.assertEqual(len(lots), 1)
        self.assertEqual(int(lots[0]["shares"]), 10)
        self.assertEqual(ns["_lots_want_vol"]([2]), 10)

    def test_partial_sell_keeps_odd_remainder(self):
        ns = _load_orders_ns()
        A = ns["A"]
        now = datetime.datetime(2023, 5, 26, 15, 0, 0)
        ns["_apply_sell_fill"](now, "trail_stop", 37.3, 2600)
        self.assertIsNotNone(A.position)
        self.assertEqual(int(A.position["shares"]), 10)
        self.assertEqual(int(A.bt_held), 10)
        self.assertNotIn("SELL", A.acted)
        ns["_apply_sell_fill"](now, "trail_stop", 37.3, 10)
        self.assertIsNone(A.position)
        self.assertEqual(int(A.bt_held), 0)
        self.assertIn("SELL", A.acted)


if __name__ == "__main__":
    unittest.main()
