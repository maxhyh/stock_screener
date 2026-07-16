#!/usr/bin/env python3
"""
P2 纸面执行滚动回放（60/90/120 交易日窗口）。

用途：
1) 对多个 profile 在近期窗口进行逐日执行回放
2) 统计收益、回撤、换手、执行阻塞与风控阻塞
3) 产出汇总表用于参数档位比较与后续 A/B 选择
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from utils.output_paths import get_output_dirs, list_dual
from core.data.market_data_gateway import AShareMarketDataGateway

OUTPUT_DIR = BASE_DIR / "output"
EXEC_DIR = OUTPUT_DIR / "execution"
BACKTEST_DIR = OUTPUT_DIR / "backtest"
P2_SCRIPT = BASE_DIR / "scripts" / "quant_p2_paper_trade.py"
LOG_DIR = BASE_DIR / "logs" / "p2_rolling_replay"
_P2_MODULE_CACHE = None
_P2_MODULE_CACHE_PROFILE = ""


def _zero_ledger_summary() -> dict[str, float]:
    return {
        "executed_days": 0,
        "nav_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "turnover_sum": 0.0,
        "turnover_mean": 0.0,
        "exec_block_rate_pct": 0.0,
        "risk_block_rate_pct": 0.0,
        "target_weight_sum_mean": 0.0,
        "unfilled_target_weight_sum": 0.0,
        "impact_cost_bps_mean": 0.0,
        "max_participation_pct": 0.0,
        "filled_orders": 0.0,
        "blocked_orders": 0.0,
        "rejected_orders": 0.0,
        "target_weight_source_external_rate_pct": 0.0,
        "target_weight_checksum_coverage_pct": 0.0,
        "target_weight_checksum_unique_count": 0.0,
        "upstream_target_weight_present_days": 0.0,
        "upstream_target_weight_present_rate_pct": 0.0,
        "upstream_target_weight_sum_mean": 0.0,
        "upstream_target_weight_positive_count_mean": 0.0,
        "upstream_target_weight_max_mean": 0.0,
        "upstream_target_weight_gap_abs_max": 0.0,
        "upstream_target_weight_overrun_max": 0.0,
        "upstream_target_weight_underuse_max": 0.0,
        "holiday_gap_guard_days": 0.0,
        "holiday_gap_guard_rate_pct": 0.0,
        "holiday_gap_signal_trade_gap_days_max": 0.0,
        "holiday_gap_post_trade_gap_days_max": 0.0,
        "holiday_gap_target_scale_min": 1.0,
        "entry_not_tradable_orders": 0.0,
        "exit_not_tradable_orders": 0.0,
        "broker_entry_not_tradable_orders": 0.0,
        "broker_exit_not_tradable_orders": 0.0,
        "broker_tradability_block_orders": 0.0,
        "blocked_target_weight_sum": 0.0,
        "entry_not_tradable_target_weight_sum": 0.0,
        "exit_not_tradable_target_weight_sum": 0.0,
        "max_daily_tradability_blocked_orders": 0.0,
        "reserve_enabled_days": 0.0,
        "reserve_candidate_pool_n_mean": 0.0,
        "reserve_rounds_used_max": 0.0,
        "pre_optimizer_blocked_count_sum": 0.0,
        "post_optimizer_blocked_count_sum": 0.0,
        "risk_entry_not_tradable_hit_sum": 0.0,
        "blocked_sell_current_weight_sum": 0.0,
        "blocked_sell_current_weight_max": 0.0,
        "blocked_sell_notional_sum": 0.0,
        "blocked_sell_orders_sum": 0.0,
        "blocked_sell_entry_risk_score_weighted_mean_max": 0.0,
        "blocked_sell_entry_tradability_safe_score_weighted_mean_min": 0.0,
        "blocked_sell_entry_exit_trap_risk_score_weighted_mean_max": 0.0,
        "blocked_sell_entry_exit_trap_volume_drought_risk_weighted_mean_max": 0.0,
        "blocked_sell_high_entry_exit_trap_risk_orders_sum": 0.0,
        "blocked_sell_high_entry_exit_trap_volume_drought_orders_sum": 0.0,
        "blocked_sell_entry_limit_headroom_min": 0.0,
        "blocked_sell_high_entry_risk_orders_sum": 0.0,
        "blocked_sell_low_entry_safety_orders_sum": 0.0,
        "blocked_sell_reserve_entry_orders_sum": 0.0,
        "blocked_exit_buy_freeze_days": 0.0,
        "blocked_exit_freeze_sell_weight_max": 0.0,
        "blocked_exit_freeze_sell_notional_max": 0.0,
        "blocked_exit_freeze_orders_sum": 0.0,
        "blocked_exit_freeze_target_weight_sum": 0.0,
        "active_blocked_sell_state_count_max": 0.0,
        "active_blocked_sell_state_weight_max": 0.0,
        "active_blocked_sell_state_notional_max": 0.0,
        "active_blocked_sell_state_max_consecutive_days_max": 0.0,
        "blocked_state_count_max": 0.0,
        "blocked_state_buy_count_max": 0.0,
        "blocked_state_sell_count_max": 0.0,
        "blocked_state_max_consecutive_days_max": 0.0,
        "blocked_state_sell_notional_max": 0.0,
        "blocked_state_buy_target_weight_sum": 0.0,
        "blocked_state_sell_target_weight_sum": 0.0,
        "blocked_state_resolved_count_sum": 0.0,
        "empty_signal_days": 0.0,
        "empty_signal_rate_pct": 0.0,
        "empty_signal_raw_days": 0.0,
        "empty_after_universe_filter_days": 0.0,
        "empty_signal_raw_rows_sum": 0.0,
        "empty_signal_post_filter_rows_sum": 0.0,
        "empty_signal_filtered_bj9_rows_sum": 0.0,
        "empty_signal_filtered_st_rows_sum": 0.0,
        "executable_pool_halt_days": 0.0,
        "executable_pool_halt_rate_pct": 0.0,
        "executable_pool_halt_input_sum": 0.0,
        "executable_pool_halt_blocked_sum": 0.0,
        "executable_pool_halt_adv_hit_sum": 0.0,
        "executable_pool_halt_entry_not_tradable_hit_sum": 0.0,
        "executable_pool_halt_style_hit_sum": 0.0,
    }


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _parse_list_arg(raw: str) -> list[str]:
    out: list[str] = []
    for part in str(raw or "").split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _parse_windows(raw: str) -> list[int]:
    vals: list[int] = []
    for tok in _parse_list_arg(raw):
        try:
            n = int(tok)
        except Exception:
            continue
        if n > 0:
            vals.append(n)
    dedup = sorted(set(vals))
    return dedup or [60, 90, 120]


def _parse_float_grid(raw: str, fallback: list[float]) -> list[float]:
    vals: list[float] = []
    for tok in _parse_list_arg(raw):
        try:
            v = float(tok)
        except Exception:
            continue
        if np.isfinite(v) and v >= 0:
            vals.append(float(v))
    vals = sorted(set(vals))
    return vals if vals else [float(x) for x in fallback]


def _parse_int_grid(raw: str, fallback: list[int], min_value: int = 1) -> list[int]:
    vals: list[int] = []
    for tok in _parse_list_arg(raw):
        try:
            v = int(tok)
        except Exception:
            continue
        if v >= int(min_value):
            vals.append(int(v))
    vals = sorted(set(vals))
    return vals if vals else [int(x) for x in fallback]


def _env_optional_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        val = float(raw)
    except Exception:
        return None
    return val if np.isfinite(val) else None


def _sanitize_channel(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", str(name or "").strip().lower()).strip("_")
    return s or "paper_replay"


def _sanitize_profile_slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", str(name or "").strip()).strip("_")
    return s


def _single_profile_slug(profiles: list[str]) -> str:
    if len(profiles) != 1:
        return ""
    return _sanitize_channel(profiles[0])


def _list_signal_dates() -> list[str]:
    dirs = get_output_dirs(OUTPUT_DIR)
    files = list_dual(["daily_*.csv"], dirs["daily"], dirs["base"])
    pat = re.compile(r"daily_(\d{8})\.csv$")
    dates: list[str] = []
    for p in files:
        m = pat.match(p.name)
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


def _list_profile_signal_dates(profile_signal_root: str | Path, profile: str) -> list[str]:
    root = Path(profile_signal_root)
    slug = _sanitize_profile_slug(profile)
    if not slug:
        return []
    profile_dir = root / slug
    if not profile_dir.exists():
        return []
    pat = re.compile(r"daily_(\d{8})\.csv$")
    dates: list[str] = []
    for p in profile_dir.glob("daily_*.csv"):
        m = pat.match(p.name)
        if m:
            dates.append(m.group(1))
    return sorted(set(dates))


def _normalize_yyyymmdd(value: object) -> str | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.strftime("%Y%m%d")


def _normalize_trade_date_fast(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw[:10] if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _load_market_trade_dates(parquet_file: str | Path | None = None) -> list[str]:
    """Return replayable ODS sessions; legacy argument is intentionally ignored."""
    del parquet_file
    return [_normalize_yyyymmdd(date) for date in AShareMarketDataGateway().available_trade_dates()]


def _filter_signal_dates_with_next_trade_day(
    signal_dates: list[str],
    trade_dates: list[str],
) -> tuple[list[str], dict[str, object]]:
    clean_signal_dates = sorted({str(d).strip() for d in signal_dates if str(d).strip()})
    clean_trade_dates = sorted({str(d).strip() for d in trade_dates if str(d).strip()})
    if not clean_signal_dates or not clean_trade_dates:
        return clean_signal_dates, {
            "next_trade_day_filter_applied": False,
            "market_trade_dates": int(len(clean_trade_dates)),
            "raw_signal_dates": int(len(clean_signal_dates)),
            "replayable_signal_dates": int(len(clean_signal_dates)),
            "excluded_no_next_trade_dates": [],
            "market_last_trade_date": "",
        }

    # P2 executes each signal on the next available market trade date, but the
    # signal day itself must also exist in the market bars. Otherwise stale
    # shared daily files can silently enter promotion evidence.
    last_trade_date = clean_trade_dates[-1]
    market_set = set(clean_trade_dates)
    replayable = [d for d in clean_signal_dates if d in market_set and d < last_trade_date]
    excluded = [d for d in clean_signal_dates if d >= last_trade_date]
    excluded_missing_market = [d for d in clean_signal_dates if d < last_trade_date and d not in market_set]
    return replayable, {
        "next_trade_day_filter_applied": True,
        "market_trade_dates": int(len(clean_trade_dates)),
        "raw_signal_dates": int(len(clean_signal_dates)),
        "replayable_signal_dates": int(len(replayable)),
        "excluded_no_next_trade_dates": excluded,
        "excluded_missing_market_dates": excluded_missing_market,
        "market_last_trade_date": last_trade_date,
    }


def _window_calendar_coverage(target_dates: list[str], requested_window: int, available_dates: int) -> dict[str, float]:
    requested = max(1, int(requested_window))
    actual = int(len(target_dates))
    return {
        "requested_window_days": float(requested),
        "profile_signal_days_available": float(max(0, int(available_dates))),
        "signal_calendar_shortfall_days": float(max(requested - actual, 0)),
        "signal_calendar_coverage_pct": float(actual / requested * 100.0),
    }


def _resolve_profile_calendar_dates(
    *,
    shared_signal_dates: list[str],
    profile_signal_dates: list[str],
    has_profile_calendar: bool,
    align_to_shared: bool,
) -> tuple[list[str], str, dict[str, object]]:
    shared = sorted({str(d).strip() for d in shared_signal_dates if str(d).strip()})
    profile_dates = sorted({str(d).strip() for d in profile_signal_dates if str(d).strip()})
    if not has_profile_calendar:
        return shared, "shared", {
            "profile_calendar_aligned_to_shared": False,
            "profile_calendar_missing_shared_dates": [],
            "profile_calendar_extra_profile_dates": [],
        }
    if align_to_shared:
        profile_set = set(profile_dates)
        shared_set = set(shared)
        return [d for d in shared if d in profile_set], "profile_aligned_shared", {
            "profile_calendar_aligned_to_shared": True,
            "profile_calendar_missing_shared_dates": [d for d in shared if d not in profile_set],
            "profile_calendar_extra_profile_dates": [d for d in profile_dates if d not in shared_set],
        }
    return profile_dates, "profile", {
        "profile_calendar_aligned_to_shared": False,
        "profile_calendar_missing_shared_dates": [],
        "profile_calendar_extra_profile_dates": [d for d in profile_dates if d not in set(shared)],
    }


def _resolve_profile_signal_file(profile_signal_root: str | Path, profile: str, date_str: str) -> Path | None:
    root = Path(profile_signal_root)
    slug = _sanitize_profile_slug(profile)
    if not slug:
        return None
    candidates = [
        root / slug / f"daily_{date_str}.csv",
        OUTPUT_DIR / "daily_profiles" / slug / f"daily_{date_str}.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _max_drawdown_pct(nav_series: list[float]) -> float:
    if not nav_series:
        return 0.0
    nav = np.asarray(nav_series, dtype=float)
    nav = nav[np.isfinite(nav) & (nav > 0)]
    if len(nav) == 0:
        return 0.0
    peak = np.maximum.accumulate(nav)
    dd = nav / np.where(peak > 0, peak, np.nan) - 1.0
    return float(np.nanmin(dd) * 100.0)


def _objective_score(
    nav_return_pct: float,
    max_drawdown_pct: float,
    turnover_mean: float,
    exec_block_rate_pct: float,
    risk_block_rate_pct: float,
    style_hit_rate_pct: float,
) -> float:
    # 多指标目标：收益优先，同时惩罚回撤/换手/执行阻塞/风格过度拦截
    return float(
        nav_return_pct
        - 0.60 * abs(max_drawdown_pct)
        - 0.00002 * max(turnover_mean, 0.0)
        - 0.12 * max(exec_block_rate_pct, 0.0)
        - 0.12 * max(risk_block_rate_pct, 0.0)
        - 0.08 * max(style_hit_rate_pct, 0.0)
    )


def _summarize_ledger(ledger_file: Path) -> dict[str, float]:
    if (not ledger_file.exists()) or ledger_file.stat().st_size == 0:
        return _zero_ledger_summary()
    df = pd.read_csv(ledger_file)
    if df.empty:
        return _zero_ledger_summary()

    has_broker_entry_col = "broker_entry_not_tradable_orders" in df.columns
    has_broker_exit_col = "broker_exit_not_tradable_orders" in df.columns
    for c in [
        "nav_pre",
        "nav_post",
        "turnover",
        "filled_orders",
        "partial_orders",
        "blocked_orders",
        "rejected_orders",
        "risk_input_count",
        "risk_blocked_count",
        "risk_style_limits_hit",
        "risk_style_size_limits_hit",
        "risk_style_beta_limits_hit",
        "risk_style_momentum_limits_hit",
        "risk_style_vol_limits_hit",
        "risk_adv_limits_hit",
        "executable_pool_halt",
        "executable_pool_input_count",
        "executable_pool_blocked_count",
        "holiday_gap_guard",
        "holiday_gap_signal_trade_gap_days",
        "holiday_gap_post_trade_gap_days",
        "holiday_gap_target_scale",
        "holiday_gap_total_position_cap",
        "holiday_gap_single_pos_cap",
        "holiday_gap_reason_override_applied",
        "upstream_target_weight_present",
        "upstream_target_weight_sum",
        "upstream_target_weight_positive_count",
        "upstream_target_weight_max",
        "target_weight_sum",
        "unfilled_target_weight",
        "impact_cost_bps_mean",
        "max_participation_pct",
        "entry_not_tradable_orders",
        "exit_not_tradable_orders",
        "broker_entry_not_tradable_orders",
        "broker_exit_not_tradable_orders",
        "blocked_target_weight",
        "entry_not_tradable_target_weight",
        "exit_not_tradable_target_weight",
        "reserve_enabled",
        "reserve_candidate_pool_n",
        "reserve_rounds_used",
        "pre_optimizer_blocked_count",
        "post_optimizer_blocked_count",
        "risk_entry_not_tradable_hit",
        "blocked_sell_current_weight",
        "blocked_sell_notional",
        "blocked_sell_orders",
        "blocked_sell_entry_tradability_safe_score_mean",
        "blocked_sell_entry_tradability_safe_score_weighted_mean",
        "blocked_sell_entry_risk_score_mean",
        "blocked_sell_entry_risk_score_weighted_mean",
        "blocked_sell_entry_exit_trap_risk_score_mean",
        "blocked_sell_entry_exit_trap_risk_score_weighted_mean",
        "blocked_sell_entry_exit_trap_safe_score_weighted_mean",
        "blocked_sell_entry_exit_trap_volume_drought_risk_weighted_mean",
        "blocked_sell_entry_limit_headroom_min",
        "blocked_sell_high_entry_risk_orders",
        "blocked_sell_high_entry_exit_trap_risk_orders",
        "blocked_sell_high_entry_exit_trap_volume_drought_orders",
        "blocked_sell_low_entry_safety_orders",
        "blocked_sell_reserve_entry_orders",
        "blocked_exit_buy_freeze",
        "blocked_exit_freeze_sell_weight",
        "blocked_exit_freeze_sell_notional",
        "blocked_exit_freeze_orders",
        "blocked_exit_freeze_target_weight",
        "active_blocked_sell_state_count",
        "active_blocked_sell_state_weight",
        "active_blocked_sell_state_notional",
        "active_blocked_sell_state_max_consecutive_days",
        "blocked_state_count",
        "blocked_state_buy_count",
        "blocked_state_sell_count",
        "blocked_state_max_consecutive_days",
        "blocked_state_sell_notional",
        "blocked_state_buy_target_weight",
        "blocked_state_sell_target_weight",
        "blocked_state_resolved_count",
        "empty_signal",
        "empty_signal_raw_rows",
        "empty_signal_post_filter_rows",
        "empty_signal_filtered_bj9_rows",
        "empty_signal_filtered_st_rows",
    ]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        else:
            df[c] = 0.0
    if not has_broker_entry_col:
        df["broker_entry_not_tradable_orders"] = df["entry_not_tradable_orders"]
    if not has_broker_exit_col:
        df["broker_exit_not_tradable_orders"] = df["exit_not_tradable_orders"]

    nav_start = float(df["nav_pre"].iloc[0]) if len(df) else 0.0
    nav_end = float(df["nav_post"].iloc[-1]) if len(df) else 0.0
    nav_return_pct = (nav_end / nav_start - 1.0) * 100.0 if nav_start > 0 else 0.0

    nav_curve = [nav_start] + [float(x) for x in df["nav_post"].tolist()]
    max_dd_pct = _max_drawdown_pct(nav_curve)

    total_orders = float(
        (df["filled_orders"] + df["partial_orders"] + df["blocked_orders"] + df["rejected_orders"]).sum()
    )
    blocked_orders = float((df["blocked_orders"] + df["rejected_orders"]).sum())
    exec_block_rate_pct = blocked_orders / total_orders * 100.0 if total_orders > 0 else 0.0

    risk_input = float(df["risk_input_count"].sum())
    risk_blocked = float(df["risk_blocked_count"].sum())
    risk_block_rate_pct = risk_blocked / risk_input * 100.0 if risk_input > 0 else 0.0
    style_hit_total = float(df["risk_style_limits_hit"].sum())
    style_hit_rate_pct = style_hit_total / max(risk_input, 1e-9) * 100.0 if risk_input > 0 else 0.0

    turnover_sum = float(df["turnover"].sum())
    turnover_mean = float(df["turnover"].mean()) if len(df) else 0.0
    target_weight_source = df.get("target_weight_source", pd.Series([""] * len(df), index=df.index)).astype(str)
    target_weight_checksum = df.get("target_weight_checksum", pd.Series([""] * len(df), index=df.index)).astype(str)
    execution_state = df.get("execution_state", pd.Series([""] * len(df), index=df.index)).astype(str)
    empty_mask = (df["empty_signal"] > 0) | execution_state.isin(["empty_signal_raw", "empty_after_universe_filter"])
    lineage_mask = ~(
        ((df["executable_pool_halt"] > 0) & (df["target_weight_sum"] <= 1e-12))
        | ((empty_mask) & (df["target_weight_sum"] <= 1e-12))
    )
    lineage_den = int(lineage_mask.sum())
    external_rate = (
        float(target_weight_source.loc[lineage_mask].eq("external_target_weight").mean() * 100.0)
        if lineage_den > 0
        else 100.0
    )
    checksum_coverage = (
        float(target_weight_checksum.loc[lineage_mask].str.strip().ne("").mean() * 100.0)
        if lineage_den > 0
        else 100.0
    )
    entry_not_tradable = float(df["entry_not_tradable_orders"].sum())
    exit_not_tradable = float(df["exit_not_tradable_orders"].sum())
    broker_entry_not_tradable = float(df["broker_entry_not_tradable_orders"].sum())
    broker_exit_not_tradable = float(df["broker_exit_not_tradable_orders"].sum())
    daily_tradability_blocked = df["entry_not_tradable_orders"] + df["exit_not_tradable_orders"]
    halt_mask = df["executable_pool_halt"] > 0
    halt_days = int(halt_mask.sum())
    holiday_gap_guard_mask = df["holiday_gap_guard"] > 0
    holiday_gap_guard_days = int(holiday_gap_guard_mask.sum())
    holiday_gap_override_days = int((df["holiday_gap_reason_override_applied"] > 0).sum())
    upstream_target_mask = df["upstream_target_weight_present"] > 0
    upstream_target_days = int(upstream_target_mask.sum())
    upstream_gap = (
        (df["target_weight_sum"] - df["upstream_target_weight_sum"]).abs()
        if "upstream_target_weight_sum" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    upstream_delta = (
        df["target_weight_sum"] - df["upstream_target_weight_sum"]
        if "upstream_target_weight_sum" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    empty_days = int(empty_mask.sum())
    empty_after_filter_mask = execution_state.eq("empty_after_universe_filter")
    empty_raw_mask = execution_state.eq("empty_signal_raw")

    return {
        "executed_days": int(len(df)),
        "nav_return_pct": float(nav_return_pct),
        "max_drawdown_pct": float(max_dd_pct),
        "turnover_sum": float(turnover_sum),
        "turnover_mean": float(turnover_mean),
        "exec_block_rate_pct": float(exec_block_rate_pct),
        "risk_block_rate_pct": float(risk_block_rate_pct),
        "style_hit_total": float(style_hit_total),
        "style_hit_mean": float(df["risk_style_limits_hit"].mean()) if len(df) else 0.0,
        "style_hit_rate_pct": float(style_hit_rate_pct),
        "style_hit_size_total": float(df["risk_style_size_limits_hit"].sum()),
        "style_hit_beta_total": float(df["risk_style_beta_limits_hit"].sum()),
        "style_hit_momentum_total": float(df["risk_style_momentum_limits_hit"].sum()),
        "style_hit_vol_total": float(df["risk_style_vol_limits_hit"].sum()),
        "target_weight_sum_mean": float(df["target_weight_sum"].mean()) if len(df) else 0.0,
        "unfilled_target_weight_sum": float(df["unfilled_target_weight"].sum()),
        "impact_cost_bps_mean": float(df["impact_cost_bps_mean"].mean()) if len(df) else 0.0,
        "max_participation_pct": float(df["max_participation_pct"].max()) if len(df) else 0.0,
        "filled_orders": float(df["filled_orders"].sum()),
        "blocked_orders": float(df["blocked_orders"].sum()),
        "rejected_orders": float(df["rejected_orders"].sum()),
        "target_weight_source_external_rate_pct": float(external_rate),
        "target_weight_checksum_coverage_pct": float(checksum_coverage),
        "target_weight_checksum_unique_count": float(target_weight_checksum[target_weight_checksum.str.strip().ne("")].nunique()),
        "upstream_target_weight_present_days": float(upstream_target_days),
        "upstream_target_weight_present_rate_pct": float(upstream_target_days / max(len(df), 1) * 100.0) if len(df) else 0.0,
        "upstream_target_weight_sum_mean": float(df.loc[upstream_target_mask, "upstream_target_weight_sum"].mean())
        if upstream_target_days
        else 0.0,
        "upstream_target_weight_positive_count_mean": float(
            df.loc[upstream_target_mask, "upstream_target_weight_positive_count"].mean()
        )
        if upstream_target_days
        else 0.0,
        "upstream_target_weight_max_mean": float(df.loc[upstream_target_mask, "upstream_target_weight_max"].mean())
        if upstream_target_days
        else 0.0,
        "upstream_target_weight_gap_abs_max": float(upstream_gap.loc[upstream_target_mask].max())
        if upstream_target_days
        else 0.0,
        "upstream_target_weight_overrun_max": float(upstream_delta.loc[upstream_target_mask].clip(lower=0.0).max())
        if upstream_target_days
        else 0.0,
        "upstream_target_weight_underuse_max": float((-upstream_delta.loc[upstream_target_mask]).clip(lower=0.0).max())
        if upstream_target_days
        else 0.0,
        "holiday_gap_guard_days": float(holiday_gap_guard_days),
        "holiday_gap_guard_rate_pct": float(holiday_gap_guard_days / max(len(df), 1) * 100.0) if len(df) else 0.0,
        "holiday_gap_signal_trade_gap_days_max": float(df["holiday_gap_signal_trade_gap_days"].max()) if len(df) else 0.0,
        "holiday_gap_post_trade_gap_days_max": float(df["holiday_gap_post_trade_gap_days"].max()) if len(df) else 0.0,
        "holiday_gap_target_scale_min": float(df["holiday_gap_target_scale"].min()) if len(df) else 1.0,
        "holiday_gap_reason_override_days": float(holiday_gap_override_days),
        "holiday_gap_reason_override_rate_pct": float(holiday_gap_override_days / max(len(df), 1) * 100.0)
        if len(df)
        else 0.0,
        "entry_not_tradable_orders": float(entry_not_tradable),
        "exit_not_tradable_orders": float(exit_not_tradable),
        "broker_entry_not_tradable_orders": float(broker_entry_not_tradable),
        "broker_exit_not_tradable_orders": float(broker_exit_not_tradable),
        "broker_tradability_block_orders": float(broker_entry_not_tradable + broker_exit_not_tradable),
        "blocked_target_weight_sum": float(df["blocked_target_weight"].sum()),
        "entry_not_tradable_target_weight_sum": float(df["entry_not_tradable_target_weight"].sum()),
        "exit_not_tradable_target_weight_sum": float(df["exit_not_tradable_target_weight"].sum()),
        "max_daily_tradability_blocked_orders": float(daily_tradability_blocked.max()) if len(df) else 0.0,
        "reserve_enabled_days": float(df["reserve_enabled"].sum()),
        "reserve_candidate_pool_n_mean": float(df["reserve_candidate_pool_n"].mean()) if len(df) else 0.0,
        "reserve_rounds_used_max": float(df["reserve_rounds_used"].max()) if len(df) else 0.0,
        "pre_optimizer_blocked_count_sum": float(df["pre_optimizer_blocked_count"].sum()),
        "post_optimizer_blocked_count_sum": float(df["post_optimizer_blocked_count"].sum()),
        "risk_entry_not_tradable_hit_sum": float(df["risk_entry_not_tradable_hit"].sum()),
        "blocked_sell_current_weight_sum": float(df["blocked_sell_current_weight"].sum()),
        "blocked_sell_current_weight_max": float(df["blocked_sell_current_weight"].max()) if len(df) else 0.0,
        "blocked_sell_notional_sum": float(df["blocked_sell_notional"].sum()),
        "blocked_sell_orders_sum": float(df["blocked_sell_orders"].sum()),
        "blocked_sell_entry_risk_score_weighted_mean_max": float(
            df["blocked_sell_entry_risk_score_weighted_mean"].max()
        )
        if len(df)
        else 0.0,
        "blocked_sell_entry_exit_trap_risk_score_weighted_mean_max": float(
            df["blocked_sell_entry_exit_trap_risk_score_weighted_mean"].max()
        )
        if len(df)
        else 0.0,
        "blocked_sell_entry_exit_trap_volume_drought_risk_weighted_mean_max": float(
            df["blocked_sell_entry_exit_trap_volume_drought_risk_weighted_mean"].max()
        )
        if len(df)
        else 0.0,
        "blocked_sell_entry_tradability_safe_score_weighted_mean_min": float(
            df.loc[df["blocked_sell_orders"] > 0, "blocked_sell_entry_tradability_safe_score_weighted_mean"].min()
        )
        if (len(df) and (df["blocked_sell_orders"] > 0).any())
        else 0.0,
        "blocked_sell_entry_limit_headroom_min": float(
            df.loc[df["blocked_sell_orders"] > 0, "blocked_sell_entry_limit_headroom_min"].min()
        )
        if (len(df) and (df["blocked_sell_orders"] > 0).any())
        else 0.0,
        "blocked_sell_high_entry_risk_orders_sum": float(df["blocked_sell_high_entry_risk_orders"].sum()),
        "blocked_sell_high_entry_exit_trap_risk_orders_sum": float(
            df["blocked_sell_high_entry_exit_trap_risk_orders"].sum()
        ),
        "blocked_sell_high_entry_exit_trap_volume_drought_orders_sum": float(
            df["blocked_sell_high_entry_exit_trap_volume_drought_orders"].sum()
        ),
        "blocked_sell_low_entry_safety_orders_sum": float(df["blocked_sell_low_entry_safety_orders"].sum()),
        "blocked_sell_reserve_entry_orders_sum": float(df["blocked_sell_reserve_entry_orders"].sum()),
        "blocked_exit_buy_freeze_days": float((df["blocked_exit_buy_freeze"] > 0).sum()),
        "blocked_exit_freeze_sell_weight_max": float(df["blocked_exit_freeze_sell_weight"].max()) if len(df) else 0.0,
        "blocked_exit_freeze_sell_notional_max": float(df["blocked_exit_freeze_sell_notional"].max()) if len(df) else 0.0,
        "blocked_exit_freeze_orders_sum": float(df["blocked_exit_freeze_orders"].sum()),
        "blocked_exit_freeze_target_weight_sum": float(df["blocked_exit_freeze_target_weight"].sum()),
        "active_blocked_sell_state_count_max": float(df["active_blocked_sell_state_count"].max()) if len(df) else 0.0,
        "active_blocked_sell_state_weight_max": float(df["active_blocked_sell_state_weight"].max()) if len(df) else 0.0,
        "active_blocked_sell_state_notional_max": float(df["active_blocked_sell_state_notional"].max()) if len(df) else 0.0,
        "active_blocked_sell_state_max_consecutive_days_max": float(
            df["active_blocked_sell_state_max_consecutive_days"].max()
        )
        if len(df)
        else 0.0,
        "blocked_state_count_max": float(df["blocked_state_count"].max()) if len(df) else 0.0,
        "blocked_state_buy_count_max": float(df["blocked_state_buy_count"].max()) if len(df) else 0.0,
        "blocked_state_sell_count_max": float(df["blocked_state_sell_count"].max()) if len(df) else 0.0,
        "blocked_state_max_consecutive_days_max": float(df["blocked_state_max_consecutive_days"].max()) if len(df) else 0.0,
        "blocked_state_sell_notional_max": float(df["blocked_state_sell_notional"].max()) if len(df) else 0.0,
        "blocked_state_buy_target_weight_sum": float(df["blocked_state_buy_target_weight"].sum()),
        "blocked_state_sell_target_weight_sum": float(df["blocked_state_sell_target_weight"].sum()),
        "blocked_state_resolved_count_sum": float(df["blocked_state_resolved_count"].sum()),
        "empty_signal_days": float(empty_days),
        "empty_signal_rate_pct": float(empty_days / max(len(df), 1) * 100.0) if len(df) else 0.0,
        "empty_signal_raw_days": float(empty_raw_mask.sum()),
        "empty_after_universe_filter_days": float(empty_after_filter_mask.sum()),
        "empty_signal_raw_rows_sum": float(df.loc[empty_mask, "empty_signal_raw_rows"].sum()),
        "empty_signal_post_filter_rows_sum": float(df.loc[empty_mask, "empty_signal_post_filter_rows"].sum()),
        "empty_signal_filtered_bj9_rows_sum": float(df.loc[empty_mask, "empty_signal_filtered_bj9_rows"].sum()),
        "empty_signal_filtered_st_rows_sum": float(df.loc[empty_mask, "empty_signal_filtered_st_rows"].sum()),
        "executable_pool_halt_days": float(halt_days),
        "executable_pool_halt_rate_pct": float(halt_days / max(len(df), 1) * 100.0) if len(df) else 0.0,
        "executable_pool_halt_input_sum": float(df.loc[halt_mask, "executable_pool_input_count"].sum()),
        "executable_pool_halt_blocked_sum": float(df.loc[halt_mask, "executable_pool_blocked_count"].sum()),
        "executable_pool_halt_adv_hit_sum": float(df.loc[halt_mask, "risk_adv_limits_hit"].sum()),
        "executable_pool_halt_entry_not_tradable_hit_sum": float(
            df.loc[halt_mask, "risk_entry_not_tradable_hit"].sum()
        ),
        "executable_pool_halt_style_hit_sum": float(df.loc[halt_mask, "risk_style_limits_hit"].sum()),
    }


def _run_p2_day(
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
    global _P2_MODULE_CACHE, _P2_MODULE_CACHE_PROFILE
    rc = 1
    try:
        os.environ.clear()
        os.environ.update(env)
        os.chdir(BASE_DIR)
        sys.argv = [str(P2_SCRIPT), *cmd[2:]]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            profile = str(env.get("MFTS_P2_PROFILE", ""))
            if _P2_MODULE_CACHE is None or _P2_MODULE_CACHE_PROFILE != profile:
                mod = importlib.import_module("scripts.quant_p2_paper_trade")
                mod = importlib.reload(mod)
                _P2_MODULE_CACHE = mod
                _P2_MODULE_CACHE_PROFILE = profile
            else:
                mod = _P2_MODULE_CACHE
            rc = int(mod.main())
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="P2 纸面执行滚动回放")
    p.add_argument(
        "--profiles",
        type=str,
        default=os.environ.get("MFTS_P2_PROFILE", "right_h8_low_turnover"),
        help="档位列表，逗号分隔",
    )
    p.add_argument("--windows", type=str, default="60,90,120", help="窗口列表，逗号分隔（交易日）")
    p.add_argument("--broker", type=str, default="paper", help="执行通道（paper/live）")
    p.add_argument("--initial-capital", type=float, default=1_000_000.0, help="回放初始资金")
    p.add_argument(
        "--risk-max-industry-weight",
        type=float,
        default=_env_optional_float("MFTS_RISK_MAX_INDUSTRY_WEIGHT"),
        help="单行业目标权重上限(0~1)；不传则使用各 profile/P2 默认值",
    )
    p.add_argument(
        "--risk-max-adv-participation",
        type=float,
        default=_env_optional_float("MFTS_RISK_MAX_ADV_PARTICIPATION"),
        help="单票成交额参与率上限(0~1)；不传则使用各 profile/P2 默认值",
    )
    p.add_argument(
        "--risk-min-price",
        type=float,
        default=_env_optional_float("MFTS_RISK_MIN_PRICE"),
        help="最低开盘价过滤；不传则使用各 profile/P2 默认值",
    )
    p.add_argument("--style-size-grid", type=str, default=os.environ.get("MFTS_STYLE_SIZE_GRID", "0.6,0.9,1.2"), help="style size 阈值网格，逗号分隔")
    p.add_argument("--style-beta-grid", type=str, default=os.environ.get("MFTS_STYLE_BETA_GRID", "0.6,0.9,1.2"), help="style beta 阈值网格，逗号分隔")
    p.add_argument("--style-momentum-grid", type=str, default=os.environ.get("MFTS_STYLE_MOMENTUM_GRID", "0.8,1.2,1.6"), help="style momentum 阈值网格，逗号分隔")
    p.add_argument("--style-vol-grid", type=str, default=os.environ.get("MFTS_STYLE_VOL_GRID", "0.8,1.1,1.4"), help="style vol 阈值网格，逗号分隔")
    p.add_argument("--style-lb-short-grid", type=str, default=os.environ.get("MFTS_STYLE_LB_SHORT_GRID", "20"), help="style short lookback 网格")
    p.add_argument("--style-lb-beta-grid", type=str, default=os.environ.get("MFTS_STYLE_LB_BETA_GRID", "60"), help="style beta lookback 网格")
    p.add_argument("--max-grid-combos", type=int, default=0, help="最多执行的 style 组合数（0=全部）")
    p.add_argument(
        "--profile-signal-root",
        type=str,
        default=os.environ.get("MFTS_PROFILE_SIGNAL_ROOT", str(OUTPUT_DIR / "daily_profiles")),
        help="profile 隔离 daily 信号根目录；若存在 <root>/<profile>/daily_YYYYMMDD.csv 则优先使用",
    )
    p.add_argument(
        "--disable-shared-calendar-alignment",
        action="store_true",
        help="多 profile 对比时不把 profile 专属 signal calendar 对齐到 shared/main reference calendar；仅单档排障使用",
    )
    p.add_argument("--verbose", action="store_true", help="直接输出每日 P2 子进程日志；默认写入 logs/p2_rolling_replay")
    p.add_argument("--disable-industry-coverage-gate", action="store_true", help="关闭 P2 元数据行业覆盖率/新鲜度门禁")
    p.add_argument(
        "--min-industry-coverage-pct",
        type=float,
        default=float(os.environ.get("MFTS_MIN_INDUSTRY_COVERAGE_PCT", "80.0")),
        help="透传到 quant_p2_paper_trade.py 的行业覆盖率最低阈值(%%)",
    )
    p.add_argument(
        "--max-metadata-staleness-days",
        type=float,
        default=float(os.environ.get("MFTS_MAX_METADATA_STALENESS_DAYS", "3.0")),
        help="透传到 quant_p2_paper_trade.py 的元数据最大允许陈旧天数",
    )
    p.add_argument("--write-latest", action="store_true", help="写入 latest 快捷文件")
    p.add_argument(
        "--execution-mode",
        choices=["subprocess", "inprocess"],
        default=os.environ.get("MFTS_P2_ROLLING_EXECUTION_MODE", "subprocess"),
        help="每日 P2 执行方式；subprocess 为历史口径，inprocess 用同进程调用减少启动开销",
    )
    p.add_argument("--strict", action="store_true", help="若任一组合无执行样本则返回失败")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    if not P2_SCRIPT.exists():
        _log(f"缺少脚本: {P2_SCRIPT}")
        return 1

    profiles = _parse_list_arg(args.profiles)
    if not profiles:
        _log("profiles 为空")
        return 1
    windows = _parse_windows(args.windows)
    size_grid = _parse_float_grid(args.style_size_grid, [0.9])
    beta_grid = _parse_float_grid(args.style_beta_grid, [0.9])
    momentum_grid = _parse_float_grid(args.style_momentum_grid, [1.2])
    vol_grid = _parse_float_grid(args.style_vol_grid, [1.1])
    lb_short_grid = _parse_int_grid(args.style_lb_short_grid, [20], min_value=5)
    lb_beta_grid = _parse_int_grid(args.style_lb_beta_grid, [60], min_value=10)
    style_grid = [
        {
            "style_size": float(s),
            "style_beta": float(b),
            "style_momentum": float(m),
            "style_vol": float(v),
            "style_lb_short": int(ls),
            "style_lb_beta": int(lb),
        }
        for (s, b, m, v, ls, lb) in product(
            size_grid, beta_grid, momentum_grid, vol_grid, lb_short_grid, lb_beta_grid
        )
    ]
    if int(args.max_grid_combos) > 0:
        style_grid = style_grid[: int(args.max_grid_combos)]
    if not style_grid:
        _log("style 网格为空")
        return 1
    raw_signal_dates = _list_signal_dates()
    if not raw_signal_dates:
        _log("未找到 daily_YYYYMMDD 信号文件")
        return 1
    market_trade_dates = _load_market_trade_dates()
    signal_dates, shared_signal_filter_meta = _filter_signal_dates_with_next_trade_day(
        raw_signal_dates,
        market_trade_dates,
    )
    if not signal_dates:
        _log("没有可回放的信号日：所有信号日都缺少下一交易日。")
        return 1
    if shared_signal_filter_meta.get("excluded_no_next_trade_dates"):
        _log(
            "排除缺少下一交易日的 shared 信号日: "
            f"{shared_signal_filter_meta.get('excluded_no_next_trade_dates')}"
        )
    if shared_signal_filter_meta.get("excluded_missing_market_dates"):
        _log(
            "排除缺少市场行情的 shared 信号日: "
            f"{shared_signal_filter_meta.get('excluded_missing_market_dates')}"
        )

    _log(
        "开始滚动回放: "
        f"profiles={profiles}, windows={windows}, signal_dates={len(signal_dates)}, "
        f"raw_signal_dates={len(raw_signal_dates)}, "
        f"style_combos={len(style_grid)}"
    )

    replay_dir = EXEC_DIR / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []

    profile_signal_date_counts: dict[str, int] = {}
    profile_replayable_signal_date_counts: dict[str, int] = {}
    profile_signal_filter_meta: dict[str, dict[str, object]] = {}
    align_profile_calendar_to_shared = len(profiles) > 1 and not bool(args.disable_shared_calendar_alignment)
    for profile in profiles:
        raw_profile_signal_dates = _list_profile_signal_dates(args.profile_signal_root, profile)
        profile_signal_date_counts[profile] = int(len(raw_profile_signal_dates))
        profile_signal_dates, filter_meta = _filter_signal_dates_with_next_trade_day(
            raw_profile_signal_dates,
            market_trade_dates,
        )
        profile_replayable_signal_date_counts[profile] = int(len(profile_signal_dates))
        profile_signal_filter_meta[profile] = filter_meta
        has_profile_calendar = bool(raw_profile_signal_dates)
        calendar_dates, signal_date_source, calendar_meta = _resolve_profile_calendar_dates(
            shared_signal_dates=signal_dates,
            profile_signal_dates=profile_signal_dates,
            has_profile_calendar=has_profile_calendar,
            align_to_shared=align_profile_calendar_to_shared,
        )
        if has_profile_calendar:
            excluded = filter_meta.get("excluded_no_next_trade_dates") or []
            missing_market = filter_meta.get("excluded_missing_market_dates") or []
            suffix_parts = []
            if excluded:
                suffix_parts.append(f"excluded_no_next_trade={excluded}")
            if missing_market:
                suffix_parts.append(f"excluded_missing_market={missing_market}")
            if calendar_meta.get("profile_calendar_aligned_to_shared"):
                suffix_parts.append(
                    "aligned_to_shared=1"
                    f", missing_shared={len(calendar_meta.get('profile_calendar_missing_shared_dates') or [])}"
                    f", extra_profile={len(calendar_meta.get('profile_calendar_extra_profile_dates') or [])}"
                )
            suffix = f", {', '.join(suffix_parts)}" if suffix_parts else ""
            _log(
                f"profile={profile} 使用 profile 专属 signal calendar: "
                f"days={len(profile_signal_dates)}, raw_days={len(raw_profile_signal_dates)}{suffix}"
            )
        else:
            _log(
                f"profile={profile} 未找到可回放 profile 专属 signal calendar，"
                f"回退 shared daily: days={len(signal_dates)}"
            )
        for window in windows:
            target_dates = calendar_dates[-window:] if len(calendar_dates) > window else calendar_dates[:]
            calendar_coverage = _window_calendar_coverage(
                target_dates,
                requested_window=int(window),
                available_dates=len(calendar_dates),
            )
            for combo_idx, style_cfg in enumerate(style_grid, start=1):
                if not target_dates:
                    summary_rows.append(
                        {
                            "profile": profile,
                            "window": int(window),
                            **calendar_coverage,
                            "style_combo_idx": int(combo_idx),
                            "style_size": float(style_cfg["style_size"]),
                            "style_beta": float(style_cfg["style_beta"]),
                            "style_momentum": float(style_cfg["style_momentum"]),
                            "style_vol": float(style_cfg["style_vol"]),
                            "style_lb_short": int(style_cfg["style_lb_short"]),
                            "style_lb_beta": int(style_cfg["style_lb_beta"]),
                            "signal_days": 0,
                            "signal_date_source": signal_date_source,
                            "profile_calendar_aligned_to_shared": int(
                                bool(calendar_meta.get("profile_calendar_aligned_to_shared"))
                            ),
                            "profile_calendar_missing_shared_dates": int(
                                len(calendar_meta.get("profile_calendar_missing_shared_dates") or [])
                            ),
                            "profile_calendar_extra_profile_dates": int(
                                len(calendar_meta.get("profile_calendar_extra_profile_dates") or [])
                            ),
                            "run_success_days": 0,
                            "run_failed_days": 0,
                            "executed_days": 0,
                            "nav_return_pct": 0.0,
                            "max_drawdown_pct": 0.0,
                            "turnover_sum": 0.0,
                            "turnover_mean": 0.0,
                            "exec_block_rate_pct": 0.0,
                            "risk_block_rate_pct": 0.0,
                            "style_hit_total": 0.0,
                            "style_hit_mean": 0.0,
                            "style_hit_rate_pct": 0.0,
                            "objective_score": -1e9,
                            "channel": "",
                        }
                    )
                    continue

                channel = _sanitize_channel(f"paper_replay_{profile}_{window}_g{combo_idx}_{ts}")
                state_file = replay_dir / f"{channel}_state.json"
                ledger_file = EXEC_DIR / f"{channel}_ledger.csv"
                if state_file.exists():
                    state_file.unlink()
                if ledger_file.exists():
                    ledger_file.unlink()

                _log(
                    f"回放 profile={profile}, window={window}, combo={combo_idx}/{len(style_grid)}, "
                    f"days={len(target_dates)}, source={signal_date_source}, "
                    f"range={target_dates[0]}~{target_dates[-1]}, channel={channel}"
                )

                success_days = 0
                failed_days = 0
                for idx, d in enumerate(target_dates):
                    profile_signal_file = _resolve_profile_signal_file(args.profile_signal_root, profile, str(d))
                    cmd = [
                        sys.executable,
                        str(P2_SCRIPT),
                        "--broker",
                        str(args.broker),
                        "--channel",
                        str(channel),
                        "--state-file",
                        str(state_file),
                        "--initial-capital",
                        str(max(100000.0, float(args.initial_capital))),
                        "--risk-max-style-size-exposure-abs",
                        str(max(0.0, float(style_cfg["style_size"]))),
                        "--risk-max-style-beta-exposure-abs",
                        str(max(0.0, float(style_cfg["style_beta"]))),
                        "--risk-max-style-momentum-exposure-abs",
                        str(max(0.0, float(style_cfg["style_momentum"]))),
                        "--risk-max-style-vol-exposure-abs",
                        str(max(0.0, float(style_cfg["style_vol"]))),
                        "--risk-style-lb-short",
                        str(max(5, int(style_cfg["style_lb_short"]))),
                        "--risk-style-lb-beta",
                        str(max(10, int(style_cfg["style_lb_beta"]))),
                        "--min-industry-coverage-pct",
                        str(max(0.0, float(args.min_industry_coverage_pct))),
                        "--max-metadata-staleness-days",
                        str(max(0.0, float(args.max_metadata_staleness_days))),
                        "--strict",
                    ]
                    if profile_signal_file is not None:
                        cmd.extend(["--signal-file", str(profile_signal_file)])
                    else:
                        cmd.extend(["--date", str(d)])
                    if args.risk_max_industry_weight is not None:
                        cmd.extend(
                            [
                                "--risk-max-industry-weight",
                                str(min(max(float(args.risk_max_industry_weight), 0.05), 1.0)),
                            ]
                        )
                    if args.risk_max_adv_participation is not None:
                        cmd.extend(
                            [
                                "--risk-max-adv-participation",
                                str(min(max(float(args.risk_max_adv_participation), 0.001), 0.50)),
                            ]
                        )
                    if args.risk_min_price is not None:
                        cmd.extend(["--risk-min-price", str(max(0.0, float(args.risk_min_price)))])
                    if bool(args.disable_industry_coverage_gate):
                        cmd.append("--disable-industry-coverage-gate")
                    if idx == 0:
                        cmd.append("--reset-state")
                    env = os.environ.copy()
                    env["MFTS_P2_PROFILE"] = str(profile)
                    env["MFTS_ACTIVE_PROFILE"] = str(profile)
                    child_log_file = ""
                    proc = _run_p2_day(
                        cmd,
                        env=env,
                        execution_mode=str(args.execution_mode),
                        verbose=bool(args.verbose),
                    )
                    if not bool(args.verbose):
                        LOG_DIR.mkdir(parents=True, exist_ok=True)
                        child_log = LOG_DIR / f"{channel}_{d}.log"
                        child_log.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
                        child_log_file = str(child_log)
                    ok = proc.returncode == 0
                    success_days += int(ok)
                    failed_days += int(not ok)
                    _log(
                        f"day profile={profile}, window={window}, date={d}, "
                        f"ok={int(ok)}, signal={'profile' if profile_signal_file is not None else 'shared'}, "
                        f"log={child_log_file or 'stdout'}"
                    )
                    run_rows.append(
                        {
                            "profile": profile,
                            "window": int(window),
                            "style_combo_idx": int(combo_idx),
                            "style_size": float(style_cfg["style_size"]),
                            "style_beta": float(style_cfg["style_beta"]),
                            "style_momentum": float(style_cfg["style_momentum"]),
                            "style_vol": float(style_cfg["style_vol"]),
                            "style_lb_short": int(style_cfg["style_lb_short"]),
                            "style_lb_beta": int(style_cfg["style_lb_beta"]),
                            "channel": channel,
                            "signal_date": d,
                            "signal_date_source": signal_date_source,
                            "profile_calendar_aligned_to_shared": int(
                                bool(calendar_meta.get("profile_calendar_aligned_to_shared"))
                            ),
                            "signal_file": str(profile_signal_file or ""),
                            "child_log_file": child_log_file,
                            "execution_mode": str(args.execution_mode),
                            "return_code": int(proc.returncode),
                            "ok": int(ok),
                        }
                    )

                metrics = _summarize_ledger(ledger_file)
                obj = _objective_score(
                    nav_return_pct=float(metrics.get("nav_return_pct", 0.0)),
                    max_drawdown_pct=float(metrics.get("max_drawdown_pct", 0.0)),
                    turnover_mean=float(metrics.get("turnover_mean", 0.0)),
                    exec_block_rate_pct=float(metrics.get("exec_block_rate_pct", 0.0)),
                    risk_block_rate_pct=float(metrics.get("risk_block_rate_pct", 0.0)),
                    style_hit_rate_pct=float(metrics.get("style_hit_rate_pct", 0.0)),
                )
                summary_rows.append(
                    {
                        "profile": profile,
                        "window": int(window),
                        "style_combo_idx": int(combo_idx),
                        "style_size": float(style_cfg["style_size"]),
                        "style_beta": float(style_cfg["style_beta"]),
                        "style_momentum": float(style_cfg["style_momentum"]),
                        "style_vol": float(style_cfg["style_vol"]),
                        "style_lb_short": int(style_cfg["style_lb_short"]),
                        "style_lb_beta": int(style_cfg["style_lb_beta"]),
                        "channel": channel,
                        "signal_start": target_dates[0],
                        "signal_end": target_dates[-1],
                        "signal_days": int(len(target_dates)),
                        **calendar_coverage,
                        "signal_date_source": signal_date_source,
                        "profile_calendar_aligned_to_shared": int(
                            bool(calendar_meta.get("profile_calendar_aligned_to_shared"))
                        ),
                        "profile_calendar_missing_shared_dates": int(
                            len(calendar_meta.get("profile_calendar_missing_shared_dates") or [])
                        ),
                        "profile_calendar_extra_profile_dates": int(
                            len(calendar_meta.get("profile_calendar_extra_profile_dates") or [])
                        ),
                        "run_success_days": int(success_days),
                        "run_failed_days": int(failed_days),
                        "executed_days": int(metrics.get("executed_days", 0)),
                        "nav_return_pct": float(metrics.get("nav_return_pct", 0.0)),
                        "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0.0)),
                        "turnover_sum": float(metrics.get("turnover_sum", 0.0)),
                        "turnover_mean": float(metrics.get("turnover_mean", 0.0)),
                        "exec_block_rate_pct": float(metrics.get("exec_block_rate_pct", 0.0)),
                        "risk_block_rate_pct": float(metrics.get("risk_block_rate_pct", 0.0)),
                        "style_hit_total": float(metrics.get("style_hit_total", 0.0)),
                        "style_hit_mean": float(metrics.get("style_hit_mean", 0.0)),
                        "style_hit_rate_pct": float(metrics.get("style_hit_rate_pct", 0.0)),
                        "style_hit_size_total": float(metrics.get("style_hit_size_total", 0.0)),
                        "style_hit_beta_total": float(metrics.get("style_hit_beta_total", 0.0)),
                        "style_hit_momentum_total": float(metrics.get("style_hit_momentum_total", 0.0)),
                        "style_hit_vol_total": float(metrics.get("style_hit_vol_total", 0.0)),
                        "target_weight_sum_mean": float(metrics.get("target_weight_sum_mean", 0.0)),
                        "unfilled_target_weight_sum": float(metrics.get("unfilled_target_weight_sum", 0.0)),
                        "impact_cost_bps_mean": float(metrics.get("impact_cost_bps_mean", 0.0)),
                        "max_participation_pct": float(metrics.get("max_participation_pct", 0.0)),
                        "target_weight_source_external_rate_pct": float(metrics.get("target_weight_source_external_rate_pct", 0.0)),
                        "target_weight_checksum_coverage_pct": float(metrics.get("target_weight_checksum_coverage_pct", 0.0)),
                        "target_weight_checksum_unique_count": float(metrics.get("target_weight_checksum_unique_count", 0.0)),
                        "upstream_target_weight_present_days": float(
                            metrics.get("upstream_target_weight_present_days", 0.0)
                        ),
                        "upstream_target_weight_present_rate_pct": float(
                            metrics.get("upstream_target_weight_present_rate_pct", 0.0)
                        ),
                        "upstream_target_weight_sum_mean": float(
                            metrics.get("upstream_target_weight_sum_mean", 0.0)
                        ),
                        "upstream_target_weight_positive_count_mean": float(
                            metrics.get("upstream_target_weight_positive_count_mean", 0.0)
                        ),
                        "upstream_target_weight_max_mean": float(
                            metrics.get("upstream_target_weight_max_mean", 0.0)
                        ),
                        "upstream_target_weight_gap_abs_max": float(
                            metrics.get("upstream_target_weight_gap_abs_max", 0.0)
                        ),
                        "upstream_target_weight_overrun_max": float(
                            metrics.get("upstream_target_weight_overrun_max", 0.0)
                        ),
                        "upstream_target_weight_underuse_max": float(
                            metrics.get("upstream_target_weight_underuse_max", 0.0)
                        ),
                        "holiday_gap_guard_days": float(metrics.get("holiday_gap_guard_days", 0.0)),
                        "holiday_gap_guard_rate_pct": float(metrics.get("holiday_gap_guard_rate_pct", 0.0)),
                        "holiday_gap_signal_trade_gap_days_max": float(
                            metrics.get("holiday_gap_signal_trade_gap_days_max", 0.0)
                        ),
                        "holiday_gap_post_trade_gap_days_max": float(
                            metrics.get("holiday_gap_post_trade_gap_days_max", 0.0)
                        ),
                        "holiday_gap_target_scale_min": float(metrics.get("holiday_gap_target_scale_min", 1.0)),
                        "entry_not_tradable_orders": float(metrics.get("entry_not_tradable_orders", 0.0)),
                        "exit_not_tradable_orders": float(metrics.get("exit_not_tradable_orders", 0.0)),
                        "broker_entry_not_tradable_orders": float(metrics.get("broker_entry_not_tradable_orders", 0.0)),
                        "broker_exit_not_tradable_orders": float(metrics.get("broker_exit_not_tradable_orders", 0.0)),
                        "broker_tradability_block_orders": float(metrics.get("broker_tradability_block_orders", 0.0)),
                        "blocked_target_weight_sum": float(metrics.get("blocked_target_weight_sum", 0.0)),
                        "entry_not_tradable_target_weight_sum": float(metrics.get("entry_not_tradable_target_weight_sum", 0.0)),
                        "exit_not_tradable_target_weight_sum": float(metrics.get("exit_not_tradable_target_weight_sum", 0.0)),
                        "max_daily_tradability_blocked_orders": float(metrics.get("max_daily_tradability_blocked_orders", 0.0)),
                        "reserve_enabled_days": float(metrics.get("reserve_enabled_days", 0.0)),
                        "reserve_candidate_pool_n_mean": float(metrics.get("reserve_candidate_pool_n_mean", 0.0)),
                        "reserve_rounds_used_max": float(metrics.get("reserve_rounds_used_max", 0.0)),
                        "pre_optimizer_blocked_count_sum": float(metrics.get("pre_optimizer_blocked_count_sum", 0.0)),
                        "post_optimizer_blocked_count_sum": float(metrics.get("post_optimizer_blocked_count_sum", 0.0)),
                        "risk_entry_not_tradable_hit_sum": float(metrics.get("risk_entry_not_tradable_hit_sum", 0.0)),
                        "blocked_sell_current_weight_sum": float(metrics.get("blocked_sell_current_weight_sum", 0.0)),
                        "blocked_sell_current_weight_max": float(metrics.get("blocked_sell_current_weight_max", 0.0)),
                        "blocked_sell_notional_sum": float(metrics.get("blocked_sell_notional_sum", 0.0)),
                        "blocked_sell_orders_sum": float(metrics.get("blocked_sell_orders_sum", 0.0)),
                        "blocked_sell_entry_risk_score_weighted_mean_max": float(
                            metrics.get("blocked_sell_entry_risk_score_weighted_mean_max", 0.0)
                        ),
                        "blocked_sell_entry_tradability_safe_score_weighted_mean_min": float(
                            metrics.get("blocked_sell_entry_tradability_safe_score_weighted_mean_min", 0.0)
                        ),
                        "blocked_sell_entry_exit_trap_risk_score_weighted_mean_max": float(
                            metrics.get("blocked_sell_entry_exit_trap_risk_score_weighted_mean_max", 0.0)
                        ),
                        "blocked_sell_entry_exit_trap_volume_drought_risk_weighted_mean_max": float(
                            metrics.get(
                                "blocked_sell_entry_exit_trap_volume_drought_risk_weighted_mean_max",
                                0.0,
                            )
                        ),
                        "blocked_sell_entry_limit_headroom_min": float(
                            metrics.get("blocked_sell_entry_limit_headroom_min", 0.0)
                        ),
                        "blocked_sell_high_entry_risk_orders_sum": float(
                            metrics.get("blocked_sell_high_entry_risk_orders_sum", 0.0)
                        ),
                        "blocked_sell_high_entry_exit_trap_risk_orders_sum": float(
                            metrics.get("blocked_sell_high_entry_exit_trap_risk_orders_sum", 0.0)
                        ),
                        "blocked_sell_high_entry_exit_trap_volume_drought_orders_sum": float(
                            metrics.get("blocked_sell_high_entry_exit_trap_volume_drought_orders_sum", 0.0)
                        ),
                        "blocked_sell_low_entry_safety_orders_sum": float(
                            metrics.get("blocked_sell_low_entry_safety_orders_sum", 0.0)
                        ),
                        "blocked_sell_reserve_entry_orders_sum": float(
                            metrics.get("blocked_sell_reserve_entry_orders_sum", 0.0)
                        ),
                        "blocked_exit_buy_freeze_days": float(metrics.get("blocked_exit_buy_freeze_days", 0.0)),
                        "blocked_exit_freeze_sell_weight_max": float(
                            metrics.get("blocked_exit_freeze_sell_weight_max", 0.0)
                        ),
                        "blocked_exit_freeze_sell_notional_max": float(
                            metrics.get("blocked_exit_freeze_sell_notional_max", 0.0)
                        ),
                        "blocked_exit_freeze_orders_sum": float(metrics.get("blocked_exit_freeze_orders_sum", 0.0)),
                        "blocked_exit_freeze_target_weight_sum": float(
                            metrics.get("blocked_exit_freeze_target_weight_sum", 0.0)
                        ),
                        "active_blocked_sell_state_count_max": float(
                            metrics.get("active_blocked_sell_state_count_max", 0.0)
                        ),
                        "active_blocked_sell_state_weight_max": float(
                            metrics.get("active_blocked_sell_state_weight_max", 0.0)
                        ),
                        "active_blocked_sell_state_notional_max": float(
                            metrics.get("active_blocked_sell_state_notional_max", 0.0)
                        ),
                        "active_blocked_sell_state_max_consecutive_days_max": float(
                            metrics.get("active_blocked_sell_state_max_consecutive_days_max", 0.0)
                        ),
                        "blocked_state_count_max": float(metrics.get("blocked_state_count_max", 0.0)),
                        "blocked_state_buy_count_max": float(metrics.get("blocked_state_buy_count_max", 0.0)),
                        "blocked_state_sell_count_max": float(metrics.get("blocked_state_sell_count_max", 0.0)),
                        "blocked_state_max_consecutive_days_max": float(
                            metrics.get("blocked_state_max_consecutive_days_max", 0.0)
                        ),
                        "blocked_state_sell_notional_max": float(metrics.get("blocked_state_sell_notional_max", 0.0)),
                        "blocked_state_buy_target_weight_sum": float(
                            metrics.get("blocked_state_buy_target_weight_sum", 0.0)
                        ),
                        "blocked_state_sell_target_weight_sum": float(
                            metrics.get("blocked_state_sell_target_weight_sum", 0.0)
                        ),
                        "blocked_state_resolved_count_sum": float(metrics.get("blocked_state_resolved_count_sum", 0.0)),
                        "empty_signal_days": float(metrics.get("empty_signal_days", 0.0)),
                        "empty_signal_rate_pct": float(metrics.get("empty_signal_rate_pct", 0.0)),
                        "empty_signal_raw_days": float(metrics.get("empty_signal_raw_days", 0.0)),
                        "empty_after_universe_filter_days": float(metrics.get("empty_after_universe_filter_days", 0.0)),
                        "empty_signal_raw_rows_sum": float(metrics.get("empty_signal_raw_rows_sum", 0.0)),
                        "empty_signal_post_filter_rows_sum": float(metrics.get("empty_signal_post_filter_rows_sum", 0.0)),
                        "empty_signal_filtered_bj9_rows_sum": float(metrics.get("empty_signal_filtered_bj9_rows_sum", 0.0)),
                        "empty_signal_filtered_st_rows_sum": float(metrics.get("empty_signal_filtered_st_rows_sum", 0.0)),
                        "executable_pool_halt_days": float(metrics.get("executable_pool_halt_days", 0.0)),
                        "executable_pool_halt_rate_pct": float(metrics.get("executable_pool_halt_rate_pct", 0.0)),
                        "executable_pool_halt_input_sum": float(metrics.get("executable_pool_halt_input_sum", 0.0)),
                        "executable_pool_halt_blocked_sum": float(metrics.get("executable_pool_halt_blocked_sum", 0.0)),
                        "executable_pool_halt_adv_hit_sum": float(
                            metrics.get("executable_pool_halt_adv_hit_sum", 0.0)
                        ),
                        "executable_pool_halt_entry_not_tradable_hit_sum": float(
                            metrics.get("executable_pool_halt_entry_not_tradable_hit_sum", 0.0)
                        ),
                        "executable_pool_halt_style_hit_sum": float(
                            metrics.get("executable_pool_halt_style_hit_sum", 0.0)
                        ),
                        "objective_score": float(obj),
                    }
                )

    run_df = pd.DataFrame(run_rows)
    summary_df = pd.DataFrame(summary_rows).sort_values(
        ["window", "objective_score", "nav_return_pct"], ascending=[True, False, False]
    )
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profiles": profiles,
        "windows": windows,
        "signal_dates": len(signal_dates),
        "raw_signal_dates": len(raw_signal_dates),
        "shared_signal_filter": shared_signal_filter_meta,
        "market_trade_dates": len(market_trade_dates),
        "market_last_trade_date": market_trade_dates[-1] if market_trade_dates else "",
        "profile_signal_root": str(args.profile_signal_root),
        "profile_signal_date_counts": profile_signal_date_counts,
        "profile_replayable_signal_date_counts": profile_replayable_signal_date_counts,
        "profile_signal_filter": profile_signal_filter_meta,
        "profile_calendar_aligned_to_shared": bool(align_profile_calendar_to_shared),
        "style_grid_count": int(len(style_grid)),
        "style_grid": style_grid,
        "execution_mode": str(args.execution_mode),
        "objective": "ret - 0.60*|mdd| - 0.00002*turnover_mean - 0.12*exec_block - 0.12*risk_block - 0.08*style_hit_rate",
    }

    profile_slug = _single_profile_slug(profiles)
    suffix = f"_{profile_slug}" if profile_slug else ""

    run_file = BACKTEST_DIR / f"p2_rolling_replay_runs_{ts}{suffix}.csv"
    summary_file = BACKTEST_DIR / f"p2_rolling_replay_summary_{ts}{suffix}.csv"
    meta_file = BACKTEST_DIR / f"p2_rolling_replay_meta_{ts}{suffix}.json"
    run_df.to_csv(run_file, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_file, index=False, encoding="utf-8-sig")
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.write_latest:
        if profile_slug:
            run_df.to_csv(BACKTEST_DIR / f"p2_rolling_replay_runs_latest_{profile_slug}.csv", index=False, encoding="utf-8-sig")
            summary_df.to_csv(BACKTEST_DIR / f"p2_rolling_replay_summary_latest_{profile_slug}.csv", index=False, encoding="utf-8-sig")
            (BACKTEST_DIR / f"p2_rolling_replay_meta_latest_{profile_slug}.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            run_df.to_csv(BACKTEST_DIR / "p2_rolling_replay_runs_latest.csv", index=False, encoding="utf-8-sig")
            summary_df.to_csv(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv", index=False, encoding="utf-8-sig")
            (BACKTEST_DIR / "p2_rolling_replay_meta_latest.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    _log(f"回放明细: {run_file}")
    _log(f"回放汇总: {summary_file}")
    if not summary_df.empty:
        top = summary_df.iloc[0]
        _log(
            "最佳组合: "
            f"profile={top['profile']}, window={int(top['window'])}, "
            f"objective={float(top['objective_score']):.4f}, "
            f"ret={float(top['nav_return_pct']):.2f}%, mdd={float(top['max_drawdown_pct']):.2f}%"
        )

    if args.strict and summary_df.empty:
        return 2
    if args.strict and bool((summary_df["executed_days"] <= 0).any()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
