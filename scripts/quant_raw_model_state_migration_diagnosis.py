#!/usr/bin/env python3
"""Diagnose train/validation/test state migration for raw-model folds.

This script is diagnosis-only. It does not train a production model, create a
profile, or feed P2. It explains whether a failing raw-model fold is caused by
day-state/deployability expectations that worked in validation but became
optimistic in the held-out test window.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from scripts.quant_raw_model_instability_attribution import (  # noqa: E402
    _clean_with_extras,
    _knn_day_expectation,
    _training_day_deployability_state,
    add_exante_market_regime,
)
from scripts.quant_raw_model_walkforward_diagnosis import (  # noqa: E402
    BACKTEST_DIR,
    DATA_FILE,
    _iter_windows,
    _parse_feature_list,
    _parse_int_list,
    _safe_float,
    feature_drift_rows,
    load_model_metadata,
    load_raw_model_frame_cached,
)


DEPLOY_MIN_EXPECTED_RETURN_PCT = 0.0
DEPLOY_MIN_POSITIVE_RATE_PCT = 48.0
DEPLOY_MAX_LEFT_TAIL_RATE_PCT = 45.0
OUTCOME_COLS = {
    "deploy_day_all_mean_return_pct",
    "deploy_day_positive_rate_pct",
    "deploy_day_left_tail_rate_pct",
}


def _daily_regime_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "trade_date" not in df.columns:
        return pd.DataFrame(columns=["trade_date", "market_regime_exante"])
    work = df[["trade_date", "market_regime_exante"]].copy() if "market_regime_exante" in df.columns else df[["trade_date"]].copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    if "market_regime_exante" not in work.columns:
        work["market_regime_exante"] = "neutral"
    work["market_regime_exante"] = work["market_regime_exante"].fillna("neutral").astype(str)
    work = work[work["trade_date"].notna()].copy()
    if work.empty:
        return pd.DataFrame(columns=["trade_date", "market_regime_exante"])
    return (
        work.groupby("trade_date", as_index=False)["market_regime_exante"]
        .agg(lambda s: str(s.mode(dropna=True).iloc[0]) if not s.mode(dropna=True).empty else "neutral")
        .sort_values("trade_date")
        .reset_index(drop=True)
    )


def _state_with_regime(df: pd.DataFrame, *, label_col: str) -> pd.DataFrame:
    state = _training_day_deployability_state(df, label_col=label_col)
    regime = _daily_regime_frame(df)
    if state.empty:
        return state
    return state.merge(regime, on="trade_date", how="left").assign(
        market_regime_exante=lambda x: x["market_regime_exante"].fillna("neutral").astype(str)
    )


def _numeric_state_features(state: pd.DataFrame) -> list[str]:
    return [
        c
        for c in state.columns
        if c not in {"trade_date", "market_regime_exante", *OUTCOME_COLS}
        and pd.api.types.is_numeric_dtype(state[c])
    ]


def build_calibration_detail(
    fit_state: pd.DataFrame,
    target_state: pd.DataFrame,
    *,
    split: str,
    neighbor_days: int,
) -> pd.DataFrame:
    """Predict target split deployability from fit day-state neighbors."""

    cols = [
        "split",
        "trade_date",
        "market_regime_exante",
        "expected_return_pct",
        "actual_return_pct",
        "calibration_error_pct",
        "expected_positive_rate_pct",
        "actual_positive_rate_pct",
        "expected_left_tail_rate_pct",
        "actual_left_tail_rate_pct",
        "expected_deploy_signal",
        "actual_positive_day",
    ]
    if fit_state.empty or target_state.empty:
        return pd.DataFrame(columns=cols)
    exp_ret = _knn_day_expectation(
        fit_state,
        target_state,
        target_col="deploy_day_all_mean_return_pct",
        neighbor_days=int(neighbor_days),
    )
    exp_pos = _knn_day_expectation(
        fit_state,
        target_state,
        target_col="deploy_day_positive_rate_pct",
        neighbor_days=int(neighbor_days),
    )
    exp_tail = _knn_day_expectation(
        fit_state,
        target_state,
        target_col="deploy_day_left_tail_rate_pct",
        neighbor_days=int(neighbor_days),
    )
    if exp_ret.empty or exp_pos.empty or exp_tail.empty:
        return pd.DataFrame(columns=cols)
    out = target_state[["trade_date", "market_regime_exante", *OUTCOME_COLS]].copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.normalize()
    out["expected_return_pct"] = out["trade_date"].map(exp_ret).astype(float)
    out["expected_positive_rate_pct"] = out["trade_date"].map(exp_pos).astype(float)
    out["expected_left_tail_rate_pct"] = out["trade_date"].map(exp_tail).astype(float)
    out = out.rename(
        columns={
            "deploy_day_all_mean_return_pct": "actual_return_pct",
            "deploy_day_positive_rate_pct": "actual_positive_rate_pct",
            "deploy_day_left_tail_rate_pct": "actual_left_tail_rate_pct",
        }
    )
    out["calibration_error_pct"] = pd.to_numeric(out["actual_return_pct"], errors="coerce") - pd.to_numeric(
        out["expected_return_pct"],
        errors="coerce",
    )
    out["expected_deploy_signal"] = (
        pd.to_numeric(out["expected_return_pct"], errors="coerce").ge(DEPLOY_MIN_EXPECTED_RETURN_PCT)
        & pd.to_numeric(out["expected_positive_rate_pct"], errors="coerce").ge(DEPLOY_MIN_POSITIVE_RATE_PCT)
        & pd.to_numeric(out["expected_left_tail_rate_pct"], errors="coerce").le(DEPLOY_MAX_LEFT_TAIL_RATE_PCT)
    )
    out["actual_positive_day"] = pd.to_numeric(out["actual_return_pct"], errors="coerce").gt(0.0)
    out.insert(0, "split", str(split))
    return out.loc[:, cols].sort_values("trade_date").reset_index(drop=True)


def summarize_calibration(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for split, g in detail.groupby("split", sort=True):
        deploy = g["expected_deploy_signal"].astype(bool)
        deployed = g.loc[deploy].copy()
        rows.append(
            {
                "split": str(split),
                "days": int(len(g)),
                "expected_return_mean_pct": _safe_float(g["expected_return_pct"].mean(), 0.0),
                "actual_return_mean_pct": _safe_float(g["actual_return_pct"].mean(), 0.0),
                "calibration_error_mean_pct": _safe_float(g["calibration_error_pct"].mean(), 0.0),
                "calibration_error_p10_pct": _safe_float(g["calibration_error_pct"].quantile(0.10), 0.0),
                "expected_deploy_days": int(deploy.sum()),
                "expected_deploy_rate_pct": float(deploy.mean() * 100.0) if len(deploy) else 0.0,
                "deployed_actual_return_mean_pct": _safe_float(deployed["actual_return_pct"].mean(), 0.0) if not deployed.empty else 0.0,
                "deployed_actual_positive_day_rate_pct": float(deployed["actual_positive_day"].mean() * 100.0) if not deployed.empty else 0.0,
                "sign_accuracy_pct": float((g["expected_return_pct"].gt(0.0) == g["actual_return_pct"].gt(0.0)).mean() * 100.0)
                if len(g)
                else 0.0,
            }
        )
    return pd.DataFrame(rows)


def build_regime_summary(states: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for split, state in states.items():
        if state.empty:
            continue
        for regime, g in state.groupby("market_regime_exante", sort=True):
            rows.append(
                {
                    "split": str(split),
                    "market_regime_exante": str(regime),
                    "days": int(len(g)),
                    "day_mean_return_pct": _safe_float(g["deploy_day_all_mean_return_pct"].mean(), 0.0),
                    "positive_day_rate_pct": float(pd.to_numeric(g["deploy_day_all_mean_return_pct"], errors="coerce").gt(0.0).mean() * 100.0),
                    "stock_positive_rate_mean_pct": _safe_float(g["deploy_day_positive_rate_pct"].mean(), 0.0),
                    "left_tail_rate_mean_pct": _safe_float(g["deploy_day_left_tail_rate_pct"].mean(), 0.0),
                }
            )
    return pd.DataFrame(rows)


def build_state_drift(fit_state: pd.DataFrame, target_states: dict[str, pd.DataFrame], *, max_features: int) -> pd.DataFrame:
    features = _numeric_state_features(fit_state)
    rows = []
    for split, state in target_states.items():
        if state.empty or not features:
            continue
        drift = pd.DataFrame(feature_drift_rows(fit_state, state, features=features, max_features=min(int(max_features), len(features))))
        if drift.empty:
            continue
        drift.insert(0, "split", str(split))
        rows.extend(drift.to_dict(orient="records"))
    return pd.DataFrame(rows)


def build_state_migration_verdict(calibration_summary: pd.DataFrame, state_drift: pd.DataFrame, regime_summary: pd.DataFrame) -> dict[str, object]:
    test = calibration_summary[calibration_summary["split"].astype(str).eq("test")].head(1)
    valid = calibration_summary[calibration_summary["split"].astype(str).eq("valid")].head(1)
    test_error = _safe_float(test["calibration_error_mean_pct"].iloc[0], 0.0) if not test.empty else 0.0
    test_expected = _safe_float(test["expected_return_mean_pct"].iloc[0], 0.0) if not test.empty else 0.0
    test_actual = _safe_float(test["actual_return_mean_pct"].iloc[0], 0.0) if not test.empty else 0.0
    test_deploy_rate = _safe_float(test["expected_deploy_rate_pct"].iloc[0], 0.0) if not test.empty else 0.0
    valid_actual = _safe_float(valid["actual_return_mean_pct"].iloc[0], 0.0) if not valid.empty else 0.0
    test_drift = state_drift[state_drift["split"].astype(str).eq("test")].copy() if not state_drift.empty else pd.DataFrame()
    max_psi = _safe_float(test_drift["psi"].max(), 0.0) if not test_drift.empty and "psi" in test_drift.columns else 0.0
    max_std_diff = _safe_float(test_drift["std_mean_diff"].max(), 0.0) if not test_drift.empty and "std_mean_diff" in test_drift.columns else 0.0
    regime_bits = []
    if not regime_summary.empty:
        pivot = regime_summary[regime_summary["split"].astype(str).eq("test")].copy()
        for row in pivot.sort_values("day_mean_return_pct").head(3).itertuples(index=False):
            regime_bits.append(
                f"{getattr(row, 'market_regime_exante')}:{_safe_float(getattr(row, 'day_mean_return_pct', 0.0)):+.2f}"
            )
    if test_expected > 0.0 and test_error <= -1.0 and test_deploy_rate >= 70.0:
        verdict = "optimistic_deployability_miscalibration"
        action = "do not add another abstention head; explain why fit-neighbor expected returns are optimistic in this test fold"
    elif max_psi >= 0.30 or max_std_diff >= 1.0:
        verdict = "state_distribution_shift"
        action = "inspect top drifted day-state features and add state features or split-specific model treatment before more labels"
    elif valid_actual > 0.0 and test_actual <= 0.0:
        verdict = "validation_to_test_return_shift"
        action = "validation state does not represent the test fold; avoid validation-calibrated thresholds as promotion evidence"
    else:
        verdict = "mixed_needs_review"
        action = "review calibration detail, state drift, and regime rows before selecting the next raw-model experiment"
    return {
        "state_migration_verdict": verdict,
        "recommended_next_action": action,
        "test_expected_return_mean_pct": float(test_expected),
        "test_actual_return_mean_pct": float(test_actual),
        "test_calibration_error_mean_pct": float(test_error),
        "test_expected_deploy_rate_pct": float(test_deploy_rate),
        "valid_actual_return_mean_pct": float(valid_actual),
        "test_state_drift_max_psi": float(max_psi),
        "test_state_drift_max_std_mean_diff": float(max_std_diff),
        "worst_test_regimes": ";".join(regime_bits),
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diagnose raw-model fold state migration")
    p.add_argument("--data-file", default=str(DATA_FILE))
    p.add_argument("--model-file", default="")
    p.add_argument("--features", default="")
    p.add_argument("--horizon", type=int, default=10)
    p.add_argument("--folds", default="2")
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2026-04-14")
    p.add_argument("--train-months", type=int, default=24)
    p.add_argument("--test-months", type=int, default=4)
    p.add_argument("--step-months", type=int, default=4)
    p.add_argument("--valid-months", type=int, default=3)
    p.add_argument("--neighbor-days", type=int, default=20)
    p.add_argument("--max-drift-features", type=int, default=40)
    p.add_argument("--include-bj9", action="store_true")
    p.add_argument("--feature-cache-file", default="auto")
    p.add_argument("--no-feature-cache", action="store_true")
    p.add_argument("--label", default="h10_fold2_state_migration")
    p.add_argument("--write-latest", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    horizon = int(args.horizon)
    label_col = f"label_h{horizon}"
    focus_folds = set(_parse_int_list(args.folds, [2]))
    features = _parse_feature_list(args.features or None, args.model_file)
    frame, cache = load_raw_model_frame_cached(
        data_file=Path(args.data_file).resolve(),
        features=features,
        horizons=[horizon],
        start=str(args.start),
        end=str(args.end),
        exclude_bj9=not bool(args.include_bj9),
        cache_file="none" if args.no_feature_cache else str(args.feature_cache_file),
    )
    print(f"raw_model_frame_cache={'hit' if cache.get('cache_hit') else 'miss'}:{cache.get('cache_file', '')}")
    frame = add_exante_market_regime(frame)
    usable_features = [f for f in features if f in frame.columns]
    if not usable_features:
        raise RuntimeError("No usable features")
    windows = list(
        _iter_windows(
            pd.to_datetime(args.start).normalize(),
            pd.to_datetime(args.end).normalize(),
            train_months=max(1, int(args.train_months)),
            test_months=max(1, int(args.test_months)),
            step_months=max(1, int(args.step_months)),
            allow_partial_final_test=True,
        )
    )
    summary_rows = []
    calibration_parts = []
    drift_parts = []
    regime_parts = []
    verdict_rows = []
    model_meta = load_model_metadata(args.model_file)
    for win in windows:
        fold = int(win["fold"])
        if fold not in focus_folds:
            continue
        train_raw = frame[frame["trade_date"].between(win["train_start"], win["train_end"], inclusive="both")].copy()
        test_raw = frame[frame["trade_date"].between(win["test_start"], win["test_end"], inclusive="both")].copy()
        train_full = _clean_with_extras(train_raw, usable_features, label_col)
        test_full = _clean_with_extras(test_raw, usable_features, label_col)
        valid_cut = pd.Timestamp(win["train_end"]) - pd.DateOffset(months=max(1, int(args.valid_months))) + pd.Timedelta(days=1)
        fit_full = train_full[train_full["trade_date"].lt(valid_cut)].copy()
        valid_full = train_full[train_full["trade_date"].ge(valid_cut)].copy()
        if fit_full.empty or valid_full.empty:
            fit_full = train_full.copy()
            valid_full = pd.DataFrame(columns=train_full.columns)
        states = {
            "fit": _state_with_regime(fit_full, label_col=label_col),
            "valid": _state_with_regime(valid_full, label_col=label_col),
            "test": _state_with_regime(test_full, label_col=label_col),
        }
        detail = pd.concat(
            [
                build_calibration_detail(states["fit"], states["valid"], split="valid", neighbor_days=int(args.neighbor_days)),
                build_calibration_detail(states["fit"], states["test"], split="test", neighbor_days=int(args.neighbor_days)),
            ],
            ignore_index=True,
        )
        cal_summary = summarize_calibration(detail)
        drift = build_state_drift(states["fit"], {"valid": states["valid"], "test": states["test"]}, max_features=int(args.max_drift_features))
        regimes = build_regime_summary(states)
        verdict = build_state_migration_verdict(cal_summary, drift, regimes)
        for df in [detail, cal_summary, drift, regimes]:
            if not df.empty:
                df.insert(0, "fold", int(fold))
                df.insert(1, "horizon", int(horizon))
        summary_rows.extend(cal_summary.to_dict(orient="records") if not cal_summary.empty else [])
        calibration_parts.append(detail)
        drift_parts.append(drift)
        regime_parts.append(regimes)
        verdict_rows.append(
            {
                "fold": int(fold),
                "horizon": int(horizon),
                "test_start": pd.Timestamp(win["test_start"]).strftime("%Y-%m-%d"),
                "test_end": pd.Timestamp(win["test_end"]).strftime("%Y-%m-%d"),
                **verdict,
                **{f"source_model_{k}": v for k, v in model_meta.items()},
            }
        )
    summary = pd.DataFrame(summary_rows)
    calibration_detail = pd.concat([x for x in calibration_parts if not x.empty], ignore_index=True) if calibration_parts else pd.DataFrame()
    state_drift = pd.concat([x for x in drift_parts if not x.empty], ignore_index=True) if drift_parts else pd.DataFrame()
    regime_summary = pd.concat([x for x in regime_parts if not x.empty], ignore_index=True) if regime_parts else pd.DataFrame()
    verdict_df = pd.DataFrame(verdict_rows)
    if verdict_df.empty:
        raise RuntimeError("No fold state migration diagnostics produced")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = BACKTEST_DIR / f"quant_raw_model_state_migration_diagnosis_{str(args.label)}_{ts}"
    files = {
        "summary": str(base.with_name(base.name + "_summary.csv")),
        "calibration_detail": str(base.with_name(base.name + "_calibration_detail.csv")),
        "state_drift": str(base.with_name(base.name + "_state_drift.csv")),
        "regime_summary": str(base.with_name(base.name + "_regime_summary.csv")),
        "verdict": str(base.with_name(base.name + "_verdict.csv")),
        "metadata": str(base.with_name(base.name + ".json")),
    }
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(files["summary"], index=False, encoding="utf-8-sig")
    calibration_detail.to_csv(files["calibration_detail"], index=False, encoding="utf-8-sig")
    state_drift.to_csv(files["state_drift"], index=False, encoding="utf-8-sig")
    regime_summary.to_csv(files["regime_summary"], index=False, encoding="utf-8-sig")
    verdict_df.to_csv(files["verdict"], index=False, encoding="utf-8-sig")
    payload: dict[str, Any] = {
        "created_at": ts,
        "args": vars(args),
        "files": files,
        "frame_cache": cache,
    }
    Path(files["metadata"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest_prefix = BACKTEST_DIR / f"quant_raw_model_state_migration_diagnosis_latest_{str(args.label)}"
        summary.to_csv(latest_prefix.with_name(latest_prefix.name + "_summary.csv"), index=False, encoding="utf-8-sig")
        calibration_detail.to_csv(latest_prefix.with_name(latest_prefix.name + "_calibration_detail.csv"), index=False, encoding="utf-8-sig")
        state_drift.to_csv(latest_prefix.with_name(latest_prefix.name + "_state_drift.csv"), index=False, encoding="utf-8-sig")
        regime_summary.to_csv(latest_prefix.with_name(latest_prefix.name + "_regime_summary.csv"), index=False, encoding="utf-8-sig")
        verdict_df.to_csv(latest_prefix.with_name(latest_prefix.name + "_verdict.csv"), index=False, encoding="utf-8-sig")
    print(verdict_df.to_string(index=False))
    print(f"state_migration_verdict={files['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
