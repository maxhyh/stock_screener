"""A股交易日辅助工具。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


def _coerce_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _weekday_fallback_dates(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def load_trade_dates_from_parquet(parquet_file: str | Path | None) -> list[date]:
    if not parquet_file:
        return []
    path = Path(parquet_file)
    if not path.exists():
        return []
    try:
        df = pd.read_parquet(path, columns=["trade_date"])
    except Exception:
        return []
    if df.empty or "trade_date" not in df.columns:
        return []
    dt = pd.to_datetime(df["trade_date"].astype(str), errors="coerce").dropna()
    if dt.empty:
        return []
    return sorted({x.date() for x in dt.tolist()})


def fetch_trade_dates_from_ak(
    *,
    start: object | None = None,
    end: object | None = None,
) -> list[date]:
    try:
        import akshare as ak
    except Exception:
        return []
    try:
        df = ak.tool_trade_date_hist_sina()
    except Exception:
        return []
    if df is None or df.empty:
        return []
    col = "trade_date" if "trade_date" in df.columns else df.columns[0]
    dt = pd.to_datetime(df[col], errors="coerce").dropna()
    if dt.empty:
        return []
    dates = sorted({x.date() for x in dt.tolist()})
    start_d = _coerce_date(start)
    end_d = _coerce_date(end)
    if start_d is not None:
        dates = [d for d in dates if d >= start_d]
    if end_d is not None:
        dates = [d for d in dates if d <= end_d]
    return dates


def get_trade_dates(
    *,
    start: object | None = None,
    end: object | None = None,
    parquet_file: str | Path | None = None,
    known_dates: Iterable[object] | None = None,
    include_remote: bool = True,
) -> list[date]:
    start_d = _coerce_date(start)
    end_d = _coerce_date(end)
    merged: set[date] = set()
    if known_dates is not None:
        merged.update(d for x in known_dates if (d := _coerce_date(x)) is not None)
    merged.update(load_trade_dates_from_parquet(parquet_file))
    if include_remote:
        merged.update(fetch_trade_dates_from_ak(start=start_d, end=end_d))
    if merged:
        dates = sorted(merged)
        if start_d is not None:
            dates = [d for d in dates if d >= start_d]
        if end_d is not None:
            dates = [d for d in dates if d <= end_d]
        return dates
    if start_d is None or end_d is None:
        return []
    return _weekday_fallback_dates(start_d, end_d)


def nearest_trade_day_on_or_before(
    target: object,
    *,
    parquet_file: str | Path | None = None,
    known_dates: Iterable[object] | None = None,
    include_remote: bool = True,
) -> date:
    target_d = _coerce_date(target)
    if target_d is None:
        raise ValueError("invalid target date")
    start = target_d - timedelta(days=370)
    dates = get_trade_dates(
        start=start,
        end=target_d,
        parquet_file=parquet_file,
        known_dates=known_dates,
        include_remote=include_remote,
    )
    if dates:
        return dates[-1]
    cur = target_d
    while cur.weekday() >= 5:
        cur -= timedelta(days=1)
    return cur


def previous_trade_day(
    target: object,
    *,
    parquet_file: str | Path | None = None,
    known_dates: Iterable[object] | None = None,
    include_remote: bool = True,
) -> date:
    target_d = _coerce_date(target)
    if target_d is None:
        raise ValueError("invalid target date")
    return nearest_trade_day_on_or_before(
        target_d - timedelta(days=1),
        parquet_file=parquet_file,
        known_dates=known_dates,
        include_remote=include_remote,
    )


def trade_dates_between(
    start_exclusive: object,
    end_inclusive: object,
    *,
    parquet_file: str | Path | None = None,
    known_dates: Iterable[object] | None = None,
    include_remote: bool = True,
) -> list[str]:
    start_d = _coerce_date(start_exclusive)
    end_d = _coerce_date(end_inclusive)
    if start_d is None or end_d is None or end_d <= start_d:
        return []
    dates = get_trade_dates(
        start=start_d + timedelta(days=1),
        end=end_d,
        parquet_file=parquet_file,
        known_dates=known_dates,
        include_remote=include_remote,
    )
    return [d.strftime("%Y%m%d") for d in dates if d > start_d]
