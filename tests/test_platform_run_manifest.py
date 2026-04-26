# -*- coding: utf-8 -*-
"""运行 manifest 测试。"""

from __future__ import annotations

import json

from core.platform.run_manifest import build_run_manifest, finalize_run_manifest, write_run_manifest


def test_run_manifest_writes_versions_and_finalize(tmp_path):
    data_file = tmp_path / "data.csv"
    data_file.write_text("a,b\n1,2\n", encoding="utf-8")

    manifest = build_run_manifest(
        run_type="unit_test",
        argv=["python", "demo.py"],
        params={"mode": "test"},
        tracked_files={"data": data_file},
        config_fingerprint="abc123",
    )
    path = write_run_manifest(tmp_path, manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_type"] == "unit_test"
    assert payload["versions"]["data"]["exists"] is True
    assert payload["config_fingerprint"] == "abc123"

    finalized = finalize_run_manifest(path, status="success", step_results={"a": True}, notes=["ok"])
    assert finalized["status"] == "success"
    assert finalized["step_results"] == {"a": True}
    assert finalized["notes"] == ["ok"]
