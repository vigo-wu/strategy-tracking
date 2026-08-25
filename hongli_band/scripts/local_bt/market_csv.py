# coding: utf-8
"""KlineDump 日线 CSV → 切片 / 形成中周 K。"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence


OHLC_FIELDS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class DailyBar:
    day: str
    dt: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0
    stock: str = ""
    period: str = "1d"


class BarFrame:
    """get_market_data_ex 返回值：有 index / columns，可供 _series_from_ex 解析。"""

    def __init__(self, bars: Sequence[DailyBar], fields: Sequence[str] | None = None):
        fields = list(fields) if fields else list(OHLC_FIELDS)
        self.columns = fields
        self.index = [b.dt for b in bars]
        self._cols: dict[str, list] = {}
        for field in fields:
            key = str(field).strip().lower()
            if key == "open":
                self._cols[field] = [float(b.open) for b in bars]
            elif key == "high":
                self._cols[field] = [float(b.high) for b in bars]
            elif key == "low":
                self._cols[field] = [float(b.low) for b in bars]
            elif key == "close":
                self._cols[field] = [float(b.close) for b in bars]
            elif key == "volume":
                self._cols[field] = [float(b.volume) for b in bars]
            elif key == "amount":
                self._cols[field] = [float(b.amount) for b in bars]
            elif key in ("time", "date", "datetime", "stime"):
                self._cols[field] = [b.dt for b in bars]
            else:
                self._cols[field] = [float(b.close) for b in bars]

    def __getitem__(self, field: str):
        return self._cols[field]

    def __len__(self) -> int:
        return len(self.index)


def digits_only(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def compact_day(s: str | None) -> str:
    d = digits_only(s or "")
    return d[:8] if len(d) >= 8 else ""


def parse_bar_datetime(raw: str) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    d = digits_only(s)
    if len(d) >= 14:
        try:
            return datetime.strptime(d[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None
    if len(d) >= 8:
        try:
            dt = datetime.strptime(d[:8], "%Y%m%d")
            return dt.replace(hour=15, minute=0, second=0)
        except ValueError:
            return None
    return None


def week_monday(day: str) -> str:
    d = datetime.strptime(str(day), "%Y%m%d")
    monday = d - timedelta(days=int(d.weekday()))
    return monday.strftime("%Y%m%d")


def _is_weekly_period(period: str | None) -> bool:
    p = str(period or "").strip().lower()
    return p in ("1w", "week", "weekly", "w")


def aggregate_weekly(dailies: Sequence[DailyBar]) -> list[DailyBar]:
    """按自然周一分组；最后一组含截至序列末日的未收盘周。"""
    groups: dict[str, list[DailyBar]] = {}
    order: list[str] = []
    for bar in dailies:
        key = week_monday(bar.day)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(bar)
    out: list[DailyBar] = []
    for key in order:
        bucket = groups[key]
        if not bucket:
            continue
        first = bucket[0]
        last = bucket[-1]
        out.append(
            DailyBar(
                day=last.day,
                dt=last.dt,
                open=float(first.open),
                high=max(float(x.high) for x in bucket),
                low=min(float(x.low) for x in bucket),
                close=float(last.close),
                volume=sum(float(x.volume) for x in bucket),
                amount=sum(float(x.amount) for x in bucket),
                stock=last.stock,
                period="1w",
            )
        )
    return out


def slice_bars(
    bars: Sequence[DailyBar],
    end_day: str,
    count: int | None = None,
    start_day: str = "",
) -> list[DailyBar]:
    end = compact_day(end_day) or "99991231"
    start = compact_day(start_day)
    kept = [b for b in bars if b.day <= end]
    if start:
        kept = [b for b in kept if b.day >= start]
    if count is not None and int(count) > 0:
        kept = kept[-int(count) :]
    return kept


def _open_csv(path: Path):
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            text = None
    if text is None:
        raise ValueError("cannot decode csv: %s" % path)
    return text.splitlines()


def _float(val, default: float = 0.0) -> float:
    s = str(val or "").strip().replace(",", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def load_daily_csv(path: str | Path, stock: str = "") -> tuple[str, list[DailyBar]]:
    """读取 KlineDump 日线 CSV。返回 (stock, bars)。"""
    p = Path(path)
    if not p.is_file():
        hint = ""
        parent = p.parent
        if parent.is_dir():
            names = [x.name for x in sorted(parent.glob("*.csv"))]
            if names:
                hint = "; existing csv: " + ", ".join(names[:12])
                if len(names) > 12:
                    hint += ", ..."
        else:
            hint = "; directory missing: %s" % parent
        raise FileNotFoundError(str(p) + hint)
    rows = csv.DictReader(_open_csv(p))
    want = str(stock or "").strip().upper()
    bars: list[DailyBar] = []
    periods: list[str] = []
    inferred = ""
    for row in rows:
        if not row:
            continue
        keys = {str(k).strip().lower(): k for k in row.keys() if k is not None}
        def col(*names: str) -> str:
            for name in names:
                k = keys.get(name.lower())
                if k is not None:
                    return str(row.get(k) or "")
            return ""

        period = str(col("period") or "1d").strip().lower() or "1d"
        if period in ("1w", "week", "weekly", "w"):
            periods.append("1w")
            continue
        periods.append(period)
        dt = parse_bar_datetime(col("datetime", "time", "date", "stime"))
        if dt is None:
            continue
        close = _float(col("close"))
        if close <= 0:
            continue
        code = str(col("stock", "code") or "").strip().upper()
        if want and code and code != want:
            continue
        if not inferred and code:
            inferred = code
        day = dt.strftime("%Y%m%d")
        dt = dt.replace(hour=15, minute=0, second=0, microsecond=0)
        open_ = _float(col("open"), close)
        high = _float(col("high"), max(open_, close))
        low = _float(col("low"), min(open_, close))
        volume = _float(col("volume"))
        amount = _float(col("amount"))
        bars.append(
            DailyBar(
                day=day,
                dt=dt,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                amount=amount,
                stock=code or want,
                period="1d",
            )
        )
    if not bars:
        raise ValueError("no daily bars in %s" % p)
    if periods and all(x == "1w" for x in periods):
        raise ValueError("need daily 1d CSV, got weekly: %s" % p)
    bars.sort(key=lambda b: b.day)
    dedup: dict[str, DailyBar] = {}
    for b in bars:
        dedup[b.day] = b
    bars = [dedup[k] for k in sorted(dedup)]
    out_stock = want or inferred or bars[0].stock
    if not out_stock:
        raise ValueError("stock code missing; pass --stock or CSV stock column")
    return out_stock, bars


def walk_days(
    bars: Sequence[DailyBar],
    start: str = "",
    end: str = "",
) -> list[DailyBar]:
    start_d = compact_day(start)
    end_d = compact_day(end)
    out = list(bars)
    if start_d:
        out = [b for b in out if b.day >= start_d]
    if end_d:
        out = [b for b in out if b.day <= end_d]
    return out


class MarketStore:
    def __init__(self, bars: Sequence[DailyBar], stock: str):
        self.bars = list(bars)
        self.stock = str(stock).strip().upper()

    def frame(
        self,
        period: str,
        end_time: str,
        count: int | None,
        fields: Iterable[str] | None = None,
        start_time: str = "",
        stock: str = "",
    ) -> BarFrame:
        dailies = slice_bars(self.bars, end_time, count=None, start_day=start_time)
        if _is_weekly_period(period):
            seq = aggregate_weekly(dailies)
            if count is not None and int(count) > 0:
                seq = seq[-int(count) :]
        else:
            seq = slice_bars(dailies, end_time, count=count, start_day="")
        cols = list(fields) if fields else list(OHLC_FIELDS)
        return BarFrame(seq, cols)
