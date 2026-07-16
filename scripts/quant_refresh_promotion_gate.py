#!/usr/bin/env python3
"""
刷新 profile promotion gate 所需的 latest 工件。

流程：
1) 可选刷新 score-alpha latest，检验最终排序/target weight 是否有推荐代理 alpha
2) 运行 rolling compare，更新 latest 研究侧工件
3) 运行 P2 rolling replay，更新 latest 执行侧工件
4) 运行 promotion review，产出 latest review / decision
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from utils.output_paths import get_output_dirs, list_dual  # noqa: E402
from core.data.market_data_gateway import AShareMarketDataGateway  # noqa: E402

PROFILE_FILE = BASE_DIR / "config" / "quant_live_profiles.json"
OUTPUT_DIR = BASE_DIR / "output"
BACKTEST_DIR = BASE_DIR / "output" / "backtest"
DAILY_PROFILE_DIR = BASE_DIR / "output" / "daily_profiles"
ROLLING_SUMMARY_LATEST = BACKTEST_DIR / "quant_profile_rolling_compare_summary_latest.csv"


def _parse_windows(raw: object) -> list[int]:
    out: list[int] = []
    for tok in str(raw or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            value = int(tok)
        except Exception:
            continue
        if value > 0:
            out.append(value)
    return sorted(set(out))


def _derive_min_profile_signal_days(raw_min: int, windows: list[int]) -> int:
    if int(raw_min) > 0:
        return int(raw_min)
    evidence_windows = [int(x) for x in windows if int(x) >= 60]
    source = evidence_windows or windows
    return int(min(source)) if source else 60


def _normalize_yyyymmdd(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return ""
    return ts.strftime("%Y%m%d")


def _normalize_trade_date_fast(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw[:10] if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _load_market_last_trade_date() -> str:
    dates = _load_market_trade_dates()
    return dates[-1] if dates else ""


def _load_market_trade_dates(data_file: Path | None = None) -> list[str]:
    """Return replayable ODS sessions; legacy argument is intentionally ignored."""
    del data_file
    return [_normalize_yyyymmdd(date) for date in AShareMarketDataGateway().available_trade_dates()]


def _sanitize_profile_slug(profile: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(profile)).strip("._")


def _capacity_feasible_daily_path(profile: str, backtest_dir: Path = BACKTEST_DIR) -> Path:
    slug = _sanitize_profile_slug(str(profile))
    return backtest_dir / f"quant_capacity_feasible_alpha_diagnosis_latest_{slug}_daily.csv"


def _static_to_p2_score_col(root_config: dict, profile: str) -> str:
    profiles = root_config.get("profiles", {})
    cfg = profiles.get(str(profile), {}) if isinstance(profiles, dict) else {}
    if isinstance(cfg, dict):
        for key in ("capacity_safe_primary_label_score_col", "target_score_col"):
            value = str(cfg.get(key, "") or "").strip()
            if value:
                return value
    return "portfolio_rank_score"


def _list_profile_daily_dates(profile: str, daily_profile_dir: Path = DAILY_PROFILE_DIR) -> list[str]:
    slug = _sanitize_profile_slug(str(profile))
    if not slug:
        return []
    profile_dir = daily_profile_dir / slug
    if not profile_dir.exists():
        return []
    pat = re.compile(r"daily_(\d{8})\.csv$")
    dates: list[str] = []
    for fp in profile_dir.glob("daily_*.csv"):
        m = pat.match(fp.name)
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


def _list_shared_daily_dates(output_dir: Path = OUTPUT_DIR) -> list[str]:
    dirs = get_output_dirs(output_dir)
    files = list_dual(["daily_*.csv"], dirs["daily"], dirs["base"])
    pat = re.compile(r"daily_(\d{8})\.csv$")
    dates: list[str] = []
    for fp in files:
        m = pat.match(fp.name)
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


def _build_reference_signal_dates(
    *,
    end: str,
    market_trade_dates: list[str] | None = None,
    required_signal_days: int,
    output_dir: Path = OUTPUT_DIR,
) -> list[str]:
    end_yyyymmdd = _normalize_yyyymmdd(end)
    market_trade_dates = sorted(set(str(x) for x in (market_trade_dates or []) if str(x).strip()))
    last_trade = market_trade_dates[-1] if market_trade_dates else ""
    market_set = set(market_trade_dates)
    dates = _list_shared_daily_dates(output_dir)
    dates = [
        d
        for d in dates
        if (not end_yyyymmdd or d <= end_yyyymmdd)
        and (not last_trade or d < last_trade)
        and (not market_set or d in market_set)
    ]
    required = max(1, int(required_signal_days))
    return dates[-required:]


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
        market_last = _load_market_last_trade_date()
        if not market_last:
            raise RuntimeError("共享 ODS 没有可用交易日，无法推导 promotion gate 时间范围")
        end_dt = pd.to_datetime(market_last, format="%Y%m%d").normalize()
    start_dt = (end_dt - pd.DateOffset(months=max(1, int(lookback_months)))).normalize()
    return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")


def _run(cmd: list[str], description: str) -> None:
    print(f"[promotion-gate] ▶ {description}")
    proc = subprocess.run(cmd, cwd=str(BASE_DIR))
    if proc.returncode != 0:
        raise RuntimeError(f"{description} 失败，返回码={proc.returncode}")


def _discover_score_alpha_diagnosis_files(profiles: list[str], backtest_dir: Path = BACKTEST_DIR) -> list[Path]:
    files: list[Path] = []
    for profile in profiles:
        fp = backtest_dir / f"quant_score_alpha_diagnosis_latest_{profile}.json"
        if fp.exists():
            files.append(fp)
    return files


def _discover_score_alpha_daily_globs(profiles: list[str], daily_profile_dir: Path = DAILY_PROFILE_DIR) -> dict[str, str]:
    out: dict[str, str] = {}
    for profile in profiles:
        profile_dir = daily_profile_dir / str(profile)
        if not profile_dir.exists():
            continue
        if not any(profile_dir.glob("daily_*.csv")):
            continue
        out[str(profile)] = str(profile_dir / "daily_*.csv")
    return out


def _read_score_alpha_gate(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    gate = payload.get("alpha_quality_gate", {})
    if not isinstance(gate, dict):
        return {}
    return dict(gate)


def _score_alpha_gate_passes(path: Path) -> bool:
    gate = _read_score_alpha_gate(path)
    return bool(gate.get("pass", False))


def _detect_score_alpha_profile(path: Path, profiles: list[str]) -> str:
    stem = path.stem
    marker = "quant_score_alpha_diagnosis_latest_"
    if stem.startswith(marker):
        return stem[len(marker) :]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    label = str(payload.get("artifact_label", "")) if isinstance(payload, dict) else ""
    text = f"{label} {path.name}"
    for profile in sorted(profiles, key=len, reverse=True):
        if str(label) == str(profile) or str(profile) in text:
            return str(profile)
    return ""


def _build_score_alpha_precheck(
    *,
    profiles: list[str],
    main_profile: str,
    score_alpha_files: list[Path],
) -> tuple[list[str], list[dict[str, object]]]:
    by_profile: dict[str, Path] = {}
    for fp in score_alpha_files:
        profile = _detect_score_alpha_profile(fp, profiles)
        if profile:
            by_profile[profile] = fp
    keep: list[str] = []
    rows: list[dict[str, object]] = []
    for profile in profiles:
        if str(profile) == str(main_profile):
            keep.append(str(profile))
            rows.append(
                {
                    "profile": str(profile),
                    "decision": "keep",
                    "is_main_profile": True,
                    "score_alpha_file": "",
                    "score_alpha_gate_pass": True,
                    "reason": "main_profile_always_kept",
                    "gate_reasons": "",
                }
            )
            continue
        fp = by_profile.get(str(profile))
        gate = _read_score_alpha_gate(fp) if fp else {}
        passed = bool(gate.get("pass", False))
        reasons = gate.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = [str(reasons)] if reasons else []
        if fp and passed:
            keep.append(str(profile))
        reason = "score_alpha_passed" if passed else ("score_alpha_gate_failed" if fp else "score_alpha_missing")
        rows.append(
            {
                "profile": str(profile),
                "decision": "keep" if passed else "skip",
                "is_main_profile": False,
                "score_alpha_file": str(fp) if fp else "",
                "score_alpha_gate_pass": bool(passed),
                "reason": reason,
                "gate_reasons": ",".join(str(x) for x in reasons),
            }
        )
    return keep, rows


def _filter_profiles_by_score_alpha_gate(
    *,
    profiles: list[str],
    main_profile: str,
    score_alpha_files: list[Path],
) -> list[str]:
    keep, rows = _build_score_alpha_precheck(
        profiles=profiles,
        main_profile=main_profile,
        score_alpha_files=score_alpha_files,
    )
    for row in rows:
        if row.get("decision") == "skip":
            profile = row.get("profile", "")
            print(f"[promotion-gate] precheck skip {profile}: score-alpha gate missing or failed")
    return keep


def _write_score_alpha_precheck_report(
    *,
    rows: list[dict[str, object]],
    requested_profiles: list[str],
    effective_profiles: list[str],
    main_profile: str,
    backtest_dir: Path = BACKTEST_DIR,
) -> tuple[Path, Path]:
    backtest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "main_profile": str(main_profile),
        "requested_profiles": [str(x) for x in requested_profiles],
        "effective_profiles": [str(x) for x in effective_profiles],
        "skipped_profiles": [str(r.get("profile", "")) for r in rows if r.get("decision") == "skip"],
        "rows": rows,
    }
    json_path = backtest_dir / f"quant_score_alpha_precheck_{ts}.json"
    csv_path = backtest_dir / f"quant_score_alpha_precheck_{ts}.csv"
    latest_json = backtest_dir / "quant_score_alpha_precheck_latest.json"
    latest_csv = backtest_dir / "quant_score_alpha_precheck_latest.csv"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(latest_csv, index=False, encoding="utf-8-sig")
    return json_path, csv_path


def _build_signal_coverage_precheck(
    *,
    profiles: list[str],
    main_profile: str,
    min_required_days: int,
    end: str,
    market_last_trade_date: str,
    daily_profile_dir: Path = DAILY_PROFILE_DIR,
    reference_dates: list[str] | None = None,
    market_trade_dates: list[str] | None = None,
) -> tuple[list[str], list[dict[str, object]]]:
    keep: list[str] = []
    rows: list[dict[str, object]] = []
    end_yyyymmdd = _normalize_yyyymmdd(end)
    last_trade = str(market_last_trade_date or "").strip()
    market_set = set(str(x) for x in (market_trade_dates or []) if str(x).strip())
    required = max(1, int(min_required_days))
    reference_dates = sorted(set(str(x) for x in (reference_dates or []) if str(x).strip()))
    for profile in profiles:
        profile = str(profile)
        is_main = profile == str(main_profile)
        raw_dates = _list_profile_daily_dates(profile, daily_profile_dir)
        dates_le_end = [d for d in raw_dates if not end_yyyymmdd or d <= end_yyyymmdd]
        replayable_dates = [
            d for d in dates_le_end if (not last_trade or d < last_trade) and (not market_set or d in market_set)
        ]
        raw_count = int(len(raw_dates))
        within_end_count = int(len(dates_le_end))
        replayable_count = int(len(replayable_dates))
        coverage_pct = float(replayable_count / required * 100.0)
        replayable_set = set(replayable_dates)
        missing_reference = [d for d in reference_dates if d not in replayable_set]
        reference_count = int(len(reference_dates))
        reference_covered = int(reference_count - len(missing_reference))
        reference_coverage_pct = float(reference_covered / reference_count * 100.0) if reference_count else 0.0
        if is_main and reference_count:
            missing_reference = []
            reference_covered = reference_count
            reference_coverage_pct = 100.0
        if is_main:
            decision = "keep"
            reason = "main_profile_always_kept"
            keep.append(profile)
        elif raw_count <= 0:
            decision = "skip"
            reason = "profile_daily_missing"
        elif replayable_count < required:
            decision = "skip"
            reason = "profile_signal_days_insufficient"
        elif missing_reference:
            decision = "skip"
            reason = "profile_signal_calendar_mismatch"
        else:
            decision = "keep"
            reason = "profile_signal_coverage_passed"
            keep.append(profile)
        rows.append(
            {
                "profile": profile,
                "decision": decision,
                "is_main_profile": bool(is_main),
                "reason": reason,
                "required_signal_days": int(required),
                "raw_profile_signal_days": int(raw_count),
                "profile_signal_days_le_end": int(within_end_count),
                "replayable_profile_signal_days": int(replayable_count),
                "signal_coverage_pct": float(coverage_pct),
                "first_signal_date": replayable_dates[0] if replayable_dates else "",
                "last_signal_date": replayable_dates[-1] if replayable_dates else "",
                "required_reference_signal_days": int(reference_count),
                "reference_signal_days_covered": int(reference_covered),
                "reference_signal_coverage_pct": float(reference_coverage_pct),
                "missing_reference_signal_days": int(len(missing_reference)),
                "missing_reference_signal_dates": ",".join(missing_reference),
                "end_date": str(end),
                "market_last_trade_date": str(last_trade),
                "excluded_after_end_days": int(max(raw_count - within_end_count, 0)),
                "excluded_no_next_trade_days": int(max(within_end_count - replayable_count, 0)),
            }
        )
    return keep, rows


def _write_signal_coverage_precheck_report(
    *,
    rows: list[dict[str, object]],
    requested_profiles: list[str],
    effective_profiles: list[str],
    main_profile: str,
    min_required_days: int,
    backtest_dir: Path = BACKTEST_DIR,
) -> tuple[Path, Path]:
    backtest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "main_profile": str(main_profile),
        "min_required_signal_days": int(min_required_days),
        "requested_profiles": [str(x) for x in requested_profiles],
        "effective_profiles": [str(x) for x in effective_profiles],
        "skipped_profiles": [str(r.get("profile", "")) for r in rows if r.get("decision") == "skip"],
        "rows": rows,
    }
    json_path = backtest_dir / f"quant_signal_coverage_precheck_{ts}.json"
    csv_path = backtest_dir / f"quant_signal_coverage_precheck_{ts}.csv"
    latest_json = backtest_dir / "quant_signal_coverage_precheck_latest.json"
    latest_csv = backtest_dir / "quant_signal_coverage_precheck_latest.csv"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(latest_csv, index=False, encoding="utf-8-sig")
    return json_path, csv_path


def _profile_daily_paths_by_date(profile: str, daily_profile_dir: Path = DAILY_PROFILE_DIR) -> dict[str, Path]:
    slug = _sanitize_profile_slug(str(profile))
    if not slug:
        return {}
    profile_dir = daily_profile_dir / slug
    if not profile_dir.exists():
        return {}
    pat = re.compile(r"daily_(\d{8})\.csv$")
    out: dict[str, Path] = {}
    for fp in profile_dir.glob("daily_*.csv"):
        m = pat.match(fp.name)
        if m:
            out[m.group(1)] = fp
    return out


def _shared_daily_paths_by_date(output_dir: Path = OUTPUT_DIR) -> dict[str, Path]:
    dirs = get_output_dirs(output_dir)
    files = list_dual(["daily_*.csv"], dirs["daily"], dirs["base"])
    pat = re.compile(r"daily_(\d{8})\.csv$")
    out: dict[str, Path] = {}
    for fp in files:
        m = pat.match(fp.name)
        if m:
            out[m.group(1)] = fp
    return out


def _target_weight_sum_for_daily(path: Path) -> tuple[float, bool, int]:
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return 0.0, False, 0
    except Exception:
        return 0.0, False, 0
    if "target_weight" not in df.columns:
        return 0.0, False, int(len(df))
    vals = pd.to_numeric(df["target_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    return float(vals.sum()), True, int(len(df))


def _build_target_utilization_precheck(
    *,
    profiles: list[str],
    main_profile: str,
    required_signal_days: int,
    end: str,
    market_last_trade_date: str,
    daily_profile_dir: Path = DAILY_PROFILE_DIR,
    output_dir: Path = OUTPUT_DIR,
    reference_dates: list[str] | None = None,
    market_trade_dates: list[str] | None = None,
    min_target_weight_sum_mean: float = 0.30,
    max_zero_target_rate_pct: float = 5.0,
) -> tuple[list[str], list[dict[str, object]]]:
    required = max(1, int(required_signal_days))
    suffix = f"_{required}"
    end_yyyymmdd = _normalize_yyyymmdd(end)
    last_trade = str(market_last_trade_date or "").strip()
    market_set = set(str(x) for x in (market_trade_dates or []) if str(x).strip())
    reference_dates = sorted(set(str(x) for x in (reference_dates or []) if str(x).strip()))
    shared_paths = _shared_daily_paths_by_date(output_dir)
    raw_rows: list[dict[str, object]] = []
    main_metrics: dict[str, object] = {}

    for profile in profiles:
        profile = str(profile)
        is_main = profile == str(main_profile)
        path_map = _profile_daily_paths_by_date(profile, daily_profile_dir)
        source = "profile_daily"
        if is_main and not path_map:
            path_map = shared_paths
            source = "shared_daily"
        raw_dates = sorted(path_map)
        replayable_dates = [
            d
            for d in raw_dates
            if (not end_yyyymmdd or d <= end_yyyymmdd)
            and (not last_trade or d < last_trade)
            and (not market_set or d in market_set)
        ]
        target_dates = list(reference_dates) if reference_dates else replayable_dates[-required:]
        sums: list[float] = []
        missing_dates: list[str] = []
        missing_target_dates: list[str] = []
        total_rows = 0
        for day in target_dates:
            fp = path_map.get(day)
            if fp is None:
                missing_dates.append(day)
                continue
            target_sum, has_target_weight, row_count = _target_weight_sum_for_daily(fp)
            total_rows += int(row_count)
            if not has_target_weight:
                missing_target_dates.append(day)
                continue
            sums.append(float(target_sum))
        s = pd.Series(sums, dtype=float)
        available_days = int(len(sums))
        mean_sum = float(s.mean()) if available_days else 0.0
        p10_sum = float(s.quantile(0.10)) if available_days else 0.0
        zero_days = int((s <= 1e-12).sum()) if available_days else 0
        zero_rate = float(zero_days / available_days * 100.0) if available_days else 0.0
        target_available = bool(available_days > 0 and not missing_dates and not missing_target_dates)
        row = {
            "profile": profile,
            "is_main_profile": bool(is_main),
            "decision": "keep",
            "reason": "main_profile_always_kept" if is_main else "target_utilization_passed",
            "daily_source": source,
            "required_signal_days": int(required),
            "target_utilization_days": int(available_days),
            "target_utilization_available": bool(target_available),
            "target_utilization_rows": int(total_rows),
            f"target_weight_sum_mean{suffix}": float(mean_sum),
            f"target_weight_sum_p10{suffix}": float(p10_sum),
            f"zero_target_days{suffix}": int(zero_days),
            f"zero_target_rate_pct{suffix}": float(zero_rate),
            "target_weight_sum_mean": float(mean_sum),
            "target_weight_sum_p10": float(p10_sum),
            "zero_target_days": int(zero_days),
            "zero_target_rate_pct": float(zero_rate),
            "min_target_weight_sum_mean": float(min_target_weight_sum_mean),
            "max_zero_target_rate_pct": float(max_zero_target_rate_pct),
            "missing_daily_days": int(len(missing_dates)),
            "missing_daily_dates": ",".join(missing_dates),
            "missing_target_weight_days": int(len(missing_target_dates)),
            "missing_target_weight_dates": ",".join(missing_target_dates),
            "first_signal_date": target_dates[0] if target_dates else "",
            "last_signal_date": target_dates[-1] if target_dates else "",
        }
        raw_rows.append(row)
        if is_main:
            main_metrics = row

    main_available = bool(main_metrics.get("target_utilization_available", False))
    main_mean = float(main_metrics.get("target_weight_sum_mean", 0.0))
    main_zero_rate = float(main_metrics.get("zero_target_rate_pct", 0.0))
    keep: list[str] = []
    rows: list[dict[str, object]] = []
    for row in raw_rows:
        is_main = bool(row.get("is_main_profile", False))
        if is_main:
            row["decision"] = "keep"
            row["reason"] = "main_profile_always_kept"
            keep.append(str(row.get("profile", "")))
            rows.append(row)
            continue
        reasons: list[str] = []
        if not bool(row.get("target_utilization_available", False)):
            reasons.append("target_utilization_missing")
        mean_sum = float(row.get("target_weight_sum_mean", 0.0))
        zero_rate = float(row.get("zero_target_rate_pct", 0.0))
        main_mean_exception = bool(main_available and main_mean < float(min_target_weight_sum_mean) and mean_sum >= main_mean - 1e-12)
        main_zero_exception = bool(main_available and main_zero_rate > float(max_zero_target_rate_pct) and zero_rate <= main_zero_rate + 1e-12)
        if mean_sum < float(min_target_weight_sum_mean) and not main_mean_exception:
            reasons.append("target_weight_sum_mean_below_floor")
        if zero_rate > float(max_zero_target_rate_pct) and not main_zero_exception:
            reasons.append("zero_target_rate_above_floor")
        if reasons:
            row["decision"] = "skip"
            row["reason"] = ",".join(reasons)
        else:
            row["decision"] = "keep"
            row["reason"] = "target_utilization_passed"
            keep.append(str(row.get("profile", "")))
        rows.append(row)
    return keep, rows


def _write_target_utilization_precheck_report(
    *,
    rows: list[dict[str, object]],
    requested_profiles: list[str],
    effective_profiles: list[str],
    main_profile: str,
    required_signal_days: int,
    backtest_dir: Path = BACKTEST_DIR,
) -> tuple[Path, Path]:
    backtest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "main_profile": str(main_profile),
        "required_signal_days": int(required_signal_days),
        "requested_profiles": [str(x) for x in requested_profiles],
        "effective_profiles": [str(x) for x in effective_profiles],
        "skipped_profiles": [str(r.get("profile", "")) for r in rows if r.get("decision") == "skip"],
        "rows": rows,
    }
    json_path = backtest_dir / f"quant_target_utilization_precheck_{ts}.json"
    csv_path = backtest_dir / f"quant_target_utilization_precheck_{ts}.csv"
    latest_json = backtest_dir / "quant_target_utilization_precheck_latest.json"
    latest_csv = backtest_dir / "quant_target_utilization_precheck_latest.csv"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(latest_csv, index=False, encoding="utf-8-sig")
    return json_path, csv_path


def _find_p2_summary_row(df: pd.DataFrame, profile: str, window: int) -> pd.Series | None:
    if df.empty or "profile" not in df.columns or "window" not in df.columns:
        return None
    mask = (df["profile"].astype(str) == str(profile)) & (pd.to_numeric(df["window"], errors="coerce") == int(window))
    rows = df.loc[mask]
    if rows.empty:
        return None
    return rows.iloc[0]


def _float_field(row: pd.Series | None, field: str, default: float = 0.0) -> float:
    if row is None or field not in row.index:
        return float(default)
    try:
        value = pd.to_numeric(row.get(field), errors="coerce")
        if pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _build_p2_smoke_precheck(
    *,
    profiles: list[str],
    main_profile: str,
    summary_path: Path,
    smoke_window: int,
    min_target_weight_sum: float,
    nav_margin_pct: float = 0.0,
    mdd_margin_pct: float = 0.0,
) -> tuple[list[str], list[dict[str, object]]]:
    keep: list[str] = []
    rows: list[dict[str, object]] = []
    try:
        df = pd.read_csv(summary_path)
    except Exception:
        df = pd.DataFrame()
    main_row = _find_p2_summary_row(df, str(main_profile), int(smoke_window))
    main_nav = _float_field(main_row, "nav_return_pct")
    main_mdd = _float_field(main_row, "max_drawdown_pct")
    main_entry_blocks = _float_field(main_row, "broker_entry_not_tradable_orders")
    main_exit_blocks = _float_field(main_row, "broker_exit_not_tradable_orders")
    main_run_failed = _float_field(main_row, "run_failed_days")
    for profile in profiles:
        profile = str(profile)
        is_main = profile == str(main_profile)
        row = _find_p2_summary_row(df, profile, int(smoke_window))
        reasons: list[str] = []
        if row is None:
            reasons.append("p2_smoke_row_missing")
        nav = _float_field(row, "nav_return_pct")
        mdd = _float_field(row, "max_drawdown_pct")
        target_sum = _float_field(row, "target_weight_sum_mean")
        run_failed = _float_field(row, "run_failed_days")
        entry_blocks = _float_field(row, "broker_entry_not_tradable_orders")
        exit_blocks = _float_field(row, "broker_exit_not_tradable_orders")
        if is_main:
            decision = "keep"
            reason = "main_profile_always_kept"
            keep.append(profile)
        else:
            if row is None:
                pass
            if run_failed > 0:
                reasons.append("p2_smoke_run_failed")
            if nav + float(nav_margin_pct) < main_nav:
                reasons.append("p2_smoke_nav_below_main")
            if mdd + float(mdd_margin_pct) < main_mdd:
                reasons.append("p2_smoke_mdd_worse_than_main")
            if target_sum < float(min_target_weight_sum):
                reasons.append("p2_smoke_target_weight_below_floor")
            if entry_blocks > main_entry_blocks:
                reasons.append("p2_smoke_entry_blocks_worse_than_main")
            if exit_blocks > main_exit_blocks:
                reasons.append("p2_smoke_exit_blocks_worse_than_main")
            if reasons:
                decision = "skip"
                reason = ",".join(reasons)
            else:
                decision = "keep"
                reason = "p2_smoke_passed"
                keep.append(profile)
        rows.append(
            {
                "profile": profile,
                "decision": decision,
                "is_main_profile": bool(is_main),
                "reason": reason,
                "window": int(smoke_window),
                "p2_summary": str(summary_path),
                "main_nav_return_pct": float(main_nav),
                "candidate_nav_return_pct": float(nav),
                "main_max_drawdown_pct": float(main_mdd),
                "candidate_max_drawdown_pct": float(mdd),
                "candidate_target_weight_sum_mean": float(target_sum),
                "min_target_weight_sum": float(min_target_weight_sum),
                "main_run_failed_days": float(main_run_failed),
                "candidate_run_failed_days": float(run_failed),
                "main_entry_not_tradable_orders": float(main_entry_blocks),
                "candidate_entry_not_tradable_orders": float(entry_blocks),
                "main_exit_not_tradable_orders": float(main_exit_blocks),
                "candidate_exit_not_tradable_orders": float(exit_blocks),
            }
        )
    return keep, rows


def _write_p2_smoke_precheck_report(
    *,
    rows: list[dict[str, object]],
    requested_profiles: list[str],
    effective_profiles: list[str],
    main_profile: str,
    smoke_window: int,
    backtest_dir: Path = BACKTEST_DIR,
) -> tuple[Path, Path]:
    backtest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "main_profile": str(main_profile),
        "smoke_window": int(smoke_window),
        "requested_profiles": [str(x) for x in requested_profiles],
        "effective_profiles": [str(x) for x in effective_profiles],
        "skipped_profiles": [str(r.get("profile", "")) for r in rows if r.get("decision") == "skip"],
        "rows": rows,
    }
    json_path = backtest_dir / f"quant_p2_smoke_precheck_{ts}.json"
    csv_path = backtest_dir / f"quant_p2_smoke_precheck_{ts}.csv"
    latest_json = backtest_dir / "quant_p2_smoke_precheck_latest.json"
    latest_csv = backtest_dir / "quant_p2_smoke_precheck_latest.csv"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(latest_csv, index=False, encoding="utf-8-sig")
    return json_path, csv_path


def _p2_rolling_replay_cmd(
    *,
    profiles_arg: str,
    windows_arg: str,
    max_metadata_staleness_days: float,
    execution_mode: str,
) -> list[str]:
    return [
        sys.executable,
        str(BASE_DIR / "scripts" / "quant_p2_rolling_replay.py"),
        "--profiles",
        str(profiles_arg),
        "--windows",
        str(windows_arg),
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
        str(max(0.0, float(max_metadata_staleness_days))),
        "--execution-mode",
        str(execution_mode),
        "--write-latest",
    ]


def _missing_profiles_in_summary(path: Path, profiles: list[str]) -> list[str]:
    if not path.exists():
        return [str(x) for x in profiles]
    try:
        df = pd.read_csv(path)
    except Exception:
        return [str(x) for x in profiles]
    if "profile" not in df.columns:
        return [str(x) for x in profiles]
    existing = set(df["profile"].dropna().astype(str))
    return [str(x) for x in profiles if str(x) not in existing]


def _validate_reused_rolling_summary(path: Path, profiles: list[str]) -> None:
    missing = _missing_profiles_in_summary(path, profiles)
    if missing:
        raise RuntimeError(
            f"复用 rolling summary 失败: {path} 缺少 profile={','.join(missing)}；"
            "请先刷新 rolling compare 或不要使用 --reuse-rolling-latest"
        )


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
    p.add_argument(
        "--profile-signal-root",
        type=str,
        default=str(DAILY_PROFILE_DIR),
        help="profile-isolated daily signal 根目录；默认 output/daily_profiles",
    )
    p.add_argument(
        "--precheck-signal-coverage",
        action="store_true",
        help="在 P2 前要求 candidate 具备足够 profile-isolated daily signal 覆盖率；main profile 始终保留",
    )
    p.add_argument(
        "--precheck-target-utilization",
        action="store_true",
        help="在 P2 前检查 profile daily target_weight 利用率；--precheck-signal-coverage 会自动启用该检查",
    )
    p.add_argument(
        "--target-utilization-window",
        type=int,
        default=int(os.environ.get("MFTS_TARGET_UTILIZATION_WINDOW", "60")),
        help="target utilization precheck 使用的 replayable signal days，默认 60",
    )
    p.add_argument(
        "--target-utilization-min-mean",
        type=float,
        default=float(os.environ.get("MFTS_TARGET_UTILIZATION_MIN_MEAN", "0.30")),
        help="candidate target_weight_sum_mean 下限；默认 30%",
    )
    p.add_argument(
        "--target-utilization-max-zero-rate-pct",
        type=float,
        default=float(os.environ.get("MFTS_TARGET_UTILIZATION_MAX_ZERO_RATE_PCT", "5.0")),
        help="candidate zero-target daily rate 上限；默认 5%",
    )
    p.add_argument(
        "--disable-signal-calendar-parity",
        action="store_true",
        help="关闭候选 profile 对主档 shared replayable signal dates 的同日历覆盖检查；仅排障使用",
    )
    p.add_argument(
        "--min-profile-signal-days",
        type=int,
        default=int(os.environ.get("MFTS_MIN_PROFILE_SIGNAL_DAYS", "0")),
        help="候选 profile 最少 replayable signal days；0 表示按 P2 主证据窗口自动推导",
    )
    p.add_argument("--max-metadata-staleness-days", type=float, default=float(os.environ.get("MFTS_MAX_METADATA_STALENESS_DAYS", "999.0")))
    p.add_argument(
        "--p2-execution-mode",
        choices=["subprocess", "inprocess"],
        default=os.environ.get("MFTS_P2_ROLLING_EXECUTION_MODE", "subprocess"),
        help="P2 rolling replay 执行方式；promotion refresh 可用 inprocess 降低启动开销",
    )
    p.add_argument(
        "--fail-fast-p2-smoke-window",
        type=int,
        default=int(os.environ.get("MFTS_FAIL_FAST_P2_SMOKE_WINDOW", "0")),
        help="先跑指定窗口的 P2 smoke；候选若 NAV/MDD/仓位/阻塞不过关，则不再跑完整长窗；0=关闭",
    )
    p.add_argument(
        "--p2-smoke-min-target-weight-sum",
        type=float,
        default=float(os.environ.get("MFTS_P2_SMOKE_MIN_TARGET_WEIGHT_SUM", "0.30")),
        help="P2 smoke 候选 target_weight_sum_mean 下限",
    )
    p.add_argument(
        "--p2-smoke-nav-margin-pct",
        type=float,
        default=float(os.environ.get("MFTS_P2_SMOKE_NAV_MARGIN_PCT", "0.0")),
        help="P2 smoke NAV 对主档容忍差距（百分点）；默认必须不弱于主档",
    )
    p.add_argument(
        "--p2-smoke-mdd-margin-pct",
        type=float,
        default=float(os.environ.get("MFTS_P2_SMOKE_MDD_MARGIN_PCT", "0.0")),
        help="P2 smoke MDD 对主档容忍差距（百分点）；默认必须不差于主档",
    )
    p.add_argument("--min-p2-executed-days", type=int, default=int(os.environ.get("MFTS_MIN_P2_EXECUTED_DAYS", "20")))
    p.add_argument("--min-promote-margin", type=float, default=float(os.environ.get("MFTS_MIN_PROMOTE_MARGIN", "1.0")))
    p.add_argument(
        "--rolling-summary",
        type=str,
        default=str(ROLLING_SUMMARY_LATEST),
        help="promotion review 使用的 rolling summary；默认 latest",
    )
    p.add_argument(
        "--reuse-rolling-latest",
        action="store_true",
        help="复用已有 rolling summary latest，跳过 rolling compare 刷新；会校验本次 profiles 是否齐全",
    )
    p.add_argument(
        "--score-alpha-diagnosis",
        type=str,
        default="",
        help="可选 score-alpha JSON/CSV，逗号分隔；为空时自动附加存在的 profile latest JSON",
    )
    p.add_argument(
        "--refresh-score-alpha",
        action="store_true",
        help="先为 profile-isolated daily 文件刷新 score-alpha latest JSON，再运行 promotion review",
    )
    p.add_argument(
        "--score-alpha-profiles",
        type=str,
        default="",
        help="刷新 score-alpha 的 profile，逗号分隔；默认排除 main profile 后使用本次 profiles",
    )
    p.add_argument(
        "--score-alpha-forward-days",
        type=int,
        default=int(os.environ.get("MFTS_SCORE_ALPHA_FORWARD_DAYS", "8")),
    )
    p.add_argument("--score-alpha-top-n", type=int, default=int(os.environ.get("MFTS_SCORE_ALPHA_TOP_N", "5")))
    p.add_argument("--score-alpha-min-top-days", type=int, default=int(os.environ.get("MFTS_SCORE_ALPHA_MIN_TOP_DAYS", "5")))
    p.add_argument(
        "--precheck-score-alpha",
        action="store_true",
        help="在 rolling/P2 前用 score-alpha gate 裁剪候选；main profile 始终保留",
    )
    p.add_argument("--precheck-only", action="store_true", help="只执行 precheck 并写出 latest 报告，不刷新 rolling/P2/promotion")
    args = p.parse_args()
    if (
        bool(args.precheck_only)
        and not bool(args.precheck_score_alpha)
        and not bool(args.precheck_signal_coverage)
        and not bool(args.precheck_target_utilization)
    ):
        args.precheck_score_alpha = True

    config_file = Path(args.config).resolve()
    root = json.loads(config_file.read_text(encoding="utf-8"))
    profiles = [x.strip() for x in str(args.profiles).split(",") if x.strip()] or _load_profiles(config_file)
    main_profile = str(root.get("default_profile", profiles[0] if profiles else "quality_regime"))
    start, end = _derive_period(args.end or None, int(args.lookback_months))
    rolling_summary_path = Path(str(args.rolling_summary)).resolve()
    windows = _parse_windows(args.p2_windows)

    refreshed_score_profiles: list[str] = []
    if bool(args.refresh_score_alpha):
        score_profiles = [x.strip() for x in str(args.score_alpha_profiles).split(",") if x.strip()]
        if not score_profiles:
            score_profiles = [p for p in profiles if str(p) != str(main_profile)]
        daily_globs = _discover_score_alpha_daily_globs(score_profiles, DAILY_PROFILE_DIR)
        for profile in score_profiles:
            daily_glob = daily_globs.get(str(profile), "")
            if not daily_glob:
                print(f"[promotion-gate] warning: skip score-alpha {profile}: no profile daily files")
                continue
            _run(
                [
                    sys.executable,
                    str(BASE_DIR / "scripts" / "quant_score_alpha_diagnosis.py"),
                    "--daily-glob",
                    daily_glob,
                    "--start",
                    start,
                    "--end",
                    end,
                    "--forward-days",
                    str(max(1, int(args.score_alpha_forward_days))),
                    "--top-n",
                    str(max(1, int(args.score_alpha_top_n))),
                    "--min-top-days",
                    str(max(0, int(args.score_alpha_min_top_days))),
                    "--label",
                    str(profile),
                    "--write-latest",
                ],
                f"score-alpha diagnosis latest: {profile}",
            )
            refreshed_score_profiles.append(str(profile))

    explicit_score_alpha_files = (
        [Path(x.strip()).resolve() for x in str(args.score_alpha_diagnosis).split(",") if x.strip()]
        if args.score_alpha_diagnosis
        else []
    )
    score_alpha_files = (
        explicit_score_alpha_files
        if explicit_score_alpha_files
        else _discover_score_alpha_diagnosis_files(
            refreshed_score_profiles if bool(args.refresh_score_alpha) else profiles,
            BACKTEST_DIR,
        )
    )
    effective_profiles = profiles
    if bool(args.precheck_score_alpha):
        effective_profiles, precheck_rows = _build_score_alpha_precheck(
            profiles=profiles,
            main_profile=main_profile,
            score_alpha_files=score_alpha_files,
        )
        for row in precheck_rows:
            if row.get("decision") == "skip":
                print(f"[promotion-gate] precheck skip {row.get('profile', '')}: score-alpha gate missing or failed")
        precheck_json, precheck_csv = _write_score_alpha_precheck_report(
            rows=precheck_rows,
            requested_profiles=profiles,
            effective_profiles=effective_profiles,
            main_profile=main_profile,
            backtest_dir=BACKTEST_DIR,
        )
        print(f"[promotion-gate] score-alpha precheck json={precheck_json}")
        print(f"[promotion-gate] score-alpha precheck csv={precheck_csv}")
        if len(effective_profiles) <= 1:
            print("[promotion-gate] precheck kept only the main profile; P2 refresh will not spend on failed candidates")
    if bool(args.precheck_signal_coverage):
        coverage_requested_profiles = list(profiles)
        min_signal_days = _derive_min_profile_signal_days(int(args.min_profile_signal_days), windows)
        market_trade_dates = _load_market_trade_dates()
        market_last_trade_date = market_trade_dates[-1] if market_trade_dates else ""
        reference_dates: list[str] = []
        if not bool(args.disable_signal_calendar_parity):
            reference_dates = _build_reference_signal_dates(
                end=end,
                market_trade_dates=market_trade_dates,
                required_signal_days=min_signal_days,
                output_dir=OUTPUT_DIR,
            )
        coverage_keep, coverage_rows = _build_signal_coverage_precheck(
            profiles=coverage_requested_profiles,
            main_profile=main_profile,
            min_required_days=min_signal_days,
            end=end,
            market_last_trade_date=market_last_trade_date,
            daily_profile_dir=Path(str(args.profile_signal_root)).resolve(),
            reference_dates=reference_dates,
            market_trade_dates=market_trade_dates,
        )
        for row in coverage_rows:
            if row.get("decision") == "skip":
                print(
                    "[promotion-gate] precheck skip "
                    f"{row.get('profile', '')}: {row.get('reason', '')} "
                    f"({row.get('replayable_profile_signal_days', 0)}/"
                    f"{row.get('required_signal_days', min_signal_days)} replayable days, "
                    f"missing_reference={row.get('missing_reference_signal_days', 0)})"
                )
        coverage_keep_set = set(coverage_keep)
        effective_profiles = [p for p in effective_profiles if p in coverage_keep_set]
        if main_profile not in effective_profiles and main_profile in coverage_keep_set:
            effective_profiles.insert(0, main_profile)
        coverage_json, coverage_csv = _write_signal_coverage_precheck_report(
            rows=coverage_rows,
            requested_profiles=coverage_requested_profiles,
            effective_profiles=effective_profiles,
            main_profile=main_profile,
            min_required_days=min_signal_days,
            backtest_dir=BACKTEST_DIR,
        )
        print(f"[promotion-gate] signal coverage precheck json={coverage_json}")
        print(f"[promotion-gate] signal coverage precheck csv={coverage_csv}")
        if len(effective_profiles) <= 1:
            print("[promotion-gate] signal coverage precheck kept only the main profile; P2 refresh will not spend on sparse candidates")
    if bool(args.precheck_target_utilization) or bool(args.precheck_signal_coverage):
        target_requested_profiles = list(profiles)
        target_window = max(1, int(args.target_utilization_window))
        market_trade_dates = _load_market_trade_dates()
        market_last_trade_date = market_trade_dates[-1] if market_trade_dates else ""
        reference_dates: list[str] = []
        if not bool(args.disable_signal_calendar_parity):
            reference_dates = _build_reference_signal_dates(
                end=end,
                market_trade_dates=market_trade_dates,
                required_signal_days=target_window,
                output_dir=OUTPUT_DIR,
            )
        target_keep, target_rows = _build_target_utilization_precheck(
            profiles=target_requested_profiles,
            main_profile=main_profile,
            required_signal_days=target_window,
            end=end,
            market_last_trade_date=market_last_trade_date,
            daily_profile_dir=Path(str(args.profile_signal_root)).resolve(),
            output_dir=OUTPUT_DIR,
            reference_dates=reference_dates,
            market_trade_dates=market_trade_dates,
            min_target_weight_sum_mean=float(args.target_utilization_min_mean),
            max_zero_target_rate_pct=float(args.target_utilization_max_zero_rate_pct),
        )
        for row in target_rows:
            if row.get("decision") == "skip":
                print(
                    "[promotion-gate] precheck skip "
                    f"{row.get('profile', '')}: {row.get('reason', '')} "
                    f"(target_mean={float(row.get('target_weight_sum_mean', 0.0)):.4f}, "
                    f"zero_rate={float(row.get('zero_target_rate_pct', 0.0)):.2f}%)"
                )
        target_keep_set = set(target_keep)
        effective_profiles = [p for p in effective_profiles if p in target_keep_set]
        if main_profile not in effective_profiles and main_profile in target_keep_set:
            effective_profiles.insert(0, main_profile)
        target_json, target_csv = _write_target_utilization_precheck_report(
            rows=target_rows,
            requested_profiles=target_requested_profiles,
            effective_profiles=effective_profiles,
            main_profile=main_profile,
            required_signal_days=target_window,
            backtest_dir=BACKTEST_DIR,
        )
        print(f"[promotion-gate] target utilization precheck json={target_json}")
        print(f"[promotion-gate] target utilization precheck csv={target_csv}")
        if len(effective_profiles) <= 1:
            print("[promotion-gate] target utilization precheck kept only the main profile; P2 refresh will not spend on cash-like candidates")
    if bool(args.precheck_only):
        print("[promotion-gate] precheck-only requested; skip rolling/P2/shadow/funnel/promotion refresh")
        return 0
    profile_arg = ",".join(effective_profiles)

    smoke_window = int(args.fail_fast_p2_smoke_window)
    if smoke_window > 0:
        smoke_requested_profiles = list(effective_profiles)
        _run(
            _p2_rolling_replay_cmd(
                profiles_arg=profile_arg,
                windows_arg=str(smoke_window),
                max_metadata_staleness_days=float(args.max_metadata_staleness_days),
                execution_mode=str(args.p2_execution_mode),
            ),
            f"P2 smoke rolling replay latest: window={smoke_window}",
        )
        smoke_keep, smoke_rows = _build_p2_smoke_precheck(
            profiles=smoke_requested_profiles,
            main_profile=main_profile,
            summary_path=BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv",
            smoke_window=smoke_window,
            min_target_weight_sum=float(args.p2_smoke_min_target_weight_sum),
            nav_margin_pct=float(args.p2_smoke_nav_margin_pct),
            mdd_margin_pct=float(args.p2_smoke_mdd_margin_pct),
        )
        for row in smoke_rows:
            if row.get("decision") == "skip":
                print(f"[promotion-gate] P2 smoke skip {row.get('profile', '')}: {row.get('reason', '')}")
        smoke_json, smoke_csv = _write_p2_smoke_precheck_report(
            rows=smoke_rows,
            requested_profiles=smoke_requested_profiles,
            effective_profiles=smoke_keep,
            main_profile=main_profile,
            smoke_window=smoke_window,
            backtest_dir=BACKTEST_DIR,
        )
        print(f"[promotion-gate] P2 smoke precheck json={smoke_json}")
        print(f"[promotion-gate] P2 smoke precheck csv={smoke_csv}")
        smoke_skipped = [str(row.get("profile", "")) for row in smoke_rows if row.get("decision") == "skip"]
        if smoke_skipped:
            _run(
                [
                    sys.executable,
                    str(BASE_DIR / "scripts" / "quant_p2_smoke_failure_diagnosis.py"),
                    "--p2-summary",
                    str(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"),
                    "--p2-smoke-precheck",
                    str(smoke_csv),
                    "--main-profile",
                    str(main_profile),
                    "--profiles",
                    ",".join(smoke_requested_profiles),
                    "--window",
                    str(smoke_window),
                    "--write-latest",
                ],
                "P2 smoke failure diagnosis latest",
            )
            _run(
                [
                    sys.executable,
                    str(BASE_DIR / "scripts" / "quant_p2_failure_day_attribution.py"),
                    "--failure-detail",
                    str(BACKTEST_DIR / "quant_p2_smoke_failure_detail_latest.csv"),
                    "--p2-summary",
                    str(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"),
                    "--main-profile",
                    str(main_profile),
                    "--profiles",
                    ",".join(smoke_skipped),
                    "--window",
                    str(smoke_window),
                    "--worst-n",
                    "3",
                    "--write-latest",
                ],
                "P2 failure day attribution latest",
            )
            _run(
                [
                    sys.executable,
                    str(BASE_DIR / "scripts" / "quant_p2_holiday_gap_guard_attribution.py"),
                    "--p2-summary",
                    str(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"),
                    "--main-profile",
                    str(main_profile),
                    "--profiles",
                    ",".join(smoke_skipped),
                    "--windows",
                    str(smoke_window),
                    "--write-latest",
                ],
                "P2 holiday-gap guard attribution latest",
            )
            for skipped_profile in smoke_skipped:
                capacity_daily = _capacity_feasible_daily_path(skipped_profile, BACKTEST_DIR)
                if not capacity_daily.exists():
                    continue
                _run(
                    [
                        sys.executable,
                        str(BASE_DIR / "scripts" / "quant_static_to_p2_pass_through_diagnosis.py"),
                        "--capacity-daily",
                        str(capacity_daily),
                        "--p2-summary",
                        str(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"),
                        "--main-profile",
                        str(main_profile),
                        "--profile",
                        str(skipped_profile),
                        "--window",
                        str(smoke_window),
                        "--score-col",
                        _static_to_p2_score_col(root, skipped_profile),
                        "--write-latest",
                    ],
                    f"Static-to-P2 pass-through diagnosis latest: {skipped_profile}",
                )
        effective_profiles = smoke_keep
        profile_arg = ",".join(effective_profiles)
        if len(effective_profiles) <= 1:
            print("[promotion-gate] P2 smoke kept only the main profile; skip long-window P2/promotion refresh")
            return 0

    if bool(args.reuse_rolling_latest):
        _validate_reused_rolling_summary(rolling_summary_path, effective_profiles)
        print(f"[promotion-gate] reuse rolling summary: {rolling_summary_path}")
    else:
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
        _p2_rolling_replay_cmd(
            profiles_arg=profile_arg,
            windows_arg=str(args.p2_windows),
            max_metadata_staleness_days=float(args.max_metadata_staleness_days),
            execution_mode=str(args.p2_execution_mode),
        ),
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

    review_cmd = [
        sys.executable,
        str(BASE_DIR / "scripts" / "quant_profile_promotion_review.py"),
        "--config",
        str(config_file),
        "--profiles",
        profile_arg,
        "--rolling-summary",
        str(rolling_summary_path),
        "--p2-summary",
        str(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"),
        "--min-p2-executed-days",
        str(max(1, int(args.min_p2_executed_days))),
        "--min-promote-margin",
        str(float(args.min_promote_margin)),
        "--write-latest",
    ]
    if score_alpha_files:
        review_cmd.extend(["--score-alpha-diagnosis", ",".join(str(x) for x in score_alpha_files)])

    _run(
        review_cmd,
        "promotion review latest",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
