# -*- coding: utf-8 -*-
"""Offline tests for yearly cash-flow history extraction (valuation data layer)."""
import os
import sys
from unittest.mock import patch, MagicMock

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.fundamental_adapter import AkshareFundamentalAdapter, _em_symbol, _report_year
from data_provider.base import DataFetcherManager


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


def test_akshare_cashflow_history_fail_open_on_internal_parse_error():
    """Fail-open must hold even when parsing the fetched DataFrame raises,
    not just when _call_df_candidates itself fails."""
    adapter = AkshareFundamentalAdapter()
    df = _em_cashflow_df()

    def fake_call(candidates):
        if candidates[0][0] == "stock_cash_flow_sheet_by_yearly_em":
            return df, "stock_cash_flow_sheet_by_yearly_em", []
        return None, None, []

    with patch.object(adapter, "_call_df_candidates", side_effect=fake_call), \
            patch("data_provider.fundamental_adapter._report_year", side_effect=RuntimeError("boom")):
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
