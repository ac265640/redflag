"""Raw Yahoo data, loaded by selected category so unrelated endpoints stay lazy."""
import pandas as pd
import streamlit as st

from data.fetch_yahoo import arrow_safe, fetch_yahoo_group, refresh, YAHOO_GROUP_KEYS
from visualization.components import hero, section, setup_page, notice


ticker = setup_page("Yahoo Finance Data")

with st.sidebar:
    if st.button("Refresh selected Yahoo data", use_container_width=True, key=f"refresh_yahoo_{ticker}"):
        refresh(ticker)
        st.rerun()

hero(f"{ticker}: Yahoo Finance data", "Source-specific market, financial statement, ownership and analyst datasets. Only the selected category is requested.", demo=False)

categories = list(YAHOO_GROUP_KEYS.keys())
selected = st.selectbox("Data category", categories, index=0, key=f"yahoo_category_{ticker}")
with st.spinner(f"Loading Yahoo Finance · {selected}…"):
    data = fetch_yahoo_group(ticker, selected)

info = data.get("info", {}) if isinstance(data.get("info"), dict) else {}
name = info.get("longName") or info.get("shortName") or ticker
if selected == "Profile":
    hero(f"{name}: company profile", "Profile data returned by Yahoo Finance fast metadata. Missing profile fields remain N/A.", demo=False)
    metrics = [
        ("Price", info.get("last_price") or info.get("regularMarketPrice")),
        ("Market cap", info.get("market_cap") or info.get("marketCap")),
        ("Currency", info.get("currency") or "INR"),
        ("Exchange", info.get("exchange") or "N/A"),
    ]
    cols = st.columns(4)
    for col, (label, value) in zip(cols, metrics):
        if label == "Market cap" and isinstance(value, (int, float)):
            value = f"₹{value/1e7:,.0f} Cr"
        col.metric(label, value if value not in (None, "") else "N/A")

loaded = [k for k, v in data.items() if isinstance(v, pd.DataFrame) and not v.empty]
st.caption(f"Yahoo ticker: {ticker} · Selected category: {selected} · Datasets returned: {len(loaded)}/{len(YAHOO_GROUP_KEYS[selected])}")

if selected == "Profile":
    if info:
        profile_df = pd.DataFrame(list(info.items()), columns=["Field", "Value"])
        profile_df["Field"] = profile_df["Field"].astype(str)
        profile_df["Value"] = profile_df["Value"].map(lambda value: "" if value is None else str(value))
        st.dataframe(profile_df, use_container_width=True, hide_index=True, height=650)
    else:
        notice("Yahoo Finance did not return fast profile metadata for this security. Company identity remains available from the local NSE/BSE directory.")
else:
    TITLES = {
        "Price": [("Historical price (1 year)", "history")],
        "Financials": [("Annual income statement", "financials_annual"), ("Quarterly income statement", "financials_quarterly")],
        "Balance Sheet": [("Annual balance sheet", "balance_annual"), ("Quarterly balance sheet", "balance_quarterly")],
        "Cash Flow": [("Annual cash flow", "cashflow_annual"), ("Quarterly cash flow", "cashflow_quarterly")],
        "Ownership": [("Major holders", "major_holders"), ("Institutional holders", "institutional_holders"), ("Mutual fund holders", "mutualfund_holders"), ("Insider transactions", "insider_transactions"), ("Insider purchases", "insider_purchases")],
        "Corporate Actions": [("Corporate actions", "actions"), ("Dividends", "dividends"), ("Stock splits", "splits")],
        "Analysts": [("Analyst recommendations", "recommendations"), ("Recommendation summary", "recommendations_summary"), ("Upgrades / downgrades", "upgrades_downgrades"), ("Analyst price targets", "analyst_targets"), ("Earnings dates", "earnings_dates"), ("Earnings history", "earnings_history"), ("Earnings estimates", "earnings_estimate"), ("Revenue estimates", "revenue_estimate"), ("Growth estimates", "growth_estimates"), ("EPS trend", "eps_trend"), ("EPS revisions", "eps_revisions")],
        "ESG": [("Yahoo sustainability / ESG dataset", "sustainability")],
        "Other": [("Valuation measures", "valuation"), ("Fast quote data", "fast_info"), ("Shares outstanding history", "shares_full"), ("Upcoming calendar", "calendar"), ("Insider roster", "insider_roster"), ("Yahoo news", "news"), ("SEC filings available through Yahoo", "sec_filings")],
    }
    for title, key in TITLES.get(selected, []):
        section(title, "Yahoo Finance response", "chart")
        frame = data.get(key, pd.DataFrame())
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            st.dataframe(arrow_safe(frame), use_container_width=True, hide_index=False, height=min(520, max(180, 42 + len(frame) * 26)))
        else:
            notice(f"Yahoo Finance did not return {title.lower()} for {ticker}. This dataset is not available from the provider in this run.")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
