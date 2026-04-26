# -*- coding: utf-8 -*-
"""
MFTS 核心算法单元测试

测试内容:
1. BIAS 计算正确性
2. Z-Score 计算正确性
3. Alpha 评分向量化版本与逐行版本一致性
4. 信号生成逻辑
"""

import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.mfts_screener import (
    calc_indicators,
    calculate_alpha_score,
    calculate_alpha_score_vectorized,
    get_limit_ratio,
    PARAMS,
)


class TestBiasCalculation:
    """BIAS 计算测试"""
    
    def test_bias_basic(self, sample_stock_data):
        """测试 BIAS 基础计算"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        # BIAS 应该存在
        assert 'bias' in df.columns
        assert 'bias13' in df.columns
        
        # BIAS 值应在合理范围内 (-50%, +50%)
        valid_bias = df['bias'].dropna()
        assert (valid_bias > -50).all() and (valid_bias < 50).all()
    
    def test_bias_formula(self, sample_stock_data):
        """验证 BIAS 计算公式"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        # 手动计算 BIAS 验证
        # BIAS = (close - MA) / MA * 100
        for code in df['ts_code'].unique():
            code_df = df[df['ts_code'] == code].copy()
            code_df = code_df.reset_index(drop=True)
            
            # 取第30行（确保有足够数据）
            if len(code_df) >= 30:
                idx = 29
                ma = code_df['ma_bias_base'].iloc[idx]
                close = code_df['close'].iloc[idx]
                expected_bias = (close - ma) / ma * 100
                actual_bias = code_df['bias'].iloc[idx]
                
                # 允许小误差
                assert abs(expected_bias - actual_bias) < 0.01, \
                    f"BIAS mismatch: expected {expected_bias:.4f}, got {actual_bias:.4f}"


class TestZScoreCalculation:
    """Z-Score 计算测试"""
    
    def test_zscore_basic(self, sample_stock_data):
        """测试 Z-Score 基础计算"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        assert 'z_score' in df.columns
        
        # Z-Score 应在合理范围内 (-5, +5)
        valid_z = df['z_score'].dropna()
        assert (valid_z > -5).all() and (valid_z < 5).all()
    
    def test_zscore_distribution(self, sample_stock_data):
        """Z-Score 应近似标准正态分布"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_z = df['z_score'].dropna()
        
        # 均值应接近 0
        assert abs(valid_z.mean()) < 0.5
        
        # 标准差应接近 1
        assert 0.5 < valid_z.std() < 2.0


class TestAlphaScore:
    """Alpha 评分测试"""
    
    def test_alpha_score_range(self, sample_stock_data):
        """Alpha 评分应在合理范围内"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        # 使用默认参数
        adaptive_deep = PARAMS['buy_deep']
        adaptive_mid = PARAMS['buy_mid']
        dynamic_z = PARAMS['z_buy_deep']
        
        scores = calculate_alpha_score_vectorized(df, adaptive_deep, adaptive_mid, dynamic_z)
        
        # 评分范围约 -10 到 +20
        assert (scores >= -15).all() and (scores <= 25).all()
    
    def test_alpha_score_consistency(self, sample_stock_data):
        """
        验证向量化版本和逐行版本的 Alpha 评分一致性
        这是确保 Pine Script 复刻准确性的关键测试
        """
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        # 只测试有完整数据的行
        df = df.dropna(subset=['bias', 'z_score', 'rsi', 'mfi']).head(20)
        
        if len(df) == 0:
            pytest.skip("No valid data for testing")
        
        adaptive_deep = PARAMS['buy_deep']
        adaptive_mid = PARAMS['buy_mid']
        dynamic_z = PARAMS['z_buy_deep']
        
        # 向量化计算
        vec_scores = calculate_alpha_score_vectorized(df, adaptive_deep, adaptive_mid, dynamic_z)
        
        # 逐行计算
        row_scores = []
        for _, row in df.iterrows():
            score = calculate_alpha_score(row, adaptive_deep, adaptive_mid, dynamic_z)
            row_scores.append(score)
        
        row_scores = pd.Series(row_scores, index=df.index)
        
        # 比较结果（允许小浮点误差）
        diff = (vec_scores - row_scores).abs()
        assert (diff < 0.01).all(), \
            f"Score mismatch! Max diff: {diff.max():.4f}"
    
    def test_falling_knife_penalty(self, single_row_data):
        """测试 Falling Knife 扣分逻辑"""
        row = single_row_data.copy()
        
        # 设置 Falling Knife 条件
        row['clv'] = -0.8  # < -0.7
        row['spread'] = 1.0  # > avg_spread * 1.5
        row['avg_spread'] = 0.5
        row['close'] = 9.5  # < open
        row['open'] = 10.0
        
        score = calculate_alpha_score(row, -10.0, -7.0, -1.96)
        
        # Falling Knife 应导致 -5 分
        assert score == -5.0


class TestLimitRatio:
    """涨跌停幅度识别测试"""
    
    def test_st_stock(self):
        """ST 股票应返回 5%"""
        assert get_limit_ratio('000001.SZ', 'ST测试') == 0.05
        assert get_limit_ratio('000001.SZ', '*ST测试') == 0.05
    
    def test_kcb_stock(self):
        """科创板应返回 20%"""
        assert get_limit_ratio('688001.SH', '科创股票') == 0.20
    
    def test_cyb_stock(self):
        """创业板应返回 20%"""
        assert get_limit_ratio('300001.SZ', '创业板股票') == 0.20
    
    def test_bjse_stock(self):
        """北交所应返回 30%"""
        assert get_limit_ratio('830001.BJ', '北交所股票') == 0.30
        assert get_limit_ratio('430001.BJ', '北交所股票') == 0.30
    
    def test_main_board(self):
        """主板应返回 10%"""
        assert get_limit_ratio('600001.SH', '上证股票') == 0.10
        assert get_limit_ratio('000001.SZ', '深证股票') == 0.10


class TestIndicatorCalculation:
    """技术指标计算测试"""
    
    def test_all_indicators_exist(self, sample_stock_data):
        """验证所有必需指标都已计算"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        required_indicators = [
            'ma5', 'ma20', 'ma120', 'ma250',
            'vol_ma5', 'vol_ma20',
            'bias', 'bias13', 'z_score',
            'rsi', 'macd', 'macd_signal', 'macd_hist',
            'k_val', 'd_val', 'j_val',
            'mfi', 'bb_pos', 'atr', 'adx',
            'mom_5', 'mom_20',
            'pv_corr_5', 'pv_corr_20',
            'pos_52w', 'clv', 'spread', 'obv',
        ]
        
        for indicator in required_indicators:
            assert indicator in df.columns, f"Missing indicator: {indicator}"
    
    def test_rsi_range(self, sample_stock_data):
        """RSI 应在 0-100 范围内"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_rsi = df['rsi'].dropna()
        assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()
    
    def test_mfi_range(self, sample_stock_data):
        """MFI 应在 0-100 范围内"""
        df = sample_stock_data.copy()
        df = calc_indicators(df)
        
        valid_mfi = df['mfi'].dropna()
        assert (valid_mfi >= 0).all() and (valid_mfi <= 100).all()


class TestOversoldSignal:
    """超跌信号测试"""
    
    @pytest.mark.skip(reason="oversold_stock_data fixture not compatible with calc_indicators groupby")
    def test_deep_oversold_detection(self, oversold_stock_data):
        """
        验证超跌指标能被正确计算
        """
        df = oversold_stock_data.copy()
        df = calc_indicators(df)
        
        # 验证关键指标存在
        assert 'z_score' in df.columns, "z_score should exist"
        assert 'bias' in df.columns, "bias should exist"
        
        # 验证计算结果不全为 NaN
        assert df['z_score'].notna().any(), "z_score should have valid values"
        assert df['bias'].notna().any(), "bias should have valid values"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
