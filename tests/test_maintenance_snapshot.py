# -*- coding: utf-8 -*-
"""Regression tests for the repo maintenance snapshot tooling."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = REPO_ROOT / "skills" / "audit-a-share-quant-project" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

import build_maintenance_snapshot as snapshot  # noqa: E402


def test_architecture_snapshot_reports_large_production_files(tmp_path):
    scripts_dir = tmp_path / "scripts"
    tests_dir = tmp_path / "tests"
    scripts_dir.mkdir()
    tests_dir.mkdir()

    (scripts_dir / "big.py").write_text(("print('x')\n" * 1301), encoding="utf-8")
    (scripts_dir / "small.py").write_text("print('ok')\n", encoding="utf-8")
    (tests_dir / "test_big.py").write_text(("assert True\n" * 1400), encoding="utf-8")

    architecture = snapshot.collect_architecture_size(tmp_path)
    large_paths = {item["path"]: item for item in architecture["large_production_files"]}

    assert architecture["total_python_lines"] == 2702
    assert large_paths["scripts/big.py"]["severity"] == "high"
    assert "tests/test_big.py" not in large_paths


def test_maintenance_snapshot_includes_architecture_sections(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "big.py").write_text(("print('x')\n" * 1801), encoding="utf-8")

    text = snapshot._format_snapshot(tmp_path)

    assert "## Architecture Size" in text
    assert "- large_production_files: 1" in text
    assert "- scripts/big.py: 1801 lines" in text
    assert "- critical scripts/big.py: 1801 lines" in text
