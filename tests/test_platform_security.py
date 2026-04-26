# -*- coding: utf-8 -*-
"""平台安全治理测试。"""

from __future__ import annotations

import json

from core.platform.security_governance import build_config_fingerprint, load_security_config, record_config_change


def test_security_config_fingerprint_is_stable(monkeypatch):
    monkeypatch.setenv("MFTS_LOCAL_ONLY", "true")
    monkeypatch.setenv("MFTS_API_WRITE_TOKEN", "secret")
    monkeypatch.setenv("MFTS_ALERT_WEBHOOK", "")
    monkeypatch.setenv("MFTS_ACTIVE_PROFILE", "balanced")
    cfg = load_security_config()
    fp1 = build_config_fingerprint(cfg)
    fp2 = build_config_fingerprint(cfg)
    assert fp1 == fp2


def test_record_config_change_writes_jsonl(tmp_path):
    path = record_config_change(
        tmp_path,
        actor="codex",
        scope="profile",
        before={"a": 1},
        after={"a": 2},
        reason="test",
    )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["actor"] == "codex"
    assert payload["after"]["a"] == 2
