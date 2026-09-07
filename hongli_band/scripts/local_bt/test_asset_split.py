# coding: utf-8
"""asset_split：合格池抽取、freeze 复用、reshuffle。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from asset_split import (  # noqa: E402
    AssetSplitError,
    draw_asset_split,
    fill_asset_split,
    list_eligible_stocks,
    validate_asset_split,
)


class AssetSplitTest(unittest.TestCase):
    def test_same_seed_reproducible(self) -> None:
        pool = ["A.SH", "B.SH", "C.SZ", "D.SZ", "E.SH", "F.SH"]
        spec = {
            "year_start": 2018,
            "year_end": 2020,
            "asset_split": {
                "mode": "random_from_csv",
                "n_tune": 2,
                "n_holdout": 2,
                "seed": 7,
            },
        }
        a = draw_asset_split(spec, reshuffle=True, eligible=pool)
        b = draw_asset_split(spec, reshuffle=True, eligible=pool)
        self.assertEqual(a["tune_stocks"], b["tune_stocks"])
        self.assertEqual(a["holdout_stocks"], b["holdout_stocks"])
        self.assertEqual(len(set(a["tune_stocks"]) & set(a["holdout_stocks"])), 0)

    def test_pool_too_small(self) -> None:
        spec = {
            "asset_split": {
                "mode": "random_from_csv",
                "n_tune": 3,
                "n_holdout": 3,
                "seed": 1,
            }
        }
        with self.assertRaises(AssetSplitError) as ctx:
            draw_asset_split(spec, reshuffle=True, eligible=["A.SH", "B.SH"])
        self.assertIn("不足", str(ctx.exception))

    def test_freeze_reuse_unless_reshuffle(self) -> None:
        pool = ["A.SH", "B.SH", "C.SZ", "D.SZ"]
        spec = {
            "asset_split": {
                "mode": "random_from_csv",
                "n_tune": 2,
                "n_holdout": 1,
                "seed": 99,
            }
        }
        first = draw_asset_split(spec, reshuffle=True, eligible=pool)
        freeze = {"asset_split": first}
        reused = draw_asset_split(
            {**spec, "asset_split": {**spec["asset_split"], "seed": 1}},
            reshuffle=False,
            freeze=freeze,
            eligible=pool,
        )
        self.assertEqual(reused["tune_stocks"], first["tune_stocks"])
        self.assertEqual(reused["holdout_stocks"], first["holdout_stocks"])
        reshuffled = draw_asset_split(spec, reshuffle=True, freeze=freeze, eligible=pool)
        # seed 99 与第一次相同，名单应相同；换 seed 才变
        other = draw_asset_split(
            {
                "asset_split": {
                    "mode": "random_from_csv",
                    "n_tune": 2,
                    "n_holdout": 1,
                    "seed": 12345,
                }
            },
            reshuffle=True,
            eligible=pool,
        )
        self.assertEqual(reshuffled["tune_stocks"], first["tune_stocks"])
        self.assertTrue(
            other["tune_stocks"] != first["tune_stocks"]
            or other["holdout_stocks"] != first["holdout_stocks"]
        )

    def test_validate_intersect(self) -> None:
        with self.assertRaises(AssetSplitError):
            validate_asset_split(
                {
                    "mode": "random_from_csv",
                    "n_tune": 1,
                    "n_holdout": 1,
                    "tune_stocks": ["A.SH"],
                    "holdout_stocks": ["A.SH"],
                }
            )

    def test_mode_off(self) -> None:
        out = draw_asset_split({"asset_split": {"mode": "off"}}, reshuffle=True)
        self.assertEqual(out["mode"], "off")
        self.assertEqual(out["tune_stocks"], [])
        self.assertEqual(out["holdout_stocks"], [])

    def test_list_eligible_filters_years(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            none = root / "none"
            none.mkdir()
            # 伪造 daily_csvs_by_stock
            metas = [
                {"stock": "111111.SH", "start": "20150101", "end": "20161231", "path": "a"},
                {"stock": "222222.SZ", "start": "20180101", "end": "20201231", "path": "b"},
            ]
            with patch("asset_split.daily_csvs_by_stock", return_value=metas):
                with patch("asset_split.resolve_universe_dir", return_value=none):
                    got = list_eligible_stocks(none, 2018, 2020)
            self.assertEqual(got, ["222222.SZ"])

    def test_fill_defaults(self) -> None:
        filled = fill_asset_split({})
        self.assertEqual(filled["mode"], "off")
        filled2 = fill_asset_split({"asset_split": {"mode": "random_from_csv"}})
        self.assertEqual(filled2["n_tune"], 20)
        self.assertEqual(filled2["n_holdout"], 20)
        self.assertEqual(filled2["seed"], 42)


if __name__ == "__main__":
    unittest.main()
