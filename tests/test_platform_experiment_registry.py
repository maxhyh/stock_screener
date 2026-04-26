# -*- coding: utf-8 -*-
"""实验注册表测试。"""

from __future__ import annotations

from core.platform.experiment_registry import (
    build_experiment_record,
    load_experiment_registry,
    register_experiment,
)


def test_register_experiment_persists_registry(tmp_path):
    record = build_experiment_record(
        name="demo",
        stage="train",
        params={"top_n": 10},
        metrics={"ic": 0.12},
        artifacts={"model_file": "demo.pkl"},
    )
    path = register_experiment(tmp_path, record)
    assert path.exists()

    items = load_experiment_registry(tmp_path)
    assert len(items) == 1
    assert items[0]["name"] == "demo"
    assert items[0]["metrics"]["ic"] == 0.12
