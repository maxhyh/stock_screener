# -*- coding: utf-8 -*-
"""Canonical, read-only A-share ODS market-data gateway."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from core.data.ashare_ods_loader import AShareOdsLoader, normalize_ods_trade_date
from utils.market_data_units import normalize_amount_volume_units


class AShareMarketDataGateway:
    """Expose ODS market bars and sessions with reproducible data lineage."""

    def __init__(self, data_root: str | Path | None = None) -> None:
        self.loader = AShareOdsLoader(data_root)

    @property
    def data_root(self) -> Path:
        return self.loader.data_root.resolve()

    def available_trade_dates(self, start: object | None = None, end: object | None = None) -> list[str]:
        """Return dates with both a trading-calendar session and daily bars."""
        bar_dates = self.loader.available_trade_dates("daily_bars")
        if start is not None:
            start_date = normalize_ods_trade_date(start)
            bar_dates = [date for date in bar_dates if date >= start_date]
        if end is not None:
            end_date = normalize_ods_trade_date(end)
            bar_dates = [date for date in bar_dates if date <= end_date]
        if not bar_dates:
            return []

        calendar = self.loader.read_dataset("trading_calendar", bar_dates[0], bar_dates[-1])
        if calendar.empty or "trade_date" not in calendar.columns or "is_trading_day" not in calendar.columns:
            return bar_dates
        calendar_dates = pd.to_datetime(calendar["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        trading = pd.Series(calendar["is_trading_day"]).fillna(False).astype(bool)
        valid = set(calendar_dates.loc[trading].dropna().astype(str))
        calendar_covered = set(calendar_dates.dropna().astype(str))
        # The shared calendar is currently a sparse snapshot series. It can
        # validate a fully covered interval, but must not erase otherwise
        # complete daily-bar sessions in historical replay windows.
        if not set(bar_dates).issubset(calendar_covered):
            return bar_dates
        return [date for date in bar_dates if date in valid]

    def _expand_session_window(
        self,
        start: object,
        end: object,
        *,
        lookback_sessions: int,
        forward_sessions: int,
    ) -> tuple[str, str, list[str]]:
        requested_start = normalize_ods_trade_date(start)
        requested_end = normalize_ods_trade_date(end)
        sessions = self.available_trade_dates()
        requested = [date for date in sessions if requested_start <= date <= requested_end]
        if not requested:
            return requested_start, requested_end, []
        first = sessions.index(requested[0])
        last = sessions.index(requested[-1])
        expanded_start = sessions[max(0, first - max(0, int(lookback_sessions)))]
        expanded_end = sessions[min(len(sessions) - 1, last + max(0, int(forward_sessions)))]
        return expanded_start, expanded_end, requested

    def _lineage(self, start: str, end: str, *, include_bj9: bool, requested_start: str, requested_end: str) -> dict[str, object]:
        datasets = ["daily_bars", "daily_basic", "daily_adj_factor", "daily_limits", "instrument_master"]
        identities: list[dict[str, str]] = []
        for dataset in datasets:
            for part in self.loader.selected_partitions(dataset, start, end):
                identities.append({"dataset": dataset, "trade_date": part.trade_date, "snapshot": part.snapshot})
        encoded = json.dumps(identities, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return {
            "data_source": "ashare_ods",
            "data_root": str(self.data_root),
            "snapshot_policy": "latest_snapshot_per_trade_date",
            "price_mode": "unadjusted",
            "requested_start": requested_start,
            "requested_end": requested_end,
            "expanded_start": start,
            "expanded_end": end,
            "include_bj9": bool(include_bj9),
            "datasets": datasets,
            "snapshot_count": len(identities),
            "snapshot_digest": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        }

    def load_bars(
        self,
        start: object,
        end: object,
        *,
        include_bj9: bool = False,
        lookback_sessions: int = 0,
        forward_sessions: int = 0,
    ) -> pd.DataFrame:
        """Load normalized unadjusted bars over an explicit trading-session window."""
        requested_start = normalize_ods_trade_date(start)
        requested_end = normalize_ods_trade_date(end)
        expanded_start, expanded_end, _ = self._expand_session_window(
            requested_start,
            requested_end,
            lookback_sessions=lookback_sessions,
            forward_sessions=forward_sessions,
        )
        frame = self.loader.load_daily_panel(expanded_start, expanded_end, include_bj9=include_bj9)
        frame = normalize_amount_volume_units(frame)
        frame.attrs["market_data_lineage"] = self._lineage(
            expanded_start,
            expanded_end,
            include_bj9=include_bj9,
            requested_start=requested_start,
            requested_end=requested_end,
        )
        return frame

    def load_stock_info(self, asof_date: object, *, include_bj9: bool = False) -> pd.DataFrame:
        """Load instrument metadata as of the requested date with ODS lineage."""
        frame = self.loader.load_stock_info(asof_date, include_bj9=include_bj9)
        date = normalize_ods_trade_date(asof_date)
        frame.attrs["market_data_lineage"] = self._lineage(
            date,
            date,
            include_bj9=include_bj9,
            requested_start=date,
            requested_end=date,
        )
        return frame

    def daily_bar_counts(
        self,
        trade_dates: list[str],
        *,
        include_bj9: bool = False,
    ) -> dict[str, int]:
        """Return per-session instrument coverage without loading the full panel.

        This is intentionally a read-only, partition-level check for pipeline
        coverage gates. It does not join metadata or use future observations.
        """
        counts: dict[str, int] = {}
        for trade_date in trade_dates:
            part = self.loader.latest_partition("daily_bars", trade_date)
            if part is None:
                counts[trade_date] = 0
                continue
            files = sorted(part.path.glob("*.parquet"))
            if not files:
                counts[trade_date] = 0
                continue
            frame = pd.read_parquet(files[0], columns=["instrument_id"])
            codes = frame["instrument_id"].astype(str).str.strip()
            if not include_bj9:
                codes = codes.loc[~codes.str.startswith(("8", "9"), na=False)]
            counts[trade_date] = int(codes.nunique())
        return counts


def load_execution_bars(
    start: object,
    end: object,
    *,
    data_root: str | Path | None = None,
    include_bj9: bool = False,
    lookback_sessions: int = 20,
    forward_sessions: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Return normalized bars and the shared P2/backtest execution index."""
    market = AShareMarketDataGateway(data_root).load_bars(
        start,
        end,
        include_bj9=include_bj9,
        lookback_sessions=lookback_sessions,
        forward_sessions=forward_sessions,
    )
    work = market.copy()
    if work.empty:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "vol", "amount"])
        empty.index = pd.MultiIndex.from_arrays([[], []], names=["trade_date", "code"])
        return work, empty, dict(market.attrs.get("market_data_lineage", {}))
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["code"] = work["ts_code"].astype(str).str.strip()
    for column in ("open", "high", "low", "close", "vol", "amount"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["trade_date", "code"]).sort_values(["code", "trade_date"]).reset_index(drop=True)
    work["prev_close"] = work.groupby("code", observed=True)["close"].shift(1)
    work["amount_ma20"] = (
        work.groupby("code", observed=True)["amount"]
        .transform(lambda x: x.rolling(20, min_periods=5).mean())
        .fillna(0.0)
    )
    work["amount_min5"] = work.groupby("code", observed=True)["amount"].transform(lambda x: x.rolling(5, min_periods=1).min())
    work["amount_min10"] = (
        work.groupby("code", observed=True)["amount"]
        .transform(lambda x: x.rolling(10, min_periods=3).min())
        .fillna(work["amount_min5"])
    )
    lineage = dict(market.attrs.get("market_data_lineage", {}))
    work.attrs["market_data_lineage"] = lineage
    return work, work.set_index(["trade_date", "code"]).sort_index(), lineage


__all__ = ["AShareMarketDataGateway", "load_execution_bars"]
