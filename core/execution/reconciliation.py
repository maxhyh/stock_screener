# -*- coding: utf-8 -*-
"""
仓位对账模块：本地记录 vs 券商实际仓位对账。

使用方法:
    from core.execution.reconciliation import reconcile_positions, ReconciliationResult

    result = reconcile_positions(local_positions, broker_positions)
    if result.has_critical_mismatch:
        alert("仓位不一致，暂停交易！")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PositionMismatch:
    """单个标的的仓位差异"""
    code: str
    name: str
    local_qty: int
    broker_qty: int
    diff_qty: int
    diff_value: float  # 差异对应市值
    mismatch_type: str  # qty_diff / local_only / broker_only


@dataclass
class ReconciliationResult:
    """对账结果"""
    is_matched: bool                       # 完全一致
    has_critical_mismatch: bool            # 是否有超阈值差异
    mismatches: list[PositionMismatch] = field(default_factory=list)
    total_local_value: float = 0.0
    total_broker_value: float = 0.0
    abs_diff_value: float = 0.0
    abs_diff_pct: float = 0.0              # 差异占 NAV 比例
    matched_count: int = 0
    mismatch_count: int = 0
    local_only_count: int = 0             # 本地有，券商没有
    broker_only_count: int = 0            # 券商有，本地没有
    summary: str = ""


def reconcile_positions(
    local_positions: dict[str, dict[str, Any]],
    broker_positions: dict[str, dict[str, Any]],
    price_map: dict[str, float] | None = None,
    nav: float = 0.0,
    critical_diff_pct: float = 0.01,  # 差异超过 NAV 的 1% 视为严重
) -> ReconciliationResult:
    """
    逐标的对账。

    Args:
        local_positions: {code: {"qty": int, "avg_cost": float, "name": str, ...}}
        broker_positions: {code: {"qty": int, "avg_cost": float, "name": str, ...}}
        price_map: {code: latest_price} 用于估算差异市值
        nav: 当前净值，用于计算差异占比
        critical_diff_pct: 差异占 NAV 比例超过此值视为严重

    Returns:
        ReconciliationResult
    """
    price_map = price_map or {}
    all_codes = sorted(set(local_positions.keys()) | set(broker_positions.keys()))

    mismatches: list[PositionMismatch] = []
    matched_count = 0
    total_local_value = 0.0
    total_broker_value = 0.0

    for code in all_codes:
        local = local_positions.get(code, {})
        broker = broker_positions.get(code, {})

        local_qty = int(local.get("qty", 0))
        broker_qty = int(broker.get("qty", 0))
        name = str(local.get("name", "") or broker.get("name", "") or code)
        price = float(price_map.get(code, local.get("avg_cost", 0.0) or broker.get("avg_cost", 0.0)))

        total_local_value += local_qty * price
        total_broker_value += broker_qty * price

        if local_qty == broker_qty:
            matched_count += 1
            continue

        diff_qty = broker_qty - local_qty
        diff_value = abs(diff_qty) * price

        if local_qty > 0 and broker_qty == 0:
            mtype = "local_only"
        elif local_qty == 0 and broker_qty > 0:
            mtype = "broker_only"
        else:
            mtype = "qty_diff"

        mismatches.append(PositionMismatch(
            code=code,
            name=name,
            local_qty=local_qty,
            broker_qty=broker_qty,
            diff_qty=diff_qty,
            diff_value=diff_value,
            mismatch_type=mtype,
        ))

    abs_diff = sum(m.diff_value for m in mismatches)
    eff_nav = max(nav, total_local_value, total_broker_value, 1.0)
    diff_pct = abs_diff / eff_nav

    local_only = sum(1 for m in mismatches if m.mismatch_type == "local_only")
    broker_only = sum(1 for m in mismatches if m.mismatch_type == "broker_only")
    is_matched = len(mismatches) == 0
    has_critical = diff_pct > critical_diff_pct

    # 生成摘要
    lines = []
    if is_matched:
        lines.append(f"✅ 对账通过：{matched_count} 个持仓完全一致")
    else:
        lines.append(f"⚠️ 对账发现 {len(mismatches)} 个差异（总差异 ¥{abs_diff:,.0f}，占 NAV {diff_pct:.2%}）")
        for m in mismatches:
            lines.append(
                f"  [{m.mismatch_type}] {m.code} {m.name}: "
                f"本地={m.local_qty} 券商={m.broker_qty} 差异={m.diff_qty:+d} "
                f"(¥{m.diff_value:,.0f})"
            )
        if has_critical:
            lines.append(f"🚨 差异超过阈值 {critical_diff_pct:.1%}，建议暂停交易并人工核查！")

    summary = "\n".join(lines)
    if has_critical:
        logger.error(summary)
    elif not is_matched:
        logger.warning(summary)
    else:
        logger.info(summary)

    return ReconciliationResult(
        is_matched=is_matched,
        has_critical_mismatch=has_critical,
        mismatches=mismatches,
        total_local_value=total_local_value,
        total_broker_value=total_broker_value,
        abs_diff_value=abs_diff,
        abs_diff_pct=diff_pct,
        matched_count=matched_count,
        mismatch_count=len(mismatches),
        local_only_count=local_only,
        broker_only_count=broker_only,
        summary=summary,
    )


__all__ = ["reconcile_positions", "ReconciliationResult", "PositionMismatch"]
