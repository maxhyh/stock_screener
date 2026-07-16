# -*- coding: utf-8 -*-
"""P2 纸面 OMS 核心再平衡逻辑测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from core.execution import create_broker
from core.execution.paper_broker import PaperBroker, PaperBrokerStateError
from scripts.quant_p2_paper_trade import (
    _assign_profile_target_weights,
    _classify_executable_pool_halt_reason,
    _external_target_weight_budget,
    _load_signal_df_with_stats,
    _rebalance as _legacy_script_rebalance,
)
import scripts.quant_p2_paper_trade as p2_trade


def _bars_idx_for_date(trade_date: str, locked_up: bool = False) -> pd.DataFrame:
    td = pd.Timestamp(trade_date)
    if locked_up:
        open_1 = 11.0
        high_1 = 11.0
        low_1 = 11.0
        prev_1 = 10.0
    else:
        open_1 = 10.1
        high_1 = 10.4
        low_1 = 10.0
        prev_1 = 10.0

    df = pd.DataFrame(
        {
            "trade_date": [td, td],
            "code": ["000001", "000002"],
            "open": [open_1, 20.0],
            "high": [high_1, 20.3],
            "low": [low_1, 19.8],
            "close": [10.2, 20.1],
            "vol": [1_000_000, 1_500_000],
            "amount": [100_000_000, 200_000_000],
            "prev_close": [prev_1, 19.9],
        }
    )
    return df.set_index(["trade_date", "code"]).sort_index()


def _signal_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": ["000001", "000002"],
            "名称": ["平安银行", "万科A"],
            "ML评分": [0.9, 0.8],
            "排名_num": [1, 2],
        }
    )


def test_p2_load_bars_uses_bounded_ods_execution_window(monkeypatch):
    source = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-04-01", "2026-04-02"]),
            "code": ["000001", "000001"],
            "open": [10.0, 10.2],
            "high": [10.1, 10.3],
            "low": [9.9, 10.1],
            "close": [10.0, 10.2],
            "vol": [100.0, 110.0],
            "amount": [1_000_000.0, 1_100_000.0],
            "prev_close": [9.8, 10.0],
            "amount_ma20": [1_000_000.0, 1_050_000.0],
            "amount_min5": [1_000_000.0, 1_000_000.0],
            "amount_min10": [1_000_000.0, 1_000_000.0],
        }
    )
    calls: list[dict[str, object]] = []

    def fake_load_execution_bars(start, end, *, lookback_sessions, forward_sessions, include_bj9):
        calls.append(
            {
                "start": str(start),
                "end": str(end),
                "lookback_sessions": lookback_sessions,
                "forward_sessions": forward_sessions,
                "include_bj9": include_bj9,
            }
        )
        return source.copy(), source.set_index(["trade_date", "code"]), {"data_source": "ashare_ods"}

    p2_trade._BARS_CACHE = None
    monkeypatch.setattr(p2_trade, "load_execution_bars", fake_load_execution_bars, raising=False)

    out = p2_trade._load_bars("2026-04-01", "2026-04-02")

    assert calls == [
        {
            "start": "2026-04-01",
            "end": "2026-04-02",
            "lookback_sessions": 20,
            "forward_sessions": 1,
            "include_bj9": False,
        }
    ]
    assert out.attrs["market_data_lineage"]["data_source"] == "ashare_ods"


def test_p2_profile_target_weights_honor_reserve_cap():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003", "000004"],
            "名称": ["A", "B", "C", "D"],
            "ML评分": [0.95, 0.90, 0.85, 0.80],
            "reserve_candidate": [0, 0, 1, 1],
            "amount_ma20": [200_000_000.0] * 4,
        }
    )

    out = _assign_profile_target_weights(
        signal_df=signal_df,
        profile_cfg={
            "optimizer_mode": "capacity_crowding_aware",
            "target_score_col": "ML评分",
            "target_max_reserve_weight": 0.02,
            "redistribute_clipped_weight": True,
            "target_max_industry_weight": 1.0,
            "target_capacity_amount_col": "amount_ma20",
            "target_capacity_amount_buffer": 1.0,
            "target_capital_base": 1_000_000.0,
            "min_valid_positions": 1,
        },
        total_target_pos=0.40,
        max_single_pos=0.15,
        industry_map={"000001": "I1", "000002": "I2", "000003": "I3", "000004": "I4"},
        primary_top_n=2,
    )

    reserve_weight = float(
        pd.to_numeric(out.loc[out["reserve_candidate"].astype(int).gt(0), "target_weight"], errors="coerce")
        .fillna(0.0)
        .sum()
    )
    assert 0.0 < reserve_weight <= 0.02 + 1e-12


def test_p2_profile_target_weights_honor_exit_trap_caps():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "名称": ["A", "B", "C"],
            "ML评分": [0.95, 0.90, 0.85],
            "exit_trap_risk_score": [0.90, 0.80, 0.70],
            "amount_ma20": [200_000_000.0] * 3,
        }
    )

    out = _assign_profile_target_weights(
        signal_df=signal_df,
        profile_cfg={
            "optimizer_mode": "capacity_crowding_aware",
            "target_score_col": "ML评分",
            "target_exit_trap_risk_threshold": 0.65,
            "target_max_exit_trap_weight": 0.07,
            "target_max_exit_trap_single_weight": 0.03,
            "redistribute_clipped_weight": True,
            "target_max_industry_weight": 1.0,
            "target_capacity_amount_col": "amount_ma20",
            "target_capacity_amount_buffer": 1.0,
            "target_capital_base": 1_000_000.0,
            "min_valid_positions": 1,
        },
        total_target_pos=0.30,
        max_single_pos=0.20,
        industry_map={"000001": "I1", "000002": "I2", "000003": "I3"},
        primary_top_n=3,
    )

    high_risk = out[pd.to_numeric(out["exit_trap_risk_score"], errors="coerce").fillna(0.0).ge(0.65)]
    high_risk_weight = float(pd.to_numeric(high_risk["target_weight"], errors="coerce").fillna(0.0).sum())
    assert 0.0 < high_risk_weight <= 0.07 + 1e-12
    assert float(pd.to_numeric(high_risk["target_weight"], errors="coerce").fillna(0.0).max()) <= 0.03 + 1e-12


def _bars_idx_three_for_date(trade_date: str) -> pd.DataFrame:
    td = pd.Timestamp(trade_date)
    df = pd.DataFrame(
        {
            "trade_date": [td, td, td],
            "code": ["000001", "000002", "000003"],
            "open": [10.0, 20.0, 30.0],
            "high": [10.2, 20.3, 30.4],
            "low": [9.9, 19.8, 29.7],
            "close": [10.1, 20.1, 30.2],
            "vol": [1_000_000, 1_500_000, 1_800_000],
            "amount": [100_000_000, 200_000_000, 300_000_000],
            "prev_close": [9.9, 19.8, 29.8],
        }
    )
    return df.set_index(["trade_date", "code"]).sort_index()


def _bars_idx_blocked_exit_and_buy(trade_date: str) -> pd.DataFrame:
    td = pd.Timestamp(trade_date)
    df = pd.DataFrame(
        {
            "trade_date": [td, td],
            "code": ["000001", "000002"],
            "open": [9.0, 20.0],
            "high": [9.0, 20.2],
            "low": [9.0, 19.8],
            "close": [9.0, 20.1],
            "vol": [1_000_000, 1_500_000],
            "amount": [90_000_000, 200_000_000],
            "prev_close": [10.0, 19.9],
        }
    )
    return df.set_index(["trade_date", "code"]).sort_index()


def test_create_broker_returns_paper_instance(tmp_path):
    broker = create_broker(
        "paper",
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
    )
    assert isinstance(broker, PaperBroker)


def test_load_signal_df_classifies_bj_only_as_empty_after_universe_filter(tmp_path):
    fp = tmp_path / "daily_20260319.csv"
    fp.write_text("代码,名称,ML评分\n920001,BJ1,0.9\n920002,BJ2,0.8\n", encoding="utf-8-sig")

    df, stats = _load_signal_df_with_stats(fp, top_n=10, include_bj9=False, exclude_st=True)

    assert df.empty
    assert int(stats["empty_signal"]) == 1
    assert stats["empty_signal_reason"] == "empty_after_universe_filter"
    assert int(stats["raw_rows"]) == 2
    assert int(stats["filtered_bj9_rows"]) == 2
    assert int(stats["post_filter_rows"]) == 0


def test_load_signal_df_classifies_raw_empty_signal(tmp_path):
    fp = tmp_path / "daily_20260320.csv"
    fp.write_text("代码,名称,ML评分\n", encoding="utf-8-sig")

    df, stats = _load_signal_df_with_stats(fp, top_n=10, include_bj9=False, exclude_st=True)

    assert df.empty
    assert int(stats["empty_signal"]) == 1
    assert stats["empty_signal_reason"] == "empty_signal_raw"


def test_external_target_weight_budget_caps_p2_reoptimization_budget():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "target_weight": [0.012, 0.018, 0.0],
            "target_weight_checksum": ["abc", "abc", "abc"],
        }
    )

    out = _external_target_weight_budget(signal_df)

    assert out["has_external_target_weight"] is True
    assert out["target_weight_sum"] == pytest.approx(0.03)
    assert int(out["target_weight_positive_count"]) == 2
    assert out["target_weight_max"] == pytest.approx(0.018)
    assert out["target_weight_checksum"] == "abc"


def test_external_target_weight_budget_preserves_explicit_zero_budget():
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002"],
            "target_weight": [0.0, 0.0],
            "target_weight_checksum": ["zero", "zero"],
        }
    )

    out = _external_target_weight_budget(signal_df)

    assert out["has_external_target_weight"] is True
    assert out["target_weight_sum"] == pytest.approx(0.0)
    assert int(out["target_weight_positive_count"]) == 0
    assert out["target_weight_max"] == pytest.approx(0.0)
    assert out["target_weight_checksum"] == "zero"


def test_rebalance_generates_buy_orders_and_positions(tmp_path):
    broker = PaperBroker(
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
    )
    state = {"cash": 1_000_000.0, "positions": {}}
    result = broker.rebalance_on_state(
        state=state,
        signal_df=_signal_df(),
        bars_idx=_bars_idx_for_date("2026-03-21"),
        signal_date=pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-21"),
        run_id="t1",
        top_n=2,
        target_total_pos=0.6,
        max_single_pos=0.35,
    )
    orders_df, fills_df, new_state = result.orders_df, result.fills_df, result.state

    assert not orders_df.empty
    assert not fills_df.empty
    assert (orders_df["side"] == "BUY").any()
    assert any(int(v.get("qty", 0)) > 0 for v in new_state["positions"].values())
    assert float(new_state["cash"]) < 1_000_000.0


def test_rebalance_uses_external_target_weight_when_present(tmp_path):
    broker = PaperBroker(
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
    )
    signal_df = _signal_df()
    signal_df["target_weight"] = [0.10, 0.50]
    signal_df["impact_cost_bps"] = [0.0, 0.0]

    result = broker.rebalance_on_state(
        state={"cash": 1_000_000.0, "positions": {}},
        signal_df=signal_df,
        bars_idx=_bars_idx_for_date("2026-03-21"),
        signal_date=pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-21"),
        run_id="target_weight",
        top_n=2,
        target_total_pos=0.6,
        max_single_pos=0.6,
    )

    buys = result.orders_df[result.orders_df["side"] == "BUY"].set_index("code")
    assert float(buys.loc["000001", "target_weight"]) == 0.10
    assert float(buys.loc["000002", "target_weight"]) == 0.50
    assert str(buys.loc["000001", "target_weight_source"]) == "external_target_weight"
    assert str(buys.loc["000002", "target_weight_source"]) == "external_target_weight"
    assert int(buys.loc["000002", "requested_qty"]) > int(buys.loc["000001", "requested_qty"])
    assert result.ledger_row["target_weight_sum"] == pytest.approx(0.60)
    assert result.ledger_row["target_weight_raw_sum"] == pytest.approx(0.60)
    assert result.ledger_row["target_weight_source"] == "external_target_weight"


def test_rebalance_uses_all_positive_external_target_weights_beyond_topn(tmp_path):
    broker = PaperBroker(
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
    )
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003"],
            "名称": ["A", "B", "C"],
            "ML评分": [0.9, 0.8, 0.7],
            "排名_num": [1, 2, 3],
            "target_weight": [0.10, 0.20, 0.30],
        }
    )

    result = broker.rebalance_on_state(
        state={"cash": 1_000_000.0, "positions": {}},
        signal_df=signal_df,
        bars_idx=_bars_idx_three_for_date("2026-03-21"),
        signal_date=pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-21"),
        run_id="reserve_pool_external_weight",
        top_n=2,
        target_total_pos=0.6,
        max_single_pos=0.6,
    )

    buys = result.orders_df[result.orders_df["side"] == "BUY"].set_index("code")
    assert set(buys.index) == {"000001", "000002", "000003"}
    assert float(buys.loc["000003", "target_weight"]) == 0.30
    assert result.ledger_row["target_weight_sum"] == pytest.approx(0.60)


def test_rebalance_explicit_zero_external_target_is_risk_off_exit_only(tmp_path):
    broker = PaperBroker(
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
    )
    signal_df = _signal_df()
    signal_df["target_weight"] = [0.0, 0.0]

    result = broker.rebalance_on_state(
        state={
            "cash": 900_000.0,
            "positions": {"000001": {"name": "平安银行", "qty": 10_000, "avg_cost": 9.5}},
        },
        signal_df=signal_df,
        bars_idx=_bars_idx_for_date("2026-03-21"),
        signal_date=pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-21"),
        run_id="explicit_zero_target_risk_off",
        top_n=2,
        target_total_pos=0.0,
        max_single_pos=0.6,
    )

    assert set(result.orders_df["side"]) == {"SELL"}
    assert set(result.orders_df["status"]) == {"filled"}
    assert result.state["positions"] == {}
    assert result.ledger_row["target_weight_sum"] == pytest.approx(0.0)
    assert result.ledger_row["target_weight_source"] == "external_target_weight"


def test_rebalance_empty_signal_is_risk_off_exit_only(tmp_path):
    broker = PaperBroker(
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
    )

    result = broker.rebalance_on_state(
        state={
            "cash": 900_000.0,
            "positions": {"000001": {"name": "平安银行", "qty": 10_000, "avg_cost": 9.5}},
        },
        signal_df=pd.DataFrame(columns=["代码", "名称", "ML评分", "排名_num", "target_weight"]),
        bars_idx=_bars_idx_for_date("2026-03-21"),
        signal_date=pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-21"),
        run_id="empty_signal_risk_off",
        top_n=2,
        target_total_pos=0.0,
        max_single_pos=0.6,
    )

    assert set(result.orders_df["side"]) == {"SELL"}
    assert set(result.orders_df["status"]) == {"filled"}
    assert result.state["positions"] == {}
    assert float(result.state["cash"]) > 900_000.0
    assert result.ledger_row["target_weight_sum"] == pytest.approx(0.0)


def test_executable_pool_halt_reason_classifies_mixed_gate_hits():
    reason = _classify_executable_pool_halt_reason(
        {
            "entry_not_tradable_hit": 2,
            "adv_limits_hit": 8,
            "style_limits_hit": 3,
        }
    )
    assert reason == "pretrade_empty:entry_not_tradable+adv_capacity+style_exposure"


def test_legacy_script_rebalance_delegates_to_canonical_target_weight_path():
    signal_df = _signal_df()
    signal_df["target_weight"] = [0.10, 0.50]

    orders_df, _fills_df, new_state = _legacy_script_rebalance(
        signal_df=signal_df,
        state={"cash": 1_000_000.0, "positions": {}},
        bars_idx=_bars_idx_for_date("2026-03-21"),
        signal_date=pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-21"),
        top_n=2,
        total_target_pos=0.6,
        max_single_pos=0.6,
        lot_size=100,
        fee_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
        run_id="legacy_wrapper_target_weight",
    )

    buys = orders_df[orders_df["side"] == "BUY"].set_index("code")
    assert float(buys.loc["000001", "target_weight"]) == 0.10
    assert float(buys.loc["000002", "target_weight"]) == 0.50
    assert str(buys.loc["000001", "target_weight_source"]) == "external_target_weight"
    assert int(buys.loc["000002", "requested_qty"]) > 20_000
    assert int(buys.loc["000001", "requested_qty"]) < 12_000
    assert new_state["run_info"]["target_weight_sum"] == pytest.approx(0.60)


def test_rebalance_blocks_limit_up_entry(tmp_path):
    broker = PaperBroker(
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
    )
    state = {"cash": 1_000_000.0, "positions": {}}
    result = broker.rebalance_on_state(
        state=state,
        signal_df=_signal_df().head(1),
        bars_idx=_bars_idx_for_date("2026-03-21", locked_up=True),
        signal_date=pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-21"),
        run_id="t2",
        top_n=1,
        target_total_pos=0.6,
        max_single_pos=0.6,
    )
    orders_df, new_state = result.orders_df, result.state

    assert len(orders_df) == 1
    assert orders_df.iloc[0]["status"] == "blocked"
    assert orders_df.iloc[0]["reason"] == "entry_not_tradable"
    assert new_state["positions"] == {}


def test_rebalance_tracks_blocked_exit_state_and_freezes_new_buys(tmp_path):
    broker = PaperBroker(
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
        blocked_state_enabled=True,
        block_buy_on_exit_blocked=True,
        blocked_exit_freeze_min_weight=0.02,
    )
    signal_df = pd.DataFrame(
        {
            "代码": ["000002"],
            "名称": ["万科A"],
            "ML评分": [0.9],
            "排名_num": [1],
            "target_weight": [0.30],
        }
    )

    result = broker.rebalance_on_state(
        state={
            "cash": 900_000.0,
            "positions": {"000001": {"name": "平安银行", "qty": 10_000, "avg_cost": 10.0}},
        },
        signal_df=signal_df,
        bars_idx=_bars_idx_blocked_exit_and_buy("2026-03-30"),
        signal_date=pd.Timestamp("2026-03-27"),
        trade_date=pd.Timestamp("2026-03-30"),
        run_id="blocked_exit_state",
        top_n=1,
        target_total_pos=0.30,
        max_single_pos=0.30,
    )

    orders = result.orders_df.set_index(["side", "code"])
    assert orders.loc[("SELL", "000001"), "status"] == "blocked"
    assert orders.loc[("SELL", "000001"), "reason"] == "exit_not_tradable"
    assert orders.loc[("BUY", "000002"), "status"] == "blocked"
    assert orders.loc[("BUY", "000002"), "reason"] == "blocked_exit_freeze"
    assert int(result.ledger_row["blocked_exit_buy_freeze"]) == 1
    assert result.ledger_row["blocked_exit_freeze_reason"] == "same_day_exit_block"
    assert int(result.ledger_row["blocked_exit_freeze_orders"]) == 1
    assert float(result.ledger_row["blocked_sell_current_weight"]) > 0.02
    assert float(result.ledger_row["blocked_exit_freeze_sell_weight"]) > 0.02
    assert float(result.ledger_row["active_blocked_sell_state_count"]) == 0.0
    blocked_state = result.state["blocked_order_state"]
    assert "SELL:000001" in blocked_state
    assert "BUY:000002" in blocked_state
    assert int(blocked_state["SELL:000001"]["consecutive_days"]) == 1

    second = broker.rebalance_on_state(
        state=result.state,
        signal_df=signal_df,
        bars_idx=_bars_idx_blocked_exit_and_buy("2026-04-07"),
        signal_date=pd.Timestamp("2026-04-03"),
        trade_date=pd.Timestamp("2026-04-07"),
        run_id="blocked_exit_state_after_gap",
        top_n=1,
        target_total_pos=0.30,
        max_single_pos=0.30,
    )
    second_state = second.state["blocked_order_state"]
    assert second.ledger_row["blocked_exit_freeze_reason"] == "same_day_exit_block+active_blocked_sell_state"
    assert float(second.ledger_row["active_blocked_sell_state_count"]) == 1.0
    assert float(second.ledger_row["active_blocked_sell_state_weight"]) > 0.02
    assert int(second_state["SELL:000001"]["total_blocked_days"]) == 2
    assert int(second_state["SELL:000001"]["consecutive_days"]) == 1


def test_blocked_sell_order_preserves_entry_tradability_lineage(tmp_path):
    broker = PaperBroker(
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=0.0,
        slippage_bps=0.0,
        stamp_tax_bps=0.0,
        blocked_state_enabled=True,
        block_buy_on_exit_blocked=False,
    )
    buy_signal = pd.DataFrame(
        {
            "代码": ["000001"],
            "名称": ["平安银行"],
            "ML评分": [0.9],
            "排名_num": [1],
            "target_weight": [0.30],
            "tradability_safe_score": [0.25],
            "tradability_entry_risk_score": [0.75],
            "tradability_limit_headroom_pct": [0.80],
            "exit_trap_safe_score": [0.20],
            "exit_trap_risk_score": [0.80],
            "exit_trap_downside_headroom_pct": [0.60],
            "reserve_candidate": [1],
        }
    )

    first = broker.rebalance_on_state(
        state={"cash": 1_000_000.0, "positions": {}},
        signal_df=buy_signal,
        bars_idx=_bars_idx_for_date("2026-03-27"),
        signal_date=pd.Timestamp("2026-03-26"),
        trade_date=pd.Timestamp("2026-03-27"),
        run_id="entry_lineage_buy",
        top_n=1,
        target_total_pos=0.30,
        max_single_pos=0.30,
    )
    assert float(first.state["positions"]["000001"]["entry_tradability_safe_score"]) == 0.25

    second = broker.rebalance_on_state(
        state=first.state,
        signal_df=pd.DataFrame(columns=["代码", "名称", "ML评分", "排名_num", "target_weight"]),
        bars_idx=_bars_idx_blocked_exit_and_buy("2026-03-30"),
        signal_date=pd.Timestamp("2026-03-27"),
        trade_date=pd.Timestamp("2026-03-30"),
        run_id="entry_lineage_blocked_sell",
        top_n=1,
        target_total_pos=0.0,
        max_single_pos=0.30,
    )

    sell = second.orders_df[second.orders_df["side"].eq("SELL")].iloc[0]
    assert sell["status"] == "blocked"
    assert sell["reason"] == "exit_not_tradable"
    assert float(sell["position_entry_tradability_safe_score"]) == 0.25
    assert float(sell["position_entry_risk_score"]) == 0.75
    assert float(sell["position_entry_exit_trap_risk_score"]) == 0.80
    assert int(sell["position_entry_reserve_candidate"]) == 1
    assert float(second.ledger_row["blocked_sell_entry_risk_score_weighted_mean"]) == 0.75
    assert float(second.ledger_row["blocked_sell_entry_exit_trap_risk_score_weighted_mean"]) == 0.80
    assert int(second.ledger_row["blocked_sell_high_entry_risk_orders"]) == 1
    assert int(second.ledger_row["blocked_sell_high_entry_exit_trap_risk_orders"]) == 1
    assert int(second.ledger_row["blocked_sell_low_entry_safety_orders"]) == 1
    assert int(second.ledger_row["blocked_sell_reserve_entry_orders"]) == 1


def test_paper_broker_requires_explicit_reset_when_state_is_corrupt(tmp_path):
    state_file = tmp_path / "paper_state.json"
    state_file.write_text("not-json", encoding="utf-8")
    broker = PaperBroker(
        state_file=state_file,
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
    )

    with pytest.raises(PaperBrokerStateError):
        broker.rebalance(
            signal_df=_signal_df(),
            signal_date=pd.Timestamp("2026-03-20"),
            trade_date=pd.Timestamp("2026-03-21"),
            bars_idx=_bars_idx_for_date("2026-03-21"),
            run_id="corrupt_state_requires_reset",
            top_n=2,
            target_total_pos=0.6,
            max_single_pos=0.35,
            reset_state=False,
            dry_run=True,
        )

    result = broker.rebalance(
        signal_df=_signal_df(),
        signal_date=pd.Timestamp("2026-03-20"),
        trade_date=pd.Timestamp("2026-03-21"),
        bars_idx=_bars_idx_for_date("2026-03-21"),
        run_id="corrupt_state_with_reset",
        top_n=2,
        target_total_pos=0.6,
        max_single_pos=0.35,
        reset_state=True,
        dry_run=True,
    )
    assert not result.orders_df.empty
