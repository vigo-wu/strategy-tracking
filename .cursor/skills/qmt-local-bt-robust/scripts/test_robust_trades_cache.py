# coding: utf-8
"""trades_cache_key / sidecar 命中条件（不跑完整回放）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
LOCAL_BT = REPO / "factor_band" / "scripts" / "local_bt"
if str(LOCAL_BT) not in sys.path:
    sys.path.insert(0, str(LOCAL_BT))

from robust_run import (  # noqa: E402
    overrides_changed,
    trades_cache_hit,
    trades_cache_key,
    trades_cache_sidecar,
    write_trades_cache_sidecar,
)


class TradesCacheKeyTests(unittest.TestCase):
    def test_key_stable_across_key_order(self) -> None:
        a = {"factor_params": {"stop_loss": {"pct": 0.08}}, "structure": {"ema": {"1d": {"mid": 20}}}}
        b = {"structure": {"ema": {"1d": {"mid": 20}}}, "factor_params": {"stop_loss": {"pct": 0.08}}}
        self.assertEqual(trades_cache_key(a, compound=True), trades_cache_key(b, compound=True))

    def test_key_changes_with_overrides(self) -> None:
        a = {"factor_params": {"stop_loss": {"pct": 0.08}}}
        b = {"factor_params": {"stop_loss": {"pct": 0.10}}}
        self.assertNotEqual(trades_cache_key(a, compound=True), trades_cache_key(b, compound=True))

    def test_key_changes_with_compound(self) -> None:
        ov = {"factor_params": {"stop_loss": {"pct": 0.08}}}
        self.assertNotEqual(
            trades_cache_key(ov, compound=True),
            trades_cache_key(ov, compound=False),
        )

    def test_overrides_changed(self) -> None:
        self.assertFalse(overrides_changed({"a": 1}, {"a": 1}))
        self.assertFalse(overrides_changed({"b": 2, "a": 1}, {"a": 1, "b": 2}))
        self.assertTrue(overrides_changed({"a": 1}, {"a": 2}))
        self.assertTrue(overrides_changed(None, {"a": 1}))


class TradesCacheHitTests(unittest.TestCase):
    def test_sidecar_path(self) -> None:
        log = Path("basket_001_local_bt_book_fixed_20190101_20251231_kabcdef12.txt")
        self.assertEqual(
            trades_cache_sidecar(log).name,
            "basket_001_local_bt_book_fixed_20190101_20251231_kabcdef12.ovfp",
        )

    def test_hit_requires_matching_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trades = root / "x_操作明细.csv"
            side = root / "x.ovfp"
            trades.write_text("hdr\n", encoding="utf-8")
            key = trades_cache_key({"k": 1}, compound=True)
            self.assertFalse(trades_cache_hit(trades, side, key))
            write_trades_cache_sidecar(side, key)
            self.assertTrue(trades_cache_hit(trades, side, key))
            self.assertFalse(trades_cache_hit(trades, side, key, force_rerun=True))
            other = trades_cache_key({"k": 2}, compound=True)
            self.assertFalse(trades_cache_hit(trades, side, other))


if __name__ == "__main__":
    unittest.main()
