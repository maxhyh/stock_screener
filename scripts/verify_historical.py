#!/usr/bin/env python3
"""
历史验证脚本 - 扩展版
计算T+1, T+5, T+10的收益率

使用方法:
    python scripts/verify_historical.py --days 30
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime, timedelta
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.output_paths import ensure_output_dirs, list_dual, write_dual_csv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def get_future_returns(stock_codes, base_date, data_df, periods=[1, 5, 10]):
    """
    获取未来N日的收益率
    
    Args:
        stock_codes: 股票代码列表
        base_date: 基准日期
        data_df: 全量数据
        periods: 周期列表 [1, 5, 10]
    
    Returns:
        dict: {code: {1: return_1d, 5: return_5d, 10: return_10d}}
    """
    results = {}
    
    for code in stock_codes:
        stock_data = data_df[data_df['ts_code'] == code].sort_values('trade_date').reset_index(drop=True)

        # 找到基准日期的行位置（必须使用位置索引，不能用原DataFrame索引标签）
        base_positions = stock_data.index[stock_data['trade_date'] == base_date].tolist()
        if not base_positions:
            continue

        base_pos = base_positions[0]
        base_price = stock_data.iloc[base_pos]['close']
        
        results[code] = {'base_price': base_price}
        
        # 计算各周期收益
        for period in periods:
            future_pos = base_pos + period
            if future_pos < len(stock_data):
                future_price = stock_data.iloc[future_pos]['close']
                returns = ((future_price / base_price) - 1) * 100
                results[code][f'T+{period}'] = returns
            else:
                results[code][f'T+{period}'] = None
    
    return results


def verify_historical(days=30):
    """
    验证过去N天的所有推荐
    
    Args:
        days: 回溯天数
    """
    print("=" * 70)
    print(f"历史验证 - 过去{days}天")
    print("=" * 70)
    
    # 1. 加载市场数据
    print("\n加载市场数据...")
    parquet_file = os.path.join(DATA_DIR, "daily_all_5y.parquet")
    df = pd.read_parquet(parquet_file)
    df['trade_date'] = pd.to_datetime(df['trade_date'].astype(str))
    df['ts_code'] = df['ts_code'].astype(str)
    df = df.sort_values(['ts_code', 'trade_date'])
    
    # 2. 查找所有daily文件（兼容新旧目录）
    print("\n查找历史推荐...")
    dirs = ensure_output_dirs(OUTPUT_DIR)
    daily_dir = dirs['daily']
    verify_dir = dirs['verify']
    base_dir = Path(OUTPUT_DIR)
    daily_paths = list_dual(["daily_*.csv"], daily_dir, base_dir)
    
    # 筛选最近N天
    cutoff_date = datetime.now() - timedelta(days=days)
    recent_files = []
    
    for fpath in daily_paths:
        f = fpath.name
        date_str = f.replace('daily_', '').replace('.csv', '')
        file_date = datetime.strptime(date_str, '%Y%m%d')
        if file_date >= cutoff_date:
            recent_files.append((file_date, fpath))
    
    recent_files.sort(reverse=True)
    print(f"找到 {len(recent_files)} 个交易日的推荐记录")
    
    if not recent_files:
        print("\n❌ 没有找到历史推荐记录")
        return
    
    # 3. 逐个验证
    all_results = []
    
    for file_date, file_path in recent_files:
        print(f"\n处理 {file_date.strftime('%Y-%m-%d')}...")
        
        # 读取推荐
        picks = pd.read_csv(file_path)
        
        # 计算未来收益
        date_pd = pd.to_datetime(file_date)
        returns = get_future_returns(
            picks['代码'].tolist(), 
            date_pd, 
            df, 
            periods=[1, 5, 10]
        )
        
        # 统计
        stats = {
            '日期': file_date.strftime('%Y-%m-%d'),
            '推荐数': len(picks),
        }
        
        # T+1统计
        t1_returns = [r['T+1'] for r in returns.values() if r.get('T+1') is not None]
        if t1_returns:
            stats['T+1胜率%'] = (np.array(t1_returns) > 0).mean() * 100
            stats['T+1平均%'] = np.mean(t1_returns)
            stats['T+1最大%'] = np.max(t1_returns)
        else:
            stats['T+1胜率%'] = stats['T+1平均%'] = stats['T+1最大%'] = None
        
        # T+5统计
        t5_returns = [r['T+5'] for r in returns.values() if r.get('T+5') is not None]
        if t5_returns:
            stats['T+5胜率%'] = (np.array(t5_returns) > 0).mean() * 100
            stats['T+5平均%'] = np.mean(t5_returns)
            stats['T+5最大%'] = np.max(t5_returns)
        else:
            stats['T+5胜率%'] = stats['T+5平均%'] = stats['T+5最大%'] = None
        
        # T+10统计
        t10_returns = [r['T+10'] for r in returns.values() if r.get('T+10') is not None]
        if t10_returns:
            stats['T+10胜率%'] = (np.array(t10_returns) > 0).mean() * 100
            stats['T+10平均%'] = np.mean(t10_returns)
            stats['T+10最大%'] = np.max(t10_returns)
        else:
            stats['T+10胜率%'] = stats['T+10平均%'] = stats['T+10最大%'] = None
        
        all_results.append(stats)
        
        # 保存详细结果
        detail_rows = []
        for code in picks['代码']:
            if code in returns:
                row = picks[picks['代码'] == code].iloc[0].to_dict()
                row.update(returns[code])
                detail_rows.append(row)
        
        if detail_rows:
            detail_df = pd.DataFrame(detail_rows)
            detail_new = verify_dir / f"verification_extended_{file_date.strftime('%Y%m%d')}.csv"
            detail_legacy = base_dir / f"verification_extended_{file_date.strftime('%Y%m%d')}.csv"
            write_dual_csv(detail_df, detail_new, detail_legacy, index=False, encoding='utf-8-sig')
    
    # 4. 保存汇总结果
    summary_df = pd.DataFrame(all_results)
    summary_new = verify_dir / "historical_summary.csv"
    summary_legacy = base_dir / "historical_summary.csv"
    write_dual_csv(summary_df, summary_new, summary_legacy, index=False, encoding='utf-8-sig')
    
    # 5. 打印汇总
    print("\n" + "=" * 70)
    print("历史验证汇总")
    print("=" * 70)
    print(summary_df.to_string(index=False))
    
    # 6. 总体统计
    print("\n" + "=" * 70)
    print("总体表现")
    print("=" * 70)
    
    valid_summary = summary_df.dropna()
    if len(valid_summary) > 0:
        print(f"\nT+1: 胜率={valid_summary['T+1胜率%'].mean():.1f}%, 平均收益={valid_summary['T+1平均%'].mean():.2f}%")
        print(f"T+5: 胜率={valid_summary['T+5胜率%'].mean():.1f}%, 平均收益={valid_summary['T+5平均%'].mean():.2f}%")
        print(f"T+10: 胜率={valid_summary['T+10胜率%'].mean():.1f}%, 平均收益={valid_summary['T+10平均%'].mean():.2f}%")
    
    print(f"\n✅ 结果已保存到 {summary_new} (兼容写入: {summary_legacy})")
    
    return summary_df


def main():
    parser = argparse.ArgumentParser(description='历史验证')
    parser.add_argument('--days', type=int, default=30, help='回溯天数，默认30')
    args = parser.parse_args()
    
    verify_historical(days=args.days)


if __name__ == "__main__":
    main()
