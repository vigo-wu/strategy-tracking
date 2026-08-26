# coding: utf-8
"""HlBand 本地回测可视化（Streamlit）。

启动:
  streamlit run hongli_band/scripts/local_bt/app.py
  或: python hongli_band/local_bt_ui.py
"""
from __future__ import annotations

import io
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
    csv_date_range,
    date_to_ymd,
    filter_trades_by_range,
    list_daily_csvs,
    list_detail_csvs,
    load_detail_raw,
    ohlc_from_csv,
    parse_budget_from_log,
    trades_to_dataframe,
    ymd_to_date,
)
from run import run_backtest  # noqa: E402
from trades_csv import trades_csv_path  # noqa: E402

import streamlit as st  # noqa: E402


st.set_page_config(page_title="HlBand 本地回测", layout="wide")
st.title("HlBand 本地回测可视化")


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

    # 保证 x 轴与标记用同一套日期索引
    ohlc = ohlc.copy()
    ohlc.index = pd.DatetimeIndex(pd.to_datetime(ohlc.index).normalize())

    fig.add_trace(
        go.Candlestick(
            x=ohlc.index,
            open=ohlc["Open"],
            high=ohlc["High"],
            low=ohlc["Low"],
            close=ohlc["Close"],
            name="日线",
            increasing_line_color="#e53935",
            decreasing_line_color="#43a047",
        ),
        row=1,
        col=1,
    )
    if "Volume" in ohlc.columns:
        fig.add_trace(
            go.Bar(x=ohlc.index, y=ohlc["Volume"], name="成交量", marker_color="#90a4ae"),
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
            low = float(ohlc.loc[bd, "Low"])
            px = float(t.get("buy_price") or low)
            label_y = low - pad
            fig.add_shape(
                type="line",
                x0=bd,
                x1=bd,
                y0=low,
                y1=label_y,
                line=dict(color=color_b, width=1, dash="dash"),
                row=1,
                col=1,
            )
            buy_x.append(bd)
            buy_y.append(label_y)
            buy_hover.append(f"买 #{ti} @ {px:.4g}<br>{bd.strftime('%Y-%m-%d')}")
        if sd is not None:
            high = float(ohlc.loc[sd, "High"])
            px = float(t.get("sell_price") or high)
            label_y = high + pad
            fig.add_shape(
                type="line",
                x0=sd,
                x1=sd,
                y0=high,
                y1=label_y,
                line=dict(color=color_s, width=1, dash="dash"),
                row=1,
                col=1,
            )
            sell_x.append(sd)
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
    fig.update_xaxes(fixedrange=False, rangeslider_visible=False)
    fig.update_yaxes(title_text="价格", fixedrange=False, range=[y_lo, y_hi], row=1, col=1)
    fig.update_yaxes(title_text="量", fixedrange=False, row=2, col=1)
    fig.update_xaxes(title_text="日期", row=2, col=1)
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


# ---------- sidebar / controls ----------
mode = st.radio("模式", ["跑本地回测", "仅分析已有明细"], horizontal=True)

with st.sidebar:
    st.header("参数")
    csv_dir = st.text_input("行情目录", value=str(DEFAULT_CSV_DIR))
    daily_files = list_daily_csvs(csv_dir)
    daily_labels = [p.name for p in daily_files]
    uploaded = st.file_uploader("或上传日线 CSV", type=["csv"])

if mode == "跑本地回测":
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
        log_buf = io.StringIO()
        with st.spinner(f"回测 {meta['stock']} {start_s}–{end_s} …"):
            try:
                # 捕获 print
                old_out, old_err = sys.stdout, sys.stderr

                class _Cap:
                    def __init__(self, primary, buf):
                        self.primary = primary
                        self.buf = buf

                    def write(self, data):
                        self.primary.write(data)
                        self.buf.write(data)
                        return len(data) if data else 0

                    def flush(self):
                        self.primary.flush()

                sys.stdout = _Cap(old_out, log_buf)
                sys.stderr = _Cap(old_err, log_buf)
                try:
                    log_path = run_backtest(
                        selected_csv,
                        start=start_s,
                        end=end_s,
                        stock=meta["stock"],
                        out_dir=out_dir,
                    )
                finally:
                    sys.stdout, sys.stderr = old_out, old_err
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
