# coding: utf-8
"""KlineDump 日线 CSV → 切片；周线默认对齐 QMT 回测原生 1w（不含未收盘周）。"""
from __future__ import annotations

import bisect
import csv
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np


OHLC_FIELDS = ("open", "high", "low", "close", "volume")
_DAILY_NAME_RE = re.compile(r"(?i)(\d{6})[._](SZ|SH)")


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

    def __init__(
        self,
        bars: Sequence[DailyBar] | None = None,
        fields: Sequence[str] | None = None,
        *,
        index: Sequence[datetime] | None = None,
        cols: dict | None = None,
    ):
        fields = list(fields) if fields else list(OHLC_FIELDS)
        self.columns = fields
        if cols is not None:
            self.index = list(index) if index is not None else []
            self._cols = cols
            return
        bars = list(bars or [])
        self.index = [b.dt for b in bars]
        self._cols = {}
        for field in fields:
            self._cols[field] = _col_from_bars(bars, field, self.index)

    def __getitem__(self, field: str):
        return self._cols[field]

    def __len__(self) -> int:
        return len(self.index)


def _col_from_bars(bars: Sequence[DailyBar], field: str, index: Sequence[datetime]):
    key = str(field).strip().lower()
    if key == "open":
        return [float(b.open) for b in bars]
    if key == "high":
        return [float(b.high) for b in bars]
    if key == "low":
        return [float(b.low) for b in bars]
    if key == "close":
        return [float(b.close) for b in bars]
    if key == "volume":
        return [float(b.volume) for b in bars]
    if key == "amount":
        return [float(b.amount) for b in bars]
    if key in ("time", "date", "datetime", "stime"):
        return list(index)
    return [float(b.close) for b in bars]


class _ColPack:
    """已排序日/周 K：days 供 bisect，OHLCV 为 numpy 列。"""

    def __init__(self, bars: Sequence[DailyBar]):
        self.bars = list(bars)
        n = len(self.bars)
        self.days = [b.day for b in self.bars]
        self.index = [b.dt for b in self.bars]
        if n == 0:
            z = np.zeros(0, dtype=float)
            self.open = self.high = self.low = self.close = self.volume = self.amount = z
            return
        self.open = np.fromiter((b.open for b in self.bars), dtype=float, count=n)
        self.high = np.fromiter((b.high for b in self.bars), dtype=float, count=n)
        self.low = np.fromiter((b.low for b in self.bars), dtype=float, count=n)
        self.close = np.fromiter((b.close for b in self.bars), dtype=float, count=n)
        self.volume = np.fromiter((b.volume for b in self.bars), dtype=float, count=n)
        self.amount = np.fromiter((b.amount for b in self.bars), dtype=float, count=n)

    def bounds(self, end_day: str, start_day: str = "", count: int | None = None) -> tuple[int, int]:
        end = compact_day(end_day) or "99991231"
        start = compact_day(start_day)
        hi = bisect.bisect_right(self.days, end)
        lo = bisect.bisect_left(self.days, start) if start else 0
        if lo > hi:
            lo = hi
        if count is not None and int(count) > 0:
            want = int(count)
            if hi - lo > want:
                lo = hi - want
        return lo, hi

    def drop_forming_hi(self, lo: int, hi: int, end_day: str) -> int:
        end = compact_day(end_day)
        if not end or hi <= lo:
            return hi
        cur = week_monday(end)
        while hi > lo and week_monday(self.days[hi - 1]) == cur:
            hi -= 1
        return hi

    def as_frame(self, lo: int, hi: int, fields: Sequence[str]) -> BarFrame:
        fields = list(fields)
        idx = self.index[lo:hi]
        cols = {}
        for field in fields:
            key = str(field).strip().lower()
            if key == "open":
                cols[field] = self.open[lo:hi]
            elif key == "high":
                cols[field] = self.high[lo:hi]
            elif key == "low":
                cols[field] = self.low[lo:hi]
            elif key == "close":
                cols[field] = self.close[lo:hi]
            elif key == "volume":
                cols[field] = self.volume[lo:hi]
            elif key == "amount":
                cols[field] = self.amount[lo:hi]
            elif key in ("time", "date", "datetime", "stime"):
                cols[field] = idx
            else:
                cols[field] = self.close[lo:hi]
        return BarFrame(fields=fields, index=idx, cols=cols)

    def as_ohlcv(self, lo: int, hi: int):
        if hi <= lo:
            return None
        return (
            self.open[lo:hi],
            self.high[lo:hi],
            self.low[lo:hi],
            self.close[lo:hi],
            self.volume[lo:hi],
        )

    def as_ohlcv_with_days(self, lo: int, hi: int):
        pack = self.as_ohlcv(lo, hi)
        if pack is None:
            return None
        return pack + (list(self.days[lo:hi]),)


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
            return dt.replace(hour=0, minute=0, second=0)
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


def drop_unclosed_week(bars: Sequence[DailyBar], end_day: str) -> list[DailyBar]:
    """丢掉 end_day 所在自然周。QMT 回测 K 线在 00:00，本周 1w 尚未收盘。"""
    end = compact_day(end_day)
    if not end or not bars:
        return list(bars)
    cur = week_monday(end)
    return [b for b in bars if week_monday(b.day) != cur]


def aggregate_weekly(
    dailies: Sequence[DailyBar],
    *,
    drop_forming: bool = True,
    end_day: str = "",
) -> list[DailyBar]:
    """按自然周（周一为一周）把日 K 合成周 K。

    默认 drop_forming=True：不含 end_day 所在周，对齐 QMT 原生 1w。
    周五当天也不把本周算进去（回测 bar=0000，本周周 K 要到下一周才出现）。
    """
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
        dt = last.dt.replace(hour=0, minute=0, second=0, microsecond=0)
        out.append(
            DailyBar(
                day=last.day,
                dt=dt,
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
    if drop_forming:
        end = compact_day(end_day) or (dailies[-1].day if dailies else "")
        out = drop_unclosed_week(out, end)
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


def _csv_missing_hint(p: Path) -> str:
    parent = p.parent
    if parent.is_dir():
        names = [x.name for x in sorted(parent.glob("*.csv"))]
        if names:
            hint = "; existing csv: " + ", ".join(names[:12])
            if len(names) > 12:
                hint += ", ..."
            return hint
        return ""
    return "; directory missing: %s" % parent


_PEEK_HEAD = 8192
_PEEK_TAIL = 2048


def _try_decode_bytes(data: bytes, encodings: tuple[str, ...], trim: str) -> str:
    """trim=end 丢掉尾部残缺字节；trim=start 丢掉头部残缺字节。"""
    last_err: UnicodeDecodeError | None = None
    for enc in encodings:
        for i in range(0, 4):
            if trim == "end":
                piece = data if i == 0 else data[:-i]
            else:
                piece = data if i == 0 else data[i:]
            if not piece:
                continue
            try:
                return piece.decode(enc)
            except UnicodeDecodeError as e:
                last_err = e
                continue
    raise ValueError("cannot decode csv bytes") from last_err


def _csv_header_index(header_line: str) -> dict[str, int]:
    row = next(csv.reader([header_line]))
    return {str(c).strip().lower(): i for i, c in enumerate(row) if c is not None}


def _csv_cell(row: list[str], keys: dict[str, int], *names: str) -> str:
    for name in names:
        i = keys.get(name.lower())
        if i is not None and 0 <= i < len(row):
            return str(row[i] or "")
    return ""


def _peek_daily_row(line: str, keys: dict[str, int]) -> tuple[str, str] | None:
    """有效日线行 → (stock, yyyymmdd)；周线 / 空行 / 无日期则跳过。"""
    raw = str(line or "").strip()
    if not raw:
        return None
    row = next(csv.reader([raw]))
    if not row or all(not str(c).strip() for c in row):
        return None
    period_raw = str(_csv_cell(row, keys, "period") or "").strip().lower()
    if period_raw and _is_weekly_period(period_raw):
        return None
    dt = parse_bar_datetime(_csv_cell(row, keys, "datetime", "time", "date", "stime"))
    if dt is None:
        return None
    close = _float(_csv_cell(row, keys, "close"))
    if close <= 0:
        return None
    code = str(_csv_cell(row, keys, "stock", "code") or "").strip().upper()
    return code, dt.strftime("%Y%m%d")


def stock_code_from_csv_name(path: str | Path) -> str:
    """`000166_SZ_1d_....csv` → `000166.SZ`。"""
    m = _DAILY_NAME_RE.search(Path(path).name)
    if not m:
        return ""
    return "%s.%s" % (m.group(1), m.group(2).upper())


def _data_line_starts(data: bytes) -> list[int]:
    """不含表头的数据行起始偏移。"""
    first_nl = data.find(b"\n")
    if first_nl < 0:
        return []
    starts: list[int] = []
    i = first_nl + 1
    n = len(data)
    while i < n:
        starts.append(i)
        j = data.find(b"\n", i)
        if j < 0:
            break
        i = j + 1
    return starts


def _data_line_text(data: bytes, starts: list[int], index: int) -> str:
    a = starts[index]
    b = starts[index + 1] if index + 1 < len(starts) else len(data)
    piece = data[a:b]
    text = _try_decode_bytes(piece, ("utf-8-sig", "utf-8", "gbk"), trim="end")
    return text.strip("\r\n")


def _first_valid_from_start(
    data: bytes, keys: dict[str, int], starts: list[int]
) -> tuple[str, str] | None:
    """从头跳过上市前 close=0，碰到第一根有效日 K 即停。"""
    for i in range(len(starts)):
        parsed = _peek_daily_row(_data_line_text(data, starts, i), keys)
        if parsed is not None:
            return parsed
    return None


def _last_valid_from_end(
    data: bytes, keys: dict[str, int], starts: list[int]
) -> tuple[str, str] | None:
    """从末尾跳过退市后 close=0，碰到最后一根有效日 K 即停。"""
    for i in range(len(starts) - 1, -1, -1):
        parsed = _peek_daily_row(_data_line_text(data, starts, i), keys)
        if parsed is not None:
            return parsed
    return None


def peek_daily_csv_meta(path: str | Path) -> dict[str, Any]:
    """头尾窗取区间；头窗全是占位 0 时从头扫到第一根有效日 K。不物化 OHLCV。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p) + _csv_missing_hint(p))
    data = p.read_bytes()
    if not data:
        raise ValueError("empty csv: %s" % p)
    n_nl = data.count(b"\n")
    if data[-1:] not in (b"\n", b"\r"):
        n_nl += 1
    n = max(0, n_nl - 1)
    head = data[:_PEEK_HEAD]
    tail = data[-_PEEK_TAIL:] if len(data) > _PEEK_TAIL else data

    head_text = _try_decode_bytes(head, ("utf-8-sig", "utf-8", "gbk"), trim="end")
    head_lines = head_text.splitlines()
    # 大文件时 head 末行可能被截断
    if len(head) >= _PEEK_HEAD and head_lines and not (
        head_text.endswith("\n") or head_text.endswith("\r")
    ):
        head_lines = head_lines[:-1]
    if not head_lines:
        raise ValueError("no header in %s" % p)
    keys = _csv_header_index(head_lines[0])
    first: tuple[str, str] | None = None
    for line in head_lines[1:]:
        parsed = _peek_daily_row(line, keys)
        if parsed is not None:
            first = parsed
            break
    last: tuple[str, str] | None = None
    if len(data) <= _PEEK_HEAD:
        body = head_lines[1:]
    else:
        # 滑动尾窗不一定落在行首，丢掉首段残缺行；只要最后一行完整即可
        tail_text = _try_decode_bytes(tail, ("utf-8", "gbk"), trim="start")
        body = tail_text.splitlines()
        if body:
            body = body[1:]
    for line in reversed(body):
        parsed = _peek_daily_row(line, keys)
        if parsed is not None:
            last = parsed
            break
    if first is None or last is None:
        starts = _data_line_starts(data)
        if first is None:
            first = _first_valid_from_start(data, keys, starts)
        if last is None:
            last = _last_valid_from_end(data, keys, starts)
    if first is None or last is None or n <= 0:
        raise ValueError("no daily bars in %s" % p)
    code = first[0] or last[0] or stock_code_from_csv_name(p)
    if not code:
        raise ValueError("stock code missing in %s" % p)
    return {
        "stock": code,
        "start": first[1],
        "end": last[1],
        "n": int(n),
        "path": str(p.resolve()),
    }


def _load_ohlcv_csv(
    path: str | Path,
    stock: str = "",
    want_period: str = "1d",
) -> tuple[str, list[DailyBar]]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p) + _csv_missing_hint(p))
    weekly_want = _is_weekly_period(want_period)
    rows = csv.DictReader(_open_csv(p))
    want = str(stock or "").strip().upper()
    bars: list[DailyBar] = []
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

        period_raw = str(col("period") or "").strip().lower()
        if period_raw:
            is_week = _is_weekly_period(period_raw)
        else:
            is_week = weekly_want
        if weekly_want != is_week:
            continue
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
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
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
                period="1w" if weekly_want else "1d",
            )
        )
    if not bars:
        raise ValueError("no %s bars in %s" % ("weekly" if weekly_want else "daily", p))
    bars.sort(key=lambda b: b.day)
    dedup: dict[str, DailyBar] = {}
    for b in bars:
        dedup[b.day] = b
    bars = [dedup[k] for k in sorted(dedup)]
    out_stock = want or inferred or bars[0].stock
    if not out_stock:
        raise ValueError("stock code missing; pass --stock or CSV stock column")
    return out_stock, bars


def load_daily_csv(path: str | Path, stock: str = "") -> tuple[str, list[DailyBar]]:
    """读取 KlineDump 日线 CSV。返回 (stock, bars)。"""
    return _load_ohlcv_csv(path, stock=stock, want_period="1d")


def load_weekly_csv(path: str | Path, stock: str = "") -> tuple[str, list[DailyBar]]:
    """读取 KlineDump 周线 CSV。返回 (stock, bars)。"""
    return _load_ohlcv_csv(path, stock=stock, want_period="1w")


def find_weekly_csv(daily_path: str | Path, stock: str = "") -> Path | None:
    """同目录下找 `{code}_1w_*.csv`，与日线文件前缀一致时优先。"""
    p = Path(daily_path)
    parent = p.parent
    if not parent.is_dir():
        return None
    prefixes: list[str] = []
    name = p.name
    if "_1d_" in name:
        prefixes.append(name.split("_1d_")[0])
    tag = str(stock or "").strip().upper().replace(".", "_")
    if tag and tag not in prefixes:
        prefixes.append(tag)
    matches: list[Path] = []
    for pref in prefixes:
        matches.extend(sorted(parent.glob("%s_1w_*.csv" % pref)))
    if not matches:
        return None
    uniq = sorted(set(matches), key=lambda x: x.name)
    return uniq[-1]


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
    def __init__(
        self,
        bars: Sequence[DailyBar],
        stock: str,
        weekly: Sequence[DailyBar] | None = None,
    ):
        self.bars = list(bars)
        self.weekly = list(weekly) if weekly else []
        self.stock = str(stock).strip().upper()
        self._daily = _ColPack(self.bars)
        if self.weekly:
            self._weekly = _ColPack(self.weekly)
        else:
            formed = aggregate_weekly(self.bars, drop_forming=False)
            self._weekly = _ColPack(formed)

    def slice_daily(
        self,
        end_day: str,
        start_day: str = "",
        count: int | None = None,
    ) -> list[DailyBar]:
        lo, hi = self._daily.bounds(end_day, start_day, count)
        return self._daily.bars[lo:hi]

    def frame(
        self,
        period: str,
        end_time: str,
        count: int | None,
        fields: Iterable[str] | None = None,
        start_time: str = "",
        stock: str = "",
    ) -> BarFrame:
        cols = list(fields) if fields else list(OHLC_FIELDS)
        if _is_weekly_period(period):
            lo, hi = self._weekly.bounds(end_time, start_time, count=None)
            hi = self._weekly.drop_forming_hi(lo, hi, end_time)
            if count is not None and int(count) > 0 and hi - lo > int(count):
                lo = hi - int(count)
            return self._weekly.as_frame(lo, hi, cols)
        lo, hi = self._daily.bounds(end_time, start_time, count)
        return self._daily.as_frame(lo, hi, cols)

    def ohlcv(
        self,
        period: str,
        end_day: str,
        count: int | None = None,
        start_day: str = "",
    ):
        """与 frame() 相同切片，返回 (open, high, low, close, volume) 的 numpy 视图。"""
        pack = self.ohlcv_with_days(period, end_day, count, start_day)
        if pack is None:
            return None
        return pack[:5]

    def ohlcv_with_days(
        self,
        period: str,
        end_day: str,
        count: int | None = None,
        start_day: str = "",
    ):
        """返回 (open, high, low, close, volume, days)。"""
        if _is_weekly_period(period):
            lo, hi = self._weekly.bounds(end_day, start_day, count=None)
            hi = self._weekly.drop_forming_hi(lo, hi, end_day)
            if count is not None and int(count) > 0 and hi - lo > int(count):
                lo = hi - int(count)
            return self._weekly.as_ohlcv_with_days(lo, hi)
        lo, hi = self._daily.bounds(end_day, start_day, count)
        return self._daily.as_ohlcv_with_days(lo, hi)
