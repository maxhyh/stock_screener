from __future__ import annotations

import numpy as np
import pandas as pd


UNKNOWN_INDUSTRY_LABEL = "未知"


def _safe_num_series(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(float(default), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(float(default))


def add_execution_overlay_scores(
    df: pd.DataFrame,
    *,
    base_score_col: str,
    price_col: str,
    amount_col: str,
    industry_col: str,
    liquidity_blend: float = 0.0,
    adv_penalty_blend: float = 0.0,
    industry_crowding_blend: float = 0.0,
) -> pd.DataFrame:
    out = df.copy()
    base_score = _safe_num_series(out, base_score_col, 0.0).clip(lower=0.0)
    close_px = _safe_num_series(out, price_col, 0.0).clip(lower=0.0)
    amount = _safe_num_series(out, amount_col, 0.0).clip(lower=0.0)

    liquidity_rank = np.log1p(amount).rank(method="average", pct=True)
    price_rank = close_px.rank(method="average", pct=True)
    out["liquidity_score"] = (0.80 * liquidity_rank + 0.20 * price_rank).fillna(0.0).clip(0.0, 1.0)

    positive_amount = amount[amount > 0]
    if positive_amount.empty:
        out["adv_capacity_score"] = out["liquidity_score"]
    else:
        scale = max(float(positive_amount.quantile(0.50)), 1.0)
        high = max(float(positive_amount.quantile(0.90)), scale)
        denom = np.log1p(max(high / scale, 1.0))
        amt_buffer = np.log1p((amount / scale).clip(lower=0.0)) / denom if denom > 0 else 0.0
        if not isinstance(amt_buffer, pd.Series):
            amt_buffer = pd.Series(float(amt_buffer), index=out.index, dtype=float)
        amt_buffer = amt_buffer.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(0.0, 1.0)
        out["adv_capacity_score"] = (0.65 * np.sqrt(liquidity_rank.clip(lower=0.0)) + 0.35 * amt_buffer).clip(0.0, 1.0)

    industry = (
        out[industry_col].astype(str).fillna("").str.strip()
        if industry_col in out.columns
        else pd.Series("", index=out.index, dtype=object)
    )
    industry = industry.replace({"": UNKNOWN_INDUSTRY_LABEL, "nan": UNKNOWN_INDUSTRY_LABEL, "None": UNKNOWN_INDUSTRY_LABEL})
    out[industry_col] = industry
    if len(out) == 0:
        out["industry_balance_score"] = pd.Series(dtype=float)
    else:
        ind_count = industry.map(industry.value_counts()).astype(float)
        count_norm = ind_count / max(float(ind_count.max()), 1.0)
        positive_mass = base_score.clip(lower=0.0)
        if float(positive_mass.sum()) > 0:
            mass_by_industry = positive_mass.groupby(industry).sum()
        else:
            mass_by_industry = out["adv_capacity_score"].groupby(industry).mean()
        mass_norm = industry.map(mass_by_industry / max(float(mass_by_industry.max()), 1.0)).astype(float)
        crowding = (0.55 * count_norm + 0.45 * mass_norm).clip(0.0, 1.0)
        out["industry_balance_score"] = (1.0 - crowding).clip(0.0, 1.0)

    score = base_score.copy()
    liquidity_blend = min(max(float(liquidity_blend), 0.0), 0.50)
    adv_penalty_blend = min(max(float(adv_penalty_blend), 0.0), 0.50)
    industry_crowding_blend = min(max(float(industry_crowding_blend), 0.0), 0.50)

    if liquidity_blend > 0:
        score = (1.0 - liquidity_blend) * score + liquidity_blend * out["liquidity_score"]
    if adv_penalty_blend > 0:
        score = (1.0 - adv_penalty_blend) * score + adv_penalty_blend * out["adv_capacity_score"]
    if industry_crowding_blend > 0:
        score = (1.0 - industry_crowding_blend) * score + industry_crowding_blend * out["industry_balance_score"]

    out["execution_score"] = pd.to_numeric(score, errors="coerce").fillna(0.0)
    return out
