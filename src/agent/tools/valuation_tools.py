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

    try:
        result = _estimate(records, market_cap=market_cap)
    except Exception as exc:
        logger.warning("estimate_intrinsic_value estimate failed for %s: %s", stock_code, exc)
        return {"status": "error", "error": f"estimate:{exc}", "stock_code": stock_code}

    result["stock_code"] = stock_code
    # Reporting currency of the FCF records (financialCurrency), always surfaced
    # so the LLM can caveat HK/US verdicts even when `valuation` is empty —
    # market_cap (trading currency) and this can differ ~8-10% for HK-listed
    # mainland companies. See strategies/value_undervalued.yaml step 4.
    result["currency"] = records[0].get("currency", "") if records else ""
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
