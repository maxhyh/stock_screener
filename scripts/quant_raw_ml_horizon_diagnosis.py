#!/usr/bin/env python3
"""Diagnose whether raw ML score failure is horizon mismatch or broad decay.

The input is a persisted research-stage snapshot that still contains the raw
full-universe score (`raw_scored_post_indicator`). The report evaluates the
same `ml_score` against multiple open-to-open horizons without changing any
profile or P2 artifact.
"""

from __future__ import annotations

import argparse
import glob
import json
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.data import AShareMarketDataGateway

BASE_DIR = Path(__file__).resolve().parents[1]
BACKTEST_DIR = BASE_DIR / "output" / "backtest"
MODEL_DIR = BASE_DIR / "models"
PROFILE_CONFIG = BASE_DIR / "config" / "quant_live_profiles.json"

DEFAULT_STAGE = "raw_scored_post_indicator"
DEFAULT_HORIZONS = [1, 3, 5, 8, 10, 15]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        x = float(value)
        if np.isfinite(x):
            return float(x)
    except Exception:
        pass
    return float(default)


def _safe_int(value: object, default: int = 0) -> int:
    return int(round(_safe_float(value, float(default))))


def _parse_list_int(raw: str | list[int] | tuple[int, ...] | None, default: list[int]) -> list[int]:
    if raw is None:
        return list(default)
    if isinstance(raw, str):
        vals = raw.split(",")
    else:
        vals = [str(x) for x in raw]
    out: list[int] = []
    for value in vals:
        try:
            x = int(str(value).strip())
        except Exception:
            continue
        if x > 0 and x not in out:
            out.append(x)
    return out or list(default)


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(value).lower()).strip("_")


def _parse_date(value: object) -> pd.Timestamp | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts).normalize()


def _discover_paths(raw_glob: str) -> list[Path]:
    paths: list[Path] = []
    for part in str(raw_glob or "").split(","):
        part = part.strip()
        if not part:
            continue
        paths.extend(Path(p).resolve() for p in glob.glob(str(part)))
    return sorted(set(paths))


def _normalize_code_series(raw: pd.Series) -> pd.Series:
    def one(value: object) -> str:
        s = str(value or "").strip()
        if not s or s.lower() == "nan":
            return ""
        if "." in s:
            code, suffix = s.split(".", 1)
            code = "".join(ch for ch in code if ch.isdigit()).zfill(6)
            suffix = suffix.upper()[:2]
            return f"{code}.{suffix}" if code else ""
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) < 6:
            return ""
        code = digits[-6:]
        suffix = "SH" if code.startswith(("6", "9")) else "SZ"
        return f"{code}.{suffix}"

    return raw.map(one)


def load_stage_scores(
    paths: list[Path],
    *,
    stage: str = DEFAULT_STAGE,
    score_col: str = "ml_score",
    start: str = "",
    end: str = "",
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    wanted = {
        "日期",
        "trade_date",
        "research_stage",
        "代码",
        "ts_code",
        "行业",
        "industry",
        score_col,
        "ML评分",
    }
    for path in paths:
        try:
            df = pd.read_csv(path, usecols=lambda c: c in wanted, low_memory=False)
        except Exception:
            continue
        if df.empty or "research_stage" not in df.columns:
            continue
        df = df[df["research_stage"].astype(str).eq(str(stage))].copy()
        if df.empty:
            continue
        if "日期" in df.columns:
            dates = pd.to_datetime(df["日期"], errors="coerce")
        elif "trade_date" in df.columns:
            dates = pd.to_datetime(df["trade_date"], errors="coerce")
        else:
            dates = pd.Series(pd.NaT, index=df.index)
        if dates.notna().any():
            df["signal_date"] = dates.dt.normalize()
        else:
            raw = path.stem.replace("research_stages_", "", 1)
            ts = pd.to_datetime(raw, errors="coerce")
            if pd.isna(ts):
                continue
            df["signal_date"] = pd.Timestamp(ts).normalize()
        code_col = "ts_code" if "ts_code" in df.columns else ("代码" if "代码" in df.columns else "")
        if not code_col:
            continue
        df["code"] = _normalize_code_series(df[code_col])
        if score_col not in df.columns and score_col == "ml_score" and "ML评分" in df.columns:
            df[score_col] = df["ML评分"]
        if score_col not in df.columns:
            continue
        df[score_col] = pd.to_numeric(df[score_col], errors="coerce")
        if "industry" not in df.columns:
            df["industry"] = df["行业"] if "行业" in df.columns else ""
        df["industry"] = df["industry"].fillna("未知").astype(str).replace({"": "未知"})
        df = df[df["code"].ne("") & df["signal_date"].notna() & df[score_col].notna()].copy()
        frames.append(df[["signal_date", "code", "industry", score_col]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if start:
        s = _parse_date(start)
        if s is not None:
            out = out[out["signal_date"].ge(s)].copy()
    if end:
        e = _parse_date(end)
        if e is not None:
            out = out[out["signal_date"].le(e)].copy()
    return out.drop_duplicates(subset=["signal_date", "code"], keep="last").reset_index(drop=True)


def load_market_opens(
    path: Path | None = None,
    *,
    start: object | None = None,
    end: object | None = None,
    forward_sessions: int = 0,
) -> pd.DataFrame:
    """Load explicit inspection bars or a bounded shared-ODS window."""
    if path is not None:
        df = pd.read_parquet(path, columns=["ts_code", "trade_date", "open"])
    else:
        if start is None or end is None:
            raise ValueError("start/end are required when reading market opens from shared ODS")
        df = AShareMarketDataGateway().load_bars(start, end, forward_sessions=max(0, int(forward_sessions)))
    df["code"] = _normalize_code_series(df["ts_code"])
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.normalize()
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df = df.dropna(subset=["trade_date", "code", "open"]).copy()
    return df[df["code"].ne("") & df["open"].gt(0.0)].sort_values(["code", "trade_date"]).reset_index(drop=True)


def attach_open_to_open_returns(raw: pd.DataFrame, bars: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    out = raw.copy()
    horizons = sorted(set(int(h) for h in horizons if int(h) > 0))
    for h in horizons:
        out[f"forward_return_h{h}"] = np.nan
    if out.empty or bars.empty:
        return out

    bar_map = {str(code): g.reset_index(drop=True) for code, g in bars.groupby("code", sort=False)}
    for code, idx in out.groupby("code").groups.items():
        g = bar_map.get(str(code))
        if g is None or g.empty:
            continue
        row_idx = np.array(list(idx))
        signals = pd.to_datetime(out.loc[row_idx, "signal_date"], errors="coerce").dt.normalize().to_numpy(dtype="datetime64[ns]")
        dates = g["trade_date"].to_numpy(dtype="datetime64[ns]")
        opens = pd.to_numeric(g["open"], errors="coerce").to_numpy(dtype=float)
        signal_pos = np.searchsorted(dates, signals, side="left")
        exact = (signal_pos < len(dates)) & (dates[np.minimum(signal_pos, len(dates) - 1)] == signals)
        fallback = np.searchsorted(dates, signals, side="right") - 1
        base_pos = np.where(exact, signal_pos, fallback)
        for h in horizons:
            entry = base_pos + 1
            exit_ = entry + int(h)
            ok = (base_pos >= 0) & (entry >= 0) & (exit_ < len(opens))
            vals = np.full(len(row_idx), np.nan, dtype=float)
            if ok.any():
                entry_open = opens[entry[ok]]
                exit_open = opens[exit_[ok]]
                valid = np.isfinite(entry_open) & np.isfinite(exit_open) & (entry_open > 0.0)
                tmp = np.full(int(ok.sum()), np.nan, dtype=float)
                tmp[valid] = exit_open[valid] / entry_open[valid] - 1.0
                vals[ok] = tmp
            out.loc[row_idx, f"forward_return_h{h}"] = vals
    return out


def _top_industry_label(df: pd.DataFrame) -> str:
    if df.empty or "industry" not in df.columns:
        return ""
    s = df["industry"].fillna("未知").astype(str).replace({"": "未知"})
    return str(s.value_counts().index[0]) if not s.empty else ""


def _top_industry_weight_pct(df: pd.DataFrame) -> float:
    if df.empty or "industry" not in df.columns:
        return 0.0
    s = df["industry"].fillna("未知").astype(str).replace({"": "未知"})
    return float(s.value_counts(normalize=True).iloc[0] * 100.0) if not s.empty else 0.0


def _daily_ic(g: pd.DataFrame, score_col: str, ret_col: str, direction: str) -> float | None:
    work = g[[score_col, ret_col]].copy()
    work[score_col] = pd.to_numeric(work[score_col], errors="coerce")
    work[ret_col] = pd.to_numeric(work[ret_col], errors="coerce")
    work = work.dropna()
    if len(work) < 10 or work[score_col].nunique(dropna=True) < 2 or work[ret_col].nunique(dropna=True) < 2:
        return None
    score = work[score_col] if direction == "desc" else -work[score_col]
    ic = score.rank().corr(work[ret_col].rank())
    return float(ic) if pd.notna(ic) and np.isfinite(ic) else None


def summarize_horizons(
    scored: pd.DataFrame,
    *,
    score_col: str = "ml_score",
    horizons: list[int] | None = None,
    top_n: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    horizons = sorted(set(horizons or DEFAULT_HORIZONS))
    summary_rows: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    for h in horizons:
        ret_col = f"forward_return_h{h}"
        if ret_col not in scored.columns:
            continue
        for direction in ["desc", "asc"]:
            work = scored.dropna(subset=[score_col, ret_col]).copy()
            if work.empty:
                continue
            work["_score_eff"] = pd.to_numeric(work[score_col], errors="coerce")
            if direction == "asc":
                work["_score_eff"] = -work["_score_eff"]
            work = work.dropna(subset=["_score_eff", ret_col])
            selected = (
                work.sort_values(["signal_date", "_score_eff"], ascending=[True, False])
                .groupby("signal_date", group_keys=False)
                .head(max(1, int(top_n)))
                .copy()
            )
            bottom = (
                work.sort_values(["signal_date", "_score_eff"], ascending=[True, True])
                .groupby("signal_date", group_keys=False)
                .head(max(1, int(top_n)))
                .copy()
            )
            ic_values: list[float] = []
            for date, g in work.groupby("signal_date", sort=True):
                ic = _daily_ic(g, score_col, ret_col, direction)
                if ic is not None:
                    ic_values.append(ic)
                day_top = selected[selected["signal_date"].eq(date)]
                day_bottom = bottom[bottom["signal_date"].eq(date)]
                daily_rows.append(
                    {
                        "signal_date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                        "horizon": int(h),
                        "score_direction": direction,
                        "rows": int(len(g)),
                        "rank_ic": float(ic) if ic is not None else np.nan,
                        "top_mean_return_pct": _safe_float(day_top[ret_col].mean() * 100.0, 0.0),
                        "bottom_mean_return_pct": _safe_float(day_bottom[ret_col].mean() * 100.0, 0.0),
                        "top_minus_bottom_pct": _safe_float((day_top[ret_col].mean() - day_bottom[ret_col].mean()) * 100.0, 0.0),
                    }
                )
            all_mean = _safe_float(work[ret_col].mean() * 100.0, 0.0)
            top_mean = _safe_float(selected[ret_col].mean() * 100.0, 0.0)
            bottom_mean = _safe_float(bottom[ret_col].mean() * 100.0, 0.0)
            ic_mean = float(np.mean(ic_values)) if ic_values else 0.0
            ic_std = float(np.std(ic_values, ddof=1)) if len(ic_values) > 1 else 0.0
            gate_pass = top_mean > 0.0 and top_mean > all_mean and top_mean > bottom_mean and ic_mean > 0.0
            summary_rows.append(
                {
                    "horizon": int(h),
                    "score_col": score_col,
                    "score_direction": direction,
                    "rows": int(len(work)),
                    "days": int(work["signal_date"].nunique()),
                    "valid_forward_rows": int(work[ret_col].notna().sum()),
                    "all_mean_forward_return_pct": all_mean,
                    "top_n": int(top_n),
                    "top_rows": int(len(selected)),
                    "top_mean_forward_return_pct": top_mean,
                    "bottom_mean_forward_return_pct": bottom_mean,
                    "top_minus_all_pct": float(top_mean - all_mean),
                    "top_minus_bottom_pct": float(top_mean - bottom_mean),
                    "rank_ic_mean": ic_mean,
                    "icir": float(ic_mean / ic_std) if ic_std > 1e-12 else 0.0,
                    "rank_ic_positive_day_rate_pct": float(np.mean(np.array(ic_values) > 0.0) * 100.0) if ic_values else 0.0,
                    "top_hit_rate_pct": float((selected[ret_col] > 0.0).mean() * 100.0) if not selected.empty else 0.0,
                    "top_industry_label": _top_industry_label(selected),
                    "top_industry_weight_pct": _top_industry_weight_pct(selected),
                    "horizon_alpha_gate_pass": bool(gate_pass),
                }
            )
    return pd.DataFrame(summary_rows), pd.DataFrame(daily_rows)


def load_model_metadata(model_file: str = "") -> dict[str, object]:
    if model_file:
        fp = Path(model_file).expanduser().resolve()
    else:
        files = sorted(MODEL_DIR.glob("mfts_lgbm_*.pkl"))
        fp = files[-1] if files else Path("")
    if not fp or not fp.exists():
        return {"model_file": "", "label_mode": "", "label_horizon": 0, "train_objective": ""}
    try:
        payload = pickle.load(open(fp, "rb"))
    except Exception as exc:
        return {"model_file": str(fp), "label_mode": "", "label_horizon": 0, "train_objective": "", "error": str(exc)}
    if not isinstance(payload, dict):
        return {"model_file": str(fp), "label_mode": "", "label_horizon": 0, "train_objective": ""}
    metrics = payload.get("metrics", {})
    out: dict[str, object] = {
        "model_file": str(fp),
        "timestamp": str(payload.get("timestamp", "")),
        "label_mode": str(payload.get("label_mode", "")),
        "label_horizon": _safe_int(payload.get("label_horizon", 0)),
        "train_objective": str(payload.get("train_objective", "")),
        "execution_hint": str(payload.get("execution_hint", "")),
    }
    if isinstance(metrics, dict):
        for split in ["train", "valid", "test"]:
            raw = metrics.get(split, {})
            if isinstance(raw, dict):
                out[f"{split}_mean_ic"] = _safe_float(raw.get("mean_ic", 0.0))
                out[f"{split}_icir"] = _safe_float(raw.get("icir", 0.0))
                out[f"{split}_top10_avg_return"] = _safe_float(raw.get("top10_avg_return", 0.0))
                out[f"{split}_top30_avg_return"] = _safe_float(raw.get("top30_avg_return", 0.0))
    return out


def load_profile_metadata(profile: str = "", config_file: str = "") -> dict[str, object]:
    fp = Path(config_file).expanduser().resolve() if config_file else PROFILE_CONFIG
    if not profile or not fp.exists():
        return {"profile": str(profile or ""), "profile_holding_days": 0}
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"profile": str(profile), "profile_holding_days": 0, "profile_config_file": str(fp), "error": str(exc)}
    profiles = raw.get("profiles", {}) if isinstance(raw, dict) else {}
    cfg = profiles.get(str(profile), {}) if isinstance(profiles, dict) else {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "profile": str(profile),
        "profile_config_file": str(fp),
        "profile_holding_days": _safe_int(cfg.get("holding_days", 0)),
        "profile_top_n": _safe_int(cfg.get("top_n", 0)),
        "profile_target_score_col": str(cfg.get("target_score_col", "")),
    }


def build_horizon_verdict(
    summary: pd.DataFrame,
    model_meta: dict[str, object],
    profile_meta: dict[str, object] | None = None,
) -> dict[str, object]:
    trained_h = _safe_int(model_meta.get("label_horizon", 0))
    profile_meta = profile_meta or {}
    profile_h = _safe_int(profile_meta.get("profile_holding_days", 0))
    desc = summary[summary.get("score_direction", pd.Series(dtype=str)).astype(str).eq("desc")].copy()
    asc = summary[summary.get("score_direction", pd.Series(dtype=str)).astype(str).eq("asc")].copy()
    desc_pass = desc[desc.get("horizon_alpha_gate_pass", pd.Series(dtype=bool)).astype(bool)].copy()
    asc_pass = asc[asc.get("horizon_alpha_gate_pass", pd.Series(dtype=bool)).astype(bool)].copy()
    desc_pass_horizons = {_safe_int(x) for x in desc_pass.get("horizon", pd.Series(dtype=int)).tolist()}
    asc_pass_horizons = {_safe_int(x) for x in asc_pass.get("horizon", pd.Series(dtype=int)).tolist()}
    relevant_horizons = {x for x in [trained_h, profile_h] if x > 0}
    desc_relevant_pass = bool(desc_pass_horizons & relevant_horizons) if relevant_horizons else bool(desc_pass_horizons)
    asc_relevant_pass = bool(asc_pass_horizons & relevant_horizons) if relevant_horizons else bool(asc_pass_horizons)

    trained_desc_pass = False
    if trained_h > 0 and not desc.empty:
        rows = desc[pd.to_numeric(desc["horizon"], errors="coerce").fillna(0).astype(int).eq(trained_h)]
        trained_desc_pass = bool(rows["horizon_alpha_gate_pass"].astype(bool).any()) if not rows.empty else False

    best_desc = desc.sort_values(
        ["horizon_alpha_gate_pass", "rank_ic_mean", "top_minus_bottom_pct"],
        ascending=[False, False, False],
    ).head(1)
    best_asc = asc.sort_values(
        ["horizon_alpha_gate_pass", "rank_ic_mean", "top_minus_bottom_pct"],
        ascending=[False, False, False],
    ).head(1)
    best_desc_row = best_desc.iloc[0].to_dict() if not best_desc.empty else {}
    best_asc_row = best_asc.iloc[0].to_dict() if not best_asc.empty else {}

    if trained_desc_pass:
        verdict = "trained_horizon_alpha_pass"
        action = "raw ml_score passes at the trained open_to_open horizon; investigate later pipeline/P2 residual"
    elif not desc_pass.empty:
        verdict = "horizon_mismatch_possible"
        action = "ml_score only passes at a non-trained horizon; audit label_horizon versus profile holding_days"
    elif not asc_pass.empty:
        if relevant_horizons and not asc_relevant_pass:
            verdict = "raw_ml_alpha_failed_profile_horizons"
            action = "ml_score fails at trained/profile horizons; only non-profile inverted horizon passes, so audit labels/sign before profile work"
        else:
            verdict = "score_sign_inversion_possible"
            action = "ascending ml_score passes while descending fails; audit model direction, ranking labels, and prediction sign"
    else:
        verdict = "raw_ml_alpha_failed_all_horizons"
        action = "ml_score fails across tested open_to_open horizons; review raw labels/features/model before profile work"
    return {
        "overall_verdict": verdict,
        "recommended_next_action": action,
        "model_label_mode": str(model_meta.get("label_mode", "")),
        "model_label_horizon": trained_h,
        "model_train_objective": str(model_meta.get("train_objective", "")),
        "model_file": str(model_meta.get("model_file", "")),
        "profile": str(profile_meta.get("profile", "")),
        "profile_holding_days": profile_h,
        "model_profile_horizon_mismatch": bool(trained_h > 0 and profile_h > 0 and trained_h != profile_h),
        "relevant_horizons": ",".join(str(x) for x in sorted(relevant_horizons)),
        "desc_relevant_horizon_pass": bool(desc_relevant_pass),
        "asc_relevant_horizon_pass": bool(asc_relevant_pass),
        "trained_horizon_desc_pass": bool(trained_desc_pass),
        "desc_pass_horizons": ",".join(str(int(x)) for x in sorted(desc_pass_horizons)),
        "asc_pass_horizons": ",".join(str(int(x)) for x in sorted(asc_pass_horizons)),
        "best_desc_horizon": _safe_int(best_desc_row.get("horizon", 0)),
        "best_desc_rank_ic_mean": _safe_float(best_desc_row.get("rank_ic_mean", 0.0)),
        "best_desc_top_mean_forward_return_pct": _safe_float(best_desc_row.get("top_mean_forward_return_pct", 0.0)),
        "best_desc_top_minus_bottom_pct": _safe_float(best_desc_row.get("top_minus_bottom_pct", 0.0)),
        "best_asc_horizon": _safe_int(best_asc_row.get("horizon", 0)),
        "best_asc_rank_ic_mean": _safe_float(best_asc_row.get("rank_ic_mean", 0.0)),
        "best_asc_top_mean_forward_return_pct": _safe_float(best_asc_row.get("top_mean_forward_return_pct", 0.0)),
        "best_asc_top_minus_bottom_pct": _safe_float(best_asc_row.get("top_minus_bottom_pct", 0.0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose raw ml_score across open-to-open horizons")
    parser.add_argument("--stage-glob", required=True, help="research_stages CSV glob(s)")
    parser.add_argument("--market-file", default="", help="optional explicit market parquet; default is shared ODS")
    parser.add_argument("--profile", default="", help="profile/artifact label")
    parser.add_argument("--stage", default=DEFAULT_STAGE)
    parser.add_argument("--score-col", default="ml_score")
    parser.add_argument("--horizons", default=",".join(str(x) for x in DEFAULT_HORIZONS))
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--model-file", default="")
    parser.add_argument("--config", default=str(PROFILE_CONFIG), help="profile config JSON used to report holding_days mismatch")
    parser.add_argument("--write-latest", action="store_true")
    args = parser.parse_args()

    horizons = _parse_list_int(args.horizons, DEFAULT_HORIZONS)
    paths = _discover_paths(str(args.stage_glob))
    if not paths:
        raise RuntimeError("No research stage files found")
    raw = load_stage_scores(
        paths,
        stage=str(args.stage),
        score_col=str(args.score_col),
        start=str(args.start or ""),
        end=str(args.end or ""),
    )
    if raw.empty:
        raise RuntimeError("No raw stage rows after filtering")
    bars = load_market_opens(
        Path(args.market_file).resolve() if args.market_file else None,
        start=raw["signal_date"].min(),
        end=raw["signal_date"].max(),
        forward_sessions=max(horizons) + 1,
    )
    scored = attach_open_to_open_returns(raw, bars, horizons)
    summary, daily = summarize_horizons(scored, score_col=str(args.score_col), horizons=horizons, top_n=max(1, int(args.top_n)))
    model_meta = load_model_metadata(str(args.model_file or ""))
    profile_meta = load_profile_metadata(str(args.profile or ""), str(args.config or ""))
    verdict = build_horizon_verdict(summary, model_meta, profile_meta)

    label = str(args.profile or "raw_ml_horizon")
    slug = _slug(label)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_fp = BACKTEST_DIR / f"quant_raw_ml_horizon_diagnosis_{slug}_{ts}_summary.csv"
    daily_fp = BACKTEST_DIR / f"quant_raw_ml_horizon_diagnosis_{slug}_{ts}_daily.csv"
    verdict_fp = BACKTEST_DIR / f"quant_raw_ml_horizon_diagnosis_{slug}_{ts}_verdict.csv"
    json_fp = BACKTEST_DIR / f"quant_raw_ml_horizon_diagnosis_{slug}_{ts}.json"
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_fp, index=False, encoding="utf-8-sig")
    daily.to_csv(daily_fp, index=False, encoding="utf-8-sig")
    verdict_df = pd.DataFrame(
        [
            {
                **verdict,
                **{f"model_{k}": v for k, v in model_meta.items() if k not in verdict},
                **{k: v for k, v in profile_meta.items() if k not in verdict},
            }
        ]
    )
    verdict_df.to_csv(verdict_fp, index=False, encoding="utf-8-sig")
    payload: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile": label,
        "stage_file_count": len(paths),
        "rows": int(len(raw)),
        "stage": str(args.stage),
        "score_col": str(args.score_col),
        "horizons": horizons,
        "summary": str(summary_fp),
        "daily": str(daily_fp),
        "verdict": str(verdict_fp),
        "verdict_rows": verdict_df.to_dict(orient="records"),
    }
    json_fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_latest:
        latest_base = BACKTEST_DIR / f"quant_raw_ml_horizon_diagnosis_latest_{slug}"
        summary.to_csv(latest_base.with_name(latest_base.name + "_summary.csv"), index=False, encoding="utf-8-sig")
        daily.to_csv(latest_base.with_name(latest_base.name + "_daily.csv"), index=False, encoding="utf-8-sig")
        verdict_df.to_csv(latest_base.with_name(latest_base.name + "_verdict.csv"), index=False, encoding="utf-8-sig")
        latest_base.with_suffix(".json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.to_csv(BACKTEST_DIR / "quant_raw_ml_horizon_diagnosis_latest_summary.csv", index=False, encoding="utf-8-sig")
        daily.to_csv(BACKTEST_DIR / "quant_raw_ml_horizon_diagnosis_latest_daily.csv", index=False, encoding="utf-8-sig")
        verdict_df.to_csv(BACKTEST_DIR / "quant_raw_ml_horizon_diagnosis_latest_verdict.csv", index=False, encoding="utf-8-sig")
        (BACKTEST_DIR / "quant_raw_ml_horizon_diagnosis_latest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(verdict_df.to_string(index=False))
    print(summary.to_string(index=False))
    print(f"raw_ml_horizon_summary={summary_fp}")
    print(f"raw_ml_horizon_verdict={verdict_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
