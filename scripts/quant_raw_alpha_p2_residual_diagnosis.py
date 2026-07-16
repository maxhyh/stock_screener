#!/usr/bin/env python3
"""Decision layer joining raw-universe alpha, final static alpha, and P2 residual.

This script consumes existing diagnostics instead of rerunning heavy research
snapshots:

- `quant_stage_transition_diagnosis.py` score/transition/alpha-decay outputs
- `quant_static_to_p2_pass_through_diagnosis.py` summary output

It is designed for the post-v29 question: is the problem raw model alpha,
pipeline/ranking attrition, or P2 path execution residual?
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
BACKTEST_DIR = BASE_DIR / "output" / "backtest"

DEFAULT_RAW_STAGE = "raw_scored_post_indicator"
DEFAULT_FINAL_STAGE = "final_target_weight"
DEFAULT_RAW_SCORE_COLS = ["ml_score", "hybrid_score", "refactor_score", "execution_score", "liquidity_score"]
DEFAULT_FINAL_SCORE_COLS = ["target_weight", "portfolio_rank_score"]


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


def _parse_list(raw: str | list[str] | tuple[str, ...] | None, default: list[str]) -> list[str]:
    if raw is None:
        return list(default)
    if isinstance(raw, str):
        values = [x.strip() for x in raw.split(",") if x.strip()]
    else:
        values = [str(x).strip() for x in raw if str(x).strip()]
    return values or list(default)


def _latest(pattern: str) -> Path | None:
    matches = sorted(glob.glob(str(BACKTEST_DIR / pattern)))
    return Path(matches[-1]) if matches else None


def _load_csv(path: str | Path | None) -> pd.DataFrame:
    if path is None or not str(path).strip():
        return pd.DataFrame()
    fp = Path(path).expanduser().resolve()
    if not fp.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(fp)
    except Exception:
        return pd.DataFrame()


def _score_pass(row: pd.Series | dict[str, object]) -> bool:
    get = row.get if isinstance(row, dict) else row.get
    return (
        _safe_float(get("top_mean_forward_return_pct", 0.0)) > 0.0
        and _safe_float(get("top_minus_all_pct", 0.0)) > 0.0
        and _safe_float(get("top_minus_bottom_pct", 0.0)) > 0.0
        and _safe_float(get("rank_ic_mean", 0.0)) > 0.0
    )


def _score_strength(row: pd.Series) -> float:
    return (
        _safe_float(row.get("top_mean_forward_return_pct", 0.0))
        + _safe_float(row.get("top_minus_all_pct", 0.0))
        + _safe_float(row.get("top_minus_bottom_pct", 0.0))
        + 10.0 * _safe_float(row.get("rank_ic_mean", 0.0))
    )


def _best_score(rows: pd.DataFrame) -> dict[str, object]:
    if rows.empty:
        return {
            "score_col": "",
            "score_pass": False,
            "top_mean_forward_return_pct": 0.0,
            "top_minus_all_pct": 0.0,
            "top_minus_bottom_pct": 0.0,
            "rank_ic_mean": 0.0,
        }
    work = rows.copy()
    work["_score_pass"] = work.apply(_score_pass, axis=1)
    work["_strength"] = work.apply(_score_strength, axis=1)
    passed = work[work["_score_pass"]].copy()
    best = (passed if not passed.empty else work).sort_values("_strength", ascending=False).iloc[0]
    return {
        "score_col": str(best.get("score_col", "")),
        "score_pass": bool(best.get("_score_pass", False)),
        "top_mean_forward_return_pct": _safe_float(best.get("top_mean_forward_return_pct", 0.0)),
        "top_minus_all_pct": _safe_float(best.get("top_minus_all_pct", 0.0)),
        "top_minus_bottom_pct": _safe_float(best.get("top_minus_bottom_pct", 0.0)),
        "rank_ic_mean": _safe_float(best.get("rank_ic_mean", 0.0)),
        "all_mean_forward_return_pct": _safe_float(best.get("all_mean_forward_return_pct", 0.0)),
        "top_industry_label": str(best.get("top_industry_label", "") or ""),
        "top_industry_count_weight_pct": _safe_float(best.get("top_industry_count_weight_pct", 0.0)),
    }


def _worst_transition(transition_summary: pd.DataFrame) -> dict[str, object]:
    if transition_summary.empty:
        return {
            "damaging_transition": False,
            "from_stage": "",
            "to_stage": "",
            "dropped_minus_kept_pct": 0.0,
            "from_mean_forward_return_pct": 0.0,
            "to_mean_forward_return_pct": 0.0,
        }
    work = transition_summary.copy()
    work["_dropped_minus_kept"] = pd.to_numeric(work.get("dropped_minus_kept_pct", 0.0), errors="coerce").fillna(0.0)
    work["_from_mean"] = pd.to_numeric(work.get("from_mean_forward_return_pct", 0.0), errors="coerce").fillna(0.0)
    work["_to_mean"] = pd.to_numeric(work.get("to_mean_forward_return_pct", 0.0), errors="coerce").fillna(0.0)
    harmful = work[(work["_dropped_minus_kept"] > 0.0) & (work["_to_mean"] < work["_from_mean"])].copy()
    if harmful.empty:
        return {
            "damaging_transition": False,
            "from_stage": "",
            "to_stage": "",
            "dropped_minus_kept_pct": 0.0,
            "from_mean_forward_return_pct": 0.0,
            "to_mean_forward_return_pct": 0.0,
        }
    row = harmful.sort_values("_dropped_minus_kept", ascending=False).iloc[0]
    return {
        "damaging_transition": True,
        "from_stage": str(row.get("from_stage", "")),
        "to_stage": str(row.get("to_stage", "")),
        "dropped_minus_kept_pct": _safe_float(row.get("dropped_minus_kept_pct", 0.0)),
        "from_mean_forward_return_pct": _safe_float(row.get("from_mean_forward_return_pct", 0.0)),
        "to_mean_forward_return_pct": _safe_float(row.get("to_mean_forward_return_pct", 0.0)),
    }


def _p2_row(static_to_p2_summary: pd.DataFrame) -> dict[str, object]:
    if static_to_p2_summary.empty:
        return {
            "p2_pass_through_verdict": "missing_static_to_p2_evidence",
            "p2_aligned_days": 0,
            "relative_return_gap_sum_pct": 0.0,
            "static_positive_days": 0,
            "static_positive_p2_underperform_days": 0,
        }
    row = static_to_p2_summary.iloc[0]
    return {
        "p2_pass_through_verdict": str(row.get("verdict", "")),
        "p2_aligned_days": _safe_int(row.get("aligned_days", 0)),
        "relative_return_gap_sum_pct": _safe_float(row.get("relative_return_gap_sum_pct", 0.0)),
        "static_positive_days": _safe_int(row.get("static_positive_days", 0)),
        "static_positive_p2_underperform_days": _safe_int(row.get("static_positive_p2_underperform_days", 0)),
        "static_positive_p2_underperform_rate_pct": _safe_float(
            row.get("static_positive_p2_underperform_rate_pct", 0.0)
        ),
        "cash_drag_proxy_sum_pct": _safe_float(row.get("cash_drag_proxy_sum_pct", 0.0)),
        "holiday_guard_days": _safe_int(row.get("holiday_guard_days", 0)),
        "exit_block_delta_sum": _safe_int(row.get("exit_block_delta_sum", 0)),
        "target_weight_gap_mean": _safe_float(row.get("target_weight_gap_mean", 0.0)),
    }


def _overall_verdict(row: dict[str, object]) -> tuple[str, str]:
    raw_ml_pass = bool(row.get("raw_ml_score_pass", False))
    raw_any_pass = bool(row.get("raw_any_score_pass", False))
    final_pass = bool(row.get("final_gate_score_pass", False))
    p2_verdict = str(row.get("p2_pass_through_verdict", ""))
    damaging = bool(row.get("damaging_transition", False))
    p2_failed = p2_verdict not in {"static_alpha_p2_passed"} and not p2_verdict.startswith("missing_")

    if not final_pass:
        if damaging:
            return (
                "fix_pipeline_alpha_attrition_before_profile",
                "final gate score failed and a damaging transition drops better names than it keeps",
            )
        return ("stop_profile_evolution_final_alpha_failed", "final target/rank score does not pass static alpha checks")
    if p2_failed:
        if not raw_ml_pass and not raw_any_pass:
            return (
                "final_static_alpha_not_p2_executed_raw_alpha_weak",
                "final static score passes, but raw-universe scores are weak and P2 pass-through fails",
            )
        return (
            "final_static_alpha_not_p2_executed",
            "final static score passes, but same-calendar P2 return path fails versus the main profile",
        )
    if final_pass and p2_verdict == "static_alpha_p2_passed":
        return (
            "static_and_p2_alpha_passed_needs_long_windows",
            "static alpha and P2 pass-through passed; still requires 60/90/120 promotion evidence",
        )
    if not raw_ml_pass:
        return (
            "raw_ml_alpha_weak_needs_model_review",
            "raw ML score fails full-universe top/spread/RankIC checks",
        )
    return ("mixed_needs_review", "evidence is incomplete or mixed")


def build_raw_alpha_p2_residual_report(
    *,
    score_stage_summary: pd.DataFrame,
    transition_summary: pd.DataFrame,
    static_to_p2_summary: pd.DataFrame,
    profile: str,
    main_profile: str,
    raw_stage: str = DEFAULT_RAW_STAGE,
    final_stage: str = DEFAULT_FINAL_STAGE,
    raw_score_cols: list[str] | None = None,
    final_score_cols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_score_cols = raw_score_cols or DEFAULT_RAW_SCORE_COLS
    final_score_cols = final_score_cols or DEFAULT_FINAL_SCORE_COLS
    score = score_stage_summary.copy()
    if score.empty:
        score_candidates = pd.DataFrame()
    else:
        score_candidates = score[
            score["research_stage"].astype(str).isin([raw_stage, final_stage])
            & score["score_col"].astype(str).isin(set(raw_score_cols) | set(final_score_cols))
        ].copy()
        score_candidates["score_pass"] = score_candidates.apply(_score_pass, axis=1)
        score_candidates["score_strength"] = score_candidates.apply(_score_strength, axis=1)

    raw_rows = score_candidates[
        score_candidates.get("research_stage", pd.Series(dtype=str)).astype(str).eq(raw_stage)
        & score_candidates.get("score_col", pd.Series(dtype=str)).astype(str).isin(raw_score_cols)
    ].copy()
    final_rows = score_candidates[
        score_candidates.get("research_stage", pd.Series(dtype=str)).astype(str).eq(final_stage)
        & score_candidates.get("score_col", pd.Series(dtype=str)).astype(str).isin(final_score_cols)
    ].copy()
    raw_best = _best_score(raw_rows)
    final_best = _best_score(final_rows)
    raw_ml = raw_rows[raw_rows.get("score_col", pd.Series(dtype=str)).astype(str).eq("ml_score")].copy()
    raw_ml_best = _best_score(raw_ml)
    transition = _worst_transition(transition_summary)
    p2 = _p2_row(static_to_p2_summary)

    row: dict[str, object] = {
        "profile": profile,
        "main_profile": main_profile,
        "raw_stage": raw_stage,
        "final_stage": final_stage,
        "raw_ml_score_pass": bool(raw_ml_best.get("score_pass", False)),
        "raw_ml_top_mean_forward_return_pct": _safe_float(raw_ml_best.get("top_mean_forward_return_pct", 0.0)),
        "raw_ml_top_minus_all_pct": _safe_float(raw_ml_best.get("top_minus_all_pct", 0.0)),
        "raw_ml_top_minus_bottom_pct": _safe_float(raw_ml_best.get("top_minus_bottom_pct", 0.0)),
        "raw_ml_rank_ic_mean": _safe_float(raw_ml_best.get("rank_ic_mean", 0.0)),
        "raw_any_score_pass": bool(raw_best.get("score_pass", False)),
        "raw_best_score_col": str(raw_best.get("score_col", "")),
        "raw_best_top_mean_forward_return_pct": _safe_float(raw_best.get("top_mean_forward_return_pct", 0.0)),
        "raw_best_top_minus_all_pct": _safe_float(raw_best.get("top_minus_all_pct", 0.0)),
        "raw_best_top_minus_bottom_pct": _safe_float(raw_best.get("top_minus_bottom_pct", 0.0)),
        "raw_best_rank_ic_mean": _safe_float(raw_best.get("rank_ic_mean", 0.0)),
        "raw_best_top_industry_label": str(raw_best.get("top_industry_label", "")),
        "raw_best_top_industry_weight_pct": _safe_float(raw_best.get("top_industry_count_weight_pct", 0.0)),
        "final_gate_score_pass": bool(final_best.get("score_pass", False)),
        "final_best_score_col": str(final_best.get("score_col", "")),
        "final_best_top_mean_forward_return_pct": _safe_float(final_best.get("top_mean_forward_return_pct", 0.0)),
        "final_best_top_minus_all_pct": _safe_float(final_best.get("top_minus_all_pct", 0.0)),
        "final_best_top_minus_bottom_pct": _safe_float(final_best.get("top_minus_bottom_pct", 0.0)),
        "final_best_rank_ic_mean": _safe_float(final_best.get("rank_ic_mean", 0.0)),
    }
    row.update({f"transition_{k}": v for k, v in transition.items() if k != "damaging_transition"})
    row["damaging_transition"] = bool(transition.get("damaging_transition", False))
    row.update(p2)
    verdict, action = _overall_verdict(row)
    row["overall_verdict"] = verdict
    row["recommended_next_action"] = action

    lead = [
        "profile",
        "overall_verdict",
        "recommended_next_action",
        "raw_ml_score_pass",
        "raw_ml_top_mean_forward_return_pct",
        "raw_ml_rank_ic_mean",
        "raw_any_score_pass",
        "raw_best_score_col",
        "raw_best_top_mean_forward_return_pct",
        "raw_best_rank_ic_mean",
        "final_gate_score_pass",
        "final_best_score_col",
        "final_best_top_mean_forward_return_pct",
        "final_best_rank_ic_mean",
        "p2_pass_through_verdict",
        "relative_return_gap_sum_pct",
        "static_positive_days",
        "static_positive_p2_underperform_days",
        "damaging_transition",
        "transition_from_stage",
        "transition_to_stage",
        "transition_dropped_minus_kept_pct",
    ]
    summary = pd.DataFrame([row])
    summary = summary[[c for c in lead if c in summary.columns] + [c for c in summary.columns if c not in lead]]
    if not score_candidates.empty:
        score_candidates = score_candidates.sort_values(
            ["research_stage", "score_pass", "score_strength"],
            ascending=[True, False, False],
        ).reset_index(drop=True)
    return summary, score_candidates


def _default_score_stage_path(label: str) -> Path | None:
    if label:
        latest = BACKTEST_DIR / f"quant_stage_transition_diagnosis_latest_{label}_score_stage_summary.csv"
        if latest.exists():
            return latest
        return _latest(f"quant_stage_transition_diagnosis_{label}_*_score_stage_summary.csv")
    return BACKTEST_DIR / "quant_stage_transition_diagnosis_latest_score_stage_summary.csv"


def _default_transition_path(label: str) -> Path | None:
    if label:
        latest = BACKTEST_DIR / f"quant_stage_transition_diagnosis_latest_{label}_transition_summary.csv"
        if latest.exists():
            return latest
        return _latest(f"quant_stage_transition_diagnosis_{label}_*_transition_summary.csv")
    return BACKTEST_DIR / "quant_stage_transition_diagnosis_latest_transition_summary.csv"


def _default_static_to_p2_path(profile: str) -> Path | None:
    slug = _slug(profile)
    latest = BACKTEST_DIR / f"quant_static_to_p2_pass_through_latest_{slug}_summary.csv"
    if latest.exists():
        return latest
    return _latest(f"quant_static_to_p2_pass_through_{slug}_*_summary.csv")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose raw alpha, final static alpha, and P2 residual")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--main-profile", default="quality_regime")
    parser.add_argument("--stage-label", default="", help="Label used by quant_stage_transition_diagnosis latest outputs")
    parser.add_argument("--score-stage-summary", default="")
    parser.add_argument("--transition-summary", default="")
    parser.add_argument("--static-to-p2-summary", default="")
    parser.add_argument("--raw-stage", default=DEFAULT_RAW_STAGE)
    parser.add_argument("--final-stage", default=DEFAULT_FINAL_STAGE)
    parser.add_argument("--raw-score-cols", default=",".join(DEFAULT_RAW_SCORE_COLS))
    parser.add_argument("--final-score-cols", default=",".join(DEFAULT_FINAL_SCORE_COLS))
    parser.add_argument("--write-latest", action="store_true")
    args = parser.parse_args()

    score_path = Path(args.score_stage_summary).expanduser().resolve() if str(args.score_stage_summary or "").strip() else _default_score_stage_path(str(args.stage_label))
    transition_path = Path(args.transition_summary).expanduser().resolve() if str(args.transition_summary or "").strip() else _default_transition_path(str(args.stage_label))
    static_path = Path(args.static_to_p2_summary).expanduser().resolve() if str(args.static_to_p2_summary or "").strip() else _default_static_to_p2_path(str(args.profile))
    score_stage_summary = _load_csv(score_path)
    transition_summary = _load_csv(transition_path)
    static_to_p2_summary = _load_csv(static_path)
    summary, score_candidates = build_raw_alpha_p2_residual_report(
        score_stage_summary=score_stage_summary,
        transition_summary=transition_summary,
        static_to_p2_summary=static_to_p2_summary,
        profile=str(args.profile),
        main_profile=str(args.main_profile),
        raw_stage=str(args.raw_stage),
        final_stage=str(args.final_stage),
        raw_score_cols=_parse_list(args.raw_score_cols, DEFAULT_RAW_SCORE_COLS),
        final_score_cols=_parse_list(args.final_score_cols, DEFAULT_FINAL_SCORE_COLS),
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slug(str(args.profile))
    summary_fp = BACKTEST_DIR / f"quant_raw_alpha_p2_residual_diagnosis_{slug}_{ts}_summary.csv"
    candidates_fp = BACKTEST_DIR / f"quant_raw_alpha_p2_residual_diagnosis_{slug}_{ts}_score_candidates.csv"
    json_fp = BACKTEST_DIR / f"quant_raw_alpha_p2_residual_diagnosis_{slug}_{ts}.json"
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_fp, index=False, encoding="utf-8-sig")
    score_candidates.to_csv(candidates_fp, index=False, encoding="utf-8-sig")
    payload: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile": str(args.profile),
        "main_profile": str(args.main_profile),
        "score_stage_summary": str(score_path or ""),
        "transition_summary": str(transition_path or ""),
        "static_to_p2_summary": str(static_path or ""),
        "summary": str(summary_fp),
        "score_candidates": str(candidates_fp),
        "rows": summary.to_dict(orient="records"),
    }
    json_fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest_summary = BACKTEST_DIR / f"quant_raw_alpha_p2_residual_diagnosis_latest_{slug}_summary.csv"
        latest_candidates = BACKTEST_DIR / f"quant_raw_alpha_p2_residual_diagnosis_latest_{slug}_score_candidates.csv"
        latest_json = BACKTEST_DIR / f"quant_raw_alpha_p2_residual_diagnosis_latest_{slug}.json"
        summary.to_csv(latest_summary, index=False, encoding="utf-8-sig")
        score_candidates.to_csv(latest_candidates, index=False, encoding="utf-8-sig")
        latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.to_csv(BACKTEST_DIR / "quant_raw_alpha_p2_residual_diagnosis_latest_summary.csv", index=False, encoding="utf-8-sig")
        score_candidates.to_csv(
            BACKTEST_DIR / "quant_raw_alpha_p2_residual_diagnosis_latest_score_candidates.csv",
            index=False,
            encoding="utf-8-sig",
        )
        (BACKTEST_DIR / "quant_raw_alpha_p2_residual_diagnosis_latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(summary.to_string(index=False))
    print(f"raw_alpha_p2_residual_summary={summary_fp}")
    print(f"raw_alpha_p2_residual_score_candidates={candidates_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
