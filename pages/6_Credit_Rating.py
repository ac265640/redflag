"""Credit rating intelligence from NSE and official Indian rating-agency reports."""
from concurrent.futures import ThreadPoolExecutor, wait
import pandas as pd
import streamlit as st

from data.public_sources import (
    RATING_RATIONALE_URLS,
    fetch_credit_announcements,
    source_links,
    fetch_agency_rating_reports,
)
from visualization.components import hero, section, setup_page, notice, card_grid, metric_card

ticker=setup_page("Credit Rating")
hero(f"{ticker}: Credit Rating", "Instrument-level debt ratings from rating agencies, exchange disclosures and clearly labelled issuer-published summaries.", demo=False)

refresh_col, note_col = st.columns([1, 3])
with refresh_col:
    if st.button("Refresh rating sources", type="primary", use_container_width=True):
        fetch_agency_rating_reports.clear()
        fetch_credit_announcements.clear()
        st.rerun()
with note_col:
    st.caption("A completed check means retrieval attempts ended; it does not imply that every agency returned a report. Undated issuer summaries are labelled separately.")

# Agency reports are primary; NSE is an additional source. Show retrieval state.
agency_reports = pd.DataFrame()
ratings = pd.DataFrame()
source = "Credit-rating sources did not return a result."
try:
    with st.status("Checking rating agencies and NSE disclosures concurrently…", expanded=False) as status:
        _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rfi-credit")
        _agency_future = _pool.submit(fetch_agency_rating_reports, ticker)
        _nse_future = _pool.submit(fetch_credit_announcements, ticker)
        _done, _pending = wait([_agency_future, _nse_future], timeout=15)
        if _agency_future in _done:
            try: agency_reports = _agency_future.result()
            except Exception: agency_reports = pd.DataFrame()
        else:
            _agency_future.cancel()
        if _nse_future in _done:
            try: ratings, source = _nse_future.result()
            except Exception as exc: source = f"NSE credit disclosures unavailable: {type(exc).__name__}"
        else:
            _nse_future.cancel()
            source = "NSE credit disclosure lookup timed out; agency results are shown separately if available."
        _pool.shutdown(wait=False, cancel_futures=True)
        status.update(label="Credit-rating source checks complete · timed out sources isolated", state="complete")
except Exception as exc:
    st.warning(f"Credit-rating retrieval encountered a source error: {type(exc).__name__}: {exc}")

if ratings.empty:
    notice(f"{source} No rating is invented. An empty result means this run could not verify a public rating; it does not establish that the company is unrated.")
else:
    latest = ratings.iloc[0]
    card_grid([
        metric_card("Verified rating rows", str(len(ratings)), "NSE + rating agencies", "credit_score"),
        metric_card("Latest agency", str(latest.get("Agency") or "N/A"), str(latest.get("Date") or "N/A"), "business"),
        metric_card("Latest rating", str(latest.get("Rating") or "N/A"), str(latest.get("Outlook") or "N/A"), "credit_score"),
        metric_card("Latest action", str(latest.get("Action") or "N/A"), str(latest.get("Instrument") or "N/A"), "trending_up"),
    ], cols=4)

section("Current ratings & issuer disclosures", "Ratings are instrument/facility specific. Each row identifies whether the evidence is a CRA report, exchange disclosure or an issuer-published summary. Undated issuer summaries are not presented as dated CRA actions.", "credit_score")
show_cols=[c for c in ["Date","Agency","Instrument","Rating","Outlook","Action","Source Type","Source"] if c in ratings.columns]
st.dataframe(ratings[show_cols].head(30), use_container_width=True, hide_index=True, column_config={"Source":st.column_config.LinkColumn("Official source")})

# Latest two reports per agency: enough detail for an analyst while keeping the page fast/readable.
section("Latest rating reports & rationale", "The latest two company-specific public reports found for each agency are shown. Rationale is extracted from the agency report; no synthetic explanation is generated.", "download")
if not agency_reports.empty:
    for agency, grp in agency_reports.groupby("Agency", sort=True):
        st.markdown(f"### {agency}")
        for i, (_, row) in enumerate(grp.head(2).iterrows()):
            title=str(row.get("Title") or "Rating report")
            url=str(row.get("URL") or "")
            with st.container(border=True):
                st.markdown(f"**{title}**")
                c1,c2,c3,c4=st.columns(4)
                c1.metric("Rating", str(row.get("Rating") or "N/A"))
                c2.metric("Outlook", str(row.get("Outlook") or "N/A"))
                c3.metric("Action", str(row.get("Action") or "N/A"))
                c4.metric("Instrument", str(row.get("Instrument") or "N/A"))
                if row.get("Date"):
                    st.caption(f"Report date: {row.get('Date')}")
                rationale=str(row.get("Rationale") or "").strip()
                if rationale:
                    st.markdown("**Why the agency gave/reaffirmed this rating:**")
                    st.write(rationale)
                if url.startswith("http"):
                    # Do not download every PDF/HTML report during page render.
                    # Opening the official report is enough for verification and
                    # keeps this page fast; report bytes are fetched only when the
                    # user opens the source.
                    st.markdown(f"[Open official rating report]({url})")
else:
    if not ratings.empty:
        notice("A rating summary is available in the current ratings table, but a full company-specific CRA rationale report was not retrieved in this run. Open the linked issuer disclosure and refresh the CRA archive lookup before relying on it.")
    else:
        notice("No company-specific CRA report or issuer-published rating summary was retrieved. This is a source-coverage or retrieval limitation; it does not establish that the company is unrated. Use Refresh rating sources to retry.")

section("Credit-risk signals", "Simple flags from retrieved rating actions. These are analyst-review signals, not proof of default.", "warning")
action_rows = ratings[~ratings.get("Source Type", pd.Series("", index=ratings.index)).astype(str).str.contains("issuer summary", case=False, na=False)].copy() if not ratings.empty else pd.DataFrame()
if action_rows.empty:
    a,b,c=st.columns(3); a.metric("Downgrades","N/A"); b.metric("Negative outlook/watch","N/A"); c.metric("Withdrawn","N/A")
    st.info("No dated rating-action event was parsed in this run. The issuer-published rating summary is not an action history, so risk-signal counts are unavailable rather than zero.")
else:
    downgrades=int(action_rows["Action"].astype(str).str.contains("Downgraded",case=False,na=False).sum())
    negative=int(action_rows["Outlook"].astype(str).str.contains("Negative|Watch Negative",case=False,regex=True,na=False).sum())
    withdrawn=int(action_rows["Action"].astype(str).str.contains("Withdrawn",case=False,na=False).sum())
    a,b,c=st.columns(3); a.metric("Downgrades",downgrades); b.metric("Negative outlook/watch",negative); c.metric("Withdrawn",withdrawn)
    if downgrades or negative or withdrawn:
        st.warning("One or more credit-risk signals were found. Read the latest agency rationale before drawing an investment conclusion.")
    else:
        st.info("No downgrade, negative-outlook/watch or withdrawal signal was detected in the rating-action records retrieved. Missing agency data is not a positive signal.")

section("Rating-agency sources", "Primary public agency archives used by the dashboard.", "link")
for agency,url in RATING_RATIONALE_URLS.items():
    st.markdown(f"- [{agency} rating source]({url})")
links=source_links(ticker)
st.markdown(f"- [NSE Corporate Announcements]({links['NSE Announcements']})")
st.markdown(f"- [NSE Credit Rating XBRL]({links['NSE Credit Rating XBRL']})")

st.info("Credit ratings apply to specific debt instruments, facilities or issuers, not to the equity share itself. The dashboard reports the agency's published opinion and the rationale from its own report.")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
