# -*- coding: utf-8 -*-
"""P2 纸面 OMS 核心再平衡逻辑测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from core.execution import create_broker
from core.execution.paper_broker import PaperBroker, PaperBrokerStateError
from scripts.quant_p2_paper_trade import _rebalance as _legacy_script_rebalance


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
