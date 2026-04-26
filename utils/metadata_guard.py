"""股票元数据健康度门禁。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


def load_metadata_health(data_dir: str | Path) -> dict[str, object]:
    """读取股票元数据的行业覆盖率与文件新鲜度。"""
    data_dir = Path(data_dir)
    candidates = [
        data_dir / "stock_info.csv",
        data_dir / "stock_metadata.csv",
        data_dir / "stock_basic.csv",
    ]
    for fp in candidates:
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp, dtype=str)
        except Exception:
            continue
        if df.empty:
            continue
        ind_col = "industry" if "industry" in df.columns else ("行业" if "行业" in df.columns else None)
        if ind_col is None:
            continue
        ind = df[ind_col].where(~df[ind_col].isna(), "").astype(str).str.strip()
        ind = ind.replace({"nan": "", "None": "", "NONE": ""})
        nonempty = int((ind != "").sum())
        rows = int(len(df))
        cov = float(nonempty / max(rows, 1) * 100.0)
        modified_ts = datetime.fromtimestamp(fp.stat().st_mtime)
        age_days = max((datetime.now() - modified_ts).total_seconds() / 86400.0, 0.0)
        return {
            "file": str(fp),
            "rows": rows,
            "industry_nonempty": nonempty,
            "coverage_pct": cov,
            "ok": True,
            "modified_at": modified_ts.isoformat(timespec="seconds"),
            "age_days": float(age_days),
        }
    return {
        "file": "",
        "rows": 0,
        "industry_nonempty": 0,
        "coverage_pct": 0.0,
        "ok": False,
        "modified_at": "",
        "age_days": float("inf"),
    }


def evaluate_metadata_guard(
    info: dict[str, object],
    *,
    min_coverage_pct: float,
    max_age_days: float,
) -> dict[str, object]:
    """评估元数据覆盖率与新鲜度是否满足执行门禁。"""
    coverage_pct = float(info.get("coverage_pct", 0.0) or 0.0)
    age_days = float(info.get("age_days", float("inf")) or float("inf"))
    base_ok = bool(info.get("ok", False))
    coverage_ok = coverage_pct >= max(0.0, float(min_coverage_pct))
    freshness_ok = age_days <= max(0.0, float(max_age_days))
    reasons: list[str] = []
    if not base_ok:
        reasons.append("metadata_missing")
    if base_ok and not coverage_ok:
        reasons.append("industry_coverage_low")
    if base_ok and not freshness_ok:
        reasons.append("metadata_stale")
    return {
        **dict(info),
        "min_coverage_pct": float(min_coverage_pct),
        "max_age_days": float(max_age_days),
        "coverage_ok": bool(coverage_ok),
        "freshness_ok": bool(freshness_ok),
        "passed": bool(base_ok and coverage_ok and freshness_ok),
        "reason": ",".join(reasons) if reasons else "ok",
    }
