"""统一风险引擎门面。"""

from __future__ import annotations

import pandas as pd

from core.risk import PreTradeRiskConfig, apply_pretrade_risk_gates


def evaluate_pretrade_portfolio(
    candidates: pd.DataFrame,
    bars_idx: pd.DataFrame,
    industry_map: dict[str, str],
    config: PreTradeRiskConfig,
    *,
    trade_date: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """将现有前置风控封装为平台级统一入口。"""
    return apply_pretrade_risk_gates(
        candidates,
        bars_idx=bars_idx,
        trade_date=trade_date,
        industry_map=industry_map,
        config=config,
    )
