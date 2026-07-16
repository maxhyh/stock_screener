import pandas as pd

import scripts.quant_sell_trap_predictor_diagnosis as diag


def test_summarize_predictor_reports_direction_and_recall():
    detail = pd.DataFrame(
        {
            "profile": ["p", "p", "p", "p"],
            "window": [10, 10, 10, 10],
            "blocked_sell_label": [1, 1, 0, 0],
            "position_entry_exit_trap_risk_score": [0.80, 0.70, 0.20, 0.30],
            "position_entry_risk_score": [0.60, 0.40, 0.10, 0.20],
            "position_entry_reserve_candidate": [1, 0, 0, 1],
            "blocked_current_weight": [0.05, 0.04, 0.0, 0.0],
        }
    )

    out = diag.summarize_predictor(detail, risk_threshold=0.65)

    row = out.iloc[0]
    assert int(row["sell_orders"]) == 4
    assert int(row["blocked_sell_orders"]) == 2
    assert round(float(row["entry_exit_trap_risk_blocked_mean"]), 2) == 0.75
    assert round(float(row["entry_exit_trap_risk_filled_mean"]), 2) == 0.25
    assert round(float(row["high_exit_trap_risk_blocked_recall_pct"]), 2) == 100.0
    assert bool(row["predictor_direction_ok"]) is True


def test_summarize_predictor_flags_bad_direction():
    detail = pd.DataFrame(
        {
            "profile": ["p", "p"],
            "window": [10, 10],
            "blocked_sell_label": [1, 0],
            "position_entry_exit_trap_risk_score": [0.10, 0.90],
            "position_entry_risk_score": [0.0, 0.0],
            "position_entry_reserve_candidate": [0, 0],
            "blocked_current_weight": [0.02, 0.0],
        }
    )

    out = diag.summarize_predictor(detail, risk_threshold=0.65)

    assert bool(out.iloc[0]["predictor_direction_ok"]) is False
