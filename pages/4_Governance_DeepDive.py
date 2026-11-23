"""Governance summary from NSE Integrated Filing – Governance and announcements."""
import re
from concurrent.futures import ThreadPoolExecutor, wait
import pandas as pd
import streamlit as st

from data.public_sources import fetch_governance_announcements, fetch_governance_filings, fetch_governance_xbrl_summary, source_links
from visualization.components import hero, section, setup_page, notice, card_grid, metric_card

ticker = setup_page("Governance Deep Dive")
hero(f"{ticker.replace('.NS', '')}: Governance Deep Dive", "Governance coverage is extracted from NSE Integrated Filing – Governance and relevant NSE corporate announcements. No synthetic governance values are created.", demo=False)

retry_col, browser_col, source_col = st.columns([1.1, 1.35, 2.2])
with retry_col:
    refresh_governance = st.button("↻ Refresh NSE data", key=f"refresh_governance_{ticker}", use_container_width=True)
with browser_col:
    browser_retry = st.button("Try browser fallback", key=f"browser_governance_{ticker}", use_container_width=True, help="Uses local Chrome/Selenium only when the direct NSE route does not return records.")
with source_col:
    st.caption("Normal navigation uses short, cached API requests. Browser automation is manual because it can be slower and depends on local Chrome/driver configuration.")
if refresh_governance:
    fetch_governance_filings.clear()
    fetch_governance_announcements.clear()
    fetch_governance_xbrl_summary.clear()
    st.rerun()
if browser_retry:
    st.session_state[f"governance_browser_retry_{ticker}"] = True
    fetch_governance_filings.clear()
    fetch_governance_xbrl_summary.clear()
    st.rerun()
use_browser_fallback = bool(st.session_state.pop(f"governance_browser_retry_{ticker}", False))
# NSE catalogue and corporate-announcement endpoints are independent. Load them
# concurrently and stop waiting after 8 seconds; one slow route must not block
# governance ratios or other dashboard pages.
filings = pd.DataFrame()
ann = pd.DataFrame()
filing_source = "NSE governance catalogue timed out or returned no records"
ann_source = "NSE announcements timed out or returned no records"
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rfi-governance")
_filing_future = _pool.submit(fetch_governance_filings, ticker, use_browser_fallback=use_browser_fallback)
_ann_future = _pool.submit(fetch_governance_announcements, ticker)
try:
    _done, _pending = wait([_filing_future, _ann_future], timeout=8)
    if _filing_future in _done:
        try: filings, filing_source = _filing_future.result()
        except Exception as exc: filing_source = f"NSE governance catalogue error: {type(exc).__name__}"
    if _ann_future in _done:
        try: ann, ann_source = _ann_future.result()
        except Exception as exc: ann_source = f"NSE announcements error: {type(exc).__name__}"
    for _future in _pending:
        _future.cancel()
finally:
    _pool.shutdown(wait=False, cancel_futures=True)

# ------------------------------------------------------------
# Source-backed governance summary
# ------------------------------------------------------------
def _valid_count(df, column):
    if df is None or df.empty or column not in df.columns:
        return 0
    vals = df[column].astype(str).str.strip()
    return int(((vals != "") & (vals.str.lower() != "nan") & (vals.str.lower() != "none")).sum())


def _clean_date_series(df):
    if df is None or df.empty or "Date" not in df.columns:
        return pd.Series(dtype="datetime64[ns]")
    return pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)


def _latest_filing_info(df):
    if df is None or df.empty:
        return "N/A", "N/A"
    work = df.copy()
    if "Date" in work.columns:
        work["_parsed_date"] = _clean_date_series(work)
        work = work.sort_values("_parsed_date", ascending=False, na_position="last")
    row = work.iloc[0]
    date = row.get("Date", "")
    period = row.get("Quarter / Period", "")
    date = "N/A" if pd.isna(date) or str(date).strip().lower() in {"", "nan", "none"} else str(date)
    period = "N/A" if pd.isna(period) or str(period).strip().lower() in {"", "nan", "none"} else str(period)
    return date, period


filing_count = len(filings)
attachment_count = _valid_count(filings, "Attachment")
xbrl_count = _valid_count(filings, "XBRL")
announcement_count = len(ann)
latest_filing_date, latest_period = _latest_filing_info(filings)


def _current_independent_director_count(filing_count_value, period_end_text, announcements_df, company_name):
    """Adjust the filing-period independent-director count for later NSE board changes.

    The Integrated Filing is period-end data. If an independent-director appointment or
    cessation occurs after that period, the dashboard should not present the period-end
    number as the current board count. Only explicit NSE announcements referring to the
    selected company are used; otherwise None is returned.
    """
    base = gov_xbrl.get("independent_directors") if "gov_xbrl" in globals() else None
    if base is None or announcements_df is None or announcements_df.empty:
        return None
    try:
        end_dt = pd.to_datetime(period_end_text, errors="coerce", dayfirst=True)
        if pd.isna(end_dt):
            return None
        work = announcements_df.copy()
        work["_dt"] = pd.to_datetime(work.get("Date", ""), errors="coerce", dayfirst=True)
        work = work[work["_dt"] > end_dt]
        if work.empty:
            return int(base)
        company = str(company_name or "").strip().lower()
        if not company:
            return int(base)
        current = int(base)
        changed = False
        for _, row in work.iterrows():
            typ = str(row.get("Type", "")).lower()
            details = str(row.get("Details", "")).lower()
            blob = f"{typ} {details}"
            if "independent director" not in blob:
                continue
            # Do not count appointments/cessations belonging only to subsidiaries.
            if company and company not in details and company not in typ:
                continue
            if re.search(r"\bappointment\b.*\bindependent director\b|\bindependent director\b.*\bappointment\b", blob):
                current += 1
                changed = True
            elif re.search(r"\b(cessation|ceased|resignation|resigned)\b.*\bindependent director\b|\bindependent director\b.*\b(cessation|ceased|resignation|resigned)\b", blob):
                current = max(0, current - 1)
                changed = True
        return current if changed else int(base)
    except Exception:
        return None

# Parse the latest actual NSE Integrated Filing – Governance XBRL.
# The filing metadata table alone cannot tell us board/committee/compliance facts.
with st.status("Reading the latest NSE governance filing…", expanded=False) as retrieval_status:
    gov_xbrl = fetch_governance_xbrl_summary(
        ticker, filings.to_json(orient="records"), use_browser_fallback=use_browser_fallback
    )
    retrieval_status.update(label="NSE governance filing read", state="complete")

company_name = ""
if filings is not None and not filings.empty and "Company Name" in filings.columns:
    vals = filings["Company Name"].dropna().astype(str).str.strip()
    if not vals.empty:
        company_name = vals.iloc[0]
current_independent = _current_independent_director_count(filing_count, latest_period, ann, company_name)

# Show retrieval diagnostics for every run. This is intentionally available even
# when one field (for example Board Directors) parsed successfully, because a
# partial parse should never hide the remaining source/parser state.
errs = gov_xbrl.get("errors") or []
attempted = gov_xbrl.get("attempted_sources") or gov_xbrl.get("attempted_xbrl_urls") or []
source_hits = gov_xbrl.get("source_hits") or []
with st.expander("NSE source verification", expanded=False):
    status = gov_xbrl.get("parse_status", "failed")
    stage = gov_xbrl.get("retrieval_stage", "") or "not returned"
    core_extracted = int(gov_xbrl.get("core_fields_extracted", 0) or 0)
    core_expected = int(gov_xbrl.get("core_fields_expected", 8) or 8)
    validation_passed = gov_xbrl.get("validation_passed")
    source_hits = gov_xbrl.get("source_hits") or []

    if status == "failed":
        st.error("No governance metrics could be verified from the sources retrieved in this run. This can indicate an NSE timeout, unavailable filing link or parser mismatch; it is not a governance-quality conclusion.")
    elif status == "partial":
        st.warning(f"Verified NSE filing data is available for {core_extracted}/{core_expected} core governance fields. Unavailable fields remain N/A.")
    else:
        st.success("Verified governance rows were extracted from the NSE filing and passed the data-quality checks.")

    st.write("Core governance fields extracted:", f"{core_extracted}/{core_expected}")
    if filing_source:
        st.caption(f"Filing catalogue: {filing_source}")
    if ann_source:
        st.caption(f"Announcement source: {ann_source}")
    if validation_passed is False:
        st.warning("Some candidate values failed the data-quality checks and were excluded. Excluded values are shown as N/A.")
    elif validation_passed is True and core_extracted > 0:
        st.success("Cross-field validation passed for the extracted values.")
    else:
        st.info("Validation rules are active; no additional validated core fields were available in this run.")

    if source_hits:
        st.write("Verified source:", "NSE Integrated Filing – Governance (iXBRL)")
    else:
        st.write("Verified source:", "NSE Integrated Filing – Governance")

    if latest_period != "N/A":
        st.write("Reporting period:", latest_period)
    if latest_filing_date != "N/A":
        st.write("Filing date:", latest_filing_date)

def _fact(key):
    return gov_xbrl.get(key)

def _display_count(key):
    value = _fact(key)
    return "N/A" if value is None else str(value)

def _compliance_label():
    yes, no, na = _fact("affirmations_yes"), _fact("affirmations_no"), _fact("affirmations_na")
    if yes is None and no is None and na is None:
        return "N/A"
    if no and no > 0:
        return f"Attention ({no} No)"
    if yes and na:
        return f"Mostly compliant ({yes} Yes; {na} N/A)"
    if yes:
        return f"Positive ({yes} Yes)"
    return "N/A"

def _governance_interpretation():
    points=[]
    if _fact("board_total") is not None:
        indep = _fact("independent_directors")
        txt = f"The latest NSE governance filing reports **{_fact('board_total')} directors for the filing period**"
        if indep is not None:
            txt += f", including **{indep} independent directors**."
        else:
            txt += "."
        points.append(txt)
    committee_parts=[]
    for label,key in [("Audit Committee","audit_members"),("NRC","nrc_members"),("Stakeholders Committee","stakeholder_members"),("Risk Management Committee","risk_members")]:
        if _fact(key) is not None:
            committee_parts.append(f"{label}: {_fact(key)} members")
    if committee_parts:
        points.append("Committee structure extracted from XBRL: **" + "; ".join(committee_parts) + ".**")
    if _fact("committee_meetings") is not None:
        q=_fact("committee_quorum_yes")
        if q is not None:
            points.append(f"The filing records **{_fact('committee_meetings')} committee meeting(s)**, with quorum marked Yes for **{q}** of them.")
        else:
            points.append(f"The filing records **{_fact('committee_meetings')} committee meeting(s)**.")
    comp=_compliance_label()
    if comp != "N/A":
        points.append(f"Regulatory affirmation status: **{comp}** based on the statuses actually present in the filing.")
    if _fact("related_party_status"):
        points.append(f"Related-party policy/approval disclosure status captured: **{_fact('related_party_status')}**.")
    if not points:
        points.append("The NSE filing catalog was retrieved, but this run did not validate populated director/committee rows. N/A is a source/parser limitation, not a conclusion about the company's governance. Open the original filing below for verification.")
    return points

# ------------------------------------------------------------
# Easy-to-understand analyst summary
# ------------------------------------------------------------
section(
    "Governance summary",
    "A quick analyst-style view of what the retrieved NSE governance filings tell us.",
    "account_balance",
)

if filing_count == 0:
    if any(_fact(k) is not None for k in ("board_total", "independent_directors", "audit_members", "nrc_members", "stakeholder_members", "risk_members", "cyber_security_count", "investor_grievance_unresolved")):
        st.info(f"NSE filing-index metadata was not returned, but the company governance detail page was retrieved for {ticker}. The governance fields below are read directly from that NSE page.")
    else:
        notice(
            f"No NSE Integrated Filing – Governance records were returned for {ticker}. "
            f"{filing_source}. The page does not infer governance quality when source data is unavailable."
        )
else:
    xbrl_pct = round((xbrl_count / filing_count) * 100, 1) if filing_count else 0
    st.markdown(
        f"**Analyst view:** The latest available NSE governance filing record for **{ticker}** is dated **{latest_filing_date}** "
        f"and the catalog contains **{filing_count} record(s)**. **{xbrl_count}/{filing_count} ({xbrl_pct:.0f}%)** "
        "have an XBRL link. A link confirms filing availability only. Values below are taken from verified rows and each value's source/period appears in Field-level evidence; some fields may use an older official fallback if the latest representation cannot be parsed."
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Board directors", _display_count("board_total"))
    c2.metric("Independent directors (filing period)", _display_count("independent_directors"))
    c3.metric("Audit Committee", _display_count("audit_members"))
    c4.metric("Risk Committee", _display_count("risk_members"))
    c5.metric("Compliance affirmations", _compliance_label())

    if current_independent is not None and _fact("independent_directors") is not None and current_independent != _fact("independent_directors"):
        st.info(
            f"**Board-date distinction:** the filing-period count is **{_fact('independent_directors')}** as of **{latest_period}**. "
            f"NSE post-period announcements indicate **{current_independent} independent director(s)** after subsequent board changes. "
            "The filing-period number is retained for historical accuracy; the post-filing count is shown separately and is not inferred."
        )

    # --------------------------------------------------------
    # Simple analyst read: positives + things to review
    # --------------------------------------------------------
    st.markdown("#### Governance assessment")
    assessment_points = []
    review_points = []

    if _fact("board_total") is not None:
        msg = f"Board structure is disclosed with {_fact('board_total')} director(s) for the filing period"
        if _fact("independent_directors") is not None:
            msg += f", including {_fact('independent_directors')} independent director(s)."
        assessment_points.append(msg)

    committee_values = [
        _fact("audit_members"), _fact("nrc_members"),
        _fact("stakeholder_members"), _fact("risk_members")
    ]
    committee_count = sum(v is not None for v in committee_values)
    if committee_count:
        assessment_points.append(f"{committee_count} key governance committee structure(s) were identified from the latest XBRL filing.")

    if _fact("committee_meetings") is not None:
        q = _fact("committee_quorum_yes")
        if q is not None and q == _fact("committee_meetings"):
            assessment_points.append(f"All {_fact('committee_meetings')} reported committee meeting(s) show quorum met.")
        elif q is not None:
            review_points.append(f"Quorum was marked Yes for {q} of {_fact('committee_meetings')} committee meeting(s); review the exceptions in the original filing.")

    if _fact("board_meetings") is not None:
        bq = _fact("board_quorum_yes")
        if bq is not None and bq == _fact("board_meetings"):
            assessment_points.append(f"All {_fact('board_meetings')} reported board meeting(s) show quorum met.")
        elif bq is not None:
            review_points.append(f"Board meeting quorum was marked Yes for {bq} of {_fact('board_meetings')} reported meeting(s).")

    if _fact("affirmations_no") is not None and _fact("affirmations_no") > 0:
        review_points.append(f"{_fact('affirmations_no')} compliance affirmation(s) are marked No and should be reviewed.")
    elif _fact("affirmations_yes") is not None and _fact("affirmations_yes") > 0:
        assessment_points.append(f"{_fact('affirmations_yes')} compliance affirmation(s) are marked Yes in the latest filing.")

    if _fact("cyber_security_count") is not None:
        if _fact("cyber_security_count") == 0:
            assessment_points.append("The filing reports zero cyber-security incidents/breaches for the reported quarter.")
        else:
            review_points.append(f"The filing reports {_fact('cyber_security_count')} cyber-security incident(s)/breach(es); review the disclosure details.")

    if _fact("investor_grievance_unresolved") is not None:
        if _fact("investor_grievance_unresolved") == 0:
            assessment_points.append("No unresolved investor complaints are reported at quarter-end.")
        else:
            review_points.append(f"{_fact('investor_grievance_unresolved')} investor complaint(s) remain unresolved at quarter-end.")

    if _fact("chairperson_related_to_md_ceo") == "Yes":
        review_points.append("The filing states that the chairperson is related to the MD/CEO; this is a governance point worth reviewing in context.")

    if assessment_points:
        st.markdown("**What looks positive / covered**")
        for item in assessment_points:
            st.markdown(f"- {item}")
    if review_points:
        st.markdown("**What an equity analyst should review**")
        for item in review_points:
            st.markdown(f"- {item}")
    if not assessment_points and not review_points:
        st.warning("Filing metadata and XBRL links were retrieved, but populated governance rows were not validated in this run. Do not interpret N/A as zero or as a governance weakness. Open the original NSE source below to verify the details.")

    st.markdown("#### What the latest filing tells us")
    for item in _governance_interpretation():
        st.markdown(f"- {item}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("NRC members", _display_count("nrc_members"))
    c2.metric("Stakeholder Committee", _display_count("stakeholder_members"))
    c3.metric("Committee meetings", _display_count("committee_meetings"))
    c4.metric("Committee meetings with quorum", _display_count("committee_quorum_yes"))

    # Show source URL and reporting period for each metric. This is essential
    # when a historical iXBRL fallback is used instead of the latest quarter.
    field_sources = gov_xbrl.get("field_sources") or {}
    if field_sources:
        historical_periods = sorted({str(v.get("period") or "").strip() for v in field_sources.values()
                                     if "historical ixbrl fallback" in str(v.get("source", "")).lower() and str(v.get("period") or "").strip()})
        if historical_periods:
            st.info("Some governance metrics are sourced from an older, verified NSE iXBRL filing (" + ", ".join(historical_periods) + "). They are explicitly period-labelled below and should not be interpreted as current-quarter figures.")
        source_labels = {
            "board_total": "Board directors", "independent_directors": "Independent directors",
            "audit_members": "Audit Committee members", "nrc_members": "NRC members",
            "stakeholder_members": "Stakeholder Committee members", "risk_members": "Risk Committee members",
            "committee_meetings": "Committee meetings", "board_meetings": "Board meetings",
            "committee_quorum_yes": "Committee meetings with quorum", "board_quorum_yes": "Board meetings with quorum",
            "affirmations_yes": "Affirmations marked Yes", "affirmations_no": "Affirmations marked No",
            "affirmations_na": "Affirmations marked N/A", "cyber_security_count": "Cyber-security incidents",
            "investor_grievance_unresolved": "Unresolved investor complaints",
        }
        evidence_rows = []
        for key, item in field_sources.items():
            evidence_rows.append({
                "Metric": source_labels.get(key, key.replace("_", " ").title()),
                "Value": _fact(key),
                "Source": item.get("source", "NSE filing"),
                "Reporting period": item.get("period") or "Not identified in source",
                "Source URL": item.get("url", ""),
            })
        with st.expander("Field-level evidence (source and period for each number)", expanded=False):
            evidence_df = pd.DataFrame(evidence_rows)
            # XBRL evidence can legitimately mix numeric counts with text values
            # such as Yes/No/N/A.  Convert the display column to strings so
            # Streamlit/PyArrow does not infer an integer dtype and then fail on
            # a later text value.
            if "Value" in evidence_df.columns:
                evidence_df["Value"] = evidence_df["Value"].map(lambda v: "" if pd.isna(v) else str(v))
            st.dataframe(evidence_df, use_container_width=True, hide_index=True, column_config={
                "Source URL": st.column_config.LinkColumn("Source URL")
            })

    if _fact("affirmations_no") is not None and _fact("affirmations_no") > 0:
        st.warning(f"The latest filing contains {_fact('affirmations_no')} compliance affirmation(s) marked No. Review the underlying XBRL before drawing a governance conclusion.")
    elif _fact("affirmations_yes") is not None and _fact("affirmations_yes") > 0:
        st.success("The latest filing contains positive compliance affirmations; this is a disclosure-based observation, not an independent audit of governance quality.")

    if _fact("cyber_security_text"):
        st.markdown(f"**Cyber-security disclosure:** {_fact('cyber_security_text')}")
    if _fact("investor_grievance_text"):
        st.markdown(f"**Investor-grievance disclosure:** {_fact('investor_grievance_text')}")

    st.caption(
        f"Source: {_fact('source') or gov_xbrl.get('source')}. "
        "N/A means the field was not available or could not be parsed from the retrieved filing; it is not a zero and not a negative finding."
    )

    with st.expander("📖 How to interpret these governance indicators", expanded=True):
        st.markdown("**Use these numbers as a quick equity-research screening tool — not as a standalone governance rating.**")
        st.markdown("### Analyst takeaway — quick research summary")
        analyst_takeaway = []
        bt, ind = _fact("board_total"), _fact("independent_directors")
        if bt is not None and ind is not None and 0 <= ind <= bt and bt > 0:
            ratio = (ind / bt * 100)
            analyst_takeaway.append(f"**Board independence (filing period):** {ind} of {bt} directors are classified as independent (**{ratio:.1f}%**). An analyst should assess whether independent oversight is supported by committee composition and actual participation.")
        elif bt is not None and ind is not None:
            analyst_takeaway.append("**Board independence:** the extracted independent-director count failed validation and is therefore not used in the analyst conclusion.")
        elif bt is not None:
            analyst_takeaway.append(f"**Board structure:** the latest filing reports {bt} directors, but an independent-director count could not be reliably extracted.")
        if _fact("committee_meetings") is not None:
            q = _fact("committee_quorum_yes")
            if q is not None:
                analyst_takeaway.append(f"**Committee functioning:** {q} of {_fact('committee_meetings')} reported committee meetings show quorum met. Any exception should be reviewed in the underlying filing.")
            else:
                analyst_takeaway.append(f"**Committee functioning:** {_fact('committee_meetings')} committee meeting(s) were disclosed; quorum detail was not reliably extracted.")
        if _fact("affirmations_yes") is not None or _fact("affirmations_no") is not None:
            yes = _fact("affirmations_yes") or 0
            no = _fact("affirmations_no") or 0
            na = _fact("affirmations_na") or 0
            if no:
                analyst_takeaway.append(f"**Compliance:** {no} governance affirmation(s) are marked No, versus {yes} Yes and {na} N/A. This is the first item an equity analyst should investigate.")
            else:
                analyst_takeaway.append(f"**Compliance:** the filing contains {yes} Yes affirmation(s) and {na} N/A; no explicit No affirmation was extracted from the filing.")
        if _fact("investor_grievance_unresolved") is not None:
            analyst_takeaway.append(f"**Investor protection:** {_fact('investor_grievance_unresolved')} investor complaint(s) remain unresolved at period-end according to the filing.")
        if not analyst_takeaway:
            analyst_takeaway.append("**Analyst takeaway:** the NSE filing was retrieved, but the underlying governance facts were not reliably extracted. Do not treat the N/A values as a governance conclusion.")
        for item in analyst_takeaway:
            st.markdown(f"- {item}")

        # One-line analyst view that changes with the retrieved filing facts.
        if bt is not None and ind is not None and bt:
            ind_pct = ind / bt * 100
            compliance_no = _fact("affirmations_no") or 0
            unresolved = _fact("investor_grievance_unresolved")
            if compliance_no > 0:
                tone = "**Review required:** the filing contains explicit compliance exceptions."
            elif unresolved is not None and unresolved > 0:
                tone = "**Monitor:** investor grievances remain unresolved at period-end."
            elif ind_pct >= 50:
                tone = "**Generally constructive:** the filing shows a majority of directors classified as independent; assess committee effectiveness, participation and any post-filing board changes."
            else:
                tone = "**Context required:** the filing shows less than half of directors classified as independent; assess board composition, promoter influence, committee independence and actual participation."
            st.info(f"**Analyst time-saving summary:** {tone}")

        interpretation = pd.DataFrame([
            ["Board directors", "Total directors disclosed for the filing period."],
            ["Independent directors", "Directors classified as independent for the filing period. This is not automatically the current board count."],
            ["Audit Committee", "Number of members in the Audit Committee, which oversees financial reporting, audit and internal-control matters."],
            ["NRC", "Nomination & Remuneration Committee. It oversees director/senior-management appointments, evaluation and remuneration."],
            ["Stakeholder Committee", "Committee responsible for shareholder/investor-related matters and grievance handling."],
            ["Risk Committee", "Risk Management Committee membership and oversight of major business/financial risks, where applicable."],
            ["Board Meetings", "Number of Board meetings reported in the filing period."],
            ["Committee Meetings", "Number of committee meetings reported in the filing period."],
            ["Quorum Met", "Number of reported committee meetings where the required minimum attendance was met."],
            ["Compliance affirmations", "Whether the company marked the specified governance/compliance statements Yes, No or N/A."],
            ["Cybersecurity", "Cybersecurity incidents disclosed in the filing, if reported."],
            ["Investor complaints", "Investor complaints received and the number remaining unresolved at period-end, if disclosed."],
        ], columns=["Indicator", "What it means for an analyst"])
        st.dataframe(interpretation, use_container_width=True, hide_index=True)
        st.caption("N/A means the value was not available or could not be reliably extracted from the retrieved NSE filing. It does not mean zero, compliant, or a negative finding.")

section("Filing coverage", "Actual Integrated Filing – Governance records returned by NSE, including attachment and XBRL links where published.", "file")
if not filings.empty:
    cols=[c for c in ["Date","Quarter / Period","Type","Details","Attachment","XBRL","iXBRL"] if c in filings.columns]
    st.dataframe(filings[cols].head(12), use_container_width=True, hide_index=True, column_config={
        "Attachment": st.column_config.LinkColumn("Attachment"),
        "XBRL": st.column_config.LinkColumn("XBRL"),
        "iXBRL": st.column_config.LinkColumn("iXBRL"),
    })
    st.caption(f"Showing up to 12 of {len(filings)} retrieved governance filings. Open the attachment/XBRL to verify the original NSE submission.")
else:
    notice("No integrated governance filing record was returned for this symbol.")

with st.expander("View all retrieved governance announcements"):
    if not ann.empty:
        st.dataframe(ann, use_container_width=True, hide_index=True, column_config={"Source": st.column_config.LinkColumn("Source")})
    else:
        st.info("No governance-related announcements were returned.")

section("Primary sources", "Use the exchange source to verify every governance item before citing it in an equity-research report.", "link")
links=source_links(ticker)
for label,url in links.items():
    if label in ("NSE Governance","NSE Integrated Governance","NSE Announcements"):
        st.markdown(f"- [{label}]({url})")

st.info("This page summarises only governance data actually retrieved from NSE. Missing source fields are shown as N/A rather than assumed to be zero, compliant or non-compliant.")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
