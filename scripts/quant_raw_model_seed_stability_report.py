#!/usr/bin/env python3
"""Aggregate raw-model family runs into a seed/sample stability gate.

This script consumes existing
`quant_raw_model_instability_attribution_*_variant_family_summary.csv`
artifacts. It does not train models, create profiles, or run P2. Its job is to
prevent cherry-picking a single lucky seed or sampling mode before a raw model
line advances to any capacity/P2 work.
"""

from __future__ import annotations

import argparse
import glob
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


def _discover_summary_files(raw: str) -> list[Path]:
    paths: list[Path] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        matches = glob.glob(part)
        if matches:
            paths.extend(Path(x).resolve() for x in matches)
        else:
            p = Path(part).expanduser().resolve()
            if p.exists():
                paths.append(p)
    return sorted(set(paths))


def _run_label_from_path(path: Path) -> str:
    stem = path.stem
    prefix = "quant_raw_model_instability_attribution_latest_"
    suffix = "_variant_family_summary"
    if stem.startswith(prefix):
        stem = stem[len(prefix) :]
    if stem.endswith(suffix):
        stem = stem[: -len(suffix)]
    return _slug(stem or path.stem)


def load_run_details(paths: list[Path], *, variants: list[str] | None = None) -> pd.DataFrame:
    wanted = set(variants or [])
    rows: list[dict[str, object]] = []
    for path in paths:
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if df.empty or "variant" not in df.columns:
            continue
        if wanted:
            df = df[df["variant"].astype(str).isin(wanted)].copy()
        run_label = _run_label_from_path(path)
        for row in df.to_dict(orient="records"):
            fold_count = _safe_int(row.get("fold_count", 0))
            pass_fold_count = _safe_int(row.get("pass_fold_count", 0))
            fold_pass_rate = _safe_float(row.get("fold_pass_rate_pct", 0.0))
            if fold_count > 0 and "fold_pass_rate_pct" not in row:
                fold_pass_rate = 100.0 * float(pass_fold_count) / float(fold_count)
            verdict = str(row.get("variant_family_verdict", "") or "")
            rows.append(
                {
                    "source_file": str(path),
                    "run_label": run_label,
                    "variant": str(row.get("variant", "")),
                    "variant_family_verdict": verdict,
                    "variant_model_gate_pass": verdict == "variant_model_gate_pass",
                    "fold_count": fold_count,
                    "pass_fold_count": pass_fold_count,
                    "fold_pass_rate_pct": fold_pass_rate,
                    "critical_fold_pass": _safe_bool(row.get("critical_fold_pass", False)),
                    "mean_top_return_pct": _safe_float(row.get("mean_top_return_pct", 0.0)),
                    "mean_top_minus_all_pct": _safe_float(row.get("mean_top_minus_all_pct", 0.0)),
                    "mean_rank_ic": _safe_float(row.get("mean_rank_ic", 0.0)),
                    "fold6_alpha_gate_pass": _safe_bool(row.get("fold6_alpha_gate_pass", False)),
                    "fold6_top_mean_return_pct": _safe_float(row.get("fold6_top_mean_return_pct", 0.0)),
                    "fold6_top_minus_all_pct": _safe_float(row.get("fold6_top_minus_all_pct", 0.0)),
                    "fold7_alpha_gate_pass": _safe_bool(row.get("fold7_alpha_gate_pass", False)),
                    "fold7_top_mean_return_pct": _safe_float(row.get("fold7_top_mean_return_pct", 0.0)),
                    "fold7_top_minus_all_pct": _safe_float(row.get("fold7_top_minus_all_pct", 0.0)),
                }
            )
    return pd.DataFrame(rows)


def _next_action(verdict: str) -> str:
    if verdict == "sample_stability_pass":
        return "eligible for next raw-model review only; still do not create profile/P2 without production training plan"
    if verdict == "insufficient_runs":
        return "rerun at least one independent seed and one deterministic sample-mode before judging the variant"
    if verdict == "critical_fold_unstable":
        return "keep capacity/P2 blocked; fix the critical fold across seeds/sample modes first"
    if verdict == "fold_stability_unstable":
        return "improve split stability across all folds before interpreting pooled alpha"
    if verdict == "pooled_alpha_unstable":
        return "raw objective/features are not robustly positive; revisit labels, drift handling, or features"
    return "do not advance to profile/P2; sample stability gate failed"


def build_stability_summary(
    details: pd.DataFrame,
    *,
    min_run_count: int = 2,
    required_pass_run_rate_pct: float = 100.0,
    min_fold_pass_rate_pct: float = 50.0,
) -> pd.DataFrame:
    if details.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for variant, g in details.groupby("variant", sort=True):
        run_count = int(len(g))
        pass_run_count = int(g["variant_model_gate_pass"].astype(bool).sum())
        pass_run_rate = 100.0 * pass_run_count / max(run_count, 1)
        all_critical = bool(g["critical_fold_pass"].astype(bool).all()) if run_count else False
        min_fold_rate = _safe_float(g["fold_pass_rate_pct"].min(), 0.0)
        min_mean_top = _safe_float(g["mean_top_return_pct"].min(), 0.0)
        min_mean_spread = _safe_float(g["mean_top_minus_all_pct"].min(), 0.0)
        min_rank_ic = _safe_float(g["mean_rank_ic"].min(), 0.0)
        worst_fold7_top = _safe_float(g["fold7_top_mean_return_pct"].min(), 0.0)
        worst_fold7_spread = _safe_float(g["fold7_top_minus_all_pct"].min(), 0.0)

        if run_count < int(min_run_count):
            stability_verdict = "insufficient_runs"
        elif not all_critical:
            stability_verdict = "critical_fold_unstable"
        elif min_fold_rate < float(min_fold_pass_rate_pct):
            stability_verdict = "fold_stability_unstable"
        elif min_mean_top <= 0.0 or min_mean_spread <= 0.0 or min_rank_ic <= 0.0:
            stability_verdict = "pooled_alpha_unstable"
        elif pass_run_rate < float(required_pass_run_rate_pct):
            stability_verdict = "sample_stability_failed"
        else:
            stability_verdict = "sample_stability_pass"

        rows.append(
            {
                "variant": str(variant),
                "run_count": run_count,
                "pass_run_count": pass_run_count,
                "pass_run_rate_pct": pass_run_rate,
                "required_pass_run_rate_pct": float(required_pass_run_rate_pct),
                "min_run_count": int(min_run_count),
                "min_fold_pass_rate_pct_required": float(min_fold_pass_rate_pct),
                "min_observed_fold_pass_rate_pct": min_fold_rate,
                "all_critical_fold_pass": all_critical,
                "min_mean_top_return_pct": min_mean_top,
                "min_mean_top_minus_all_pct": min_mean_spread,
                "min_mean_rank_ic": min_rank_ic,
                "worst_fold7_top_mean_return_pct": worst_fold7_top,
                "worst_fold7_top_minus_all_pct": worst_fold7_spread,
                "run_labels": ",".join(str(x) for x in g["run_label"].tolist()),
                "failed_run_labels": ",".join(str(x) for x in g.loc[~g["variant_model_gate_pass"].astype(bool), "run_label"].tolist()),
                "stability_verdict": stability_verdict,
                "recommended_next_action": _next_action(stability_verdict),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["stability_verdict", "pass_run_rate_pct", "min_observed_fold_pass_rate_pct", "min_mean_top_minus_all_pct"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def _write_outputs(
    summary: pd.DataFrame,
    details: pd.DataFrame,
    *,
    label: str,
    write_latest: bool,
    backtest_dir: Path = BACKTEST_DIR,
) -> dict[str, str]:
    backtest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slug(label or "raw_model_seed_stability")
    prefix = backtest_dir / f"quant_raw_model_seed_stability_report_{slug}_{ts}"
    paths = {
        "variant_summary": str(prefix.with_name(prefix.name + "_variant_summary.csv")),
        "run_detail": str(prefix.with_name(prefix.name + "_run_detail.csv")),
        "verdict": str(prefix.with_name(prefix.name + "_verdict.json")),
    }
    summary.to_csv(paths["variant_summary"], index=False)
    details.to_csv(paths["run_detail"], index=False)
    verdict_payload = {
        "label": str(label),
        "generated_at": ts,
        "variant_count": int(len(summary)),
        "sample_stability_pass_variants": summary.loc[
            summary.get("stability_verdict", pd.Series(dtype=str)).astype(str).eq("sample_stability_pass"),
            "variant",
        ].astype(str).tolist()
        if not summary.empty
        else [],
        "outputs": paths,
    }
    Path(paths["verdict"]).write_text(json.dumps(verdict_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if write_latest:
        latest_prefix = backtest_dir / f"quant_raw_model_seed_stability_report_latest_{slug}"
        latest_paths = {
            "variant_summary": str(latest_prefix.with_name(latest_prefix.name + "_variant_summary.csv")),
            "run_detail": str(latest_prefix.with_name(latest_prefix.name + "_run_detail.csv")),
            "verdict": str(latest_prefix.with_name(latest_prefix.name + "_verdict.json")),
        }
        summary.to_csv(latest_paths["variant_summary"], index=False)
        details.to_csv(latest_paths["run_detail"], index=False)
        latest_payload = dict(verdict_payload)
        latest_payload["outputs"] = latest_paths
        Path(latest_paths["verdict"]).write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.update({f"latest_{k}": v for k, v in latest_paths.items()})
    return paths


def main() -> int:
    p = argparse.ArgumentParser(description="Aggregate raw-model seed/sample stability evidence")
    p.add_argument(
        "--summary-files",
        default=str(BACKTEST_DIR / "quant_raw_model_instability_attribution_latest_*_variant_family_summary.csv"),
        help="comma-separated files or globs of variant_family_summary CSV artifacts",
    )
    p.add_argument("--variants", default="", help="optional comma-separated variant filter")
    p.add_argument("--min-run-count", type=int, default=2)
    p.add_argument("--required-pass-run-rate-pct", type=float, default=100.0)
    p.add_argument("--min-fold-pass-rate-pct", type=float, default=50.0)
    p.add_argument("--label", default="h10_raw_model_seed_stability")
    p.add_argument("--write-latest", action="store_true")
    args = p.parse_args()

    files = _discover_summary_files(str(args.summary_files))
    variants = _parse_str_list(args.variants)
    details = load_run_details(files, variants=variants or None)
    if details.empty:
        raise SystemExit("No usable variant_family_summary rows found")
    summary = build_stability_summary(
        details,
        min_run_count=int(args.min_run_count),
        required_pass_run_rate_pct=float(args.required_pass_run_rate_pct),
        min_fold_pass_rate_pct=float(args.min_fold_pass_rate_pct),
    )
    paths = _write_outputs(summary, details, label=str(args.label), write_latest=bool(args.write_latest))
    print(summary.to_string(index=False))
    print("outputs=" + json.dumps(paths, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
