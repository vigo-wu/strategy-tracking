"""
红利T策略 · 日线信号扫描（v2.5）。
R-A：零浮仓假设下提示低吸；R-B 需已知 Float A 成本（脚本仅输出指标与 A/B 条件是否满足价位）。
R高抛：上轨且 J>=100。无 R1。
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
OUT_DIR = THEME_ROOT / "output"
DATA_DIR = REPO_ROOT / "data" / "daily"
LIST_MD = THEME_ROOT / "list.md"
OUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

BOLL_N = 20
BOLL_K = 2.0
MA_N = 20
KDJ_N = 9
SPACE_STEP = 0.025


@dataclass
class SignalRow:
    code: str
    name: str
    trade_date: str
    close: float
    ma20: float
    boll_mid: float
    boll_upper: float
    boll_lower: float
    kdj_j: float
    signal_buy_a: bool
    signal_buy_b_ready: bool
    signal_sell: bool
    note: str = ""


def load_list_md(path: Path = LIST_MD) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*([^|]+?)\s*\|", line.strip())
        if not m:
            continue
        rows.append({"code6": m.group(1), "name": m.group(2).strip()})
    if not rows:
        raise ValueError(f"未能从 {path} 解析到股票代码")
    return pd.DataFrame(rows)


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    colmap = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "vol",
        "date": "date",
        "open": "open",
        "close": "close",
        "high": "high",
        "low": "low",
        "vol": "vol",
        "volume": "vol",
    }
    out = df.rename(columns={c: colmap[c] for c in df.columns if c in colmap})
    for c in ("open", "high", "low", "close", "vol"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out["date"] = out["date"].astype(str).str[:10]
    return out.dropna(subset=["close"]).reset_index(drop=True)


def fetch_hist(code6: str, start: str, end: str, *, force: bool = False) -> pd.DataFrame | None:
    cache = DATA_DIR / f"{code6}.csv"
    cached = None
    if cache.exists() and not force:
        try:
            cached = pd.read_csv(cache)
        except Exception:
            cached = None
    if cached is not None and not cached.empty and str(cached["date"].iloc[-1])[:10] >= end[:10]:
        return cached
    try:
        import akshare as ak

        raw = ak.fund_etf_hist_em(
            symbol=code6,
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="qfq",
        )
        df = _normalize_ohlcv(raw)
        if df is not None and len(df):
            df.to_csv(cache, index=False)
            return df
    except Exception as e:
        print(f"  akshare fail {code6}: {e}")
    return cached


def calc_daily_indicators(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    out["ma20"] = out["close"].rolling(MA_N).mean()
    mid = out["close"].rolling(BOLL_N).mean()
    std = out["close"].rolling(BOLL_N).std(ddof=0)
    out["boll_mid"] = mid
    out["boll_upper"] = mid + BOLL_K * std
    out["boll_lower"] = mid - BOLL_K * std
    low_n = out["low"].rolling(KDJ_N).min()
    high_n = out["high"].rolling(KDJ_N).max()
    rsv = (out["close"] - low_n) / (high_n - low_n).replace(0, pd.NA) * 100
    out["k"] = rsv.ewm(com=2, adjust=False).mean()
    out["d"] = out["k"].ewm(com=2, adjust=False).mean()
    out["j"] = 3 * out["k"] - 2 * out["d"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="红利T v2.5 日线信号")
    parser.add_argument("--list", type=Path, default=LIST_MD)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument(
        "--float-a-price",
        type=float,
        default=None,
        help="若已持有 Float A，传入成交价以判定今日能否开 B（空间>=2.5%%）",
    )
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    universe = load_list_md(args.list)
    print(f"report: {today} | HongliT v2.5 | n={len(universe)}")
    start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")

    signals: list[SignalRow] = []
    for _, row in universe.iterrows():
        code, name = row["code6"], row["name"]
        df = fetch_hist(code, start, today, force=args.force_refresh)
        if df is None or len(df) < 40:
            print(f"  FAIL data {code} {name}")
            continue
        ind = calc_daily_indicators(df)
        last = ind.iloc[-1]
        if pd.isna(last["boll_lower"]) or pd.isna(last["j"]):
            continue
        close = float(last["close"])
        lower = float(last["boll_lower"])
        upper = float(last["boll_upper"])
        mid = float(last["boll_mid"])
        j = float(last["j"])
        buy = close <= lower * 1.002 and j <= 0
        sell = close >= upper * 0.998 and j >= 100
        buy_a = buy  # 实盘须另核零浮仓
        buy_b = False
        notes = []
        if buy:
            notes.append("低吸条件(须核零浮仓→A / 有A+空间→B)")
            if args.float_a_price is not None:
                buy_b = close <= args.float_a_price * (1 - SPACE_STEP)
                drop = (args.float_a_price - close) / args.float_a_price * 100
                notes.append(
                    f"相对A跌{drop:.2f}% → {'可开B' if buy_b else '空间不足跳过B'}"
                )
        if sell:
            notes.append("R高抛(清全部浮仓)")
        if not notes:
            notes.append("观望")
        sig = SignalRow(
            code=code,
            name=name,
            trade_date=str(last["date"])[:10],
            close=round(close, 4),
            ma20=round(float(last["ma20"]), 4) if pd.notna(last["ma20"]) else 0.0,
            boll_mid=round(mid, 4),
            boll_upper=round(upper, 4),
            boll_lower=round(lower, 4),
            kdj_j=round(j, 2),
            signal_buy_a=bool(buy_a),
            signal_buy_b_ready=bool(buy_b),
            signal_sell=bool(sell),
            note=";".join(notes),
        )
        signals.append(sig)
        flag = "SELL" if sell else ("BUY?" if buy else "HOLD")
        print(f"  [{flag}] {code} close={sig.close} J={sig.kdj_j} | {sig.note}")

    trade_date = signals[0].trade_date if signals else today
    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "version": "v2.5",
        "space_step": SPACE_STEP,
        "signals": [asdict(s) for s in signals],
        "note": "v2.5无R1；B须相对A>=2.5%；高抛清全部浮仓",
    }
    out = OUT_DIR / f"screener_{trade_date}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([asdict(s) for s in signals]).to_csv(
        OUT_DIR / f"screener_{trade_date}.csv", index=False, encoding="utf-8-sig"
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
