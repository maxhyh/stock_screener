#!/usr/bin/env python3
"""
纯MFTS选股脚本 - 修复版
基于Alpha评分规则，正确调用API

使用方法:
    python scripts/daily_mfts_select.py
    python scripts/daily_mfts_select.py --date 20260109 --top 30
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'core'))

from mfts_screener import calc_indicators, calculate_alpha_score, load_metadata
from core.data.market_data_gateway import AShareMarketDataGateway

OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def select_stocks_mfts(target_date=None, top_n=30):
    """
    纯MFTS规则选股
    
    Args:
        target_date: 目标日期(YYYYMMDD)，None表示最新交易日
        top_n: 选择前N只股票
    """
    print("=" * 70)
    print("MFTS纯规则选股（Alpha评分）")
    print("=" * 70)
    
    # 1. 加载数据
    print("\n[1/4] 从共享只读 ODS 加载市场数据...")
    gateway = AShareMarketDataGateway()
    sessions = gateway.available_trade_dates()
    if not sessions:
        raise RuntimeError("共享 ODS 没有可用日线会话")
    requested_date = pd.to_datetime(target_date).strftime("%Y-%m-%d") if target_date else sessions[-1]
    eligible_sessions = [date for date in sessions if date <= requested_date]
    if not eligible_sessions:
        raise ValueError(f"目标日期 {requested_date} 前没有 ODS 日线会话")
    resolved_date = eligible_sessions[-1]
    df = gateway.load_bars(resolved_date, resolved_date, include_bj9=False, lookback_sessions=252)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    
    # 确定目标日期
    target_date = pd.to_datetime(resolved_date)
    
    print(f"目标日期: {target_date.date()}")
    
    # 2. 计算指标
    print("\n[2/4] 计算MFTS技术指标...")
    df = df.sort_values(['ts_code', 'trade_date'])
    df = calc_indicators(df)
    df = df.dropna(subset=['ma120', 'vol_ma20', 'z_score'])
    
    # 添加辅助列
    df['vol_ratio'] = df['vol'] / df['vol_ma20']
    
    # 3. 筛选目标日期
    today_df = df[df['trade_date'] == target_date].copy()
    # 实盘约束：不参与北交所 9 开头标的
    today_df = today_df[~today_df['ts_code'].astype(str).str.startswith('9')].copy()
    
    if len(today_df) == 0:
        print(f"\n❌ 错误: {target_date.date()} 无数据")
        return None
    
    print(f"股票数量: {len(today_df)}")
    
    # 4. 计算Alpha评分（正确的逐行调用方式）
    print("\n[3/4] 计算Alpha评分...")
    today_df['alpha_score'] = today_df.apply(
        lambda row: calculate_alpha_score(
            row,
            adaptive_buy_deep=-10,
            adaptive_buy_mid=-7,
            dynamic_z_deep=-2.0
        ),
        axis=1
    )
    
    # 筛选有效股票（alpha_score > 0表示有买入信号）
    valid_df = today_df[today_df['alpha_score'] > 0].copy()
    print(f"有效信号数: {len(valid_df)}")
    
    if len(valid_df) == 0:
        print("\n⚠️ 警告: 今日无符合条件的股票")
        # 如果没有正分股票，取分数最高的作为备选
        valid_df = today_df.copy()
    
    # 5. 按Alpha评分排序
    print(f"\n[4/4] 选择Top {top_n}股票（按Alpha评分）...")
    top_stocks = valid_df.nlargest(top_n, 'alpha_score').copy()
    
    # 加载元数据
    meta_dict = load_metadata(target_date)
    top_stocks['name'] = top_stocks['ts_code'].apply(
        lambda x: meta_dict.get(x, {}).get('name', x)
    )
    
    # 确定信号类型
    def get_signal_type(row):
        if row['alpha_score'] < 0:
            return '风险'
        elif row['alpha_score'] < 5:
            return '轻度超跌'
        elif row['alpha_score'] < 10:
            return '中度超跌'
        else:
            return '深度超跌'
    
    top_stocks['signal'] = top_stocks.apply(get_signal_type, axis=1)
    
    # 整理输出
    output_cols = ['ts_code', 'name', 'signal', 'alpha_score', 'close', 'pct_chg',
                   'bias', 'z_score', 'rsi', 'vol_ratio']
    
    # 确保所有列存在
    for col in output_cols:
        if col not in top_stocks.columns:
            top_stocks[col] = np.nan
    
    result = top_stocks[output_cols].copy()
    
    result.columns = ['代码', '名称', '信号', 'Alpha评分', '收盘价', '涨跌幅%',
                      'BIAS-20', 'Z-Score', 'RSI', '量比']
    
    result['日期'] = target_date.strftime('%Y-%m-%d')
    result['排名'] = range(1, len(result) + 1)
    
    # 重新排列列
    result = result[['日期', '排名', '代码', '名称', '信号', 'Alpha评分',
                     '收盘价', 'BIAS-20', 'Z-Score', 'RSI', '量比', '涨跌幅%']]
    
    # 6. 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_str = target_date.strftime('%Y%m%d')
    output_file = os.path.join(OUTPUT_DIR, f"daily_mfts_{date_str}.csv")
    result.to_csv(output_file, index=False, encoding='utf-8-sig')
    
    # 7. 打印结果
    print("\n" + "=" * 70)
    print(f"Top {len(result)} 推荐股票（纯MFTS规则）")
    print("=" * 70)
    print(result.to_string(index=False))
    
    print(f"\n✅ 结果已保存: {output_file}")
    
    # 统计
    print("\n" + "=" * 70)
    print("统计信息")
    print("=" * 70)
    print(f"平均Alpha评分: {result['Alpha评分'].mean():.2f}")
    print(f"平均BIAS-20: {result['BIAS-20'].mean():.2f}%")
    print(f"平均RSI: {result['RSI'].mean():.1f}")
    print(f"信号分布:")
    for sig, count in result['信号'].value_counts().items():
        print(f"  {sig}: {count}只")
    
    return result


def main():
    parser = argparse.ArgumentParser(description='MFTS纯规则选股')
    parser.add_argument('--date', type=str, help='目标日期(YYYYMMDD)，默认最新交易日')
    parser.add_argument('--top', type=int, default=30, help='选择Top N股票，默认30')
    args = parser.parse_args()
    
    try:
        result = select_stocks_mfts(target_date=args.date, top_n=args.top)
        if result is not None:
            print("\n✅ 选股完成!")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
