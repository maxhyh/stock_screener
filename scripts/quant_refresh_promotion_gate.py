#!/usr/bin/env python3
"""
刷新 profile promotion gate 所需的 latest 工件。

流程：
1) 运行 rolling compare，更新 latest 研究侧工件
2) 运行 P2 rolling replay，更新 latest 执行侧工件
3) 运行 promotion review，产出 latest review / decision
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

PROFILE_FILE = BASE_DIR / "config" / "quant_live_profiles.json"
DATA_FILE = BASE_DIR / "data" / "daily_all_5y.parquet"
BACKTEST_DIR = BASE_DIR / "output" / "backtest"


def _load_profiles(config_file: Path) -> list[str]:
    root = json.loads(config_file.read_text(encoding="utf-8"))
    profiles = root.get("profiles", {})
    if not isinstance(profiles, dict):
        raise RuntimeError("profile 配置无 profiles")
    default_profile = str(root.get("default_profile", "quality_regime"))
    names = [default_profile]
    for name in sorted(profiles):
        if str(name).startswith("quality_regime_candidate") and str(name) != default_profile:
            names.append(str(name))
    return list(dict.fromkeys([x for x in names if x]))


def _derive_period(end: str | None, lookback_months: int) -> tuple[str, str]:
    if end:
        end_dt = pd.to_datetime(end).normalize()
    else:
        if not DATA_FILE.exists():
            raise FileNotFoundError(f"未找到主数据: {DATA_FILE}")
        df = pd.read_parquet(DATA_FILE, columns=["trade_date"])
        if df.empty:
            raise RuntimeError("主数据为空，无法推导 promotion gate 时间范围")
        end_dt = pd.to_datetime(df["trade_date"].astype(str), errors="coerce").dropna().max().normalize()
    start_dt = (end_dt - pd.DateOffset(months=max(1, int(lookback_months)))).normalize()
    return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")


def _run(cmd: list[str], description: str) -> None:
    print(f"[promotion-gate] ▶ {description}")
    proc = subprocess.run(cmd, cwd=str(BASE_DIR))
    if proc.returncode != 0:
        raise RuntimeError(f"{description} 失败，返回码={proc.returncode}")


def main() -> int:
    p = argparse.ArgumentParser(description="刷新 promotion gate latest 工件")
    p.add_argument("--config", type=str, default=str(PROFILE_FILE))
    p.add_argument("--profiles", type=str, default="", help="逗号分隔；默认取 default_profile + candidate")
    p.add_argument("--end", type=str, default="", help="rolling compare 结束日期 YYYY-MM-DD；默认主数据最新日")
    p.add_argument("--lookback-months", type=int, default=int(os.environ.get("MFTS_PROMOTION_LOOKBACK_MONTHS", "10")))
    p.add_argument("--train-months", type=int, default=int(os.environ.get("MFTS_PROMOTION_TRAIN_MONTHS", "4")))
    p.add_argument("--test-months", type=int, default=int(os.environ.get("MFTS_PROMOTION_TEST_MONTHS", "2")))
    p.add_argument("--step-months", type=int, default=int(os.environ.get("MFTS_PROMOTION_STEP_MONTHS", "1")))
    p.add_argument("--p2-windows", type=str, default=os.environ.get("MFTS_PROMOTION_P2_WINDOWS", "20,60,90,120"))
    p.add_argument("--max-metadata-staleness-days", type=float, default=float(os.environ.get("MFTS_MAX_METADATA_STALENESS_DAYS", "999.0")))
    p.add_argument("--min-p2-executed-days", type=int, default=int(os.environ.get("MFTS_MIN_P2_EXECUTED_DAYS", "20")))
    p.add_argument("--min-promote-margin", type=float, default=float(os.environ.get("MFTS_MIN_PROMOTE_MARGIN", "1.0")))
    args = p.parse_args()

    config_file = Path(args.config).resolve()
    profiles = [x.strip() for x in str(args.profiles).split(",") if x.strip()] or _load_profiles(config_file)
    start, end = _derive_period(args.end or None, int(args.lookback_months))
    profile_arg = ",".join(profiles)

    _run(
        [
            sys.executable,
            str(BASE_DIR / "scripts" / "quant_profile_rolling_compare.py"),
            "--config",
            str(config_file),
            "--profiles",
            profile_arg,
            "--start",
            start,
            "--end",
            end,
            "--train-months",
            str(max(1, int(args.train_months))),
            "--test-months",
            str(max(1, int(args.test_months))),
            "--step-months",
            str(max(1, int(args.step_months))),
            "--write-latest",
        ],
        "rolling compare latest",
    )

    _run(
        [
            sys.executable,
            str(BASE_DIR / "scripts" / "quant_p2_rolling_replay.py"),
            "--profiles",
            profile_arg,
            "--windows",
            str(args.p2_windows),
            "--style-size-grid",
            "999",
            "--style-beta-grid",
            "999",
            "--style-momentum-grid",
            "999",
            "--style-vol-grid",
            "999",
            "--style-lb-short-grid",
            "20",
            "--style-lb-beta-grid",
            "60",
            "--max-grid-combos",
            "1",
            "--max-metadata-staleness-days",
            str(max(0.0, float(args.max_metadata_staleness_days))),
            "--write-latest",
        ],
        "P2 rolling replay latest",
    )

    _run(
        [
            sys.executable,
            str(BASE_DIR / "scripts" / "quant_p2_shadow_diagnosis.py"),
            "--profiles",
            profile_arg,
            "--windows",
            str(args.p2_windows),
            "--write-latest",
        ],
        "P2 shadow diagnosis latest",
    )

    _run(
        [
            sys.executable,
            str(BASE_DIR / "scripts" / "quant_research_execution_funnel.py"),
            "--profiles",
            profile_arg,
            "--write-latest",
        ],
        "research-to-execution funnel latest",
    )

    _run(
        [
            sys.executable,
            str(BASE_DIR / "scripts" / "quant_profile_promotion_review.py"),
            "--config",
            str(config_file),
            "--profiles",
            profile_arg,
            "--rolling-summary",
            str(BACKTEST_DIR / "quant_profile_rolling_compare_summary_latest.csv"),
            "--p2-summary",
            str(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"),
            "--min-p2-executed-days",
            str(max(1, int(args.min_p2_executed_days))),
            "--min-promote-margin",
            str(float(args.min_promote_margin)),
            "--write-latest",
        ],
        "promotion review latest",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
