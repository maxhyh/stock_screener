#!/usr/bin/env python3
"""
输出文件迁移脚本（根目录 -> 分层子目录）

默认 dry-run，仅展示将要迁移的文件。
示例:
    python scripts/migrate_outputs.py
    python scripts/migrate_outputs.py --apply
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"

PATTERNS = {
    "scan": ["mfts_scan_*.csv", "mfts_latest.csv"],
    "daily": ["daily_*.csv", "daily_mfts_*.csv"],
    "verify": ["verification_*.csv", "verification_extended_*.csv", "historical_summary.csv"],
    "backtest": [
        "backtest_*.csv",
        "mfts_backtest_*.csv",
        "version_comparison.png",
        "backtest_charts.png",
        "backtest_comparison.png",
        "signal_stats.json",
        "factor_ic_analysis_T1.csv",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 output 根目录文件到分层目录")
    parser.add_argument("--apply", action="store_true", help="执行迁移（默认仅预览）")
    args = parser.parse_args()

    if not OUTPUT_DIR.exists():
        print(f"❌ 输出目录不存在: {OUTPUT_DIR}")
        return 1

    moved = 0
    skipped = 0

    print("=" * 70)
    print("输出迁移预览" if not args.apply else "执行输出迁移")
    print("=" * 70)

    for group, patterns in PATTERNS.items():
        target_dir = OUTPUT_DIR / group
        target_dir.mkdir(parents=True, exist_ok=True)

        for pattern in patterns:
            for src in sorted(OUTPUT_DIR.glob(pattern)):
                if src.parent != OUTPUT_DIR:
                    continue
                dst = target_dir / src.name
                if dst.exists():
                    print(f"SKIP (已存在): {src.name} -> {group}/")
                    skipped += 1
                    continue

                if args.apply:
                    shutil.move(str(src), str(dst))
                    print(f"MOVE: {src.name} -> {group}/")
                else:
                    print(f"PLAN: {src.name} -> {group}/")
                moved += 1

    print("-" * 70)
    print(f"待迁移/已迁移: {moved} 个, 跳过: {skipped} 个")
    if not args.apply:
        print("提示: 使用 --apply 执行真实迁移。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
