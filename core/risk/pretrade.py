"""下单前组合风控硬门禁。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from core.data.market_data_gateway import AShareMarketDataGateway
from utils.code_utils import limit_ratio_for_stock, normalize_ts_code, normalize_ts_code_series
from utils.portfolio_weights import build_score_weights


@dataclass
class PreTradeRiskConfig:
    enabled: bool = True
    capital_base: float = 1_000_000.0
    max_industry_weight: float = 0.35
    max_adv_participation: float = 0.05
    min_price: float = 2.0
    blacklist_codes: set[str] | None = None
    # 风格暴露门禁（绝对值上限；<=0 视为关闭）
    max_style_size_exposure_abs: float = 0.0
    max_style_beta_exposure_abs: float = 0.0
    max_style_momentum_exposure_abs: float = 0.0
    max_style_vol_exposure_abs: float = 0.0
    style_exposure_basis: str = "invested_weighted"
    style_lb_short: int = 20
    style_lb_beta: int = 60
    max_names: int = 0
    block_entry_not_tradable: bool = False


UNKNOWN_INDUSTRY_LABEL = "未知"
UNKNOWN_INDUSTRY_BUCKET = "__unknown_industry__"


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        x = float(v)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _load_blacklist(blacklist_file: str | Path | None) -> set[str]:
    if not blacklist_file:
        return set()
    p = Path(blacklist_file)
    if not p.exists():
        return set()
    out: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.add(normalize_ts_code(s))
    return {x for x in out if x}


def _is_limit_enabled(limit: float) -> bool:
    x = _safe_float(limit, 0.0)
    return bool(np.isfinite(x) and x > 0)


def _clip_limit(limit: float) -> float:
    x = _safe_float(limit, 0.0)
    if np.isfinite(x) and x > 0:
        return float(x)
    return float("inf")


def _is_locked_limit_up(row: pd.Series | None, code: str, name: str) -> bool:
    if row is None:
        return False
    prev_close = _safe_float(row.get("prev_close", np.nan), np.nan)
    op = _safe_float(row.get("open", np.nan), np.nan)
    hi = _safe_float(row.get("high", np.nan), np.nan)
    lo = _safe_float(row.get("low", np.nan), np.nan)
    if (not np.isfinite(prev_close)) or prev_close <= 0:
        return False
    ratio = limit_ratio_for_stock(code, name)
    limit_up = prev_close * (1.0 + abs(float(ratio)))
    return (op >= limit_up * 0.999) and (hi >= limit_up * 0.999) and (lo >= limit_up * 0.999)


def _zscore_map(raw_map: dict[str, float]) -> dict[str, float]:
    if not raw_map:
        return {}
    s = pd.Series(raw_map, dtype=float)
    finite = s[np.isfinite(s)]
    if finite.empty:
        return {str(k): 0.0 for k in raw_map.keys()}
    std = float(finite.std(ddof=0))
    if std <= 1e-12:
        z = finite * 0.0
    else:
        z = (finite - float(finite.mean())) / std
    out = {str(k): float(z.get(k, 0.0)) for k in raw_map.keys()}
    return out


def _resolve_asof_date(dates: pd.Index, trade_date: pd.Timestamp) -> pd.Timestamp:
    if len(dates) == 0:
        return pd.Timestamp(trade_date).normalize()
    d = pd.to_datetime(dates).sort_values()
    t = pd.Timestamp(trade_date).normalize()
    pos = int(d.searchsorted(t, side="left"))
    if pos < len(d) and d[pos] == t:
        return d[max(0, pos - 1)]
    if pos <= 0:
        return d[0]
    return d[min(len(d) - 1, pos - 1)]


def _compute_style_factor_zscores(
    *,
    bars_idx: pd.DataFrame,
    trade_date: pd.Timestamp,
    codes: list[str],
    lb_short: int,
    lb_beta: int,
) -> dict[str, dict[str, float]]:
    """
    计算候选池风格因子 z-score（基于 trade_date 的前一交易日 as-of）：
    - size_z: log(amount)
    - momentum_z: 近 lb_short 日动量
    - vol_z: 近 lb_short 日日收益波动
    - beta_z: 对全市场等权收益近 lb_beta 日 beta
    """
    out: dict[str, dict[str, float]] = {}
    codes = [normalize_ts_code(x) for x in codes]
    codes = [c for c in codes if c]
    if not codes:
        return out
    if bars_idx is None or bars_idx.empty:
        return {c: {"size_z": 0.0, "momentum_z": 0.0, "vol_z": 0.0, "beta_z": 0.0} for c in codes}
    if "close" not in bars_idx.columns:
        return {c: {"size_z": 0.0, "momentum_z": 0.0, "vol_z": 0.0, "beta_z": 0.0} for c in codes}

    idx_dates = bars_idx.index.get_level_values(0).unique()
    if len(idx_dates) == 0:
        return {c: {"size_z": 0.0, "momentum_z": 0.0, "vol_z": 0.0, "beta_z": 0.0} for c in codes}
    all_dates = pd.to_datetime(idx_dates).sort_values()
    asof_date = _resolve_asof_date(all_dates, trade_date)

    max_lb = max(5, int(max(lb_short, lb_beta)))
    asof_pos = int(all_dates.searchsorted(asof_date, side="left"))
    if asof_pos >= len(all_dates) or all_dates[asof_pos] != asof_date:
        asof_pos = max(0, min(len(all_dates) - 1, asof_pos - 1))
        asof_date = all_dates[asof_pos]
    start_pos = max(0, asof_pos - (max_lb + 3))
    start_date = all_dates[start_pos]

    cols = ["close"]
    if "amount" in bars_idx.columns:
        cols.append("amount")
    try:
        win = bars_idx.loc[(slice(start_date, asof_date), slice(None)), cols].reset_index()
    except Exception:
        return {c: {"size_z": 0.0, "momentum_z": 0.0, "vol_z": 0.0, "beta_z": 0.0} for c in codes}
    if win.empty:
        return {c: {"size_z": 0.0, "momentum_z": 0.0, "vol_z": 0.0, "beta_z": 0.0} for c in codes}

    win["trade_date"] = pd.to_datetime(win["trade_date"], errors="coerce").dt.normalize()
    win["code"] = normalize_ts_code_series(win["code"])
    win["close"] = pd.to_numeric(win["close"], errors="coerce")
    if "amount" in win.columns:
        win["amount"] = pd.to_numeric(win["amount"], errors="coerce")
    else:
        win["amount"] = np.nan
    win = win.dropna(subset=["trade_date", "code", "close"])
    if win.empty:
        return {c: {"size_z": 0.0, "momentum_z": 0.0, "vol_z": 0.0, "beta_z": 0.0} for c in codes}

    close_px = win.pivot(index="trade_date", columns="code", values="close").sort_index()
    if close_px.empty:
        return {c: {"size_z": 0.0, "momentum_z": 0.0, "vol_z": 0.0, "beta_z": 0.0} for c in codes}
    if asof_date not in close_px.index:
        asof_date = close_px.index.max()
    returns = close_px.pct_change()
    market_ret = returns.mean(axis=1, skipna=True)

    asof_rows = win[win["trade_date"] == asof_date][["code", "amount"]].drop_duplicates(subset=["code"], keep="last")
    amount_map = dict(zip(asof_rows["code"], asof_rows["amount"]))

    size_raw: dict[str, float] = {}
    momentum_raw: dict[str, float] = {}
    vol_raw: dict[str, float] = {}
    beta_raw: dict[str, float] = {}

    for code in codes:
        if code not in close_px.columns:
            continue
        cl = close_px[code].loc[:asof_date].dropna()
        if len(cl) >= int(lb_short) + 1:
            momentum_raw[code] = float(cl.iloc[-1] / cl.iloc[-(int(lb_short) + 1)] - 1.0)
        r = returns[code].loc[:asof_date].dropna()
        if len(r) >= max(5, int(lb_short // 2)):
            vol_raw[code] = float(r.tail(int(lb_short)).std(ddof=0))
        m_aligned = market_ret.loc[r.index].dropna()
        if len(m_aligned) >= max(10, int(lb_beta // 3)):
            rr = r.loc[m_aligned.index].tail(int(lb_beta))
            mm = m_aligned.tail(int(lb_beta))
            if len(rr) >= 5 and float(mm.var(ddof=0)) > 1e-12:
                cov = float(np.cov(rr.to_numpy(dtype=float), mm.to_numpy(dtype=float), ddof=0)[0, 1])
                beta_raw[code] = cov / float(mm.var(ddof=0))
        amt = _safe_float(amount_map.get(code, np.nan), np.nan)
        if np.isfinite(amt) and amt > 0:
            size_raw[code] = float(np.log1p(amt))

    size_z = _zscore_map(size_raw)
    momentum_z = _zscore_map(momentum_raw)
    vol_z = _zscore_map(vol_raw)
    beta_z = _zscore_map(beta_raw)

    for code in codes:
        out[code] = {
            "size_z": float(size_z.get(code, 0.0)),
            "momentum_z": float(momentum_z.get(code, 0.0)),
            "vol_z": float(vol_z.get(code, 0.0)),
            "beta_z": float(beta_z.get(code, 0.0)),
        }
    return out


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


def load_industry_map(
    data_dir: str | Path | None = None,
    *,
    asof_date: object | None = None,
) -> dict[str, str]:
    """Read ODS instrument industries as of the signal date.

    ``data_dir`` is retained temporarily for call compatibility but is not read.
    """
    del data_dir
    gateway = AShareMarketDataGateway()
    if asof_date is None:
        sessions = gateway.available_trade_dates()
        if not sessions:
            return {}
        asof_date = sessions[-1]
    df = gateway.load_stock_info(asof_date, include_bj9=True)
    if df.empty:
        return {}
    code_col = "ts_code" if "ts_code" in df.columns else ("代码" if "代码" in df.columns else None)
    ind_col = "industry" if "industry" in df.columns else ("行业" if "行业" in df.columns else None)
    if not code_col or not ind_col:
        return {}
    work = df[[code_col, ind_col]].copy()
    work["code"] = normalize_ts_code_series(work[code_col])
    work = work[work["code"] != ""].copy()
    work["industry"] = work[ind_col].astype(str).fillna("").str.strip().replace({"nan": "", "None": ""})
    return dict(zip(work["code"], work["industry"]))


def apply_pretrade_risk_gates(
    *,
    signal_df: pd.DataFrame,
    bars_idx: pd.DataFrame,
    trade_date: pd.Timestamp,
    total_target_pos: float,
    max_single_pos: float,
    cfg: PreTradeRiskConfig,
    industry_map: dict[str, str] | None = None,
    current_positions: dict[str, dict[str, object]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """
    返回:
    1) 过滤后信号
    2) 被拦截明细
    3) 汇总指标
    """
    if signal_df.empty:
        return signal_df.copy(), pd.DataFrame(), {"enabled": cfg.enabled, "input_count": 0, "kept_count": 0, "blocked_count": 0}
    if not cfg.enabled:
        return signal_df.copy(), pd.DataFrame(), {"enabled": False, "input_count": int(len(signal_df)), "kept_count": int(len(signal_df)), "blocked_count": 0}

    work = signal_df.copy()
    work["代码"] = normalize_ts_code_series(work["代码"])
    work = work[work["代码"] != ""].copy()
    if work.empty:
        return work, pd.DataFrame(), {"enabled": True, "input_count": 0, "kept_count": 0, "blocked_count": 0}

    if "名称" not in work.columns:
        work["名称"] = work["代码"]
    if "ML评分" not in work.columns:
        work["ML评分"] = 0.0
    work["ML评分"] = pd.to_numeric(work["ML评分"], errors="coerce").fillna(0.0)
    has_external_weight = "target_weight" in work.columns
    if has_external_weight:
        work["target_weight"] = pd.to_numeric(work["target_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    if "排名_num" not in work.columns:
        if "排名" in work.columns:
            work["排名_num"] = pd.to_numeric(work["排名"], errors="coerce")
        else:
            work["排名_num"] = np.arange(1, len(work) + 1)
    work = work.sort_values(["排名_num", "ML评分"], ascending=[True, False]).reset_index(drop=True)

    blacklist = set(cfg.blacklist_codes or set())
    industry_map = industry_map or {}
    target_codes = set(work["代码"].astype(str).map(normalize_ts_code).tolist())
    current_industry_weight: dict[str, float] = {}
    current_position_weight_total = 0.0
    for raw_code, raw_pos in (current_positions or {}).items():
        code = normalize_ts_code(raw_code)
        if not code or code in target_codes:
            continue
        pos = dict(raw_pos or {})
        qty = int(_safe_float(pos.get("qty", 0), 0.0))
        if qty <= 0:
            continue
        bar = _get_bar_row(bars_idx, trade_date, code)
        px = _safe_float(bar.get("open", np.nan), np.nan) if bar is not None else np.nan
        if (not np.isfinite(px)) or px <= 0:
            px = _safe_float(pos.get("avg_cost", 0.0), 0.0)
        if px <= 0 or cfg.capital_base <= 0:
            continue
        wt = float(qty * px / max(float(cfg.capital_base), 1e-12))
        if wt <= 0:
            continue
        industry_raw = str(industry_map.get(code, "") or "").strip()
        industry_bucket = industry_raw if industry_raw else UNKNOWN_INDUSTRY_BUCKET
        current_industry_weight[industry_bucket] = float(current_industry_weight.get(industry_bucket, 0.0)) + wt
        current_position_weight_total += wt
    style_limits = {
        "size": _clip_limit(cfg.max_style_size_exposure_abs),
        "beta": _clip_limit(cfg.max_style_beta_exposure_abs),
        "momentum": _clip_limit(cfg.max_style_momentum_exposure_abs),
        "vol": _clip_limit(cfg.max_style_vol_exposure_abs),
    }
    style_enabled = any(np.isfinite(v) for v in style_limits.values())
    style_exposure_basis = str(getattr(cfg, "style_exposure_basis", "invested_weighted") or "invested_weighted").strip().lower()
    if style_exposure_basis not in {"invested_weighted", "nav_weighted"}:
        style_exposure_basis = "invested_weighted"
    style_map = (
        _compute_style_factor_zscores(
            bars_idx=bars_idx,
            trade_date=trade_date,
            codes=work["代码"].astype(str).tolist(),
            lb_short=max(5, int(cfg.style_lb_short)),
            lb_beta=max(10, int(cfg.style_lb_beta)),
        )
        if style_enabled
        else {}
    )

    blocked_map: dict[str, dict[str, object]] = {}
    remaining = work.copy()
    reweight_rounds = 0
    missing_industry_codes: set[str] = set()

    while not remaining.empty:
        if has_external_weight and "target_weight" in remaining.columns:
            weights = pd.to_numeric(remaining["target_weight"], errors="coerce").fillna(0.0).clip(lower=0.0).to_numpy(dtype=float)
        else:
            scores = remaining["ML评分"].to_numpy(dtype=float)
            primary_count = int(cfg.max_names) if int(cfg.max_names) > 0 else len(remaining)
            primary_count = max(0, min(primary_count, len(remaining)))
            weights = np.zeros(len(remaining), dtype=float)
            primary_weights = build_score_weights(
                scores[:primary_count],
                total_target=float(total_target_pos),
                single_cap=float(max_single_pos),
            )
            if len(primary_weights) == primary_count:
                weights[:primary_count] = primary_weights
        remaining = remaining.copy()
        remaining["risk_weight"] = weights

        kept = []
        round_blocked = []
        industry_used: dict[str, float] = dict(current_industry_weight)
        style_used_weight = 0.0
        style_used_sum = {"size": 0.0, "beta": 0.0, "momentum": 0.0, "vol": 0.0}

        for _, row in remaining.iterrows():
            code = normalize_ts_code(row.get("代码", ""))
            name = str(row.get("名称", "") or code)
            wt = _safe_float(row.get("risk_weight", 0.0), 0.0)
            industry_raw = str(industry_map.get(code, "") or "").strip()
            industry_missing = not bool(industry_raw)
            industry = industry_raw if industry_raw else UNKNOWN_INDUSTRY_LABEL
            industry_bucket = industry if not industry_missing else UNKNOWN_INDUSTRY_BUCKET
            if industry_missing:
                missing_industry_codes.add(code)
            style = style_map.get(code, {"size_z": 0.0, "beta_z": 0.0, "momentum_z": 0.0, "vol_z": 0.0})
            size_z = _safe_float(style.get("size_z", 0.0), 0.0)
            beta_z = _safe_float(style.get("beta_z", 0.0), 0.0)
            momentum_z = _safe_float(style.get("momentum_z", 0.0), 0.0)
            vol_z = _safe_float(style.get("vol_z", 0.0), 0.0)
            reasons: list[str] = []

            if code in blacklist:
                reasons.append("blacklist")

            bar = _get_bar_row(bars_idx, trade_date, code)
            if bar is None:
                reasons.append("missing_bar")
                open_px = np.nan
                amount = np.nan
            else:
                open_px = _safe_float(bar.get("open", np.nan), np.nan)
                amount = _safe_float(bar.get("amount", np.nan), np.nan)
                if (not np.isfinite(open_px)) or open_px <= 0:
                    reasons.append("invalid_open")
                if np.isfinite(open_px) and open_px < float(cfg.min_price):
                    reasons.append("min_price")
                if (not np.isfinite(amount)) or amount <= 0:
                    reasons.append("invalid_amount")
                if bool(cfg.block_entry_not_tradable) and _is_locked_limit_up(bar, code, name):
                    reasons.append("entry_not_tradable")

            if np.isfinite(amount) and amount > 0 and wt > 0 and cfg.capital_base > 0:
                participation = float(cfg.capital_base * wt / amount)
                if participation > float(cfg.max_adv_participation):
                    reasons.append("adv_participation")
            else:
                participation = np.nan

            # 每轮都基于“当前剩余可投篮子”的权重重算，
            # 避免前序标的被拦截后，幸存标的权重抬升但未重新过门禁。
            used = industry_used.get(industry_bucket, 0.0)
            if wt > 0:
                if used + wt > float(cfg.max_industry_weight) + 1e-9:
                    if float(current_industry_weight.get(industry_bucket, 0.0)) > 0:
                        reasons.append("post_trade_industry_clip")
                    else:
                        reasons.append("industry_weight_unknown" if industry_missing else "industry_weight")

            next_style_exp = {
                "size": 0.0,
                "beta": 0.0,
                "momentum": 0.0,
                "vol": 0.0,
            }
            if style_enabled and wt > 0:
                next_w = style_used_weight + wt
                factor_vals = {
                    "size": size_z,
                    "beta": beta_z,
                    "momentum": momentum_z,
                    "vol": vol_z,
                }
                for fac, val in factor_vals.items():
                    denom = 1.0 if style_exposure_basis == "nav_weighted" else max(next_w, 1e-12)
                    next_exp = (style_used_sum.get(fac, 0.0) + wt * val) / denom
                    next_style_exp[fac] = float(next_exp)
                    lim = float(style_limits.get(fac, np.inf))
                    if np.isfinite(lim) and abs(float(next_exp)) > lim + 1e-9:
                        reasons.append(f"style_{fac}_exposure")

            if reasons:
                round_blocked.append(
                    {
                        "code": code,
                        "name": name,
                        "industry": industry,
                        "industry_missing": int(industry_missing),
                        "rank": int(_safe_float(row.get("排名_num", 9999), 9999)),
                        "ml_score": _safe_float(row.get("ML评分", 0.0), 0.0),
                        "risk_weight": float(wt),
                        "target_weight": _safe_float(row.get("target_weight", wt), wt),
                        "reasons": ",".join(sorted(set(reasons))),
                        "open_price": float(open_px) if np.isfinite(open_px) else np.nan,
                        "amount": float(amount) if np.isfinite(amount) else np.nan,
                        "participation_pct": float(participation * 100.0) if np.isfinite(participation) else np.nan,
                        "post_trade_industry_base_weight": float(current_industry_weight.get(industry_bucket, 0.0)),
                        "style_size_z": float(size_z),
                        "style_beta_z": float(beta_z),
                        "style_momentum_z": float(momentum_z),
                        "style_vol_z": float(vol_z),
                        "style_size_exposure_next": float(next_style_exp["size"]),
                        "style_beta_exposure_next": float(next_style_exp["beta"]),
                        "style_momentum_exposure_next": float(next_style_exp["momentum"]),
                        "style_vol_exposure_next": float(next_style_exp["vol"]),
                        "style_exposure_basis": style_exposure_basis,
                    }
                )
                continue

            kept.append(row)
            if wt > 0:
                industry_used[industry_bucket] = industry_used.get(industry_bucket, 0.0) + wt
            if style_enabled and wt > 0:
                style_used_weight += wt
                style_used_sum["size"] += wt * size_z
                style_used_sum["beta"] += wt * beta_z
                style_used_sum["momentum"] += wt * momentum_z
                style_used_sum["vol"] += wt * vol_z

        for item in round_blocked:
            code = str(item["code"])
            existing = blocked_map.get(code)
            if existing is None:
                blocked_map[code] = item
                continue
            merged = sorted(set(str(existing.get("reasons", "")).split(",")) | set(str(item.get("reasons", "")).split(",")))
            existing["reasons"] = ",".join([x for x in merged if x])
            existing["risk_weight"] = max(_safe_float(existing.get("risk_weight", 0.0), 0.0), _safe_float(item.get("risk_weight", 0.0), 0.0))
            if not np.isfinite(_safe_float(existing.get("participation_pct", np.nan), np.nan)) and np.isfinite(_safe_float(item.get("participation_pct", np.nan), np.nan)):
                existing["participation_pct"] = item["participation_pct"]

        if not round_blocked:
            kept_df = pd.DataFrame(kept) if kept else pd.DataFrame(columns=remaining.columns)
            break

        reweight_rounds += 1
        if has_external_weight:
            kept_df = pd.DataFrame(kept) if kept else pd.DataFrame(columns=remaining.columns)
            break
        remaining = pd.DataFrame(kept) if kept else pd.DataFrame(columns=remaining.columns)
        remaining = remaining.drop(columns=["risk_weight"], errors="ignore")
    else:
        kept_df = pd.DataFrame(columns=work.columns)

    blocked = sorted(blocked_map.values(), key=lambda x: (int(_safe_float(x.get("rank", 9999), 9999)), str(x.get("code", ""))))
    blocked_df = pd.DataFrame(blocked)
    stats = {
        "enabled": True,
        "input_count": int(len(work)),
        "kept_count": int(len(kept_df)),
        "blocked_count": int(len(blocked_df)),
        "blocked_rate_pct": float(len(blocked_df) / max(len(work), 1) * 100.0),
        "reweight_rounds": int(reweight_rounds),
        "missing_industry_count": int(len(missing_industry_codes)),
        "industry_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("industry_weight")).sum()) if not blocked_df.empty else 0,
        "post_trade_industry_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("post_trade_industry_clip")).sum()) if not blocked_df.empty else 0,
        "unknown_industry_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("industry_weight_unknown")).sum()) if not blocked_df.empty else 0,
        "adv_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("adv_participation")).sum()) if not blocked_df.empty else 0,
        "post_trade_existing_weight": float(current_position_weight_total),
        "style_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("style_")).sum()) if not blocked_df.empty else 0,
        "style_size_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("style_size_exposure")).sum()) if not blocked_df.empty else 0,
        "style_beta_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("style_beta_exposure")).sum()) if not blocked_df.empty else 0,
        "style_momentum_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("style_momentum_exposure")).sum()) if not blocked_df.empty else 0,
        "style_vol_limits_hit": int((blocked_df["reasons"].astype(str).str.contains("style_vol_exposure")).sum()) if not blocked_df.empty else 0,
        "style_exposure_basis": style_exposure_basis,
        "entry_not_tradable_hit": int((blocked_df["reasons"].astype(str).str.contains("entry_not_tradable")).sum()) if not blocked_df.empty else 0,
        "max_names": int(cfg.max_names),
    }
    return kept_df.drop(columns=["risk_weight"], errors="ignore"), blocked_df, stats


__all__ = [
    "PreTradeRiskConfig",
    "apply_pretrade_risk_gates",
    "load_industry_map",
    "_load_blacklist",
]
