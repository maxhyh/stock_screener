# -*- coding: utf-8 -*-
"""平台执行状态机测试。"""

from __future__ import annotations

from core.platform.execution_lifecycle import (
    OrderEvent,
    OrderEventType,
    OrderLifecycleState,
    OrderStatus,
    apply_order_event,
)


def test_order_lifecycle_handles_partial_fill_then_fill():
    state = OrderLifecycleState(order_id="ord_1", requested_qty=1000)
    state = apply_order_event(state, OrderEvent(OrderEventType.CREATE))
    state = apply_order_event(state, OrderEvent(OrderEventType.SUBMIT))
    state = apply_order_event(state, OrderEvent(OrderEventType.PARTIAL_FILL, qty=400))
    assert state.status == OrderStatus.PARTIALLY_FILLED
    assert state.filled_qty == 400

    state = apply_order_event(state, OrderEvent(OrderEventType.FILL))
    assert state.status == OrderStatus.FILLED
    assert state.filled_qty == 1000
    assert state.is_terminal is True


def test_order_lifecycle_retry_exhaustion_marks_failed():
    state = OrderLifecycleState(order_id="ord_2", requested_qty=500)
    state = apply_order_event(state, OrderEvent(OrderEventType.REJECT, reason="network"))
    state = apply_order_event(state, OrderEvent(OrderEventType.RETRY), max_retries=1)
    assert state.status == OrderStatus.PENDING_SUBMIT
    assert state.retry_count == 1

    state = apply_order_event(state, OrderEvent(OrderEventType.RETRY), max_retries=1)
    assert state.status == OrderStatus.FAILED
    assert state.last_reason == "retry_exhausted"
