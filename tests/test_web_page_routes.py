# -*- coding: utf-8 -*-
"""Web 页面渲染测试。"""

from __future__ import annotations

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("/", "A 股量化驾驶舱"),
        ("/ml", "今日推荐工作台"),
        ("/ml/history", "历史验证研究页"),
        ("/backtest", "历史回测研究页"),
        ("/signal-analysis", "信号绩效剖析"),
        ("/platform/ops", "平台运维与风险暴露"),
    ],
)
def test_main_pages_render_successfully(client, path, needle):
    response = client.get(path)
    assert response.status_code == 200
    assert needle in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "path",
    [
        "/static/pages/index.js",
        "/static/pages/ml_daily.js",
        "/static/pages/ml_history.js",
        "/static/pages/backtest.js",
        "/static/pages/signal_analysis.js",
        "/static/pages/platform_ops.js",
    ],
)
def test_page_scripts_are_served(client, path):
    response = client.get(path)
    assert response.status_code == 200
