#!/usr/bin/env python3
"""Diagnose residual failing folds for a raw-model variant.

This consumes existing `quant_raw_model_instability_attribution` artifacts. It
does not train models, create profiles, or run P2. Its job is to explain why a
variant that fixed one critical fold still fails other folds.
"""

from __future__ import annotations

import argparse
import json
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


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(value).lower()).strip("_")


def _parse_int_list(raw: str | None, default: list[int]) -> list[int]:
    vals = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        vals.append(int(part))
    return list(dict.fromkeys(vals)) or list(default)


def _prefix_from_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    raw = str(path)
    for suffix in (
        "_variant_summary.csv",
        "_variant_family_summary.csv",
        "_exante_regime_summary.csv",
        "_regime_summary.csv",
        "_selected_feature_exposure.csv",
        "_feature_importance_drift.csv",
    ):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return Path(raw).resolve()


def _read_artifact(prefix: Path, suffix: str) -> pd.DataFrame:
    path = prefix.with_name(prefix.name + suffix)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def residual_failure_label(row: pd.Series | dict[str, object]) -> str:
    top = _safe_float(row.get("top_mean_return_pct", 0.0))
    spread = _safe_float(row.get("top_minus_all_pct", 0.0))
    bottom_spread = _safe_float(row.get("top_minus_bottom_pct", 0.0))
    ic = _safe_float(row.get("rank_ic_mean", 0.0))
    passed = _safe_bool(row.get("alpha_gate_pass", False))
    if passed:
        return "fold_passed"
    if top <= 0.0 and spread > 0.0 and bottom_spread > 0.0 and ic > 0.0:
        return "absolute_loss_but_beats_pool"
    if top > 0.0 and spread <= 0.0 and bottom_spread <= 0.0:
        return "positive_top_but_pool_and_bottom_lag"
    if top > 0.0 and spread <= 0.0:
        return "pool_relative_failure"
    if top <= 0.0 and spread <= 0.0:
        return "absolute_and_relative_failure"
    return "mixed_metric_failure"


def _failure_reasons(row: pd.Series | dict[str, object]) -> str:
    raw = str(row.get("failure_label", "") or "")
    if raw and raw != "nan":
        return raw
    bits = []
    if _safe_float(row.get("top_mean_return_pct", 0.0)) <= 0.0:
        bits.append("top_mean_non_positive")
    if _safe_float(row.get("top_minus_all_pct", 0.0)) <= 0.0:
        bits.append("top_not_above_pool")
    if _safe_float(row.get("top_minus_bottom_pct", 0.0)) <= 0.0:
        bits.append("top_not_above_bottom")
    if _safe_float(row.get("rank_ic_mean", 0.0)) <= 0.0:
        bits.append("rank_ic_non_positive")
    return "+".join(bits) if bits else "pass"


def _severity_score(row: pd.Series) -> float:
    score = 0.0
    if _safe_float(row.get("top_mean_return_pct", 0.0)) <= 0.0:
        score += abs(_safe_float(row.get("top_mean_return_pct", 0.0))) + 1.0
    if _safe_float(row.get("top_minus_all_pct", 0.0)) <= 0.0:
        score += abs(_safe_float(row.get("top_minus_all_pct", 0.0))) + 0.5
    if _safe_float(row.get("top_minus_bottom_pct", 0.0)) <= 0.0:
        score += abs(_safe_float(row.get("top_minus_bottom_pct", 0.0))) + 0.5
    if _safe_float(row.get("rank_ic_mean", 0.0)) <= 0.0:
        score += abs(_safe_float(row.get("rank_ic_mean", 0.0))) + 0.25
    return float(score * max(_safe_float(row.get("days", 1.0), 1.0), 1.0))


def _summarize_exante_failures(exante: pd.DataFrame, *, fold: int, variant: str, max_items: int = 4) -> tuple[str, pd.DataFrame]:
    if exante.empty:
        return "", pd.DataFrame()
    work = exante[
        pd.to_numeric(exante.get("fold", -1), errors="coerce").fillna(-1).astype(int).eq(int(fold))
        & exante.get("variant", pd.Series(dtype=str)).astype(str).eq(str(variant))
    ].copy()
    if work.empty:
        return "", pd.DataFrame()
    work["alpha_gate_pass"] = work.get("alpha_gate_pass", False).map(_safe_bool)
    work["residual_failure_label"] = work.apply(residual_failure_label, axis=1)
    work["residual_failure_reasons"] = work.apply(_failure_reasons, axis=1)
    work["severity_score"] = work.apply(_severity_score, axis=1)
    fail = work[~work["alpha_gate_pass"]].sort_values("severity_score", ascending=False).copy()
    if fail.empty:
        return "", fail
    labels = []
    for r in fail.head(int(max_items)).itertuples(index=False):
        regime = getattr(r, "regime_exante", "")
        labels.append(
            f"{regime}:top={_safe_float(getattr(r, 'top_mean_return_pct', 0.0)):+.2f},"
            f"spread={_safe_float(getattr(r, 'top_minus_all_pct', 0.0)):+.2f},"
            f"days={int(_safe_float(getattr(r, 'days', 0), 0))},"
            f"{getattr(r, 'residual_failure_label', '')}"
        )
    return ";".join(labels), fail


def _summarize_expost_failures(regime: pd.DataFrame, *, fold: int, variant: str, max_items: int = 4) -> str:
    if regime.empty:
        return ""
    work = regime[
        pd.to_numeric(regime.get("fold", -1), errors="coerce").fillna(-1).astype(int).eq(int(fold))
        & regime.get("variant", pd.Series(dtype=str)).astype(str).eq(str(variant))
    ].copy()
    if work.empty:
        return ""
    work["alpha_gate_pass"] = work.get("alpha_gate_pass", False).map(_safe_bool)
    work["residual_failure_label"] = work.apply(residual_failure_label, axis=1)
    work["severity_score"] = work.apply(_severity_score, axis=1)
    fail = work[~work["alpha_gate_pass"]].sort_values("severity_score", ascending=False).head(int(max_items))
    return ";".join(
        f"{getattr(r, 'regime_proxy_expost', '')}:top={_safe_float(getattr(r, 'top_mean_return_pct', 0.0)):+.2f},"
        f"spread={_safe_float(getattr(r, 'top_minus_all_pct', 0.0)):+.2f},"
        f"days={int(_safe_float(getattr(r, 'days', 0), 0))},"
        f"{getattr(r, 'residual_failure_label', '')}"
        for r in fail.itertuples(index=False)
    )


def _summarize_exposure(exposure: pd.DataFrame, *, fold: int, variant: str, max_features: int = 8) -> str:
    if exposure.empty:
        return ""
    work = exposure[
        pd.to_numeric(exposure.get("fold", -1), errors="coerce").fillna(-1).astype(int).eq(int(fold))
        & exposure.get("variant", pd.Series(dtype=str)).astype(str).eq(str(variant))
    ].copy()
    if work.empty:
        return ""
    work["top_minus_all"] = pd.to_numeric(work.get("top_minus_all", 0.0), errors="coerce").fillna(0.0)
    work["_abs"] = work["top_minus_all"].abs()
    work = work.sort_values("_abs", ascending=False).head(int(max_features))
    return ";".join(f"{r.feature}:{_safe_float(r.top_minus_all):+.3f}" for r in work.itertuples(index=False))


def _summarize_drifted_importance(
    importance: pd.DataFrame,
    *,
    fold: int,
    variant: str,
    min_importance_share_pct: float = 2.0,
    psi_threshold: float = 0.30,
    std_diff_threshold: float = 0.60,
    max_features: int = 8,
) -> str:
    if importance.empty:
        return ""
    work = importance[
        pd.to_numeric(importance.get("fold", -1), errors="coerce").fillna(-1).astype(int).eq(int(fold))
        & importance.get("variant", pd.Series(dtype=str)).astype(str).eq(str(variant))
    ].copy()
    if work.empty:
        return ""
    for col in ("importance_share_pct", "psi", "std_mean_diff"):
        work[col] = pd.to_numeric(work.get(col, 0.0), errors="coerce").fillna(0.0)
    work = work[
        (work["importance_share_pct"] >= float(min_importance_share_pct))
        & ((work["psi"] >= float(psi_threshold)) | (work["std_mean_diff"] >= float(std_diff_threshold)))
    ].copy()
    if work.empty:
        return ""
    work["_rank"] = work["importance_share_pct"] + work["psi"] + work["std_mean_diff"]
    work = work.sort_values("_rank", ascending=False).head(int(max_features))
    return ";".join(
        f"{r.feature}:share={_safe_float(r.importance_share_pct):.1f},"
        f"psi={_safe_float(r.psi):.2f},std={_safe_float(r.std_mean_diff):.2f}"
        for r in work.itertuples(index=False)
    )


def _fold_interpretation(label: str) -> str:
    if label == "absolute_loss_but_beats_pool":
        return "top bucket loses money in a weak window; useful relative ordering is not enough for deployable alpha"
    if label == "positive_top_but_pool_and_bottom_lag":
        return "top bucket is positive but anti-selects versus broad pool and bottom bucket"
    if label == "pool_relative_failure":
        return "top bucket is positive but misses the available market beta/opportunity set"
    if label == "absolute_and_relative_failure":
        return "top bucket loses money and underperforms the pool"
    if label == "fold_passed":
        return "fold passes the raw alpha gate"
    return "mixed residual metric failure; inspect regime details"


def build_residual_diagnosis(
    *,
    prefix: Path,
    variant: str,
    baseline_variant: str,
    focus_folds: list[int],
    min_importance_share_pct: float = 2.0,
    psi_threshold: float = 0.30,
    std_diff_threshold: float = 0.60,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    variant_summary = _read_artifact(prefix, "_variant_summary.csv")
    exante = _read_artifact(prefix, "_exante_regime_summary.csv")
    regime = _read_artifact(prefix, "_regime_summary.csv")
    exposure = _read_artifact(prefix, "_selected_feature_exposure.csv")
    importance = _read_artifact(prefix, "_feature_importance_drift.csv")
    if variant_summary.empty:
        raise RuntimeError(f"missing variant_summary for {prefix}")

    rows: list[dict[str, object]] = []
    detail_parts: list[pd.DataFrame] = []
    for fold in focus_folds:
        cand = variant_summary[
            pd.to_numeric(variant_summary.get("fold", -1), errors="coerce").fillna(-1).astype(int).eq(int(fold))
            & variant_summary.get("variant", pd.Series(dtype=str)).astype(str).eq(str(variant))
        ].head(1)
        if cand.empty:
            continue
        base = variant_summary[
            pd.to_numeric(variant_summary.get("fold", -1), errors="coerce").fillna(-1).astype(int).eq(int(fold))
            & variant_summary.get("variant", pd.Series(dtype=str)).astype(str).eq(str(baseline_variant))
        ].head(1)
        c = cand.iloc[0]
        b = base.iloc[0] if not base.empty else pd.Series(dtype=object)
        label = residual_failure_label(c)
        exante_summary, exante_detail = _summarize_exante_failures(exante, fold=int(fold), variant=str(variant))
        if not exante_detail.empty:
            exante_detail["focus_fold"] = int(fold)
            exante_detail["diagnosed_variant"] = str(variant)
            detail_parts.append(exante_detail)
        rows.append(
            {
                "focus_fold": int(fold),
                "variant": str(variant),
                "test_start": c.get("test_start", ""),
                "test_end": c.get("test_end", ""),
                "alpha_gate_pass": _safe_bool(c.get("alpha_gate_pass", False)),
                "residual_failure_label": label,
                "failure_reasons": _failure_reasons(c),
                "interpretation": _fold_interpretation(label),
                "candidate_top_mean_return_pct": _safe_float(c.get("top_mean_return_pct", 0.0)),
                "candidate_all_mean_return_pct": _safe_float(c.get("all_mean_return_pct", 0.0)),
                "candidate_top_minus_all_pct": _safe_float(c.get("top_minus_all_pct", 0.0)),
                "candidate_top_minus_bottom_pct": _safe_float(c.get("top_minus_bottom_pct", 0.0)),
                "candidate_rank_ic_mean": _safe_float(c.get("rank_ic_mean", 0.0)),
                "baseline_top_mean_return_pct": _safe_float(b.get("top_mean_return_pct", 0.0)),
                "baseline_top_minus_all_pct": _safe_float(b.get("top_minus_all_pct", 0.0)),
                "delta_top_vs_baseline_pct": _safe_float(c.get("top_mean_return_pct", 0.0)) - _safe_float(b.get("top_mean_return_pct", 0.0)),
                "delta_spread_vs_baseline_pct": _safe_float(c.get("top_minus_all_pct", 0.0)) - _safe_float(b.get("top_minus_all_pct", 0.0)),
                "failed_exante_regimes": exante_summary,
                "failed_expost_regimes": _summarize_expost_failures(regime, fold=int(fold), variant=str(variant)),
                "top_feature_exposures": _summarize_exposure(exposure, fold=int(fold), variant=str(variant)),
                "drifted_important_features": _summarize_drifted_importance(
                    importance,
                    fold=int(fold),
                    variant=str(variant),
                    min_importance_share_pct=float(min_importance_share_pct),
                    psi_threshold=float(psi_threshold),
                    std_diff_threshold=float(std_diff_threshold),
                ),
            }
        )
    summary = pd.DataFrame(rows)
    detail = pd.concat(detail_parts, ignore_index=True) if detail_parts else pd.DataFrame()
    if summary.empty:
        verdict = "no_focus_fold_rows"
        action = "check artifact prefix, variant, and focus folds"
    elif bool(summary["alpha_gate_pass"].all()):
        verdict = "all_focus_folds_pass"
        action = "continue only with broader seed/sample stability gates; do not jump directly to profile/P2"
    else:
        verdict = "residual_folds_explained_model_not_deployable"
        action = "use residual labels to design the next raw-model test; do not create a profile or run P2"
    payload = {
        "artifact_prefix": str(prefix),
        "variant": str(variant),
        "baseline_variant": str(baseline_variant),
        "focus_folds": ",".join(str(int(x)) for x in focus_folds),
        "overall_verdict": verdict,
        "recommended_next_action": action,
        "failing_folds": ",".join(str(int(x)) for x in summary.loc[~summary["alpha_gate_pass"], "focus_fold"].tolist()) if not summary.empty else "",
    }
    return summary, detail, payload


def _write_outputs(
    summary: pd.DataFrame,
    detail: pd.DataFrame,
    payload: dict[str, object],
    *,
    label: str,
    write_latest: bool,
) -> dict[str, str]:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slug(label or "raw_model_residual_fold_diagnosis")
    prefix = BACKTEST_DIR / f"quant_raw_model_residual_fold_diagnosis_{slug}_{ts}"
    paths = {
        "summary": str(prefix.with_name(prefix.name + "_summary.csv")),
        "exante_detail": str(prefix.with_name(prefix.name + "_exante_detail.csv")),
        "verdict": str(prefix.with_name(prefix.name + "_verdict.json")),
    }
    summary.to_csv(paths["summary"], index=False, encoding="utf-8-sig")
    detail.to_csv(paths["exante_detail"], index=False, encoding="utf-8-sig")
    payload = {**payload, "generated_at": ts, "outputs": paths}
    Path(paths["verdict"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if write_latest:
        latest = BACKTEST_DIR / f"quant_raw_model_residual_fold_diagnosis_latest_{slug}"
        latest_paths = {
            "summary": str(latest.with_name(latest.name + "_summary.csv")),
            "exante_detail": str(latest.with_name(latest.name + "_exante_detail.csv")),
            "verdict": str(latest.with_name(latest.name + "_verdict.json")),
        }
        summary.to_csv(latest_paths["summary"], index=False, encoding="utf-8-sig")
        detail.to_csv(latest_paths["exante_detail"], index=False, encoding="utf-8-sig")
        latest_payload = {**payload, "outputs": latest_paths}
        Path(latest_paths["verdict"]).write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.update({f"latest_{k}": v for k, v in latest_paths.items()})
    return paths


def main() -> int:
    p = argparse.ArgumentParser(description="Explain residual failing folds for a raw-model variant")
    p.add_argument(
        "--artifact-prefix",
        default=str(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_h10_label_objective_7fold_date_stratified"),
        help="instability attribution artifact prefix; suffixes are inferred",
    )
    p.add_argument("--variant", default="rank_norm_regime_label_ranked")
    p.add_argument("--baseline-variant", default="baseline")
    p.add_argument("--focus-folds", default="2,6")
    p.add_argument("--min-importance-share-pct", type=float, default=2.0)
    p.add_argument("--drift-psi-threshold", type=float, default=0.30)
    p.add_argument("--drift-std-diff-threshold", type=float, default=0.60)
    p.add_argument("--label", default="h10_label_objective_fold2_fold6_residuals")
    p.add_argument("--write-latest", action="store_true")
    args = p.parse_args()

    summary, detail, payload = build_residual_diagnosis(
        prefix=_prefix_from_path(args.artifact_prefix),
        variant=str(args.variant),
        baseline_variant=str(args.baseline_variant),
        focus_folds=_parse_int_list(args.focus_folds, [2, 6]),
        min_importance_share_pct=float(args.min_importance_share_pct),
        psi_threshold=float(args.drift_psi_threshold),
        std_diff_threshold=float(args.drift_std_diff_threshold),
    )
    paths = _write_outputs(summary, detail, payload, label=str(args.label), write_latest=bool(args.write_latest))
    print(summary.to_string(index=False))
    print("verdict=" + json.dumps(payload, ensure_ascii=False))
    print("outputs=" + json.dumps(paths, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
