#!/usr/bin/env python3
"""Turn residual raw-model fold failures into treatment hypotheses.

This script consumes `quant_raw_model_residual_fold_diagnosis` artifacts. It
does not train models, create profiles, or run P2. Its purpose is narrower:
separate residual folds into different model-treatment problems so the next
experiment is defined before any new profile is considered.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
BACKTEST_DIR = BASE_DIR / "output" / "backtest"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(value).lower()).strip("_")


def _split_tokens(text: object) -> list[str]:
    return [part.strip() for part in str(text or "").split(";") if part and part.strip()]


def _feature_value_map(text: object) -> dict[str, float]:
    out: dict[str, float] = {}
    for token in _split_tokens(text):
        if ":" not in token:
            continue
        name, raw_val = token.split(":", 1)
        value_match = re.search(r"[-+]?\d+(?:\.\d+)?", raw_val)
        if value_match:
            out[name.strip()] = _safe_float(value_match.group(0))
    return out


def _has_feature(text: object, feature: str) -> bool:
    return any(token.startswith(f"{feature}:") or token == feature for token in _split_tokens(text))


def _regime_tokens_matching(text: object, *, top_negative: bool = False, spread_negative: bool = False) -> list[str]:
    hits: list[str] = []
    for token in _split_tokens(text):
        if ":" not in token:
            continue
        regime = token.split(":", 1)[0]
        top_match = re.search(r"top=([-+]?\d+(?:\.\d+)?)", token)
        spread_match = re.search(r"spread=([-+]?\d+(?:\.\d+)?)", token)
        top = _safe_float(top_match.group(1), 0.0) if top_match else 0.0
        spread = _safe_float(spread_match.group(1), 0.0) if spread_match else 0.0
        if top_negative and top >= 0.0:
            continue
        if spread_negative and spread >= 0.0:
            continue
        hits.append(str(regime))
    return hits


def _join_unique(values: list[str]) -> str:
    return ",".join(dict.fromkeys(str(v) for v in values if str(v)))


def _fold_treatment(row: pd.Series | dict[str, object]) -> dict[str, object]:
    label = str(row.get("residual_failure_label", "") or "")
    fold = int(_safe_float(row.get("focus_fold", 0), 0))
    top = _safe_float(row.get("candidate_top_mean_return_pct", 0.0))
    spread = _safe_float(row.get("candidate_top_minus_all_pct", 0.0))
    bottom_spread = _safe_float(row.get("candidate_top_minus_bottom_pct", 0.0))
    rank_ic = _safe_float(row.get("candidate_rank_ic_mean", 0.0))
    failed_exante = row.get("failed_exante_regimes", "")
    failed_expost = row.get("failed_expost_regimes", "")
    exposure = _feature_value_map(row.get("top_feature_exposures", ""))
    drifted = str(row.get("drifted_important_features", "") or "")

    absolute_loss_gap = max(0.0, -top)
    pool_lag = max(0.0, -spread)
    bottom_lag = max(0.0, -bottom_spread)
    relative_defense = max(0.0, spread)
    priority = "medium"
    hard_block = "fold_not_failed"
    treatment_family = "no_treatment_needed"
    primary_failure = "fold_passed_or_unclassified"
    hypothesis = "No fold-specific treatment is recommended from this row."
    experiments = "do_not_create_profile"
    gate = "raw_model_full_7fold_gate_before_any_capacity_or_p2"
    implicated_regimes: list[str] = []
    implicated_features: list[str] = []

    if label == "absolute_loss_but_beats_pool":
        priority = "high"
        hard_block = "top_bucket_absolute_return_negative"
        treatment_family = "weak_market_absolute_return_calibration"
        primary_failure = "relative_rank_defense_not_absolute_alpha"
        implicated_regimes = _regime_tokens_matching(failed_exante, top_negative=True)
        if not implicated_regimes and "broad_down" in str(failed_expost):
            implicated_regimes = ["broad_down"]
        for feature in ("pv_corr_20", "rs_20d", "mom_20", "bias"):
            if feature in exposure or f"{feature}_cs" in exposure:
                implicated_features.append(feature)
        hypothesis = (
            "The model still ranks defensively versus the pool, but the selected basket has negative absolute "
            "return. Ranking-only fixes are insufficient; test an ex-ante absolute-return calibrator or "
            "weak-market deployment veto trained without future tradability or return labels from the test fold."
        )
        experiments = (
            "1) add a raw-model calibration head for expected top-bucket absolute return; "
            "2) test weak/neutral/risk-on regime gates using only signal-date features; "
            "3) require calibrated top return > 0 without destroying spread and RankIC across all 7 folds"
        )
        gate = (
            "fold2 and any weak-window fold must have top_mean_return_pct > 0, top_minus_all_pct > 0, "
            "top_minus_bottom_pct > 0, and rank_ic_mean > 0 in the full 7-fold raw-universe run"
        )
    elif label == "positive_top_but_pool_and_bottom_lag":
        priority = "high"
        hard_block = "top_bucket_misses_available_market_opportunity"
        primary_failure = "market_beta_opportunity_capture_gap"
        implicated_regimes = _regime_tokens_matching(failed_exante, spread_negative=True)
        pos52w_exposure = min(exposure.get("pos_52w", 0.0), exposure.get("pos_52w_cs", 0.0))
        if _has_feature(drifted, "pos_52w") or pos52w_exposure < 0.0:
            treatment_family = "beta_capture_pos52w_drift_repair"
            implicated_features.append("pos_52w")
            hypothesis = (
                "The selected top bucket is positive but lags the broad pool and bottom bucket while pos_52w is "
                "both drifted and under-selected. Test whether the model is systematically under-capturing "
                "strong/neutral-market beta when 52-week-position distributions shift."
            )
            experiments = (
                "1) compare drift-robust pos_52w treatments: rank transform, winsorization, per-regime calibration, "
                "or interaction with beta/momentum regime; 2) test a neutral/broad-up opportunity-capture head; "
                "3) reject any variant that fixes fold6 by re-breaking fold2 absolute-return protection"
            )
            gate = (
                "fold6 neutral/broad-up buckets must have top_minus_all_pct >= 0 and top_minus_bottom_pct > 0 "
                "while full 7-fold top_mean_return_pct and RankIC remain positive"
            )
        else:
            treatment_family = "market_beta_capture_repair"
            hypothesis = (
                "The top bucket is positive but under-captures the available market opportunity. Test beta and "
                "opportunity-capture calibration before any portfolio or P2 experiment."
            )
            experiments = (
                "compare regime-specific beta capture objective, high-beta opportunity overlay, and fold-neutral "
                "ranking calibration across all 7 folds"
            )
            gate = "top_minus_all_pct >= 0 and top_minus_bottom_pct > 0 in the failing fold and full 7-fold run"
    elif label in {"pool_relative_failure", "mixed_metric_failure", "absolute_and_relative_failure"}:
        priority = "medium"
        hard_block = "residual_fold_alpha_gate_failed"
        treatment_family = "generic_residual_alpha_repair"
        primary_failure = str(label)
        hypothesis = "The fold needs a model-level repair before profile/P2 work."
        experiments = "rerun raw-model objective and regime diagnostics; do not create a profile from this fold"
        gate = "full 7-fold raw-universe alpha gate must pass"

    return {
        "focus_fold": fold,
        "variant": row.get("variant", ""),
        "test_start": row.get("test_start", ""),
        "test_end": row.get("test_end", ""),
        "residual_failure_label": label,
        "treatment_family": treatment_family,
        "primary_failure_mode": primary_failure,
        "priority": priority,
        "hard_block_reason": hard_block,
        "absolute_loss_gap_pct": absolute_loss_gap,
        "pool_lag_pct": pool_lag,
        "bottom_lag_pct": bottom_lag,
        "relative_defense_pct": relative_defense,
        "rank_ic_mean": rank_ic,
        "implicated_regimes": _join_unique(implicated_regimes),
        "implicated_features": _join_unique(implicated_features),
        "treatment_hypothesis": hypothesis,
        "recommended_raw_model_experiments": experiments,
        "fold_specific_gate_to_clear": gate,
        "no_profile_p2_reason": "residual raw-model fold gates are not solved; this artifact is not promotion evidence",
        "next_action": "run treatment-specific raw-universe 7-fold diagnostics only",
    }


def build_treatment_probe(residual_summary: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    if residual_summary.empty:
        raise RuntimeError("residual summary is empty")
    rows = [_fold_treatment(row) for _, row in residual_summary.iterrows()]
    out = pd.DataFrame(rows)
    failing = out[out["hard_block_reason"].astype(str) != "fold_not_failed"].copy()
    fold2 = out[out["focus_fold"].eq(2)].head(1)
    fold6 = out[out["focus_fold"].eq(6)].head(1)
    verdict = "residual_treatment_hypotheses_only_no_profile_p2"
    if not fold2.empty and str(fold2.iloc[0]["treatment_family"]) != "weak_market_absolute_return_calibration":
        verdict = "residual_treatment_probe_needs_manual_review"
    if not fold6.empty and "pos52w" not in str(fold6.iloc[0]["treatment_family"]):
        verdict = "residual_treatment_probe_needs_manual_review"
    payload = {
        "overall_verdict": verdict,
        "allow_profile_build": False,
        "allow_p2": False,
        "failing_folds": ",".join(str(int(x)) for x in failing["focus_fold"].tolist()),
        "recommended_next_action": (
            "For fold2, test weak-market absolute-return calibration; for fold6, test beta/pos_52w drift "
            "opportunity capture. Only a clean full 7-fold raw-universe pass can reopen capacity/P2 work."
        ),
        "profile_block_reason": "fold2/fold6 residual raw-model failures are unsolved",
    }
    return out, payload


def _markdown_report(summary: pd.DataFrame, payload: dict[str, object]) -> str:
    lines = [
        "# Raw Model Residual Treatment Probe",
        "",
        f"- overall verdict: `{payload.get('overall_verdict')}`",
        f"- profile build allowed: `{payload.get('allow_profile_build')}`",
        f"- P2 allowed: `{payload.get('allow_p2')}`",
        "",
        "## Fold Treatments",
    ]
    for row in summary.itertuples(index=False):
        lines.extend(
            [
                "",
                f"### Fold {int(row.focus_fold)}",
                "",
                f"- treatment family: `{row.treatment_family}`",
                f"- failure mode: `{row.primary_failure_mode}`",
                f"- hard block: `{row.hard_block_reason}`",
                f"- absolute loss gap pct: `{_safe_float(row.absolute_loss_gap_pct):.6f}`",
                f"- pool lag pct: `{_safe_float(row.pool_lag_pct):.6f}`",
                f"- bottom lag pct: `{_safe_float(row.bottom_lag_pct):.6f}`",
                f"- implicated regimes: `{row.implicated_regimes}`",
                f"- implicated features: `{row.implicated_features}`",
                "",
                str(row.treatment_hypothesis),
                "",
                f"Next raw-model experiments: {row.recommended_raw_model_experiments}",
                "",
                f"Gate to clear: {row.fold_specific_gate_to_clear}",
            ]
        )
    return "\n".join(lines) + "\n"


def _write_outputs(
    summary: pd.DataFrame,
    payload: dict[str, object],
    *,
    label: str,
    write_latest: bool,
) -> dict[str, str]:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slug(label or "raw_model_residual_treatment_probe")
    prefix = BACKTEST_DIR / f"quant_raw_model_residual_treatment_probe_{slug}_{ts}"
    paths = {
        "summary": str(prefix.with_name(prefix.name + "_summary.csv")),
        "verdict": str(prefix.with_name(prefix.name + "_verdict.json")),
        "report": str(prefix.with_name(prefix.name + "_report.md")),
    }
    summary.to_csv(paths["summary"], index=False, encoding="utf-8-sig")
    payload = {**payload, "generated_at": ts, "outputs": paths}
    Path(paths["verdict"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(paths["report"]).write_text(_markdown_report(summary, payload), encoding="utf-8")
    if write_latest:
        latest = BACKTEST_DIR / f"quant_raw_model_residual_treatment_probe_latest_{slug}"
        latest_paths = {
            "summary": str(latest.with_name(latest.name + "_summary.csv")),
            "verdict": str(latest.with_name(latest.name + "_verdict.json")),
            "report": str(latest.with_name(latest.name + "_report.md")),
        }
        summary.to_csv(latest_paths["summary"], index=False, encoding="utf-8-sig")
        latest_payload = {**payload, "outputs": latest_paths}
        Path(latest_paths["verdict"]).write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        Path(latest_paths["report"]).write_text(_markdown_report(summary, latest_payload), encoding="utf-8")
        paths.update({f"latest_{k}": v for k, v in latest_paths.items()})
    return paths


def main() -> int:
    p = argparse.ArgumentParser(description="Create fold-specific raw-model residual treatment hypotheses")
    p.add_argument(
        "--residual-summary",
        default=str(
            BACKTEST_DIR
            / "quant_raw_model_residual_fold_diagnosis_latest_h10_label_objective_fold2_fold6_residuals_summary.csv"
        ),
        help="residual fold diagnosis summary CSV",
    )
    p.add_argument("--label", default="h10_label_objective_fold2_fold6_treatment_probe")
    p.add_argument("--write-latest", action="store_true")
    args = p.parse_args()

    residual_summary = pd.read_csv(Path(args.residual_summary).expanduser())
    summary, payload = build_treatment_probe(residual_summary)
    paths = _write_outputs(summary, payload, label=str(args.label), write_latest=bool(args.write_latest))
    print(summary.to_string(index=False))
    print("verdict=" + json.dumps(payload, ensure_ascii=False))
    print("outputs=" + json.dumps(paths, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
