# -*- coding: utf-8 -*-
"""P0: 数据契约与执行约束关键回归测试。"""

from __future__ import annotations

import importlib

import pandas as pd

import core.mfts_screener as screener
import scripts.quant_portfolio_backtest as qpb
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


def test_load_metadata_normalizes_code_keys(monkeypatch, tmp_path):
    p = tmp_path / "stock_info.csv"
    pd.DataFrame(
        {
            "ts_code": ["sz000001", "000002.SZ", "bj920000"],
            "name": ["平安银行", "万科A", "北交测试"],
            "industry": ["银行", "地产", ""],
        }
    ).to_csv(p, index=False, encoding="utf-8")
    monkeypatch.setattr(screener, "META_FILE", str(p))

    meta = screener.load_metadata()
    assert "000001" in meta
    assert "000002" in meta
    assert "920000" in meta
    assert meta["000001"]["name"] == "平安银行"


def test_industry_map_supports_prefixed_codes(monkeypatch, tmp_path):
    data_dir = tmp_path
    p = data_dir / "stock_info.csv"
    pd.DataFrame(
        {
            "ts_code": ["sz000001", "sh600000", "bj920000"],
            "industry": ["银行", "非银金融", None],
        }
    ).to_csv(p, index=False, encoding="utf-8")

    monkeypatch.setattr(qpb, "DATA_DIR", str(data_dir))
    ind_map = qpb._load_industry_map()

    assert ind_map.get("000001") == "银行"
    assert ind_map.get("600000") == "非银金融"
    assert ind_map.get("920000", "") == ""


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
