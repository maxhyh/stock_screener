#!/usr/bin/env python3
"""
项目健康检查脚本
- 检查核心文件是否存在
- 检查关键数据文件新鲜度
- 检查输出目录结构和膨胀情况
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "daily_all_5y.parquet"
MODEL_DIR = BASE_DIR / "models"
OUTPUT_DIR = BASE_DIR / "output"
MEMORY_DIR = BASE_DIR / "memory"

REQUIRED_FILES = [
    BASE_DIR / "core" / "mfts_screener.py",
    BASE_DIR / "scripts" / "daily_all.py",
    BASE_DIR / "scripts" / "daily_incremental_update.py",
    BASE_DIR / "scripts" / "daily_ml_select.py",
    BASE_DIR / "web" / "app.py",
    BASE_DIR / "config" / "settings.py",
]


def age_hours(path: Path) -> float:
    return (datetime.now().timestamp() - path.stat().st_mtime) / 3600


def fmt_ok(ok: bool) -> str:
    return "OK" if ok else "FAIL"


def main() -> int:
    print("=" * 68)
    print("MFTS 项目健康检查")
    print("=" * 68)

    failures = 0

    print("\n[1] 核心文件检查")
    for p in REQUIRED_FILES:
        ok = p.exists()
        print(f"- {p.relative_to(BASE_DIR)}: {fmt_ok(ok)}")
        if not ok:
            failures += 1

    print("\n[2] 数据文件检查")
    if DATA_FILE.exists():
        h = age_hours(DATA_FILE)
        print(f"- data/daily_all_5y.parquet: OK (age={h:.1f}h)")
        if h > 72:
            print("  警告: 数据超过 72 小时未更新")
    else:
        print("- data/daily_all_5y.parquet: FAIL")
        failures += 1

    print("\n[3] 模型文件检查")
    model_files = sorted(MODEL_DIR.glob("mfts_lgbm_*.pkl")) if MODEL_DIR.exists() else []
    print(f"- models/mfts_lgbm_*.pkl: {'OK' if model_files else 'FAIL'} (count={len(model_files)})")
    if not model_files:
        failures += 1

    print("\n[4] 输出目录检查")
    if OUTPUT_DIR.exists():
        scan_files = {p.name for p in OUTPUT_DIR.glob("mfts_scan_*.csv")}
        scan_files.update({p.name for p in (OUTPUT_DIR / "scan").glob("mfts_scan_*.csv")})
        daily_files = {p.name for p in OUTPUT_DIR.glob("daily_*.csv")}
        daily_files.update({p.name for p in (OUTPUT_DIR / "daily").glob("daily_*.csv")})
        verify_files = {p.name for p in OUTPUT_DIR.glob("verification_*.csv")}
        verify_files.update({p.name for p in (OUTPUT_DIR / "verify").glob("verification_*.csv")})
        backtest_files = {p.name for p in OUTPUT_DIR.glob("mfts_backtest_*.csv")}
        backtest_files.update({p.name for p in OUTPUT_DIR.glob("backtest_*.csv")})
        backtest_files.update({p.name for p in (OUTPUT_DIR / "backtest").glob("mfts_backtest_*.csv")})
        backtest_files.update({p.name for p in (OUTPUT_DIR / "backtest").glob("backtest_*.csv")})
        scan_count = len(scan_files)
        daily_count = len(daily_files)
        verify_count = len(verify_files)
        backtest_count = len(backtest_files)
        print(f"- mfts_scan_*.csv: {scan_count}")
        print(f"- daily_*.csv: {daily_count}")
        print(f"- verification_*.csv: {verify_count}")
        print(f"- backtest*.csv: {backtest_count}")
    else:
        print("- output/: FAIL")
        failures += 1

    print("\n[5] 项目记忆系统检查")
    memory_files = [
        MEMORY_DIR / "profile.md",
        MEMORY_DIR / "actives.md",
        MEMORY_DIR / "learnings.md",
        MEMORY_DIR / "errors.md",
        MEMORY_DIR / "nightly_review_draft.md",
    ]
    for p in memory_files:
        ok = p.exists()
        print(f"- {p.relative_to(BASE_DIR)}: {fmt_ok(ok)}")
        if not ok:
            failures += 1

    print("\n" + "=" * 68)
    if failures:
        print(f"结果: FAIL ({failures} 项失败)")
        return 1

    print("结果: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
