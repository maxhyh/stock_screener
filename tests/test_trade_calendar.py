# -*- coding: utf-8 -*-
"""交易日历工具测试。"""

from __future__ import annotations

import datetime as dt

import scripts.daily_all as daily_all
import scripts.daily_incremental_update as daily_incremental_update
from utils.trade_calendar import nearest_trade_day_on_or_before, trade_dates_between


def test_trade_dates_between_uses_known_trade_days():
    out = trade_dates_between(
        "20260403",
        "20260408",
        known_dates=["20260403", "20260407", "20260408"],
        include_remote=False,
    )
    assert out == ["20260407", "20260408"]


def test_nearest_trade_day_on_or_before_skips_holiday_with_known_dates():
    out = nearest_trade_day_on_or_before(
        "20260406",
        known_dates=["20260403", "20260407", "20260408"],
        include_remote=False,
    )
    assert out == dt.date(2026, 4, 3)


def test_daily_all_get_auto_target_date_uses_ods_sessions(monkeypatch):
    class _FakeDateTime:
        @classmethod
        def now(cls):
            return dt.datetime(2026, 4, 6, 19, 0, 0)  # 节假日周一晚间

    monkeypatch.setattr(daily_all, "datetime", _FakeDateTime)
    class _Gateway:
        def available_trade_dates(self, *, end=None):
            assert end == "2026-04-06"
            return ["2026-04-03"]

    monkeypatch.setattr(daily_all, "AShareMarketDataGateway", _Gateway)
    assert daily_all.get_auto_target_date() == "20260403"


def test_incremental_update_latest_trade_date_uses_trade_calendar_helper(monkeypatch):
    class _FakeDate(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 4, 6)

    monkeypatch.setattr(daily_incremental_update.datetime, "date", _FakeDate)
    monkeypatch.setattr(
        daily_incremental_update,
        "nearest_trade_day_on_or_before",
        lambda target, parquet_file=None: dt.date(2026, 4, 3),
    )
    assert daily_incremental_update.get_latest_trade_date() == "20260403"
