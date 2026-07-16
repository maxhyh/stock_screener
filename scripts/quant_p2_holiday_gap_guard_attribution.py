#!/usr/bin/env python3
"""Attribute holiday-gap guard effects in P2 replay evidence.

This report is diagnostic only. It compares candidate ledgers against the main
profile on the same signal dates and estimates whether holiday-gap scaling
looked protective or mostly created cash drag. It is not a counterfactual
portfolio replay and must not be used as a direct promotion pass condition.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

BACKTEST_DIR = BASE_DIR / "output" / "backtest"
EXEC_DIR = BASE_DIR / "output" / "execution"


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


def _parse_list(raw: object) -> list[str]:
    out: list[str] = []
    for part in str(raw or "").split(","):
        s = part.strip()
        if s:
            out.append(s)
    return list(dict.fromkeys(out))


def _parse_windows(raw: object) -> list[int]:
    out: list[int] = []
    for item in _parse_list(raw):
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0:
            out.append(value)
    return sorted(set(out))


def _yyyymmdd(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.notna(ts):
        return ts.strftime("%Y%m%d")
    raw = str(value or "").strip()
    return raw.replace("-", "")[:8] if raw else ""


def _date_display(value: object) -> str:
    d = _yyyymmdd(value)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _load_summary(path: str, profiles: list[str]) -> tuple[pd.DataFrame, str]:
    fp = Path(path).expanduser().resolve() if str(path or "").strip() else BACKTEST_DIR / "p2_rolling_replay_summary_latest.csv"
    if not fp.exists():
        raise FileNotFoundError(str(fp))
    df = pd.read_csv(fp)
    if profiles and "profile" in df.columns:
        needed = set(profiles)
        df = df[df["profile"].astype(str).isin(needed)].copy()
    if df.empty:
        raise RuntimeError("P2 rolling summary is empty after profile filtering")
    return df.reset_index(drop=True), str(fp)


def _best_summary_rows(summary_df: pd.DataFrame, windows: list[int] | None) -> pd.DataFrame:
    df = summary_df.copy()
    if "window" in df.columns:
        df["window"] = pd.to_numeric(df["window"], errors="coerce").fillna(0).astype(int)
        if windows:
            df = df[df["window"].isin([int(x) for x in windows])].copy()
    if df.empty:
        return df
    sort_cols = [c for c in ["profile", "window", "objective_score", "nav_return_pct", "executed_days"] if c in df.columns]
    ascending = [True, True, False, False, False][: len(sort_cols)]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=ascending)
    return df.groupby(["profile", "window"], as_index=False).head(1).reset_index(drop=True)


def _summary_row(best_rows: pd.DataFrame, profile: str, window: int) -> pd.Series | None:
    rows = best_rows[best_rows["profile"].astype(str).eq(str(profile))].copy()
    if "window" in rows.columns:
        rows = rows[pd.to_numeric(rows["window"], errors="coerce").fillna(0).astype(int).eq(int(window))]
    return None if rows.empty else rows.iloc[0]


def _load_ledger(channel: str) -> pd.DataFrame:
    df = _load_csv(EXEC_DIR / f"{channel}_ledger.csv")
    if df.empty:
        return df
    out = df.copy()
    out["signal_key"] = out["signal_date"].map(_yyyymmdd) if "signal_date" in out.columns else ""
    out["trade_key"] = out["trade_date"].map(_yyyymmdd) if "trade_date" in out.columns else ""
    nav_pre = pd.to_numeric(out.get("nav_pre", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0)
    nav_post = pd.to_numeric(out.get("nav_post", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0)
    base = nav_post.shift(1)
    if len(base) > 0:
        base.iloc[0] = nav_pre.iloc[0]
    base = base.where(base.gt(0.0), nav_pre)
    out["daily_return_pct"] = np.where(base.gt(0.0), (nav_post / base - 1.0) * 100.0, 0.0)
    return out


def _artifact_path(channel: str, kind: str, trade_date: object, run_id: object) -> Path:
    return EXEC_DIR / f"{channel}_{kind}_{_yyyymmdd(trade_date)}_{run_id}.csv"


def _risk_summary(risk_df: pd.DataFrame, *, artifact_exists: bool) -> dict[str, object]:
    out = {
        "risk_artifact_missing": not bool(artifact_exists),
        "risk_gate_rows": 0,
        "risk_adv_hit_rows": 0,
        "risk_style_hit_rows": 0,
        "risk_industry_hit_rows": 0,
        "risk_entry_not_tradable_rows": 0,
        "risk_missing_bar_rows": 0,
    }
    if risk_df.empty:
        return out
    reasons = risk_df.get("reasons", pd.Series("", index=risk_df.index)).astype(str).str.lower()
    out["risk_artifact_missing"] = False
    out["risk_gate_rows"] = int(len(risk_df))
    out["risk_adv_hit_rows"] = int(reasons.str.contains("adv_participation", na=False).sum())
    out["risk_style_hit_rows"] = int(reasons.str.contains("style_", na=False).sum())
    out["risk_industry_hit_rows"] = int(reasons.str.contains("industry_weight|post_trade_industry", na=False).sum())
    out["risk_entry_not_tradable_rows"] = int(reasons.str.contains("entry_not_tradable", na=False).sum())
    out["risk_missing_bar_rows"] = int(reasons.str.contains("missing_bar", na=False).sum())
    return out


def _orders_summary(orders_df: pd.DataFrame, *, artifact_exists: bool) -> dict[str, object]:
    out = {
        "orders_artifact_missing": not bool(artifact_exists),
        "order_rows": 0,
        "blocked_orders": 0,
        "blocked_buy_orders": 0,
        "blocked_sell_orders": 0,
        "blocked_sell_current_weight_sum": 0.0,
        "blocked_sell_notional_sum": 0.0,
        "blocked_sell_codes": "",
    }
    if orders_df.empty:
        return out
    status = orders_df.get("status", pd.Series("", index=orders_df.index)).astype(str).str.lower()
    side = orders_df.get("side", pd.Series("", index=orders_df.index)).astype(str).str.upper()
    blocked = status.eq("blocked")
    buy = side.eq("BUY")
    sell = side.eq("SELL")
    blocked_sell = blocked & sell
    blocked_weight = pd.to_numeric(
        orders_df.get("blocked_current_weight", pd.Series(0.0, index=orders_df.index)),
        errors="coerce",
    ).fillna(0.0)
    blocked_notional = pd.to_numeric(
        orders_df.get("blocked_notional", pd.Series(0.0, index=orders_df.index)),
        errors="coerce",
    ).fillna(0.0)
    out["orders_artifact_missing"] = False
    out["order_rows"] = int(len(orders_df))
    out["blocked_orders"] = int(blocked.sum())
    out["blocked_buy_orders"] = int((blocked & buy).sum())
    out["blocked_sell_orders"] = int(blocked_sell.sum())
    out["blocked_sell_current_weight_sum"] = float(blocked_weight.loc[blocked_sell].sum())
    out["blocked_sell_notional_sum"] = float(blocked_notional.loc[blocked_sell].sum())
    if blocked_sell.any() and "code" in orders_df.columns:
        out["blocked_sell_codes"] = ",".join(orders_df.loc[blocked_sell, "code"].astype(str).tolist())
    return out


def _role_artifacts(channel: str, row: pd.Series) -> dict[str, object]:
    trade_date = row.get("trade_date", "")
    run_id = str(row.get("run_id", ""))
    orders_fp = _artifact_path(channel, "orders", trade_date, run_id)
    risk_fp = _artifact_path(channel, "risk_gates", trade_date, run_id)
    orders = _load_csv(orders_fp)
    risk = _load_csv(risk_fp)
    out: dict[str, object] = {
        "orders_file": str(orders_fp if orders_fp.exists() else ""),
        "risk_file": str(risk_fp if risk_fp.exists() else ""),
    }
    out.update(_orders_summary(orders, artifact_exists=orders_fp.exists()))
    out.update(_risk_summary(risk, artifact_exists=risk_fp.exists()))
    return out


def _day_label(row: dict[str, object], cash_drag_threshold: float) -> str:
    guard = bool(row.get("candidate_holiday_gap_guard", False))
    target_gap = _safe_float(row.get("target_weight_gap", 0.0))
    exit_worse = _safe_int(row.get("candidate_blocked_sell_orders", 0)) > _safe_int(
        row.get("main_blocked_sell_orders", 0)
    )
    if guard and target_gap <= -abs(float(cash_drag_threshold)) and exit_worse:
        return "holiday_gap_cash_drag+sell_trap"
    if guard and target_gap <= -abs(float(cash_drag_threshold)):
        return "holiday_gap_cash_drag"
    if guard and exit_worse:
        return "holiday_gap_sell_trap"
    if guard:
        return "holiday_gap_guard_day"
    return "no_guard_day"


def _detail_row(
    *,
    main_profile: str,
    candidate_profile: str,
    window: int,
    main_channel: str,
    candidate_channel: str,
    signal_key: str,
    main_row: pd.Series,
    candidate_row: pd.Series,
    cash_drag_threshold: float,
) -> dict[str, object]:
    main_ret = _safe_float(main_row.get("daily_return_pct", 0.0))
    cand_ret = _safe_float(candidate_row.get("daily_return_pct", 0.0))
    main_target = _safe_float(main_row.get("target_weight_sum", 0.0))
    cand_target = _safe_float(candidate_row.get("target_weight_sum", 0.0))
    guard = _safe_int(candidate_row.get("holiday_gap_guard", 0)) > 0
    reason = str(candidate_row.get("holiday_gap_reason", "") or "").strip()
    if not guard:
        reason = "no_guard"
    elif not reason or reason.lower() == "none":
        reason = "holiday_gap_guard"
    main_art = _role_artifacts(main_channel, main_row)
    cand_art = _role_artifacts(candidate_channel, candidate_row)
    row: dict[str, object] = {
        "candidate_profile": candidate_profile,
        "main_profile": main_profile,
        "window": int(window),
        "signal_date": _date_display(signal_key),
        "main_trade_date": _date_display(main_row.get("trade_date", "")),
        "candidate_trade_date": _date_display(candidate_row.get("trade_date", "")),
        "main_daily_return_pct": main_ret,
        "candidate_daily_return_pct": cand_ret,
        "relative_return_gap_pct": cand_ret - main_ret,
        "main_target_weight_sum": main_target,
        "candidate_target_weight_sum": cand_target,
        "target_weight_gap": cand_target - main_target,
        "cash_drag_proxy_pct": max(0.0, main_target - cand_target) * max(0.0, main_ret),
        "candidate_holiday_gap_guard": int(guard),
        "candidate_holiday_gap_reason": reason,
        "candidate_holiday_gap_target_scale": _safe_float(candidate_row.get("holiday_gap_target_scale", 1.0), 1.0),
        "candidate_holiday_gap_reason_override_applied": _safe_int(
            candidate_row.get("holiday_gap_reason_override_applied", 0)
        ),
        "candidate_holiday_gap_signal_trade_gap_days": _safe_int(
            candidate_row.get("holiday_gap_signal_trade_gap_days", 0)
        ),
        "candidate_holiday_gap_post_trade_gap_days": _safe_int(
            candidate_row.get("holiday_gap_post_trade_gap_days", 0)
        ),
        "main_broker_entry_not_tradable_orders": _safe_int(main_row.get("broker_entry_not_tradable_orders", 0)),
        "candidate_broker_entry_not_tradable_orders": _safe_int(
            candidate_row.get("broker_entry_not_tradable_orders", 0)
        ),
        "main_broker_exit_not_tradable_orders": _safe_int(main_row.get("broker_exit_not_tradable_orders", 0)),
        "candidate_broker_exit_not_tradable_orders": _safe_int(
            candidate_row.get("broker_exit_not_tradable_orders", 0)
        ),
        "exit_block_delta": _safe_int(candidate_row.get("broker_exit_not_tradable_orders", 0))
        - _safe_int(main_row.get("broker_exit_not_tradable_orders", 0)),
        "main_blocked_sell_current_weight": _safe_float(main_row.get("blocked_sell_current_weight", 0.0)),
        "candidate_blocked_sell_current_weight": _safe_float(candidate_row.get("blocked_sell_current_weight", 0.0)),
        "blocked_sell_weight_gap": _safe_float(candidate_row.get("blocked_sell_current_weight", 0.0))
        - _safe_float(main_row.get("blocked_sell_current_weight", 0.0)),
        "main_execution_state": str(main_row.get("execution_state", "")),
        "candidate_execution_state": str(candidate_row.get("execution_state", "")),
    }
    for prefix, artifact in [("main", main_art), ("candidate", cand_art)]:
        for key, value in artifact.items():
            row[f"{prefix}_{key}"] = value
    row["candidate_blocked_sell_orders"] = _safe_int(row.get("candidate_blocked_sell_orders", 0))
    row["main_blocked_sell_orders"] = _safe_int(row.get("main_blocked_sell_orders", 0))
    row["day_guard_label"] = _day_label(row, cash_drag_threshold)
    return row


def build_day_detail(
    summary_df: pd.DataFrame,
    *,
    main_profile: str,
    candidate_profiles: list[str],
    windows: list[int],
    cash_drag_threshold: float = 0.05,
) -> pd.DataFrame:
    best = _best_summary_rows(summary_df, windows)
    if best.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for window in windows:
        main_summary = _summary_row(best, main_profile, window)
        if main_summary is None:
            continue
        main_channel = str(main_summary.get("channel", ""))
        main_ledger = _load_ledger(main_channel)
        if main_ledger.empty:
            continue
        main_map = {
            str(r.get("signal_key", "")): r
            for _, r in main_ledger.iterrows()
            if str(r.get("signal_key", "")).strip()
        }
        for candidate in candidate_profiles:
            if candidate == main_profile:
                continue
            cand_summary = _summary_row(best, candidate, window)
            if cand_summary is None:
                continue
            cand_channel = str(cand_summary.get("channel", ""))
            cand_ledger = _load_ledger(cand_channel)
            if cand_ledger.empty:
                continue
            cand_map = {
                str(r.get("signal_key", "")): r
                for _, r in cand_ledger.iterrows()
                if str(r.get("signal_key", "")).strip()
            }
            for signal_key in sorted(set(main_map) & set(cand_map)):
                rows.append(
                    _detail_row(
                        main_profile=main_profile,
                        candidate_profile=candidate,
                        window=window,
                        main_channel=main_channel,
                        candidate_channel=cand_channel,
                        signal_key=signal_key,
                        main_row=main_map[signal_key],
                        candidate_row=cand_map[signal_key],
                        cash_drag_threshold=cash_drag_threshold,
                    )
                )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail
    lead_cols = [
        "candidate_profile",
        "window",
        "signal_date",
        "day_guard_label",
        "candidate_holiday_gap_guard",
        "candidate_holiday_gap_reason",
        "candidate_holiday_gap_reason_override_applied",
        "relative_return_gap_pct",
        "cash_drag_proxy_pct",
        "target_weight_gap",
        "main_daily_return_pct",
        "candidate_daily_return_pct",
        "main_target_weight_sum",
        "candidate_target_weight_sum",
        "candidate_broker_exit_not_tradable_orders",
        "main_broker_exit_not_tradable_orders",
        "candidate_blocked_sell_current_weight",
        "main_blocked_sell_current_weight",
    ]
    cols = [c for c in lead_cols if c in detail.columns] + [c for c in detail.columns if c not in lead_cols]
    return detail[cols]


def _metric_sum(df: pd.DataFrame, col: str) -> float:
    return float(pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())


def _metric_mean(df: pd.DataFrame, col: str) -> float:
    s = pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").dropna()
    return float(s.mean()) if len(s) else 0.0


def _metric_min(df: pd.DataFrame, col: str) -> float:
    s = pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").dropna()
    return float(s.min()) if len(s) else 0.0


def _metric_max(df: pd.DataFrame, col: str) -> float:
    s = pd.to_numeric(df.get(col, pd.Series(dtype=float)), errors="coerce").dropna()
    return float(s.max()) if len(s) else 0.0


def _group_metrics(df: pd.DataFrame) -> dict[str, object]:
    days = int(len(df))
    rel = pd.to_numeric(df.get("relative_return_gap_pct", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    cand_ret = pd.to_numeric(df.get("candidate_daily_return_pct", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    exit_blocks = _metric_sum(df, "candidate_broker_exit_not_tradable_orders")
    return {
        "day_count": days,
        "relative_return_gap_sum_pct": float(rel.sum()),
        "relative_return_gap_mean_pct": float(rel.mean()) if days else 0.0,
        "relative_return_gap_median_pct": float(rel.median()) if days else 0.0,
        "worst_relative_return_gap_pct": float(rel.min()) if days else 0.0,
        "candidate_underperform_days": int(rel.lt(0.0).sum()),
        "candidate_underperform_rate_pct": float(rel.lt(0.0).sum() / max(days, 1) * 100.0),
        "candidate_daily_return_sum_pct": float(cand_ret.sum()),
        "candidate_daily_return_mean_pct": float(cand_ret.mean()) if days else 0.0,
        "candidate_worst_daily_return_pct": float(cand_ret.min()) if days else 0.0,
        "candidate_negative_day_rate_pct": float(cand_ret.lt(0.0).sum() / max(days, 1) * 100.0),
        "target_weight_gap_mean": _metric_mean(df, "target_weight_gap"),
        "target_weight_gap_min": _metric_min(df, "target_weight_gap"),
        "cash_drag_proxy_sum_pct": _metric_sum(df, "cash_drag_proxy_pct"),
        "cash_drag_proxy_mean_pct": _metric_mean(df, "cash_drag_proxy_pct"),
        "candidate_exit_block_orders": float(exit_blocks),
        "main_exit_block_orders": _metric_sum(df, "main_broker_exit_not_tradable_orders"),
        "exit_block_delta_orders": _metric_sum(df, "exit_block_delta"),
        "candidate_exit_block_rate_pct": float(exit_blocks / max(days, 1) * 100.0),
        "candidate_blocked_sell_weight_max": _metric_max(df, "candidate_blocked_sell_current_weight"),
        "candidate_blocked_sell_weight_mean": _metric_mean(df, "candidate_blocked_sell_current_weight"),
        "risk_adv_hit_rows": _metric_sum(df, "candidate_risk_adv_hit_rows"),
        "risk_style_hit_rows": _metric_sum(df, "candidate_risk_style_hit_rows"),
        "risk_industry_hit_rows": _metric_sum(df, "candidate_risk_industry_hit_rows"),
        "risk_entry_not_tradable_rows": _metric_sum(df, "candidate_risk_entry_not_tradable_rows"),
        "missing_order_artifact_days": int(
            pd.Series(df.get("candidate_orders_artifact_missing", pd.Series(False, index=df.index))).astype(bool).sum()
        ),
        "missing_risk_artifact_days": int(
            pd.Series(df.get("candidate_risk_artifact_missing", pd.Series(False, index=df.index))).astype(bool).sum()
        ),
    }


def _reason_verdict(
    *,
    reason_metrics: dict[str, object],
    baseline_metrics: dict[str, object] | None,
    min_sample_days: int,
    cash_drag_threshold: float,
) -> str:
    if str(reason_metrics.get("candidate_holiday_gap_reason", "")) == "no_guard":
        return "baseline_no_guard"
    days = _safe_int(reason_metrics.get("day_count", 0))
    if days < int(min_sample_days):
        return "insufficient_sample"
    rel_sum = _safe_float(reason_metrics.get("relative_return_gap_sum_pct", 0.0))
    target_gap = _safe_float(reason_metrics.get("target_weight_gap_mean", 0.0))
    exit_rate = _safe_float(reason_metrics.get("candidate_exit_block_rate_pct", 0.0))
    blocked_max = _safe_float(reason_metrics.get("candidate_blocked_sell_weight_max", 0.0))
    worst = _safe_float(reason_metrics.get("candidate_worst_daily_return_pct", 0.0))
    baseline_exit_rate = _safe_float((baseline_metrics or {}).get("candidate_exit_block_rate_pct", exit_rate))
    baseline_blocked_max = _safe_float((baseline_metrics or {}).get("candidate_blocked_sell_weight_max", blocked_max))
    baseline_worst = _safe_float((baseline_metrics or {}).get("candidate_worst_daily_return_pct", worst))
    no_block_improvement = exit_rate >= baseline_exit_rate and blocked_max >= baseline_blocked_max
    downside_improved = worst >= baseline_worst
    if rel_sum < 0.0 and target_gap <= -abs(float(cash_drag_threshold)) and no_block_improvement:
        return "false_positive_cash_drag"
    if rel_sum >= 0.0 and exit_rate <= baseline_exit_rate and downside_improved:
        return "effective_protection"
    return "mixed_needs_review"


def build_reason_summary(
    detail: pd.DataFrame,
    *,
    min_sample_days: int = 3,
    cash_drag_threshold: float = 0.05,
) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    group_cols = ["candidate_profile", "main_profile", "window", "candidate_holiday_gap_reason"]
    for keys, group in detail.groupby(group_cols, dropna=False):
        row = dict(zip(group_cols, keys))
        row.update(_group_metrics(group))
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    verdicts: list[str] = []
    for idx, row in out.iterrows():
        peer = out[
            out["candidate_profile"].astype(str).eq(str(row["candidate_profile"]))
            & out["main_profile"].astype(str).eq(str(row["main_profile"]))
            & pd.to_numeric(out["window"], errors="coerce").fillna(0).astype(int).eq(_safe_int(row["window"]))
            & out["candidate_holiday_gap_reason"].astype(str).eq("no_guard")
        ]
        baseline = None if peer.empty else peer.iloc[0].to_dict()
        verdicts.append(
            _reason_verdict(
                reason_metrics=row.to_dict(),
                baseline_metrics=baseline,
                min_sample_days=min_sample_days,
                cash_drag_threshold=cash_drag_threshold,
            )
        )
    out["guard_reason_verdict"] = verdicts
    lead = [
        "candidate_profile",
        "window",
        "candidate_holiday_gap_reason",
        "guard_reason_verdict",
        "day_count",
        "relative_return_gap_sum_pct",
        "cash_drag_proxy_sum_pct",
        "target_weight_gap_mean",
        "candidate_exit_block_rate_pct",
        "candidate_blocked_sell_weight_max",
        "candidate_worst_daily_return_pct",
    ]
    cols = [c for c in lead if c in out.columns] + [c for c in out.columns if c not in lead]
    return out[cols]


def _summary_metric(summary_rows: pd.DataFrame, profile: str, window: int, col: str) -> object:
    row = _summary_row(summary_rows, profile, window)
    return "" if row is None else row.get(col, "")


def build_window_summary(detail: pd.DataFrame, summary_df: pd.DataFrame, *, main_profile: str) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    windows = sorted(pd.to_numeric(detail["window"], errors="coerce").fillna(0).astype(int).unique().tolist())
    best = _best_summary_rows(summary_df, windows)
    rows: list[dict[str, object]] = []
    for (candidate, window), group in detail.groupby(["candidate_profile", "window"], dropna=False):
        window_i = _safe_int(window)
        guard = group[pd.to_numeric(group["candidate_holiday_gap_guard"], errors="coerce").fillna(0).gt(0)].copy()
        no_guard = group[pd.to_numeric(group["candidate_holiday_gap_guard"], errors="coerce").fillna(0).le(0)].copy()
        guard_m = _group_metrics(guard)
        no_guard_m = _group_metrics(no_guard)
        row: dict[str, object] = {
            "candidate_profile": str(candidate),
            "main_profile": main_profile,
            "window": window_i,
            "aligned_days": int(len(group)),
            "guard_days": int(len(guard)),
            "non_guard_days": int(len(no_guard)),
            "guard_rate_pct": float(len(guard) / max(len(group), 1) * 100.0),
            "main_nav_return_pct": _summary_metric(best, main_profile, window_i, "nav_return_pct"),
            "candidate_nav_return_pct": _summary_metric(best, str(candidate), window_i, "nav_return_pct"),
            "main_max_drawdown_pct": _summary_metric(best, main_profile, window_i, "max_drawdown_pct"),
            "candidate_max_drawdown_pct": _summary_metric(best, str(candidate), window_i, "max_drawdown_pct"),
            "mdd_note": "Window MDD is actual P2 summary; guard/non-guard downside fields are daily proxies, not counterfactual MDD.",
        }
        for prefix, metrics in [("guard", guard_m), ("non_guard", no_guard_m)]:
            for key, value in metrics.items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    out = pd.DataFrame(rows)
    lead = [
        "candidate_profile",
        "window",
        "aligned_days",
        "guard_days",
        "non_guard_days",
        "guard_rate_pct",
        "main_nav_return_pct",
        "candidate_nav_return_pct",
        "main_max_drawdown_pct",
        "candidate_max_drawdown_pct",
        "guard_relative_return_gap_sum_pct",
        "guard_cash_drag_proxy_sum_pct",
        "guard_target_weight_gap_mean",
        "guard_candidate_exit_block_rate_pct",
        "guard_candidate_blocked_sell_weight_max",
        "guard_candidate_worst_daily_return_pct",
        "non_guard_candidate_worst_daily_return_pct",
    ]
    cols = [c for c in lead if c in out.columns] + [c for c in out.columns if c not in lead]
    return out[cols]


def build_holiday_gap_attribution(
    summary_df: pd.DataFrame,
    *,
    main_profile: str,
    candidate_profiles: list[str],
    windows: list[int],
    min_sample_days: int = 3,
    cash_drag_threshold: float = 0.05,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail = build_day_detail(
        summary_df,
        main_profile=main_profile,
        candidate_profiles=candidate_profiles,
        windows=windows,
        cash_drag_threshold=cash_drag_threshold,
    )
    reason = build_reason_summary(
        detail,
        min_sample_days=min_sample_days,
        cash_drag_threshold=cash_drag_threshold,
    )
    window = build_window_summary(detail, summary_df, main_profile=main_profile)
    return detail, reason, window


def main() -> int:
    parser = argparse.ArgumentParser(description="Attribute holiday-gap guard effects from P2 ledgers")
    parser.add_argument("--p2-summary", default="", help="P2 rolling summary CSV; default latest")
    parser.add_argument("--main-profile", default="quality_regime")
    parser.add_argument("--profiles", default="", help="Candidate profiles; default all profiles except main")
    parser.add_argument("--windows", default="60,90,120", help="Comma-separated P2 windows")
    parser.add_argument("--min-sample-days", type=int, default=3)
    parser.add_argument("--cash-drag-threshold", type=float, default=0.05)
    parser.add_argument("--write-latest", action="store_true")
    args = parser.parse_args()

    requested_profiles = _parse_list(args.profiles)
    summary_profiles = list(dict.fromkeys([str(args.main_profile)] + requested_profiles))
    summary_df, summary_path = _load_summary(args.p2_summary, summary_profiles if requested_profiles else [])
    windows = _parse_windows(args.windows) or [60, 90, 120]
    best = _best_summary_rows(summary_df, windows)
    if best.empty:
        print("未生成 holiday-gap guard attribution；P2 summary/window 为空")
        return 2
    if not requested_profiles:
        requested_profiles = [
            str(x)
            for x in best.get("profile", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()
            if str(x) != str(args.main_profile)
        ]
    detail, reason, window = build_holiday_gap_attribution(
        summary_df,
        main_profile=str(args.main_profile),
        candidate_profiles=requested_profiles,
        windows=windows,
        min_sample_days=max(1, int(args.min_sample_days)),
        cash_drag_threshold=abs(float(args.cash_drag_threshold)),
    )
    if detail.empty:
        print("未生成 holiday-gap guard attribution；请检查 profiles/windows/ledger")
        return 2
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_fp = BACKTEST_DIR / f"quant_p2_holiday_gap_guard_day_detail_{ts}.csv"
    reason_fp = BACKTEST_DIR / f"quant_p2_holiday_gap_guard_reason_summary_{ts}.csv"
    window_fp = BACKTEST_DIR / f"quant_p2_holiday_gap_guard_window_summary_{ts}.csv"
    meta_fp = BACKTEST_DIR / f"quant_p2_holiday_gap_guard_attribution_{ts}.json"
    detail.to_csv(detail_fp, index=False, encoding="utf-8-sig")
    reason.to_csv(reason_fp, index=False, encoding="utf-8-sig")
    window.to_csv(window_fp, index=False, encoding="utf-8-sig")
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "p2_summary": summary_path,
        "main_profile": str(args.main_profile),
        "candidate_profiles": requested_profiles,
        "windows": windows,
        "min_sample_days": max(1, int(args.min_sample_days)),
        "cash_drag_threshold": abs(float(args.cash_drag_threshold)),
        "day_detail": str(detail_fp),
        "reason_summary": str(reason_fp),
        "window_summary": str(window_fp),
        "note": "Guard/non-guard downside fields are attribution proxies, not counterfactual MDD.",
    }
    meta_fp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        detail.to_csv(BACKTEST_DIR / "quant_p2_holiday_gap_guard_day_detail_latest.csv", index=False, encoding="utf-8-sig")
        reason.to_csv(
            BACKTEST_DIR / "quant_p2_holiday_gap_guard_reason_summary_latest.csv",
            index=False,
            encoding="utf-8-sig",
        )
        window.to_csv(
            BACKTEST_DIR / "quant_p2_holiday_gap_guard_window_summary_latest.csv",
            index=False,
            encoding="utf-8-sig",
        )
        (BACKTEST_DIR / "quant_p2_holiday_gap_guard_attribution_latest.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    lead_cols = [
        "candidate_profile",
        "window",
        "candidate_holiday_gap_reason",
        "guard_reason_verdict",
        "day_count",
        "relative_return_gap_sum_pct",
        "cash_drag_proxy_sum_pct",
        "target_weight_gap_mean",
        "candidate_exit_block_rate_pct",
    ]
    print(reason[[c for c in lead_cols if c in reason.columns]].to_string(index=False))
    print(f"holiday_gap_guard_day_detail={detail_fp}")
    print(f"holiday_gap_guard_reason_summary={reason_fp}")
    print(f"holiday_gap_guard_window_summary={window_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
