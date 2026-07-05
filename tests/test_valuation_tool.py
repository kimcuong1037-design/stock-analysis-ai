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
