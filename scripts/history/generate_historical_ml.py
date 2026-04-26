#!/usr/bin/env python3
"""
批量生成ML历史选股结果
"""
import sys
import os
import subprocess

# 基础路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT_PATH = os.path.join(BASE_DIR, 'scripts', 'daily_ml_select.py')

# 要生成的日期 (最近一周交易日)
dates = ['20260105', '20260106', '20260107', '20260108', '20260109', '20260112']

print("=" * 70)
print(f"开始批量生成ML历史选股结果 ({len(dates)}天)")
print("=" * 70)

for date_str in dates:
    print(f"\n>>> 处理日期: {date_str}")
    cmd = [sys.executable, SCRIPT_PATH, '--date', date_str]
    
    try:
        # 同步运行
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ 生成 {date_str} 失败: {e}")
    except Exception as e:
        print(f"❌ 错误: {e}")

print("\n" + "=" * 70)
print("批量生成完成")
print("=" * 70)
