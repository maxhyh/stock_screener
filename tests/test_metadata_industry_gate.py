# -*- coding: utf-8 -*-
"""行业元数据完整率门禁测试。"""

from __future__ import annotations

import pandas as pd

import scripts.daily_incremental_update as diu


def test_extract_sector_pairs_uses_label_for_query_and_board_for_name():
    df = pd.DataFrame(
        {
            "label": ["hangye_ZA01", "new_blhy"],
            "板块": ["农业", "玻璃行业"],
        }
    )
    pairs = diu._extract_sector_pairs_from_sector_spot(df)
    assert pairs == [("hangye_ZA01", "农业"), ("new_blhy", "玻璃行业")]


def test_merge_industry_prefers_new_then_old():
    base_meta = pd.DataFrame(
        {
            "ts_code": ["000001", "000002", "000003"],
            "name": ["A", "B", "C"],
            "industry": ["", "", ""],
        }
    )
    industry_map = {"000001": "银行"}
    old_meta = pd.DataFrame(
        {
            "ts_code": ["000002", "000003"],
            "name": ["B_old", "C_old"],
            "industry": ["地产", "化工"],
        }
    )

    out = diu._merge_industry_into_metadata(base_meta, industry_map, old_meta)
    got = dict(zip(out["ts_code"], out["industry"]))
    assert got["000001"] == "银行"
    assert got["000002"] == "地产"
    assert got["000003"] == "化工"


def test_apply_industry_completeness_gate_blocks_degradation():
    old_meta = pd.DataFrame(
        {
            "ts_code": ["000001", "000002"],
            "name": ["A", "B"],
            "industry": ["银行", "地产"],
        }
    )
    new_meta = pd.DataFrame(
        {
            "ts_code": ["000001", "000002"],
            "name": ["A_new", "B_new"],
            "industry": ["", ""],
        }
    )

    final_meta, gate_hit, new_cov, old_cov = diu._apply_industry_completeness_gate(
        new_meta,
        old_meta,
        min_coverage=0.7,
    )
    assert gate_hit is True
    assert new_cov < 0.7
    assert old_cov >= 0.7
    assert dict(zip(final_meta["ts_code"], final_meta["industry"])) == {
        "000001": "银行",
        "000002": "地产",
    }


def test_apply_industry_completeness_gate_allows_when_old_also_low():
    old_meta = pd.DataFrame(
        {
            "ts_code": ["000001", "000002"],
            "name": ["A", "B"],
            "industry": ["", ""],
        }
    )
    new_meta = pd.DataFrame(
        {
            "ts_code": ["000001", "000002"],
            "name": ["A_new", "B_new"],
            "industry": ["银行", ""],
        }
    )

    final_meta, gate_hit, _, _ = diu._apply_industry_completeness_gate(
        new_meta,
        old_meta,
        min_coverage=0.7,
    )
    assert gate_hit is False
    assert dict(zip(final_meta["ts_code"], final_meta["industry"])) == {
        "000001": "银行",
        "000002": "",
    }


def test_build_metadata_with_industry_uses_cache_and_old_fallback(monkeypatch, tmp_path):
    meta_file = tmp_path / "stock_info.csv"
    cache_file = tmp_path / "industry_cache.csv"
    pd.DataFrame(
        {
            "ts_code": ["000001", "000002"],
            "name": ["A_old", "B_old"],
            "industry": ["银行", "地产"],
        }
    ).to_csv(meta_file, index=False, encoding="utf-8")

    spot = pd.DataFrame({"代码": ["sz000001", "sz000002"], "名称": ["A_new", "B_new"]})

    monkeypatch.setattr(diu, "_load_industry_cache", lambda _: {"000001": "银行"})
    monkeypatch.setattr(diu, "_fetch_industry_map_from_ak", lambda: {})
    monkeypatch.setattr(diu, "_save_industry_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(diu, "MIN_INDUSTRY_COVERAGE", 0.6)

    final_meta, stats = diu.build_metadata_with_industry(
        df_spot=spot,
        meta_file=str(meta_file),
        cache_file=str(cache_file),
    )
    out = dict(zip(final_meta["ts_code"], final_meta["industry"]))
    assert out["000001"] == "银行"   # cache
    assert out["000002"] == "地产"   # old fallback
    assert stats["gate_hit"] is False


def test_build_metadata_with_industry_uses_sina_fallback_when_coverage_low(monkeypatch, tmp_path):
    meta_file = tmp_path / "stock_info.csv"
    cache_file = tmp_path / "industry_cache.csv"
    pd.DataFrame({"ts_code": [], "name": [], "industry": []}).to_csv(meta_file, index=False, encoding="utf-8")

    spot = pd.DataFrame({"代码": ["sz000001", "sz000002"], "名称": ["A_new", "B_new"]})

    monkeypatch.setattr(diu, "_load_industry_cache", lambda _: {})
    monkeypatch.setattr(diu, "_fetch_industry_map_from_ak", lambda: {})
    monkeypatch.setattr(diu, "_fetch_industry_map_from_spot_em", lambda: {})
    monkeypatch.setattr(diu, "_fetch_industry_map_from_sina_sectors", lambda: {"000001": "银行", "000002": "地产"})
    monkeypatch.setattr(diu, "_save_industry_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(diu, "MIN_INDUSTRY_COVERAGE", 0.6)
    monkeypatch.setattr(diu, "INDUSTRY_FALLBACK_TARGET_COVERAGE", 0.8)

    final_meta, stats = diu.build_metadata_with_industry(
        df_spot=spot,
        meta_file=str(meta_file),
        cache_file=str(cache_file),
    )

    out = dict(zip(final_meta["ts_code"], final_meta["industry"]))
    assert out["000001"] == "银行"
    assert out["000002"] == "地产"
    assert stats["sina_fallback_industry_count"] == 2
    assert stats["final_coverage"] == 1.0


def test_build_metadata_with_industry_skips_sina_fallback_when_coverage_high(monkeypatch, tmp_path):
    meta_file = tmp_path / "stock_info.csv"
    cache_file = tmp_path / "industry_cache.csv"
    pd.DataFrame({"ts_code": [], "name": [], "industry": []}).to_csv(meta_file, index=False, encoding="utf-8")

    # spot 自带行业，覆盖率已经足够，不应再触发新浪兜底
    spot = pd.DataFrame(
        {
            "代码": ["sz000001", "sz000002"],
            "名称": ["A_new", "B_new"],
            "行业": ["银行", "地产"],
        }
    )

    called = {"sina": 0}

    def _mock_sina():
        called["sina"] += 1
        return {"000001": "银行"}

    monkeypatch.setattr(diu, "_load_industry_cache", lambda _: {})
    monkeypatch.setattr(diu, "_fetch_industry_map_from_ak", lambda: {})
    monkeypatch.setattr(diu, "_fetch_industry_map_from_spot_em", lambda: {})
    monkeypatch.setattr(diu, "_fetch_industry_map_from_sina_sectors", _mock_sina)
    monkeypatch.setattr(diu, "_save_industry_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(diu, "MIN_INDUSTRY_COVERAGE", 0.6)
    monkeypatch.setattr(diu, "INDUSTRY_FALLBACK_TARGET_COVERAGE", 0.8)

    final_meta, stats = diu.build_metadata_with_industry(
        df_spot=spot,
        meta_file=str(meta_file),
        cache_file=str(cache_file),
    )

    assert called["sina"] == 0
    assert stats["sina_fallback_industry_count"] == 0
    assert stats["final_coverage"] == 1.0
    out = dict(zip(final_meta["ts_code"], final_meta["industry"]))
    assert out["000001"] == "银行"
    assert out["000002"] == "地产"


def test_refresh_stock_metadata_writes_csv(monkeypatch, tmp_path):
    meta_file = tmp_path / "stock_info.csv"
    cache_file = tmp_path / "industry_cache.csv"

    spot = pd.DataFrame({"代码": ["sz000001"], "名称": ["平安银行"]})
    out_meta = pd.DataFrame({"ts_code": ["000001"], "name": ["平安银行"], "industry": ["银行"]})

    monkeypatch.setattr(diu, "_fetch_spot_for_metadata", lambda: spot)
    monkeypatch.setattr(
        diu,
        "build_metadata_with_industry",
        lambda df_spot, meta_file, cache_file: (
            out_meta,
            {
                "final_coverage": 1.0,
                "new_coverage": 1.0,
                "old_coverage": 0.0,
                "gate_hit": False,
                "fresh_industry_count": 0,
                "spot_fallback_industry_count": 0,
                "sina_fallback_industry_count": 1,
            },
        ),
    )

    ok, stats = diu.refresh_stock_metadata(meta_file=str(meta_file), cache_file=str(cache_file))
    assert ok is True
    assert stats["final_coverage"] == 1.0

    saved = pd.read_csv(meta_file, dtype={"ts_code": str})
    assert saved.loc[0, "ts_code"] == "000001"
    assert saved.loc[0, "name"] == "平安银行"
    assert saved.loc[0, "industry"] == "银行"
