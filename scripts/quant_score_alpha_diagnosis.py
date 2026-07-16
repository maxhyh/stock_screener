#!/usr/bin/env python3
"""Score-level alpha diagnostics for persisted daily recommendation artifacts.

This is intentionally a recommendation-proxy diagnostic. It compares score
columns available in daily CSV artifacts against forward open-to-open returns,
but it does not claim to reconstruct the full raw prediction universe.
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
sys.path.insert(0, str(BASE_DIR / "scripts"))

from quant_alpha_execution_attribution import (  # noqa: E402
    _attach_forward_returns,
    _discover_daily_paths,
    _load_daily_recommendations,
    _load_industry_map,
    _load_market_bars,
    _load_ods_market_bars,
    _parse_date,
    _top_industry_pct,
    _turnover_by_day,
)

BACKTEST_DIR = BASE_DIR / "output" / "backtest"


SCORE_CANDIDATES: list[tuple[str, str, str]] = [
    ("rank", "排名", "asc"),
    ("ml_score", "ML评分", "desc"),
    ("quality_score", "质量分", "desc"),
    ("signal_quality_score", "信号质量分", "desc"),
    ("hybrid_score", "综合分", "desc"),
    ("stability_score", "稳定分", "desc"),
    ("refactor_score", "重构分", "desc"),
    ("liquidity_score", "流动性分", "desc"),
    ("adv_capacity_score", "ADV容量分", "desc"),
    ("industry_balance_score", "行业均衡分", "desc"),
    ("portfolio_rank_score", "portfolio_rank_score", "desc"),
    ("reserve_safe_score", "reserve_safe_score", "desc"),
    ("reserve_capacity_score", "reserve_capacity_score", "desc"),
    ("tradability_safe_score", "tradability_safe_score", "desc"),
    ("exit_trap_safe_score", "exit_trap_safe_score", "desc"),
    ("exit_trap_risk_score", "exit_trap_risk_score", "asc"),
    ("target_weight", "target_weight", "desc"),
    ("target_weight_raw", "target_weight_raw", "desc"),
]

DEFAULT_ALPHA_GATE_SCORE_COLS = ("target_weight", "portfolio_rank_score")


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _parse_score_cols(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if raw is None:
        return list(DEFAULT_ALPHA_GATE_SCORE_COLS)
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in raw if str(p).strip()]
    return parts or list(DEFAULT_ALPHA_GATE_SCORE_COLS)


def _effective_score(s: pd.Series, direction: str) -> pd.Series:
    vals = pd.to_numeric(s, errors="coerce")
    if direction == "asc":
        vals = -vals
    return vals


def _rank_ic_values(df: pd.DataFrame, score_col: str, direction: str) -> list[float]:
    values: list[float] = []
    work = df.dropna(subset=["forward_return"]).copy()
    if work.empty or score_col not in work.columns:
        return values
    work["_score_eff"] = _effective_score(work[score_col], direction)
    for _, g in work.groupby("signal_date"):
        g = g.dropna(subset=["_score_eff", "forward_return"])
        if len(g) < 3 or g["_score_eff"].nunique(dropna=True) < 2 or g["forward_return"].nunique(dropna=True) < 2:
            continue
        ic = g["_score_eff"].rank().corr(g["forward_return"].rank())
        if pd.notna(ic) and np.isfinite(ic):
            values.append(float(ic))
    return values


def _quantile_spreads(df: pd.DataFrame, score_col: str, direction: str) -> list[float]:
    spreads: list[float] = []
    work = df.dropna(subset=["forward_return"]).copy()
    if work.empty or score_col not in work.columns:
        return spreads
    work["_score_eff"] = _effective_score(work[score_col], direction)
    for _, g in work.groupby("signal_date"):
        g = g.dropna(subset=["_score_eff", "forward_return"])
        if len(g) < 3:
            continue
        g = g.sort_values("_score_eff", ascending=False)
        n = max(1, int(np.ceil(len(g) / 3)))
        top = _safe_float(g.head(n)["forward_return"].mean(), np.nan)
        bottom = _safe_float(g.tail(n)["forward_return"].mean(), np.nan)
        if np.isfinite(top) and np.isfinite(bottom):
            spreads.append(top - bottom)
    return spreads


def _select_top_by_score(df: pd.DataFrame, score_col: str, direction: str, top_n: int) -> pd.DataFrame:
    if df.empty or score_col not in df.columns:
        return df.iloc[0:0].copy()
    work = df.copy()
    work["_score_eff"] = _effective_score(work[score_col], direction)
    work = work.dropna(subset=["_score_eff"]).copy()
    if work.empty:
        return work
    return (
        work.sort_values(["signal_date", "_score_eff"], ascending=[True, False])
        .groupby("signal_date", group_keys=False)
        .head(max(1, int(top_n)))
        .copy()
    )


def _top_industry_label(df: pd.DataFrame) -> str:
    if df.empty or "industry" not in df.columns:
        return ""
    s = df["industry"].fillna("未知").astype(str).str.strip().replace({"": "未知"})
    if s.empty:
        return ""
    return str(s.value_counts().index[0])


def _summarize_score(df: pd.DataFrame, *, label: str, score_col: str, direction: str, top_n: int) -> dict[str, object]:
    valid = df.dropna(subset=["forward_return"]).copy()
    score_values = pd.to_numeric(df.get(score_col, pd.Series(dtype=float)), errors="coerce")
    selected = _select_top_by_score(df, score_col, direction, top_n)
    selected_valid = selected.dropna(subset=["forward_return"]).copy()
    bottom = (
        df.assign(_score_eff=_effective_score(df[score_col], direction))
        .dropna(subset=["_score_eff", "forward_return"])
        .sort_values(["signal_date", "_score_eff"], ascending=[True, True])
        .groupby("signal_date", group_keys=False)
        .head(max(1, int(top_n)))
        .copy()
        if score_col in df.columns and not df.empty
        else df.iloc[0:0].copy()
    )
    ic_values = _rank_ic_values(df, score_col, direction)
    spreads = _quantile_spreads(df, score_col, direction)
    all_mean = _safe_float(valid["forward_return"].mean(), 0.0) if not valid.empty else 0.0
    top_mean = _safe_float(selected_valid["forward_return"].mean(), 0.0) if not selected_valid.empty else 0.0
    bottom_mean = _safe_float(bottom["forward_return"].mean(), 0.0) if not bottom.empty else 0.0
    ic_mean = float(np.mean(ic_values)) if ic_values else 0.0
    ic_std = float(np.std(ic_values, ddof=1)) if len(ic_values) > 1 else 0.0
    return {
        "score_label": label,
        "score_col": score_col,
        "direction": direction,
        "rows": int(len(df)),
        "valid_forward_rows": int(len(valid)),
        "days": int(valid["signal_date"].nunique()) if not valid.empty else 0,
        "score_non_null_rows": int(score_values.notna().sum()),
        "score_unique_values": int(score_values.nunique(dropna=True)),
        "all_mean_forward_return_pct": float(all_mean * 100.0),
        "top_n": int(top_n),
        "top_rows": int(len(selected)),
        "top_valid_forward_rows": int(len(selected_valid)),
        "top_days": int(selected_valid["signal_date"].nunique()) if not selected_valid.empty else 0,
        "top_mean_forward_return_pct": float(top_mean * 100.0),
        "top_median_forward_return_pct": float(selected_valid["forward_return"].median() * 100.0)
        if not selected_valid.empty
        else 0.0,
        "top_hit_rate_pct": float((selected_valid["forward_return"] > 0).mean() * 100.0)
        if not selected_valid.empty
        else 0.0,
        "bottom_mean_forward_return_pct": float(bottom_mean * 100.0),
        "top_minus_all_pct": float((top_mean - all_mean) * 100.0),
        "top_minus_bottom_pct": float((top_mean - bottom_mean) * 100.0),
        "rank_ic_mean": float(ic_mean),
        "icir": float(ic_mean / ic_std) if ic_std > 1e-12 else 0.0,
        "rank_ic_positive_day_rate_pct": float(np.mean(np.array(ic_values) > 0.0) * 100.0) if ic_values else 0.0,
        "quantile_spread_pct": float(np.mean(spreads) * 100.0) if spreads else 0.0,
        "turnover_proxy": float(_turnover_by_day(selected)),
        "top_mean_amount_signal": float(pd.to_numeric(selected_valid["amount_signal"], errors="coerce").mean())
        if (not selected_valid.empty and "amount_signal" in selected_valid.columns)
        else 0.0,
        "top_industry_label": _top_industry_label(selected),
        "top_industry_count_weight_pct": float(_top_industry_pct(selected)),
        "top_target_weight_sum_mean": float(
            selected.groupby("signal_date")["target_weight"].sum().mean()
            if "target_weight" in selected.columns and not selected.empty
            else 0.0
        ),
    }


def _infer_scores(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for label, col, direction in SCORE_CANDIDATES:
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        if vals.notna().sum() == 0 or vals.nunique(dropna=True) < 2:
            continue
        out.append((label, col, direction))
    return out


def evaluate_alpha_quality_gate(
    summary: pd.DataFrame,
    *,
    gate_score_cols: str | list[str] | tuple[str, ...] | None = None,
    min_top_mean_forward_return_pct: float = 0.0,
    min_top_minus_all_pct: float = 0.0,
    min_top_minus_bottom_pct: float = 0.0,
    min_rank_ic: float = 0.0,
    min_top_days: int = 5,
    min_top_valid_rows: int = 1,
) -> dict[str, Any]:
    """Evaluate whether final ranking/weight scores beat the candidate pool.

    This is a smoke gate for expensive P2 work. It intentionally evaluates
    persisted recommendation artifacts, so it should be treated as a
    recommendation-proxy gate rather than a full-universe raw alpha proof.
    """

    score_cols = _parse_score_cols(gate_score_cols)
    thresholds = {
        "min_top_mean_forward_return_pct": float(min_top_mean_forward_return_pct),
        "min_top_minus_all_pct": float(min_top_minus_all_pct),
        "min_top_minus_bottom_pct": float(min_top_minus_bottom_pct),
        "min_rank_ic": float(min_rank_ic),
        "min_top_days": int(max(0, int(min_top_days))),
        "min_top_valid_rows": int(max(0, int(min_top_valid_rows))),
    }
    if summary.empty or "score_col" not in summary.columns:
        return {
            "pass": False,
            "reasons": ["empty_score_summary"],
            "gate_score_cols": score_cols,
            "thresholds": thresholds,
            "evaluated": [],
        }

    gate_rows = summary[summary["score_col"].astype(str).isin(score_cols)].copy()
    if gate_rows.empty:
        return {
            "pass": False,
            "reasons": ["gate_scores_missing"],
            "gate_score_cols": score_cols,
            "thresholds": thresholds,
            "evaluated": [],
        }

    evaluated: list[dict[str, Any]] = []
    pass_any = False
    for _, row in gate_rows.iterrows():
        top_days = int(_safe_float(row.get("top_days", 0), 0.0))
        top_valid_rows = int(_safe_float(row.get("top_valid_forward_rows", 0), 0.0))
        top_mean = _safe_float(row.get("top_mean_forward_return_pct", np.nan), np.nan)
        top_minus_all = _safe_float(row.get("top_minus_all_pct", np.nan), np.nan)
        top_minus_bottom = _safe_float(row.get("top_minus_bottom_pct", np.nan), np.nan)
        rank_ic = _safe_float(row.get("rank_ic_mean", np.nan), np.nan)
        row_reasons: list[str] = []
        if top_days < thresholds["min_top_days"]:
            row_reasons.append("top_days_too_low")
        if top_valid_rows < thresholds["min_top_valid_rows"]:
            row_reasons.append("top_valid_rows_too_low")
        if not np.isfinite(top_mean) or top_mean <= thresholds["min_top_mean_forward_return_pct"]:
            row_reasons.append("top_mean_not_positive")
        if not np.isfinite(top_minus_all) or top_minus_all <= thresholds["min_top_minus_all_pct"]:
            row_reasons.append("top_not_above_pool_average")
        if not np.isfinite(top_minus_bottom) or top_minus_bottom <= thresholds["min_top_minus_bottom_pct"]:
            row_reasons.append("top_not_above_bottom_bucket")
        if not np.isfinite(rank_ic) or rank_ic <= thresholds["min_rank_ic"]:
            row_reasons.append("rank_ic_not_positive")
        row_pass = not row_reasons
        pass_any = pass_any or row_pass
        evaluated.append(
            {
                "artifact_label": str(row.get("artifact_label", "")),
                "score_label": str(row.get("score_label", "")),
                "score_col": str(row.get("score_col", "")),
                "top_days": top_days,
                "top_valid_forward_rows": top_valid_rows,
                "top_mean_forward_return_pct": _safe_float(row.get("top_mean_forward_return_pct", 0.0), 0.0),
                "all_mean_forward_return_pct": _safe_float(row.get("all_mean_forward_return_pct", 0.0), 0.0),
                "top_minus_all_pct": float(top_minus_all) if np.isfinite(top_minus_all) else None,
                "top_minus_bottom_pct": float(top_minus_bottom) if np.isfinite(top_minus_bottom) else None,
                "rank_ic_mean": float(rank_ic) if np.isfinite(rank_ic) else None,
                "pass": bool(row_pass),
                "reasons": row_reasons,
            }
        )

    reasons = [] if pass_any else ["no_gate_score_passed"]
    return {
        "pass": bool(pass_any),
        "reasons": reasons,
        "gate_score_cols": score_cols,
        "thresholds": thresholds,
        "evaluated": evaluated,
        "limitation": (
            "This gate checks persisted recommendation artifacts. Passing it is required before expensive P2 "
            "long-window experiments, but it is not sufficient for promotion."
        ),
    }


def build_score_diagnosis(
    *,
    daily_glob: str,
    market_file: Path | None = None,
    start: str = "",
    end: str = "",
    forward_days: int = 8,
    top_n: int = 20,
    label: str = "",
    group_col: str = "",
    gate_score_cols: str | list[str] | tuple[str, ...] | None = None,
    min_top_mean_forward_return_pct: float = 0.0,
    min_top_minus_all_pct: float = 0.0,
    min_top_minus_bottom_pct: float = 0.0,
    min_rank_ic: float = 0.0,
    min_top_days: int = 5,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = _discover_daily_paths(daily_glob)
    daily = _load_daily_recommendations(paths, start=start, end=end)
    if daily.empty:
        raise RuntimeError("未找到可用 daily recommendation 文件")
    if "建议持有天数" not in daily.columns:
        daily["建议持有天数"] = int(max(1, int(forward_days)))
    if market_file is None:
        bars, _ = _load_ods_market_bars(daily, max(1, int(forward_days)))
    else:
        bars = _load_market_bars(market_file)
    daily = _attach_forward_returns(daily, bars, default_horizon=max(1, int(forward_days)))
    industry_map = _load_industry_map(daily["signal_date"].max())
    mapped_industry = daily["code"].map(industry_map)
    if "行业" in daily.columns:
        fallback_industry = daily["行业"].fillna("").astype(str).str.strip()
        mapped_industry = mapped_industry.where(mapped_industry.notna() & mapped_industry.astype(str).str.strip().ne(""), fallback_industry)
    daily["industry"] = mapped_industry.fillna("未知").astype(str).str.strip().replace({"": "未知"})
    scores = _infer_scores(daily)
    rows: list[dict[str, object]] = []
    group_col = str(group_col or "").strip()
    if group_col and group_col in daily.columns:
        for group_value, group_df in daily.groupby(group_col, dropna=False):
            group_scores = _infer_scores(group_df)
            for score_label, score_col, direction in group_scores:
                row = _summarize_score(
                    group_df,
                    label=score_label,
                    score_col=score_col,
                    direction=direction,
                    top_n=top_n,
                )
                row[group_col] = str(group_value)
                rows.append(row)
    else:
        rows = [
            _summarize_score(daily, label=score_label, score_col=score_col, direction=direction, top_n=top_n)
            for score_label, score_col, direction in scores
        ]
    out = pd.DataFrame(rows)
    if not out.empty:
        out.insert(0, "artifact_label", str(label or "daily_recommendation_proxy"))
        sort_cols = ["top_mean_forward_return_pct", "rank_ic_mean", "top_minus_bottom_pct"]
        if group_col and group_col in out.columns:
            sort_cols = [group_col, *sort_cols]
            ascending = [True, False, False, False]
        else:
            ascending = [False, False, False]
        out = out.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "artifact_label": str(label or "daily_recommendation_proxy"),
        "daily_glob": daily_glob,
        "daily_file_count": int(len(paths)),
        "daily_rows": int(len(daily)),
        "signal_start": str(daily["signal_date"].min().date()),
        "signal_end": str(daily["signal_date"].max().date()),
        "forward_days_default": int(forward_days),
        "top_n": int(top_n),
        "score_count": int(len(scores)),
        "group_col": str(group_col),
        "limitation": (
            "This report is computed from persisted daily recommendation artifacts. "
            "It is a recommendation-proxy alpha diagnostic, not a full-universe raw prediction IC report."
        ),
    }
    profile_gate = evaluate_alpha_quality_gate(
        out,
        gate_score_cols=gate_score_cols,
        min_top_mean_forward_return_pct=float(min_top_mean_forward_return_pct),
        min_top_minus_all_pct=float(min_top_minus_all_pct),
        min_top_minus_bottom_pct=float(min_top_minus_bottom_pct),
        min_rank_ic=float(min_rank_ic),
        min_top_days=int(min_top_days),
    )
    if group_col:
        meta["alpha_quality_gate"] = {
            "pass": False,
            "reasons": ["grouped_diagnostic_not_profile_gate"],
            "grouped_diagnostic_only": True,
            "profile_gate_applicable": False,
            "subgroup_alpha_quality_gate": profile_gate,
            "limitation": (
                "A grouped score diagnosis can identify promising or dangerous sub-slices, "
                "but a passing subgroup is not a profile-level alpha gate pass."
            ),
        }
    else:
        meta["alpha_quality_gate"] = profile_gate
    return out, meta


def main() -> int:
    p = argparse.ArgumentParser(description="Score-level alpha diagnosis for daily recommendation artifacts")
    p.add_argument("--daily-glob", required=True, help="daily recommendation CSV glob(s), comma separated")
    p.add_argument("--market-file", default="", help="optional explicit market parquet; default is shared ODS")
    p.add_argument("--start", default="", help="signal start date")
    p.add_argument("--end", default="", help="signal end date")
    p.add_argument("--forward-days", type=int, default=8, help="default forward open-to-open horizon")
    p.add_argument("--top-n", type=int, default=20, help="top-N per signal date")
    p.add_argument("--label", default="", help="artifact/profile label")
    p.add_argument("--group-col", default="", help="Optional column used to produce separate grouped score diagnostics")
    p.add_argument(
        "--gate-score-cols",
        default=",".join(DEFAULT_ALPHA_GATE_SCORE_COLS),
        help="comma-separated score columns that can pass the alpha-quality smoke gate",
    )
    p.add_argument(
        "--min-top-mean-forward-return-pct",
        type=float,
        default=0.0,
        help="minimum absolute top-bucket mean forward return, in percent",
    )
    p.add_argument(
        "--min-top-minus-all-pct",
        type=float,
        default=0.0,
        help="minimum top bucket minus candidate-pool average, in percentage points",
    )
    p.add_argument(
        "--min-top-minus-bottom-pct",
        type=float,
        default=0.0,
        help="minimum top bucket minus bottom bucket, in percentage points",
    )
    p.add_argument("--min-rank-ic", type=float, default=0.0, help="minimum rank IC mean required by the smoke gate")
    p.add_argument("--min-top-days", type=int, default=5, help="minimum valid top-bucket signal days for gate scores")
    p.add_argument("--enforce-alpha-gate", action="store_true", help="return non-zero when the alpha-quality gate fails")
    p.add_argument("--write-latest", action="store_true", help="write latest shortcut files")
    args = p.parse_args()

    out, meta = build_score_diagnosis(
        daily_glob=str(args.daily_glob),
        market_file=Path(args.market_file).resolve() if args.market_file else None,
        start=str(args.start),
        end=str(args.end),
        forward_days=max(1, int(args.forward_days)),
        top_n=max(1, int(args.top_n)),
        label=str(args.label or ""),
        group_col=str(args.group_col or ""),
        gate_score_cols=str(args.gate_score_cols or ""),
        min_top_mean_forward_return_pct=float(args.min_top_mean_forward_return_pct),
        min_top_minus_all_pct=float(args.min_top_minus_all_pct),
        min_top_minus_bottom_pct=float(args.min_top_minus_bottom_pct),
        min_rank_ic=float(args.min_rank_ic),
        min_top_days=max(0, int(args.min_top_days)),
    )
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{args.label}" if args.label else ""
    safe_suffix = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in suffix)
    csv_path = BACKTEST_DIR / f"quant_score_alpha_diagnosis{safe_suffix}_{ts}.csv"
    json_path = BACKTEST_DIR / f"quant_score_alpha_diagnosis{safe_suffix}_{ts}.json"
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    payload = dict(meta)
    payload["rows"] = out.to_dict(orient="records")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest_base = BACKTEST_DIR / f"quant_score_alpha_diagnosis_latest{safe_suffix}"
        out.to_csv(latest_base.with_suffix(".csv"), index=False, encoding="utf-8-sig")
        latest_base.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out.to_string(index=False))
    gate = payload.get("alpha_quality_gate", {})
    print(f"alpha_quality_gate_pass={bool(gate.get('pass', False))}")
    if gate.get("reasons"):
        print(f"alpha_quality_gate_reasons={','.join(str(x) for x in gate.get('reasons', []))}")
    print(f"score_alpha_csv={csv_path}")
    print(f"score_alpha_json={json_path}")
    if args.enforce_alpha_gate and not bool(gate.get("pass", False)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
