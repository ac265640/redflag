"""Offline smoke tests; run with python tests/test_disclosure_analyzer_offline.py."""
import importlib.util
import io
import sys
import types
from reportlab.pdfgen import canvas
from pathlib import Path

# The build container does not include Streamlit. Stub only its cache decorator
# so the pure analysis logic can still be tested without an app runtime.
st = types.ModuleType("streamlit")
def cache_data(*args, **kwargs):
    def deco(fn):
        fn.clear = lambda: None
        return fn
    return deco
st.cache_data = cache_data
st.secrets = {}
sys.modules.setdefault("streamlit", st)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("disclosure_analyzer", ROOT / "intelligence" / "disclosure_analyzer.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_url_allowlist():
    assert mod._allowed_url("https://nsearchives.nseindia.com/corporate/test.pdf")[0]
    assert mod._allowed_url("https://www.sebi.gov.in/files/test.pdf")[0]
    assert not mod._allowed_url("http://www.nseindia.com/test.pdf")[0]
    assert not mod._allowed_url("https://nseindia.com.evil.example/test.pdf")[0]


def test_adverse_penalty_verdict():
    pages = [{"page": 2, "text": "The Adjudicating Officer imposed a penalty of Rs. 5 lakh on the company. The company may appeal the order within 45 days."}]
    result = mod._rules_based_verdict(
        {"Type": "Penalty order", "Category": "Regulatory actions & enforcement", "Details": "Penalty imposed"},
        pages, pages[0]["text"], "PDF", 3,
    )
    assert result["ok"]
    assert result["verdict"].startswith("Adverse regulatory action")
    assert "Rs. 5 lakh" in " ".join(result["amounts_detected"])
    assert result["facts"][0]["page"] == 2


def test_show_cause_is_not_final_order():
    text = "The regulator issued a show-cause notice asking the company to respond. No final order has been passed as of the filing date."
    result = mod._rules_based_verdict(
        {"Type": "Show cause notice", "Category": "Regulatory actions & enforcement", "Details": text},
        [{"page": 1, "text": text}], text, "PDF", 1,
    )
    assert "not a final adverse finding" in result["verdict"]


def test_promoter_disclosure_not_automatically_adverse():
    text = "The promoter submitted a disclosure under Regulation 31(4) of the SEBI Substantial Acquisition of Shares and Takeovers Regulations, 2011."
    result = mod._rules_based_verdict(
        {"Type": "Disclosure under SEBI Takeover Regulations", "Category": "Promoter & shareholding", "Details": text},
        [{"page": 1, "text": text}], text, "PDF", 1,
    )
    assert result["verdict"].startswith("Promoter/shareholding disclosure")
    assert "title alone is not adverse evidence" in result["verdict_rationale"]


def test_evidence_quotes_must_exist_on_page():
    pages = [{"page": 4, "text": "The company disclosed that a penalty of Rs. 5 lakh was imposed."}]
    facts = [
        {"fact": "Penalty imposed", "evidence": "a penalty of Rs. 5 lakh was imposed", "page": 4},
        {"fact": "Revenue increased", "evidence": "Revenue increased by 30 percent", "page": 4},
    ]
    checked = mod._validate_llm_facts(facts, pages)
    assert len(checked) == 1
    assert checked[0]["page"] == 4


def test_missing_source_produces_no_verdict():
    result = mod.analyze_disclosure("SUZLON.NS", {"Type": "Penalty", "Source": ""})
    assert not result["ok"]
    assert "No direct primary-source" in result["error"]


def test_pdf_download_and_page_extraction():
    pdf_buffer = io.BytesIO()
    pdf_canvas = canvas.Canvas(pdf_buffer)
    pdf_canvas.drawString(72, 760, "The Adjudicating Officer imposed a penalty of Rs. 5 lakh on the company.")
    pdf_canvas.save()
    pdf_bytes = pdf_buffer.getvalue()

    class FakeResponse:
        def __init__(self, url, content=b"", content_type="application/pdf"):
            self.url = url
            self.content = content
            self.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
        def raise_for_status(self):
            return None
        def iter_content(self, chunk_size=65536):
            yield self.content
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    class FakeSession:
        def __init__(self):
            self.headers = {}
        def get(self, url, **kwargs):
            if url == mod.NSE_PRIME_URL:
                return FakeResponse(url, b"NSE filing section", "text/html")
            return FakeResponse(url, pdf_bytes, "application/pdf")
        def close(self):
            pass

    original_session = mod.requests.Session
    try:
        mod.requests.Session = FakeSession
        mod.fetch_and_extract_document.clear()
        result = mod.fetch_and_extract_document("https://nsearchives.nseindia.com/corporate/example.pdf")
    finally:
        mod.requests.Session = original_session
    assert result["ok"]
    assert result["page_count"] == 1
    assert "penalty of Rs. 5 lakh" in result["pages"][0]["text"]


def test_openai_compatible_llm_response_is_evidence_checked():
    import os
    page_text = "The Adjudicating Officer imposed a penalty of Rs. 5 lakh on the company."
    result_payload = {
        "document_summary": "A penalty was imposed, subject to checking the operative order.",
        "event_nature": "Final penalty order",
        "verdict_label": "Adverse disclosed event",
        "verdict_rationale": "The document states that a penalty was imposed.",
        "materiality": "Medium",
        "confidence": "High",
        "amounts": ["Rs. 5 lakh"],
        "facts": [{"fact": "Penalty imposed", "evidence": "penalty of Rs. 5 lakh on the company", "page": 1}],
        "company_impact": {
            "earnings": "Potential other expense, subject to accounting period.",
            "cash_flow": "Cash outflow depends on payment status.",
            "balance_sheet": "Check for provision or payable.",
            "operations": "No operational effect disclosed.",
            "governance": "Regulatory compliance matter.",
        },
        "watch_items": ["Check appeal status."],
        "limitations": ["Check subsequent order updates."],
    }
    class FakePostResponse:
        def raise_for_status(self):
            return None
        def json(self):
            import json
            return {"choices": [{"message": {"content": json.dumps(result_payload)}}]}
    original_post = mod.requests.post
    old_env = {key: os.environ.get(key) for key in ["REDFLAG_LLM_API_KEY", "REDFLAG_LLM_BASE_URL", "REDFLAG_LLM_MODEL"]}
    try:
        os.environ["REDFLAG_LLM_API_KEY"] = "test-key"
        os.environ["REDFLAG_LLM_BASE_URL"] = "https://api.example.com/v1"
        os.environ["REDFLAG_LLM_MODEL"] = "test-model"
        mod.requests.post = lambda *args, **kwargs: FakePostResponse()
        result = mod._call_llm(
            {"ticker": "TEST.NS", "Type": "Penalty order", "Date": "2026-11-01", "Category": "Regulatory actions & enforcement", "Details": "Penalty"},
            [{"page": 1, "text": page_text}],
            "https://nsearchives.nseindia.com/corporate/example.pdf", "PDF", 2,
        )
    finally:
        mod.requests.post = original_post
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    assert result is not None
    assert result["mode"].startswith("AI-generated")
    assert len(result["facts"]) == 1
    assert result["pages_total"] == 2
    assert result["verdict"] == "Adverse disclosed event"


if __name__ == "__main__":
    tests = [test_url_allowlist, test_adverse_penalty_verdict, test_show_cause_is_not_final_order,
             test_promoter_disclosure_not_automatically_adverse, test_evidence_quotes_must_exist_on_page,
             test_missing_source_produces_no_verdict, test_pdf_download_and_page_extraction,
             test_openai_compatible_llm_response_is_evidence_checked]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} offline checks passed")
