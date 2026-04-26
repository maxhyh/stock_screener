# -*- coding: utf-8 -*-
"""
技术指标计算测试

测试 RSI、MACD、KDJ 等指标的计算正确性
"""

import pytest
import pandas as pd
import numpy as np
import warnings
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.mfts_screener import calc_indicators


class TestRSI:
    """RSI 指标测试"""
    
    @pytest.mark.skip(reason="calc_indicators requires multi-stock data, single stock edge case not supported")
    def test_rsi_extreme_up(self):
        """连续上涨时 RSI 应偏高"""
        # 创建连续上涨数据 (需要足够多天数让 RSI 计算稳定)
        n = 50
        data = {
            'ts_code': ['TEST'] * n,
            'trade_date': pd.date_range('2025-01-01', periods=n),
            'open': [10 + i * 0.3 for i in range(n)],
            'high': [10.5 + i * 0.3 for i in range(n)],
            'low': [9.8 + i * 0.3 for i in range(n)],
            'close': [10.2 + i * 0.3 for i in range(n)],
            'vol': [1e6] * n,
            'amount': [1e7] * n,
            'pct_chg': [1.5] * n,
        }
        df = pd.DataFrame(data)
        df = calc_indicators(df)
        
        # RSI 应该存在且在合理范围内
        last_rsi = df['rsi'].iloc[-1]
        assert pd.notna(last_rsi), "RSI should be calculated"
        assert last_rsi > 50, f"RSI should be above 50 for uptrend, got {last_rsi}"
    
    @pytest.mark.skip(reason="calc_indicators requires multi-stock data, single stock edge case not supported")
    def test_rsi_extreme_down(self):
        """连续下跌时 RSI 应偏低"""
        n = 50
        data = {
            'ts_code': ['TEST'] * n,
            'trade_date': pd.date_range('2025-01-01', periods=n),
            'open': [30 - i * 0.2 for i in range(n)],
            'high': [30.2 - i * 0.2 for i in range(n)],
            'low': [29.5 - i * 0.2 for i in range(n)],
            'close': [29.8 - i * 0.2 for i in range(n)],
            'vol': [1e6] * n,
            'amount': [1e7] * n,
            'pct_chg': [-1.5] * n,
        }
        df = pd.DataFrame(data)
        df = calc_indicators(df)
        
        last_rsi = df['rsi'].iloc[-1]
        assert pd.notna(last_rsi), "RSI should be calculated"
        assert last_rsi < 50, f"RSI should be below 50 for downtrend, got {last_rsi}"


class TestMACD:
    """MACD 指标测试"""
    
    def test_macd_components_exist(self, sample_stock_data):
        """MACD 三个组件都应存在"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        assert 'macd' in df.columns
        assert 'macd_signal' in df.columns
        assert 'macd_hist' in df.columns
    
    def test_macd_hist_formula(self, sample_stock_data):
        """验证 MACD Histogram = MACD - Signal"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_idx = df['macd'].notna() & df['macd_signal'].notna()
        if valid_idx.sum() > 0:
            expected_hist = df.loc[valid_idx, 'macd'] - df.loc[valid_idx, 'macd_signal']
            actual_hist = df.loc[valid_idx, 'macd_hist']
            
            diff = (expected_hist - actual_hist).abs()
            assert (diff < 0.0001).all(), "MACD Hist calculation error"


class TestKDJ:
    """KDJ 指标测试"""
    
    def test_kdj_range(self, sample_stock_data):
        """K、D 值应在 0-100 范围内，J 值可超出"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_k = df['k_val'].dropna()
        valid_d = df['d_val'].dropna()
        
        assert (valid_k >= 0).all() and (valid_k <= 100).all()
        assert (valid_d >= 0).all() and (valid_d <= 100).all()
    
    def test_kdj_formula(self, sample_stock_data):
        """验证 J = 3K - 2D"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_idx = df['k_val'].notna() & df['d_val'].notna()
        if valid_idx.sum() > 0:
            expected_j = 3 * df.loc[valid_idx, 'k_val'] - 2 * df.loc[valid_idx, 'd_val']
            actual_j = df.loc[valid_idx, 'j_val']
            
            diff = (expected_j - actual_j).abs()
            assert (diff < 0.0001).all(), "KDJ J calculation error"


class TestATR:
    """ATR 指标测试"""
    
    def test_atr_positive(self, sample_stock_data):
        """ATR 应为正值"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_atr = df['atr'].dropna()
        assert (valid_atr > 0).all()
    
    def test_atr_percent(self, sample_stock_data):
        """ATR% 应在合理范围内"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_atr_pct = df['atr_percent'].dropna()
        # ATR% 通常在 0-20% 之间
        assert (valid_atr_pct > 0).all() and (valid_atr_pct < 30).all()


class TestADX:
    """ADX 指标测试"""
    
    def test_adx_range(self, sample_stock_data):
        """ADX 应在 0-100 范围内"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_adx = df['adx'].dropna()
        assert (valid_adx >= 0).all() and (valid_adx <= 100).all()
    
    def test_di_components(self, sample_stock_data):
        """+DI 和 -DI 应存在"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        assert 'plus_di' in df.columns
        assert 'minus_di' in df.columns


class TestBollingerBands:
    """布林带测试"""
    
    def test_bb_position_range(self, sample_stock_data):
        """BB Position 应在合理范围内"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_bb = df['bb_pos'].dropna()
        # BB Position 可能超出 0-100，允许更大容忍度
        # 只要大部分值在 -50 到 150 范围内即可
        in_range = (valid_bb >= -50) & (valid_bb <= 150)
        assert in_range.mean() > 0.90, f"BB Position out of range ratio: {1 - in_range.mean():.2%}"


class TestMovingAverages:
    """移动平均线测试"""
    
    def test_ma_ordering(self, sample_stock_data):
        """验证 MA 计算的连续性"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        # MA5 应该比 MA20 需要更少的数据点
        ma5_first_valid = df['ma5'].first_valid_index()
        ma20_first_valid = df['ma20'].first_valid_index()
        
        assert ma5_first_valid <= ma20_first_valid
    
    def test_volume_ma(self, sample_stock_data):
        """验证成交量 MA 计算"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        assert 'vol_ma5' in df.columns
        assert 'vol_ma20' in df.columns
        
        # 成交量 MA 应为正值
        valid_vol_ma = df['vol_ma20'].dropna()
        assert (valid_vol_ma > 0).all()


class TestVwap:
    """A股日线 VWAP 单位口径测试。"""

    def test_vwap_matches_price_when_amount_uses_rmb_and_vol_uses_hands(self):
        rows = []
        for code_idx, code in enumerate(["000001.SZ", "000002.SZ"]):
            base = 10.0 + code_idx
            for i in range(30):
                close = base + i * 0.1
                vol_hands = 1000 + i * 10
                rows.append(
                    {
                        "ts_code": code,
                        "trade_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=i),
                        "open": close * 0.99,
                        "high": close * 1.01,
                        "low": close * 0.98,
                        "close": close,
                        "vol": vol_hands,
                        "amount": close * vol_hands * 100.0,
                        "pct_chg": 0.0 if i == 0 else 1.0,
                    }
                )
        df = pd.DataFrame(rows).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        out = calc_indicators(df)
        valid = out["vwap"].dropna()
        diff = (valid - out.loc[valid.index, "close"]).abs()
        assert (diff < 1e-6).all()


class TestMomentum:
    """动量因子测试"""
    
    def test_momentum_range(self, sample_stock_data):
        """动量应在合理范围内"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_mom5 = df['mom_5'].dropna()
        valid_mom20 = df['mom_20'].dropna()
        
        # 动量通常在 -50% 到 +50% 之间
        assert (valid_mom5 > -0.5).all() and (valid_mom5 < 0.5).all()
        assert (valid_mom20 > -0.8).all() and (valid_mom20 < 0.8).all()


def test_calc_indicators_no_groupby_apply_deprecation(sample_stock_data):
    """calc_indicators 不应触发 groupby.apply 分组列弃用告警。"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        _ = calc_indicators(sample_stock_data.copy())
    deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert not deprecations, "calc_indicators produced DeprecationWarning"


def test_calc_indicators_group_boundaries_do_not_bleed():
    """相同走势的两只股票应得到完全一致的分组指标。"""
    rows = []
    dates = pd.date_range("2025-01-01", periods=80, freq="B")
    close_path = np.linspace(10.0, 18.0, len(dates)) + np.sin(np.arange(len(dates)) / 5.0)
    volume_path = 1000 + (np.arange(len(dates)) % 7) * 50

    for code in ["000001.SZ", "000002.SZ"]:
        prev_close = None
        for i, trade_date in enumerate(dates):
            close = float(close_path[i])
            open_price = close * (0.995 if i % 2 == 0 else 1.005)
            high = max(open_price, close) * 1.01
            low = min(open_price, close) * 0.99
            vol = float(volume_path[i])
            pct_chg = 0.0 if prev_close is None else (close / prev_close - 1.0) * 100.0
            rows.append(
                {
                    "ts_code": code,
                    "trade_date": trade_date,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "vol": vol,
                    "amount": close * vol * 100.0,
                    "pct_chg": pct_chg,
                }
            )
            prev_close = close

    df = pd.DataFrame(rows).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    out = calc_indicators(df)

    code_a = out[out["ts_code"] == "000001.SZ"].reset_index(drop=True)
    code_b = out[out["ts_code"] == "000002.SZ"].reset_index(drop=True)
    compare_cols = [
        "ma20",
        "vol_ma20",
        "z_score",
        "pv_corr_5",
        "rsi",
        "macd",
        "macd_signal",
        "macd_hist",
        "atr",
        "adx",
        "gap_zscore",
        "vp_divergence",
    ]

    for col in compare_cols:
        assert np.allclose(code_a[col], code_b[col], equal_nan=True), f"grouped indicator mismatch for {col}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
