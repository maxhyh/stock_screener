# -*- coding: utf-8 -*-
"""执行通道工厂与 live shadow 测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from core.execution import create_broker
from core.execution.live_broker import LiveBroker
from core.execution.paper_broker import PaperBroker, PaperBrokerStateError


def test_create_broker_supports_paper_and_live(tmp_path):
    paper = create_broker(
        "paper",
        state_file=tmp_path / "paper_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
    )
    live = create_broker(
        "live",
        state_file=tmp_path / "live_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
        live_mode="shadow",
    )
    assert isinstance(paper, PaperBroker)
    assert isinstance(live, LiveBroker)


def test_live_shadow_rebalance_runs(tmp_path):
    broker = create_broker(
        "live",
        state_file=tmp_path / "live_state.json",
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
        live_mode="shadow",
    )
    signal_df = pd.DataFrame(
        {
            "代码": ["000001", "000002"],
            "名称": ["A", "B"],
            "ML评分": [0.9, 0.8],
            "排名_num": [1, 2],
        }
    )
    bars_idx = (
        pd.DataFrame(
            {
                "trade_date": [pd.Timestamp("2026-04-09"), pd.Timestamp("2026-04-09")],
                "code": ["000001", "000002"],
                "open": [10.0, 20.0],
                "high": [10.2, 20.2],
                "low": [9.9, 19.8],
                "close": [10.1, 20.1],
                "vol": [1_000_000, 1_000_000],
                "amount": [100_000_000, 200_000_000],
                "prev_close": [9.9, 19.9],
            }
        )
        .set_index(["trade_date", "code"])
        .sort_index()
    )
    result = broker.rebalance(
        signal_df=signal_df,
        signal_date=pd.Timestamp("2026-04-08"),
        trade_date=pd.Timestamp("2026-04-09"),
        bars_idx=bars_idx,
        run_id="live_shadow_t1",
        top_n=2,
        target_total_pos=0.6,
        max_single_pos=0.35,
        reset_state=True,
        dry_run=True,
    )
    assert not result.orders_df.empty
    assert "channel_status" in result.orders_df.columns


def test_paper_broker_raises_on_corrupt_state_file(tmp_path):
    state_file = tmp_path / "paper_state.json"
    state_file.write_text("{bad json", encoding="utf-8")
    broker = create_broker(
        "paper",
        state_file=state_file,
        initial_capital=1_000_000,
        lot_size=100,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
    )

    with pytest.raises(PaperBrokerStateError):
        broker.rebalance(
            signal_df=pd.DataFrame(columns=["代码", "名称", "ML评分", "排名_num"]),
            signal_date=pd.Timestamp("2026-04-08"),
            trade_date=pd.Timestamp("2026-04-09"),
            bars_idx=pd.DataFrame().set_index(pd.MultiIndex.from_arrays([[], []], names=["trade_date", "code"])),
            run_id="corrupt_state",
            top_n=1,
            target_total_pos=0.6,
            max_single_pos=0.35,
            reset_state=False,
            dry_run=True,
        )

    quarantined = list(tmp_path.glob("paper_state.corrupt_*json"))
    assert quarantined
    assert not state_file.exists()
