#!/usr/bin/env python3
"""Join capacity-feasible alpha evidence to realized P2 path returns.

This diagnostic answers a narrow question: when a score looks positive after
capacity constraints, did that static evidence actually pass through to P2
daily returns versus the main profile, or was it consumed by cash drag, holiday
guards, sell traps, or underdeployment?

It is diagnostic evidence only. It does not change profiles or promotion gates.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

import quant_p2_smoke_failure_diagnosis as p2_smoke  # noqa: E402

BACKTEST_DIR = BASE_DIR / "output" / "backtest"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _safe_int(value: object, default: int = 0) -> int:
    return int(round(_safe_float(value, float(default))))


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(value).lower()).strip("_")


def _yyyymmdd(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.notna(ts):
        return ts.strftime("%Y%m%d")
    raw = str(value or "").strip()
    return raw.replace("-", "")[:8] if raw else ""


def _date_display(value: object) -> str:
    d = _yyyymmdd(value)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""


def _latest_capacity_daily(profile: str) -> Path | None:
    slug = _slug(profile)
    latest = BACKTEST_DIR / f"quant_capacity_feasible_alpha_diagnosis_latest_{slug}_daily.csv"
    if latest.exists():
        return latest
    matches = sorted(glob.glob(str(BACKTEST_DIR / f"quant_capacity_feasible_alpha_diagnosis_{slug}_*_daily.csv")))
    return Path(matches[-1]) if matches else None


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return pd.read_csv(path)


def _corr(a: pd.Series, b: pd.Series) -> float:
    left = pd.to_numeric(a, errors="coerce")
    right = pd.to_numeric(b, errors="coerce")
    mask = left.notna() & right.notna()
    if int(mask.sum()) < 3:
        return float("nan")
    if float(left.loc[mask].std(ddof=0)) <= 1e-12 or float(right.loc[mask].std(ddof=0)) <= 1e-12:
        return float("nan")
    return float(left.loc[mask].corr(right.loc[mask]))


def _num(row: pd.Series, col: str, default: float = 0.0) -> float:
    return _safe_float(row.get(col, default), default)


def _intnum(row: pd.Series, col: str, default: int = 0) -> int:
    return _safe_int(row.get(col, default), default)


def build_p2_relative_detail(
    p2_summary: pd.DataFrame,
    *,
    main_profile: str,
    candidate_profile: str,
    window: int | None = None,
) -> pd.DataFrame:
    """Build same-signal-date P2 path comparison with guard/block fields."""

    best = p2_smoke._best_summary_rows(p2_summary, window)
    main_row = p2_smoke._row_for_profile(best, main_profile, window)
    cand_row = p2_smoke._row_for_profile(best, candidate_profile, window)
    if main_row is None or cand_row is None:
        return pd.DataFrame()
    main_ledger = p2_smoke._load_ledger(str(main_row.get("channel", "")))
    cand_ledger = p2_smoke._load_ledger(str(cand_row.get("channel", "")))
    if main_ledger.empty or cand_ledger.empty:
        return pd.DataFrame()
    main_map = {str(r.get("signal_key", "")): r for _, r in main_ledger.iterrows() if str(r.get("signal_key", ""))}
    cand_map = {str(r.get("signal_key", "")): r for _, r in cand_ledger.iterrows() if str(r.get("signal_key", ""))}
    rows: list[dict[str, object]] = []
    for key in sorted(set(main_map) & set(cand_map)):
        m = main_map[key]
        c = cand_map[key]
        main_ret = _num(m, "daily_return")
        cand_ret = _num(c, "daily_return")
        target_gap = _num(c, "target_weight_sum") - _num(m, "target_weight_sum")
        rows.append(
            {
                "signal_key": key,
                "signal_date": _date_display(key),
                "main_profile": main_profile,
                "candidate_profile": candidate_profile,
                "window": _safe_int(cand_row.get("window", window or 0), window or 0),
                "main_trade_date": _date_display(m.get("trade_date", "")),
                "candidate_trade_date": _date_display(c.get("trade_date", "")),
                "main_daily_return_pct": float(main_ret * 100.0),
                "candidate_daily_return_pct": float(cand_ret * 100.0),
                "relative_return_gap_pct": float((cand_ret - main_ret) * 100.0),
                "main_target_weight_sum": _num(m, "target_weight_sum"),
                "candidate_target_weight_sum": _num(c, "target_weight_sum"),
                "target_weight_gap": float(target_gap),
                "cash_drag_proxy_pct": float(max(0.0, -target_gap) * max(0.0, main_ret) * 100.0),
                "main_holiday_gap_guard": _intnum(m, "holiday_gap_guard"),
                "candidate_holiday_gap_guard": _intnum(c, "holiday_gap_guard"),
                "main_holiday_gap_reason": str(m.get("holiday_gap_reason", "") or ""),
                "candidate_holiday_gap_reason": str(c.get("holiday_gap_reason", "") or ""),
                "main_holiday_gap_target_scale": _num(m, "holiday_gap_target_scale", 1.0),
                "candidate_holiday_gap_target_scale": _num(c, "holiday_gap_target_scale", 1.0),
                "main_broker_entry_blocks": _intnum(m, "broker_entry_not_tradable_orders"),
                "candidate_broker_entry_blocks": _intnum(c, "broker_entry_not_tradable_orders"),
                "main_broker_exit_blocks": _intnum(m, "broker_exit_not_tradable_orders"),
                "candidate_broker_exit_blocks": _intnum(c, "broker_exit_not_tradable_orders"),
                "exit_block_delta": _intnum(c, "broker_exit_not_tradable_orders")
                - _intnum(m, "broker_exit_not_tradable_orders"),
                "main_blocked_sell_current_weight": _num(m, "blocked_sell_current_weight"),
                "candidate_blocked_sell_current_weight": _num(c, "blocked_sell_current_weight"),
                "blocked_sell_weight_gap": _num(c, "blocked_sell_current_weight")
                - _num(m, "blocked_sell_current_weight"),
                "main_risk_blocked_rate_pct": _num(m, "risk_blocked_rate_pct"),
                "candidate_risk_blocked_rate_pct": _num(c, "risk_blocked_rate_pct"),
                "risk_blocked_rate_gap_pct": _num(c, "risk_blocked_rate_pct") - _num(m, "risk_blocked_rate_pct"),
                "main_execution_state": str(m.get("execution_state", "") or ""),
                "candidate_execution_state": str(c.get("execution_state", "") or ""),
            }
        )
    return pd.DataFrame(rows)


def _prepare_capacity_daily(
    capacity_daily: pd.DataFrame,
    *,
    score_col: str,
    primary_promotion_mode: str,
) -> pd.DataFrame:
    if capacity_daily.empty:
        return pd.DataFrame()
    df = capacity_daily.copy()
    if "score_col" in df.columns:
        df = df[df["score_col"].astype(str).eq(str(score_col))].copy()
    if "primary_promotion_mode" in df.columns:
        df = df[df["primary_promotion_mode"].astype(str).eq(str(primary_promotion_mode))].copy()
    if df.empty:
        return df
    df["signal_key"] = df["signal_date"].map(_yyyymmdd)
    rename = {
        "pool_mean_forward_return_pct": "static_pool_forward_return_pct",
        "selected_weighted_forward_return_pct": "static_selected_forward_return_pct",
        "selected_equal_forward_return_pct": "static_selected_equal_forward_return_pct",
        "selected_minus_pool_pct": "static_selected_minus_pool_pct",
        "target_weight_sum": "static_target_weight_sum",
        "capacity_shortfall_weight": "static_capacity_shortfall_weight",
        "max_industry_weight": "static_max_industry_weight",
        "max_adv_participation_pct": "static_max_adv_participation_pct",
        "selection_loss_pct": "static_selection_loss_pct",
    }
    keep = [
        "signal_key",
        "signal_date",
        "score_col",
        "primary_promotion_mode",
        "input_rows",
        "top_n",
        "rank_ic",
        "zero_target",
        "selected_count",
        "blocked_count",
        "adv_clip_rows",
        "industry_clip_rows",
        "reserve_clip_rows",
        "exit_trap_clip_rows",
        "selection_loss_label",
        "top_selected_overlap_rate_pct",
        "top_dropped_rows",
        "top_dropped_mean_forward_return_pct",
        "selected_replacement_rows",
        "selected_replacement_mean_forward_return_pct",
    ]
    keep += [c for c in rename if c in df.columns]
    out = df[[c for c in keep if c in df.columns]].rename(columns=rename)
    return out.drop_duplicates(subset=["signal_key"], keep="last").reset_index(drop=True)


def _classify_day(row: pd.Series) -> str:
    static_positive = bool(row.get("static_positive", False))
    p2_under = bool(row.get("p2_underperform_main", False))
    holiday = _safe_int(row.get("candidate_holiday_gap_guard", 0)) > 0
    target_gap = _safe_float(row.get("target_weight_gap", 0.0))
    exit_worse = _safe_int(row.get("exit_block_delta", 0)) > 0 or _safe_float(row.get("blocked_sell_weight_gap", 0.0)) > 0.0025
    entry_worse = _safe_int(row.get("candidate_broker_entry_blocks", 0)) > _safe_int(row.get("main_broker_entry_blocks", 0))
    if static_positive and p2_under and holiday and target_gap < -0.05 and exit_worse:
        return "static_positive_lost_to_holiday_cash_drag_and_sell_trap"
    if static_positive and p2_under and holiday and target_gap < -0.05:
        return "static_positive_lost_to_holiday_cash_drag"
    if static_positive and p2_under and exit_worse:
        return "static_positive_lost_to_sell_trap"
    if static_positive and p2_under and entry_worse:
        return "static_positive_lost_to_entry_block"
    if static_positive and p2_under and target_gap < -0.05:
        return "static_positive_lost_to_underdeployment"
    if static_positive and p2_under:
        return "static_positive_lost_to_path_return"
    if static_positive and not p2_under:
        return "static_alpha_p2_passed_day"
    if (not static_positive) and p2_under:
        return "static_alpha_negative_p2_lost"
    return "static_alpha_negative_but_p2_ok"


def _verdict(summary: dict[str, object], reason_summary: pd.DataFrame) -> str:
    aligned = _safe_int(summary.get("aligned_days", 0))
    if aligned < 20:
        return "insufficient_sample"
    static_mean = _safe_float(summary.get("static_selected_forward_return_mean_pct", 0.0))
    spread_mean = _safe_float(summary.get("static_selected_minus_pool_mean_pct", 0.0))
    rel_sum = _safe_float(summary.get("relative_return_gap_sum_pct", 0.0))
    if static_mean <= 0.0 or spread_mean <= 0.0:
        return "static_alpha_not_positive"
    if rel_sum >= 0.0:
        return "static_alpha_p2_passed"
    if reason_summary.empty or "negative_gap_abs_sum_pct" not in reason_summary.columns:
        return "static_alpha_not_p2_passed"
    total_loss = float(pd.to_numeric(reason_summary["negative_gap_abs_sum_pct"], errors="coerce").fillna(0.0).sum())
    if total_loss <= 1e-12:
        return "static_alpha_not_p2_passed"

    def _share(labels: list[str]) -> float:
        mask = reason_summary["pass_through_label"].astype(str).str.contains("|".join(labels), case=False, regex=True)
        loss = float(pd.to_numeric(reason_summary.loc[mask, "negative_gap_abs_sum_pct"], errors="coerce").fillna(0.0).sum())
        return loss / total_loss

    if _share(["holiday"]) >= 0.45:
        return "holiday_cash_drag_dominant"
    if _share(["sell_trap"]) >= 0.45:
        return "sell_trap_dominant"
    if _share(["underdeployment"]) >= 0.45:
        return "underdeployment_dominant"
    return "static_alpha_not_p2_passed"


def build_pass_through_report(
    *,
    capacity_daily: pd.DataFrame,
    p2_detail: pd.DataFrame,
    profile: str,
    main_profile: str,
    window: int,
    score_col: str,
    primary_promotion_mode: str = "keep",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return summary, daily detail, and reason summary dataframes."""

    cap = _prepare_capacity_daily(
        capacity_daily,
        score_col=score_col,
        primary_promotion_mode=primary_promotion_mode,
    )
    if cap.empty or p2_detail.empty:
        empty_summary = pd.DataFrame(
            [
                {
                    "profile": profile,
                    "main_profile": main_profile,
                    "window": int(window),
                    "score_col": score_col,
                    "primary_promotion_mode": primary_promotion_mode,
                    "verdict": "insufficient_sample",
                    "aligned_days": 0,
                }
            ]
        )
        return empty_summary, pd.DataFrame(), pd.DataFrame()
    detail = p2_detail.copy()
    detail["signal_key"] = detail["signal_date"].map(_yyyymmdd)
    merged = detail.merge(cap, on="signal_key", how="left", suffixes=("", "_capacity"))
    for col in [
        "static_selected_forward_return_pct",
        "static_selected_equal_forward_return_pct",
        "static_selected_minus_pool_pct",
        "static_pool_forward_return_pct",
        "static_target_weight_sum",
        "rank_ic",
        "static_capacity_shortfall_weight",
        "static_selection_loss_pct",
    ]:
        if col not in merged.columns:
            merged[col] = np.nan
        merged[col] = pd.to_numeric(merged[col], errors="coerce")
    merged["static_positive"] = merged["static_selected_forward_return_pct"].gt(0.0)
    merged["static_spread_positive"] = merged["static_selected_minus_pool_pct"].gt(0.0)
    merged["p2_underperform_main"] = pd.to_numeric(merged["relative_return_gap_pct"], errors="coerce").lt(0.0)
    merged["candidate_p2_negative"] = pd.to_numeric(merged["candidate_daily_return_pct"], errors="coerce").lt(0.0)
    merged["static_positive_p2_underperform"] = merged["static_positive"] & merged["p2_underperform_main"]
    merged["static_positive_candidate_negative"] = merged["static_positive"] & merged["candidate_p2_negative"]
    merged["p2_minus_static_proxy_pct"] = (
        pd.to_numeric(merged["candidate_daily_return_pct"], errors="coerce")
        - pd.to_numeric(merged["static_selected_forward_return_pct"], errors="coerce")
    )
    merged["pass_through_label"] = merged.apply(_classify_day, axis=1)
    merged["missing_capacity_row"] = merged["static_selected_forward_return_pct"].isna()

    rel = pd.to_numeric(merged["relative_return_gap_pct"], errors="coerce").fillna(0.0)
    static_ret = pd.to_numeric(merged["static_selected_forward_return_pct"], errors="coerce")
    static_spread = pd.to_numeric(merged["static_selected_minus_pool_pct"], errors="coerce")
    cand_ret = pd.to_numeric(merged["candidate_daily_return_pct"], errors="coerce").fillna(0.0)
    main_ret = pd.to_numeric(merged["main_daily_return_pct"], errors="coerce").fillna(0.0)
    target_gap = pd.to_numeric(merged["target_weight_gap"], errors="coerce").fillna(0.0)
    cash_drag = pd.to_numeric(merged["cash_drag_proxy_pct"], errors="coerce").fillna(0.0)
    static_pos = merged["static_positive"].fillna(False)
    p2_under = merged["p2_underperform_main"].fillna(False)

    reason_summary = (
        merged.assign(negative_gap_abs_pct=np.where(rel.lt(0.0), -rel, 0.0))
        .groupby("pass_through_label", dropna=False)
        .agg(
            days=("signal_key", "count"),
            relative_return_gap_sum_pct=("relative_return_gap_pct", "sum"),
            relative_return_gap_mean_pct=("relative_return_gap_pct", "mean"),
            negative_gap_abs_sum_pct=("negative_gap_abs_pct", "sum"),
            static_selected_forward_return_mean_pct=("static_selected_forward_return_pct", "mean"),
            candidate_daily_return_mean_pct=("candidate_daily_return_pct", "mean"),
            target_weight_gap_mean=("target_weight_gap", "mean"),
            cash_drag_proxy_sum_pct=("cash_drag_proxy_pct", "sum"),
            exit_block_delta_sum=("exit_block_delta", "sum"),
            blocked_sell_weight_gap_max=("blocked_sell_weight_gap", "max"),
        )
        .reset_index()
        .sort_values(["negative_gap_abs_sum_pct", "days"], ascending=[False, False])
    )

    summary: dict[str, object] = {
        "profile": profile,
        "main_profile": main_profile,
        "window": int(window),
        "score_col": score_col,
        "primary_promotion_mode": primary_promotion_mode,
        "aligned_days": int(len(merged)),
        "capacity_rows_matched": int((~merged["missing_capacity_row"]).sum()),
        "missing_capacity_rows": int(merged["missing_capacity_row"].sum()),
        "static_positive_days": int(static_pos.sum()),
        "static_positive_rate_pct": float(static_pos.mean() * 100.0) if len(static_pos) else 0.0,
        "static_positive_p2_underperform_days": int((static_pos & p2_under).sum()),
        "static_positive_p2_underperform_rate_pct": float((static_pos & p2_under).sum() / max(int(static_pos.sum()), 1) * 100.0),
        "static_positive_candidate_negative_days": int(merged["static_positive_candidate_negative"].sum()),
        "static_selected_forward_return_mean_pct": float(static_ret.mean()) if static_ret.notna().any() else 0.0,
        "static_selected_minus_pool_mean_pct": float(static_spread.mean()) if static_spread.notna().any() else 0.0,
        "candidate_daily_return_mean_pct": float(cand_ret.mean()) if len(cand_ret) else 0.0,
        "main_daily_return_mean_pct": float(main_ret.mean()) if len(main_ret) else 0.0,
        "relative_return_gap_sum_pct": float(rel.sum()),
        "relative_return_gap_mean_pct": float(rel.mean()) if len(rel) else 0.0,
        "relative_return_gap_static_positive_sum_pct": float(rel.loc[static_pos].sum()) if static_pos.any() else 0.0,
        "relative_return_gap_static_nonpositive_sum_pct": float(rel.loc[~static_pos].sum()) if (~static_pos).any() else 0.0,
        "static_vs_candidate_p2_corr": _corr(static_ret, cand_ret),
        "static_vs_relative_gap_corr": _corr(static_ret, rel),
        "target_weight_gap_mean": float(target_gap.mean()) if len(target_gap) else 0.0,
        "target_weight_gap_p10": float(target_gap.quantile(0.10)) if len(target_gap) else 0.0,
        "cash_drag_proxy_sum_pct": float(cash_drag.sum()),
        "cash_drag_proxy_static_positive_sum_pct": float(cash_drag.loc[static_pos].sum()) if static_pos.any() else 0.0,
        "holiday_guard_days": int(pd.to_numeric(merged["candidate_holiday_gap_guard"], errors="coerce").fillna(0).gt(0).sum())
        if "candidate_holiday_gap_guard" in merged.columns
        else 0,
        "exit_block_delta_sum": int(pd.to_numeric(merged["exit_block_delta"], errors="coerce").fillna(0).sum())
        if "exit_block_delta" in merged.columns
        else 0,
        "blocked_sell_weight_gap_max": float(pd.to_numeric(merged["blocked_sell_weight_gap"], errors="coerce").fillna(0.0).max())
        if "blocked_sell_weight_gap" in merged.columns and len(merged)
        else 0.0,
        "underdeployment_days": int(merged["pass_through_label"].astype(str).str.contains("underdeployment|cash_drag", regex=True).sum()),
        "sell_trap_days": int(merged["pass_through_label"].astype(str).str.contains("sell_trap", regex=True).sum()),
    }
    summary["verdict"] = _verdict(summary, reason_summary)

    lead = [
        "signal_date",
        "pass_through_label",
        "static_selected_forward_return_pct",
        "static_selected_minus_pool_pct",
        "candidate_daily_return_pct",
        "main_daily_return_pct",
        "relative_return_gap_pct",
        "target_weight_gap",
        "cash_drag_proxy_pct",
        "candidate_holiday_gap_reason",
        "candidate_holiday_gap_target_scale",
        "exit_block_delta",
        "blocked_sell_weight_gap",
        "selection_loss_label",
    ]
    merged = merged[[c for c in lead if c in merged.columns] + [c for c in merged.columns if c not in lead]]
    return pd.DataFrame([summary]), merged, reason_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose static alpha to P2 pass-through")
    parser.add_argument("--capacity-daily", default="", help="Capacity-feasible daily CSV; default latest for profile")
    parser.add_argument("--p2-summary", default=str(BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"))
    parser.add_argument("--main-profile", default="quality_regime")
    parser.add_argument("--profile", required=True, help="Candidate profile")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--score-col", default="portfolio_rank_score")
    parser.add_argument("--primary-promotion-mode", default="keep")
    parser.add_argument("--write-latest", action="store_true")
    args = parser.parse_args()

    capacity_path = Path(args.capacity_daily).expanduser().resolve() if str(args.capacity_daily or "").strip() else None
    if capacity_path is None:
        capacity_path = _latest_capacity_daily(str(args.profile))
    if capacity_path is None:
        raise FileNotFoundError(f"capacity feasible daily file not found for profile={args.profile}")
    p2_summary_path = Path(args.p2_summary).expanduser().resolve()
    capacity_daily = _load_csv(capacity_path)
    p2_summary = _load_csv(p2_summary_path)
    p2_detail = build_p2_relative_detail(
        p2_summary,
        main_profile=str(args.main_profile),
        candidate_profile=str(args.profile),
        window=int(args.window) if args.window else None,
    )
    summary, detail, reason = build_pass_through_report(
        capacity_daily=capacity_daily,
        p2_detail=p2_detail,
        profile=str(args.profile),
        main_profile=str(args.main_profile),
        window=int(args.window),
        score_col=str(args.score_col),
        primary_promotion_mode=str(args.primary_promotion_mode),
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slug(str(args.profile))
    summary_fp = BACKTEST_DIR / f"quant_static_to_p2_pass_through_{slug}_{ts}_summary.csv"
    detail_fp = BACKTEST_DIR / f"quant_static_to_p2_pass_through_{slug}_{ts}_detail.csv"
    reason_fp = BACKTEST_DIR / f"quant_static_to_p2_pass_through_{slug}_{ts}_reason_summary.csv"
    meta_fp = BACKTEST_DIR / f"quant_static_to_p2_pass_through_{slug}_{ts}.json"
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_fp, index=False, encoding="utf-8-sig")
    detail.to_csv(detail_fp, index=False, encoding="utf-8-sig")
    reason.to_csv(reason_fp, index=False, encoding="utf-8-sig")
    meta: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile": str(args.profile),
        "main_profile": str(args.main_profile),
        "window": int(args.window),
        "score_col": str(args.score_col),
        "primary_promotion_mode": str(args.primary_promotion_mode),
        "capacity_daily": str(capacity_path),
        "p2_summary": str(p2_summary_path),
        "summary": str(summary_fp),
        "detail": str(detail_fp),
        "reason_summary": str(reason_fp),
        "rows": summary.to_dict(orient="records"),
    }
    meta_fp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest_summary = BACKTEST_DIR / f"quant_static_to_p2_pass_through_latest_{slug}_summary.csv"
        latest_detail = BACKTEST_DIR / f"quant_static_to_p2_pass_through_latest_{slug}_detail.csv"
        latest_reason = BACKTEST_DIR / f"quant_static_to_p2_pass_through_latest_{slug}_reason_summary.csv"
        latest_json = BACKTEST_DIR / f"quant_static_to_p2_pass_through_latest_{slug}.json"
        summary.to_csv(latest_summary, index=False, encoding="utf-8-sig")
        detail.to_csv(latest_detail, index=False, encoding="utf-8-sig")
        reason.to_csv(latest_reason, index=False, encoding="utf-8-sig")
        latest_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.to_csv(BACKTEST_DIR / "quant_static_to_p2_pass_through_latest_summary.csv", index=False, encoding="utf-8-sig")
        detail.to_csv(BACKTEST_DIR / "quant_static_to_p2_pass_through_latest_detail.csv", index=False, encoding="utf-8-sig")
        reason.to_csv(
            BACKTEST_DIR / "quant_static_to_p2_pass_through_latest_reason_summary.csv",
            index=False,
            encoding="utf-8-sig",
        )
        (BACKTEST_DIR / "quant_static_to_p2_pass_through_latest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(summary.to_string(index=False))
    if not reason.empty:
        print(reason.to_string(index=False))
    print(f"static_to_p2_summary={summary_fp}")
    print(f"static_to_p2_detail={detail_fp}")
    print(f"static_to_p2_reason_summary={reason_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
