# -*- coding: utf-8 -*-
"""Web 变更类接口安全与命令路由测试。"""

from __future__ import annotations

import json

import pytest

from web.app import create_app
import web.routes.results as results_routes


@pytest.fixture
def app():
    app = create_app()
    app.config.update(
        TESTING=True,
        LOCAL_ONLY=True,
        API_WRITE_TOKEN="",
    )
    return app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def test_run_scan_blocks_non_local_without_token(client):
    resp = client.post("/api/run_scan", environ_base={"REMOTE_ADDR": "10.0.0.8"})
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False


def test_run_scan_uses_core_engine_and_accepts_date(client, monkeypatch):
    captured = {}

    class Dummy:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return Dummy()

    monkeypatch.setattr(results_routes.subprocess, "run", fake_run)

    resp = client.post(
        "/api/run_scan",
        json={"date": "20260320"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["command"][-2:] == ["--date", "20260320"]
    assert body["command"][1].endswith("core/mfts_screener.py")
    assert captured["kwargs"]["cwd"].endswith("stock_screener")


def test_download_data_is_disabled_for_read_only_ods(client, monkeypatch):
    called = {"run": False}

    def fake_run(*_args, **_kwargs):
        called["run"] = True
        raise AssertionError("read-only ODS route must not invoke a downloader")

    monkeypatch.setattr(results_routes.subprocess, "run", fake_run)

    resp = client.post(
        "/api/download_data",
        json={"date": "20260319"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 410
    body = resp.get_json()
    assert body["success"] is False
    assert "只读" in body["error"]
    assert called["run"] is False


def test_token_required_when_configured(monkeypatch):
    app = create_app()
    app.config.update(TESTING=True, LOCAL_ONLY=False, API_WRITE_TOKEN="secret-token")

    class Dummy:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(results_routes.subprocess, "run", lambda *args, **kwargs: Dummy())

    with app.test_client() as c:
        denied = c.post("/api/run_scan", environ_base={"REMOTE_ADDR": "10.0.0.8"})
        assert denied.status_code == 401

        allowed = c.post(
            "/api/run_scan",
            headers={"X-API-Token": "secret-token"},
            environ_base={"REMOTE_ADDR": "10.0.0.8"},
        )
        assert allowed.status_code == 200
        assert allowed.get_json()["success"] is True


def test_signal_stats_recompute_requires_auth(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    backtest_dir = output_dir / "backtest"
    backtest_dir.mkdir(parents=True, exist_ok=True)
    (backtest_dir / "signal_stats.json").write_text(json.dumps({"stats": []}), encoding="utf-8")

    app = create_app()
    app.config.update(TESTING=True, LOCAL_ONLY=True, API_WRITE_TOKEN="", OUTPUT_DIR=str(output_dir))

    with app.test_client() as c:
        resp = c.get(
            "/api/signal/stats?start_date=2026-01-01",
            environ_base={"REMOTE_ADDR": "10.0.0.8"},
        )
        assert resp.status_code == 403
