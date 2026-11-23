"""Unified Annual Report & Management Intelligence workspace.

The page shares one annual-report evidence pipeline and keeps management claims,
financial validation and disclosure review signals connected to original pages.
"""
from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from data.annual_report import annual_report_evidence, annual_report_risk_signals
from data.fetch_live import DataUnavailable, get_source_preserving_financials
from intelligence.management_vs_numbers import (
    extract_management_commitments,
    management_vs_numbers,
)
from visualization.components import load_listing_cached, setup_page, render


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else "N/A"))


def _money(value: Any) -> str:
    try:
        number = float(value)
        if pd.isna(number):
            return "N/A"
        return f"₹{number:,.0f} Cr"
    except (TypeError, ValueError):
        return "N/A"


def _metric(label: str, value: Any, help_text: str = "") -> None:
    st.metric(label, value, help=help_text or None)


def _clear_report_caches() -> None:
    import importlib
    ar = importlib.import_module("data.annual_report")
    mvn = importlib.import_module("intelligence.management_vs_numbers")

    for name in (
        "discover_annual_reports", "_download_pdf", "extract_annual_report_pages",
        "build_evidence_index", "annual_report_evidence", "annual_report_risk_signals",
    ):
        fn = getattr(ar, name, None)
        clear = getattr(fn, "clear", None)
        if callable(clear):
            clear()
    for name in ("extract_management_commentary", "management_vs_numbers"):
        fn = getattr(mvn, name, None)
        clear = getattr(fn, "clear", None)
        if callable(clear):
            clear()


def _company_name(ticker: str) -> str:
    try:
        listing, _ = load_listing_cached()
        if listing is not None and not listing.empty:
            match = listing[listing["key"].astype(str).str.upper().eq(ticker.upper())]
            if not match.empty:
                return str(match.iloc[0].get("name") or ticker)
    except Exception:
        pass
    return ticker


def _financial_snapshot(financials: pd.DataFrame) -> tuple[list[dict[str, str]], str]:
    if financials is None or financials.empty:
        return [], "Financial statements are not available from the connected provider."
    latest = financials.iloc[-1]
    previous = financials.iloc[-2] if len(financials) > 1 else None
    year = str(financials.index[-1])
    rows = []
    for label, key in (("Revenue", "revenue"), ("EBITDA", "ebitda"), ("PAT", "pat"), ("Operating cash flow", "cfo")):
        value = latest.get(key, float("nan"))
        prior = previous.get(key, float("nan")) if previous is not None else float("nan")
        delta = "N/A"
        try:
            current_f, prior_f = float(value), float(prior)
            if pd.notna(current_f) and pd.notna(prior_f) and abs(prior_f) > 1e-12:
                delta = f"{(current_f / prior_f - 1) * 100:+.1f}% YoY"
        except (TypeError, ValueError):
            pass
        rows.append({"Metric": label, "Latest reported value": _money(value), "YoY": delta})
    source = str(financials.attrs.get("source", "Source metadata unavailable"))
    return rows, f"{year} · {source}"


ticker = setup_page("Annual Report & Management Intelligence")
if not ticker:
    st.stop()

company_name = _company_name(ticker)

st.markdown(
    """
    <style>
    .ari-hero{border:1px solid rgba(56,189,248,.30);border-radius:18px;padding:20px 22px;margin-bottom:14px;
      background:radial-gradient(circle at 90% 5%,rgba(14,165,233,.17),transparent 36%),linear-gradient(125deg,rgba(9,31,50,.98),rgba(4,16,29,.98));}
    .ari-kicker{color:#56d8f4;text-transform:uppercase;letter-spacing:.13em;font-size:11px;font-weight:800;margin-bottom:7px}
    .ari-title{color:#f3f8fc;font-size:clamp(24px,2.5vw,34px);font-weight:850;letter-spacing:-.035em;margin:0;line-height:1.12}
    .ari-sub{color:#9fb4c5;font-size:14px;margin-top:8px;line-height:1.5}
    .ari-pill{display:inline-block;border:1px solid rgba(56,189,248,.25);background:rgba(12,42,61,.6);border-radius:999px;padding:5px 9px;color:#bdefff;font-size:11px;font-weight:700;margin:8px 6px 0 0}
    .ari-panel{border:1px solid rgba(71,145,184,.25);border-radius:15px;background:linear-gradient(145deg,rgba(11,36,55,.90),rgba(4,18,31,.92));padding:15px 16px;margin-bottom:12px}
    .ari-panel h3{color:#eaf5fc;font-size:16px;font-weight:800;margin:0 0 9px}
    .ari-muted{color:#93aabd;font-size:12px;line-height:1.5}
    .ari-risk{border:1px solid rgba(148,163,184,.18);border-left:4px solid #eab308;border-radius:11px;padding:12px 14px;margin:8px 0;background:rgba(9,26,41,.72)}
    .ari-risk.high{border-left-color:#fb7185}.ari-risk.review{border-left-color:#fbbf24}
    .ari-risk-title{color:#eaf3fa;font-weight:800;font-size:14px;margin-bottom:4px}
    .ari-risk-body{color:#c5d3df;font-size:13px;line-height:1.48}
    .ari-risk-meta{color:#8ea7b9;font-size:11px;margin-top:6px}
    div[data-testid="stSegmentedControl"] button{font-weight:700!important;font-size:12px!important}
    [data-testid="stMetric"]{background:rgba(9,29,46,.78);border:1px solid rgba(73,145,183,.22);padding:12px;border-radius:12px;min-height:94px}
    [data-testid="stMetricLabel"]{color:#9eb3c2!important;font-size:12px!important}
    [data-testid="stMetricValue"]{color:#f3f8fc!important;font-weight:800!important}
    [data-testid="stDataFrame"]{border:1px solid rgba(71,145,184,.20);border-radius:10px;overflow:hidden}
    </style>
    """,
    unsafe_allow_html=True,
)

header_left, header_right = st.columns([5, 1.2], vertical_alignment="center")
with header_left:
    render(
        f'<div class="ari-hero"><div class="ari-kicker">Red Flag Intelligence / Company Analysis</div>'
        f'<h1 class="ari-title">{esc(company_name)}</h1>'
        f'<div class="ari-sub">{esc(ticker)} · Annual Report & Management Intelligence</div>'
        '<span class="ari-pill">Evidence-first</span><span class="ari-pill">Page-linked disclosures</span>'
        '<span class="ari-pill">Management accountability</span></div>'
    )
with header_right:
    refresh_report = st.button("↻ Refresh report", key=f"ari_refresh_{ticker}", use_container_width=True)
    browser_retry = st.button("Browser fallback", key=f"ari_browser_{ticker}", use_container_width=True, help="Use Selenium/Chrome only when normal NSE/BSE retrieval fails. This can take longer.")

basis = st.radio(
    "Financial statement basis",
    ["Consolidated", "Standalone"],
    horizontal=True,
    index=0,
    key=f"ari_basis_{ticker}",
    help="Consolidated is the default equity-research view. Standalone is the parent-company view.",
)

if refresh_report:
    _clear_report_caches()
    st.rerun()

with st.spinner("Checking exchange filings and extracting the latest annual report…"):
    result = annual_report_evidence(ticker, basis, use_browser_fallback=browser_retry)

reports = result.get("reports") if isinstance(result.get("reports"), pd.DataFrame) else pd.DataFrame()
evidence = result.get("evidence") if isinstance(result.get("evidence"), pd.DataFrame) else pd.DataFrame()
latest_url = str(result.get("latest_url") or "")
pages = result.get("pages") or []
period = str(result.get("period") or "N/A")
extraction_status = str(result.get("extraction_status") or "pdf_unavailable")
source = str(result.get("source") or "Exchange source unavailable")

# Load a local cached statement frame for a compact financial snapshot. It is
# stale-first; first-time network retrieval still uses parallel statement calls.
financials = pd.DataFrame()
financial_error = ""
try:
    financials = get_source_preserving_financials(ticker)
except DataUnavailable as exc:
    financial_error = str(exc)
except Exception as exc:
    financial_error = f"{type(exc).__name__}: financial statement data unavailable"

risk_signals = annual_report_risk_signals(latest_url) if latest_url and pages else pd.DataFrame()
found_topics = int(evidence["Status"].astype(str).eq("Found").sum()) if not evidence.empty and "Status" in evidence.columns else 0
page_count = len(pages)

# Persist annual-report and management findings separately. Switching tabs or
# navigating away must not silently erase previously reviewed evidence.
linked_key = f"linked_report_intelligence_{ticker}"
annual_linked_key = f"linked_report_annual_{ticker}"
management_linked_key = f"linked_report_management_{ticker}"
linked_source_key = f"linked_report_source_{ticker}"
previous_report_url = str(st.session_state.get(linked_source_key, "") or "")
if latest_url and previous_report_url and latest_url != previous_report_url:
    # Do not carry management checks from a superseded annual report into the new one.
    st.session_state.pop(management_linked_key, None)
if latest_url:
    st.session_state[linked_source_key] = latest_url
    if pages:
        st.session_state[annual_linked_key] = risk_signals.to_dict(orient="records") if not risk_signals.empty else []
else:
    st.session_state.pop(annual_linked_key, None)
    st.session_state.pop(management_linked_key, None)
    st.session_state.pop(linked_source_key, None)

evidence_coverage = (100.0 * found_topics / len(evidence)) if not evidence.empty else None
metric_cols = st.columns(5)
with metric_cols[0]:
    _metric("Report period", period, "Period reported in the source filing")
with metric_cols[1]:
    _metric("Pages extracted", f"{page_count:,}" if page_count else "N/A", "Actual PDF pages with successful extraction")
with metric_cols[2]:
    _metric("Evidence coverage", f"{evidence_coverage:.0f}%" if evidence_coverage is not None else "N/A", f"{found_topics} of {len(evidence)} configured topics located with page references")
with metric_cols[3]:
    _metric("Disclosure signals", len(risk_signals), "Evidence pointers for analyst review; not confirmed red flags")
with metric_cols[4]:
    _metric("Report status", "Parsed" if extraction_status == "text_extracted" else ("PDF only" if extraction_status == "pdf_retrieved_but_text_unavailable" else "Unavailable"))

if latest_url:
    source_col, download_col = st.columns([4, 1.2])
    with source_col:
        st.markdown(f"**Primary source:** [{esc(period)} · Open original exchange attachment]({latest_url})")
        st.caption(f"Source: {source} · Statement basis: {basis}")
    with download_col:
        st.link_button("Open annual report PDF ↗", latest_url, use_container_width=True)
else:
    st.warning(f"Annual report attachment not retrieved. {source}. No quotes, page numbers or management conclusions have been inferred.")
    st.caption("Normal retrieval intentionally avoids launching Chrome in the background. Use the Browser fallback button above only when the official exchange endpoints do not return an attachment.")

views = ["Executive Summary", "Annual Report Analysis", "Management Commentary", "Promise vs Actual", "Risk Signals"]
view = st.segmented_control(
    "Intelligence workspace",
    options=views,
    default="Executive Summary",
    key=f"ari_view_{ticker}",
)
view = view or "Executive Summary"

management_result: dict[str, Any] = {}
if view in {"Management Commentary", "Promise vs Actual", "Risk Signals"} and latest_url:
    with st.spinner("Extracting management statements and checking reported financial trends…"):
        try:
            management_result = management_vs_numbers(ticker, basis)
        except Exception as exc:
            management_result = {"commentary": pd.DataFrame(), "checks": pd.DataFrame(), "error": f"{type(exc).__name__}: management analysis unavailable"}

commentary = management_result.get("commentary") if isinstance(management_result.get("commentary"), pd.DataFrame) else pd.DataFrame()
checks = management_result.get("checks") if isinstance(management_result.get("checks"), pd.DataFrame) else pd.DataFrame()
commitments = extract_management_commitments(commentary) if not commentary.empty else pd.DataFrame()

if not checks.empty:
    contradicted = checks[checks["Status"].astype(str).isin(["Contradicts", "Mixed"])].copy()
    management_records = []
    for _, row in contradicted.iterrows():
        management_records.append({
            "Finding ID": f"MGMT-{ticker}-{str(row.get('Theme', 'theme')).replace(' ', '-')}",
            "Disclosure area": f"Management vs numbers · {row.get('Theme', 'N/A')}",
            "Attention": "Contradiction — analyst review" if str(row.get("Status")) == "Contradicts" else "Mixed evidence",
            "Page": "See management statement evidence",
            "Evidence": str(row.get("Analyst interpretation", "N/A")),
            "Interpretation": "Management narrative and financial trend require investigation; not proof of misconduct.",
            "Source": latest_url,
        })
    st.session_state[management_linked_key] = management_records

# Forensic Red Flags reads this combined evidence list. The score engine does not.
linked_records = (
    list(st.session_state.get(annual_linked_key, []))
    + list(st.session_state.get(management_linked_key, []))
)
st.session_state[linked_key] = linked_records

# -----------------------------------------------------------------------------
# Executive Summary
# -----------------------------------------------------------------------------
if view == "Executive Summary":
    left, right = st.columns([1.25, 1], gap="medium")
    with left:
        st.markdown('<div class="ari-panel"><h3>Executive Summary</h3>', unsafe_allow_html=True)
        if latest_url and extraction_status == "text_extracted":
            st.write(
                f"The latest available annual-report attachment for {company_name} was retrieved from {source}. "
                f"The extractor processed {page_count:,} pages and located {found_topics} of {len(evidence)} configured disclosure topics. "
                f"It also surfaced {len(risk_signals)} disclosure-led review signals. These are research prompts, not automatic conclusions about fraud or misstatement."
            )
        elif latest_url:
            st.write("The official annual-report attachment is available, but automated text extraction did not produce usable page text. The original PDF remains the source of truth; no page-level finding is inferred.")
        else:
            st.write("The annual-report attachment is not currently available from the configured exchange retrieval sources. The page will retain N/A until a verifiable document is retrieved.")
        st.markdown('</div>', unsafe_allow_html=True)
        if not financials.empty:
            fin_rows, fin_note = _financial_snapshot(financials)
            st.markdown('<div class="ari-panel"><h3>Key financials · source-reported</h3>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(fin_rows), use_container_width=True, hide_index=True)
            st.caption(fin_note)
            st.markdown('</div>', unsafe_allow_html=True)
        elif financial_error:
            st.info(financial_error)
    with right:
        st.markdown('<div class="ari-panel"><h3>Research coverage</h3>', unsafe_allow_html=True)
        coverage_rows = [
            {"Research area": "Financial statements", "Status": "Available" if not financials.empty else "N/A"},
            {"Research area": "Annual-report page evidence", "Status": "Available" if found_topics else "N/A"},
            {"Research area": "Auditor / accounting review", "Status": "Available" if not risk_signals.empty else "N/A"},
            {"Research area": "Management commentary", "Status": "Loaded on tab selection" if latest_url else "N/A"},
            {"Research area": "Subsequent-period commitment tracking", "Status": "Requires later filings"},
        ]
        st.dataframe(pd.DataFrame(coverage_rows), use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('<div class="ari-panel"><h3>Analyst workflow</h3><div class="ari-muted">1. Verify original annual-report pages.<br>2. Review accounting and disclosure signals.<br>3. Compare management statements with the reported numbers.<br>4. Carry material issues into Forensic Red Flags for cross-source investigation.</div></div>', unsafe_allow_html=True)


    findings_col, distribution_col = st.columns([1.35, 1], gap="medium")
    with findings_col:
        st.markdown('<div class="ari-panel"><h3>Top findings from annual report</h3>', unsafe_allow_html=True)
        if risk_signals.empty:
            st.info("No configured disclosure review signals were extracted. This is not proof that the report contains no risks.")
        else:
            for _, row in risk_signals.head(5).iterrows():
                attention = str(row.get("Attention", "Review"))
                css = "high" if "High" in attention else "review"
                render(
                    f'<div class="ari-risk {css}"><div class="ari-risk-title">{esc(row.get("Disclosure area"))} · {esc(attention)}</div>'
                    f'<div class="ari-risk-body">{esc(row.get("Evidence"))}</div>'
                    f'<div class="ari-risk-meta">{esc(row.get("Finding ID"))} · PDF page {esc(row.get("Page"))}</div></div>'
                )
        st.markdown('</div>', unsafe_allow_html=True)
    with distribution_col:
        st.markdown('<div class="ari-panel"><h3>Disclosure review distribution</h3>', unsafe_allow_html=True)
        if risk_signals.empty:
            st.info("Distribution unavailable until report text is extracted.")
        else:
            distribution = risk_signals.groupby("Attention", dropna=False).size().rename("Findings").reset_index()
            st.dataframe(distribution, use_container_width=True, hide_index=True)
            st.caption("Counts reflect extracted disclosure patterns requiring analyst review, not confirmed violations or a fraud score.")
        st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Annual Report Analysis
# -----------------------------------------------------------------------------
elif view == "Annual Report Analysis":
    st.markdown("#### Annual-report evidence map")
    st.caption("Every located topic links to the original PDF and its extracted page. 'Not located' is not evidence that the disclosure or risk is absent.")
    if evidence.empty:
        st.info("No page-level text evidence is available. Check the PDF retrieval status above.")
    else:
        display = evidence[["Topic", "Status", "Page", "Basis", "Evidence quote"]].copy()
        display["Page"] = display["Page"].map(lambda value: "N/A" if pd.isna(value) else str(value))
        st.dataframe(display, use_container_width=True, hide_index=True, height=520)
    st.markdown("#### Disclosure review signals")
    if risk_signals.empty:
        st.info("No configured disclosure patterns were located in the extracted text. This does not establish that the company has no risks.")
    else:
        for _, row in risk_signals.iterrows():
            css = "high" if "High" in str(row["Attention"]) else "review"
            render(
                f'<div class="ari-risk {css}"><div class="ari-risk-title">{esc(row["Disclosure area"])} · {esc(row["Attention"])}</div>'
                f'<div class="ari-risk-body">{esc(row["Evidence"])}</div>'
                f'<div class="ari-risk-meta">{esc(row["Finding ID"])} · PDF page {esc(row["Page"])} · Disclosure requires analyst validation</div></div>'
            )
    with st.expander("Annual-report diligence checklist", expanded=False):
        checks_list = [
            "Read consolidated financial statements and notes to accounts.",
            "Review auditor opinion, key audit matters and internal financial controls.",
            "Inspect related-party transactions, loans, guarantees and balances.",
            "Reconcile contingent liabilities, tax disputes and pending litigation.",
            "Compare exceptional items and accounting-policy changes over multiple years.",
            "Review subsidiaries, joint ventures, segment contribution and capital allocation.",
        ]
        for item in checks_list:
            st.markdown(f"- {item}")

# -----------------------------------------------------------------------------
# Management Commentary
# -----------------------------------------------------------------------------
elif view == "Management Commentary":
    st.markdown("#### Management statements and financial validation")
    if commentary.empty:
        st.info("Management commentary was not extracted from the MD&A / Directors' Report sections, or the annual-report text is unavailable.")
    else:
        m1, m2, m3 = st.columns(3)
        with m1: _metric("Evidence statements", len(commentary))
        with m2: _metric("Themes identified", int(commentary["Theme"].nunique()))
        with m3: _metric("Contradictions", int(checks["Status"].astype(str).eq("Contradicts").sum()) if not checks.empty else 0)
        commentary_display = commentary[["Theme", "Tone", "Page", "Statement"]].copy()
        commentary_display["Page"] = commentary_display["Page"].map(lambda value: "N/A" if pd.isna(value) else str(value))
        st.dataframe(commentary_display, use_container_width=True, hide_index=True, height=420)
    if not checks.empty:
        st.markdown("#### Management narrative vs reported numbers")
        st.caption("A contradiction is a review prompt. It is not, by itself, proof that management has misled investors.")
        st.dataframe(checks[["Theme", "Financial check", "Status", "Analyst interpretation"]], use_container_width=True, hide_index=True)
    elif latest_url:
        st.info("No comparable financial validation was available for the extracted management themes.")

# -----------------------------------------------------------------------------
# Promise vs Actual
# -----------------------------------------------------------------------------
elif view == "Promise vs Actual":
    st.markdown("#### Management commitments tracker")
    st.caption("Forward-looking statements are captured from the annual report. Delivery status is not guessed: later-period filings are needed to verify completion.")
    if commitments.empty:
        st.info("No clear forward-looking commitment statements were located in the extracted management commentary.")
    else:
        st.metric("Candidate commitments", len(commitments))
        st.dataframe(commitments, use_container_width=True, hide_index=True, height=420)
        st.warning("All entries remain 'Needs subsequent-period validation' until later annual reports, results, exchange filings or project disclosures confirm actual delivery.")
    if not checks.empty:
        st.markdown("#### Current-period financial checks")
        st.dataframe(checks[["Theme", "Financial check", "Status", "Analyst interpretation"]], use_container_width=True, hide_index=True)

# -----------------------------------------------------------------------------
# Risk Signals & Forensic hand-off
# -----------------------------------------------------------------------------
elif view == "Risk Signals":
    st.markdown("#### Findings requiring analyst review")
    st.caption("This combines disclosure pointers and management-versus-number observations. It does not label a company fraudulent and does not duplicate the sector forensic score.")
    if risk_signals.empty and checks.empty:
        st.info("No page-linked review signals or management checks are available from this report retrieval.")
    else:
        if not risk_signals.empty:
            st.markdown("**Annual-report disclosures**")
            st.dataframe(risk_signals[["Finding ID", "Disclosure area", "Attention", "Page", "Evidence"]], use_container_width=True, hide_index=True)
        if not checks.empty:
            selected_checks = checks[checks["Status"].astype(str).isin(["Contradicts", "Mixed"])].copy()
            st.markdown("**Management narrative vs financial performance**")
            if selected_checks.empty:
                st.success("No contradiction or mixed-status management checks were triggered by the available comparison.")
            else:
                st.dataframe(selected_checks[["Theme", "Financial check", "Status", "Analyst interpretation"]], use_container_width=True, hide_index=True)
    st.markdown("#### Continue to forensic investigation")
    st.caption("The same annual-report findings are stored for the Forensic Red Flags page as linked evidence. They are not counted twice in the risk score.")
    if st.button("Open Forensic Red Flags →", type="primary", key=f"ari_open_forensic_{ticker}"):
        st.switch_page("pages/3_Forensic_Red_Flags.py")

st.divider()
st.caption("Evidence policy: unavailable source data remains N/A. A disclosure pattern is a review signal, not a verified misstatement. All material findings must be checked against the original document and relevant subsequent filings.")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
