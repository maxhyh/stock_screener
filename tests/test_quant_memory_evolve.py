# -*- coding: utf-8 -*-
"""Project memory evolution tests."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.quant_memory_evolve as mem


def _write_min_memory(memory_dir: Path) -> None:
    memory_dir.mkdir()
    (memory_dir / "profile.md").write_text(
        "# Project Profile\n\n- Main profile: `quality_regime`.\n- Research OOS strength does not justify promotion without P2 execution parity.\n",
        encoding="utf-8",
    )
    (memory_dir / "actives.md").write_text(
        "# Active Memory\n\n<!-- memory:auto:start -->\nold\n<!-- memory:auto:end -->\n\n## Manual Notes\n\n- keep me\n",
        encoding="utf-8",
    )
    (memory_dir / "learnings.md").write_text(
        """# Long-Term Learnings

## Learnings Log

### 2026-04-26 | v7 fails despite industry balance
- tags: p2, promotion, adv
- reusable: yes
- confidence: high
- evidence: promotion_decision_latest.json
- action: Keep v7 in shadow until NAV parity and target weight floors pass.

Industry concentration improved, but execution did not pass.

### 2026-04-26 | one-off note
- tags: scratch
- reusable: no
- confidence: low

Do not promote this.
""",
        encoding="utf-8",
    )
    (memory_dir / "errors.md").write_text(
        """# Error Memory

## Error Log

### 2026-04-26 | Low cash can fake lower drawdown
- tags: cash_drag, promotion
- status: active
- severity: high
- mitigation: Require target weight floors.
- evidence: target_weight_sum_mean below floor.

Do not treat low exposure as alpha.
""",
        encoding="utf-8",
    )
    (memory_dir / "state.json").write_text('{"schema_version":1,"active_hashes":[]}\n', encoding="utf-8")


def test_parse_and_select_reusable_entries(tmp_path: Path):
    memory_dir = tmp_path / "memory"
    _write_min_memory(memory_dir)

    entries = mem.parse_markdown_entries(memory_dir / "learnings.md") + mem.parse_markdown_entries(memory_dir / "errors.md")
    active = mem.select_active_entries(entries, max_active=10)

    titles = {e.title for e in active}
    assert "v7 fails despite industry balance" in titles
    assert "Low cash can fake lower drawdown" in titles
    assert "one-off note" not in titles


def test_build_memory_preserves_manual_notes_and_writes_state(tmp_path: Path):
    memory_dir = tmp_path / "memory"
    _write_min_memory(memory_dir)

    actives_text, review_text, state = mem.build_memory(memory_dir, max_active=10)

    assert "v7 fails despite industry balance" in actives_text
    assert "Low cash can fake lower drawdown" in actives_text
    assert "- keep me" in actives_text
    assert "newly_promoted_active_hashes" in review_text
    assert state["learning_entry_count"] == 2
    assert state["error_entry_count"] == 1
    assert len(state["active_hashes"]) == 2


def test_append_learning_then_refresh(tmp_path: Path):
    memory_dir = tmp_path / "memory"
    _write_min_memory(memory_dir)

    mem.append_learning(
        memory_dir=memory_dir,
        title="New reusable capacity rule",
        tags="capacity, p2",
        evidence="artifact.csv",
        action="Keep capacity checks before promotion.",
        confidence="high",
        reusable="yes",
        body="Capacity evidence should be explicit.",
    )
    actives_text, _, state = mem.build_memory(memory_dir, max_active=10)

    assert "New reusable capacity rule" in actives_text
    assert state["learning_entry_count"] == 3


def test_state_loader_handles_corrupt_json(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("{bad", encoding="utf-8")

    out = mem.load_state(p)

    assert out["schema_version"] == 1
    assert out["active_hashes"] == []
