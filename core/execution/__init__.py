"""执行通道注册表。"""

from __future__ import annotations

from core.execution.adapter import BrokerAdapter, RebalanceResult
from core.execution.live_broker import LiveBroker
from core.execution.paper_broker import PaperBroker
from core.execution.reconciliation import reconcile_positions, ReconciliationResult, PositionMismatch


def create_broker(name: str, **kwargs) -> BrokerAdapter:
    n = str(name or "").strip().lower()
    if n in {"paper", "paper_trade", "papertrading"}:
        return PaperBroker(
            state_file=kwargs["state_file"],
            initial_capital=kwargs["initial_capital"],
            lot_size=kwargs["lot_size"],
            fee_bps=kwargs["fee_bps"],
            slippage_bps=kwargs["slippage_bps"],
            stamp_tax_bps=kwargs["stamp_tax_bps"],
            blocked_state_enabled=kwargs.get("blocked_state_enabled", True),
            block_buy_on_exit_blocked=kwargs.get("block_buy_on_exit_blocked", False),
            blocked_exit_freeze_min_weight=kwargs.get("blocked_exit_freeze_min_weight", 0.0),
        )
    if n in {"live", "real", "broker"}:
        return LiveBroker(
            state_file=kwargs["state_file"],
            initial_capital=kwargs["initial_capital"],
            lot_size=kwargs["lot_size"],
            fee_bps=kwargs["fee_bps"],
            slippage_bps=kwargs["slippage_bps"],
            stamp_tax_bps=kwargs["stamp_tax_bps"],
            live_mode=kwargs.get("live_mode", "shadow"),
            gateway_client=kwargs.get("gateway_client"),
        )
    raise ValueError(f"Unsupported broker: {name}. Available: paper/live")


__all__ = [
    "BrokerAdapter", "RebalanceResult",
    "PaperBroker", "LiveBroker", "create_broker",
    "reconcile_positions", "ReconciliationResult", "PositionMismatch",
]
