# coding: utf-8
"""实盘评估 Streamlit 页：侧栏门槛 + 随机组合开跑 / 汇总。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from analyze import (
    DEFAULT_DIVIDEND_TYPE,
    DIVIDEND_LABELS,
    DIVIDEND_TYPES,
)
from robust_gate import default_gate, fill_gate
from robust_run import RobustError, run_robust
from robust_sample import sample_baskets_for_spec
from robust_spec import (
    ROBUST_ROOT,
    YEAR_DEFAULTS,
    RobustSpecError,
    resolve_overrides_from_summary,
    run_dir,
    validate_year_windows,
)
from robust_summarize import summarize_run
from ui_cache import CACHE_PATH, merge_form_cache, snapshot_form_state

ROBUST_MODE = "实盘评估"
THEME = Path(__file__).resolve().parents[2]
GRID_ROOT = THEME / "report" / "grid"
PARAM_SOURCE_CONFIG = "现行 config（默认）"


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
    dg = default_gate()
    for k, v in YEAR_DEFAULTS.items():
        ss.setdefault("robust_%s" % k, int(v))
    ss.setdefault("robust_run_id", "post_grid_robust")
    ss.setdefault("robust_n_baskets", 40)
    ss.setdefault("robust_basket_size", 10)
    ss.setdefault("robust_seed", 42)
    ss.setdefault("robust_workers", 4)
    ss.setdefault("robust_ma_type", "EMA")
    ss.setdefault("robust_compare_div", DEFAULT_DIVIDEND_TYPE)
    ss.setdefault("robust_compound", True)
    ss.setdefault("robust_universe", "tools/csv/none")
    ss.setdefault("robust_param_source", PARAM_SOURCE_CONFIG)
    ss.setdefault("robust_busy", False)
    # hard
    ss.setdefault("robust_h_calmar_en", bool(dg["hard"]["calmar"]["enabled"]))
    ss.setdefault("robust_h_calmar_min", float(dg["hard"]["calmar"]["min"]))
    ss.setdefault("robust_h_dd_en", bool(dg["hard"]["max_dd"]["enabled"]))
    ss.setdefault("robust_h_dd_pct", abs(float(dg["hard"]["max_dd"]["floor"])) * 100.0)
    ss.setdefault("robust_h_sharpe_en", bool(dg["hard"]["oos_sharpe"]["enabled"]))
    ss.setdefault("robust_h_sharpe_min", float(dg["hard"]["oos_sharpe"]["min"]))
    ss.setdefault("robust_h_pf_en", bool(dg["hard"]["profit_factor"]["enabled"]))
    ss.setdefault("robust_h_pf_min", float(dg["hard"]["profit_factor"]["min"]))
    # soft
    ss.setdefault("robust_s_wr_en", bool(dg["soft"]["win_rate"]["enabled"]))
    ss.setdefault("robust_s_wr_veto", bool(dg["soft"]["win_rate"]["veto"]))
    ss.setdefault("robust_s_wr_min", float(dg["soft"]["win_rate"]["min"]))
    ss.setdefault("robust_s_nt_en", bool(dg["soft"]["n_trades"]["enabled"]))
    ss.setdefault("robust_s_nt_veto", bool(dg["soft"]["n_trades"]["veto"]))
    ss.setdefault("robust_s_nt_min", int(dg["soft"]["n_trades"]["min"]))
    ss.setdefault("robust_s_nt_psy", float(dg["soft"]["n_trades"]["per_stock_year_min"]))
    # aggregate
    ss.setdefault("robust_a_pass", float(dg["aggregate"]["pass_rate_min"]))
    ss.setdefault("robust_a_calmar", float(dg["aggregate"]["median_calmar_min"]))
    ss.setdefault("robust_a_tail_pct", abs(float(dg["aggregate"]["tail_max_dd_floor"])) * 100.0)


def gate_from_state() -> dict[str, Any]:
    ss = st.session_state
    return fill_gate(
        {
            "hard": {
                "calmar": {
                    "enabled": bool(ss.get("robust_h_calmar_en", True)),
                    "min": float(ss.get("robust_h_calmar_min") or 1.2),
                },
                "max_dd": {
                    "enabled": bool(ss.get("robust_h_dd_en", True)),
                    "floor": -abs(float(ss.get("robust_h_dd_pct") or 12.0)) / 100.0,
                },
                "oos_sharpe": {
                    "enabled": bool(ss.get("robust_h_sharpe_en", True)),
                    "min": float(ss.get("robust_h_sharpe_min") or 0.7),
                },
                "profit_factor": {
                    "enabled": bool(ss.get("robust_h_pf_en", True)),
                    "min": float(ss.get("robust_h_pf_min") or 1.4),
                },
            },
            "soft": {
                "win_rate": {
                    "enabled": bool(ss.get("robust_s_wr_en", True)),
                    "veto": bool(ss.get("robust_s_wr_veto", False)),
                    "min": float(ss.get("robust_s_wr_min") or 42.0),
                },
                "n_trades": {
                    "enabled": bool(ss.get("robust_s_nt_en", True)),
                    "veto": bool(ss.get("robust_s_nt_veto", False)),
                    "min": int(ss.get("robust_s_nt_min") or 1),
                    "per_stock_year_min": float(ss.get("robust_s_nt_psy") or 0.5),
                },
            },
            "aggregate": {
                "pass_rate_min": float(ss.get("robust_a_pass") or 0.7),
                "median_calmar_min": float(ss.get("robust_a_calmar") or 1.2),
                "tail_max_dd_floor": -abs(float(ss.get("robust_a_tail_pct") or 15.0)) / 100.0,
            },
        }
    )


def _current_spec() -> dict[str, Any]:
    ss = st.session_state
    pick = str(ss.get("robust_param_source") or PARAM_SOURCE_CONFIG).strip()
    ofrom = "" if (not pick or pick == PARAM_SOURCE_CONFIG) else pick
    raw = {
        "theme": "hongli_band",
        "run_id": str(ss.get("robust_run_id") or "post_grid_robust").strip(),
        "overrides_from": ofrom,
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
        "universe_dir": str(ss.get("robust_universe") or "tools/csv/none"),
        "ma_type": str(ss.get("robust_ma_type") or "EMA"),
        "compare_div": str(ss.get("robust_compare_div") or DEFAULT_DIVIDEND_TYPE),
        "compound_backtest": bool(ss.get("robust_compound", True)),
        "gate": gate_from_state(),
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


def render_robust_sidebar() -> None:
    _ensure_state()
    busy = bool(st.session_state.get("robust_busy"))
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
    st.caption("盲测窗须晚于验收期，且三窗互不重叠；GO/NO-GO 只看盲测窗。")
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
    st.number_input("进程数", min_value=0, max_value=16, step=1, key="robust_workers", disabled=busy, persist_state="session")
    st.text_input("宇宙目录", key="robust_universe", disabled=busy, persist_state="session")
    st.selectbox("均线", options=["EMA", "SMA"], key="robust_ma_type", disabled=busy, persist_state="session")
    st.selectbox(
        "复权",
        options=list(DIVIDEND_TYPES),
        format_func=lambda k: "%s（%s）" % (DIVIDEND_LABELS.get(k, k), k),
        key="robust_compare_div",
        disabled=busy,
        persist_state="session",
    )
    st.checkbox("复利组合", key="robust_compound", disabled=busy, persist_state="session")

    st.markdown("**硬门（单组必过）**")
    st.checkbox("卡玛", key="robust_h_calmar_en", disabled=busy, persist_state="session")
    st.number_input("卡玛 ≥", min_value=0.0, step=0.1, key="robust_h_calmar_min", disabled=busy, persist_state="session")
    st.checkbox("最大回撤", key="robust_h_dd_en", disabled=busy, persist_state="session")
    st.number_input("回撤下限 %（绝对值）", min_value=1.0, max_value=80.0, step=1.0, key="robust_h_dd_pct", disabled=busy, persist_state="session")
    st.checkbox("夏普", key="robust_h_sharpe_en", disabled=busy, persist_state="session")
    st.number_input("夏普 ≥", min_value=0.0, step=0.1, key="robust_h_sharpe_min", disabled=busy, persist_state="session")
    st.checkbox("盈亏比", key="robust_h_pf_en", disabled=busy, persist_state="session")
    st.number_input("盈亏比 ≥", min_value=0.0, step=0.1, key="robust_h_pf_min", disabled=busy, persist_state="session")

    st.markdown("**软门（默认只警告）**")
    st.checkbox("胜率启用", key="robust_s_wr_en", disabled=busy, persist_state="session")
    st.checkbox("胜率否决", key="robust_s_wr_veto", disabled=busy, persist_state="session")
    st.number_input("胜率 ≥ %", min_value=0.0, max_value=100.0, step=1.0, key="robust_s_wr_min", disabled=busy, persist_state="session")
    st.checkbox("笔数启用", key="robust_s_nt_en", disabled=busy, persist_state="session")
    st.checkbox("笔数否决", key="robust_s_nt_veto", disabled=busy, persist_state="session")
    st.number_input("笔数下限", min_value=0, step=1, key="robust_s_nt_min", disabled=busy, persist_state="session")
    st.number_input("每票每年笔数 ≥", min_value=0.0, step=0.1, key="robust_s_nt_psy", disabled=busy, persist_state="session")

    st.markdown("**整次裁决**")
    st.number_input("通过率 ≥", min_value=0.0, max_value=1.0, step=0.05, key="robust_a_pass", disabled=busy, persist_state="session")
    st.number_input("中位卡玛 ≥", min_value=0.0, step=0.1, key="robust_a_calmar", disabled=busy, persist_state="session")
    st.number_input("尾部回撤 P10 下限 %", min_value=1.0, max_value=80.0, step=1.0, key="robust_a_tail_pct", disabled=busy, persist_state="session")


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


def render_robust_mode() -> None:
    _ensure_state()
    busy = bool(st.session_state.get("robust_busy"))
    repo = THEME.parent

    st.markdown("**参数来源**")
    st.caption("默认用现行 config；可选网格 summary 灌入 recommend 的 overrides。不改 config 文件。")
    sums = _list_grid_summaries()
    rels = [PARAM_SOURCE_CONFIG]
    for path in sums:
        try:
            rels.append(str(path.relative_to(repo)).replace("\\", "/"))
        except ValueError:
            rels.append(str(path))
    # 网格「送入」写入的路径若不在列表则补上
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
        try:
            meta = resolve_overrides_from_summary(pick)
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
    with st.container(horizontal=True):
        do_run = st.button("开跑", type="primary", disabled=busy, key="robust_run")
        do_sum = st.button("只汇总", disabled=busy, key="robust_sum_only")
        do_preview = st.button("预览抽篮", disabled=busy, key="robust_preview_btn")
        do_reshuffle = st.button("重抽并开跑", disabled=busy, key="robust_reshuffle")
    st.caption("开跑沿用 freeze 名单；「重抽并开跑」忽略旧名单。只汇总用当前侧栏门槛重算，不重跑。")

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

    if do_preview:
        try:
            raw = _current_spec()
            sampled = sample_baskets_for_spec(raw, reshuffle=True)
            st.session_state["robust_preview_baskets"] = sampled
        except Exception as e:
            st.error(str(e))

    preview = st.session_state.get("robust_preview_baskets")
    if isinstance(preview, dict):
        with st.expander(
            "抽篮预览 · 合格池 %s · 平均重叠 %s"
            % (preview.get("eligible_n"), preview.get("mean_jaccard")),
            expanded=True,
        ):
            rows = []
            for b in (preview.get("baskets") or [])[:8]:
                rows.append(
                    {"组": b.get("id"), "标的": ", ".join(b.get("stocks") or [])}
                )
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("仅展示前 8 组；开跑以 freeze 为准。")

    if do_run or do_reshuffle:
        _run_now(reshuffle=bool(do_reshuffle))
    if do_sum:
        _summarize_now()

    _render_results()


def _run_now(*, reshuffle: bool) -> None:
    st.session_state["robust_busy"] = True
    bar = st.progress(0.0)
    status = st.empty()

    def on_progress(ev: dict[str, Any]) -> None:
        done = int(ev.get("done") or 0)
        total = max(int(ev.get("total") or 1), 1)
        bar.progress(min(1.0, float(done) / float(total)))
        status.info("%s · %s/%s · %s" % (ev.get("phase"), done, total, ev.get("label") or ""))

    try:
        raw = _current_spec()
        out = run_robust(
            raw,
            reshuffle=reshuffle,
            workers=int(st.session_state.get("robust_workers") or 0),
            on_progress=on_progress,
        )
        st.session_state["robust_summary"] = out
        verd = (out.get("verdict") or {}).get("verdict")
        status.success("完成 · %s" % verd)
        bar.progress(1.0)
    except (RobustSpecError, RobustError) as e:
        st.error(str(e))
    except Exception as e:
        st.error("%s: %s" % (type(e).__name__, e))
    finally:
        st.session_state["robust_busy"] = False
        _persist()


def _summarize_now() -> None:
    try:
        raw = _current_spec()
        root = run_dir(raw)
        if not root.is_dir():
            st.error("尚无 run 目录：%s" % root)
            return
        out = summarize_run(root, gate=gate_from_state(), spec=raw)
        st.session_state["robust_summary"] = out
        st.success("已按当前侧栏门槛重算：%s" % ((out.get("verdict") or {}).get("verdict")))
        _persist()
    except Exception as e:
        st.error(str(e))


def _render_results() -> None:
    summary = st.session_state.get("robust_summary")
    if not isinstance(summary, dict) or not summary.get("verdict"):
        return
    st.divider()
    st.markdown("**评估结论**")
    verd = summary.get("verdict") or {}
    label = str(verd.get("verdict") or "")
    if label == "GO":
        st.success("%s · %s" % (label, verd.get("reason") or ""))
    else:
        st.error("%s · %s" % (label, verd.get("reason") or ""))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("通过率", "%.0f%%" % (100.0 * float(verd.get("pass_rate") or 0)))
    m2.metric("通过组数", "%s / %s" % (verd.get("n_pass"), verd.get("n_baskets")))
    m3.metric(
        "中位卡玛",
        "—" if verd.get("median_calmar") is None else "%.3f" % verd["median_calmar"],
    )
    m4.metric(
        "P10 回撤",
        "—"
        if verd.get("p10_max_dd") is None
        else "%.2f%%" % (100.0 * float(verd["p10_max_dd"])),
    )
    caps = []
    if summary.get("mean_jaccard") is not None:
        caps.append("篮子平均重叠 %s" % summary.get("mean_jaccard"))
    if summary.get("run_id"):
        caps.append("run_id=%s" % summary.get("run_id"))
    if caps:
        st.caption(" · ".join(caps))

    fails = summary.get("fail_counts") or {}
    warns = summary.get("warn_counts") or {}
    if fails or warns:
        f1, f2 = st.columns(2)
        with f1:
            if fails:
                st.markdown("失败原因")
                st.dataframe(
                    pd.DataFrame([{"原因": k, "次数": v} for k, v in fails.items()]),
                    hide_index=True,
                    width="stretch",
                )
        with f2:
            if warns:
                st.markdown("警告原因")
                st.dataframe(
                    pd.DataFrame([{"原因": k, "次数": v} for k, v in warns.items()]),
                    hide_index=True,
                    width="stretch",
                )

    rows = []
    for b in summary.get("baskets") or []:
        dep = (b.get("windows") or {}).get("deploy") or {}
        mdd = dep.get("max_dd")
        rows.append(
            {
                "组": b.get("id"),
                "通过": "是" if b.get("pass") else "否",
                "卡玛": dep.get("calmar"),
                "回撤%": None if mdd is None else round(float(mdd) * 100.0, 2),
                "夏普": dep.get("oos_sharpe"),
                "盈亏比": dep.get("profit_factor"),
                "胜率%": dep.get("win_rate"),
                "笔数": dep.get("n_trades"),
                "失败": b.get("fail"),
                "警告": b.get("warn"),
            }
        )
    if rows:
        st.markdown("**各组盲测 KPI**")
        only_fail = st.checkbox("只看未通过", key="robust_only_fail", value=False)
        df = pd.DataFrame(rows)
        if only_fail:
            df = df[df["通过"] == "否"]
        st.dataframe(
            df,
            hide_index=True,
            width="stretch",
            column_config={
                "卡玛": st.column_config.NumberColumn("卡玛", format="%.3f"),
                "回撤%": st.column_config.NumberColumn("回撤%", format="%.2f"),
                "夏普": st.column_config.NumberColumn("夏普", format="%.3f"),
                "盈亏比": st.column_config.NumberColumn("盈亏比", format="%.2f"),
                "胜率%": st.column_config.NumberColumn("胜率%", format="%.1f"),
                "笔数": st.column_config.NumberColumn("笔数", format="%d"),
            },
        )

    with st.expander("产物路径"):
        st.code(str(summary.get("summary_path") or summary.get("root") or ""))
