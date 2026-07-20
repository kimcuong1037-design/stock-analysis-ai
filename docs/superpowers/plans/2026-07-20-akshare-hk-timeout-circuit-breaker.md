# akshare 港股日线超时熔断 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `AkshareFetcher` 在港股日线连续超时后进入短时冷却，冷却期内对港股日线请求快速失败，使 `DataFetcherManager` 毫秒级降级到 `YfinanceFetcher`，消除批量港股查询里每只重复白等约 19s 的问题。

**Architecture:** 在 `AkshareFetcher` 实例内维护港股专用熔断状态（连续超时计数 + 冷却截止时间戳），完全参照 `data_provider/longbridge_fetcher.py` 的连接冷却先例。判定入口与记账都收敛在 `_fetch_hk_data()` 内；不改 `DataFetcherManager`、不改 fetcher 接口契约、不碰 A 股/ETF/美股/实时行情路径。超时判定复用现有的 `_classify_realtime_http_error()`，只有 `"timeout"` 类别计入连续计数。

**Tech Stack:** Python 3、pytest（`-m "not network"` 离线测试）、pandas、akshare（仅在测试中被 monkeypatch，不实际联网）。

## Global Constraints

- 默认冷却时长 `180` 秒；环境变量 `AKSHARE_HK_COOLDOWN_SECONDS`，取值 `0` 表示禁用熔断（回退到当前行为）。
- 连续超时阈值固定常量 `_HK_TIMEOUT_STREAK_THRESHOLD = 2`，不新增配置项。
- 配置解析容错：空值/非法值回落默认 180，负值按 0（禁用）处理——与 Longbridge `_connection_cooldown_seconds()` 完全一致。
- 只影响「akshare 港股日线」路径；A 股、ETF、美股、实时行情、`DataFetcherManager` 过滤/降级逻辑一律不改。
- 不改数据源默认优先级数值（`AKSHARE_PRIORITY=1` / `YFINANCE_PRIORITY=4` 不动）。
- 异常类型对外语义不变：现有 banned/blocked/频率/rate/限制 → `RateLimitError`，其余 → `DataFetchError`；本改动只新增 streak/cooldown 记账。
- commit message 用英文，不加 `Co-Authored-By`。未经确认不执行 `git push` / `git tag`。
- `docs/CHANGELOG.md` 的 `[Unreleased]` 用扁平格式：每条一行 `- [类型] 描述`，禁止新增 `### 类目标题`。

**相关现状代码位置（实现时以实际行号为准）：**
- `data_provider/akshare_fetcher.py`
  - 模块常量区：约第 62-66 行（`_AKSHARE_HISTORY_CALL_TIMEOUT = 30.0` 附近）
  - 超时分类器：`_classify_realtime_http_error()` 约第 245 行，`isinstance(exc, (TimeoutError, requests.exceptions.Timeout))` 或含 timeout 关键字时返回 `("timeout", detail)`
  - 类定义与 `__init__`：`class AkshareFetcher` 约第 374 行，`__init__` 约第 390-403 行
  - 港股取数：`_fetch_hk_data()` 约第 807-870 行
  - 已 import：`os`（第 28 行）、`time`（第 30 行）、`logging`（第 26 行）；`from .base import BaseFetcher, DataFetchError, RateLimitError, ...`（第 47 行）
- 异常类：`DataFetchError`（`data_provider/base.py:273`）、`RateLimitError(DataFetchError)`（`data_provider/base.py:278`）
- 冷却先例：`data_provider/longbridge_fetcher.py` 的 `_connection_cooldown_seconds()`（第 55-64 行）、`_cooldown_until`/`_mark_connection_cooldown()`（第 429、444 行）
- 市场支持表：`DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT`（`data_provider/base.py:565`），`AkshareFetcher` 支持 `{"cn","hk"}`，`YfinanceFetcher` 支持 `{"cn","hk","us"}`

---

## File Structure

| 文件 | 变更 | 职责 |
| --- | --- | --- |
| `data_provider/akshare_fetcher.py` | Modify | 新增模块级冷却配置解析 + 常量；`AkshareFetcher` 新增熔断状态与 helper；`_fetch_hk_data()` 加入口冷却检查、成功重置、超时记账 |
| `tests/test_akshare_hk_timeout_circuit_breaker.py` | Create | 熔断行为单元测试 + 管理器降级集成测试 |
| `.env.example` | Modify | 新增 `AKSHARE_HK_COOLDOWN_SECONDS` 说明 |
| `docs/CHANGELOG.md` | Modify | `[Unreleased]` 追加一行 `- [改进] ...` |
| `docs/FAQ.md` | Modify | 新增「港股查询慢/自动熔断」FAQ 条目 |
| `docs/FAQ_EN.md` | Modify（评估后） | 同步英文条目，或在交付说明写明未同步原因 |

---

## Task 1: 模块级冷却配置解析与常量

**Files:**
- Modify: `data_provider/akshare_fetcher.py`（模块常量区约第 62-66 行附近）
- Test: `tests/test_akshare_hk_timeout_circuit_breaker.py`

**Interfaces:**
- Produces:
  - 模块常量 `_DEFAULT_HK_COOLDOWN_SECONDS: int = 180`、`_HK_TIMEOUT_STREAK_THRESHOLD: int = 2`
  - 模块函数 `_hk_cooldown_seconds() -> int`：读 `AKSHARE_HK_COOLDOWN_SECONDS`，空/非法回落 180，负值→0

- [ ] **Step 1: Write the failing test**

新建 `tests/test_akshare_hk_timeout_circuit_breaker.py`，写入文件头与第一组测试：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_akshare_hk_timeout_circuit_breaker.py -k hk_cooldown_seconds -v`
Expected: FAIL —— `ImportError: cannot import name '_hk_cooldown_seconds'`

- [ ] **Step 3: Write minimal implementation**

在 `data_provider/akshare_fetcher.py` 模块常量区（`_AKSHARE_TIMEOUT_PROCESS_START_METHOD = "spawn"` 之后）新增：

```python
_DEFAULT_HK_COOLDOWN_SECONDS = 180
_HK_TIMEOUT_STREAK_THRESHOLD = 2


def _hk_cooldown_seconds() -> int:
    """akshare 港股日线连续超时后的冷却秒数；0 表示禁用熔断。

    解析规则与 Longbridge 连接冷却一致：空值/非法值回落默认 180，负值按 0 处理。
    """
    raw = os.getenv("AKSHARE_HK_COOLDOWN_SECONDS", "").strip()
    if raw == "":
        return _DEFAULT_HK_COOLDOWN_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_HK_COOLDOWN_SECONDS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_akshare_hk_timeout_circuit_breaker.py -k hk_cooldown_seconds -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add data_provider/akshare_fetcher.py tests/test_akshare_hk_timeout_circuit_breaker.py
git commit -m "feat(data): add akshare HK cooldown-seconds config parser"
```

---

## Task 2: AkshareFetcher 港股熔断状态与 `_fetch_hk_data` 集成

**Files:**
- Modify: `data_provider/akshare_fetcher.py`（`AkshareFetcher.__init__` 约第 390 行；新增 helper 方法；`_fetch_hk_data()` 约第 807 行）
- Test: `tests/test_akshare_hk_timeout_circuit_breaker.py`

**Interfaces:**
- Consumes（来自 Task 1）：`_hk_cooldown_seconds()`、`_HK_TIMEOUT_STREAK_THRESHOLD`
- Produces（`AkshareFetcher` 新增，供本任务与 Task 3 使用）：
  - 实例属性 `self._hk_timeout_streak: int`、`self._hk_cooldown_until: float`
  - `_hk_is_cooling_down(self) -> bool`
  - `_hk_cooldown_remaining(self) -> float`
  - `_reset_hk_timeout_streak(self) -> None`
  - `_register_hk_timeout(self) -> None`
  - `_fetch_hk_data()` 行为：冷却期内快速抛 `DataFetchError`（原因含「冷却」）；成功返回前重置 streak；捕获到 `"timeout"` 类异常时累计 streak 并在达阈值时设冷却

- [ ] **Step 1: Write the failing test**

在测试文件追加 fixture 与行为测试（接在 Task 1 的测试之后）：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_akshare_hk_timeout_circuit_breaker.py -k "circuit or streak or cooldown_expiry or disabled or rate_limit_error or non_timeout" -v`
Expected: FAIL —— `AttributeError: 'AkshareFetcher' object has no attribute '_hk_is_cooling_down'`（以及第三次调用仍触网、streak 属性不存在等）

- [ ] **Step 3: Write minimal implementation**

3a. 在 `AkshareFetcher.__init__` 末尾（`eastmoney_patch()` 之后）新增熔断状态：

```python
        self._hk_timeout_streak = 0
        self._hk_cooldown_until = 0.0
```

3b. 在 `AkshareFetcher` 内新增 helper 方法（放在 `_fetch_hk_data` 之前即可）：

```python
    def _hk_cooldown_remaining(self) -> float:
        """当前冷却剩余秒数（非正表示未在冷却）。"""
        return self._hk_cooldown_until - time.time()

    def _hk_is_cooling_down(self) -> bool:
        """港股日线是否处于熔断冷却期。冷却禁用（秒数<=0）时恒为 False。"""
        if _hk_cooldown_seconds() <= 0:
            return False
        return self._hk_cooldown_remaining() > 0

    def _reset_hk_timeout_streak(self) -> None:
        self._hk_timeout_streak = 0

    def _register_hk_timeout(self) -> None:
        """记录一次港股日线超时；达到阈值则进入冷却。禁用时不累计、不熔断。"""
        cooldown_seconds = _hk_cooldown_seconds()
        if cooldown_seconds <= 0:
            return
        self._hk_timeout_streak += 1
        if self._hk_timeout_streak >= _HK_TIMEOUT_STREAK_THRESHOLD:
            self._hk_cooldown_until = time.time() + cooldown_seconds
            logger.warning(
                "[港股熔断] akshare 港股日线连续超时 %d 次，进入冷却 %ds",
                self._hk_timeout_streak,
                cooldown_seconds,
            )
```

3c. 修改 `_fetch_hk_data()`：在方法体最前（`import akshare as ak` 之后、`_set_random_user_agent()` 之前）加入口检查；在 `ak.stock_hk_hist(...)` 成功返回后重置 streak；在 except 分支最前对 `"timeout"` 类异常记账。改后关键片段：

```python
    def _fetch_hk_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak

        # 熔断入口：冷却期内直接快速失败，交由管理器降级到下一数据源
        if self._hk_is_cooling_down():
            remaining = max(0.0, self._hk_cooldown_remaining())
            logger.debug(
                "[港股熔断] 冷却中，跳过 akshare 港股请求 %s，剩余约 %.0fs",
                stock_code,
                remaining,
            )
            raise DataFetchError(
                f"Akshare 港股数据源冷却中，跳过（连续超时熔断），剩余约 {remaining:.0f}s"
            )

        # 防封禁策略 1: 随机 User-Agent
        self._set_random_user_agent()

        # 防封禁策略 2: 强制休眠
        self._enforce_rate_limit()

        # 确保代码格式正确（5位数字）
        code = stock_code.lower().replace('hk', '').zfill(5)

        logger.info(f"[API调用] ak.stock_hk_hist(symbol={code}, period=daily, "
                   f"start_date={start_date.replace('-', '')}, end_date={end_date.replace('-', '')}, adjust=qfq)")

        try:
            import time as _time
            api_start = _time.time()

            df = ak.stock_hk_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust="qfq"  # 前复权
            )

            api_elapsed = _time.time() - api_start

            # 成功完成（未超时）→ 打断连续超时计数
            self._reset_hk_timeout_streak()

            if df is not None and not df.empty:
                logger.info(f"[API返回] ak.stock_hk_hist 成功: 返回 {len(df)} 行数据, 耗时 {api_elapsed:.2f}s")
                logger.info(f"[API返回] 列名: {list(df.columns)}")
                logger.info(f"[API返回] 日期范围: {df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]}")
                logger.debug(f"[API返回] 最新3条数据:\n{df.tail(3).to_string()}")
            else:
                logger.warning(f"[API返回] ak.stock_hk_hist 返回空数据, 耗时 {api_elapsed:.2f}s")

            return df

        except Exception as e:
            # 仅超时类失败计入熔断，其余维持既有语义
            category, _detail = _classify_realtime_http_error(e)
            if category == "timeout":
                self._register_hk_timeout()

            error_msg = str(e).lower()

            # 检测反爬封禁
            if any(keyword in error_msg for keyword in ['banned', 'blocked', '频率', 'rate', '限制']):
                logger.warning(f"检测到可能被封禁: {e}")
                raise RateLimitError(f"Akshare 可能被限流: {e}") from e

            raise DataFetchError(f"Akshare 获取港股数据失败: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_akshare_hk_timeout_circuit_breaker.py -v`
Expected: PASS（Task 1 的 5 条 + 本任务 6 条全部通过）

- [ ] **Step 5: Commit**

```bash
git add data_provider/akshare_fetcher.py tests/test_akshare_hk_timeout_circuit_breaker.py
git commit -m "feat(data): circuit-break akshare HK daily line after consecutive timeouts"
```

---

## Task 3: DataFetcherManager 降级集成测试

**Files:**
- Test: `tests/test_akshare_hk_timeout_circuit_breaker.py`（追加集成测试；本任务不新增生产代码）

**Interfaces:**
- Consumes：Task 2 的 `AkshareFetcher._hk_cooldown_until` / `_hk_is_cooling_down()`；`DataFetcherManager(fetchers=[...])`（`data_provider/base.py`）
- 验证目标：akshare 处于冷却期时，`DataFetcherManager.get_daily_data("hk00700")` 快速降级到 `YfinanceFetcher` 且**不触发 akshare 网络调用**

- [ ] **Step 1: Write the failing test**

在测试文件追加集成测试：

```python
from data_provider.base import BaseFetcher, DataFetcherManager


class _OkYfinanceStub(BaseFetcher):
    """最小可用的 yfinance 替身：直接返回标准化日线，绕过 normalize/clean/indicators。"""

    name = "YfinanceFetcher"
    priority = 4

    def _fetch_raw_data(self, stock_code, start_date, end_date):  # pragma: no cover
        raise NotImplementedError

    def _normalize_data(self, df, stock_code):  # pragma: no cover
        return df

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        return pd.DataFrame(
            {
                "date": ["2026-07-16", "2026-07-17"],
                "open": [478.0, 488.8],
                "high": [494.8, 488.8],
                "low": [477.4, 458.0],
                "close": [484.0, 461.6],
                "volume": [42851475, 36237657],
            }
        )


def test_manager_falls_back_to_yfinance_while_akshare_cooling(monkeypatch):
    monkeypatch.setenv("AKSHARE_HK_COOLDOWN_SECONDS", "180")
    akshare_fetcher = AkshareFetcher()
    monkeypatch.setattr(akshare_fetcher, "_enforce_rate_limit", lambda: None)
    monkeypatch.setattr(akshare_fetcher, "_set_random_user_agent", lambda: None)
    # 预置为冷却中
    akshare_fetcher._hk_cooldown_until = time.time() + 999

    fake = _install_fake_ak(monkeypatch, [_make_success_df()])  # 若被调用即视为熔断失效

    manager = DataFetcherManager(fetchers=[akshare_fetcher, _OkYfinanceStub()])
    df, source = manager.get_daily_data(_HK_CODE, days=30)

    assert source == "YfinanceFetcher"
    assert not df.empty
    assert fake.calls == 0  # akshare 冷却期内未触网
```

- [ ] **Step 2: Run test to verify it fails (or captures the guard)**

先临时确认该测试确实锁定新行为：把 `akshare_fetcher._hk_cooldown_until` 那行注释掉并把 `AKSHARE_HK_COOLDOWN_SECONDS` 设为 `0` 跑一次，应看到 `fake.calls == 1`（akshare 被真实调用）——证明断言 `fake.calls == 0` 对熔断行为敏感。确认后恢复。

Run（正式）：`.venv/bin/python -m pytest tests/test_akshare_hk_timeout_circuit_breaker.py -k manager_falls_back -v`
Expected: 恢复冷却预置后 PASS；akshare stub 调用次数为 0，源为 `YfinanceFetcher`。

- [ ] **Step 3: 实现**

本任务无生产代码改动（依赖 Task 2 已实现的熔断 + 管理器既有降级）。若测试未通过，回到 Task 2 排查冷却入口是否在 `_set_random_user_agent`/`_enforce_rate_limit` 之前抛出。

- [ ] **Step 4: Run full test file**

Run: `.venv/bin/python -m pytest tests/test_akshare_hk_timeout_circuit_breaker.py -v`
Expected: PASS（全部 12 条）

- [ ] **Step 5: Commit**

```bash
git add tests/test_akshare_hk_timeout_circuit_breaker.py
git commit -m "test(data): manager falls back to yfinance while akshare HK cools down"
```

---

## Task 4: 文档与配置同步

**Files:**
- Modify: `.env.example`（数据源优先级 override 段落，约第 744-762 行）
- Modify: `docs/CHANGELOG.md`（`[Unreleased]` 约第 10 行下）
- Modify: `docs/FAQ.md`（「数据相关」段落）
- Modify（评估后）: `docs/FAQ_EN.md`

**Interfaces:** 无代码接口；交付需保证命令、配置项、默认值与实现一致。

- [ ] **Step 1: `.env.example` 新增配置说明**

在 `.env.example` 的 `# YFINANCE_PRIORITY=4 ...` 一行之后（数据源优先级 override 区块内）追加：

```bash
# AkShare HK daily-line circuit breaker: after this many seconds of cooldown,
# HK daily requests that hit consecutive eastmoney timeouts are skipped fast and
# fall back to Yahoo Finance. Default: 180. Set 0 to disable (always try AkShare).
# AKSHARE_HK_COOLDOWN_SECONDS=180
```

- [ ] **Step 2: `docs/CHANGELOG.md` 追加一行（扁平格式）**

在 `## [Unreleased]` 下、紧接第一条 `- [改进]`/`- [新功能]` 之前或之后，新增独立一行：

```markdown
- [改进] akshare 港股日线连续超时后自动熔断降级到 Yahoo Finance，避免批量港股查询重复等待；可用 AKSHARE_HK_COOLDOWN_SECONDS 调整（默认 180 秒，0 关闭）
```

- [ ] **Step 3: `docs/FAQ.md` 新增 FAQ 条目**

在「## 📊 数据相关」段落内新增一条（紧跟现有 Q 之后，编号顺延）：

```markdown
### Q: 港股分析偶尔要等十几秒才出结果？

**现象**：查询港股（如 hk00700）时，偶尔要等约 15-20 秒才返回。

**原因**：默认港股日线优先走 AkShare（东方财富爬虫）。当东方财富接口不可达/缓慢时，请求会读超时后才降级到 Yahoo Finance。

**解决方案**：
1. 系统已内置自动熔断：AkShare 港股日线连续超时后进入冷却期（默认 180 秒），冷却期内直接跳过 AkShare、改用 Yahoo Finance，避免每只港股重复等待。
2. 如需调整或关闭，可在 `.env` 设置：
   ```bash
   AKSHARE_HK_COOLDOWN_SECONDS=180   # 冷却秒数，设 0 关闭熔断
   ```
3. 若港股为主要分析对象，也可考虑配置更稳定的正规数据源（如 Longbridge / Tushare 积分）。
```

- [ ] **Step 4: 评估并同步 `docs/FAQ_EN.md`**

Run: `grep -n "YFINANCE_PRIORITY\|HK\|Hong Kong" docs/FAQ_EN.md`
- 若 `FAQ_EN.md` 存在对应「数据相关」结构，新增等价英文条目；
- 若结构差异较大或本次不同步，在交付说明「未验证项/说明」里写明原因（依 `AGENTS.md`「中英双语文档同步评估」要求）。

- [ ] **Step 5: 验证文档一致性并提交**

Run: `grep -n "AKSHARE_HK_COOLDOWN_SECONDS" .env.example docs/CHANGELOG.md docs/FAQ.md`
Expected: 三个文件均出现该配置名，默认值均为 180、关闭值均为 0，措辞一致。

```bash
git add .env.example docs/CHANGELOG.md docs/FAQ.md docs/FAQ_EN.md
git commit -m "docs: document akshare HK timeout circuit breaker and AKSHARE_HK_COOLDOWN_SECONDS"
```

---

## Task 5: 全量验证矩阵

**Files:** 无（仅运行验证）

- [ ] **Step 1: 语法编译**

Run: `.venv/bin/python -m py_compile data_provider/akshare_fetcher.py`
Expected: 无输出（成功）

- [ ] **Step 2: 目标测试全绿**

Run: `.venv/bin/python -m pytest -m "not network" tests/test_akshare_hk_timeout_circuit_breaker.py tests/test_akshare_history_timeout.py -v`
Expected: PASS（新增文件 12 条 + 既有港股超时回归测试全过，确认无回归）

- [ ] **Step 3: CI 门禁**

Run: `./scripts/ci_gate.sh`
Expected: 通过（flake8 + 相关 pytest）。若因环境缺依赖等非本改动原因失败，在交付说明中标注并给出本地已跑通的子集。

- [ ] **Step 4: 交付说明**

按 `AGENTS.md` 第 9 节整理：改了什么 / 为什么这么改 / 验证情况 / 未验证项 / 风险点 / 回滚方式（回滚：`AKSHARE_HK_COOLDOWN_SECONDS=0` 或 revert PR）。

---

## Self-Review

**Spec coverage：**
- §4.1 状态（streak + cooldown_until）→ Task 2 Step 3a/3b ✅
- §4.2 配置（`AKSHARE_HK_COOLDOWN_SECONDS`，默认 180，0 禁用，阈值常量 2）→ Task 1 + Global Constraints ✅
- §4.3 触发判定（入口冷却检查在限速前、复用 `_classify_realtime_http_error`、仅 timeout 计数、成功重置、非超时不计数）→ Task 2 Step 3c + 测试 ✅
- §4.4 恢复（冷却过期自然放行）→ Task 2 `test_cooldown_expiry_allows_real_call_again` ✅
- §4.5 可观测性（进入冷却 WARNING、冷却期跳过 DEBUG）→ Task 2 Step 3b/3c ✅
- §5 测试 1-7 → Task 2（1-6）+ Task 3（7）✅
- §6 文档同步（.env.example / CHANGELOG / FAQ / FAQ_EN 评估）→ Task 4 ✅
- §7 验证矩阵 → Task 5 ✅

**Placeholder scan：** 无 TBD/TODO/"类似上文"占位；每个代码步骤均含完整可粘贴代码。

**Type consistency：** `_hk_cooldown_seconds()`、`_HK_TIMEOUT_STREAK_THRESHOLD`、`_hk_is_cooling_down()`、`_hk_cooldown_remaining()`、`_reset_hk_timeout_streak()`、`_register_hk_timeout()`、`_hk_timeout_streak`、`_hk_cooldown_until` 在 Task 1/2/3 中命名一致；异常类 `DataFetchError`/`RateLimitError` 均来自 `data_provider.base`，与 akshare_fetcher 现有 import 一致。
