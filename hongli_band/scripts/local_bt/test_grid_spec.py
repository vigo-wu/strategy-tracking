# coding: utf-8
"""grid_spec：单族 / 笛卡尔积 / kind / TRAIL patch / 导入纠正。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from grid_spec import (  # noqa: E402
    GridSpecError,
    axes_from_cells,
    axes_from_selection,
    build_cells,
    catalog_ids,
    correct_cell_kinds,
    default_param_selection,
    fill_year_windows,
    generator_locked,
    infer_kind,
    keep_from_cells,
    make_spec,
    overrides_summary,
    parse_scan_token,
    parse_scan_values,
    patch_trail_arm,
    product_count,
    unique_levels,
    validate_year_windows,
)

DEFAULTS = {
    "STOP_LOSS": 0.08,
    "TIME_FORCE_BARS": 30,
    "TIME_FORCE_MIN_RET": 0.03,
    "TRAIL_TIERS": (
        (0.03, 0.06, 0.015, None),
        (0.06, 0.10, 0.03, 0.03),
        (0.10, None, 0.04, None),
    ),
}


class GridSpecTest(unittest.TestCase):
    def test_stop_loss_default_chips(self) -> None:
        cells = build_cells({"STOP_LOSS": [0.06, 0.10]}, DEFAULTS)
        ids = [c["id"] for c in cells]
        self.assertEqual(ids, ["base", "sl06", "sl10"])
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["base"]["kind"], "base")
        self.assertEqual(by["base"]["overrides"], {})
        self.assertEqual(by["sl06"]["kind"], "tighten")
        self.assertEqual(by["sl06"]["overrides"]["STOP_LOSS"], 0.06)
        self.assertEqual(by["sl10"]["kind"], "loosen")
        self.assertEqual(by["sl10"]["overrides"]["STOP_LOSS"], 0.10)

    def test_current_value_not_a_variant(self) -> None:
        cells = build_cells({"STOP_LOSS": [0.06, 0.08, 0.10]}, DEFAULTS)
        self.assertEqual([c["id"] for c in cells], ["base", "sl06", "sl10"])

    def test_cartesian_stop_and_trail(self) -> None:
        cells = build_cells(
            {"STOP_LOSS": [0.06, 0.10], "TRAIL": [0.04]},
            DEFAULTS,
        )
        ids = [c["id"] for c in cells]
        self.assertEqual(
            set(ids),
            {"base", "sl06", "sl10", "arm04", "sl06_arm04", "sl10_arm04"},
        )
        self.assertEqual(len(cells), 6)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["arm04"]["kind"], "loosen")
        self.assertEqual(by["sl06"]["kind"], "tighten")
        self.assertEqual(by["sl06_arm04"]["kind"], "other")
        self.assertEqual(by["sl10_arm04"]["kind"], "other")
        self.assertEqual(set(by["sl06_arm04"]["overrides"]), {"STOP_LOSS", "TRAIL_TIERS"})
        arm = by["arm04"]["overrides"]["TRAIL_TIERS"][0][0]
        self.assertAlmostEqual(arm, 0.04)
        self.assertAlmostEqual(by["arm04"]["overrides"]["TRAIL_TIERS"][0][1], 0.06)
        self.assertEqual(len(by["arm04"]["overrides"]["TRAIL_TIERS"]), 3)

    def test_product_count(self) -> None:
        self.assertEqual(product_count({"STOP_LOSS": [0.06, 0.10]}, DEFAULTS), 3)
        self.assertEqual(
            product_count({"STOP_LOSS": [0.06, 0.10], "TRAIL": [0.04]}, DEFAULTS),
            6,
        )

    def test_min_ret_zero_is_other_not_off(self) -> None:
        cells = build_cells({"TIME_FORCE_MIN_RET": [0.0]}, DEFAULTS)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["tfm0"]["kind"], "other")
        self.assertIn("关闭让路", by["tfm0"]["label"])

    def test_bars_zero_is_off(self) -> None:
        cells = build_cells({"TIME_FORCE_BARS": [0]}, DEFAULTS)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["tfb0"]["kind"], "off")
        self.assertEqual(by["tfb0"]["overrides"]["TIME_FORCE_BARS"], 0)

    def test_trail_arm_rejects_at_peak_hi(self) -> None:
        with self.assertRaises(GridSpecError):
            patch_trail_arm(DEFAULTS["TRAIL_TIERS"], 0.06)
        with self.assertRaises(GridSpecError):
            unique_levels("TRAIL", [0.06], DEFAULTS)

    def test_keep_label_on_rebuild(self) -> None:
        first = build_cells({"STOP_LOSS": [0.06, 0.10]}, DEFAULTS)
        first[1]["label"] = "手改止损6"
        first[1]["kind"] = "other"
        keep = keep_from_cells(first)
        second = build_cells({"STOP_LOSS": [0.06, 0.10]}, DEFAULTS, keep=keep)
        by = {c["id"]: c for c in second}
        self.assertEqual(by["sl06"]["label"], "手改止损6")
        self.assertEqual(by["sl06"]["kind"], "other")

    def test_correct_illegal_kind_inline(self) -> None:
        raw = [
            {"id": "base", "kind": "base", "overrides": {}},
            {"id": "sl06", "kind": "sl06", "overrides": {"STOP_LOSS": 0.06}},
        ]
        fixed = correct_cell_kinds(raw, DEFAULTS)
        self.assertEqual(fixed[1]["kind"], "tighten")
        path = REPO / "hongli_band" / "gridConfig" / "stop_loss.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        fixed = correct_cell_kinds(spec["cells"], DEFAULTS)
        by = {c["id"]: c for c in fixed}
        self.assertEqual(by["base"]["kind"], "base")
        self.assertEqual(by["sl06"]["kind"], "tighten")
        self.assertEqual(by["sl10"]["kind"], "loosen")
        self.assertTrue(by["sl07"]["kind"] in ("tighten", "loosen"))
        axes = axes_from_cells(fixed, DEFAULTS)
        self.assertIn("STOP_LOSS", axes)
        self.assertFalse(generator_locked(fixed))

    def test_infer_kind_stop(self) -> None:
        self.assertEqual(infer_kind("STOP_LOSS", 0.06, DEFAULTS), "tighten")
        self.assertEqual(infer_kind("STOP_LOSS", 0.10, DEFAULTS), "loosen")

    def test_unknown_keys_lock_generator(self) -> None:
        cells = [
            {"id": "base", "kind": "base", "overrides": {}},
            {"id": "x", "kind": "other", "overrides": {"NOT_A_CONFIG": 0.1}},
        ]
        self.assertTrue(generator_locked(cells))
        known = [
            {"id": "base", "kind": "base", "overrides": {}},
            {"id": "ch03", "kind": "other", "overrides": {"CHASE_MAX_PCT": 0.03}},
        ]
        self.assertFalse(generator_locked(known))

    def test_overrides_summary(self) -> None:
        self.assertEqual(overrides_summary({}), "（现行）")
        self.assertIn("STOP_LOSS=0.06", overrides_summary({"STOP_LOSS": 0.06}))

    def test_catalog_includes_entry_not_infra(self) -> None:
        ids = catalog_ids()
        self.assertIn("CHASE_MAX_PCT", ids)
        self.assertIn("W_BIAS_HARD", ids)
        self.assertIn("MA_TOUCH_TOL", ids)
        self.assertIn("STOP_LOSS", ids)
        self.assertIn("TRAIL", ids)
        self.assertNotIn("STATE_FILE", ids)
        self.assertNotIn("DRY_RUN", ids)
        self.assertNotIn("TRAIL_TIERS", ids)

    def test_parse_percent_and_int(self) -> None:
        self.assertAlmostEqual(parse_scan_token("STOP_LOSS", "6"), 0.06)
        self.assertAlmostEqual(parse_scan_token("STOP_LOSS", "0.06"), 0.06)
        self.assertAlmostEqual(parse_scan_token("STOP_LOSS", "6%"), 0.06)
        self.assertAlmostEqual(parse_scan_token("STOP_LOSS", "6％"), 0.06)
        self.assertEqual(parse_scan_token("VOL_PULLBACK_N", "8"), 8)
        self.assertEqual(parse_scan_values("STOP_LOSS", "6, 10"), [0.06, 0.10])
        self.assertEqual(parse_scan_values("STOP_LOSS", "6% 10%"), [0.06, 0.10])
        self.assertEqual(parse_scan_values("STOP_LOSS", "6%,10%"), [0.06, 0.10])
        self.assertEqual(parse_scan_values("CHASE_MAX_PCT", "3 7"), [0.03, 0.07])

    def test_cartesian_stop_and_chase(self) -> None:
        defaults = dict(DEFAULTS)
        defaults["CHASE_MAX_PCT"] = 0.05
        cells = build_cells(
            {"STOP_LOSS": [0.06, 0.10], "CHASE_MAX_PCT": [0.03]},
            defaults,
        )
        ids = [c["id"] for c in cells]
        self.assertIn("sl06_ch03", ids)
        self.assertEqual(len(cells), 6)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["sl06_ch03"]["kind"], "other")
        self.assertEqual(by["ch03"]["kind"], "other")
        self.assertAlmostEqual(by["ch03"]["overrides"]["CHASE_MAX_PCT"], 0.03)
        self.assertEqual(set(by["sl06_ch03"]["overrides"]), {"STOP_LOSS", "CHASE_MAX_PCT"})

    def test_default_selection_none(self) -> None:
        sel = default_param_selection()
        self.assertFalse(sel["STOP_LOSS"]["selected"])
        self.assertFalse(any(rec.get("selected") for rec in sel.values()))
        axes = axes_from_selection(sel)
        self.assertEqual(axes, {})
        cells = build_cells(axes, DEFAULTS)
        self.assertEqual([c["id"] for c in cells], ["base"])

    def test_trail_scan_six_still_rejected(self) -> None:
        with self.assertRaises(GridSpecError):
            unique_levels("TRAIL", parse_scan_values("TRAIL", "6"), DEFAULTS)

    def test_year_windows_fill_and_overlap(self) -> None:
        filled = fill_year_windows({})
        self.assertEqual(filled["year_start"], 2018)
        self.assertEqual(filled["check_end"], 2026)
        spec = make_spec([{"id": "base", "kind": "base", "overrides": {}}], sweep="t")
        self.assertEqual(spec["tune_end"], 2022)
        with self.assertRaises(GridSpecError) as ctx:
            validate_year_windows(
                {
                    "year_start": 2018,
                    "year_end": 2026,
                    "tune_start": 2018,
                    "tune_end": 2023,
                    "check_start": 2023,
                    "check_end": 2026,
                }
            )
        self.assertIn("重叠", str(ctx.exception))
        ok = validate_year_windows(
            {
                "year_start": 2020,
                "year_end": 2024,
                "tune_start": 2020,
                "tune_end": 2021,
                "check_start": 2023,
                "check_end": 2024,
            }
        )
        self.assertEqual(ok["tune_end"], 2021)


if __name__ == "__main__":
    unittest.main()
