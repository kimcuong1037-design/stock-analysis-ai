# 价值低估策略 + value 标签断点修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增基于确定性 owner-earnings DCF 的"价值低估"策略（数据层多年现金流 → 估值引擎 → Agent 工具 → 策略 YAML），并修复画像访谈 `value` 风格无策略命中的断点。

**Architecture:** 全追加式改动。数据层在两个现有 fundamental adapter 上各加一个 `get_cashflow_history` 方法，`DataFetcherManager` 按 `_market_tag` 路由；估值引擎是 `src/services/valuation_service.py` 纯函数（零网络零 LLM）；新工具 `estimate_intrinsic_value` 组合两者并注册进 tool registry；策略 YAML 显式声明 `profile_tags: {style: [value]}` 打通画像推荐链路。

**Tech Stack:** Python 3（pandas/akshare/yfinance，均为既有依赖）、pytest、React + TypeScript + vitest（Web 端小改动）。

**Spec:** `docs/superpowers/specs/2026-07-04-value-undervalued-strategy-design.md`

## Global Constraints

- 不新增 env 配置；估值常数集中在 `src/services/valuation_service.py` 顶部（`DISCOUNT_RATE=0.10`、`TERMINAL_GROWTH=0.025`、`MARGIN_OF_SAFETY=0.30`、`GROWTH_CAP=0.15`、`GROWTH_HAIRCUT=0.7`、`CAPEX_FALLBACK_RATIO=0.8`、`STAGE1_YEARS=10`）。
- 数据层 fail-open：任何失败返回空列表/`status` 字段，不抛异常、不拖垮问股主流程。
- commit message 用英文，**不添加 Co-Authored-By**（仓库规则覆盖工具默认行为）。不执行 `git push` / `git tag`。
- 新测试全部离线（mock DataFrame / MagicMock），真实网络请求不进默认 CI。
- Python 验证入口：`python -m pytest tests/<file> -v`（收尾跑 `./scripts/ci_gate.sh`）；Web 验证：`cd apps/dsa-web && npm run lint && npm run build && npx vitest run <file>`。
- A 股金额单位为元（EM 年度报表原始单位），与行情 `total_mv`（元）一致；yfinance 侧金额与 `financialCurrency` 一致，工具输出附 `currency` 元信息。

---

### Task 1: A 股年度现金流历史（AkshareFundamentalAdapter）

**Files:**
- Modify: `data_provider/fundamental_adapter.py`（`AkshareFundamentalAdapter` 类内新增方法 + 模块级常量/辅助函数）
- Test: `tests/test_cashflow_history.py`（新建）

**Interfaces:**
- Consumes: 既有 `self._call_df_candidates(candidates) -> (df, source, errors)`、`_pick_by_keywords(row, keywords)`、`_safe_float(value)`。
- Produces: `AkshareFundamentalAdapter.get_cashflow_history(stock_code: str, max_years: int = 10) -> List[dict]`，每条记录 `{"year": int, "ocf": float, "capex": float|None, "revenue": float|None, "net_profit": float|None, "currency": "CNY", "source": str}`，按 `year` 降序。Task 3 的 manager 路由与 Task 4 的估值引擎按此契约消费。

- [ ] **Step 1: Write the failing tests**

新建 `tests/test_cashflow_history.py`：

```python
# -*- coding: utf-8 -*-
"""Offline tests for yearly cash-flow history extraction (valuation data layer)."""
import os
import sys
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.fundamental_adapter import AkshareFundamentalAdapter, _em_symbol, _report_year


def test_em_symbol_prefixes():
    assert _em_symbol("600519") == "SH600519"
    assert _em_symbol("000001") == "SZ000001"
    assert _em_symbol("300750") == "SZ300750"
    assert _em_symbol("920001") == "BJ920001"
    assert _em_symbol("430047") == "BJ430047"


def test_report_year_parses_common_formats():
    assert _report_year("2025-12-31 00:00:00") == 2025
    assert _report_year("2024-12-31") == 2024
    assert _report_year(None) is None
    assert _report_year("bad") is None


def _em_cashflow_df():
    return pd.DataFrame({
        "REPORT_DATE": ["2025-12-31 00:00:00", "2024-12-31 00:00:00", "2023-12-31 00:00:00"],
        "NETCASH_OPERATE": [110e8, 100e8, 90e8],
        "CONSTRUCT_LONG_ASSET": [20e8, 18e8, 15e8],
    })


def _em_profit_df():
    return pd.DataFrame({
        "REPORT_DATE": ["2025-12-31 00:00:00", "2024-12-31 00:00:00"],
        "TOTAL_OPERATE_INCOME": [500e8, 450e8],
        "PARENT_NETPROFIT": [120e8, 110e8],
    })


def test_akshare_cashflow_history_merges_profit_by_year():
    adapter = AkshareFundamentalAdapter()

    def fake_call(candidates):
        fn = candidates[0][0]
        if fn == "stock_cash_flow_sheet_by_yearly_em":
            return _em_cashflow_df(), "stock_cash_flow_sheet_by_yearly_em", []
        return _em_profit_df(), "stock_profit_sheet_by_yearly_em", []

    with patch.object(adapter, "_call_df_candidates", side_effect=fake_call):
        records = adapter.get_cashflow_history("600519")

    assert [r["year"] for r in records] == [2025, 2024, 2023]
    assert records[0]["ocf"] == 110e8
    assert records[0]["capex"] == 20e8
    assert records[0]["revenue"] == 500e8
    assert records[0]["net_profit"] == 120e8
    # 2023 no profit row -> supplementary fields tolerated as None
    assert records[2]["revenue"] is None
    assert records[0]["currency"] == "CNY"


def test_akshare_cashflow_history_chinese_columns():
    adapter = AkshareFundamentalAdapter()
    df = pd.DataFrame({
        "报告期": ["2025-12-31", "2024-12-31"],
        "经营活动产生的现金流量净额": [50e8, 45e8],
        "购建固定资产、无形资产和其他长期资产支付的现金": [10e8, 9e8],
    })

    def fake_call(candidates):
        if candidates[0][0] == "stock_cash_flow_sheet_by_yearly_em":
            return df, "stock_cash_flow_sheet_by_yearly_em", []
        return None, None, ["profit_unavailable"]

    with patch.object(adapter, "_call_df_candidates", side_effect=fake_call):
        records = adapter.get_cashflow_history("000001")

    assert len(records) == 2
    assert records[0]["ocf"] == 50e8
    assert records[0]["capex"] == 10e8
    assert records[0]["revenue"] is None


def test_akshare_cashflow_history_fail_open():
    adapter = AkshareFundamentalAdapter()
    with patch.object(adapter, "_call_df_candidates", return_value=(None, None, ["boom"])):
        assert adapter.get_cashflow_history("600519") == []


def test_akshare_cashflow_history_caps_years():
    adapter = AkshareFundamentalAdapter()
    df = pd.DataFrame({
        "REPORT_DATE": [f"{y}-12-31" for y in range(2025, 2010, -1)],
        "NETCASH_OPERATE": [float(i) for i in range(15)],
    })

    def fake_call(candidates):
        if candidates[0][0] == "stock_cash_flow_sheet_by_yearly_em":
            return df, "src", []
        return None, None, []

    with patch.object(adapter, "_call_df_candidates", side_effect=fake_call):
        records = adapter.get_cashflow_history("600519", max_years=10)
    assert len(records) == 10
    assert records[0]["year"] == 2025
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cashflow_history.py -v`
Expected: FAIL — `ImportError: cannot import name '_em_symbol'`

- [ ] **Step 3: Implement in `data_provider/fundamental_adapter.py`**

模块级（放在 `_DIVIDEND_KEYWORD_MAP` 附近）：

```python
_CASHFLOW_HISTORY_KEYWORDS = {
    "report_date": ["REPORT_DATE", "报告期", "报告日期", "截止日期"],
    "ocf": ["NETCASH_OPERATE", "经营活动产生的现金流量净额", "经营现金流"],
    "capex": ["CONSTRUCT_LONG_ASSET", "购建固定资产"],
    "revenue": ["TOTAL_OPERATE_INCOME", "营业总收入", "营业收入"],
    "net_profit": ["PARENT_NETPROFIT", "归属于母公司", "归母净利润", "净利润"],
}

_BJ_CODE_PREFIXES = ("92", "43", "83", "87", "88")


def _em_symbol(stock_code: str) -> str:
    """Convert a bare A-share code to the EM statement symbol (SH/SZ/BJ prefix)."""
    code = str(stock_code).strip()
    if code.startswith("6"):
        return f"SH{code}"
    if code.startswith(_BJ_CODE_PREFIXES):
        return f"BJ{code}"
    return f"SZ{code}"


def _report_year(value: Any) -> Optional[int]:
    """Extract a 4-digit year from an EM report-date value."""
    if value is None:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None
```

（`re`、`Any`、`Optional` 已在该文件 import；若缺 `re` 则补。）

`AkshareFundamentalAdapter` 类内（`get_fundamental_bundle` 之后）：

```python
    def get_cashflow_history(self, stock_code: str, max_years: int = 10) -> List[Dict[str, Any]]:
        """Yearly cash-flow history for valuation. Fail-open: [] on any failure."""
        symbol = _em_symbol(stock_code)
        cash_df, cash_source, _cash_errors = self._call_df_candidates([
            ("stock_cash_flow_sheet_by_yearly_em", {"symbol": symbol}),
        ])
        if cash_df is None or cash_df.empty:
            return []

        profit_by_year: Dict[int, Dict[str, Any]] = {}
        profit_df, _, _ = self._call_df_candidates([
            ("stock_profit_sheet_by_yearly_em", {"symbol": symbol}),
        ])
        if profit_df is not None and not profit_df.empty:
            for _, row in profit_df.iterrows():
                year = _report_year(_pick_by_keywords(row, _CASHFLOW_HISTORY_KEYWORDS["report_date"]))
                if year is None:
                    continue
                profit_by_year[year] = {
                    "revenue": _safe_float(_pick_by_keywords(row, _CASHFLOW_HISTORY_KEYWORDS["revenue"])),
                    "net_profit": _safe_float(_pick_by_keywords(row, _CASHFLOW_HISTORY_KEYWORDS["net_profit"])),
                }

        records: List[Dict[str, Any]] = []
        for _, row in cash_df.iterrows():
            year = _report_year(_pick_by_keywords(row, _CASHFLOW_HISTORY_KEYWORDS["report_date"]))
            ocf = _safe_float(_pick_by_keywords(row, _CASHFLOW_HISTORY_KEYWORDS["ocf"]))
            if year is None or ocf is None:
                continue
            extra = profit_by_year.get(year, {})
            records.append({
                "year": year,
                "ocf": ocf,
                "capex": _safe_float(_pick_by_keywords(row, _CASHFLOW_HISTORY_KEYWORDS["capex"])),
                "revenue": extra.get("revenue"),
                "net_profit": extra.get("net_profit"),
                "currency": "CNY",
                "source": cash_source or "akshare",
            })
        records.sort(key=lambda r: r["year"], reverse=True)
        return records[:max_years]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cashflow_history.py -v`
Expected: PASS（全部 6 个用例）

- [ ] **Step 5: Commit**

```bash
git add data_provider/fundamental_adapter.py tests/test_cashflow_history.py
git commit -m "feat(data): add yearly cash-flow history extraction for A-share valuation"
```

---

### Task 2: 美股/港股年度现金流历史（YfinanceFundamentalAdapter）

**Files:**
- Modify: `data_provider/yfinance_fundamental_adapter.py`
- Test: `tests/test_cashflow_history.py`（追加）

**Interfaces:**
- Consumes: 既有 `_convert_to_yf_symbol(stock_code)`、`_pick_row(df, keys)`、`_safe_float(value)`。
- Produces: `YfinanceFundamentalAdapter.get_cashflow_history(stock_code: str, max_years: int = 10) -> List[dict]`，记录契约与 Task 1 相同（`currency` 取 `financialCurrency`/`currency`，缺省 `""`）。

- [ ] **Step 1: Write the failing tests**

在 `tests/test_cashflow_history.py` 末尾追加：

```python
from unittest.mock import MagicMock

from data_provider.yfinance_fundamental_adapter import YfinanceFundamentalAdapter


def _yf_annual_cashflow():
    cols = [pd.Timestamp("2025-09-30"), pd.Timestamp("2024-09-30"),
            pd.Timestamp("2023-09-30"), pd.Timestamp("2022-09-30")]
    return pd.DataFrame(
        [[120e9, 110e9, 105e9, 100e9], [-11e9, -10e9, -10e9, -9e9]],
        index=["Operating Cash Flow", "Capital Expenditure"],
        columns=cols,
    )


def _yf_annual_income():
    cols = [pd.Timestamp("2025-09-30"), pd.Timestamp("2024-09-30")]
    return pd.DataFrame(
        [[400e9, 380e9], [95e9, 90e9]],
        index=["Total Revenue", "Net Income"],
        columns=cols,
    )


def _mock_yf_ticker():
    ticker = MagicMock()
    ticker.cashflow = _yf_annual_cashflow()
    ticker.income_stmt = _yf_annual_income()
    ticker.get_info.return_value = {"financialCurrency": "USD"}
    ticker.info = {"financialCurrency": "USD"}
    return ticker


def test_yfinance_cashflow_history_annual_records():
    adapter = YfinanceFundamentalAdapter()
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = _mock_yf_ticker()
    with patch.dict(sys.modules, {"yfinance": fake_yf}):
        records = adapter.get_cashflow_history("AAPL")

    assert [r["year"] for r in records] == [2025, 2024, 2023, 2022]
    assert records[0]["ocf"] == 120e9
    assert records[0]["capex"] == -11e9  # raw sign preserved; engine uses abs()
    assert records[0]["revenue"] == 400e9
    assert records[0]["net_profit"] == 95e9
    assert records[2]["revenue"] is None
    assert records[0]["currency"] == "USD"


def test_yfinance_cashflow_history_fail_open_on_ticker_error():
    adapter = YfinanceFundamentalAdapter()
    broken = MagicMock()
    type(broken).cashflow = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = broken
    with patch.dict(sys.modules, {"yfinance": fake_yf}):
        assert adapter.get_cashflow_history("AAPL") == []


def test_yfinance_cashflow_history_empty_symbol():
    adapter = YfinanceFundamentalAdapter()
    assert adapter.get_cashflow_history("") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cashflow_history.py -k yfinance -v`
Expected: FAIL — `AttributeError: ... has no attribute 'get_cashflow_history'`

- [ ] **Step 3: Implement in `data_provider/yfinance_fundamental_adapter.py`**

模块级常量（放在 `_CASHFLOW_OP_KEYS` 附近）：

```python
_CF_HIST_OP_KEYS = (
    "Operating Cash Flow",
    "Total Cash From Operating Activities",
    "Cash Flow From Continuing Operating Activities",
)
_CF_HIST_CAPEX_KEYS = ("Capital Expenditure", "Capital Expenditures")
_IS_HIST_REVENUE_KEYS = ("Total Revenue", "Operating Revenue")
_IS_HIST_NET_INCOME_KEYS = ("Net Income", "Net Income Common Stockholders")
```

`YfinanceFundamentalAdapter` 类内：

```python
    def get_cashflow_history(self, stock_code: str, max_years: int = 10) -> List[Dict[str, Any]]:
        """Yearly (annual) cash-flow history via yfinance. Fail-open: []."""
        try:
            import yfinance as yf
        except Exception:
            return []
        symbol = _convert_to_yf_symbol(stock_code)
        if not symbol:
            return []
        ticker = yf.Ticker(symbol)
        try:
            cashflow_df = ticker.cashflow
        except Exception:
            return []
        if cashflow_df is None or getattr(cashflow_df, "empty", True):
            return []

        try:
            income_df = ticker.income_stmt
        except Exception:
            income_df = None
        if income_df is not None and getattr(income_df, "empty", True):
            income_df = None

        currency = ""
        try:
            info = ticker.get_info() if hasattr(ticker, "get_info") else (ticker.info or {})
            if isinstance(info, dict):
                currency = str(info.get("financialCurrency") or info.get("currency") or "")
        except Exception:
            currency = ""

        ocf_row = _pick_row(cashflow_df, _CF_HIST_OP_KEYS)
        capex_row = _pick_row(cashflow_df, _CF_HIST_CAPEX_KEYS)
        revenue_row = _pick_row(income_df, _IS_HIST_REVENUE_KEYS) if income_df is not None else None
        ni_row = _pick_row(income_df, _IS_HIST_NET_INCOME_KEYS) if income_df is not None else None

        records: List[Dict[str, Any]] = []
        for col in cashflow_df.columns:
            year = getattr(col, "year", None)
            if year is None:
                match = re.search(r"(19|20)\d{2}", str(col))
                year = int(match.group(0)) if match else None
            ocf = _safe_float(ocf_row.get(col)) if ocf_row is not None else None
            if year is None or ocf is None:
                continue
            records.append({
                "year": int(year),
                "ocf": ocf,
                "capex": _safe_float(capex_row.get(col)) if capex_row is not None else None,
                "revenue": _safe_float(revenue_row.get(col)) if revenue_row is not None else None,
                "net_profit": _safe_float(ni_row.get(col)) if ni_row is not None else None,
                "currency": currency,
                "source": "yfinance",
            })
        records.sort(key=lambda r: r["year"], reverse=True)
        return records[:max_years]
```

文件顶部若无 `import re` 则补上。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cashflow_history.py -v`
Expected: PASS（Task 1 + Task 2 全部用例）

- [ ] **Step 5: Commit**

```bash
git add data_provider/yfinance_fundamental_adapter.py tests/test_cashflow_history.py
git commit -m "feat(data): add yearly cash-flow history for HK/US via yfinance"
```

---

### Task 3: Manager 市场路由（DataFetcherManager.get_cashflow_history）

**Files:**
- Modify: `data_provider/base.py`（`DataFetcherManager` 类内，放在 `get_fundamental_context` 附近）
- Test: `tests/test_cashflow_history.py`（追加）

**Interfaces:**
- Consumes: Task 1/2 的两个 adapter 方法；既有 `_market_tag(code)`、`normalize_stock_code(code)`、`self._fundamental_adapter`、`self._yfinance_fundamental_adapter`。
- Produces: `DataFetcherManager.get_cashflow_history(stock_code: str, max_years: int = 10) -> List[dict]`。Task 5 的工具按此消费。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_cashflow_history.py`：

```python
from data_provider.base import DataFetcherManager


def _manager_with_stub_adapters():
    manager = DataFetcherManager.__new__(DataFetcherManager)  # skip heavy __init__
    manager._fundamental_adapter = MagicMock()
    manager._yfinance_fundamental_adapter = MagicMock()
    manager._fundamental_adapter.get_cashflow_history.return_value = [{"year": 2025, "ocf": 1.0}]
    manager._yfinance_fundamental_adapter.get_cashflow_history.return_value = [{"year": 2025, "ocf": 2.0}]
    return manager


def test_manager_routes_cn_to_akshare_adapter():
    manager = _manager_with_stub_adapters()
    records = manager.get_cashflow_history("600519")
    assert records[0]["ocf"] == 1.0
    manager._fundamental_adapter.get_cashflow_history.assert_called_once()


def test_manager_routes_hk_us_to_yfinance_adapter():
    manager = _manager_with_stub_adapters()
    assert manager.get_cashflow_history("AAPL")[0]["ocf"] == 2.0
    assert manager.get_cashflow_history("hk00700")[0]["ocf"] == 2.0


def test_manager_cashflow_history_fail_open():
    manager = _manager_with_stub_adapters()
    manager._fundamental_adapter.get_cashflow_history.side_effect = RuntimeError("boom")
    assert manager.get_cashflow_history("600519") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cashflow_history.py -k manager -v`
Expected: FAIL — `AttributeError: 'DataFetcherManager' object has no attribute 'get_cashflow_history'`

- [ ] **Step 3: Implement in `data_provider/base.py`**

`DataFetcherManager` 类内，紧邻 `get_fundamental_context`：

```python
    def get_cashflow_history(self, stock_code: str, max_years: int = 10) -> List[Dict[str, Any]]:
        """Yearly cash-flow history for intrinsic-value estimation.

        Routes CN codes to akshare and HK/US codes to yfinance. Fail-open:
        returns [] on any failure so valuation degrades instead of breaking
        the analysis flow.
        """
        try:
            code = normalize_stock_code(stock_code)
            market = _market_tag(code)
            if market in {"us", "hk"}:
                return self._yfinance_fundamental_adapter.get_cashflow_history(code, max_years=max_years)
            return self._fundamental_adapter.get_cashflow_history(code, max_years=max_years)
        except Exception as exc:
            logger.warning("get_cashflow_history failed for %s: %s", stock_code, exc)
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cashflow_history.py -v`
Expected: PASS（全部用例）

- [ ] **Step 5: Commit**

```bash
git add data_provider/base.py tests/test_cashflow_history.py
git commit -m "feat(data): route cash-flow history by market in DataFetcherManager"
```

---

### Task 4: 估值引擎（valuation_service，纯函数）

**Files:**
- Create: `src/services/valuation_service.py`
- Test: `tests/test_valuation_service.py`（新建）

**Interfaces:**
- Consumes: 无运行时依赖（纯标准库）；输入为 Task 1-3 契约的记录列表。
- Produces: `estimate_intrinsic_value(yearly_records: List[dict], market_cap: float|None = None, shares_outstanding: float|None = None) -> dict`，返回 `{status, assumptions, valuation, verdict, data_confidence, yearly_series}`。`verdict ∈ {undervalued, fair, overvalued, unknown, insufficient_data, not_applicable}`（`unknown` = 数据足够但缺市值，无法给折价判定——对 spec 枚举的一处补充）。Task 5 的工具按此消费。

- [ ] **Step 1: Write the failing tests**

新建 `tests/test_valuation_service.py`：

```python
# -*- coding: utf-8 -*-
"""Deterministic tests for the owner-earnings DCF valuation engine."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.valuation_service import (
    CAPEX_FALLBACK_RATIO,
    GROWTH_CAP,
    GROWTH_HAIRCUT,
    MARGIN_OF_SAFETY,
    estimate_intrinsic_value,
)


def _flat_records(n=5, ocf=100.0, capex=20.0):
    return [{"year": 2025 - i, "ocf": ocf, "capex": capex} for i in range(n)]


def test_flat_fcf_valuation_shape_and_bounds():
    result = estimate_intrinsic_value(_flat_records())
    assert result["status"] == "ok"
    assert result["data_confidence"] == "high"
    assert result["assumptions"]["fcf_base"] == 80.0  # median of flat 100-20
    assert result["assumptions"]["g1"] == 0.0  # flat history -> no growth credit
    base = result["valuation"]["base"]
    # zero-growth 10y + terminal at r=10%, g2=2.5%: sane PV multiple band
    assert 8 * 80 < base < 20 * 80
    assert result["valuation"]["conservative"] <= base
    assert result["verdict"] == "unknown"  # no market cap supplied


def test_verdict_boundaries_against_base_value():
    records = _flat_records()
    base = estimate_intrinsic_value(records)["valuation"]["base"]
    assert estimate_intrinsic_value(records, market_cap=base * (1 - MARGIN_OF_SAFETY - 0.01))["verdict"] == "undervalued"
    assert estimate_intrinsic_value(records, market_cap=base * 0.9)["verdict"] == "fair"
    assert estimate_intrinsic_value(records, market_cap=base * 1.01)["verdict"] == "overvalued"


def test_growth_is_clamped_and_haircut():
    # FCF doubling yearly -> raw CAGR 100%, must clamp to cap*haircut
    records = [{"year": 2025 - i, "ocf": 100.0 * (2 ** -i), "capex": 0.0} for i in range(5)]
    result = estimate_intrinsic_value(records)
    assert abs(result["assumptions"]["g1"] - GROWTH_CAP * GROWTH_HAIRCUT) < 1e-9


def test_capex_missing_uses_conservative_fallback():
    records = [{"year": 2025 - i, "ocf": 100.0, "capex": None} for i in range(5)]
    result = estimate_intrinsic_value(records)
    assert result["assumptions"]["fcf_base"] == 100.0 * CAPEX_FALLBACK_RATIO
    assert all(item["fcf"] == 100.0 * CAPEX_FALLBACK_RATIO for item in result["yearly_series"])


def test_negative_capex_sign_normalized():
    # yfinance reports capex as negative outflow; engine must use abs()
    a = estimate_intrinsic_value([{"year": 2025 - i, "ocf": 100.0, "capex": -20.0} for i in range(5)])
    b = estimate_intrinsic_value([{"year": 2025 - i, "ocf": 100.0, "capex": 20.0} for i in range(5)])
    assert a["valuation"]["base"] == b["valuation"]["base"]


def test_negative_fcf_base_not_applicable():
    records = [{"year": 2025 - i, "ocf": -50.0, "capex": 10.0} for i in range(5)]
    result = estimate_intrinsic_value(records, market_cap=1000.0)
    assert result["status"] == "not_applicable"
    assert result["verdict"] == "not_applicable"
    assert result["valuation"] == {}


def test_insufficient_years():
    result = estimate_intrinsic_value(_flat_records(n=2), market_cap=1000.0)
    assert result["status"] == "insufficient_data"
    assert result["verdict"] == "insufficient_data"
    assert result["data_confidence"] == "insufficient"


def test_medium_confidence_with_four_years():
    result = estimate_intrinsic_value(_flat_records(n=4))
    assert result["status"] == "ok"
    assert result["data_confidence"] == "medium"


def test_per_share_when_shares_given():
    result = estimate_intrinsic_value(_flat_records(), shares_outstanding=10.0)
    assert abs(result["valuation"]["per_share"] - result["valuation"]["base"] / 10.0) < 1e-9


def test_records_missing_ocf_are_skipped():
    records = _flat_records() + [{"year": 2019, "ocf": None, "capex": 1.0}]
    result = estimate_intrinsic_value(records)
    assert result["assumptions"]["years_used"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_valuation_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.valuation_service'`

- [ ] **Step 3: Create `src/services/valuation_service.py`**

```python
# -*- coding: utf-8 -*-
"""Deterministic owner-earnings DCF valuation (Buffett/Munger/段永平 style).

Pure functions: no LLM, no network, no I/O — inputs are passed in by callers
(see src/agent/tools/valuation_tools.py). All numbers are reproducible and
unit-tested.

Constant rationale (deliberately conservative, not configurable by design —
see docs/superpowers/specs/2026-07-04-value-undervalued-strategy-design.md):

- DISCOUNT_RATE 10%: long-run equity opportunity-cost benchmark.
- TERMINAL_GROWTH 2.5%: ~nominal GDP floor; keeps terminal value modest.
- MARGIN_OF_SAFETY 30%: classic value-investing buy threshold.
- GROWTH_CAP 15% + GROWTH_HAIRCUT 0.7: clamp optimistic FCF history.
- CAPEX_FALLBACK_RATIO 0.8: FCF ~= 0.8 x OCF when capex is unavailable.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

DISCOUNT_RATE = 0.10
TERMINAL_GROWTH = 0.025
MARGIN_OF_SAFETY = 0.30
GROWTH_CAP = 0.15
GROWTH_HAIRCUT = 0.7
CAPEX_FALLBACK_RATIO = 0.8
STAGE1_YEARS = 10
MIN_YEARS = 3
HIGH_CONFIDENCE_YEARS = 5


def _record_fcf(record: Dict[str, Any]) -> Optional[float]:
    ocf = record.get("ocf")
    if ocf is None:
        return None
    capex = record.get("capex")
    if capex is None:
        return ocf * CAPEX_FALLBACK_RATIO
    # yfinance reports capex as a negative outflow, akshare as positive spend
    return ocf - abs(capex)


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _historical_growth(fcfs_desc: List[float]) -> float:
    """Clamped, haircut FCF CAGR from oldest to newest (0 when not computable)."""
    if len(fcfs_desc) < 2:
        return 0.0
    newest, oldest = fcfs_desc[0], fcfs_desc[-1]
    if newest <= 0 or oldest <= 0:
        return 0.0
    years = len(fcfs_desc) - 1
    cagr = (newest / oldest) ** (1.0 / years) - 1.0
    return max(0.0, min(cagr, GROWTH_CAP)) * GROWTH_HAIRCUT


def _dcf(base_fcf: float, g_start: float) -> float:
    """Two-stage DCF: growth transitions linearly from g_start to TERMINAL_GROWTH."""
    pv = 0.0
    fcf = base_fcf
    for i in range(1, STAGE1_YEARS + 1):
        t = (i - 1) / max(STAGE1_YEARS - 1, 1)
        g = g_start + (TERMINAL_GROWTH - g_start) * t
        fcf *= (1.0 + g)
        pv += fcf / (1.0 + DISCOUNT_RATE) ** i
    terminal = fcf * (1.0 + TERMINAL_GROWTH) / (DISCOUNT_RATE - TERMINAL_GROWTH)
    pv += terminal / (1.0 + DISCOUNT_RATE) ** STAGE1_YEARS
    return pv


def estimate_intrinsic_value(
    yearly_records: Optional[List[Dict[str, Any]]],
    market_cap: Optional[float] = None,
    shares_outstanding: Optional[float] = None,
) -> Dict[str, Any]:
    """Estimate a conservative intrinsic-value range from yearly FCF history.

    Verdict semantics:
    - undervalued: market cap trades >= MARGIN_OF_SAFETY below base value
    - fair / overvalued: inside the margin band / above base value
    - unknown: valuation computed but no market cap to compare against
    - insufficient_data: fewer than MIN_YEARS usable years
    - not_applicable: non-positive FCF base (value approach does not apply)
    """
    records = sorted(
        [r for r in (yearly_records or []) if r.get("year") is not None and r.get("ocf") is not None],
        key=lambda r: r["year"],
        reverse=True,
    )[:STAGE1_YEARS]

    series: List[Dict[str, Any]] = []
    for record in records:
        item = dict(record)
        item["fcf"] = _record_fcf(record)
        series.append(item)
    fcfs = [item["fcf"] for item in series if item["fcf"] is not None]

    n = len(fcfs)
    confidence = (
        "high" if n >= HIGH_CONFIDENCE_YEARS
        else "medium" if n >= MIN_YEARS
        else "insufficient"
    )
    result: Dict[str, Any] = {
        "status": "ok",
        "assumptions": {},
        "valuation": {},
        "verdict": "insufficient_data",
        "data_confidence": confidence,
        "yearly_series": series,
    }
    if n < MIN_YEARS:
        result["status"] = "insufficient_data"
        return result

    fcf_base = _median(fcfs)
    if fcf_base <= 0:
        result["status"] = "not_applicable"
        result["verdict"] = "not_applicable"
        result["assumptions"] = {"fcf_base": fcf_base, "reason": "negative_fcf_base"}
        return result

    g1 = _historical_growth(fcfs)
    base_value = _dcf(fcf_base, g1)
    conservative_value = _dcf(fcf_base, g1 / 2.0)
    discount = (1.0 - market_cap / base_value) if market_cap else None

    result["assumptions"] = {
        "fcf_base": fcf_base,
        "g1": g1,
        "g2": TERMINAL_GROWTH,
        "discount_rate": DISCOUNT_RATE,
        "stage1_years": STAGE1_YEARS,
        "margin_of_safety": MARGIN_OF_SAFETY,
        "years_used": n,
    }
    result["valuation"] = {
        "conservative": conservative_value,
        "base": base_value,
        "market_cap": market_cap,
        "per_share": (base_value / shares_outstanding) if shares_outstanding else None,
        "discount": discount,
    }
    if not market_cap or market_cap <= 0:
        result["verdict"] = "unknown"
    elif discount >= MARGIN_OF_SAFETY:
        result["verdict"] = "undervalued"
    elif market_cap > base_value:
        result["verdict"] = "overvalued"
    else:
        result["verdict"] = "fair"
    return result
```

（`re` 未用到则删掉该 import。）

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_valuation_service.py -v`
Expected: PASS（全部 10 个用例）

- [ ] **Step 5: Commit**

```bash
git add src/services/valuation_service.py tests/test_valuation_service.py
git commit -m "feat(valuation): add deterministic owner-earnings DCF engine"
```

---

### Task 5: Agent 工具 estimate_intrinsic_value + 注册 + 显示名

**Files:**
- Create: `src/agent/tools/valuation_tools.py`
- Modify: `src/agent/factory.py:183-190`（import + 注册循环）
- Modify: `api/v1/endpoints/agent.py:20-37`（`TOOL_DISPLAY_NAMES`）
- Test: `tests/test_valuation_tool.py`（新建）

**Interfaces:**
- Consumes: Task 3 `manager.get_cashflow_history(code)`、既有 `manager.get_realtime_quote(code, log_final_failure=False)`（`.total_mv` 单位为元）、Task 4 引擎、`src.agent.tools.data_tools._get_fetcher_manager`。
- Produces: registry 内名为 `estimate_intrinsic_value` 的工具，handler 返回 Task 4 的结果 dict + `stock_code` 字段；`ALL_VALUATION_TOOLS: List[ToolDefinition]`。Task 6 策略 YAML 在 `required_tools` 中引用该名字。

- [ ] **Step 1: Write the failing tests**

新建 `tests/test_valuation_tool.py`：

```python
# -*- coding: utf-8 -*-
"""Contract tests for the estimate_intrinsic_value agent tool."""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent.tools.valuation_tools import (
    ALL_VALUATION_TOOLS,
    _handle_estimate_intrinsic_value,
)


def _records(n=5):
    return [{"year": 2025 - i, "ocf": 100e8, "capex": 20e8} for i in range(n)]


def test_tool_definition_registered_name():
    assert [t.name for t in ALL_VALUATION_TOOLS] == ["estimate_intrinsic_value"]


def test_handler_contract_fields():
    manager = MagicMock()
    manager.get_cashflow_history.return_value = _records()
    quote = MagicMock()
    quote.total_mv = 500e8
    manager.get_realtime_quote.return_value = quote

    with patch("src.agent.tools.valuation_tools._get_fetcher_manager", return_value=manager):
        result = _handle_estimate_intrinsic_value("600519")

    assert result["stock_code"] == "600519"
    for key in ("status", "assumptions", "valuation", "verdict", "data_confidence", "yearly_series"):
        assert key in result
    assert result["status"] == "ok"
    assert result["valuation"]["market_cap"] == 500e8


def test_handler_quote_failure_degrades_to_unknown_verdict():
    manager = MagicMock()
    manager.get_cashflow_history.return_value = _records()
    manager.get_realtime_quote.side_effect = RuntimeError("quote down")

    with patch("src.agent.tools.valuation_tools._get_fetcher_manager", return_value=manager):
        result = _handle_estimate_intrinsic_value("600519")

    assert result["status"] == "ok"
    assert result["verdict"] == "unknown"


def test_handler_history_failure_returns_error_status():
    manager = MagicMock()
    manager.get_cashflow_history.side_effect = RuntimeError("boom")

    with patch("src.agent.tools.valuation_tools._get_fetcher_manager", return_value=manager):
        result = _handle_estimate_intrinsic_value("600519")

    assert result["status"] == "error"
    assert "boom" in result["error"]


def test_tool_registered_in_factory_registry():
    from src.agent import factory

    factory._TOOL_REGISTRY = None  # force rebuild
    registry = factory.get_tool_registry()
    assert "estimate_intrinsic_value" in registry
    factory._TOOL_REGISTRY = None


def test_tool_display_name_present():
    from api.v1.endpoints.agent import TOOL_DISPLAY_NAMES

    assert TOOL_DISPLAY_NAMES.get("estimate_intrinsic_value") == "估值计算"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_valuation_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.tools.valuation_tools'`

- [ ] **Step 3: Create `src/agent/tools/valuation_tools.py`**

```python
# -*- coding: utf-8 -*-
"""Agent tool: deterministic intrinsic-value estimation (owner-earnings DCF).

Composes the market-routed cash-flow history (DataFetcherManager) with the
pure valuation engine (src/services/valuation_service). All failures degrade
to a structured status instead of raising, so a valuation outage never breaks
the chat/analysis flow.
"""
import logging

from src.agent.tools.data_tools import _get_fetcher_manager
from src.agent.tools.registry import ToolDefinition, ToolParameter
from src.services.valuation_service import estimate_intrinsic_value as _estimate

logger = logging.getLogger(__name__)


def _handle_estimate_intrinsic_value(stock_code: str) -> dict:
    manager = _get_fetcher_manager()
    try:
        records = manager.get_cashflow_history(stock_code)
    except Exception as exc:
        logger.warning("estimate_intrinsic_value history failed for %s: %s", stock_code, exc)
        return {"status": "error", "error": f"cashflow_history:{exc}", "stock_code": stock_code}

    market_cap = None
    try:
        quote = manager.get_realtime_quote(stock_code, log_final_failure=False)
        market_cap = getattr(quote, "total_mv", None) if quote else None
    except Exception as exc:
        logger.info("estimate_intrinsic_value quote unavailable for %s: %s", stock_code, exc)

    result = _estimate(records, market_cap=market_cap)
    result["stock_code"] = stock_code
    return result


estimate_intrinsic_value_tool = ToolDefinition(
    name="estimate_intrinsic_value",
    description=(
        "基于多年经营现金流与资本开支的确定性 DCF 估值（巴菲特式 owner earnings）。"
        "返回内在价值保守/基准区间、相对当前市值的折价率、安全边际判定与所用假设。"
        "适用于价值投资类策略；现金流为负或历史不足 3 年时会明确降级，不给硬结论。"
    ),
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code, e.g., '600519', 'hk00700', 'AAPL'",
        ),
    ],
    handler=_handle_estimate_intrinsic_value,
    category="analysis",
)

ALL_VALUATION_TOOLS = [estimate_intrinsic_value_tool]
```

- [ ] **Step 4: Wire into factory and display names**

`src/agent/factory.py` `get_tool_registry()` 内：

```python
    from src.agent.tools.backtest_tools import ALL_BACKTEST_TOOLS
    from src.agent.tools.valuation_tools import ALL_VALUATION_TOOLS

    registry = ToolRegistry()
    for tool_fn in ALL_DATA_TOOLS + ALL_ANALYSIS_TOOLS + ALL_SEARCH_TOOLS + ALL_MARKET_TOOLS + ALL_BACKTEST_TOOLS + ALL_VALUATION_TOOLS:
        registry.register(tool_fn)
```

`api/v1/endpoints/agent.py` `TOOL_DISPLAY_NAMES` 末尾追加：

```python
    "estimate_intrinsic_value":   "估值计算",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_valuation_tool.py -v`
Expected: PASS（全部 6 个用例）

- [ ] **Step 6: Commit**

```bash
git add src/agent/tools/valuation_tools.py src/agent/factory.py api/v1/endpoints/agent.py tests/test_valuation_tool.py
git commit -m "feat(agent): add estimate_intrinsic_value tool backed by DCF engine"
```

---

### Task 6: 价值低估策略 YAML

**Files:**
- Create: `strategies/value_undervalued.yaml`
- Test: `tests/test_value_undervalued_skill.py`（新建）

**Interfaces:**
- Consumes: Task 5 的工具名 `estimate_intrinsic_value`；既有 skill loader（`src/agent/skills/base.py` 已解析 `profile_tags`）。
- Produces: skill id `value_undervalued`（`category: value`，显式 `profile_tags`）。Task 7 推荐回归、Task 8 Web 分组依赖它。

- [ ] **Step 1: Write the failing test**

新建 `tests/test_value_undervalued_skill.py`：

```python
# -*- coding: utf-8 -*-
"""Loader-level contract tests for the value_undervalued strategy YAML."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.agent.factory import get_skill_manager


def _skill():
    return get_skill_manager().get("value_undervalued")


def test_skill_loads_with_value_category():
    skill = _skill()
    assert skill is not None
    assert skill.display_name == "价值低估"
    assert skill.category == "value"


def test_skill_declares_explicit_value_profile_tags():
    skill = _skill()
    assert skill.profile_tags.get("style") == ["value"]
    assert skill.profile_tags.get("horizon") == ["long"]
    assert set(skill.profile_tags.get("risk", [])) == {"conservative", "balanced"}


def test_skill_requires_valuation_tool():
    skill = _skill()
    assert "estimate_intrinsic_value" in skill.required_tools


def test_skill_instructions_mandate_tool_call():
    skill = _skill()
    assert "estimate_intrinsic_value" in skill.instructions
    assert "安全边际" in skill.instructions
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_value_undervalued_skill.py -v`
Expected: FAIL — `skill is None`（YAML 不存在）

- [ ] **Step 3: Create `strategies/value_undervalued.yaml`**

```yaml
# Value Undervalued Strategy / 价值低估

name: value_undervalued
display_name: 价值低估
description: 巴菲特/芒格式价值投资：用多年自由现金流折现估算内在价值，只在市价显著低于内在价值（安全边际≥30%）时买入。
category: value
core_rules: [2, 3, 5]
required_tools:
  - get_stock_info
  - get_realtime_quote
  - estimate_intrinsic_value
  - search_stock_news
aliases: [价值, 价值投资, 低估, 价值低估, 安全边际]
default_priority: 50

profile_tags:
  style: [value]
  horizon: [long]
  risk: [conservative, balanced]

instructions: |
  **价值低估策略（Value Undervalued Strategy）**

  方法论：企业价值 = 存续期内可以拿出来的自由现金流的折现值（巴菲特/芒格/段永平）。
  估算必须保守，结论必须留安全边际；买入的理由只有一个——价格明显低于价值。

  分析框架（按顺序执行）：

  1. **能力圈检查**
     - 用 `get_stock_info` 查看收入、利润、经营现金流是否长期方向一致、可理解。
     - 收入利润长期背离、现金流与利润严重不匹配、商业模式看不懂的公司，
       直接降低确定性并提示回避，不要硬给估值结论。
     - 银行/保险等金融股与强周期股：现金流口径特殊，本策略估值参考性有限，必须明确提示。

  2. **好生意检查**
     - ROE 水平与稳定性、毛利率、经营现金流对净利润的覆盖度、历史分红记录。
     - 现金流质量差（利润高但收不到钱）时显著下调评分。

  3. **内在价值（必须调用工具）**
     - **必须调用 `estimate_intrinsic_value` 工具获取内在价值区间，禁止自行心算估值。**
     - 引用工具返回的 assumptions（FCF 基数、增长率、折现率）向用户说明估值前提。
     - 工具返回 `not_applicable`（自由现金流为负）：按价值策略应回避，signal 不高于 hold。
     - 工具返回 `insufficient_data`：明确说明数据不足，只给观察结论，降低 confidence。
     - 工具返回 `unknown`（缺市值）：用 `get_realtime_quote` 的总市值与估值区间自行对比折价。

  4. **安全边际判定**
     - 折价率 ≥ 30%（市值低于基准内在价值三成以上）才可给 buy / strong_buy。
     - 折价不足 30%：给 hold，并明确说出"什么市值/价格才值得买"。
     - 市值高于基准内在价值：给 sell 或 hold，说明高估程度。
     - 不依据短线技术形态操作；技术趋势仅用于确认长期基本面逻辑未被证伪。

  输出要求：
  - 明确公司处于：显著低估 / 合理 / 高估 / 不适用价值估值。
  - 复述估值假设（FCF 基数、g1、折现率 10%、永续增长 2.5%），让用户看到保守程度。
  - 给出安全边际口径的买点：对应折价 30% 的市值或股价水平。

  评分调整建议：
  - 折价 ≥ 30% 且现金流质量高（OCF 稳定覆盖净利润）：`sentiment_score +15`
  - 折价 ≥ 30% 但依赖单年异常现金流或数据置信度为 medium：`sentiment_score +6`
  - 工具返回 not_applicable（负自由现金流）：`sentiment_score -12`
  - 市值高于基准内在价值（无安全边际）：`sentiment_score -10`
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_value_undervalued_skill.py -v`
Expected: PASS（全部 4 个用例）

- [ ] **Step 5: Commit**

```bash
git add strategies/value_undervalued.yaml tests/test_value_undervalued_skill.py
git commit -m "feat(strategy): add value_undervalued skill with explicit profile tags"
```

---

### Task 7: value 标签断点修复（分类推导 + growth_quality + 推荐回归）

**Files:**
- Modify: `src/agent/skills/profile_tags.py:11-16`（`_CATEGORY_DEFAULTS`）
- Modify: `strategies/growth_quality.yaml`（追加 `profile_tags` 块）
- Test: `tests/test_profile_tags.py`（追加）、`tests/test_profile_recommender.py`（追加）

**Interfaces:**
- Consumes: Task 6 的 `value_undervalued` skill；既有 `resolve_profile_tags(skill)`、`recommend_skills(answers, skills, max_count)`。
- Produces: `_CATEGORY_DEFAULTS["value"]` 推导规则；`growth_quality` 携带显式 `profile_tags: {style: [value, framework], horizon: [long, swing], risk: [balanced]}`。

- [ ] **Step 1: Write the failing tests**

`tests/test_profile_tags.py` 追加（复用该文件既有的 `_skill(**kw)` helper）：

```python
def test_value_category_derives_value_style():
    s = _skill(category="value")
    tags = resolve_profile_tags(s)
    assert tags["style"] == ["value"]
    assert tags["horizon"] == ["long"]
    assert set(tags["risk"]) == {"conservative", "balanced"}
```

`tests/test_profile_recommender.py` 追加（真实策略目录端到端回归——这是断点修复的验收测试）:

```python
def test_value_style_interview_recommends_value_undervalued_from_real_skills():
    from src.agent.factory import get_skill_manager

    skills = get_skill_manager().list_skills()
    answers = {"horizon": "long", "risk": "balanced", "style": "value", "watch": "low"}
    result = recommend_skills(answers, skills, max_count=3)
    assert "value_undervalued" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_profile_tags.py tests/test_profile_recommender.py -v`
Expected: 新增两个用例 FAIL（value 类目推导落到 trend 默认；真实策略推荐不含 value_undervalued——注意 Task 6 已让 value_undervalued 通过显式 tags 命中，此回归主要锁 `_CATEGORY_DEFAULTS` 与端到端不回退）

- [ ] **Step 3: Implement**

`src/agent/skills/profile_tags.py` 的 `_CATEGORY_DEFAULTS` 增加：

```python
    "value": {"style": ["value"], "horizon": ["long"], "risk": ["conservative", "balanced"]},
```

`strategies/growth_quality.yaml` 在 `market_regimes: [trending_up]` 之后追加：

```yaml
profile_tags:
  style: [value, framework]
  horizon: [long, swing]
  risk: [balanced]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_profile_tags.py tests/test_profile_recommender.py tests/test_profile_api.py -v`
Expected: PASS（含原有用例零回归）

- [ ] **Step 5: Commit**

```bash
git add src/agent/skills/profile_tags.py strategies/growth_quality.yaml tests/test_profile_tags.py tests/test_profile_recommender.py
git commit -m "fix(profile): make interview value style resolve to real strategies"
```

---

### Task 8: Web 策略中心"价值"分类

**Files:**
- Modify: `apps/dsa-web/src/components/profile/StrategyCenter.tsx:14-18`（分类 → i18n key 映射）
- Modify: `apps/dsa-web/src/i18n/uiText.ts`（zh + en 两个字典）
- Test: `apps/dsa-web/src/components/profile/__tests__/StrategyCenter.test.tsx`（追加）

**Interfaces:**
- Consumes: `GET /api/v1/agent/skills` 返回的 `category: "value"`（Task 6 上线后出现）。
- Produces: 策略中心新增"价值"分组；未知分类仍回落"其他"（现状保持）。

- [ ] **Step 1: Write the failing test**

在 `StrategyCenter.test.tsx` 顶部的 `vi.mock('../../../api/agent', ...)` skills 数组中追加一条（追加分组不影响既有断言）：

```tsx
          { id: 'value_undervalued', name: '价值低估', description: '内在价值折现估值', category: 'value' },
```

然后在 `describe('StrategyCenter', ...)` 内追加用例：

```tsx
  it('groups value-category skills under the 价值 heading', async () => {
    render(<StrategyCenter selected={[]} onChange={() => {}} maxSelected={3} />);
    expect(await screen.findByText('价值')).toBeInTheDocument();
    expect(screen.getByText('价值低估')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/dsa-web && npx vitest run src/components/profile/__tests__/StrategyCenter.test.tsx`
Expected: FAIL —"价值"分组不存在（value 分类落入"其他"）

- [ ] **Step 3: Implement**

`StrategyCenter.tsx` 分类映射（`framework` 之后、`other` 之前）：

```tsx
  value: 'strategyCenter.category.value',
```

`uiText.ts` zh 字典（`strategyCenter.category.framework` 行后）：

```ts
  'strategyCenter.category.value': '价值',
```

`uiText.ts` en 字典（同位置）：

```ts
  'strategyCenter.category.value': 'Value',
```

- [ ] **Step 4: Run tests + lint + build**

Run: `cd apps/dsa-web && npx vitest run src/components/profile/__tests__/StrategyCenter.test.tsx && npm run lint && npm run build`
Expected: 测试 PASS、lint 0 error、build 成功

- [ ] **Step 5: Commit**

```bash
git add apps/dsa-web/src/components/profile/StrategyCenter.tsx apps/dsa-web/src/i18n/uiText.ts apps/dsa-web/src/components/profile/__tests__/StrategyCenter.test.tsx
git commit -m "feat(web): add value category group in strategy center"
```

---

### Task 9: 文档、CHANGELOG 与全量验证

**Files:**
- Modify: `strategies/README.md`（内置策略清单处追加一行，格式跟随现有清单）
- Modify: `docs/CHANGELOG.md`（`[Unreleased]` 扁平条目）
- Modify: `docs/` 下投资画像/策略专题文档（若存在策略清单或画像访谈说明，补"价值低估"与 value 风格命中说明；以 `grep -rl "策略中心\|投资画像" docs/` 实际命中文件为准）

**Interfaces:**
- Consumes: Task 1-8 全部落地后的实际行为。
- Produces: 文档与代码一致；CI 全绿。

- [ ] **Step 1: Update docs**

`docs/CHANGELOG.md` `[Unreleased]` 追加（扁平格式，禁止小节标题）：

```markdown
- [新功能] 新增"价值低估"策略：基于多年自由现金流的确定性 DCF 估值工具 estimate_intrinsic_value + 安全边际判定，覆盖 A 股/港股/美股（数据不足时明确降级）
- [修复] 修复投资画像访谈"价值成长"风格无策略命中的断点：value 分类推导 + value_undervalued/growth_quality 显式 profile_tags + 策略中心"价值"分组
```

`strategies/README.md`：在内置策略清单中按现有格式补 `value_undervalued / 价值低估 / value` 一行；如清单含分类说明，补充 `value（价值）` 分类。

- [ ] **Step 2: Full verification**

```bash
./scripts/ci_gate.sh
python -m pytest tests/test_cashflow_history.py tests/test_valuation_service.py tests/test_valuation_tool.py tests/test_value_undervalued_skill.py tests/test_profile_tags.py tests/test_profile_recommender.py -v
cd apps/dsa-web && npm run lint && npm run build
```

Expected: ci_gate 通过（flake8 + pytest not-network）、列出的测试全 PASS、web lint/build 成功。

- [ ] **Step 3: Commit**

```bash
git add strategies/README.md docs/CHANGELOG.md docs/
git commit -m "docs: document value_undervalued strategy and profile value-tag fix"
```

---

## 交付说明模板（收尾时按仓库规范输出）

- 改了什么 / 为什么这么改：对照 spec 第 1、5 节。
- 验证情况：Task 9 Step 2 的命令与结果。
- 未验证项：akshare / yfinance 真实网络拉取（离线 mock 锁契约，线上失败走 fail-open 降级）；`network-smoke` 工作流可作为观测。
- 风险点：spec 第 10 节（接口列名漂移、yfinance 仅 ~4 年、金融/周期股失真、固定折现率）。
- 回滚方式：spec 第 8 节（删 YAML + 工具注册即下线；其余独立可回退）。
