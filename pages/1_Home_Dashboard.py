"""Home Dashboard: selected-company risk at a glance."""
import streamlit as st

from core.constants import fmt
from visualization.components import badge, card_grid, get_analysis, hero, metric_card, render, section, setup_page


ticker = setup_page("Home Dashboard")
a = get_analysis(ticker)

hero("Risk at a glance", f"Selected company: {a.name}. This dashboard uses live/source-backed data only; unavailable fields remain N/A.", demo=False)

card_grid([
    metric_card("Sector-screen index", f"{a.financial.score:.0f}", "Severity-weighted · higher means more triggered risk signals", "search"),
    metric_card("Highest flag severity", a.grade, "Severity of the most serious triggered check", "shield-alert"),
    metric_card("Revenue", f"₹{fmt(a.financials.iloc[-1].revenue, 0)} Cr", str(a.financials.index[-1]), "chart"),
    metric_card("Operating cash flow", f"₹{fmt(a.financials.iloc[-1].cfo, 0)} Cr", "Latest reported period", "activity"),
], cols=4)

section("Current analyst read", "A concise first view before opening the detailed modules.", "info")
for line in a.explanations:
    st.markdown(f"- {line}")

section("Risk areas", "The dashboard deliberately separates verified source layers instead of manufacturing missing scores.", "layers")
rows = [
    ("Financial / forensic", f"{a.financial.score:.0f}/100 screening index", "Sector-aware live statements"),
    ("Governance", "Open Governance Deep Dive", "NSE filing layer"),
    ("ESG", "Open ESG Scorecard", "NSE BRSR + supplemental sources"),
    ("Credit", "Open Credit Rating", "Official rating agencies + NSE"),
    ("Annual report", "Open Annual Report Intelligence", "NSE-submitted report"),
    ("Management", "Open Management Intelligence", "Annual-report evidence"),
    ("Regulatory", "Open Corporate & Regulatory Intelligence", "NSE announcements"),
]
for title, value, source in rows:
    render(f'<div class="rf-row"><div><b>{title}</b><br><span class="m">{source}</span></div><div><b>{value}</b></div></div>')

section("Go to final verdict", "The final page combines the available outputs from all modules into one investment-research conclusion.", "check-circle")
st.page_link("pages/13_Final_Investment_Summary.py", label="Open Final Investment Verdict", icon=":material/task_alt:")

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
