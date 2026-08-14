# coding: utf-8
"""从 MiniQMT xtdata 落盘 ONR CSV（非交易）。

需要：CPython 3.10/3.11（xtquant 无 3.14 wheel）+ 已登录的 MiniQMT。
默认把 D:\\service\\GJQMT\\bin.x64\\Lib\\site-packages 加进 sys.path。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from onr_strategy.backtest.compact import compact_from_minutes, sparse_minutes
from onr_strategy.backtest.config import OnrConfig
from onr_strategy.backtest.data import add_hhmm, is_bj

DEFAULT_XT_SITE = Path(r"D:\service\GJQMT\bin.x64\Lib\site-packages")
INDEX_CODES = ("000001.SH", "399006.SZ")
KLINE_FIELDS = ["time", "open", "high", "low", "close", "volume", "amount"]
SECTORS = ("沪深A股", "上证A股", "深证A股")


def _log(msg: str) -> None:
    print(msg, flush=True)


def ensure_xtquant(site: Optional[str] = None):
    extra = Path(site) if site else DEFAULT_XT_SITE
    if extra.is_dir() and str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
    try:
        from xtquant import xtdata  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "无法导入 xtquant。请用 CPython 3.10 或 3.11，且 MiniQMT 已启动。\n"
            "当前解释器: %s\n"
            "可设 --xt-site 指向 ...\\bin.x64\\Lib\\site-packages\n"
            "原因: %s" % (sys.version.split()[0], exc)
        )
    return xtdata


def is_ashare(symbol: str) -> bool:
    if is_bj(symbol):
        return False
    code, _, mkt = symbol.partition(".")
    if mkt not in ("SH", "SZ") or not code.isdigit() or len(code) != 6:
        return False
    n = int(code)
    if mkt == "SH":
        return 600000 <= n <= 605999 or 688000 <= n <= 689999
    return n <= 3999 or 300000 <= n <= 301999


def list_symbols(xtdata, extra: Sequence[str] = ()) -> List[str]:
    found: List[str] = []
    for name in SECTORS:
        try:
            chunk = xtdata.get_stock_list_in_sector(name) or []
        except Exception as exc:
            _log("sector skip %s: %s" % (name, exc))
            continue
        found.extend(chunk)
    out = []
    seen = set()
    for sym in list(found) + list(extra):
        if not sym or sym in seen:
            continue
        if not is_ashare(sym):
            continue
        seen.add(sym)
        out.append(sym)
    return sorted(out)


def _parse_open_date(val) -> Optional[date]:
    if val is None or val == "" or val == 0 or val == "0":
        return None
    text = str(val).split(".")[0]
    if len(text) < 8:
        return None
    try:
        return datetime.strptime(text[:8], "%Y%m%d").date()
    except ValueError:
        return None


def load_meta(xtdata, symbols: Sequence[str]) -> pd.DataFrame:
    rows = []
    for i, sym in enumerate(symbols):
        if i and i % 500 == 0:
            _log("meta %d/%d" % (i, len(symbols)))
        try:
            det = xtdata.get_instrument_detail(sym) or {}
        except Exception:
            det = {}
        name = str(det.get("InstrumentName") or "")
        rows.append(
            {
                "symbol": sym,
                "name": name,
                "list_date": _parse_open_date(det.get("OpenDate")),
                "is_st": ("ST" in name.upper()) or ("退" in name),
                "sw2": "",
                "exchange": sym.split(".")[-1],
                "float_volume": float(det.get("FloatVolume") or 0),
            }
        )
    return pd.DataFrame(rows)


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def parse_times(values) -> pd.DatetimeIndex:
    s = pd.Series(list(values))
    if s.empty:
        return pd.DatetimeIndex([])
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s)
    text = s.astype(str).str.split(".").str[0]
    nlen = int(text.str.len().max() or 0)
    if nlen <= 8 and text.str.fullmatch(r"\d+").all():
        return pd.to_datetime(text.str[:8], format="%Y%m%d", errors="coerce")
    if nlen == 14 and text.str.fullmatch(r"\d+").all():
        return pd.to_datetime(text.str[:14], format="%Y%m%d%H%M%S", errors="coerce")
    num = pd.to_numeric(s, errors="coerce")
    vmax = float(num.max()) if num.notna().any() else 0
    if vmax > 1e16:
        return pd.to_datetime(num, unit="ns")
    if vmax > 1e11:
        return pd.to_datetime(num, unit="ms")
    return pd.to_datetime(s, errors="coerce")


def kline_frame(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "time" in out.columns:
        ts = parse_times(out["time"])
    else:
        ts = parse_times(out.index)
    out = out.reset_index(drop=True)
    out["datetime"] = ts
    out["symbol"] = symbol
    keep = ["symbol", "datetime", "open", "high", "low", "close", "volume"]
    if "amount" in out.columns:
        keep.append("amount")
    out = out[keep].dropna(subset=["datetime"])
    if "amount" not in out.columns:
        out["amount"] = out["close"] * out["volume"]
    return add_hhmm(out)


def fetch_kline(xtdata, symbols: Sequence[str], period: str, start: str, end: str) -> Dict[str, pd.DataFrame]:
    if not symbols:
        return {}
    md = xtdata.get_market_data_ex(
        KLINE_FIELDS,
        list(symbols),
        period=period,
        start_time=start,
        end_time=end,
        dividend_type="front_ratio",
        fill_data=False,
    )
    if not md:
        return {}
    # 新接口：{stock: DataFrame}；旧接口：{field: DataFrame}
    first = next(iter(md.values()))
    out: Dict[str, pd.DataFrame] = {}
    if isinstance(first, pd.DataFrame) and first.index.name != "stime" and any(
        str(idx).endswith((".SH", ".SZ")) for idx in list(first.index)[:3]
    ) and period == "1d":
        # field-oriented: rows=stocks, cols=times
        for field, frame in md.items():
            if not isinstance(frame, pd.DataFrame):
                continue
            for sym in frame.index:
                piece = frame.loc[sym]
                rec = out.setdefault(str(sym), {})
                rec[field] = piece
        rebuilt = {}
        for sym, rec in out.items():
            rebuilt[sym] = pd.DataFrame(rec)
        return rebuilt
    if isinstance(md, dict) and symbols[0] in md:
        return {k: v for k, v in md.items() if isinstance(v, pd.DataFrame)}
    # 可能全是 stock->df
    return {k: v for k, v in md.items() if isinstance(v, pd.DataFrame)}


def download_batches(xtdata, symbols: Sequence[str], period: str, start: str, end: str, batch: int) -> None:
    n = len(symbols)
    for i in range(0, n, batch):
        chunk = list(symbols[i : i + batch])
        _log("download %s %d-%d / %d" % (period, i + 1, min(i + batch, n), n))
        xtdata.download_history_data2(chunk, period, start, end)


def daily_tables(
    xtdata,
    meta: pd.DataFrame,
    start: str,
    end: str,
    batch: int = 80,
) -> pd.DataFrame:
    symbols = list(meta["symbol"])
    frames = []
    float_map = dict(zip(meta["symbol"], meta["float_volume"]))
    for i in range(0, len(symbols), batch):
        chunk = symbols[i : i + batch]
        _log("daily fetch %d-%d / %d" % (i + 1, min(i + batch, len(symbols)), len(symbols)))
        md = fetch_kline(xtdata, chunk, "1d", start, end)
        for sym, raw in md.items():
            bar = kline_frame(sym, raw)
            if bar.empty:
                continue
            bar["date"] = bar["datetime"].dt.date
            fv = float(float_map.get(sym) or 0)
            bar["float_mkt_cap"] = fv * bar["close"]
            bar["suspended"] = ((bar["volume"].fillna(0) <= 0) & (bar["amount"].fillna(0) <= 0)).astype(int)
            pre = bar["close"].shift(1)
            bar["pre_close"] = pre
            frames.append(
                bar[
                    [
                        "date",
                        "symbol",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                        "pre_close",
                        "float_mkt_cap",
                        "suspended",
                    ]
                ]
            )
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def candidate_pairs(daily: pd.DataFrame, meta: pd.DataFrame) -> List[Tuple[str, date]]:
    st = set(meta.loc[meta["is_st"], "symbol"])
    pairs = []
    for sym, g in daily.groupby("symbol"):
        if sym in st:
            continue
        g = g.sort_values("date")
        for _, row in g.iterrows():
            pre = row.get("pre_close")
            if pre is None or pd.isna(pre) or float(pre) <= 0:
                continue
            close = float(row["close"])
            high = float(row["high"])
            ret = close / float(pre) - 1.0
            hi = high / float(pre) - 1.0
            if 0.015 <= ret <= 0.09 or (hi >= 0.03 and ret >= 0.0):
                pairs.append((str(sym), row["date"]))
    return pairs


def write_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    _log("wrote %s rows=%d" % (path, len(df)))


def dump_minutes_for_candidates(
    xtdata,
    pairs: Sequence[Tuple[str, date]],
    cfg: OnrConfig,
    out_dir: Path,
    batch_syms: int = 8,
) -> None:
    by_sym: Dict[str, List[date]] = {}
    for sym, day in pairs:
        by_sym.setdefault(sym, []).append(day)
    symbols = sorted(by_sym)
    compact_rows = []
    sparse_rows = []
    for i in range(0, len(symbols), batch_syms):
        chunk = symbols[i : i + batch_syms]
        days = []
        for s in chunk:
            days.extend(by_sym[s])
        start = ymd(min(days))
        end = ymd(max(days))
        _log("1m fetch %d-%d / %d  %s-%s" % (i + 1, min(i + batch_syms, len(symbols)), len(symbols), start, end))
        md = fetch_kline(xtdata, chunk, "1m", start + "093000", end + "150000")
        for sym in chunk:
            raw = md.get(sym)
            bars = kline_frame(sym, raw) if raw is not None else pd.DataFrame()
            if bars.empty:
                continue
            bars["_day"] = bars["datetime"].dt.date
            want = set(by_sym[sym])
            nxt = set()
            # T+1 早盘：候选日的下一自然交易日也尽量留下 09:30–10:00
            all_days = sorted(bars["_day"].unique())
            pos = {d: j for j, d in enumerate(all_days)}
            for d in list(want):
                j = pos.get(d)
                if j is not None and j + 1 < len(all_days):
                    nxt.add(all_days[j + 1])
            keep_days = want | nxt
            for day, g in bars.groupby("_day"):
                if day not in keep_days:
                    continue
                g = g.drop(columns=["_day"])
                if day in want:
                    pack = compact_from_minutes(g, cfg)
                    pack["date"] = day
                    pack["symbol"] = sym
                    compact_rows.append(pack)
                sparse_rows.append(sparse_minutes(g))
    if compact_rows:
        write_csv(out_dir / "intraday.csv", pd.DataFrame(compact_rows))
    if sparse_rows:
        write_csv(out_dir / "minute.csv", pd.concat(sparse_rows, ignore_index=True))


def dump_index_minutes(xtdata, start: str, end: str, out_dir: Path) -> None:
    download_batches(xtdata, INDEX_CODES, "1m", start + "093000", end + "150000", batch=2)
    md = fetch_kline(xtdata, INDEX_CODES, "1m", start + "093000", end + "150000")
    frames = []
    for code in INDEX_CODES:
        raw = md.get(code)
        bar = kline_frame(code, raw) if raw is not None else pd.DataFrame()
        if bar.empty:
            continue
        frames.append(sparse_minutes(bar))
        # 指数量比需要 09:30–14:45 全日，不能只留稀疏窗
        frames.append(bar)
    if not frames:
        _log("index 1m empty")
        return
    idx = pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "datetime"])
    write_csv(out_dir / "index_minute.csv", idx)


def run_dump(args: argparse.Namespace) -> int:
    xtdata = ensure_xtquant(args.xt_site)
    cfg = OnrConfig()
    start_d = pd.Timestamp(args.start).date()
    end_d = pd.Timestamp(args.end).date()
    start, end = ymd(start_d), ymd(end_d)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    extra = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else []
    symbols = list_symbols(xtdata, extra)
    if args.smoke:
        symbols = (extra or symbols)[: max(8, len(extra) or 8)]
        _log("smoke symbols=%s" % ",".join(symbols))
    if not symbols:
        raise SystemExit("没有股票列表。确认 MiniQMT 已登录，板块「沪深A股」可用。")

    if not args.skip_download:
        download_batches(xtdata, symbols + list(INDEX_CODES), "1d", start, end, batch=args.batch)
    meta = load_meta(xtdata, symbols)
    daily = daily_tables(xtdata, meta, start, end, batch=args.batch)
    if daily.empty:
        raise SystemExit("日线为空。先启动 MiniQMT 并检查 download 是否成功。")
    write_csv(out_dir / "meta.csv", meta.drop(columns=["float_volume"], errors="ignore"))
    write_csv(out_dir / "daily.csv", daily)

    pairs = candidate_pairs(daily, meta)
    if args.smoke:
        pairs = pairs[:80]
    _log("candidate stock-days=%d unique=%d" % (len(pairs), len({s for s, _ in pairs})))
    cand_syms = sorted({s for s, _ in pairs})
    if cand_syms and not args.skip_download:
        download_batches(xtdata, cand_syms, "1m", start + "093000", end + "150000", batch=max(4, args.batch // 4))
    dump_minutes_for_candidates(xtdata, pairs, cfg, out_dir)
    dump_index_minutes(xtdata, start, end, out_dir)
    _log("done -> %s" % out_dir)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ONR MiniQMT 行情落盘")
    p.add_argument("--out", default="onr_strategy/data/xtdata")
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--xt-site", default=str(DEFAULT_XT_SITE))
    p.add_argument("--symbols", default="", help="逗号分隔，限制股票")
    p.add_argument("--smoke", action="store_true", help="少量标的冒烟")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--batch", type=int, default=40)
    args = p.parse_args(argv)
    return run_dump(args)


if __name__ == "__main__":
    raise SystemExit(main())
