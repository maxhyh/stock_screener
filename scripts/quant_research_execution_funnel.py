#!/usr/bin/env python3
"""Research-to-execution funnel diagnostics for quant profiles."""

from __future__ import annotations

import argparse
import json
import os
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
        out = float(value)
        if np.isfinite(out):
            return float(out)
    except Exception:
        pass
    return float(default)


def _parse_profiles(raw: str) -> list[str]:
    out: list[str] = []
    for token in str(raw or "").split(","):
        name = token.strip()
        if name:
            out.append(name)
    return list(dict.fromkeys(out))


def _concat_csv(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for fp in paths:
        if not fp.exists() or fp.stat().st_size == 0:
            continue
        try:
            df = pd.read_csv(fp)
        except Exception:
            continue
        if not df.empty:
            df["_source_file"] = str(fp)
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _max_drawdown_pct(values: list[float]) -> float:
    if not values:
        return 0.0
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0
    peak = np.maximum.accumulate(arr)
    dd = arr / np.maximum(peak, 1e-12) - 1.0
    return float(np.min(dd) * 100.0)


def _profile_patterns(profile: str, latest_only: bool = True) -> dict[str, list[Path]]:
    prefix = f"paper_replay_{profile}_"
    ledgers = sorted(EXEC_DIR.glob(f"{prefix}*ledger.csv"))
    if latest_only and ledgers:
        latest = max(ledgers, key=lambda p: p.stat().st_mtime)
        channel_prefix = latest.name.replace("_ledger.csv", "_")
        return {
            "ledger": [latest],
            "orders": sorted(EXEC_DIR.glob(f"{channel_prefix}orders_*.csv")),
            "risk": sorted(EXEC_DIR.glob(f"{channel_prefix}risk_gates_*.csv")),
        }
    return {
        "ledger": ledgers,
        "orders": sorted(EXEC_DIR.glob(f"{prefix}*orders_*.csv")),
        "risk": sorted(EXEC_DIR.glob(f"{prefix}*risk_gates_*.csv")),
    }


def _summarize_profile(profile: str, latest_only: bool = True) -> dict[str, object]:
    paths = _profile_patterns(profile, latest_only=latest_only)
    ledger = _concat_csv(paths["ledger"])
    orders = _concat_csv(paths["orders"])
    risk = _concat_csv(paths["risk"])

    row: dict[str, object] = {
        "profile": profile,
        "ledger_files": int(len(paths["ledger"])),
        "orders_files": int(len(paths["orders"])),
        "risk_files": int(len(paths["risk"])),
        "executed_days": 0,
        "nav_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "raw_ml_top_rows": 0,
        "quality_gate_rows": 0,
        "execution_overlay_rows": 0,
        "pretrade_kept_rows": 0,
        "pretrade_blocked_rows": 0,
        "p2_order_rows": 0,
        "p2_filled_order_rows": 0,
        "p2_partial_order_rows": 0,
        "p2_blocked_order_rows": 0,
        "p2_rejected_order_rows": 0,
        "p2_fill_rate_pct": 0.0,
        "adv_blocked_rows": 0,
        "industry_blocked_rows": 0,
        "blocked_target_weight": 0.0,
        "target_weight_sum_mean": 0.0,
        "unfilled_target_weight": 0.0,
        "impact_cost_bps_mean": 0.0,
        "max_participation_pct": 0.0,
        "mean_top_industry_weight_pct": 0.0,
        "worst_top_industry_weight_pct": 0.0,
        "post_trade_industry_limits_hit": 0,
    }

    if not ledger.empty:
        for col in [
            "nav_pre",
            "nav_post",
            "risk_input_count",
            "risk_kept_count",
            "risk_blocked_count",
            "target_weight_sum",
            "unfilled_target_weight",
            "impact_cost_bps_mean",
            "max_participation_pct",
        ]:
            ledger[col] = pd.to_numeric(ledger.get(col, 0.0), errors="coerce").fillna(0.0)
        nav_start = _safe_float(ledger["nav_pre"].iloc[0], 0.0)
        nav_end = _safe_float(ledger["nav_post"].iloc[-1], 0.0)
        row["executed_days"] = int(len(ledger))
        row["nav_return_pct"] = float((nav_end / nav_start - 1.0) * 100.0) if nav_start > 0 else 0.0
        row["max_drawdown_pct"] = _max_drawdown_pct([nav_start] + ledger["nav_post"].astype(float).tolist())
        row["raw_ml_top_rows"] = int(ledger["risk_input_count"].sum())
        row["quality_gate_rows"] = int(ledger["risk_input_count"].sum())
        row["execution_overlay_rows"] = int(ledger["risk_kept_count"].sum())
        row["pretrade_kept_rows"] = int(ledger["risk_kept_count"].sum())
        row["pretrade_blocked_rows"] = int(ledger["risk_blocked_count"].sum())
        row["target_weight_sum_mean"] = float(ledger["target_weight_sum"].mean()) if len(ledger) else 0.0
        row["unfilled_target_weight"] = float(ledger["unfilled_target_weight"].sum())
        row["impact_cost_bps_mean"] = float(ledger["impact_cost_bps_mean"].mean()) if len(ledger) else 0.0
        row["max_participation_pct"] = float(ledger["max_participation_pct"].max()) if len(ledger) else 0.0
        if "risk_post_trade_industry_limits_hit" in ledger.columns:
            row["post_trade_industry_limits_hit"] = int(pd.to_numeric(ledger["risk_post_trade_industry_limits_hit"], errors="coerce").fillna(0).sum())

    if not orders.empty:
        orders["status"] = orders.get("status", "").astype(str).str.lower()
        orders["target_weight"] = pd.to_numeric(orders.get("target_weight", 0.0), errors="coerce").fillna(0.0)
        total_orders = int(len(orders))
        filled = int((orders["status"] == "filled").sum())
        partial = int((orders["status"] == "partial").sum())
        blocked = int((orders["status"] == "blocked").sum())
        rejected = int((orders["status"] == "rejected").sum())
        row["p2_order_rows"] = total_orders
        row["p2_filled_order_rows"] = filled
        row["p2_partial_order_rows"] = partial
        row["p2_blocked_order_rows"] = blocked
        row["p2_rejected_order_rows"] = rejected
        row["p2_fill_rate_pct"] = float((filled + partial) / max(total_orders, 1) * 100.0)
        row["blocked_target_weight"] = float(orders.loc[orders["status"].isin(["blocked", "rejected"]), "target_weight"].sum())
        if "industry_weight_post" in orders.columns:
            ind_w = pd.to_numeric(orders["industry_weight_post"], errors="coerce").dropna()
            row["mean_top_industry_weight_pct"] = float(ind_w.mean() * 100.0) if not ind_w.empty else 0.0
            row["worst_top_industry_weight_pct"] = float(ind_w.max() * 100.0) if not ind_w.empty else 0.0

    if not risk.empty and "reasons" in risk.columns:
        reasons = risk["reasons"].astype(str)
        row["adv_blocked_rows"] = int(reasons.str.contains("adv_participation", na=False).sum())
        row["industry_blocked_rows"] = int(reasons.str.contains("industry_weight", na=False).sum())

    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-to-execution funnel diagnostics")
    parser.add_argument(
        "--profiles",
        type=str,
        default=(
            "quality_regime,quality_regime_candidate,quality_regime_candidate_v2,"
            "quality_regime_candidate_v3,quality_regime_candidate_v4_exec,"
            "quality_regime_candidate_v5_capacity_guard,quality_regime_candidate_v6_liquidity_guard,"
            "quality_regime_candidate_v7_industry_balance"
        ),
        help="Profile names, comma separated",
    )
    parser.add_argument("--write-latest", action="store_true", help="Write latest shortcut files")
    parser.add_argument("--include-all-runs", action="store_true", help="Aggregate all matching replay artifacts instead of only the latest channel")
    args = parser.parse_args()

    profiles = _parse_profiles(args.profiles)
    if not profiles:
        raise RuntimeError("No profiles provided")
    rows = [_summarize_profile(profile, latest_only=not bool(args.include_all_runs)) for profile in profiles]
    out = pd.DataFrame(rows)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = BACKTEST_DIR / f"quant_research_execution_funnel_{ts}.csv"
    json_path = BACKTEST_DIR / f"quant_research_execution_funnel_{ts}.json"
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profiles": profiles,
        "rows": out.to_dict(orient="records"),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.write_latest:
        out.to_csv(BACKTEST_DIR / "quant_research_execution_funnel_latest.csv", index=False, encoding="utf-8-sig")
        (BACKTEST_DIR / "quant_research_execution_funnel_latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(out.to_string(index=False))
    print(f"funnel_csv={csv_path}")
    print(f"funnel_json={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
