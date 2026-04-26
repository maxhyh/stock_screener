# -*- coding: utf-8 -*-
"""股票代码与涨跌停规则的通用工具。"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd


_DIGIT_RE = re.compile(r"\d+")


def normalize_ts_code(code: Any) -> str:
    """
    统一标准化为 6 位数字代码。

    兼容输入：
    - 000001 / 1
    - 000001.SZ / 600000.SH
    - sz000001 / sh600000 / bj920000
    """
    if code is None:
        return ""
    s = str(code).strip()
    if not s:
        return ""
    s = s.split(".")[0].strip()
    nums = "".join(_DIGIT_RE.findall(s))
    if not nums:
        return ""
    return nums[-6:].zfill(6)


def normalize_ts_code_series(series: pd.Series) -> pd.Series:
    """向量化标准化代码序列到 6 位数字字符串。"""
    s = series.astype(str).str.strip()
    s = s.str.split(".").str[0]
    s = s.str.replace(r"[^0-9]", "", regex=True)
    s = s.str[-6:]
    has_digit = s.str.len() > 0
    out = pd.Series("", index=s.index, dtype=object)
    out.loc[has_digit] = s.loc[has_digit].str.zfill(6)
    return out


def is_st_name(name: Any) -> bool:
    s = str(name or "").upper()
    return ("ST" in s) or ("*ST" in s)


def limit_ratio_for_stock(code: Any, name: Any = "") -> float:
    """
    识别 A 股涨跌停幅度：
    - ST: 5%
    - 北交所(8/4开头): 30%
    - 科创/创业板(688/30): 20%
    - 其他: 10%
    """
    c = normalize_ts_code(code)
    if is_st_name(name):
        return 0.05
    # [Audit Fix P1-5] 北交所包含 8/4/9 开头
    if c.startswith("8") or c.startswith("4") or c.startswith("9"):
        return 0.30
    if c.startswith("688") or c.startswith("30"):
        return 0.20
    return 0.10


def limit_ratio_vectorized(codes: pd.Series, names: pd.Series | None = None) -> np.ndarray:
    """
    向量化涨跌停幅度。

    `codes` 允许未标准化格式，函数内部会归一化。
    """
    c = normalize_ts_code_series(codes)
    if names is None:
        is_st = pd.Series(False, index=c.index)
    else:
        is_st = names.astype(str).str.upper().str.contains("ST", na=False)
    is_kc_cy = c.str.startswith("688") | c.str.startswith("30")
    # [Audit Fix P1-5] 北交所包含 8/4/9 开头
    is_bj = c.str.startswith("8") | c.str.startswith("4") | c.str.startswith("9")
    return np.select([is_st, is_bj, is_kc_cy], [0.05, 0.30, 0.20], default=0.10)
