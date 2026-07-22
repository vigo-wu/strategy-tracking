"""
红利中字头 list 池 · 日度选股（origin v3.1）。
仅扫描 list.md；周线近似多头 + 缩量逼近 EMA60 + 阳线站上 EMA20 + 量>3日均×1.2。
大盘：上证收盘≥日EMA130 才建议开仓（脚本输出校验结果）。
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import baostock as bs
import pandas as pd

THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
OUT_DIR = THEME_ROOT / "output"
DATA_DIR = REPO_ROOT / "data" / "daily"
LIST_MD = THEME_ROOT / "list.md"
OUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Hit:
    code: str
    name: str
    trade_date: str
    close: float
    open: float
    low: float
    ema20: float
    ema60: float
    atr14: float
    stop_r1: float
    swing_high: float
    vol_ratio: float
    note: str = "list固定池；待核大盘/板块"


def to_bs_code(code6: str) -> str:
    c = code6.zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"sh.{c}"
    return f"sz.{c}"


def load_list_md(path: Path = LIST_MD) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*([^|]+?)\s*\|", line.strip())
        if not m:
            continue
        code6, name = m.group(1), m.group(2).strip()
        rows.append({"code": to_bs_code(code6), "code6": code6, "name": name})
    if not rows:
        raise ValueError(f"未能从 {path} 解析到股票代码")
    return pd.DataFrame(rows)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr14(df: pd.DataFrame) -> pd.Series:
    prev_c = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_c).abs(),
            (df["low"] - prev_c).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=14, adjust=False).mean()


def check_bars(df: pd.DataFrame) -> tuple[bool, dict]:
    if len(df) < 160:
        return False, {"reason": "bars<160"}
    d = df.copy()
    d["ema20"] = ema(d["close"], 20)
    d["ema60"] = ema(d["close"], 60)
    d["w_fast"] = ema(d["close"], 60)
    d["w_slow"] = ema(d["close"], 130)
    d["mavol3"] = d["vol"].rolling(3).mean()
    d["mavol5"] = d["vol"].rolling(5).mean()
    d["mavol20"] = d["vol"].rolling(20).mean()
    d["atr"] = atr14(d)

    i = len(d) - 1
    row = d.iloc[i]
    prev = d.iloc[i - 1]
    if pd.isna(row["w_slow"]) or pd.isna(row["atr"]) or pd.isna(row["mavol3"]):
        return False, {"reason": "nan"}

    week_ok = bool(row["w_fast"] > row["w_slow"] and row["close"] >= row["w_fast"])
    near60 = bool(row["low"] <= row["ema60"] * 1.02 and row["close"] <= row["ema60"] * 1.05)
    vol_shrink = bool(row["mavol5"] <= row["mavol20"] * 0.85)
    yang = bool(row["close"] > row["open"])
    reclaim = bool(row["close"] > row["ema20"])
    vol_ok = bool(row["vol"] > row["mavol3"] * 1.2)
    ok = week_ok and near60 and vol_shrink and yang and reclaim and vol_ok

    window = d.iloc[max(0, i - 19) : i + 1]
    stop = float(row["close"] - 2 * row["atr"])
    meta = {
        "close": float(row["close"]),
        "open": float(row["open"]),
        "low": float(row["low"]),
        "ema20": float(row["ema20"]),
        "ema60": float(row["ema60"]),
        "atr14": float(row["atr"]),
        "stop_r1": stop,
        "swing_high": float(window["high"].max()),
        "vol_ratio": float(row["vol"] / row["mavol3"]) if row["mavol3"] else 0.0,
        "trade_date": str(row["date"])[:10],
        "pct_chg": float(row["close"] / prev["close"] - 1) * 100,
    }
    return ok, meta


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        cached = pd.read_csv(path)
        if cached.empty:
            return None
        return cached
    except Exception:
        return None


def _download_bars(bs_code: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount,tradestatus",
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="2",
        )
    except Exception:
        return None
    if rs.error_code != "0":
        return None
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None
    df = pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "vol", "amount", "tradestatus"]
    )
    for c in ("open", "high", "low", "close", "vol", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["tradestatus"] == "1"].dropna(subset=["close"])
    df = df[df["vol"] > 0].reset_index(drop=True)
    return df if len(df) else None


def fetch_hist(
    code6: str,
    start: str,
    end: str,
    *,
    force: bool = False,
    bs_code: str | None = None,
    cache_name: str | None = None,
) -> pd.DataFrame | None:
    """优先拉新；网络失败则回退本地缓存。"""
    cache = DATA_DIR / (cache_name or f"{code6}.csv")
    cached = _read_cache(cache)
    if (
        not force
        and cached is not None
        and str(cached["date"].iloc[-1])[:10] >= end[:10]
    ):
        return cached

    df = _download_bars(bs_code or to_bs_code(code6), start, end)
    if df is not None and len(df):
        df.to_csv(cache, index=False)
        return df
    return cached


def check_market_gate(start: str, end: str, *, force: bool = False) -> dict:
    """上证指数 sh.000001 收盘 ≥ 日EMA130 → 允许开仓。"""
    df = fetch_hist(
        "000001",
        start,
        end,
        force=force,
        bs_code="sh.000001",
        cache_name="000001_sh.csv",
    )
    if df is None or len(df) < 160:
        return {"ok": False, "reason": "上证数据不足", "trade_date": end, "symbol": "sh.000001"}
    d = df.copy()
    d["ema130"] = ema(d["close"], 130)
    row = d.iloc[-1]
    close = float(row["close"])
    ema130 = float(row["ema130"])
    return {
        "ok": bool(close >= ema130),
        "trade_date": str(row["date"])[:10],
        "close": round(close, 2),
        "ema130": round(ema130, 2),
        "symbol": "sh.000001",
        "reason": "上证≥日EMA130" if close >= ema130 else "上证弱(收盘<日EMA130)，停新开",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="v3.1 list 选股")
    parser.add_argument("--list", type=Path, default=LIST_MD, help="名单 markdown 路径")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="强制重拉 baostock 日线（断网重连后用）",
    )
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    universe = load_list_md(args.list)
    print(f"报告日: {today} | v3.1 list池 {len(universe)} 只 | {args.list}")
    if args.force_refresh:
        print("强制刷新日线缓存")
    start = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")
    lg = bs.login()
    print("baostock:", lg.error_code, lg.error_msg)
    online = lg.error_code == "0"
    if not online:
        print("网络不可用，改用本地 data/daily 缓存选股")
    hits: list[Hit] = []
    fail = {"hist_fail": 0, "tech_fail": 0}
    market = {"ok": False, "reason": "未校验"}
    try:
        market = check_market_gate(start, today, force=online and args.force_refresh)
        print(f"大盘: {market}")
        for _, row in universe.iterrows():
            code, name = row["code6"], row["name"]
            if online:
                df = fetch_hist(code, start, today, force=args.force_refresh)
            else:
                df = _read_cache(DATA_DIR / f"{code}.csv")
            if df is None or len(df) < 160:
                fail["hist_fail"] += 1
                continue
            df = df[df["date"].astype(str).str[:10] <= today].reset_index(drop=True)
            ok, meta = check_bars(df)
            if not ok:
                fail["tech_fail"] += 1
                continue
            note = "list命中"
            if not market.get("ok"):
                note += "；大盘过滤建议跳过开仓"
            if not online:
                note += "；缓存数据"
            hits.append(
                Hit(
                    code=code,
                    name=name,
                    trade_date=meta["trade_date"],
                    close=round(meta["close"], 2),
                    open=round(meta["open"], 2),
                    low=round(meta["low"], 2),
                    ema20=round(meta["ema20"], 2),
                    ema60=round(meta["ema60"], 2),
                    atr14=round(meta["atr14"], 3),
                    stop_r1=round(meta["stop_r1"], 2),
                    swing_high=round(meta["swing_high"], 2),
                    vol_ratio=round(meta["vol_ratio"], 2),
                    note=note,
                )
            )
            print(f"  ✓ HIT {code} {name} 止损{meta['stop_r1']:.2f} 量比{meta['vol_ratio']:.2f}")
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    trade_date = hits[0].trade_date if hits else market.get("trade_date", today)
    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "version": "v3.1",
        "list_path": str(args.list),
        "universe_size": len(universe),
        "hit_count": len(hits),
        "fail_stats": fail,
        "market": market,
        "data_mode": "online" if online else "cache",
        "force_refresh": bool(args.force_refresh),
        "hits": [asdict(h) for h in hits],
        "note": "仅list池；大盘=上证指数sh.000001收盘≥日EMA130",
    }
    out = OUT_DIR / f"screener_{trade_date}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([asdict(h) for h in hits]).to_csv(
        OUT_DIR / f"screener_{trade_date}.csv", index=False, encoding="utf-8-sig"
    )
    print(f"命中 {len(hits)} | {fail} | 已写 {out}")


if __name__ == "__main__":
    main()
