# coding: utf-8
"""网格分组进度：progress.json、pause.flag、脏组删目录、worker 是否仍活着。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

PROGRESS_NAME = "progress.json"
PAUSE_NAME = "pause.flag"
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_DIRTY = "dirty"
HEARTBEAT_STALE_SEC = 120.0
SPAWN_GRACE_SEC = 45.0
CMDLINE_CACHE_SEC = 5.0
WAIT_DEAD_TIMEOUT_SEC = 20.0
WAIT_DEAD_SETTLE_SEC = 0.4
_CMDLINE_CACHE: dict[int, tuple[float, str]] = {}

IsCellDir = Callable[[Path], bool]


class GridPaused(Exception):
    """协作暂停（pause.flag）；干净退出，不是 GridError。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def progress_path(dest: str | Path) -> Path:
    return Path(dest) / PROGRESS_NAME


def pause_path(dest: str | Path) -> Path:
    return Path(dest) / PAUSE_NAME


def atomic_write_json(path: str | Path, data: Mapping[str, Any]) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(data), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(dest)


def load_progress(dest: str | Path) -> dict[str, Any] | None:
    p = progress_path(dest)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def save_progress(dest: str | Path, data: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(data)
    out["heartbeat_at"] = now_iso()
    atomic_write_json(progress_path(dest), out)
    return out


def touch_pause(dest: str | Path) -> Path:
    p = pause_path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("pause\n", encoding="utf-8")
    return p


def clear_pause(dest: str | Path) -> None:
    p = pause_path(dest)
    if p.is_file():
        p.unlink()


def pause_requested(dest: str | Path) -> bool:
    return pause_path(dest).is_file()


def check_pause(dest: str | Path) -> None:
    if pause_requested(dest):
        raise GridPaused()


def effective_batch_size(n_cells: int, batch_size: int) -> int:
    n = max(int(n_cells or 0), 0)
    bs = int(batch_size or 0)
    if n <= 0:
        return 1
    if bs <= 0 or bs >= n:
        return n
    return bs


def chunk_ids(cell_ids: Iterable[str], batch_size: int) -> list[list[str]]:
    ids = [str(x).strip() for x in cell_ids if str(x).strip()]
    bs = effective_batch_size(len(ids), batch_size)
    if not ids:
        return []
    return [ids[i : i + bs] for i in range(0, len(ids), bs)]


def order_cells_current_first(cells: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(c) for c in cells]
    rows.sort(key=lambda c: 0 if (c.get("is_current") or str(c.get("id") or "") == "base") else 1)
    return rows


def cell_ids_of(cells: Iterable[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for raw in cells:
        cid = str(raw.get("id") or "").strip()
        if cid:
            out.append(cid)
    return out


def build_progress(
    cell_ids: Iterable[str],
    batch_size: int,
    *,
    worker_pid: int = 0,
) -> dict[str, Any]:
    ids = [str(x).strip() for x in cell_ids if str(x).strip()]
    chunks = chunk_ids(ids, batch_size)
    batches = [
        {"index": i, "cell_ids": list(chunk), "status": STATUS_PENDING}
        for i, chunk in enumerate(chunks)
    ]
    stamp = now_iso()
    return {
        "batch_size": effective_batch_size(len(ids), batch_size),
        "cell_ids": ids,
        "batches": batches,
        "current_batch": 0 if batches else -1,
        "worker_pid": int(worker_pid or 0),
        "started_at": stamp,
        "heartbeat_at": stamp,
        "batch_cell_done": 0,
        "batch_cell_total": len(chunks[0]) if chunks else 0,
    }


def iter_batches(progress: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = progress.get("batches")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        rec = dict(item)
        rec["index"] = int(rec.get("index") if rec.get("index") is not None else i)
        rec["cell_ids"] = [str(x).strip() for x in (rec.get("cell_ids") or []) if str(x).strip()]
        rec["status"] = str(rec.get("status") or STATUS_PENDING)
        out.append(rec)
    return out


def done_cell_ids(progress: Mapping[str, Any] | None) -> list[str]:
    if not progress:
        return []
    ids: list[str] = []
    for batch in iter_batches(progress):
        if str(batch.get("status") or "") != STATUS_DONE:
            continue
        ids.extend(str(x) for x in (batch.get("cell_ids") or []) if str(x).strip())
    return ids


def all_batches_done(progress: Mapping[str, Any] | None) -> bool:
    batches = iter_batches(progress or {})
    return bool(batches) and all(str(b.get("status") or "") == STATUS_DONE for b in batches)


def first_unfinished_index(progress: Mapping[str, Any] | None) -> int | None:
    if not progress:
        return None
    for batch in iter_batches(progress):
        if str(batch.get("status") or "") != STATUS_DONE:
            return int(batch["index"])
    return None


def set_batch_status(progress: dict[str, Any], index: int, status: str) -> dict[str, Any]:
    batches = iter_batches(progress)
    for batch in batches:
        if int(batch["index"]) == int(index):
            batch["status"] = str(status)
    progress["batches"] = batches
    progress["current_batch"] = int(index)
    return progress


def pid_exists(pid: int) -> bool:
    pid = int(pid or 0)
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cmdline_looks_like_grid(cmd: str) -> bool:
    return "grid_run.py" in str(cmd or "").replace("\\", "/")


def cmdline_looks_foreign(cmd: str) -> bool:
    text = str(cmd or "").strip()
    if not text:
        return False
    return not cmdline_looks_like_grid(text)


def _linux_cmdline(pid: int) -> str:
    try:
        raw = Path("/proc/%s/cmdline" % pid).read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", "replace")
    except Exception:
        return ""


def _windows_cmdline_cim(pid: int) -> str:
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-CimInstance Win32_Process -Filter 'ProcessId=%s').CommandLine" % pid,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _windows_cmdline_wmic(pid: int) -> str:
    try:
        out = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "ProcessId=%s" % pid,
                "get",
                "CommandLine",
                "/value",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        blob = (out.stdout or "") + (out.stderr or "")
        for line in blob.splitlines():
            if line.lower().startswith("commandline="):
                return line.split("=", 1)[-1].strip()
    except Exception:
        return ""
    return ""


def process_cmdline(pid: int) -> str:
    pid = int(pid or 0)
    if pid <= 0:
        return ""
    now = time.time()
    cached = _CMDLINE_CACHE.get(pid)
    if cached and now - cached[0] < CMDLINE_CACHE_SEC:
        return cached[1]
    if os.name != "nt":
        text = _linux_cmdline(pid)
    else:
        text = _windows_cmdline_cim(pid) or _windows_cmdline_wmic(pid)
    _CMDLINE_CACHE[pid] = (now, text)
    return text


def heartbeat_stale(progress: Mapping[str, Any] | None, *, now: datetime | None = None) -> bool:
    if not progress:
        return True
    ts = parse_iso(progress.get("heartbeat_at") or progress.get("started_at"))
    if ts is None:
        return True
    cur = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (cur - ts).total_seconds() > HEARTBEAT_STALE_SEC


def worker_is_alive(progress: Mapping[str, Any] | None) -> bool:
    """pid 仍在且不能证明是别人的进程。命令行读不到时宁可当成还活着，避免误删目录。"""
    if not progress:
        return False
    pid = int(progress.get("worker_pid") or 0)
    if not pid_exists(pid):
        return False
    cmd = process_cmdline(pid)
    if cmdline_looks_foreign(cmd):
        return False
    return True


def worker_definitely_dead(progress: Mapping[str, Any] | None) -> bool:
    """只有 pid 没了，或命令行明确不是 grid_run.py，才允许自动 dirty/删目录。"""
    if not progress:
        return True
    pid = int(progress.get("worker_pid") or 0)
    if pid <= 0:
        return True
    if not pid_exists(pid):
        return True
    return cmdline_looks_foreign(process_cmdline(pid))


def wait_until_dead(pid: int, *, timeout: float = WAIT_DEAD_TIMEOUT_SEC, poll: float = 0.2) -> bool:
    pid = int(pid or 0)
    if pid <= 0:
        return True
    deadline = time.time() + max(float(timeout), 0.0)
    while True:
        if not pid_exists(pid):
            return True
        if time.time() >= deadline:
            return not pid_exists(pid)
        time.sleep(max(float(poll), 0.05))


def ui_worker_busy(
    progress: Mapping[str, Any] | None,
    *,
    session_pid: int = 0,
    spawned_at: float | None = None,
    now: float | None = None,
    grace: float = SPAWN_GRACE_SEC,
    stopping: bool = False,
) -> bool:
    """UI 忙碌：progress 里的 worker 仍活着，或刚 spawn 的宽限期内 session pid 还在。不用裸 pid_exists。"""
    if stopping:
        return True
    if worker_is_alive(progress):
        return True
    pid = int(session_pid or 0)
    if pid <= 0 or spawned_at is None:
        return False
    cur = time.time() if now is None else float(now)
    try:
        age = cur - float(spawned_at)
    except (TypeError, ValueError):
        return False
    if age < 0 or age > float(grace):
        return False
    return pid_exists(pid)


def delete_cell_dirs(
    dest: str | Path,
    cell_ids: Iterable[str],
    is_cell_dir: IsCellDir,
) -> list[str]:
    root = Path(dest)
    removed: list[str] = []
    if not root.is_dir():
        return removed
    want = {str(x).strip() for x in cell_ids if str(x).strip()}
    for cid in want:
        child = root / cid
        if not is_cell_dir(child):
            continue
        shutil.rmtree(child)
        removed.append(cid)
    return removed


def mark_running_dead_as_dirty(
    dest: str | Path,
    progress: dict[str, Any] | None,
    is_cell_dir: IsCellDir,
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """pid 已死且组仍是 running → dirty，并只删该组格子目录。未确认已死时不删。"""
    if not progress:
        return progress
    if not force and not worker_definitely_dead(progress):
        return progress
    changed = False
    for batch in iter_batches(progress):
        if str(batch.get("status") or "") != STATUS_RUNNING:
            continue
        set_batch_status(progress, int(batch["index"]), STATUS_DIRTY)
        delete_cell_dirs(dest, batch.get("cell_ids") or [], is_cell_dir)
        progress["worker_pid"] = 0
        changed = True
    if changed:
        save_progress(dest, progress)
    return progress


def infer_existing_batch_status(
    dest: str | Path,
    progress: dict[str, Any],
    is_cell_dir: IsCellDir,
) -> dict[str, Any]:
    """resume 没有 progress.json 时：整组目录都在 → done；缺一部分 → dirty。"""
    root = Path(dest)
    for batch in iter_batches(progress):
        ids = list(batch.get("cell_ids") or [])
        if not ids:
            continue
        flags = [is_cell_dir(root / cid) for cid in ids]
        if all(flags):
            set_batch_status(progress, int(batch["index"]), STATUS_DONE)
        elif any(flags):
            set_batch_status(progress, int(batch["index"]), STATUS_DIRTY)
    return progress


def stop_worker_and_dirty(
    dest: str | Path,
    pid: int,
    is_cell_dir: IsCellDir,
    *,
    timeout: float = WAIT_DEAD_TIMEOUT_SEC,
) -> dict[str, Any]:
    """杀进程树，等到 pid 消失后再 dirty/删目录。未退出则不删。"""
    pid = int(pid or 0)
    terminate_process_tree(pid)
    dead = wait_until_dead(pid, timeout=timeout)
    if dead and WAIT_DEAD_SETTLE_SEC > 0:
        time.sleep(WAIT_DEAD_SETTLE_SEC)
        dead = not pid_exists(pid)
    prog = load_progress(dest)
    if not dead:
        return {"ok": False, "progress": prog}
    prog = mark_running_dead_as_dirty(dest, prog, is_cell_dir, force=True)
    return {"ok": True, "progress": prog}


def can_resume(progress: Mapping[str, Any] | None) -> bool:
    if not progress:
        return False
    if all_batches_done(progress):
        return False
    return first_unfinished_index(progress) is not None


def progress_caption(progress: Mapping[str, Any] | None) -> str:
    if not progress:
        return ""
    batches = iter_batches(progress)
    n = len(batches)
    if n <= 0:
        return ""
    cur = int(progress.get("current_batch") or 0)
    done_cells = int(progress.get("batch_cell_done") or 0)
    tot_cells = int(progress.get("batch_cell_total") or 0)
    idx = min(max(cur, 0), n - 1)
    status = str((batches[idx].get("status") if idx < n else "") or "")
    cell_tot = tot_cells or len(batches[idx].get("cell_ids") or [])
    walk_tot = progress.get("batch_walk_total")
    walk_done = progress.get("batch_walk_done")
    try:
        walk_tot_i = int(walk_tot or 0)
        walk_done_f = float(walk_done or 0)
    except (TypeError, ValueError):
        walk_tot_i = 0
        walk_done_f = 0.0
    if walk_tot_i > 0:
        return "第 %s/%s 组 · 本组 %s/%s 格 · walk %.1f/%s · %s" % (
            idx + 1,
            n,
            done_cells,
            cell_tot,
            walk_done_f,
            walk_tot_i,
            status or "—",
        )
    return "第 %s/%s 组 · 本组 %s/%s 格 · %s" % (
        idx + 1,
        n,
        done_cells,
        cell_tot,
        status or "—",
    )


def terminate_process_tree(pid: int) -> None:
    pid = int(pid or 0)
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        pass


def tail_text(path: str | Path, n: int = 16) -> str:
    p = Path(path)
    if not p.is_file() or int(n) <= 0:
        return ""
    raw = p.read_bytes()
    text = ""
    for enc in ("utf-8", "utf-8-sig", "gbk", "cp936"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text and raw:
        text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    return "\n".join(lines[-int(n) :])


def walk_progress_ratio(progress: Mapping[str, Any] | None) -> tuple[float, int]:
    if not progress:
        return 0.0, 0
    try:
        tot = int(progress.get("batch_walk_total") or 0)
        done = float(progress.get("batch_walk_done") or 0)
    except (TypeError, ValueError):
        return 0.0, 0
    if tot <= 0:
        return 0.0, 0
    return min(1.0, max(0.0, done / float(tot))), tot


def spawn_creationflags() -> int:
    if os.name == "nt":
        return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return 0


def python_executable() -> str:
    return sys.executable or "python"


def grid_worker_argv(
    *,
    spec_path: str,
    sweep_dir: str,
    workers: int = 0,
    batch_size: int = 0,
    resume: bool = False,
    script: str | Path | None = None,
) -> list[str]:
    py = python_executable()
    path = str(script or (Path(__file__).resolve().parent / "grid_run.py"))
    cmd = [
        py,
        path,
        "--spec",
        str(spec_path),
        "--sweep-dir",
        str(sweep_dir),
        "--workers",
        str(int(workers or 0)),
    ]
    if resume:
        cmd.append("--resume")
        return cmd
    if int(batch_size or 0) > 0:
        cmd.extend(["--batch-size", str(int(batch_size))])
    return cmd
