# coding: utf-8
"""分组进度：切组、dirty 整组删除、resume 不 prune、pause.flag。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from grid_progress import (  # noqa: E402
    STATUS_DIRTY,
    STATUS_DONE,
    STATUS_PENDING,
    STATUS_RUNNING,
    GridPaused,
    _CMDLINE_CACHE,
    build_progress,
    can_resume,
    check_pause,
    chunk_ids,
    delete_cell_dirs,
    done_cell_ids,
    effective_batch_size,
    grid_worker_argv,
    infer_existing_batch_status,
    load_progress,
    mark_running_dead_as_dirty,
    order_cells_current_first,
    process_cmdline,
    progress_caption,
    save_progress,
    set_batch_status,
    stop_worker_and_dirty,
    tail_text,
    touch_pause,
    ui_worker_busy,
    wait_until_dead,
    walk_progress_ratio,
    worker_definitely_dead,
    worker_is_alive,
)
from grid_run import (  # noqa: E402
    GridError,
    is_cell_dir,
    prune_stale_cell_dirs,
    run_sweep,
)
from test_grid_run import _FakeSummarize, _POOL_DEFAULTS, _walk  # noqa: E402


class ChunkIdsTest(unittest.TestCase):
    def test_twenty_five_by_ten(self) -> None:
        ids = ["c%s" % i for i in range(25)]
        chunks = chunk_ids(ids, 10)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 10)
        self.assertEqual(len(chunks[1]), 10)
        self.assertEqual(len(chunks[2]), 5)

    def test_batch_size_zero_one_group(self) -> None:
        ids = ["a", "b", "c"]
        self.assertEqual(chunk_ids(ids, 0), [ids])
        self.assertEqual(effective_batch_size(3, 0), 3)
        self.assertEqual(effective_batch_size(3, 99), 3)

    def test_current_first_order(self) -> None:
        cells = [
            {"id": "a", "is_current": False},
            {"id": "base", "is_current": True},
            {"id": "b", "is_current": False},
        ]
        ordered = order_cells_current_first(cells)
        self.assertEqual([c["id"] for c in ordered], ["base", "a", "b"])


class ProgressDirtyTest(unittest.TestCase):
    def test_delete_only_named_cell_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "sw"
            dest.mkdir(parents=True)
            for cid in ("keep", "drop"):
                cell = dest / cid
                cell.mkdir()
                (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            (dest / "spec.json").write_text("{}", encoding="utf-8")
            removed = delete_cell_dirs(dest, ["drop"], is_cell_dir)
            self.assertEqual(removed, ["drop"])
            self.assertTrue((dest / "keep").is_dir())
            self.assertFalse((dest / "drop").exists())
            self.assertTrue((dest / "spec.json").is_file())

    def test_running_dead_pid_becomes_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "sw"
            dest.mkdir(parents=True)
            cell = dest / "c1"
            cell.mkdir()
            (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            prog = build_progress(["c0", "c1"], 1, worker_pid=99999999)
            set_batch_status(prog, 0, STATUS_DONE)
            set_batch_status(prog, 1, STATUS_RUNNING)
            save_progress(dest, prog)
            with patch("grid_progress.worker_is_alive", return_value=False):
                out = mark_running_dead_as_dirty(dest, load_progress(dest), is_cell_dir)
            self.assertEqual(out["batches"][1]["status"], STATUS_DIRTY)
            self.assertFalse(cell.exists())
            self.assertTrue(can_resume(out))
            self.assertEqual(done_cell_ids(out), ["c0"])

    def test_pause_flag_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            check_pause(dest)
            touch_pause(dest)
            with self.assertRaises(GridPaused):
                check_pause(dest)


class ResumeSweepTest(unittest.TestCase):
    def _cells(self, n: int) -> list[dict]:
        rows = []
        for i in range(n):
            cid = "base" if i == 0 else "c%s" % i
            rows.append(
                {
                    "id": cid,
                    "label": cid,
                    "kind": "base" if i == 0 else "other",
                    "overrides": {},
                    "is_current": i == 0,
                }
            )
        return rows

    def test_resume_skips_done_reruns_dirty(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "batch_unit",
            "compare_div": "front_ratio",
            "cells": self._cells(25),
        }
        book = [_walk(start="20200101", end="20201231")]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "batch_unit"
            dest.mkdir(parents=True)
            ids = ["base"] + ["c%s" % i for i in range(1, 25)]
            prog = build_progress(ids, 10, worker_pid=0)
            set_batch_status(prog, 0, STATUS_DONE)
            set_batch_status(prog, 1, STATUS_DIRTY)
            save_progress(dest, prog)
            kept = dest / "base"
            kept.mkdir()
            (kept / "cell_meta.json").write_text("{}", encoding="utf-8")
            dirty_id = prog["batches"][1]["cell_ids"][0]
            leftover = dest / dirty_id
            leftover.mkdir()
            (leftover / "cell_meta.json").write_text("{}", encoding="utf-8")
            ran: list[str] = []

            def fake_run_cells(cells, jobs, cell_dest, defaults, workers, on_progress=None, pause_dest=None):
                ran.extend([c["id"] for c in cells])

            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run._load_summarize", return_value=_FakeSummarize()):
                        with patch("grid_run.run_cells", side_effect=fake_run_cells):
                            with patch("grid_run.prune_stale_cell_dirs") as prune:
                                info = run_sweep(
                                    spec,
                                    workers=1,
                                    sweep_dir=dest,
                                    batch_size=3,
                                    resume=True,
                                    include_sma_ema=True,
                                )
            prune.assert_not_called()
            self.assertTrue(kept.is_dir())
            self.assertEqual(ran[:10], prog["batches"][1]["cell_ids"])
            self.assertFalse(info.get("paused"))

    def test_resume_keeps_freeze_sma(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "sma_unit",
            "compare_div": "front_ratio",
            "cells": self._cells(2),
        }
        book = [_walk()]
        jobs = book + [_walk(sample="sma"), _walk(sample="ema")]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "sma_unit"
            dest.mkdir(parents=True)
            freeze = {
                "include_sma_ema": True,
                "n_jobs": 3,
                "n_book": 1,
                "compare_div": "front_ratio",
                "year_start": 2018,
                "year_end": 2026,
                "tune_start": 2018,
                "tune_end": 2022,
                "check_start": 2023,
                "check_end": 2026,
                "book": [],
                "asset_split": {"mode": "off"},
                "tune_stocks": [],
                "holdout_stocks": [],
                "gate": {},
            }
            (dest / "freeze.json").write_text(json.dumps(freeze), encoding="utf-8")
            prog = build_progress(["base", "c1"], 10, worker_pid=0)
            save_progress(dest, prog)
            with patch("grid_run.assemble_jobs", return_value=(book, jobs)) as assemble:
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run._load_summarize", return_value=_FakeSummarize()):
                        with patch("grid_run.run_cells"):
                            run_sweep(
                                spec,
                                workers=1,
                                sweep_dir=dest,
                                resume=True,
                                include_sma_ema=False,
                            )
            self.assertTrue(assemble.call_args.kwargs.get("include_sma_ema"))
            out_f = json.loads((dest / "freeze.json").read_text(encoding="utf-8"))
            self.assertTrue(out_f["include_sma_ema"])
            self.assertEqual(out_f["n_jobs"], 3)

    def test_prune_keep_batch_would_drop_done(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "sw"
            dest.mkdir(parents=True)
            for cid in ("base", "c1", "c2"):
                cell = dest / cid
                cell.mkdir()
                (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            removed = prune_stale_cell_dirs(dest, ["c1", "c2"])
            self.assertIn("base", removed)
            self.assertFalse((dest / "base").exists())

    def test_pause_flag_marks_dirty_and_deletes(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "pause_unit",
            "compare_div": "front_ratio",
            "cells": self._cells(4),
        }
        book = [_walk()]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "pause_unit"

            def boom(*_a, **_k):
                touch_pause(dest)
                from grid_progress import check_pause as cp

                cp(dest)

            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run._load_summarize", return_value=_FakeSummarize()):
                        with patch("grid_run.run_cells", side_effect=boom):
                            info = run_sweep(
                                spec,
                                workers=1,
                                sweep_dir=dest,
                                batch_size=2,
                            )
            self.assertTrue(info.get("paused"))
            prog = load_progress(dest)
            self.assertEqual(prog["batches"][0]["status"], STATUS_DIRTY)
            self.assertEqual(prog["batches"][1]["status"], STATUS_PENDING)
            self.assertFalse((dest / "base").exists())

    def test_summarize_done_ids_only(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "sum_unit",
            "compare_div": "front_ratio",
            "cells": self._cells(4),
        }
        book = [_walk()]
        fake = _FakeSummarize()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "sum_unit"
            seen: list = []
            inner = _FakeSummarize()

            def capture(d, gate=None, cell_ids=None):
                seen.append(list(cell_ids or []))
                return inner.summarize_sweep(d, gate=gate, cell_ids=cell_ids)

            fake.summarize_sweep = capture  # type: ignore[method-assign]
            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run._load_summarize", return_value=fake):
                        with patch("grid_run.run_cells"):
                            run_sweep(spec, workers=1, sweep_dir=dest, batch_size=2)
            self.assertTrue(seen)
            self.assertEqual(len(seen), 2)
            self.assertEqual(len(seen[-1]), 4)

    def test_worker_argv_resume_omits_batch_and_sma(self) -> None:
        cmd = grid_worker_argv(
            spec_path="s.json",
            sweep_dir="d",
            workers=4,
            batch_size=10,
            resume=True,
            include_sma_ema=True,
        )
        self.assertIn("--resume", cmd)
        self.assertNotIn("--batch-size", cmd)
        self.assertNotIn("--include-sma-ema", cmd)
        cmd2 = grid_worker_argv(
            spec_path="s.json",
            sweep_dir="d",
            batch_size=10,
            include_sma_ema=True,
        )
        self.assertIn("--batch-size", cmd2)
        self.assertIn("10", cmd2)
        self.assertIn("--include-sma-ema", cmd2)


class WorkerLivenessTest(unittest.TestCase):
    def setUp(self) -> None:
        _CMDLINE_CACHE.clear()

    def test_empty_cmdline_pid_alive_is_not_definitely_dead(self) -> None:
        prog = {"worker_pid": 4242, "heartbeat_at": "2000-01-01T00:00:00+00:00"}
        with patch("grid_progress.pid_exists", return_value=True):
            with patch("grid_progress.process_cmdline", return_value=""):
                self.assertTrue(worker_is_alive(prog))
                self.assertFalse(worker_definitely_dead(prog))

    def test_foreign_cmdline_is_dead(self) -> None:
        prog = {"worker_pid": 4242}
        with patch("grid_progress.pid_exists", return_value=True):
            with patch("grid_progress.process_cmdline", return_value="notepad.exe"):
                self.assertFalse(worker_is_alive(prog))
                self.assertTrue(worker_definitely_dead(prog))

    def test_reconcile_does_not_delete_if_pid_still_up(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "sw"
            dest.mkdir()
            cell = dest / "c1"
            cell.mkdir()
            (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            prog = build_progress(["c1"], 1, worker_pid=4242)
            set_batch_status(prog, 0, STATUS_RUNNING)
            save_progress(dest, prog)
            with patch("grid_progress.pid_exists", return_value=True):
                with patch("grid_progress.process_cmdline", return_value=""):
                    out = mark_running_dead_as_dirty(dest, load_progress(dest), is_cell_dir)
            self.assertEqual(out["batches"][0]["status"], STATUS_RUNNING)
            self.assertTrue(cell.exists())

    def test_reconcile_deletes_when_pid_gone(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "sw"
            dest.mkdir()
            cell = dest / "c1"
            cell.mkdir()
            (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            prog = build_progress(["c1"], 1, worker_pid=4242)
            set_batch_status(prog, 0, STATUS_RUNNING)
            save_progress(dest, prog)
            with patch("grid_progress.pid_exists", return_value=False):
                out = mark_running_dead_as_dirty(dest, load_progress(dest), is_cell_dir)
            self.assertEqual(out["batches"][0]["status"], STATUS_DIRTY)
            self.assertFalse(cell.exists())

    def test_ui_busy_uses_spawn_grace_not_naked_pid(self) -> None:
        with patch("grid_progress.pid_exists", return_value=True) as exists:
            self.assertTrue(
                ui_worker_busy(
                    None,
                    session_pid=99,
                    spawned_at=100.0,
                    now=110.0,
                    grace=45.0,
                )
            )
            exists.assert_called()
            self.assertFalse(
                ui_worker_busy(
                    None,
                    session_pid=99,
                    spawned_at=100.0,
                    now=200.0,
                    grace=45.0,
                )
            )

    def test_ui_busy_stopping_blocks_continue(self) -> None:
        self.assertTrue(ui_worker_busy(None, stopping=True))

    def test_wait_until_dead_true_then_false(self) -> None:
        calls = {"n": 0}

        def exists(_pid: int) -> bool:
            calls["n"] += 1
            return calls["n"] < 3

        with patch("grid_progress.pid_exists", side_effect=exists):
            with patch("grid_progress.time.sleep"):
                self.assertTrue(wait_until_dead(7, timeout=2.0, poll=0.01))

        with patch("grid_progress.pid_exists", return_value=True):
            with patch("grid_progress.time.sleep"):
                with patch("grid_progress.time.time", side_effect=[0.0, 0.0, 9.0, 9.0]):
                    self.assertFalse(wait_until_dead(7, timeout=1.0, poll=0.01))

    def test_stop_worker_waits_before_delete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "sw"
            dest.mkdir()
            cell = dest / "c1"
            cell.mkdir()
            (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            prog = build_progress(["c1"], 1, worker_pid=7)
            set_batch_status(prog, 0, STATUS_RUNNING)
            save_progress(dest, prog)
            with patch("grid_progress.terminate_process_tree") as kill:
                with patch("grid_progress.wait_until_dead", return_value=False):
                    with patch("grid_progress.WAIT_DEAD_SETTLE_SEC", 0):
                        out = stop_worker_and_dirty(dest, 7, is_cell_dir, timeout=1)
            kill.assert_called_once_with(7)
            self.assertFalse(out["ok"])
            self.assertTrue(cell.exists())
            self.assertEqual(load_progress(dest)["batches"][0]["status"], STATUS_RUNNING)
            with patch("grid_progress.terminate_process_tree"):
                with patch("grid_progress.wait_until_dead", return_value=True):
                    with patch("grid_progress.WAIT_DEAD_SETTLE_SEC", 0):
                        with patch("grid_progress.pid_exists", return_value=False):
                            out = stop_worker_and_dirty(dest, 7, is_cell_dir, timeout=1)
            self.assertTrue(out["ok"])
            self.assertFalse(cell.exists())
            self.assertEqual(load_progress(dest)["batches"][0]["status"], STATUS_DIRTY)

    def test_process_cmdline_prefers_cim(self) -> None:
        _CMDLINE_CACHE.clear()
        with patch("grid_progress.os.name", "nt"):
            with patch("grid_progress._windows_cmdline_cim", return_value="py grid_run.py --resume") as cim:
                with patch("grid_progress._windows_cmdline_wmic") as wmic:
                    cmd = process_cmdline(321)
        self.assertIn("grid_run.py", cmd)
        cim.assert_called_once()
        wmic.assert_not_called()

    def test_caption_uses_walks(self) -> None:
        prog = build_progress(["a", "b"], 2)
        prog["batch_walk_done"] = 1.5
        prog["batch_walk_total"] = 4
        cap = progress_caption(prog)
        self.assertIn("walk 1.5/4", cap)
        frac, tot = walk_progress_ratio(prog)
        self.assertEqual(tot, 4)
        self.assertAlmostEqual(frac, 1.5 / 4)

    def test_tail_text_last_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "worker.log"
            p.write_text("a\nb\nc\nd\n", encoding="utf-8")
            self.assertEqual(tail_text(p, 2), "c\nd")
            self.assertEqual(tail_text(p, 10), "a\nb\nc\nd")

    def test_infer_partial_batch_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "sw"
            dest.mkdir()
            keep = dest / "a"
            keep.mkdir()
            (keep / "cell_meta.json").write_text("{}", encoding="utf-8")
            prog = build_progress(["a", "b"], 2)
            infer_existing_batch_status(dest, prog, is_cell_dir)
            self.assertEqual(prog["batches"][0]["status"], STATUS_DIRTY)


class ResumeNoProgressTest(unittest.TestCase):
    def _cells(self, n: int) -> list[dict]:
        rows = []
        for i in range(n):
            cid = "base" if i == 0 else "c%s" % i
            rows.append(
                {
                    "id": cid,
                    "label": cid,
                    "kind": "base" if i == 0 else "other",
                    "overrides": {},
                    "is_current": i == 0,
                }
            )
        return rows

    def test_resume_without_progress_uses_freeze_batch_size(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "noprog",
            "compare_div": "front_ratio",
            "cells": self._cells(4),
        }
        book = [_walk()]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "noprog"
            dest.mkdir(parents=True)
            freeze = {
                "include_sma_ema": False,
                "n_jobs": 1,
                "n_book": 1,
                "batch_size": 2,
                "compare_div": "front_ratio",
                "year_start": 2018,
                "year_end": 2026,
                "tune_start": 2018,
                "tune_end": 2022,
                "check_start": 2023,
                "check_end": 2026,
                "book": [],
                "asset_split": {"mode": "off"},
                "tune_stocks": [],
                "holdout_stocks": [],
                "gate": {},
            }
            (dest / "freeze.json").write_text(json.dumps(freeze), encoding="utf-8")
            for cid in ("base", "c1"):
                cell = dest / cid
                cell.mkdir()
                (cell / "cell_meta.json").write_text("{}", encoding="utf-8")
            ran: list[str] = []

            def fake_run_cells(cells, jobs, cell_dest, defaults, workers, on_progress=None, pause_dest=None):
                ran.extend([c["id"] for c in cells])

            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run._load_summarize", return_value=_FakeSummarize()):
                        with patch("grid_run.run_cells", side_effect=fake_run_cells):
                            info = run_sweep(spec, workers=1, sweep_dir=dest, resume=True)
            self.assertEqual(info["n_batches"], 2)
            self.assertEqual(ran, ["c2", "c3"])
            self.assertTrue((dest / "base").is_dir())

    def test_resume_live_worker_raises(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "live",
            "compare_div": "front_ratio",
            "cells": self._cells(2),
        }
        book = [_walk()]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "live"
            dest.mkdir(parents=True)
            prog = build_progress(["base", "c1"], 2, worker_pid=99)
            save_progress(dest, prog)
            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                with patch("grid_run.worker_is_alive", return_value=True):
                    with self.assertRaises(GridError):
                        run_sweep(spec, workers=1, sweep_dir=dest, resume=True)

    def test_cell_summarize_passes_id(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "one",
            "compare_div": "front_ratio",
            "cells": self._cells(2),
        }
        book = [_walk()]
        seen: list = []
        fake = _FakeSummarize()
        inner = _FakeSummarize()

        def capture(d, gate=None, cell_ids=None):
            seen.append(list(cell_ids or []))
            return inner.summarize_sweep(d, gate=gate, cell_ids=cell_ids)

        fake.summarize_sweep = capture  # type: ignore[method-assign]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "one"
            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run._load_summarize", return_value=fake):
                        with patch("grid_run.run_cells"):
                            run_sweep(spec, workers=1, sweep_dir=dest, cell_id="base")
        self.assertEqual(seen[-1], ["base"])

    def test_keyboard_interrupt_marks_dirty(self) -> None:
        spec = {
            "theme": "hongli_band",
            "sweep": "intr",
            "compare_div": "front_ratio",
            "cells": self._cells(2),
        }
        book = [_walk()]
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "report" / "grid" / "intr"

            def boom(*_a, **_k):
                raise KeyboardInterrupt()

            with patch("grid_run.assemble_jobs", return_value=(book, book)):
                with patch("grid_run.load_exit_defaults", return_value=_POOL_DEFAULTS):
                    with patch("grid_run._load_summarize", return_value=_FakeSummarize()):
                        with patch("grid_run.run_cells", side_effect=boom):
                            info = run_sweep(spec, workers=1, sweep_dir=dest, batch_size=2)
            self.assertTrue(info.get("paused"))
            self.assertEqual(load_progress(dest)["batches"][0]["status"], STATUS_DIRTY)


if __name__ == "__main__":
    unittest.main()
