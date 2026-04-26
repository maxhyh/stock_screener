# -*- coding: utf-8 -*-
"""signal pretrade 对齐报告测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

import scripts.quant_signal_pretrade_alignment_report as mod


def test_alignment_report_end_to_end(tmp_path, monkeypatch):
    out_dir = tmp_path / "output"
    exec_dir = out_dir / "execution"
    risk_dir = out_dir / "risk"
    exec_dir.mkdir(parents=True, exist_ok=True)
    risk_dir.mkdir(parents=True, exist_ok=True)

    ledger = pd.DataFrame(
        {
            "run_id": ["20260414_100000_aaaa1111"],
            "signal_date": ["2026-04-13"],
            "trade_date": ["2026-04-14"],
            "risk_input_count": [10],
            "risk_blocked_count": [2],
            "risk_blocked_rate_pct": [20.0],
        }
    )
    ledger.to_csv(exec_dir / "paper_diag_ledger.csv", index=False)

    (risk_dir / "signal_pretrade_summary_20260413.json").write_text(
        json.dumps(
            {
                "date": "2026-04-13",
                "pretrade": {
                    "stage": "pretrade_gate_on",
                    "pool_n": 40,
                    "kept_count": 38,
                    "blocked_count": 2,
                    "blocked_rate_pct": 5.0,
                    "top_reason": "min_price",
                    "top_reason_count": 2,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    pd.DataFrame({"reasons": ["min_price", "min_price"]}).to_csv(
        risk_dir / "signal_pretrade_gates_20260413.csv", index=False
    )
    pd.DataFrame({"reasons": ["adv_participation", "industry_weight"]}).to_csv(
        exec_dir / "paper_diag_risk_gates_20260414_20260414_100000_aaaa1111.csv", index=False
    )

    monkeypatch.setattr(mod, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_signal_pretrade_alignment_report.py",
            "--broker",
            "paper",
            "--channel",
            "paper_diag",
            "--write-latest",
        ],
    )
    rc = mod.main()
    assert rc == 0

    latest_csv = risk_dir / "pretrade_alignment_paper_diag_latest.csv"
    latest_json = risk_dir / "pretrade_alignment_summary_paper_diag_latest.json"
    assert latest_csv.exists()
    assert latest_json.exists()

    df = pd.read_csv(latest_csv)
    assert len(df) == 1
    row = df.iloc[0]
    assert str(row["signal_stage"]) == "pretrade_gate_on"
    assert int(row["signal_blocked_count"]) == 2
    assert int(row["p2_risk_blocked_count"]) == 2
    assert str(row["p2_top_reason"]) == "adv_participation"
    assert float(row["blocked_rate_gap_pct"]) == 15.0

    summary = json.loads(latest_json.read_text(encoding="utf-8"))
    metrics = summary.get("metrics", {})
    assert int(metrics.get("matched_signal_summary_rows", 0)) == 1
    assert float(metrics.get("mean_signal_blocked_rate_pct", 0.0)) == 5.0
    assert float(metrics.get("mean_p2_risk_blocked_rate_pct", 0.0)) == 20.0
