# -*- coding: utf-8 -*-
"""共享权重分配工具测试。"""

from __future__ import annotations

import numpy as np

from utils.portfolio_weights import build_score_weights


def test_build_score_weights_respects_total_target_and_single_cap():
    weights = build_score_weights(np.array([1.0, 0.5, 0.1], dtype=float), total_target=0.6, single_cap=0.25)

    assert len(weights) == 3
    assert abs(float(weights.sum()) - 0.6) < 1e-9
    assert float(weights.max()) <= 0.25 + 1e-9


def test_build_score_weights_returns_empty_when_target_invalid():
    weights = build_score_weights(np.array([1.0, 2.0], dtype=float), total_target=0.0, single_cap=0.2)

    assert weights.size == 0
