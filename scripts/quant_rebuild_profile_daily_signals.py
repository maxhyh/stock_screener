#!/usr/bin/env python3
"""Rebuild profile-isolated daily signals for P2 replay evidence."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from core.data.market_data_gateway import AShareMarketDataGateway

OUTPUT_DIR = BASE_DIR / "output"
DAILY_DIR = OUTPUT_DIR / "daily"
LOG_DIR = BASE_DIR / "logs" / "profile_daily_rebuild"
DAILY_SCRIPT = BASE_DIR / "scripts" / "daily_ml_select.py"

_DAILY_MODULE_CACHE = None


def _parse_profiles(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def _load_trade_dates() -> list[str]:
    """Use ODS replayable sessions, never a local legacy parquet calendar."""
    return [pd.Timestamp(date).strftime("%Y%m%d") for date in AShareMarketDataGateway().available_trade_dates()]


def _load_daily_file_dates(daily_dir: Path | None = None) -> list[str]:
    daily_dir = daily_dir or DAILY_DIR
    if not daily_dir.exists():
        return []
    dates: list[str] = []
    for path in daily_dir.glob("daily_*.csv"):
        stem = path.stem
        raw = stem.replace("daily_", "", 1)
        if len(raw) == 8 and raw.isdigit():
            dates.append(raw)
    return sorted(set(dates))


def _normalize_yyyymmdd(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.notna(ts):
        return ts.strftime("%Y%m%d")
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _select_dates(args: argparse.Namespace) -> list[str]:
    if str(getattr(args, "date_source", "data")) == "daily-files":
        dates = _load_daily_file_dates()
        if not dates:
            dates = _load_trade_dates()
    else:
        dates = _load_trade_dates()
    if not dates:
        return []
    if bool(getattr(args, "replayable_only", False)):
        trade_dates = _load_trade_dates()
        if trade_dates:
            last_trade_date = str(trade_dates[-1])
            dates = [d for d in dates if str(d) < last_trade_date]
    if args.start or args.end:
        start = _normalize_yyyymmdd(args.start) if args.start else str(dates[0])
        end = _normalize_yyyymmdd(args.end) if args.end else str(dates[-1])
        dates = [d for d in dates if start <= d <= end]
        if not args.start and int(args.days) > 0:
            dates = dates[-int(args.days) :]
    elif int(args.days) > 0:
        dates = dates[-int(args.days) :]
    return dates


def _remove_output_file(path: Path) -> bool:
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception:
        return False
    return False


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Rebuild profile-isolated daily signal files")
    p.add_argument("--profiles", required=True, help="Comma-separated profile names")
    p.add_argument("--days", type=int, default=120, help="Recent trading days to rebuild when start/end are absent")
    p.add_argument("--start", type=str, default="", help="Start date YYYYMMDD")
    p.add_argument("--end", type=str, default="", help="End date YYYYMMDD")
    p.add_argument("--stage-min-stocks", type=int, default=int(os.environ.get("MFTS_STAGE_MIN_STOCKS", "3000")))
    p.add_argument(
        "--max-metadata-staleness-days",
        type=float,
        default=float(os.environ.get("MFTS_MAX_METADATA_STALENESS_DAYS", "3.0")),
        help="Forwarded to daily_ml_select metadata gate; use a large value for historical evidence rebuilds",
    )
    p.add_argument("--force", action="store_true", help="Overwrite existing profile daily files")
    p.add_argument("--strict", action="store_true", help="Return nonzero when any date/profile fails")
    p.add_argument("--verbose", action="store_true", help="Stream child daily_ml_select output instead of writing logs")
    p.add_argument("--disable-industry-coverage-gate", action="store_true")
    p.add_argument(
        "--replayable-only",
        action="store_true",
        help="Exclude signal dates without a next market trade day before applying --days/start/end selection",
    )
    p.add_argument(
        "--date-source",
        choices=["data", "daily-files"],
        default=os.environ.get("MFTS_DAILY_REBUILD_DATE_SOURCE", "data"),
        help="Select rebuild calendar from parquet data or existing output/daily file names",
    )
    p.add_argument(
        "--execution-mode",
        choices=["subprocess", "inprocess"],
        default=os.environ.get("MFTS_DAILY_REBUILD_EXECUTION_MODE", "subprocess"),
        help="Run daily_ml_select as historical subprocesses or in-process to reduce startup overhead",
    )
    return p


def _run_daily_select(
    cmd: list[str],
    *,
    env: dict[str, str],
    execution_mode: str,
    verbose: bool,
) -> subprocess.CompletedProcess:
    if execution_mode == "subprocess":
        if verbose:
            return subprocess.run(cmd, cwd=str(BASE_DIR), env=env)
        return subprocess.run(cmd, cwd=str(BASE_DIR), env=env, text=True, capture_output=True)

    old_argv = sys.argv[:]
    old_env = os.environ.copy()
    old_cwd = os.getcwd()
    stdout = io.StringIO()
    stderr = io.StringIO()
    global _DAILY_MODULE_CACHE
    rc = 1
    try:
        os.environ.clear()
        os.environ.update(env)
        os.chdir(BASE_DIR)
        sys.argv = [str(DAILY_SCRIPT), *cmd[2:]]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            if _DAILY_MODULE_CACHE is None:
                mod = importlib.import_module("scripts.daily_ml_select")
                _DAILY_MODULE_CACHE = mod
            else:
                mod = _DAILY_MODULE_CACHE
            result = mod.main()
            rc = int(result or 0)
    except SystemExit as exc:
        try:
            rc = int(exc.code or 0)
        except Exception:
            rc = 1
    except Exception as exc:
        rc = 1
        stderr.write(f"{type(exc).__name__}: {exc}\n")
    finally:
        sys.argv = old_argv
        os.environ.clear()
        os.environ.update(old_env)
        os.chdir(old_cwd)
    if verbose:
        if stdout.getvalue():
            print(stdout.getvalue(), end="")
        if stderr.getvalue():
            print(stderr.getvalue(), end="", file=sys.stderr)
    return subprocess.CompletedProcess(cmd, rc, stdout.getvalue(), stderr.getvalue())


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
    indicator_cache_start = ""
    indicator_cache_end = ""
    if str(args.execution_mode) == "inprocess":
        lookback_days = max(1, int(os.environ.get("MFTS_ML_LOOKBACK_DAYS", "450")))
        forward_days = max(0, int(os.environ.get("MFTS_ML_FORWARD_BUFFER_DAYS", "2")))
        if str(os.environ.get("MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY", "false")).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }:
            forward_days = max(forward_days, int(os.environ.get("MFTS_SIGNAL_PRETRADE_FORWARD_BUFFER_DAYS", "10")))
        indicator_cache_start = (pd.to_datetime(dates[0]) - pd.Timedelta(days=lookback_days)).strftime("%Y%m%d")
        indicator_cache_end = (pd.to_datetime(dates[-1]) + pd.Timedelta(days=forward_days)).strftime("%Y%m%d")

    rows: list[dict[str, object]] = []
    for profile in profiles:
        out_dir = OUTPUT_DIR / "daily_profiles" / profile
        out_dir.mkdir(parents=True, exist_ok=True)
        for d in dates:
            out_file = out_dir / f"daily_{d}.csv"
            if out_file.exists() and not bool(args.force):
                rows.append(
                    {
                        "profile": profile,
                        "date": d,
                        "status": "skipped",
                        "return_code": 0,
                        "output_file": str(out_file),
                        "stale_output_removed": 0,
                    }
                )
                continue
            stale_removed = int(_remove_output_file(out_file)) if bool(args.force) else 0
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
                str(max(0.0, float(args.max_metadata_staleness_days))),
            ]
            if bool(args.disable_industry_coverage_gate):
                cmd.append("--disable-industry-coverage-gate")
            env = os.environ.copy()
            env["MFTS_ACTIVE_PROFILE"] = profile
            env["MFTS_P2_PROFILE"] = profile
            env["MFTS_DAILY_OUTPUT_PROFILE"] = profile
            env["MFTS_ALLOW_EMPTY_DAILY_OUTPUT"] = "true"
            env["MFTS_STAGE_MIN_STOCKS"] = str(max(0, int(args.stage_min_stocks)))
            if str(args.execution_mode) == "inprocess":
                env.setdefault("MFTS_DAILY_SELECT_CACHE_DATA", "true")
                env.setdefault("MFTS_DAILY_SELECT_CACHE_MODEL", "true")
                env.setdefault("MFTS_DAILY_SELECT_PRECOMPUTE_INDICATORS", "true")
                if indicator_cache_start:
                    env.setdefault("MFTS_DAILY_SELECT_CACHE_START", indicator_cache_start)
                if indicator_cache_end:
                    env.setdefault("MFTS_DAILY_SELECT_CACHE_END", indicator_cache_end)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] rebuild {profile} {d}", flush=True)
            proc = _run_daily_select(
                cmd,
                env=env,
                execution_mode=str(args.execution_mode),
                verbose=bool(args.verbose),
            )
            if bool(args.verbose):
                log_file = ""
            else:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                log_path = LOG_DIR / f"{profile}_{d}.log"
                log_path.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
                log_file = str(log_path)
            status = "ok" if proc.returncode == 0 else "failed"
            if proc.returncode != 0 and out_file.exists():
                stale_removed = int(_remove_output_file(out_file)) or stale_removed
            rows.append(
                {
                    "profile": profile,
                    "date": d,
                    "status": status,
                    "return_code": int(proc.returncode),
                    "output_file": str(out_file),
                    "stale_output_removed": int(stale_removed),
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
