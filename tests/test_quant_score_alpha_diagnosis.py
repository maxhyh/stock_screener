import pandas as pd

from scripts import quant_score_alpha_diagnosis as score_diag
from scripts.quant_score_alpha_diagnosis import (
    _infer_scores,
    _select_top_by_score,
    _summarize_score,
    evaluate_alpha_quality_gate,
)


def test_select_top_by_score_respects_descending_direction():
    df = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-01-01"] * 3),
            "code": ["A", "B", "C"],
            "score": [0.1, 0.9, 0.5],
            "forward_return": [0.0, 0.1, 0.2],
        }
    )

    out = _select_top_by_score(df, "score", "desc", top_n=2)

    assert out["code"].tolist() == ["B", "C"]


def test_select_top_by_score_respects_ascending_direction_for_rank():
    df = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-01-01"] * 3),
            "code": ["A", "B", "C"],
            "排名": [3, 1, 2],
            "forward_return": [0.0, 0.1, 0.2],
        }
    )

    out = _select_top_by_score(df, "排名", "asc", top_n=2)

    assert out["code"].tolist() == ["B", "C"]


def test_summarize_score_reports_positive_spread_when_score_orders_returns():
    rows = []
    for d in pd.to_datetime(["2026-01-01", "2026-01-02"]):
        rows.extend(
            [
                {"signal_date": d, "code": f"{d.date()}A", "score": 3.0, "forward_return": 0.03},
                {"signal_date": d, "code": f"{d.date()}B", "score": 2.0, "forward_return": 0.01},
                {"signal_date": d, "code": f"{d.date()}C", "score": 1.0, "forward_return": -0.02},
            ]
        )
    df = pd.DataFrame(rows)

    summary = _summarize_score(df, label="score", score_col="score", direction="desc", top_n=1)

    assert summary["top_mean_forward_return_pct"] > 0
    assert summary["top_minus_bottom_pct"] > 0
    assert summary["rank_ic_mean"] > 0


def test_infer_scores_skips_constant_or_missing_columns():
    df = pd.DataFrame(
        {
            "排名": [1, 2, 3],
            "ML评分": [0.1, 0.2, 0.3],
            "质量分": [1.0, 1.0, 1.0],
        }
    )

    scores = _infer_scores(df)
    cols = [col for _, col, _ in scores]

    assert "排名" in cols
    assert "ML评分" in cols
    assert "质量分" not in cols


def test_build_score_diagnosis_can_group_by_research_stage(monkeypatch):
    daily = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-01-01"] * 6),
            "code": ["A", "B", "C", "D", "E", "F"],
            "research_stage": ["raw", "raw", "raw", "final", "final", "final"],
            "ML评分": [3.0, 2.0, 1.0, 1.0, 2.0, 3.0],
            "forward_return": [0.03, 0.01, -0.02, -0.02, 0.01, 0.03],
        }
    )
    monkeypatch.setattr(score_diag, "_discover_daily_paths", lambda _: [pd.Index([])])
    monkeypatch.setattr(score_diag, "_load_daily_recommendations", lambda *_, **__: daily.copy())
    monkeypatch.setattr(score_diag, "_load_market_bars", lambda *_: pd.DataFrame())
    monkeypatch.setattr(score_diag, "_attach_forward_returns", lambda df, *_, **__: df)
    monkeypatch.setattr(score_diag, "_load_industry_map", lambda _asof_date: {})

    out, meta = score_diag.build_score_diagnosis(
        daily_glob="unused",
        group_col="research_stage",
        top_n=1,
        label="group_test",
    )

    assert meta["group_col"] == "research_stage"
    assert set(out["research_stage"]) == {"raw", "final"}
    assert meta["alpha_quality_gate"]["pass"] is False
    assert meta["alpha_quality_gate"]["reasons"] == ["grouped_diagnostic_not_profile_gate"]
    assert meta["alpha_quality_gate"]["grouped_diagnostic_only"] is True


def test_alpha_quality_gate_passes_when_target_weight_beats_pool():
    summary = pd.DataFrame(
        [
            {
                "artifact_label": "profile",
                "score_label": "target_weight",
                "score_col": "target_weight",
                "top_days": 6,
                "top_valid_forward_rows": 12,
                "top_mean_forward_return_pct": 1.2,
                "all_mean_forward_return_pct": 0.4,
                "top_minus_all_pct": 0.8,
                "top_minus_bottom_pct": 1.5,
                "rank_ic_mean": 0.12,
            }
        ]
    )

    gate = evaluate_alpha_quality_gate(summary, min_top_days=5)

    assert gate["pass"] is True
    assert gate["evaluated"][0]["pass"] is True


def test_alpha_quality_gate_rejects_cash_drag_like_bad_target_score():
    summary = pd.DataFrame(
        [
            {
                "artifact_label": "profile",
                "score_label": "target_weight",
                "score_col": "target_weight",
                "top_days": 6,
                "top_valid_forward_rows": 12,
                "top_mean_forward_return_pct": -1.0,
                "all_mean_forward_return_pct": -0.2,
                "top_minus_all_pct": -0.8,
                "top_minus_bottom_pct": 0.4,
                "rank_ic_mean": -0.05,
            }
        ]
    )

    gate = evaluate_alpha_quality_gate(summary, min_top_days=5)

    assert gate["pass"] is False
    assert gate["reasons"] == ["no_gate_score_passed"]
    assert "top_not_above_pool_average" in gate["evaluated"][0]["reasons"]
    assert "rank_ic_not_positive" in gate["evaluated"][0]["reasons"]


def test_alpha_quality_gate_rejects_negative_top_even_when_relative_spread_positive():
    summary = pd.DataFrame(
        [
            {
                "artifact_label": "profile",
                "score_label": "target_weight",
                "score_col": "target_weight",
                "top_days": 6,
                "top_valid_forward_rows": 12,
                "top_mean_forward_return_pct": -0.1,
                "all_mean_forward_return_pct": -1.0,
                "top_minus_all_pct": 0.9,
                "top_minus_bottom_pct": 1.2,
                "rank_ic_mean": 0.08,
            }
        ]
    )

    gate = evaluate_alpha_quality_gate(summary, min_top_days=5)

    assert gate["pass"] is False
    assert "top_mean_not_positive" in gate["evaluated"][0]["reasons"]


def test_build_score_diagnosis_includes_alpha_quality_gate(monkeypatch):
    daily = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-01-01"] * 4 + ["2026-01-02"] * 4),
            "code": ["A", "B", "C", "D", "E", "F", "G", "H"],
            "target_weight": [0.04, 0.03, 0.02, 0.01, 0.04, 0.03, 0.02, 0.01],
            "forward_return": [0.04, 0.03, -0.01, -0.02, 0.05, 0.02, -0.01, -0.03],
        }
    )
    monkeypatch.setattr(score_diag, "_discover_daily_paths", lambda _: [pd.Index([])])
    monkeypatch.setattr(score_diag, "_load_daily_recommendations", lambda *_, **__: daily.copy())
    monkeypatch.setattr(score_diag, "_load_market_bars", lambda *_: pd.DataFrame())
    monkeypatch.setattr(score_diag, "_attach_forward_returns", lambda df, *_, **__: df)
    monkeypatch.setattr(score_diag, "_load_industry_map", lambda _asof_date: {})

    _, meta = score_diag.build_score_diagnosis(
        daily_glob="unused",
        top_n=1,
        label="gate_test",
        min_top_days=2,
    )

    assert meta["alpha_quality_gate"]["pass"] is True
