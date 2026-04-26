"""组合权重分配工具。"""

from __future__ import annotations

import hashlib
import json

import numpy as np


def build_score_weights(scores: np.ndarray, total_target: float, single_cap: float) -> np.ndarray:
    """按分数构建目标权重，并进行单票上限再分配。"""
    if len(scores) == 0 or total_target <= 0 or single_cap <= 0:
        return np.array([], dtype=float)
    s = np.asarray(scores, dtype=float)
    s = np.where(np.isfinite(s), s, 0.0)
    s = s - np.min(s)
    s = s + 1e-6
    if float(np.sum(s)) <= 0:
        s = np.ones_like(s)
    w = s / float(np.sum(s)) * total_target
    fixed = np.zeros(len(w), dtype=bool)
    for _ in range(8):
        over = (~fixed) & (w > single_cap)
        if not np.any(over):
            break
        fixed = fixed | over
        w[fixed] = single_cap
        capped = float(np.sum(w[fixed]))
        free = ~fixed
        if not np.any(free):
            w[fixed] = single_cap
            break
        remain = max(total_target - capped, 0.0)
        free_scores = s[free]
        free_scores = free_scores / np.sum(free_scores)
        w[free] = free_scores * remain
    if np.any(~fixed):
        w[~fixed] = np.minimum(w[~fixed], single_cap)
    return w


def build_target_weight_checksum(code_weights, *, precision: int = 10) -> str:
    """Build a stable checksum for a code -> target_weight set."""
    rows: list[tuple[str, float]] = []
    for code, weight in code_weights:
        code_s = str(code or "").strip()
        if not code_s:
            continue
        try:
            w = float(weight)
        except Exception:
            continue
        if not np.isfinite(w) or w <= 0:
            continue
        rows.append((code_s, round(float(w), int(precision))))
    payload = json.dumps(sorted(rows), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
