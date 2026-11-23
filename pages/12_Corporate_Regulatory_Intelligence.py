"""Corporate & Regulatory Intelligence — analyst-focused event monitoring."""
from __future__ import annotations

import html
import re
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from urllib.parse import urlparse

from intelligence.corporate_regulatory import fetch_corporate_regulatory_events, event_summary
from intelligence.disclosure_analyzer import (
    analyze_disclosure, event_key, clear_disclosure_analysis_cache,
)
from visualization.components import badge, notice, render, setup_page, load_listing_cached


ticker = setup_page("Corporate & Regulatory Intelligence")

# The listing directory is already cached by the Welcome search. Use it only to
# resolve a human-readable company name; fall back to the selected ticker safely.
company_label = str(ticker)
try:
    listing, _listing_source = load_listing_cached()
    if isinstance(listing, pd.DataFrame) and not listing.empty and "key" in listing.columns and "name" in listing.columns:
        _match = listing[listing["key"].astype(str).str.upper().eq(str(ticker).upper())]
        if not _match.empty:
            company_label = str(_match.iloc[0]["name"])
except Exception:
    pass

# Keep the familiar Red Flag Intelligence visual language, but use clear panels
# and concise analyst labels rather than a raw NSE-announcement dump.
render(
    '<style>'
    '.cri-hero{border:1px solid #dce7df;border-radius:18px;padding:22px 24px;margin-bottom:14px;'
    'background:linear-gradient(135deg,#ffffff 0%,#f2f8f4 100%);box-shadow:0 8px 24px rgba(30,65,44,.06)}'
    '.cri-kicker{color:#16856b;font-size:11px;letter-spacing:.14em;font-weight:800;text-transform:uppercase;margin-bottom:7px}'
    '.cri-title{color:#1f2c24;font-size:clamp(24px,2.4vw,34px);font-weight:850;margin:0;line-height:1.15}'
    '.cri-sub{color:#59685f;font-size:14px;margin-top:8px;line-height:1.55}'
    '.cri-panel{border:1px solid #dce7df;border-radius:15px;background:#ffffff;padding:15px 16px;margin:8px 0 14px;box-shadow:0 4px 14px rgba(30,65,44,.04)}'
    '.cri-muted{color:#68766d;font-size:12px;line-height:1.5}'
    '.cri-event{border:1px solid #dce7df;border-left:4px solid #c28b2c;border-radius:12px;padding:14px 16px;margin:9px 0;background:#ffffff;box-shadow:0 3px 10px rgba(25,50,34,.035)}'
    '.cri-event.urgent{border-left-color:#c24145}.cri-event.review{border-left-color:#c28b2c}.cri-event.monitor{border-left-color:#438b9e}'
    '.cri-event-title{font-weight:800;color:#25352b;font-size:14px;margin-bottom:5px}'
    '.cri-event-body{font-size:13px;line-height:1.55;color:#46564b}'
    '.cri-event-meta{font-size:11px;color:#718077;margin-top:7px}'
    '[data-testid="stMetric"]{background:#ffffff;border:1px solid #dce7df;padding:13px;border-radius:12px;min-height:96px;box-shadow:0 3px 12px rgba(30,65,44,.04)}'
    '[data-testid="stDataFrame"]{border:1px solid #dce7df;border-radius:10px;overflow:hidden;background:#ffffff}'
    '.cri-verdict-status{border:1px solid #d7e4dc;background:#f5faf6;border-radius:12px;padding:14px 16px;margin:8px 0 12px;color:#34483b}'
    '.cri-chart-note{color:#69776e;font-size:12px;margin-top:5px}'
    '</style>'
)

hero_left, hero_right = st.columns([5, 1.35], vertical_alignment="center")
with hero_left:
    render(
        '<div class="cri-hero">'
        '<div class="cri-kicker">Red Flag Intelligence / Company Analysis</div>'
        f'<h1 class="cri-title">{html.escape(company_label)} · {html.escape(str(ticker))}</h1>'
        '<div class="cri-sub" style="font-weight:700;color:#d8f1fb">Corporate &amp; Regulatory Intelligence</div>'
        '<div class="cri-sub">Understand what the company disclosed, why an event matters, and what an equity-research analyst should investigate next.</div>'
        f'<div style="margin-top:10px">{badge("Primary-source led", "blue")} {badge("Event classification", "gray")} {badge("Analyst review queue", "gray")}</div>'
        '</div>'
    )
with hero_right:
    period_label = st.selectbox("Coverage period", ["Last 1 year", "Last 3 years", "Last 5 years"], index=2, key=f"cri_period_{ticker}")
    years = {"Last 1 year": 1, "Last 3 years": 3, "Last 5 years": 5}[period_label]
    refresh = st.button("↻ Refresh filings", key=f"cri_refresh_{ticker}", use_container_width=True)
    if refresh:
        fetch_corporate_regulatory_events.clear()
        clear_disclosure_analysis_cache()
        st.rerun()

with st.spinner(f"Loading {period_label.lower()} of NSE corporate disclosures…"):
    try:
        events, source_note = fetch_corporate_regulatory_events(ticker, years=years)
    except Exception as exc:
        events = pd.DataFrame(columns=["Date", "Type", "Category", "Analyst attention", "Details", "Source"])
        source_note = f"Corporate disclosure source unavailable ({type(exc).__name__})."

if not isinstance(events, pd.DataFrame):
    events = pd.DataFrame(columns=["Date", "Type", "Category", "Analyst attention", "Details", "Source"])
for col in ["Date", "Type", "Category", "Analyst attention", "Details", "Source"]:
    if col not in events.columns:
        events[col] = ""
events = events.copy()

summary = event_summary(events)
urgent_count = int((events["Analyst attention"] == "Urgent review").sum()) if not events.empty else 0
review_count = int((events["Analyst attention"] == "Analyst review").sum()) if not events.empty else 0
monitor_count = int((events["Analyst attention"] == "Monitor").sum()) if not events.empty else 0
routine_count = int((events["Analyst attention"] == "Routine").sum()) if not events.empty else 0

# Overview cards: do not convert announcement counts into an unsupported risk score.
st.markdown("### Corporate intelligence overview")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Disclosures retrieved", f"{summary['events']:,}", help=f"NSE corporate announcements classified for {period_label.lower()}.")
k2.metric("Priority for review", f"{urgent_count + review_count:,}", help="Urgent review plus analyst review. These are workflow priorities, not proven misconduct.")
k3.metric("Regulatory actions", f"{summary['regulatory']:,}", help="Explicit action-type language such as orders, penalties or show-cause notices. Generic SEBI references are excluded.")
k4.metric("Legal matters", f"{summary['legal']:,}", help="Disclosures classified as litigation, claims, court or tribunal matters.")

st.caption(f"Source: {source_note}. Coverage: {period_label.lower()} of NSE corporate announcements. Classification is keyword-assisted and must be checked against the original filing; it is not a legal conclusion or standalone risk score.")

if events.empty:
    notice("No research-category corporate announcements were retrieved for this selection. This does not prove that the company has no legal, regulatory or corporate matters.")

# Category and attention distributions are transparent counts, not a risk gauge.
# Horizontal bars preserve long category labels and use the dashboard's light-theme palette.
def _render_research_bar_chart(labels, values, colors, *, height: int = 300, chart_key: str = "") -> None:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=list(values),
        y=list(labels),
        orientation="h",
        marker={"color": list(colors), "line": {"color": "#ffffff", "width": 1}},
        text=[f"{int(v):,}" for v in values],
        textposition="outside",
        textfont={"family": "Inter, Segoe UI, sans-serif", "size": 12, "color": "#33443a"},
        cliponaxis=False,
        hovertemplate="%{y}<br><b>%{x:,}</b> event(s)<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin={"l": 8, "r": 36, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, Segoe UI, sans-serif", "size": 12, "color": "#46564b"},
        showlegend=False,
        bargap=0.38,
        xaxis={"title": None, "showgrid": True, "gridcolor": "#e8eee9", "zeroline": False,
               "showline": False, "ticks": "", "rangemode": "tozero"},
        yaxis={"title": None, "showgrid": False, "showline": False, "ticks": "",
               "autorange": "reversed", "automargin": True},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": "#cfdcd2", "font": {"color": "#26352c"}},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "responsive": True})

left, right = st.columns([1.3, 1], gap="large")
with left:
    st.markdown("#### Disclosure mix")
    if not events.empty:
        category_series = (
            events["Category"].fillna("").astype(str).str.strip().replace("", "Unclassified")
        )
        category_counts = category_series.value_counts().sort_values(ascending=True)
        if not category_counts.empty:
            palette = ["#77a992", "#4f9278", "#2f8267", "#176f57", "#ba934c", "#a86d55", "#6c8791", "#879b8e"]
            colours = [palette[i % len(palette)] for i in range(len(category_counts))]
            _render_research_bar_chart(
                category_counts.index.tolist(), category_counts.astype(int).tolist(), colours,
                height=max(280, min(460, 58 * len(category_counts) + 100)), chart_key="cri_category_mix",
            )
        else:
            st.caption("No classified categories are available for the retrieved records.")
    else:
        st.caption("Category distribution will appear when source records are available.")
    st.markdown('<div class="cri-chart-note">Counts show retrieved disclosures by their best-fit category. A higher count is not automatically a higher risk.</div>', unsafe_allow_html=True)
with right:
    st.markdown("#### Analyst attention queue")
    attention_labels = ["Urgent review", "Analyst review", "Monitor", "Routine"]
    attention_values = [urgent_count, review_count, monitor_count, routine_count]
    if sum(attention_values) > 0:
        attention_palette = ["#c65353", "#c28b2c", "#438b9e", "#16856b"]
        _render_research_bar_chart(attention_labels, attention_values, attention_palette, height=300, chart_key="cri_attention")
    else:
        st.caption("No classified events to display.")
    st.markdown('<div class="cri-chart-note">Review levels are workflow priorities only; they do not establish wrongdoing or legal liability.</div>', unsafe_allow_html=True)

st.markdown("---")


def _render_primary_source_verdict(row: pd.Series, widget_scope: str) -> None:
    """Render a cached source-grounded analysis for one exchange event."""
    event = row.to_dict()
    stable_id = event_key(str(ticker), event)
    result_key = f"cri_primary_verdict_{stable_id}"
    button_key = f"cri_analyse_{widget_scope}_{stable_id}"
    existing = st.session_state.get(result_key)

    st.caption("The dashboard checks the original filing, reads the document and builds an evidence-linked assessment of what happened and what it may mean for the company.")
    action_label = "Re-read filing & update verdict" if existing else "Analyse original filing & generate analyst verdict"
    if st.button(action_label, key=button_key, use_container_width=True):
        if existing:
            clear_disclosure_analysis_cache()
            st.session_state.pop(result_key, None)
        with st.spinner("Downloading and reading the original filing; building the analyst verdict…"):
            analysis = analyze_disclosure(str(ticker), event)
        st.session_state[result_key] = analysis
        existing = analysis

    if not isinstance(existing, dict):
        source_url = str(event.get("Source", "") or event.get("Original source", ""))
        if source_url.startswith("https://"):
            st.markdown(f"[Open original exchange filing ↗]({source_url})")
            st.caption("No analysis has been run yet. Select the button above to read the filing and prepare an evidence-based verdict.")
        else:
            st.info("The exchange record did not provide a direct document link for this event. No verdict has been generated from the headline alone.")
        return

    if not existing.get("ok"):
        raw_error = str(existing.get("error", "The source document could not be analysed."))
        source_url = str(existing.get("source_url", "") or event.get("Source", "") or event.get("Original source", ""))
        lower_error = raw_error.lower()
        if "not on the approved exchange/regulator source list" in lower_error or "redirect blocked" in lower_error:
            parsed_host = urlparse(source_url).hostname or "not available"
            st.markdown(
                '<div class="cri-verdict-status"><b>Document could not be verified for automated reading</b><br>'
                'The filing record points to a document address that is not yet confirmed as an official exchange or regulator source. '
                'The dashboard has paused the download to avoid analysing an unrelated or altered file. '
                '<b>No company-impact verdict has been generated.</b><br><br>'
                '<b>Next step:</b> Open the original filing below. If the document is published by an official exchange, regulator or issuer, '
                'its document-host domain can be verified and added to the trusted-source configuration.</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"Document host returned by the filing record: {parsed_host} · Not yet verified")
            if source_url.startswith("https://"):
                st.markdown(f"[Open original filing on the exchange / issuer website ↗]({source_url})")
            st.caption("Source verification protects against analysing unrelated or altered documents. This status is not a negative finding about the company.")
        elif "no direct primary-source attachment url" in lower_error:
            st.info("The exchange record has no direct attachment link, so the dashboard could not read the underlying document. No verdict has been generated.")
            if source_url.startswith("https://"):
                st.markdown(f"[Open the available filing record ↗]({source_url})")
        else:
            st.info("The filing could not be retrieved or read on this attempt. No verdict has been generated. Try refreshing the filings or opening the original source directly.")
            if source_url.startswith("https://"):
                st.markdown(f"[Open original filing ↗]({source_url})")
            with st.expander("Technical retrieval detail"):
                st.caption(raw_error)
        return

    mode = str(existing.get("mode", "Document analysis"))
    if mode.startswith("AI-generated"):
        st.success(f"Analysis engine: {mode}")
    else:
        st.info(f"Analysis engine: {mode}. This is a provisional automated assessment, not an LLM-generated opinion.")

    st.markdown("#### Analyst verdict")
    verdict = str(existing.get("verdict", "Insufficient evidence"))
    materiality = str(existing.get("materiality", "Not quantifiable from this filing"))
    confidence = str(existing.get("confidence", "Not stated"))
    m1, m2, m3 = st.columns(3)
    m1.metric("Verdict", verdict)
    m2.metric("Materiality", materiality)
    m3.metric("Confidence", confidence)
    st.write(str(existing.get("summary", "")))
    st.markdown("**Why this verdict**")
    st.write(str(existing.get("verdict_rationale", "No supported rationale was returned.")))

    facts = existing.get("facts", [])
    if facts:
        st.markdown("#### Facts verified from the document")
        for fact in facts[:8]:
            if not isinstance(fact, dict):
                continue
            st.markdown(f"**{fact.get('fact', 'Verified fact')}**")
            st.caption(f"Source p. {fact.get('page', 'N/A')} · {fact.get('evidence', '')}")
    else:
        st.caption("No page-validated factual extracts were available. Treat the verdict as insufficient evidence.")

    impact = existing.get("impact", {})
    if isinstance(impact, dict) and impact:
        st.markdown("#### What this could mean for the company")
        impact_items = list(impact.items())
        for start in range(0, len(impact_items), 2):
            cells = st.columns(2)
            for cell, (label, explanation) in zip(cells, impact_items[start:start + 2]):
                with cell:
                    st.markdown(f"**{label}**")
                    st.write(str(explanation))

    watch_items = existing.get("watch_items", [])
    if watch_items:
        st.markdown("#### What the analyst should monitor next")
        for item in watch_items[:8]:
            st.markdown(f"- {item}")

    limitations = existing.get("limitations", [])
    if limitations:
        st.markdown("#### Evidence limitations & interpretation")
        for item in limitations[:8]:
            st.markdown(f"- {item}")

    pages_read = existing.get("pages_read", "N/A")
    pages_total = existing.get("pages_total", existing.get("source_pages", "N/A"))
    model_pages = existing.get("pages_sent_to_model")
    model_note = f" · AI context: {model_pages} text-bearing page(s)" if model_pages is not None and str(mode).startswith("AI-generated") else ""
    truncated_note = " · AI context was truncated; see limitations" if existing.get("model_context_truncated") else ""
    st.caption(f"Document read: {existing.get('document_type', 'source')} · {pages_read}/{pages_total} text-bearing/total pages · {int(existing.get('characters_reviewed', 0) or 0):,} characters reviewed{model_note}{truncated_note}")
    source_url = str(existing.get("source_url", event.get("Source", "")))
    if source_url.startswith("https://"):
        st.markdown(f"[Open original primary-source filing for verification]({source_url})")


# Priority event cards
st.markdown("### Priority events · Analyst focus")
st.caption("These disclosures have been prioritised for analyst review. Each item explains the event type and offers a source-based investigation; a review priority is not proof of misconduct.")
if not events.empty:
    priority = events[events["Analyst attention"].isin(["Urgent review", "Analyst review"])].copy()
    priority["_sort_date"] = pd.to_datetime(priority["Date"], errors="coerce", dayfirst=True)
    priority = priority.sort_values("_sort_date", ascending=False, na_position="last").drop(columns="_sort_date")
    if priority.empty:
        st.success("No events were classified as urgent or analyst-review priorities in the retrieved records. Continue to monitor routine disclosures.")
    else:
        for idx, row in priority.head(6).iterrows():
            level = str(row.get("Analyst attention", ""))
            tone_class = "urgent" if level == "Urgent review" else "review"
            event_type = html.escape(str(row.get("Type", "Corporate disclosure")))
            raw_date = str(row.get("Date", "")).strip()
            date = html.escape(raw_date if raw_date and raw_date.lower() not in {"date not supplied", "nan", "none"} else "Filing date not provided by exchange record")
            category = str(row.get("Category", "Other corporate disclosure"))
            details = html.escape(str(row.get("Details", "Details not supplied")))
            render(
                f'<div class="cri-event {tone_class}"><div class="cri-event-title">{event_type}</div>'
                f'<div class="cri-event-body">{details}</div>'
                f'<div class="cri-event-meta">{date} · {html.escape(category)} · {html.escape(level)}</div></div>'
            )
            with st.expander(f"Read original filing & see company impact · {row.get('Type', 'Event')}", expanded=False):
                _render_primary_source_verdict(row, "priority")
else:
    st.caption("Priority cards will appear when relevant events are retrieved.")

# Compact timeline: source filing dates are shown as supplied by the exchange.
st.markdown("### Corporate event timeline")
st.caption("Most recent retrieved disclosures first. Timeline dates are filing dates where the exchange record supplies a date.")
if not events.empty:
    timeline = events.copy()
    timeline["_sort_date"] = pd.to_datetime(timeline["Date"], errors="coerce", dayfirst=True)
    timeline = timeline.sort_values("_sort_date", ascending=False, na_position="last").head(8)
    for _, row in timeline.iterrows():
        c_date, c_event, c_category, c_attention = st.columns([1.0, 2.5, 2.0, 1.1])
        c_date.caption(str(row.get("Date", "Date not supplied")))
        c_event.write(str(row.get("Type", "Corporate disclosure")))
        c_category.caption(str(row.get("Category", "Other")))
        c_attention.caption(str(row.get("Analyst attention", "Monitor")))
        st.divider()
else:
    st.caption("No dated event records are currently available.")

# Event explorer with one search field and compact table; full details remain in expanders.
st.markdown("### Corporate event explorer")
st.caption("Search by event title, category or disclosure text, then open a row's details to inspect the primary source.")
search_col, category_col, attention_col = st.columns([2.2, 1.4, 1.3])
with search_col:
    query = st.text_input("Search disclosures", placeholder="e.g. SEBI order, litigation, auditor, pledge", key=f"cri_search_{ticker}")
with category_col:
    category_options = ["All categories"] + sorted(events["Category"].dropna().astype(str).unique().tolist()) if not events.empty else ["All categories"]
    selected_category = st.selectbox("Category", category_options, key=f"cri_category_{ticker}")
with attention_col:
    attention_options = ["All attention levels", "Urgent review", "Analyst review", "Monitor", "Routine"]
    selected_attention = st.selectbox("Attention", attention_options, key=f"cri_attention_{ticker}")

filtered = events.copy()
if query.strip() and not filtered.empty:
    q = query.strip().lower()
    searchable = filtered[["Type", "Category", "Details"]].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    filtered = filtered.loc[searchable.str.contains(re.escape(q), na=False)].copy()
if selected_category != "All categories":
    filtered = filtered[filtered["Category"] == selected_category]
if selected_attention != "All attention levels":
    filtered = filtered[filtered["Analyst attention"] == selected_attention]

if filtered.empty:
    st.info("No disclosures match the current search and filters.")
else:
    display = filtered[["Date", "Type", "Category", "Analyst attention"]].rename(columns={
        "Date": "Filing date", "Type": "Event", "Category": "Category", "Analyst attention": "Attention"
    })
    st.dataframe(display, use_container_width=True, hide_index=True, height=min(460, 42 + 36 * min(len(display), 11)))
    st.caption(f"Showing {len(filtered):,} matching disclosures.")

    st.markdown("#### Select a disclosure for full-document investigation")
    # Keep the complete filtered queue selectable; do not limit AI analysis to
    # an arbitrary first 12 rows while the table can contain hundreds of filings.
    event_options = list(range(len(filtered)))
    def _event_label(position: int) -> str:
        selected_row = filtered.iloc[position]
        return f"{selected_row.get('Date', 'Date not supplied')} · {selected_row.get('Type', 'Corporate disclosure')} · {selected_row.get('Category', 'Unclassified')}"
    selection_key = f"cri_selected_event_{ticker}_{len(filtered)}_{selected_category}_{selected_attention}_{query.strip()[:24]}"
    selected_position = st.selectbox(
        "Choose any retrieved disclosure",
        options=event_options,
        format_func=_event_label,
        key=selection_key,
    )
    selected_row = filtered.iloc[int(selected_position)]
    st.markdown(
        f"**Selected event:** {selected_row.get('Type', 'Corporate disclosure')}  \n"
        f"**Category:** {selected_row.get('Category', 'N/A')} · **Attention:** {selected_row.get('Analyst attention', 'N/A')}"
    )
    _render_primary_source_verdict(selected_row, "explorer")

# Follow-up queue is derived from the disclosure text and never invents open/closed legal status.
st.markdown("### Legal & regulatory follow-up watchlist")
st.caption("This is an analyst follow-up queue, not a court-case status feed. Open/closed status is not inferred when the source does not disclose it.")
if not events.empty:
    watch = events[events["Category"].isin(["Regulatory actions & enforcement", "Legal & litigation"])].copy()
    if watch.empty:
        st.success("No regulatory-action or litigation disclosures were retrieved in this period.")
    else:
        watch_table = watch[["Date", "Type", "Category", "Analyst attention"]].rename(columns={
            "Date": "Filing date", "Type": "Matter / disclosure", "Category": "Matter type", "Analyst attention": "Review priority"
        })
        st.dataframe(watch_table, use_container_width=True, hide_index=True)
else:
    st.caption("The follow-up queue will populate when relevant disclosures are retrieved.")

with st.expander("How the automated disclosure verdict works"):
    st.markdown(
        "1. The dashboard downloads the direct NSE/BSE/regulator attachment.\n"
        "2. It extracts text page by page and retains the page number for every evidence quote.\n"
        "3. When an OpenAI-compatible model is configured, it produces a structured analyst verdict and company-impact assessment.\n"
        "4. Without model credentials, the built-in rules-based reader still extracts facts and produces a clearly labelled provisional assessment.\n\n"
        "The engine separates confirmed facts from potential impact, and a show-cause notice from a final order. If the source cannot be downloaded or read, it displays no verdict rather than guessing from the headline."
    )
    st.markdown("**Enable AI-generated verdicts:** add an API key, base URL and model name under `[disclosure_ai]` in `.streamlit/secrets.toml`. See `DISCLOSURE_AI_SETUP.txt`. Never share or commit the key.")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
