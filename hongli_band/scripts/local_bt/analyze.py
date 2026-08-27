# coding: utf-8
"""本地回测操作明细 → 轮次 / 权益 / KPI；日线 CSV → OHLC。"""
from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
REPORT_PY = (
    REPO / ".cursor" / "skills" / "qmt-backtest-report" / "scripts" / "generate_report.py"
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from market_csv import compact_day, load_daily_csv, peek_daily_csv_meta  # noqa: E402


def _load_report_mod():
    spec = importlib.util.spec_from_file_location("qmt_generate_report", REPORT_PY)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % REPORT_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_REPORT = None


def report_mod():
    global _REPORT
    if _REPORT is None:
        _REPORT = _load_report_mod()
    return _REPORT


def ymd_to_date(s: str) -> date:
    d = compact_day(s)
    if len(d) != 8:
        raise ValueError("bad day: %s" % s)
    return datetime.strptime(d, "%Y%m%d").date()


def date_to_ymd(d: date | datetime | str) -> str:
    if isinstance(d, str):
        return compact_day(d)
    if isinstance(d, datetime):
        return d.strftime("%Y%m%d")
    return d.strftime("%Y%m%d")


def list_daily_csvs(data_dir: str | Path | None = None) -> list[Path]:
    root = Path(data_dir) if data_dir else (REPO / "tools" / "csv")
    if not root.is_dir():
        return []
    return sorted(root.glob("*_1d_*.csv"))


def _prefer_daily_meta(cur: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """同代码多份日线：结束日更新、根数更多、路径名字典序更大者优先。"""
    if other["end"] != cur["end"]:
        return other if other["end"] > cur["end"] else cur
    n_o, n_c = int(other.get("n") or 0), int(cur.get("n") or 0)
    if n_o != n_c:
        return other if n_o > n_c else cur
    p_o, p_c = str(other.get("path") or ""), str(cur.get("path") or "")
    return other if p_o > p_c else cur


def daily_csvs_by_stock(data_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """行情目录按标的去重，每只保留一份最新日线。"""
    by_stock: dict[str, dict[str, Any]] = {}
    for path in list_daily_csvs(data_dir):
        try:
            meta = peek_daily_csv_meta(path)
        except Exception:
            continue
        stock = str(meta.get("stock") or "").strip().upper()
        if not stock:
            continue
        prev = by_stock.get(stock)
        by_stock[stock] = meta if prev is None else _prefer_daily_meta(prev, meta)
    return [by_stock[k] for k in sorted(by_stock)]


def union_date_range(metas: list[dict[str, Any]]) -> tuple[str, str]:
    starts = [compact_day(str(m.get("start") or "")) for m in metas]
    ends = [compact_day(str(m.get("end") or "")) for m in metas]
    starts = [s for s in starts if len(s) == 8]
    ends = [e for e in ends if len(e) == 8]
    if not starts or not ends:
        raise ValueError("empty date range")
    return min(starts), max(ends)


def iter_year_windows(start: str, end: str) -> list[tuple[str, str, str]]:
    """闭区间 [start, end] 按自然年切开。返回 [(year, y_start, y_end), ...]。"""
    s = compact_day(start)
    e = compact_day(end)
    if len(s) != 8 or len(e) != 8:
        raise ValueError("bad range: %s %s" % (start, end))
    if s > e:
        raise ValueError("start after end: %s %s" % (s, e))
    y0 = int(s[:4])
    y1 = int(e[:4])
    out: list[tuple[str, str, str]] = []
    for y in range(y0, y1 + 1):
        ys = s if y == y0 else "%04d0101" % y
        ye = e if y == y1 else "%04d1231" % y
        if ys > ye:
            continue
        out.append((str(y), ys, ye))
    return out


def _overlap_yyyymmdd(a0: str, a1: str, b0: str, b1: str) -> tuple[str, str] | None:
    lo = max(a0, b0)
    hi = min(a1, b1)
    if lo <= hi:
        return lo, hi
    return None


def build_year_jobs(
    metas: list[dict[str, Any]],
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    """标的 × 年；与行情无交集的年跳过。"""
    jobs: list[dict[str, Any]] = []
    for year, ys, ye in iter_year_windows(start, end):
        for meta in metas:
            ms = compact_day(str(meta.get("start") or ""))
            me = compact_day(str(meta.get("end") or ""))
            if len(ms) != 8 or len(me) != 8:
                continue
            ov = _overlap_yyyymmdd(ys, ye, ms, me)
            if ov is None:
                continue
            path = str(meta.get("path") or "")
            if not path:
                continue
            jobs.append(
                {
                    "csv": path,
                    "stock": str(meta.get("stock") or "").strip().upper(),
                    "year": year,
                    "start": ov[0],
                    "end": ov[1],
                }
            )
    return jobs


def list_detail_csvs() -> list[Path]:
    """已有操作明细：回测记录 + report 下 *_操作明细.csv。"""
    out: list[Path] = []
    hist = THEME / "回测记录"
    if hist.is_dir():
        out.extend(sorted(hist.glob("*.csv")))
    report = THEME / "report"
    if report.is_dir():
        out.extend(sorted(report.glob("*操作明细*.csv")))
        out.extend(sorted(report.glob("*_trades.csv")))
    # 去重保序
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(p)
    return uniq


def csv_date_range(csv_path: str | Path, stock: str = "") -> dict[str, Any]:
    code, bars = load_daily_csv(csv_path, stock=stock)
    if not bars:
        raise ValueError("empty bars: %s" % csv_path)
    return {
        "stock": code,
        "start": bars[0].day,
        "end": bars[-1].day,
        "n": len(bars),
        "path": str(Path(csv_path).resolve()),
    }


def ohlc_from_csv(
    csv_path: str | Path,
    start: str = "",
    end: str = "",
    stock: str = "",
) -> pd.DataFrame:
    code, bars = load_daily_csv(csv_path, stock=stock)
    start_d = compact_day(start)
    end_d = compact_day(end)
    rows = []
    for b in bars:
        if start_d and b.day < start_d:
            continue
        if end_d and b.day > end_d:
            continue
        rows.append(
            {
                "Date": pd.Timestamp(b.day),
                "Open": b.open,
                "High": b.high,
                "Low": b.low,
                "Close": b.close,
                "Volume": b.volume,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.set_index("Date").sort_index()


def _normalize_trades(rounds: list[dict]) -> list[dict]:
    trades = []
    for i, r in enumerate(rounds, 1):
        t = dict(r)
        t.setdefault("i", i)
        t.setdefault("buy_signal", "-")
        t.setdefault("sell_signal", "-")
        t.setdefault("buy_label", t.get("buy_signal", "-"))
        t.setdefault("sell_label", t.get("sell_signal", "-"))
        t.setdefault("buy_signal_day", t.get("buy_open_day"))
        t.setdefault("sell_signal_day", t.get("sell_exec_day"))
        if "hold_calendar_days" not in t:
            try:
                b = datetime.strptime(str(t["buy_open_day"])[:8], "%Y%m%d")
                s = datetime.strptime(str(t["sell_exec_day"])[:8], "%Y%m%d")
                t["hold_calendar_days"] = (s - b).days
            except Exception:
                t["hold_calendar_days"] = None
        trades.append(t)
    return trades


def parse_budget_from_log(log_path: str | Path | None, default: float = 50000.0) -> float:
    if not log_path:
        return float(default)
    p = Path(log_path)
    if not p.is_file():
        return float(default)
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"budget=\s*([0-9.]+)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return float(default)


def load_detail_raw(path: str | Path) -> pd.DataFrame:
    mod = report_mod()
    return mod._read_csv_auto(Path(path))


def analyze_detail(
    detail_path: str | Path,
    budget: float = 50000.0,
    meta: dict | None = None,
) -> dict[str, Any]:
    """操作明细 → trades / equity / stats。"""
    mod = report_mod()
    path = Path(detail_path)
    rounds = mod.parse_terminal_rounds(path)
    trades = _normalize_trades(rounds)
    meta_d = meta or {
        "tag": "HlBand",
        "ver": "local",
        "stock": "?",
        "period": "1d",
        "budget": float(budget),
    }
    if "budget" not in meta_d:
        meta_d["budget"] = float(budget)
    stats = mod.compute_stats(meta_d, trades, diag={}, price_info={"source": "terminal", "terminal_csv": str(path)})
    eq = mod.equity_curve(trades, float(budget))
    return {
        "path": str(path.resolve()),
        "trades": trades,
        "stats": stats,
        "equity": eq,
        "budget": float(budget),
        "sum_pnl_detail": float(stats.get("sum_pnl") or 0.0),
    }


def filter_trades_by_range(
    trades: list[dict],
    start: str = "",
    end: str = "",
) -> list[dict]:
    start_d = compact_day(start)
    end_d = compact_day(end)
    out = []
    for t in trades:
        d = compact_day(str(t.get("sell_exec_day") or t.get("buy_open_day") or ""))
        if not d:
            continue
        if start_d and d < start_d:
            continue
        if end_d and d > end_d:
            continue
        out.append(t)
    return _normalize_trades(out)


def trades_to_dataframe(trades: list[dict]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            columns=[
                "i",
                "buy_open_day",
                "sell_exec_day",
                "buy_price",
                "sell_price",
                "shares",
                "pnl",
                "ret_pct",
                "hold_calendar_days",
            ]
        )
    cols = [
        "i",
        "buy_open_day",
        "sell_exec_day",
        "buy_price",
        "sell_price",
        "shares",
        "cost",
        "pnl",
        "ret_pct",
        "hold_calendar_days",
        "buy_signal",
        "sell_signal",
    ]
    rows = [{c: t.get(c) for c in cols} for t in trades]
    return pd.DataFrame(rows)


def summarize_detail(
    detail_path: str | Path,
    budget: float = 50000.0,
    stock: str = "",
) -> dict[str, Any]:
    """操作明细 → 汇总表一行用的 KPI。"""
    result = analyze_detail(
        detail_path,
        budget=budget,
        meta={
            "tag": "HlBand",
            "ver": "local",
            "stock": stock or "?",
            "period": "1d",
            "budget": float(budget),
        },
    )
    stats = result["stats"] or {}
    return {
        "n_buy": int(stats.get("n_buy") or 0),
        "sum_pnl": float(stats.get("sum_pnl") or 0.0),
        "win_rate": float(stats.get("win_rate") or 0.0),
        "avg_ret": float(stats.get("avg_ret") or 0.0),
        "max_win": float(stats.get("max_win") or 0.0),
        "max_loss": float(stats.get("max_loss") or 0.0),
    }


def summarize_batch_row(row: dict[str, Any]) -> dict[str, Any]:
    """把 run_batch 一行补上 KPI / 中文状态。"""
    out = dict(row)
    if not out.get("ok"):
        out["status"] = "失败"
        out.setdefault("n_buy", None)
        out.setdefault("sum_pnl", None)
        out.setdefault("win_rate", None)
        out.setdefault("avg_ret", None)
        out.setdefault("max_win", None)
        out.setdefault("max_loss", None)
        return out
    detail = out.get("detail") or ""
    try:
        kpi = summarize_detail(
            detail,
            budget=float(out.get("budget") or 50000.0),
            stock=str(out.get("stock") or ""),
        )
        out.update(kpi)
        out["status"] = "成功"
    except Exception as e:
        out["ok"] = False
        out["status"] = "失败"
        out["error"] = "analyze: %s" % e
        out.setdefault("n_buy", None)
        out.setdefault("sum_pnl", None)
        out.setdefault("win_rate", None)
        out.setdefault("avg_ret", None)
        out.setdefault("max_win", None)
        out.setdefault("max_loss", None)
    return out


def batch_summary_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    recs = []
    has_year = any(str(r.get("year") or "").strip() for r in rows)
    for r in rows:
        walk_s = compact_day(str(r.get("walk_start") or ""))
        walk_e = compact_day(str(r.get("walk_end") or ""))
        walk = ""
        if walk_s or walk_e:
            walk = "%s–%s" % (walk_s or "?", walk_e or "?")
        rec: dict[str, Any] = {"标的": r.get("stock") or ""}
        if has_year:
            rec["年份"] = str(r.get("year") or "")
        rec.update(
            {
                "状态": r.get("status") or ("成功" if r.get("ok") else "失败"),
                "walk 区间": walk,
                "轮次": r.get("n_buy"),
                "总盈亏": r.get("sum_pnl"),
                "胜率": r.get("win_rate"),
                "平均收益%": r.get("avg_ret"),
                "最大单笔%": r.get("max_win"),
                "最大亏损%": r.get("max_loss"),
                "说明": r.get("error") or "",
            }
        )
        recs.append(rec)
    cols = [
        "标的",
        "状态",
        "walk 区间",
        "轮次",
        "总盈亏",
        "胜率",
        "平均收益%",
        "最大单笔%",
        "最大亏损%",
        "说明",
    ]
    if has_year:
        cols = ["标的", "年份"] + [c for c in cols if c != "标的"]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("轮次",):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("总盈亏", "胜率", "平均收益%", "最大单笔%", "最大亏损%"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def summarize_batch_by_year(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按年汇总：胜率 / 平均收益% 按轮次加权。"""
    by_year: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        y = str(r.get("year") or "").strip()
        if not y:
            walk = compact_day(str(r.get("walk_start") or ""))
            y = walk[:4] if len(walk) >= 4 else ""
        if not y:
            y = "?"
        by_year.setdefault(y, []).append(r)
    out: list[dict[str, Any]] = []
    for y in sorted(by_year):
        xs = by_year[y]
        n_ok = sum(1 for r in xs if r.get("ok"))
        n_buy = 0.0
        sum_pnl = 0.0
        win_n = 0.0
        ret_w = 0.0
        max_win: float | None = None
        max_loss: float | None = None
        for r in xs:
            if not r.get("ok"):
                continue
            nb = float(r.get("n_buy") or 0)
            n_buy += nb
            sum_pnl += float(r.get("sum_pnl") or 0)
            win_n += float(r.get("win_rate") or 0) / 100.0 * nb
            ret_w += float(r.get("avg_ret") or 0) * nb
            mw = r.get("max_win")
            ml = r.get("max_loss")
            if mw is not None and mw != "":
                fv = float(mw)
                max_win = fv if max_win is None else max(max_win, fv)
            if ml is not None and ml != "":
                fv = float(ml)
                max_loss = fv if max_loss is None else min(max_loss, fv)
        out.append(
            {
                "year": y,
                "n_stock": len(xs),
                "n_ok": n_ok,
                "n_buy": int(n_buy) if n_buy == int(n_buy) else n_buy,
                "sum_pnl": sum_pnl if n_ok else None,
                "win_rate": (100.0 * win_n / n_buy) if n_buy else None,
                "avg_ret": (ret_w / n_buy) if n_buy else None,
                "max_win": max_win,
                "max_loss": max_loss,
            }
        )
    return out


def batch_year_summary_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    recs = []
    for r in summarize_batch_by_year(rows):
        recs.append(
            {
                "年份": r.get("year") or "",
                "标的数": r.get("n_stock"),
                "成功数": r.get("n_ok"),
                "轮次": r.get("n_buy"),
                "总盈亏": r.get("sum_pnl"),
                "胜率": r.get("win_rate"),
                "平均收益%": r.get("avg_ret"),
                "最大单笔%": r.get("max_win"),
                "最大亏损%": r.get("max_loss"),
            }
        )
    cols = [
        "年份",
        "标的数",
        "成功数",
        "轮次",
        "总盈亏",
        "胜率",
        "平均收益%",
        "最大单笔%",
        "最大亏损%",
    ]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("标的数", "成功数", "轮次"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("总盈亏", "胜率", "平均收益%", "最大单笔%", "最大亏损%"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def write_batch_summary_csv(rows: list[dict[str, Any]], path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "stock",
        "year",
        "ok",
        "status",
        "walk_start",
        "walk_end",
        "n_bars",
        "n_buy",
        "sum_pnl",
        "win_rate",
        "avg_ret",
        "max_win",
        "max_loss",
        "budget",
        "error",
        "csv",
        "log",
        "detail",
    ]
    recs = [{k: r.get(k) for k in fields} for r in rows]
    pd.DataFrame(recs, columns=fields).to_csv(dest, index=False, encoding="utf-8-sig")
    return dest


def write_batch_year_summary_csv(rows: list[dict[str, Any]], path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "year",
        "n_stock",
        "n_ok",
        "n_buy",
        "sum_pnl",
        "win_rate",
        "avg_ret",
        "max_win",
        "max_loss",
    ]
    recs = [{k: r.get(k) for k in fields} for r in summarize_batch_by_year(rows)]
    pd.DataFrame(recs, columns=fields).to_csv(dest, index=False, encoding="utf-8-sig")
    return dest
