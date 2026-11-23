"""Offline regression tests for the BSE annual-report fallback."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

# The annual-report module only needs Streamlit's cache decorator during import.
# This small test stub keeps the parser tests runnable in offline CI environments.
if "streamlit" not in sys.modules:
    try:
        import streamlit  # noqa: F401
    except ModuleNotFoundError:
        stub = types.ModuleType("streamlit")

        def cache_data(*args, **kwargs):
            def decorate(fn):
                fn.clear = lambda: None
                return fn
            if args and callable(args[0]):
                return decorate(args[0])
            return decorate

        stub.cache_data = cache_data
        sys.modules["streamlit"] = stub

from data import annual_report as ar


class _Response:
    def __init__(self, *, text="", payload=None):
        self.text = text
        self._payload = payload
        self.ok = True
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class BSEAnnualReportFallbackTests(unittest.TestCase):
    def test_quick_search_extracts_scrip_code_after_exact_symbol(self):
        response = _Response(
            text="<ul><li><strong>BOSCHLTD</strong> INE323A01026 500530</li></ul>"
        )
        with patch.object(ar.requests, "get", return_value=response):
            self.assertEqual(ar._lookup_bse_scrip_code("BOSCHLTD"), "500530")

    def test_direct_quick_search_runs_when_full_bse_scrip_list_is_unavailable(self):
        with patch.object(ar, "_load_bse_scrip_rows", return_value=[]), patch.object(
            ar, "_lookup_bse_scrip_code", side_effect=lambda q: "500530" if q == "BOSCHLTD" else ""
        ):
            self.assertEqual(ar._bse_scrip_code("BOSCHLTD.NS"), "500530")

    def test_annual_report_new_pdfdownload_field_is_normalized(self):
        payload = {
            "Table": [{
                "CompanyName": "Bosch Limited",
                "Year": "2025",
                "PDFDownload": "https://www.bseindia.com/xml-data/corpfiling/AttachHis/Bosch_AR_2025.pdf",
            }]
        }
        with patch.object(ar, "_bse_scrip_code", return_value="500530"), patch.object(
            ar.requests, "get", return_value=_Response(payload=payload)
        ):
            rows, source = ar._fetch_bse_annual_reports("BOSCHLTD.NS")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["Attachment"].endswith("Bosch_AR_2025.pdf"))
        self.assertEqual(rows[0]["To Year"], "2025")
        self.assertIn("AnnualReport_New", source)


if __name__ == "__main__":
    unittest.main()
