# coding: utf-8
"""本地回测用的 QMT Context / passorder / 时间戳替身。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from market_csv import MarketStore, compact_day


def split_stock(stock: str) -> tuple[str, str]:
    s = str(stock or "").strip().upper()
    if "." in s:
        code, market = s.rsplit(".", 1)
        return code, market
    return s, "SH"


def timetag_to_datetime(tag: Any, fmt: str) -> str:
    raw = str(int(tag)) if str(tag).strip().lstrip("-").isdigit() else compact_day(str(tag))
    d = compact_day(raw)
    if len(str(raw)) >= 14 and str(raw).isdigit():
        dt = datetime.strptime(str(raw)[:14], "%Y%m%d%H%M%S")
    elif d:
        dt = datetime.strptime(d, "%Y%m%d").replace(hour=0, minute=0, second=0)
    else:
        dt = datetime.now()
    return dt.strftime(fmt)


def _as_tag(dt: datetime) -> int:
    return int(dt.strftime("%Y%m%d%H%M%S"))


def passorder(*_args: Any, **_kwargs: Any) -> None:
    return None


def download_history_data(*_args: Any, **_kwargs: Any) -> None:
    return None


def _parse_md_call(args: tuple, kwargs: dict) -> dict[str, Any]:
    fields = kwargs.get("fields")
    stock_code = kwargs.get("stock_code")
    period = kwargs.get("period")
    start_time = kwargs.get("start_time", "")
    end_time = kwargs.get("end_time")
    count = kwargs.get("count")
    if args:
        if fields is None and len(args) >= 1:
            fields = args[0]
        if stock_code is None and len(args) >= 2:
            stock_code = args[1]
        if period is None and len(args) >= 3:
            period = args[2]
        if "start_time" not in kwargs and len(args) >= 4:
            start_time = args[3]
        if end_time is None and len(args) >= 5:
            end_time = args[4]
        if count is None and len(args) >= 6:
            count = args[5]
    if isinstance(stock_code, (list, tuple)):
        stocks = [str(x) for x in stock_code]
    elif stock_code:
        stocks = [str(stock_code)]
    else:
        stocks = []
    if fields is None:
        fields = ["open", "high", "low", "close", "volume"]
    try:
        count_i = None if count is None else int(count)
    except (TypeError, ValueError):
        count_i = None
    return {
        "fields": list(fields),
        "stocks": stocks,
        "period": str(period or "1d"),
        "start_time": str(start_time or ""),
        "end_time": str(end_time or ""),
        "count": count_i,
    }


class MockContext:
    def __init__(self, store: MarketStore, walk_tags: list[int], stock: str):
        code, market = split_stock(stock)
        self.stockcode = code
        self.market = market
        self.period = "1d"
        self.do_back_test = True
        self._local_bt = True
        self.barpos = 0
        self.accountid = ""
        self.start = ""
        self.end = ""
        self._store = store
        self._walk_tags = list(walk_tags)
        self.run_time_calls = []

    def set_account(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set_universe(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def run_time(self, *args: Any, **kwargs: Any) -> None:
        self.run_time_calls.append((args, kwargs))
        return None

    def is_last_bar(self) -> bool:
        return False

    def get_bar_timetag(self, barpos: int | None = None) -> int:
        i = self.barpos if barpos is None else int(barpos)
        if i < 0 or i >= len(self._walk_tags):
            return 0
        return int(self._walk_tags[i])

    def walk_end_day(self) -> str:
        i = int(self.barpos)
        if i < 0 or i >= len(self._walk_tags):
            return ""
        return compact_day(str(self._walk_tags[i]))

    def ohlcv(self, period: str, count: int | None = None):
        end = self.walk_end_day()
        if not end:
            return None
        return self._store.ohlcv(period, end, count)

    def get_market_data_ex(self, *args: Any, **kwargs: Any):
        return self._md(*args, **kwargs)

    def get_market_data(self, *args: Any, **kwargs: Any):
        return self._md(*args, **kwargs)

    def _md(self, *args: Any, **kwargs: Any):
        spec = _parse_md_call(args, kwargs)
        stocks = spec["stocks"] or [self.stockcode + "." + self.market]
        out = {}
        for raw in stocks:
            frame = self._store.frame(
                period=spec["period"],
                end_time=spec["end_time"],
                count=spec["count"],
                fields=spec["fields"],
                start_time=spec["start_time"],
                stock=raw,
            )
            out[str(raw)] = frame
        return out


class BookMockContext(MockContext):
    """多标的 CSV 路由：组合 BOOK 回放。"""

    def __init__(
        self,
        stores: dict[str, MarketStore],
        walk_tags: list[int],
        chart_stock: str,
    ):
        chart = str(chart_stock or "").strip().upper()
        if not chart:
            chart = next(iter(stores))
        primary = stores.get(chart) or next(iter(stores.values()))
        super().__init__(primary, walk_tags, chart)
        self._stores = {str(k).strip().upper(): v for k, v in stores.items()}
        self.chart_stock = chart

    def _store_for(self, raw: str) -> MarketStore | None:
        key = str(raw or "").strip().upper()
        if key in self._stores:
            return self._stores[key]
        code, mkt = split_stock(key)
        alt = "%s.%s" % (code, mkt)
        return self._stores.get(alt)

    def _md(self, *args: Any, **kwargs: Any):
        spec = _parse_md_call(args, kwargs)
        stocks = spec["stocks"] or [self.chart_stock]
        out = {}
        for raw in stocks:
            st = self._store_for(str(raw))
            if st is None:
                continue
            frame = st.frame(
                period=spec["period"],
                end_time=spec["end_time"],
                count=spec["count"],
                fields=spec["fields"],
                start_time=spec["start_time"],
                stock=str(raw),
            )
            out[str(raw)] = frame
        return out


def inject_qmt_globals(ns: dict) -> None:
    ns["passorder"] = passorder
    ns["download_history_data"] = download_history_data
    ns["down_history_data"] = download_history_data
    ns["timetag_to_datetime"] = timetag_to_datetime
    ns["_LOCAL_BT"] = True
