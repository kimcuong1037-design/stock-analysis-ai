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
