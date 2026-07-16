#!/usr/bin/env python3
"""Aggregate fold-level raw-model failures across runs.

This diagnosis consumes existing `quant_raw_model_instability_attribution`
artifacts. It does not train a model, create profiles, or run P2. Its purpose
is to explain why a critical fold keeps failing across seeds/sample modes by
joining fold metrics, regime failures, top-bucket feature exposure, and
feature-drift/importance evidence.
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter
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


def _safe_int(value: object, default: int = 0) -> int:
    return int(round(_safe_float(value, float(default))))


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return bool(value)
    raw = str(value).strip().lower()
    return raw in {"1", "true", "yes", "y"}


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(value).lower()).strip("_")


def _parse_str_list(raw: str | None) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def _prefix_from_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    raw = str(path)
    for suffix in (
        "_variant_summary.csv",
        "_variant_family_summary.csv",
        "_fold_attribution.csv",
        "_regime_summary.csv",
        "_selected_feature_exposure.csv",
        "_feature_importance_drift.csv",
        "_feature_drift.csv",
    ):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    return Path(raw).resolve()


def _discover_prefixes(raw: str) -> list[Path]:
    prefixes: list[Path] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        matches = glob.glob(part)
        if matches:
            prefixes.extend(_prefix_from_path(x) for x in matches)
        else:
            prefixes.append(_prefix_from_path(part))
    return sorted(set(prefixes))


def _run_label(prefix: Path) -> str:
    stem = prefix.name
    root = "quant_raw_model_instability_attribution_latest_"
    if stem.startswith(root):
        stem = stem[len(root) :]
    elif stem.startswith("quant_raw_model_instability_attribution_"):
        stem = stem[len("quant_raw_model_instability_attribution_") :]
    return _slug(stem or prefix.name)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_fold_artifacts(prefixes: list[Path], *, variants: list[str], focus_fold: int) -> dict[str, pd.DataFrame]:
    wanted = set(variants or [])
    frames = {"variant": [], "regime": [], "exante_regime": [], "exposure": [], "importance": []}
    for prefix in prefixes:
        label = _run_label(prefix)
        for key, suffix in {
            "variant": "_variant_summary.csv",
            "regime": "_regime_summary.csv",
            "exante_regime": "_exante_regime_summary.csv",
            "exposure": "_selected_feature_exposure.csv",
            "importance": "_feature_importance_drift.csv",
        }.items():
            df = _read_csv(prefix.with_name(prefix.name + suffix))
            if df.empty:
                continue
            if "fold" in df.columns:
                df = df[pd.to_numeric(df["fold"], errors="coerce").fillna(-1).astype(int).eq(int(focus_fold))].copy()
            if wanted and "variant" in df.columns:
                df = df[df["variant"].astype(str).isin(wanted)].copy()
            if df.empty:
                continue
            df["run_label"] = label
            df["artifact_prefix"] = str(prefix)
            frames[key].append(df)
    return {
        key: pd.concat(vals, ignore_index=True) if vals else pd.DataFrame()
        for key, vals in frames.items()
    }


def _failure_reason_counts(labels: pd.Series) -> str:
    counts: Counter[str] = Counter()
    for label in labels.fillna("").astype(str):
        for part in label.split("+"):
            part = part.strip()
            if part and part != "pass":
                counts[part] += 1
    return ";".join(f"{k}:{v}" for k, v in counts.most_common(8))


def _top_regime_failures(regime: pd.DataFrame) -> str:
    if regime.empty:
        return ""
    work = regime.copy()
    work["alpha_gate_pass"] = work.get("alpha_gate_pass", False).map(_safe_bool)
    fail = work[~work["alpha_gate_pass"]].copy()
    if fail.empty:
        return ""
    counts = Counter(str(x) for x in fail.get("regime_proxy_expost", pd.Series(dtype=str)).fillna(""))
    return ";".join(f"{k}:{v}" for k, v in counts.most_common(6) if k)


def _top_exante_regime_failures(regime: pd.DataFrame) -> str:
    if regime.empty:
        return ""
    work = regime.copy()
    work["alpha_gate_pass"] = work.get("alpha_gate_pass", False).map(_safe_bool)
    fail = work[~work["alpha_gate_pass"]].copy()
    if fail.empty:
        return ""
    counts = Counter(str(x) for x in fail.get("regime_exante", pd.Series(dtype=str)).fillna(""))
    return ";".join(f"{k}:{v}" for k, v in counts.most_common(6) if k)


def summarize_feature_exposure(exposure: pd.DataFrame, *, max_features: int = 8) -> str:
    if exposure.empty or "feature" not in exposure.columns:
        return ""
    work = exposure.copy()
    work["top_minus_all"] = pd.to_numeric(work.get("top_minus_all", 0.0), errors="coerce").fillna(0.0)
    rows = []
    for feature, g in work.groupby("feature", sort=False):
        vals = g["top_minus_all"].astype(float)
        mean = float(vals.mean())
        abs_mean = float(vals.abs().mean())
        sign = "+" if mean >= 0.0 else "-"
        same_sign = float((np.sign(vals) == np.sign(mean if mean != 0.0 else 1.0)).mean() * 100.0)
        rows.append(
            {
                "feature": str(feature),
                "mean": mean,
                "abs_mean": abs_mean,
                "sign": sign,
                "same_sign_pct": same_sign,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return ""
    out = out.sort_values(["abs_mean", "same_sign_pct"], ascending=[False, False]).head(int(max_features))
    return ";".join(
        f"{r.feature}:{r.mean:+.3f}/{r.same_sign_pct:.0f}%"
        for r in out.itertuples(index=False)
    )


def summarize_drift_importance(
    importance: pd.DataFrame,
    *,
    min_importance_share_pct: float = 2.0,
    psi_threshold: float = 0.30,
    std_diff_threshold: float = 0.60,
    max_features: int = 8,
) -> str:
    if importance.empty or "feature" not in importance.columns:
        return ""
    work = importance.copy()
    for col in ("importance_share_pct", "psi", "std_mean_diff"):
        work[col] = pd.to_numeric(work.get(col, 0.0), errors="coerce").fillna(0.0)
    drifted = work[
        (work["importance_share_pct"] >= float(min_importance_share_pct))
        & ((work["psi"] >= float(psi_threshold)) | (work["std_mean_diff"] >= float(std_diff_threshold)))
    ].copy()
    if drifted.empty:
        return ""
    grouped = (
        drifted.groupby("feature", sort=False)
        .agg(
            count=("feature", "size"),
            mean_importance_share_pct=("importance_share_pct", "mean"),
            max_psi=("psi", "max"),
            max_std_mean_diff=("std_mean_diff", "max"),
        )
        .reset_index()
    )
    grouped["_rank"] = (
        grouped["count"] * 100.0
        + grouped["mean_importance_share_pct"]
        + grouped["max_psi"]
        + grouped["max_std_mean_diff"]
    )
    grouped = grouped.sort_values("_rank", ascending=False).head(int(max_features))
    return ";".join(
        f"{r.feature}:{int(r.count)}x/share={r.mean_importance_share_pct:.1f}/psi={r.max_psi:.2f}/std={r.max_std_mean_diff:.2f}"
        for r in grouped.itertuples(index=False)
    )


def _verdict(row: dict[str, object]) -> tuple[str, str]:
    pass_rate = _safe_float(row.get("fold_pass_rate_pct", 0.0))
    worst_top = _safe_float(row.get("worst_top_mean_return_pct", 0.0))
    worst_spread = _safe_float(row.get("worst_top_minus_all_pct", 0.0))
    regime_failures = str(row.get("recurring_regime_failures", ""))
    exante_failures = str(row.get("recurring_exante_regime_failures", ""))
    drift = str(row.get("drifted_important_features", ""))
    exposure = str(row.get("recurring_top_feature_exposure", ""))
    if pass_rate >= 100.0 and worst_top > 0.0 and worst_spread > 0.0:
        return ("focus_fold_stable_pass", "fold passes across all provided runs; continue only with broader raw-model gates")
    if worst_top <= 0.0 and worst_spread <= 0.0:
        if drift and exposure:
            return ("absolute_failure_with_drifted_exposure", "negative top bucket and spread persist; inspect drifted important features and top-bucket exposures")
        if exante_failures:
            return ("absolute_failure_exante_regime_identifiable", "negative top bucket and spread persist inside signal-date regimes")
        if regime_failures:
            return ("absolute_failure_regime_sensitive", "negative top bucket and spread persist inside recurring regimes")
        return ("absolute_and_relative_failure", "top bucket is negative and underperforms the pool")
    if worst_top <= 0.0:
        return ("absolute_top_bucket_failure", "top bucket is negative even when relative spread may be positive")
    if worst_spread <= 0.0:
        return ("pool_relative_failure", "top bucket can be positive but fails to beat the full pool")
    return ("mixed_sample_instability", "fold result is sample-sensitive; do not advance without stability")


def build_fold_failure_summary(
    artifacts: dict[str, pd.DataFrame],
    *,
    focus_fold: int,
    min_importance_share_pct: float = 2.0,
    psi_threshold: float = 0.30,
    std_diff_threshold: float = 0.60,
) -> pd.DataFrame:
    variant = artifacts.get("variant", pd.DataFrame())
    if variant.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    regime = artifacts.get("regime", pd.DataFrame())
    exante_regime = artifacts.get("exante_regime", pd.DataFrame())
    exposure = artifacts.get("exposure", pd.DataFrame())
    importance = artifacts.get("importance", pd.DataFrame())
    for name, g in variant.groupby("variant", sort=True):
        work = g.copy()
        work["alpha_gate_pass"] = work.get("alpha_gate_pass", False).map(_safe_bool)
        work["top_mean_return_pct"] = pd.to_numeric(work.get("top_mean_return_pct", 0.0), errors="coerce").fillna(0.0)
        work["top_minus_all_pct"] = pd.to_numeric(work.get("top_minus_all_pct", 0.0), errors="coerce").fillna(0.0)
        work["rank_ic_mean"] = pd.to_numeric(work.get("rank_ic_mean", 0.0), errors="coerce").fillna(0.0)
        reg = regime[regime.get("variant", pd.Series(dtype=str)).astype(str).eq(str(name))].copy() if not regime.empty else pd.DataFrame()
        exreg = exante_regime[exante_regime.get("variant", pd.Series(dtype=str)).astype(str).eq(str(name))].copy() if not exante_regime.empty else pd.DataFrame()
        exp = exposure[exposure.get("variant", pd.Series(dtype=str)).astype(str).eq(str(name))].copy() if not exposure.empty else pd.DataFrame()
        imp = importance[importance.get("variant", pd.Series(dtype=str)).astype(str).eq(str(name))].copy() if not importance.empty else pd.DataFrame()
        row = {
            "focus_fold": int(focus_fold),
            "variant": str(name),
            "run_count": int(len(work)),
            "fold_pass_count": int(work["alpha_gate_pass"].sum()),
            "fold_pass_rate_pct": float(work["alpha_gate_pass"].mean() * 100.0),
            "worst_top_mean_return_pct": float(work["top_mean_return_pct"].min()),
            "mean_top_mean_return_pct": float(work["top_mean_return_pct"].mean()),
            "worst_top_minus_all_pct": float(work["top_minus_all_pct"].min()),
            "mean_top_minus_all_pct": float(work["top_minus_all_pct"].mean()),
            "mean_rank_ic": float(work["rank_ic_mean"].mean()),
            "failure_reason_counts": _failure_reason_counts(work.get("failure_label", pd.Series(dtype=str))),
            "recurring_regime_failures": _top_regime_failures(reg),
            "recurring_exante_regime_failures": _top_exante_regime_failures(exreg),
            "recurring_top_feature_exposure": summarize_feature_exposure(exp),
            "drifted_important_features": summarize_drift_importance(
                imp,
                min_importance_share_pct=float(min_importance_share_pct),
                psi_threshold=float(psi_threshold),
                std_diff_threshold=float(std_diff_threshold),
            ),
            "run_labels": ",".join(str(x) for x in work.get("run_label", pd.Series(dtype=str)).tolist()),
        }
        verdict, action = _verdict(row)
        row["failure_matrix_verdict"] = verdict
        row["recommended_next_action"] = action
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["failure_matrix_verdict", "fold_pass_rate_pct", "mean_top_minus_all_pct"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def build_run_matrix(artifacts: dict[str, pd.DataFrame]) -> pd.DataFrame:
    variant = artifacts.get("variant", pd.DataFrame())
    if variant.empty:
        return pd.DataFrame()
    keep = [
        "run_label",
        "fold",
        "variant",
        "test_start",
        "test_end",
        "top_mean_return_pct",
        "all_mean_return_pct",
        "top_minus_all_pct",
        "top_minus_bottom_pct",
        "rank_ic_mean",
        "alpha_gate_pass",
        "failure_label",
    ]
    cols = [c for c in keep if c in variant.columns]
    return variant[cols].sort_values(["variant", "run_label"]).reset_index(drop=True)


def _write_outputs(
    summary: pd.DataFrame,
    run_matrix: pd.DataFrame,
    *,
    label: str,
    write_latest: bool,
) -> dict[str, str]:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slug(label or "raw_model_fold_failure_matrix")
    prefix = BACKTEST_DIR / f"quant_raw_model_fold_failure_matrix_{slug}_{ts}"
    paths = {
        "variant_summary": str(prefix.with_name(prefix.name + "_variant_summary.csv")),
        "run_matrix": str(prefix.with_name(prefix.name + "_run_matrix.csv")),
        "verdict": str(prefix.with_name(prefix.name + "_verdict.json")),
    }
    summary.to_csv(paths["variant_summary"], index=False, encoding="utf-8-sig")
    run_matrix.to_csv(paths["run_matrix"], index=False, encoding="utf-8-sig")
    payload = {
        "label": str(label),
        "generated_at": ts,
        "variant_count": int(len(summary)),
        "outputs": paths,
        "verdict_counts": summary.get("failure_matrix_verdict", pd.Series(dtype=str)).value_counts().to_dict()
        if not summary.empty
        else {},
    }
    Path(paths["verdict"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if write_latest:
        latest = BACKTEST_DIR / f"quant_raw_model_fold_failure_matrix_latest_{slug}"
        latest_paths = {
            "variant_summary": str(latest.with_name(latest.name + "_variant_summary.csv")),
            "run_matrix": str(latest.with_name(latest.name + "_run_matrix.csv")),
            "verdict": str(latest.with_name(latest.name + "_verdict.json")),
        }
        summary.to_csv(latest_paths["variant_summary"], index=False, encoding="utf-8-sig")
        run_matrix.to_csv(latest_paths["run_matrix"], index=False, encoding="utf-8-sig")
        latest_payload = dict(payload)
        latest_payload["outputs"] = latest_paths
        Path(latest_paths["verdict"]).write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.update({f"latest_{k}": v for k, v in latest_paths.items()})
    return paths


def main() -> int:
    p = argparse.ArgumentParser(description="Aggregate critical fold failures across raw-model instability runs")
    p.add_argument(
        "--artifact-prefixes",
        default=str(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_h10_ranknorm*_7fold*"),
        help="comma-separated artifact prefixes or glob patterns; suffixes are inferred",
    )
    p.add_argument("--variants", default="baseline,rank_normalized,blend_rank_norm_huber,blend_rank_norm_l1,rank_norm_drop_high_drift")
    p.add_argument("--focus-fold", type=int, default=7)
    p.add_argument("--min-importance-share-pct", type=float, default=2.0)
    p.add_argument("--drift-psi-threshold", type=float, default=0.30)
    p.add_argument("--drift-std-diff-threshold", type=float, default=0.60)
    p.add_argument("--label", default="h10_fold7_failure_matrix")
    p.add_argument("--write-latest", action="store_true")
    args = p.parse_args()

    prefixes = _discover_prefixes(str(args.artifact_prefixes))
    artifacts = load_fold_artifacts(prefixes, variants=_parse_str_list(args.variants), focus_fold=int(args.focus_fold))
    summary = build_fold_failure_summary(
        artifacts,
        focus_fold=int(args.focus_fold),
        min_importance_share_pct=float(args.min_importance_share_pct),
        psi_threshold=float(args.drift_psi_threshold),
        std_diff_threshold=float(args.drift_std_diff_threshold),
    )
    if summary.empty:
        raise SystemExit("No usable fold artifacts found")
    run_matrix = build_run_matrix(artifacts)
    paths = _write_outputs(summary, run_matrix, label=str(args.label), write_latest=bool(args.write_latest))
    print(summary.to_string(index=False))
    print("outputs=" + json.dumps(paths, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
