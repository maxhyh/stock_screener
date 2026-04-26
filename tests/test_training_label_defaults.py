# -*- coding: utf-8 -*-
"""训练标签默认 horizon 配置测试。"""

from __future__ import annotations

import json

from config.settings import resolve_default_label_horizon


def test_resolve_default_label_horizon_reads_default_profile(tmp_path):
    cfg_file = tmp_path / "quant_live_profiles.json"
    cfg_file.write_text(
        json.dumps(
            {
                "default_profile": "balanced",
                "profiles": {
                    "balanced": {"holding_days": 3},
                    "aggressive": {"holding_days": 5},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert resolve_default_label_horizon(cfg_file, fallback=8) == 3


def test_resolve_default_label_horizon_falls_back_on_invalid_config(tmp_path):
    cfg_file = tmp_path / "quant_live_profiles.json"
    cfg_file.write_text('{"default_profile":"balanced","profiles":{"balanced":{}}}', encoding="utf-8")

    assert resolve_default_label_horizon(cfg_file, fallback=8) == 8
    assert resolve_default_label_horizon(tmp_path / "missing.json", fallback=6) == 6

