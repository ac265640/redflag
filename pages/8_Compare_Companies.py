"""Compare Companies: any 2-4 listed companies side by side."""
import pandas as pd
import streamlit as st

from core.scoring_engine import summary_row
from intelligence.peer_benchmark import peer_percentiles
from visualization import charts
from visualization.components import hero, load_listing_cached, load_universe_summary, notice, section, setup_page, try_analysis

ticker = setup_page("Compare Companies")
hero("Compare companies", "Up to four companies side by side. The radar shows quality on every axis (risks inverted), so bigger is better.")
listing, _ = load_listing_cached()
labels = dict(zip(listing["key"], listing["label"]))

default = [ticker] if ticker in labels else []
sel = st.multiselect("Search and pick companies", list(listing["key"]), default=default, max_selections=4, format_func=lambda k: labels[k])
if len(sel) < 2:
    st.info("Pick at least two companies.")
    st.stop()

with st.spinner("Analysing…"):
    an = {t: try_analysis(t) for t in sel}
missing = [t for t, a in an.items() if a is None]
if missing:
    notice("No financial statements available for: " + ", ".join(missing) + ". They are excluded.")
an = {t: a for t, a in an.items() if a is not None}
if len(an) < 2:
    st.stop()

axes = {
    "Financial quality": lambda a: 100 - a.financial.score,
    "Hidden-forensic quality": lambda a: None if a.hidden_score is None else 100 - a.hidden_score,
    "Governance": lambda a: a.governance_score,
    "ESG": lambda a: a.esg_score,
    "Credit quality": lambda a: None if a.credit_risk is None else 100 - a.credit_risk,
}
usable = [k for k, f in axes.items() if all(f(a) is not None for a in an.values())]
sector_profiles = [getattr(getattr(a, "sector_forensic", None), "profile", None) for a in an.values()]
sector_keys = {p.key for p in sector_profiles if p is not None}
all_sector_aware = all(p is not None for p in sector_profiles)
if (not all_sector_aware or len(sector_keys) != 1) and "Financial quality" in usable:
    usable.remove("Financial quality")
    notice("The selected companies do not all share the same validated sector-specific rule set. Their financial screening indices are excluded from the shared radar to avoid misleading comparison.")
if any(a.data_mode == "live" for a in an.values()):
    notice(f"Live companies only show the source-backed axes available for every selected company: {', '.join(usable) if usable else 'no shared axes'}.")

c1, c2 = st.columns([1.2, 1])
with c1:
    section("Quality profile", "", "chart")
    if len(usable) >= 3:
        st.plotly_chart(charts.radar(usable, {t: [axes[k](a) for k in usable] for t, a in an.items()}, height=420), use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("Fewer than three shared axes, so a radar would be misleading. See the score table.")
with c2:
    section("Scores", "", "layers")
    tbl = pd.DataFrame([summary_row(a) for a in an.values()]).set_index("Ticker")
    if all_sector_aware and len(sector_keys) == 1:
        st.caption("Financial screening is compared only because all selected companies use the same business-model rule set. It remains a screening index, not a fraud probability.")
        visible = ["Company", "Business model", "Grade", "Sector-screen index", "Governance", "ESG", "Credit risk", "Flags"]
    else:
        st.caption("Sector-specific financial indices are excluded from a like-for-like comparison because the selected companies do not all share the same validated rule set.")
        visible = ["Company", "Business model", "Grade", "Governance", "ESG", "Credit risk", "Flags"]
    st.dataframe(tbl[[c for c in visible if c in tbl.columns]].T.astype(str), use_container_width=True)

section("Peer percentile", "Peer benchmarking requires source-backed live analysis for the selected company and its comparable listed peers.", "users")
if ticker in set(load_universe_summary().Ticker):
    st.dataframe(peer_percentiles(load_universe_summary(), ticker), use_container_width=True, hide_index=True)
else:
    st.info("N/A — a full source-backed peer set is not yet available for this company. No synthetic peer scores are used.")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
