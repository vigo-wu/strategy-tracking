# coding: utf-8
"""实盘评估 Streamlit 页：侧栏四维综合分 + 随机组合开跑 / 汇总。"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import pandas as pd
import streamlit as st

from analyze import (
    DEFAULT_DIVIDEND_TYPE,
    DIVIDEND_LABELS,
    DIVIDEND_TYPES,
)
from asset_split import DEFAULT_UNIVERSE_DIR
from grid_progress import (
    SPAWN_GRACE_SEC,
    load_progress,
    spawn_creationflags,
    tail_text,
    ui_worker_busy,
    walk_progress_ratio,
)
from grid_run import resolve_pool_workers
from robust_score import (
    _median,
    default_score,
    eval_run_score,
    score_basket,
    validate_score,
)
from robust_run import (
    robust_progress_caption,
    robust_worker_argv,
    stop_robust_worker,
)
from robust_sample import sample_baskets_for_spec
from robust_spec import (
    ROBUST_ROOT,
    YEAR_DEFAULTS,
    RobustSpecError,
    fingerprints_match,
    json_ready,
    resolve_overrides_from_summary,
    run_dir,
    sampling_fingerprint,
    validate_year_windows,
)
from robust_summarize import summarize_run
from ui_cache import CACHE_PATH, merge_form_cache, snapshot_form_state

ROBUST_MODE = "实盘评估"
THEME = Path(__file__).resolve().parents[2]
REPO = THEME.parent
GRID_ROOT = THEME / "report" / "grid"
PARAM_SOURCE_CONFIG = "现行 config（默认）"

_PROGRESS_FRAG = None


def _persist() -> None:
    try:
        merge_form_cache(snapshot_form_state(st.session_state), CACHE_PATH)
    except Exception:
        pass


def _ensure_state() -> None:
    ss = st.session_state
    pending = ss.pop("robust_pending_run_id", None)
    if pending is not None:
        ss["robust_run_id"] = str(pending)
    ds = default_score()
    for k, v in YEAR_DEFAULTS.items():
        ss.setdefault("robust_%s" % k, int(v))
    ss.setdefault("robust_run_id", "post_grid_robust")
    ss.setdefault("robust_n_baskets", 40)
    ss.setdefault("robust_basket_size", 10)
    ss.setdefault("robust_seed", 42)
    ss.setdefault("robust_workers", 0)
    ss.setdefault("robust_compare_div", DEFAULT_DIVIDEND_TYPE)
    ss.setdefault("robust_compound", True)
    ss.setdefault("robust_universe", DEFAULT_UNIVERSE_DIR)
    ss.setdefault("robust_full_span", False)
    ss.setdefault("robust_eligible_n", 0)
    ss.setdefault("robust_drawn_baskets", [])
    ss.setdefault("robust_draw_fp", {})
    ss.setdefault("robust_mean_jaccard", None)
    ss.setdefault("robust_param_source", PARAM_SOURCE_CONFIG)
    ss.setdefault("robust_cell_id", "")
    ss.setdefault("robust_busy", False)
    ss.setdefault("robust_worker_pid", 0)
    ss.setdefault("robust_stopping", False)
    ss.setdefault("robust_score_w_def", float(ds["w_def"]) * 100.0)
    ss.setdefault("robust_score_w_str", float(ds["w_str"]) * 100.0)
    ss.setdefault("robust_score_w_res", float(ds["w_res"]) * 100.0)
    ss.setdefault("robust_score_w_gen", float(ds["w_gen"]) * 100.0)
    ss.setdefault("robust_score_dd_cap_pct", float(ds["dd_cap"]) * 100.0)
    ss.setdefault("robust_score_factor_target", float(ds["factor_target"]))
    ss.setdefault("robust_score_pf_cap", float(ds["pf_cap"]))
    ss.setdefault("robust_score_sharpe_target", float(ds["sharpe_target"]))
    ss.setdefault("robust_score_n_trades_floor", int(ds["n_trades_floor"]))
    ss.setdefault("robust_score_n_trades_full", int(ds["n_trades_full"]))
    ss.setdefault("robust_score_go_floor", float(ds["go_floor"]))


def _score_from_state() -> dict[str, Any]:
    """从侧栏读评分配置；勿在 widget 实例化后回写同名 session 键。"""
    ss = st.session_state
    raw = {
        "w_def": float(ss.get("robust_score_w_def") or 30.0),
        "w_str": float(ss.get("robust_score_w_str") or 25.0),
        "w_res": float(ss.get("robust_score_w_res") or 25.0),
        "w_gen": float(ss.get("robust_score_w_gen") or 20.0),
        "dd_cap": float(ss.get("robust_score_dd_cap_pct") or 35.0),
        "factor_target": float(ss.get("robust_score_factor_target") or 0.5),
        "pf_cap": float(ss.get("robust_score_pf_cap") or 5.0),
        "sharpe_target": float(ss.get("robust_score_sharpe_target") or 0.5),
        "n_trades_floor": float(ss.get("robust_score_n_trades_floor") or 30.0),
        "n_trades_full": float(ss.get("robust_score_n_trades_full") or 80.0),
        "go_floor": float(ss.get("robust_score_go_floor") or 50.0),
    }
    return validate_score(raw)


def _score_cfg_for_view() -> dict[str, Any]:
    try:
        return _score_from_state()
    except ValueError:
        return default_score()


def _current_spec() -> dict[str, Any]:
    ss = st.session_state
    pick = str(ss.get("robust_param_source") or PARAM_SOURCE_CONFIG).strip()
    ofrom = "" if (not pick or pick == PARAM_SOURCE_CONFIG) else pick
    raw = {
        "theme": "factor_band",
        "run_id": str(ss.get("robust_run_id") or "post_grid_robust").strip(),
        "overrides_from": ofrom,
        "overrides_cell_id": str(ss.get("robust_cell_id") or "").strip() if ofrom else "",
        "overrides": {},
        "year_start": int(ss.get("robust_year_start")),
        "year_end": int(ss.get("robust_year_end")),
        "tune_start": int(ss.get("robust_tune_start")),
        "tune_end": int(ss.get("robust_tune_end")),
        "check_start": int(ss.get("robust_check_start")),
        "check_end": int(ss.get("robust_check_end")),
        "deploy_start": int(ss.get("robust_deploy_start")),
        "deploy_end": int(ss.get("robust_deploy_end")),
        "n_baskets": int(ss.get("robust_n_baskets") or 40),
        "basket_size": int(ss.get("robust_basket_size") or 10),
        "seed": int(ss.get("robust_seed") or 42),
        "universe_dir": DEFAULT_UNIVERSE_DIR,
        "full_span": bool(ss.get("robust_full_span")),
        "compare_div": str(ss.get("robust_compare_div") or DEFAULT_DIVIDEND_TYPE),
        "compound_backtest": bool(ss.get("robust_compound", True)),
        "score": _score_cfg_for_view(),
    }
    manual = str(ss.get("robust_overrides_json") or "").strip()
    if manual:
        try:
            ov = json.loads(manual)
            if isinstance(ov, dict) and ov:
                raw["overrides"] = ov
                raw["overrides_from"] = ""
        except Exception:
            pass
    return raw


def _run_name() -> str:
    return str(st.session_state.get("robust_run_id") or "").strip()


def _run_path(name: str = "") -> Path:
    return ROBUST_ROOT / str(name or _run_name() or "run")


def _load_robust_progress(name: str = "") -> dict[str, Any] | None:
    dest = _run_path(name)
    if not dest.is_dir():
        return None
    return load_progress(dest)


def _robust_session_busy_kwargs() -> dict[str, Any]:
    spawned = st.session_state.get("robust_worker_spawned_at")
    try:
        spawned_at = float(spawned) if spawned is not None else None
    except (TypeError, ValueError):
        spawned_at = None
    return {
        "session_pid": int(st.session_state.get("robust_worker_pid") or 0),
        "spawned_at": spawned_at,
        "grace": SPAWN_GRACE_SEC,
        "stopping": bool(st.session_state.get("robust_stopping")),
    }


def _robust_is_busy() -> bool:
    prog = _load_robust_progress()
    busy = ui_worker_busy(prog, **_robust_session_busy_kwargs())
    st.session_state["robust_busy"] = bool(busy)
    if not busy:
        st.session_state["robust_worker_pid"] = 0
        st.session_state.pop("robust_worker_spawned_at", None)
        st.session_state["robust_stopping"] = False
    return bool(busy)


def _store_drawn(sampled: Mapping[str, Any], spec: Mapping[str, Any]) -> None:
    st.session_state["robust_drawn_baskets"] = list(sampled.get("baskets") or [])
    st.session_state["robust_eligible_n"] = int(sampled.get("eligible_n") or 0)
    st.session_state["robust_mean_jaccard"] = sampled.get("mean_jaccard")
    st.session_state["robust_draw_fp"] = dict(
        sampled.get("sampling_fingerprint") or sampling_fingerprint(spec)
    )


def _drawn_valid(spec: Mapping[str, Any]) -> bool:
    baskets = st.session_state.get("robust_drawn_baskets") or []
    fp = st.session_state.get("robust_draw_fp")
    if not baskets or not isinstance(fp, dict) or not fp:
        return False
    return fingerprints_match(fp, sampling_fingerprint(spec))


def _ensure_drawn(spec: dict[str, Any], *, reshuffle: bool) -> str:
    if not reshuffle and _drawn_valid(spec):
        spec["baskets"] = list(st.session_state.get("robust_drawn_baskets") or [])
        spec["sampling_fingerprint"] = dict(st.session_state.get("robust_draw_fp") or {})
        return "session"
    sampled = sample_baskets_for_spec(spec, reshuffle=True)
    _store_drawn(sampled, spec)
    spec["baskets"] = list(sampled.get("baskets") or [])
    spec["sampling_fingerprint"] = dict(sampled.get("sampling_fingerprint") or {})
    return "drawn"


def _begin_run_request(ss: MutableMapping[str, Any], *, reshuffle: bool = False) -> None:
    ss["robust_action"] = "reshuffle" if reshuffle else "run"


def _begin_pause_request(ss: MutableMapping[str, Any]) -> None:
    ss["robust_action"] = "pause"


def _begin_resume_request(ss: MutableMapping[str, Any]) -> None:
    ss["robust_action"] = "resume"


def _mark_start() -> None:
    _begin_run_request(st.session_state, reshuffle=False)


def _mark_reshuffle() -> None:
    _begin_run_request(st.session_state, reshuffle=True)


def _mark_pause() -> None:
    _begin_pause_request(st.session_state)


def _mark_resume() -> None:
    _begin_resume_request(st.session_state)


def _mark_summarize() -> None:
    st.session_state["robust_action"] = "summarize"


def render_robust_sidebar() -> None:
    _ensure_state()
    busy = _robust_is_busy()
    st.caption("锁定网格参数后，随机抽组合回放，看能不能上实盘。默认不改 config。")
    st.text_input("run_id", key="robust_run_id", disabled=busy, persist_state="session")
    y1, y2 = st.columns(2)
    with y1:
        st.number_input("回测年起", min_value=1990, max_value=2100, step=1, key="robust_year_start", disabled=busy, persist_state="session")
    with y2:
        st.number_input("回测年止", min_value=1990, max_value=2100, step=1, key="robust_year_end", disabled=busy, persist_state="session")
    t1, t2 = st.columns(2)
    with t1:
        st.number_input("调参期起", min_value=1990, max_value=2100, step=1, key="robust_tune_start", disabled=busy, persist_state="session")
    with t2:
        st.number_input("调参期止", min_value=1990, max_value=2100, step=1, key="robust_tune_end", disabled=busy, persist_state="session")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("验收期起", min_value=1990, max_value=2100, step=1, key="robust_check_start", disabled=busy, persist_state="session")
    with c2:
        st.number_input("验收期止", min_value=1990, max_value=2100, step=1, key="robust_check_end", disabled=busy, persist_state="session")
    d1, d2 = st.columns(2)
    with d1:
        st.number_input("盲测起", min_value=1990, max_value=2100, step=1, key="robust_deploy_start", disabled=busy, persist_state="session")
    with d2:
        st.number_input("盲测止", min_value=1990, max_value=2100, step=1, key="robust_deploy_end", disabled=busy, persist_state="session")
    st.caption("盲测窗须晚于验收期，且三窗互不重叠。结构/复原看调参 vs 验收；盲测进泛化与盈亏盾。")
    try:
        validate_year_windows(
            {
                "year_start": st.session_state.get("robust_year_start"),
                "year_end": st.session_state.get("robust_year_end"),
                "tune_start": st.session_state.get("robust_tune_start"),
                "tune_end": st.session_state.get("robust_tune_end"),
                "check_start": st.session_state.get("robust_check_start"),
                "check_end": st.session_state.get("robust_check_end"),
                "deploy_start": st.session_state.get("robust_deploy_start"),
                "deploy_end": st.session_state.get("robust_deploy_end"),
            }
        )
    except RobustSpecError as e:
        st.error(str(e))

    st.number_input("组合组数 N", min_value=1, max_value=200, step=1, key="robust_n_baskets", disabled=busy, persist_state="session")
    st.number_input("每组只数 K", min_value=1, max_value=50, step=1, key="robust_basket_size", disabled=busy, persist_state="session")
    st.number_input("seed", min_value=0, max_value=2_147_483_647, step=1, key="robust_seed", disabled=busy, persist_state="session")
    st.caption("宇宙：`%s`（与参数网格相同）。改 N/K/seed/年份/全区间后须再点抽取。" % DEFAULT_UNIVERSE_DIR)
    st.checkbox(
        "只抽全区间有行情",
        key="robust_full_span",
        disabled=busy,
        persist_state="session",
    )
    st.caption("勾选后：起始年年内已有第一根、且行情接到宇宙最末日。")
    if st.button("抽取", disabled=busy, key="robust_draw"):
        _draw_clicked()
    n_b = len(st.session_state.get("robust_drawn_baskets") or [])
    k = int(st.session_state.get("robust_basket_size") or 0)
    st.caption(
        "合格池 %s · 已抽 %s 组 × %s 只 · 平均重叠 %s"
        % (
            st.session_state.get("robust_eligible_n") or "—",
            n_b or "—",
            k or "—",
            st.session_state.get("robust_mean_jaccard") if n_b else "—",
        )
    )
    if n_b:
        with st.expander("已抽各组", expanded=False):
            for b in st.session_state.get("robust_drawn_baskets") or []:
                st.code("%s  %s" % (b.get("id"), ", ".join(b.get("stocks") or [])))

    st.number_input(
        "并行进程数（0=自动=min(N, CPU)；1=串行）",
        min_value=0,
        max_value=16,
        step=1,
        key="robust_workers",
        disabled=busy,
        persist_state="session",
    )
    n_preview = int(st.session_state.get("robust_n_baskets") or 40)
    pool_n = resolve_pool_workers(int(st.session_state.get("robust_workers") or 0), n_preview)
    st.caption("将开 %s 路（%s 组）" % (pool_n, n_preview))
    st.selectbox(
        "复权",
        options=list(DIVIDEND_TYPES),
        format_func=lambda k: "%s（%s）" % (DIVIDEND_LABELS.get(k, k), k),
        key="robust_compare_div",
        disabled=busy,
        persist_state="session",
    )
    st.checkbox("复利组合", key="robust_compound", disabled=busy, persist_state="session")

    with st.expander("评分维度", expanded=False):
        st.caption("改这里再点「只汇总」会重算 GO；主表用侧栏现算，不必重跑。")
        w1, w2 = st.columns(2)
        with w1:
            st.number_input(
                "防御权重%",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.0f",
                key="robust_score_w_def",
                disabled=busy,
                persist_state="session",
            )
            st.number_input(
                "复原权重%",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.0f",
                key="robust_score_w_res",
                disabled=busy,
                persist_state="session",
            )
        with w2:
            st.number_input(
                "结构权重%",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.0f",
                key="robust_score_w_str",
                disabled=busy,
                persist_state="session",
            )
            st.number_input(
                "泛化权重%",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.0f",
                key="robust_score_w_gen",
                disabled=busy,
                persist_state="session",
            )
        w_sum = (
            float(st.session_state.get("robust_score_w_def") or 0.0)
            + float(st.session_state.get("robust_score_w_str") or 0.0)
            + float(st.session_state.get("robust_score_w_res") or 0.0)
            + float(st.session_state.get("robust_score_w_gen") or 0.0)
        )
        st.caption("当前权重和 %.0f%%（打分时归一成 1；嵌套盲测顶泛化维，不摊权）" % w_sum)
        st.number_input(
            "回撤 0 分线 %",
            min_value=0.1,
            max_value=100.0,
            step=1.0,
            format="%.1f",
            key="robust_score_dd_cap_pct",
            disabled=busy,
            persist_state="session",
        )
        st.number_input(
            "获利因子目标",
            min_value=0.01,
            max_value=10.0,
            step=0.05,
            format="%.2f",
            key="robust_score_factor_target",
            disabled=busy,
            persist_state="session",
        )
        st.number_input(
            "盈亏比封顶",
            min_value=0.1,
            max_value=99.0,
            step=0.5,
            format="%.1f",
            key="robust_score_pf_cap",
            disabled=busy,
            persist_state="session",
        )
        st.number_input(
            "夏普目标",
            min_value=0.01,
            max_value=5.0,
            step=0.05,
            format="%.2f",
            key="robust_score_sharpe_target",
            disabled=busy,
            persist_state="session",
        )
        n1, n2 = st.columns(2)
        with n1:
            st.number_input(
                "笔数 0 分线",
                min_value=0,
                max_value=10000,
                step=1,
                key="robust_score_n_trades_floor",
                disabled=busy,
                persist_state="session",
            )
        with n2:
            st.number_input(
                "笔数满分线",
                min_value=1,
                max_value=10000,
                step=1,
                key="robust_score_n_trades_full",
                disabled=busy,
                persist_state="session",
            )
        st.number_input(
            "GO 中位分门槛",
            min_value=0.1,
            max_value=100.0,
            step=1.0,
            format="%.1f",
            key="robust_score_go_floor",
            disabled=busy,
            persist_state="session",
        )
        try:
            _score_from_state()
        except ValueError as e:
            st.error(str(e))


def _list_grid_summaries() -> list[Path]:
    if not GRID_ROOT.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(GRID_ROOT.glob("*/summary.json")):
        out.append(p)
    return out


def _list_history() -> list[Path]:
    if not ROBUST_ROOT.is_dir():
        return []
    return sorted([p for p in ROBUST_ROOT.iterdir() if p.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)


def _draw_clicked() -> None:
    try:
        spec = _current_spec()
        validate_year_windows(spec)
        sampled = sample_baskets_for_spec(spec, reshuffle=True)
        _store_drawn(sampled, spec)
        st.session_state["robust_flash"] = "已抽取 %s 组 × %s 只（合格池 %s）" % (
            sampled.get("n_baskets"),
            sampled.get("basket_size"),
            sampled.get("eligible_n"),
        )
        _persist()
    except Exception as e:
        st.session_state["robust_flash"] = str(e)


def _can_continue(prog: dict[str, Any] | None) -> bool:
    if _robust_is_busy():
        return False
    dest = _run_path()
    if not dest.is_dir():
        return False
    if (dest / "spec.json").is_file() or (dest / "freeze.json").is_file():
        batches = (prog or {}).get("batches") or []
        if batches and all(isinstance(b, dict) and str(b.get("status") or "") == "done" for b in batches):
            return False
        return True
    return False


def _spawn_robust_worker(dest: Path, spec_file: Path, *, reshuffle: bool) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = robust_worker_argv(
        spec_path=str(spec_file),
        workers=int(st.session_state.get("robust_workers") or 0),
        reshuffle=bool(reshuffle),
    )
    log_path = dest / "worker.log"
    log_f = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=spawn_creationflags(),
        )
    except Exception as e:
        log_f.close()
        st.error("无法启动实盘评估进程：%s" % e)
        st.session_state["robust_busy"] = False
        st.session_state["robust_stopping"] = False
        return
    log_f.close()
    st.session_state["robust_worker_pid"] = int(proc.pid)
    st.session_state["robust_worker_spawned_at"] = time.time()
    st.session_state["robust_busy"] = True
    st.session_state["robust_stopping"] = False
    st.session_state["robust_flash"] = "已启动进程 pid=%s。进度在下方刷新。" % proc.pid
    _persist()
    st.rerun()


def _handle_actions() -> None:
    action = str(st.session_state.pop("robust_action", "") or "")
    if not action:
        return
    if action == "pause":
        dest = _run_path()
        pid = int(st.session_state.get("robust_worker_pid") or 0)
        if pid <= 0:
            prog = load_progress(dest)
            pid = int((prog or {}).get("worker_pid") or 0)
        st.session_state["robust_stopping"] = True
        with st.spinner("正在结束进程树…"):
            result = stop_robust_worker(pid)
        if not result.get("ok"):
            st.error("进程未在时限内退出，请再点暂停。")
            _persist()
            return
        st.session_state["robust_stopping"] = False
        st.session_state["robust_busy"] = False
        st.session_state["robust_worker_pid"] = 0
        st.session_state.pop("robust_worker_spawned_at", None)
        st.session_state["robust_flash"] = "已暂停：已完成组留盘，未完成组续跑会重跑。"
        _persist()
        st.rerun()
        return
    if action == "summarize":
        _summarize_now()
        return
    if action == "resume":
        if _robust_is_busy():
            st.error("仍有 worker 在跑，请先暂停")
            return
        dest = _run_path()
        spec_file = dest / "spec.json"
        if not spec_file.is_file():
            st.error("找不到 %s" % spec_file)
            return
        _spawn_robust_worker(dest, spec_file, reshuffle=False)
        return
    if action not in ("run", "reshuffle"):
        return
    if _robust_is_busy():
        st.error("已有实盘评估在跑")
        return
    spec = _current_spec()
    try:
        validate_year_windows(spec)
    except RobustSpecError as e:
        st.error(str(e))
        return
    try:
        how = _ensure_drawn(spec, reshuffle=action == "reshuffle")
    except Exception as e:
        st.error(str(e))
        return
    dest = run_dir(spec)
    dest.mkdir(parents=True, exist_ok=True)
    spec_file = dest / "spec.json"
    spec_file.write_text(
        json.dumps(json_ready(spec), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if how == "drawn":
        st.session_state["robust_flash"] = "名单空或指纹已变，已自动抽取后再开跑。"
    _spawn_robust_worker(dest, spec_file, reshuffle=False)


def _sync_robust_worker_state(*, load_summary: bool = True) -> dict[str, Any] | None:
    name = _run_name()
    if not name:
        return None
    dest = _run_path(name)
    prog = load_progress(dest)
    live = ui_worker_busy(prog, **_robust_session_busy_kwargs())
    was_busy = bool(st.session_state.get("robust_busy"))
    st.session_state["robust_busy"] = bool(live)
    if not live:
        st.session_state["robust_worker_pid"] = 0
        st.session_state.pop("robust_worker_spawned_at", None)
        st.session_state["robust_stopping"] = False
        if load_summary:
            summary_p = dest / "summary.json"
            if summary_p.is_file() and (was_busy or not st.session_state.get("robust_summary")):
                try:
                    st.session_state["robust_summary"] = json.loads(
                        summary_p.read_text(encoding="utf-8")
                    )
                except Exception:
                    pass
        if was_busy:
            _persist()
    return prog


def _render_run_status() -> None:
    name = _run_name()
    prog = _load_robust_progress(name) if name else None
    busy = bool(st.session_state.get("robust_busy")) or ui_worker_busy(
        prog, **_robust_session_busy_kwargs()
    )
    if not name and not busy:
        return
    cap = robust_progress_caption(prog) if prog else ""
    if busy:
        st.info("正在跑实盘评估" + (" · %s" % cap if cap else " · 正在写 progress"))
    elif cap:
        st.caption(cap)
    frac, walk_tot = walk_progress_ratio(prog)
    if walk_tot > 0:
        st.progress(frac)
        st.caption("walk %.1f / %s" % (float((prog or {}).get("batch_walk_done") or 0), walk_tot))
    if name:
        log_path = _run_path(name) / "worker.log"
        tail = tail_text(log_path, 16)
        if tail:
            st.code(tail, language="text")


def _progress_tick() -> None:
    was = bool(st.session_state.get("robust_busy"))
    _sync_robust_worker_state()
    _render_run_status()
    now = bool(st.session_state.get("robust_busy"))
    if was != now:
        st.rerun()


def _call_progress_fragment() -> None:
    global _PROGRESS_FRAG
    if _PROGRESS_FRAG is None:
        fn = _progress_tick
        if hasattr(st, "fragment"):
            try:
                fn = st.fragment(run_every=2.0)(_progress_tick)
            except Exception:
                fn = _progress_tick
        _PROGRESS_FRAG = fn
    _PROGRESS_FRAG()


def render_robust_mode() -> None:
    _ensure_state()
    _handle_actions()
    flash = st.session_state.pop("robust_flash", None)
    if flash:
        st.info(str(flash))
    _sync_robust_worker_state()
    _call_progress_fragment()
    busy = _robust_is_busy()
    repo = REPO
    prog = _load_robust_progress()

    st.markdown("**参数来源**")
    st.caption("默认用现行 config；可选网格 summary 灌入指定格子（缺省 recommend.id）的 overrides。不改 config 文件。")
    sums = _list_grid_summaries()
    rels = [PARAM_SOURCE_CONFIG]
    for path in sums:
        try:
            rels.append(str(path.relative_to(repo)).replace("\\", "/"))
        except ValueError:
            rels.append(str(path))
    cur = str(st.session_state.get("robust_param_source") or PARAM_SOURCE_CONFIG).strip()
    if cur and cur not in rels:
        rels.append(cur)
    st.selectbox(
        "参数",
        options=rels,
        disabled=busy,
        key="robust_param_source",
        persist_state="session",
    )
    pick = str(st.session_state.get("robust_param_source") or PARAM_SOURCE_CONFIG).strip()
    if pick and pick != PARAM_SOURCE_CONFIG:
        st.text_input(
            "格子 id",
            key="robust_cell_id",
            disabled=busy,
            help="空则用 summary.recommend.id；网格「送入」会写入所选 id。",
        )
        cell_id = str(st.session_state.get("robust_cell_id") or "").strip()
        try:
            meta = resolve_overrides_from_summary(
                pick, recommend_id=cell_id or None
            )
            st.caption(
                "将用 **%s**（%s）· %s"
                % (
                    meta.get("id"),
                    meta.get("kind"),
                    ", ".join(sorted(meta.get("overrides") or {})) or "空 overrides",
                )
            )
        except Exception as e:
            st.warning(str(e))
    else:
        st.caption("使用拼接脚本 / config 现行常量（空 overrides）。")

    with st.expander("高级：粘贴 overrides JSON（非空则优先）", expanded=False):
        st.text_area(
            "overrides JSON",
            key="robust_overrides_json",
            height=100,
            disabled=busy,
            label_visibility="collapsed",
        )

    st.markdown("**操作**")
    resume_ok = bool(not busy and _can_continue(prog))
    with st.container(horizontal=True):
        st.button(
            "开跑",
            type="primary",
            disabled=busy,
            key="robust_run",
            on_click=_mark_start,
        )
        st.button("暂停", disabled=not busy, key="robust_pause", on_click=_mark_pause)
        st.button("继续", disabled=not resume_ok, key="robust_resume", on_click=_mark_resume)
        st.button("只汇总", disabled=busy, key="robust_sum_only", on_click=_mark_summarize)
        st.button("重抽并开跑", disabled=busy, key="robust_reshuffle", on_click=_mark_reshuffle)
    st.caption("开跑沿用已抽/freeze 名单；指纹变了会自动重抽。继续跳过已有成交表的组。只汇总用当前侧栏评分重算。")

    hist = _list_history()
    if hist:
        with st.expander("加载历史 run", expanded=False):
            hnames = [path.name for path in hist]
            h1, h2 = st.columns((3, 1))
            with h1:
                hpick = st.selectbox(
                    "历史",
                    options=hnames,
                    key="robust_hist_pick",
                    label_visibility="collapsed",
                    disabled=busy,
                )
            with h2:
                do_hist = st.button("加载", disabled=busy or not hpick, key="robust_hist_load")
            if do_hist and hpick:
                sp = ROBUST_ROOT / hpick / "summary.json"
                if sp.is_file():
                    st.session_state["robust_summary"] = json.loads(
                        sp.read_text(encoding="utf-8")
                    )
                    st.session_state["robust_pending_run_id"] = hpick
                    st.rerun()
                else:
                    st.warning("无 summary.json：%s" % sp)

    preview = st.session_state.get("robust_drawn_baskets")
    if isinstance(preview, list) and preview:
        with st.expander(
            "抽篮 · 合格池 %s · 平均重叠 %s"
            % (
                st.session_state.get("robust_eligible_n"),
                st.session_state.get("robust_mean_jaccard"),
            ),
            expanded=False,
        ):
            rows = [
                {"组": b.get("id"), "标的": ", ".join(b.get("stocks") or [])}
                for b in preview
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    _render_results()


def _summarize_now() -> None:
    try:
        raw = _current_spec()
        root = run_dir(raw)
        if not root.is_dir():
            st.error("尚无 run 目录：%s" % root)
            return
        out = summarize_run(root, score=_score_from_state(), spec=raw)
        st.session_state["robust_summary"] = out
        st.success("已按当前侧栏评分重算：%s" % ((out.get("verdict") or {}).get("verdict")))
        _persist()
    except Exception as e:
        st.error(str(e))


_EPS_TONE = 1e-6
_PASS_BG = "background-color: rgba(46, 160, 67, 0.18)"


def _p10(vals: list[float]) -> float | None:
    xs = sorted(float(x) for x in vals)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    idx = 0.10 * (len(xs) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(xs) - 1)
    frac = idx - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def _fmt_score(val: Any) -> str:
    if val is None:
        return "—"
    try:
        return "%.2f" % float(val)
    except (TypeError, ValueError):
        return "—"


def _style_pass(series: pd.Series, *, kind: str, cfg: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for val in series:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            out.append("")
            continue
        try:
            x = float(val)
        except (TypeError, ValueError):
            out.append("")
            continue
        ok = False
        if kind == "dd":
            try:
                cap = float(cfg.get("dd_cap") or 0.35) * 100.0
            except (TypeError, ValueError):
                cap = 35.0
            ok = x <= cap + _EPS_TONE
        elif kind == "n":
            try:
                floor = float(cfg.get("n_trades_floor") or 30.0)
            except (TypeError, ValueError):
                floor = 30.0
            ok = x + _EPS_TONE >= floor
        else:
            ok = x + _EPS_TONE >= 0.0
        out.append(_PASS_BG if ok else "")
    return out


def _live_basket_rows(
    baskets: list[Any], cfg: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    missing_all = False
    for b in baskets:
        if not isinstance(b, Mapping):
            continue
        wins = b.get("windows") if isinstance(b.get("windows"), Mapping) else {}
        all_block = wins.get("all") if isinstance(wins, Mapping) else None
        if not isinstance(all_block, Mapping) or not all_block:
            missing_all = True
        sc = score_basket(wins, cfg)
        dep = wins.get("deploy") if isinstance(wins.get("deploy"), Mapping) else {}
        mdd = dep.get("max_dd")
        try:
            mdd_pct = None if mdd is None else round(float(mdd) * 100.0, 2)
        except (TypeError, ValueError):
            mdd_pct = None
        rows.append(
            {
                "id": b.get("id"),
                "s_def": sc.get("s_def"),
                "s_str": sc.get("s_str"),
                "s_res": sc.get("s_res"),
                "s_gen": sc.get("s_gen"),
                "total": sc.get("total"),
                "scored": sc.get("scored"),
                "calmar": dep.get("calmar"),
                "max_dd": mdd,
                "oos_sharpe": dep.get("oos_sharpe") if dep.get("oos_sharpe") is not None else dep.get("sharpe"),
                "profit_factor": dep.get("profit_factor"),
                "win_rate": dep.get("win_rate"),
                "n_trades": dep.get("n_trades"),
                "回撤%": mdd_pct,
            }
        )
    return rows, missing_all


def _render_results() -> None:
    summary = st.session_state.get("robust_summary")
    if not isinstance(summary, dict) or not (
        summary.get("verdict") or summary.get("baskets")
    ):
        return
    st.divider()
    st.markdown("**评估结论**")
    cfg = _score_cfg_for_view()
    live_rows, missing_all = _live_basket_rows(list(summary.get("baskets") or []), cfg)
    verd = eval_run_score(live_rows, cfg)
    label = str(verd.get("verdict") or "")
    if label == "GO":
        st.success("%s · %s" % (label, verd.get("reason") or ""))
    else:
        st.error("%s · %s" % (label, verd.get("reason") or ""))
    if missing_all:
        st.warning("旧 summary 缺 windows.all，现算防御/泛化会偏。请先点「只汇总」从成交表重算。")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("中位总分", _fmt_score(verd.get("median_total")))
    m2.metric("已评分组", "%s / %s" % (verd.get("n_scored"), verd.get("n_baskets")))
    m3.metric("GO 门槛", _fmt_score(verd.get("go_floor")))
    p10 = _p10(
        [float(r["max_dd"]) for r in live_rows if r.get("max_dd") is not None]
    )
    m4.metric(
        "P10 回撤",
        "—" if p10 is None else "%.2f%%" % (100.0 * p10),
    )
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("中位防御", _fmt_score(_median([r["s_def"] for r in live_rows if r.get("s_def") is not None])))
    d2.metric("中位结构", _fmt_score(_median([r["s_str"] for r in live_rows if r.get("s_str") is not None])))
    d3.metric("中位复原", _fmt_score(_median([r["s_res"] for r in live_rows if r.get("s_res") is not None])))
    d4.metric("中位泛化", _fmt_score(_median([r["s_gen"] for r in live_rows if r.get("s_gen") is not None])))
    caps = []
    if summary.get("mean_jaccard") is not None:
        caps.append("篮子平均重叠 %s" % summary.get("mean_jaccard"))
    if summary.get("run_id"):
        caps.append("run_id=%s" % summary.get("run_id"))
    caps.append("主表用侧栏现算，只汇总才落盘")
    st.caption(" · ".join(caps))

    table_rows = []
    for r in live_rows:
        table_rows.append(
            {
                "组": r.get("id"),
                "总分": r.get("total"),
                "防御": r.get("s_def"),
                "结构": r.get("s_str"),
                "复原": r.get("s_res"),
                "泛化": r.get("s_gen"),
                "卡玛": r.get("calmar"),
                "回撤%": r.get("回撤%"),
                "夏普": r.get("oos_sharpe"),
                "盈亏比": r.get("profit_factor"),
                "胜率%": r.get("win_rate"),
                "笔数": r.get("n_trades"),
            }
        )
    if table_rows:
        st.markdown("**各组综合分 / 盲测 KPI**")
        df = pd.DataFrame(table_rows)
        styled = df.style
        tone_map = {
            "回撤%": "dd",
            "笔数": "n",
            "夏普": "zero",
            "卡玛": "zero",
            "胜率%": "zero",
            "盈亏比": "zero",
        }
        for col, kind in tone_map.items():
            if col in df.columns:
                styled = styled.apply(
                    lambda s, k=kind: _style_pass(s, kind=k, cfg=cfg),
                    subset=[col],
                )
        fmt: dict[str, str] = {}
        for col in ("总分", "防御", "结构", "复原", "泛化"):
            if col in df.columns:
                fmt[col] = "{:.2f}"
        if "卡玛" in df.columns:
            fmt["卡玛"] = "{:.3f}"
        if "回撤%" in df.columns:
            fmt["回撤%"] = "{:.2f}"
        if "夏普" in df.columns:
            fmt["夏普"] = "{:.3f}"
        if "盈亏比" in df.columns:
            fmt["盈亏比"] = "{:.2f}"
        if "胜率%" in df.columns:
            fmt["胜率%"] = "{:.1f}"
        if "笔数" in df.columns:
            fmt["笔数"] = "{:.0f}"
        if fmt:
            styled = styled.format(fmt, na_rep="—")
        st.dataframe(styled, hide_index=True, width="stretch")

    with st.expander("产物路径"):
        st.code(str(summary.get("summary_path") or summary.get("root") or ""))
