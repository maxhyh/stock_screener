#!/usr/bin/env python3
"""
MFTS回测对比脚本
对比纯MFTS规则版 vs ML增强版的历史表现

使用方法:
    python scripts/history/backtest_comparison.py --days 30
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime, timedelta
import argparse
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 无GUI后端

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def load_returns(stock_codes, base_date, data_df, period=1):
    """获取未来N日收益率"""
    returns = {}
    
    for code in stock_codes:
        stock_data = data_df[data_df['ts_code'] == code].sort_values('trade_date').reset_index(drop=True)
        base_positions = stock_data.index[stock_data['trade_date'] == base_date].tolist()

        if not base_positions:
            continue

        base_pos = base_positions[0]
        base_price = stock_data.iloc[base_pos]['close']

        future_pos = base_pos + period
        if future_pos < len(stock_data):
            future_price = stock_data.iloc[future_pos]['close']
            returns[code] = ((future_price / base_price) - 1) * 100
    
    return returns


def backtest_comparison(days=30):
    """
    回测对比
    
    Args:
        days: 回测天数
    """
    print("=" * 70)
    print(f"MFTS回测对比（过去{days}天）")
    print("=" * 70)
    
    # 加载数据
    print("\n加载市场数据...")
    parquet_file = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    df = pd.read_parquet(parquet_file)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    
    # 查找推荐文件
    print("\n查找历史推荐...")
    mfts_files = sorted([f for f in os.listdir(OUTPUT_DIR) 
                         if f.startswith('daily_mfts_') and f.endswith('.csv')])
    ml_files = sorted([f for f in os.listdir(OUTPUT_DIR) 
                       if f.startswith('daily_') and not f.startswith('daily_mfts_') 
                       and f.endswith('.csv')])
    
    # 过滤日期
    cutoff = datetime.now() - timedelta(days=days)
    
    results = []
    
    for mfts_file in mfts_files:
        date_str = mfts_file.replace('daily_mfts_', '').replace('.csv', '')
        file_date = datetime.strptime(date_str, '%Y%m%d')
        
        if file_date <cutoff:
            continue
        
        # 查找对应的ML文件
        ml_file = f"daily_{date_str}.csv"
        
        if ml_file not in ml_files:
            continue
        
        print(f"\n处理 {file_date.strftime('%Y-%m-%d')}...")
        
        # 读取推荐
        mfts_picks = pd.read_csv(os.path.join(OUTPUT_DIR, mfts_file))
        ml_picks = pd.read_csv(os.path.join(OUTPUT_DIR, ml_file))
        
        # 计算T+1收益
        date_pd = pd.to_datetime(file_date)
        mfts_returns = load_returns(mfts_picks['代码'].tolist(), date_pd, df, 1)
        ml_returns = load_returns(ml_picks['代码'].tolist(), date_pd, df, 1)
        
        # 统计
        mfts_r = list(mfts_returns.values())
        ml_r = list(ml_returns.values())
        
        if mfts_r and ml_r:
            stats = {
                '日期': file_date.strftime('%Y-%m-%d'),
                'MFTS胜率%': (np.array(mfts_r) > 0).mean() * 100,
                'MFTS平均%': np.mean(mfts_r),
                'MFTS最大%': np.max(mfts_r),
                'ML胜率%': (np.array(ml_r) > 0).mean() * 100,
                'ML平均%': np.mean(ml_r),
                'ML最大%': np.max(ml_r),
            }
            results.append(stats)
    
    if not results:
        print("\n❌ 没有找到可对比的数据")
        print("请先运行：")
        print("  python scripts/daily_mfts_select.py")
        print("  python scripts/daily_ml_select.py")
        return
    
    # 生成报告
    df_results = pd.DataFrame(results)
    
    # 保存
    report_file = os.path.join(OUTPUT_DIR, "backtest_comparison.csv")
    df_results.to_csv(report_file, index=False, encoding='utf-8-sig')
    
    # 打印
    print("\n" + "=" * 70)
    print("回测对比结果")
    print("=" * 70)
    print(df_results.to_string(index=False))
    
    # 汇总
    print("\n" + "=" * 70)
    print("整体对比")
    print("=" * 70)
    
    summary = {
        '策略': ['纯MFTS', 'ML增强'],
        '平均胜率': [
            df_results['MFTS胜率%'].mean(),
            df_results['ML胜率%'].mean()
        ],
        '平均收益': [
            df_results['MFTS平均%'].mean(),
            df_results['ML平均%'].mean()
        ],
        '最大收益': [
            df_results['MFTS最大%'].mean(),
            df_results['ML最大%'].mean()
        ]
    }
    
    summary_df = pd.DataFrame(summary)
    print(summary_df.to_string(index=False))
    
    # 判断胜负
    print("\n" + "=" * 70)
    mfts_win = (df_results['MFTS平均%'] > df_results['ML平均%']).sum()
    ml_win = (df_results['ML平均%'] > df_results['MFTS平均%']).sum()
    
    print(f"MFTS胜出天数: {mfts_win}")
    print(f"ML胜出天数: {ml_win}")
    
    if ml_win > mfts_win:
        print("\n🏆 ML增强版表现更优")
        improvement = ((summary['平均收益'][1] / summary['平均收益'][0]) - 1) * 100
        print(f"   收益提升: {improvement:.1f}%")
    else:
        print("\n⚠️ 纯MFTS表现更优")
    
    # 生成图表
    try:
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        
        # 胜率对比
        axes[0].plot(df_results['日期'], df_results['MFTS胜率%'], 'o-', label='纯MFTS', linewidth=2)
        axes[0].plot(df_results['日期'], df_results['ML胜率%'], 's-', label='ML增强', linewidth=2)
        axes[0].axhline(y=50, color='r', linestyle='--', alpha=0.3)
        axes[0].set_ylabel('胜率 (%)')
        axes[0].set_title('胜率对比')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        axes[0].tick_params(axis='x', rotation=45)
        
        # 收益对比
        axes[1].plot(df_results['日期'], df_results['MFTS平均%'], 'o-', label='纯MFTS', linewidth=2)
        axes[1].plot(df_results['日期'], df_results['ML平均%'], 's-', label='ML增强', linewidth=2)
        axes[1].axhline(y=0, color='r', linestyle='--', alpha=0.3)
        axes[1].set_ylabel('平均收益 (%)')
        axes[1].set_title('收益对比')
        axes[1].legend()
        axes[1].grid(True, alpha=0.3)
        axes[1].tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        chart_file = os.path.join(OUTPUT_DIR, "backtest_comparison.png")
        plt.savefig(chart_file, dpi=150, bbox_inches='tight')
        print(f"\n图表已保存: {chart_file}")
    except Exception as e:
        print(f"\n图表生成失败: {e}")
    
    print(f"\n✅ 报告已保存: {report_file}")


def main():
    parser = argparse.ArgumentParser(description='MFTS回测对比')
    parser.add_argument('--days', type=int, default=30, help='回测天数，默认30')
    args = parser.parse_args()
    
    backtest_comparison(days=args.days)


if __name__ == "__main__":
    main()
