"""Regression tests for sector-aware forensic rule selection and missing-data safety."""
import unittest
import sys
import types

import numpy as np
import pandas as pd

# The sector classifier uses Streamlit only for a UI cache decorator. Permit
# offline unit tests in environments where Streamlit is not installed.
if "streamlit" not in sys.modules:
    try:
        import streamlit  # noqa: F401
    except ModuleNotFoundError:
        stub = types.ModuleType("streamlit")
        stub.cache_data = lambda *args, **kwargs: (lambda fn: fn)
        sys.modules["streamlit"] = stub

from financial_redflags.sector_engine import evaluate_sector_forensics
from financial_redflags.ratio_flags import compute_beneish


def frame():
    return pd.DataFrame({
        "revenue": [1000.0, 1100.0, 1200.0, 1300.0],
        "cogs": [600.0, 660.0, 720.0, 780.0],
        "sga": [120.0, 130.0, 140.0, 150.0],
        "ebitda": [220.0, 220.0, 210.0, 180.0],
        "other_income": [10.0, 10.0, 10.0, 10.0],
        "depreciation": [40.0, 42.0, 44.0, 46.0],
        "interest": [20.0, 22.0, 24.0, 28.0],
        "exceptional": [0.0, 0.0, 0.0, 0.0],
        "pbt": [170.0, 168.0, 152.0, 106.0],
        "tax": [42.0, 42.0, 38.0, 27.0],
        "pat": [128.0, 126.0, 114.0, 79.0],
        "receivables": [100.0, 115.0, 140.0, 190.0],
        "inventory": [120.0, 135.0, 160.0, 210.0],
        "payables": [90.0, 95.0, 100.0, 110.0],
        "cash": [80.0, 85.0, 90.0, 95.0],
        "current_assets": [350.0, 380.0, 420.0, 470.0],
        "ppe": [500.0, 520.0, 540.0, 560.0],
        "cwip": [20.0, 25.0, 30.0, 35.0],
        "total_assets": [1000.0, 1100.0, 1200.0, 1300.0],
        "long_term_debt": [200.0, 220.0, 240.0, 260.0],
        "short_term_debt": [50.0, 50.0, 55.0, 60.0],
        "total_debt": [250.0, 270.0, 295.0, 320.0],
        "current_liabilities": [200.0, 220.0, 240.0, 260.0],
        "net_worth": [500.0, 550.0, 600.0, 650.0],
        "retained_earnings": [300.0, 330.0, 360.0, 390.0],
        "total_liabilities": [500.0, 550.0, 600.0, 650.0],
        "cfo": [120.0, 110.0, 80.0, 40.0],
        "capex": [60.0, 65.0, 70.0, 75.0],
        "fcf": [60.0, 45.0, 10.0, -35.0],
    }, index=["FY2023", "FY2024", "FY2025", "FY2026"])


class SectorForensicTests(unittest.TestCase):
    def test_motilal_uses_brokerage_profile_and_skips_industrial_rules(self):
        result = evaluate_sector_forensics("MOTILALOFS.NS", {"sector": "Financial Services", "industry": "Capital Markets"}, frame())
        self.assertEqual(result.profile.key, "brokerage")
        codes = {r["code"]: r for r in result.checks}
        self.assertEqual(codes["IND_INVENTORY_NA"]["status"], "Not applicable")
        self.assertEqual(codes["IND_CCC_NA"]["status"], "Not applicable")
        self.assertEqual(codes["MODEL_ALTMAN_NA"]["status"], "Not applicable")
        self.assertEqual(codes["MODEL_BENEISH_NA"]["status"], "Not applicable")
        self.assertNotIn("IND_INVENTORY_GAP", codes)
        self.assertNotIn("IND_RECEIVABLES_GAP", codes)

    def test_bank_excludes_industrial_cashflow_inventory_and_altman(self):
        result = evaluate_sector_forensics("HDFCBANK.NS", {"sector": "Financial Services", "industry": "Banks - Regional"}, frame())
        self.assertEqual(result.profile.key, "banking")
        codes = {r["code"]: r for r in result.checks}
        self.assertEqual(codes["MODEL_ALTMAN_NA"]["status"], "Not applicable")
        self.assertEqual(codes["MODEL_BENEISH_NA"]["status"], "Not applicable")
        self.assertEqual(codes["FI_CFO_PAT_NA"]["status"], "Not applicable")
        self.assertNotIn("IND_INVENTORY_GAP", codes)
        self.assertNotIn("IND_INTEREST_COVER", codes)

    def test_cement_runs_inventory_and_working_capital_checks(self):
        result = evaluate_sector_forensics("ULTRACEMCO.NS", {}, frame())
        self.assertEqual(result.profile.key, "cement")
        codes = {r["code"]: r for r in result.checks}
        self.assertIn("IND_INVENTORY_GAP", codes)
        self.assertIn("IND_CCC_LENGTHENING", codes)
        self.assertIn("IND_NET_DEBT_EBITDA", codes)

    def test_missing_fields_are_unavailable_not_zero(self):
        d = frame()
        d["cash"] = np.nan
        d["sga"] = np.nan
        d["cfo"] = np.nan
        result = evaluate_sector_forensics("ULTRACEMCO.NS", {}, d)
        codes = {r["code"]: r for r in result.checks}
        self.assertEqual(codes["CF_CFO_PAT"]["status"], "Unavailable")
        self.assertEqual(codes["MODEL_BENEISH"]["status"], "Unavailable")
        self.assertEqual(codes["IND_NET_DEBT_EBITDA"]["status"], "Unavailable")

    def test_missing_other_income_does_not_get_zero_filled_for_interest_cover(self):
        d = frame()
        d["other_income"] = np.nan
        result = evaluate_sector_forensics("ULTRACEMCO.NS", {}, d)
        codes = {r["code"]: r for r in result.checks}
        self.assertEqual(codes["IND_INTEREST_COVER"]["status"], "Unavailable")

    def test_score_only_uses_executed_tests(self):
        d = frame()
        d["inventory"] = np.nan
        d["receivables"] = np.nan
        result = evaluate_sector_forensics("ULTRACEMCO.NS", {}, d)
        self.assertGreaterEqual(result.score, 0)
        self.assertLessEqual(result.score, 100)
        self.assertGreater(result.applicable_count, 0)
        self.assertGreater(result.unavailable_count, 0)

    def test_test_coverage_excludes_unavailable_sector_kpi_rows(self):
        result = evaluate_sector_forensics("HDFCBANK.NS", {"sector": "Financial Services", "industry": "Banks - Regional"}, frame())
        check_unavailable = sum(row["status"] == "Unavailable" for row in result.checks)
        self.assertEqual(result.unavailable_count, check_unavailable)
        expected = 100 * result.applicable_count / (result.applicable_count + check_unavailable)
        self.assertAlmostEqual(result.coverage_pct, expected)
        self.assertTrue(any(row["Status"] == "Unavailable" for row in result.sector_metrics))

    def test_beneish_zero_prior_leverage_base_returns_unavailable_without_crashing(self):
        d = frame()
        d.loc["FY2025", "current_liabilities"] = 0.0
        d.loc["FY2025", "long_term_debt"] = 0.0
        result = evaluate_sector_forensics("ULTRACEMCO.NS", {}, d)
        codes = {r["code"]: r for r in result.checks}
        self.assertEqual(codes["MODEL_BENEISH"]["status"], "Unavailable")

    def test_legacy_beneish_does_not_neutral_fill_missing_inputs(self):
        d = frame()
        d["sga"] = np.nan
        score = compute_beneish(d)
        self.assertTrue(score["M_Score"].isna().all())

    def test_live_analysis_uses_sector_score_and_does_not_claim_overall_score(self):
        from unittest.mock import patch
        from core.scoring_engine import _analyze_live
        profile = {"name":"Motilal Oswal Financial Services Limited", "sector":"Financial Services",
                   "industry":"Capital Markets", "market_cap_cr":np.nan, "data_mode":"live"}
        with patch("core.scoring_engine.get_profile", return_value=profile), \
             patch("data.fetch_live.get_source_preserving_financials", return_value=frame()):
            analysis = _analyze_live("MOTILALOFS")
        self.assertEqual(analysis.sector_forensic.profile.key, "brokerage")
        self.assertAlmostEqual(analysis.financial.score, analysis.sector_forensic.score)
        self.assertTrue(np.isnan(analysis.overall_risk))
        self.assertEqual(analysis.data_mode, "live")


if __name__ == "__main__":
    unittest.main()
