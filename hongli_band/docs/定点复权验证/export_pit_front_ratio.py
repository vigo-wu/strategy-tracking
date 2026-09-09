# coding: utf-8
"""用 qmt_common/pit_front 对 none CSV 做等比 PIT 回放，导出 front_ratio 与除权快照。"""
from __future__ import annotations

import csv
import datetime
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
PIT_PATH = REPO / "scripts" / "qmt_common" / "pit_front.py"
CSV_ROOT = REPO / "tools" / "csv"
OUT_ROOT = Path(__file__).resolve().parent / "front_ratio"
STOCK = "000001.SZ"


def _load_pit():
    A = SimpleNamespace(is_backtest=True, _pit_ohlc_cache={})
    ns = {"datetime": datetime, "A": A}
    src = PIT_PATH.read_text(encoding="utf-8")
    exec(compile(src, str(PIT_PATH), "exec"), ns, ns)
    ns["A"] = A
    return ns


def _day8(raw: str) -> str:
    d = "".join(ch for ch in str(raw or "") if ch.isdigit())[:8]
    return d if len(d) == 8 else ""


def _fmt_dt(day: str, raw: str) -> str:
    s = str(raw or "").strip()
    if "-" in s:
        return s
    if len(day) == 8:
        return "%s-%s-%s" % (day[:4], day[4:6], day[6:8])
    return s


def load_ohlc_csv(path: Path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            day = _day8(row.get("datetime") or row.get("date") or "")
            if not day:
                continue
            try:
                o = float(row["open"])
                h = float(row["high"])
                l = float(row["low"])
                c = float(row["close"])
            except (KeyError, TypeError, ValueError):
                continue
            vol = float(row.get("volume") or 0)
            amt = float(row.get("amount") or 0)
            rows.append(
                {
                    "stock": (row.get("stock") or STOCK).strip() or STOCK,
                    "period": (row.get("period") or "").strip(),
                    "datetime": _fmt_dt(day, row.get("datetime") or ""),
                    "day": day,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": vol,
                    "amount": amt,
                }
            )
    return rows


def load_close_map(path: Path) -> dict[str, float]:
    out = {}
    if not path.is_file():
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            day = _day8(row.get("datetime") or row.get("date") or "")
            if not day:
                continue
            try:
                out[day] = float(row["close"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def find_none_csv(period: str) -> Path:
    folder = CSV_ROOT / "none"
    hits = sorted(folder.glob("000001_SZ_%s_*.csv" % period))
    if not hits:
        raise FileNotFoundError("缺 none CSV: %s/000001_SZ_%s_*.csv" % (folder, period))
    return hits[-1]


def find_qmt_front_ratio(period: str) -> Path | None:
    folder = CSV_ROOT / "front_ratio"
    hits = sorted(folder.glob("000001_SZ_%s_*.csv" % period))
    return hits[-1] if hits else None


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def new_events(events, prev_asof: str, asof: str, first_bar: str):
    """(prev_asof, asof] 内、且能改当前序列的事件（须有 bar t < e.day）。"""
    out = []
    for day, dr in events:
        if prev_asof and day <= prev_asof:
            continue
        if day > asof:
            break
        if first_bar and day <= first_bar:
            continue
        out.append((day, dr))
    return out


def export_period(ns, period: str, events) -> dict:
    src = find_none_csv(period)
    raw_rows = load_ohlc_csv(src)
    if not raw_rows:
        raise ValueError("空 CSV: %s" % src)
    days = [r["day"] for r in raw_rows]
    opens = [r["open"] for r in raw_rows]
    highs = [r["high"] for r in raw_rows]
    lows = [r["low"] for r in raw_rows]
    closes = [r["close"] for r in raw_rows]
    n = len(days)
    start, end = days[0], days[-1]
    ns["A"]._pit_ohlc_cache = {}

    snap_dir = OUT_ROOT / "snapshots" / period
    dump_fields = [
        "stock",
        "period",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    snap_fields = dump_fields + ["day", "raw_close", "cum_dr", "asof", "new_event_day", "new_dr"]
    event_hits = []
    prev_asof = ""
    last_adj = None
    last_asof = end

    for i, asof in enumerate(days):
        hit = new_events(events, prev_asof, asof, days[0])
        is_last = i == n - 1
        if hit or is_last:
            o2, h2, l2, c2 = ns["pit_adjust_ohlc_cached"](
                STOCK, days[: i + 1], opens[: i + 1], highs[: i + 1],
                lows[: i + 1], closes[: i + 1], events, asof, "ratio",
            )
            last_adj = (o2, h2, l2, c2)
            last_asof = asof
            new_day = hit[0][0] if hit else ""
            new_dr = hit[0][1] if hit else ""
            extra = ""
            if len(hit) > 1:
                extra = ";".join("%s:%.6f" % (d, dr) for d, dr in hit[1:])
            rows = []
            for j in range(i + 1):
                mul = ns["pit_cum_dr"](events, days[j], asof)
                rows.append(
                    {
                        "stock": raw_rows[j]["stock"],
                        "period": raw_rows[j]["period"] or period,
                        "datetime": raw_rows[j]["datetime"],
                        "open": o2[j],
                        "high": h2[j],
                        "low": l2[j],
                        "close": c2[j],
                        "volume": raw_rows[j]["volume"],
                        "amount": raw_rows[j]["amount"],
                        "day": days[j],
                        "raw_close": closes[j],
                        "cum_dr": mul,
                        "asof": asof,
                        "new_event_day": new_day,
                        "new_dr": new_dr,
                    }
                )
            kind = "event" if hit else "final"
            name = "asof_%s_%s.csv" % (asof, kind)
            write_csv(snap_dir / name, snap_fields, rows)
            event_hits.append(
                {
                    "asof": asof,
                    "kind": kind,
                    "n_bars": i + 1,
                    "events": [{"day": d, "dr": dr} for d, dr in hit],
                    "first_raw_close": closes[0],
                    "first_pit_close": c2[0],
                    "last_raw_close": closes[i],
                    "last_pit_close": c2[i],
                    "file": str((snap_dir / name).relative_to(OUT_ROOT)).replace("\\", "/"),
                    "extra": extra,
                }
            )
        prev_asof = asof

    assert last_adj is not None
    o2, h2, l2, c2 = last_adj
    final_rows = []
    for j in range(n):
        final_rows.append(
            {
                "stock": raw_rows[j]["stock"],
                "period": raw_rows[j]["period"] or period,
                "datetime": raw_rows[j]["datetime"],
                "open": o2[j],
                "high": h2[j],
                "low": l2[j],
                "close": c2[j],
                "volume": raw_rows[j]["volume"],
                "amount": raw_rows[j]["amount"],
            }
        )
    out_name = "000001_SZ_%s_%s_%s.csv" % (period, start, end)
    out_path = OUT_ROOT / out_name
    write_csv(out_path, dump_fields, final_rows)

    qmt_path = find_qmt_front_ratio(period)
    qmt_map = load_close_map(qmt_path) if qmt_path else {}
    diffs = []
    max_abs = 0.0
    n_overlap = 0
    n_mismatch = 0
    for j, day in enumerate(days):
        if day not in qmt_map:
            continue
        n_overlap += 1
        pit_c = float(c2[j])
        qmt_c = float(qmt_map[day])
        dlt = pit_c - qmt_c
        ad = abs(dlt)
        if ad > max_abs:
            max_abs = ad
        if ad > 1e-9:
            n_mismatch += 1
            if len(diffs) < 30:
                diffs.append(
                    {
                        "day": day,
                        "raw": closes[j],
                        "pit": pit_c,
                        "qmt": qmt_c,
                        "diff": dlt,
                        "cum_dr": ns["pit_cum_dr"](events, day, last_asof),
                    }
                )
    compare_path = OUT_ROOT / ("compare_vs_qmt_%s.csv" % period)
    write_csv(
        compare_path,
        ["day", "raw", "pit", "qmt", "diff", "cum_dr"],
        diffs,
    )
    return {
        "period": period,
        "none_csv": str(src).replace("\\", "/"),
        "qmt_csv": str(qmt_path).replace("\\", "/") if qmt_path else "",
        "out_csv": str(out_path.relative_to(OUT_ROOT)).replace("\\", "/"),
        "n_bars": n,
        "start": start,
        "end": end,
        "n_snapshots": len(event_hits),
        "n_event_snapshots": sum(1 for x in event_hits if x["kind"] == "event"),
        "snapshots": event_hits,
        "qmt_compare": {
            "n_overlap": n_overlap,
            "n_mismatch_gt_1e-9": n_mismatch,
            "max_abs_diff": max_abs,
            "mismatch_sample": diffs,
            "compare_csv": str(compare_path.relative_to(OUT_ROOT)).replace("\\", "/"),
        },
    }


def main() -> int:
    ns = _load_pit()
    fac_path = CSV_ROOT / "divid_factors" / "000001_SZ.json"
    factors = json.loads(fac_path.read_text(encoding="utf-8"))
    events = ns["pit_parse_events"](factors)
    full = ns["pit_parse_full_events"](factors)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    none_1d = find_none_csv("1d")
    none_rows = load_ohlc_csv(none_1d)
    first_day, last_day = none_rows[0]["day"], none_rows[-1]["day"]
    in_sample = [e for e in events if first_day < e[0] <= last_day]
    all_events = [
        {
            "day": day,
            "interest": i,
            "bonus": b,
            "gift": g,
            "allot": a,
            "allot_px": ap,
            "dr": dr,
            "ratio_used": dr > 1.0,
            "in_sample": first_day < day <= last_day,
        }
        for day, i, b, g, a, ap, dr in full
    ]
    write_csv(
        OUT_ROOT / "events.csv",
        [
            "day",
            "interest",
            "bonus",
            "gift",
            "allot",
            "allot_px",
            "dr",
            "ratio_used",
            "in_sample",
        ],
        all_events,
    )

    summary = {
        "stock": STOCK,
        "mode": "front_ratio",
        "formula": "P_adj(t;T) = P_raw(t) / Pi{dr | t < e.day <= T}",
        "factors": str(fac_path).replace("\\", "/"),
        "n_ratio_events": len(events),
        "n_in_sample_ratio_events": len(in_sample),
        "in_sample_events": [{"day": d, "dr": dr} for d, dr in in_sample],
        "periods": {},
    }
    for period in ("1d", "1w"):
        summary["periods"][period] = export_period(ns, period, events)

    (OUT_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(
        {
            "out": str(OUT_ROOT),
            "n_ratio_events": len(events),
            "n_in_sample": len(in_sample),
            "1d_snaps": summary["periods"]["1d"]["n_snapshots"],
            "1w_snaps": summary["periods"]["1w"]["n_snapshots"],
            "1d_max_abs_diff": summary["periods"]["1d"]["qmt_compare"]["max_abs_diff"],
            "1w_max_abs_diff": summary["periods"]["1w"]["qmt_compare"]["max_abs_diff"],
            "1d_mismatch": summary["periods"]["1d"]["qmt_compare"]["n_mismatch_gt_1e-9"],
            "1w_mismatch": summary["periods"]["1w"]["qmt_compare"]["n_mismatch_gt_1e-9"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
