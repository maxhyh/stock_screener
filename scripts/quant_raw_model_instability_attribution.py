#!/usr/bin/env python3
"""Explain raw-model walk-forward fold instability.

This is a diagnosis-only script. It does not create profiles, does not save a
production model, and does not feed P2. It reruns selected failing folds with a
small set of controlled variants, then attributes failures to regime,
feature-drift, sample weighting, or objective choice.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from scripts.quant_raw_model_walkforward_diagnosis import (  # noqa: E402
    BACKTEST_DIR,
    DATA_FILE,
    DEFAULT_HORIZONS,
    _clean_feature_label_frame,
    _iter_windows,
    _parse_feature_list,
    _parse_int_list,
    _sample_rows,
    _safe_float,
    _safe_int,
    _slug,
    feature_drift_rows,
    load_model_metadata,
    load_raw_model_frame_cached,
    summarize_predictions,
)


DEFAULT_VARIANTS = [
    "baseline",
    "recency_weighted",
    "lambdarank",
    "regression_l1",
    "huber",
    "rank_normalized",
    "cross_sectional_only",
    "drop_high_drift",
    "regime_specific",
]
ENSEMBLE_VARIANTS = {
    "blend_rank_norm_cross_sectional": ["rank_normalized", "cross_sectional_only"],
    "blend_rank_norm_l1": ["rank_normalized", "regression_l1"],
    "blend_rank_norm_huber": ["rank_normalized", "huber"],
    "blend_rank_norm_cross_l1": ["rank_normalized", "cross_sectional_only", "regression_l1"],
}
RANK_NORM_PREFIX = "rank_norm_"
ENGINEERED_PREFIX = "engineered_"
CONTEXT_PREFIX = "context_"
DOWNSIDE_PREFIX = "downside_"
STATE_WEIGHTED_PREFIX = "state_weighted_"
MATCHED_STATE_PREFIX = "matched_state_"
STATE_SIMILARITY_WEIGHT_COL = "_state_similarity_weight"
TREATMENT_VARIANTS = {
    "abs_calibrated_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["absolute_return_blend"],
    },
    "day_veto_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["day_level_absolute_veto"],
    },
    "pos52w_beta_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["pos52w_beta_overlay"],
    },
    "conditional_pos52w_beta_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["conditional_pos52w_beta_overlay"],
    },
    "abs_pos52w_beta_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["absolute_return_blend", "pos52w_beta_overlay"],
    },
    "day_veto_conditional_pos52w_beta_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["day_level_absolute_veto", "conditional_pos52w_beta_overlay"],
    },
    "day_calibrated_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["day_state_absolute_calibration"],
    },
    "day_opportunity_pos52w_beta_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["day_state_pos52w_beta_opportunity_overlay"],
    },
    "day_calibrated_opportunity_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["day_state_absolute_calibration", "day_state_pos52w_beta_opportunity_overlay"],
    },
    "day_calibrated_context_rank_norm_regime_label_ranked": {
        "base_variant": "context_rank_norm_regime_label_ranked",
        "treatments": ["day_state_absolute_calibration"],
    },
    "day_calibrated_downside_context_rank_norm_regime_label_ranked": {
        "base_variant": "downside_context_rank_norm_regime_label_ranked",
        "treatments": ["day_state_absolute_calibration"],
    },
    "two_stage_hit_rank_norm_regime_label_ranked": {
        "base_variant": "rank_norm_regime_label_ranked",
        "treatments": ["positive_hit_blend"],
    },
    "engineered_two_stage_hit_rank_norm_regime_label_positive_ranked": {
        "base_variant": "engineered_rank_norm_regime_label_positive_ranked",
        "treatments": ["positive_hit_blend"],
    },
    "context_two_stage_hit_rank_norm_regime_label_tail_ranked": {
        "base_variant": "context_rank_norm_regime_label_tail_ranked",
        "treatments": ["positive_hit_blend"],
    },
    "context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_weak_positive_ranked",
        "treatments": ["positive_hit_blend"],
    },
    "day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_weak_positive_ranked",
        "treatments": ["positive_hit_blend", "day_state_absolute_calibration"],
    },
    "abstain_context_rank_norm_regime_label_weak_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_weak_positive_ranked",
        "treatments": ["day_state_deployability_abstention"],
    },
    "abstain_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_weak_positive_ranked",
        "treatments": ["positive_hit_blend", "day_state_deployability_abstention"],
    },
    "abstain_day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_weak_positive_ranked",
        "treatments": ["positive_hit_blend", "day_state_absolute_calibration", "day_state_deployability_abstention"],
    },
    "validated_abstain_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_weak_positive_ranked",
        "treatments": ["positive_hit_blend", "validated_day_state_deployability_abstention"],
    },
    "validated_abstain_day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_weak_positive_ranked",
        "treatments": ["positive_hit_blend", "day_state_absolute_calibration", "validated_day_state_deployability_abstention"],
    },
    "hit_abstain_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_weak_positive_ranked",
        "treatments": ["positive_hit_blend", "positive_hit_deployability_abstention"],
    },
    "context_two_stage_hit_rank_norm_regime_label_strict_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_strict_positive_ranked",
        "treatments": ["positive_hit_blend"],
    },
    "context_two_stage_hit_rank_norm_regime_label_margin_positive_ranked": {
        "base_variant": "context_rank_norm_regime_label_margin_positive_ranked",
        "treatments": ["positive_hit_blend"],
    },
}


def _strip_state_training_prefix(variant: str) -> tuple[str, list[str]]:
    """Strip diagnosis-only state-training wrappers from a variant name."""

    out = str(variant)
    wrappers: list[str] = []
    changed = True
    while changed:
        changed = False
        for prefix, name in (
            (STATE_WEIGHTED_PREFIX, "state_similarity_weighted_training"),
            (MATCHED_STATE_PREFIX, "matched_state_training"),
        ):
            if out.startswith(prefix):
                wrappers.append(name)
                out = out[len(prefix) :]
                changed = True
                break
    return out, wrappers


REGIME_EXTRA_COLS = [
    "market_ret_pct",
    "market_up_rate_pct",
    "market_regime_exante",
    "market_ret_20d",
    "market_up_rate_20d",
    "market_vol_20d",
]
DAY_STATE_RAW_FEATURES = [
    "pos_52w",
    "rs_20d",
    "mom_20",
    "bias",
    "atr_percent",
    "volatility_ratio",
    "vol_ratio",
    "pv_corr_20",
    "pct_chg",
    "amount",
    "vol",
    "market_ret_pct",
    "market_up_rate_pct",
    "gap_open_pct",
    "intraday_ret_pct",
    "range_pct",
    "close_location",
    "amount_log",
    "vol_log",
    "stock_minus_market_ret",
    "gap_minus_market_ret",
    "intraday_minus_market_ret",
    "market_stress_x_range",
    "market_stress_x_vol",
    "weak_market_mom20",
    "strong_market_pos52w",
]
DEFENSIVE_FEATURES = [
    "pos_52w",
    "pos_52w_cs",
    "rs_20d",
    "rs_20d_cs",
    "mom_20",
    "mom_20_cs",
    "bias",
    "bias_cs",
    "atr_percent",
    "atr_percent_cs",
    "volatility_ratio",
    "volatility_ratio_cs",
    "vol_ratio",
    "vol_ratio_cs",
]
ENGINEERED_FEATURE_BASES = [
    "mom20_minus_mom5",
    "rs20_minus_rs5",
    "pos52w_x_rs20",
    "pos52w_x_mom20",
    "pos52w_x_bias",
    "pv20_x_mom20",
    "vol_stress",
    "risk_adjusted_mom20",
    "mean_reversion_pressure",
]
CONTEXT_FEATURE_BASES = [
    "gap_open_pct",
    "intraday_ret_pct",
    "range_pct",
    "close_location",
    "amount_log",
    "vol_log",
    "stock_minus_market_ret",
    "gap_minus_market_ret",
    "intraday_minus_market_ret",
    "market_stress_x_range",
    "market_stress_x_vol",
    "weak_market_mom20",
    "strong_market_pos52w",
]


def _parse_str_list(raw: str | None, default: list[str]) -> list[str]:
    if raw is None:
        return list(default)
    vals = [x.strip() for x in str(raw).split(",") if x.strip()]
    return list(dict.fromkeys(vals)) or list(default)


def _alpha_gate_pass(row: dict[str, object]) -> bool:
    return bool(
        _safe_float(row.get("top_mean_return_pct", 0.0)) > 0.0
        and _safe_float(row.get("top_minus_all_pct", 0.0)) > 0.0
        and _safe_float(row.get("top_minus_bottom_pct", 0.0)) > 0.0
        and _safe_float(row.get("rank_ic_mean", 0.0)) > 0.0
    )


def _failure_label(row: dict[str, object]) -> str:
    reasons = []
    if _safe_float(row.get("top_mean_return_pct", 0.0)) <= 0.0:
        reasons.append("top_mean_non_positive")
    if _safe_float(row.get("top_minus_all_pct", 0.0)) <= 0.0:
        reasons.append("top_not_above_pool")
    if _safe_float(row.get("top_minus_bottom_pct", 0.0)) <= 0.0:
        reasons.append("top_not_above_bottom")
    if _safe_float(row.get("rank_ic_mean", 0.0)) <= 0.0:
        reasons.append("rank_ic_non_positive")
    return "+".join(reasons) if reasons else "pass"


def _regime_label(x: float) -> str:
    if x <= -1.0:
        return "broad_down"
    if x < 0.0:
        return "mild_down"
    if x < 1.0:
        return "mild_up"
    return "broad_up"


def _exante_market_regime(row: pd.Series) -> str:
    ret20 = _safe_float(row.get("market_ret_20d", 0.0), 0.0)
    up20 = _safe_float(row.get("market_up_rate_20d", 50.0), 50.0)
    vol20 = _safe_float(row.get("market_vol_20d", 0.0), 0.0)
    if ret20 <= -0.10 and up20 < 48.0:
        return "risk_off"
    if ret20 >= 0.10 and up20 > 52.0:
        return "risk_on"
    if vol20 >= 1.50 and up20 < 50.0:
        return "high_vol_down"
    return "neutral"


def _safe_div(num: pd.Series, den: pd.Series, default: float = 0.0) -> pd.Series:
    out = pd.to_numeric(num, errors="coerce") / pd.to_numeric(den, errors="coerce").replace(0.0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan).fillna(float(default))


def add_exante_market_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Add signal-date market regime from same-day and trailing market data.

    The regime uses only information available by signal-date close. It is
    therefore suitable for diagnostic prediction variants. Ex-post label regimes
    remain separate and are only used for attribution tables.
    """

    if df.empty or "trade_date" not in df.columns:
        return df.copy()
    out = df.copy()
    pct = pd.to_numeric(out.get("pct_chg", pd.Series(index=out.index, dtype=float)), errors="coerce")
    out["_pct_chg_tmp"] = pct
    daily = (
        out.groupby("trade_date", sort=True)
        .agg(
            market_ret_pct=("_pct_chg_tmp", "mean"),
            market_up_rate_pct=("_pct_chg_tmp", lambda s: float((pd.to_numeric(s, errors="coerce") > 0.0).mean() * 100.0)),
        )
        .sort_index()
    )
    daily["market_ret_20d"] = daily["market_ret_pct"].rolling(20, min_periods=5).mean()
    daily["market_up_rate_20d"] = daily["market_up_rate_pct"].rolling(20, min_periods=5).mean()
    daily["market_vol_20d"] = daily["market_ret_pct"].rolling(20, min_periods=5).std().fillna(0.0)
    daily["market_regime_exante"] = daily.apply(_exante_market_regime, axis=1)
    out = out.drop(columns=["_pct_chg_tmp"], errors="ignore").merge(
        daily[REGIME_EXTRA_COLS],
        left_on="trade_date",
        right_index=True,
        how="left",
    )
    out["market_regime_exante"] = out["market_regime_exante"].fillna("neutral")
    return out


def _clean_with_extras(df: pd.DataFrame, features: list[str], label_col: str) -> pd.DataFrame:
    raw_cols = ["open", "high", "low", "close", "vol", "amount", "pct_chg"]
    cols = ["trade_date", "ts_code", *raw_cols, *REGIME_EXTRA_COLS, *features, label_col]
    work = df.loc[:, [c for c in cols if c in df.columns]].copy()
    numeric_regime_cols = [c for c in REGIME_EXTRA_COLS if c != "market_regime_exante"]
    for col in [*features, label_col, *raw_cols, *numeric_regime_cols]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    if "market_regime_exante" in work.columns:
        work["market_regime_exante"] = work["market_regime_exante"].fillna("neutral").astype(str)
    need = [c for c in features + [label_col] if c in work.columns]
    return work.dropna(subset=need).reset_index(drop=True)


def _recency_weights(train_df: pd.DataFrame, *, half_life_days: float = 240.0) -> np.ndarray:
    dates = pd.to_datetime(train_df["trade_date"], errors="coerce")
    max_date = dates.max()
    age = (max_date - dates).dt.days.fillna(0).clip(lower=0).to_numpy(dtype=float)
    w = np.exp(-age / max(float(half_life_days), 1.0))
    return w / max(float(np.mean(w)), 1e-12)


def _downside_aware_weights(train_df: pd.DataFrame, label_col: str, *, day_col: str = "trade_date") -> np.ndarray:
    """Emphasize weak-day survivor selection without changing the label target."""

    if train_df.empty or label_col not in train_df.columns:
        return np.ones(len(train_df), dtype=float)
    vals = pd.to_numeric(train_df[label_col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    if vals.notna().sum() == 0:
        return np.ones(len(train_df), dtype=float)
    vals = vals.fillna(float(vals.median()))
    if day_col in train_df.columns:
        dates = pd.to_datetime(train_df[day_col], errors="coerce").fillna(pd.Timestamp("1970-01-01"))
    else:
        dates = pd.Series(np.arange(len(train_df)), index=train_df.index)
    by_day = vals.groupby(dates, sort=False)
    day_mean = by_day.transform("mean").fillna(float(vals.mean()))
    day_std = by_day.transform("std").replace(0.0, np.nan).fillna(float(vals.std(ddof=1) or 1.0))
    daily_rank = by_day.rank(pct=True).replace([np.inf, -np.inf], np.nan).fillna(0.5)
    weak_day = day_mean.lt(0.0)
    severe_loss = vals.lt(-1.0) | vals.lt(day_mean - 0.50 * day_std.abs())
    resilient_winner = weak_day & vals.gt(0.0)
    weak_top_rank = weak_day & daily_rank.ge(0.80)
    q90 = float(vals.abs().quantile(0.90))
    magnitude = (vals.abs() / max(q90, 1e-9)).clip(lower=0.0, upper=1.0)
    weights = (
        1.0
        + 0.75 * weak_day.astype(float)
        + 0.75 * resilient_winner.astype(float)
        + 0.50 * severe_loss.astype(float)
        + 0.25 * weak_top_rank.astype(float)
        + 0.25 * magnitude
    )
    weights = weights.clip(lower=0.50, upper=4.00).to_numpy(dtype=float)
    return weights / max(float(np.mean(weights)), 1e-12)


def _state_feature_columns(train_state: pd.DataFrame, reference_state: pd.DataFrame) -> list[str]:
    return [
        c
        for c in train_state.columns
        if c != "trade_date"
        and c in reference_state.columns
        and pd.api.types.is_numeric_dtype(train_state[c])
        and pd.api.types.is_numeric_dtype(reference_state[c])
    ]


def _state_similarity_day_weights(
    train_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    *,
    neighbor_days: int = 20,
) -> tuple[pd.Series, str]:
    """Weight training signal dates by similarity to a reference state set.

    This is diagnosis-only and intentionally transductive when the reference is
    the held-out test window: it uses only signal-date state features, never
    held-out labels, to ask whether historical states similar to the test window
    contain a learnable alpha pattern.
    """

    train_state = _day_state_frame(train_df)
    reference_state = _day_state_frame(reference_df)
    if train_state.empty or reference_state.empty:
        return pd.Series(dtype=float), "state_similarity=no_day_state"
    features = _state_feature_columns(train_state, reference_state)
    if not features:
        return pd.Series(dtype=float), "state_similarity=no_shared_state_features"
    train = train_state.dropna(subset=["trade_date"]).copy()
    ref = reference_state.dropna(subset=["trade_date"]).copy()
    if train.empty or ref.empty:
        return pd.Series(dtype=float), "state_similarity=empty_state"
    for col in features:
        train[col] = pd.to_numeric(train[col], errors="coerce")
        ref[col] = pd.to_numeric(ref[col], errors="coerce")
    mean = train[features].mean()
    std = train[features].std(ddof=1).replace(0.0, np.nan).fillna(1.0)
    train_x = ((train[features] - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=float)
    ref_x = ((ref[features] - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=float)
    k = max(1, min(int(neighbor_days), len(ref_x)))
    distances: list[float] = []
    for row in train_x:
        d = np.linalg.norm(ref_x - row, axis=1)
        distances.append(float(np.sort(d)[:k].mean()))
    dist = np.asarray(distances, dtype=float)
    scale = float(np.nanmedian(dist[np.isfinite(dist)])) if np.isfinite(dist).any() else 1.0
    if scale <= 1e-9:
        raw = np.ones(len(dist), dtype=float)
    else:
        raw = np.exp(-dist / scale)
    weights = pd.Series(raw, index=pd.to_datetime(train["trade_date"], errors="coerce").dt.normalize(), dtype=float)
    weights = weights.replace([np.inf, -np.inf], np.nan).fillna(float(weights.median() if len(weights) else 1.0))
    weights = weights.clip(lower=0.05, upper=1.0)
    weights = weights / max(float(weights.mean()), 1e-12)
    weights = weights.clip(lower=0.25, upper=4.0)
    weights = weights / max(float(weights.mean()), 1e-12)
    top_features = ",".join(features[:8])
    return (
        weights,
        "state_similarity="
        f"train_days={len(train)},reference_days={len(ref)},features={len(features)},"
        f"k={k},weight_min={float(weights.min()):.2f},weight_max={float(weights.max()):.2f},"
        f"top_features={top_features}",
    )


def _attach_state_similarity_weights(
    train_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    *,
    neighbor_days: int = 20,
) -> tuple[pd.DataFrame, str]:
    out = train_df.copy()
    day_weights, note = _state_similarity_day_weights(out, reference_df, neighbor_days=int(neighbor_days))
    if day_weights.empty:
        out[STATE_SIMILARITY_WEIGHT_COL] = 1.0
        return out, note + ";fallback_weight=1.0"
    day = pd.to_datetime(out["trade_date"], errors="coerce").dt.normalize()
    out[STATE_SIMILARITY_WEIGHT_COL] = day.map(day_weights).fillna(1.0).astype(float).to_numpy(dtype=float)
    return out, note


def _matched_state_training_frame(
    train_df: pd.DataFrame,
    reference_df: pd.DataFrame,
    *,
    neighbor_days: int = 20,
    keep_day_rate: float = 0.45,
    min_days: int = 60,
) -> tuple[pd.DataFrame, str]:
    day_weights, note = _state_similarity_day_weights(train_df, reference_df, neighbor_days=int(neighbor_days))
    if day_weights.empty:
        return train_df.copy(), "matched_state_training=" + note + ";fallback_all_train"
    unique_days = int(pd.to_datetime(train_df["trade_date"], errors="coerce").dt.normalize().nunique())
    keep_n = max(int(min_days), int(np.ceil(unique_days * min(max(float(keep_day_rate), 0.05), 1.0))))
    keep_n = max(1, min(unique_days, keep_n))
    keep_days = set(day_weights.sort_values(ascending=False).head(keep_n).index)
    day = pd.to_datetime(train_df["trade_date"], errors="coerce").dt.normalize()
    out = train_df.loc[day.isin(keep_days)].copy()
    if out.empty:
        return train_df.copy(), "matched_state_training=empty_after_match;fallback_all_train"
    return (
        out.reset_index(drop=True),
        "matched_state_training="
        f"kept_days={keep_n}/{unique_days},kept_rows={len(out)}/{len(train_df)},"
        f"keep_day_rate={float(keep_day_rate):.2f};{note}",
    )


def _make_rank_labels(df: pd.DataFrame, label_col: str, n_bins: int = 5) -> pd.Series:
    def one(g: pd.Series) -> pd.Series:
        if len(g) < n_bins or g.nunique(dropna=True) < 2:
            return pd.Series(np.zeros(len(g), dtype=int), index=g.index)
        return pd.qcut(g, q=n_bins, labels=False, duplicates="drop").fillna(0).astype(int)

    return df.groupby("trade_date", sort=False)[label_col].transform(one)


def _group_sizes(df: pd.DataFrame) -> np.ndarray:
    return df.groupby("trade_date", sort=False).size().to_numpy(dtype=int)


def _rank_normalize_feature_frame(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in features:
        if col not in out.columns:
            continue
        vals = pd.to_numeric(out[col], errors="coerce")
        out[col] = vals.groupby(out["trade_date"], sort=False).rank(pct=True).fillna(0.5)
    return out


def _objective_params_for_variant(variant: str) -> tuple[str, str]:
    variant = _base_model_variant(variant)
    if variant in (
        "label_demeaned",
        "label_ranked",
        "label_positive_ranked",
        "label_tail_ranked",
        "label_weak_positive_ranked",
        "label_state_weak_positive_ranked",
        "label_strict_positive_ranked",
        "label_margin_positive_ranked",
        "regime_label_demeaned",
        "regime_label_ranked",
        "regime_label_positive_ranked",
        "regime_label_tail_ranked",
        "regime_label_weak_positive_ranked",
        "regime_label_state_weak_positive_ranked",
        "regime_label_strict_positive_ranked",
        "regime_label_margin_positive_ranked",
    ):
        return "regression", "rmse"
    if variant == "regression_l1":
        return "regression_l1", "l1"
    if variant == "huber":
        return "huber", "huber"
    return "regression", "rmse"


def _is_ensemble_variant(variant: str) -> bool:
    return str(variant) in ENSEMBLE_VARIANTS


def _treatment_spec(variant: str) -> dict[str, object]:
    raw = str(variant)
    if raw in TREATMENT_VARIANTS:
        return dict(TREATMENT_VARIANTS.get(raw, {}))
    stripped, _ = _strip_state_training_prefix(raw)
    if stripped != raw:
        return dict(TREATMENT_VARIANTS.get(stripped, {}))
    return {}


def _canonical_model_variant(variant: str) -> str:
    spec = _treatment_spec(str(variant))
    return str(spec.get("base_variant", variant))


def _variant_treatments(variant: str) -> list[str]:
    spec = _treatment_spec(str(variant))
    raw = spec.get("treatments", [])
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _uses_rank_normalization(variant: str) -> bool:
    variant = str(variant)
    stripped, _ = _strip_state_training_prefix(variant)
    if stripped != variant:
        return _uses_rank_normalization(stripped)
    canonical = _canonical_model_variant(variant)
    if canonical != variant:
        return _uses_rank_normalization(canonical)
    if variant.startswith(DOWNSIDE_PREFIX):
        return _uses_rank_normalization(variant[len(DOWNSIDE_PREFIX) :])
    if variant.startswith(ENGINEERED_PREFIX):
        return _uses_rank_normalization(variant[len(ENGINEERED_PREFIX) :])
    if variant.startswith(CONTEXT_PREFIX):
        return _uses_rank_normalization(variant[len(CONTEXT_PREFIX) :])
    return variant == "rank_normalized" or variant.startswith(RANK_NORM_PREFIX)


def _uses_engineered_features(variant: str) -> bool:
    variant = str(variant)
    stripped, _ = _strip_state_training_prefix(variant)
    if stripped != variant:
        return _uses_engineered_features(stripped)
    canonical = _canonical_model_variant(variant)
    if canonical != variant:
        return _uses_engineered_features(canonical)
    if variant.startswith(DOWNSIDE_PREFIX):
        return _uses_engineered_features(variant[len(DOWNSIDE_PREFIX) :])
    return variant.startswith(ENGINEERED_PREFIX)


def _uses_context_features(variant: str) -> bool:
    variant = str(variant)
    stripped, _ = _strip_state_training_prefix(variant)
    if stripped != variant:
        return _uses_context_features(stripped)
    canonical = _canonical_model_variant(variant)
    if canonical != variant:
        return _uses_context_features(canonical)
    if variant.startswith(DOWNSIDE_PREFIX):
        return _uses_context_features(variant[len(DOWNSIDE_PREFIX) :])
    return variant.startswith(CONTEXT_PREFIX)


def _uses_downside_weights(variant: str) -> bool:
    variant = str(variant)
    stripped, _ = _strip_state_training_prefix(variant)
    if stripped != variant:
        return _uses_downside_weights(stripped)
    canonical = _canonical_model_variant(variant)
    if canonical != variant:
        return _uses_downside_weights(canonical)
    if variant.startswith(DOWNSIDE_PREFIX):
        return True
    if variant.startswith(ENGINEERED_PREFIX):
        return _uses_downside_weights(variant[len(ENGINEERED_PREFIX) :])
    if variant.startswith(CONTEXT_PREFIX):
        return _uses_downside_weights(variant[len(CONTEXT_PREFIX) :])
    return False


def _uses_state_similarity_weights(variant: str) -> bool:
    _, wrappers = _strip_state_training_prefix(str(variant))
    return "state_similarity_weighted_training" in wrappers


def _uses_matched_state_training(variant: str) -> bool:
    _, wrappers = _strip_state_training_prefix(str(variant))
    return "matched_state_training" in wrappers


def _base_model_variant(variant: str) -> str:
    variant = str(variant)
    stripped, _ = _strip_state_training_prefix(variant)
    if stripped != variant:
        return _base_model_variant(stripped)
    canonical = _canonical_model_variant(variant)
    if canonical != variant:
        return _base_model_variant(canonical)
    if variant.startswith(DOWNSIDE_PREFIX):
        return _base_model_variant(variant[len(DOWNSIDE_PREFIX) :])
    if variant.startswith(ENGINEERED_PREFIX):
        return _base_model_variant(variant[len(ENGINEERED_PREFIX) :])
    if variant.startswith(CONTEXT_PREFIX):
        return _base_model_variant(variant[len(CONTEXT_PREFIX) :])
    if variant == "rank_normalized":
        return "baseline"
    if variant.startswith(RANK_NORM_PREFIX):
        base = variant[len(RANK_NORM_PREFIX) :]
        return "baseline" if base in ("", "baseline") else base
    return variant


def _variant_feature_mode(variant: str) -> str:
    if _uses_context_features(variant):
        return "context"
    if _uses_engineered_features(variant):
        return "engineered"
    base = _base_model_variant(variant)
    if base == "cross_sectional_only":
        return "cross_sectional_only"
    if base == "drop_high_drift":
        return "drop_high_drift"
    return "all"


def _variant_label_mode(variant: str) -> str:
    base = _base_model_variant(variant)
    if base in ("label_demeaned", "regime_label_demeaned"):
        return "daily_demeaned"
    if base in ("label_ranked", "regime_label_ranked"):
        return "daily_ranked"
    if base in ("label_positive_ranked", "regime_label_positive_ranked"):
        return "positive_daily_ranked"
    if base in ("label_tail_ranked", "regime_label_tail_ranked"):
        return "tail_positive_daily_ranked"
    if base in ("label_weak_positive_ranked", "regime_label_weak_positive_ranked"):
        return "weak_positive_daily_ranked"
    if base in ("label_state_weak_positive_ranked", "regime_label_state_weak_positive_ranked"):
        return "state_weak_positive_daily_ranked"
    if base in ("label_strict_positive_ranked", "regime_label_strict_positive_ranked"):
        return "strict_positive_daily_ranked"
    if base in ("label_margin_positive_ranked", "regime_label_margin_positive_ranked"):
        return "margin_positive_daily_ranked"
    return "raw"


def _is_regime_specific_model(base_variant: str) -> bool:
    return str(base_variant) in (
        "regime_specific",
        "regime_label_demeaned",
        "regime_label_ranked",
        "regime_label_positive_ranked",
        "regime_label_tail_ranked",
        "regime_label_weak_positive_ranked",
        "regime_label_state_weak_positive_ranked",
        "regime_label_strict_positive_ranked",
        "regime_label_margin_positive_ranked",
    )


def _lgb_train_variant_for_base(base_variant: str) -> str:
    if str(base_variant) in (
        "label_demeaned",
        "label_ranked",
        "label_positive_ranked",
        "label_strict_positive_ranked",
        "label_margin_positive_ranked",
        "label_state_weak_positive_ranked",
        "regime_label_demeaned",
        "regime_label_ranked",
        "regime_label_positive_ranked",
        "regime_label_tail_ranked",
        "regime_label_weak_positive_ranked",
        "regime_label_state_weak_positive_ranked",
        "regime_label_strict_positive_ranked",
        "regime_label_margin_positive_ranked",
    ):
        return "baseline"
    return str(base_variant)


def _state_weak_day_mask(df: pd.DataFrame) -> pd.Series:
    """Identify weak signal-date states from ex-ante features only."""

    if df.empty or "trade_date" not in df.columns:
        return pd.Series(False, index=df.index)
    day = pd.to_datetime(df["trade_date"], errors="coerce").dt.normalize()
    state = pd.DataFrame({"trade_date": day})
    if "market_vol_20d" in df.columns:
        state["market_vol_20d"] = pd.to_numeric(df["market_vol_20d"], errors="coerce")
    if "market_up_rate_20d" in df.columns:
        state["market_up_rate_20d"] = pd.to_numeric(df["market_up_rate_20d"], errors="coerce")
    if "pos_52w" in df.columns:
        state["pos_52w_day_mean"] = pd.to_numeric(df["pos_52w"], errors="coerce").groupby(day, sort=False).transform("mean")
    if "volatility_ratio" in df.columns:
        state["volatility_ratio_day_std"] = pd.to_numeric(df["volatility_ratio"], errors="coerce").groupby(day, sort=False).transform("std")
    if "amount" in df.columns:
        state["amount_day_std"] = pd.to_numeric(df["amount"], errors="coerce").groupby(day, sort=False).transform("std")
    if "pv_corr_20" in df.columns:
        state["pv_corr_20_day_mean"] = pd.to_numeric(df["pv_corr_20"], errors="coerce").groupby(day, sort=False).transform("mean")
    score = pd.Series(0.0, index=df.index, dtype=float)
    if "market_vol_20d" in state.columns and state["market_vol_20d"].notna().any():
        score += state["market_vol_20d"].ge(float(state["market_vol_20d"].quantile(0.70))).astype(float)
    if "market_up_rate_20d" in state.columns and state["market_up_rate_20d"].notna().any():
        score += state["market_up_rate_20d"].le(float(state["market_up_rate_20d"].quantile(0.35))).astype(float)
    if "pos_52w_day_mean" in state.columns and state["pos_52w_day_mean"].notna().any():
        score += state["pos_52w_day_mean"].le(float(state["pos_52w_day_mean"].quantile(0.35))).astype(float)
    if "volatility_ratio_day_std" in state.columns and state["volatility_ratio_day_std"].notna().any():
        score += state["volatility_ratio_day_std"].ge(float(state["volatility_ratio_day_std"].quantile(0.70))).astype(float)
    if "amount_day_std" in state.columns and state["amount_day_std"].notna().any():
        score += state["amount_day_std"].ge(float(state["amount_day_std"].quantile(0.70))).astype(float)
    if "pv_corr_20_day_mean" in state.columns and state["pv_corr_20_day_mean"].notna().any():
        score += state["pv_corr_20_day_mean"].le(float(state["pv_corr_20_day_mean"].quantile(0.35))).astype(float)
    return score.ge(2.0).fillna(False)


def _make_training_label(df: pd.DataFrame, label_col: str, mode: str) -> pd.Series:
    vals = pd.to_numeric(df[label_col], errors="coerce")
    mode = str(mode or "raw")
    if mode == "daily_demeaned":
        mean = vals.groupby(df["trade_date"], sort=False).transform("mean")
        return (vals - mean).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if mode == "daily_ranked":
        ranked = vals.groupby(df["trade_date"], sort=False).rank(pct=True)
        return ranked.replace([np.inf, -np.inf], np.nan).fillna(0.5)
    if mode == "positive_daily_ranked":
        ranked = vals.groupby(df["trade_date"], sort=False).rank(pct=True)
        positive = vals.gt(0.0).astype(float)
        return (0.65 * ranked + 0.35 * positive).replace([np.inf, -np.inf], np.nan).fillna(0.5)
    if mode == "tail_positive_daily_ranked":
        ranked = vals.groupby(df["trade_date"], sort=False).rank(pct=True)
        positive = vals.gt(0.0).astype(float)
        left_tail = ranked.le(0.20).astype(float)
        severe_loss = vals.lt(-1.0).astype(float)
        target = 0.60 * ranked + 0.30 * positive - 0.10 * left_tail - 0.10 * severe_loss
        return target.clip(lower=0.0, upper=1.0).replace([np.inf, -np.inf], np.nan).fillna(0.5)
    if mode == "weak_positive_daily_ranked":
        ranked = vals.groupby(df["trade_date"], sort=False).rank(pct=True)
        day_mean = vals.groupby(df["trade_date"], sort=False).transform("mean")
        positive_rank_target = pd.Series(
            np.where(vals.gt(0.0), 0.50 + 0.50 * ranked, 0.05 * ranked),
            index=df.index,
            dtype=float,
        )
        target = pd.Series(np.where(day_mean.lt(0.0), positive_rank_target, ranked), index=df.index, dtype=float)
        return target.clip(lower=0.0, upper=1.0).replace([np.inf, -np.inf], np.nan).fillna(0.5)
    if mode == "state_weak_positive_daily_ranked":
        ranked = vals.groupby(df["trade_date"], sort=False).rank(pct=True)
        state_weak = _state_weak_day_mask(df)
        positive_rank_target = pd.Series(
            np.where(vals.gt(0.0), 0.50 + 0.50 * ranked, 0.04 * ranked),
            index=df.index,
            dtype=float,
        )
        target = pd.Series(np.where(state_weak, positive_rank_target, ranked), index=df.index, dtype=float)
        return target.clip(lower=0.0, upper=1.0).replace([np.inf, -np.inf], np.nan).fillna(0.5)
    if mode == "strict_positive_daily_ranked":
        ranked = vals.groupby(df["trade_date"], sort=False).rank(pct=True)
        target = pd.Series(
            np.where(vals.gt(0.0), 0.55 + 0.45 * ranked, 0.03 * ranked),
            index=df.index,
            dtype=float,
        )
        return target.clip(lower=0.0, upper=1.0).replace([np.inf, -np.inf], np.nan).fillna(0.5)
    if mode == "margin_positive_daily_ranked":
        ranked = vals.groupby(df["trade_date"], sort=False).rank(pct=True)
        strong_positive = vals.gt(0.50)
        weak_positive = vals.gt(0.0) & ~strong_positive
        target = pd.Series(
            np.select(
                [strong_positive.to_numpy(dtype=bool), weak_positive.to_numpy(dtype=bool)],
                [0.65 + 0.35 * ranked.to_numpy(dtype=float), 0.35 + 0.20 * ranked.to_numpy(dtype=float)],
                default=0.03 * ranked.to_numpy(dtype=float),
            ),
            index=df.index,
            dtype=float,
        )
        return target.clip(lower=0.0, upper=1.0).replace([np.inf, -np.inf], np.nan).fillna(0.5)
    return vals.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _model_note_prefix(variant: str, note: str = "") -> str:
    bits = []
    _, wrappers = _strip_state_training_prefix(str(variant))
    bits.extend(wrappers)
    if _uses_engineered_features(variant):
        bits.append("engineered_features")
    if _uses_context_features(variant):
        bits.append("context_features")
    if _uses_downside_weights(variant):
        bits.append("downside_weighted_samples")
    if _uses_rank_normalization(variant):
        bits.append("rank_normalized_features")
    treatments = _variant_treatments(variant)
    if treatments:
        bits.append("treatments=" + ",".join(treatments))
    base = _base_model_variant(variant)
    if base != str(variant):
        bits.append(f"base_model={base}")
    if note:
        bits.append(note)
    return ";".join(bits)


def _sample_rows_for_mode(df: pd.DataFrame, max_rows: int, seed: int, sample_mode: str) -> pd.DataFrame:
    """Sample diagnostic train/test rows without changing production behavior."""

    max_rows = int(max_rows)
    if max_rows <= 0 or len(df) <= max_rows:
        return df.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    mode = str(sample_mode or "random").strip().lower()
    if mode in ("none", "all", "full"):
        return df.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    if mode == "random":
        return _sample_rows(df, max_rows, seed)
    if mode != "date_stratified":
        raise ValueError(f"unsupported sample_mode={sample_mode!r}")

    if "trade_date" not in df.columns:
        return _sample_rows(df, max_rows, seed)
    work = df.copy()
    groups = list(work.groupby("trade_date", sort=True, group_keys=False))
    if not groups:
        return work.head(0).copy()
    base = max(1, max_rows // len(groups))
    remaining = max_rows
    samples = []
    for idx, (_, g) in enumerate(groups):
        groups_left = len(groups) - idx
        quota = min(len(g), max(1, min(base, remaining - groups_left + 1)))
        if quota >= len(g):
            sample = g.copy()
        else:
            stable_key = pd.util.hash_pandas_object(g["ts_code"].astype(str), index=False)
            sample = g.assign(_sample_key=stable_key.to_numpy()).sort_values(["_sample_key", "ts_code"]).head(quota).drop(columns=["_sample_key"])
        samples.append(sample)
        remaining -= len(sample)
        if remaining <= 0:
            break
    out = pd.concat(samples, ignore_index=True) if samples else work.head(0).copy()
    return out.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def _train_lgb_variant(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    *,
    features: list[str],
    label_col: str,
    variant: str,
    num_boost_round: int,
    early_stopping_rounds: int,
    seed: int,
    num_threads: int,
    recency_half_life_days: float,
    sample_weight_mode: str = "",
    raw_label_col: str | None = None,
) -> Any:
    import lightgbm as lgb

    variant = str(variant)
    callbacks = [lgb.log_evaluation(period=0)]
    common = {
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "max_depth": 8,
        "min_data_in_leaf": 100,
        "lambda_l1": 0.1,
        "lambda_l2": 0.1,
        "seed": int(seed),
        "feature_fraction_seed": int(seed),
        "bagging_seed": int(seed),
        "verbose": -1,
        "num_threads": int(num_threads),
    }
    if variant == "lambdarank":
        train_rank = _make_rank_labels(train_df, label_col)
        valid_rank = _make_rank_labels(valid_df, label_col) if not valid_df.empty else pd.Series(dtype=int)
        params = {
            **common,
            "objective": "lambdarank",
            "metric": "ndcg",
            "ndcg_eval_at": [5, 10, 30],
            "lambdarank_truncation_level": 30,
        }
        train_data = lgb.Dataset(
            train_df[features].to_numpy(dtype=float),
            label=train_rank.to_numpy(dtype=float),
            group=_group_sizes(train_df),
            feature_name=features,
        )
        valid_sets = [train_data]
        valid_names = ["train"]
        if not valid_df.empty:
            valid_data = lgb.Dataset(
                valid_df[features].to_numpy(dtype=float),
                label=valid_rank.to_numpy(dtype=float),
                group=_group_sizes(valid_df),
                feature_name=features,
                reference=train_data,
            )
            valid_sets.append(valid_data)
            valid_names.append("valid")
            if early_stopping_rounds > 0:
                callbacks.append(lgb.early_stopping(stopping_rounds=int(early_stopping_rounds), verbose=False))
    else:
        objective, metric = _objective_params_for_variant(variant)
        params = {**common, "objective": objective, "metric": metric}
        mode = str(sample_weight_mode or "").lower()
        if mode == "downside":
            weight = _downside_aware_weights(train_df, raw_label_col or label_col)
        elif mode == "state_similarity":
            weight = pd.to_numeric(train_df.get(STATE_SIMILARITY_WEIGHT_COL, 1.0), errors="coerce").fillna(1.0).to_numpy(dtype=float)
            weight = weight / max(float(np.mean(weight)), 1e-12)
        elif mode == "downside_state_similarity":
            state_weight = pd.to_numeric(train_df.get(STATE_SIMILARITY_WEIGHT_COL, 1.0), errors="coerce").fillna(1.0).to_numpy(dtype=float)
            downside_weight = _downside_aware_weights(train_df, raw_label_col or label_col)
            weight = state_weight * downside_weight
            weight = weight / max(float(np.mean(weight)), 1e-12)
        elif variant == "recency_weighted":
            weight = _recency_weights(train_df, half_life_days=recency_half_life_days)
        else:
            weight = None
        train_data = lgb.Dataset(
            train_df[features].to_numpy(dtype=float),
            label=train_df[label_col].to_numpy(dtype=float),
            weight=weight,
            feature_name=features,
        )
        valid_sets = [train_data]
        valid_names = ["train"]
        if not valid_df.empty:
            valid_data = lgb.Dataset(
                valid_df[features].to_numpy(dtype=float),
                label=valid_df[label_col].to_numpy(dtype=float),
                feature_name=features,
                reference=train_data,
            )
            valid_sets.append(valid_data)
            valid_names.append("valid")
            if early_stopping_rounds > 0:
                callbacks.append(lgb.early_stopping(stopping_rounds=int(early_stopping_rounds), verbose=False))
    return lgb.train(
        params,
        train_data,
        num_boost_round=max(20, int(num_boost_round)),
        valid_sets=valid_sets,
        valid_names=valid_names,
        callbacks=callbacks,
    )


class _ConstantPositiveHitModel:
    def __init__(self, value: float):
        self.value = float(min(max(value, 0.0), 1.0))

    def predict(self, x: object) -> np.ndarray:
        try:
            n = len(x)  # type: ignore[arg-type]
        except Exception:
            n = 0
        return np.full(int(n), self.value, dtype=float)


def _train_lgb_positive_hit(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    *,
    features: list[str],
    label_col: str,
    num_boost_round: int,
    early_stopping_rounds: int,
    seed: int,
    num_threads: int,
) -> Any:
    import lightgbm as lgb

    y = pd.to_numeric(train_df[label_col], errors="coerce").gt(0.0).astype(int)
    if y.nunique(dropna=True) < 2:
        return _ConstantPositiveHitModel(float(y.mean()) if len(y) else 0.0)
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "max_depth": 8,
        "min_data_in_leaf": 100,
        "lambda_l1": 0.1,
        "lambda_l2": 0.1,
        "seed": int(seed),
        "feature_fraction_seed": int(seed),
        "bagging_seed": int(seed),
        "verbose": -1,
        "num_threads": int(num_threads),
    }
    train_data = lgb.Dataset(
        train_df[features].to_numpy(dtype=float),
        label=y.to_numpy(dtype=float),
        feature_name=features,
    )
    callbacks = [lgb.log_evaluation(period=0)]
    valid_sets = [train_data]
    valid_names = ["train"]
    if not valid_df.empty:
        valid_y = pd.to_numeric(valid_df[label_col], errors="coerce").gt(0.0).astype(int)
        valid_data = lgb.Dataset(
            valid_df[features].to_numpy(dtype=float),
            label=valid_y.to_numpy(dtype=float),
            feature_name=features,
            reference=train_data,
        )
        valid_sets.append(valid_data)
        valid_names.append("valid")
        if early_stopping_rounds > 0:
            callbacks.append(lgb.early_stopping(stopping_rounds=int(early_stopping_rounds), verbose=False))
    return lgb.train(
        params,
        train_data,
        num_boost_round=max(20, int(num_boost_round)),
        valid_sets=valid_sets,
        valid_names=valid_names,
        callbacks=callbacks,
    )


def _predict_regime_specific(
    fit_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    test_df: pd.DataFrame,
    *,
    features: list[str],
    label_col: str,
    num_boost_round: int,
    early_stopping_rounds: int,
    seed: int,
    num_threads: int,
    recency_half_life_days: float,
    min_regime_train_rows: int,
    min_regime_train_days: int,
    sample_weight_mode: str = "",
    raw_label_col: str | None = None,
) -> tuple[np.ndarray, pd.DataFrame, str]:
    global_model = _train_lgb_variant(
        fit_df,
        valid_df,
        features=features,
        label_col=label_col,
        variant="baseline",
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
        seed=seed,
        num_threads=num_threads,
        recency_half_life_days=recency_half_life_days,
        sample_weight_mode=sample_weight_mode,
        raw_label_col=raw_label_col,
    )
    pred = pd.Series(global_model.predict(test_df[features].to_numpy(dtype=float)), index=test_df.index, dtype=float)
    notes = []
    imp_parts = []
    regimes = sorted(str(x) for x in test_df.get("market_regime_exante", pd.Series(["neutral"])).fillna("neutral").unique())
    for idx, regime in enumerate(regimes):
        test_mask = test_df.get("market_regime_exante", pd.Series("neutral", index=test_df.index)).fillna("neutral").astype(str).eq(regime)
        if not bool(test_mask.any()):
            continue
        fit_mask = fit_df.get("market_regime_exante", pd.Series("neutral", index=fit_df.index)).fillna("neutral").astype(str).eq(regime)
        valid_mask = valid_df.get("market_regime_exante", pd.Series("neutral", index=valid_df.index)).fillna("neutral").astype(str).eq(regime) if not valid_df.empty else pd.Series(dtype=bool)
        fit_regime = fit_df.loc[fit_mask].copy()
        valid_regime = valid_df.loc[valid_mask].copy() if not valid_df.empty else pd.DataFrame()
        train_days = int(fit_regime["trade_date"].nunique()) if not fit_regime.empty else 0
        if len(fit_regime) < int(min_regime_train_rows) or train_days < int(min_regime_train_days):
            notes.append(f"{regime}:global_fallback(test={int(test_mask.sum())},train={len(fit_regime)},days={train_days})")
            model = global_model
        else:
            model = _train_lgb_variant(
                fit_regime,
                valid_regime,
                features=features,
                label_col=label_col,
                variant="baseline",
                num_boost_round=num_boost_round,
                early_stopping_rounds=early_stopping_rounds,
                seed=seed + idx + 1,
                num_threads=num_threads,
                recency_half_life_days=recency_half_life_days,
                sample_weight_mode=sample_weight_mode,
                raw_label_col=raw_label_col,
            )
            pred.loc[test_mask] = model.predict(test_df.loc[test_mask, features].to_numpy(dtype=float))
            notes.append(f"{regime}:regime_model(test={int(test_mask.sum())},train={len(fit_regime)},days={train_days})")
        imp = _feature_importance(model, features)
        imp["importance_gain"] = pd.to_numeric(imp["importance_gain"], errors="coerce").fillna(0.0) * float(test_mask.sum())
        imp_parts.append(imp[["feature", "importance_gain"]])
    if imp_parts:
        importance = pd.concat(imp_parts, ignore_index=True).groupby("feature", as_index=False)["importance_gain"].sum()
        total = float(importance["importance_gain"].sum())
        importance["importance_share_pct"] = importance["importance_gain"] / max(total, 1e-12) * 100.0
        importance = importance.sort_values("importance_gain", ascending=False).reset_index(drop=True)
    else:
        importance = _feature_importance(global_model, features)
    return pred.to_numpy(dtype=float), importance, ";".join(notes)


def _feature_importance(model: Any, features: list[str]) -> pd.DataFrame:
    try:
        gain = model.feature_importance(importance_type="gain")
    except Exception:
        gain = np.zeros(len(features), dtype=float)
    out = pd.DataFrame({"feature": features, "importance_gain": gain})
    total = float(out["importance_gain"].sum())
    out["importance_share_pct"] = out["importance_gain"] / max(total, 1e-12) * 100.0
    return out.sort_values("importance_gain", ascending=False).reset_index(drop=True)


def _drop_high_drift_features(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    *,
    features: list[str],
    psi_threshold: float,
    std_diff_threshold: float,
) -> tuple[list[str], pd.DataFrame]:
    drift = pd.DataFrame(feature_drift_rows(train_df, test_df, features=features, max_features=len(features)))
    if drift.empty:
        return list(features), drift
    drop = set(
        drift[
            (pd.to_numeric(drift["psi"], errors="coerce").fillna(0.0) >= float(psi_threshold))
            | (pd.to_numeric(drift["std_mean_diff"], errors="coerce").fillna(0.0) >= float(std_diff_threshold))
        ]["feature"].astype(str)
    )
    kept = [f for f in features if f not in drop]
    return (kept or list(features)), drift


def _regime_summary(pred: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    if pred.empty:
        return pd.DataFrame()
    day_mean = pred.groupby("trade_date")["label"].mean().rename("day_all_mean_return_pct")
    work = pred.merge(day_mean, left_on="trade_date", right_index=True, how="left")
    work["regime_proxy_expost"] = work["day_all_mean_return_pct"].map(lambda x: _regime_label(_safe_float(x, 0.0)))
    rows = []
    for regime, g in work.groupby("regime_proxy_expost", sort=True):
        row = summarize_predictions(g, score_col="pred", label_col="label", top_n=int(top_n), direction="desc")
        rows.append({"regime_proxy_expost": str(regime), **row, "failure_label": _failure_label(row)})
    return pd.DataFrame(rows)


def _exante_regime_summary(pred: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    if pred.empty or "market_regime_exante" not in pred.columns:
        return pd.DataFrame()
    rows = []
    work = pred.copy()
    work["market_regime_exante"] = work["market_regime_exante"].fillna("neutral").astype(str)
    for regime, g in work.groupby("market_regime_exante", sort=True):
        row = summarize_predictions(g, score_col="pred", label_col="label", top_n=int(top_n), direction="desc")
        rows.append({"regime_exante": str(regime), **row, "failure_label": _failure_label(row)})
    return pd.DataFrame(rows)


def _selected_feature_exposure(pred: pd.DataFrame, feature_cols: list[str], *, top_n: int) -> pd.DataFrame:
    if pred.empty:
        return pd.DataFrame()
    work = pred.sort_values(["trade_date", "pred"], ascending=[True, False]).copy()
    work["_is_top"] = False
    top_idx = work.groupby("trade_date", group_keys=False).head(max(1, int(top_n))).index
    work.loc[top_idx, "_is_top"] = True
    rows = []
    for f in feature_cols:
        if f not in work.columns:
            continue
        all_mean = _safe_float(work[f].mean(), 0.0)
        top_mean = _safe_float(work.loc[work["_is_top"], f].mean(), 0.0)
        rows.append(
            {
                "feature": str(f),
                "all_mean": all_mean,
                "top_mean": top_mean,
                "top_minus_all": float(top_mean - all_mean),
            }
        )
    return pd.DataFrame(rows)


def _daily_zscore_score(df: pd.DataFrame, score_col: str = "pred") -> pd.Series:
    vals = pd.to_numeric(df[score_col], errors="coerce")
    g = vals.groupby(df["trade_date"], sort=False)
    mean = g.transform("mean")
    std = g.transform("std").replace(0.0, np.nan)
    return ((vals - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _daily_zscore_values(values: object, dates: object) -> pd.Series:
    vals = pd.to_numeric(pd.Series(values), errors="coerce")
    date_ser = pd.Series(dates, index=vals.index)
    g = vals.groupby(date_ser, sort=False)
    mean = g.transform("mean")
    std = g.transform("std").replace(0.0, np.nan)
    return ((vals - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _mean_daily_feature_zscore(df: pd.DataFrame, features: list[str]) -> pd.Series:
    parts = []
    for feature in features:
        if feature not in df.columns:
            continue
        parts.append(_daily_zscore_values(df[feature].to_numpy(dtype=float), df["trade_date"]).rename(str(feature)))
    if not parts:
        return pd.Series(np.zeros(len(df), dtype=float), index=df.index)
    return pd.concat(parts, axis=1).mean(axis=1).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _numeric_col(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(float(default), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(float(default))


def _add_diagnostic_engineered_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Add diagnosis-only interaction features from signal-date inputs.

    These features are deterministic transforms of existing same-day indicator
    columns. They do not use labels, future prices, P2 artifacts, or profile
    outputs, so they are safe for raw-model experiments.
    """

    if df.empty:
        return df.copy(), []
    out = df.copy()
    pos = _numeric_col(out, "pos_52w")
    rs20 = _numeric_col(out, "rs_20d")
    rs5 = _numeric_col(out, "rs_5d")
    mom20 = _numeric_col(out, "mom_20")
    mom5 = _numeric_col(out, "mom_5")
    bias = _numeric_col(out, "bias")
    pv20 = _numeric_col(out, "pv_corr_20")
    vol_ratio = _numeric_col(out, "vol_ratio")
    vol = _numeric_col(out, "volatility_ratio")
    atr = _numeric_col(out, "atr_percent")
    bb_pos = _numeric_col(out, "bb_pos", 0.5)
    engineered = {
        "mom20_minus_mom5": mom20 - mom5,
        "rs20_minus_rs5": rs20 - rs5,
        "pos52w_x_rs20": pos * rs20,
        "pos52w_x_mom20": pos * mom20,
        "pos52w_x_bias": pos * bias,
        "pv20_x_mom20": pv20 * mom20,
        "vol_stress": vol_ratio * vol,
        "risk_adjusted_mom20": mom20 / (1.0 + atr.abs() + vol.abs()),
        "mean_reversion_pressure": (bb_pos - 0.5) * bias,
    }
    added: list[str] = []
    for name in ENGINEERED_FEATURE_BASES:
        if name not in engineered:
            continue
        out[name] = pd.to_numeric(engineered[name], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
        added.append(name)
        if "trade_date" in out.columns:
            cs_name = f"{name}_cs"
            out[cs_name] = _daily_zscore_values(out[name].to_numpy(dtype=float), out["trade_date"])
            added.append(cs_name)
    return out, added


def _add_diagnostic_context_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Add richer signal-date context features for raw-model experiments.

    The context family uses only signal-date OHLCV, same-day market breadth, and
    trailing market state already known by the close. It deliberately avoids
    future labels, P2 artifacts, profile outputs, and next-day tradability.
    """

    if df.empty:
        return df.copy(), []
    out, added = _add_diagnostic_engineered_features(df)
    open_px = _numeric_col(out, "open")
    high_px = _numeric_col(out, "high")
    low_px = _numeric_col(out, "low")
    close_px = _numeric_col(out, "close")
    pct = _numeric_col(out, "pct_chg")
    amount = _numeric_col(out, "amount")
    vol = _numeric_col(out, "vol")
    market_ret = _numeric_col(out, "market_ret_pct")
    market_ret20 = _numeric_col(out, "market_ret_20d")
    market_vol20 = _numeric_col(out, "market_vol_20d")
    pos = _numeric_col(out, "pos_52w")
    mom20 = _numeric_col(out, "mom_20")
    vol_ratio = _numeric_col(out, "vol_ratio")

    prev_close = _safe_div(close_px, 1.0 + pct / 100.0, default=0.0)
    intraday_ret = (_safe_div(close_px, open_px, default=1.0) - 1.0) * 100.0
    gap_open = (_safe_div(open_px, prev_close, default=1.0) - 1.0) * 100.0
    range_pct = _safe_div(high_px - low_px, prev_close.replace(0.0, np.nan), default=0.0) * 100.0
    close_location = _safe_div(close_px - low_px, high_px - low_px, default=0.5)
    market_stress = market_ret20.abs() + market_vol20.abs()

    context = {
        "gap_open_pct": gap_open,
        "intraday_ret_pct": intraday_ret,
        "range_pct": range_pct,
        "close_location": close_location.clip(lower=0.0, upper=1.0),
        "amount_log": np.log1p(amount.clip(lower=0.0)),
        "vol_log": np.log1p(vol.clip(lower=0.0)),
        "stock_minus_market_ret": pct - market_ret,
        "gap_minus_market_ret": gap_open - market_ret,
        "intraday_minus_market_ret": intraday_ret - market_ret,
        "market_stress_x_range": market_stress * range_pct,
        "market_stress_x_vol": market_stress * vol_ratio,
        "weak_market_mom20": mom20 * market_ret20.clip(upper=0.0).abs(),
        "strong_market_pos52w": pos * market_ret20.clip(lower=0.0),
    }
    for name in CONTEXT_FEATURE_BASES:
        if name not in context:
            continue
        out[name] = pd.to_numeric(context[name], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
        added.append(name)
        if "trade_date" in out.columns:
            cs_name = f"{name}_cs"
            out[cs_name] = _daily_zscore_values(out[name].to_numpy(dtype=float), out["trade_date"])
            added.append(cs_name)
    return out, list(dict.fromkeys(added))


def _blend_with_absolute_return_calibrator(
    pred: pd.DataFrame,
    abs_pred_values: np.ndarray | pd.Series,
    *,
    abs_weight: float = 0.35,
) -> pd.Series:
    primary = _daily_zscore_values(pred["pred"].to_numpy(dtype=float), pred["trade_date"])
    abs_score = _daily_zscore_values(pd.Series(abs_pred_values).to_numpy(dtype=float), pred["trade_date"])
    w = min(max(float(abs_weight), 0.0), 1.0)
    return ((1.0 - w) * primary + w * abs_score).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _apply_positive_hit_blend(
    pred: pd.DataFrame,
    fit: pd.DataFrame,
    valid: pd.DataFrame,
    test_eval: pd.DataFrame,
    *,
    features: list[str],
    label_col: str,
    num_boost_round: int,
    early_stopping_rounds: int,
    seed: int,
    num_threads: int,
    hit_weight: float = 0.35,
) -> tuple[pd.DataFrame, str]:
    out = pred.copy()
    if fit.empty or label_col not in fit.columns:
        return out, "positive_hit_blend=no_train_label"
    model = _train_lgb_positive_hit(
        fit,
        valid,
        features=features,
        label_col=label_col,
        num_boost_round=int(num_boost_round),
        early_stopping_rounds=int(early_stopping_rounds),
        seed=int(seed) + 31,
        num_threads=max(1, int(num_threads)),
    )
    hit_prob = pd.Series(model.predict(test_eval[features].to_numpy(dtype=float)), index=out.index, dtype=float)
    primary = _daily_zscore_values(out["pred"].to_numpy(dtype=float), out["trade_date"])
    hit_score = _daily_zscore_values(hit_prob.to_numpy(dtype=float), out["trade_date"])
    w = min(max(float(hit_weight), 0.0), 1.0)
    out["pred"] = ((1.0 - w) * primary + w * hit_score).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out["_positive_hit_prob"] = hit_prob.to_numpy(dtype=float)
    out["_positive_hit_blend_active"] = True
    return out, f"positive_hit_blend_weight={w:.2f};mean_hit_prob={float(hit_prob.mean()):.3f}"


def _daily_top_hit_score_frame(
    df: pd.DataFrame,
    *,
    hit_col: str,
    label_col: str,
    top_n: int,
) -> pd.DataFrame:
    if df.empty or hit_col not in df.columns or label_col not in df.columns or "trade_date" not in df.columns:
        return pd.DataFrame()
    work = df[["trade_date", hit_col, label_col]].copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work[hit_col] = pd.to_numeric(work[hit_col], errors="coerce")
    work[label_col] = pd.to_numeric(work[label_col], errors="coerce")
    work = work.dropna(subset=["trade_date", hit_col, label_col])
    if work.empty:
        return pd.DataFrame()
    rows = []
    for trade_date, g in work.groupby("trade_date", sort=True):
        top = g.sort_values(hit_col, ascending=False).head(max(1, int(top_n)))
        rows.append(
            {
                "trade_date": pd.Timestamp(trade_date).normalize(),
                "hit_top_mean_prob": _safe_float(top[hit_col].mean(), 0.0),
                "hit_top_mean_return_pct": _safe_float(top[label_col].mean(), 0.0),
            }
        )
    return pd.DataFrame(rows)


def _choose_hit_deployability_threshold(
    valid_scores: pd.DataFrame,
    *,
    min_validation_deploy_rate_pct: float,
) -> tuple[float, float, float]:
    if valid_scores.empty or "hit_top_mean_prob" not in valid_scores.columns:
        return 1.0, 0.0, 0.0
    work = valid_scores.copy()
    work["hit_top_mean_prob"] = pd.to_numeric(work["hit_top_mean_prob"], errors="coerce")
    work["hit_top_mean_return_pct"] = pd.to_numeric(work["hit_top_mean_return_pct"], errors="coerce")
    work = work.dropna(subset=["hit_top_mean_prob", "hit_top_mean_return_pct"])
    if work.empty:
        return 1.0, 0.0, 0.0
    candidates = sorted(set(float(x) for x in work["hit_top_mean_prob"].quantile([0.0, 0.25, 0.40, 0.50, 0.60, 0.70, 0.80]).dropna().tolist()))
    rows = []
    for threshold in candidates:
        deploy = work["hit_top_mean_prob"].ge(float(threshold))
        rate = float(deploy.mean() * 100.0)
        mean_ret = _safe_float(work.loc[deploy, "hit_top_mean_return_pct"].mean(), 0.0) if bool(deploy.any()) else -999.0
        rows.append({"threshold": threshold, "validation_deploy_rate_pct": rate, "validation_deployed_mean_return_pct": mean_ret})
    grid = pd.DataFrame(rows)
    eligible = grid[grid["validation_deploy_rate_pct"].ge(float(min_validation_deploy_rate_pct))].copy()
    if eligible.empty:
        eligible = grid.copy()
    positive = eligible[eligible["validation_deployed_mean_return_pct"].gt(0.0)].copy()
    ranked = positive if not positive.empty else eligible
    ranked = ranked.sort_values(
        ["validation_deployed_mean_return_pct", "validation_deploy_rate_pct", "threshold"],
        ascending=[False, False, True],
    )
    best = ranked.iloc[0]
    return (
        _safe_float(best.get("threshold"), 1.0),
        _safe_float(best.get("validation_deploy_rate_pct"), 0.0),
        _safe_float(best.get("validation_deployed_mean_return_pct"), 0.0),
    )


def _apply_positive_hit_deployability_abstention(
    pred: pd.DataFrame,
    fit: pd.DataFrame,
    valid: pd.DataFrame,
    test_eval: pd.DataFrame,
    *,
    features: list[str],
    label_col: str,
    top_n: int,
    num_boost_round: int,
    early_stopping_rounds: int,
    seed: int,
    num_threads: int,
    min_validation_deploy_rate_pct: float = 50.0,
) -> tuple[pd.DataFrame, str]:
    out = pred.copy()
    if fit.empty or valid.empty or label_col not in fit.columns or label_col not in valid.columns:
        out["_deploy_signal"] = True
        return out, "positive_hit_deployability_abstention=no_validation_fallback_all_deploy"
    model = _train_lgb_positive_hit(
        fit,
        valid,
        features=features,
        label_col=label_col,
        num_boost_round=int(num_boost_round),
        early_stopping_rounds=int(early_stopping_rounds),
        seed=int(seed) + 47,
        num_threads=max(1, int(num_threads)),
    )
    valid_work = valid[["trade_date", *features, label_col]].copy()
    valid_work["_hit_prob_for_deploy"] = model.predict(valid_work[features].to_numpy(dtype=float))
    valid_scores = _daily_top_hit_score_frame(
        valid_work,
        hit_col="_hit_prob_for_deploy",
        label_col=label_col,
        top_n=int(top_n),
    )
    threshold, valid_rate, valid_mean = _choose_hit_deployability_threshold(
        valid_scores,
        min_validation_deploy_rate_pct=float(min_validation_deploy_rate_pct),
    )
    if "_positive_hit_prob" in out.columns:
        test_prob = pd.to_numeric(out["_positive_hit_prob"], errors="coerce").fillna(0.0)
    else:
        test_prob = pd.Series(model.predict(test_eval[features].to_numpy(dtype=float)), index=out.index, dtype=float)
        out["_positive_hit_prob"] = test_prob.to_numpy(dtype=float)
    test_work = out[["trade_date", "label"]].copy()
    test_work["_hit_prob_for_deploy"] = test_prob.to_numpy(dtype=float)
    test_scores = _daily_top_hit_score_frame(
        test_work,
        hit_col="_hit_prob_for_deploy",
        label_col="label",
        top_n=int(top_n),
    )
    score_map = test_scores.set_index("trade_date")["hit_top_mean_prob"] if not test_scores.empty else pd.Series(dtype=float)
    day = pd.to_datetime(out["trade_date"], errors="coerce").dt.normalize()
    day_score = day.map(score_map).fillna(0.0).astype(float)
    deploy = day_score.ge(float(threshold))
    prior = out["_deploy_signal"].astype(bool) if "_deploy_signal" in out.columns else pd.Series(True, index=out.index)
    out["_deploy_signal"] = (prior & deploy.reset_index(drop=True)).to_numpy(dtype=bool)
    out["_day_hit_deploy_score"] = day_score.to_numpy(dtype=float)
    prior_active = out["_treatment_active"].astype(bool) if "_treatment_active" in out.columns else pd.Series(False, index=out.index)
    out["_treatment_active"] = (prior_active | (~deploy).reset_index(drop=True)).to_numpy(dtype=bool)
    deploy_days = int(out.groupby("trade_date")["_deploy_signal"].max().sum()) if not out.empty else 0
    total_days = int(out["trade_date"].nunique()) if not out.empty else 0
    return (
        out,
        "positive_hit_deployability_abstention="
        f"threshold={float(threshold):.3f},deploy_days={deploy_days}/{total_days},"
        f"validation_deploy_rate={float(valid_rate):.1f},validation_deployed_mean={float(valid_mean):+.2f},"
        f"mean_test_hit_deploy_score={float(day_score.mean()):.3f}",
    )


def _apply_pos52w_beta_overlay(
    pred: pd.DataFrame,
    *,
    pos_weight: float = 0.30,
    beta_weight: float = 0.15,
) -> pd.Series:
    primary = _daily_zscore_values(pred["pred"].to_numpy(dtype=float), pred["trade_date"])
    pos_score = _mean_daily_feature_zscore(pred, ["pos_52w", "pos_52w_cs"])
    beta_score = _mean_daily_feature_zscore(pred, ["rs_20d", "rs_20d_cs", "mom_20", "mom_20_cs", "bias", "bias_cs"])
    adjusted = primary + float(pos_weight) * pos_score + float(beta_weight) * beta_score
    return adjusted.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _day_state_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Build signal-date day-state features available by the close.

    These features are used only for diagnosis-time train/test treatment
    selection. They deliberately avoid label or future data; label outcomes are
    joined separately when learning a calibration target from training days.
    """

    if df.empty or "trade_date" not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work = work[work["trade_date"].notna()].copy()
    if work.empty:
        return pd.DataFrame()
    aggs: dict[str, tuple[str, str]] = {}
    for col in ["market_ret_20d", "market_up_rate_20d", "market_vol_20d"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
            aggs[col] = (col, "mean")
    for col in DAY_STATE_RAW_FEATURES:
        if col not in work.columns:
            continue
        work[col] = pd.to_numeric(work[col], errors="coerce")
        aggs[f"{col}_day_mean"] = (col, "mean")
        aggs[f"{col}_day_std"] = (col, "std")
    if not aggs:
        return pd.DataFrame({"trade_date": sorted(work["trade_date"].unique())})
    out = work.groupby("trade_date", as_index=False).agg(**aggs)
    for col in out.columns:
        if col != "trade_date":
            out[col] = pd.to_numeric(out[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return out.sort_values("trade_date").reset_index(drop=True)


def _knn_day_expectation(
    train_state: pd.DataFrame,
    test_state: pd.DataFrame,
    *,
    target_col: str,
    neighbor_days: int = 20,
) -> pd.Series:
    if train_state.empty or test_state.empty or target_col not in train_state.columns:
        return pd.Series(dtype=float)
    feature_cols = [
        c
        for c in train_state.columns
        if c not in {"trade_date", target_col}
        and c in test_state.columns
        and pd.api.types.is_numeric_dtype(train_state[c])
    ]
    if not feature_cols:
        return pd.Series(dtype=float)
    train = train_state.dropna(subset=[target_col]).copy()
    if train.empty:
        return pd.Series(dtype=float)
    for col in feature_cols:
        train[col] = pd.to_numeric(train[col], errors="coerce")
        test_state[col] = pd.to_numeric(test_state[col], errors="coerce")
    mean = train[feature_cols].mean()
    std = train[feature_cols].std(ddof=1).replace(0.0, np.nan).fillna(1.0)
    train_x = ((train[feature_cols] - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=float)
    test_x = ((test_state[feature_cols] - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=float)
    train_y = pd.to_numeric(train[target_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    k = max(1, min(int(neighbor_days), len(train)))
    out: dict[pd.Timestamp, float] = {}
    for idx, row in enumerate(test_x):
        dist = np.linalg.norm(train_x - row, axis=1)
        nearest = np.argsort(dist)[:k]
        out[pd.Timestamp(test_state.iloc[idx]["trade_date"]).normalize()] = float(np.mean(train_y[nearest]))
    return pd.Series(out, dtype=float)


def _training_day_all_return_state(train_df: pd.DataFrame, *, label_col: str) -> pd.DataFrame:
    if train_df.empty or label_col not in train_df.columns:
        return pd.DataFrame()
    state = _day_state_frame(train_df)
    if state.empty:
        return state
    ret = (
        train_df.assign(
            trade_date=pd.to_datetime(train_df["trade_date"], errors="coerce").dt.normalize(),
            _label=pd.to_numeric(train_df[label_col], errors="coerce"),
        )
        .dropna(subset=["_label"])
        .groupby("trade_date", as_index=False)["_label"]
        .mean()
        .rename(columns={"_label": "train_day_all_mean_return_pct"})
    )
    return state.merge(ret, on="trade_date", how="inner")


def _training_day_deployability_state(train_df: pd.DataFrame, *, label_col: str) -> pd.DataFrame:
    """Summarize prior signal-date environments for an abstention head.

    This stays at the day level: it does not use test labels or oracle stock
    selection in the test period. The target asks whether similar training
    signal dates had broad enough positive-return opportunity to justify
    deploying a daily long basket at all.
    """

    if train_df.empty or label_col not in train_df.columns:
        return pd.DataFrame()
    state = _day_state_frame(train_df)
    if state.empty:
        return state
    work = train_df[["trade_date", label_col]].copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["_label"] = pd.to_numeric(work[label_col], errors="coerce")
    work = work.dropna(subset=["trade_date", "_label"])
    if work.empty:
        return pd.DataFrame()
    ret = (
        work.groupby("trade_date", as_index=False)
        .agg(
            deploy_day_all_mean_return_pct=("_label", "mean"),
            deploy_day_positive_rate_pct=("_label", lambda s: float((pd.to_numeric(s, errors="coerce") > 0.0).mean() * 100.0)),
            deploy_day_left_tail_rate_pct=("_label", lambda s: float((pd.to_numeric(s, errors="coerce") <= -1.0).mean() * 100.0)),
        )
        .sort_values("trade_date")
    )
    return state.merge(ret, on="trade_date", how="inner")


def _apply_day_state_absolute_calibration(
    pred: pd.DataFrame,
    train_df: pd.DataFrame,
    *,
    label_col: str,
    neighbor_days: int = 20,
    max_defensive_weight: float = 0.55,
) -> tuple[pd.DataFrame, str]:
    out = pred.copy()
    train_state = _training_day_all_return_state(train_df, label_col=label_col)
    test_state = _day_state_frame(out)
    expected = _knn_day_expectation(
        train_state,
        test_state,
        target_col="train_day_all_mean_return_pct",
        neighbor_days=int(neighbor_days),
    )
    if expected.empty:
        return out, "day_state_absolute_calibration=no_day_state"
    day = pd.to_datetime(out["trade_date"], errors="coerce").dt.normalize()
    exp = day.map(expected).fillna(0.0).astype(float)
    strength = (-exp / 1.50).clip(lower=0.0, upper=1.0)
    primary = _daily_zscore_values(out["pred"].to_numpy(dtype=float), out["trade_date"])
    defensive = -_mean_daily_feature_zscore(out, DEFENSIVE_FEATURES)
    out["pred"] = (primary + float(max_defensive_weight) * strength.reset_index(drop=True) * defensive).replace(
        [np.inf, -np.inf],
        np.nan,
    ).fillna(0.0)
    out["_day_abs_expected_return_pct"] = exp.to_numpy(dtype=float)
    active = strength.gt(1e-9)
    out["_absolute_calibration_active"] = active.to_numpy(dtype=bool)
    prior_active = out["_treatment_active"].astype(bool) if "_treatment_active" in out.columns else pd.Series(False, index=out.index)
    out["_treatment_active"] = (prior_active | active.reset_index(drop=True)).to_numpy(dtype=bool)
    active_days = int(out.groupby("trade_date")["_treatment_active"].max().sum()) if not out.empty else 0
    total_days = int(out["trade_date"].nunique()) if not out.empty else 0
    return (
        out,
        "day_state_absolute_calibration="
        f"k{int(neighbor_days)},active_days={active_days}/{total_days},"
        f"mean_expected={float(exp.mean()):+.2f},p10_expected={float(exp.quantile(0.10)):+.2f}",
    )


def _apply_day_state_deployability_abstention(
    pred: pd.DataFrame,
    train_df: pd.DataFrame,
    *,
    label_col: str,
    neighbor_days: int = 20,
    min_expected_return_pct: float = 0.0,
    min_expected_positive_rate_pct: float = 48.0,
    max_expected_left_tail_rate_pct: float = 45.0,
) -> tuple[pd.DataFrame, str]:
    out = pred.copy()
    train_state = _training_day_deployability_state(train_df, label_col=label_col)
    test_state = _day_state_frame(out)
    exp_ret = _knn_day_expectation(
        train_state,
        test_state,
        target_col="deploy_day_all_mean_return_pct",
        neighbor_days=int(neighbor_days),
    )
    exp_pos = _knn_day_expectation(
        train_state,
        test_state,
        target_col="deploy_day_positive_rate_pct",
        neighbor_days=int(neighbor_days),
    )
    exp_tail = _knn_day_expectation(
        train_state,
        test_state,
        target_col="deploy_day_left_tail_rate_pct",
        neighbor_days=int(neighbor_days),
    )
    if exp_ret.empty or exp_pos.empty or exp_tail.empty:
        out["_deploy_signal"] = True
        return out, "day_state_deployability_abstention=no_day_state_fallback_all_deploy"
    day = pd.to_datetime(out["trade_date"], errors="coerce").dt.normalize()
    ret_row = day.map(exp_ret).fillna(0.0).astype(float)
    pos_row = day.map(exp_pos).fillna(0.0).astype(float)
    tail_row = day.map(exp_tail).fillna(100.0).astype(float)
    deploy = (
        ret_row.ge(float(min_expected_return_pct))
        & pos_row.ge(float(min_expected_positive_rate_pct))
        & tail_row.le(float(max_expected_left_tail_rate_pct))
    )
    prior = out["_deploy_signal"].astype(bool) if "_deploy_signal" in out.columns else pd.Series(True, index=out.index)
    out["_deploy_signal"] = (prior & deploy.reset_index(drop=True)).to_numpy(dtype=bool)
    out["_day_deploy_expected_return_pct"] = ret_row.to_numpy(dtype=float)
    out["_day_deploy_expected_positive_rate_pct"] = pos_row.to_numpy(dtype=float)
    out["_day_deploy_expected_left_tail_rate_pct"] = tail_row.to_numpy(dtype=float)
    prior_active = out["_treatment_active"].astype(bool) if "_treatment_active" in out.columns else pd.Series(False, index=out.index)
    out["_treatment_active"] = (prior_active | (~deploy).reset_index(drop=True)).to_numpy(dtype=bool)
    deploy_days = int(out.groupby("trade_date")["_deploy_signal"].max().sum()) if not out.empty else 0
    total_days = int(out["trade_date"].nunique()) if not out.empty else 0
    return (
        out,
        "day_state_deployability_abstention="
        f"k{int(neighbor_days)},deploy_days={deploy_days}/{total_days},"
        f"mean_expected={float(ret_row.mean()):+.2f},mean_pos_rate={float(pos_row.mean()):.1f},"
        f"mean_left_tail={float(tail_row.mean()):.1f},"
        f"min_return={float(min_expected_return_pct):+.2f},"
        f"min_pos_rate={float(min_expected_positive_rate_pct):.1f},"
        f"max_left_tail={float(max_expected_left_tail_rate_pct):.1f}",
    )


def _deployability_expectations(
    train_state: pd.DataFrame,
    test_state: pd.DataFrame,
    *,
    neighbor_days: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    exp_ret = _knn_day_expectation(
        train_state,
        test_state,
        target_col="deploy_day_all_mean_return_pct",
        neighbor_days=int(neighbor_days),
    )
    exp_pos = _knn_day_expectation(
        train_state,
        test_state,
        target_col="deploy_day_positive_rate_pct",
        neighbor_days=int(neighbor_days),
    )
    exp_tail = _knn_day_expectation(
        train_state,
        test_state,
        target_col="deploy_day_left_tail_rate_pct",
        neighbor_days=int(neighbor_days),
    )
    return exp_ret, exp_pos, exp_tail


def _choose_validated_deployability_thresholds(
    fit_state: pd.DataFrame,
    valid_state: pd.DataFrame,
    *,
    neighbor_days: int,
    base_min_expected_return_pct: float,
    min_expected_positive_rate_pct: float,
    max_expected_left_tail_rate_pct: float,
    min_validation_deploy_rate_pct: float,
) -> tuple[float, float, pd.DataFrame]:
    exp_ret, exp_pos, exp_tail = _deployability_expectations(fit_state, valid_state, neighbor_days=int(neighbor_days))
    if exp_ret.empty or exp_pos.empty or exp_tail.empty or valid_state.empty:
        return float(base_min_expected_return_pct), 0.0, pd.DataFrame()
    work = valid_state[["trade_date", "deploy_day_all_mean_return_pct"]].copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["expected_return_pct"] = work["trade_date"].map(exp_ret).astype(float)
    work["expected_positive_rate_pct"] = work["trade_date"].map(exp_pos).astype(float)
    work["expected_left_tail_rate_pct"] = work["trade_date"].map(exp_tail).astype(float)
    work = work.dropna(subset=["expected_return_pct", "expected_positive_rate_pct", "expected_left_tail_rate_pct", "deploy_day_all_mean_return_pct"])
    if work.empty:
        return float(base_min_expected_return_pct), 0.0, pd.DataFrame()
    raw_candidates = [float(base_min_expected_return_pct)]
    raw_candidates.extend(float(x) for x in work["expected_return_pct"].quantile([0.25, 0.40, 0.50, 0.60, 0.70, 0.80]).dropna().tolist())
    candidates = sorted(set(round(x, 6) for x in raw_candidates))
    rows = []
    for threshold in candidates:
        deploy = (
            work["expected_return_pct"].ge(float(threshold))
            & work["expected_positive_rate_pct"].ge(float(min_expected_positive_rate_pct))
            & work["expected_left_tail_rate_pct"].le(float(max_expected_left_tail_rate_pct))
        )
        rate = float(deploy.mean() * 100.0) if len(deploy) else 0.0
        mean_ret = _safe_float(work.loc[deploy, "deploy_day_all_mean_return_pct"].mean(), 0.0) if bool(deploy.any()) else -999.0
        rows.append(
            {
                "threshold": float(threshold),
                "validation_deploy_rate_pct": rate,
                "validation_deployed_mean_return_pct": mean_ret,
            }
        )
    grid = pd.DataFrame(rows)
    eligible = grid[grid["validation_deploy_rate_pct"].ge(float(min_validation_deploy_rate_pct))].copy()
    if eligible.empty:
        eligible = grid.copy()
    positive = eligible[eligible["validation_deployed_mean_return_pct"].gt(0.0)].copy()
    ranked = positive if not positive.empty else eligible
    ranked = ranked.sort_values(
        ["validation_deployed_mean_return_pct", "validation_deploy_rate_pct", "threshold"],
        ascending=[False, False, True],
    )
    best = ranked.iloc[0]
    return (
        _safe_float(best.get("threshold"), float(base_min_expected_return_pct)),
        _safe_float(best.get("validation_deploy_rate_pct"), 0.0),
        grid,
    )


def _apply_validated_day_state_deployability_abstention(
    pred: pd.DataFrame,
    fit_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    *,
    label_col: str,
    neighbor_days: int = 20,
    min_expected_return_pct: float = 0.0,
    min_expected_positive_rate_pct: float = 48.0,
    max_expected_left_tail_rate_pct: float = 45.0,
    min_validation_deploy_rate_pct: float = 50.0,
) -> tuple[pd.DataFrame, str]:
    out = pred.copy()
    fit_state = _training_day_deployability_state(fit_df, label_col=label_col)
    valid_state = _training_day_deployability_state(valid_df, label_col=label_col)
    if fit_state.empty or valid_state.empty:
        return _apply_day_state_deployability_abstention(
            out,
            fit_df,
            label_col=label_col,
            neighbor_days=int(neighbor_days),
            min_expected_return_pct=float(min_expected_return_pct),
            min_expected_positive_rate_pct=float(min_expected_positive_rate_pct),
            max_expected_left_tail_rate_pct=float(max_expected_left_tail_rate_pct),
        )
    threshold, valid_deploy_rate, grid = _choose_validated_deployability_thresholds(
        fit_state,
        valid_state,
        neighbor_days=int(neighbor_days),
        base_min_expected_return_pct=float(min_expected_return_pct),
        min_expected_positive_rate_pct=float(min_expected_positive_rate_pct),
        max_expected_left_tail_rate_pct=float(max_expected_left_tail_rate_pct),
        min_validation_deploy_rate_pct=float(min_validation_deploy_rate_pct),
    )
    out, note = _apply_day_state_deployability_abstention(
        out,
        fit_df,
        label_col=label_col,
        neighbor_days=int(neighbor_days),
        min_expected_return_pct=float(threshold),
        min_expected_positive_rate_pct=float(min_expected_positive_rate_pct),
        max_expected_left_tail_rate_pct=float(max_expected_left_tail_rate_pct),
    )
    best_valid_mean = 0.0
    if not grid.empty:
        hit = grid[np.isclose(pd.to_numeric(grid["threshold"], errors="coerce"), float(threshold))]
        if not hit.empty:
            best_valid_mean = _safe_float(hit["validation_deployed_mean_return_pct"].iloc[0], 0.0)
    return (
        out,
        "validated_" + note
        + f";validated_threshold={float(threshold):+.2f},"
        + f"validation_deploy_rate={float(valid_deploy_rate):.1f},"
        + f"validation_deployed_mean={float(best_valid_mean):+.2f}",
    )


def _regime_absolute_return_allowlist(
    train_df: pd.DataFrame,
    *,
    label_col: str,
    min_regime_mean_return_pct: float = 0.0,
) -> tuple[set[str], pd.DataFrame]:
    if train_df.empty or "market_regime_exante" not in train_df.columns or label_col not in train_df.columns:
        return set(), pd.DataFrame()
    work = train_df[["trade_date", "market_regime_exante", label_col]].copy()
    work[label_col] = pd.to_numeric(work[label_col], errors="coerce")
    work = work.dropna(subset=[label_col])
    if work.empty:
        return set(), pd.DataFrame()
    day = (
        work.groupby(["trade_date", "market_regime_exante"], sort=True)[label_col]
        .mean()
        .reset_index(name="day_all_mean_return_pct")
    )
    summary = (
        day.groupby("market_regime_exante", as_index=False)
        .agg(
            train_days=("trade_date", "nunique"),
            train_day_mean_return_pct=("day_all_mean_return_pct", "mean"),
            train_positive_day_rate_pct=("day_all_mean_return_pct", lambda s: float((pd.to_numeric(s, errors="coerce") > 0.0).mean() * 100.0)),
        )
        .sort_values("market_regime_exante")
    )
    allowed = set(
        summary[
            pd.to_numeric(summary["train_day_mean_return_pct"], errors="coerce").fillna(0.0)
            > float(min_regime_mean_return_pct)
        ]["market_regime_exante"].astype(str)
    )
    return allowed, summary


def _apply_day_level_absolute_veto(
    pred: pd.DataFrame,
    train_df: pd.DataFrame,
    *,
    label_col: str,
    min_regime_mean_return_pct: float = 0.0,
) -> tuple[pd.DataFrame, str]:
    out = pred.copy()
    allowed, summary = _regime_absolute_return_allowlist(
        train_df,
        label_col=label_col,
        min_regime_mean_return_pct=float(min_regime_mean_return_pct),
    )
    if not allowed:
        out["_deploy_signal"] = True
        return out, "day_level_absolute_veto=no_allowed_regime_fallback_all_deploy"
    regimes = out.get("market_regime_exante", pd.Series("neutral", index=out.index)).fillna("neutral").astype(str)
    out["_deploy_signal"] = regimes.isin(allowed).to_numpy(dtype=bool)
    rate = float(out.groupby("trade_date")["_deploy_signal"].max().mean() * 100.0) if "trade_date" in out.columns and not out.empty else 0.0
    regime_bits = []
    if not summary.empty:
        for r in summary.itertuples(index=False):
            regime_bits.append(
                f"{getattr(r, 'market_regime_exante')}:{_safe_float(getattr(r, 'train_day_mean_return_pct', 0.0)):+.2f}"
            )
    return out, f"day_level_absolute_veto_allowed={','.join(sorted(allowed))};deploy_day_rate={rate:.1f};train_regime_mean={';'.join(regime_bits)}"


def _pos52w_beta_overlay_allowlist(
    train_df: pd.DataFrame,
    *,
    label_col: str,
    top_n: int,
) -> tuple[set[str], pd.DataFrame]:
    if train_df.empty or "market_regime_exante" not in train_df.columns or label_col not in train_df.columns:
        return set(), pd.DataFrame()
    work = train_df.copy()
    work["_pos52w_beta_score"] = _apply_pos52w_beta_overlay(
        work.assign(pred=np.zeros(len(work), dtype=float)),
        pos_weight=1.0,
        beta_weight=0.50,
    )
    rows = []
    for regime, g in work.groupby(work["market_regime_exante"].fillna("neutral").astype(str), sort=True):
        row = summarize_predictions(g, score_col="_pos52w_beta_score", label_col=label_col, top_n=int(top_n), direction="desc")
        rows.append({"market_regime_exante": str(regime), **row, "failure_label": _failure_label(row)})
    summary = pd.DataFrame(rows)
    if summary.empty:
        return set(), summary
    allowed = set(
        summary[
            (pd.to_numeric(summary["top_mean_return_pct"], errors="coerce").fillna(0.0) > 0.0)
            & (pd.to_numeric(summary["top_minus_all_pct"], errors="coerce").fillna(0.0) > 0.0)
            & (pd.to_numeric(summary["top_minus_bottom_pct"], errors="coerce").fillna(0.0) > 0.0)
        ]["market_regime_exante"].astype(str)
    )
    return allowed, summary


def _pos52w_beta_day_opportunity_state(
    train_df: pd.DataFrame,
    *,
    label_col: str,
    top_n: int,
) -> pd.DataFrame:
    if train_df.empty or label_col not in train_df.columns or "trade_date" not in train_df.columns:
        return pd.DataFrame()
    work = train_df.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work = work[work["trade_date"].notna()].copy()
    work["_pos52w_beta_score"] = _apply_pos52w_beta_overlay(
        work.assign(pred=np.zeros(len(work), dtype=float)),
        pos_weight=1.0,
        beta_weight=0.50,
    )
    rows = []
    for trade_date, g in work.groupby("trade_date", sort=True):
        row = summarize_predictions(g, score_col="_pos52w_beta_score", label_col=label_col, top_n=int(top_n), direction="desc")
        rows.append(
            {
                "trade_date": pd.Timestamp(trade_date).normalize(),
                "pos52w_beta_train_top_return_pct": _safe_float(row.get("top_mean_return_pct", 0.0)),
                "pos52w_beta_train_top_minus_all_pct": _safe_float(row.get("top_minus_all_pct", 0.0)),
                "pos52w_beta_train_top_minus_bottom_pct": _safe_float(row.get("top_minus_bottom_pct", 0.0)),
            }
        )
    perf = pd.DataFrame(rows)
    state = _day_state_frame(train_df)
    return state.merge(perf, on="trade_date", how="inner") if not state.empty and not perf.empty else pd.DataFrame()


def _apply_day_state_pos52w_beta_opportunity_overlay(
    pred: pd.DataFrame,
    train_df: pd.DataFrame,
    *,
    label_col: str,
    top_n: int,
    neighbor_days: int = 20,
    min_expected_edge_pct: float = 0.0,
    pos_weight: float = 0.30,
    beta_weight: float = 0.15,
) -> tuple[pd.DataFrame, str]:
    out = pred.copy()
    train_state = _pos52w_beta_day_opportunity_state(train_df, label_col=label_col, top_n=int(top_n))
    test_state = _day_state_frame(out)
    edge = _knn_day_expectation(
        train_state,
        test_state,
        target_col="pos52w_beta_train_top_minus_all_pct",
        neighbor_days=int(neighbor_days),
    )
    top = _knn_day_expectation(
        train_state,
        test_state,
        target_col="pos52w_beta_train_top_return_pct",
        neighbor_days=int(neighbor_days),
    )
    bottom_edge = _knn_day_expectation(
        train_state,
        test_state,
        target_col="pos52w_beta_train_top_minus_bottom_pct",
        neighbor_days=int(neighbor_days),
    )
    if edge.empty or top.empty or bottom_edge.empty:
        return out, "day_state_pos52w_beta_opportunity=no_day_state"
    day = pd.to_datetime(out["trade_date"], errors="coerce").dt.normalize()
    edge_row = day.map(edge).fillna(0.0).astype(float)
    top_row = day.map(top).fillna(0.0).astype(float)
    bottom_row = day.map(bottom_edge).fillna(0.0).astype(float)
    active = edge_row.gt(float(min_expected_edge_pct)) & top_row.gt(0.0) & bottom_row.gt(0.0)
    overlay = _apply_pos52w_beta_overlay(out, pos_weight=float(pos_weight), beta_weight=float(beta_weight))
    out.loc[active.to_numpy(dtype=bool), "pred"] = overlay.loc[active.to_numpy(dtype=bool)].to_numpy(dtype=float)
    out["_day_pos52w_beta_expected_edge_pct"] = edge_row.to_numpy(dtype=float)
    out["_pos52w_beta_opportunity_active"] = active.to_numpy(dtype=bool)
    prior_active = out["_treatment_active"].astype(bool) if "_treatment_active" in out.columns else pd.Series(False, index=out.index)
    out["_treatment_active"] = (prior_active | active.reset_index(drop=True)).to_numpy(dtype=bool)
    active_days = int(pd.Series(active.to_numpy(dtype=bool), index=out.index).groupby(out["trade_date"]).max().sum()) if not out.empty else 0
    total_days = int(out["trade_date"].nunique()) if not out.empty else 0
    return (
        out,
        "day_state_pos52w_beta_opportunity="
        f"k{int(neighbor_days)},active_days={active_days}/{total_days},"
        f"mean_edge={float(edge_row.mean()):+.2f},p60_edge={float(edge_row.quantile(0.60)):+.2f},"
        f"min_edge={float(min_expected_edge_pct):+.2f}",
    )


def _apply_conditional_pos52w_beta_overlay(
    pred: pd.DataFrame,
    train_df: pd.DataFrame,
    *,
    label_col: str,
    top_n: int,
    pos_weight: float = 0.30,
    beta_weight: float = 0.15,
) -> tuple[pd.DataFrame, str]:
    out = pred.copy()
    allowed, summary = _pos52w_beta_overlay_allowlist(train_df, label_col=label_col, top_n=int(top_n))
    if not allowed:
        return out, "conditional_pos52w_beta_overlay=no_allowed_regime"
    overlay = _apply_pos52w_beta_overlay(out, pos_weight=float(pos_weight), beta_weight=float(beta_weight))
    regimes = out.get("market_regime_exante", pd.Series("neutral", index=out.index)).fillna("neutral").astype(str)
    mask = regimes.isin(allowed)
    out.loc[mask, "pred"] = overlay.loc[mask].to_numpy(dtype=float)
    regime_bits = []
    if not summary.empty:
        for r in summary.itertuples(index=False):
            regime_bits.append(
                f"{getattr(r, 'market_regime_exante')}:top={_safe_float(getattr(r, 'top_mean_return_pct', 0.0)):+.2f},"
                f"spread={_safe_float(getattr(r, 'top_minus_all_pct', 0.0)):+.2f},"
                f"ic={_safe_float(getattr(r, 'rank_ic_mean', 0.0)):+.3f}"
            )
    return out, f"conditional_pos52w_beta_allowed={','.join(sorted(allowed))};train_overlay={';'.join(regime_bits)}"


def _apply_treatment_adjustments(
    pred: pd.DataFrame,
    *,
    variant: str,
    fit: pd.DataFrame,
    valid: pd.DataFrame,
    test_eval: pd.DataFrame,
    features: list[str],
    label_col: str,
    num_boost_round: int,
    early_stopping_rounds: int,
    seed: int,
    num_threads: int,
    recency_half_life_days: float,
    min_regime_train_rows: int,
    min_regime_train_days: int,
    top_n: int,
    day_state_neighbor_days: int,
    day_opportunity_min_edge_pct: float,
    abstention_min_expected_return_pct: float,
    abstention_min_positive_rate_pct: float,
    abstention_max_left_tail_rate_pct: float,
    abstention_min_validation_deploy_rate_pct: float,
) -> tuple[pd.DataFrame, str]:
    treatments = _variant_treatments(variant)
    if not treatments or pred.empty:
        return pred, ""
    out = pred.copy()
    notes = []
    if "absolute_return_blend" in treatments:
        abs_values, _, abs_note = _predict_regime_specific(
            fit,
            valid,
            test_eval,
            features=features,
            label_col=label_col,
            num_boost_round=int(num_boost_round),
            early_stopping_rounds=int(early_stopping_rounds),
            seed=int(seed) + 17,
            num_threads=max(1, int(num_threads)),
            recency_half_life_days=float(recency_half_life_days),
            min_regime_train_rows=int(min_regime_train_rows),
            min_regime_train_days=int(min_regime_train_days),
        )
        out["pred"] = _blend_with_absolute_return_calibrator(out, abs_values, abs_weight=0.35)
        notes.append("absolute_return_blend_weight=0.35")
        if abs_note:
            notes.append("absolute_return_calibrator=" + abs_note)
    if "pos52w_beta_overlay" in treatments:
        out["pred"] = _apply_pos52w_beta_overlay(out, pos_weight=0.30, beta_weight=0.15)
        notes.append("pos52w_beta_overlay=pos52w_0.30+beta_0.15")
    if "positive_hit_blend" in treatments:
        out, hit_note = _apply_positive_hit_blend(
            out,
            fit,
            valid,
            test_eval,
            features=features,
            label_col=label_col,
            num_boost_round=int(num_boost_round),
            early_stopping_rounds=int(early_stopping_rounds),
            seed=int(seed),
            num_threads=max(1, int(num_threads)),
            hit_weight=0.35,
        )
        notes.append(hit_note)
    if "positive_hit_deployability_abstention" in treatments:
        out, hit_abstention_note = _apply_positive_hit_deployability_abstention(
            out,
            fit,
            valid,
            test_eval,
            features=features,
            label_col=label_col,
            top_n=int(top_n),
            num_boost_round=int(num_boost_round),
            early_stopping_rounds=int(early_stopping_rounds),
            seed=int(seed),
            num_threads=max(1, int(num_threads)),
            min_validation_deploy_rate_pct=float(abstention_min_validation_deploy_rate_pct),
        )
        notes.append(hit_abstention_note)
    if "conditional_pos52w_beta_overlay" in treatments:
        out, overlay_note = _apply_conditional_pos52w_beta_overlay(
            out,
            fit,
            label_col=label_col,
            top_n=int(top_n),
            pos_weight=0.30,
            beta_weight=0.15,
        )
        notes.append(overlay_note)
    if "day_state_absolute_calibration" in treatments:
        out, calibration_note = _apply_day_state_absolute_calibration(
            out,
            fit,
            label_col=label_col,
            neighbor_days=int(day_state_neighbor_days),
            max_defensive_weight=0.55,
        )
        notes.append(calibration_note)
    if "day_state_deployability_abstention" in treatments:
        out, abstention_note = _apply_day_state_deployability_abstention(
            out,
            fit,
            label_col=label_col,
            neighbor_days=int(day_state_neighbor_days),
            min_expected_return_pct=float(abstention_min_expected_return_pct),
            min_expected_positive_rate_pct=float(abstention_min_positive_rate_pct),
            max_expected_left_tail_rate_pct=float(abstention_max_left_tail_rate_pct),
        )
        notes.append(abstention_note)
    if "validated_day_state_deployability_abstention" in treatments:
        out, abstention_note = _apply_validated_day_state_deployability_abstention(
            out,
            fit,
            valid,
            label_col=label_col,
            neighbor_days=int(day_state_neighbor_days),
            min_expected_return_pct=float(abstention_min_expected_return_pct),
            min_expected_positive_rate_pct=float(abstention_min_positive_rate_pct),
            max_expected_left_tail_rate_pct=float(abstention_max_left_tail_rate_pct),
            min_validation_deploy_rate_pct=float(abstention_min_validation_deploy_rate_pct),
        )
        notes.append(abstention_note)
    if "day_state_pos52w_beta_opportunity_overlay" in treatments:
        out, opportunity_note = _apply_day_state_pos52w_beta_opportunity_overlay(
            out,
            fit,
            label_col=label_col,
            top_n=int(top_n),
            neighbor_days=int(day_state_neighbor_days),
            min_expected_edge_pct=float(day_opportunity_min_edge_pct),
            pos_weight=0.30,
            beta_weight=0.15,
        )
        notes.append(opportunity_note)
    if "day_level_absolute_veto" in treatments:
        out, veto_note = _apply_day_level_absolute_veto(
            out,
            fit,
            label_col=label_col,
            min_regime_mean_return_pct=0.0,
        )
        notes.append(veto_note)
    return out, ";".join(notes)


def build_ensemble_prediction(
    pred_cache: dict[str, pd.DataFrame],
    variant: str,
) -> tuple[pd.DataFrame, str]:
    deps = ENSEMBLE_VARIANTS.get(str(variant), [])
    missing = [d for d in deps if d not in pred_cache]
    if missing:
        return pd.DataFrame(), f"missing_dependencies={','.join(missing)}"
    base_cols = ["trade_date", "ts_code", "pct_chg", "amount", "close", "market_regime_exante", "label"]
    merged: pd.DataFrame | None = None
    for dep in deps:
        part = pred_cache[dep].loc[:, [c for c in base_cols + ["pred"] if c in pred_cache[dep].columns]].copy()
        part[f"pred_{dep}"] = _daily_zscore_score(part, "pred")
        part = part.drop(columns=["pred"])
        if merged is None:
            merged = part
        else:
            keep_cols = ["trade_date", "ts_code", f"pred_{dep}"]
            merged = merged.merge(part[keep_cols], on=["trade_date", "ts_code"], how="inner")
    if merged is None or merged.empty:
        return pd.DataFrame(), "empty_ensemble"
    pred_cols = [f"pred_{dep}" for dep in deps]
    merged["pred"] = merged[pred_cols].mean(axis=1)
    return merged[[c for c in base_cols + ["pred"] if c in merged.columns]].copy(), f"ensemble_deps={','.join(deps)}"


def build_instability_verdict(variant_summary: pd.DataFrame, focus_folds: list[int]) -> dict[str, object]:
    base = variant_summary[
        variant_summary["variant"].astype(str).eq("baseline")
        & variant_summary["horizon"].astype(int).eq(int(variant_summary["horizon"].astype(int).mode().iloc[0]))
    ].copy() if not variant_summary.empty else pd.DataFrame()
    if not base.empty:
        base_focus = base[base["fold"].astype(int).isin([int(x) for x in focus_folds])]
        base_pass_rate = float(base_focus["alpha_gate_pass"].astype(bool).mean() * 100.0) if not base_focus.empty else 0.0
        base_top = _safe_float(base_focus["top_mean_return_pct"].mean(), 0.0) if not base_focus.empty else 0.0
    else:
        base_pass_rate = 0.0
        base_top = 0.0
    by_variant = (
        variant_summary[variant_summary["fold"].astype(int).isin([int(x) for x in focus_folds])]
        .groupby("variant", as_index=False)
        .agg(
            pass_rate_pct=("alpha_gate_pass", lambda s: float(pd.Series(s).astype(bool).mean() * 100.0)),
            mean_top_return_pct=("top_mean_return_pct", "mean"),
            mean_top_minus_all_pct=("top_minus_all_pct", "mean"),
            mean_rank_ic=("rank_ic_mean", "mean"),
        )
        if not variant_summary.empty
        else pd.DataFrame()
    )
    full_passing = by_variant[by_variant["pass_rate_pct"].ge(100.0)] if not by_variant.empty else pd.DataFrame()
    partial_passing = by_variant[by_variant["pass_rate_pct"].gt(max(base_pass_rate, 0.0))] if not by_variant.empty else pd.DataFrame()
    if not full_passing.empty:
        best = full_passing.sort_values(["pass_rate_pct", "mean_top_minus_all_pct", "mean_rank_ic"], ascending=[False, False, False]).iloc[0].to_dict()
        verdict = "instability_variant_has_focus_fix"
        action = "variant stabilizes all focused failing folds; rerun full 7-fold walk-forward before any profile/P2 work"
    elif not partial_passing.empty:
        best = partial_passing.sort_values(["pass_rate_pct", "mean_top_minus_all_pct", "mean_rank_ic"], ascending=[False, False, False]).iloc[0].to_dict()
        verdict = "instability_variant_partial_fix_only"
        action = "variant rescues only part of the focused failing folds; do not build a profile until remaining fold failure is explained"
    else:
        best = by_variant.sort_values(["mean_top_minus_all_pct", "mean_rank_ic"], ascending=[False, False]).head(1)
        best = best.iloc[0].to_dict() if not best.empty else {}
        verdict = "instability_not_fixed_by_basic_variants"
        action = "basic weighting/objective/drift variants do not stabilize failing folds; focus on regime-specific model or new features"
    return {
        "overall_verdict": verdict,
        "recommended_next_action": action,
        "focus_folds": ",".join(str(int(x)) for x in focus_folds),
        "baseline_focus_pass_rate_pct": float(base_pass_rate),
        "baseline_focus_top_mean_return_pct": float(base_top),
        "best_variant": str(best.get("variant", "")),
        "best_variant_pass_rate_pct": _safe_float(best.get("pass_rate_pct", 0.0)),
        "best_variant_mean_top_return_pct": _safe_float(best.get("mean_top_return_pct", 0.0)),
        "best_variant_mean_top_minus_all_pct": _safe_float(best.get("mean_top_minus_all_pct", 0.0)),
        "best_variant_mean_rank_ic": _safe_float(best.get("mean_rank_ic", 0.0)),
    }


def build_fold_attribution(
    variant_summary: pd.DataFrame,
    regime_summary: pd.DataFrame,
    importance: pd.DataFrame,
    exposure: pd.DataFrame,
    *,
    focus_folds: list[int],
    drift_psi_threshold: float = 0.30,
    drift_std_diff_threshold: float = 0.60,
) -> pd.DataFrame:
    rows = []
    focus = [int(x) for x in focus_folds]
    for fold in focus:
        fv = variant_summary[variant_summary["fold"].astype(int).eq(int(fold))].copy() if not variant_summary.empty else pd.DataFrame()
        if fv.empty:
            continue
        base = fv[fv["variant"].astype(str).eq("baseline")].head(1)
        base_row = base.iloc[0].to_dict() if not base.empty else {}
        alts = fv[~fv["variant"].astype(str).eq("baseline")].copy()
        if not alts.empty:
            alts["_pass"] = alts["alpha_gate_pass"].astype(bool).astype(int)
            best = alts.sort_values(["_pass", "top_minus_all_pct", "rank_ic_mean"], ascending=[False, False, False]).iloc[0].to_dict()
        else:
            best = {}

        base_pass = bool(base_row.get("alpha_gate_pass", False))
        best_pass = bool(best.get("alpha_gate_pass", False))
        if base_pass:
            fold_verdict = "baseline_pass"
        elif best_pass:
            fold_verdict = "variant_rescued_fold"
        elif _safe_float(base_row.get("top_mean_return_pct", 0.0)) <= 0.0:
            fold_verdict = "absolute_top_bucket_failure"
        elif _safe_float(base_row.get("top_minus_all_pct", 0.0)) <= 0.0 and _safe_float(base_row.get("top_minus_bottom_pct", 0.0)) <= 0.0:
            fold_verdict = "top_bucket_selection_inversion"
        elif _safe_float(base_row.get("rank_ic_mean", 0.0)) <= 0.0:
            fold_verdict = "rank_order_breakdown"
        else:
            fold_verdict = "weak_pool_relative_alpha"

        freg = regime_summary[
            regime_summary["fold"].astype(int).eq(int(fold)) & regime_summary["variant"].astype(str).eq("baseline")
        ].copy() if not regime_summary.empty else pd.DataFrame()
        if not freg.empty:
            freg["_bad"] = freg["failure_label"].astype(str).ne("pass")
            bad_regimes = freg[freg["_bad"]].sort_values(["top_minus_all_pct", "top_mean_return_pct"], ascending=[True, True])
            regime_failures = [
                f"{r['regime_proxy_expost']}:{r['failure_label']}"
                for _, r in bad_regimes.iterrows()
            ]
            worst_regime = str(bad_regimes.iloc[0]["regime_proxy_expost"]) if not bad_regimes.empty else ""
        else:
            regime_failures = []
            worst_regime = ""

        fimp = importance[
            importance["fold"].astype(int).eq(int(fold)) & importance["variant"].astype(str).eq("baseline")
        ].copy() if not importance.empty else pd.DataFrame()
        if not fimp.empty:
            fimp["importance_share_pct"] = pd.to_numeric(fimp["importance_share_pct"], errors="coerce").fillna(0.0)
            fimp["psi"] = pd.to_numeric(fimp["psi"], errors="coerce").fillna(0.0)
            fimp["std_mean_diff"] = pd.to_numeric(fimp["std_mean_diff"], errors="coerce").fillna(0.0)
            drift_imp = fimp[
                fimp["importance_share_pct"].ge(1.0)
                & (fimp["psi"].ge(float(drift_psi_threshold)) | fimp["std_mean_diff"].ge(float(drift_std_diff_threshold)))
            ].sort_values(["importance_share_pct", "psi", "std_mean_diff"], ascending=[False, False, False])
            drift_imp_features = [
                f"{r['feature']}(share={_safe_float(r['importance_share_pct']):.2f},psi={_safe_float(r['psi']):.2f},std={_safe_float(r['std_mean_diff']):.2f})"
                for _, r in drift_imp.head(5).iterrows()
            ]
        else:
            drift_imp_features = []

        fexp = exposure[
            exposure["fold"].astype(int).eq(int(fold)) & exposure["variant"].astype(str).eq("baseline")
        ].copy() if not exposure.empty else pd.DataFrame()
        if not fexp.empty:
            fexp["abs_top_minus_all"] = pd.to_numeric(fexp["top_minus_all"], errors="coerce").abs().fillna(0.0)
            top_exposures = [
                f"{r['feature']}:{_safe_float(r['top_minus_all']):+.3f}"
                for _, r in fexp.sort_values("abs_top_minus_all", ascending=False).head(8).iterrows()
            ]
        else:
            top_exposures = []

        rows.append(
            {
                "fold": int(fold),
                "test_start": str(base_row.get("test_start", "")),
                "test_end": str(base_row.get("test_end", "")),
                "baseline_failure_label": str(base_row.get("failure_label", "")),
                "fold_attribution_verdict": fold_verdict,
                "baseline_top_mean_return_pct": _safe_float(base_row.get("top_mean_return_pct", 0.0)),
                "baseline_all_mean_return_pct": _safe_float(base_row.get("all_mean_return_pct", 0.0)),
                "baseline_top_minus_all_pct": _safe_float(base_row.get("top_minus_all_pct", 0.0)),
                "baseline_top_minus_bottom_pct": _safe_float(base_row.get("top_minus_bottom_pct", 0.0)),
                "baseline_rank_ic_mean": _safe_float(base_row.get("rank_ic_mean", 0.0)),
                "best_variant": str(best.get("variant", "")),
                "best_variant_alpha_gate_pass": bool(best_pass),
                "best_variant_failure_label": str(best.get("failure_label", "")),
                "best_variant_top_mean_return_pct": _safe_float(best.get("top_mean_return_pct", 0.0)),
                "best_variant_top_minus_all_pct": _safe_float(best.get("top_minus_all_pct", 0.0)),
                "best_variant_rank_ic_mean": _safe_float(best.get("rank_ic_mean", 0.0)),
                "worst_baseline_regime": worst_regime,
                "baseline_regime_failures": ";".join(regime_failures),
                "drifted_important_features": ";".join(drift_imp_features),
                "baseline_top_feature_exposure": ";".join(top_exposures),
            }
        )
    return pd.DataFrame(rows)


def build_variant_family_summary(
    variant_summary: pd.DataFrame,
    *,
    critical_folds: list[int],
    min_fold_pass_rate_pct: float = 50.0,
) -> pd.DataFrame:
    if variant_summary.empty:
        return pd.DataFrame()
    rows = []
    critical = [int(x) for x in critical_folds]
    for variant, g in variant_summary.groupby("variant", sort=True):
        work = g.copy()
        work["alpha_gate_pass"] = work["alpha_gate_pass"].astype(bool)
        pass_rate = float(work["alpha_gate_pass"].mean() * 100.0)
        crit = work[work["fold"].astype(int).isin(critical)].copy()
        critical_pass = bool(not crit.empty and crit["alpha_gate_pass"].astype(bool).all())
        mean_top = _safe_float(work["top_mean_return_pct"].mean(), 0.0)
        mean_spread = _safe_float(work["top_minus_all_pct"].mean(), 0.0)
        mean_rank_ic = _safe_float(work["rank_ic_mean"].mean(), 0.0)
        deploy_rate = pd.to_numeric(work.get("deployment_day_rate_pct", pd.Series([100.0])), errors="coerce").fillna(100.0)
        active_rate = pd.to_numeric(work.get("treatment_active_day_rate_pct", pd.Series([0.0])), errors="coerce").fillna(0.0)
        if pass_rate >= float(min_fold_pass_rate_pct) and critical_pass and mean_top > 0.0 and mean_spread > 0.0 and mean_rank_ic > 0.0:
            verdict = "variant_model_gate_pass"
        elif not critical_pass:
            verdict = "critical_fold_failed"
        elif pass_rate < float(min_fold_pass_rate_pct):
            verdict = "split_unstable"
        else:
            verdict = "pooled_alpha_failed"
        fold7 = work[work["fold"].astype(int).eq(7)].head(1)
        fold6 = work[work["fold"].astype(int).eq(6)].head(1)
        rows.append(
            {
                "variant": str(variant),
                "fold_count": int(len(work)),
                "pass_fold_count": int(work["alpha_gate_pass"].sum()),
                "fold_pass_rate_pct": pass_rate,
                "critical_folds": ",".join(str(x) for x in critical),
                "critical_fold_pass": critical_pass,
                "mean_top_return_pct": mean_top,
                "mean_top_minus_all_pct": mean_spread,
                "mean_top_minus_bottom_pct": _safe_float(work["top_minus_bottom_pct"].mean(), 0.0),
                "mean_rank_ic": mean_rank_ic,
                "mean_deployment_day_rate_pct": _safe_float(deploy_rate.mean(), 100.0),
                "min_deployment_day_rate_pct": _safe_float(deploy_rate.min(), 100.0),
                "mean_treatment_active_day_rate_pct": _safe_float(active_rate.mean(), 0.0),
                "max_treatment_active_day_rate_pct": _safe_float(active_rate.max(), 0.0),
                "fold6_alpha_gate_pass": bool(fold6["alpha_gate_pass"].iloc[0]) if not fold6.empty else False,
                "fold6_top_mean_return_pct": _safe_float(fold6["top_mean_return_pct"].iloc[0], 0.0) if not fold6.empty else 0.0,
                "fold6_top_minus_all_pct": _safe_float(fold6["top_minus_all_pct"].iloc[0], 0.0) if not fold6.empty else 0.0,
                "fold7_alpha_gate_pass": bool(fold7["alpha_gate_pass"].iloc[0]) if not fold7.empty else False,
                "fold7_top_mean_return_pct": _safe_float(fold7["top_mean_return_pct"].iloc[0], 0.0) if not fold7.empty else 0.0,
                "fold7_top_minus_all_pct": _safe_float(fold7["top_minus_all_pct"].iloc[0], 0.0) if not fold7.empty else 0.0,
                "variant_family_verdict": verdict,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["variant_family_verdict", "fold_pass_rate_pct", "mean_top_minus_all_pct", "mean_rank_ic"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def append_prediction_diagnostics(
    *,
    pred: pd.DataFrame,
    variant: str,
    fold: int,
    horizon: int,
    win: dict[str, object],
    variant_features: list[str],
    usable_features: list[str],
    model_note: str,
    top_n: int,
    variant_drift: pd.DataFrame,
    imp: pd.DataFrame,
    variant_rows: list[dict[str, object]],
    regime_rows: list[dict[str, object]],
    importance_rows: list[dict[str, object]],
    exposure_rows: list[dict[str, object]],
    exante_regime_rows: list[dict[str, object]] | None = None,
    min_deployment_day_rate_pct: float = 0.0,
) -> None:
    raw_days = int(pred["trade_date"].nunique()) if "trade_date" in pred.columns and not pred.empty else 0
    deployment_day_rate_pct = 100.0
    deployed_days = raw_days
    vetoed_days = 0
    treatment_active_days = 0
    treatment_active_day_rate_pct = 0.0
    absolute_calibration_active_day_rate_pct = 0.0
    pos52w_beta_opportunity_active_day_rate_pct = 0.0
    mean_day_abs_expected_return_pct = 0.0
    mean_day_pos52w_beta_expected_edge_pct = 0.0
    mean_day_deploy_expected_return_pct = 0.0
    mean_day_deploy_expected_positive_rate_pct = 0.0
    mean_day_deploy_expected_left_tail_rate_pct = 0.0
    mean_day_hit_deploy_score = 0.0
    mean_positive_hit_prob = 0.0
    pred_eval = pred
    if "_deploy_signal" in pred.columns:
        deploy_by_day = pred.groupby("trade_date")["_deploy_signal"].max() if "trade_date" in pred.columns and not pred.empty else pd.Series(dtype=bool)
        deployed_days = int(pd.Series(deploy_by_day).astype(bool).sum()) if len(deploy_by_day) else 0
        vetoed_days = max(0, int(raw_days) - int(deployed_days))
        deployment_day_rate_pct = float(deployed_days / max(raw_days, 1) * 100.0)
        pred_eval = pred[pred["_deploy_signal"].astype(bool)].copy()
    if "_treatment_active" in pred.columns and "trade_date" in pred.columns and not pred.empty:
        active_by_day = pred.groupby("trade_date")["_treatment_active"].max()
        treatment_active_days = int(pd.Series(active_by_day).astype(bool).sum()) if len(active_by_day) else 0
        treatment_active_day_rate_pct = float(treatment_active_days / max(raw_days, 1) * 100.0)
    if "_absolute_calibration_active" in pred.columns and "trade_date" in pred.columns and not pred.empty:
        active_by_day = pred.groupby("trade_date")["_absolute_calibration_active"].max()
        absolute_calibration_active_day_rate_pct = float(pd.Series(active_by_day).astype(bool).sum() / max(raw_days, 1) * 100.0)
    if "_pos52w_beta_opportunity_active" in pred.columns and "trade_date" in pred.columns and not pred.empty:
        active_by_day = pred.groupby("trade_date")["_pos52w_beta_opportunity_active"].max()
        pos52w_beta_opportunity_active_day_rate_pct = float(pd.Series(active_by_day).astype(bool).sum() / max(raw_days, 1) * 100.0)
    if "_day_abs_expected_return_pct" in pred.columns:
        mean_day_abs_expected_return_pct = _safe_float(pd.to_numeric(pred["_day_abs_expected_return_pct"], errors="coerce").mean(), 0.0)
    if "_day_pos52w_beta_expected_edge_pct" in pred.columns:
        mean_day_pos52w_beta_expected_edge_pct = _safe_float(pd.to_numeric(pred["_day_pos52w_beta_expected_edge_pct"], errors="coerce").mean(), 0.0)
    if "_day_deploy_expected_return_pct" in pred.columns:
        mean_day_deploy_expected_return_pct = _safe_float(pd.to_numeric(pred["_day_deploy_expected_return_pct"], errors="coerce").mean(), 0.0)
    if "_day_deploy_expected_positive_rate_pct" in pred.columns:
        mean_day_deploy_expected_positive_rate_pct = _safe_float(
            pd.to_numeric(pred["_day_deploy_expected_positive_rate_pct"], errors="coerce").mean(),
            0.0,
        )
    if "_day_deploy_expected_left_tail_rate_pct" in pred.columns:
        mean_day_deploy_expected_left_tail_rate_pct = _safe_float(
            pd.to_numeric(pred["_day_deploy_expected_left_tail_rate_pct"], errors="coerce").mean(),
            0.0,
        )
    if "_day_hit_deploy_score" in pred.columns:
        mean_day_hit_deploy_score = _safe_float(pd.to_numeric(pred["_day_hit_deploy_score"], errors="coerce").mean(), 0.0)
    if "_positive_hit_prob" in pred.columns:
        mean_positive_hit_prob = _safe_float(pd.to_numeric(pred["_positive_hit_prob"], errors="coerce").mean(), 0.0)
    summary = summarize_predictions(pred_eval, score_col="pred", label_col="label", top_n=int(top_n), direction="desc")
    if deployment_day_rate_pct < float(min_deployment_day_rate_pct):
        summary["alpha_gate_pass"] = False
        prior = _failure_label(summary)
        summary["failure_label"] = "+".join(x for x in [prior, "deployment_day_rate_below_floor"] if x and x != "pass")
    variant_rows.append(
        {
            "fold": int(fold),
            "horizon": int(horizon),
            "variant": str(variant),
            "test_start": pd.Timestamp(win["test_start"]).strftime("%Y-%m-%d"),
            "test_end": pd.Timestamp(win["test_end"]).strftime("%Y-%m-%d"),
            "feature_count": int(len(variant_features)),
            "dropped_feature_count": int(len(set(usable_features) - set(variant_features))),
            "raw_days_before_veto": int(raw_days),
            "deployment_days": int(deployed_days),
            "vetoed_days": int(vetoed_days),
            "deployment_day_rate_pct": float(deployment_day_rate_pct),
            "treatment_active_days": int(treatment_active_days),
            "treatment_active_day_rate_pct": float(treatment_active_day_rate_pct),
            "absolute_calibration_active_day_rate_pct": float(absolute_calibration_active_day_rate_pct),
            "pos52w_beta_opportunity_active_day_rate_pct": float(pos52w_beta_opportunity_active_day_rate_pct),
            "mean_day_abs_expected_return_pct": float(mean_day_abs_expected_return_pct),
            "mean_day_pos52w_beta_expected_edge_pct": float(mean_day_pos52w_beta_expected_edge_pct),
            "mean_day_deploy_expected_return_pct": float(mean_day_deploy_expected_return_pct),
            "mean_day_deploy_expected_positive_rate_pct": float(mean_day_deploy_expected_positive_rate_pct),
            "mean_day_deploy_expected_left_tail_rate_pct": float(mean_day_deploy_expected_left_tail_rate_pct),
            "mean_day_hit_deploy_score": float(mean_day_hit_deploy_score),
            "mean_positive_hit_prob": float(mean_positive_hit_prob),
            "model_note": model_note,
            **summary,
            "failure_label": str(summary.get("failure_label") or _failure_label(summary)),
        }
    )
    reg = _regime_summary(pred_eval, top_n=int(top_n))
    for row in reg.to_dict(orient="records") if not reg.empty else []:
        regime_rows.append({"fold": int(fold), "horizon": int(horizon), "variant": str(variant), **row})
    if exante_regime_rows is not None:
        exreg = _exante_regime_summary(pred_eval, top_n=int(top_n))
        for row in exreg.to_dict(orient="records") if not exreg.empty else []:
            exante_regime_rows.append({"fold": int(fold), "horizon": int(horizon), "variant": str(variant), **row})
    drift_lookup = variant_drift.set_index("feature").to_dict(orient="index") if not variant_drift.empty and "feature" in variant_drift.columns else {}
    if not imp.empty:
        for _, row in imp.head(20).iterrows():
            d = drift_lookup.get(str(row["feature"]), {})
            importance_rows.append(
                {
                    "fold": int(fold),
                    "horizon": int(horizon),
                    "variant": str(variant),
                    "feature": str(row["feature"]),
                    "importance_gain": _safe_float(row["importance_gain"], 0.0),
                    "importance_share_pct": _safe_float(row["importance_share_pct"], 0.0),
                    "psi": _safe_float(d.get("psi", 0.0)),
                    "std_mean_diff": _safe_float(d.get("std_mean_diff", 0.0)),
                }
            )
    exp = _selected_feature_exposure(pred_eval, variant_features[:30], top_n=int(top_n))
    for row in exp.to_dict(orient="records") if not exp.empty else []:
        exposure_rows.append({"fold": int(fold), "horizon": int(horizon), "variant": str(variant), **row})


def main() -> int:
    p = argparse.ArgumentParser(description="Explain raw model fold instability")
    p.add_argument("--data-file", default=str(DATA_FILE))
    p.add_argument("--model-file", default="")
    p.add_argument("--features", default="")
    p.add_argument("--horizon", type=int, default=10)
    p.add_argument("--focus-folds", default="6,7")
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2026-04-14")
    p.add_argument("--train-months", type=int, default=24)
    p.add_argument("--test-months", type=int, default=4)
    p.add_argument("--step-months", type=int, default=4)
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--max-train-rows", type=int, default=100000)
    p.add_argument("--max-test-rows", type=int, default=0)
    p.add_argument(
        "--sample-mode",
        choices=["random", "date_stratified", "none"],
        default="random",
        help="diagnostic row sampling mode; date_stratified is deterministic by trade day",
    )
    p.add_argument("--num-boost-round", type=int, default=120)
    p.add_argument("--early-stopping-rounds", type=int, default=20)
    p.add_argument("--valid-months", type=int, default=3)
    p.add_argument("--variants", default=",".join(DEFAULT_VARIANTS))
    p.add_argument("--recency-half-life-days", type=float, default=240.0)
    p.add_argument("--drift-psi-threshold", type=float, default=0.30)
    p.add_argument("--drift-std-diff-threshold", type=float, default=0.60)
    p.add_argument("--critical-folds", default="7", help="folds that must pass before a model line can advance")
    p.add_argument("--min-fold-pass-rate-pct", type=float, default=50.0)
    p.add_argument(
        "--min-deployment-day-rate-pct",
        type=float,
        default=50.0,
        help="minimum deployed signal-day rate for day-veto variants to count as alpha-gate pass",
    )
    p.add_argument(
        "--day-state-neighbor-days",
        type=int,
        default=20,
        help="nearest train signal-day count for day-state calibration/opportunity treatments",
    )
    p.add_argument(
        "--state-matched-keep-day-rate",
        type=float,
        default=0.45,
        help="fraction of closest training signal dates to keep for matched_state_* diagnostic variants",
    )
    p.add_argument(
        "--state-matched-min-days",
        type=int,
        default=60,
        help="minimum training signal dates kept by matched_state_* diagnostic variants",
    )
    p.add_argument(
        "--day-opportunity-min-edge-pct",
        type=float,
        default=0.0,
        help="minimum train-neighbor expected pos52w/beta top-minus-all edge before activating opportunity overlay",
    )
    p.add_argument(
        "--abstention-min-expected-return-pct",
        type=float,
        default=0.0,
        help="minimum nearest-train-day expected all-universe return for deployability abstention variants",
    )
    p.add_argument(
        "--abstention-min-positive-rate-pct",
        type=float,
        default=48.0,
        help="minimum nearest-train-day expected positive-stock rate for deployability abstention variants",
    )
    p.add_argument(
        "--abstention-max-left-tail-rate-pct",
        type=float,
        default=45.0,
        help="maximum nearest-train-day expected <= -1pct left-tail rate for deployability abstention variants",
    )
    p.add_argument(
        "--abstention-min-validation-deploy-rate-pct",
        type=float,
        default=50.0,
        help="minimum validation deploy-day rate when calibrating deployability abstention thresholds",
    )
    p.add_argument("--min-regime-train-rows", type=int, default=15000)
    p.add_argument("--min-regime-train-days", type=int, default=40)
    p.add_argument("--seed", type=int, default=20260508)
    p.add_argument("--num-threads", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    p.add_argument("--include-bj9", action="store_true")
    p.add_argument(
        "--feature-cache-file",
        default="auto",
        help="raw feature-frame cache path; use 'auto' for metadata-keyed cache or 'none' to disable",
    )
    p.add_argument("--no-feature-cache", action="store_true", help="disable raw feature-frame cache")
    p.add_argument("--label", default="h10_instability_focus")
    p.add_argument("--write-latest", action="store_true")
    args = p.parse_args()

    horizon = int(args.horizon)
    focus_folds = _parse_int_list(args.focus_folds, [6, 7])
    critical_folds = _parse_int_list(args.critical_folds, [7])
    variants = _parse_str_list(args.variants, DEFAULT_VARIANTS)
    dependency_variants = []
    for variant in variants:
        dependency_variants.extend(ENSEMBLE_VARIANTS.get(str(variant), []))
    train_variants = [v for v in variants if not _is_ensemble_variant(v)]
    for dep in dependency_variants:
        if dep not in train_variants:
            train_variants.append(dep)
    ensemble_variants = [v for v in variants if _is_ensemble_variant(v)]
    features = _parse_feature_list(args.features or None, args.model_file)
    model_meta = load_model_metadata(args.model_file)
    frame, frame_cache = load_raw_model_frame_cached(
        data_file=Path(args.data_file).resolve(),
        features=features,
        horizons=[horizon],
        start=str(args.start),
        end=str(args.end),
        exclude_bj9=not args.include_bj9,
        cache_file="none" if args.no_feature_cache else str(args.feature_cache_file),
    )
    cache_msg = "hit" if frame_cache.get("cache_hit") else "miss"
    print(f"raw_model_frame_cache={cache_msg}:{frame_cache.get('cache_file', '')}")
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
    wins = [w for w in windows if int(w["fold"]) in set(int(x) for x in focus_folds)]
    if not wins:
        raise RuntimeError("No focus fold windows found")

    variant_rows = []
    regime_rows = []
    exante_regime_rows = []
    drift_rows = []
    importance_rows = []
    exposure_rows = []
    label_col = f"label_h{horizon}"
    for win in wins:
        fold = int(win["fold"])
        train_raw = frame[frame["trade_date"].between(win["train_start"], win["train_end"], inclusive="both")].copy()
        test_raw = frame[frame["trade_date"].between(win["test_start"], win["test_end"], inclusive="both")].copy()
        train_full = _clean_with_extras(train_raw, usable_features, label_col)
        test_full = _clean_with_extras(test_raw, usable_features, label_col)
        if len(train_full) < 5000 or len(test_full) < 1000:
            continue
        valid_cut = pd.Timestamp(win["train_end"]) - pd.DateOffset(months=max(1, int(args.valid_months))) + pd.Timedelta(days=1)
        valid_full = train_full[train_full["trade_date"].ge(valid_cut)].copy()
        fit_full = train_full[train_full["trade_date"].lt(valid_cut)].copy()
        if fit_full.empty or valid_full.empty:
            fit_full = train_full.copy()
            valid_full = pd.DataFrame(columns=train_full.columns)
        fit_full = _sample_rows_for_mode(fit_full, int(args.max_train_rows), int(args.seed) + fold, str(args.sample_mode))
        valid_full = _sample_rows_for_mode(
            valid_full,
            max(0, int(args.max_train_rows // 4)),
            int(args.seed) + fold * 10,
            str(args.sample_mode),
        )
        test_eval_full = _sample_rows_for_mode(test_full, int(args.max_test_rows), int(args.seed) + fold * 100, str(args.sample_mode))

        drift_all = pd.DataFrame(feature_drift_rows(fit_full, test_eval_full, features=usable_features, max_features=len(usable_features)))
        if not drift_all.empty:
            drift_all.insert(0, "fold", int(fold))
            drift_all.insert(1, "horizon", int(horizon))
            drift_rows.extend(drift_all.to_dict(orient="records"))

        pred_cache: dict[str, pd.DataFrame] = {}
        for variant in train_variants:
            variant = str(variant)
            fit_source_full = fit_full
            valid_source_full = valid_full
            test_source_full = test_eval_full
            variant_features = list(usable_features)
            variant_drift = drift_all.copy()
            base_variant = _base_model_variant(variant)
            feature_mode = _variant_feature_mode(variant)
            if feature_mode == "context":
                fit_source_full, context_fit_features = _add_diagnostic_context_features(fit_full)
                valid_source_full, context_valid_features = _add_diagnostic_context_features(valid_full) if not valid_full.empty else (valid_full.copy(), [])
                test_source_full, context_test_features = _add_diagnostic_context_features(test_eval_full)
                context_features = [
                    f
                    for f in context_fit_features
                    if f in test_source_full.columns and (valid_source_full.empty or f in valid_source_full.columns)
                ]
                variant_features = list(dict.fromkeys([*usable_features, *context_features]))
                variant_drift = pd.DataFrame(
                    feature_drift_rows(fit_source_full, test_source_full, features=variant_features, max_features=len(variant_features))
                )
            elif feature_mode == "engineered":
                fit_source_full, fit_engineered = _add_diagnostic_engineered_features(fit_full)
                valid_source_full, valid_engineered = _add_diagnostic_engineered_features(valid_full) if not valid_full.empty else (valid_full.copy(), [])
                test_source_full, test_engineered = _add_diagnostic_engineered_features(test_eval_full)
                engineered_features = [
                    f
                    for f in fit_engineered
                    if f in test_source_full.columns and (valid_source_full.empty or f in valid_source_full.columns)
                ]
                variant_features = list(dict.fromkeys([*usable_features, *engineered_features]))
                variant_drift = pd.DataFrame(
                    feature_drift_rows(fit_source_full, test_source_full, features=variant_features, max_features=len(variant_features))
                )
            elif feature_mode == "drop_high_drift":
                variant_features, variant_drift = _drop_high_drift_features(
                    fit_full,
                    test_eval_full,
                    features=usable_features,
                    psi_threshold=float(args.drift_psi_threshold),
                    std_diff_threshold=float(args.drift_std_diff_threshold),
                )
            elif feature_mode == "cross_sectional_only":
                variant_features = [f for f in usable_features if str(f).endswith("_cs")]
            if not variant_features:
                variant_features = list(usable_features)
            extra_cols = [c for c in REGIME_EXTRA_COLS if c in fit_source_full.columns or c in test_source_full.columns]
            fit = fit_source_full[["trade_date", "ts_code", *extra_cols, *variant_features, label_col]].copy()
            valid = valid_source_full[["trade_date", "ts_code", *extra_cols, *variant_features, label_col]].copy() if not valid_source_full.empty else pd.DataFrame()
            test_eval = test_source_full[["trade_date", "ts_code", "pct_chg", "amount", "close", *extra_cols, *variant_features, label_col]].copy()
            state_training_notes: list[str] = []
            if _uses_matched_state_training(variant):
                fit, state_note = _matched_state_training_frame(
                    fit,
                    test_eval,
                    neighbor_days=int(args.day_state_neighbor_days),
                    keep_day_rate=float(args.state_matched_keep_day_rate),
                    min_days=int(args.state_matched_min_days),
                )
                state_training_notes.append(state_note)
            if _uses_state_similarity_weights(variant):
                fit, state_note = _attach_state_similarity_weights(
                    fit,
                    test_eval,
                    neighbor_days=int(args.day_state_neighbor_days),
                )
                state_training_notes.append(state_note)
            if _uses_rank_normalization(variant):
                fit = _rank_normalize_feature_frame(fit, variant_features)
                valid = _rank_normalize_feature_frame(valid, variant_features) if not valid.empty else valid
                test_eval = _rank_normalize_feature_frame(test_eval, variant_features)
            label_mode = _variant_label_mode(variant)
            if _uses_downside_weights(variant) and _uses_state_similarity_weights(variant):
                sample_weight_mode = "downside_state_similarity"
            elif _uses_downside_weights(variant):
                sample_weight_mode = "downside"
            elif _uses_state_similarity_weights(variant):
                sample_weight_mode = "state_similarity"
            else:
                sample_weight_mode = ""
            train_label_col = label_col
            label_note = ""
            if label_mode != "raw":
                train_label_col = "_diagnostic_train_label"
                fit[train_label_col] = _make_training_label(fit, label_col, label_mode)
                if not valid.empty:
                    valid[train_label_col] = _make_training_label(valid, label_col, label_mode)
                label_note = f"label_mode={label_mode}"
            print(
                f"fold={fold} h={horizon} variant={variant} features={len(variant_features)} "
                f"train={len(fit)} valid={len(valid)} test={len(test_eval)}"
            )
            pred_cols = ["trade_date", "ts_code", "pct_chg", "amount", "close", *extra_cols, *variant_features, label_col]
            pred = test_eval.loc[:, list(dict.fromkeys([c for c in pred_cols if c in test_eval.columns]))].copy()
            pred = pred.rename(columns={label_col: "label"})
            model_note_parts = [*state_training_notes]
            if label_note:
                model_note_parts.append(label_note)
            model_note = _model_note_prefix(variant, ";".join(model_note_parts))
            if _is_regime_specific_model(base_variant):
                pred_values, imp, regime_note = _predict_regime_specific(
                    fit,
                    valid,
                    test_eval,
                    features=variant_features,
                    label_col=train_label_col,
                    num_boost_round=int(args.num_boost_round),
                    early_stopping_rounds=int(args.early_stopping_rounds),
                    seed=int(args.seed) + fold * 1000 + len(variant),
                    num_threads=max(1, int(args.num_threads)),
                    recency_half_life_days=float(args.recency_half_life_days),
                    min_regime_train_rows=int(args.min_regime_train_rows),
                    min_regime_train_days=int(args.min_regime_train_days),
                    sample_weight_mode=sample_weight_mode,
                    raw_label_col=label_col,
                )
                pred["pred"] = pred_values
                if regime_note:
                    model_note_parts.append(regime_note)
                model_note = _model_note_prefix(variant, ";".join(model_note_parts))
            else:
                model = _train_lgb_variant(
                    fit,
                    valid,
                    features=variant_features,
                    label_col=train_label_col,
                    variant=_lgb_train_variant_for_base(base_variant),
                    num_boost_round=int(args.num_boost_round),
                    early_stopping_rounds=int(args.early_stopping_rounds),
                    seed=int(args.seed) + fold * 1000 + len(variant),
                    num_threads=max(1, int(args.num_threads)),
                    recency_half_life_days=float(args.recency_half_life_days),
                    sample_weight_mode=sample_weight_mode,
                    raw_label_col=label_col,
                )
                pred["pred"] = model.predict(test_eval[variant_features].to_numpy(dtype=float))
                imp = _feature_importance(model, variant_features)
            pred, treatment_note = _apply_treatment_adjustments(
                pred,
                variant=variant,
                fit=fit,
                valid=valid,
                test_eval=test_eval,
                features=variant_features,
                label_col=label_col,
                num_boost_round=int(args.num_boost_round),
                early_stopping_rounds=int(args.early_stopping_rounds),
                seed=int(args.seed) + fold * 1000 + len(variant),
                num_threads=max(1, int(args.num_threads)),
                recency_half_life_days=float(args.recency_half_life_days),
                min_regime_train_rows=int(args.min_regime_train_rows),
                min_regime_train_days=int(args.min_regime_train_days),
                top_n=int(args.top_n),
                day_state_neighbor_days=int(args.day_state_neighbor_days),
                day_opportunity_min_edge_pct=float(args.day_opportunity_min_edge_pct),
                abstention_min_expected_return_pct=float(args.abstention_min_expected_return_pct),
                abstention_min_positive_rate_pct=float(args.abstention_min_positive_rate_pct),
                abstention_max_left_tail_rate_pct=float(args.abstention_max_left_tail_rate_pct),
                abstention_min_validation_deploy_rate_pct=float(args.abstention_min_validation_deploy_rate_pct),
            )
            if treatment_note:
                model_note_parts.append(treatment_note)
                model_note = _model_note_prefix(variant, ";".join(model_note_parts))
            pred["fold"] = int(fold)
            pred["horizon"] = int(horizon)
            pred["variant"] = str(variant)
            append_prediction_diagnostics(
                pred=pred,
                variant=variant,
                fold=fold,
                horizon=horizon,
                win=win,
                variant_features=variant_features,
                usable_features=usable_features,
                model_note=model_note,
                top_n=int(args.top_n),
                variant_drift=variant_drift,
                imp=imp,
                variant_rows=variant_rows,
                regime_rows=regime_rows,
                importance_rows=importance_rows,
                exposure_rows=exposure_rows,
                exante_regime_rows=exante_regime_rows,
                min_deployment_day_rate_pct=float(args.min_deployment_day_rate_pct),
            )
            pred_cache_cols = ["trade_date", "ts_code", "pct_chg", "amount", "close", "market_regime_exante", "label", "pred"]
            pred_cache[variant] = pred.loc[:, [c for c in pred_cache_cols if c in pred.columns]].copy()

        for variant in ensemble_variants:
            pred, model_note = build_ensemble_prediction(pred_cache, variant)
            if pred.empty:
                continue
            pred["fold"] = int(fold)
            pred["horizon"] = int(horizon)
            pred["variant"] = str(variant)
            print(
                f"fold={fold} h={horizon} variant={variant} ensemble rows={len(pred)} note={model_note}"
            )
            append_prediction_diagnostics(
                pred=pred,
                variant=str(variant),
                fold=fold,
                horizon=horizon,
                win=win,
                variant_features=[],
                usable_features=usable_features,
                model_note=model_note,
                top_n=int(args.top_n),
                variant_drift=pd.DataFrame(),
                imp=pd.DataFrame(),
                variant_rows=variant_rows,
                regime_rows=regime_rows,
                importance_rows=importance_rows,
                exposure_rows=exposure_rows,
                exante_regime_rows=exante_regime_rows,
                min_deployment_day_rate_pct=float(args.min_deployment_day_rate_pct),
            )

    variant_summary = pd.DataFrame(variant_rows)
    regime_summary = pd.DataFrame(regime_rows)
    exante_regime_summary = pd.DataFrame(exante_regime_rows)
    drift_detail = pd.DataFrame(drift_rows)
    importance = pd.DataFrame(importance_rows)
    exposure = pd.DataFrame(exposure_rows)
    verdict = build_instability_verdict(variant_summary, focus_folds)
    variant_family_summary = build_variant_family_summary(
        variant_summary,
        critical_folds=critical_folds,
        min_fold_pass_rate_pct=float(args.min_fold_pass_rate_pct),
    )
    fold_attribution = build_fold_attribution(
        variant_summary,
        regime_summary,
        importance,
        exposure,
        focus_folds=focus_folds,
        drift_psi_threshold=float(args.drift_psi_threshold),
        drift_std_diff_threshold=float(args.drift_std_diff_threshold),
    )
    verdict_df = pd.DataFrame([{**verdict, **{f"source_model_{k}": v for k, v in model_meta.items()}}])

    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(str(args.label))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = BACKTEST_DIR / f"quant_raw_model_instability_attribution_{slug}_{ts}"
    files = {
        "variant_summary": str(base.with_name(base.name + "_variant_summary.csv")),
        "variant_family_summary": str(base.with_name(base.name + "_variant_family_summary.csv")),
        "regime_summary": str(base.with_name(base.name + "_regime_summary.csv")),
        "exante_regime_summary": str(base.with_name(base.name + "_exante_regime_summary.csv")),
        "feature_drift": str(base.with_name(base.name + "_feature_drift.csv")),
        "feature_importance_drift": str(base.with_name(base.name + "_feature_importance_drift.csv")),
        "selected_feature_exposure": str(base.with_name(base.name + "_selected_feature_exposure.csv")),
        "fold_attribution": str(base.with_name(base.name + "_fold_attribution.csv")),
        "verdict": str(base.with_name(base.name + "_verdict.csv")),
        "json": str(base.with_suffix(".json")),
    }
    variant_summary.to_csv(files["variant_summary"], index=False, encoding="utf-8-sig")
    variant_family_summary.to_csv(files["variant_family_summary"], index=False, encoding="utf-8-sig")
    regime_summary.to_csv(files["regime_summary"], index=False, encoding="utf-8-sig")
    exante_regime_summary.to_csv(files["exante_regime_summary"], index=False, encoding="utf-8-sig")
    drift_detail.to_csv(files["feature_drift"], index=False, encoding="utf-8-sig")
    importance.to_csv(files["feature_importance_drift"], index=False, encoding="utf-8-sig")
    exposure.to_csv(files["selected_feature_exposure"], index=False, encoding="utf-8-sig")
    fold_attribution.to_csv(files["fold_attribution"], index=False, encoding="utf-8-sig")
    verdict_df.to_csv(files["verdict"], index=False, encoding="utf-8-sig")
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "label": str(args.label),
        "horizon": int(horizon),
        "focus_folds": focus_folds,
        "critical_folds": critical_folds,
        "variants": variants,
        "features": usable_features,
        "source_model": model_meta,
        "frame_cache": frame_cache,
        "args": vars(args),
        "files": files,
        "verdict": verdict,
    }
    Path(files["json"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest = BACKTEST_DIR / f"quant_raw_model_instability_attribution_latest_{slug}"
        for key, suffix in {
            "variant_summary": "_variant_summary.csv",
            "variant_family_summary": "_variant_family_summary.csv",
            "regime_summary": "_regime_summary.csv",
            "exante_regime_summary": "_exante_regime_summary.csv",
            "feature_drift": "_feature_drift.csv",
            "feature_importance_drift": "_feature_importance_drift.csv",
            "selected_feature_exposure": "_selected_feature_exposure.csv",
            "fold_attribution": "_fold_attribution.csv",
            "verdict": "_verdict.csv",
        }.items():
            pd.read_csv(files[key]).to_csv(latest.with_name(latest.name + suffix), index=False, encoding="utf-8-sig")
        latest.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        variant_summary.to_csv(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_variant_summary.csv", index=False, encoding="utf-8-sig")
        variant_family_summary.to_csv(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_variant_family_summary.csv", index=False, encoding="utf-8-sig")
        regime_summary.to_csv(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_regime_summary.csv", index=False, encoding="utf-8-sig")
        exante_regime_summary.to_csv(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_exante_regime_summary.csv", index=False, encoding="utf-8-sig")
        fold_attribution.to_csv(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_fold_attribution.csv", index=False, encoding="utf-8-sig")
        verdict_df.to_csv(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_verdict.csv", index=False, encoding="utf-8-sig")

    print(verdict_df.to_string(index=False))
    print(variant_family_summary.to_string(index=False))
    print(variant_summary.to_string(index=False))
    print(fold_attribution.to_string(index=False))
    print(f"instability_verdict={files['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
