"""统一组合决策引擎基础层。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from utils.portfolio_weights import build_score_weights


@dataclass
class PortfolioConstraints:
    total_target: float
    single_cap: float
    industry_cap: float = 0.0
    adv_participation_cap: float = 0.0
    capital_base: float = 1_000_000.0
    turnover_cap: float = 0.0
    min_names: int = 0
    max_names: int = 0
    min_weight: float = 0.0
    score_col: str = "ML评分"
    code_col: str = "代码"
    industry_col: str = "industry"
    amount_col: str = "amount"
    amount_buffer: float = 1.0
    redistribute_clipped: bool = False
    impact_model: str = "sqrt"
    impact_base_bps: float = 0.0
    impact_participation_bps: float = 0.0
    impact_power: float = 0.5


@dataclass
class PortfolioDecision:
    selected: pd.DataFrame
    exposures: dict[str, float]
    diagnostics: dict[str, object]


def _safe_num_series(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(float(default), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(float(default))


def _impact_cost_bps(participation: float, constraints: PortfolioConstraints) -> float:
    participation = max(float(participation), 0.0)
    base = max(float(constraints.impact_base_bps), 0.0)
    slope = max(float(constraints.impact_participation_bps), 0.0)
    if slope <= 0.0 or participation <= 0.0:
        return float(base)
    model = str(constraints.impact_model or "sqrt").strip().lower()
    if model == "linear":
        scale = participation
    else:
        power = min(max(float(constraints.impact_power), 0.10), 2.0)
        scale = participation ** power
    return float(base + slope * scale)


def build_portfolio_decision(
    candidates: pd.DataFrame,
    constraints: PortfolioConstraints,
) -> PortfolioDecision:
    """基于统一权重与约束构建组合决策。"""
    if candidates is None or candidates.empty:
        empty = pd.DataFrame(columns=list(candidates.columns) + ["target_weight"]) if candidates is not None else pd.DataFrame(columns=["target_weight"])
        return PortfolioDecision(selected=empty, exposures={}, diagnostics={"selected_count": 0, "blocked_by_min_names": False})

    df = candidates.copy()
    score_col = constraints.score_col
    code_col = constraints.code_col
    industry_col = constraints.industry_col
    if score_col not in df.columns:
        raise KeyError(f"missing score column: {score_col}")
    if code_col not in df.columns:
        raise KeyError(f"missing code column: {code_col}")

    total_target = min(max(float(constraints.total_target), 0.0), 1.0)
    single_cap = min(max(float(constraints.single_cap), 0.0), 1.0)
    industry_cap = min(max(float(constraints.industry_cap), 0.0), 1.0)
    adv_cap = min(max(float(constraints.adv_participation_cap), 0.0), 1.0)
    capital_base = max(float(constraints.capital_base), 0.0)
    amount_buffer = max(float(constraints.amount_buffer), 0.0)

    df[score_col] = pd.to_numeric(df[score_col], errors="coerce").fillna(0.0)
    if industry_col not in df.columns:
        df[industry_col] = "__unknown__"
    df[industry_col] = df[industry_col].astype(str).fillna("").replace({"": "__unknown__"})
    df["_amount_for_capacity"] = _safe_num_series(df, constraints.amount_col, 0.0).clip(lower=0.0) * amount_buffer
    df = df.sort_values(score_col, ascending=False).drop_duplicates(subset=[code_col]).reset_index(drop=True)

    primary_count = int(constraints.max_names) if int(constraints.max_names) > 0 else len(df)
    primary_count = max(0, min(primary_count, len(df)))
    weights = np.zeros(len(df), dtype=float)
    primary_weights = build_score_weights(df[score_col].head(primary_count).to_numpy(dtype=float), total_target, single_cap)
    if len(primary_weights) == primary_count:
        weights[:primary_count] = primary_weights
    df["_raw_target_weight"] = weights

    min_weight = max(float(constraints.min_weight), 0.0)
    redistribute = bool(constraints.redistribute_clipped)
    n = len(df)
    final_weights = np.zeros(n, dtype=float)
    reasons: list[set[str]] = [set() for _ in range(n)]
    industry_weight: dict[str, float] = {}
    row_caps = np.zeros(n, dtype=float)
    amount_vals = df["_amount_for_capacity"].to_numpy(dtype=float)
    raw_vals = df["_raw_target_weight"].to_numpy(dtype=float)
    industry_vals = df[industry_col].astype(str).fillna("__unknown__").replace({"": "__unknown__"}).tolist()

    for i in range(n):
        desired = max(float(raw_vals[i]), 0.0)
        amount = max(float(amount_vals[i]), 0.0)
        cap = single_cap if single_cap > 0 else 0.0
        if desired > cap + 1e-12:
            reasons[i].add("single_cap_clip")
        if adv_cap > 0 and capital_base > 0:
            if amount <= 0:
                cap = 0.0
                reasons[i].add("invalid_amount")
            else:
                adv_weight_cap = max(0.0, amount * adv_cap / capital_base)
                if desired > adv_weight_cap + 1e-12:
                    reasons[i].add("adv_participation_clip")
                cap = min(cap, adv_weight_cap)
        row_caps[i] = max(0.0, cap)

    def _industry_room(industry: str) -> float:
        if industry_cap <= 0:
            return 1.0
        return max(industry_cap - float(industry_weight.get(industry, 0.0)), 0.0)

    for i in range(n):
        desired = max(float(raw_vals[i]), 0.0)
        if desired <= 0:
            continue
        industry = str(industry_vals[i] or "__unknown__")
        room = _industry_room(industry)
        final = min(desired, float(row_caps[i]), room)
        if final + 1e-12 < desired and room + 1e-12 < min(desired, float(row_caps[i])):
            reasons[i].add("industry_weight_clip")
        if min_weight > 0 and final < min_weight:
            reasons[i].add("min_weight")
            final = 0.0
        if final > 1e-12:
            final_weights[i] = final
            industry_weight[industry] = float(industry_weight.get(industry, 0.0)) + float(final)

    if redistribute:
        target_sum = min(total_target, float(np.sum(row_caps)))
        shortfall = max(0.0, target_sum - float(np.sum(final_weights)))
        for _ in range(max(1, n * 2)):
            if shortfall <= 1e-12:
                break
            added_total = 0.0
            for i in range(n):
                industry = str(industry_vals[i] or "__unknown__")
                room = _industry_room(industry)
                available = max(0.0, min(float(row_caps[i]) - float(final_weights[i]), room))
                if available <= 1e-12:
                    continue
                add = min(shortfall, available)
                if add <= 1e-12:
                    continue
                final_weights[i] += add
                industry_weight[industry] = float(industry_weight.get(industry, 0.0)) + float(add)
                reasons[i].add("redistributed_in")
                shortfall -= add
                added_total += add
                if shortfall <= 1e-12:
                    break
            if added_total <= 1e-12:
                break

    selected_rows: list[dict[str, object]] = []
    blocked_rows: list[dict[str, object]] = []
    clipped_count = 0
    for i, row in df.iterrows():
        rec = row.to_dict()
        desired = max(float(rec.get("_raw_target_weight", 0.0)), 0.0)
        final = max(float(final_weights[i]), 0.0)
        amount = max(float(rec.get("_amount_for_capacity", 0.0) or 0.0), 0.0)
        participation = capital_base * final / amount if amount > 0 and capital_base > 0 and final > 0 else 0.0
        reason_text = ",".join(sorted(reasons[i])) if reasons[i] else "ok"

        if final + 1e-12 < desired or final > desired + 1e-12 or reason_text != "ok":
            clipped_count += 1

        rec["target_weight"] = float(final)
        rec["target_weight_raw"] = float(desired)
        rec["unfilled_target_weight"] = float(max(desired - final, 0.0))
        rec["participation_pct"] = float(participation * 100.0)
        rec["impact_cost_bps"] = float(_impact_cost_bps(participation, constraints)) if final > 0 else 0.0
        rec["constraint_reason"] = reason_text if final > 1e-12 else (reason_text if reason_text != "ok" else "zero_weight")

        if final <= 1e-12:
            blocked_rows.append(rec)
        else:
            selected_rows.append(rec)

    df = pd.DataFrame(selected_rows) if selected_rows else df.iloc[0:0].copy()
    blocked_df = pd.DataFrame(blocked_rows)
    if not df.empty and industry_col in df.columns:
        df["industry_weight_post"] = df[industry_col].map(industry_weight).fillna(0.0).astype(float)
    else:
        df["industry_weight_post"] = pd.Series(dtype=float)
    df = df.drop(columns=["_raw_target_weight", "_amount_for_capacity"], errors="ignore")
    blocked_df = blocked_df.drop(columns=["_raw_target_weight", "_amount_for_capacity"], errors="ignore")

    selected_count = int(len(df))
    blocked_by_min_names = bool(constraints.min_names > 0 and selected_count < int(constraints.min_names))
    if blocked_by_min_names:
        if not df.empty:
            more_blocked = df.copy()
            more_blocked["constraint_reason"] = "min_names"
            blocked_df = pd.concat([blocked_df, more_blocked], ignore_index=True)
        df = df.iloc[0:0].copy()

    target_weight = pd.to_numeric(df.get("target_weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    participation_pct = pd.to_numeric(df.get("participation_pct", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    impact_bps = pd.to_numeric(df.get("impact_cost_bps", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    total_weight = float(target_weight.sum())
    capacity_shortfall_weight = float(max(total_target - total_weight, 0.0))
    exposures = {
        "total_weight": total_weight,
        "capacity_shortfall_weight": capacity_shortfall_weight,
        "max_single_weight": float(target_weight.max()) if len(target_weight) else 0.0,
        "max_adv_participation_pct": float(participation_pct.max()) if len(participation_pct) else 0.0,
        "estimated_impact_cost_bps": float((target_weight * impact_bps).sum() / max(total_weight, 1e-12)) if total_weight > 0 else 0.0,
    }
    if industry_col in df.columns:
        industry_weights = (
            df.groupby(industry_col, dropna=False)["target_weight"].sum().sort_values(ascending=False).to_dict()
            if not df.empty
            else {}
        )
        exposures["max_industry_weight"] = float(max(industry_weights.values())) if industry_weights else 0.0
    else:
        industry_weights = {}

    diagnostics = {
        "selected_count": selected_count if not blocked_by_min_names else 0,
        "blocked_by_min_names": blocked_by_min_names,
        "blocked_count": int(len(blocked_df)),
        "clipped_count": int(clipped_count),
        "capacity_shortfall_weight": capacity_shortfall_weight,
        "industry_weights": industry_weights,
        "score_floor": float(df[score_col].min()) if not df.empty else 0.0,
        "blocked": blocked_df.to_dict(orient="records") if not blocked_df.empty else [],
        "constraints": {
            "total_target": float(total_target),
            "single_cap": float(single_cap),
            "industry_cap": float(industry_cap),
            "adv_participation_cap": float(adv_cap),
            "capital_base": float(capital_base),
            "max_names": int(primary_count),
            "amount_col": str(constraints.amount_col),
            "amount_buffer": float(amount_buffer),
            "redistribute_clipped": bool(redistribute),
        },
    }
    return PortfolioDecision(selected=df, exposures=exposures, diagnostics=diagnostics)
