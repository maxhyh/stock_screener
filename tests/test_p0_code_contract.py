# -*- coding: utf-8 -*-
"""P0: 数据契约与执行约束关键回归测试。"""

from __future__ import annotations

import importlib

import pandas as pd

import core.execution.paper_broker as paper_broker
import core.mfts_screener as screener
import core.risk.pretrade as pretrade
import scripts.quant_portfolio_backtest as qpb
import scripts.quant_p2_paper_trade as p2_script
from config.settings import resolve_default_label_horizon
from utils.code_utils import normalize_ts_code, normalize_ts_code_series


def test_normalize_ts_code_handles_prefixed_and_suffix_formats():
    assert normalize_ts_code("sz000001") == "000001"
    assert normalize_ts_code("000001.SZ") == "000001"
    assert normalize_ts_code("sh600000") == "600000"
    assert normalize_ts_code("bj920000") == "920000"
    assert normalize_ts_code(None) == ""


def test_normalize_ts_code_series_keeps_invalid_as_empty():
    s = pd.Series(["sz000001", "000002.SZ", None, "nan", ""])
    out = normalize_ts_code_series(s)
    assert out.iloc[0] == "000001"
    assert out.iloc[1] == "000002"
    assert out.iloc[2] == ""
    assert out.iloc[3] == ""
    assert out.iloc[4] == ""


def test_load_metadata_normalizes_code_keys(monkeypatch):
    class FakeGateway:
        def available_trade_dates(self):
            return ["2026-04-08"]

        def load_stock_info(self, _asof_date, *, include_bj9):
            assert include_bj9 is True
            return pd.DataFrame(
                {
                    "ts_code": ["sz000001", "000002.SZ", "bj920000"],
                    "name": ["平安银行", "万科A", "北交测试"],
                    "industry": ["银行", "地产", ""],
                }
            )

    monkeypatch.setattr(screener, "AShareMarketDataGateway", lambda: FakeGateway())

    meta = screener.load_metadata()
    assert "000001" in meta
    assert "000002" in meta
    assert "920000" in meta
    assert meta["000001"]["name"] == "平安银行"


def test_load_metadata_reads_ods_asof_snapshot(monkeypatch):
    class FakeGateway:
        def available_trade_dates(self):
            return ["2026-04-08"]

        def load_stock_info(self, asof_date, *, include_bj9):
            assert str(asof_date).startswith("2026-04-08")
            assert include_bj9 is True
            return pd.DataFrame(
                {
                    "ts_code": ["sz000001", "000002.SZ"],
                    "name": ["平安银行", "万科A"],
                    "industry": ["银行", "地产"],
                }
            )

    monkeypatch.setattr(screener, "AShareMarketDataGateway", lambda: FakeGateway(), raising=False)

    meta = screener.load_metadata("2026-04-08")

    assert meta["000001"] == {"name": "平安银行", "industry": "银行"}


def test_backtest_industry_map_delegates_to_ods(monkeypatch):
    seen = {}

    def fake_load_industry_map(*, asof_date=None):
        seen["asof_date"] = asof_date
        return {"000001": "银行", "600000": "非银金融"}

    monkeypatch.setattr(qpb, "load_ods_industry_map", fake_load_industry_map)
    ind_map = qpb._load_industry_map("2026-04-08")

    assert ind_map.get("000001") == "银行"
    assert ind_map.get("600000") == "非银金融"
    assert seen["asof_date"] == "2026-04-08"


def test_pretrade_industry_map_reads_ods_metadata(monkeypatch):
    class FakeGateway:
        def available_trade_dates(self):
            return ["2026-04-08"]

        def load_stock_info(self, asof_date, *, include_bj9):
            assert str(asof_date).startswith("2026-04-08")
            assert include_bj9 is True
            return pd.DataFrame({"ts_code": ["sz000001", "sh600000"], "industry": ["银行", "非银金融"]})

    monkeypatch.setattr(pretrade, "AShareMarketDataGateway", lambda: FakeGateway(), raising=False)

    ind_map = pretrade.load_industry_map(asof_date="2026-04-08")

    assert ind_map == {"000001": "银行", "600000": "非银金融"}


def test_daily_verify_defaults_align_profile(monkeypatch):
    monkeypatch.delenv("MFTS_VERIFY_LABEL_MODE", raising=False)
    monkeypatch.delenv("MFTS_VERIFY_LABEL_HORIZON", raising=False)

    import scripts.daily_verify as dv

    dv = importlib.reload(dv)
    assert dv.DEFAULT_VERIFY_LABEL_MODE == "open_to_open"
    assert dv.DEFAULT_VERIFY_LABEL_HORIZON == int(resolve_default_label_horizon(fallback=8))


def test_exec_constraints_limit_lock_behavior():
    lock_up = pd.Series({"prev_close": 10.0, "open": 11.0, "high": 11.0, "low": 11.0, "vol": 1000.0, "amount": 100000.0})
    lock_down = pd.Series({"prev_close": 10.0, "open": 9.0, "high": 9.0, "low": 9.0, "vol": 1000.0, "amount": 100000.0})
    normal = pd.Series({"prev_close": 10.0, "open": 10.2, "high": 10.4, "low": 10.0, "vol": 1000.0, "amount": 100000.0})

    assert qpb._can_enter_long(lock_up, "000001", "平安银行") is False
    assert qpb._can_exit_long(lock_down, "000001", "平安银行") is False
    assert qpb._can_exit_long(normal, "000001", "平安银行") is True


def test_missing_volume_with_positive_amount_is_tradable():
    normal_missing_vol = pd.Series(
        {
            "prev_close": 10.0,
            "open": 10.2,
            "high": 10.5,
            "low": 10.1,
            "vol": float("nan"),
            "amount": 100000.0,
        }
    )

    assert paper_broker._can_enter(normal_missing_vol, "000001", "平安银行") is True
    assert p2_script._can_enter(normal_missing_vol, "000001", "平安银行") is True
    assert qpb._can_enter_long(normal_missing_vol, "000001", "平安银行") is True
