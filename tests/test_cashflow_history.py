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
