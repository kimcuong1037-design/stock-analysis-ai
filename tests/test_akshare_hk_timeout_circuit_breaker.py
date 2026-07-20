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


_HK_CODE = "hk00700"
_START = "2026-06-20"
_END = "2026-07-20"


def _make_success_df():
    """构造带 akshare 中文列名的最小成功 DataFrame（含 `_fetch_hk_data` 成功日志会用到的 日期 列）。"""
    return pd.DataFrame(
        {
            "日期": ["2026-07-16", "2026-07-17"],
            "开盘": [478.0, 488.8],
            "收盘": [484.0, 461.6],
            "最高": [494.8, 488.8],
            "最低": [477.4, 458.0],
            "成交量": [42851475, 36237657],
            "成交额": [2.07e10, 1.67e10],
            "涨跌幅": [2.11, -4.63],
        }
    )


class _FakeAk:
    """替身：按预设脚本决定每次 stock_hk_hist 的行为（返回 df 或抛异常），并计数调用次数。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def stock_hk_hist(self, **kwargs):
        self.calls += 1
        action = self._script.pop(0) if self._script else self._last
        self._last = action
        if isinstance(action, Exception):
            raise action
        return action


@pytest.fixture
def hk_fetcher(monkeypatch):
    """构造 AkshareFetcher，并把限速休眠/UA 设置替换为 no-op，避免真实 sleep 与联网。"""
    monkeypatch.setenv("AKSHARE_HK_COOLDOWN_SECONDS", "180")
    fetcher = AkshareFetcher()
    monkeypatch.setattr(fetcher, "_enforce_rate_limit", lambda: None)
    monkeypatch.setattr(fetcher, "_set_random_user_agent", lambda: None)
    return fetcher


def _install_fake_ak(monkeypatch, script):
    fake = _FakeAk(script)
    import akshare
    monkeypatch.setattr(akshare, "stock_hk_hist", fake.stock_hk_hist)
    return fake


def test_two_consecutive_timeouts_open_circuit_and_skip_network(monkeypatch, hk_fetcher):
    fake = _install_fake_ak(
        monkeypatch,
        [TimeoutError("read timed out"), TimeoutError("read timed out")],
    )
    # 前两次真实调用都超时
    for _ in range(2):
        with pytest.raises(DataFetchError):
            hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)
    assert fake.calls == 2
    # 第三次应被熔断快速拦截，不再触网
    with pytest.raises(DataFetchError) as exc_info:
        hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)
    assert "冷却" in str(exc_info.value)
    assert fake.calls == 2  # 未新增调用


def test_success_resets_streak(monkeypatch, hk_fetcher):
    fake = _install_fake_ak(
        monkeypatch,
        [TimeoutError("read timed out"), _make_success_df(), TimeoutError("read timed out")],
    )
    with pytest.raises(DataFetchError):
        hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)  # timeout #1
    df = hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)  # success → reset
    assert not df.empty
    assert hk_fetcher._hk_timeout_streak == 0
    with pytest.raises(DataFetchError):
        hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)  # timeout again, streak=1
    assert hk_fetcher._hk_timeout_streak == 1
    assert not hk_fetcher._hk_is_cooling_down()  # 未达阈值，未熔断


def test_cooldown_expiry_allows_real_call_again(monkeypatch, hk_fetcher):
    fake = _install_fake_ak(
        monkeypatch,
        [TimeoutError("t"), TimeoutError("t"), _make_success_df()],
    )
    for _ in range(2):
        with pytest.raises(DataFetchError):
            hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)
    assert hk_fetcher._hk_is_cooling_down()
    # 手动让冷却过期
    hk_fetcher._hk_cooldown_until = time.time() - 1
    df = hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)
    assert not df.empty
    assert fake.calls == 3


def test_disabled_never_opens_circuit(monkeypatch):
    monkeypatch.setenv("AKSHARE_HK_COOLDOWN_SECONDS", "0")
    fetcher = AkshareFetcher()
    monkeypatch.setattr(fetcher, "_enforce_rate_limit", lambda: None)
    monkeypatch.setattr(fetcher, "_set_random_user_agent", lambda: None)
    fake = _install_fake_ak(monkeypatch, [TimeoutError("t")])  # 反复复用最后一个动作
    for _ in range(4):
        with pytest.raises(DataFetchError):
            fetcher._fetch_hk_data(_HK_CODE, _START, _END)
    assert fake.calls == 4  # 每次都真实调用，从不熔断
    assert not fetcher._hk_is_cooling_down()


def test_rate_limit_error_does_not_count_as_timeout(monkeypatch, hk_fetcher):
    fake = _install_fake_ak(
        monkeypatch,
        [Exception("请求过于频繁 rate limit"), Exception("请求过于频繁 rate limit")],
    )
    for _ in range(2):
        with pytest.raises(RateLimitError):
            hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)
    assert hk_fetcher._hk_timeout_streak == 0
    assert not hk_fetcher._hk_is_cooling_down()


def test_non_timeout_error_does_not_count(monkeypatch, hk_fetcher):
    fake = _install_fake_ak(
        monkeypatch,
        [ValueError("unexpected parse error"), ValueError("unexpected parse error")],
    )
    for _ in range(2):
        with pytest.raises(DataFetchError):
            hk_fetcher._fetch_hk_data(_HK_CODE, _START, _END)
    assert hk_fetcher._hk_timeout_streak == 0
    assert not hk_fetcher._hk_is_cooling_down()
