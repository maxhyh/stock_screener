# -*- coding: utf-8 -*-
"""平台监控规则测试。"""

from __future__ import annotations

from core.platform.monitoring import PlatformHealthSnapshot, evaluate_health_warnings


def test_evaluate_health_warnings_flags_critical_conditions():
    warnings = evaluate_health_warnings(
        PlatformHealthSnapshot(
            data_fresh=False,
            data_coverage_pct=70.0,
            risk_block_rate_pct=40.0,
            order_block_rate_pct=25.0,
            nav_drawdown_pct=-0.08,
            exec_diff_pct=0.05,
        )
    )
    titles = {w.title for w in warnings}
    assert "数据更新异常" in titles
    assert "行业覆盖率过低" in titles
    assert "风控拒单率偏高" in titles
    assert "订单阻塞率偏高" in titles
    assert "净值异常回撤" in titles
    assert "执行回测偏差偏大" in titles
