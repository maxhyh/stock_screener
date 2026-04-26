#!/usr/bin/env python3
"""
数据完整性检测与修复脚本
自动检测缺失的交易日数据并重新下载

使用方法:
    python scripts/fix_missing_data.py           # 检测并修复
    python scripts/fix_missing_data.py --check   # 仅检测不修复
"""

import akshare as ak
import pandas as pd
import datetime
import os
import sys
import time
import argparse
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data")
PARQUET_FILE = os.path.join(DATA_DIR, "daily_all_5y.parquet")


def get_trade_calendar(start_date='20260101', end_date=None):
    """获取交易日历"""
    if end_date is None:
        end_date = datetime.date.today().strftime('%Y%m%d')
    
    try:
        df = ak.tool_trade_date_hist_sina()
        dates = df['trade_date'].astype(str).tolist()
        # 只保留指定范围
        dates = [d for d in dates if start_date <= d <= end_date]
        return sorted(dates)
    except Exception as e:
        print(f"获取交易日历失败: {e}")
        return []


def check_data_integrity():
    """检查数据完整性，返回缺失的交易日"""
    print("=" * 60)
    print("数据完整性检测")
    print("=" * 60)
    
    if not os.path.exists(PARQUET_FILE):
        print(f"❌ 数据文件不存在: {PARQUET_FILE}")
        return []
    
    # 读取现有数据
    print("\n读取现有数据...")
    df = pd.read_parquet(PARQUET_FILE)
    df['trade_date'] = df['trade_date'].astype(str).str[:8].str.replace('-', '')
    existing_dates = set(df['trade_date'].unique())
    
    min_date = min(existing_dates)
    max_date = max(existing_dates)
    
    print(f"  数据范围: {min_date} ~ {max_date}")
    print(f"  数据行数: {len(df):,}")
    print(f"  包含交易日: {len(existing_dates)} 天")
    
    # 获取交易日历
    print("\n获取交易日历...")
    # 只检查最近30天
    check_start = (datetime.date.today() - datetime.timedelta(days=30)).strftime('%Y%m%d')
    trade_dates = get_trade_calendar(start_date=check_start)
    
    if not trade_dates:
        print("无法获取交易日历")
        return []
    
    print(f"  最近30天交易日: {len(trade_dates)} 天")
    
    # 检测缺失日期
    missing_dates = []
    for date in trade_dates:
        if date not in existing_dates and date <= max_date:
            # 只报告应该有但没有的日期
            missing_dates.append(date)
    
    # 检测pct_chg缺失的日期
    print("\n检测涨跌幅数据质量...")
    pct_missing_dates = []
    for date in trade_dates:
        if date in existing_dates:
            day_data = df[df['trade_date'] == date]
            pct_null_ratio = day_data['pct_chg'].isna().mean()
            if pct_null_ratio > 0.5:  # 超过50%缺失
                pct_missing_dates.append(date)
                print(f"  ⚠️ {date}: pct_chg缺失率 {pct_null_ratio:.1%}")
    
    # 合并需要修复的日期
    all_fix_dates = sorted(set(missing_dates + pct_missing_dates))
    
    print("\n" + "=" * 60)
    print("检测结果")
    print("=" * 60)
    
    if missing_dates:
        print(f"\n❌ 缺失的交易日 ({len(missing_dates)}天):")
        for d in missing_dates:
            print(f"   {d}")
    else:
        print("\n✅ 无缺失交易日")
    
    if pct_missing_dates:
        print(f"\n⚠️ 涨跌幅数据异常 ({len(pct_missing_dates)}天):")
        for d in pct_missing_dates:
            print(f"   {d}")
    else:
        print("\n✅ 涨跌幅数据正常")
    
    return all_fix_dates


def fix_missing_data(dates_to_fix):
    """修复缺失数据"""
    if not dates_to_fix:
        print("\n✅ 无需修复")
        return True
    
    print(f"\n准备修复 {len(dates_to_fix)} 天的数据: {dates_to_fix}")
    
    # 读取现有数据
    df = pd.read_parquet(PARQUET_FILE)
    df['trade_date'] = df['trade_date'].astype(str).str[:8].str.replace('-', '')
    
    # 获取股票列表
    codes = df['ts_code'].unique().tolist()
    print(f"股票数量: {len(codes)}")
    
    # 导入下载函数
    from scripts.daily_incremental_update import safe_download_single_day
    
    for target_date in dates_to_fix:
        print(f"\n修复 {target_date}...")
        
        # 删除该日期的旧数据
        df = df[df['trade_date'] != target_date]
        
        # 下载新数据
        new_data = []
        for code in tqdm(codes, desc=f"下载{target_date}"):
            try:
                res = safe_download_single_day(code, target_date)
                if res is not None and not res.empty:
                    new_data.append(res)
            except Exception:
                pass
        
        if new_data:
            new_df = pd.concat(new_data, ignore_index=True)
            df = pd.concat([df, new_df], ignore_index=True)
            print(f"  ✅ 获取 {len(new_df)} 条数据")
        else:
            print(f"  ⚠️ 无法获取数据")
    
    # 保存
    df = df.sort_values(['ts_code', 'trade_date'])
    df.to_parquet(PARQUET_FILE, index=False)
    print("\n✅ 数据已保存")
    
    return True


def main():
    parser = argparse.ArgumentParser(description='数据完整性检测与修复')
    parser.add_argument('--check', action='store_true', help='仅检测不修复')
    args = parser.parse_args()
    
    # 检测
    dates_to_fix = check_data_integrity()
    
    if args.check:
        print("\n(仅检测模式，未执行修复)")
        return
    
    # 询问是否修复
    if dates_to_fix:
        response = input(f"\n是否修复这 {len(dates_to_fix)} 天的数据? (y/n): ").lower()
        if response == 'y':
            fix_missing_data(dates_to_fix)
        else:
            print("取消修复")


if __name__ == "__main__":
    main()
