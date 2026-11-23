"""BRSR + supplemental ESG scorecard using public NSE data and Yahoo sustainability."""
import math
import io
import re
from concurrent.futures import ThreadPoolExecutor, wait
import pandas as pd
import streamlit as st

from data.public_sources import (fetch_brsr_filings, fetch_brsr_xbrl_metrics, fetch_crisil_esg_rating, fetch_yahoo_esg, yahoo_esg_scores, source_links, BRSR_METRIC_PATTERNS, _parse_xbrl_payload, _match_brsr_metric, _extract_brsr_value_after_label)
from visualization.components import hero, section, setup_page, notice, card_grid, metric_card

ticker=setup_page("ESG Scorecard")
hero(f"{ticker}: ESG Scorecard", "NSE BRSR/XBRL is the primary Indian disclosure source. Yahoo ESG fields are supplemental and are never treated as a substitute for BRSR.", demo=False)

refresh_col, browser_col, info_col = st.columns([1.05, 1.35, 2.2])
with refresh_col:
    refresh_esg = st.button("↻ Refresh ESG sources", key=f"refresh_esg_{ticker}", use_container_width=True)
with browser_col:
    browser_esg = st.button("Retry NSE in browser", key=f"browser_esg_{ticker}", use_container_width=True, help="Uses your installed Chrome/Selenium to read the official NSE BRSR page after direct retrieval fails.")
with info_col:
    st.caption("Direct NSE requests and cached annual-report fallback run first. Browser automation is optional because it depends on local Chrome/driver setup.")
if refresh_esg:
    fetch_brsr_filings.clear()
    fetch_brsr_xbrl_metrics.clear()
    fetch_crisil_esg_rating.clear()
    fetch_yahoo_esg.clear()
    st.rerun()
if browser_esg:
    st.session_state[f"esg_browser_retry_{ticker}"] = True
    fetch_brsr_filings.clear()
    fetch_brsr_xbrl_metrics.clear()
    st.rerun()
use_browser_fallback = bool(st.session_state.pop(f"esg_browser_retry_{ticker}", False))

# BRSR, external rating and supplemental Yahoo ESG are independent sources.
# Fetch concurrently with a bounded first-render wait; unavailable sources remain
# explicitly N/A and can be refreshed individually from the controls above.
with st.status("Checking available ESG sources (time-limited)…", expanded=False) as _esg_status:
    _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rfi-esg")
    _jobs = {
        "brsr": _pool.submit(fetch_brsr_filings, ticker, use_browser_fallback=use_browser_fallback),
        "xbrl": _pool.submit(fetch_brsr_xbrl_metrics, ticker, use_browser_fallback=use_browser_fallback),
        "crisil": _pool.submit(fetch_crisil_esg_rating, ticker),
        "yahoo": _pool.submit(fetch_yahoo_esg, ticker),
    }
    _done, _pending = wait(list(_jobs.values()), timeout=10)
    _values = {}
    for _name, _future in _jobs.items():
        if _future in _done:
            try: _values[_name] = _future.result()
            except Exception: _values[_name] = None
        else:
            _future.cancel()
            _values[_name] = None
    _pool.shutdown(wait=False, cancel_futures=True)
    brsr, brsr_source = _values.get("brsr") or (pd.DataFrame(), "NSE BRSR lookup timed out or returned no records")
    xbrl, xbrl_source = _values.get("xbrl") or (pd.DataFrame(), "BRSR XBRL extraction timed out or returned no verified metrics")
    crisil = _values.get("crisil") if isinstance(_values.get("crisil"), pd.DataFrame) else pd.DataFrame()
    yahoo = _values.get("yahoo") if isinstance(_values.get("yahoo"), pd.DataFrame) else pd.DataFrame()
    _esg_status.update(label="ESG source checks complete · each source isolated", state="complete")
scores=yahoo_esg_scores(yahoo)

def _parse_uploaded_brsr(uploaded_file):
    """Parse only metrics present in an issuer-provided BRSR PDF/XBRL upload."""
    if uploaded_file is None:
        return pd.DataFrame(), ""
    payload = uploaded_file.getvalue()
    filename = str(uploaded_file.name or "uploaded filing")
    if not payload:
        return pd.DataFrame(), "The selected file is empty."
    if len(payload) > 35 * 1024 * 1024:
        return pd.DataFrame(), "File exceeds the 35 MB upload limit."
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if suffix in {"xml", "xbrl", "zip"} or payload[:2] == b"PK":
        try:
            facts = _parse_xbrl_payload(payload)
            matched = []
            for fact in facts:
                metric = _match_brsr_metric(str(fact.get("Concept") or ""))
                if metric:
                    matched.append({
                        "Metric": metric,
                        "Value": fact.get("Value"),
                        "Unit": fact.get("Unit", ""),
                        "Concept": fact.get("Concept", ""),
                        "Context": fact.get("Context", ""),
                    })
            if matched:
                df = pd.DataFrame(matched).drop_duplicates(
                    subset=["Metric", "Context"], keep="first"
                )
                return df[["Metric", "Value", "Unit", "Concept", "Context"]], f"Uploaded XBRL: {filename}"
            return pd.DataFrame(), "The XML/XBRL file was opened, but no supported numeric BRSR concepts were found."
        except Exception as exc:
            return pd.DataFrame(), f"Could not parse this XBRL file ({type(exc).__name__})."

    if suffix == "pdf" or payload[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(payload))
            pages = []
            for page_no, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append({"page": page_no, "text": page_text})
            full_text = " ".join(str(page["text"]) for page in pages).lower()
            if not any(term in full_text for term in (
                "business responsibility and sustainability",
                "business responsibility & sustainability",
                "brsr",
            )):
                return pd.DataFrame(), "The PDF does not appear to contain a BRSR section. Please upload the official BRSR PDF or the annual report containing it."

            brsr_pages = [
                page for page in pages
                if any(term in str(page["text"]).lower() for term in (
                    "business responsibility and sustainability report",
                    "business responsibility & sustainability report",
                    "business responsibility report",
                    "brsr core",
                ))
            ]
            # BRSR tables continue over pages without repeating the title.
            # If the uploaded PDF is an annual report, scan from the first
            # identified BRSR section onward; otherwise the user-uploaded file
            # must itself contain BRSR wording before we attempt extraction.
            if brsr_pages:
                first_brsr_page = min(int(page["page"]) for page in brsr_pages)
                search_pages = [page for page in pages if int(page["page"]) >= first_brsr_page]
            else:
                search_pages = pages
            found = []
            for page in search_pages:
                lines = [
                    re.sub(r"\s+", " ", line).strip()
                    for line in str(page["text"]).splitlines() if str(line).strip()
                ]
                joined = " ".join(lines)
                for metric, patterns in BRSR_METRIC_PATTERNS.items():
                    value = None
                    for index, line in enumerate(lines):
                        if not any(re.search(pattern, line, re.I) for pattern in patterns):
                            continue
                        value = _extract_brsr_value_after_label(line, patterns)
                        if value is None:
                            value = _extract_brsr_value_after_label(
                                " ".join(lines[index:index + 3]), patterns
                            )
                        if value is not None:
                            break
                    if value is None:
                        value = _extract_brsr_value_after_label(joined, patterns)
                    if value is not None:
                        found.append({
                            "Metric": metric, "Value": value, "Unit": "",
                            "Concept": "Official uploaded BRSR PDF",
                            "Context": f"PDF page {page['page']}",
                        })
            if found:
                df = pd.DataFrame(found).drop_duplicates(subset=["Metric", "Context"], keep="first")
                return df[["Metric", "Value", "Unit", "Concept", "Context"]], f"Uploaded BRSR PDF: {filename}"
            return pd.DataFrame(), "The BRSR PDF was read, but the text extractor could not confidently locate numeric values. A scanned/image PDF may require OCR."
        except Exception as exc:
            return pd.DataFrame(), f"Could not read this PDF ({type(exc).__name__})."
    return pd.DataFrame(), "Unsupported file type. Upload an official BRSR PDF, XML, XBRL or ZIP."


# Manual source fallback: the official NSE page is JavaScript-rendered for some
# clients. A user can upload the original issuer filing and have it parsed locally.
with st.expander("Can't retrieve the BRSR automatically? Upload the official filing", expanded=False):
    st.markdown(
        "Download the company's BRSR PDF or XBRL from the official exchange filing page, "
        "then upload it here. The file is processed by this local dashboard; values are "
        "shown only when they can be extracted from the uploaded document."
    )
    uploaded_brsr = st.file_uploader(
        "Official BRSR PDF / XBRL / XML / ZIP",
        type=["pdf", "xbrl", "xml", "zip"],
        key=f"brsr_manual_upload_{ticker}",
        help="Maximum 35 MB. Prefer the exchange-filed XBRL for structured metrics."
    )
    if uploaded_brsr is not None:
        manual_xbrl, manual_source = _parse_uploaded_brsr(uploaded_brsr)
        if not manual_xbrl.empty:
            xbrl = manual_xbrl
            xbrl_source = manual_source
            st.success(
                f"Extracted {len(xbrl)} source-backed metric rows from {uploaded_brsr.name}. "
                "These are issuer-reported disclosures, not an ESG rating."
            )
        else:
            st.warning(manual_source or "No verifiable numeric metrics could be extracted.")
            if uploaded_brsr.size:
                st.caption("Try the original XBRL/ZIP if a PDF extraction returns no values.")

# No synthetic completeness percentage: show the number of actual records parsed.
card_grid([
    metric_card("BRSR records found", str(len(brsr)), "Automatic exchange lookup", "file"),
    metric_card("Reported metrics parsed", str(len(xbrl)), "Actual XBRL/PDF values extracted", "analytics"),
    metric_card("Reporting period", (f"FY{brsr.iloc[0].get('From Year')}-{brsr.iloc[0].get('To Year')}" if not brsr.empty and str(brsr.iloc[0].get("From Year", "")).strip() else "Not verified"), "Based on retrieved filing metadata", "calendar"),
    metric_card("CRISIL ESG rating", str(crisil.iloc[0].get("ESG Rating", crisil.iloc[0].get("Ratings", "N/A"))) if not crisil.empty else "Not matched", "Separate external rating source", "eco"),
], cols=4)

section("External ESG rating", "CRISIL ESG is shown when the selected company appears in CRISIL's public ESG ratings list. Yahoo sustainability is supplemental only.", "eco")
if not crisil.empty:
    st.dataframe(crisil, use_container_width=True, hide_index=True)
else:
    notice("No CRISIL ESG rating was matched for this company. This does not mean the company is unrated; the dashboard does not manufacture a rating.")
if scores['Total ESG'] is not None:
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Yahoo Total ESG", f"{scores['Total ESG']:.1f}")
    c2.metric("Environment", f"{scores['Environment']:.1f}" if scores['Environment'] is not None else "N/A")
    c3.metric("Social", f"{scores['Social']:.1f}" if scores['Social'] is not None else "N/A")
    c4.metric("Governance", f"{scores['Governance']:.1f}" if scores['Governance'] is not None else "N/A")

section("BRSR / BRSR Core data", "Actual company disclosures parsed from the latest NSE BRSR XBRL. No synthetic ESG values are used.", "analytics")
if not xbrl.empty:
    xbrl_display = xbrl.copy()
    for _c in xbrl_display.columns:
        if xbrl_display[_c].dtype == "object":
            xbrl_display[_c] = xbrl_display[_c].map(lambda v: "" if pd.isna(v) else str(v))
    st.dataframe(xbrl_display, use_container_width=True, hide_index=True)
else:
    notice(
        "We could not automatically retrieve a machine-readable BRSR/XBRL filing for this company in this run. "
        "This does not mean the company has not filed a BRSR. Open the official exchange filing page, "
        "download its BRSR PDF/XBRL, and upload it using the fallback above. No ESG performance value is inferred."
    )
    with st.expander("Technical retrieval details"):
        st.caption(str(xbrl_source))

# ------------------------------------------------------------
# ESG scorecard summary – source-backed, not a synthetic ESG score.
# ------------------------------------------------------------
def _metric_value(label):
    if xbrl.empty or "Metric" not in xbrl.columns:
        return None
    rows=xbrl[xbrl["Metric"].astype(str).str.lower().eq(label.lower())]
    if rows.empty:
        return None
    raw=rows.iloc[0].get("Value")
    try:
        return float(str(raw).replace(",", ""))
    except Exception:
        return raw if raw not in (None, "", "nan") else None

def _fmt(v):
    if v is None:
        return "N/A"
    try:
        f=float(v)
        if math.isnan(f): return "N/A"
        return f"{f:,.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(v)

latest_from = ""
latest_to = ""
if not brsr.empty:
    # Prefer the latest year pair with a real XBRL link.
    candidate=brsr[brsr.get("XBRL", pd.Series(index=brsr.index,dtype=str)).astype(str).str.startswith("http")]
    if candidate.empty: candidate=brsr
    if not candidate.empty:
        latest_from=str(candidate.iloc[0].get("From Year") or "")
        latest_to=str(candidate.iloc[0].get("To Year") or "")

section("ESG scorecard summary", "Reported BRSR disclosures are shown separately from external ESG ratings. No synthetic ESG performance score is calculated.", "analytics")
if brsr.empty and xbrl.empty:
    notice("No BRSR filing or numeric BRSR metrics could be verified automatically in this run. This is a retrieval limitation, not evidence that the company has not filed. Open the official NSE/BSE filing page or upload the original BRSR PDF/XBRL above. No ESG performance value is inferred.")
else:
    if latest_from and latest_to:
        period = f"FY{latest_from}-{latest_to}"
    elif str(xbrl_source).startswith("Uploaded"):
        period = "Uploaded filing · reporting period not independently read from metadata"
    else:
        period = "Period not verified"
    st.markdown(
        f"**Reporting period:** {period}. "
        f"**Exchange filing records retrieved:** {len(brsr)}. "
        f"**Numeric BRSR metrics extracted:** {len(xbrl)}."
    )
    st.caption(f"Metric source: {xbrl_source}.")

    key_metrics = [
        ("Water withdrawal", "Water withdrawal", "Kiloliters"),
        ("Water consumption", "Water consumption", "Kiloliters"),
        ("Waste generated", "Waste generated", "Tonnes"),
        ("Waste recycled", "Waste recycled", "Tonnes"),
    ]
    cards=[]
    for title, metric, unit in key_metrics:
        value=_metric_value(metric)
        cards.append(metric_card(title, _fmt(value), unit if value is not None else "Not reported in parsed XBRL", "analytics"))
    card_grid(cards, cols=4)

    narrative=[]
    for title, metric, unit in key_metrics:
        value=_metric_value(metric)
        if value is not None:
            narrative.append(f"**{title}:** {_fmt(value)} {unit}.")
    if narrative:
        st.markdown(" ".join(narrative))
    st.caption("These are reported BRSR/XBRL disclosures. They are not normalized ESG scores and are not interpreted as good/bad without sector and historical context.")

with st.expander("Yahoo sustainability dataset"):
    if not yahoo.empty:
        yahoo_display = yahoo.copy()
        for _c in yahoo_display.columns:
            if yahoo_display[_c].dtype == "object":
                yahoo_display[_c] = yahoo_display[_c].map(lambda v: "" if pd.isna(v) else str(v))
        st.dataframe(yahoo_display, use_container_width=True, hide_index=True, height=520)
    else: st.info("Yahoo Finance did not return a sustainability dataset for this security.")

section("Primary sources", "For equity research, cite the original NSE BRSR/XBRL or the relevant ESG rating provider rather than this dashboard.", "link")
links=source_links(ticker)
st.markdown(f"- [NSE BRSR filings]({links['NSE BRSR']})")
st.markdown(f"- [NSE Announcements]({links['NSE Announcements']})")
st.markdown("- [BSE Corporate Filings / BRSR](https://www.bseindia.com/corporates.html)")
st.markdown("- [CRISIL ESG Ratings](https://www.crisilesg.com/en/home/esg-ratings.html)")
st.markdown("- [CARE ESG Rating List](https://www.careedgeesg.com/rating)")

st.info("Important: BRSR is a company disclosure framework. It is not itself a third-party ESG rating. The dashboard therefore separates BRSR metrics, disclosure coverage and any external ESG score.")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
