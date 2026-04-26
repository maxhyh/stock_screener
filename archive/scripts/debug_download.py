#!/usr/bin/env python3
"""
测试 safe_download_single_day 函数（已归档）

一次性调试脚本，保留仅供参考。
"""
import akshare as ak
import pandas as pd
import time
import random

def safe_download_single_day_debug(code, date_str):
    """
    下载单只股票的单日数据 - 带调试输出
    """
    print(f"\n=== 调试股票 {code} ===")
    
    # 方法1: 使用腾讯接口
    try:
        time.sleep(random.uniform(0.05, 0.15))
        
        # 转换代码格式
        prefix = 'sz' if code.startswith(('000', '001', '002', '003', '300')) else 'sh'
        symbol_code = f'{prefix}{code}'
        print(f"1. 代码转换: {code} -> {symbol_code}")
        
        # 获取完整历史数据
        df_full = ak.stock_zh_a_daily(symbol=symbol_code, adjust="qfq")
        print(f"2. 获取数据: {len(df_full)} 行" if df_full is not None else "2. 获取数据: None")
        
        if df_full is not None and not df_full.empty:
            print(f"3. 数据最新日期: {df_full['date'].max()}")
            
            # 过滤目标日期
            df_full['date'] = pd.to_datetime(df_full['date']).dt.strftime('%Y%m%d')
            print(f"4. 转换后最新日期: {df_full['date'].max()}")
            
            df = df_full[df_full['date'] == date_str].copy()
            print(f"5. 过滤{date_str}: {len(df)} 行")
            
            if not df.empty:
                # 标准化列名
                rename_map = {
                    'date': 'trade_date',
                    'open': 'open',
                    'close': 'close',
                    'high': 'high',
                    'low': 'low',
                    'volume': 'vol',
                }
                
                df = df.rename(columns=rename_map)
                df['ts_code'] = code
                print(f"6. 列名标准化完成")
                
                # 计算缺失字段
                if 'amount' not in df.columns and 'vol' in df.columns and 'close' in df.columns:
                    df['amount'] = df['vol'] * df['close']
                
                # 选择需要的列
                target_cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol']
                available_cols = [c for c in target_cols if c in df.columns]
                
                # 添加可选列
                for col in ['amount', 'pct_chg', 'turnover_rate']:
                    if col in df.columns:
                        available_cols.append(col)
                
                print(f"7. 最终列: {available_cols}")
                print(f"8. ✅ 返回数据: {len(df)} 行")
                return df[available_cols]
            else:
                print(f"5. ❌ 过滤后为空")
                return None
        else:
            print(f"3. ❌ 原始数据为空")
            return None
    
    except Exception as e:
        print(f"❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        return None

# 测试几个股票
test_codes = ['000001', '600000', '000002', '601398', '300750']
date_str = '20260204'

results = []
for code in test_codes:
    result = safe_download_single_day_debug(code, date_str)
    if result is not None and not result.empty:
        results.append(result)
        print(f"✅ {code}: 成功")
    else:
        print(f"❌ {code}: 失败")

print(f"\n总计: {len(results)}/{len(test_codes)} 成功")
if results:
    combined = pd.concat(results, ignore_index=True)
    print(f"合并数据: {len(combined)} 行")
    print(combined)
