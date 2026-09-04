# coding: utf-8
"""qmt_common/single/ex_rights 单测（不依赖 QMT 终端）。"""
from __future__ import annotations

import datetime
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO = Path(__file__).resolve().parents[3]
EX_RIGHTS_PATH = REPO / "scripts" / "qmt_common" / "single" / "ex_rights.py"


def _ms_for_day(yyyymmdd: str) -> int:
    dt = datetime.datetime.strptime(yyyymmdd, "%Y%m%d")
    # 东八区 00:00 → UTC 前一日 16:00
    utc = dt - datetime.timedelta(hours=8)
    return int(utc.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)


def _load_ex_ns(**extra):
    scale_lots = bool(extra.get("scale_lots", False))
    A = SimpleNamespace(
        stock="600000.SH",
        is_backtest=False,
        position=None,
        lots=[],
        hold_peak=None,
        hold_close_peak=None,
        hold_max_ret=0.0,
        hold_bars=0,
        _hold_count_bar="",
        bt_held=0,
        bt_locked=0,
        ex_rights_applied=[],
        ex_rights_allot_pending=[],
        _divid_factors_cache={},
    )
    logs = []

    def _has_position():
        pos = getattr(A, "position", None)
        return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100

    def _bt_held_vol():
        return int(getattr(A, "bt_held", 0) or 0)

    def _save_state():
        logs.append("save")

    def _event_log(event, **fields):
        logs.append((event, fields))

    def _strategy_tag():
        return "[HlBand]"

    def _sync_position_from_lots():
        lots = [x for x in (A.lots or []) if isinstance(x, dict)]
        if not lots:
            A.position = None
            return
        total = sum(int(x.get("shares") or 0) for x in lots)
        cost_sum = sum(int(x.get("shares") or 0) * float(x.get("price") or 0) for x in lots)
        avg = (cost_sum / total) if total else 0.0
        A.position = {
            "shares": total,
            "price": avg,
            "cost": round(total * avg, 2),
            "opened_at": lots[0].get("opened_at") or "",
        }

    def _mirror_hold_from_lots():
        if not A.lots:
            return
        lot = A.lots[0]
        A.hold_peak = lot.get("hold_peak")
        A.hold_close_peak = lot.get("hold_close_peak")
        A.hold_max_ret = float(lot.get("hold_max_ret") or 0)

    def _ensure_lots():
        lots = getattr(A, "lots", None)
        cleaned = []
        if isinstance(lots, list):
            for lot in lots:
                if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= 100:
                    cleaned.append(lot)
        if cleaned:
            A.lots = cleaned
            return cleaned
        if _has_position():
            pos = A.position or {}
            px = float(pos.get("price", 0) or 0)
            peak = getattr(A, "hold_peak", None)
            if peak is None:
                peak = px
            A.lots = [
                {
                    "id": 1,
                    "shares": int(pos.get("shares", 0) or 0),
                    "price": px,
                    "opened_at": str(pos.get("opened_at", "") or ""),
                    "hold_peak": peak,
                    "hold_close_peak": getattr(A, "hold_close_peak", None) or px,
                    "hold_max_ret": float(getattr(A, "hold_max_ret", 0) or 0),
                    "hold_bars": int(getattr(A, "hold_bars", 0) or 0),
                    "hold_count_bar": "",
                }
            ]
            return A.lots
        A.lots = []
        return A.lots

    broker = {"vol": 0}

    def _broker_position(stock):
        return int(broker["vol"]), int(broker["vol"]), 0.0

    def _dividend_type():
        return str(extra.get("dividend_type") or "none")

    ns = {
        "datetime": datetime,
        "A": A,
        "STRATEGY_NAME": "HlBand",
        "SCALE_LOTS": scale_lots,
        "DRY_RUN": True,
        "DIVIDEND_TYPE": extra.get("dividend_type") or "none",
        "_has_position": _has_position,
        "_bt_held_vol": _bt_held_vol,
        "_save_state": _save_state,
        "_event_log": _event_log,
        "_strategy_tag": _strategy_tag,
        "_sync_position_from_lots": _sync_position_from_lots,
        "_mirror_hold_from_lots": _mirror_hold_from_lots,
        "_ensure_lots": _ensure_lots,
        "_broker_position": _broker_position,
        "_dividend_type": _dividend_type,
        "_diag_once": lambda *a, **k: None,
    }
    ns.update(extra.get("ns_extra") or {})
    src = EX_RIGHTS_PATH.read_text(encoding="utf-8")
    exec(compile(src, str(EX_RIGHTS_PATH), "exec"), ns, ns)
    ns["_logs"] = logs
    ns["_broker"] = broker
    ns["A"] = A
    return ns


def _trail_stop_hit(price, cost, peak, tiers=None):
    """与 hlband 阶梯逻辑一致的最小副本，供断言。"""
    if cost is None or cost <= 0 or peak is None or peak <= 0:
        return False
    max_profit = (float(peak) - float(cost)) / float(cost)
    tiers = tiers or (
        (0.03, 0.06, 0.015, None),
        (0.06, 0.10, 0.03, 0.03),
        (0.10, None, 0.04, None),
    )
    giveback_lim = None
    for lo, hi, giveback, _floor in tiers:
        if max_profit < float(lo):
            continue
        if hi is not None and max_profit >= float(hi):
            continue
        giveback_lim = float(giveback)
        break
    if giveback_lim is None:
        return False
    giveback = (float(peak) - float(price)) / float(peak)
    return giveback > giveback_lim


class ExRightsTests(unittest.TestCase):
    def test_cash_div_scales_and_trail_not_false(self):
        ns = _load_ex_ns()
        A = ns["A"]
        A.is_backtest = False
        A.position = {
            "shares": 1000,
            "price": 10.0,
            "cost": 10000.0,
            "opened_at": "20240101093000",
        }
        A.hold_peak = 11.0
        C = SimpleNamespace(
            divid_factors={
                _ms_for_day("20240601"): [0.5, 0.0, 0.0, 0.0, 0.0, 0, 1.05],
            }
        )
        # MockContext-style
        C.get_divid_factors = lambda stock: C.divid_factors

        price_after = 11.0 / 1.05
        # 未缩放时相对 peak 回撤巨大
        self.assertTrue(_trail_stop_hit(price_after, 10.0, 11.0))

        ns["_maybe_apply_ex_rights"](C, "20240601")
        cost = float(A.position["price"])
        peak = float(A.hold_peak)
        self.assertAlmostEqual(cost, 10.0 / 1.05, places=6)
        self.assertAlmostEqual(peak, 11.0 / 1.05, places=6)
        self.assertFalse(_trail_stop_hit(price_after, cost, peak))
        self.assertIn("20240601", A.ex_rights_applied)

    def test_bonus_scales_shares(self):
        ns = _load_ex_ns()
        A = ns["A"]
        A.position = {
            "shares": 1000,
            "price": 10.0,
            "cost": 10000.0,
            "opened_at": "20240101093000",
        }
        A.hold_peak = 10.0
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.0, 0.3, 0.0, 0.0, 0.0, 0, 1.3],
        }
        ns["_maybe_apply_ex_rights"](C, "20240601")
        self.assertEqual(A.position["shares"], 1300)
        self.assertAlmostEqual(A.position["price"], 10.0 / 1.3, places=6)

    def test_allot_default_unsubscribed(self):
        ns = _load_ex_ns()
        A = ns["A"]
        A.position = {
            "shares": 1000,
            "price": 10.0,
            "cost": 10000.0,
            "opened_at": "20240101093000",
        }
        A.hold_peak = 10.0
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.0, 0.0, 0.0, 0.3, 5.0, 0, 1.2],
        }
        ns["_maybe_apply_ex_rights"](C, "20240601")
        # 未认购：股数不含 allot
        self.assertEqual(A.position["shares"], 1000)
        self.assertAlmostEqual(A.position["price"], 10.0 / 1.2, places=6)
        self.assertEqual(len(A.ex_rights_allot_pending), 1)

    def test_allot_subscribe_later(self):
        ns = _load_ex_ns()
        A = ns["A"]
        A.position = {
            "shares": 1000,
            "price": 10.0,
            "cost": 10000.0,
            "opened_at": "20240101093000",
        }
        A.hold_peak = 10.0
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.0, 0.0, 0.0, 0.3, 5.0, 0, 1.2],
        }
        ns["_maybe_apply_ex_rights"](C, "20240601")
        self.assertEqual(A.position["shares"], 1000)
        # 后日到账：券商 1300
        ns["_broker"]["vol"] = 1300
        ns["_maybe_apply_ex_rights"](C, "20240610")
        self.assertEqual(A.position["shares"], 1300)
        # 加权成本 (10 - 0 + 0.3*5) / 1.3
        self.assertAlmostEqual(A.position["price"], (10.0 + 1.5) / 1.3, places=6)
        self.assertEqual(A.ex_rights_allot_pending, [])

    def test_same_open_day_skip_scale(self):
        ns = _load_ex_ns()
        A = ns["A"]
        A.position = {
            "shares": 1000,
            "price": 9.5,
            "cost": 9500.0,
            "opened_at": "20240601100000",
        }
        A.hold_peak = 9.5
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.5, 0.0, 0.0, 0.0, 0.0, 0, 1.05],
        }
        ns["_maybe_apply_ex_rights"](C, "20240601")
        self.assertAlmostEqual(A.position["price"], 9.5, places=6)
        self.assertIn("20240601", A.ex_rights_applied)

    def test_idempotent(self):
        ns = _load_ex_ns()
        A = ns["A"]
        A.position = {
            "shares": 1000,
            "price": 10.0,
            "cost": 10000.0,
            "opened_at": "20240101093000",
        }
        A.hold_peak = 10.0
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.5, 0.0, 0.0, 0.0, 0.0, 0, 1.05],
        }
        ns["_maybe_apply_ex_rights"](C, "20240601")
        px1 = A.position["price"]
        ns["_maybe_apply_ex_rights"](C, "20240601")
        self.assertAlmostEqual(A.position["price"], px1, places=6)

    def test_front_ratio_backtest_gate(self):
        ns = _load_ex_ns(dividend_type="front_ratio")
        A = ns["A"]
        A.is_backtest = True
        A.position = {
            "shares": 1000,
            "price": 10.0,
            "cost": 10000.0,
            "opened_at": "20240101093000",
        }
        A.hold_peak = 10.0
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.5, 0.0, 0.0, 0.0, 0.0, 0, 1.05],
        }
        ns["_maybe_apply_ex_rights"](C, "20240601")
        self.assertAlmostEqual(A.position["price"], 10.0, places=6)
        self.assertEqual(A.ex_rights_applied, [])

    def test_catchup_after_missed_day(self):
        ns = _load_ex_ns()
        A = ns["A"]
        A.position = {
            "shares": 1000,
            "price": 10.0,
            "cost": 10000.0,
            "opened_at": "20240101093000",
        }
        A.hold_peak = 10.0
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.5, 0.0, 0.0, 0.0, 0.0, 0, 1.05],
        }
        # 除权日后才上线
        ns["_maybe_apply_ex_rights"](C, "20240605")
        self.assertAlmostEqual(A.position["price"], 10.0 / 1.05, places=6)
        self.assertIn("20240601", A.ex_rights_applied)

    def test_scale_lots_empty_lots_allot_pending(self):
        """SCALE_LOTS + 仅有 position：ensure 后仍能建 allot_pending。"""
        ns = _load_ex_ns(scale_lots=True)
        A = ns["A"]
        A.lots = []
        A.position = {
            "shares": 1000,
            "price": 10.0,
            "cost": 10000.0,
            "opened_at": "20240101093000",
        }
        A.hold_peak = 10.0
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.0, 0.0, 0.0, 0.3, 5.0, 0, 1.2],
        }
        ns["_maybe_apply_ex_rights"](C, "20240601")
        self.assertTrue(A.lots)
        self.assertEqual(int(A.lots[0]["shares"]), 1000)
        self.assertEqual(len(A.ex_rights_allot_pending), 1)
        self.assertEqual(A.ex_rights_allot_pending[0]["vol0"], 1000)

    def test_scale_lots_bonus_and_subscribe(self):
        ns = _load_ex_ns(scale_lots=True)
        A = ns["A"]
        A.lots = [
            {
                "id": 1,
                "shares": 600,
                "price": 10.0,
                "opened_at": "20240101093000",
                "hold_peak": 11.0,
                "hold_close_peak": 11.0,
                "hold_max_ret": 0.1,
            },
            {
                "id": 2,
                "shares": 400,
                "price": 10.5,
                "opened_at": "20240201093000",
                "hold_peak": 11.0,
                "hold_close_peak": 11.0,
                "hold_max_ret": 0.05,
            },
        ]
        ns["_sync_position_from_lots"]()
        A.hold_peak = 11.0
        C = SimpleNamespace()
        C.get_divid_factors = lambda stock: {
            _ms_for_day("20240601"): [0.0, 0.3, 0.0, 0.0, 0.0, 0, 1.3],
        }
        ns["_maybe_apply_ex_rights"](C, "20240601")
        self.assertEqual(A.position["shares"], 1300)
        self.assertEqual(int(A.lots[0]["shares"]), 780)
        self.assertEqual(int(A.lots[1]["shares"]), 520)
        self.assertAlmostEqual(float(A.lots[0]["price"]), 10.0 / 1.3, places=6)


if __name__ == "__main__":
    unittest.main()
