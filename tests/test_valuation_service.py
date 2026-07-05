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
