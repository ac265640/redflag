"""Portfolio Risk: portfolio view without cross-sector score aggregation."""
import pandas as pd
import streamlit as st

from core.constants import Severity
from visualization.components import hero, load_listing_cached, notice, section, setup_page, try_analysis

setup_page("Portfolio Risk")
hero(
    "Portfolio risk",
    "Build a holdings view and inspect each company's sector-aware financial screening. Screening indices are aggregated only within the same business-model rule set.",
    demo=False,
)
listing, _ = load_listing_cached()
labels = dict(zip(listing["key"], listing["label"]))

section("Holdings", "Search and select NSE/BSE-listed companies, then assign portfolio weights.", "briefcase")
chosen = st.multiselect("Companies", list(listing["key"]), default=[], max_selections=15,
                        format_func=lambda k: labels.get(k, k))
if not chosen:
    st.info("Add at least one listed company to begin.")
    st.stop()

start = [round(100 / len(chosen), 1)] * len(chosen)
edited = st.data_editor(
    pd.DataFrame({"Ticker": chosen, "Weight (%)": start}), hide_index=True, use_container_width=True,
    disabled=["Ticker"], key="portfolio_weights_" + "|".join(chosen),
    column_config={"Weight (%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, format="%.1f")},
)
if edited["Weight (%)"].sum() <= 0:
    st.info("Give at least one holding a weight above zero.")
    st.stop()

weights = edited.set_index("Ticker")["Weight (%)"].astype(float)
weights = weights / weights.sum() * 100
records, failed = [], []
with st.spinner("Analysing holdings…"):
    for ticker in chosen:
        analysis = try_analysis(ticker)
        if analysis is None:
            failed.append(ticker)
            continue
        sector_result = getattr(analysis, "sector_forensic", None)
        profile = sector_result.profile if sector_result is not None else None
        flags = analysis.financial.flags
        high_critical = sum(1 for flag in flags if flag.severity in {Severity.HIGH, Severity.CRITICAL})
        highest = next((sev.value for sev in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
                        if any(flag.severity == sev for flag in flags)), "None")
        records.append({
            "Ticker": ticker,
            "Company": analysis.name,
            "Business model": profile.business_model if profile else "Demo / composite model",
            "Sector profile key": profile.key if profile else None,
            "Weight (%)": float(weights.get(ticker, 0.0)),
            "Sector-screen index": float(analysis.financial.score) if analysis.data_mode == "live" else None,
            "Highest severity": highest,
            "Triggered findings": len(flags),
            "High / critical findings": high_critical,
            "Tests executed": sector_result.applicable_count if sector_result else None,
            "Test coverage (%)": sector_result.coverage_pct if sector_result else None,
        })

if failed:
    notice("No source-backed analysis was available for: " + ", ".join(failed) + ". These holdings are excluded from the view.")
if not records:
    st.stop()

holdings = pd.DataFrame(records)
held_weight = float(holdings["Weight (%)"].sum())
models = holdings["Business model"].nunique()
high_weight = float(holdings.loc[holdings["Highest severity"].isin(["High", "Critical"]), "Weight (%)"].sum())
col1, col2, col3 = st.columns(3)
col1.metric("Holdings analysed", str(len(holdings)), help="Companies with a completed analysis object.")
col2.metric("Business-model profiles", str(models), help="Distinct sector-specific rule sets represented in the portfolio.")
col3.metric("Weight in high-priority names", f"{high_weight:.1f}%", help="Portfolio weight in companies with at least one high or critical financial finding.")

section("Holding-level forensic view", "Each screening index is interpreted within its own business-model rule set. Do not rank indices across different sectors.", "grid")
show_cols = ["Ticker", "Company", "Business model", "Weight (%)", "Sector-screen index", "Highest severity", "Triggered findings", "Test coverage (%)"]
st.dataframe(holdings[show_cols].round({"Weight (%)": 1, "Sector-screen index": 1, "Test coverage (%)": 1}),
             use_container_width=True, hide_index=True)

section("Within-business-model summary", "Weighted index is shown only among holdings using the identical sector-specific test set.", "layers")
group_rows = []
for model, grp in holdings.groupby("Business model", dropna=False):
    valid = grp.dropna(subset=["Sector-screen index"])
    weighted_index = None
    if not valid.empty and valid["Weight (%)"].sum() > 0:
        weighted_index = float((valid["Sector-screen index"] * valid["Weight (%)"]).sum() / valid["Weight (%)"].sum())
    group_rows.append({
        "Business model": model,
        "Holdings": len(grp),
        "Portfolio weight (%)": grp["Weight (%)"].sum(),
        "Weighted sector-screen index": weighted_index,
        "Rule-set comparability": "Same profile" if grp["Sector profile key"].nunique(dropna=True) <= 1 else "Review required",
    })
st.dataframe(pd.DataFrame(group_rows).round({"Portfolio weight (%)": 1, "Weighted sector-screen index": 1}),
             use_container_width=True, hide_index=True)

st.info(
    "A sector-screen index is a severity-weighted summary of executed financial-statement tests, not a fraud probability or a complete portfolio risk score. "
    "Different business models use different tests and thresholds; the app therefore does not calculate one blended cross-sector forensic score."
)

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
