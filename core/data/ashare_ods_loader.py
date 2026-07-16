# -*- coding: utf-8 -*-
"""Read-only adapter for the shared A-share ODS parquet data root."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd


DEFAULT_ASHARE_DATA_ROOT = Path("/Users/max/Data/ashare-source-data")


def get_ashare_data_root() -> Path:
    """Return the shared data root, preferring ``ASHARE_DATA_ROOT``."""
    raw = os.environ.get("ASHARE_DATA_ROOT", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_ASHARE_DATA_ROOT


def normalize_ods_trade_date(value: object) -> str:
    """Normalize project date inputs to ODS partition format YYYY-MM-DD."""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    s = str(value).strip()
    if not s:
        raise ValueError("trade_date is empty")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    ts = pd.Timestamp(s)
    return ts.strftime("%Y-%m-%d")


def _date_range(start: object, end: object) -> list[str]:
    start_date = pd.Timestamp(normalize_ods_trade_date(start))
    end_date = pd.Timestamp(normalize_ods_trade_date(end))
    if end_date < start_date:
        raise ValueError(f"end date {end_date.date()} is before start date {start_date.date()}")
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start_date, end_date, freq="D")]


def _read_manifest(path: Path) -> dict:
    manifest = path / "manifest.json"
    if not manifest.exists():
        return {}
    return json.loads(manifest.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class OdsPartition:
    """A single ODS dataset/trade_date/snapshot partition."""

    dataset: str
    trade_date: str
    snapshot: str
    path: Path
    manifest: dict


class AShareOdsLoader:
    """
    Read-only loader for ``/ods`` partitioned A-share parquet datasets.

    The loader never writes to the shared data root. It selects the latest
    lexicographic snapshot for each requested trade date and maps the shared
    ODS schema into the legacy project panel schema where needed.
    """

    def __init__(self, data_root: str | Path | None = None) -> None:
        self.data_root = Path(data_root).expanduser() if data_root is not None else get_ashare_data_root()
        self.ods_root = self.data_root / "ods"

    def dataset_dir(self, dataset: str) -> Path:
        return self.ods_root / dataset

    def latest_partition(self, dataset: str, trade_date: object) -> OdsPartition | None:
        date = normalize_ods_trade_date(trade_date)
        partition_dir = self.dataset_dir(dataset) / f"trade_date={date}"
        if not partition_dir.exists():
            return None
        snapshots = sorted(p for p in partition_dir.glob("snapshot=*") if p.is_dir())
        if not snapshots:
            return None
        path = snapshots[-1]
        snapshot = path.name.split("=", 1)[1]
        return OdsPartition(
            dataset=dataset,
            trade_date=date,
            snapshot=snapshot,
            path=path,
            manifest=_read_manifest(path),
        )

    def available_trade_dates(self, dataset: str) -> list[str]:
        root = self.dataset_dir(dataset)
        if not root.exists():
            return []
        dates: list[str] = []
        for child in root.glob("trade_date=*"):
            if child.is_dir():
                dates.append(child.name.split("=", 1)[1])
        return sorted(dates)

    def selected_partitions(
        self,
        dataset: str,
        start_date: object,
        end_date: object,
    ) -> list[OdsPartition]:
        """Return latest snapshot partitions selected for an inclusive date range."""
        start = normalize_ods_trade_date(start_date)
        end = normalize_ods_trade_date(end_date)
        if end < start:
            raise ValueError(f"end date {end} is before start date {start}")
        return [
            part
            for date in self.available_trade_dates(dataset)
            if start <= date <= end
            if (part := self.latest_partition(dataset, date)) is not None
        ]

    def read_dataset(
        self,
        dataset: str,
        start_date: object,
        end_date: object | None = None,
        *,
        columns: Sequence[str] | None = None,
        date_filter: bool = True,
    ) -> pd.DataFrame:
        """
        Read latest ODS snapshots for a dataset over a date range.

        Missing calendar days are skipped because ODS datasets are partitioned
        by trading or event dates, not every natural day.
        """
        end = start_date if end_date is None else end_date
        frames: list[pd.DataFrame] = []
        for date in _date_range(start_date, end):
            part = self.latest_partition(dataset, date)
            if part is None:
                continue
            files = sorted(part.path.glob("*.parquet"))
            if not files:
                continue
            frame = pd.read_parquet(files[0], columns=list(columns) if columns else None)
            if date_filter and "trade_date" in frame.columns:
                frame = frame.loc[
                    pd.to_datetime(frame["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d") == date
                ].copy()
            frames.append(frame)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def read_latest_asof(
        self,
        dataset: str,
        asof_date: object,
        *,
        columns: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """Read the latest available partition whose trade_date is <= asof_date."""
        asof = normalize_ods_trade_date(asof_date)
        dates = [d for d in self.available_trade_dates(dataset) if d <= asof]
        if not dates:
            return pd.DataFrame()
        return self.read_dataset(dataset, dates[-1], dates[-1], columns=columns, date_filter=False)

    def load_daily_panel(
        self,
        start_date: object,
        end_date: object,
        *,
        include_bj9: bool = False,
    ) -> pd.DataFrame:
        """
        Load a legacy-compatible daily panel from ODS daily datasets.

        Output preserves project-era columns such as ``ts_code`` and ``vol``
        while retaining useful ODS metadata such as limits and instrument info.
        """
        bars = self.read_dataset("daily_bars", start_date, end_date)
        if bars.empty:
            return pd.DataFrame()

        panel = self._normalize_bars(bars)
        panel = self._left_join_daily(panel, "daily_basic", start_date, end_date)
        panel = self._left_join_daily(panel, "daily_adj_factor", start_date, end_date)
        panel = self._left_join_daily(panel, "daily_limits", start_date, end_date)
        panel = self._left_join_master(panel, end_date)

        if not include_bj9:
            panel = self._filter_bj9(panel)

        panel = panel.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        return panel

    def load_stock_info(self, asof_date: object, *, include_bj9: bool = False) -> pd.DataFrame:
        """Load legacy-compatible stock metadata from instrument_master."""
        master = self.read_latest_asof("instrument_master", asof_date)
        if master.empty:
            return pd.DataFrame(columns=["ts_code", "name", "industry"])
        out = master.rename(columns={"instrument_id": "ts_code", "display_name": "name"}).copy()
        keep = [
            c
            for c in [
                "ts_code",
                "ticker",
                "exchange",
                "symbol",
                "name",
                "board",
                "industry",
                "area",
                "list_status",
                "is_hs",
            ]
            if c in out.columns
        ]
        out = out[keep]
        if not include_bj9:
            out = self._filter_bj9(out)
        return out.sort_values("ts_code").reset_index(drop=True)

    def _normalize_bars(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.rename(columns={"instrument_id": "ts_code", "volume": "vol"}).copy()
        out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
        if "ts_code" in out.columns:
            out["ts_code"] = out["ts_code"].astype(str).str.strip()
        return out

    def _left_join_daily(
        self,
        panel: pd.DataFrame,
        dataset: str,
        start_date: object,
        end_date: object,
    ) -> pd.DataFrame:
        other = self.read_dataset(dataset, start_date, end_date)
        if other.empty:
            return panel
        other = other.rename(columns={"instrument_id": "ts_code", "volume": "vol"}).copy()
        other["trade_date"] = pd.to_datetime(other["trade_date"], errors="coerce")
        drop_dupes = [c for c in other.columns if c in panel.columns and c not in {"ts_code", "trade_date"}]
        if drop_dupes:
            other = other.drop(columns=drop_dupes)
        return panel.merge(other, on=["ts_code", "trade_date"], how="left")

    def _left_join_master(self, panel: pd.DataFrame, asof_date: object) -> pd.DataFrame:
        master = self.load_stock_info(asof_date, include_bj9=True)
        if master.empty:
            return panel
        drop_dupes = [c for c in master.columns if c in panel.columns and c != "ts_code"]
        if drop_dupes:
            master = master.drop(columns=drop_dupes)
        return panel.merge(master, on="ts_code", how="left")

    def _filter_bj9(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or "ts_code" not in frame.columns:
            return frame
        code = frame["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
        mask = ~code.str.startswith("9")
        if "exchange" in frame.columns:
            mask &= frame["exchange"].astype(str).str.upper().ne("BJ")
        return frame.loc[mask].copy()


__all__ = [
    "AShareOdsLoader",
    "DEFAULT_ASHARE_DATA_ROOT",
    "OdsPartition",
    "get_ashare_data_root",
    "normalize_ods_trade_date",
]
