"""Reusable Institutional Premium UI components (HTML strings rendered with st.markdown)."""
from __future__ import annotations

from typing import Iterable, List, Optional

import pandas as pd
import streamlit as st

from core.config import CONFIG
from core.constants import GRADE_COLORS, RedFlag
from core.scoring_engine import CompanyAnalysis, analyze_universe, summary_frame
from utils.custom_css import icon, inject_css

_TONE_FOR_SEV = {"Low": "blue", "Medium": "amber", "High": "red", "Critical": "crit"}
_TONE_FOR_GRADE = {"Low": "green", "Medium": "amber", "High": "red", "Critical": "crit"}


def render(html: str) -> None:
    """Render HTML safely: collapse whitespace so Markdown does not treat indented lines as code blocks."""
    st.markdown("".join(line.strip() for line in html.splitlines()), unsafe_allow_html=True)


def setup_page(title: str = "", sidebar_picker: bool = True) -> Optional[str]:
    """Return the selected company ticker, or send the user to Welcome first."""
    ticker = st.session_state.get("ticker")
    if not ticker:
        st.switch_page("pages/0_Welcome.py")
    return ticker


@st.cache_data(show_spinner="Loading NSE + BSE listings…", ttl=24 * 3600)
def load_listing_cached():
    """(listing DataFrame, source note). Columns: key, symbol, name, exchange, isin, is_demo, label."""
    from data.fetch_universe import build_listing
    return build_listing()


@st.cache_data(show_spinner="Analysing company…", ttl=CONFIG.cache_ttl_seconds)
def _analysis(ticker: str) -> CompanyAnalysis:
    from core.scoring_engine import analyze_company
    return analyze_company(ticker)



@st.cache_data(ttl=1800, show_spinner=False)
def prefetch_company_sources(ticker: str) -> bool:
    """Fully warm the selected company's page data before opening Company Overview.

    The Welcome screen intentionally waits for this function to finish. This restores
    the original dashboard behaviour: once Company Overview opens, the company-specific
    source work needed by the analysis pages has already been fetched and cached.

    Fast/independent network families run in parallel. Annual-report extraction is kept
    as one dependent pipeline so the same PDF is reused by Annual Report Intelligence
    and Management Intelligence instead of being downloaded twice.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from data.public_sources import (
        fetch_agency_rating_reports,
        fetch_brsr_filings,
        fetch_brsr_xbrl_metrics,
        fetch_credit_announcements,
        fetch_crisil_esg_rating,
        fetch_governance_announcements,
        fetch_governance_filings,
        fetch_governance_xbrl_summary,
        fetch_yahoo_esg,
        fetch_rating_rationale_summary,
    )
    from data.fetch_yahoo import fetch_all
    from data.annual_report import annual_report_evidence
    from intelligence.corporate_regulatory import fetch_corporate_regulatory_events
    from intelligence.management_vs_numbers import management_vs_numbers
    from core.scoring_engine import analyze_company

    # These are independent and are the main source families used by the company
    # analysis pages. Run them together so the slowest source determines the wait,
    # rather than the sum of every network call.
    jobs = {
        "analysis": lambda: analyze_company(ticker),
        "yahoo": lambda: fetch_all(ticker),
        "governance_filings": lambda: fetch_governance_filings(ticker),
        "governance_announcements": lambda: fetch_governance_announcements(ticker),
        "brsr_filings": lambda: fetch_brsr_filings(ticker),
        "brsr_xbrl": lambda: fetch_brsr_xbrl_metrics(ticker),
        "crisil_esg": lambda: fetch_crisil_esg_rating(ticker),
        "yahoo_esg": lambda: fetch_yahoo_esg(ticker),
        "credit_announcements": lambda: fetch_credit_announcements(ticker),
        "agency_reports": lambda: fetch_agency_rating_reports(ticker),
        "corporate_regulatory": lambda: fetch_corporate_regulatory_events(ticker, years=5),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception:
                # A failed optional source must not block the whole company from
                # opening. The corresponding page will show its normal N/A state.
                results[name] = None

    # Governance XBRL depends on the filing metadata returned above.
    gov_filings = results.get("governance_filings")
    if isinstance(gov_filings, tuple) and len(gov_filings) == 2:
        try:
            df = gov_filings[0]
            fetch_governance_xbrl_summary(ticker, df.to_json(orient="records"))
        except Exception:
            pass

    # Read the latest annual report completely once. Management Intelligence reuses
    # the same cached annual-report evidence/PDF extraction.
    try:
        annual_report_evidence(ticker, "Consolidated")
    except Exception:
        pass
    try:
        management_vs_numbers(ticker, "Consolidated")
    except Exception:
        pass

    # Warm the latest credit-rating rationales after report discovery. Only the
    # newest few official reports are needed for the Credit Rating page.
    urls = []
    credit = results.get("credit_announcements")
    if isinstance(credit, tuple) and len(credit) == 2 and hasattr(credit[0], "empty") and not credit[0].empty:
        for u in credit[0].get("Source", []).astype(str).tolist()[:2]:
            if u.startswith("http") and u not in urls:
                urls.append(u)

    agency = results.get("agency_reports")
    if agency is not None and hasattr(agency, "empty") and not agency.empty and "URL" in agency.columns:
        for u in agency.head(2)["URL"].astype(str).tolist():
            if u.startswith("http") and u not in urls:
                urls.append(u)

    if urls:
        with ThreadPoolExecutor(max_workers=min(4, len(urls))) as pool:
            list(pool.map(fetch_rating_rationale_summary, urls))

    return True

def get_company_core_data(ticker: str, force_refresh: bool = False):
    """Load the two core Company Overview inputs concurrently.

    This intentionally does not prefetch news, ESG, governance, ratings or other
    slow optional modules. Those sources remain lazy on their own pages.
    """
    from data.fetch_live import get_live_profile, get_source_preserving_financials

    # The company name/exchange is read from the local listing cache instantly.
    # Only the core statements may access Yahoo; that call has a hard 10-second
    # wait budget and returns stale local data first on ordinary page navigation.
    profile = get_live_profile(ticker)
    financials = get_source_preserving_financials(ticker, force_refresh)
    return profile, financials


def get_analysis(ticker: str) -> CompanyAnalysis:
    """Analysis for any listed company. Shows a friendly error and stops the page if data cannot be loaded."""
    from data.fetch_live import DataUnavailable
    try:
        return _analysis(ticker)
    except DataUnavailable as e:
        st.error(f"Could not analyse {ticker}: {e}")
        st.stop()


def try_analysis(ticker: str) -> Optional[CompanyAnalysis]:
    """Like get_analysis but returns None on failure (for multi-company pages)."""
    from data.fetch_live import DataUnavailable
    try:
        return _analysis(ticker)
    except DataUnavailable:
        return None


def notice(text: str, tone: str = "info") -> None:
    """Soft inline notice card."""
    render(f'<div class="rf-card flat" style="margin-bottom:.8rem;display:flex;gap:.7rem;align-items:flex-start">{icon("info", 18, "#0071E3")}<div class="rf-sub" style="font-size:15px">{text}</div></div>')


def na_card(label: str, reason: str = "No data source connected") -> str:
    """Metric card placeholder for modules without real data."""
    return metric_card(label, "N/A", reason, "info", "#6E6E73")


@st.cache_data(show_spinner="Analysing companies…", ttl=CONFIG.cache_ttl_seconds)
def load_universe() -> List[CompanyAnalysis]:
    """Cached full-universe analysis."""
    return analyze_universe()


@st.cache_data(ttl=CONFIG.cache_ttl_seconds)
def load_universe_summary():
    """Cached summary DataFrame (one row per company)."""
    return summary_frame(load_universe())


def hero(title: str, subtitle: str, demo: bool = False) -> None:
    banner = f'<div class="rf-demo">{icon("info", 14)} {CONFIG.demo_banner}</div>' if demo else ""
    render(f'<div class="rf-hero"><h1>{title}</h1><p>{subtitle}</p>{banner}</div>')


def section(title: str, subtitle: str = "", icon_name: str = "") -> None:
    ic = icon(icon_name, 24, "#0071E3") if icon_name else ""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    render(f'<div class="rf-section"><h2>{ic}{title}</h2>{sub}</div>')


def badge(text: str, tone: str = "gray") -> str:
    return f'<span class="rf-badge {tone}">{text}</span>'


def grade_badge(grade: str) -> str:
    return badge(f"{grade} risk", _TONE_FOR_GRADE.get(grade, "gray"))


def severity_badge(sev: str) -> str:
    return badge(sev, _TONE_FOR_SEV[sev])


def metric_card(label: str, value: str, sub: str = "", icon_name: str = "activity", color: str = "") -> str:
    style = f' style="color:{color}"' if color else ""
    return (f'<div class="rf-card"><div class="rf-label">{icon(icon_name, 16)} {label}</div><div class="rf-value"{style}>{value}</div>'
            f'<div class="rf-sub">{sub}</div></div>')


def card_grid(cards: Iterable[str], cols: int = 4) -> None:
    render(f'<div class="rf-grid c{cols}">{"".join(cards)}</div>')


def analyst_flag_view(f: RedFlag) -> str:
    """One-line equity-research interpretation of a financial red flag."""
    code = str(getattr(f, "code", "")).upper()
    title = str(getattr(f, "title", "")).lower()
    mapping = {
        "RT_BENEISH": "This is a screening signal that the accounting pattern deserves a closer look. Check revenue recognition, receivables and accruals before assuming the profit quality is clean.",
        "RT_SLOAN": "A bigger gap between profit and cash means more of the reported earnings depend on accounting accruals. Analysts should check whether that profit is repeatable.",
        "RT_ALTMAN": "The balance sheet does not have as much safety cushion as a low-risk company. Check liquidity, leverage and the ability to absorb an earnings downturn.",
        "RT_CCC": "Cash is taking longer to move through the business. If this continues, the company may need more working capital funding even if reported profit is rising.",
        "CF_CFO_PAT": "Reported profit is not translating into cash strongly enough. In equity research, this is one of the first places to check earnings quality.",
        "CF_CASH_REALIZATION": "Only a limited share of operating profit is arriving as cash. Look at working capital, receivables and inventory for the reason.",
        "CF_NEGATIVE_CFO": "The company is profitable on paper but cash is leaving the operating business. That mismatch needs a clear explanation from the accounts.",
        "CF_DIVERGENCE": "Profit is moving up while operating cash moves down. That does not automatically mean manipulation, but it makes the earnings trend less convincing.",
        "CF_NEG_FCF": "After investment spending, the business is still consuming cash. Check whether this is temporary expansion or a recurring funding requirement.",
        "BS_RECEIVABLES": "Customers are taking longer to pay relative to sales growth. This can pressure cash and, in extreme cases, raise the risk of revenue quality issues.",
        "BS_INVENTORY": "Stock is growing faster than sales, so cash is being tied up in inventory. Check whether demand is slowing or inventory could require a write-down.",
        "BS_CWIP": "A large unfinished-project balance deserves scrutiny because delayed projects can postpone depreciation and later create impairment or write-off risk.",
        "BS_CASH_DEBT": "The company has cash but also carries borrowings. An analyst should understand whether the debt is strategic, temporary or inefficient capital structure.",
        "PNL_SGA_SQUEEZE": "Margins are improving while overheads fall unusually fast. Check whether costs are being capitalised rather than expensed.",
        "PNL_LOW_TAX": "A low tax rate can be legitimate, but if it persists it is important to understand tax benefits, deferred tax and the quality of the reported profit.",
        "PNL_DEP_RATE": "Lower depreciation can lift reported profit without adding cash. Check whether useful lives or asset assumptions have changed.",
        "PNL_INTEREST_COVER": "The earnings cushion over interest is thin. A weaker operating year could put more pressure on lenders and cash flows.",
        "NT_QUALIFIED": "The auditor has raised a qualification or limitation. This should be read directly in the audit report before relying heavily on the reported numbers.",
        "NT_GOING_CONCERN": "This is a major warning: the auditor sees material uncertainty around the company's ability to continue operating without support or restructuring.",
        "NT_KAMS": "Several important accounting areas require significant judgement. Analysts should read those audit matters because they often identify the most sensitive estimates.",
        "NT_POLICY_CHANGE": "A change in accounting policy or estimate can change reported profit without changing the underlying business. Check the before-and-after impact.",
        "NT_CARO": "The auditor has identified control or compliance weaknesses. These do not automatically imply fraud, but they increase the need for deeper diligence.",
    }
    if code in mapping:
        return mapping[code]
    if "receivable" in title:
        return "The main question is whether reported sales are turning into cash at the same pace."
    if "inventory" in title:
        return "The main question is whether stock growth is supported by real demand or is tying up cash."
    if "cash" in title or "cash flow" in title:
        return "The main question is whether accounting profit is backed by real operating cash generation."
    return "Treat this as a review point: understand the reason, check the trend and compare it with peers before drawing a conclusion."


def flag_card(f: RedFlag, show_logic: bool = True) -> str:
    logic = f'<div class="rf-flag-logic"><b>How we test it:</b> {f.logic}</div>' if (show_logic and f.logic) else ""
    yr = f" · {f.year}" if f.year else ""
    analyst = f'<div class="rf-analyst"><b>Analyst view:</b> {analyst_flag_view(f)}</div>'
    return (f'<div class="rf-flag {f.severity.value}"><div class="rf-flag-top"><div><div class="rf-flag-title">{f.title}</div>'
            f'<div class="rf-flag-metric">{f.metric} · rule: {f.threshold}{yr}</div></div>'
            f'<div>{badge(f.category, "gray")} {severity_badge(f.severity.value)}</div></div>'
            f'<div class="rf-flag-text">{f.explanation}</div>{analyst}{logic}</div>')


def render_flags(flags: List[RedFlag], empty: str = "No red flags detected in this area.") -> None:
    if not flags:
        render(f'<div class="rf-card flat">{icon("check", 18, "#34C759")} {empty}</div>')
        return
    render("".join(flag_card(f) for f in flags))


def callout(lines: List[str]) -> None:
    body = "".join(f"<p>{l}</p>" for l in lines)
    render(f'<div class="rf-callout">{body}</div>')


def score_color(value: float, higher_is_better: bool) -> str:
    good = value >= 66 if higher_is_better else value < 34
    bad = value < 40 if higher_is_better else value >= 60
    return "#34C759" if good else ("#FF3B30" if bad else "#FF9F0A")
