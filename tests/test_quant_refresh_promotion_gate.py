# -*- coding: utf-8 -*-
"""promotion gate refresh script tests."""

from __future__ import annotations

import json
import sys

import scripts.quant_refresh_promotion_gate as refresh


def test_derive_period_from_explicit_end():
    start, end = refresh._derive_period("2026-04-14", 10)
    assert end == "2026-04-14"
    assert start.startswith("2025-")


def test_main_builds_expected_commands(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {},
                    "quality_regime_candidate": {},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls: list[tuple[list[str], str]] = []

    def _fake_run(cmd, description):
        calls.append((list(cmd), description))

    monkeypatch.setattr(refresh, "_run", _fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_refresh_promotion_gate.py",
            "--config",
            str(config_file),
            "--end",
            "2026-04-14",
            "--lookback-months",
            "10",
            "--p2-windows",
            "60,90,120",
        ],
    )

    rc = refresh.main()
    assert rc == 0
    assert len(calls) == 5
    assert any("quant_profile_rolling_compare.py" in part for part in calls[0][0])
    assert "--write-latest" in calls[0][0]
    assert any("quant_p2_rolling_replay.py" in part for part in calls[1][0])
    assert any("quant_p2_shadow_diagnosis.py" in part for part in calls[2][0])
    assert any("quant_research_execution_funnel.py" in part for part in calls[3][0])
    assert any("quant_profile_promotion_review.py" in part for part in calls[4][0])
