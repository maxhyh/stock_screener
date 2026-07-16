# -*- coding: utf-8 -*-
"""Raw model fold-instability attribution helper tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

import scripts.quant_raw_model_instability_attribution as diag


def test_failure_label_separates_top_bucket_and_rank_failures():
    row = {
        "top_mean_return_pct": -0.1,
        "top_minus_all_pct": 0.2,
        "top_minus_bottom_pct": -0.3,
        "rank_ic_mean": 0.0,
    }

    out = diag._failure_label(row)

    assert "top_mean_non_positive" in out
    assert "top_not_above_bottom" in out
    assert "rank_ic_non_positive" in out
    assert "top_not_above_pool" not in out


def test_regime_label_uses_expost_day_mean_buckets():
    assert diag._regime_label(-1.5) == "broad_down"
    assert diag._regime_label(-0.2) == "mild_down"
    assert diag._regime_label(0.4) == "mild_up"
    assert diag._regime_label(1.2) == "broad_up"


def test_add_exante_market_regime_uses_trailing_signal_date_data():
    rows = []
    for d, ret in zip(pd.date_range("2026-01-01", periods=8), [-1.0, -0.8, -0.7, -0.6, -0.5, -0.4, -0.3, -0.2]):
        for i in range(4):
            rows.append({"trade_date": d, "ts_code": f"{i:06d}.SZ", "pct_chg": ret, "amount": 100.0})
    df = pd.DataFrame(rows)

    out = diag.add_exante_market_regime(df)

    assert "market_regime_exante" in out.columns
    assert out["market_ret_20d"].notna().any()
    assert out[out["trade_date"].eq(pd.Timestamp("2026-01-08"))]["market_regime_exante"].iloc[0] == "risk_off"


def test_clean_with_extras_preserves_exante_regime_labels():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01", "2026-01-02"],
            "ts_code": ["000001.SZ", "000002.SZ"],
            "market_regime_exante": ["risk_on", "risk_off"],
            "market_ret_20d": [0.2, -0.2],
            "x": [1.0, 2.0],
            "label": [0.5, -0.5],
        }
    )

    out = diag._clean_with_extras(df, ["x"], "label")

    assert out["market_regime_exante"].tolist() == ["risk_on", "risk_off"]
    assert out["market_ret_20d"].tolist() == [0.2, -0.2]


def test_rank_normalize_feature_frame_is_cross_sectional_by_day():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3 + ["2026-01-02"] * 3,
            "x": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
        }
    )

    out = diag._rank_normalize_feature_frame(df, ["x"])

    assert list(out["x"].round(6).iloc[:3]) == [round(1 / 3, 6), round(2 / 3, 6), 1.0]
    assert list(out["x"].round(6).iloc[3:]) == [round(1 / 3, 6), round(2 / 3, 6), 1.0]


def test_exante_regime_summary_uses_signal_date_regime_column():
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 4,
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
            "market_regime_exante": ["risk_off", "risk_off", "neutral", "neutral"],
            "pred": [4.0, 3.0, 2.0, 1.0],
            "label": [-1.0, -2.0, 3.0, 1.0],
        }
    )

    out = diag._exante_regime_summary(pred, top_n=1)
    risk = out[out["regime_exante"].eq("risk_off")].iloc[0]

    assert set(out["regime_exante"]) == {"risk_off", "neutral"}
    assert risk["top_mean_return_pct"] == -1.0
    assert "top_mean_non_positive" in risk["failure_label"]


def test_objective_params_cover_objective_family_variants():
    assert diag._objective_params_for_variant("regression_l1") == ("regression_l1", "l1")
    assert diag._objective_params_for_variant("huber") == ("huber", "huber")
    assert diag._objective_params_for_variant("baseline") == ("regression", "rmse")
    assert diag._objective_params_for_variant("rank_norm_huber") == ("huber", "huber")
    assert diag._objective_params_for_variant("rank_norm_label_demeaned") == ("regression", "rmse")


def test_rank_norm_variant_helpers_parse_base_modes():
    assert diag._base_model_variant("rank_normalized") == "baseline"
    assert diag._base_model_variant("rank_norm_lambdarank") == "lambdarank"
    assert diag._base_model_variant("abs_calibrated_rank_norm_regime_label_ranked") == "regime_label_ranked"
    assert diag._base_model_variant("engineered_rank_norm_regime_label_positive_ranked") == "regime_label_positive_ranked"
    assert diag._base_model_variant("context_rank_norm_regime_label_tail_ranked") == "regime_label_tail_ranked"
    assert diag._base_model_variant("downside_context_rank_norm_regime_label_ranked") == "regime_label_ranked"
    assert diag._base_model_variant("context_rank_norm_regime_label_weak_positive_ranked") == "regime_label_weak_positive_ranked"
    assert diag._base_model_variant("context_rank_norm_regime_label_strict_positive_ranked") == "regime_label_strict_positive_ranked"
    assert diag._base_model_variant("context_rank_norm_regime_label_margin_positive_ranked") == "regime_label_margin_positive_ranked"
    assert diag._base_model_variant("context_rank_norm_regime_label_state_weak_positive_ranked") == "regime_label_state_weak_positive_ranked"
    assert diag._base_model_variant("state_weighted_context_rank_norm_regime_label_weak_positive_ranked") == "regime_label_weak_positive_ranked"
    assert diag._base_model_variant("matched_state_context_rank_norm_regime_label_weak_positive_ranked") == "regime_label_weak_positive_ranked"
    assert (
        diag._base_model_variant("state_weighted_day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked")
        == "regime_label_weak_positive_ranked"
    )
    assert diag._variant_feature_mode("rank_norm_cross_sectional_only") == "cross_sectional_only"
    assert diag._variant_feature_mode("engineered_rank_norm_regime_label_positive_ranked") == "engineered"
    assert diag._variant_feature_mode("context_rank_norm_regime_label_tail_ranked") == "context"
    assert diag._variant_feature_mode("downside_context_rank_norm_regime_label_ranked") == "context"
    assert diag._variant_feature_mode("state_weighted_context_rank_norm_regime_label_weak_positive_ranked") == "context"
    assert diag._uses_rank_normalization("rank_norm_regression_l1") is True
    assert diag._uses_rank_normalization("pos52w_beta_rank_norm_regime_label_ranked") is True
    assert diag._uses_rank_normalization("engineered_rank_norm_regime_label_positive_ranked") is True
    assert diag._uses_rank_normalization("context_rank_norm_regime_label_tail_ranked") is True
    assert diag._uses_rank_normalization("downside_context_rank_norm_regime_label_ranked") is True
    assert diag._uses_rank_normalization("state_weighted_context_rank_norm_regime_label_weak_positive_ranked") is True
    assert diag._uses_engineered_features("engineered_rank_norm_regime_label_positive_ranked") is True
    assert diag._uses_context_features("context_rank_norm_regime_label_tail_ranked") is True
    assert diag._uses_context_features("downside_context_rank_norm_regime_label_ranked") is True
    assert diag._uses_context_features("matched_state_context_rank_norm_regime_label_weak_positive_ranked") is True
    assert diag._uses_downside_weights("downside_context_rank_norm_regime_label_ranked") is True
    assert diag._uses_state_similarity_weights("state_weighted_context_rank_norm_regime_label_weak_positive_ranked") is True
    assert diag._uses_matched_state_training("matched_state_context_rank_norm_regime_label_weak_positive_ranked") is True
    assert diag._uses_rank_normalization("cross_sectional_only") is False
    assert diag._variant_label_mode("rank_norm_label_demeaned") == "daily_demeaned"
    assert diag._variant_label_mode("rank_norm_regime_label_ranked") == "daily_ranked"
    assert diag._variant_label_mode("engineered_rank_norm_regime_label_positive_ranked") == "positive_daily_ranked"
    assert diag._variant_label_mode("context_rank_norm_regime_label_tail_ranked") == "tail_positive_daily_ranked"
    assert diag._variant_label_mode("downside_context_rank_norm_regime_label_ranked") == "daily_ranked"
    assert diag._variant_label_mode("context_rank_norm_regime_label_weak_positive_ranked") == "weak_positive_daily_ranked"
    assert diag._variant_label_mode("context_rank_norm_regime_label_state_weak_positive_ranked") == "state_weak_positive_daily_ranked"
    assert diag._variant_label_mode("context_rank_norm_regime_label_strict_positive_ranked") == "strict_positive_daily_ranked"
    assert diag._variant_label_mode("context_rank_norm_regime_label_margin_positive_ranked") == "margin_positive_daily_ranked"
    assert diag._variant_label_mode("abs_pos52w_beta_rank_norm_regime_label_ranked") == "daily_ranked"
    assert diag._is_regime_specific_model("regime_label_demeaned") is True
    assert diag._is_regime_specific_model("regime_label_positive_ranked") is True
    assert diag._is_regime_specific_model("regime_label_tail_ranked") is True
    assert diag._lgb_train_variant_for_base("label_ranked") == "baseline"
    assert diag._lgb_train_variant_for_base("regime_label_positive_ranked") == "baseline"
    assert diag._lgb_train_variant_for_base("regime_label_tail_ranked") == "baseline"
    assert diag._variant_treatments("abs_pos52w_beta_rank_norm_regime_label_ranked") == [
        "absolute_return_blend",
        "pos52w_beta_overlay",
    ]
    assert diag._variant_treatments("day_veto_conditional_pos52w_beta_rank_norm_regime_label_ranked") == [
        "day_level_absolute_veto",
        "conditional_pos52w_beta_overlay",
    ]
    assert diag._variant_treatments("day_calibrated_opportunity_rank_norm_regime_label_ranked") == [
        "day_state_absolute_calibration",
        "day_state_pos52w_beta_opportunity_overlay",
    ]
    assert diag._variant_treatments("day_calibrated_context_rank_norm_regime_label_ranked") == [
        "day_state_absolute_calibration",
    ]
    assert diag._variant_feature_mode("day_calibrated_context_rank_norm_regime_label_ranked") == "context"
    assert diag._uses_downside_weights("day_calibrated_downside_context_rank_norm_regime_label_ranked") is True
    assert diag._variant_treatments("two_stage_hit_rank_norm_regime_label_ranked") == [
        "positive_hit_blend",
    ]
    assert diag._variant_treatments("context_two_stage_hit_rank_norm_regime_label_tail_ranked") == [
        "positive_hit_blend",
    ]
    assert diag._variant_treatments("context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked") == [
        "positive_hit_blend",
    ]
    assert diag._variant_treatments("day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked") == [
        "positive_hit_blend",
        "day_state_absolute_calibration",
    ]
    assert diag._variant_treatments("abstain_context_rank_norm_regime_label_weak_positive_ranked") == [
        "day_state_deployability_abstention",
    ]
    assert diag._variant_treatments("abstain_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked") == [
        "positive_hit_blend",
        "day_state_deployability_abstention",
    ]
    assert diag._variant_treatments("abstain_day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked") == [
        "positive_hit_blend",
        "day_state_absolute_calibration",
        "day_state_deployability_abstention",
    ]
    assert diag._variant_treatments("validated_abstain_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked") == [
        "positive_hit_blend",
        "validated_day_state_deployability_abstention",
    ]
    assert diag._variant_treatments("validated_abstain_day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked") == [
        "positive_hit_blend",
        "day_state_absolute_calibration",
        "validated_day_state_deployability_abstention",
    ]
    assert diag._variant_treatments("hit_abstain_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked") == [
        "positive_hit_blend",
        "positive_hit_deployability_abstention",
    ]
    assert diag._variant_treatments("context_two_stage_hit_rank_norm_regime_label_strict_positive_ranked") == [
        "positive_hit_blend",
    ]
    assert diag._variant_treatments("context_two_stage_hit_rank_norm_regime_label_margin_positive_ranked") == [
        "positive_hit_blend",
    ]
    assert diag._variant_treatments("state_weighted_day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked") == [
        "positive_hit_blend",
        "day_state_absolute_calibration",
    ]


def test_downside_aware_weights_emphasize_weak_day_survivors_and_losses():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3 + ["2026-01-02"] * 3,
            "label": [-3.0, -0.5, 0.5, 0.1, 0.2, 0.3],
        }
    )

    out = diag._downside_aware_weights(df, "label")

    assert np.isclose(float(out.mean()), 1.0)
    assert float(out[2]) > float(out[5])
    assert float(out[0]) > float(out[3])


def test_state_similarity_weights_emphasize_train_days_near_reference_state():
    train = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3 + ["2026-01-02"] * 3,
            "market_vol_20d": [2.0] * 3 + [0.2] * 3,
            "market_up_rate_20d": [35.0] * 3 + [70.0] * 3,
            "pos_52w": [0.2, 0.3, 0.4, 0.8, 0.9, 1.0],
        }
    )
    reference = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 3,
            "market_vol_20d": [2.1] * 3,
            "market_up_rate_20d": [36.0] * 3,
            "pos_52w": [0.25, 0.35, 0.45],
        }
    )

    weights, note = diag._state_similarity_day_weights(train, reference, neighbor_days=1)

    assert "state_similarity" in note
    assert float(weights.loc[pd.Timestamp("2026-01-01")]) > float(weights.loc[pd.Timestamp("2026-01-02")])


def test_matched_state_training_frame_keeps_closest_state_days():
    train = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 2 + ["2026-01-02"] * 2 + ["2026-01-03"] * 2,
            "market_vol_20d": [2.0] * 2 + [1.0] * 2 + [0.2] * 2,
            "market_up_rate_20d": [35.0] * 2 + [50.0] * 2 + [70.0] * 2,
            "pos_52w": [0.2, 0.3, 0.5, 0.6, 0.8, 0.9],
        }
    )
    reference = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 2,
            "market_vol_20d": [2.1] * 2,
            "market_up_rate_20d": [34.0] * 2,
            "pos_52w": [0.2, 0.3],
        }
    )

    out, note = diag._matched_state_training_frame(
        train,
        reference,
        neighbor_days=1,
        keep_day_rate=1 / 3,
        min_days=1,
    )

    assert "matched_state_training" in note
    assert sorted(pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d").unique().tolist()) == ["2026-01-01"]


def test_attach_state_similarity_weights_adds_normalized_weight_column():
    train = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 2 + ["2026-01-02"] * 2,
            "market_vol_20d": [2.0] * 2 + [0.2] * 2,
            "market_up_rate_20d": [35.0] * 2 + [70.0] * 2,
            "pos_52w": [0.2, 0.3, 0.8, 0.9],
        }
    )
    reference = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 2,
            "market_vol_20d": [2.1] * 2,
            "market_up_rate_20d": [36.0] * 2,
            "pos_52w": [0.2, 0.3],
        }
    )

    out, note = diag._attach_state_similarity_weights(train, reference, neighbor_days=1)

    assert "state_similarity" in note
    assert diag.STATE_SIMILARITY_WEIGHT_COL in out.columns
    assert np.isclose(float(out[diag.STATE_SIMILARITY_WEIGHT_COL].mean()), 1.0)
    assert float(out.loc[out["trade_date"].eq("2026-01-01"), diag.STATE_SIMILARITY_WEIGHT_COL].iloc[0]) > float(
        out.loc[out["trade_date"].eq("2026-01-02"), diag.STATE_SIMILARITY_WEIGHT_COL].iloc[0]
    )


def test_make_training_label_supports_daily_demeaned_and_ranked_modes():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3 + ["2026-01-02"] * 3,
            "label": [1.0, 2.0, 4.0, -3.0, -1.0, 2.0],
            "market_vol_20d": [2.0] * 3 + [0.2] * 3,
            "market_up_rate_20d": [35.0] * 3 + [70.0] * 3,
            "pos_52w": [0.2, 0.3, 0.4, 0.8, 0.9, 1.0],
            "volatility_ratio": [2.0, 2.1, 2.2, 0.1, 0.1, 0.1],
        }
    )

    demeaned = diag._make_training_label(df, "label", "daily_demeaned")
    ranked = diag._make_training_label(df, "label", "daily_ranked")
    positive_ranked = diag._make_training_label(df, "label", "positive_daily_ranked")
    tail_ranked = diag._make_training_label(df, "label", "tail_positive_daily_ranked")
    weak_positive_ranked = diag._make_training_label(df, "label", "weak_positive_daily_ranked")
    state_weak_positive_ranked = diag._make_training_label(df, "label", "state_weak_positive_daily_ranked")
    strict_positive_ranked = diag._make_training_label(df, "label", "strict_positive_daily_ranked")
    margin_positive_ranked = diag._make_training_label(df, "label", "margin_positive_daily_ranked")

    assert np.isclose(float(demeaned.iloc[:3].mean()), 0.0)
    assert np.isclose(float(demeaned.iloc[3:].mean()), 0.0)
    assert ranked.iloc[0] < ranked.iloc[2]
    assert ranked.iloc[3] < ranked.iloc[5]
    assert ranked.between(0.0, 1.0).all()
    assert positive_ranked.iloc[0] > positive_ranked.iloc[3]
    assert positive_ranked.between(0.0, 1.0).all()
    assert tail_ranked.iloc[4] < positive_ranked.iloc[4]
    assert tail_ranked.iloc[2] > tail_ranked.iloc[0]
    assert tail_ranked.between(0.0, 1.0).all()
    assert weak_positive_ranked.iloc[3] < weak_positive_ranked.iloc[4] < weak_positive_ranked.iloc[5]
    assert weak_positive_ranked.iloc[5] > 0.5
    assert weak_positive_ranked.iloc[3] < 0.1
    assert weak_positive_ranked.between(0.0, 1.0).all()
    assert state_weak_positive_ranked.iloc[0] > 0.5
    assert state_weak_positive_ranked.iloc[3] == ranked.iloc[3]
    assert state_weak_positive_ranked.between(0.0, 1.0).all()
    assert strict_positive_ranked.iloc[0] > 0.5
    assert strict_positive_ranked.iloc[3] < 0.1
    assert strict_positive_ranked.iloc[5] > strict_positive_ranked.iloc[4]
    assert strict_positive_ranked.between(0.0, 1.0).all()
    assert margin_positive_ranked.iloc[2] > margin_positive_ranked.iloc[0]
    assert margin_positive_ranked.iloc[3] < 0.1
    assert margin_positive_ranked.iloc[5] > 0.65
    assert margin_positive_ranked.between(0.0, 1.0).all()


def test_add_diagnostic_engineered_features_uses_signal_date_inputs():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3,
            "pos_52w": [0.1, 0.5, 0.9],
            "rs_20d": [1.0, 2.0, 3.0],
            "rs_5d": [0.5, 1.0, 1.5],
            "mom_20": [2.0, 4.0, 8.0],
            "mom_5": [1.0, 2.0, 3.0],
            "bias": [0.2, 0.4, 0.6],
            "pv_corr_20": [0.3, 0.4, 0.5],
            "vol_ratio": [1.0, 1.5, 2.0],
            "volatility_ratio": [0.1, 0.2, 0.3],
            "atr_percent": [0.1, 0.1, 0.1],
            "bb_pos": [0.4, 0.5, 0.6],
        }
    )

    out, added = diag._add_diagnostic_engineered_features(df)

    assert "mom20_minus_mom5" in added
    assert "mom20_minus_mom5_cs" in added
    assert out["mom20_minus_mom5"].tolist() == [1.0, 2.0, 5.0]
    assert float(out["pos52w_x_rs20"].iloc[-1]) > float(out["pos52w_x_rs20"].iloc[0])


def test_add_diagnostic_context_features_adds_market_relative_signal_date_features():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3,
            "open": [10.0, 20.0, 30.0],
            "high": [11.0, 22.0, 33.0],
            "low": [9.0, 19.0, 28.0],
            "close": [10.5, 19.0, 32.0],
            "vol": [100.0, 200.0, 300.0],
            "amount": [1000.0, 3000.0, 9000.0],
            "pct_chg": [5.0, -5.0, 2.0],
            "market_ret_pct": [1.0, 1.0, 1.0],
            "market_ret_20d": [-0.2, -0.2, -0.2],
            "market_vol_20d": [0.5, 0.5, 0.5],
            "pos_52w": [0.1, 0.5, 0.9],
            "rs_20d": [1.0, 2.0, 3.0],
            "rs_5d": [0.5, 1.0, 1.5],
            "mom_20": [2.0, 4.0, 8.0],
            "mom_5": [1.0, 2.0, 3.0],
            "bias": [0.2, 0.4, 0.6],
            "pv_corr_20": [0.3, 0.4, 0.5],
            "vol_ratio": [1.0, 1.5, 2.0],
            "volatility_ratio": [0.1, 0.2, 0.3],
            "atr_percent": [0.1, 0.1, 0.1],
            "bb_pos": [0.4, 0.5, 0.6],
        }
    )

    out, added = diag._add_diagnostic_context_features(df)

    assert "gap_open_pct" in added
    assert "stock_minus_market_ret" in added
    assert "market_stress_x_range_cs" in added
    assert np.isclose(float(out["stock_minus_market_ret"].iloc[0]), 4.0)
    assert float(out["amount_log"].iloc[-1]) > float(out["amount_log"].iloc[0])


def test_day_state_frame_keeps_context_day_level_features():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3,
            "gap_open_pct": [1.0, 2.0, 3.0],
            "stock_minus_market_ret": [-1.0, 0.0, 1.0],
            "market_stress_x_range": [2.0, 4.0, 6.0],
        }
    )

    out = diag._day_state_frame(df)

    assert "gap_open_pct_day_mean" in out.columns
    assert "stock_minus_market_ret_day_std" in out.columns
    assert float(out["market_stress_x_range_day_mean"].iloc[0]) == 4.0


def test_positive_hit_blend_adds_secondary_hit_probability(monkeypatch):
    class DummyHitModel:
        def predict(self, values):
            return np.array([0.1, 0.5, 0.9], dtype=float)

    monkeypatch.setattr(diag, "_train_lgb_positive_hit", lambda *args, **kwargs: DummyHitModel())
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3,
            "pred": [0.0, 0.0, 0.0],
            "label": [-1.0, 0.0, 1.0],
        }
    )
    train = pd.DataFrame({"trade_date": ["2025-12-31"] * 3, "x": [1.0, 2.0, 3.0], "label": [-1.0, 1.0, 2.0]})
    test = pd.DataFrame({"trade_date": ["2026-01-01"] * 3, "x": [1.0, 2.0, 3.0], "label": [-1.0, 0.0, 1.0]})

    out, note = diag._apply_positive_hit_blend(
        pred,
        train,
        pd.DataFrame(),
        test,
        features=["x"],
        label_col="label",
        num_boost_round=20,
        early_stopping_rounds=0,
        seed=1,
        num_threads=1,
        hit_weight=0.50,
    )

    assert "positive_hit_blend_weight" in note
    assert out["_positive_hit_blend_active"].all()
    assert out["_positive_hit_prob"].tolist() == [0.1, 0.5, 0.9]
    assert float(out["pred"].iloc[-1]) > float(out["pred"].iloc[0])


def test_build_ensemble_prediction_blends_daily_zscores():
    base = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3,
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "pct_chg": [0.0, 0.0, 0.0],
            "amount": [1.0, 1.0, 1.0],
            "close": [10.0, 10.0, 10.0],
            "label": [1.0, 2.0, 3.0],
        }
    )
    pred_cache = {
        "rank_normalized": base.assign(pred=[1.0, 2.0, 3.0]),
        "cross_sectional_only": base.assign(pred=[3.0, 2.0, 1.0]),
    }

    out, note = diag.build_ensemble_prediction(pred_cache, "blend_rank_norm_cross_sectional")

    assert "ensemble_deps" in note
    assert len(out) == 3
    assert out["pred"].round(10).abs().sum() == 0.0


def test_absolute_return_calibrator_blends_daily_zscores():
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3,
            "pred": [1.0, 2.0, 3.0],
        }
    )

    out = diag._blend_with_absolute_return_calibrator(pred, np.array([3.0, 2.0, 1.0]), abs_weight=0.50)

    assert out.round(10).abs().sum() == 0.0


def test_pos52w_beta_overlay_promotes_pos52w_and_beta_features():
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 4,
            "pred": [0.0, 0.0, 0.0, 0.0],
            "pos_52w": [0.1, 0.2, 0.8, 0.9],
            "rs_20d": [0.1, 0.2, 0.8, 0.9],
            "mom_20": [0.1, 0.2, 0.8, 0.9],
            "bias": [0.1, 0.2, 0.8, 0.9],
        }
    )

    out = diag._apply_pos52w_beta_overlay(pred)

    assert float(out.iloc[3]) > float(out.iloc[0])
    assert float(out.iloc[2]) > float(out.iloc[1])


def test_day_level_absolute_veto_uses_train_regime_means_only():
    train = pd.DataFrame(
        {
            "trade_date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "market_regime_exante": ["risk_on", "risk_on", "risk_off", "risk_off"],
            "label": [1.0, 2.0, -1.0, -2.0],
        }
    )
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-02-01", "2026-02-01", "2026-02-02", "2026-02-02"],
            "market_regime_exante": ["risk_on", "risk_on", "risk_off", "risk_off"],
            "pred": [1.0, 2.0, 3.0, 4.0],
            "label": [1.0, 1.0, -1.0, -1.0],
        }
    )

    out, note = diag._apply_day_level_absolute_veto(pred, train, label_col="label")

    assert "risk_on" in note
    assert out.groupby("trade_date")["_deploy_signal"].max().tolist() == [True, False]


def test_day_state_absolute_calibration_penalizes_risky_names_on_weak_days():
    train = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 4,
            "market_ret_20d": [-0.20] * 4,
            "market_up_rate_20d": [35.0] * 4,
            "market_vol_20d": [2.0] * 4,
            "label": [-1.0, -1.2, -0.8, -1.1],
            "pos_52w": [0.1, 0.2, 0.8, 0.9],
            "rs_20d": [0.1, 0.2, 0.8, 0.9],
            "mom_20": [0.1, 0.2, 0.8, 0.9],
            "bias": [0.1, 0.2, 0.8, 0.9],
            "atr_percent": [0.1, 0.2, 0.8, 0.9],
            "volatility_ratio": [0.1, 0.2, 0.8, 0.9],
        }
    )
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 4,
            "market_ret_20d": [-0.19] * 4,
            "market_up_rate_20d": [36.0] * 4,
            "market_vol_20d": [2.1] * 4,
            "pred": np.zeros(4),
            "label": np.zeros(4),
            "pos_52w": [0.1, 0.2, 0.8, 0.9],
            "rs_20d": [0.1, 0.2, 0.8, 0.9],
            "mom_20": [0.1, 0.2, 0.8, 0.9],
            "bias": [0.1, 0.2, 0.8, 0.9],
            "atr_percent": [0.1, 0.2, 0.8, 0.9],
            "volatility_ratio": [0.1, 0.2, 0.8, 0.9],
        }
    )

    out, note = diag._apply_day_state_absolute_calibration(pred, train, label_col="label", neighbor_days=1)

    assert "day_state_absolute_calibration" in note
    assert "_deploy_signal" not in out.columns
    assert out["_treatment_active"].all()
    assert float(out["pred"].iloc[0]) > float(out["pred"].iloc[-1])


def test_day_state_deployability_abstention_vetoes_similar_weak_days():
    train = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 4 + ["2026-01-02"] * 4,
            "market_ret_20d": [-0.20] * 4 + [0.15] * 4,
            "market_up_rate_20d": [35.0] * 4 + [60.0] * 4,
            "market_vol_20d": [2.0] * 4 + [0.8] * 4,
            "label": [-2.0, -1.0, -0.5, 0.1, -0.1, 0.2, 0.6, 1.0],
            "pos_52w": [0.8, 0.7, 0.6, 0.5, 0.1, 0.2, 0.3, 0.4],
        }
    )
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 4 + ["2026-02-02"] * 4,
            "market_ret_20d": [-0.19] * 4 + [0.14] * 4,
            "market_up_rate_20d": [36.0] * 4 + [59.0] * 4,
            "market_vol_20d": [2.1] * 4 + [0.9] * 4,
            "pred": np.zeros(8),
            "label": np.zeros(8),
            "pos_52w": [0.8, 0.7, 0.6, 0.5, 0.1, 0.2, 0.3, 0.4],
        }
    )

    out, note = diag._apply_day_state_deployability_abstention(
        pred,
        train,
        label_col="label",
        neighbor_days=1,
        min_expected_return_pct=0.0,
        min_expected_positive_rate_pct=48.0,
        max_expected_left_tail_rate_pct=45.0,
    )

    assert "day_state_deployability_abstention" in note
    assert out.groupby("trade_date")["_deploy_signal"].max().tolist() == [False, True]
    assert out.groupby("trade_date")["_treatment_active"].max().tolist() == [True, False]
    assert float(out[out["trade_date"].eq("2026-02-01")]["_day_deploy_expected_return_pct"].iloc[0]) < 0.0
    assert float(out[out["trade_date"].eq("2026-02-02")]["_day_deploy_expected_return_pct"].iloc[0]) > 0.0


def test_validated_day_state_deployability_abstention_raises_threshold_from_validation():
    fit = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 3 + ["2026-01-02"] * 3 + ["2026-01-03"] * 3,
            "market_ret_20d": [-0.2] * 3 + [0.0] * 3 + [0.2] * 3,
            "market_up_rate_20d": [35.0] * 3 + [50.0] * 3 + [65.0] * 3,
            "market_vol_20d": [2.0] * 3 + [1.2] * 3 + [0.7] * 3,
            "label": [-2.0, -1.0, 0.0, -1.0, 0.2, 0.4, 0.1, 0.5, 1.0],
            "pos_52w": [0.8, 0.7, 0.6, 0.4, 0.5, 0.6, 0.1, 0.2, 0.3],
        }
    )
    valid = pd.DataFrame(
        {
            "trade_date": ["2026-01-10"] * 3 + ["2026-01-11"] * 3,
            "market_ret_20d": [0.0] * 3 + [0.2] * 3,
            "market_up_rate_20d": [50.0] * 3 + [65.0] * 3,
            "market_vol_20d": [1.2] * 3 + [0.7] * 3,
            "label": [-1.0, -0.5, 0.1, 0.2, 0.6, 1.0],
            "pos_52w": [0.4, 0.5, 0.6, 0.1, 0.2, 0.3],
        }
    )
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 3 + ["2026-02-02"] * 3,
            "market_ret_20d": [0.0] * 3 + [0.2] * 3,
            "market_up_rate_20d": [50.0] * 3 + [65.0] * 3,
            "market_vol_20d": [1.2] * 3 + [0.7] * 3,
            "pred": np.zeros(6),
            "label": np.zeros(6),
            "pos_52w": [0.4, 0.5, 0.6, 0.1, 0.2, 0.3],
        }
    )

    out, note = diag._apply_validated_day_state_deployability_abstention(
        pred,
        fit,
        valid,
        label_col="label",
        neighbor_days=1,
        min_expected_return_pct=-2.0,
        min_expected_positive_rate_pct=0.0,
        max_expected_left_tail_rate_pct=100.0,
        min_validation_deploy_rate_pct=50.0,
    )

    assert "validated_threshold" in note
    assert out.groupby("trade_date")["_deploy_signal"].max().tolist() == [False, True]


def test_positive_hit_deployability_abstention_uses_validation_threshold(monkeypatch):
    class DummyHitModel:
        def predict(self, values):
            return np.asarray(values, dtype=float).reshape(-1)

    monkeypatch.setattr(diag, "_train_lgb_positive_hit", lambda *args, **kwargs: DummyHitModel())
    fit = pd.DataFrame({"trade_date": ["2026-01-01"] * 2, "x": [0.1, 0.9], "label": [-1.0, 1.0]})
    valid = pd.DataFrame(
        {
            "trade_date": ["2026-01-02"] * 2 + ["2026-01-03"] * 2,
            "x": [0.2, 0.3, 0.8, 0.9],
            "label": [-1.0, -0.5, 0.5, 1.0],
        }
    )
    test = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 2 + ["2026-02-02"] * 2,
            "x": [0.2, 0.3, 0.8, 0.9],
            "label": [-1.0, -0.5, 0.5, 1.0],
        }
    )
    pred = test.rename(columns={"label": "label"}).assign(pred=0.0)

    out, note = diag._apply_positive_hit_deployability_abstention(
        pred,
        fit,
        valid,
        test,
        features=["x"],
        label_col="label",
        top_n=1,
        num_boost_round=20,
        early_stopping_rounds=0,
        seed=1,
        num_threads=1,
        min_validation_deploy_rate_pct=50.0,
    )

    assert "positive_hit_deployability_abstention" in note
    assert out.groupby("trade_date")["_deploy_signal"].max().tolist() == [False, True]
    assert float(out["_day_hit_deploy_score"].iloc[-1]) > float(out["_day_hit_deploy_score"].iloc[0])


def test_conditional_pos52w_beta_overlay_only_changes_allowed_regime():
    train = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 4 + ["2026-01-02"] * 4,
            "market_regime_exante": ["risk_on"] * 4 + ["risk_off"] * 4,
            "label": [0.0, 0.1, 1.0, 1.2, 0.0, 0.1, 1.0, 1.2],
            "pos_52w": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9, 0.1, 0.2],
            "rs_20d": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9, 0.1, 0.2],
            "mom_20": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9, 0.1, 0.2],
            "bias": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9, 0.1, 0.2],
        }
    )
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 4 + ["2026-02-02"] * 4,
            "market_regime_exante": ["risk_on"] * 4 + ["risk_off"] * 4,
            "pred": np.zeros(8),
            "label": np.zeros(8),
            "pos_52w": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9, 0.1, 0.2],
            "rs_20d": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9, 0.1, 0.2],
            "mom_20": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9, 0.1, 0.2],
            "bias": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9, 0.1, 0.2],
        }
    )

    out, note = diag._apply_conditional_pos52w_beta_overlay(pred, train, label_col="label", top_n=1)

    assert "conditional_pos52w_beta_allowed=risk_on" in note
    assert out.loc[out["market_regime_exante"].eq("risk_on"), "pred"].abs().sum() > 0.0
    assert out.loc[out["market_regime_exante"].eq("risk_off"), "pred"].abs().sum() == 0.0


def test_day_state_pos52w_beta_opportunity_overlay_activates_only_train_supported_days():
    train = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 4 + ["2026-01-02"] * 4,
            "market_ret_20d": [0.20] * 4 + [-0.20] * 4,
            "market_up_rate_20d": [60.0] * 4 + [35.0] * 4,
            "market_vol_20d": [0.8] * 4 + [2.0] * 4,
            "label": [0.0, 0.2, 2.0, 2.2, 2.0, 2.2, -1.0, -1.2],
            "pos_52w": [0.1, 0.2, 0.8, 0.9, 0.1, 0.2, 0.8, 0.9],
            "rs_20d": [0.1, 0.2, 0.8, 0.9, 0.1, 0.2, 0.8, 0.9],
            "mom_20": [0.1, 0.2, 0.8, 0.9, 0.1, 0.2, 0.8, 0.9],
            "bias": [0.1, 0.2, 0.8, 0.9, 0.1, 0.2, 0.8, 0.9],
        }
    )
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-02-01"] * 4 + ["2026-02-02"] * 4,
            "market_ret_20d": [0.21] * 4 + [-0.19] * 4,
            "market_up_rate_20d": [59.0] * 4 + [36.0] * 4,
            "market_vol_20d": [0.9] * 4 + [2.1] * 4,
            "pred": np.zeros(8),
            "label": np.zeros(8),
            "pos_52w": [0.1, 0.2, 0.8, 0.9, 0.1, 0.2, 0.8, 0.9],
            "rs_20d": [0.1, 0.2, 0.8, 0.9, 0.1, 0.2, 0.8, 0.9],
            "mom_20": [0.1, 0.2, 0.8, 0.9, 0.1, 0.2, 0.8, 0.9],
            "bias": [0.1, 0.2, 0.8, 0.9, 0.1, 0.2, 0.8, 0.9],
        }
    )

    out, note = diag._apply_day_state_pos52w_beta_opportunity_overlay(pred, train, label_col="label", top_n=1, neighbor_days=1)

    assert "day_state_pos52w_beta_opportunity" in note
    assert out.groupby("trade_date")["_treatment_active"].max().tolist() == [True, False]
    active = out[out["trade_date"].eq("2026-02-01")]
    inactive = out[out["trade_date"].eq("2026-02-02")]
    assert float(active["pred"].iloc[-1]) > float(active["pred"].iloc[0])
    assert inactive["pred"].abs().sum() == 0.0


def test_append_prediction_diagnostics_reports_deployment_floor_failure():
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 2 + ["2026-01-02"] * 2,
            "ts_code": ["a", "b", "c", "d"],
            "pred": [2.0, 1.0, 2.0, 1.0],
            "label": [1.0, 0.5, 1.0, 0.5],
            "_deploy_signal": [True, True, False, False],
        }
    )
    rows: list[dict[str, object]] = []

    diag.append_prediction_diagnostics(
        pred=pred,
        variant="day_veto",
        fold=1,
        horizon=10,
        win={"test_start": pd.Timestamp("2026-01-01"), "test_end": pd.Timestamp("2026-01-02")},
        variant_features=[],
        usable_features=[],
        model_note="",
        top_n=1,
        variant_drift=pd.DataFrame(),
        imp=pd.DataFrame(),
        variant_rows=rows,
        regime_rows=[],
        importance_rows=[],
        exposure_rows=[],
        min_deployment_day_rate_pct=75.0,
    )

    assert rows[0]["deployment_day_rate_pct"] == 50.0
    assert rows[0]["alpha_gate_pass"] is False
    assert "deployment_day_rate_below_floor" in rows[0]["failure_label"]


def test_append_prediction_diagnostics_reports_treatment_activation():
    pred = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 2 + ["2026-01-02"] * 2,
            "ts_code": ["a", "b", "c", "d"],
            "pred": [2.0, 1.0, 2.0, 1.0],
            "label": [1.0, 0.5, 1.0, 0.5],
            "_treatment_active": [True, True, False, False],
            "_day_abs_expected_return_pct": [-1.0, -1.0, 0.5, 0.5],
        }
    )
    rows: list[dict[str, object]] = []

    diag.append_prediction_diagnostics(
        pred=pred,
        variant="day_calibrated",
        fold=1,
        horizon=10,
        win={"test_start": pd.Timestamp("2026-01-01"), "test_end": pd.Timestamp("2026-01-02")},
        variant_features=[],
        usable_features=[],
        model_note="",
        top_n=1,
        variant_drift=pd.DataFrame(),
        imp=pd.DataFrame(),
        variant_rows=rows,
        regime_rows=[],
        importance_rows=[],
        exposure_rows=[],
    )

    assert rows[0]["treatment_active_day_rate_pct"] == 50.0
    assert rows[0]["mean_day_abs_expected_return_pct"] == -0.25


def test_sample_rows_for_mode_date_stratified_is_seed_stable_and_balanced():
    rows = []
    for d in pd.date_range("2026-01-01", periods=3):
        for i in range(10):
            rows.append({"trade_date": d, "ts_code": f"{i:06d}.SZ", "x": i})
    df = pd.DataFrame(rows)

    one = diag._sample_rows_for_mode(df, 9, 1, "date_stratified")
    two = diag._sample_rows_for_mode(df, 9, 999, "date_stratified")

    assert one[["trade_date", "ts_code"]].equals(two[["trade_date", "ts_code"]])
    assert one.groupby("trade_date").size().tolist() == [3, 3, 3]


def test_sample_rows_for_mode_none_ignores_cap_for_full_diagnostic():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-02", "2026-01-01", "2026-01-01"],
            "ts_code": ["000003.SZ", "000002.SZ", "000001.SZ"],
        }
    )

    out = diag._sample_rows_for_mode(df, 1, 1, "none")

    assert len(out) == 3
    assert out["ts_code"].tolist() == ["000001.SZ", "000002.SZ", "000003.SZ"]


def test_make_rank_labels_are_groupwise_ordered():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01"] * 6 + ["2026-01-02"] * 6,
            "label": list(range(6)) + list(reversed(range(6))),
        }
    )

    out = diag._make_rank_labels(df, "label", n_bins=3)

    assert int(out.iloc[0]) < int(out.iloc[5])
    assert int(out.iloc[6]) > int(out.iloc[11])
    assert set(out.unique()).issubset({0, 1, 2})


def test_drop_high_drift_features_keeps_stable_columns():
    train = pd.DataFrame(
        {
            "stable": np.linspace(0.0, 1.0, 100),
            "drift": np.linspace(0.0, 1.0, 100),
        }
    )
    test = pd.DataFrame(
        {
            "stable": np.linspace(0.0, 1.0, 100),
            "drift": np.linspace(10.0, 11.0, 100),
        }
    )

    kept, drift = diag._drop_high_drift_features(
        train,
        test,
        features=["stable", "drift"],
        psi_threshold=0.30,
        std_diff_threshold=0.60,
    )

    assert "stable" in kept
    assert "drift" not in kept
    assert not drift.empty


def test_build_instability_verdict_detects_partial_variant_fix():
    summary = pd.DataFrame(
        [
            {"horizon": 10, "fold": 6, "variant": "baseline", "alpha_gate_pass": False, "top_mean_return_pct": 0.1, "top_minus_all_pct": -0.2, "rank_ic_mean": 0.01},
            {"horizon": 10, "fold": 7, "variant": "baseline", "alpha_gate_pass": False, "top_mean_return_pct": -0.1, "top_minus_all_pct": 0.2, "rank_ic_mean": 0.02},
            {"horizon": 10, "fold": 6, "variant": "lambdarank", "alpha_gate_pass": True, "top_mean_return_pct": 0.5, "top_minus_all_pct": 0.3, "rank_ic_mean": 0.04},
            {"horizon": 10, "fold": 7, "variant": "lambdarank", "alpha_gate_pass": False, "top_mean_return_pct": -0.2, "top_minus_all_pct": 0.1, "rank_ic_mean": 0.03},
        ]
    )

    out = diag.build_instability_verdict(summary, [6, 7])

    assert out["overall_verdict"] == "instability_variant_partial_fix_only"
    assert out["best_variant"] == "lambdarank"
    assert out["best_variant_pass_rate_pct"] == 50.0


def test_build_instability_verdict_requires_all_focus_folds_for_focus_fix():
    summary = pd.DataFrame(
        [
            {"horizon": 10, "fold": 6, "variant": "baseline", "alpha_gate_pass": False, "top_mean_return_pct": 0.1, "top_minus_all_pct": -0.2, "rank_ic_mean": 0.01},
            {"horizon": 10, "fold": 7, "variant": "baseline", "alpha_gate_pass": False, "top_mean_return_pct": -0.1, "top_minus_all_pct": 0.2, "rank_ic_mean": 0.02},
            {"horizon": 10, "fold": 6, "variant": "recency_weighted", "alpha_gate_pass": True, "top_mean_return_pct": 0.5, "top_minus_all_pct": 0.3, "rank_ic_mean": 0.04},
            {"horizon": 10, "fold": 7, "variant": "recency_weighted", "alpha_gate_pass": True, "top_mean_return_pct": 0.4, "top_minus_all_pct": 0.2, "rank_ic_mean": 0.03},
        ]
    )

    out = diag.build_instability_verdict(summary, [6, 7])

    assert out["overall_verdict"] == "instability_variant_has_focus_fix"
    assert out["best_variant_pass_rate_pct"] == 100.0


def test_build_instability_verdict_rejects_basic_variants_when_no_focus_pass():
    summary = pd.DataFrame(
        [
            {"horizon": 10, "fold": 6, "variant": "baseline", "alpha_gate_pass": False, "top_mean_return_pct": 0.1, "top_minus_all_pct": -0.2, "rank_ic_mean": 0.01},
            {"horizon": 10, "fold": 7, "variant": "baseline", "alpha_gate_pass": False, "top_mean_return_pct": -0.1, "top_minus_all_pct": 0.2, "rank_ic_mean": 0.02},
            {"horizon": 10, "fold": 6, "variant": "recency_weighted", "alpha_gate_pass": False, "top_mean_return_pct": 0.2, "top_minus_all_pct": -0.1, "rank_ic_mean": 0.02},
            {"horizon": 10, "fold": 7, "variant": "recency_weighted", "alpha_gate_pass": False, "top_mean_return_pct": -0.2, "top_minus_all_pct": 0.1, "rank_ic_mean": 0.03},
        ]
    )

    out = diag.build_instability_verdict(summary, [6, 7])

    assert out["overall_verdict"] == "instability_not_fixed_by_basic_variants"


def test_build_fold_attribution_summarizes_regime_drift_and_exposure():
    variant_summary = pd.DataFrame(
        [
            {
                "fold": 6,
                "variant": "baseline",
                "test_start": "2025-09-01",
                "test_end": "2025-12-31",
                "alpha_gate_pass": False,
                "failure_label": "top_not_above_pool",
                "top_mean_return_pct": 0.5,
                "all_mean_return_pct": 0.8,
                "top_minus_all_pct": -0.3,
                "top_minus_bottom_pct": 0.1,
                "rank_ic_mean": 0.01,
            },
            {
                "fold": 6,
                "variant": "recency_weighted",
                "alpha_gate_pass": True,
                "failure_label": "pass",
                "top_mean_return_pct": 1.2,
                "top_minus_all_pct": 0.4,
                "rank_ic_mean": 0.03,
            },
        ]
    )
    regime_summary = pd.DataFrame(
        [
            {"fold": 6, "variant": "baseline", "regime_proxy_expost": "broad_up", "failure_label": "top_not_above_pool", "top_minus_all_pct": -0.5, "top_mean_return_pct": 0.7},
            {"fold": 6, "variant": "baseline", "regime_proxy_expost": "mild_up", "failure_label": "pass", "top_minus_all_pct": 0.2, "top_mean_return_pct": 0.4},
        ]
    )
    importance = pd.DataFrame(
        [
            {"fold": 6, "variant": "baseline", "feature": "pos_52w", "importance_share_pct": 2.0, "psi": 0.8, "std_mean_diff": 0.7},
            {"fold": 6, "variant": "baseline", "feature": "bias", "importance_share_pct": 20.0, "psi": 0.01, "std_mean_diff": 0.01},
        ]
    )
    exposure = pd.DataFrame(
        [
            {"fold": 6, "variant": "baseline", "feature": "atr_percent", "top_minus_all": 4.0},
            {"fold": 6, "variant": "baseline", "feature": "rsi", "top_minus_all": 1.0},
        ]
    )

    out = diag.build_fold_attribution(
        variant_summary,
        regime_summary,
        importance,
        exposure,
        focus_folds=[6],
    )
    row = out.iloc[0]

    assert row["fold_attribution_verdict"] == "variant_rescued_fold"
    assert row["worst_baseline_regime"] == "broad_up"
    assert "pos_52w" in row["drifted_important_features"]
    assert "atr_percent" in row["baseline_top_feature_exposure"]


def test_build_variant_family_summary_requires_critical_fold_pass():
    summary = pd.DataFrame(
        [
            {"fold": 1, "variant": "baseline", "alpha_gate_pass": True, "top_mean_return_pct": 1.0, "top_minus_all_pct": 0.2, "top_minus_bottom_pct": 0.3, "rank_ic_mean": 0.02},
            {"fold": 7, "variant": "baseline", "alpha_gate_pass": False, "top_mean_return_pct": -1.0, "top_minus_all_pct": -0.5, "top_minus_bottom_pct": 1.0, "rank_ic_mean": 0.03},
            {"fold": 1, "variant": "regime_specific", "alpha_gate_pass": True, "top_mean_return_pct": 1.0, "top_minus_all_pct": 0.2, "top_minus_bottom_pct": 0.3, "rank_ic_mean": 0.02},
            {"fold": 7, "variant": "regime_specific", "alpha_gate_pass": True, "top_mean_return_pct": 0.8, "top_minus_all_pct": 0.2, "top_minus_bottom_pct": 0.3, "rank_ic_mean": 0.02},
        ]
    )

    out = diag.build_variant_family_summary(summary, critical_folds=[7], min_fold_pass_rate_pct=50.0)
    by_variant = {str(r["variant"]): str(r["variant_family_verdict"]) for _, r in out.iterrows()}

    assert by_variant["baseline"] == "critical_fold_failed"
    assert by_variant["regime_specific"] == "variant_model_gate_pass"
