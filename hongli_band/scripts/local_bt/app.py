# coding: utf-8
"""HlBand 本地回测可视化（Streamlit）。

启动:
  streamlit run hongli_band/scripts/local_bt/app.py
  或: python hongli_band/local_bt_ui.py
"""
from __future__ import annotations

import sys
import traceback
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
DEFAULT_CSV_DIR = REPO / "tools" / "csv"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from analyze import (  # noqa: E402
    analyze_detail,
    batch_summary_dataframe,
    batch_year_summary_dataframe,
    csv_date_range,
    daily_csvs_by_stock,
    date_to_ymd,
    filter_trades_by_range,
    list_daily_csvs,
    list_detail_csvs,
    load_detail_raw,
    ohlc_from_csv,
    parse_budget_from_log,
    summarize_batch_row,
    trades_to_dataframe,
    union_date_range,
    write_batch_summary_csv,
    write_batch_year_summary_csv,
    ymd_to_date,
)
from run import run_backtest, run_batch  # noqa: E402
from stock_select import (  # noqa: E402
    DEFAULT_FILTERS,
    SCORE_YEARS,
    coverage_notes,
    csv_dir_fingerprint,
    format_book_snippet,
    report_fingerprint,
    scan_reports,
    score_universe,
    write_select_csv,
)
from trades_csv import trades_csv_path  # noqa: E402

import streamlit as st  # noqa: E402


st.set_page_config(page_title="HlBand 本地回测", layout="wide")
st.title("HlBand Backtesting")


def _daily_dir_fingerprint(csv_dir: str) -> tuple:
    root = Path(csv_dir)
    if not root.is_dir():
        return ()
    out = []
    for p in sorted(root.glob("*_1d_*.csv")):
        try:
            st_ = p.stat()
        except OSError:
            continue
        out.append((p.name, int(st_.st_mtime_ns), int(st_.st_size)))
    return tuple(out)


@st.cache_data(show_spinner="扫描行情目录…")
def _cached_daily_metas(csv_dir: str, fingerprint: tuple) -> list[dict]:
    # fingerprint 仅作缓存键：目录内文件名/mtime/size 变化即失效
    _ = fingerprint
    return daily_csvs_by_stock(csv_dir)


@st.cache_data(show_spinner="扫描回测报告与日线股性…")
def _cached_select_scan(report_dir: str, csv_dir: str, fp_report: tuple, fp_csv: tuple) -> dict:
    _ = fp_report, fp_csv
    return scan_reports(report_dir, csv_dir)


def _fmt_ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _plot_equity(eq: pd.DataFrame, budget: float, title: str) -> go.Figure:
    fig = go.Figure()
    pts = eq.dropna(subset=["date"]) if "date" in eq.columns else eq
    if pts.empty:
        fig.add_annotation(text="无已平仓成交", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
    else:
        fig.add_trace(
            go.Scatter(
                x=pts["date"],
                y=pts["equity"],
                mode="lines+markers",
                name="权益",
                line=dict(color="#1565c0", width=2),
                marker=dict(size=6),
            )
        )
        fig.add_hline(y=budget, line_dash="dash", line_color="#9e9e9e", annotation_text="预算")
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="权益 (元)",
        height=360,
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h"),
    )
    return fig


def _plot_pnl_hist(trades: list[dict]) -> go.Figure:
    pnls = [float(t["pnl"]) for t in trades]
    fig = go.Figure()
    if pnls:
        fig.add_trace(go.Histogram(x=pnls, nbinsx=min(20, max(5, len(pnls))), name="盈亏", marker_color="#1565c0"))
    fig.update_layout(
        title="单笔已实现盈亏分布",
        xaxis_title="盈亏 (元)",
        yaxis_title="笔数",
        height=320,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def _nearest_ohlc_idx(ohlc: pd.DataFrame, day_raw) -> pd.Timestamp | None:
    """把成交日对齐到日线索引上最近的一根 K；落在可见区间外则不画。"""
    digits = "".join(ch for ch in str(day_raw or "") if ch.isdigit())
    if len(digits) < 8 or ohlc.empty:
        return None
    d = pd.Timestamp(digits[:8])
    idx = pd.DatetimeIndex(pd.to_datetime(ohlc.index).normalize())
    if d < idx[0] or d > idx[-1]:
        return None
    if d in idx:
        loc = idx.get_loc(d)
        return ohlc.index[int(loc) if not isinstance(loc, slice) else loc.start]
    pos = int(idx.searchsorted(d))
    if pos >= len(idx):
        return None
    if pos == 0:
        return ohlc.index[0]
    a, b = idx[pos - 1], idx[pos]
    pick = a if abs((a - d).days) <= abs((b - d).days) else b
    loc = idx.get_loc(pick)
    return ohlc.index[int(loc) if not isinstance(loc, slice) else loc.start]


def _ohlc_x_pos(ohlc: pd.DataFrame, ts: pd.Timestamp) -> int:
    loc = ohlc.index.get_loc(ts)
    return int(loc) if not isinstance(loc, slice) else int(loc.start)


def _kline_tick_vals(n: int, max_ticks: int = 12) -> list[int]:
    if n <= 0:
        return []
    if n == 1:
        return [0]
    n_ticks = min(max_ticks, n)
    vals = [int(round(i * (n - 1) / (n_ticks - 1))) for i in range(n_ticks)]
    return sorted(set(vals))


def _plot_kline(
    ohlc: pd.DataFrame,
    trades: list[dict],
    title: str,
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.72, 0.28],
    )
    if ohlc.empty:
        fig.add_annotation(text="无 OHLC", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    # 按交易日等间距排布，周末/节假日不占轴（日历空隙不画）
    ohlc = ohlc.copy()
    ohlc.index = pd.DatetimeIndex(pd.to_datetime(ohlc.index).normalize())
    ohlc = ohlc[~ohlc.index.duplicated(keep="last")].sort_index()
    x_pos = list(range(len(ohlc)))
    x_dates = ohlc.index.strftime("%Y-%m-%d").tolist()

    fig.add_trace(
        go.Candlestick(
            x=x_pos,
            open=ohlc["Open"],
            high=ohlc["High"],
            low=ohlc["Low"],
            close=ohlc["Close"],
            name="日线",
            increasing_line_color="#e53935",
            decreasing_line_color="#43a047",
            customdata=x_dates,
            hovertemplate=(
                "%{customdata}<br>"
                "开 %{open}<br>高 %{high}<br>低 %{low}<br>收 %{close}"
                "<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )
    if "Volume" in ohlc.columns:
        fig.add_trace(
            go.Bar(
                x=x_pos,
                y=ohlc["Volume"],
                name="成交量",
                marker_color="#90a4ae",
                customdata=x_dates,
                hovertemplate="%{customdata}<br>量 %{y}<extra></extra>",
            ),
            row=2,
            col=1,
        )

    # B 在 Low 下方、S 在 High 上方；虚线连到影线端点
    y_span = float(ohlc["High"].max() - ohlc["Low"].min()) or 1.0
    pad = y_span * 0.025
    color_b = "#b71c1c"
    color_s = "#1b5e20"

    buy_x, buy_y, buy_hover = [], [], []
    sell_x, sell_y, sell_hover = [], [], []

    for t in trades:
        bd = _nearest_ohlc_idx(ohlc, t.get("buy_open_day"))
        sd = _nearest_ohlc_idx(ohlc, t.get("sell_exec_day") or t.get("sell_signal_day"))
        ti = t.get("i", "")
        if bd is not None:
            xi = _ohlc_x_pos(ohlc, bd)
            low = float(ohlc.loc[bd, "Low"])
            px = float(t.get("buy_price") or low)
            label_y = low - pad
            fig.add_shape(
                type="line",
                x0=xi,
                x1=xi,
                y0=low,
                y1=label_y,
                line=dict(color=color_b, width=1, dash="dash"),
                row=1,
                col=1,
            )
            buy_x.append(xi)
            buy_y.append(label_y)
            buy_hover.append(f"买 #{ti} @ {px:.4g}<br>{bd.strftime('%Y-%m-%d')}")
        if sd is not None:
            xi = _ohlc_x_pos(ohlc, sd)
            high = float(ohlc.loc[sd, "High"])
            px = float(t.get("sell_price") or high)
            label_y = high + pad
            fig.add_shape(
                type="line",
                x0=xi,
                x1=xi,
                y0=high,
                y1=label_y,
                line=dict(color=color_s, width=1, dash="dash"),
                row=1,
                col=1,
            )
            sell_x.append(xi)
            sell_y.append(label_y)
            sell_hover.append(f"卖 #{ti} @ {px:.4g}<br>{sd.strftime('%Y-%m-%d')}")

    if buy_x:
        fig.add_trace(
            go.Scatter(
                x=buy_x,
                y=buy_y,
                mode="text",
                name="B 买入",
                text=["B"] * len(buy_x),
                textfont=dict(color=color_b, size=13, family="Arial Black"),
                hovertext=buy_hover,
                hovertemplate="%{hovertext}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if sell_x:
        fig.add_trace(
            go.Scatter(
                x=sell_x,
                y=sell_y,
                mode="text",
                name="S 卖出",
                text=["S"] * len(sell_x),
                textfont=dict(color=color_s, size=13, family="Arial Black"),
                hovertext=sell_hover,
                hovertemplate="%{hovertext}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    fig.update_layout(
        title=title,
        height=560,
        # 默认拖拽平移；滚轮缩放需配合 plotly config scrollZoom
        dragmode="pan",
        xaxis_rangeslider_visible=False,
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h"),
    )
    # 允许 x 轴缩放/平移；y 轴留出 B/S 边距
    y_lo = float(ohlc["Low"].min()) - pad * 2.2
    y_hi = float(ohlc["High"].max()) + pad * 2.2
    tickvals = _kline_tick_vals(len(ohlc))
    fig.update_xaxes(
        type="linear",
        fixedrange=False,
        rangeslider_visible=False,
        tickmode="array",
        tickvals=tickvals,
        ticktext=[x_dates[i] for i in tickvals],
    )
    fig.update_yaxes(title_text="价格", fixedrange=False, range=[y_lo, y_hi], row=1, col=1)
    fig.update_yaxes(title_text="量", fixedrange=False, row=2, col=1)
    fig.update_xaxes(title_text="日期", showticklabels=True, row=2, col=1)
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    return fig


_KLINE_PLOT_CONFIG = {
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    "doubleClick": "reset",
}


def _render_analysis(
    detail_path: Path,
    budget: float,
    ohlc_csv: Path | None,
    range_start: str,
    range_end: str,
    stock: str,
) -> None:
    result = analyze_detail(detail_path, budget=budget)
    trades = result["trades"]
    if range_start or range_end:
        # 仅分析模式可按卖出日再筛
        filtered = filter_trades_by_range(trades, range_start, range_end)
        if filtered != trades and (range_start or range_end):
            # 重算 equity/stats
            from analyze import report_mod

            mod = report_mod()
            trades = filtered
            result["trades"] = trades
            result["stats"] = mod.compute_stats(
                {"tag": "HlBand", "ver": "local", "stock": stock or "?", "period": "1d", "budget": budget},
                trades,
                diag={},
                price_info={"source": "terminal", "terminal_csv": str(detail_path)},
            )
            result["equity"] = mod.equity_curve(trades, budget)

    stats = result["stats"]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("轮次", int(stats.get("n_buy") or 0))
    c2.metric("总盈亏", f"{float(stats.get('sum_pnl') or 0):,.2f}")
    c3.metric("胜率", f"{float(stats.get('win_rate') or 0):.1f}%")
    c4.metric("平均收益%", f"{float(stats.get('avg_ret') or 0):.2f}")
    c5.metric("最大单笔%", f"{float(stats.get('max_win') or 0):.2f}")
    c6.metric("最大亏损%", f"{float(stats.get('max_loss') or 0):.2f}")

    st.caption(f"明细真源：`{detail_path}` · 预算 {budget:,.0f} 元")

    st.plotly_chart(
        _plot_equity(result["equity"], budget, "权益曲线（预算 + 已实现盈亏累计）"),
        use_container_width=True,
    )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(_plot_pnl_hist(trades), use_container_width=True)
    with right:
        win_n = int(stats.get("win_n") or 0)
        loss_n = int(stats.get("loss_n") or 0)
        fig = go.Figure(
            data=[
                go.Bar(
                    x=["盈利", "亏损"],
                    y=[win_n, loss_n],
                    marker_color=["#43a047", "#e53935"],
                    name="笔数",
                )
            ]
        )
        fig.update_layout(
            title="盈亏笔数",
            yaxis_title="笔数",
            height=320,
            margin=dict(l=40, r=20, t=50, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

    if ohlc_csv and ohlc_csv.is_file():
        ohlc = ohlc_from_csv(ohlc_csv, start=range_start, end=range_end, stock=stock)
        st.caption("K 线：滚轮缩放 · 拖拽左右平移 · 双击复位")
        st.plotly_chart(
            _plot_kline(ohlc, trades, f"日线 + 买卖点 · {stock or ohlc_csv.name}"),
            use_container_width=True,
            config=_KLINE_PLOT_CONFIG,
        )
    else:
        st.info("未绑定行情 CSV，跳过 K 线（仅分析明细时可选对应日线）。")

    st.subheader("成交轮次")
    st.dataframe(trades_to_dataframe(trades), use_container_width=True, hide_index=True)

    st.subheader("操作明细（原始）")
    try:
        raw = load_detail_raw(detail_path)
        st.dataframe(raw, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning("无法读取原始明细：%s" % e)


def _render_batch_run(csv_dir: str, *, workers: int = 0, quiet: bool = True) -> None:
    metas = _cached_daily_metas(csv_dir, _daily_dir_fingerprint(csv_dir))
    if not metas:
        st.warning("目录无可用 `*_1d_*.csv`：%s" % csv_dir)
        return
    by_stock = {m["stock"]: m for m in metas}
    stocks = [m["stock"] for m in metas]
    pick_mode = st.radio(
        "标的范围",
        ["全部标的", "筛选标的"],
        horizontal=True,
        key="batch_pick_mode",
    )
    if pick_mode == "全部标的":
        picked = list(metas)
        st.caption("已选 **%s** 只（目录去重后）" % len(picked))
    else:
        q = str(st.text_input("代码过滤", value="", key="batch_stock_filter") or "").strip().upper()
        options = [s for s in stocks if (not q or q in s.upper())]
        selected = st.multiselect(
            "标的",
            options=options,
            default=[],
            format_func=lambda s: "%s  ·  %s–%s  (%s根)"
            % (s, by_stock[s]["start"], by_stock[s]["end"], by_stock[s]["n"]),
            key="batch_stocks",
        )
        picked = [by_stock[s] for s in selected if s in by_stock]
        if options and not picked:
            st.caption("过滤后 %s 只，尚未勾选" % len(options))
    start_d = end_d = None
    run_btn = False
    split_label = "整段区间"
    if not picked:
        st.info("请至少选择一只标的")
    else:
        u0, u1 = union_date_range(picked)
        d0, d1 = ymd_to_date(u0), ymd_to_date(u1)
        c_start, c_end = st.columns(2)
        with c_start:
            start_d = st.date_input("开始时间", value=d0, min_value=d0, max_value=d1, key="bt_batch_start")
        with c_end:
            end_d = st.date_input("结束时间", value=d1, min_value=d0, max_value=d1, key="bt_batch_end")
        if start_d > end_d:
            st.error("开始时间不能晚于结束时间")
        split_label = st.radio(
            "跑批类型",
            ["整段区间", "按自然年分段"],
            horizontal=True,
            key="batch_split",
        )
        if split_label == "按自然年分段":
            st.caption("每年独立账户、年初空仓；暖机仍用 walk 之前的历史 K 线。")
        run_btn = st.button("开始批量回测", type="primary", disabled=start_d > end_d)

    split_mode = "year" if split_label == "按自然年分段" else "range"

    if run_btn and picked and start_d and end_d and start_d <= end_d:
        start_s = _fmt_ymd(start_d)
        end_s = _fmt_ymd(end_d)
        out_dir = THEME / "report"
        bar = st.progress(0.0)
        status = st.empty()

        def on_progress(i: int, n: int, stock: str) -> None:
            bar.progress(0.0 if n <= 0 else min(1.0, float(i) / float(n)))
            if n <= 0:
                return
            unit = "个任务" if split_mode == "year" else "只"
            if i < n:
                status.info("正在回测 **%s**（%s/%s）…" % (stock, i + 1, n))
            else:
                status.success("批量完成 %s %s" % (n, unit))

        try:
            raw = run_batch(
                [Path(m["path"]) for m in picked],
                start=start_s,
                end=end_s,
                out_dir=out_dir,
                on_progress=on_progress,
                workers=int(workers),
                quiet=bool(quiet),
                split=split_mode,
                metas=picked,
            )
            if not raw:
                st.warning("所选区间与行情无交集，未生成任务。")
            else:
                rows = [summarize_batch_row(r) for r in raw]
                write_batch_summary_csv(rows, out_dir / "local_bt_batch_summary.csv")
                if split_mode == "year":
                    write_batch_year_summary_csv(rows, out_dir / "local_bt_batch_year_summary.csv")
                st.session_state["batch_result"] = {
                    "start": start_s,
                    "end": end_s,
                    "rows": rows,
                    "split": split_mode,
                }
                n_ok = sum(1 for r in rows if r.get("ok"))
                extra = ""
                if split_mode == "year":
                    extra = " · 年汇总 `local_bt_batch_year_summary.csv`"
                st.success(
                    "完成 · 成功 %s · 失败 %s · 汇总 `local_bt_batch_summary.csv`%s"
                    % (n_ok, len(rows) - n_ok, extra)
                )
        except Exception:
            st.error("批量回测失败")
            st.code(traceback.format_exc())

    batch = st.session_state.get("batch_result")
    if not batch:
        return
    split_saved = str(batch.get("split") or "range")
    st.divider()
    if split_saved == "year":
        st.subheader("按年汇总")
        st.caption("每年独立账户；胜率 / 平均收益% 按轮次加权。合计盈亏不是组合净值。")
        st.dataframe(
            batch_year_summary_dataframe(batch["rows"]),
            use_container_width=True,
            hide_index=True,
        )
    st.subheader("按标的汇总")
    st.caption("各标的独立账户、独立预算；合计盈亏不是组合净值。")
    st.dataframe(batch_summary_dataframe(batch["rows"]), use_container_width=True, hide_index=True)

    ok_rows = [r for r in batch["rows"] if r.get("ok") and r.get("detail")]
    if not ok_rows:
        st.warning("没有成功的标的，无法查看明细。")
        return

    def _detail_label(r: dict) -> str:
        year = str(r.get("year") or "").strip()
        if split_saved == "year" and year:
            return "%s · %s" % (r.get("stock") or "", year)
        return str(r.get("stock") or "")

    labels = [_detail_label(r) for r in ok_rows]
    pick = st.selectbox("查看标的明细", labels, key="batch_detail_stock")
    row = next(r for r in ok_rows if _detail_label(r) == pick)
    st.divider()
    st.subheader("明细 · %s" % pick)
    ohlc = Path(row["csv"]) if row.get("csv") else None
    _render_analysis(
        Path(row["detail"]),
        budget=float(row.get("budget") or 50000.0),
        ohlc_csv=ohlc if ohlc and ohlc.is_file() else None,
        range_start=str(row.get("walk_start") or batch.get("start") or ""),
        range_end=str(row.get("walk_end") or batch.get("end") or ""),
        stock=str(row.get("stock") or ""),
    )


def _select_display_df(df: pd.DataFrame, *, passed_only: bool = False, score_years: tuple[str, ...] | None = None) -> pd.DataFrame:
    src = df[df["passed"]].copy() if passed_only and "passed" in df.columns else df.copy()
    if src.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["名次"] = src["rank"]
    out["标的"] = src["stock"]
    out["得分"] = pd.to_numeric(src["score"], errors="coerce") * 100.0
    out["建议均线"] = src["ma_type_suggest"]
    out["白名单"] = src["in_book"].map(lambda x: "是" if x else "")
    out["跨年轮次"] = src["n_buy"]
    out["成交年"] = src["n_years_traded"]
    out["盈利年"] = src["n_years_pos"]
    out["稳定性"] = pd.to_numeric(src["stability"], errors="coerce") * 100.0
    out["年等权盈亏"] = src["pnl_year_mean"]
    out["胜率"] = src["win_rate"]
    out["利润因子"] = src["profit_factor"]
    out["策略质量"] = src["quality"]
    out["trail占比"] = pd.to_numeric(src["trail_share"], errors="coerce") * 100.0
    out["最大回撤"] = pd.to_numeric(src["max_dd"], errors="coerce") * 100.0
    out["年化波动"] = pd.to_numeric(src["vol_ann"], errors="coerce") * 100.0
    out["贴线率"] = pd.to_numeric(src["touch_ma20"], errors="coerce") * 100.0
    out["近期"] = src["recent_flag"]
    out["未过原因"] = src["fail_reason"]
    years = score_years or SCORE_YEARS
    for y in years:
        col = "pnl_%s" % y
        if col in src.columns:
            out["盈亏%s" % y] = src[col]
    return out.reset_index(drop=True)


def _plot_year_heatmap(heat: pd.DataFrame, score_years: tuple[str, ...] | None = None) -> go.Figure:
    fig = go.Figure()
    if heat is None or heat.empty:
        fig.add_annotation(text="无过线标的", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=200, margin=dict(l=40, r=20, t=40, b=40))
        return fig
    zdf = heat.copy()
    years = score_years or SCORE_YEARS
    y_cols = ["pnl_%s" % y for y in years]
    rename = {c: c.replace("pnl_", "") for c in y_cols}
    rename["recent_pnl"] = "近期"
    keep = ["stock"] + [c for c in y_cols + ["recent_pnl"] if c in zdf.columns]
    zdf = zdf[keep].set_index("stock")
    zdf = zdf.rename(columns=rename)
    fig.add_trace(
        go.Heatmap(
            z=zdf.values,
            x=list(zdf.columns),
            y=list(zdf.index),
            colorscale="RdYlGn",
            zmid=0,
            colorbar=dict(title="盈亏 (元)"),
            hovertemplate="%{y} · %{x}<br>盈亏 %{z:,.0f} 元<extra></extra>",
        )
    )
    fig.update_layout(
        title="年度盈亏（过线标的；近期不进主分）",
        xaxis_title="区间",
        yaxis_title="标的",
        height=max(280, 22 * len(zdf) + 80),
        margin=dict(l=80, r=20, t=50, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return fig


def _plot_sell_pie(counts: dict) -> go.Figure:
    fig = go.Figure()
    labels = []
    values = []
    for k, v in (counts or {}).items():
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        labels.append(str(k))
        values.append(n)
    if not values:
        fig.add_annotation(text="无卖出信号", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=20))
        return fig
    fig.add_trace(go.Pie(labels=labels, values=values, hole=0.35, name="卖出"))
    fig.update_layout(
        title="卖出原因（分年合计）",
        height=320,
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h"),
    )
    return fig


def _render_select(csv_dir: str, filters: dict) -> None:
    report_dir = str(THEME / "report")
    try:
        scanned = _cached_select_scan(
            report_dir,
            csv_dir,
            report_fingerprint(report_dir),
            csv_dir_fingerprint(csv_dir),
        )
    except Exception:
        st.error("扫描回测报告失败")
        st.code(traceback.format_exc())
        return

    scored = score_universe(scanned, filters=filters)
    df = scored["df"]
    passed = scored["passed"]
    rec = scored["recommend"]
    cov = scored.get("coverage") or {}
    years = tuple(scored.get("score_years") or SCORE_YEARS)
    out_path = THEME / "report" / "local_bt_stock_select.csv"
    try:
        write_select_csv(df, out_path)
    except Exception as e:
        st.warning("写选股 CSV 失败：%s" % e)

    for line in coverage_notes(cov, scanned):
        st.markdown("- " + line)

    n_all = int(cov.get("n_stock") or 0)
    n_pass = 0 if passed is None or passed.empty else len(passed)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("扫描标的", n_all)
    c2.metric("过线", n_pass)
    c3.metric("推荐池", 0 if rec is None or rec.empty else len(rec))
    cut = scored.get("vol_cut")
    c4.metric("波动上限", "-" if cut is None else "%.1f%%" % (float(cut) * 100.0))
    st.caption("产物：`hongli_band/report/local_bt_stock_select.csv` · 不自动改 `BOOK_STOCKS`")

    st.subheader("现白名单对照")
    book_rank = scored.get("book_rank")
    if book_rank is None or book_rank.empty:
        st.info("现白名单四只不在本次扫描结果里（可能还没跑过分年回测）。")
    else:
        st.dataframe(_select_display_df(book_rank, score_years=years), use_container_width=True, hide_index=True)

    st.subheader("推荐池 Top %s" % int(filters.get("top_n") or 6))
    if rec is None or rec.empty:
        st.warning("没有过线标的。放宽侧栏阈值，或先补齐分年批量回测。")
    else:
        st.dataframe(_select_display_df(rec, score_years=years), use_container_width=True, hide_index=True)
        st.caption("`ma_type` 为启发式（贴线+低波→EMA，否则 SMA）；白名单已有配置优先。")
        st.code(format_book_snippet(rec), language="python")

    st.subheader("打分总表")
    view = st.radio("显示", ["仅过线", "全部（含未过）"], horizontal=True, key="select_view")
    table = _select_display_df(df, passed_only=(view == "仅过线"), score_years=years)
    if table.empty:
        st.info("无行可显示")
    else:
        st.dataframe(table, use_container_width=True, hide_index=True)

    st.subheader("年度盈亏热力")
    heat = scored.get("heatmap")
    if heat is not None and not heat.empty and len(heat) > 40:
        heat = heat.head(40)
        st.caption("过线标的较多，热力只画得分最高的 40 只。")
    st.plotly_chart(_plot_year_heatmap(heat, score_years=years), use_container_width=True)

    details = scored.get("details") or {}
    names = [] if passed is None or passed.empty else passed["stock"].tolist()
    if names:
        st.subheader("标的展开")
        pick = st.selectbox("过线标的", names, key="select_detail_stock")
        one = df[df["stock"] == pick]
        if not one.empty:
            st.dataframe(_select_display_df(one, score_years=years), use_container_width=True, hide_index=True)
        info = details.get(pick) or {}
        year_rows = []
        years = info.get("years") or {}
        for y in years:
            k = years.get(y)
            if not k:
                year_rows.append({"年份": y, "状态": "缺文件", "轮次": None, "总盈亏": None, "胜率": None})
                continue
            year_rows.append(
                {
                    "年份": y,
                    "状态": "有",
                    "轮次": k.get("n_buy"),
                    "总盈亏": k.get("sum_pnl"),
                    "胜率": k.get("win_rate"),
                    "平均收益%": k.get("avg_ret"),
                    "利润因子": k.get("profit_factor"),
                    "最大回撤": None if k.get("max_dd") is None else float(k["max_dd"]) * 100.0,
                    "trail占比": None
                    if not k.get("sell")
                    else 100.0
                    * float(k["sell"].get("trail_stop") or 0)
                    / max(1, sum(int(v) for v in k["sell"].values())),
                }
            )
        recent = info.get("recent")
        if recent:
            year_rows.append(
                {
                    "年份": "近期",
                    "状态": "有",
                    "轮次": recent.get("n_buy"),
                    "总盈亏": recent.get("sum_pnl"),
                    "胜率": recent.get("win_rate"),
                    "平均收益%": recent.get("avg_ret"),
                    "利润因子": recent.get("profit_factor"),
                    "最大回撤": None
                    if recent.get("max_dd") is None
                    else float(recent["max_dd"]) * 100.0,
                    "trail占比": None,
                }
            )
        left, right = st.columns([1.4, 1])
        with left:
            st.dataframe(pd.DataFrame(year_rows), use_container_width=True, hide_index=True)
        with right:
            st.plotly_chart(_plot_sell_pie(info.get("sell") or {}), use_container_width=True)
        st.caption("看 K 线 / 成交明细请切到「仅分析已有明细」。")


# ---------- sidebar / controls ----------
mode = st.radio("模式", ["跑本地回测", "仅分析已有明细", "选股方案"], horizontal=True)
scope = "单标的"
if mode == "跑本地回测":
    scope = st.radio("范围", ["单标的", "批量（按标的汇总）"], horizontal=True)

with st.sidebar:
    st.header("参数")
    csv_dir = st.text_input("行情目录", value=str(DEFAULT_CSV_DIR))
    daily_files = list_daily_csvs(csv_dir)
    daily_labels = [p.name for p in daily_files]
    uploaded = None
    quiet = True
    workers = 0
    if mode == "跑本地回测" and scope == "单标的":
        uploaded = st.file_uploader("或上传日线 CSV", type=["csv"])
    if mode == "跑本地回测":
        quiet = not st.checkbox("详细日志（慢）", value=False, key="bt_verbose")
        if scope == "批量（按标的汇总）":
            workers = int(
                st.number_input("进程数（0=自动）", min_value=0, max_value=16, value=0, step=1, key="bt_workers")
            )
    select_filters = dict(DEFAULT_FILTERS)
    if mode == "选股方案":
        st.subheader("硬过滤")
        select_filters["min_n_buy"] = int(
            st.number_input("最少跨年轮次", min_value=0, max_value=50, value=int(DEFAULT_FILTERS["min_n_buy"]), step=1)
        )
        select_filters["min_years_traded"] = int(
            st.number_input("最少成交年数", min_value=1, max_value=5, value=int(DEFAULT_FILTERS["min_years_traded"]), step=1)
        )
        select_filters["min_pos_years"] = int(
            st.number_input("最少盈利年数", min_value=0, max_value=5, value=int(DEFAULT_FILTERS["min_pos_years"]), step=1)
        )
        select_filters["min_pos_ratio"] = float(
            st.slider("或盈利年占比 ≥", min_value=0.0, max_value=1.0, value=float(DEFAULT_FILTERS["min_pos_ratio"]), step=0.05)
        )
        select_filters["max_win_pnl_share"] = float(
            st.slider("单笔盈利占毛利上限", min_value=0.3, max_value=1.0, value=float(DEFAULT_FILTERS["max_win_pnl_share"]), step=0.05)
        )
        select_filters["vol_drop_top"] = float(
            st.slider("剔除最高波动分位", min_value=0.0, max_value=0.3, value=float(DEFAULT_FILTERS["vol_drop_top"]), step=0.05)
        )
        select_filters["top_n"] = int(
            st.slider("推荐池 N", min_value=4, max_value=9, value=int(DEFAULT_FILTERS["top_n"]), step=1)
        )
        if st.button("刷新缓存"):
            _cached_select_scan.clear()
            st.rerun()

if mode == "选股方案":
    _render_select(csv_dir, select_filters)
elif mode == "跑本地回测" and scope == "批量（按标的汇总）":
    _render_batch_run(csv_dir, workers=workers, quiet=quiet)
elif mode == "跑本地回测":
    col_a, col_b = st.columns([2, 1])
    with col_a:
        if uploaded is not None:
            tmp = HERE / "_upload_daily.csv"
            tmp.write_bytes(uploaded.getvalue())
            selected_csv = tmp
            st.success(f"已使用上传文件：{uploaded.name}")
        elif daily_labels:
            pick = st.selectbox("数据源（KlineDump 日线）", daily_labels, index=0)
            selected_csv = Path(csv_dir) / pick
        else:
            selected_csv = None
            st.warning(f"目录无 `*_1d_*.csv`：{csv_dir}")

    meta = None
    if selected_csv and selected_csv.is_file():
        try:
            meta = csv_date_range(selected_csv)
        except Exception as e:
            st.error(f"读取行情失败：{e}")
            meta = None

    if meta:
        d0 = ymd_to_date(meta["start"])
        d1 = ymd_to_date(meta["end"])
        st.caption(f"标的 **{meta['stock']}** · {meta['n']} 根日线 · {meta['start']}–{meta['end']}")
        c_start, c_end = st.columns(2)
        with c_start:
            start_d = st.date_input("开始时间", value=d0, min_value=d0, max_value=d1, key="bt_start")
        with c_end:
            end_d = st.date_input("结束时间", value=d1, min_value=d0, max_value=d1, key="bt_end")
        if start_d > end_d:
            st.error("开始时间不能晚于结束时间")
        run_btn = st.button("开始回测", type="primary", disabled=start_d > end_d)
    else:
        start_d = end_d = None
        run_btn = False

    if run_btn and selected_csv and meta and start_d and end_d:
        start_s = _fmt_ymd(start_d)
        end_s = _fmt_ymd(end_d)
        out_dir = THEME / "report"
        with st.spinner(f"回测 {meta['stock']} {start_s}–{end_s} …"):
            try:
                log_path = run_backtest(
                    selected_csv,
                    start=start_s,
                    end=end_s,
                    stock=meta["stock"],
                    out_dir=out_dir,
                    quiet=bool(quiet),
                )
                detail = trades_csv_path(log_path)
                budget = parse_budget_from_log(log_path)
                st.session_state["last_result"] = {
                    "log": str(log_path),
                    "detail": str(detail),
                    "budget": budget,
                    "ohlc_csv": str(selected_csv),
                    "stock": meta["stock"],
                    "start": start_s,
                    "end": end_s,
                }
                st.success(f"完成 · log `{log_path.name}` · 明细 `{detail.name}`")
            except Exception:
                st.error("回测失败")
                st.code(traceback.format_exc())

    last = st.session_state.get("last_result")
    if last:
        st.divider()
        _render_analysis(
            Path(last["detail"]),
            budget=float(last["budget"]),
            ohlc_csv=Path(last["ohlc_csv"]) if last.get("ohlc_csv") else None,
            range_start=last.get("start") or "",
            range_end=last.get("end") or "",
            stock=last.get("stock") or "",
        )

else:
    details = list_detail_csvs()
    labels = [str(p.relative_to(REPO)) if str(p).startswith(str(REPO)) else p.name for p in details]
    if not labels:
        st.warning("未找到操作明细（hongli_band/回测记录 或 report/*操作明细*）")
    else:
        idx = st.selectbox("已有明细", range(len(labels)), format_func=lambda i: labels[i])
        detail_path = details[idx]
        # 尝试匹配同代码日线
        code_guess = detail_path.stem.split("_")[0].split("-")[0]
        ohlc_match = None
        for p in list_daily_csvs(csv_dir):
            if code_guess and code_guess in p.name:
                ohlc_match = p
                break
        ohlc_opt = st.selectbox(
            "关联日线（可选，画 K 线）",
            ["（不关联）"] + [p.name for p in list_daily_csvs(csv_dir)],
            index=(1 + [p.name for p in list_daily_csvs(csv_dir)].index(ohlc_match.name))
            if ohlc_match
            else 0,
        )
        ohlc_csv = None
        stock = ""
        d0 = d1 = None
        if ohlc_opt != "（不关联）":
            ohlc_csv = Path(csv_dir) / ohlc_opt
            try:
                meta = csv_date_range(ohlc_csv)
                stock = meta["stock"]
                d0, d1 = ymd_to_date(meta["start"]), ymd_to_date(meta["end"])
            except Exception as e:
                st.warning(f"日线读取失败：{e}")
                ohlc_csv = None

        # 明细自身时间范围
        try:
            raw = load_detail_raw(detail_path)
            time_col = None
            for c in raw.columns:
                if str(c).strip() in ("操作时间", "成交时间", "时间"):
                    time_col = c
                    break
            if time_col is None and raw.shape[1] >= 6:
                time_col = raw.columns[5]
            days = []
            if time_col is not None:
                for v in raw[time_col]:
                    try:
                        days.append(date_to_ymd(str(v)))
                    except Exception:
                        pass
            days = [d for d in days if len(d) == 8]
            if days:
                d0 = d0 or ymd_to_date(min(days))
                d1 = d1 or ymd_to_date(max(days))
        except Exception:
            pass

        if d0 and d1:
            c_start, c_end = st.columns(2)
            with c_start:
                start_d = st.date_input("开始时间", value=d0, key="an_start")
            with c_end:
                end_d = st.date_input("结束时间", value=d1, key="an_end")
            start_s, end_s = _fmt_ymd(start_d), _fmt_ymd(end_d)
        else:
            start_s = end_s = ""
            st.caption("无法推断明细时间范围，将分析全部记录")

        budget = st.number_input("预算（元）", min_value=1000.0, value=50000.0, step=1000.0)
        if st.button("加载分析", type="primary"):
            st.session_state["analyze_only"] = {
                "detail": str(detail_path),
                "budget": float(budget),
                "ohlc_csv": str(ohlc_csv) if ohlc_csv else "",
                "stock": stock,
                "start": start_s,
                "end": end_s,
            }

        ao = st.session_state.get("analyze_only")
        if ao:
            st.divider()
            _render_analysis(
                Path(ao["detail"]),
                budget=float(ao["budget"]),
                ohlc_csv=Path(ao["ohlc_csv"]) if ao.get("ohlc_csv") else None,
                range_start=ao.get("start") or "",
                range_end=ao.get("end") or "",
                stock=ao.get("stock") or "",
            )
