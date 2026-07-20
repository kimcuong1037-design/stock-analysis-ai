# -*- coding: utf-8 -*-
"""akshare 港股日线连续超时熔断的回归测试。"""

import time

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider import akshare_fetcher as hk_mod
from data_provider.akshare_fetcher import AkshareFetcher, _hk_cooldown_seconds
from data_provider.base import DataFetchError, RateLimitError


def test_hk_cooldown_seconds_defaults_to_180(monkeypatch):
    monkeypatch.delenv("AKSHARE_HK_COOLDOWN_SECONDS", raising=False)
    assert _hk_cooldown_seconds() == 180


def test_hk_cooldown_seconds_reads_env(monkeypatch):
    monkeypatch.setenv("AKSHARE_HK_COOLDOWN_SECONDS", "60")
    assert _hk_cooldown_seconds() == 60


def test_hk_cooldown_seconds_zero_disables(monkeypatch):
    monkeypatch.setenv("AKSHARE_HK_COOLDOWN_SECONDS", "0")
    assert _hk_cooldown_seconds() == 0


def test_hk_cooldown_seconds_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("AKSHARE_HK_COOLDOWN_SECONDS", "abc")
    assert _hk_cooldown_seconds() == 180


def test_hk_cooldown_seconds_negative_clamped_to_zero(monkeypatch):
    monkeypatch.setenv("AKSHARE_HK_COOLDOWN_SECONDS", "-5")
    assert _hk_cooldown_seconds() == 0
