# -*- coding: utf-8 -*-
"""
Pytest 配置和测试夹具
"""

import pytest
import pandas as pd
import numpy as np
import sys
import os
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def sample_stock_data():
    """
    创建用于测试的模拟股票数据
    包含50个交易日的 OHLCV 数据
    """
    np.random.seed(42)
    n_days = 50
    n_stocks = 3
    
    data = []
    for stock_idx in range(n_stocks):
        code = f"00000{stock_idx+1}.SZ"
        base_price = 10.0 + stock_idx * 5
        
        # 生成价格序列
        returns = np.random.normal(0, 0.02, n_days)
        prices = base_price * np.exp(np.cumsum(returns))
        
        for i in range(n_days):
            date = pd.Timestamp('2025-01-01') + pd.Timedelta(days=i)
            close = prices[i]
            open_price = close * (1 + np.random.uniform(-0.01, 0.01))
            high = max(open_price, close) * (1 + np.random.uniform(0, 0.02))
            low = min(open_price, close) * (1 - np.random.uniform(0, 0.02))
            vol = np.random.uniform(1e6, 1e7)
            amount = vol * close
            pct_chg = (close / prices[i-1] - 1) * 100 if i > 0 else 0
            
            data.append({
                'ts_code': code,
                'trade_date': date,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'vol': vol,
                'amount': amount,
                'pct_chg': pct_chg,
            })
    
    df = pd.DataFrame(data)
    df = df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    return df


@pytest.fixture(scope="session")
def oversold_stock_data():
    """
    创建超跌场景的测试数据
    用于验证 L1 抢筹信号
    """
    np.random.seed(123)
    n_days = 30
    
    # 创建一个下跌趋势后反弹的序列
    prices = [100.0]
    for i in range(20):
        # 前20天下跌
        prices.append(prices[-1] * 0.97)
    for i in range(9):
        # 后9天反弹
        prices.append(prices[-1] * 1.02)
    
    data = []
    for i, close in enumerate(prices):
        date = pd.Timestamp('2025-01-01') + pd.Timedelta(days=i)
        open_price = close * (1 + np.random.uniform(-0.01, 0.01))
        high = max(open_price, close) * (1 + np.random.uniform(0, 0.02))
        low = min(open_price, close) * (1 - np.random.uniform(0, 0.02))
        vol = np.random.uniform(1e6, 1e7)
        amount = vol * close
        pct_chg = (close / prices[i-1] - 1) * 100 if i > 0 else 0
        
        data.append({
            'ts_code': '000001.SZ',
            'trade_date': date,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'vol': vol,
            'amount': amount,
            'pct_chg': pct_chg,
        })
    
    df = pd.DataFrame(data)
    return df


@pytest.fixture(scope="session")
def sample_metadata():
    """
    创建用于测试的股票元数据
    """
    return {
        '000001.SZ': {'name': '平安银行', 'industry': '银行'},
        '000002.SZ': {'name': '万科A', 'industry': '房地产'},
        '000003.SZ': {'name': '测试股票', 'industry': '科技'},
    }


@pytest.fixture
def single_row_data():
    """
    创建单行数据用于 Alpha 评分测试
    """
    return pd.Series({
        'close': 10.0,
        'open': 10.2,
        'high': 10.5,
        'low': 9.8,
        'vol': 1e7,
        'vol_ma5': 8e6,
        'vol_ma20': 9e6,
        'close_1': 10.5,
        'bias': -12.0,
        'bias13': -8.0,
        'z_score': -2.1,
        'mom_5': -0.10,
        'mom_20': -0.18,
        'pv_corr_5': -0.2,
        'pv_corr_20': -0.1,
        'rsi': 25.0,
        'j_val': 15.0,
        'mfi': 28.0,
        'bb_pos': 15.0,
        'pos_52w': 20.0,
        'macd': 0.1,
        'macd_signal': 0.05,
        'macd_hist': 0.05,
        'macd_hist_prev': 0.03,
        'clv': 0.2,
        'spread': 0.7,
        'avg_spread': 0.5,
        'is_high_volume': False,
        'is_narrow_spread': True,
        'close_position': 0.3,
        'low': 9.8,
        'low_20_prev': 10.0,
        'obv': 1e8,
        'obv_low_20_prev': 9e7,
    })
