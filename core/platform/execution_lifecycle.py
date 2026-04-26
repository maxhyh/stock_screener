"""真实执行层订单生命周期状态机。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class OrderStatus(str, Enum):
    NEW = "new"
    PENDING_SUBMIT = "pending_submit"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELED = "canceled"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"
    BLOCKED = "blocked"


class OrderEventType(str, Enum):
    CREATE = "create"
    SUBMIT = "submit"
    ACK = "ack"
    PARTIAL_FILL = "partial_fill"
    FILL = "fill"
    CANCEL_REQUEST = "cancel_request"
    CANCEL_ACK = "cancel_ack"
    REJECT = "reject"
    FAIL = "fail"
    EXPIRE = "expire"
    BLOCK = "block"
    RETRY = "retry"


TERMINAL_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.REJECTED,
    OrderStatus.FAILED,
    OrderStatus.EXPIRED,
    OrderStatus.BLOCKED,
}


@dataclass(frozen=True)
class OrderEvent:
    event_type: OrderEventType
    qty: int = 0
    reason: str = ""


@dataclass(frozen=True)
class OrderLifecycleState:
    order_id: str
    requested_qty: int
    status: OrderStatus = OrderStatus.NEW
    filled_qty: int = 0
    retry_count: int = 0
    last_reason: str = ""

    @property
    def remaining_qty(self) -> int:
        return max(int(self.requested_qty) - int(self.filled_qty), 0)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def can_retry(self) -> bool:
        return (not self.is_terminal) or self.status in {OrderStatus.REJECTED, OrderStatus.FAILED}


def apply_order_event(
    state: OrderLifecycleState,
    event: OrderEvent,
    *,
    max_retries: int = 2,
) -> OrderLifecycleState:
    """应用订单事件，保持成交数量与状态机一致。"""
    if state.is_terminal and event.event_type not in {OrderEventType.RETRY}:
        return state

    if event.event_type == OrderEventType.CREATE:
        return replace(state, status=OrderStatus.PENDING_SUBMIT, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.SUBMIT:
        return replace(state, status=OrderStatus.SUBMITTED, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.ACK:
        next_status = OrderStatus.SUBMITTED if state.filled_qty <= 0 else OrderStatus.PARTIALLY_FILLED
        return replace(state, status=next_status, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.PARTIAL_FILL:
        filled_qty = min(state.requested_qty, state.filled_qty + max(int(event.qty), 0))
        status = OrderStatus.FILLED if filled_qty >= state.requested_qty else OrderStatus.PARTIALLY_FILLED
        return replace(state, status=status, filled_qty=filled_qty, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.FILL:
        return replace(
            state,
            status=OrderStatus.FILLED,
            filled_qty=state.requested_qty,
            last_reason=str(event.reason or ""),
        )

    if event.event_type == OrderEventType.CANCEL_REQUEST:
        return replace(state, status=OrderStatus.CANCEL_PENDING, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.CANCEL_ACK:
        return replace(state, status=OrderStatus.CANCELED, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.REJECT:
        return replace(state, status=OrderStatus.REJECTED, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.FAIL:
        return replace(state, status=OrderStatus.FAILED, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.EXPIRE:
        return replace(state, status=OrderStatus.EXPIRED, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.BLOCK:
        return replace(state, status=OrderStatus.BLOCKED, last_reason=str(event.reason or ""))

    if event.event_type == OrderEventType.RETRY:
        if state.retry_count >= max_retries:
            return replace(state, status=OrderStatus.FAILED, last_reason="retry_exhausted")
        return replace(
            state,
            status=OrderStatus.PENDING_SUBMIT,
            retry_count=state.retry_count + 1,
            last_reason=str(event.reason or "retry"),
        )

    return state
