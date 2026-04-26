"""纸面执行通道实现（A 股约束 + 成本模型）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from core.execution.adapter import BrokerAdapter, RebalanceResult
from utils.code_utils import limit_ratio_for_stock, normalize_ts_code
from utils.portfolio_weights import build_score_weights


class PaperBrokerStateError(RuntimeError):
    """纸面账户状态文件损坏或不可恢复。"""


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _get_bar_row(bars_idx: pd.DataFrame, trade_date: pd.Timestamp, code: str) -> pd.Series | None:
    try:
        row = bars_idx.loc[(trade_date, code)]
    except KeyError:
        return None
    if isinstance(row, pd.DataFrame):
        if row.empty:
            return None
        return row.iloc[-1]
    return row


def _is_suspended(row: pd.Series | None) -> bool:
    if row is None:
        return True
    op = _safe_float(row.get("open", np.nan), np.nan)
    vol = _safe_float(row.get("vol", np.nan), np.nan)
    amt = _safe_float(row.get("amount", np.nan), np.nan)
    return (not np.isfinite(op)) or op <= 0 or (not np.isfinite(vol)) or vol <= 0 or (not np.isfinite(amt)) or amt <= 0


def _is_locked_limit_up(row: pd.Series | None, limit_ratio: float) -> bool:
    if row is None:
        return False
    prev_close = _safe_float(row.get("prev_close", np.nan), np.nan)
    op = _safe_float(row.get("open", np.nan), np.nan)
    hi = _safe_float(row.get("high", np.nan), np.nan)
    lo = _safe_float(row.get("low", np.nan), np.nan)
    if (not np.isfinite(prev_close)) or prev_close <= 0:
        return False
    limit_up = prev_close * (1.0 + abs(limit_ratio))
    return (op >= limit_up * 0.999) and (hi >= limit_up * 0.999) and (lo >= limit_up * 0.999)


def _is_locked_limit_down(row: pd.Series | None, limit_ratio: float) -> bool:
    if row is None:
        return False
    prev_close = _safe_float(row.get("prev_close", np.nan), np.nan)
    op = _safe_float(row.get("open", np.nan), np.nan)
    hi = _safe_float(row.get("high", np.nan), np.nan)
    lo = _safe_float(row.get("low", np.nan), np.nan)
    if (not np.isfinite(prev_close)) or prev_close <= 0:
        return False
    limit_down = prev_close * (1.0 - abs(limit_ratio))
    return (op <= limit_down * 1.001) and (hi <= limit_down * 1.001) and (lo <= limit_down * 1.001)


def _can_enter(row: pd.Series | None, code: str, name: str) -> bool:
    if _is_suspended(row):
        return False
    ratio = limit_ratio_for_stock(code, name)
    return not _is_locked_limit_up(row, ratio)


def _can_exit(row: pd.Series | None, code: str, name: str) -> bool:
    if _is_suspended(row):
        return False
    ratio = limit_ratio_for_stock(code, name)
    return not _is_locked_limit_down(row, ratio)


def _mark_to_market(positions: dict[str, dict[str, object]], bars_idx: pd.DataFrame, trade_date: pd.Timestamp) -> tuple[float, dict[str, float]]:
    market_value = 0.0
    px_map: dict[str, float] = {}
    for code, pos in positions.items():
        qty = int(pos.get("qty", 0))
        if qty <= 0:
            continue
        bar = _get_bar_row(bars_idx, trade_date, code)
        if bar is None:
            px = _safe_float(pos.get("avg_cost", 0.0), 0.0)
        else:
            px = _safe_float(bar.get("open", np.nan), np.nan)
            if not np.isfinite(px) or px <= 0:
                px = _safe_float(pos.get("avg_cost", 0.0), 0.0)
        px_map[code] = float(px)
        market_value += float(qty * px)
    return market_value, px_map


class PaperBroker(BrokerAdapter):
    name = "paper"

    def __init__(
        self,
        *,
        state_file: str | Path,
        initial_capital: float,
        lot_size: int,
        fee_bps: float,
        slippage_bps: float,
        stamp_tax_bps: float,
    ) -> None:
        self.state_file = Path(state_file)
        self.initial_capital = max(100000.0, float(initial_capital))
        self.lot_size = max(1, int(lot_size))
        self.fee_bps = max(0.0, float(fee_bps))
        self.slippage_bps = max(0.0, float(slippage_bps))
        self.stamp_tax_bps = max(0.0, float(stamp_tax_bps))

    def _initial_state(self) -> dict[str, object]:
        return {
            "version": 1,
            "cash": float(self.initial_capital),
            "positions": {},
            "nav": float(self.initial_capital),
            "last_trade_date": "",
            "last_signal_date": "",
        }

    def _quarantine_bad_state_file(self) -> Path | None:
        if not self.state_file.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bad_path = self.state_file.with_name(f"{self.state_file.stem}.corrupt_{stamp}{self.state_file.suffix}")
        try:
            self.state_file.replace(bad_path)
            return bad_path
        except Exception:
            return None

    def _load_state(self, reset_state: bool) -> dict[str, object]:
        if reset_state or not self.state_file.exists():
            return self._initial_state()
        try:
            st = json.loads(self.state_file.read_text(encoding="utf-8"))
            if not isinstance(st, dict):
                raise ValueError("bad state format")
            st.setdefault("positions", {})
            st.setdefault("cash", float(self.initial_capital))
            return st
        except Exception as exc:
            bad_path = self._quarantine_bad_state_file()
            loc = str(bad_path) if bad_path is not None else str(self.state_file)
            raise PaperBrokerStateError(
                f"paper state file is corrupted or unreadable: {self.state_file}. "
                f"moved_to={loc}. Use reset_state=True to rebuild account state explicitly."
            ) from exc

    def _save_state(self, state: dict[str, object], dry_run: bool) -> None:
        if dry_run:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def rebalance_on_state(
        self,
        *,
        state: dict[str, object],
        signal_df: pd.DataFrame,
        signal_date: pd.Timestamp,
        trade_date: pd.Timestamp,
        bars_idx: pd.DataFrame,
        run_id: str,
        top_n: int,
        target_total_pos: float,
        max_single_pos: float,
    ) -> RebalanceResult:
        positions_raw = state.get("positions", {})
        positions = {normalize_ts_code(k): dict(v) for k, v in positions_raw.items() if normalize_ts_code(k)}
        cash = _safe_float(state.get("cash", 0.0), 0.0)

        market_value_pre, _ = _mark_to_market(positions, bars_idx, trade_date)
        nav_pre = cash + market_value_pre

        picks = signal_df.head(max(1, top_n)).copy()
        target_total_pos = min(max(float(target_total_pos), 0.0), 1.0)
        max_single_pos = min(max(float(max_single_pos), 0.0), 1.0)
        external_weight = (
            pd.to_numeric(picks["target_weight"], errors="coerce").fillna(0.0).clip(lower=0.0).to_numpy(dtype=float)
            if "target_weight" in picks.columns
            else np.array([], dtype=float)
        )
        if len(external_weight) == len(picks) and float(np.sum(external_weight)) > 0:
            w = external_weight
            if float(np.sum(w)) > target_total_pos + 1e-12 and target_total_pos > 0:
                w = w * (target_total_pos / float(np.sum(w)))
            w = np.minimum(w, max_single_pos)
        else:
            score = pd.to_numeric(picks["ML评分"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
            w = build_score_weights(score, total_target=target_total_pos, single_cap=max_single_pos)
            if len(w) != len(picks):
                w = np.zeros(len(picks), dtype=float)
        picks["target_weight"] = w
        if "target_weight_raw" not in picks.columns:
            picks["target_weight_raw"] = picks["target_weight"]
        if "impact_cost_bps" not in picks.columns:
            picks["impact_cost_bps"] = 0.0
        if "participation_pct" not in picks.columns:
            picks["participation_pct"] = 0.0
        if "unfilled_target_weight" not in picks.columns:
            picks["unfilled_target_weight"] = 0.0
        if "industry_weight_post" not in picks.columns:
            picks["industry_weight_post"] = 0.0

        target_qty_map: dict[str, int] = {}
        target_weight_map: dict[str, float] = {}
        target_weight_raw_map: dict[str, float] = {}
        impact_bps_map: dict[str, float] = {}
        participation_map: dict[str, float] = {}
        unfilled_weight_map: dict[str, float] = {}
        industry_weight_map: dict[str, float] = {}
        name_map: dict[str, str] = {}
        rank_map: dict[str, int] = {}
        for _, row in picks.iterrows():
            code = normalize_ts_code(row.get("代码", ""))
            if not code:
                continue
            name = str(row.get("名称", "") or code)
            rank = int(_safe_float(row.get("排名_num", 9999), 9999))
            tgt_w = _safe_float(row.get("target_weight", 0.0), 0.0)
            bar = _get_bar_row(bars_idx, trade_date, code)
            open_px = _safe_float(bar.get("open", np.nan), np.nan) if bar is not None else np.nan
            qty = 0
            if np.isfinite(open_px) and open_px > 0 and tgt_w > 0:
                tgt_value = nav_pre * tgt_w
                qty = int(np.floor(tgt_value / open_px / self.lot_size) * self.lot_size)
            target_qty_map[code] = max(0, qty)
            target_weight_map[code] = float(tgt_w)
            target_weight_raw_map[code] = _safe_float(row.get("target_weight_raw", tgt_w), tgt_w)
            impact_bps_map[code] = max(0.0, _safe_float(row.get("impact_cost_bps", 0.0), 0.0))
            participation_map[code] = max(0.0, _safe_float(row.get("participation_pct", 0.0), 0.0))
            unfilled_weight_map[code] = max(0.0, _safe_float(row.get("unfilled_target_weight", 0.0), 0.0))
            industry_weight_map[code] = max(0.0, _safe_float(row.get("industry_weight_post", 0.0), 0.0))
            name_map[code] = name
            rank_map[code] = rank

        current_qty_map = {code: int(v.get("qty", 0)) for code, v in positions.items()}
        all_codes = sorted(set(current_qty_map.keys()) | set(target_qty_map.keys()))

        order_rows: list[dict[str, object]] = []
        fill_rows: list[dict[str, object]] = []

        # 先卖后买
        for code in all_codes:
            cur = int(current_qty_map.get(code, 0))
            tgt = int(target_qty_map.get(code, 0))
            if cur <= tgt:
                continue
            qty_req = cur - tgt
            name = name_map.get(code, str(positions.get(code, {}).get("name", code)))
            bar = _get_bar_row(bars_idx, trade_date, code)
            if not _can_exit(bar, code, name):
                order_rows.append(
                    {
                        "run_id": run_id,
                        "signal_date": signal_date.strftime("%Y-%m-%d"),
                        "trade_date": trade_date.strftime("%Y-%m-%d"),
                        "code": code,
                        "name": name,
                        "side": "SELL",
                        "rank": int(rank_map.get(code, 9999)),
                        "current_qty": cur,
                        "target_qty": tgt,
                        "requested_qty": qty_req,
                        "filled_qty": 0,
                        "status": "blocked",
                        "reason": "exit_not_tradable",
                        "open_price": _safe_float(bar.get("open", np.nan), np.nan) if bar is not None else np.nan,
                        "target_weight": float(target_weight_map.get(code, 0.0)),
                        "target_weight_raw": float(target_weight_raw_map.get(code, 0.0)),
                        "participation_pct": float(participation_map.get(code, 0.0)),
                        "impact_cost_bps": float(impact_bps_map.get(code, 0.0)),
                        "unfilled_target_weight": float(unfilled_weight_map.get(code, 0.0)),
                        "industry_weight_post": float(industry_weight_map.get(code, 0.0)),
                    }
                )
                continue

            open_px = _safe_float(bar.get("open", np.nan), np.nan)
            impact_bps = float(impact_bps_map.get(code, 0.0))
            fill_px = open_px * (1.0 - (self.slippage_bps + impact_bps) / 10000.0)
            gross = qty_req * fill_px
            fee = gross * self.fee_bps / 10000.0
            stamp = gross * self.stamp_tax_bps / 10000.0
            net = gross - fee - stamp
            cash += net

            new_qty = cur - qty_req
            if new_qty <= 0:
                positions.pop(code, None)
            else:
                positions[code]["qty"] = int(new_qty)
            order_rows.append(
                {
                    "run_id": run_id,
                    "signal_date": signal_date.strftime("%Y-%m-%d"),
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "code": code,
                    "name": name,
                    "side": "SELL",
                    "rank": int(rank_map.get(code, 9999)),
                    "current_qty": cur,
                    "target_qty": tgt,
                    "requested_qty": qty_req,
                    "filled_qty": qty_req,
                    "status": "filled",
                    "reason": "ok",
                    "open_price": open_px,
                    "target_weight": float(target_weight_map.get(code, 0.0)),
                    "target_weight_raw": float(target_weight_raw_map.get(code, 0.0)),
                    "participation_pct": float(participation_map.get(code, 0.0)),
                    "impact_cost_bps": float(impact_bps),
                    "unfilled_target_weight": float(unfilled_weight_map.get(code, 0.0)),
                    "industry_weight_post": float(industry_weight_map.get(code, 0.0)),
                }
            )
            fill_rows.append(
                {
                    "run_id": run_id,
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "code": code,
                    "name": name,
                    "side": "SELL",
                    "qty": qty_req,
                    "price": fill_px,
                    "gross_amount": gross,
                    "fee": fee,
                    "stamp_tax": stamp,
                    "impact_cost_bps": float(impact_bps),
                    "net_amount": net,
                }
            )

        for code in sorted(all_codes, key=lambda x: rank_map.get(x, 9999)):
            cur = int(positions.get(code, {}).get("qty", 0))
            tgt = int(target_qty_map.get(code, 0))
            if tgt <= cur:
                continue
            qty_req = tgt - cur
            name = name_map.get(code, str(positions.get(code, {}).get("name", code)))
            bar = _get_bar_row(bars_idx, trade_date, code)
            if not _can_enter(bar, code, name):
                order_rows.append(
                    {
                        "run_id": run_id,
                        "signal_date": signal_date.strftime("%Y-%m-%d"),
                        "trade_date": trade_date.strftime("%Y-%m-%d"),
                        "code": code,
                        "name": name,
                        "side": "BUY",
                        "rank": int(rank_map.get(code, 9999)),
                        "current_qty": cur,
                        "target_qty": tgt,
                        "requested_qty": qty_req,
                        "filled_qty": 0,
                        "status": "blocked",
                        "reason": "entry_not_tradable",
                        "open_price": _safe_float(bar.get("open", np.nan), np.nan) if bar is not None else np.nan,
                        "target_weight": float(target_weight_map.get(code, 0.0)),
                        "target_weight_raw": float(target_weight_raw_map.get(code, 0.0)),
                        "participation_pct": float(participation_map.get(code, 0.0)),
                        "impact_cost_bps": float(impact_bps_map.get(code, 0.0)),
                        "unfilled_target_weight": float(unfilled_weight_map.get(code, 0.0)),
                        "industry_weight_post": float(industry_weight_map.get(code, 0.0)),
                    }
                )
                continue

            open_px = _safe_float(bar.get("open", np.nan), np.nan)
            impact_bps = float(impact_bps_map.get(code, 0.0))
            fill_px = open_px * (1.0 + (self.slippage_bps + impact_bps) / 10000.0)
            fee_rate = self.fee_bps / 10000.0
            unit_cost = fill_px * (1.0 + fee_rate)
            affordable = int(np.floor(cash / max(unit_cost, 1e-9) / self.lot_size) * self.lot_size)
            qty_fill = min(qty_req, max(0, affordable))
            if qty_fill <= 0:
                order_rows.append(
                    {
                        "run_id": run_id,
                        "signal_date": signal_date.strftime("%Y-%m-%d"),
                        "trade_date": trade_date.strftime("%Y-%m-%d"),
                        "code": code,
                        "name": name,
                        "side": "BUY",
                        "rank": int(rank_map.get(code, 9999)),
                        "current_qty": cur,
                        "target_qty": tgt,
                        "requested_qty": qty_req,
                        "filled_qty": 0,
                        "status": "rejected",
                        "reason": "insufficient_cash",
                        "open_price": open_px,
                        "target_weight": float(target_weight_map.get(code, 0.0)),
                        "target_weight_raw": float(target_weight_raw_map.get(code, 0.0)),
                        "participation_pct": float(participation_map.get(code, 0.0)),
                        "impact_cost_bps": float(impact_bps),
                        "unfilled_target_weight": float(unfilled_weight_map.get(code, 0.0)),
                        "industry_weight_post": float(industry_weight_map.get(code, 0.0)),
                    }
                )
                continue

            gross = qty_fill * fill_px
            fee = gross * fee_rate
            cash -= (gross + fee)
            prev_qty = int(positions.get(code, {}).get("qty", 0))
            prev_cost = _safe_float(positions.get(code, {}).get("avg_cost", 0.0), 0.0)
            new_qty = prev_qty + qty_fill
            new_cost = (prev_qty * prev_cost + qty_fill * fill_px) / max(new_qty, 1)
            positions[code] = {
                "name": name,
                "qty": int(new_qty),
                "avg_cost": float(new_cost),
                "last_trade_date": trade_date.strftime("%Y-%m-%d"),
            }

            status = "filled" if qty_fill == qty_req else "partial"
            reason = "ok" if status == "filled" else "cash_limited"
            order_rows.append(
                {
                    "run_id": run_id,
                    "signal_date": signal_date.strftime("%Y-%m-%d"),
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "code": code,
                    "name": name,
                    "side": "BUY",
                    "rank": int(rank_map.get(code, 9999)),
                    "current_qty": cur,
                    "target_qty": tgt,
                    "requested_qty": qty_req,
                    "filled_qty": qty_fill,
                    "status": status,
                    "reason": reason,
                    "open_price": open_px,
                    "target_weight": float(target_weight_map.get(code, 0.0)),
                    "target_weight_raw": float(target_weight_raw_map.get(code, 0.0)),
                    "participation_pct": float(participation_map.get(code, 0.0)),
                    "impact_cost_bps": float(impact_bps),
                    "unfilled_target_weight": float(unfilled_weight_map.get(code, 0.0)),
                    "industry_weight_post": float(industry_weight_map.get(code, 0.0)),
                }
            )
            fill_rows.append(
                {
                    "run_id": run_id,
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                    "code": code,
                    "name": name,
                    "side": "BUY",
                    "qty": qty_fill,
                    "price": fill_px,
                    "gross_amount": gross,
                    "fee": fee,
                    "stamp_tax": 0.0,
                    "impact_cost_bps": float(impact_bps),
                    "net_amount": -(gross + fee),
                }
            )

        market_value_post, _ = _mark_to_market(positions, bars_idx, trade_date)
        nav_post = cash + market_value_post
        turnover = float(np.sum(np.abs([_safe_float(x.get("net_amount", 0.0), 0.0) for x in fill_rows])))

        orders_df = pd.DataFrame(order_rows)
        fills_df = pd.DataFrame(fill_rows)
        new_state = {
            "version": 1,
            "cash": float(cash),
            "positions": positions,
            "nav": float(nav_post),
            "nav_pre": float(nav_pre),
            "last_trade_date": trade_date.strftime("%Y-%m-%d"),
            "last_signal_date": signal_date.strftime("%Y-%m-%d"),
        }
        ledger_row = {
            "run_id": run_id,
            "signal_date": signal_date.strftime("%Y-%m-%d"),
            "trade_date": trade_date.strftime("%Y-%m-%d"),
            "nav_pre": float(nav_pre),
            "nav_post": float(nav_post),
            "cash_post": float(cash),
            "market_value_post": float(market_value_post),
            "position_count_post": int(sum(1 for v in positions.values() if int(v.get("qty", 0)) > 0)),
            "filled_orders": int((orders_df["status"] == "filled").sum()) if not orders_df.empty else 0,
            "partial_orders": int((orders_df["status"] == "partial").sum()) if not orders_df.empty else 0,
            "blocked_orders": int((orders_df["status"] == "blocked").sum()) if not orders_df.empty else 0,
            "rejected_orders": int((orders_df["status"] == "rejected").sum()) if not orders_df.empty else 0,
            "turnover": turnover,
            "target_weight_sum": float(np.sum(list(target_weight_map.values()))) if target_weight_map else 0.0,
            "unfilled_target_weight": float(np.sum(list(unfilled_weight_map.values()))) if unfilled_weight_map else 0.0,
            "impact_cost_bps_mean": float(np.mean(list(impact_bps_map.values()))) if impact_bps_map else 0.0,
            "max_participation_pct": float(np.max(list(participation_map.values()))) if participation_map else 0.0,
        }
        return RebalanceResult(
            orders_df=orders_df,
            fills_df=fills_df,
            state=new_state,
            ledger_row=ledger_row,
        )

    def rebalance(
        self,
        *,
        signal_df: pd.DataFrame,
        signal_date: pd.Timestamp,
        trade_date: pd.Timestamp,
        bars_idx: pd.DataFrame,
        run_id: str,
        top_n: int,
        target_total_pos: float,
        max_single_pos: float,
        reset_state: bool = False,
        dry_run: bool = False,
    ) -> RebalanceResult:
        state = self._load_state(reset_state=reset_state)
        result = self.rebalance_on_state(
            state=state,
            signal_df=signal_df,
            signal_date=signal_date,
            trade_date=trade_date,
            bars_idx=bars_idx,
            run_id=run_id,
            top_n=top_n,
            target_total_pos=target_total_pos,
            max_single_pos=max_single_pos,
        )
        self._save_state(result.state, dry_run=dry_run)
        return result
