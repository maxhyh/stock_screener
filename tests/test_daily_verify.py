# -*- coding: utf-8 -*-
"""daily_verify 退出码行为测试。"""

from __future__ import annotations

import sys

import pytest

import scripts.daily_verify as daily_verify


def test_daily_verify_returns_zero_when_no_sample_and_not_strict(monkeypatch):
    monkeypatch.setattr(daily_verify, "verify_predictions", lambda **kwargs: None)
    monkeypatch.setattr(sys, "argv", ["daily_verify.py", "--date", "20260409"])

    with pytest.raises(SystemExit) as ex:
        daily_verify.main()
    assert int(ex.value.code) == 0


def test_daily_verify_returns_nonzero_when_no_sample_and_strict(monkeypatch):
    monkeypatch.setattr(daily_verify, "verify_predictions", lambda **kwargs: None)
    monkeypatch.setattr(sys, "argv", ["daily_verify.py", "--date", "20260409", "--strict"])

    with pytest.raises(SystemExit) as ex:
        daily_verify.main()
    assert int(ex.value.code) == 2
