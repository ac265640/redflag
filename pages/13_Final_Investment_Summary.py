"""Investment Summary: one-page synthesis of all dashboard modules."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import pandas as pd
import streamlit as st

from core.constants import fmt
from data.public_sources import (
    fetch_agency_rating_reports,
    fetch_brsr_filings,
    fetch_brsr_xbrl_metrics,
    fetch_governance_filings,
    fetch_governance_xbrl_summary,
    fetch_yahoo_esg,
    yahoo_esg_scores,
)
from data.annual_report import annual_report_evidence
from intelligence.corporate_regulatory import fetch_corporate_regulatory_events, event_summary
from intelligence.management_vs_numbers import management_vs_numbers
from visualization.components import hero, section, setup_page, notice, card_grid, metric_card, get_analysis


def _latest_rating(reports: pd.DataFrame) -> dict:
    if reports is None or reports.empty:
        return {}
    view=reports.copy()
    if "Instrument" in view.columns:
        view["_rank"]=view["Instrument"].astype(str).map(lambda x: 2 if "Short Term" in x or "Commercial Paper" in x else (1 if x not in {"Long Term","Rating"} else 0))
        view=view.sort_values("_rank")
    return view.iloc[0].to_dict()


def _rating_risk(rating: str) -> str:
    r=re.sub(r"[^A-Z0-9+-]", "", str(rating or "").upper())
    order={"AAA":0,"AA+":1,"AA":2,"AA-":3,"A+":4,"A":5,"A-":6,"BBB+":7,"BBB":8,"BBB-":9,"BB+":10,"BB":11,"BB-":12,"B+":13,"B":14,"B-":15,"C":16,"D":17}
    if r not in order:
        return "N/A"
    if order[r] <= 6: return "Low"
    if order[r] <= 9: return "Moderate"
    return "High"


def _verdict(financial_grade: str, credit_level: str, negative_outlook: bool, high_events: int, contradictions: int, governance_attention: bool) -> tuple[str, str]:
    # Live financial grade is derived from sector-applicable checks, not the old
    # absolute-point score bands; do not reuse arbitrary numeric cut-offs.
    severe = financial_grade in {"High", "Critical"} or credit_level == "High" or high_events >= 3
    caution = financial_grade == "Medium" or credit_level == "Moderate" or negative_outlook or high_events > 0 or contradictions > 0 or governance_attention
    if severe:
        return "HIGH CAUTION", "Multiple material risk signals are present. The company needs deeper diligence before an investment conclusion."
    if caution:
        return "CAUTION / MONITOR", "The evidence is not uniformly negative, but one or more areas require follow-up before taking a high-conviction view."
    return "NO MAJOR RED FLAG IN AVAILABLE EVIDENCE", "The retrieved evidence does not show a major cross-module warning. This is a research-screen conclusion, not a buy recommendation."


@st.cache_data(ttl=1800, show_spinner=False)
def _load_summary_sources(ticker: str):
    jobs={
        "credit": lambda: fetch_agency_rating_reports(ticker),
        "brsr": lambda: fetch_brsr_filings(ticker),
        "brsr_xbrl": lambda: fetch_brsr_xbrl_metrics(ticker),
        "gov_filings": lambda: fetch_governance_filings(ticker),
        "yahoo_esg": lambda: fetch_yahoo_esg(ticker),
        "annual": lambda: annual_report_evidence(ticker, "Consolidated"),
        "management": lambda: management_vs_numbers(ticker, "Consolidated"),
        "corporate": lambda: fetch_corporate_regulatory_events(ticker, years=5),
    }
    out={}
    pool = ThreadPoolExecutor(max_workers=8)
    futures={pool.submit(fn): name for name,fn in jobs.items()}
    try:
        from concurrent.futures import as_completed, TimeoutError
        try:
            for f in as_completed(futures, timeout=22):
                name=futures[f]
                try: out[name]=f.result()
                except Exception: out[name]=None
        except TimeoutError:
            pass
        for f, name in futures.items():
            if name not in out:
                out[name]=None
                f.cancel()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    gov_filings=out.get("gov_filings")
    if isinstance(gov_filings,tuple) and len(gov_filings)==2:
        try: out["gov_xbrl"]=fetch_governance_xbrl_summary(ticker, gov_filings[0].to_json(orient="records"))
        except Exception: out["gov_xbrl"]={}
    else:
        out["gov_xbrl"]={}
    return out


ticker=setup_page("Summary")
a=get_analysis(ticker)

hero(
    f"{a.name}: Investment Summary",
    "One-page synthesis of Company Overview, Forensic Red Flags, Governance, ESG, Credit Rating, Annual Report, Management Intelligence and Corporate/Regulatory Intelligence.",
    demo=False,
)

with st.status("Loading available evidence (individual sources are time-limited)…", expanded=False) as status:
    src=_load_summary_sources(ticker)
    completed = sum(v is not None for v in src.values())
    status.update(label=f"Evidence check complete · {completed}/{len(src)} source groups returned", state="complete")

credit=src.get("credit") if isinstance(src.get("credit"),pd.DataFrame) else pd.DataFrame()
latest=_latest_rating(credit)
brsr=src.get("brsr") if isinstance(src.get("brsr"),pd.DataFrame) else pd.DataFrame()
brsr_xbrl=src.get("brsr_xbrl") if isinstance(src.get("brsr_xbrl"),pd.DataFrame) else pd.DataFrame()
yahoo=src.get("yahoo_esg") if isinstance(src.get("yahoo_esg"),pd.DataFrame) else pd.DataFrame()
scores=yahoo_esg_scores(yahoo)
gov=src.get("gov_xbrl") or {}
corp=src.get("corporate")
if isinstance(corp,tuple) and len(corp)==2:
    events, corp_source=corp
else:
    events, corp_source=pd.DataFrame(),"N/A"
management=src.get("management") or {}
checks=management.get("checks") if isinstance(management,dict) else None
contradictions=int((checks["Status"]=="Contradicts").sum()) if isinstance(checks,pd.DataFrame) and not checks.empty and "Status" in checks.columns else 0
corp_sum=event_summary(events) if isinstance(events,pd.DataFrame) else {"events":0,"high":0,"regulatory":0,"legal":0}
negative_outlook=str(latest.get("Outlook","")).lower() in {"negative","watch negative"}
credit_level=_rating_risk(str(latest.get("Rating", "")))
gov_attention=bool(gov.get("affirmations_no")) if isinstance(gov,dict) else False
verdict,verdict_text=_verdict(a.financial.grade,credit_level,negative_outlook,int(corp_sum.get("high",0)),contradictions,gov_attention)

section("Investment conclusion", "The verdict is driven only by retrieved/source-backed evidence. Missing data is not treated as a positive or negative signal.", "task_alt")
if verdict.startswith("HIGH"):
    st.error(f"### {verdict}\n\n{verdict_text}")
elif verdict.startswith("CAUTION"):
    st.warning(f"### {verdict}\n\n{verdict_text}")
else:
    st.success(f"### {verdict}\n\n{verdict_text}")

card_grid([
    metric_card("Sector-screen index", f"{a.financial.score:.0f}/100", "Severity-weighted; not a fraud probability", "search"),
    metric_card("Credit rating", str(latest.get("Rating","N/A")) if latest else "N/A", str(latest.get("Outlook","N/A")) if latest else "No verified report", "credit_score"),
    metric_card("High-attention events", str(corp_sum.get("high",0)), "NSE · last 5 years", "warning"),
    metric_card("Management contradictions", str(contradictions), "Annual-report evidence", "psychology"),
], cols=4)

section("What is driving the verdict", "The most decision-relevant signals from each module.", "layers")

# Financial / forensic
st.markdown("### 1. Financial & Forensic")
latest_fin=a.financials.iloc[-1]
prev_fin=a.financials.iloc[-2] if len(a.financials)>1 else None
fin_points=[]
fin_points.append(f"Sector-aware financial screening index: **{a.financial.score:.0f}/100** (higher means more severe triggered signals; this is not a fraud probability or cross-sector rating).")
if prev_fin is not None and pd.notna(latest_fin.revenue) and pd.notna(prev_fin.revenue) and float(prev_fin.revenue) != 0:
    growth=(latest_fin.revenue/prev_fin.revenue-1)*100
    fin_points.append(f"Latest revenue growth: **{growth:+.1f}% YoY**.")
if pd.notna(latest_fin.get("pat")) and pd.notna(latest_fin.get("cfo")) and float(latest_fin.get("pat")) != 0:
    fin_points.append(f"Operating cash flow / PAT: **{float(latest_fin.get('cfo'))/float(latest_fin.get('pat')):.2f}x**.")
else:
    fin_points.append("Operating cash flow / PAT: **N/A** for the current source/period; no substitute value is used.")
for f in a.financial.flags[:5]:
    fin_points.append(f"**{f.severity.value}: {f.title}** — {f.explanation}")
for x in fin_points: st.markdown(f"- {x}")

# Governance
action=[]
st.markdown("### 2. Governance")
if gov:
    board=gov.get("board_total"); indep=gov.get("independent_directors")
    if board is not None: action.append(f"NSE governance filing reports **{board} directors**" + (f", including **{indep} independent directors**." if indep is not None else "."))
    if gov.get("affirmations_no"): action.append(f"**{gov.get('affirmations_no')} negative compliance affirmation(s)** were present in the retrieved filing and require review.")
    if not action: action.append("Verified NSE governance filing data was retrieved, but no additional high-attention governance signal was available in the parsed fields.")
else:
    action.append("N/A — governance source data was not retrieved in this run; this is not interpreted as good or bad governance.")
for x in action: st.markdown(f"- {x}")

# ESG
st.markdown("### 3. ESG")
if not brsr.empty or not brsr_xbrl.empty:
    st.markdown(f"- NSE BRSR coverage: **{len(brsr)} filing record(s)** and **{len(brsr_xbrl)} parsed metric(s)**. This is disclosure coverage, not an ESG performance score.")
else:
    st.markdown("- N/A — no accessible NSE BRSR/XBRL metrics were retrieved automatically.")
if scores.get("Total ESG") is not None:
    st.markdown(f"- Yahoo supplemental Total ESG: **{scores['Total ESG']:.1f}**. This is supplemental and not used as a substitute for BRSR.")

# Credit
st.markdown("### 4. Credit Rating")
if latest:
    st.markdown(f"- Latest verified agency rating: **{latest.get('Agency','N/A')} {latest.get('Rating','N/A')} / {latest.get('Outlook','N/A')}** for **{latest.get('Instrument','N/A')}**.")
    st.markdown(f"- Action: **{latest.get('Action','N/A')}** · Report date: **{latest.get('Date','N/A')}**.")
    if latest.get("Rationale"):
        st.markdown(f"- **Why:** {latest.get('Rationale')}")
else:
    st.markdown("- N/A — no verified public agency report was retrieved. This does not mean the company is unrated.")

# Annual report / management
st.markdown("### 5. Annual Report & Management")
annual=src.get("annual") or {}
if annual.get("latest_url"):
    st.markdown(f"- Latest NSE annual report: **{annual.get('period','N/A')}**. Evidence topics found: **{int((annual.get('evidence')['Status']=='Found').sum()) if isinstance(annual.get('evidence'),pd.DataFrame) and not annual.get('evidence').empty else 0}**.")
else:
    st.markdown("- Annual-report evidence: **N/A** — official attachment/text was not available to the automated reader.")
if isinstance(checks,pd.DataFrame) and not checks.empty:
    supports=int((checks["Status"]=="Supports").sum())
    mixed=int((checks["Status"]=="Mixed").sum())
    st.markdown(f"- Management-vs-numbers: **{supports} supports, {mixed} mixed, {contradictions} contradicts** across the retrieved themes.")
else:
    st.markdown("- Management commentary: **N/A** — no readable evidence was extracted from the latest annual report.")

# Corporate / regulatory
st.markdown("### 6. Corporate & Regulatory")
if isinstance(events,pd.DataFrame) and not events.empty:
    st.markdown(f"- Retrieved **{len(events)} diligence-relevant NSE events** over the last 5 years, including **{corp_sum.get('high',0)} high-attention** events, **{corp_sum.get('regulatory',0)} regulatory/enforcement** and **{corp_sum.get('legal',0)} legal/litigation** events.")
    high=events[events["Analyst attention"]=="High attention"].head(3)
    for _,row in high.iterrows():
        st.markdown(f"  - **{row.get('Date','N/A')} — {row.get('Category','Event')}:** {row.get('Details','N/A')}")
else:
    st.markdown(f"- {corp_source}. No diligence-relevant event was retrieved automatically; this does not prove that no matter exists.")

section("Analyst conclusion", "Use this as the final screening page before going back to the source documents for investment work.", "insights")
conclusion=[]
if a.financial.grade == "Low": conclusion.append("The currently executable sector-appropriate financial checks did not identify a high screening level. Unavailable tests still need to be reviewed.")
elif a.financial.grade == "Medium": conclusion.append("The sector-aware financial screening level is medium; review the triggered signals, unavailable sector KPIs and original filing evidence.")
else: conclusion.append("The sector-aware financial screening level is elevated and should be resolved through deeper statement, segment and note-level diligence.")
if latest:
    conclusion.append(f"Credit quality is currently assessed as **{credit_level.lower()} risk** based on the retrieved **{latest.get('Rating','N/A')}** rating; read the agency rationale for the exact credit drivers.")
if contradictions: conclusion.append("Management commentary contains at least one contradiction with the reported financial trend; this is a review trigger, not proof of misleading disclosure.")
if corp_sum.get("high",0): conclusion.append("NSE corporate/regulatory disclosures contain high-attention items that should be read in full and reconciled with the financial statements.")
if not conclusion: conclusion.append("No single retrieved module dominates the conclusion; review the cited source documents before making an investment decision.")
for x in conclusion: st.markdown(f"- {x}")

st.info("Investment summary = research screening only. It is not a buy/sell recommendation. N/A means the underlying source could not be verified automatically; it is never treated as a clean signal.")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
