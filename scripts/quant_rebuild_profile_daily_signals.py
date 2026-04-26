#!/usr/bin/env python3
"""Rebuild profile-isolated daily signals for P2 replay evidence."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

DATA_FILE = BASE_DIR / "data" / "daily_all_5y.parquet"
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs" / "profile_daily_rebuild"
DAILY_SCRIPT = BASE_DIR / "scripts" / "daily_ml_select.py"


def _parse_profiles(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def _load_trade_dates() -> list[str]:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"missing data file: {DATA_FILE}")
    df = pd.read_parquet(DATA_FILE, columns=["trade_date", "ts_code"])
    if df.empty:
        return []
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), errors="coerce")
    df = df.dropna(subset=["trade_date"])
    counts = df.groupby(df["trade_date"].dt.strftime("%Y%m%d"))["ts_code"].nunique()
    return sorted(counts[counts > 0].index.astype(str).tolist())


def _select_dates(args: argparse.Namespace) -> list[str]:
    dates = _load_trade_dates()
    if not dates:
        return []
    if args.start or args.end:
        start = str(args.start or dates[0])
        end = str(args.end or dates[-1])
        dates = [d for d in dates if start <= d <= end]
    elif int(args.days) > 0:
        dates = dates[-int(args.days) :]
    return dates


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Rebuild profile-isolated daily signal files")
    p.add_argument("--profiles", required=True, help="Comma-separated profile names")
    p.add_argument("--days", type=int, default=120, help="Recent trading days to rebuild when start/end are absent")
    p.add_argument("--start", type=str, default="", help="Start date YYYYMMDD")
    p.add_argument("--end", type=str, default="", help="End date YYYYMMDD")
    p.add_argument("--stage-min-stocks", type=int, default=int(os.environ.get("MFTS_STAGE_MIN_STOCKS", "3000")))
    p.add_argument("--force", action="store_true", help="Overwrite existing profile daily files")
    p.add_argument("--strict", action="store_true", help="Return nonzero when any date/profile fails")
    p.add_argument("--verbose", action="store_true", help="Stream child daily_ml_select output instead of writing logs")
    p.add_argument("--disable-industry-coverage-gate", action="store_true")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    profiles = _parse_profiles(args.profiles)
    if not profiles:
        print("No profiles provided")
        return 1
    dates = _select_dates(args)
    if not dates:
        print("No dates selected")
        return 1

    rows: list[dict[str, object]] = []
    for profile in profiles:
        out_dir = OUTPUT_DIR / "daily_profiles" / profile
        out_dir.mkdir(parents=True, exist_ok=True)
        for d in dates:
            out_file = out_dir / f"daily_{d}.csv"
            if out_file.exists() and not bool(args.force):
                rows.append({"profile": profile, "date": d, "status": "skipped", "return_code": 0})
                continue
            cmd = [
                sys.executable,
                str(DAILY_SCRIPT),
                "--date",
                d,
                "--output-profile",
                profile,
                "--min-industry-coverage-pct",
                os.environ.get("MFTS_MIN_INDUSTRY_COVERAGE_PCT", "80.0"),
                "--max-metadata-staleness-days",
                os.environ.get("MFTS_MAX_METADATA_STALENESS_DAYS", "3.0"),
            ]
            if bool(args.disable_industry_coverage_gate):
                cmd.append("--disable-industry-coverage-gate")
            env = os.environ.copy()
            env["MFTS_ACTIVE_PROFILE"] = profile
            env["MFTS_P2_PROFILE"] = profile
            env["MFTS_DAILY_OUTPUT_PROFILE"] = profile
            env["MFTS_STAGE_MIN_STOCKS"] = str(max(0, int(args.stage_min_stocks)))
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] rebuild {profile} {d}", flush=True)
            if bool(args.verbose):
                proc = subprocess.run(cmd, cwd=str(BASE_DIR), env=env)
                log_file = ""
            else:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                log_path = LOG_DIR / f"{profile}_{d}.log"
                proc = subprocess.run(cmd, cwd=str(BASE_DIR), env=env, text=True, capture_output=True)
                log_path.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
                log_file = str(log_path)
            status = "ok" if proc.returncode == 0 else "failed"
            rows.append(
                {
                    "profile": profile,
                    "date": d,
                    "status": status,
                    "return_code": int(proc.returncode),
                    "log_file": log_file,
                }
            )
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {status} {profile} {d}", flush=True)
            if proc.returncode != 0 and bool(args.strict):
                break

    summary = pd.DataFrame(rows)
    out = OUTPUT_DIR / "backtest" / f"profile_daily_rebuild_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out, index=False, encoding="utf-8-sig")
    latest = OUTPUT_DIR / "backtest" / "profile_daily_rebuild_latest.csv"
    summary.to_csv(latest, index=False, encoding="utf-8-sig")
    failed = int((summary.get("status", pd.Series(dtype=str)).astype(str) == "failed").sum()) if not summary.empty else 0
    print(f"summary={out} failed={failed}", flush=True)
    return 1 if failed and bool(args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
