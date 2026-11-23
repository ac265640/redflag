"""Futuristic AI Intelligence Welcome terminal for Indian listed companies."""
from __future__ import annotations
import html
import math
from concurrent.futures import ThreadPoolExecutor, wait
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from visualization.components import load_listing_cached, render
from utils.custom_css import inject_css
from data.market_intelligence import (
    get_index_history, get_market_snapshot, get_market_news,
    get_market_sentiment, get_sector_rotation,
    get_nse_institutional_holdings, get_nse_results_calendar,
)


def safe(v): return html.escape(str(v if v is not None else ""))

def sparkline_svg(index_name, tone):
    history=get_index_history(index_name,"1M")
    if history.empty or "Close" not in history or history["Close"].dropna().empty:
        return ""
    values=pd.to_numeric(history["Close"],errors="coerce").dropna().tail(24).tolist()
    if len(values)<2: return ""
    lo,hi=min(values),max(values); span=(hi-lo) or 1.0
    points=[]
    for i,v in enumerate(values):
        x=2+i*(76/(len(values)-1)); y=24-((v-lo)/span)*21
        points.append(f"{x:.1f},{y:.1f}")
    color="#22e58b" if tone=="positive" else "#fb5267" if tone=="negative" else "#22d3ee"
    return f'<svg class="rf-sparkline" viewBox="0 0 80 27" role="img" aria-label="{safe(index_name)} one-month trend"><polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'

def market_card(row, glyph):
    name=safe(row.get("Index","Index")); value=row.get("Value"); change=row.get("Change"); pct=row.get("Change %")
    if pd.isna(value): val="N/A"; change_text="Market data unavailable"; tone="neutral"
    else:
        val=f"{float(value):,.2f}"
        if pd.isna(change) or pd.isna(pct): change_text="Change unavailable"; tone="neutral"
        else:
            up=float(change)>=0; tone="positive" if up else "negative"
            change_text=f"{'▲' if up else '▼'} {float(change):+,.2f} ({float(pct):+.2f}%)"
    return f'<div class="rf-market-card {tone}"><div class="rf-market-top"><b>{glyph}</b>{name}</div><div class="rf-market-value">{val}</div><div class="rf-market-change">{change_text}</div><div class="rf-market-date">Latest available close · {safe(row.get("As of",""))}</div></div>'

def index_chart(name, period, data=None):
    data = data if isinstance(data, pd.DataFrame) else get_index_history(name,period)
    if data.empty or "Close" not in data or data["Close"].dropna().empty:
        st.info(f"{name}: historical data is temporarily unavailable. No values have been estimated."); return
    close=pd.to_numeric(data["Close"],errors="coerce").dropna(); close=close[close>0]
    if close.empty: st.info(f"{name}: no valid observations returned."); return
    fig=go.Figure(go.Scatter(x=close.index,y=close.values,mode="lines",line=dict(color="#16856B",width=3),fill="tozeroy",fillcolor="rgba(22,133,107,.13)",hovertemplate="%{x|%d %b %Y}<br>Index: %{y:,.2f}<extra></extra>"))
    lo,hi=float(close.min()),float(close.max()); pad=max((hi-lo)*.12,abs(hi)*.001)
    fig.update_layout(height=300,margin=dict(l=12,r=10,t=8,b=8),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",showlegend=False,hovermode="x unified",font=dict(family="Inter",color="#526158",size=11))
    fig.update_xaxes(showgrid=False,zeroline=False,nticks=6); fig.update_yaxes(showgrid=True,gridcolor="rgba(80,105,87,.14)",zeroline=False,range=[lo-pad,hi+pad],tickformat=",.0f")
    st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False,"scrollZoom":False})

st.markdown(r"""<style>
.block-container{padding:1rem 1.25rem 2.2rem!important;max-width:1800px!important}
[data-testid="stAppViewContainer"]{background:radial-gradient(ellipse at 75% 0%,rgba(0,132,190,.18),transparent 38%),linear-gradient(135deg,#03101f,#061b2d 58%,#03101c)}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#031321,#061c2b)!important;border-right:1px solid rgba(34,211,238,.25)}
.rf-terminal-header{position:relative;overflow:hidden;padding:1rem 1.15rem;border:1px solid rgba(34,211,238,.32);border-radius:18px;background:linear-gradient(105deg,rgba(7,29,48,.97),rgba(5,48,70,.78));box-shadow:0 12px 36px rgba(0,0,0,.24);margin-bottom:.85rem}
.rf-terminal-header:after{content:"NSE  |  BSE";position:absolute;right:2%;top:20%;font-size:clamp(25px,4vw,54px);font-weight:900;letter-spacing:.12em;color:rgba(125,211,252,.10);transform:skew(-12deg)}
.rf-brand-line{font-size:clamp(28px,3vw,43px);font-weight:850;letter-spacing:-.04em;color:#f2f9ff}.rf-brand-line span{color:#22d3ee}.rf-brand-sub{color:#b7cad9;font-size:13px;margin-top:5px}.rf-shortcuts{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.rf-shortcuts span{border:1px solid rgba(56,189,248,.25);border-radius:999px;padding:6px 11px;color:#d7f4ff;background:rgba(2,18,31,.55);font-size:12px;font-weight:700}
.rf-search-banner{display:flex;justify-content:space-between;gap:15px;align-items:center;padding:13px 18px;border:1px solid rgba(56,189,248,.48);border-radius:16px;background:linear-gradient(110deg,rgba(25,63,85,.72),rgba(4,23,39,.94));margin:.75rem 0 .45rem}.rf-search-title{font-size:20px;font-weight:800;color:#f1f8ff}.rf-search-sub{font-size:12px;color:#b9cbd8}
.rf-heading{display:flex;align-items:center;gap:9px;color:#f3f9ff;font-weight:850;font-size:20px;margin:14px 0 10px}.rf-heading span{color:#22d3ee}
.rf-market-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:1rem}.rf-market-card{position:relative;overflow:hidden;min-height:132px;padding:13px 15px;border:1px solid rgba(56,189,248,.3);border-radius:16px;background:linear-gradient(145deg,rgba(15,51,69,.92),rgba(4,20,34,.97));box-shadow:0 8px 22px rgba(0,0,0,.18);transition:transform .22s,border-color .22s,box-shadow .22s}.rf-market-card:hover{transform:translateY(-3px);border-color:#22d3ee;box-shadow:0 12px 28px rgba(0,0,0,.3),0 0 18px rgba(34,211,238,.12)}.rf-market-card.positive{background:linear-gradient(145deg,rgba(5,74,67,.62),rgba(4,23,35,.98))}.rf-market-card.negative{background:linear-gradient(145deg,rgba(83,28,48,.52),rgba(4,23,35,.98))}.rf-market-top{display:flex;gap:9px;align-items:center;color:#c9d9e5;font-size:13px;font-weight:800}.rf-market-top b{font-size:19px;color:#22d3ee}.rf-market-value{font-size:26px;font-weight:850;color:#f6fbff;margin:6px 0 1px}.rf-market-change{font-size:12px;font-weight:800;color:#4ade80}.negative .rf-market-change{color:#fb7185}.neutral .rf-market-change{color:#94a3b8}.rf-market-date{font-size:10px;color:#9eb2c3;margin-top:5px}.rf-sparkline{position:absolute;right:12px;top:39px;width:78px;height:27px;opacity:.9;overflow:visible}
.rf-panel{border:1px solid rgba(56,189,248,.28);border-radius:17px;background:linear-gradient(145deg,rgba(11,38,57,.9),rgba(3,18,31,.96));padding:12px 15px;min-width:0}.rf-panel-title{font-size:18px;font-weight:850;color:#f2f8ff;margin-bottom:8px}.rf-news-item{padding:10px 2px;border-top:1px solid rgba(148,190,210,.13)}.rf-news-item a{color:#e7f5ff;text-decoration:none;font-size:12px;font-weight:700;line-height:1.35}.rf-news-item a:hover{color:#22d3ee}.rf-news-meta{color:#93a9ba;font-size:10px;margin-top:4px}
.rf-intel-title{font-size:20px;font-weight:850;color:#f2f8ff;margin:15px 0 10px}.rf-intel-card{border:1px solid rgba(34,211,238,.36);border-radius:15px;background:linear-gradient(145deg,rgba(13,48,68,.96),rgba(3,19,33,.98));padding:11px 12px;min-height:190px;box-shadow:0 8px 22px rgba(0,0,0,.18)}.rf-intel-card h4{font-size:13px;color:#eaf8ff;margin:0 0 9px;font-weight:800}.rf-intel-card .muted{font-size:10px;color:#91aabd}.rf-intel-card .big{font-size:22px;font-weight:850;color:#f4fbff}.rf-intel-card .positive{color:#22e58b}.rf-intel-card .negative{color:#fb5267}.rf-intel-card .neutral{color:#fbbf24}.rf-intel-card table{width:100%;border-collapse:collapse;font-size:10px;color:#dbeaf4}.rf-intel-card th{color:#8fb2c8;text-align:left;font-weight:700;padding:5px 3px;border-bottom:1px solid rgba(148,190,210,.2)}.rf-intel-card td{padding:6px 3px;border-bottom:1px solid rgba(148,190,210,.1)}.rf-source{font-size:9px;color:#829bad;margin-top:7px}.rf-intel-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.rf-gauge{width:100%;height:95px;display:block}.rf-event-row{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid rgba(148,190,210,.12);font-size:10px;color:#dbeaf4}
.rf-workflow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:14px;border:1px solid rgba(34,211,238,.32);border-radius:16px;background:linear-gradient(100deg,rgba(10,48,68,.8),rgba(4,23,38,.95));margin-top:8px}.rf-step{display:flex;gap:9px;align-items:center;color:#dcecf7;font-size:12px}.rf-step b{display:flex;align-items:center;justify-content:center;min-width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#22d3ee,#0284c7);color:#001321;font-size:15px}.rf-step strong{display:block;color:#f4fbff}.rf-step small{color:#9fb6c8}
@media(max-width:1100px){.rf-market-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.rf-intel-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.rf-market-grid{grid-template-columns:1fr 1fr}.rf-intel-grid{grid-template-columns:1fr}.rf-workflow{grid-template-columns:1fr 1fr}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style>""",unsafe_allow_html=True)

# Re-apply the common theme after page-local layout rules so Welcome matches every other page.
inject_css()

def _norm_company_text(value: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _resolve_company_query(query: str, companies: pd.DataFrame):
    """Resolve a single search string to one listed ticker or a list of matches."""
    import re
    raw = str(query or "").strip().upper().replace(" ", "")
    raw = raw.replace("NSE:", "").replace("BSE:", "")
    if not raw:
        return "empty", []
    if re.fullmatch(r"[0-9]{5,6}", raw):
        raw = raw + ".BO"
    if re.fullmatch(r"[A-Z0-9&_-]+\.(?:NS|BO)", raw):
        return "resolved", [raw]
    if companies is None or companies.empty:
        if re.fullmatch(r"[A-Z0-9&_-]+", raw):
            return "resolved", [raw + ".NS"]
        return "not_found", []

    keys = companies["key"].astype(str).str.upper()
    symbols = companies["symbol"].astype(str).str.upper()
    if raw in set(keys):
        return "resolved", [raw]
    exact_symbol = companies.loc[symbols.eq(raw), "key"].astype(str).str.upper().tolist()
    if exact_symbol:
        return ("resolved", [exact_symbol[0]]) if len(exact_symbol) == 1 else ("multiple", exact_symbol)

    # Search company names, symbols and BSE scrip keys using one input only.
    qnorm = _norm_company_text(raw)
    names_norm = companies["name"].astype(str).map(_norm_company_text)
    exact_name = companies.loc[names_norm.eq(qnorm), "key"].astype(str).str.upper().tolist()
    if exact_name:
        return ("resolved", [exact_name[0]]) if len(exact_name) == 1 else ("multiple", exact_name)
    partial = companies.loc[
        names_norm.str.contains(re.escape(qnorm), na=False) | symbols.str.contains(re.escape(raw), na=False),
        "key",
    ].astype(str).str.upper().tolist()
    partial = list(dict.fromkeys(partial))[:30]
    if len(partial) == 1:
        return "resolved", partial
    if partial:
        return "multiple", partial
    # A ticker-shaped NSE symbol can be used even if the local directory is stale.
    if re.fullmatch(r"[A-Z0-9&_-]+", raw):
        return "resolved", [raw + ".NS"]
    return "not_found", []


render('<div class="rf-terminal-header"><div class="rf-brand-line">Red Flag <span>Intelligence</span></div><div class="rf-brand-sub">Indian Equity Research Terminal · Institutional research, forensic risk, governance, ESG and credit analysis.</div><div class="rf-shortcuts"><span>⌕ Forensic Analysis</span><span>♜ Governance</span><span>◈ ESG</span><span>▤ Credit Intelligence</span><span>▥ Investment View</span></div></div>')
render('<div class="rf-search-banner"><div><div class="rf-search-title">Start Company Analysis</div><div class="rf-search-sub">One search for company name, NSE symbol, BSE code or exchange ticker</div></div><div class="rf-search-sub">Select a company and open its research workspace →</div></div>')
listing,source=load_listing_cached()
real = listing[~listing["is_demo"].astype(bool)].copy() if listing is not None and not listing.empty else pd.DataFrame()
# Searchable company picker: Streamlit shows matching exchange-listed names while typing.
# The displayed option contains name + symbol + exchange + canonical ticker so all are searchable.
if not st.session_state.get("_welcome_company_picker_v4_initialized"):
    for _legacy_key in (
        "welcome_search_query", "welcome_search_matches", "welcome_match_choice",
        "welcome_search_query_v3", "welcome_search_matches_v3",
    ):
        st.session_state.pop(_legacy_key, None)
    st.session_state.pop("welcome_company_picker_v4", None)
    st.session_state["_welcome_company_picker_v4_initialized"] = True

prior_ticker = str(st.session_state.get("ticker") or "").upper().strip()
company_labels: list[str] = []
label_to_ticker: dict[str, str] = {}
default_index = None
if real is not None and not real.empty:
    _picker_frame = real.copy().fillna("")
    _picker_frame["key"] = _picker_frame["key"].astype(str).str.upper().str.strip()
    _picker_frame["symbol"] = _picker_frame["symbol"].astype(str).str.upper().str.strip()
    _picker_frame["name"] = _picker_frame["name"].astype(str).str.strip()
    _picker_frame["exchange"] = _picker_frame["exchange"].astype(str).str.strip()
    for _row in _picker_frame.itertuples(index=False):
        _key = str(getattr(_row, "key", "")).strip().upper()
        _name = str(getattr(_row, "name", "")).strip()
        _symbol = str(getattr(_row, "symbol", "")).strip().upper()
        _exchange = str(getattr(_row, "exchange", "")).strip()
        if not _key or not _name:
            continue
        # Include all identifiers in the dropdown text so the built-in search
        # matches company name, NSE symbol, BSE code and Yahoo-style ticker.
        _label = f"{_name}  ·  {_symbol}  ·  {_exchange}  ·  {_key}"
        if _label in label_to_ticker:
            _label = f"{_label}  ·  {len(company_labels) + 1}"
        company_labels.append(_label)
        label_to_ticker[_label] = _key
    if prior_ticker:
        default_index = next((i for i, label in enumerate(company_labels)
                              if label_to_ticker.get(label) == prior_ticker), None)

search_col, action_col = st.columns([5, 1.25], gap="medium")
with search_col:
    selected_company = st.selectbox(
        "Search company",
        options=company_labels,
        index=default_index,
        placeholder="Start typing a company name, NSE symbol, BSE code or ticker…",
        key="welcome_company_picker_v4",
        label_visibility="collapsed",
        accept_new_options=True,
        help="Type to filter the NSE/BSE company list. The suggestions include company name, symbol, exchange and ticker.",
    )
with action_col:
    analyse = st.button("Analyze Company →", use_container_width=True, type="primary", key="welcome_analyze_v4")

st.caption(f"{len(real):,} listed companies · {source} · Searchable NSE/BSE directory")
if analyse:
    selected_text = str(selected_company or "").strip()
    selected_ticker = label_to_ticker.get(selected_text)
    if selected_ticker:
        st.session_state["ticker"] = selected_ticker
        st.switch_page("pages/2_Company_Overview.py")
    elif selected_text:
        result, matches = _resolve_company_query(selected_text, real)
        if result == "resolved" and matches:
            st.session_state["ticker"] = matches[0]
            st.switch_page("pages/2_Company_Overview.py")
        elif result == "multiple":
            by_key = real.copy()
            by_key["key"] = by_key["key"].astype(str).str.upper()
            by_key = by_key.set_index("key", drop=False)
            options = [key for key in matches if key in by_key.index]
            if options:
                st.warning("More than one company matches. Select the exact company below.")
                choice_labels = [
                    f"{by_key.loc[key, 'name']}  ·  {by_key.loc[key, 'symbol']}  ·  {by_key.loc[key, 'exchange']}  ·  {key}"
                    for key in options
                ]
                chosen = st.selectbox(
                    "Matching companies", choice_labels,
                    key="welcome_company_match_v4", label_visibility="collapsed",
                    placeholder="Choose the exact listed company…",
                )
                if chosen and st.button("Open selected company →", key="welcome_open_match_v4"):
                    st.session_state["ticker"] = options[choice_labels.index(chosen)]
                    st.switch_page("pages/2_Company_Overview.py")
            else:
                st.error("No listed company matches that search. Try its exact NSE symbol or BSE code.")
        elif result == "empty":
            st.warning("Start typing a company name, NSE symbol, BSE code or ticker.")
        else:
            st.error("No matching listed company was found. Try a company name, exact NSE symbol, BSE scrip code or ticker such as RELIANCE.NS / 500325.BO.")
    else:
        st.warning("Select a company from the suggestions or type an exact exchange ticker.")

if st.button("↻ Update NSE/BSE company list", key="welcome_refresh_listing", help="Refresh the local company directory from official exchange sources. Normal searches use the local listing cache."):
    from data.fetch_universe import build_listing
    build_listing(refresh=True)
    load_listing_cached.clear()
    st.rerun()

# The four-index snapshot and detailed market panels load automatically.
# Their independent source requests run concurrently with a strict wait budget.
market_title_col, market_refresh_col = st.columns([5, 1.2])
with market_title_col:
    render('<div class="rf-heading"><span>▥</span> Indian Market Snapshot · Latest Available Market Data</div>')
with market_refresh_col:
    if st.button("↻ Refresh market", key="welcome_refresh_market"):
        get_market_snapshot.clear()
        get_index_history.clear()
        st.rerun()
snapshot = get_market_snapshot()
if snapshot is None or snapshot.empty:
    st.info("Market snapshot is temporarily unavailable from the market-data provider. No index values are estimated; try refresh later.")
else:
    rows = {str(r["Index"]): r for _, r in snapshot.iterrows()}
    glyphs = {"NIFTY 50": "▥", "BANK NIFTY": "♜", "SENSEX": "▥", "INDIA VIX": "∿"}
    cards = []
    for index_name in ["NIFTY 50", "BANK NIFTY", "SENSEX", "INDIA VIX"]:
        row = rows.get(index_name, pd.Series({"Index": index_name, "Value": float("nan")}))
        cards.append(market_card(row, glyphs[index_name]))
    render('<div class="rf-market-grid">' + ''.join(cards) + '</div>')
st.caption("Market quotes show the latest available provider close and may be delayed. Refreshes are cached briefly to keep the landing page responsive.")

# The user asked for a fully automatic front-page market view. Do not gate
# charts/news/holdings behind a toggle; all panels load on first page visit.
show_market_dashboard = True
if show_market_dashboard:
    left,right=st.columns([1.35,.95],gap="medium")
    with left:
        render('<div class="rf-panel"><div class="rf-panel-title">▥ &nbsp;Index Performance</div></div>')
        a,b=st.columns([1,1.5])
        with a: index=st.selectbox("Index",["NIFTY 50","BANK NIFTY","SENSEX"],key="welcome_market_index",label_visibility="collapsed")
        with b: period=st.segmented_control("Period",options=["1D","1W","1M","3M","6M","1Y"],default="1M",key="welcome_market_period") or "1M"

    # Run the optional panels together and keep the page render bounded to 8s.
    _market_jobs = {
        "history": lambda: get_index_history(index, period),
        "news": lambda: get_market_news(5),
        "sentiment": get_market_sentiment,
        "sectors": get_sector_rotation,
        "events": lambda: get_nse_results_calendar(14),
    }
    _market_ticker = str(st.session_state.get("ticker") or "").upper()
    selected = _market_ticker
    _market_symbol = _market_ticker.replace(".NS", "").replace(".BO", "")
    if _market_ticker and not _market_ticker.endswith(".BO"):
        _market_jobs["holdings"] = lambda: get_nse_institutional_holdings(_market_symbol)
    _market_pool = ThreadPoolExecutor(max_workers=len(_market_jobs), thread_name_prefix="rfi-welcome-market")
    _market_futures = {name: _market_pool.submit(fn) for name, fn in _market_jobs.items()}
    _market_done, _market_pending = wait(list(_market_futures.values()), timeout=8)
    _market_data = {}
    for _name, _future in _market_futures.items():
        if _future in _market_done:
            try: _market_data[_name] = _future.result()
            except Exception: _market_data[_name] = None
        else:
            _future.cancel()
            _market_data[_name] = None
    _market_pool.shutdown(wait=False, cancel_futures=True)

    index_history = _market_data.get("history") if isinstance(_market_data.get("history"), pd.DataFrame) else pd.DataFrame()
    with left:
        index_chart(index,period,index_history)
    with right:
        render('<div class="rf-panel"><div class="rf-panel-title">▤ &nbsp;Market News & Alerts</div></div>')
        news=_market_data.get("news") if isinstance(_market_data.get("news"), pd.DataFrame) else pd.DataFrame()
        if news.empty: st.info("Current-year market headlines are temporarily unavailable. No headlines have been fabricated.")
        else:
            for _,item in news.iterrows():
                render(f'<div class="rf-news-item"><a href="{safe(item.get("url"))}" target="_blank" rel="noopener noreferrer">{safe(item.get("title"))} ↗</a><div class="rf-news-meta">{safe(item.get("publisher"))} · {safe(item.get("published"))}</div></div>')
        st.caption("Headlines are informational links, not investment recommendations.")

    render('<div class="rf-intel-title">▥ &nbsp;Market Intelligence & Institutional Activity</div>')
    intel_cols = st.columns(4, gap="small")

    # Market regime is calculated transparently from NIFTY trend and India VIX.
    sentiment = _market_data.get("sentiment") if isinstance(_market_data.get("sentiment"), dict) else {}
    with intel_cols[0]:
        regime = str(sentiment.get("regime", "Unavailable"))
        regime_class = "positive" if regime == "Risk-On" else "negative" if regime == "Risk-Off" else "neutral"
        nifty_ret = sentiment.get("nifty_1m")
        vix_val = sentiment.get("vix")
        above = sentiment.get("above_50dma")
        ret_text = f"{nifty_ret:+.2f}%" if isinstance(nifty_ret, (int, float)) else "N/A"
        vix_text = f"{vix_val:.2f}" if isinstance(vix_val, (int, float)) else "N/A"
        dma_text = "Above 50-DMA" if above is True else "Below 50-DMA" if above is False else "50-DMA N/A"
        gauge_color = "#22e58b" if regime == "Risk-On" else "#fb5267" if regime == "Risk-Off" else "#fbbf24"
        dash = 90 if regime == "Risk-Off" else 145 if regime == "Neutral" else 190
        render(f'<div class="rf-intel-card"><h4>◉ &nbsp;Market Sentiment & Risk Gauge</h4><div class="big {regime_class}">{safe(regime)}</div><svg class="rf-gauge" viewBox="0 0 220 100" role="img" aria-label="Rule-based market regime"><path d="M25 88 A85 85 0 0 1 195 88" fill="none" stroke="#263e50" stroke-width="17" stroke-linecap="round"/><path d="M25 88 A85 85 0 0 1 195 88" fill="none" stroke="{gauge_color}" stroke-width="17" stroke-linecap="round" stroke-dasharray="{dash} 270"/><text x="110" y="76" text-anchor="middle" fill="#eaf8ff" font-size="12" font-weight="700">{safe(regime)}</text></svg><table><tr><td>NIFTY 1M</td><td>{safe(ret_text)}</td></tr><tr><td>India VIX</td><td>{safe(vix_text)}</td></tr><tr><td>NIFTY trend</td><td>{safe(dma_text)}</td></tr></table><div class="rf-source">Rule-based, not an official exchange rating · {safe(sentiment.get("as_of") or "Date unavailable")}</div></div>')

    # Quarterly company-wise institutional ownership from NSE filings.
    with intel_cols[1]:
        if "selected" in locals() and selected:
            selected_key = str(selected)
            symbol = selected_key.replace(".NS", "").replace(".BO", "")
            if selected_key.endswith(".BO"):
                body = '<div class="muted">This is a BSE-only listing. Use the BSE filing archive to verify its quarterly shareholding pattern; NSE symbol-based retrieval is not applicable.</div>'
                source_note = f'<div class="rf-source"><a href="https://www.bseindia.com/corporates/ShareholdingPattern.html?scripcode={safe(symbol)}" target="_blank" rel="noopener">BSE Shareholding Pattern ↗</a></div>'
                holdings = pd.DataFrame()
            else:
                holdings = _market_data.get("holdings") if isinstance(_market_data.get("holdings"), pd.DataFrame) else pd.DataFrame()
            if not selected_key.endswith(".BO") and holdings.empty:
                body = f'<div class="muted">NSE filing metadata or XBRL institutional-category facts could not be retrieved for {safe(symbol)}. This is not evidence of zero institutional ownership.</div>'
                source_note = '<div class="rf-source"><a href="https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern" target="_blank" rel="noopener">Open official NSE Shareholding Patterns ↗</a></div>'
            elif not selected_key.endswith(".BO"):
                body = '<table><tr><th>Category</th><th>Latest holding</th><th>Previous</th><th>QoQ Δ</th></tr>'
                for _, h in holdings.iterrows():
                    pct = f'{float(h["Current %"]):.2f}%' if pd.notna(h["Current %"]) else 'N/A'
                    prev = f'{float(h["Previous %"]):.2f}%' if pd.notna(h["Previous %"]) else 'N/A'
                    delta = f'{float(h["Change (pp)"]):+.2f} pp' if pd.notna(h["Change (pp)"]) else 'N/A'
                    body += f'<tr><td>{safe(h["Category"])}</td><td>{safe(pct)}</td><td>{safe(prev)}</td><td>{safe(delta)}</td></tr>'
                body += '</table>'
                filing_url = str(holdings.iloc[0].get("Source", "")) if not holdings.empty else ""
                source_link = f'<a href="{safe(filing_url)}" target="_blank" rel="noopener">Open latest XBRL filing ↗</a>' if filing_url.startswith("https://") else '<a href="https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern" target="_blank" rel="noopener">NSE Shareholding Patterns ↗</a>'
                filing_date = str(holdings.iloc[0].get("Filing date", "")) if not holdings.empty else ""
                source_note = f'<div class="rf-source">NSE quarterly XBRL filing · {safe(filing_date or "Filing date unavailable")} · {source_link}. QoQ change is calculated only when the prior filing is available.</div>'
        else:
            body = '<div class="muted">Select a listed company above to view reported FII/FPI and DII ownership from its latest shareholding filing.</div>'
            source_note = '<div class="rf-source"><a href="https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern" target="_blank" rel="noopener">NSE Shareholding Patterns ↗</a></div>'
        render('<div class="rf-intel-card"><h4>♜ &nbsp;Institutional Holdings Tracker</h4>' + body + source_note + '</div>')

    # Sector-index returns from Yahoo Finance; source and delay are disclosed.
    with intel_cols[2]:
        sectors = _market_data.get("sectors") if isinstance(_market_data.get("sectors"), pd.DataFrame) else pd.DataFrame()
        if sectors.empty:
            body = '<div class="muted">Sector-index history is temporarily unavailable. No returns have been estimated.</div>'
        else:
            view = sectors.sort_values("1M", ascending=False).head(6)
            body = '<table><tr><th>Sector</th><th>1M</th><th>3M</th><th>6M</th></tr>'
            for _, row in view.iterrows():
                cells = []
                for col in ("1M", "3M", "6M"):
                    value = row.get(col)
                    cells.append(f'{float(value):+.2f}%' if pd.notna(value) else 'N/A')
                body += f'<tr><td>{safe(row["Sector"])}</td><td>{safe(cells[0])}</td><td>{safe(cells[1])}</td><td>{safe(cells[2])}</td></tr>'
            body += '</table>'
        render('<div class="rf-intel-card"><h4>▱ &nbsp;Sector Rotation Monitor</h4>' + body + '<div class="rf-source">Yahoo Finance sector-index feed · historical returns; provider may be delayed.</div></div>')

    # Confirmed future financial-results events from NSE's public event calendar.
    with intel_cols[3]:
        events = _market_data.get("events") if isinstance(_market_data.get("events"), pd.DataFrame) else pd.DataFrame()
        if events.empty:
            body = '<div class="muted">No upcoming financial-results events were returned for the next 14 days, or the NSE source is temporarily unavailable.</div>'
        else:
            body = ''
            for _, ev in events.head(6).iterrows():
                body += f'<div class="rf-event-row"><span><b>{safe(ev.get("Symbol"))}</b><br><span class="muted">{safe(ev.get("Event"))}</span></span><b>{safe(ev.get("Date"))}</b></div>'
        render('<div class="rf-intel-card"><h4>▦ &nbsp;Corporate Results Calendar</h4>' + body + '<div class="rf-source"><a href="https://www.nseindia.com/companies-listing/corporate-filings-event-calendar" target="_blank" rel="noopener">NSE Event Calendar ↗</a> · Confirmed exchange calendar dates</div></div>')

    render('<div class="rf-workflow"><div class="rf-step"><b>1</b><div><strong>Search Company</strong><small>NSE / BSE</small></div></div><div class="rf-step"><b>2</b><div><strong>Analyse Across Modules</strong><small>Financials, Governance, ESG, Credit</small></div></div><div class="rf-step"><b>3</b><div><strong>Review Red Flags & Insights</strong><small>Key risks and developments</small></div></div><div class="rf-step"><b>4</b><div><strong>Get Investment Summary</strong><small>Evidence-based verdict</small></div></div></div>')
    st.caption("Sources: Yahoo Finance market-data feed for index quotes, history and sector-index returns; NSE corporate filings for quarterly shareholding and upcoming results events; Google News RSS for current-calendar-year market headlines. Each panel shows unavailable data rather than substituting estimates.")

