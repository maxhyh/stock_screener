# -*- coding: utf-8 -*-
"""真实 HTTP 冒烟测试。"""

from __future__ import annotations

import json
import threading
from urllib.request import urlopen

from werkzeug.serving import make_server

from web.app import create_app


def test_live_http_serves_ops_page_api_and_static(tmp_path):
    app = create_app()
    app.config.update(TESTING=True, BASE_DIR=str(tmp_path), OUTPUT_DIR=str(tmp_path / "output"))

    output_dir = tmp_path / "output"
    (output_dir / "platform" / "runs").mkdir(parents=True, exist_ok=True)
    (output_dir / "platform" / "experiments").mkdir(parents=True, exist_ok=True)
    (output_dir / "risk").mkdir(parents=True, exist_ok=True)

    (output_dir / "platform" / "runs" / "run_live.json").write_text(
        json.dumps({"run_id": "run_live", "status": "success", "started_at": "2026-04-23 21:00:00"}),
        encoding="utf-8",
    )
    (output_dir / "platform" / "experiments" / "registry.json").write_text(
        json.dumps([{"experiment_id": "exp_live", "name": "live-smoke"}]),
        encoding="utf-8",
    )
    (output_dir / "risk" / "risk_exposure_summary_latest.csv").write_text(
        "state,trades,avg_exposure_pct,avg_positions,win_rate_pct,avg_portfolio_ret_pct,avg_hhi\n正常,12,62.0,6.0,58.0,1.5,0.16\n",
        encoding="utf-8",
    )
    (output_dir / "risk" / "risk_exposure_industry_latest.csv").write_text(
        "industry,avg_weight_pct,max_weight_pct\n电子,24.0,32.0\n",
        encoding="utf-8",
    )
    (output_dir / "risk" / "exec_consistency_summary_paper_latest.json").write_text(
        json.dumps(
            {
                "coverage_pct": 96.0,
                "matched_rows": 12,
                "rows": 12,
                "ret_gap_mae_pct": 0.4,
                "risk_block_rate_mean_pct": 8.0,
                "order_block_rate_mean_pct": 2.0,
                "consistency_pass": True,
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "risk" / "pretrade_alignment_summary_paper_pretrade_diag_latest.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "match_rate_pct": 94.0,
                    "mean_p2_risk_blocked_rate_pct": 7.0,
                }
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "risk" / "capacity_cost_latest.csv").write_text(
        "signal_date,state,total_exposure_pct,position_count,max_participation_pct,estimated_roundtrip_cost_bps,capacity_multiple,portfolio_ret_pct\n2026-04-10,正常,62.0,6,12.0,18.0,2.8,1.5\n",
        encoding="utf-8",
    )

    server = make_server("127.0.0.1", 0, app)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with urlopen(f"http://127.0.0.1:{port}/platform/ops") as resp:
            assert resp.status == 200
            assert "平台运维与风险暴露" in resp.read().decode("utf-8")

        with urlopen(f"http://127.0.0.1:{port}/api/platform/ops_overview") as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))
            assert payload["success"] is True
            assert payload["platform"]["latest_run_id"] == "run_live"

        with urlopen(f"http://127.0.0.1:{port}/static/pages/platform_ops.js") as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
            assert "loadOpsPage" in body
    finally:
        server.shutdown()
        thread.join(timeout=2)
