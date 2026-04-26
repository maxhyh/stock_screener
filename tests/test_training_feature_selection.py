# -*- coding: utf-8 -*-
"""训练特征选择回归测试。"""

from __future__ import annotations

import pandas as pd

from scripts.train_mfts_lgbm import select_features_by_ic


def test_select_features_by_ic_keeps_unmapped_factor_names(tmp_path):
    ic_file = tmp_path / "factor_ic.csv"
    pd.DataFrame(
        {
            "Factor": ["BIAS-20", "custom_alpha", "bias"],
            "Mean_IC": [0.12, 0.09, 0.08],
            "ICIR": [1.5, 1.1, 0.9],
        }
    ).to_csv(ic_file, index=False)

    feature_cols, selected = select_features_by_ic(str(ic_file), min_ic=0.01, top_n=None)

    assert list(selected["Factor"]) == ["BIAS-20", "custom_alpha", "bias"]
    assert feature_cols == ["bias", "custom_alpha"]
