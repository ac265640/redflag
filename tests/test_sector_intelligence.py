"""Offline tests for sector-aware ratio calculations and missing-data discipline."""
import unittest

import numpy as np
import pandas as pd

from intelligence.sector_intelligence import (
    classify_company, calculate_ratio_series, ratio_rows, compare_peers,
)
from data.fetch_live import _source_preserving_statement_frame


def statements():
    return pd.DataFrame({
        "revenue": [1000.0, 1100.0, 1200.0],
        "cogs": [600.0, 650.0, 700.0],
        "ebitda": [200.0, 220.0, 240.0],
        "depreciation": [40.0, 42.0, 44.0],
        "pat": [100.0, 115.0, 130.0],
        "total_assets": [1500.0, 1600.0, 1700.0],
        "net_worth": [800.0, 850.0, 900.0],
        "total_debt": [300.0, 320.0, 330.0],
        "cash": [80.0, 85.0, 90.0],
        "cfo": [120.0, 135.0, 145.0],
        "interest": [25.0, 26.0, 27.0],
        "receivables": [100.0, 110.0, 120.0],
        "inventory": [120.0, 125.0, 130.0],
        "payables": [90.0, 95.0, 100.0],
        "current_liabilities": [250.0, 260.0, 270.0],
        "capex": [50.0, 55.0, 60.0],
    }, index=["FY2024", "FY2025", "FY2026"])


class SectorIntelligenceTests(unittest.TestCase):
    def test_sector_classification(self):
        expected = {
            "ULTRACEMCO.NS": "cement",
            "HDFCBANK.NS": "banking",
            "IRFC.NS": "nbfc_infra",
            "TCS.NS": "it_services",
            "CDSL.NS": "depository",
            "ONGC.NS": "oil_upstream",
            "IOC.NS": "oil_downstream",
            "HDFCLIFE.NS": "insurance_life",
            "ICICIGI.NS": "insurance_general",
            "JUBLFOOD.NS": "qsr",
        }
        for ticker, sector_key in expected.items():
            with self.subTest(ticker=ticker):
                self.assertEqual(classify_company(ticker, {}).key, sector_key)

    def test_calculation_formulas(self):
        metrics = calculate_ratio_series(statements())
        self.assertAlmostEqual(float(metrics["ebitda_margin"].iloc[-1]), 20.0, places=2)
        self.assertAlmostEqual(float(metrics["cfo_pat"].iloc[-1]), 145/130, places=3)
        self.assertAlmostEqual(float(metrics["net_debt_ebitda"].iloc[-1]), 1.0, places=2)
        self.assertTrue(np.isnan(metrics["roce"].iloc[0]))  # opening balance missing

    def test_sloan_accrual_ratio_uses_average_assets(self):
        metrics = calculate_ratio_series(statements())
        expected = (130.0 - 145.0) / ((1600.0 + 1700.0) / 2) * 100
        self.assertAlmostEqual(float(metrics["sloan_accruals"].iloc[-1]), expected, places=3)
        cement = classify_company("ULTRACEMCO.NS", {})
        self.assertIn("sloan_accruals", [row["code"] for row in ratio_rows(statements(), cement)])

    def test_missing_inputs_are_not_replaced_with_zero(self):
        frame = statements()
        frame["cash"] = np.nan
        frame["depreciation"] = np.nan
        metrics = calculate_ratio_series(frame)
        self.assertTrue(metrics["net_debt_ebitda"].isna().all())
        self.assertTrue(metrics["ebit_margin"].isna().all())
        self.assertTrue(metrics["interest_coverage"].isna().all())

    def test_bank_regulatory_metrics_remain_unavailable_without_filing_inputs(self):
        bank = classify_company("HDFCBANK.NS", {})
        rows = ratio_rows(statements(), bank)
        nim = next(row for row in rows if row["code"] == "nim")
        roa = next(row for row in rows if row["code"] == "roa")
        self.assertFalse(nim["available"])
        self.assertIn("average earning assets", nim["definition"])
        self.assertTrue(roa["available"])

    def test_peer_comparison_uses_common_period_and_at_least_two_peers(self):
        company = statements()
        peer_a = statements()
        peer_b = statements().iloc[:2]
        peer_c = statements().iloc[1:]
        sector = classify_company("ULTRACEMCO.NS", {})
        result, period = compare_peers(
            "ULTRACEMCO.NS", company,
            {"A.NS": peer_a, "B.NS": peer_b, "C.NS": peer_c},
            sector,
        )
        self.assertEqual(period, "FY2026")
        self.assertEqual(len(result), 3)
        one_peer, one_period = compare_peers(
            "ULTRACEMCO.NS", company, {"A.NS": peer_a}, sector,
        )
        self.assertEqual(one_period, "FY2026")
        self.assertEqual(len(one_peer), 2)  # company + one peer; UI does not calculate a median
        no_common, no_period = compare_peers(
            "ULTRACEMCO.NS", company, {"A.NS": pd.DataFrame({"revenue":[10],"pat":[1]}, index=["FY2021"])}, sector,
        )
        self.assertTrue(no_common.empty)
        self.assertIsNone(no_period)

    def test_source_preserving_normalizer_keeps_absent_fields_null(self):
        cols = pd.to_datetime(["2026-03-31", "2025-03-31", "2024-03-31"])
        income = pd.DataFrame({
            "Total Revenue": [1200e7, 1100e7, 1000e7],
            "EBITDA": [240e7, 220e7, 200e7],
            "Net Income": [130e7, 115e7, 100e7],
        }, index=cols).T
        balance = pd.DataFrame({
            "Total Assets": [1700e7, 1600e7, 1500e7],
            "Stockholders Equity": [900e7, 850e7, 800e7],
        }, index=cols).T
        cashflow = pd.DataFrame({
            "Operating Cash Flow": [145e7, 135e7, 120e7],
        }, index=cols).T
        frame = _source_preserving_statement_frame(income, balance, cashflow)
        self.assertTrue(frame["total_debt"].isna().all())
        self.assertTrue(frame["cash"].isna().all())
        self.assertTrue(frame["current_liabilities"].isna().all())
        self.assertTrue(frame["capex"].isna().all())


if __name__ == "__main__":
    unittest.main()
