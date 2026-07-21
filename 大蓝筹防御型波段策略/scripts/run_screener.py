"""
大蓝筹防御型波段 · 日度选股（复现 model.md 通达信公式）。
预筛：市值≥500亿、成交额≥3亿、非ST；技术面：TREND + NEAR_LINE + TOUCH_BOLL + CCI_TURN。
沪深300/红利成分与股息率未自动核验，命中后需人工核对。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import baostock as bs
import numpy as np
import pandas as pd
import requests

THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
OUT_DIR = THEME_ROOT / "output"
DATA_DIR = REPO_ROOT / "data" / "daily"
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
    pct_chg: float
    market_cap_yi: float | None
    amount_yi: float | None
    ma120: float
    stop_line: float
    cci: float
    note: str = "市值+流动性预筛；成分/股息待核"


def to_bs_code(code6: str) -> str:
    if code6.startswith(("5", "6", "9")):
        return f"sh.{code6}"
    return f"sz.{code6}"


def fetch_market_cap_yi(code6: str, retries: int = 3) -> float | None:
    if code6.startswith(("688", "689", "60", "90")):
        prefix = "sh"
    else:
        prefix = "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code6}"
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=8)
            r.encoding = "gbk"
            m = re.search(r'="([^"]+)"', r.text)
            if not m:
                time.sleep(0.3 * (attempt + 1))
                continue
            parts = m.group(1).split("~")
            if len(parts) > 45 and parts[45]:
                return round(float(parts[45]), 2)
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return None


def avedev(series: pd.Series, window: int) -> pd.Series:
    def _f(x: np.ndarray) -> float:
        return float(np.mean(np.abs(x - np.mean(x))))

    return series.rolling(window).apply(_f, raw=True)


def check_bars(df: pd.DataFrame) -> tuple[bool, dict]:
    if len(df) < 260:
        return False, {"reason": "bars<260"}

    d = df.copy()
    d["ma120"] = d["close"].rolling(120).mean()
    d["ma250"] = d["close"].rolling(250).mean()
    mid = d["close"].rolling(20).mean()
    std = d["close"].rolling(20).std()
    d["boll_lower"] = mid - 2 * std
    typ = (d["high"] + d["low"] + d["close"]) / 3
    d["cci"] = (typ - typ.rolling(14).mean()) / (0.015 * avedev(typ, 14))

    i = len(d) - 1
    row = d.iloc[i]
    prev = d.iloc[i - 1]

    trend_ok = bool(row["close"] > row["ma250"] and row["ma120"] > row["ma250"])
    near_line = bool(row["close"] >= row["ma120"] and row["close"] <= row["ma120"] * 1.03)
    touch_boll = bool(row["low"] <= row["boll_lower"] * 1.01)
    cci_turn = bool(prev["cci"] < -100 and row["cci"] > prev["cci"])

    ok = trend_ok and near_line and touch_boll and cci_turn
    meta = {
        "trend_ok": trend_ok,
        "near_line": near_line,
        "touch_boll": touch_boll,
        "cci_turn": cci_turn,
        "close": float(row["close"]),
        "open": float(row["open"]),
        "low": float(row["low"]),
        "ma120": float(row["ma120"]),
        "stop_line": float(row["ma120"] * 0.98),
        "cci": float(row["cci"]) if pd.notna(row["cci"]) else None,
        "trade_date": str(row["date"])[:10],
        "pct_chg": float(row["close"] / prev["close"] - 1) * 100,
    }
    return ok, meta


def fetch_hist_bs(code6: str, start: str, end: str) -> pd.DataFrame | None:
    cache = DATA_DIR / f"{code6}.csv"
    # 优先用缓存再补尾部；此处简化：直接拉 baostock
    rs = bs.query_history_k_data_plus(
        to_bs_code(code6),
        "date,open,high,low,close,volume,amount,tradestatus",
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag="2",
    )
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
    df = df[df["tradestatus"] == "1"].dropna(subset=["close"]).reset_index(drop=True)
    df = df[df["vol"] > 0]
    if len(df):
        df.to_csv(cache, index=False)
    return df


def append_today_bar(df: pd.DataFrame, spot_row: pd.Series, today: str) -> pd.DataFrame:
    last_date = str(df.iloc[-1]["date"])[:10]
    if last_date >= today:
        return df
    bar = {
        "date": today,
        "open": float(spot_row["今开"]),
        "high": float(spot_row["最高"]),
        "low": float(spot_row["最低"]),
        "close": float(spot_row["最新价"]),
        "vol": float(spot_row["成交量"]),
        "amount": float(spot_row["成交额"]),
        "tradestatus": "1",
    }
    return pd.concat([df, pd.DataFrame([bar])], ignore_index=True)


def main() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"报告日: {today}")
    print("拉取新浪快照…")
    spot = ak.stock_zh_a_spot()
    spot["raw"] = spot["代码"].astype(str)
    spot["code"] = spot["raw"].str[-6:]
    spot["name"] = spot["名称"].astype(str)
    spot["amount"] = pd.to_numeric(spot["成交额"], errors="coerce")

    # 排除北交所、ST；成交额≥3亿（预筛，市值稍后核对）
    mask = (
        ~spot["raw"].str.startswith("bj")
        & (~spot["name"].str.contains("ST", case=False, na=False))
        & (spot["amount"] >= 3e8)
        & (spot["code"].str.match(r"^(60|00|30)\d{4}$"))
    )
    candidates = spot.loc[mask].copy()
    print(f"成交额预筛（≥3亿、非ST、主板/创业）：{len(candidates)} 只")

    # 市值 ≥500 亿
    print("市值过滤中…")
    keep_idx = []
    cap_map: dict[str, float] = {}
    for n, (idx, row) in enumerate(candidates.iterrows(), 1):
        if n % 40 == 0:
            print(f"  市值 {n}/{len(candidates)}")
        mv = fetch_market_cap_yi(row["code"])
        time.sleep(0.08)
        if mv is not None and mv >= 500:
            keep_idx.append(idx)
            cap_map[row["code"]] = mv
    candidates = candidates.loc[keep_idx].copy()
    print(f"市值≥500亿：{len(candidates)} 只")

    end = today
    start = (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d")
    lg = bs.login()
    print("baostock:", lg.error_code, lg.error_msg)

    hits: list[Hit] = []
    fail = {"hist_fail": 0, "tech_fail": 0}
    try:
        for n, (_, row) in enumerate(candidates.iterrows(), 1):
            code, name = row["code"], row["name"]
            if n % 20 == 0 or n == 1:
                print(f"  日线 {n}/{len(candidates)} … {code} {name}")
            df = fetch_hist_bs(code, start, end)
            if df is None or len(df) < 250:
                fail["hist_fail"] += 1
                continue
            df = append_today_bar(df, row, today)
            if len(df) < 260:
                fail["hist_fail"] += 1
                continue
            ok, meta = check_bars(df)
            if not ok:
                fail["tech_fail"] += 1
                continue
            hits.append(
                Hit(
                    code=code,
                    name=name,
                    trade_date=meta["trade_date"],
                    close=round(meta["close"], 2),
                    open=round(meta["open"], 2),
                    low=round(meta["low"], 2),
                    pct_chg=round(meta["pct_chg"], 2),
                    market_cap_yi=cap_map.get(code),
                    amount_yi=round(float(row["amount"]) / 1e8, 2),
                    ma120=round(meta["ma120"], 2),
                    stop_line=round(meta["stop_line"], 2),
                    cci=round(meta["cci"], 2) if meta["cci"] is not None else 0.0,
                )
            )
            print(f"  ✓ HIT {code} {name} CCI={meta['cci']:.1f} 止损{meta['stop_line']:.2f}")
    finally:
        bs.logout()

    trade_date = hits[0].trade_date if hits else today
    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "prefilter_count": int(len(candidates)),
        "hit_count": len(hits),
        "fail_stats": fail,
        "hits": [asdict(h) for h in hits],
        "note": "未自动校验沪深300/红利成分与股息率≥3.5%",
    }
    out = OUT_DIR / f"screener_{trade_date}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([asdict(h) for h in hits]).to_csv(
        OUT_DIR / f"screener_{trade_date}.csv", index=False, encoding="utf-8-sig"
    )
    print("\n======== 选股结果 ========")
    print(f"交易日 {trade_date} | 命中 {len(hits)} | 市值池 {len(candidates)} | {fail}")
    for h in hits:
        print(f"  {h.code} {h.name} 收{h.close} 止损{h.stop_line} 市值{h.market_cap_yi}亿")
    print(f"已写入 {out}")


if __name__ == "__main__":
    main()
